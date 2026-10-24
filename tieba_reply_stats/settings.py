r"""应用设置，保存在 %APPDATA%\TiebaReplyStats\settings.json。"""

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
    "follow_enhance": False,
    "follow_load_mode": "auto",  # auto / manual
    "remember_bduss": True,
    "risk_enabled": True,
    "save_result": True,
    "restore_mode": "auto",  # auto / ask
    "encrypt_result": False,
    "auto_refresh_old": False,
    "removed_thread_action": "keep",  # keep / remove / ask
    "batch_concurrency": 1,
    "identity_strategy": "full",
    "identity_timing": True,
    "identity_remember_choice": True,
    "identity_concurrency": 3,
    "webview_remember_login": False,
    "ui_mode": "simple",
    "lookup_fill_threads": False,
    "lookup_fill_pages": "1",
    "lookup_fill_limit": 50,
    "lookup_fill_all": False,
    "lookup_fill_comments": False,
    "love_level_enabled": False,
    "proxy_mode": "system",  # system / none / custom
    "proxy_url": "",
    "log_enabled": False,
    "page_size": 1000,
    "post_cache_limit_mb": 200,
    "table_density": "comfortable",  # comfortable / compact
    "theme_mode": "light",  # light / dark / system
    "accent": "blue",  # blue / green / purple / orange / pink / cyan / red
    "settings_start": "general",  # general / last
    "onboarding_seen": False,
    "window_geometry": "",
}

_CHOICES = {
    "follow_load_mode": ("auto", "manual"),
    "restore_mode": ("auto", "ask"),
    "removed_thread_action": ("keep", "remove", "ask"),
    "proxy_mode": ("system", "none", "custom"),
    "settings_start": ("general", "last"),
    "table_density": ("comfortable", "compact"),
    "theme_mode": ("light", "dark", "system"),
    "accent": ("blue", "green", "purple", "orange", "pink", "cyan", "red"),
    "lookup_fill_pages": ("1", "full"),
    "identity_strategy": ("full", "ask", "skip", "user_id", "detail"),
}


def _coerce(key: str, value: Any, default: Any) -> Any:
    if key in _CHOICES:
        return value if value in _CHOICES[key] else default
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, str):
        return value if isinstance(value, str) else str(value)
    return value


def load_settings() -> Dict[str, Any]:
    data = {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}
    result = dict(DEFAULTS)
    if isinstance(data, dict):
        for key, default in DEFAULTS.items():
            if key in data:
                result[key] = _coerce(key, data[key], default)
    if result["batch_concurrency"] not in (1, 2, 3):
        result["batch_concurrency"] = 1
    if result["page_size"] not in (100, 500, 1000, 2000):
        result["page_size"] = 1000
    if result.get("ui_mode") not in ("simple", "advanced"):
        result["ui_mode"] = "simple"
    result["post_cache_limit_mb"] = max(50, min(2000, int(result.get("post_cache_limit_mb") or 200)))
    return result


def save_settings(data: Dict[str, Any]) -> bool:
    payload: Dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        payload[key] = _coerce(key, data.get(key, default), default)
    if payload["batch_concurrency"] not in (1, 2, 3):
        payload["batch_concurrency"] = 1
    if payload["page_size"] not in (100, 500, 1000, 2000):
        payload["page_size"] = 1000
    if payload.get("ui_mode") not in ("simple", "advanced"):
        payload["ui_mode"] = "simple"
    payload["post_cache_limit_mb"] = max(50, min(2000, int(payload.get("post_cache_limit_mb") or 200)))
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
