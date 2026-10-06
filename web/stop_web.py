#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""停止生产模式服务：结束监听 127.0.0.1:8765 的进程。"""
from __future__ import annotations

import subprocess
import sys

PORT = 8765
IS_WIN = sys.platform == "win32"


def main():
    if IS_WIN:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -LocalPort {PORT} -State Listen -ErrorAction SilentlyContinue "
             "| Select-Object -ExpandProperty OwningProcess -Unique"],
            capture_output=True, text=True,
        ).stdout
        for pid in out.split():
            if pid.isdigit():
                subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"已停止进程 pid={pid}")
    else:
        subprocess.run(["pkill", "-f", f"uvicorn.*{PORT}"])
        print("已尝试停止 uvicorn")
    print("完成。")


if __name__ == "__main__":
    main()
