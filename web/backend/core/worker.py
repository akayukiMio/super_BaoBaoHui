#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""后台压缩处理线程（复用桌面版逻辑，把消息队列换成 emit 回调）。"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from .consts import ALREADY_COMPRESSED_CODECS, ENCODERS
from .ffmpeg_helper import FFmpegHelper
from .history import load_processing_history, save_processing_history
from .logger import LogManager
from .models import CompressionSettings, VideoFile

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

Emit = Callable[[str, object], None]


class CompressionWorker:
    def __init__(self, emit: Emit):
        self.emit = emit
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._thread: Optional[threading.Thread] = None
        self.settings = CompressionSettings()
        self.files: List[VideoFile] = []
        self.source_dir: Optional[Path] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, files, settings, source_dir=None):
        self.files = files
        self.settings = settings
        self.source_dir = source_dir
        self._stop_event.clear()
        self._pause_event.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()
        self._send("log", "[暂停] 处理已暂停")

    def resume(self):
        self._pause_event.set()
        self._send("log", "[恢复] 处理已继续")

    def _send(self, msg_type, data=None):
        try:
            self.emit(msg_type, data)
        except Exception:
            pass

    def _run(self):
        total = len(self.files)
        done_count = skipped_count = error_count = 0
        total_original_size = total_compressed_size = 0
        start_time = time.time()
        total_bytes_all = sum(vf.size for vf in self.files)
        completed_bytes = 0

        logger = LogManager()
        enc_cfg = ENCODERS.get(self.settings.encoder, ENCODERS["libx265"])
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
            if self._stop_event.is_set():
                self._send("log", "[中止] 用户中止了处理")
                break
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            self._send("current_file", (idx + 1, total, vf.path.name))

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

            result = ""
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
                    logger.write_result(
                        f"--- 文件 {idx + 1}/{total}  [完成] ---\n"
                        f"  文件名    : {vf.path.name}\n"
                        f"  原始大小  : {self._fmt_size(vf.size)}  ({vf.size:,} 字节)\n"
                        f"  压缩后    : {self._fmt_size(vf.output_size)}  ({vf.output_size:,} 字节)\n"
                        f"  节省空间  : {self._fmt_size(vf.size - vf.output_size)}  (压缩率 {ratio:.1f}%)\n"
                        f"  编码耗时  : {self._fmt_time(vf.encode_seconds)}\n\n"
                    )
                    history.add(str(vf.path))
                    save_processing_history(history)
                elif result == "skipped":
                    skipped_count += 1
                    if vf.error_msg:
                        self._send("log", f"[跳过] {vf.path.name}  {vf.error_msg}")
                        logger.write_result(
                            f"--- 文件 {idx + 1}/{total}  [跳过] ---\n"
                            f"  文件名    : {vf.path.name}\n  原因      : {vf.error_msg}\n\n"
                        )
                        history.add(str(vf.path))
                        save_processing_history(history)
                    else:
                        self._send("log", f"[跳过] {vf.path.name}  (已存在压缩版本)")
                        logger.write_result(
                            f"--- 文件 {idx + 1}/{total}  [跳过] ---\n"
                            f"  文件名    : {vf.path.name}\n  原因      : 输出文件已存在，未重复压缩\n\n"
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

            if result in ("done", "skipped"):
                completed_bytes += vf.size
            elapsed = time.time() - start_time
            if elapsed > 3 and completed_bytes > 0:
                speed_bps = completed_bytes / elapsed
                remaining_bytes = total_bytes_all - completed_bytes
                eta_sec = remaining_bytes / speed_bps if speed_bps > 0 else 0
                self._send("speed_update", (speed_bps / (1024 * 1024), eta_sec, elapsed))

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
                f"原始总大小 : {self._fmt_size(total_original_size)}",
                f"压缩后大小 : {self._fmt_size(total_compressed_size)}",
                f"共节省空间 : {self._fmt_size(saved)}  (压缩率 {ratio:.1f}%)",
            ])
        logger.finish_session(summary_lines)
        self._send("finished", None)

    def _log_error(self, logger, vf, idx, total):
        lines = [
            f"--- 文件 {idx + 1}/{total}  [错误] ---",
            f"  出错时间 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  文件路径 : {vf.path}",
            f"  原因     : {vf.error_msg}",
        ]
        if vf.output_path:
            lines.append(f"  输出文件 : {vf.output_path}")
        if vf.error_detail:
            lines.append("  FFmpeg 输出片段:")
            for l in vf.error_detail.splitlines():
                lines.append(f"    {l}")
        lines.append("")
        logger.write_error("\n".join(lines))

    def _process_file(self, vf: VideoFile) -> str:
        vf.status = "processing"
        self._send("file_status_update", vf.to_dict())

        if self.settings.custom_output_dir and self.source_dir:
            rel_path = vf.path.parent.relative_to(self.source_dir)
            output_dir = Path(self.settings.custom_output_dir) / rel_path
        else:
            output_dir = vf.path.parent / self.settings.output_subdir
        output_dir.mkdir(parents=True, exist_ok=True)

        output_name = vf.path.stem + ".mp4"
        output_path = output_dir / output_name

        if output_path.exists() and output_path.stat().st_size > 0 and not self.settings.overwrite:
            vf.status = "skipped"
            vf.output_path = output_path
            vf.output_size = output_path.stat().st_size
            return "skipped"

        if not self.settings.force_compress and vf.codec.lower() in ALREADY_COMPRESSED_CODECS:
            vf.status = "skipped"
            vf.error_msg = f"源文件已是 {vf.codec.upper()} 编码，无需重新压缩"
            return "skipped"

        duration = FFmpegHelper.get_duration_from_probe(vf.path)
        vf.duration = duration

        cmd = FFmpegHelper.build_compress_cmd(
            vf.path, output_path, self.settings, self.settings.overwrite,
            vf.width, vf.height
        )
        self._send("log", f"[编码] {vf.path.name}  (时长: {self._fmt_time(duration)})")

        encode_start = time.time()
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )

        stderr_tail = deque(maxlen=15)
        last_progress_time = time.time()
        for line in process.stderr:
            stderr_tail.append(line.rstrip())
            if self._stop_event.is_set():
                process.kill()
                vf.status = "error"
                vf.error_msg = "用户中止"
                vf.error_detail = "\n".join(stderr_tail)
                if output_path.exists():
                    try:
                        output_path.unlink()
                    except OSError:
                        pass
                return "error"

            self._pause_event.wait()

            if "time=" in line:
                try:
                    time_str = line.split("time=")[1].split()[0]
                    parts = time_str.split(":")
                    current_sec = (float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]))
                    if duration > 0:
                        progress = min(current_sec / duration * 100, 99.9)
                        vf.progress = progress
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
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}分{s}秒"
        else:
            h, remainder = divmod(int(seconds), 3600)
            m, s = divmod(remainder, 60)
            return f"{h}时{m}分{s}秒"
