"""应用设置（通用选项卡），保存在 %APPDATA%\\TiebaReplyStats\\settings.json。"""

from __future__ import annotations

import json
import os
from typing import Dict

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TiebaReplyStats")
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

DEFAULTS: Dict[str, bool] = {
    "color_people": True,
    "color_forum": True,
    "color_posts": True,
}


def load_settings() -> Dict[str, bool]:
    data = {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}
    result = dict(DEFAULTS)
    if isinstance(data, dict):
        for key in DEFAULTS:
            if key in data:
                result[key] = bool(data[key])
    return result


def save_settings(data: Dict[str, bool]) -> bool:
    payload = {key: bool(data.get(key, DEFAULTS[key])) for key in DEFAULTS}
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
