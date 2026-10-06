#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局常量与配置（从桌面版 video_compressor.py 抽取复用）。

后端各模块统一从这里取常量，避免与桌面版产生逻辑漂移。
"""
from __future__ import annotations

from pathlib import Path

APP_TITLE = "视频批量压缩工具 by akayukimio"
APP_VERSION = "1.2.0"

# 后端所在目录 -> 项目根（web/backend/core/consts.py -> 上三级）
BACKEND_DIR = Path(__file__).resolve().parent.parent      # web/backend
PROJECT_ROOT = BACKEND_DIR.parent.parent                   # video_compressor/
# 与桌面版共用同一份 logs / history / config，保证行为一致
APP_DIR = PROJECT_ROOT

SUPPORTED_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m4v"
}

DEFAULT_CRF = 28
DEFAULT_PRESET = "medium"
DEFAULT_OUTPUT_SUBDIR = "compressed"
CONFIG_FILE = "compressor_config.json"
HISTORY_FILE = ".processing_history.json"

# 每个编码器的配置
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

SCALE_OPTIONS = {
    "原始分辨率": None,
    "4K (3840x2160)": "3840:-2",
    "1440p (2560x1440)": "2560:-2",
    "1080p (1920x1080)": "1920:-2",
    "720p (1280x720)": "1280:-2",
    "480p (854x480)": "854:-2",
}

# 高效编码：预检命中则默认跳过
ALREADY_COMPRESSED_CODECS = {"hevc", "h265", "av1", "vp9"}
