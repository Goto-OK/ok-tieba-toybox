"""可选的 WebView2 验证窗口；由主程序以子进程启动。"""

from __future__ import annotations

import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    url = sys.argv[1]
    import webview

    window = webview.create_window("贴吧安全验证", url, width=980, height=760)
    result = {"cookies": []}

    def on_closed() -> None:
        try:
            result["cookies"] = window.get_cookies() or []
        except Exception:  # noqa: BLE001
            result["cookies"] = []

    window.events.closed += on_closed
    webview.start()
    print("__TIEBA_COOKIES__" + json.dumps(result["cookies"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
