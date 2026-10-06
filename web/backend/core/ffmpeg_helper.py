#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFmpeg 交互层（复用桌面版逻辑，无 GUI 依赖）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .consts import ENCODERS, SCALE_OPTIONS

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class FFmpegHelper:
    """封装 FFmpeg 调用"""

    @staticmethod
    def check_ffmpeg() -> bool:
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def probe_video(filepath: Path) -> dict:
        try:
            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(filepath),
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception:
            pass
        return {}

    @staticmethod
    def get_duration_from_probe(filepath: Path) -> float:
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
        settings,
        overwrite: bool = False,
        video_width: int = 0,
        video_height: int = 0,
    ) -> list:
        """构建 FFmpeg 压缩命令（自动适配 CPU/GPU 编码器）"""
        cmd = ["ffmpeg"]
        cmd.extend(["-y"] if overwrite else ["-n"])
        cmd.extend(["-i", str(input_path)])

        enc_cfg = ENCODERS.get(settings.encoder, ENCODERS["libx265"])
        cmd.extend(["-c:v", enc_cfg["codec"]])

        if enc_cfg["codec"] == "libx265":
            cmd.extend(["-crf", str(settings.crf)])
            cmd.extend(["-preset", settings.preset])
            cmd.extend(["-pix_fmt", "yuv420p"])
        else:
            cmd.extend(["-preset", settings.preset])
            cmd.extend(["-rc", "vbr"])
            cmd.extend(["-cq", str(settings.crf)])
            cmd.extend(["-b:v", "0"])
            cmd.extend(["-pix_fmt", "yuv420p"])

        # 分辨率缩放（智能处理横版/竖版视频）
        scale_label = settings.max_resolution
        if scale_label != "原始分辨率" and scale_label in SCALE_OPTIONS:
            scale_val = SCALE_OPTIONS[scale_label]
            if scale_val and video_width > 0 and video_height > 0:
                target_width = FFmpegHelper._parse_scale_target(scale_val)
                if target_width > 0 and video_width >= video_height:
                    cmd.extend(["-vf", f"scale='min(iw\\,{target_width})':'-2'"])

        cmd.extend(["-c:a", "aac"])
        cmd.extend(["-b:a", settings.audio_bitrate])
        cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(output_path))
        return cmd

    @staticmethod
    def _parse_scale_target(scale_val: str) -> int:
        try:
            return int(scale_val.split(":")[0])
        except (ValueError, IndexError):
            return 0


def detect_available_encoders() -> list:
    """检测 FFmpeg 中实际可用的编码器，返回编码器 key 列表"""
    available = []
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
            creationflags=_NO_WINDOW,
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
