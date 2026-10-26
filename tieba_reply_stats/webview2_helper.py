"""可选的 WebView2 人工验证窗口；由主程序以子进程启动。"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from urllib.parse import urlsplit

TITLE = "贴吧安全验证"


def _center(width: int, height: int) -> tuple[int, int]:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: S110, BLE001
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


def _install_clr_loader_path_workaround() -> None:
    """让 pythonnet 从纯 ASCII 路径加载 Python.Runtime.dll。

    .NET Framework 在部分系统上无法从中文路径加载该程序集；这既不是
    Python 编码问题，也不能靠改 UTF-8/GBK 彻底解决。这里只复制运行时
    程序集到 ASCII 临时目录，不改第三方包。
    """
    try:
        import shutil
        from pathlib import Path

        import clr_loader.netfx as netfx

        cache_root = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "TiebaReplyStats"
        cache_dir = cache_root / "webview2-clr"
        cache_dir.mkdir(parents=True, exist_ok=True)
        if getattr(netfx.NetFx._get_callable, "_tieba_patched", False):
            return

        def _ascii_assembly_path(assembly_path) -> Path:
            source = Path(assembly_path)
            try:
                for item in source.parent.iterdir():
                    if not item.is_file():
                        continue
                    target = cache_dir / item.name
                    if not target.exists():
                        shutil.copy2(item, target)
                return cache_dir / source.name
            except OSError:
                return source

        def _get_callable(self, assembly_path, typename: str, function: str):
            load_path = _ascii_assembly_path(assembly_path)
            func = netfx._FW.pyclr_get_function(
                self._domain,
                str(load_path).encode("utf-8"),
                typename.encode("utf-8"),
                function.encode("utf-8"),
            )
            if func == netfx.ffi.NULL:
                raise RuntimeError(
                    f"Failed to resolve {typename}.{function} from {load_path}"
                )
            return func

        _get_callable._tieba_patched = True  # type: ignore[attr-defined]
        netfx.NetFx._get_callable = _get_callable  # type: ignore[method-assign]

        import webview.util as webview_util

        source_lib = Path(webview_util.__file__).parent / "lib"
        ascii_lib = cache_root / "webview2-lib"
        ascii_lib.mkdir(parents=True, exist_ok=True)
        for item in source_lib.rglob("*"):
            if not item.is_file():
                continue
            target = ascii_lib / item.relative_to(source_lib)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(item, target)

        def _interop_dll_path(dll_name: str) -> str:
            if dll_name == "WebBrowserInterop.dll":
                dll_name = (
                    "WebBrowserInterop.x64.dll"
                    if ctypes.sizeof(ctypes.c_void_p) == 8
                    else "WebBrowserInterop.x86.dll"
                )
            return str(ascii_lib / dll_name)

        webview_util.interop_dll_path = _interop_dll_path
    except Exception:  # noqa: S110, BLE001
        pass


def _trace(text: str) -> None:
    try:
        import tempfile
        from pathlib import Path

        path = Path(tempfile.gettempdir()) / "tieba_helper_trace.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def main() -> int:
    _trace(f"main args={sys.argv!r}")
    if len(sys.argv) < 2:
        return 2
    url = sys.argv[1]
    _install_clr_loader_path_workaround()
    _trace("patched")
    import webview

    _trace("webview imported")

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
    if window is None:
        raise RuntimeError("WebView2 窗口创建失败")
    read_cookies = "--no-cookie" not in sys.argv
    cookies: list[dict] = []
    state = {
        "captcha_seen": False,
        "normal_since": 0.0,
        "closed": False,
        "auto": False,
        "login_close_scheduled": False,
    }

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
            except Exception:  # noqa: S112, BLE001
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
        except Exception:  # noqa: S110, BLE001
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

    def on_loaded() -> None:
        try:
            url = str(window.get_current_url() or "")
            host = (urlsplit(url).hostname or "").lower()
        except Exception:  # noqa: BLE001
            return
        if host and host not in (
            "tieba.baidu.com",
            "passport.baidu.com",
            "wappass.baidu.com",
            "www.baidu.com",
        ):
            _close_window()
            return
        if require_login and read_cookies and not state["login_close_scheduled"]:
            try:
                raw = normalize_cookies(window.get_cookies())
            except Exception:  # noqa: BLE001
                return
            if any(
                str(item.get("name") or "") in ("BDUSS", "TIEBA_SID")
                for item in raw
                if isinstance(item, dict)
            ):
                state["login_close_scheduled"] = True

                def close_after_login() -> None:
                    time.sleep(0.8)
                    capture_cookies()
                    state["auto"] = True
                    _close_window()

                threading.Thread(target=close_after_login, daemon=True).start()

    window.events.closed += on_closed
    window.events.loaded += on_loaded
    threading.Thread(target=monitor, daemon=True).start()
    webview.start(private_mode=not profile_dir, storage_path=profile_dir or None)
    print(
        "__TIEBA_COOKIES__"
        + json.dumps({"cookies": cookies, "auto": state["auto"]}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
