#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频批量压缩工具 (Video Batch Compressor)
========================================
基于 FFmpeg + H.265/HEVC 的视频批量压缩 GUI 工具。
适用于 iwara 等网站下载的 MMD 视频文件的存储空间优化。

支持:
  - CPU 编码: libx265 (H.265/HEVC)
  - GPU 编码: NVIDIA NVENC (hevc_nvenc / av1_nvenc)，需 NVIDIA 显卡

依赖:
  - Python 3.8+
  - FFmpeg (需安装并添加到系统 PATH，GPU 编码需对应版本)

使用方法:
  1. 确保已安装 FFmpeg: https://ffmpeg.org/download.html
  2. 运行: python video_compressor.py
"""

from __future__ import annotations

import os
import sys
import json
import time
import shutil
import queue
import threading
import subprocess
import ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from collections import deque
from concurrent.futures import ThreadPoolExecutor


# ============================================================
# 常量与配置
# ============================================================

APP_TITLE = "视频批量压缩工具 by akayukimio"
APP_VERSION = "1.2.0"
SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m4v"}
DEFAULT_CRF = 28          # H.265 默认 CRF 值（MMD 动画类视频推荐 26-30）
DEFAULT_PRESET = "medium"  # FFmpeg 编码预设
DEFAULT_OUTPUT_SUBDIR = "compressed"
CONFIG_FILE = "compressor_config.json"
HISTORY_FILE = ".processing_history.json"
APP_DIR = Path(__file__).parent  # 应用程序所在目录

# ============================================================
# 编码器配置
# ============================================================

# 每个编码器的配置:
#   label          - 界面显示名称
#   codec          - FFmpeg 编码器名称
#   quality_param  - 质量参数 (CPU 用 crf, GPU 用 cq)
#   default_q      - 默认质量值
#   default_preset - 默认编码速度预设
#   presets        - 可用的编码速度预设
ENCODERS = {
    "libx265": {
        "label": "CPU 编码 H.265 (libx265)",
        "codec": "libx265",
        "quality_param": "crf",
        "default_q": 28,
        "default_preset": "medium",
        "presets": [
            "ultrafast", "superfast", "veryfast", "faster",
            "fast", "medium", "slow", "slower", "veryslow"
        ],
    },
    "hevc_nvenc": {
        "label": "GPU 编码 H.265 (NVIDIA NVENC)",
        "codec": "hevc_nvenc",
        "quality_param": "cq",
        "default_q": 24,
        "default_preset": "p5",
        "presets": ["p1", "p2", "p3", "p4", "p5", "p6", "p7"],
    },
    "av1_nvenc": {
        "label": "GPU 编码 AV1 (NVIDIA NVENC)",
        "codec": "av1_nvenc",
        "quality_param": "cq",
        "default_q": 26,
        "default_preset": "p5",
        "presets": ["p1", "p2", "p3", "p4", "p5", "p6", "p7"],
    },
}


def detect_available_encoders() -> list:
    """检测 FFmpeg 中实际可用的编码器，返回编码器 key 列表"""
    available = []
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15
        )
        encoders_text = result.stdout
        for enc_key in ENCODERS:
            if ENCODERS[enc_key]["codec"] in encoders_text:
                available.append(enc_key)
    except Exception:
        pass
    if not available:
        available = ["libx265"]
    return available


def load_processing_history() -> set:
    """加载处理历史记录（已处理过的文件路径集合）"""
    path = APP_DIR / HISTORY_FILE
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("processed", []))
    except Exception:
        pass
    return set()


def save_processing_history(history: set):
    """保存处理历史记录"""
    path = APP_DIR / HISTORY_FILE
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"processed": list(history)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# 分辨率缩放选项
SCALE_OPTIONS = {
    "原始分辨率": None,
    "4K (3840x2160)": "3840:-2",
    "1440p (2560x1440)": "2560:-2",
    "1080p (1920x1080)": "1920:-2",
    "720p (1280x720)": "1280:-2",
    "480p (854x480)": "854:-2",
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class VideoFile:
    """表示一个待处理的视频文件"""
    path: Path
    size: int = 0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = ""
    status: str = "pending"  # pending, processing, done, skipped, error
    output_path: Optional[Path] = None
    output_size: int = 0
    error_msg: str = ""
    error_detail: str = ""   # FFmpeg 错误输出片段（供错误日志排查用）
    encode_seconds: float = 0.0  # 本次编码耗时（秒）
    progress: float = 0.0
    checked: bool = False       # 是否勾选参与本次处理


@dataclass
class CompressionSettings:
    """压缩设置"""
    encoder: str = "libx265"  # 编码器 key: libx265 / hevc_nvenc / av1_nvenc
    crf: int = DEFAULT_CRF
    preset: str = DEFAULT_PRESET
    output_subdir: str = DEFAULT_OUTPUT_SUBDIR
    scale: Optional[str] = None
    audio_bitrate: str = "128k"
    overwrite: bool = False
    max_resolution: str = "原始分辨率"
    custom_output_dir: str = ""  # 自定义输出根目录（为空时使用源目录下的子文件夹）
    force_compress: bool = False  # 强制压缩：即使源文件已是 HEVC/AV1 等高效编码也不跳过


# ============================================================
# FFmpeg 交互层
# ============================================================

class FFmpegHelper:
    """封装 FFmpeg 调用"""

    @staticmethod
    def check_ffmpeg() -> bool:
        """检查 FFmpeg 是否可用"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def probe_video(filepath: Path) -> dict:
        """使用 ffprobe 获取视频信息"""
        try:
            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(filepath)
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception:
            pass
        return {}

    @staticmethod
    def get_duration_from_probe(filepath: Path) -> float:
        """获取视频时长（秒）"""
        info = FFmpegHelper.probe_video(filepath)
        if info and "format" in info:
            try:
                return float(info["format"].get("duration", 0))
            except (ValueError, TypeError):
                pass
        return 0.0

    @staticmethod
    def build_compress_cmd(
        input_path: Path,
        output_path: Path,
        settings: CompressionSettings,
        overwrite: bool = False,
        video_width: int = 0,
        video_height: int = 0
    ) -> list:
        """构建 FFmpeg 压缩命令（自动适配 CPU/GPU 编码器）
        
        Args:
            video_width: 视频原始宽度，用于智能分辨率缩放
            video_height: 视频原始高度，用于智能分辨率缩放
        """
        cmd = ["ffmpeg"]

        if overwrite:
            cmd.extend(["-y"])
        else:
            cmd.extend(["-n"])  # 不覆盖已存在的文件

        cmd.extend(["-i", str(input_path)])

        # 编码器配置
        enc_cfg = ENCODERS.get(settings.encoder, ENCODERS["libx265"])
        cmd.extend(["-c:v", enc_cfg["codec"]])

        if enc_cfg["codec"] == "libx265":
            # ---- CPU 软件编码: 恒定质量 (CRF) ----
            cmd.extend(["-crf", str(settings.crf)])
            cmd.extend(["-preset", settings.preset])
            cmd.extend(["-pix_fmt", "yuv420p"])
        else:
            # ---- NVIDIA NVENC 硬件编码: 恒定质量 (CQ) VBR 模式 ----
            cmd.extend(["-preset", settings.preset])       # p1(最快) ~ p7(最好)
            cmd.extend(["-rc", "vbr"])                     # VBR 码率控制
            cmd.extend(["-cq", str(settings.crf)])         # 质量值 (0-51)
            cmd.extend(["-b:v", "0"])                      # 不限码率，纯质量模式
            cmd.extend(["-pix_fmt", "yuv420p"])

        # 分辨率缩放（智能处理横版/竖版视频）
        scale_label = settings.max_resolution
        if scale_label != "原始分辨率" and scale_label in SCALE_OPTIONS:
            scale_val = SCALE_OPTIONS[scale_label]
            if scale_val and video_width > 0 and video_height > 0:
                target_width = FFmpegHelper._parse_scale_target(scale_val)
                if target_width > 0:
                    if video_width >= video_height:
                        # 横版视频：限制宽度不超过目标值，避免放大小分辨率视频
                        cmd.extend(["-vf", f"scale='min(iw\\,{target_width})':'-2'"])
                    # 竖版视频：跳过缩放，保持原始分辨率

        # 音频编码
        cmd.extend(["-c:a", "aac"])
        cmd.extend(["-b:a", settings.audio_bitrate])

        # 输出
        cmd.extend(["-movflags", "+faststart"])  # 优化 MP4 网络播放
        cmd.append(str(output_path))

        return cmd

    @staticmethod
    def _parse_scale_target(scale_val: str) -> int:
        """从缩放选项中解析目标宽度值"""
        try:
            return int(scale_val.split(":")[0])
        except (ValueError, IndexError):
            return 0


# ============================================================
# 压缩工作线程
# ============================================================

class CompressionWorker:
    """后台压缩处理线程"""

    def __init__(self, message_queue: queue.Queue):
        self.msg_queue = message_queue
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始不暂停
        self._thread: Optional[threading.Thread] = None
        self.settings = CompressionSettings()
        self.files: list[VideoFile] = []
        self.source_dir: Optional[Path] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, files: list[VideoFile], settings: CompressionSettings, source_dir: Optional[Path] = None):
        """开始处理"""
        self.files = files
        self.settings = settings
        self.source_dir = source_dir
        self._stop_event.clear()
        self._pause_event.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """停止处理"""
        self._stop_event.set()
        self._pause_event.set()  # 确保不在暂停状态阻塞

    def pause(self):
        """暂停处理"""
        self._pause_event.clear()
        self._send("log", "[暂停] 处理已暂停")

    def resume(self):
        """恢复处理"""
        self._pause_event.set()
        self._send("log", "[恢复] 处理已继续")

    def _send(self, msg_type: str, data=None):
        """发送消息到 GUI"""
        self.msg_queue.put((msg_type, data))

    def _run(self):
        """主处理循环"""
        total = len(self.files)
        done_count = 0
        skipped_count = 0
        error_count = 0
        total_original_size = 0
        total_compressed_size = 0
        start_time = time.time()
        # 速度/ETA 追踪
        total_bytes_all = sum(vf.size for vf in self.files)
        completed_bytes = 0

        # 开启日志会话
        logger = LogManager()
        enc_cfg = ENCODERS.get(self.settings.encoder, ENCODERS["libx265"])
        # 加载处理历史
        history = load_processing_history()
        header_lines = [
            f"开始时间   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"文件总数   : {total}",
            f"编码器     : {enc_cfg['label']}",
            f"质量值     : {enc_cfg['quality_param'].upper()} {self.settings.crf}",
            f"编码预设   : {self.settings.preset}",
            f"最大分辨率 : {self.settings.max_resolution}",
            f"音频码率   : {self.settings.audio_bitrate}",
            f"输出位置   : {self.settings.custom_output_dir + '（镜像源文件夹结构）' if self.settings.custom_output_dir else f'各源文件目录下的 {self.settings.output_subdir} 子文件夹'}",
        ]
        result_log_path, error_log_path, delete_log_path = logger.start_session(
            f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}", header_lines
        )
        self._send("log_session_paths", (result_log_path, error_log_path, delete_log_path))

        self._send("log", f"[开始] 共 {total} 个文件待处理")
        self._send("overall_progress", (0, total))

        for idx, vf in enumerate(self.files):
            # 检查停止信号
            if self._stop_event.is_set():
                self._send("log", "[中止] 用户中止了处理")
                break

            # 检查暂停信号
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            # 更新当前文件
            self._send("current_file", (idx + 1, total, vf.path.name))

            # Worker 层安全检查：如果文件已在处理历史中，直接跳过
            if str(vf.path) in history:
                skipped_count += 1
                vf.status = "skipped"
                self._send("log", f"[跳过] {vf.path.name}  (已在处理历史中)")
                logger.write_result(
                    f"--- 文件 {idx + 1}/{total}  [跳过] ---\n"
                    f"  文件名    : {vf.path.name}\n"
                    f"  原因      : 已在处理历史记录中，无需重复处理\n\n"
                )
                self._send("file_status", (idx, vf.status))
                self._send("overall_progress", (idx + 1, total))
                completed_bytes += vf.size
                continue

            try:
                result = self._process_file(vf)
                if result == "done":
                    done_count += 1
                    total_original_size += vf.size
                    total_compressed_size += vf.output_size
                    ratio = (1 - vf.output_size / vf.size) * 100 if vf.size > 0 else 0
                    self._send("log",
                        f"[完成] {vf.path.name}  "
                        f"{self._fmt_size(vf.size)} → {self._fmt_size(vf.output_size)}  "
                        f"({ratio:.1f}% 压缩率)")
                    # 结果日志: 单个文件的成果
                    logger.write_result(
                        f"--- 文件 {idx + 1}/{total}  [完成] ---\n"
                        f"  文件名    : {vf.path.name}\n"
                        f"  原始大小  : {self._fmt_size(vf.size)}  ({vf.size:,} 字节)\n"
                        f"  压缩后    : {self._fmt_size(vf.output_size)}  ({vf.output_size:,} 字节)\n"
                        f"  节省空间  : {self._fmt_size(vf.size - vf.output_size)}  "
                        f"(压缩率 {ratio:.1f}%)\n"
                        f"  编码耗时  : {self._fmt_time(vf.encode_seconds)}\n\n"
                    )
                    # 记录到处理历史
                    history.add(str(vf.path))
                    save_processing_history(history)
                elif result == "skipped":
                    skipped_count += 1
                    if vf.error_msg:
                        # 压缩后反而更大，被保护机制拦截
                        self._send("log", f"[跳过] {vf.path.name}  {vf.error_msg}")
                        logger.write_result(
                            f"--- 文件 {idx + 1}/{total}  [跳过] ---\n"
                            f"  文件名    : {vf.path.name}\n"
                            f"  原因      : {vf.error_msg}\n\n"
                        )
                        # 压缩后更大被跳过，仍记录到历史，避免下次重复处理
                        history.add(str(vf.path))
                        save_processing_history(history)
                    else:
                        self._send("log", f"[跳过] {vf.path.name}  (已存在压缩版本)")
                        logger.write_result(
                            f"--- 文件 {idx + 1}/{total}  [跳过] ---\n"
                            f"  文件名    : {vf.path.name}\n"
                            f"  原因      : 输出文件已存在，未重复压缩\n\n"
                        )
                elif result == "error":
                    error_count += 1
                    self._send("log", f"[错误] {vf.path.name}  {vf.error_msg}")
                    self._log_error(logger, vf, idx, total)
            except Exception as e:
                error_count += 1
                vf.status = "error"
                vf.error_msg = str(e)
                self._send("log", f"[错误] {vf.path.name}  {e}")
                self._log_error(logger, vf, idx, total)

            self._send("file_status", (idx, vf.status))
            self._send("overall_progress", (idx + 1, total))

            # 更新速度/ETA
            if result in ("done", "skipped"):
                completed_bytes += vf.size
            elapsed = time.time() - start_time
            if elapsed > 3 and completed_bytes > 0:
                speed_bps = completed_bytes / elapsed
                speed_mbs = speed_bps / (1024 * 1024)
                remaining_bytes = total_bytes_all - completed_bytes
                eta_sec = remaining_bytes / speed_bps if speed_bps > 0 else 0
                self._send("speed_update", (speed_mbs, eta_sec, elapsed))

        elapsed = time.time() - start_time
        self._send("log", "")
        self._send("log", "=" * 50)
        self._send("log", f"[汇总] 处理完成！耗时 {self._fmt_time(elapsed)}")
        self._send("log", f"  成功: {done_count}  跳过: {skipped_count}  失败: {error_count}")
        summary_lines = [
            f"处理耗时   : {self._fmt_time(elapsed)}",
            f"成功       : {done_count} 个",
            f"跳过       : {skipped_count} 个",
            f"失败       : {error_count} 个",
        ]
        if total_compressed_size > 0:
            saved = total_original_size - total_compressed_size
            ratio = (1 - total_compressed_size / total_original_size) * 100 if total_original_size > 0 else 0
            self._send("log",
                f"  原始大小: {self._fmt_size(total_original_size)}  "
                f"压缩后: {self._fmt_size(total_compressed_size)}  "
                f"节省: {self._fmt_size(saved)} ({ratio:.1f}%)")
            summary_lines.extend([
                f"原始总大小 : {self._fmt_size(total_original_size)}  ({total_original_size:,} 字节)",
                f"压缩后大小 : {self._fmt_size(total_compressed_size)}  ({total_compressed_size:,} 字节)",
                f"共节省空间 : {self._fmt_size(saved)}  (压缩率 {ratio:.1f}%)",
            ])
        logger.finish_session(summary_lines)
        self._send("finished", None)

    def _log_error(self, logger: LogManager, vf: VideoFile, idx: int, total: int):
        """写入错误日志（含 FFmpeg 输出片段）"""
        lines = [
            f"--- 文件 {idx + 1}/{total}  [错误] ---",
            f"  出错时间 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  文件路径 : {vf.path}",
            f"  原因     : {vf.error_msg}",
        ]
        if vf.output_path:
            lines.append(f"  输出文件 : {vf.output_path}")
        if vf.error_detail:
            lines.append(f"  FFmpeg 输出片段:")
            for l in vf.error_detail.splitlines():
                lines.append(f"    {l}")
        lines.append("")
        logger.write_error("\n".join(lines))

    def _process_file(self, vf: VideoFile) -> str:
        """处理单个视频文件"""
        vf.status = "processing"
        self._send("file_status_update", vf)

        # 确定输出路径
        if self.settings.custom_output_dir and self.source_dir:
            # 自定义输出目录：镜像源文件夹结构
            rel_path = vf.path.parent.relative_to(self.source_dir)
            output_dir = Path(self.settings.custom_output_dir) / rel_path
        else:
            # 默认：源文件目录下的子文件夹
            output_dir = vf.path.parent / self.settings.output_subdir
        output_dir.mkdir(parents=True, exist_ok=True)

        # 输出文件名：保留原文件名，确保后缀为 .mp4
        output_name = vf.path.stem + ".mp4"
        output_path = output_dir / output_name

        # 如果输出文件已存在且大小合理，跳过
        if output_path.exists() and output_path.stat().st_size > 0 and not self.settings.overwrite:
            vf.status = "skipped"
            vf.output_path = output_path
            vf.output_size = output_path.stat().st_size
            return "skipped"

        # 预检查：源文件已经是高效编码格式，跳过以避免越压越大
        already_compressed_codecs = {"hevc", "h265", "av1", "vp9"}
        if not self.settings.force_compress and vf.codec.lower() in already_compressed_codecs:
            vf.status = "skipped"
            vf.error_msg = f"源文件已是 {vf.codec.upper()} 编码，无需重新压缩"
            return "skipped"

        # 获取视频时长用于计算进度
        duration = FFmpegHelper.get_duration_from_probe(vf.path)
        vf.duration = duration

        # 构建命令
        cmd = FFmpegHelper.build_compress_cmd(
            vf.path, output_path, self.settings, self.settings.overwrite,
            vf.width, vf.height
        )

        self._send("log", f"[编码] {vf.path.name}  (时长: {self._fmt_time(duration)})")

        # 执行 FFmpeg
        encode_start = time.time()
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )

        # 实时读取进度，同时保留最近 15 行输出（出错时写入错误日志）
        stderr_tail = deque(maxlen=15)
        last_progress_time = time.time()
        for line in process.stderr:
            stderr_tail.append(line.rstrip())
            if self._stop_event.is_set():
                process.kill()
                vf.status = "error"
                vf.error_msg = "用户中止"
                vf.error_detail = "\n".join(stderr_tail)
                # 清理不完整的输出文件
                if output_path.exists():
                    try:
                        output_path.unlink()
                    except OSError:
                        pass
                return "error"

            # 暂停检测
            self._pause_event.wait()

            # 解析进度
            if "time=" in line:
                try:
                    time_str = line.split("time=")[1].split()[0]
                    parts = time_str.split(":")
                    current_sec = (
                        float(parts[0]) * 3600
                        + float(parts[1]) * 60
                        + float(parts[2])
                    )
                    if duration > 0:
                        progress = min(current_sec / duration * 100, 99.9)
                        vf.progress = progress
                        # 限制进度更新频率
                        now = time.time()
                        if now - last_progress_time > 0.3:
                            self._send("file_progress", progress)
                            last_progress_time = now
                except (IndexError, ValueError):
                    pass

        process.wait()
        vf.encode_seconds = time.time() - encode_start

        if process.returncode != 0:
            vf.status = "error"
            vf.error_msg = f"FFmpeg 返回码: {process.returncode}"
            vf.error_detail = "\n".join(stderr_tail)
            if output_path.exists():
                try:
                    output_path.unlink()
                except OSError:
                    pass
            return "error"

        if not output_path.exists() or output_path.stat().st_size == 0:
            vf.status = "error"
            vf.error_msg = "输出文件为空或不存在"
            vf.error_detail = "\n".join(stderr_tail)
            return "error"

        output_size = output_path.stat().st_size

        # 压缩保护：如果输出文件比源文件更大，丢弃输出并标记为跳过
        if output_size >= vf.size:
            vf.status = "skipped"
            vf.error_msg = f"压缩后反而更大 ({self._fmt_size(output_size)} > {self._fmt_size(vf.size)})，已丢弃"
            try:
                output_path.unlink()
            except OSError:
                pass
            return "skipped"

        vf.status = "done"
        vf.output_path = output_path
        vf.output_size = output_size
        vf.progress = 100.0
        self._send("file_progress", 100.0)
        return "done"

    @staticmethod
    def _fmt_size(size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        """格式化时间"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}分{s}秒"
        else:
            h, remainder = divmod(int(seconds), 3600)
            m, s = divmod(remainder, 60)
            return f"{h}时{m}分{s}秒"


# ============================================================
# 日志管理器
# ============================================================

class LogManager:
    """
    会话日志管理器。

    日志存放在程序目录下的 logs/ 文件夹，分三个子目录:
      - 结果日志/结果日志_YYYYMMDD_HHMMSS.log  记录每个文件的转换成果与汇总
      - 错误日志/错误日志_YYYYMMDD_HHMMSS.log  记录失败文件的详细错误信息
      - 删除日志/删除日志_YYYYMMDD_HHMMSS.log  记录源文件删除操作

    使用 UTF-8 (带 BOM) 编码，记事本/Excel 可直接打开不乱码。
    线程安全，供工作线程和 GUI 线程共同调用。
    """

    LOG_DIR = APP_DIR / "logs"
    current_logger: Optional['LogManager'] = None  # 类级别共享引用

    def __init__(self):
        self._lock = threading.Lock()
        self.result_fp = None
        self.error_fp = None
        self.delete_fp = None
        self.result_path: Optional[Path] = None
        self.error_path: Optional[Path] = None
        self.delete_path: Optional[Path] = None

    def start_session(self, session_id: str, header_lines: list) -> tuple:
        """
        开启一次日志会话。
        返回 (结果日志路径, 错误日志路径, 删除日志路径)
        """
        # 创建子目录
        for sub in ["结果日志", "错误日志", "删除日志"]:
            (self.LOG_DIR / sub).mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.result_path = self.LOG_DIR / "结果日志" / f"结果日志_{ts}.log"
        self.error_path = self.LOG_DIR / "错误日志" / f"错误日志_{ts}.log"
        self.delete_path = self.LOG_DIR / "删除日志" / f"删除日志_{ts}.log"

        self.result_fp = open(self.result_path, "w", encoding="utf-8-sig")
        self.error_fp = open(self.error_path, "w", encoding="utf-8-sig")
        self.delete_fp = open(self.delete_path, "w", encoding="utf-8-sig")

        sep = "=" * 66
        self.result_fp.write(f"{sep}\n视频压缩结果日志  会话: {session_id}\n{sep}\n")
        self.error_fp.write(f"{sep}\n视频压缩错误日志  会话: {session_id}\n{sep}\n")
        self.delete_fp.write(f"{sep}\n视频压缩删除日志  会话: {session_id}\n{sep}\n")
        for line in header_lines:
            self.result_fp.write(f"{line}\n")
            self.error_fp.write(f"{line}\n")
            self.delete_fp.write(f"{line}\n")
        self.result_fp.write(f"\n{'=' * 66}\n\n")
        self.error_fp.write(f"\n{'=' * 66}\n\n")
        self.delete_fp.write(f"\n{'=' * 66}\n\n")
        self._flush()
        LogManager.current_logger = self
        return (str(self.result_path), str(self.error_path), str(self.delete_path))

    def _flush(self):
        if self.result_fp:
            self.result_fp.flush()
        if self.error_fp:
            self.error_fp.flush()
        if self.delete_fp:
            self.delete_fp.flush()

    def write_result(self, text: str):
        """写入结果日志"""
        with self._lock:
            if self.result_fp:
                self.result_fp.write(text)
                self._flush()

    def write_error(self, text: str):
        """写入错误日志"""
        with self._lock:
            if self.error_fp:
                self.error_fp.write(text)
                self._flush()

    def write_delete(self, text: str):
        """写入删除日志"""
        with self._lock:
            if self.delete_fp:
                self.delete_fp.write(text)
                self.delete_fp.flush()

    def finish_session(self, summary_lines: list):
        """写入汇总并关闭日志文件"""
        with self._lock:
            if self.result_fp:
                sep = "=" * 66
                self.result_fp.write(f"\n{sep}\n汇总\n{sep}\n")
                for line in summary_lines:
                    self.result_fp.write(f"{line}\n")
                self.result_fp.write(f"{sep}\n")
                self.result_fp.close()
                self.result_fp = None
            if self.error_fp:
                self.error_fp.write("\n[日志结束]\n")
                self.error_fp.close()
                self.error_fp = None
            if self.delete_fp:
                self.delete_fp.write("\n[日志结束]\n")
                self.delete_fp.close()
                self.delete_fp = None
            LogManager.current_logger = None


# ============================================================
# GUI 界面
# ============================================================

class VideoCompressorApp:
    """主 GUI 应用"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("900x720")
        self.root.minsize(800, 600)

        # 消息队列（工作线程 → GUI）
        self.msg_queue: queue.Queue = queue.Queue()

        # 状态
        self.video_files: list[VideoFile] = []
        self.worker = CompressionWorker(self.msg_queue)
        self.settings = CompressionSettings()
        self.source_dir: Optional[Path] = None
        self.is_processing = False
        self.is_paused = False
        self.dark_mode = False  # 暗夜模式状态
        self.is_scanning = False  # 扫描中状态
        self.force_compress = False  # 强制压缩模式（关闭编码预检跳过）
        self._checking_deletable = False  # 是否正在后台检查可删除文件

        # 检测可用编码器 (CPU / GPU)
        self.available_encoders = detect_available_encoders()
        self.enc_label_to_key = {
            ENCODERS[key]["label"]: key for key in self.available_encoders
        }

        # 样式
        self._setup_styles()

        # 构建界面
        self._build_ui()

        # 默认优先使用 GPU 编码器 (配置文件存在时会覆盖此默认值)
        default_enc = (
            "hevc_nvenc" if "hevc_nvenc" in self.available_encoders
            else self.available_encoders[0]
        )
        self.encoder_var.set(ENCODERS[default_enc]["label"])

        # 加载配置
        self._load_config()

        # 检查 FFmpeg
        if not FFmpegHelper.check_ffmpeg():
            self.root.after(500, self._show_ffmpeg_warning)

        # 捕获按钮回调中抛出的异常。
        # 通过桌面快捷方式以 pythonw.exe（无控制台）启动时，若回调内部报错，
        # 默认的 report_callback_exception 只会把 traceback 打到不存在/stdout 未接的
        # stderr，用户看不到任何提示，表现为“点击没反应”。这里改为弹窗提示并写入日志。
        self.root.report_callback_exception = self._on_tk_exception

        # 消息轮询
        self._poll_messages()

    def _on_tk_exception(self, exc_type, exc, tb):
        """Tkinter 回调异常兜底处理：弹窗提示 + 落盘崩溃日志，避免静默失败。

        以 pythonw.exe（无控制台）启动时，异常无法打到 stderr，
        因此这里主动将完整 traceback 写入 logs/崩溃日志/ 下的文件，方便事后排查。
        """
        import traceback
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        self._log(f"[异常] {exc_type.__name__}: {exc}")
        # 将完整 traceback 落盘，便于无控制台启动时排查
        crash_path = None
        try:
            crash_dir = LogManager.LOG_DIR / "崩溃日志"
            crash_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            crash_path = crash_dir / f"崩溃日志_{ts}.log"
            with open(crash_path, "w", encoding="utf-8-sig") as f:
                f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"异常: {exc_type.__name__}: {exc}\n\n")
                f.write(detail)
        except Exception:
            crash_path = None
        msg = f"执行操作时发生错误：\n\n{exc_type.__name__}: {exc}"
        if crash_path:
            msg += f"\n\n完整堆栈已写入日志文件：\n{crash_path}"
        else:
            msg += "\n\n（详情已写入日志面板）"
        try:
            messagebox.showerror("操作出错", msg, parent=self.root)
        except Exception:
            pass
        # 同时打印到 stderr，方便从控制台启动时查看
        try:
            sys.stderr.write(detail + "\n")
        except Exception:
            pass

    def _setup_styles(self):
        """配置 ttk 样式"""
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._apply_theme()

    def _apply_theme(self):
        """应用当前主题（亮色/暗色）"""
        if self.dark_mode:
            bg = "#1e1e2e"
            fg = "#cdd6f4"
            entry_bg = "#313244"
            entry_fg = "#cdd6f4"
            accent = "#89b4fa"
            accent2 = "#a6e3a1"
            tree_bg = "#1e1e2e"
            tree_fg = "#cdd6f4"
            tree_sel = "#45475a"
            log_bg = "#1e1e2e"
            log_fg = "#a6adc8"
            trough = "#313244"
            hint_fg = "#a6adc8"
            bar_bg = "#89b4fa"
            bar_bg2 = "#a6e3a1"
        else:
            bg = "#f0f0f0"
            fg = "#1e1e1e"
            entry_bg = "#ffffff"
            entry_fg = "#1e1e1e"
            accent = "#2196F3"
            accent2 = "#4CAF50"
            tree_bg = "#ffffff"
            tree_fg = "#1e1e1e"
            tree_sel = "#d0e8ff"
            log_bg = "#ffffff"
            log_fg = "#333333"
            trough = "#e0e0e0"
            hint_fg = "gray"
            bar_bg = "#2196F3"
            bar_bg2 = "#4CAF50"

        s = self.style
        # 全局 ttk 样式
        s.configure(".", background=bg, foreground=fg)
        s.configure("TFrame", background=bg)
        s.configure("TLabel", background=bg, foreground=fg)
        s.configure("TButton", background=entry_bg, foreground=fg)
        s.configure("TCheckbutton", background=bg, foreground=fg)
        s.configure("TLabelframe", background=bg, foreground=fg)
        s.configure("TLabelframe.Label", background=bg, foreground=accent)
        s.configure("TEntry", fieldbackground=entry_bg, foreground=entry_fg)
        s.configure("TCombobox", fieldbackground=entry_bg, foreground=entry_fg,
                     selectbackground=tree_sel, selectforeground=fg)
        s.configure("Treeview", background=tree_bg, foreground=tree_fg,
                     fieldbackground=tree_bg, selectbackground=tree_sel,
                     selectforeground=fg)
        s.configure("Treeview.Heading", background=entry_bg, foreground=fg)
        s.configure("Green.Horizontal.TProgressbar",
                     troughcolor=trough, background=bar_bg2)
        s.configure("Blue.Horizontal.TProgressbar",
                     troughcolor=trough, background=bar_bg)
        s.map("TButton", background=[("active", tree_sel)])

        # 根窗口
        self.root.configure(bg=bg)

        # 日志文本框
        if hasattr(self, 'log_text'):
            self.log_text.configure(bg=log_bg, fg=log_fg,
                                     insertbackground=fg, selectbackground=tree_sel)

        # 当前文件标签和速度标签
        if hasattr(self, 'current_file_label'):
            self.current_file_label.configure(foreground=hint_fg)
        if hasattr(self, 'speed_label'):
            self.speed_label.configure(foreground=hint_fg)

    def _toggle_dark_mode(self):
        """切换亮色/暗色主题"""
        self.dark_mode = not self.dark_mode
        self._apply_theme()
        self.theme_btn.config(text="☀️ 亮色" if self.dark_mode else "🌙 暗色")

    def _on_force_compress_toggle(self):
        """编码预检开关回调"""
        self.force_compress = self.force_compress_var.get()
        if self.force_compress:
            self._log("[模式] 编码预检已关闭 — HEVC/AV1/VP9 高效编码源文件将照常压缩")
        else:
            self._log("[模式] 编码预检已开启 — HEVC/AV1/VP9 高效编码源文件将被跳过")

    def _build_ui(self):
        """构建主界面"""
        # 主容器
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ---- 顶部：文件夹选择 ----
        folder_frame = ttk.LabelFrame(main_frame, text=" 源文件夹 ", padding=8)
        folder_frame.pack(fill=tk.X, pady=(0, 8))

        self.folder_var = tk.StringVar(value="(请选择包含视频文件的文件夹)")
        folder_entry = ttk.Entry(folder_frame, textvariable=self.folder_var, state="readonly")
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        ttk.Button(folder_frame, text="选择文件夹", command=self._select_folder).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(folder_frame, text="选择文件", command=self._select_files).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(folder_frame, text="扫描", command=self._scan_files).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(folder_frame, text="清除", command=self._clear_files).pack(side=tk.LEFT)

        # ---- 设置面板 ----
        settings_frame = ttk.LabelFrame(main_frame, text=" 压缩设置 ", padding=8)
        settings_frame.pack(fill=tk.X, pady=(0, 8))

        # 第一行: 编码器 和 质量
        row1 = ttk.Frame(settings_frame)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="编码器:").pack(side=tk.LEFT)
        self.encoder_var = tk.StringVar()
        self.encoder_combo = ttk.Combobox(row1, textvariable=self.encoder_var,
                                           values=list(self.enc_label_to_key.keys()),
                                           state="readonly", width=30)
        self.encoder_combo.pack(side=tk.LEFT, padx=(2, 12))
        self.encoder_var.trace_add("write", self._on_encoder_change)

        self.crf_label_quality = ttk.Label(row1, text="质量 (CRF):")
        self.crf_label_quality.pack(side=tk.LEFT)
        self.crf_var = tk.IntVar(value=DEFAULT_CRF)
        crf_scale = ttk.Scale(row1, from_=18, to=40, variable=self.crf_var,
                               orient=tk.HORIZONTAL, length=160)
        crf_scale.pack(side=tk.LEFT, padx=5)
        self.crf_label = ttk.Label(row1, text=str(DEFAULT_CRF), width=3)
        self.crf_label.pack(side=tk.LEFT)
        self.crf_var.trace_add("write", self._on_crf_change)

        self.quality_hint = ttk.Label(row1, text="", foreground="gray")
        self.quality_hint.pack(side=tk.LEFT, padx=(8, 0))

        # 第二行: 编码速度 和 分辨率
        row1b = ttk.Frame(settings_frame)
        row1b.pack(fill=tk.X, pady=2)

        ttk.Label(row1b, text="编码速度:").pack(side=tk.LEFT)
        self.preset_var = tk.StringVar(value=DEFAULT_PRESET)
        self.preset_combo = ttk.Combobox(row1b, textvariable=self.preset_var,
                                          state="readonly", width=12)
        self.preset_combo.pack(side=tk.LEFT, padx=5)
        self.preset_hint = ttk.Label(row1b, text="", foreground="gray")
        self.preset_hint.pack(side=tk.LEFT, padx=(8, 0))

        # 第三行: 分辨率和输出
        row2 = ttk.Frame(settings_frame)
        row2.pack(fill=tk.X, pady=2)

        ttk.Label(row2, text="最大分辨率:").pack(side=tk.LEFT)
        self.scale_var = tk.StringVar(value="原始分辨率")
        scale_combo = ttk.Combobox(row2, textvariable=self.scale_var,
                                    values=list(SCALE_OPTIONS.keys()),
                                    state="readonly", width=18)
        scale_combo.pack(side=tk.LEFT, padx=5)

        ttk.Label(row2, text="    输出子文件夹:").pack(side=tk.LEFT)
        self.subdir_var = tk.StringVar(value=DEFAULT_OUTPUT_SUBDIR)
        subdir_entry = ttk.Entry(row2, textvariable=self.subdir_var, width=15)
        subdir_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(row2, text="    音频码率:").pack(side=tk.LEFT)
        self.audio_br_var = tk.StringVar(value="128k")
        audio_combo = ttk.Combobox(row2, textvariable=self.audio_br_var,
                                    values=["64k", "96k", "128k", "192k", "256k", "320k"],
                                    state="readonly", width=8)
        audio_combo.pack(side=tk.LEFT, padx=5)

        # 第四行: 自定义输出目录
        row3 = ttk.Frame(settings_frame)
        row3.pack(fill=tk.X, pady=2)

        self.use_custom_output_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row3, text="自定义输出目录:", variable=self.use_custom_output_var,
                         command=self._on_custom_output_toggle).pack(side=tk.LEFT)
        self.custom_output_var = tk.StringVar(value="")
        self.custom_output_entry = ttk.Entry(row3, textvariable=self.custom_output_var, width=50, state="disabled")
        self.custom_output_entry.pack(side=tk.LEFT, padx=5)
        self.custom_output_btn = ttk.Button(row3, text="浏览...", command=self._select_output_dir, state="disabled")
        self.custom_output_btn.pack(side=tk.LEFT)

        # 第五行: 编码预检开关
        row4 = ttk.Frame(settings_frame)
        row4.pack(fill=tk.X, pady=(4, 2))

        self.force_compress_var = tk.BooleanVar(value=False)
        self.force_check = ttk.Checkbutton(row4, text="强制压缩高效编码源文件 (HEVC/AV1/VP9)",
                                            variable=self.force_compress_var,
                                            command=self._on_force_compress_toggle)
        self.force_check.pack(side=tk.LEFT)

        # ---- 文件列表 ----
        list_frame = ttk.LabelFrame(main_frame, text=" 视频文件列表 ", padding=4)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # Treeview
        columns = ("check", "filename", "size", "resolution", "duration", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
        self.tree.heading("check", text="✓")
        self.tree.heading("filename", text="文件名")
        self.tree.heading("size", text="大小")
        self.tree.heading("resolution", text="分辨率")
        self.tree.heading("duration", text="时长")
        self.tree.heading("status", text="状态")

        self.tree.column("check", width=30, minwidth=30, anchor=tk.CENTER)
        self.tree.column("filename", width=300, minwidth=180)
        self.tree.column("size", width=80, minwidth=60, anchor=tk.E)
        self.tree.column("resolution", width=100, minwidth=80, anchor=tk.CENTER)
        self.tree.column("duration", width=80, minwidth=60, anchor=tk.CENTER)
        self.tree.column("status", width=80, minwidth=60, anchor=tk.CENTER)

        # 点击勾选列切换选中状态
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)

        # 滚动条
        scrollbar_y = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        # 选择栏 + 统计栏
        select_frame = ttk.Frame(list_frame)
        select_frame.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(select_frame, text="全选", width=5, command=self._select_all).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(select_frame, text="取消全选", width=8, command=self._deselect_all).pack(side=tk.LEFT, padx=(0, 8))
        self.stats_label = ttk.Label(select_frame, text="共 0 个文件")
        self.stats_label.pack(side=tk.LEFT)

        # ---- 进度区域 ----
        progress_frame = ttk.LabelFrame(main_frame, text=" 处理进度 ", padding=8)
        progress_frame.pack(fill=tk.X, pady=(0, 8))

        # 总体进度
        overall_row = ttk.Frame(progress_frame)
        overall_row.pack(fill=tk.X, pady=2)
        ttk.Label(overall_row, text="总体进度:", width=10).pack(side=tk.LEFT)
        self.overall_progress = ttk.Progressbar(overall_row, mode="determinate",
                                                  style="Blue.Horizontal.TProgressbar")
        self.overall_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.overall_label = ttk.Label(overall_row, text="0/0", width=10, anchor=tk.E)
        self.overall_label.pack(side=tk.LEFT)

        # 当前文件进度
        file_row = ttk.Frame(progress_frame)
        file_row.pack(fill=tk.X, pady=2)
        ttk.Label(file_row, text="当前文件:", width=10).pack(side=tk.LEFT)
        self.file_progress = ttk.Progressbar(file_row, mode="determinate",
                                               style="Green.Horizontal.TProgressbar")
        self.file_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.file_progress_label = ttk.Label(file_row, text="0%", width=10, anchor=tk.E)
        self.file_progress_label.pack(side=tk.LEFT)

        self.current_file_label = ttk.Label(progress_frame, text="", foreground="gray")
        self.current_file_label.pack(anchor=tk.W, pady=(4, 0))

        # 速度/ETA 行
        speed_row = ttk.Frame(progress_frame)
        speed_row.pack(fill=tk.X, pady=2)
        self.speed_label = ttk.Label(speed_row, text="", foreground="gray")
        self.speed_label.pack(side=tk.LEFT)

        # ---- 控制按钮和日志 ----
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.BOTH, expand=True)

        # 按钮
        btn_frame = ttk.Frame(bottom_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 4))

        self.start_btn = ttk.Button(btn_frame, text="▶ 开始压缩", command=self._start_compress)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.pause_btn = ttk.Button(btn_frame, text="⏸ 暂停", command=self._toggle_pause, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.stop_btn = ttk.Button(btn_frame, text="⏹ 停止", command=self._stop_compress, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.delete_btn = ttk.Button(btn_frame, text="🗑 删除已压缩源文件", command=self._delete_source_files)
        self.delete_btn.pack(side=tk.LEFT, padx=(12, 4))

        self.log_dir_btn = ttk.Button(btn_frame, text="📂 打开日志文件夹", command=self._open_log_dir)
        self.log_dir_btn.pack(side=tk.RIGHT, padx=(0, 4))

        self.save_config_btn = ttk.Button(btn_frame, text="💾 保存设置", command=self._save_config)
        self.save_config_btn.pack(side=tk.RIGHT)

        self.theme_btn = ttk.Button(btn_frame, text="🌙 暗色", command=self._toggle_dark_mode)
        self.theme_btn.pack(side=tk.RIGHT, padx=(0, 4))

        # 日志
        log_frame = ttk.LabelFrame(bottom_frame, text=" 日志 ", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=8, state=tk.DISABLED,
                                 font=("Consolas", 9), wrap=tk.WORD)
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # ---- 事件处理 ----

    def _on_crf_change(self, *args):
        """CRF/CQ 值变更时更新标签"""
        self.crf_label.config(text=str(self.crf_var.get()))

    def _on_encoder_change(self, *args):
        """编码器变更时同步相关控件"""
        enc_key = self.enc_label_to_key.get(self.encoder_var.get(), "libx265")
        cfg = ENCODERS[enc_key]

        # 更新预设列表和默认值
        self.preset_combo["values"] = cfg["presets"]
        self.preset_var.set(cfg["default_preset"])

        if enc_key == "libx265":
            # CPU 编码
            self.crf_label_quality.config(text="质量 (CRF):")
            self.quality_hint.config(text="提示: 值越小质量越高、文件越大 (推荐 26-30)")
            self.preset_hint.config(text="提示: 越慢压缩率越好，但耗时越长")
            self.crf_var.set(cfg["default_q"])
        else:
            # GPU 硬件编码
            self.crf_label_quality.config(text="质量 (CQ):")
            if enc_key == "av1_nvenc":
                self.quality_hint.config(text="提示: 值越小质量越高、文件越大 (推荐 24-28)")
            else:
                self.quality_hint.config(text="提示: 值越小质量越高、文件越大 (推荐 22-26)")
            self.preset_hint.config(text="提示: p1 最快、p7 质量最好 (推荐 p5)")
            self.crf_var.set(cfg["default_q"])

    def _select_folder(self):
        """选择源文件夹"""
        folder = filedialog.askdirectory(title="选择包含视频文件的文件夹")
        if folder:
            self.source_dir = Path(folder)
            self.folder_var.set(str(self.source_dir))
            self._scan_files()

    def _select_files(self):
        """通过 Windows 文件浏览对话框多选视频文件（后台线程执行）"""
        if self.is_scanning:
            return
        ext_patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        filetypes = [
            ("视频文件", ext_patterns),
            ("所有文件", "*.*"),
        ]
        paths = filedialog.askopenfilenames(
            title="选择视频文件（可按住 Ctrl 或 Shift 多选）",
            filetypes=filetypes,
        )
        if not paths:
            return

        self.is_scanning = True
        self._log(f"[选择] 已选 {len(paths)} 个文件，正在读取信息...")
        self.video_files.clear()
        self.tree.delete(*self.tree.get_children())
        self.stats_label.config(text="读取中...")

        def bg_select():
            history = load_processing_history()
            total_files = len(paths)
            self.msg_queue.put(("scan_progress", (0, total_files)))
            files = []
            for i, p in enumerate(paths):
                filepath = Path(p)
                try:
                    size = filepath.stat().st_size
                except OSError:
                    continue
                vf = VideoFile(path=filepath, size=size, status="pending", checked=True)
                if str(filepath) in history:
                    vf.status = "done"
                info = FFmpegHelper.probe_video(filepath)
                if info:
                    for stream in info.get("streams", []):
                        if stream.get("codec_type") == "video":
                            vf.width = int(stream.get("width", 0))
                            vf.height = int(stream.get("height", 0))
                            vf.codec = stream.get("codec_name", "")
                            break
                    if "format" in info:
                        try:
                            vf.duration = float(info["format"].get("duration", 0))
                        except (ValueError, TypeError):
                            pass
                files.append(vf)
                self.msg_queue.put(("scan_progress", (i + 1, total_files)))
            files.sort(key=lambda v: v.path.name.lower())
            total_size = sum(v.size for v in files)
            processed_count = sum(1 for v in files if v.status == "done")
            self.msg_queue.put(("scan_complete", (files, len(files), total_size, processed_count, True)))

        threading.Thread(target=bg_select, daemon=True).start()

    def _select_output_dir(self):
        """选择自定义输出目录"""
        folder = filedialog.askdirectory(title="选择压缩文件输出目录")
        if folder:
            self.custom_output_var.set(folder)

    def _on_custom_output_toggle(self):
        """自定义输出目录复选框切换"""
        if self.use_custom_output_var.get():
            self.custom_output_entry.config(state="normal")
            self.custom_output_btn.config(state="normal")
        else:
            self.custom_output_entry.config(state="disabled")
            self.custom_output_btn.config(state="disabled")

    def _on_tree_click(self, event):
        """处理 Treeview 点击事件，切换勾选状态"""
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        column = self.tree.identify_column(event.x)
        if column != "#1":  # 只有点击第一列（勾选列）才触发
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        children = self.tree.get_children()
        if item not in children:
            return
        idx = children.index(item)
        if idx < len(self.video_files):
            vf = self.video_files[idx]
            vf.checked = not vf.checked
            check_mark = "☑" if vf.checked else "☐"
            values = list(self.tree.item(item, "values"))
            values[0] = check_mark
            self.tree.item(item, values=values)
            self._update_stats()

    def _select_all(self):
        """全选所有文件"""
        for i, vf in enumerate(self.video_files):
            vf.checked = True
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[0] = "☑"
            self.tree.item(item, values=values)
        self._update_stats()

    def _deselect_all(self):
        """取消全选"""
        for i, vf in enumerate(self.video_files):
            vf.checked = False
        for item in self.tree.get_children():
            values = list(self.tree.item(item, "values"))
            values[0] = "☐"
            self.tree.item(item, values=values)
        self._update_stats()

    def _update_stats(self):
        """更新统计栏，显示选中文件的数量和总大小"""
        total = len(self.video_files)
        checked = [vf for vf in self.video_files if vf.checked]
        checked_count = len(checked)
        checked_size = sum(vf.size for vf in checked)
        total_size = sum(vf.size for vf in self.video_files)
        if checked_count == 0:
            self.stats_label.config(
                text=f"共 {total} 个文件  |  总大小: {self._fmt_size(total_size)}  （未选择文件）"
            )
        else:
            self.stats_label.config(
                text=f"共 {total} 个文件  |  已选: {checked_count} 个  |  "
                     f"选中大小: {self._fmt_size(checked_size)}  |  "
                     f"总大小: {self._fmt_size(total_size)}"
            )

    def _scan_files(self):
        """扫描文件夹中的视频文件（后台线程执行，避免 GUI 卡顿）"""
        if not self.source_dir or not self.source_dir.exists():
            messagebox.showwarning("提示", "请先选择一个有效的文件夹。")
            return
        if self.is_scanning:
            return

        self.is_scanning = True
        self._log("[扫描] 正在扫描视频文件...")
        self.video_files.clear()
        self.tree.delete(*self.tree.get_children())
        self.stats_label.config(text="扫描中...")

        source_dir = self.source_dir
        output_subdir = self.settings.output_subdir

        def bg_scan():
            history = load_processing_history()
            # 第一遍：快速统计文件总数
            all_paths = []
            for ext in SUPPORTED_EXTENSIONS:
                for filepath in source_dir.rglob(f"*{ext}"):
                    if output_subdir in filepath.parts:
                        rel = filepath.relative_to(source_dir)
                        if output_subdir in rel.parts:
                            continue
                    all_paths.append(filepath)
            total_files = len(all_paths)
            self.msg_queue.put(("scan_progress", (0, total_files)))
            # 第二遍：逐文件探测
            files = []
            for i, filepath in enumerate(all_paths):
                try:
                    size = filepath.stat().st_size
                except OSError:
                    continue
                vf = VideoFile(path=filepath, size=size, status="pending")
                if str(filepath) in history:
                    vf.status = "done"
                info = FFmpegHelper.probe_video(filepath)
                if info:
                    for stream in info.get("streams", []):
                        if stream.get("codec_type") == "video":
                            vf.width = int(stream.get("width", 0))
                            vf.height = int(stream.get("height", 0))
                            vf.codec = stream.get("codec_name", "")
                            break
                    if "format" in info:
                        try:
                            vf.duration = float(info["format"].get("duration", 0))
                        except (ValueError, TypeError):
                            pass
                files.append(vf)
                self.msg_queue.put(("scan_progress", (i + 1, total_files)))
            files.sort(key=lambda v: v.path.name.lower())
            total_size = sum(v.size for v in files)
            processed_count = sum(1 for v in files if v.status == "done")
            self.msg_queue.put(("scan_complete", (files, len(files), total_size, processed_count)))

        threading.Thread(target=bg_scan, daemon=True).start()

    def _clear_files(self):
        """清除文件列表"""
        self.video_files.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.stats_label.config(text="共 0 个文件")
        self.source_dir = None
        self.folder_var.set("(请选择包含视频文件的文件夹)")

    def _start_compress(self):
        """开始压缩"""
        if not self.video_files:
            messagebox.showwarning("提示", "请先扫描视频文件。")
            return

        if not FFmpegHelper.check_ffmpeg():
            messagebox.showerror("错误",
                "未检测到 FFmpeg！\n\n"
                "请安装 FFmpeg 并将其添加到系统 PATH 中。\n"
                "下载地址: https://ffmpeg.org/download.html")
            return

        # 筛选勾选的文件
        selected_files = [vf for vf in self.video_files if vf.checked and vf.status not in ("done",)]
        if not selected_files:
            messagebox.showwarning("提示",
                "没有可处理的文件。\n\n"
                "请勾选要处理的文件，或点击“全选”按钮。\n"
                "已标记为“已完成”的文件不会重复处理。")
            return

        # 收集设置
        enc_key = self.enc_label_to_key.get(self.encoder_var.get(), "libx265")
        custom_dir = self.custom_output_var.get().strip() if self.use_custom_output_var.get() else ""
        self.settings = CompressionSettings(
            encoder=enc_key,
            crf=self.crf_var.get(),
            preset=self.preset_var.get(),
            output_subdir=self.subdir_var.get().strip() or DEFAULT_OUTPUT_SUBDIR,
            max_resolution=self.scale_var.get(),
            audio_bitrate=self.audio_br_var.get(),
            custom_output_dir=custom_dir,
            force_compress=self.force_compress,
        )
        self._log(f"[设置] 编码器: {ENCODERS[enc_key]['label']}  "
                  f"质量: {self.crf_var.get()}  预设: {self.preset_var.get()}")

        # ---- 磁盘空间预检 + 三联预览 ----
        total_source_size = sum(vf.size for vf in selected_files)
        # 确定输出目标路径
        if custom_dir:
            output_dest = custom_dir
        else:
            output_dest = f"各源文件目录下的 {self.settings.output_subdir} 子文件夹"
        # 检查输出目标盘的剩余空间
        try:
            if custom_dir:
                check_path = Path(custom_dir)
            elif self.source_dir:
                check_path = self.source_dir
            else:
                check_path = selected_files[0].path.parent
            disk_usage = shutil.disk_usage(str(check_path))
            free_gb = disk_usage.free / (1024 ** 3)
            # 粗略估计压缩后大小（约源文件的 50%）
            estimated_output = total_source_size * 0.5
            space_warning = ""
            if free_gb < estimated_output / (1024 ** 3) * 1.1:  # 留 10% 余量
                space_warning = (f"\n\n⚠️ 警告：目标盘剩余空间 ({free_gb:.1f} GB) "
                                 f"可能不足以容纳预计输出 ({estimated_output / (1024**3):.1f} GB)！")
        except Exception:
            free_gb = -1
            space_warning = "\n\n⚠️ 无法检测目标盘剩余空间"

        # 三联预览确认弹窗
        enc_label = ENCODERS[enc_key]['label']
        preview_msg = (
            f"即将开始压缩：\n\n"
            f"  📁 文件数量 : {len(selected_files)} 个\n"
            f"  📊 源文件总大小 : {self._fmt_size(total_source_size)}\n"
            f"  📦 预计输出大小 : ~{self._fmt_size(int(estimated_output))}  (按约 50% 压缩率估算)\n"
            f"  📂 输出位置 : {output_dest}\n"
            f"  💾 目标盘剩余 : {free_gb:.1f} GB\n"
            f"  🎬 编码器 : {enc_label}\n"
            f"  ⚙️ 质量 : {self.crf_var.get()}  预设 : {self.preset_var.get()}\n"
            f"{space_warning}\n"
            f"确定开始吗？"
        )
        if not messagebox.askyesno("压缩预览确认", preview_msg):
            return

        # 重置状态（仅重置选中的文件）
        for vf in selected_files:
            vf.status = "pending"
            vf.progress = 0.0
            vf.error_msg = ""

        self.is_processing = True
        self.is_paused = False
        self.start_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL)
        self.overall_progress["value"] = 0
        self.file_progress["value"] = 0
        self.speed_label.config(text="")

        self._log(f"[开始] 已选 {len(selected_files)} 个文件待处理")

        # 启动工作线程
        self.worker = CompressionWorker(self.msg_queue)
        self.worker.start(selected_files, self.settings, self.source_dir)

    def _toggle_pause(self):
        """切换暂停/恢复"""
        if not self.is_processing:
            return

        if self.is_paused:
            self.worker.resume()
            self.pause_btn.config(text="⏸ 暂停")
            self.is_paused = False
        else:
            self.worker.pause()
            self.pause_btn.config(text="▶ 恢复")
            self.is_paused = True

    def _stop_compress(self):
        """停止压缩"""
        if self.is_processing:
            if messagebox.askyesno("确认", "确定要停止当前的压缩任务吗？\n已完成的文件不受影响。"):
                self.worker.stop()

    def _on_finished(self):
        """处理完成"""
        self.is_processing = False
        self.is_paused = False
        self.start_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.DISABLED, text="⏸ 暂停")
        self.stop_btn.config(state=tk.DISABLED)
        # 刷新文件列表状态
        self._refresh_tree()

    # ---- 消息轮询 ----

    def _poll_messages(self):
        """轮询工作线程消息"""
        try:
            while True:
                msg_type, data = self.msg_queue.get_nowait()
                self._handle_message(msg_type, data)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_messages)

    def _handle_message(self, msg_type: str, data):
        """处理工作线程消息"""
        if msg_type == "scan_progress":
            current, total = data
            if total > 0:
                self.overall_progress["maximum"] = total
                self.overall_progress["value"] = current
                self.overall_label.config(text=f"{current}/{total}")
                self.stats_label.config(text=f"扫描中... {current}/{total}")
        elif msg_type == "scan_complete":
            # 扫描完成：填充 Treeview
            files, count, total_size, processed_count = data[0], data[1], data[2], data[3]
            is_select = data[4] if len(data) > 4 else False
            self.video_files = files
            self.tree.delete(*self.tree.get_children())
            items = []
            for vf in self.video_files:
                check_mark = "☑" if vf.checked else "☐"
                size_str = self._fmt_size(vf.size)
                res_str = f"{vf.width}x{vf.height}" if vf.width else "未知"
                dur_str = self._fmt_time(vf.duration) if vf.duration else "未知"
                status_str = self._get_status_text(vf.status)
                items.append((check_mark, vf.path.name, size_str, res_str, dur_str, status_str))
            if items:
                for item_vals in items:
                    self.tree.insert("", tk.END, values=item_vals)
            if is_select and self.video_files:
                self.source_dir = self.video_files[0].path.parent
                self.folder_var.set(f"已手动选择 {count} 个文件")
            self._update_stats()
            self._log(f"[扫描] 找到 {count} 个视频文件，总大小 {self._fmt_size(total_size)}")
            if processed_count > 0:
                self._log(f"[扫描] 其中 {processed_count} 个文件之前已处理过（标记为“已完成”）")
            self.is_scanning = False
        elif msg_type == "log":
            self._log(data)
        elif msg_type == "log_session_paths":
            result_path, error_path, delete_path = data
            self._log("[日志] 本次会话日志文件：")
            self._log(f"  结果日志: {result_path}")
            self._log(f"  错误日志: {error_path}")
            self._log(f"  删除日志: {delete_path}")
        elif msg_type == "overall_progress":
            current, total = data
            if total > 0:
                self.overall_progress["maximum"] = total
                self.overall_progress["value"] = current
                self.overall_label.config(text=f"{current}/{total}")
        elif msg_type == "file_progress":
            self.file_progress["value"] = data
            self.file_progress_label.config(text=f"{data:.1f}%")
        elif msg_type == "current_file":
            idx, total, name = data
            self.current_file_label.config(text=f"正在处理: {name}")
        elif msg_type == "file_status":
            idx, status = data
            # 更新 Treeview 中的状态
            children = self.tree.get_children()
            if idx < len(children):
                item = children[idx]
                values = list(self.tree.item(item, "values"))
                values[4] = self._get_status_text(status)
                self.tree.item(item, values=values)
        elif msg_type == "speed_update":
            speed_mbs, eta_sec, elapsed = data
            # 格式化速度
            if speed_mbs >= 1:
                speed_str = f"{speed_mbs:.1f} MB/s"
            else:
                speed_str = f"{speed_mbs * 1024:.0f} KB/s"
            # 格式化已用时间
            elapsed_str = self._fmt_time(elapsed)
            # 格式化 ETA
            if eta_sec < 60:
                eta_str = f"{int(eta_sec)}秒"
            elif eta_sec < 3600:
                m, s = divmod(int(eta_sec), 60)
                eta_str = f"{m}分{s}秒"
            else:
                h, remainder = divmod(int(eta_sec), 3600)
                m, s = divmod(remainder, 60)
                eta_str = f"{h}时{m}分{s}秒"
            self.speed_label.config(
                text=f"⚡ {speed_str}  |  已用: {elapsed_str}  |  预计剩余: {eta_str}"
            )
        elif msg_type == "finished":
            self._on_finished()
        elif msg_type == "deletable_ready":
            self._checking_deletable = False
            self.delete_btn.config(state=tk.NORMAL)
            self._proceed_delete(data)
        elif msg_type == "deletable_error":
            self._checking_deletable = False
            self.delete_btn.config(state=tk.NORMAL)
            self._log(f"[异常] 检查可删除文件失败: {data}")
            messagebox.showerror(
                "操作出错",
                f"检查可删除文件时发生错误：\n\n{type(data).__name__}: {data}",
                parent=self.root,
            )

    def _refresh_tree(self):
        """刷新 Treeview 中所有文件的状态"""
        children = self.tree.get_children()
        for i, vf in enumerate(self.video_files):
            if i < len(children):
                item = children[i]
                values = list(self.tree.item(item, "values"))
                values[4] = self._get_status_text(vf.status)
                self.tree.item(item, values=values)

    # ---- 工具方法 ----

    def _open_log_dir(self):
        """打开日志文件夹"""
        log_dir = LogManager.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(log_dir))
        else:
            import subprocess as sp
            sp.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(log_dir)])

    def _log(self, text: str):
        """写入日志"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {text}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _get_deletable_files(self) -> list:
        """获取可安全删除的源文件（在后台线程调用，含较多磁盘探测）。
        检查两类来源：
          1. 当前会话中压缩成功的文件（有 output_path）
          2. 处理历史记录中的文件（从 .processing_history.json 加载）
        只有当对应的压缩输出文件确实存在且非空时才纳入删除列表。
        """
        deletable = []
        seen_paths = set()

        # 实时读取输出相关设置（避免使用未同步的 self.settings）
        subdir = self.subdir_var.get().strip() or DEFAULT_OUTPUT_SUBDIR
        custom_dir = (
            self.custom_output_var.get().strip()
            if self.use_custom_output_var.get() else ""
        )
        # 自定义输出目录只遍历一次建立文件名索引，供逐文件兜底复用，
        # 避免对每个源文件都递归遍历整棵输出树（那会长时间卡死界面）。
        custom_index = self._build_output_index(custom_dir) if custom_dir else None

        # 第一类：当前会话中压缩成功的文件
        for vf in self.video_files:
            if vf.status != "done" or not vf.output_path:
                continue
            key = os.path.normcase(str(vf.path))
            if key in seen_paths:
                continue
            try:
                if vf.output_path.exists() and vf.output_path.stat().st_size > 0:
                    deletable.append(vf)
                    seen_paths.add(key)
            except OSError:
                pass

        # 第二类：处理历史记录中的文件（即使本次未运行压缩）
        history = load_processing_history()
        for path_str in history:
            key = os.path.normcase(path_str)
            if key in seen_paths:
                continue
            source_path = Path(path_str)
            if not source_path.exists():
                continue  # 源文件已不存在，跳过
            # 查找对应的压缩输出文件（精确路径优先，兜底才用文件名索引）
            output_path = self._find_output_for_source(
                source_path, subdir=subdir, custom_dir=custom_dir,
                custom_index=custom_index,
            )
            if output_path and output_path.exists() and output_path.stat().st_size > 0:
                try:
                    size = source_path.stat().st_size
                except OSError:
                    continue
                # 创建一个临时 VideoFile 用于显示
                vf = VideoFile(
                    path=source_path,
                    size=size,
                    status="done",
                    output_path=output_path,
                )
                deletable.append(vf)
                seen_paths.add(key)

        return deletable

    @staticmethod
    def _build_output_index(custom_dir: str) -> dict:
        """遍历自定义输出目录一次，建立 {文件名: [完整路径, ...]} 索引。
        仅在按精确镜像路径找不到输出时作为兜底使用，避免逐文件重复遍历整棵树。"""
        index = {}
        try:
            for root_dir, _dirs, files in os.walk(custom_dir):
                for fn in files:
                    index.setdefault(fn, []).append(Path(root_dir) / fn)
        except OSError:
            pass
        return index

    def _find_output_for_source(
        self,
        source_path: Path,
        subdir: Optional[str] = None,
        custom_dir: Optional[str] = None,
        custom_index: Optional[dict] = None,
    ) -> Optional[Path]:
        """根据源文件路径查找对应的压缩输出文件。

        优先使用可精确计算、且唯一可靠的路径：
          - 默认模式：源文件目录 / 输出子文件夹 / 同名.mp4
          - 自定义输出目录：镜像源文件夹结构后的精确路径
        只要能算出镜像路径，它就是唯一答案；找不到就说明该源文件确实没有
        对应压缩输出，不再按文件名全局搜索——否则容易误匹配到别的源文件的
        同名输出，污染可删除列表、使“还有 xx 个文件”数量虚高。
        只有在完全不知道 source_dir（无法算镜像）时，才退回到按文件名兜底。
        """
        output_name = source_path.stem + ".mp4"

        if subdir is None:
            subdir = self.subdir_var.get().strip() or DEFAULT_OUTPUT_SUBDIR
        if custom_dir is None:
            custom_dir = (
                self.custom_output_var.get().strip()
                if self.use_custom_output_var.get() else ""
            )

        def _valid(p: Path) -> bool:
            try:
                return p.exists() and p.stat().st_size > 0
            except OSError:
                return False

        # 1) 默认位置：源文件目录下的输出子文件夹（精确、唯一）
        default_output = source_path.parent / subdir / output_name
        if _valid(default_output):
            return default_output

        # 2) 自定义输出目录：镜像源文件夹结构（精确、唯一）
        if custom_dir and self.source_dir:
            custom_base = Path(custom_dir)
            try:
                rel_dir = source_path.parent.relative_to(self.source_dir)
                custom_output = custom_base / rel_dir / output_name
                if _valid(custom_output):
                    return custom_output
            except ValueError:
                pass
            # 已知 source_dir：镜像路径即唯一答案，找不到就判定无可删除输出，
            # 不再做可能误匹配的全局文件名搜索。
            return None

        # 3) 兜底：仅当完全不知道 source_dir 时，才按文件名在输出目录里查
        if custom_dir:
            if custom_index is None:
                custom_index = self._build_output_index(custom_dir)
            for cand in custom_index.get(output_name, []):
                if _valid(cand):
                    return cand

        return None

    @staticmethod
    def _send_to_recycle_bin(path: str) -> bool:
        """将文件移入 Windows 回收站（可恢复），成功返回 True"""
        if sys.platform != "win32":
            return False
        try:
            # FO_PROMPTUSER = 0, FO_ALLOWUNDO = 0x40, FOF_NOCONFIRMATION = 0x10
            # FOF_NOERRORUI = 0x400
            flags = 0x40 | 0x10 | 0x400  # FO_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI
            ShFileOp = ctypes.c_void_p
            class SHFILEOPSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("hwnd", ctypes.c_void_p),
                    ("wFunc", ctypes.c_uint),
                    ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p),
                    ("fFlags", ctypes.c_ushort),
                    # fAnyOperationsAborted 在 Win32 中是 BOOL(int, 4 字节)，
                    # 若声明为 c_bool(1 字节) 会破坏后续字段偏移，
                    # 导致 SHFileOperationW 读到的结构体错位而失败。
                    ("fAnyOperationsAborted", ctypes.c_uint),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", ctypes.c_wchar_p),
                ]
            # pFrom 需要双 null 结尾
            path_double_null = path + '\0'
            op = SHFILEOPSTRUCT()
            op.hwnd = 0
            op.wFunc = 3  # FO_DELETE
            op.pFrom = path_double_null
            op.pTo = None
            op.fFlags = flags
            op.fAnyOperationsAborted = False
            op.hNameMappings = None
            op.lpszProgressTitle = None
            result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
            return result == 0
        except Exception:
            return False

    def _delete_source_files(self):
        """删除已成功压缩的源文件（优先移入回收站）。

        可删除列表要遍历处理历史并逐个探测磁盘，数据量大时会长时间占用主线程，
        导致整个窗口被 Windows 判定为“未响应”并卡死。因此把扫描放到后台线程，
        算完后再回主线程弹窗确认。
        """
        if self.is_processing:
            messagebox.showinfo(
                "提示", "压缩任务进行中，请等待完成后再删除源文件。",
                parent=self.root,
            )
            return
        if self._checking_deletable:
            return
        self._checking_deletable = True
        self.delete_btn.config(state=tk.DISABLED)
        self._log("[删除] 正在后台检查可删除的源文件，请稍候…")

        def bg_check():
            try:
                deletable = self._get_deletable_files()
                self.msg_queue.put(("deletable_ready", deletable))
            except Exception as e:
                self.msg_queue.put(("deletable_error", e))

        threading.Thread(target=bg_check, daemon=True).start()

    def _proceed_delete(self, deletable: list):
        """拿到可删除列表后，在主线程进行确认与实际删除"""
        if not deletable:
            messagebox.showinfo(
                "提示",
                "没有可删除的文件。\n\n只有压缩成功且输出文件存在的源文件才可删除。",
                parent=self.root,
            )
            return

        total_size = sum(vf.size for vf in deletable)
        # 显示前几个文件名作为预览
        preview_lines = []
        for i, vf in enumerate(deletable):
            if i < 8:
                preview_lines.append(f"  • {vf.path.name}  ({self._fmt_size(vf.size)})")
            elif i == 8:
                preview_lines.append(f"  ... 还有 {len(deletable) - 8} 个文件")
                break
        preview = "\n".join(preview_lines)

        confirm = messagebox.askyesno(
            "确认删除源文件",
            f"即将删除 {len(deletable)} 个源文件，共 {self._fmt_size(total_size)}。\n\n"
            f"{preview}\n\n"
            f"这些文件的压缩版本已存在，删除后源文件将移入回收站（可恢复）。\n"
            f"确定要继续吗？",
            parent=self.root,
        )
        if not confirm:
            return

        self._log(f"[删除] 开始删除 {len(deletable)} 个源文件...")

        # 获取或创建删除日志
        logger = LogManager.current_logger
        standalone_delete_path = None
        if logger is None:
            # 没有活跃的压缩会话，创建独立的删除日志
            delete_dir = LogManager.LOG_DIR / "删除日志"
            delete_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            standalone_delete_path = delete_dir / f"删除日志_{ts}.log"
            sep = "=" * 66
            del_fp = open(standalone_delete_path, "w", encoding="utf-8-sig")
            del_fp.write(f"{sep}\n视频压缩删除日志  会话: delete_{ts}\n{sep}\n")
            del_fp.write(f"删除时间   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            del_fp.write(f"待删除文件 : {len(deletable)} 个\n")
            del_fp.write(f"总大小     : {self._fmt_size(total_size)}\n")
            del_fp.write(f"\n{'=' * 66}\n\n")
            del_fp.flush()
        else:
            del_fp = None

        deleted = 0
        failed = 0
        for i, vf in enumerate(deletable):
            try:
                if sys.platform == "win32":
                    success = self._send_to_recycle_bin(str(vf.path))
                    if success:
                        deleted += 1
                        vf.status = "deleted"
                        self._log(f"  [回收站] {vf.path.name}")
                        # 写入删除日志
                        record = (
                            f"--- 文件 {i + 1}/{len(deletable)}  [已删除] ---\n"
                            f"  文件名    : {vf.path.name}\n"
                            f"  源路径    : {vf.path}\n"
                            f"  原始大小  : {self._fmt_size(vf.size)}  ({vf.size:,} 字节)\n"
                            f"  压缩文件  : {vf.output_path}\n"
                            f"  删除时间  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"  方式      : 移入回收站\n\n"
                        )
                        if logger:
                            logger.write_delete(record)
                        elif del_fp:
                            del_fp.write(record)
                            del_fp.flush()
                    else:
                        failed += 1
                        self._log(f"  [失败] {vf.path.name} — 移入回收站失败")
                else:
                    vf.path.unlink()
                    deleted += 1
                    vf.status = "deleted"
                    self._log(f"  [已删除] {vf.path.name}")
            except Exception as e:
                failed += 1
                self._log(f"  [失败] {vf.path.name} — {e}")

        # 写入删除汇总
        summary = (
            f"\n{'=' * 66}\n"
            f"删除汇总\n"
            f"{'=' * 66}\n"
            f"成功删除   : {deleted} 个\n"
            f"删除失败   : {failed} 个\n"
            f"共释放空间 : {self._fmt_size(sum(vf.size for vf in deletable if vf.status == 'deleted'))}\n"
            f"{'=' * 66}\n"
        )
        if logger:
            logger.write_delete(summary)
        elif del_fp:
            del_fp.write(summary)
            del_fp.write("\n[日志结束]\n")
            del_fp.close()
            del_fp = None
            self._log(f"[删除] 独立删除日志已保存: {standalone_delete_path}")

        self._refresh_tree()
        self._update_stats()
        self._log(f"[删除] 完成：成功 {deleted} 个，失败 {failed} 个")

        if failed > 0:
            messagebox.showwarning("部分失败",
                f"成功删除 {deleted} 个文件，{failed} 个失败。\n详见日志面板。",
                parent=self.root)
        else:
            messagebox.showinfo("完成",
                f"已成功将 {deleted} 个源文件移入回收站。\n"
                f"共释放 {self._fmt_size(total_size)} 空间。\n"
                f"如需恢复，可从回收站还原。",
                parent=self.root)

    @staticmethod
    def _get_status_text(status: str) -> str:
        """状态码转显示文本"""
        mapping = {
            "pending": "等待中",
            "processing": "处理中",
            "done": "已完成",
            "skipped": "已跳过",
            "error": "错误",
            "deleted": "已删除",
        }
        return mapping.get(status, status)

    @staticmethod
    def _fmt_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds <= 0:
            return "--:--"
        if seconds < 60:
            return f"0:{int(seconds):02d}"
        elif seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}:{s:02d}"
        else:
            h, remainder = divmod(int(seconds), 3600)
            m, s = divmod(remainder, 60)
            return f"{h}:{m:02d}:{s:02d}"

    def _show_ffmpeg_warning(self):
        """FFmpeg 未安装警告"""
        messagebox.showwarning("FFmpeg 未检测到",
            "未在系统 PATH 中找到 FFmpeg。\n\n"
            "本工具需要 FFmpeg 才能进行视频压缩。\n"
            "请访问 https://ffmpeg.org/download.html 下载并安装。\n\n"
            "安装后请重启本工具。")

    # ---- 配置持久化 ----

    def _save_config(self):
        """保存当前设置到配置文件"""
        enc_key = self.enc_label_to_key.get(self.encoder_var.get(), "libx265")
        config = {
            "encoder": enc_key,
            "crf": self.crf_var.get(),
            "preset": self.preset_var.get(),
            "output_subdir": self.subdir_var.get(),
            "max_resolution": self.scale_var.get(),
            "audio_bitrate": self.audio_br_var.get(),
            "custom_output_dir": self.custom_output_var.get().strip() if self.use_custom_output_var.get() else "",
            "last_source_dir": str(self.source_dir) if self.source_dir else "",
        }
        try:
            config_path = Path.home() / ".video_compressor" / CONFIG_FILE
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self._log("[设置] 配置已保存")
        except Exception as e:
            self._log(f"[设置] 保存失败: {e}")

    def _load_config(self):
        """从配置文件加载设置"""
        try:
            config_path = Path.home() / ".video_compressor" / CONFIG_FILE
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                # 编码器 (校验是否可用)
                enc_key = config.get("encoder", "libx265")
                if enc_key not in self.available_encoders:
                    enc_key = "libx265"
                    if "hevc_nvenc" in self.available_encoders:
                        enc_key = "hevc_nvenc"
                self.encoder_var.set(ENCODERS[enc_key]["label"])
                self._on_encoder_change()

                self.crf_var.set(config.get("crf", ENCODERS[enc_key]["default_q"]))
                self.crf_label.config(text=str(self.crf_var.get()))
                self.preset_var.set(config.get("preset", ENCODERS[enc_key]["default_preset"]))
                self.subdir_var.set(config.get("output_subdir", DEFAULT_OUTPUT_SUBDIR))
                self.scale_var.set(config.get("max_resolution", "原始分辨率"))
                self.audio_br_var.set(config.get("audio_bitrate", "128k"))

                # 自定义输出目录
                custom_dir = config.get("custom_output_dir", "")
                if custom_dir:
                    self.use_custom_output_var.set(True)
                    self.custom_output_var.set(custom_dir)
                    self.custom_output_entry.config(state="normal")
                    self.custom_output_btn.config(state="normal")

                last_dir = config.get("last_source_dir", "")
                if last_dir and Path(last_dir).exists():
                    self.source_dir = Path(last_dir)
                    self.folder_var.set(str(self.source_dir))

                self._log("[设置] 已加载上次的配置")
        except Exception:
            pass


# ============================================================
# 入口
# ============================================================

def main():
    root = tk.Tk()

    # Windows DPI 感知
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    # 设置图标
    icon_path = APP_DIR / "icon.ico"
    try:
        if icon_path.exists():
            root.iconbitmap(default=str(icon_path))
        else:
            root.iconbitmap(default="")
    except tk.TclError:
        pass

    app = VideoCompressorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
