#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据结构：视频文件与压缩设置（可 JSON 序列化，供前端消费）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .consts import DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_OUTPUT_SUBDIR


@dataclass
class VideoFile:
    """表示一个待处理的视频文件"""
    path: Path
    size: int = 0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = ""
    status: str = "pending"  # pending, processing, done, skipped, moved, error, deleted
    output_path: Optional[Path] = None
    output_size: int = 0
    error_msg: str = ""
    error_detail: str = ""
    encode_seconds: float = 0.0
    progress: float = 0.0
    checked: bool = False
    source_action: str = ""          # "" | "deleted"（删源）| "moved"（原片归档）
    archive_path: Optional[Path] = None

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.path.name,
            "size": self.size,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "codec": self.codec,
            "status": self.status,
            "output_path": str(self.output_path) if self.output_path else None,
            "output_size": self.output_size,
            "error_msg": self.error_msg,
            "encode_seconds": self.encode_seconds,
            "progress": round(self.progress, 1),
            "checked": self.checked,
            "source_action": self.source_action,
            "archive_path": str(self.archive_path) if self.archive_path else None,
        }


@dataclass
class CompressionSettings:
    """压缩设置"""
    encoder: str = "libx265"
    crf: int = DEFAULT_CRF
    preset: str = DEFAULT_PRESET
    output_subdir: str = DEFAULT_OUTPUT_SUBDIR
    scale: Optional[str] = None
    audio_bitrate: str = "128k"
    overwrite: bool = False
    max_resolution: str = "原始分辨率"
    custom_output_dir: str = ""
    force_compress: bool = False
    # 工作流自动化（只有交接任务默认开启，手动会话保持原行为）
    auto_delete_source: bool = False    # 压缩成功且产物校验通过 -> 源文件进回收站
    auto_archive_source: bool = False   # 没压动/无需压缩 -> 把源文件搬到存储目录（平铺）

    @classmethod
    def from_dict(cls, d: dict) -> "CompressionSettings":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (d or {}).items() if k in known})
