#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件系统浏览、扫描、可删除文件计算。

浏览器无法直接拿到本地绝对路径，因此目录浏览/扫描全部由后端执行并返回 JSON。
可删除计算沿用桌面版修复后的“精确路径优先”策略，避免同名误匹配。
"""
from __future__ import annotations

import os
import string
from pathlib import Path
from typing import List, Optional

from .consts import DEFAULT_OUTPUT_SUBDIR, SUPPORTED_EXTENSIONS
from .ffmpeg_helper import FFmpegHelper
from .history import load_processing_history
from .models import VideoFile


# ---------------- 目录浏览 ----------------

def list_drives() -> List[dict]:
    drives = []
    if os.name == "nt":
        for c in string.ascii_uppercase:
            p = f"{c}:\\"
            try:
                if os.path.exists(p):
                    drives.append({"name": f"{c}:", "path": p})
            except OSError:
                pass
    else:
        drives.append({"name": "/", "path": "/"})
    return drives


def list_dir(path: Optional[str]) -> dict:
    """返回某目录下的子文件夹与视频文件，供前端文件浏览器使用。"""
    result = {"path": "", "parent": None, "dirs": [], "files": [], "error": ""}
    target = Path(path) if path else None

    if target is None:
        result["path"] = ""
        result["dirs"] = list_drives()
        return result

    try:
        target = target.resolve()
    except OSError as e:
        result["error"] = str(e)
        return result

    result["path"] = str(target)
    result["parent"] = str(target.parent) if str(target.parent) != str(target) else None

    dirs, files = [], []
    try:
        for child in target.iterdir():
            try:
                if child.is_dir():
                    dirs.append({"name": child.name, "path": str(child)})
                elif child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    files.append({
                        "name": child.name,
                        "path": str(child),
                        "size": child.stat().st_size,
                    })
            except OSError:
                continue
    except OSError as e:
        result["error"] = str(e)

    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    result["dirs"] = dirs
    result["files"] = files
    return result


# ---------------- 扫描 / 探测 ----------------

def _probe_to_videofile(filepath: Path, history: set) -> Optional[VideoFile]:
    try:
        size = filepath.stat().st_size
    except OSError:
        return None
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
    return vf


def scan_folder(source_dir: str, recursive: bool, output_subdir: str) -> List[dict]:
    base = Path(source_dir)
    if not base.exists():
        return []
    history = load_processing_history()
    collected = []
    if recursive:
        for ext in SUPPORTED_EXTENSIONS:
            for filepath in base.rglob(f"*{ext}"):
                if output_subdir in filepath.relative_to(base).parts:
                    continue
                collected.append(filepath)
    else:
        for ext in SUPPORTED_EXTENSIONS:
            for filepath in base.glob(f"*{ext}"):
                collected.append(filepath)

    files = []
    for filepath in collected:
        vf = _probe_to_videofile(filepath, history)
        if vf:
            files.append(vf)
    files.sort(key=lambda v: v.path.name.lower())
    return [v.to_dict() for v in files]


def build_file_list(paths: List[str]) -> List[dict]:
    history = load_processing_history()
    files = []
    for p in paths:
        vf = _probe_to_videofile(Path(p), history)
        if vf:
            files.append(vf)
    files.sort(key=lambda v: v.path.name.lower())
    return [v.to_dict() for v in files]


# ---------------- 可删除文件计算 ----------------

def build_output_index(custom_dir: str) -> dict:
    index = {}
    try:
        for root_dir, _dirs, files in os.walk(custom_dir):
            for fn in files:
                index.setdefault(fn, []).append(Path(root_dir) / fn)
    except OSError:
        pass
    return index


def _valid(p: Path) -> bool:
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def find_output_for_source(
    source_path: Path,
    subdir: str,
    custom_dir: str,
    source_dir: Optional[Path],
    custom_index: Optional[dict] = None,
) -> Optional[Path]:
    output_name = source_path.stem + ".mp4"

    # 1) 默认位置：源目录 / 输出子文件夹 / 同名.mp4（精确、唯一）
    default_output = source_path.parent / subdir / output_name
    if _valid(default_output):
        return default_output

    # 2) 自定义输出目录：镜像源文件夹结构（精确、唯一）
    if custom_dir and source_dir:
        custom_base = Path(custom_dir)
        try:
            rel_dir = source_path.parent.relative_to(source_dir)
            custom_output = custom_base / rel_dir / output_name
            if _valid(custom_output):
                return custom_output
        except ValueError:
            pass
        return None  # 已知根目录：镜像即唯一答案，不做易误匹配的全局搜索

    # 3) 兜底：仅在完全不知道 source_dir 时，按文件名在输出目录里查
    if custom_dir:
        if custom_index is None:
            custom_index = build_output_index(custom_dir)
        for cand in custom_index.get(output_name, []):
            if _valid(cand):
                return cand
    return None


def compute_deletable(
    video_files: List[VideoFile],
    subdir: str,
    custom_dir: str,
    source_dir: Optional[Path],
) -> List[dict]:
    deletable = []
    seen = set()

    # 第一类：当前会话压缩成功且已记录 output_path 的文件
    for vf in video_files:
        if vf.status != "done" or not vf.output_path:
            continue
        key = os.path.normcase(str(vf.path))
        if key in seen:
            continue
        if _valid(vf.output_path):
            deletable.append({
                "path": str(vf.path), "name": vf.path.name,
                "size": vf.size, "output_path": str(vf.output_path),
            })
            seen.add(key)

    # 第二类：处理历史中的文件
    history = load_processing_history()
    custom_index = build_output_index(custom_dir) if custom_dir else None
    for path_str in history:
        key = os.path.normcase(path_str)
        if key in seen:
            continue
        source_path = Path(path_str)
        if not source_path.exists():
            continue
        out = find_output_for_source(source_path, subdir, custom_dir, source_dir, custom_index)
        if out and _valid(out):
            try:
                size = source_path.stat().st_size
            except OSError:
                continue
            deletable.append({
                "path": str(source_path), "name": source_path.name,
                "size": size, "output_path": str(out),
            })
            seen.add(key)
    return deletable
