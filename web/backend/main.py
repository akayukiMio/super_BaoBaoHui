#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频批量压缩工具 - 本地 Web 后端 (FastAPI)。

仅监听 127.0.0.1，避免把磁盘/删除能力暴露到局域网。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import fsbrowse
from core.consts import (
    APP_TITLE, APP_VERSION, ENCODERS, SCALE_OPTIONS, SUPPORTED_EXTENSIONS,
)
from core.ffmpeg_helper import FFmpegHelper, detect_available_encoders
from core.history import load_config, save_config
from core.recycle import send_many_to_recycle_bin, send_to_recycle_bin
from core.task_manager import task_manager

app = FastAPI(title=APP_TITLE, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:4173", "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    task_manager.attach_loop(asyncio.get_running_loop())


# ---------------- 请求体模型 ----------------

class ScanReq(BaseModel):
    path: str
    recursive: bool = True
    output_subdir: str = "compressed"


class SelectReq(BaseModel):
    paths: List[str]


class StartReq(BaseModel):
    paths: List[str]
    settings: dict
    source_dir: Optional[str] = None


class DeletableReq(BaseModel):
    subdir: str = "compressed"
    custom_dir: str = ""
    source_dir: Optional[str] = None


class DeleteReq(BaseModel):
    paths: List[str]


class ConfigReq(BaseModel):
    config: dict


# ---------------- 基础信息 ----------------

@app.get("/api/health")
async def health():
    return {"ok": True, "app": APP_TITLE, "version": APP_VERSION}


@app.get("/api/ffmpeg")
async def ffmpeg():
    return {"available": await asyncio.to_thread(FFmpegHelper.check_ffmpeg)}


@app.get("/api/encoders")
async def encoders():
    available = await asyncio.to_thread(detect_available_encoders)
    enc_meta = {
        k: {
            "label": ENCODERS[k]["label"],
            "codec": ENCODERS[k]["codec"],
            "quality_param": ENCODERS[k]["quality_param"],
            "default_q": ENCODERS[k]["default_q"],
            "default_preset": ENCODERS[k]["default_preset"],
            "presets": ENCODERS[k]["presets"],
        }
        for k in available
    }
    return {
        "available": available,
        "encoders": enc_meta,
        "scale_options": list(SCALE_OPTIONS.keys()),
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


@app.get("/api/config")
async def get_config():
    return load_config()


@app.post("/api/config")
async def post_config(req: ConfigReq):
    return {"ok": save_config(req.config)}


# ---------------- 目录浏览 / 扫描 ----------------

@app.get("/api/browse")
async def browse(path: Optional[str] = None):
    return await asyncio.to_thread(fsbrowse.list_dir, path)


@app.post("/api/scan")
async def scan(req: ScanReq):
    files = await asyncio.to_thread(
        fsbrowse.scan_folder, req.path, req.recursive, req.output_subdir
    )
    return {"files": files}


@app.post("/api/select")
async def select(req: SelectReq):
    files = await asyncio.to_thread(fsbrowse.build_file_list, req.paths)
    return {"files": files}


# ---------------- 任务控制 ----------------

@app.post("/api/start")
async def start(req: StartReq):
    ok = task_manager.start(req.paths, req.settings, req.source_dir)
    return {"ok": ok, "reason": "" if ok else "已有任务在运行"}


@app.post("/api/pause")
async def pause():
    task_manager.pause()
    return {"ok": True}


@app.post("/api/resume")
async def resume():
    task_manager.resume()
    return {"ok": True}


@app.post("/api/stop")
async def stop():
    task_manager.stop()
    return {"ok": True}


@app.get("/api/state")
async def state():
    return {
        "is_processing": task_manager.is_processing,
        "is_paused": task_manager.is_paused,
        "overall": task_manager.overall,
        "file_progress": task_manager.file_progress,
        "current_file": task_manager.current_file,
        "speed_text": task_manager.speed_text,
    }


# ---------------- 删除已压缩源文件 ----------------

@app.post("/api/deletable")
async def deletable(req: DeletableReq):
    src_dir = Path(req.source_dir) if req.source_dir else None
    items = await asyncio.to_thread(
        fsbrowse.compute_deletable, task_manager.files, req.subdir, req.custom_dir, src_dir
    )
    return {"items": items}


@app.post("/api/delete")
async def delete(req: DeleteReq):
    paths = req.paths
    if not paths:
        return {"deleted": 0, "failed": 0}
    # 优先批量移入回收站（一次调用），失败再逐个兜底
    batch_ok = await asyncio.to_thread(send_many_to_recycle_bin, paths)
    if batch_ok:
        return {"deleted": len(paths), "failed": 0}
    deleted = failed = 0
    for p in paths:
        ok = await asyncio.to_thread(send_to_recycle_bin, p)
        if ok:
            deleted += 1
        else:
            failed += 1
    return {"deleted": deleted, "failed": failed}


# ---------------- WebSocket 进度流 ----------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q = task_manager.subscribe()
    try:
        await ws.send_json(task_manager.snapshot())
    except Exception:
        pass

    async def pump():
        while True:
            event = await q.get()
            await ws.send_json(event)

    async def recv():
        while True:
            await ws.receive_text()  # 客户端心跳；断开时抛异常

    pump_task = asyncio.create_task(pump())
    try:
        await recv()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        pump_task.cancel()
        task_manager.unsubscribe(q)
