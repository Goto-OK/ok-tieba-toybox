"""可选的 WebView2 人工验证窗口；由主程序以子进程启动。"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes

TITLE = "贴吧安全验证"


def _center(width: int, height: int) -> tuple[int, int]:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        pass
    try:
        screen_w = int(ctypes.windll.user32.GetSystemMetrics(0))
        screen_h = int(ctypes.windll.user32.GetSystemMetrics(1))
    except Exception:  # noqa: BLE001
        return 80, 80
    return max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 2)


def _child_window_texts() -> list[str]:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    outer = user32.FindWindowW(None, TITLE)
    if not outer:
        return []
    texts: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value:
                texts.append(buffer.value)
        return True

    user32.EnumChildWindows(outer, callback, 0)
    return texts


def _close_window() -> None:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    outer = user32.FindWindowW(None, TITLE)
    if outer:
        user32.PostMessageW(outer, 0x0010, 0, 0)  # WM_CLOSE


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    url = sys.argv[1]
    import webview

    width, height = 980, 760
    x, y = _center(width, height)
    for index, value in enumerate(sys.argv):
        if value == "--x" and index + 1 < len(sys.argv):
            try:
                x = int(sys.argv[index + 1])
            except ValueError:
                pass
        if value == "--y" and index + 1 < len(sys.argv):
            try:
                y = int(sys.argv[index + 1])
            except ValueError:
                pass

    profile_dir = ""
    for index, value in enumerate(sys.argv):
        if value == "--profile-dir" and index + 1 < len(sys.argv):
            profile_dir = sys.argv[index + 1]
    require_login = "--require-login" in sys.argv

    window = webview.create_window(
        TITLE,
        url,
        width=width,
        height=height,
        x=x,
        y=y,
        on_top=True,
        text_select=False,
    )
    read_cookies = "--no-cookie" not in sys.argv
    cookies = []
    state = {"captcha_seen": False, "normal_since": 0.0, "closed": False, "auto": False}

    def normalize_cookies(raw) -> list[dict]:
        result = []
        for item in raw or []:
            if isinstance(item, dict) and "name" in item:
                result.append(item)
                continue
            try:
                for name, morsel in item.items():
                    result.append(
                        {
                            "name": name,
                            "value": morsel.value,
                            "domain": morsel["domain"] or "",
                            "path": morsel["path"] or "/",
                        }
                    )
            except Exception:  # noqa: BLE001
                continue
        return result

    def on_closed() -> None:
        nonlocal cookies
        state["closed"] = True
        if not read_cookies or cookies:
            return
        try:
            cookies = normalize_cookies(window.get_cookies())
        except Exception:  # noqa: BLE001
            cookies = []

    def capture_cookies() -> None:
        nonlocal cookies
        if not read_cookies:
            return
        try:
            cookies = normalize_cookies(window.get_cookies())
        except Exception:  # noqa: BLE001
            pass

    def monitor() -> None:
        started = time.monotonic()
        while not state["closed"]:
            time.sleep(0.25)
            if state["closed"]:
                return
            texts = _child_window_texts()
            marker = " ".join(texts).lower()
            captcha = any(
                item in marker
                for item in ("安全验证", "验证码", "wappass", "verify", "captcha")
            )
            if captcha:
                state["captcha_seen"] = True
                state["normal_since"] = 0.0
                continue
            normal = "百度贴吧" in marker or "贴吧" in marker
            if normal:
                if state["normal_since"] == 0.0:
                    state["normal_since"] = time.monotonic()
                stable = time.monotonic() - state["normal_since"]
                if stable >= 0.5 and (state["captcha_seen"] or time.monotonic() - started >= 2.0):
                    capture_cookies()
                    if require_login and not any(
                        str(item.get("name") or "").upper() in ("BDUSS", "TIEBA_SID")
                        for item in cookies
                        if isinstance(item, dict)
                    ):
                        state["normal_since"] = 0.0
                        continue
                    state["auto"] = True
                    _close_window()
                    return
            if time.monotonic() - started >= (300.0 if require_login else 30.0):
                capture_cookies()
                _close_window()
                return

    window.events.closed += on_closed
    threading.Thread(target=monitor, daemon=True).start()
    webview.start(private_mode=not profile_dir, storage_path=profile_dir or None)
    print(
        "__TIEBA_COOKIES__"
        + json.dumps({"cookies": cookies, "auto": state["auto"]}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
