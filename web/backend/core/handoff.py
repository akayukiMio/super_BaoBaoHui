#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交接队列：给外部工作流（如 IwaraTimeSaver）投递“这个文件压一下”的入口。

设计要点：
- 队列持久化到 handoff_queue.json，进程重启后未完成的 job 会重新排队；
- 单 worker：只有 task_manager 空闲时才取下一个 job；
- 每个 job 跑完把逐文件结果（状态/产物/删源/搬源）写回队列，外部可轮询；
- 交接任务默认开启 auto_delete_source / auto_archive_source，手动会话行为不变。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import List, Optional

from .consts import APP_DIR
from .history import load_config

QUEUE_FILE = APP_DIR / "handoff_queue.json"
_SETTING_KEYS = (
    "encoder", "crf", "preset", "output_subdir", "scale", "audio_bitrate",
    "overwrite", "max_resolution", "custom_output_dir", "force_compress",
)


def handoff_settings(override: Optional[dict] = None) -> dict:
    """用压缩器自己保存的配置构造 settings；交接任务固定开启自动清理/归档。"""
    cfg = load_config() or {}
    s = {k: cfg.get(k) for k in _SETTING_KEYS if k in cfg}
    s["auto_delete_source"] = True
    s["auto_archive_source"] = True
    if override:
        for k, v in override.items():
            if k in _SETTING_KEYS or k in ("auto_delete_source", "auto_archive_source"):
                s[k] = v
    return s


class HandoffQueue:
    def __init__(self, path: Path = QUEUE_FILE):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.jobs: List[dict] = []
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.jobs = [j for j in data if isinstance(j, dict) and j.get("job_id")]
        except Exception:
            self.jobs = []

    def _save(self):
        try:
            tmp = str(self.path) + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.jobs, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # ---------- 查询 ----------
    def snapshot(self) -> List[dict]:
        with self._lock:
            # 计算排队位置（运行中的 position=0）
            queued = [j for j in self.jobs if j.get("state") == "queued"]
            pos = {j["job_id"]: i + 1 for i, j in enumerate(queued)}
            out = []
            for j in self.jobs:
                item = dict(j)
                item["position"] = pos.get(j["job_id"], 0)
                out.append(item)
            return out

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            for j in self.jobs:
                if j["job_id"] == job_id:
                    return dict(j)
            return None

    # ---------- 入队 ----------
    def enqueue(self, job: dict) -> tuple[bool, str, int]:
        with self._lock:
            active = [j for j in self.jobs if j.get("state") in ("queued", "running")]
            for j in active:
                if j["job_id"] == job["job_id"]:
                    return False, "duplicate_active_job", 0
            paths = set(job.get("paths") or [])
            for j in active:
                if paths & set(j.get("paths") or []):
                    return False, "duplicate_active_path", 0
            # 只保留最近 200 条已完成记录，避免文件无限增长
            done = [j for j in self.jobs if j.get("state") not in ("queued", "running")]
            if len(done) > 200:
                done = done[-200:]
                self.jobs = active + done
            item = {
                "job_id": job["job_id"],
                "paths": list(job.get("paths") or []),
                "source_dir": job.get("source_dir") or "",
                "size": int(job.get("size") or 0),
                "state": "queued",
                "enqueued_at": time.time(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": "",
                "settings_override": job.get("settings_override") or None,
            }
            self.jobs.append(item)
            self._save()
            queued = [j for j in self.jobs if j.get("state") == "queued"]
            return True, "", len(queued)

    # ---------- 状态流转 ----------
    def claim_next(self) -> Optional[dict]:
        with self._lock:
            for j in self.jobs:
                if j.get("state") == "queued":
                    j["state"] = "running"
                    j["started_at"] = time.time()
                    self._save()
                    return dict(j)
            return None

    def requeue(self, job_id: str):
        with self._lock:
            for j in self.jobs:
                if j["job_id"] == job_id and j.get("state") == "running":
                    j["state"] = "queued"
                    j["started_at"] = None
                    self._save()
                    return

    def finish(self, job_id: str, state: str, result: Optional[list] = None, error: str = ""):
        with self._lock:
            for j in self.jobs:
                if j["job_id"] == job_id:
                    j["state"] = state
                    j["result"] = result
                    j["error"] = error
                    j["finished_at"] = time.time()
                    self._save()
                    return

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            for j in self.jobs:
                if j["job_id"] == job_id and j.get("state") == "queued":
                    j["state"] = "canceled"
                    j["finished_at"] = time.time()
                    self._save()
                    return True
            return False


class HandoffRunner(threading.Thread):
    """单线程消费者：task_manager 空闲时取 job 并启动压缩。"""

    def __init__(self, queue: HandoffQueue, task_manager):
        super().__init__(daemon=True, name="handoff-runner")
        self.queue = queue
        self.tm = task_manager
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                if self.tm.is_processing:
                    time.sleep(0.5)
                    continue
                job = self.queue.claim_next()
                if not job:
                    time.sleep(1.0)
                    continue
                self._run_job(job)
            except Exception:
                time.sleep(1.0)

    def _run_job(self, job: dict):
        settings = handoff_settings(job.get("settings_override"))
        ok = self.tm.start(job["paths"], settings, job.get("source_dir") or None)
        if not ok:
            # 手动会话正在跑，稍后重试
            self.queue.requeue(job["job_id"])
            time.sleep(1.0)
            return
        while self.tm.is_processing and not self._stop.is_set():
            time.sleep(0.5)
        results = []
        try:
            results = [vf.to_dict() for vf in self.tm.files]
        except Exception:
            results = []
        self.queue.finish(job["job_id"], "done", results, "")


# 全局单例（由 main.py 在 startup 时接线）
queue = HandoffQueue()
runner: Optional[HandoffRunner] = None
