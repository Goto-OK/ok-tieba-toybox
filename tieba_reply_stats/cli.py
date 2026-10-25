"""命令行入口。"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, List, Optional, cast

from .collect import CollectError, CollectOptions, collect_thread, extract_tid
from .export import export_workbook
from .fetch import (
    DEFAULT_UA,
    CaptchaError,
    Fetcher,
    FetchError,
    ThreadGoneError,
    load_cookie_file,
    parse_cookie_input,
)
from .models import ThreadData
from .version import __version__ as VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ok-tieba-toybox",
        description="OK的贴吧玩具箱：抓取贴吧楼层与楼中楼，按用户统计并导出 Excel。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python tieba_stats.py https://tieba.baidu.com/p/1234567890\n"
            "  python tieba_stats.py 1234567890 -o 统计.xlsx --delay 1.5\n"
            '  python tieba_stats.py <url1> <url2> --no-comments --cookie "BDUSS=...; STOKEN=..."\n'
        ),
    )
    parser.add_argument("urls", nargs="+", help="帖子链接或帖子 ID，可一次传入多个")
    parser.add_argument("-o", "--output", help="输出 xlsx 路径（默认：OK的贴吧玩具箱_时间.xlsx）")
    parser.add_argument("--delay", type=float, default=0.8, help="每次请求前的间隔秒数（默认 0.8）")
    parser.add_argument("--timeout", type=float, default=20, help="单次请求超时秒数（默认 20）")
    parser.add_argument("--retries", type=int, default=3, help="单次请求最多重试次数（默认 3）")
    parser.add_argument("--max-pages", type=int, default=0, help="最多抓取多少页主题楼层（0 表示全部）")
    parser.add_argument("--no-comments", action="store_true", help="只统计主题楼层，不抓楼中楼")
    parser.add_argument("--exclude-op", action="store_true", help="统计时不把 1 楼（楼主主帖）算作回复")
    parser.add_argument(
        "--enrich-levels",
        action="store_true",
        help="为只回楼中楼的用户补全本吧等级（较慢，每人多一次查询）",
    )
    parser.add_argument("--max-comment-pages", type=int, default=30, help="单层楼中楼最多翻页数（默认 30）")
    parser.add_argument(
        "--mode",
        choices=("guest", "login"),
        help="抓取模式；默认免登录，传 --cookie 且未指定时自动登录",
    )
    parser.add_argument("--cookie", help="浏览器里复制的 Cookie 字符串")
    parser.add_argument("--cookie-file", help="Cookie 文件（k=v 文本或 Netscape cookies.txt）")
    parser.add_argument("--proxy", help="代理地址，如 http://127.0.0.1:7890")
    parser.add_argument("--dump-html", help="把抓到的原始页面保存到该目录（排查解析问题用）")
    parser.add_argument("--cache-dir", help="页面缓存目录（重跑时加速）")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存，强制重新请求")
    parser.add_argument("--user-agent", help="自定义 User-Agent")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式，只输出结果")
    parser.add_argument("-V", "--version", action="version", version=f"ok-tieba-toybox {VERSION}")
    return parser


def _default_output() -> str:
    return f"OK的贴吧玩具箱_{datetime.now():%Y%m%d_%H%M}.xlsx"


def _load_cookies(args) -> dict:
    cookies = {}
    if args.cookie_file:
        if not os.path.isfile(args.cookie_file):
            raise SystemExit(f"找不到 Cookie 文件：{args.cookie_file}")
        cookies.update(load_cookie_file(args.cookie_file))
    if args.cookie:
        cookies.update(parse_cookie_input(args.cookie))
    return cookies


def _retry_with_cookie(error, raw, fetcher, options, cookies) -> Optional[ThreadData]:
    """被安全验证拦截时，交互式让用户粘贴 Cookie 再试一次。"""
    print(f"\n[被拦截] {error}")
    if cookies:
        return None
    if not sys.stdin.isatty():
        print('当前不是交互终端，请改用 --cookie "浏览器里的 Cookie" 重试。')
        return None
    print("请用浏览器打开该帖子，F12 → Network → 复制请求头里的整行 Cookie，粘贴到这里。")
    try:
        entered = input("Cookie（直接回车退出）：").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not entered:
        return None

    parsed = parse_cookie_input(entered)
    if not parsed:
        print("没有识别到有效的 Cookie。")
        return None
    cookies.update(parsed)
    fetcher.add_cookies(parsed)
    try:
        return collect_thread(raw, fetcher, options)
    except CaptchaError as retry_error:
        print(f"[仍被拦截] {retry_error}")
        return None
    except (ThreadGoneError, CollectError, FetchError, ValueError) as retry_error:
        print(f"帖子抓取失败：{retry_error}")
        return None


def main(argv: Optional[List[str]] = None) -> int:
    stdout = cast(Any, sys.stdout)
    stderr = cast(Any, sys.stderr)
    if hasattr(stdout, "reconfigure"):
        try:
            stdout.reconfigure(encoding="utf-8", errors="replace")
            stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 个别 Windows 控制台不支持重设编码
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    verbose = not args.quiet

    try:
        cookies = _load_cookies(args)
    except SystemExit as error:
        print(error)
        return 2

    mode = args.mode or ("login" if cookies.get("BDUSS") else "guest")
    fetcher = Fetcher(
        cookie=cookies,
        user_agent=args.user_agent or DEFAULT_UA,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
        proxy=args.proxy,
        cache_dir=args.cache_dir,
        dump_dir=args.dump_html,
        refresh=args.refresh,
        verbose=verbose,
    )
    options = CollectOptions(
        mode=mode,
        max_pages=max(0, args.max_pages),
        include_comments=not args.no_comments,
        enrich_levels=args.enrich_levels,
        pb_levels=args.enrich_levels,
        max_comment_pages=max(1, args.max_comment_pages),
        verbose=verbose,
    )

    threads: List[ThreadData] = []
    for raw in args.urls:
        try:
            tid = extract_tid(raw)
        except ValueError as error:
            print(f"跳过：{error}")
            continue
        if verbose:
            print()
        thread: Optional[ThreadData] = None
        try:
            thread = collect_thread(raw, fetcher, options)
        except CaptchaError as error:
            thread = _retry_with_cookie(error, raw, fetcher, options, cookies)
            if thread is None:
                return 2
        except (ThreadGoneError, CollectError, FetchError, ValueError) as error:
            print(f"帖子 {tid} 抓取失败：{error}")
            continue
        threads.append(thread)
        if verbose:
            print(
                f"  完成：{len(thread.floors)} 层 / {len(thread.comments)} 条楼中楼"
                f" / {len(thread.user_stats())} 位用户"
            )

    if not threads:
        print("没有成功抓取任何帖子，未生成文件。")
        return 1

    output = os.path.abspath(args.output or _default_output())
    export_workbook(output, threads, include_op=not args.exclude_op)

    print()
    print(f"已生成：{output}")
    print(f"共 {len(threads)} 个帖子：")
    for index, thread in enumerate(threads, start=1):
        title = thread.meta.title or thread.meta.tid
        flag = "" if thread.complete else "（部分缺失）"
        print(
            f"  {index}. {title}  "
            f"{len(thread.floors)} 层 / {len(thread.comments)} 条楼中楼 / "
            f"{len(thread.user_stats())} 位用户{flag}"
        )
        for warning in thread.warnings[:3]:
            print(f"      - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
