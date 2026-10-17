"""把 Cookie 保存在本机（Windows DPAPI 加密，仅当前用户可解密）。

贴吧的登录 Cookie 属于敏感信息，这里不写明文：
- 用 Windows 自带的 DPAPI（CryptProtectData）按当前用户加密；
- 文件放在 %APPDATA%\\TiebaReplyStats\\cookie.bin；
- 换电脑或换 Windows 用户后无法解密，需要重新粘贴一次。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
from datetime import datetime
from typing import Optional

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TiebaReplyStats")
COOKIE_FILE = os.path.join(APP_DIR, "cookie.bin")
ENTROPY = b"TiebaReplyStats/v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _make_blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, max(1, len(data)))
    blob = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _crypt32():
    return ctypes.WinDLL("crypt32", use_last_error=True)


def _protect(data: bytes) -> Optional[bytes]:
    if os.name != "nt" or not data:
        return None
    crypt32 = _crypt32()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_in, _keep_in = _make_blob(data)
    blob_entropy, _keep_entropy = _make_blob(ENTROPY)
    blob_out = _Blob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in), "TiebaReplyStats", ctypes.byref(blob_entropy),
        None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _unprotect(data: bytes) -> Optional[bytes]:
    if os.name != "nt" or not data:
        return None
    crypt32 = _crypt32()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_in, _keep_in = _make_blob(data)
    blob_entropy, _keep_entropy = _make_blob(ENTROPY)
    blob_out = _Blob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, ctypes.byref(blob_entropy),
        None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
    )
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def save_cookie(cookie: str) -> bool:
    """加密保存 Cookie；成功返回 True。"""
    cookie = (cookie or "").strip()
    if not cookie:
        return False
    payload = json.dumps(
        {"v": 1, "cookie": cookie, "saved_at": datetime.now().isoformat(timespec="seconds")},
        ensure_ascii=False,
    ).encode("utf-8")
    encrypted = _protect(payload)
    if encrypted is None:
        return False
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(COOKIE_FILE, "wb") as handle:
            handle.write(encrypted)
        return True
    except OSError:
        return False


def load_cookie() -> str:
    """读取上次保存的 Cookie；没有或解密失败时返回空字符串。"""
    try:
        with open(COOKIE_FILE, "rb") as handle:
            encrypted = handle.read()
    except OSError:
        return ""
    raw = _unprotect(encrypted)
    if not raw:
        return ""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if isinstance(data, dict) and data.get("v") == 1:
        return str(data.get("cookie") or "")
    return ""


def clear_cookie() -> bool:
    try:
        os.remove(COOKIE_FILE)
        return True
    except OSError:
        return False
