#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局任务管理器：持有 worker 与状态，并把进度事件广播给 WebSocket 订阅者。

worker 在后台线程运行，通过 emit() 回调投递事件；emit 用
loop.call_soon_threadsafe 把事件安全地扇出到每个 asyncio.Queue。
"""
from __future__ import annotations

import asyncio
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .ffmpeg_helper import FFmpegHelper
from .models import CompressionSettings, VideoFile
from .worker import CompressionWorker


class TaskManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: set = set()

        self.files: List[VideoFile] = []
        self._cache: Dict[str, VideoFile] = {}   # normcase(path) -> VideoFile（复用扫描结果）
        self.settings = CompressionSettings()
        self.source_dir: Optional[Path] = None
        self.worker: Optional[CompressionWorker] = None

        self.is_processing = False
        self.is_paused = False

        self.logs: deque = deque(maxlen=800)
        # 进度快照
        self.overall = {"current": 0, "total": 0}
        self.file_progress = 0.0
        self.current_file = ""
        self.speed_text = ""

    # ---------- 事件循环 / 订阅 ----------
    def attach_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    def _broadcast(self, event: dict):
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "data": {
                "is_processing": self.is_processing,
                "is_paused": self.is_paused,
                "overall": self.overall,
                "file_progress": self.file_progress,
                "current_file": self.current_file,
                "speed_text": self.speed_text,
                "logs": list(self.logs)[-200:],
            },
        }

    # ---------- worker -> 广播 ----------
    def emit(self, msg_type: str, data):
        # 更新快照
        if msg_type == "log":
            ts = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] {data}")
        elif msg_type == "overall_progress":
            self.overall = {"current": data[0], "total": data[1]}
        elif msg_type == "file_progress":
            self.file_progress = data
        elif msg_type == "current_file":
            self.current_file = data[2]
        elif msg_type == "speed_update":
            speed_mbs, eta_sec, elapsed = data
            speed_str = f"{speed_mbs:.1f} MB/s" if speed_mbs >= 1 else f"{speed_mbs * 1024:.0f} KB/s"
            self.speed_text = f"⚡ {speed_str}  |  已用: {self._fmt_time(elapsed)}  |  预计剩余: {self._fmt_time(eta_sec)}"
        elif msg_type == "finished":
            self.is_processing = False
            self.is_paused = False

        event = {"type": msg_type, "data": list(data) if isinstance(data, tuple) else data}
        if self.loop is not None:
            try:
                self.loop.call_soon_threadsafe(self._broadcast, event)
            except RuntimeError:
                pass  # 事件循环已关闭

    # ---------- 任务控制 ----------
    def _ensure_videofile(self, path_str: str) -> VideoFile:
        key = str(Path(path_str)).lower()
        vf = self._cache.get(key)
        if vf is not None:
            return vf
        fp = Path(path_str)
        try:
            size = fp.stat().st_size
        except OSError:
            size = 0
        vf = VideoFile(path=fp, size=size, status="pending", checked=True)
        info = FFmpegHelper.probe_video(fp)
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
        self._cache[key] = vf
        return vf

    def cache_files(self, files: List[VideoFile]):
        for vf in files:
            self._cache[str(vf.path).lower()] = vf

    def start(self, paths: List[str], settings_dict: dict, source_dir: Optional[str]) -> bool:
        if self.worker and self.worker.is_running:
            return False
        files = [self._ensure_videofile(p) for p in paths]
        for vf in files:
            vf.status = "pending"
            vf.progress = 0.0
            vf.error_msg = ""
        self.files = files
        self.settings = CompressionSettings.from_dict(settings_dict)
        self.source_dir = Path(source_dir) if source_dir else None
        self.is_processing = True
        self.is_paused = False
        self.overall = {"current": 0, "total": len(files)}
        self.file_progress = 0.0
        self.worker = CompressionWorker(self.emit)
        self.worker.start(files, self.settings, self.source_dir)
        return True

    def pause(self):
        if self.worker and self.is_processing:
            self.is_paused = True
            self.worker.pause()

    def resume(self):
        if self.worker and self.is_processing:
            self.is_paused = False
            self.worker.resume()

    def stop(self):
        if self.worker:
            self.worker.stop()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}秒"
        elif seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}分{s}秒"
        else:
            h, remainder = divmod(int(seconds), 3600)
            m, s = divmod(remainder, 60)
            return f"{h}时{m}分{s}秒"


# 全局单例
task_manager = TaskManager()
