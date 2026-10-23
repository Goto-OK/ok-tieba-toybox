"""可选的 WebView2 人工验证窗口；由主程序以子进程启动。"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    url = sys.argv[1]
    import webview

    webview.create_window("贴吧安全验证", url, width=980, height=760)
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
