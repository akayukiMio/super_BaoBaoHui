#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建桌面快捷方式：双击用 pythonw 静默拉起 run_web.py 并打开浏览器。

- 所有路径由本文件位置自动推导，不再硬编码绝对路径（换机器/换目录也能用）。
- 通过 PowerShell -EncodedCommand（UTF-16LE）传脚本，规避 Windows PowerShell
  按 ANSI 读取 UTF-8 文件导致的中文乱码问题。
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # .../web
PROJECT_ROOT = HERE.parent                          # .../video_compressor
WEB_DIR = str(HERE)
SCRIPT = str(HERE / "run_web.py")
ICON = str(PROJECT_ROOT / "icon.ico")
VENV_PYW = str(HERE / "backend" / ".venv" / ("Scripts/pythonw.exe" if os.name == "nt" else "bin/python"))
SHORTCUT_NAME = "视频压缩工具(网页版).lnk"

PS_TEMPLATE = r'''
$ErrorActionPreference = "Stop"
$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop '@@SHORTCUT_NAME@@'
$webDir = '@@WEB_DIR@@'
$script = '@@SCRIPT@@'
$icon = '@@ICON@@'
$venvPyw = '@@VENV_PYW@@'
if (Test-Path $venvPyw) {
  $pythonw = $venvPyw
} else {
  $pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
  if (-not $pythonw) { $pythonw = (Get-Command python.exe).Source }
}
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = $pythonw
$s.Arguments = '"' + $script + '"'
$s.WorkingDirectory = $webDir
$s.IconLocation = $icon + ',0'
$s.Description = '视频批量压缩工具 网页版 (本地浏览器·无窗口)'
$s.Save()
Write-Output $lnk
'''


def render() -> str:
    return (
        PS_TEMPLATE
        .replace("@@SHORTCUT_NAME@@", SHORTCUT_NAME)
        .replace("@@WEB_DIR@@", WEB_DIR)
        .replace("@@SCRIPT@@", SCRIPT)
        .replace("@@ICON@@", ICON)
        .replace("@@VENV_PYW@@", VENV_PYW)
    )


def main():
    enc = base64.b64encode(render().encode("utf-16-le")).decode("ascii")
    subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc])
    lnk = os.path.join(os.path.join(os.path.expanduser("~"), "Desktop"), SHORTCUT_NAME)
    if os.path.exists(lnk):
        print("OK:", lnk)
    else:
        print("快捷方式创建可能失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
