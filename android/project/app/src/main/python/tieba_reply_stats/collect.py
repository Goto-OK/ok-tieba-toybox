"""抓取编排：翻页、楼中楼、失败降级与进度输出。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from .fetch import CaptchaError, Fetcher, FetchError, ThreadGoneError
from .models import Comment, Floor, ThreadData, ThreadMeta
from .parse import parse_comments_page, parse_thread_page, parse_total_comment

TIEBA_HOSTS = {"tieba.baidu.com", "tieba.baidu.com.cn"}
HARD_PAGE_LIMIT = 500


class CollectError(RuntimeError):
    """帖子无法解析或抓取失败。"""


class CollectCancelled(RuntimeError):
    """用户主动停止。"""


@dataclass
class CollectOptions:
    max_pages: int = 0  # 0 表示抓完全部
    include_comments: bool = True
    max_comment_pages: int = 30  # 单层楼中楼最多翻多少页（防止异常死循环）
    enrich_levels: bool = False  # 为只回楼中楼、没发过楼层的用户补全等级（较慢）
    pb_levels: bool = True  # 用新版网页接口补全楼层/楼中楼等级（较快，默认开）
    verbose: bool = True
    log: Optional[Callable[[str], None]] = None  # 自定义输出（GUI 用）
    should_stop: Optional[Callable[[], bool]] = None  # 返回 True 时中断抓取


def _noop_log(*_args) -> None:
    return None


def extract_tid(raw: str) -> str:
    """从各种贴吧链接/ID 中取出 tid。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("帖子地址为空")
    if text.isdigit() and len(text) >= 5:
        return text
    match = re.search(r"/p/(\d+)", text)
    if match:
        return match.group(1)
    match = re.search(r"[?&]tid=(\d+)", text)
    if match:
        return match.group(1)
    match = re.search(r"(\d{6,})", text)
    if match:
        return match.group(1)
    raise ValueError(f"无法从地址中识别帖子 ID：{raw}")


def normalize_url(raw: str) -> str:
    text = (raw or "").strip()
    if text.isdigit():
        return f"https://tieba.baidu.com/p/{text}"
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    parsed = urlparse(text)
    if "tieba.baidu.com" not in (parsed.netloc or ""):
        raise ValueError(f"不是百度贴吧链接：{raw}")
    return text


def thread_page_url(tid: str, pn: int) -> str:
    return f"https://tieba.baidu.com/p/{tid}?pn={pn}"


def comment_url(tid: str, pid: str, pn: int) -> str:
    return f"https://tieba.baidu.com/p/comment?tid={tid}&pid={pid}&pn={pn}"


def total_comment_url(tid: str, fid: str, pn: int) -> str:
    return f"https://tieba.baidu.com/p/totalComment?tid={tid}&fid={fid or 0}&pn={pn}&see_lz=0"


def collect_thread(url: str, fetcher: Fetcher, options: CollectOptions) -> ThreadData:
    tid = extract_tid(url)
    source_url = normalize_url(url)
    if options.log is not None:
        log = options.log
    elif options.verbose:
        log = print
    else:
        log = _noop_log

    _check_stop(options)
    log(f"[帖子 {tid}] {source_url}")
    if getattr(fetcher, "online", True) and not fetcher.cookie_dict().get("BDUSS"):
        from .page_pb import collect_thread_anon

        log("  未提供 Cookie，使用游客模式（公开帖子 / 每层前 10 条楼中楼）")
        return collect_thread_anon(source_url, fetcher, options)
    first = fetcher.get(thread_page_url(tid, 1), name=f"thread_{tid}_p1")
    meta, floors = parse_thread_page(first.text, source_url, tid)
    if not floors:
        raise CollectError(
            "页面里没有解析到任何楼层。可能是：帖子被删、需要登录、或页面结构变化。"
            " 可用 --dump-html 保存页面样本以便排查。"
        )

    meta.url = source_url
    floors_by_no: Dict[int, Floor] = {floor.post_no: floor for floor in floors}
    floor_page: Dict[str, int] = {floor.pid: 1 for floor in floors}
    pages_fetched = 1
    failed_pages = 0
    warnings: List[str] = []

    total_page = meta.total_page or 0
    if total_page and options.max_pages:
        limit = min(total_page, options.max_pages)
    elif total_page:
        limit = total_page
    else:
        limit = options.max_pages or HARD_PAGE_LIMIT
    log(f"  共 {total_page or '未知'} 页，计划抓取 {limit} 页")

    pn = 2
    while pn <= limit:
        _check_stop(options)
        try:
            response = fetcher.get(thread_page_url(tid, pn), name=f"thread_{tid}_p{pn}")
        except CaptchaError:
            raise
        except ThreadGoneError:
            warnings.append(f"第 {pn} 页返回 404，后续页不再抓取")
            log(f"  ! 第 {pn} 页 404，停止翻页")
            failed_pages += 1
            break
        except FetchError as error:
            failed_pages += 1
            warnings.append(f"第 {pn} 页抓取失败，已跳过：{error}")
            log(f"  ! 第 {pn} 页抓取失败：{error}")
            pn += 1
            continue

        _page_meta, page_items = parse_thread_page(response.text, source_url, tid)
        pages_fetched += 1
        if not page_items:
            log(f"  第 {pn} 页没有楼层，视为已到最后一页")
            break
        fresh = [floor for floor in page_items if floor.post_no not in floors_by_no]
        if not fresh:
            log(f"  第 {pn} 页楼层重复，视为已到最后一页")
            break
        for floor in fresh:
            floors_by_no[floor.post_no] = floor
            floor_page[floor.pid] = pn
        log(f"  第 {pn} 页：{len(fresh)} 层")
        pn += 1

    thread = ThreadData(
        meta=ThreadMeta(
            tid=tid,
            fid=meta.fid,
            title=meta.title,
            forum=meta.forum,
            url=source_url,
            total_page=total_page or pages_fetched,
            reply_num=meta.reply_num,
        ),
        floors=sorted(floors_by_no.values(), key=lambda item: item.post_no),
        pages_fetched=pages_fetched,
        warnings=warnings,
        complete=failed_pages == 0,
    )

    if total_page and pages_fetched < total_page and not options.max_pages:
        thread.complete = False
        thread.warnings.append(f"只抓到 {pages_fetched}/{total_page} 页")

    if options.include_comments:
        thread.comments = _collect_comments(tid, thread, floor_page, fetcher, options, log)
        if any("实际抓到" in item for item in thread.warnings):
            thread.complete = False
    else:
        log("  已跳过楼中楼（--no-comments）")
        thread.warnings.append("已按 --no-comments 跳过楼中楼")

    if options.pb_levels:
        from .pbapi import fill_thread_levels

        filled = fill_thread_levels(thread, fetcher, log)
        if filled:
            log(f"  新版网页接口补全等级：{filled} 处")

    if options.enrich_levels:
        enrich_user_levels(thread, fetcher, options, log)

    stats = thread.user_stats()
    with_level = sum(1 for item in stats if item["level"])
    missing = [item["name"] for item in stats if not item["level"]]
    if missing:
        log(f"  等级：{with_level}/{len(stats)} 人有等级，缺 {len(missing)} 人（{', '.join(missing[:5])}）")
    else:
        log(f"  等级：{with_level}/{len(stats)} 人全部有等级")

    return thread


def _collect_comments(
    tid: str,
    thread: ThreadData,
    floor_page: Dict[str, int],
    fetcher: Fetcher,
    options: CollectOptions,
    log,
) -> List[Comment]:
    targets = [floor for floor in thread.floors if floor.reply_num > 0]
    if not targets:
        log("  没有楼中楼回复")
        return []

    floors_by_pid = {floor.pid: floor for floor in thread.floors}
    collected: Dict[str, Comment] = {}
    floor_have: Dict[int, int] = {}

    # 1) 按页批量拉 totalComment（每楼最多返回前 10 条）
    pages: Dict[int, List[Floor]] = {}
    for floor in targets:
        pages.setdefault(floor_page.get(floor.pid, 1), []).append(floor)

    for pn in sorted(pages):
        _check_stop(options)
        try:
            payload = fetcher.get_json(total_comment_url(tid, thread.meta.fid, pn), name=f"total_{tid}_{pn}")
            got = parse_total_comment(payload, floors_by_pid)
        except CaptchaError:
            raise
        except Exception as error:  # noqa: BLE001 - JSON 解析失败等，后面逐楼补齐
            got = {}
            if options.verbose:
                log(f"    ! 第 {pn} 页 totalComment 失败，稍后逐楼补齐：{error}")
        for comment_list in got.values():
            for comment in comment_list:
                if comment.pid and comment.pid not in collected:
                    collected[comment.pid] = comment
                    floor_have[comment.floor_no] = floor_have.get(comment.floor_no, 0) + 1

    # 2) 不足的楼用 /p/comment 逐楼补齐（翻页）
    log(f"  楼中楼：{len(targets)} 层有回复，开始抓取…")
    for index, floor in enumerate(targets, start=1):
        _check_stop(options)
        have = floor_have.get(floor.post_no, 0)
        if have < floor.reply_num:
            more = _fetch_floor_comments(tid, floor, fetcher, options, log, set(collected.keys()), have)
            for comment in more:
                if comment.pid and comment.pid not in collected:
                    collected[comment.pid] = comment
                    floor_have[comment.floor_no] = floor_have.get(comment.floor_no, 0) + 1
        have = floor_have.get(floor.post_no, 0)
        if have < floor.reply_num:
            message = (
                f"{floor.post_no}楼声明 {floor.reply_num} 条回复，实际抓到 {have} 条"
                "（可能被折叠、删除或需要登录）"
            )
            if message not in thread.warnings:
                thread.warnings.append(message)
        if options.verbose and (index % 10 == 0 or index == len(targets)):
            log(f"    {index}/{len(targets)} 层，累计 {len(collected)} 条回复")

    _fill_missing_uids(collected, thread.floors)
    _fill_comment_levels(collected, thread.floors)

    log(f"  楼中楼完成：{len(collected)} 条")
    return sorted(
        collected.values(),
        key=lambda item: (item.floor_no, item.posted_at or datetime.min),
    )


def _fetch_floor_comments(
    tid: str,
    floor: Floor,
    fetcher: Fetcher,
    options: CollectOptions,
    log,
    known_pids: set,
    have: int,
) -> List[Comment]:
    """用 /p/comment 逐页拉某个楼的楼中楼，返回尚未抓到的部分。"""
    comments: List[Comment] = []
    pn = 1
    while pn <= max(1, options.max_comment_pages) and have + len(comments) < floor.reply_num:
        _check_stop(options)
        try:
            response = fetcher.get(comment_url(tid, floor.pid, pn), name=f"comment_{floor.pid}_{pn}")
        except CaptchaError:
            raise
        except FetchError as error:
            if options.verbose:
                log(f"    ! {floor.post_no}楼 第 {pn} 页楼中楼失败：{error}")
            break

        items, _has_next = parse_comments_page(response.text, floor)
        if not items:
            break
        for comment in items:
            key = comment.pid or f"{floor.post_no}:{comment.author}:{comment.content[:40]}"
            if key in known_pids:
                continue
            known_pids.add(key)
            comments.append(comment)
        pn += 1
    return comments


def _fill_missing_uids(collected: Dict[str, Comment], floors: List[Floor]) -> None:
    """/p/comment 里拿不到 user_id，用姓名把楼层里的 uid 补回去，避免同一用户被拆成两条。"""
    name_to_uid: Dict[str, str] = {}
    for floor in floors:
        if floor.author_id:
            if floor.author:
                name_to_uid.setdefault(floor.author, floor.author_id)
            if floor.author_name:
                name_to_uid.setdefault(floor.author_name, floor.author_id)
    for comment in collected.values():
        if comment.author_id:
            if comment.author:
                name_to_uid.setdefault(comment.author, comment.author_id)
            if comment.author_name:
                name_to_uid.setdefault(comment.author_name, comment.author_id)
    for comment in collected.values():
        if not comment.author_id:
            if comment.author in name_to_uid:
                comment.author_id = name_to_uid[comment.author]
            elif comment.author_name in name_to_uid:
                comment.author_id = name_to_uid[comment.author_name]


def _fill_comment_levels(collected: Dict[str, Comment], floors: List[Floor]) -> None:
    """楼中楼接口不带等级；用同一用户发过的楼层把等级补到评论上。"""
    level_by_uid: Dict[str, str] = {}
    level_by_name: Dict[str, str] = {}
    for floor in floors:
        if not floor.level:
            continue
        if floor.author_id:
            level_by_uid.setdefault(floor.author_id, floor.level)
        if floor.author:
            level_by_name.setdefault(floor.author, floor.level)
        if floor.author_name:
            level_by_name.setdefault(floor.author_name, floor.level)
    for comment in collected.values():
        if comment.level:
            continue
        comment.level = (
            level_by_uid.get(comment.author_id)
            or level_by_name.get(comment.author_name)
            or level_by_name.get(comment.author)
            or ""
        )


def enrich_user_levels(thread: ThreadData, fetcher: Fetcher, options: CollectOptions, log) -> None:
    """为只回楼中楼、没发过楼层的用户补全本吧等级。

    用官方客户端接口查「关注的贴吧」，从中找到本吧的等级。
    对方隐藏关注列表、或没关注本吧时拿不到，跳过即可。
    """
    from .profile import fetch_follow_forums, fetch_panel

    stats = thread.user_stats()
    todo = [item for item in stats if not item["level"] and (item["uid"] or item["username"])]
    if not todo:
        log("  等级补全：所有人都已有等级")
        return

    bar = (thread.meta.forum or "").rstrip("吧")
    comments_by_key: Dict[str, List[Comment]] = {}
    for comment in thread.comments:
        key = comment.author_id or f"name:{comment.author}"
        comments_by_key.setdefault(key, []).append(comment)
    floors_by_key: Dict[str, List[Floor]] = {}
    for floor in thread.floors:
        key = floor.author_id or f"name:{floor.author}"
        floors_by_key.setdefault(key, []).append(floor)

    log(f"  等级补全：{len(todo)} 位用户需要查询（较慢）…")
    done = 0
    for item in todo:
        _check_stop(options)
        level = ""
        if item["uid"]:
            follow = fetch_follow_forums(fetcher, item["uid"], max_pages=2)
            for forum in follow.get("forums") or []:
                if bar and forum["name"].rstrip("吧") == bar:
                    level = str(forum["level"])
                    break
        if not level and item.get("username"):
            # 关注列表被隐藏、或楼中楼没解析出用户ID时，从“等级头衔”里恢复本吧等级
            panel = fetch_panel(fetcher, item["username"])
            for forum in panel.get("forums") or []:
                if bar and forum["name"].rstrip("吧") == bar:
                    level = str(forum["level"])
                    break
        if not level:
            continue
        key = item["uid"] or f"name:{item['name']}"
        for floor in floors_by_key.get(key, []):
            floor.level = level
        for comment in comments_by_key.get(key, []):
            comment.level = level
        done += 1
        if options.verbose and (done % 10 == 0 or done == len(todo)):
            log(f"    已补全 {done}/{len(todo)}，当前 {item['name']} → Lv.{level}")

    log(f"  等级补全完成：{done} 位用户")


def _check_stop(options: CollectOptions) -> None:
    if options.should_stop is not None and options.should_stop():
        raise CollectCancelled("已停止")
