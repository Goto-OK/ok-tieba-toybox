#!/usr/bin/env python3
"""百度贴吧楼层回复统计 —— 命令行入口。

用法：
    python tieba_stats.py https://tieba.baidu.com/p/1234567890
    python tieba_stats.py 1234567890 -o 统计.xlsx
"""

import sys

from tieba_reply_stats.cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)
