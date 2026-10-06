#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产模式启动器（供桌面快捷方式以 pythonw.exe 无控制台方式调用）。

做法：父进程以后台隐藏子进程方式拉起 uvicorn（输出写入 web/.run/backend.log，
使用 CREATE_NO_WINDOW 不弹任何命令行窗口），轮询端口就绪后用 os.startfile 打开浏览器。
- 幂等：若 8765 已在监听，则只打开浏览器。
- 若前端未构建（web/frontend/dist 不存在），首次自动执行一次 npm run build。
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
DIST = FRONTEND_DIR / "dist"
RUN_DIR = HERE / ".run"
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"

IS_WIN = os.name == "nt"
VENV_PY = BACKEND_DIR / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_browser():
    try:
        if IS_WIN:
            os.startfile(URL)
        else:
            webbrowser.open(URL)
    except Exception:
        try:
            webbrowser.open(URL)
        except Exception:
            pass


def ensure_build():
    if (DIST / "index.html").exists():
        return
    npm = "npm.cmd" if IS_WIN else "npm"
    subprocess.run([npm, "run", "build"], cwd=str(FRONTEND_DIR), check=False)


def start_server_detached():
    RUN_DIR.mkdir(exist_ok=True)
    log = open(RUN_DIR / "backend.log", "ab")
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    kwargs = dict(
        cwd=str(BACKEND_DIR), stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    if IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # 不弹控制台窗口
    else:
        kwargs["start_new_session"] = True
    p = subprocess.Popen(
        [py, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        **kwargs,
    )
    (RUN_DIR / "backend.pid").write_text(str(p.pid), encoding="utf-8")


def wait_port(timeout: float = 90.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if port_open(PORT):
            return True
        time.sleep(0.4)
    return False


def main():
    if port_open(PORT):
        open_browser()
        return
    ensure_build()
    start_server_detached()
    wait_port()
    open_browser()  # 无论是否探测到就绪都尝试打开，失败可查 web/.run/backend.log


if __name__ == "__main__":
    main()
