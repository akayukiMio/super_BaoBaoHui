#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产模式启动器：单进程运行（uvicorn 直接托管已构建的前端），打开浏览器。

用 pythonw.exe 运行则完全没有命令行窗口；只有一个后台 python 进程。
若前端尚未构建（web/frontend/dist 不存在），首次会自动执行一次 npm run build。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE / "backend"
FRONTEND_DIR = HERE / "frontend"
DIST = FRONTEND_DIR / "dist"
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"

# venv 的无控制台解释器（Windows 用 pythonw.exe）
if os.name == "nt":
    VENV_PYW = BACKEND_DIR / ".venv" / "Scripts" / "pythonw.exe"
else:
    VENV_PYW = BACKEND_DIR / ".venv" / "bin" / "python"


def deps_missing() -> bool:
    try:
        import uvicorn  # noqa: F401
        import fastapi  # noqa: F401
        return False
    except ImportError:
        return True


def ensure_build():
    if (DIST / "index.html").exists():
        return
    npm = "npm.cmd" if os.name == "nt" else "npm"
    subprocess.run([npm, "run", "build"], cwd=str(FRONTEND_DIR), check=False)


def open_browser_later():
    time.sleep(1.8)
    try:
        webbrowser.open(URL)
    except Exception:
        pass


def main():
    # 依赖不在当前解释器里（例如用系统 pythonw 启动）→ 用 venv 的 pythonw 重启，保持无窗口
    if deps_missing() and VENV_PYW.exists():
        os.execv(str(VENV_PYW), [str(VENV_PYW), str(Path(__file__).resolve())])
        return

    ensure_build()
    os.chdir(BACKEND_DIR)
    sys.path.insert(0, str(BACKEND_DIR))

    threading.Thread(target=open_browser_later, daemon=True).start()
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
