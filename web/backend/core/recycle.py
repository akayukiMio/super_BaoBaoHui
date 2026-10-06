#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 回收站操作（复用桌面版并新增批量接口）。"""
from __future__ import annotations

import ctypes
import sys
from typing import List

# FO_DELETE=3; FOF_ALLOWUNDO=0x40, FOF_NOCONFIRMATION=0x10, FOF_NOERRORUI=0x400
_FLAGS = 0x40 | 0x10 | 0x400


class _SHFILEOPSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        # Win32 中 fAnyOperationsAborted 是 BOOL(4 字节)
        ("fAnyOperationsAborted", ctypes.c_uint),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


def _run_op(p_from: str) -> bool:
    op = _SHFILEOPSTRUCT()
    op.hwnd = 0
    op.wFunc = 3  # FO_DELETE
    op.pFrom = p_from
    op.pTo = None
    op.fFlags = _FLAGS
    op.fAnyOperationsAborted = 0
    op.hNameMappings = None
    op.lpszProgressTitle = None
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return result == 0
    except Exception:
        return False


def send_to_recycle_bin(path: str) -> bool:
    """单个文件移入回收站（可恢复）"""
    if sys.platform != "win32":
        return False
    # pFrom 需双 null 结尾：str 末尾补一个 \0，c_wchar_p 再自动补一个
    return _run_op(path + "\0")


def send_many_to_recycle_bin(paths: List[str]) -> bool:
    """批量移入回收站：一次 SHFileOperationW 调用，明显快于逐个。"""
    if sys.platform != "win32" or not paths:
        return False
    joined = "\0".join(paths) + "\0"  # 各路径以 \0 分隔，整体再补 \0
    return _run_op(joined)
