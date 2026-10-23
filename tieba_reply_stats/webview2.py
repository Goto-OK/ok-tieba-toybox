"""可选的 WebView2 人工验证窗口。

没有 Evergreen Runtime 或没有 pywebview 时直接返回不可用，
主程序继续使用系统浏览器 + 完整 Cookie。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import winreg


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


def _cookie_header(cookies) -> str:
    pairs = []
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        domain = str(cookie.get("domain") or "")
        if not name:
            continue
        if domain and "baidu.com" not in domain:
            continue
        pairs.append(f"{name}={value}")
    return "; ".join(dict.fromkeys(pairs))


def open_verification(url: str, timeout: int = 600) -> str:
    """打开内置验证窗口，返回可粘贴到完整 Cookie 框的 Cookie 头。"""
    if not available():
        return ""
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--webview2-verify", url]
    else:
        command = [sys.executable, "-m", "tieba_reply_stats.webview2_helper", url]
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
    marker = "__TIEBA_COOKIES__"
    for line in completed.stdout.splitlines():
        if line.startswith(marker):
            try:
                return _cookie_header(json.loads(line[len(marker) :]))
            except json.JSONDecodeError:
                return ""
    return ""
