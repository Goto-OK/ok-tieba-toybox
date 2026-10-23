"""可选的 WebView2 人工验证窗口；由主程序以子进程启动。"""

from __future__ import annotations

import ctypes
import json
import sys


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
    window = webview.create_window(
        "贴吧安全验证",
        url,
        width=width,
        height=height,
        x=x,
        y=y,
        on_top=True,
    )
    cookies = []

    def on_closed() -> None:
        nonlocal cookies
        try:
            cookies = window.get_cookies() or []
        except Exception:  # noqa: BLE001
            cookies = []

    window.events.closed += on_closed
    webview.start(private_mode=True)
    print("__TIEBA_COOKIES__" + json.dumps(cookies, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
