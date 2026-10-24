"""可选的 WebView2 人工验证窗口。

没有 Evergreen Runtime 或没有 pywebview 时直接返回不可用，
主程序继续使用系统浏览器 + 完整 Cookie。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import winreg
from pathlib import Path
from urllib.parse import urlsplit


def _runtime_installed() -> bool:
    if os.name != "nt":
        return False
    roots = [
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1E7E9E8-1D2B-4B7D-8F0A-2F6E5B0F1B7F}",
        r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F1E7E9E8-1D2B-4B7D-8F0A-2F6E5B0F1B7F}",
    ]
    for root in roots:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as key:
                if winreg.QueryValueEx(key, "pv"):
                    return True
        except OSError:
            continue
    for base in (
        os.environ.get("ProgramFiles(x86)", ""),
        os.environ.get("ProgramFiles", ""),
    ):
        if base and os.path.isdir(os.path.join(base, "Microsoft", "EdgeWebView", "Application")):
            return True
    return False


def available() -> bool:
    if importlib.util.find_spec("webview") is None:
        return False
    return _runtime_installed()


def login_profile_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return str(Path(base) / "TiebaReplyStats" / "webview2-login")


def login_profile_exists() -> bool:
    return os.path.isdir(login_profile_dir())


def clear_login_profile() -> bool:
    path = login_profile_dir()
    if not os.path.isdir(path):
        return True
    try:
        shutil.rmtree(path)
        return True
    except OSError:
        return False


ALLOWED_HOSTS = ("tieba.baidu.com", "passport.baidu.com", "wappass.baidu.com")
LOGIN_COOKIE_NAMES = ("BDUSS", "TIEBA_SID")


def is_allowed_url(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host in ALLOWED_HOSTS


def has_login_cookie(cookies) -> bool:
    if isinstance(cookies, dict):
        return any(cookies.get(name) for name in LOGIN_COOKIE_NAMES)
    for item in cookies or []:
        if isinstance(item, dict) and str(item.get("name") or "") in LOGIN_COOKIE_NAMES:
            return True
    return False


def filter_cookies(cookies, anonymous: bool) -> dict[str, str]:
    result: dict[str, str] = {}
    ranks: dict[str, tuple[int, int]] = {}
    for item in cookies or []:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").lower()
        if domain and "baidu.com" not in domain:
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        if anonymous and name in ("BDUSS", "STOKEN"):
            continue
        path = str(item.get("path") or "/")
        rank = (1 if domain.endswith("tieba.baidu.com") else 0, len(path))
        if name not in ranks or rank >= ranks[name]:
            ranks[name] = rank
            result[name] = str(item.get("value") or "")
    return result


def _run_window(
    url: str,
    timeout: int = 600,
    center=None,
    read_cookies: bool = True,
    persistent: bool = False,
    require_login: bool = False,
):
    if not available():
        raise RuntimeError("WebView2 不可用")
    extra = []
    if center:
        extra = ["--x", str(int(center[0])), "--y", str(int(center[1]))]
    if not read_cookies:
        extra.append("--no-cookie")
    if require_login:
        extra.append("--require-login")
    if persistent:
        Path(login_profile_dir()).mkdir(parents=True, exist_ok=True)
        extra.extend(["--profile-dir", login_profile_dir()])
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--webview2-verify", url, *extra]
    else:
        command = [sys.executable, "-m", "tieba_reply_stats.webview2_helper", url, *extra]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "WebView2 验证窗口启动失败")
    return completed


def open_window(url: str, timeout: int = 600, center=None) -> None:
    """打开内置窗口并等待用户关闭，不读取 Cookie。"""
    _run_window(url, timeout=timeout, center=center, read_cookies=False)


def open_verification(
    url: str,
    timeout: int = 600,
    center=None,
    persistent: bool = False,
    require_login: bool = False,
):
    """真实验证码窗口；返回 WebView2 Cookie 列表，由调用方按权限过滤。"""
    completed = _run_window(
        url,
        timeout=timeout,
        center=center,
        persistent=persistent,
        require_login=require_login,
    )
    marker = "__TIEBA_COOKIES__"
    for line in completed.stdout.splitlines():
        if line.startswith(marker):
            try:
                data = json.loads(line[len(marker) :])
            except json.JSONDecodeError:
                return {"cookies": [], "auto": False}
            if isinstance(data, list):
                return {"cookies": data, "auto": False}
            if isinstance(data, dict):
                return data
    return {"cookies": [], "auto": False}
