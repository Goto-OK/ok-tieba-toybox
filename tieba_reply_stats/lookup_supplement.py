"""查用户发言补全：当前已抓主题 + 可选回抓 feed 主题。"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set

from .collect import CollectOptions, collect_thread
from .models import ThreadData


def _identity(user: Dict) -> Dict[str, str]:
    return {
        "uid": str(user.get("uid") or user.get("user_id") or user.get("author_id") or ""),
        "tieba_uid": str(user.get("tieba_uid") or ""),
        "portrait": str(user.get("portrait") or "").split("?")[0],
        "username": str(user.get("username") or user.get("author_name") or ""),
    }


def _matches(author_id: str, tieba_uid: str, portrait: str, username: str, identity: Dict[str, str]) -> bool:
    if identity["uid"] and author_id == identity["uid"]:
        return True
    if identity["tieba_uid"] and tieba_uid == identity["tieba_uid"]:
        return True
    clean_portrait = (portrait or "").split("?")[0]
    if identity["portrait"] and clean_portrait == identity["portrait"]:
        return True
    if identity["username"] and username == identity["username"]:
        return True
    return False


def _post_row(
    thread: ThreadData,
    pid: str,
    ts: Optional[datetime],
    kind: str,
    content: str,
    floor_no: int,
    source: str,
) -> Dict:
    return {
        "tid": thread.meta.tid,
        "title": thread.meta.title,
        "bar": thread.meta.forum,
        "time": ts.strftime("%Y-%m-%d") if ts else "",
        "ts": int(ts.timestamp()) if ts else 0,
        "type": kind,
        "pid": pid,
        "content": (content or "")[:120],
        "url": f"https://tieba.baidu.com/p/{thread.meta.tid}" + (f"?pid={pid}" if pid else ""),
        "source": source,
        "floor": floor_no,
    }


def merge_current_threads(
    posts: Sequence[Dict],
    threads: Iterable[ThreadData],
    user: Dict,
) -> Dict:
    identity = _identity(user)
    seen = {str(item.get("pid") or "") for item in posts if item.get("pid")}
    added: List[Dict] = []
    for thread in threads:
        for floor in thread.floors:
            if not _matches(floor.author_id, floor.tieba_uid, floor.portrait, floor.author_name, identity):
                continue
            pid = str(floor.pid or "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            added.append(
                _post_row(
                    thread,
                    pid,
                    floor.posted_at,
                    "主题帖" if floor.post_no == 1 else "回复",
                    floor.content,
                    floor.post_no,
                    "当前已抓主题",
                )
            )
        for comment in thread.comments:
            if not _matches(
                comment.author_id, comment.tieba_uid, comment.portrait, comment.author_name, identity
            ):
                continue
            pid = str(comment.pid or "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            added.append(
                _post_row(
                    thread,
                    pid,
                    comment.posted_at,
                    "回复",
                    comment.content,
                    comment.floor_no,
                    "当前已抓主题",
                )
            )
    return {"posts": added, "seen": seen}


def thread_ids_from_posts(posts: Sequence[Dict]) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for post in posts:
        tid = str(post.get("tid") or "")
        if tid and tid not in seen:
            seen.add(tid)
            result.append(tid)
    return result


def fetch_feed_thread_supplements(
    fetcher,
    posts: Sequence[Dict],
    user: Dict,
    *,
    limit: int = 50,
    full: bool = False,
    include_comments: bool = False,
    current_tids: Optional[Set[str]] = None,
    log: Optional[Callable[[str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict:
    """从 feed 的 thread_id 回抓主题，返回补充行和失败数。"""
    identity = _identity(user)
    known = set(current_tids or ())
    tids = [tid for tid in thread_ids_from_posts(posts) if tid not in known]
    if not full and limit > 0:
        tids = tids[:limit]
    seen = {str(item.get("pid") or "") for item in posts if item.get("pid")}
    added: List[Dict] = []
    failed = 0
    options = CollectOptions(
        mode="guest",
        max_pages=0 if full else 1,
        include_comments=include_comments,
        comment_depth=0 if include_comments else 0,
        comment_concurrency=1,
        max_comment_pages=50,
        enrich_levels=False,
        enrich_identities=False,
        pb_levels=False,
        verbose=False,
        log=log,
        should_stop=should_stop,
    )
    for tid in tids:
        if should_stop and should_stop():
            break
        try:
            thread = collect_thread(f"https://tieba.baidu.com/p/{tid}", fetcher, options)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        for floor in thread.floors:
            if not _matches(floor.author_id, floor.tieba_uid, floor.portrait, floor.author_name, identity):
                continue
            pid = str(floor.pid or "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            added.append(
                _post_row(
                    thread,
                    pid,
                    floor.posted_at,
                    "主题帖" if floor.post_no == 1 else "回复",
                    floor.content,
                    floor.post_no,
                    "回抓主题",
                )
            )
        if include_comments:
            for comment in thread.comments:
                if not _matches(
                    comment.author_id, comment.tieba_uid, comment.portrait, comment.author_name, identity
                ):
                    continue
                pid = str(comment.pid or "")
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                added.append(
                    _post_row(
                        thread,
                        pid,
                        comment.posted_at,
                        "回复",
                        comment.content,
                        comment.floor_no,
                        "回抓主题",
                    )
                )
    return {"posts": added, "seen": seen, "failed": failed, "threads": len(tids)}
