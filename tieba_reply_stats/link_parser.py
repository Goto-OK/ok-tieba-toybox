"""官方帖子链接解析：主题 / 楼层 / 楼中楼 → 完整内部记录。"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from .collect import CollectOptions, collect_thread
from .models import ThreadData


def parse_link(raw: str) -> Dict[str, str]:
    text = (raw or "").strip()
    if not text:
        return {}
    match = re.search(r"/p/(\d+)", text)
    tid = match.group(1) if match else ""
    if not tid and text.isdigit():
        tid = text
    if not tid:
        return {}
    pid_match = re.search(r"[?&#]pid=(\d+)", text, re.I)
    pid = pid_match.group(1) if pid_match else ""
    url = f"https://tieba.baidu.com/p/{tid}"
    if pid:
        url += f"?pid={pid}"
    return {"tid": tid, "pid": pid, "url": url}


def extract_links(raw: str) -> List[str]:
    return [line.strip() for line in (raw or "").splitlines() if line.strip()]


def _row(thread: ThreadData, pid: str) -> Optional[Dict]:
    for floor in thread.floors:
        if pid and floor.pid != pid:
            continue
        return {
            "pid": floor.pid,
            "tid": thread.meta.tid,
            "time": floor.posted_at.strftime("%Y-%m-%d %H:%M") if floor.posted_at else "",
            "type": "主题帖" if floor.post_no == 1 else "回复",
            "bar": thread.meta.forum,
            "title": thread.meta.title,
            "content": floor.content,
            "floor": floor.post_no,
            "url": f"https://tieba.baidu.com/p/{thread.meta.tid}?pid={floor.pid}",
            "author": floor.author,
            "author_name": floor.author_name,
            "author_id": floor.author_id,
            "tieba_uid": floor.tieba_uid,
            "portrait": floor.portrait,
            "source": "链接解析",
        }
    for comment in thread.comments:
        if pid and comment.pid != pid:
            continue
        return {
            "pid": comment.pid,
            "tid": thread.meta.tid,
            "time": comment.posted_at.strftime("%Y-%m-%d %H:%M") if comment.posted_at else "",
            "type": "回复",
            "bar": thread.meta.forum,
            "title": thread.meta.title,
            "content": comment.content,
            "floor": comment.floor_no,
            "url": f"https://tieba.baidu.com/p/{thread.meta.tid}?pid={comment.pid}",
            "author": comment.author,
            "author_name": comment.author_name,
            "author_id": comment.author_id,
            "tieba_uid": comment.tieba_uid,
            "portrait": comment.portrait,
            "source": "链接解析",
        }
    return None


def parse_links(
    raw: str,
    fetcher,
    *,
    log: Optional[Callable[[str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    max_links: int = 200,
) -> Dict:
    """解析一批链接；同一 tid 只抓一次主题。"""
    links = extract_links(raw)[:max_links]
    result = {"rows": [], "errors": [], "threads": 0, "links": len(links)}
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for link in links:
        parsed = parse_link(link)
        if not parsed:
            result["errors"].append({"link": link, "error": "无法识别 tid"})
            continue
        grouped.setdefault(parsed["tid"], []).append(parsed)

    options = CollectOptions(
        mode="guest",
        max_pages=0,
        include_comments=True,
        comment_depth=0,
        comment_concurrency=1,
        max_comment_pages=50,
        enrich_levels=False,
        enrich_identities=False,
        pb_levels=False,
        verbose=False,
        log=log,
        should_stop=should_stop,
    )
    seen_pids = set()
    for tid, items in grouped.items():
        if should_stop and should_stop():
            break
        try:
            thread = collect_thread(f"https://tieba.baidu.com/p/{tid}", fetcher, options)
            result["threads"] += 1
        except Exception as error:  # noqa: BLE001
            for item in items:
                result["errors"].append({"link": item["url"], "error": str(error)})
            continue
        for item in items:
            pid = item.get("pid") or ""
            row = _row(thread, pid)
            if row is None:
                result["errors"].append({"link": item["url"], "error": "未找到该 pid"})
                continue
            row["url"] = item["url"]
            if not pid:
                row["note"] = "主题链接，默认取楼主帖"
            key = str(row.get("pid") or row.get("url") or "")
            if key and key in seen_pids:
                continue
            if key:
                seen_pids.add(key)
            result["rows"].append(row)
    return result
