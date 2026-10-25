"""GUI 共用小工具。"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from typing import Optional

_EMOJI_CODE_RE = re.compile(r"\[U\+([0-9A-Fa-f]{4,6})\]", re.I)


def display_text(value) -> str:
    """界面直接显示 emoji；Tk 8.6 以单色字形渲染。"""
    return str(value or "")


def decode_display(value) -> str:
    """把 [U+XXXX] 还原成 emoji，用于回查。"""
    return _EMOJI_CODE_RE.sub(lambda match: chr(int(match.group(1), 16)), str(value or ""))


def resource_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def optional_int(text: str) -> Optional[int]:
    try:
        return int(str(text).strip())
    except ValueError:
        return None


def default_output_path() -> str:
    desktop = ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "Desktop")
        desktop = os.path.expandvars(value)
    except OSError:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.expanduser("~")
    return os.path.join(desktop, f"OK的贴吧玩具箱_{datetime.now():%Y%m%d_%H%M}.xlsx")
