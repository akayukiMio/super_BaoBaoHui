#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""处理历史与配置的读写（与桌面版共用同一份文件，行为保持一致）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .consts import APP_DIR, CONFIG_FILE, HISTORY_FILE

CONFIG_DIR = Path.home() / ".video_compressor"


def load_processing_history() -> set:
    path = APP_DIR / HISTORY_FILE
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("processed", []))
    except Exception:
        pass
    return set()


def save_processing_history(history: set):
    path = APP_DIR / HISTORY_FILE
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"processed": list(history)}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_config() -> dict:
    path = CONFIG_DIR / CONFIG_FILE
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(config: dict) -> bool:
    path = CONFIG_DIR / CONFIG_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
