"""手动补充的 STOKEN（DPAPI，仅当前 Windows 用户可解密）。"""

from __future__ import annotations

import os
from typing import Optional

from .cookie_store import _protect, _unprotect

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TiebaReplyStats")
STOKEN_FILE = os.path.join(APP_DIR, "stoken.bin")


def save_stoken(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    data = _protect(text.encode("utf-8"))
    if not data:
        return False
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(STOKEN_FILE, "wb") as handle:
            handle.write(data)
        return True
    except OSError:
        return False


def load_stoken() -> Optional[str]:
    try:
        with open(STOKEN_FILE, "rb") as handle:
            data = _unprotect(handle.read())
    except OSError:
        return None
    if not data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None
