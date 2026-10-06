#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""停止 run_dev.py 启动的前后端服务（按 PID 文件递归终止进程树）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN_DIR = HERE / ".run"
IS_WIN = sys.platform == "win32"


def kill_pidfile(name: str):
    pidfile = RUN_DIR / name
    if not pidfile.exists():
        return
    pid = pidfile.read_text(encoding="utf-8").strip()
    if not pid.isdigit():
        pidfile.unlink(missing_ok=True)
        return
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["kill", "--", pid],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pidfile.unlink(missing_ok=True)
    print(f"已停止 {name} (pid={pid})")


if __name__ == "__main__":
    kill_pidfile("frontend.pid")
    kill_pidfile("backend.pid")
    print("完成。")
