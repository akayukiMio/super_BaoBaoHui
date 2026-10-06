#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建桌面快捷方式：双击用 pythonw 静默拉起 run_dev.py 并打开浏览器。

通过 PowerShell -EncodedCommand（UTF-16LE）传脚本，规避 Windows PowerShell
按 ANSI 读取 UTF-8 文件导致的中文乱码问题。
"""
import base64
import os
import subprocess
import sys

PS = r'''
$ErrorActionPreference = "Stop"
$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desktop '视频压缩工具(网页版).lnk'
$webDir = 'e:\administrator\1!5!\script\video_compressor\web'
# 优先用 venv 的 pythonw.exe（依赖齐全且无控制台窗口）
$pythonw = Join-Path $webDir 'backend\.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source }
if (-not $pythonw) { $pythonw = (Get-Command python.exe).Source }
$script = Join-Path $webDir 'run_web.py'
$icon = 'e:\administrator\1!5!\script\video_compressor\icon.ico'
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = $pythonw
$s.Arguments = '"' + $script + '"'
$s.WorkingDirectory = $webDir
$s.IconLocation = $icon + ',0'
$s.Description = '视频批量压缩工具 网页版 (本地浏览器·无窗口)'
$s.Save()
Write-Output $lnk
'''


def main():
    enc = base64.b64encode(PS.encode("utf-16-le")).decode("ascii")
    subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc])
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    lnk = os.path.join(desktop, "视频压缩工具(网页版).lnk")
    if os.path.exists(lnk):
        print("OK:", lnk)
    else:
        # 兼容 OneDrive 桌面等重定向情况
        import glob
        found = glob.glob(os.path.join(os.path.expanduser("~"), "**", "视频压缩工具(网页版).lnk"), recursive=True)
        print("FOUND:", found if found else "未找到快捷方式，创建可能失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
