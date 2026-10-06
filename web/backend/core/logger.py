#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话日志管理器（复用桌面版逻辑）。

日志存放于项目目录 logs/ 下：结果日志 / 错误日志 / 删除日志，
UTF-8(BOM) 编码，记事本/Excel 可直接打开。线程安全。
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .consts import APP_DIR


class LogManager:
    LOG_DIR = APP_DIR / "logs"
    current_logger: Optional["LogManager"] = None

    def __init__(self):
        self._lock = threading.Lock()
        self.result_fp = None
        self.error_fp = None
        self.delete_fp = None
        self.result_path: Optional[Path] = None
        self.error_path: Optional[Path] = None
        self.delete_path: Optional[Path] = None

    def start_session(self, session_id: str, header_lines: list) -> tuple:
        for sub in ["结果日志", "错误日志", "删除日志"]:
            (self.LOG_DIR / sub).mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.result_path = self.LOG_DIR / "结果日志" / f"结果日志_{ts}.log"
        self.error_path = self.LOG_DIR / "错误日志" / f"错误日志_{ts}.log"
        self.delete_path = self.LOG_DIR / "删除日志" / f"删除日志_{ts}.log"

        self.result_fp = open(self.result_path, "w", encoding="utf-8-sig")
        self.error_fp = open(self.error_path, "w", encoding="utf-8-sig")
        self.delete_fp = open(self.delete_path, "w", encoding="utf-8-sig")

        sep = "=" * 66
        self.result_fp.write(f"{sep}\n视频压缩结果日志  会话: {session_id}\n{sep}\n")
        self.error_fp.write(f"{sep}\n视频压缩错误日志  会话: {session_id}\n{sep}\n")
        self.delete_fp.write(f"{sep}\n视频压缩删除日志  会话: {session_id}\n{sep}\n")
        for line in header_lines:
            self.result_fp.write(f"{line}\n")
            self.error_fp.write(f"{line}\n")
            self.delete_fp.write(f"{line}\n")
        self.result_fp.write(f"\n{'=' * 66}\n\n")
        self.error_fp.write(f"\n{'=' * 66}\n\n")
        self.delete_fp.write(f"\n{'=' * 66}\n\n")
        self._flush()
        LogManager.current_logger = self
        return (str(self.result_path), str(self.error_path), str(self.delete_path))

    def _flush(self):
        if self.result_fp:
            self.result_fp.flush()
        if self.error_fp:
            self.error_fp.flush()
        if self.delete_fp:
            self.delete_fp.flush()

    def write_result(self, text: str):
        with self._lock:
            if self.result_fp:
                self.result_fp.write(text)
                self._flush()

    def write_error(self, text: str):
        with self._lock:
            if self.error_fp:
                self.error_fp.write(text)
                self._flush()

    def write_delete(self, text: str):
        with self._lock:
            if self.delete_fp:
                self.delete_fp.write(text)
                self.delete_fp.flush()

    def finish_session(self, summary_lines: list):
        with self._lock:
            if self.result_fp:
                sep = "=" * 66
                self.result_fp.write(f"\n{sep}\n汇总\n{sep}\n")
                for line in summary_lines:
                    self.result_fp.write(f"{line}\n")
                self.result_fp.write(f"{sep}\n")
                self.result_fp.close()
                self.result_fp = None
            if self.error_fp:
                self.error_fp.write("\n[日志结束]\n")
                self.error_fp.close()
                self.error_fp = None
            if self.delete_fp:
                self.delete_fp.write("\n[日志结束]\n")
                self.delete_fp.close()
                self.delete_fp = None
            LogManager.current_logger = None
