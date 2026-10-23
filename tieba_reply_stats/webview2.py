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


def filter_cookies(cookies, anonymous: bool) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in cookies or []:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "")
        if domain and "baidu.com" not in domain:
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        if anonymous and name in ("BDUSS", "STOKEN"):
            continue
        result[name] = str(item.get("value") or "")
    return result


def _run_window(url: str, timeout: int = 600, center=None):
    if not available():
        raise RuntimeError("WebView2 不可用")
    extra = []
    if center:
        extra = ["--x", str(int(center[0])), "--y", str(int(center[1]))]
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
    _run_window(url, timeout=timeout, center=center)


def open_verification(url: str, timeout: int = 600, center=None):
    """真实验证码窗口；返回 WebView2 Cookie 列表，由调用方按权限过滤。"""
    completed = _run_window(url, timeout=timeout, center=center)
    marker = "__TIEBA_COOKIES__"
    for line in completed.stdout.splitlines():
        if line.startswith(marker):
            try:
                data = json.loads(line[len(marker) :])
            except json.JSONDecodeError:
                return []
            return data if isinstance(data, list) else []
    return []
