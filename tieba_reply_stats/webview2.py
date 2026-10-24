"""可选的 WebView2 人工验证窗口。

没有 Evergreen Runtime 或没有 pywebview 时直接返回不可用，
主程序继续使用系统浏览器 + 完整 Cookie。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
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


PROFILE_META_NAME = "profile-meta.json"


def _profile_meta_path() -> str:
    return os.path.join(login_profile_dir(), PROFILE_META_NAME)


def _normalized_cookies(cookies) -> dict:
    if not isinstance(cookies, dict):
        return {}
    return {str(key).upper(): str(value) for key, value in cookies.items() if value}


def _fingerprint_identity(cookies) -> tuple[str, str]:
    values = _normalized_cookies(cookies)
    uid = values.get("TIEBAUID") or ""
    bduss = values.get("BDUSS") or ""
    sid = values.get("TIEBA_SID") or ""
    if uid:
        return "TIEBAUID", f"TIEBAUID={uid}"
    if bduss:
        return "BDUSS", f"BDUSS={bduss}"
    if sid:
        return "TIEBA_SID", f"TIEBA_SID={sid}"
    return "", ""


def _fingerprint_hash(salt: str, identity: str) -> str:
    return hashlib.sha256(f"{salt}\n{identity}".encode("utf-8")).hexdigest()


def save_profile_fingerprint(cookies) -> bool:
    """保存 profile 的加盐指纹；不保存原始 Cookie。"""
    kind, identity = _fingerprint_identity(cookies)
    if not identity:
        return False
    profile = login_profile_dir()
    try:
        Path(profile).mkdir(parents=True, exist_ok=True)
        salt = secrets.token_hex(16)
        payload = {
            "version": 1,
            "kind": kind,
            "salt": salt,
            "hash": _fingerprint_hash(salt, identity),
            "updated_at": int(time.time()),
        }
        with open(_profile_meta_path(), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        return True
    except OSError:
        return False


def match_profile_fingerprint(cookies) -> bool | None:
    """返回 True/False；无指纹、类型不同或无法生成时返回 None。"""
    kind, identity = _fingerprint_identity(cookies)
    if not identity:
        return None
    try:
        with open(_profile_meta_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
        stored_kind = str(payload.get("kind") or "")
        salt = str(payload.get("salt") or "")
        expected = str(payload.get("hash") or "")
        if not salt or not expected:
            return None
        if stored_kind and stored_kind != kind:
            return None
        return secrets.compare_digest(expected, _fingerprint_hash(salt, identity))
    except (OSError, ValueError, TypeError):
        return None


def switch_profile_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return str(Path(base) / "TiebaReplyStats" / "webview2-switch")


def prepare_switch_profile() -> str:
    path = switch_profile_dir()
    try:
        shutil.rmtree(path)
    except OSError:
        pass
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def clear_switch_profile() -> None:
    try:
        shutil.rmtree(switch_profile_dir())
    except OSError:
        pass


def cleanup_profile_backup() -> None:
    target = login_profile_dir()
    backup = target + ".bak"
    try:
        if os.path.isdir(target):
            shutil.rmtree(backup)
        elif os.path.isdir(backup):
            os.replace(backup, target)
    except OSError:
        pass


def _replace_with_retry(source: str, target: str, attempts: int = 3) -> None:
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except OSError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(1)


def replace_login_profile(temp_dir: str) -> None:
    """用临时 profile 替换正式 profile；失败时回滚。"""
    source = os.path.abspath(temp_dir)
    target = os.path.abspath(login_profile_dir())
    backup = target + ".bak"
    if not os.path.isdir(source):
        raise RuntimeError("临时登录目录不存在")
    cleanup_profile_backup()
    try:
        if os.path.isdir(target):
            _replace_with_retry(target, backup)
        _replace_with_retry(source, target)
    except OSError:
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            if os.path.isdir(backup) and not os.path.isdir(target):
                _replace_with_retry(backup, target)
        except OSError:
            pass
        raise RuntimeError("内置登录目录被占用，旧登录已保留")
    try:
        shutil.rmtree(backup)
    except OSError:
        pass


def clear_profile_fingerprint() -> None:
    try:
        os.remove(_profile_meta_path())
    except OSError:
        pass


ALLOWED_HOSTS = (
    "tieba.baidu.com",
    "passport.baidu.com",
    "wappass.baidu.com",
    "www.baidu.com",
)
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
    profile_dir: str = "",
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
    if persistent or profile_dir:
        target_profile = profile_dir or login_profile_dir()
        Path(target_profile).mkdir(parents=True, exist_ok=True)
        extra.extend(["--profile-dir", target_profile])
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
    profile_dir: str = "",
):
    """真实验证码窗口；返回 WebView2 Cookie 列表，由调用方按权限过滤。"""
    completed = _run_window(
        url,
        timeout=timeout,
        center=center,
        persistent=persistent,
        require_login=require_login,
        profile_dir=profile_dir,
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
