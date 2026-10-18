"""应用设置（通用选项卡），保存在 %APPDATA%\\TiebaReplyStats\\settings.json。"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TiebaReplyStats")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

DEFAULTS: Dict[str, Any] = {
    "color_people": True,
    "color_forum": True,
    "color_posts": True,
    "mode": "guest",  # guest / login
    "mode_chosen": False,  # 是否已完成首次选择
    "risk_enabled": False,  # 本地标记 / 红绿灯，默认关闭
}


def load_settings() -> Dict[str, Any]:
    data = {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}
    result = dict(DEFAULTS)
    if isinstance(data, dict):
        for key in DEFAULTS:
            if key not in data:
                continue
            if key == "mode":
                result[key] = data[key] if data[key] in ("guest", "login") else "guest"
            else:
                result[key] = bool(data[key])
    return result


def save_settings(data: Dict[str, Any]) -> bool:
    payload: Dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        value = data.get(key, default)
        if key == "mode":
            payload[key] = value if value in ("guest", "login") else "guest"
        else:
            payload[key] = bool(value)
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
