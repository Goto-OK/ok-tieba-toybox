"""查询单个贴吧用户的资料：发言、关注的贴吧、各吧等级。

接口：
- 关注贴吧（官方客户端接口，POST，带 BDUSS）：
  https://tiebac.baidu.com/c/f/forum/like?friend_uid=...&page_no=..&page_size=..
  返回 forum_list.non-gconforum，包含每个吧的 level_id / level_name（头衔）。
  对方若把关注列表设为私密，则不会返回数据。
- 发言（PC 接口，GET，带签名）：
  https://tieba.baidu.com/c/u/feed/myThread?portrait=..&pn=..&rn=..
  返回 list，每项含 thread_info（标题、fname 吧名）和 post_info（正文片段）。
"""

from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote, urlencode

from . import post_cache, profile_pb, userpost_pb

PC_SALT = b"36770b1f34c9bbf2e7d1a99d2b82fa9e"


def _cache_user_key(uid: str, portrait: str) -> str:
    return str(uid or portrait or "").strip()


def _cached_get_json(
    fetcher,
    url: str,
    name: str,
    key: tuple[str, str, int],
    use_cache: bool = True,
    cache_priority: int = post_cache.PRIORITY_HIGH,
    variant: str = "",
):
    user_key, kind, page = key
    if use_cache:
        hit = post_cache.cache().get_page(user_key, kind, page, variant=variant)
        if hit is not None:
            return hit
    payload = fetcher.get_json(url, name=name)
    if use_cache and user_key:
        post_cache.cache().put_page(user_key, kind, page, payload, priority=cache_priority, variant=variant)
    return payload


def _cached_thread_page(
    fetcher,
    uid: str,
    page: int,
    use_cache: bool = True,
    cache_priority: int = post_cache.PRIORITY_HIGH,
) -> List[Dict]:
    variant = "60:v1"
    if use_cache:
        hit = post_cache.cache().get_page(uid, "topic", page, variant=variant)
        if hit is not None:
            return list(hit.get("items") or [])
    raw = userpost_pb._request(fetcher, int(uid), page)
    items = userpost_pb.parse_response(raw)
    if use_cache:
        post_cache.cache().put_page(uid, "topic", page, {"items": items}, priority=cache_priority, variant=variant)
    return items


def clear_post_cache() -> None:
    """清空本次运行的发言缓存（热内存 + 冷库）。"""
    post_cache.clear_post_cache()


def get_cached_user(uid: str) -> Optional[Dict]:
    return post_cache.cache().get_user(str(uid or ""))

APP_SALT = b"tiebaclient!!!"
CLIENT_VERSION = "22.12.1.0"
FOLLOW_URL = "https://tiebac.baidu.com/c/f/forum/like"
POSTS_URL = "https://tieba.baidu.com/c/u/feed/myThread"
PANEL_URL = "https://tiebac.baidu.com/home/get/panel?un={un}"
PROFILE_URL = "https://tieba.baidu.com/home/main?un={un}&fr=home"
USER_JSON_URL = "https://tieba.baidu.com/i/sys/user_json?{key}={value}&ie=utf-8"
SEARCH_USER_URL = "https://tieba.baidu.com/mo/q/search/user?word={word}"
PORTRAIT_RE = re.compile(r"[?&]id=(tb\.[0-9A-Za-z._-]+)")


_MOJIBAKE_HINTS = (
    "锟斤拷",
    "杩",
    "橀",
    "吂",
    "姹",
    "熸",
    "湀",
    "浣",
    "犲",
    "鐨",
    "鏄",
    "涓",
    "浜",
    "鍜",
    "寮",
    "鍙",
    "璇",
    "鍚",
    "闂",
    "棰",
    "绔",
    "鎴",
    "戠",
    "瓒",
    "娓",
    "爜",
    "銆",
    "傚",
    "姛",
    "鑳",
    "芥",
    "槸",
    "寰",
    "堝",
    "啋",
)
_WEIRD_RE = re.compile(r"[\u0080-\u07ff\ue000-\uf8ff]")


def _fix_mojibake(text: str) -> str:
    """还原 GBK/UTF-8 混淆的乱码；已经是正常中文就原样返回，避免二次破坏。"""
    if not text:
        return text
    suspicious = any(hint in text for hint in _MOJIBAKE_HINTS) or bool(_WEIRD_RE.search(text))
    if not suspicious:
        return text
    try:
        fixed = text.encode("gb18030", errors="ignore").decode("utf-8", errors="ignore")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if not fixed or fixed == text or _WEIRD_RE.search(fixed):
        return text
    return fixed


def search_user_by_nickname(fetcher, nickname: str) -> Dict:
    """按昵称搜用户（贴吧移动版搜索，匹配 name/user_nickname/show_nickname）。"""
    text = (nickname or "").strip()
    if not text:
        return {}
    target = text.lower()
    for page in (1, 2):
        try:
            payload = fetcher.get_json(SEARCH_USER_URL.format(word=quote(text)) + f"&pn={page}")
        except Exception:  # noqa: BLE001
            break
        data = payload.get("data") or {}
        exact = data.get("exactMatch")
        fuzzy = data.get("fuzzyMatch")
        exact_items = exact if isinstance(exact, list) else [exact] if isinstance(exact, dict) else []
        fuzzy_items = fuzzy if isinstance(fuzzy, list) else [fuzzy] if isinstance(fuzzy, dict) else []
        items = exact_items + fuzzy_items
        for item in items:
            if not isinstance(item, dict):
                continue
            names = {
                str(item.get(key) or "").strip().lower() for key in ("name", "user_nickname", "show_nickname")
            }
            if target not in names:
                continue
            username = str(item.get("name") or "").strip()
            return {
                "uid": str(item.get("id") or ""),
                "username": username,
                "nickname": _fix_mojibake(
                    str(item.get("user_nickname") or item.get("show_nickname") or username)
                ),
                "portrait": str(item.get("portrait") or "").split("?")[0].rstrip("/").rsplit("/", 1)[-1],
            }
        if not data.get("has_more"):
            break
    return {}


def resolve_user(fetcher, query: str, mode: str = "用户名") -> Dict:
    """把 昵称/用户名/用户ID 解析成 uid、用户名、头像。"""
    text = (query or "").strip()
    if not text:
        return {}
    if mode == "昵称":
        return search_user_by_nickname(fetcher, text)
    if mode == "贴吧ID":
        profile = profile_pb.fetch_profile_by_tieba_uid(fetcher, text)
        if not profile.get("uid"):
            return {}
        return {
            "uid": str(profile["uid"]),
            "tieba_uid": text,
            "username": profile.get("username") or "",
            "nickname": profile.get("nickname") or "",
            "portrait": profile.get("portrait") or "",
        }
    key = "uid" if mode == "用户ID" or (mode == "自动" and text.isdigit()) else "un"
    try:
        payload = fetcher.get_json(USER_JSON_URL.format(key=key, value=quote(text)))
    except Exception:  # noqa: BLE001
        return {}
    creator = payload.get("creator") or {}
    resolved_uid = str(payload.get("id") or creator.get("id") or "")
    username = _fix_mojibake(str(payload.get("raw_name") or creator.get("name") or ""))
    nickname = _fix_mojibake(str(creator.get("show_nickname") or creator.get("name_show") or ""))
    if key == "uid":
        # 不存在的 ID 会返回一个占位账号（名字为空或 ID 对不上），直接判为找不到
        if resolved_uid != text or (not username and not nickname):
            return {}
    return {
        "uid": resolved_uid,
        "username": username,
        "nickname": nickname,
        "portrait": str(creator.get("portrait") or creator.get("itieba_portrait") or "").split("?")[0],
    }


def fetch_panel(fetcher, username: str) -> Dict:
    """用户面板：发帖数、关注数、以及按等级分组的贴吧（隐藏关注时也能拿到一部分）。"""
    if not username:
        return {}
    try:
        payload = fetcher.get_json(PANEL_URL.format(un=quote(username)))
    except Exception:  # noqa: BLE001
        return {}
    data = payload.get("data") or {}
    grade = (data.get("honor") or {}).get("grade") or {}
    forums = []
    for level, info in grade.items():
        if not isinstance(info, dict):
            continue
        for name in info.get("forum_list") or []:
            if name:
                forums.append({"name": name, "level": int(level), "level_name": ""})
    return {
        "post_num": data.get("post_num"),
        "followed_count": data.get("followed_count"),
        "forums": forums,
        "private": bool(data.get("is_private")),
    }


def _sign(params: Dict[str, object], salt: bytes) -> Dict[str, object]:
    data = sorted(params.items(), key=lambda item: item[0])
    md5 = hashlib.md5()
    for key, value in data:
        md5.update(f"{key}={value}".encode())
    md5.update(salt)
    signed = dict(data)
    signed["sign"] = md5.hexdigest()
    return signed


def fetch_portrait(fetcher, username: str) -> str:
    """从用户主页里取 portrait（用于调用需要 portrait 的接口）。"""
    if not username:
        return ""
    try:
        text = fetcher.get(PROFILE_URL.format(un=quote(username))).text
    except Exception:  # noqa: BLE001
        return ""
    match = PORTRAIT_RE.search(text)
    return match.group(1) if match else ""


def fetch_follow_forums(fetcher, user_id: str, max_pages: int = 3) -> Dict:
    """官方客户端接口：查用户关注的贴吧（含等级/头衔）。"""
    bduss = fetcher.cookie_dict().get("BDUSS", "")
    if not bduss:
        return {"ok": False, "error": "缺少 BDUSS", "forums": [], "private": False}
    if not user_id:
        return {"ok": False, "error": "缺少用户ID", "forums": [], "private": False}

    forums: List[Dict] = []
    private = False
    page = 1
    while page <= max_pages:
        params = {
            "BDUSS": bduss,
            "_client_version": CLIENT_VERSION,
            "friend_uid": user_id,
            "page_no": page,
            "page_size": 100,
        }
        try:
            payload = fetcher.post_json(FOLLOW_URL, _sign(params, APP_SALT), name=f"follow_{user_id}_{page}")
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "error": str(error), "forums": forums, "private": private}

        forum_list = payload.get("forum_list") or {}
        items = []
        for key in ("non-gconforum", "gconforum"):
            value = forum_list.get(key)
            if isinstance(value, list):
                items.extend(value)
        if not items:
            # 没有数据：可能是对方隐藏了关注列表
            private = True
            break
        for item in items:
            name = item.get("name")
            if not name:
                continue
            forums.append(
                {
                    "name": name,
                    "level": int(item.get("level_id") or 0),
                    "level_name": item.get("level_name") or "",
                    "fid": item.get("id"),
                }
            )
        if len(items) < 100:
            break
        page += 1
    return {"ok": True, "forums": forums, "private": private, "error": ""}


def _strip_tags(text) -> str:
    if isinstance(text, list):
        text = "".join(str(item.get("text") or "") for item in text if isinstance(item, dict))
    text = str(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(text: str):
    try:
        return datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def fetch_user_posts(
    fetcher,
    portrait: str,
    count: int = 20,
    start_date: str = "",
    end_date: str = "",
    prefer: str = "end",
    uid: str = "",
    status: Optional[Dict[str, object]] = None,
    topic_max_pages: int = 50,
    use_cache: bool = True,
    cache_priority: int = 1,
) -> List[Dict]:
    """PC 接口：取用户发言（主题帖 + 回复），按时间倒序，最多 count 条。

    type=2 是「回复」，type=1 是「主题帖」；两个都取才不会漏。
    可选 start_date / end_date（YYYY-MM-DD）限定日期范围。
    """
    posts: List[Dict] = []
    if status is not None:
        status.clear()
        status.update({"replies_ok": None, "replies_error": "", "replies_empty": False,
                       "replies_exhausted": False,
                       "threads_ok": None, "threads_error": "",
                       "topic_pages": 0, "topic_reached_start": False,
                       "topic_truncated": False, "topic_exhausted": False,
                       "requested_start": start_date, "requested_end": end_date,
                       "requested_count": count, "coverage_start": "", "coverage_end": ""})
    if not portrait and not uid:
        return posts
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    seen = set()

    def add_post(tid, pid, title, bar, ts, kind, content):
        key = pid or f"{tid}:{title}"
        if key in seen:
            return
        seen.add(key)
        title = title or ""
        content = (content or "").strip()
        if not title and not content:
            return
        ts = int(ts or 0)
        day = datetime.fromtimestamp(ts).date() if ts else None
        if start and day and day < start:
            return
        if end and day and day > end:
            return
        posts.append(
            {
                "tid": str(tid),
                "title": title,
                "bar": bar or "",
                "time": day.strftime("%Y-%m-%d") if day else "",
                "ts": ts,
                "type": kind,
                "pid": str(pid),
                "content": content[:120],
                "url": f"https://tieba.baidu.com/p/{tid}" + (f"?pid={pid}" if pid else ""),
                "source": "官方",
            }
        )

    # 1) replies: old PC feed (type=2)
    # 指定日期 + 优先最早时要翻到开始日期，不能只按 count 截断，
    # 否则后面的主题流会把这批回复挤出结果。
    # 旧接口支持 rn=100，用大页减少翻页数；80*20 只能到最近几个月。
    reply_page_size = 300
    # 指定开始日期 + 优先最早：抓取必须到开始日期；
    # 指定开始日期 + 优先最近：每条流取够 count 即停。
    deep_start = bool(start) and prefer == "start"
    collect_start = deep_start
    page = 1
    while page <= 150 and (len(posts) < count or collect_start):
        params = _sign(
            {
                "pn": page,
                "rn": reply_page_size,
                "portrait": portrait,
                "type": 2,
                "subapp_type": "pc",
                "_client_type": 20,
            },
            PC_SALT,
        )
        try:
            payload = _cached_get_json(
                fetcher,
                POSTS_URL + "?" + urlencode(params),
                f"posts_{portrait[:12]}_2_{page}",
                (_cache_user_key(uid, portrait), "reply", page),
                use_cache=use_cache,
                cache_priority=cache_priority,
                variant=f"{reply_page_size}:v1",
            )
            if status is not None:
                status["replies_ok"] = True
        except Exception as error:  # noqa: BLE001
            if status is not None:
                status["replies_ok"] = False
                status["replies_error"] = str(error)
            break
        data = payload.get("data") or {}
        items = data.get("list") or []
        if not items:
            if status is not None:
                status["replies_empty"] = True
                status["replies_exhausted"] = True
            break
        reached_start = False
        for item in items:
            thread = item.get("thread_info") or {}
            post = item.get("post_info") or {}
            tid = str(thread.get("tid") or thread.get("id") or "")
            pid = str(post.get("id") or "")
            content = "".join(
                str(fragment.get("text") or "")
                for fragment in (post.get("content") or [])
                if isinstance(fragment, dict)
            )
            ts = int(post.get("time") or thread.get("create_time") or thread.get("last_time_int") or 0)
            day = datetime.fromtimestamp(ts).date() if ts else None
            if start and day and day < start:
                reached_start = True
                continue
            first_post_id = str(thread.get("first_post_id") or "")
            kind = "主题帖" if first_post_id and pid == first_post_id else "回复"
            add_post(tid, pid, thread.get("title") or "", thread.get("fname") or "", ts, kind, content)
        if reached_start:
            break
        if not data.get("has_more"):
            if status is not None:
                status["replies_exhausted"] = True
            break
        page += 1

    # 2) threads: new protobuf feed, deep pages until start date/empty/cap.
    topic_page = 0
    topic_reached_start = False
    topic_exhausted = False
    if uid:
        while topic_page < max(1, int(topic_max_pages)):
            topic_page += 1
            try:
                thread_items = _cached_thread_page(
                    fetcher, uid, topic_page, use_cache=use_cache, cache_priority=cache_priority
                )
                if status is not None:
                    status["threads_ok"] = True
                    status["topic_pages"] = topic_page
            except Exception as error:  # noqa: BLE001
                if status is not None:
                    status["threads_ok"] = False
                    status["threads_error"] = str(error)
                break
            if not thread_items:
                topic_exhausted = True
                break
            for item in thread_items:
                add_post(
                    item.get("tid"),
                    item.get("pid"),
                    item.get("title"),
                    item.get("forum"),
                    item.get("ts"),
                    "主题帖",
                    item.get("content"),
                )
            oldest = min((int(item.get("ts") or 0) for item in thread_items), default=0)
            oldest_day = datetime.fromtimestamp(oldest).date() if oldest else None
            if deep_start and start and oldest_day and oldest_day < start:
                topic_reached_start = True
                break
            if len(posts) >= count and not deep_start:
                break
        if status is not None:
            status["topic_reached_start"] = topic_reached_start
            status["topic_exhausted"] = topic_exhausted
            status["topic_truncated"] = bool(
                not topic_reached_start and not topic_exhausted and topic_page >= max(1, int(topic_max_pages))
            )
    elif portrait:
        # fallback: old PC feed type=1
        page = 1
        while page <= 8 and (len(posts) < count or collect_start):
            params = _sign(
                {
                    "pn": page,
                    "rn": reply_page_size,
                    "portrait": portrait,
                    "type": 1,
                    "subapp_type": "pc",
                    "_client_type": 20,
                },
                PC_SALT,
            )
            try:
                payload = _cached_get_json(
                    fetcher,
                    POSTS_URL + "?" + urlencode(params),
                    f"posts_{portrait[:12]}_1_{page}",
                    (_cache_user_key(uid, portrait), "thread", page),
                    use_cache=use_cache,
                    cache_priority=cache_priority,
                    variant=f"{reply_page_size}:v1",
                )
            except Exception as error:  # noqa: BLE001
                if status is not None:
                    status["threads_ok"] = False
                    status["threads_error"] = str(error)
                break
            data = payload.get("data") or {}
            items = data.get("list") or []
            if not items:
                break
            for item in items:
                thread = item.get("thread_info") or {}
                tid = str(thread.get("tid") or thread.get("id") or "")
                ts = int(thread.get("create_time") or thread.get("last_time_int") or 0)
                add_post(
                    tid,
                    "",
                    thread.get("title") or "",
                    thread.get("fname") or "",
                    ts,
                    "主题帖",
                    _strip_tags(thread.get("abstract") or ""),
                )
            if not data.get("has_more"):
                break
            page += 1

    # 未知时间的条目统一放末尾，避免“优先最早”时被 0 时间戳顶到最前。
    known = [item for item in posts if item.get("ts")]
    unknown = [item for item in posts if not item.get("ts")]
    known.sort(key=lambda item: item.get("ts") or 0, reverse=(prefer != "start"))
    # 不做类型配额：按时间排序后是什么就返回什么，避免人为改变数据。
    posts = known + unknown
    coverage_dates = [
        datetime.fromtimestamp(int(item.get("ts") or 0)).date()
        for item in posts
        if int(item.get("ts") or 0) > 0
    ]
    coverage_start = min(coverage_dates).strftime("%Y-%m-%d") if coverage_dates else ""
    coverage_end = max(coverage_dates).strftime("%Y-%m-%d") if coverage_dates else ""
    if status is not None:
        status["coverage_start"] = coverage_start
        status["coverage_end"] = coverage_end
    if uid:
        cache_key = str(uid)
        post_cache.cache().put_user(
            cache_key,
            {
                "posts": posts,
                "fetched_at": time.time(),
                "count": count,
                "requested_start": start_date,
                "requested_end": end_date,
                "requested_count": count,
                "coverage_start": coverage_start,
                "coverage_end": coverage_end,
                "start_date": start_date,
                "end_date": end_date,
                "prefer": prefer,
                "replies_exhausted": bool((status or {}).get("replies_exhausted")),
                "topic_exhausted": bool((status or {}).get("topic_exhausted")),
                "status": dict(status or {}),
                "oldest_ts": min((int(item.get("ts") or 0) for item in known), default=0),
                "newest_ts": max((int(item.get("ts") or 0) for item in known), default=0),
            },
            priority=int(cache_priority),
        )
    return posts[:count]


def cached_user_posts(
    uid: str,
    count: int,
    start_date: str = "",
    end_date: str = "",
    prefer: str = "end",
    promote: bool = True,
) -> Optional[List[Dict]]:
    """命中批量/交互缓存时返回筛选后的发言；覆盖不足返回 None。"""
    data = post_cache.cache().get_user(str(uid or ""), promote=promote)
    if not data:
        return None
    posts = list(data.get("posts") or [])
    if not posts:
        return None
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    cached_start = _parse_date(str(data.get("coverage_start") or data.get("start_date") or ""))
    cached_end = _parse_date(str(data.get("coverage_end") or data.get("end_date") or ""))
    if start and (not cached_start or start < cached_start):
        return None
    if end and (not cached_end or end > cached_end):
        return None
    filtered = []
    for item in posts:
        day = _parse_date(str(item.get("time") or ""))
        if start and day and day < start:
            continue
        if end and day and day > end:
            continue
        filtered.append(item)
    exhausted = bool(
        data.get("replies_exhausted")
        and data.get("topic_exhausted")
    )
    if len(filtered) < count and not start and not exhausted:
        # 条数不够，且回复流/主题流没有都确认到底时，交给联网补抓。
        return None
    filtered.sort(key=lambda item: item.get("ts") or 0, reverse=(prefer != "start"))
    return filtered[:count]


def fetch_user_profile(
    fetcher,
    user_id: str,
    username: str,
    portrait: str = "",
    bar_name: str = "",
    post_count: int = 20,
    start_date: str = "",
    end_date: str = "",
    prefer: str = "end",
    load_follow: bool = True,
    topic_max_pages: int = 50,
    use_cache: bool = True,
    cached_posts: Optional[List[Dict]] = None,
    cache_priority: int = 1,
) -> Dict:

    """组合查询：关注的吧（含等级）+ 发言 + 本吧等级。"""
    pb = profile_pb.fetch_profile(fetcher, user_id, portrait) if (user_id or portrait) else {}
    if pb.get("uid") and not user_id:
        user_id = str(pb["uid"])
    if pb.get("username"):
        username = pb["username"]
    if not portrait:
        portrait = pb.get("portrait") or fetch_portrait(fetcher, username)
    post_sources: Dict[str, object] = {}

    def side() -> tuple:
        if load_follow:
            follow_data = fetch_follow_forums(fetcher.clone(), user_id)
        else:
            follow_data = {"forums": [], "private": False, "error": ""}
        panel_data = fetch_panel(fetcher.clone(), username)
        return follow_data, panel_data

    with ThreadPoolExecutor(max_workers=2) as pool:
        posts_future = None
        if cached_posts is None and (portrait or user_id):
            posts_future = pool.submit(
                fetch_user_posts,
                fetcher.clone(),
                portrait,
                post_count,
                start_date,
                end_date,
                prefer,
                user_id,
                post_sources,
                topic_max_pages,
                use_cache,
                cache_priority,
            )
        side_future = pool.submit(side)
        try:
            posts = cached_posts or (posts_future.result() if posts_future is not None else [])
        except Exception:  # noqa: BLE001
            posts = []
        try:
            follow, panel = side_future.result()
        except Exception:  # noqa: BLE001
            follow = {"forums": [], "private": False, "error": ""}
            panel = {}

    if cached_posts is not None:
        post_sources["cached"] = True
        cached_data = post_cache.cache().get_user(str(user_id or ""), promote=False)
        if cached_data:
            fetched_at = float(cached_data.get("fetched_at") or 0)
            if fetched_at:
                post_sources["cached_age_minutes"] = max(0, int((time.time() - fetched_at) / 60))
            for key in ("replies_exhausted", "topic_exhausted"):
                if key in cached_data:
                    post_sources[key] = cached_data[key]
            cached_status = cached_data.get("status") or {}
            post_sources.setdefault("topic_pages", cached_status.get("topic_pages", 0))
            post_sources.setdefault("topic_truncated", cached_status.get("topic_truncated", False))
    target = (bar_name or "").rstrip("吧")
    level_in_bar = ""
    level_name = ""
    for forum in follow.get("forums") or []:
        if target and forum["name"].rstrip("吧") == target and int(forum.get("level") or 0) > 0:
            level_in_bar = str(forum["level"])
            level_name = forum.get("level_name") or ""
            break

    # 关注列表被隐藏时，用面板“等级头衔吧” + 客户端 likeForum 恢复一部分
    hidden_forums = []
    if load_follow and not follow.get("forums"):
        merged: Dict[str, Dict] = {}
        for forum in (panel.get("forums") or []) + (pb.get("forums") or []):
            name = forum.get("name") or ""
            if not name:
                continue
            level = int(forum.get("level") or 0)
            old = merged.get(name)
            if old is None or level > int(old.get("level") or 0):
                merged[name] = {"name": name, "level": level, "level_name": forum.get("level_name") or ""}
        hidden_forums = sorted(merged.values(), key=lambda item: item.get("level") or 0, reverse=True)
        if not level_in_bar:
            for forum in hidden_forums:
                if target and forum["name"].rstrip("吧") == target and int(forum.get("level") or 0) > 0:
                    level_in_bar = str(forum["level"])
                    break

    return {
        "ok": True,
        "user_id": user_id,
        "tieba_uid": str(pb.get("tieba_uid") or ""),
        "username": username,
        "nickname": pb.get("nickname") or "",
        "portrait": portrait,
        "bar_level": level_in_bar,
        "bar_level_name": level_name,
        "recent_posts": posts,
        "post_sources": post_sources,
        "followed_forums": follow.get("forums") or [],
        "followed_private": follow.get("private", False),
        "follow_error": follow.get("error", ""),
        "follow_loaded": bool(load_follow and follow.get("ok")),
        "follow_partial": bool(hidden_forums) and not follow.get("forums"),
        "hidden_forums": hidden_forums,
        "like_forum": pb.get("forums") or [],
        "priv_like": pb.get("priv_like"),
        "fans": pb.get("fans"),
        "concern": pb.get("concern"),
        "followed_count": panel.get("followed_count"),
        "post_num": pb.get("post_num") or panel.get("post_num"),
        "profile_url": PROFILE_URL.format(un=quote(username)) if username else "",
    }
