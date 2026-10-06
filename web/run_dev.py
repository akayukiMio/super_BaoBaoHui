#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开发模式启动器：后台拉起后端(uvicorn)与前端(vite)，等待端口就绪后打开浏览器。

- 仅监听 127.0.0.1
- 幂等：若服务已在运行，则只打开浏览器
- 子进程以分离方式启动，日志写入 web/.run/*.log，PID 写入 web/.run/*.pid
用法：pythonw run_dev.py（由桌面快捷方式调用）
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE / "backend"
FRONTEND_DIR = HERE / "frontend"
RUN_DIR = HERE / ".run"

BACKEND_PORT = 8765
FRONTEND_PORT = 5173
URL = f"http://127.0.0.1:{FRONTEND_PORT}"

IS_WIN = sys.platform == "win32"
VENV_PY = BACKEND_DIR / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")

DETACH = 0x00000008 | 0x00000200 if IS_WIN else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_port(port: int, timeout: float = 60.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if port_open(port):
            return True
        time.sleep(0.5)
    return False


def spawn(cmd, cwd: Path, log_name: str, pid_name: str):
    RUN_DIR.mkdir(exist_ok=True)
    log = open(RUN_DIR / log_name, "ab")
    kwargs = dict(cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if IS_WIN:
        kwargs["creationflags"] = DETACH
    else:
        kwargs["start_new_session"] = True
    p = subprocess.Popen(cmd, **kwargs)
    (RUN_DIR / pid_name).write_text(str(p.pid), encoding="utf-8")
    return p


def start_backend():
    if port_open(BACKEND_PORT):
        return
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    spawn(
        [py, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
         "--port", str(BACKEND_PORT), "--reload"],
        BACKEND_DIR, "backend.log", "backend.pid",
    )


def start_frontend():
    if port_open(FRONTEND_PORT):
        return
    npm = "npm.cmd" if IS_WIN else "npm"
    spawn([npm, "run", "dev"], FRONTEND_DIR, "frontend.log", "frontend.pid")


def main():
    os.chdir(HERE)
    start_backend()
    start_frontend()
    ok = wait_port(FRONTEND_PORT, timeout=90) and wait_port(BACKEND_PORT, timeout=10)
    webbrowser.open(URL)
    if not ok:
        # 打开失败时给出提示日志位置
        (RUN_DIR / "run_dev.out").write_text(
            "服务未能及时就绪，请查看 web/.run/backend.log 与 frontend.log",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
