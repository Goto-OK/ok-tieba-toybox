"""贴吧新版网页（PC 新版，界面类似 App）的接口封装。

新版网页的帖子页数据来自：
    POST https://tieba.baidu.com/c/f/pb/page_pc
    form: kz=<帖子ID>&pn=<页码>&r=0&lz=0&_client_type=20&sign=<PC签名>

返回 JSON 里：
    page      {current_page, total_page, has_more}
    post_list 楼层列表（author_id / floor / content / time / sub_post_number）
    user_list 本帖出现的用户（id / name / level_id / level_name / portrait）

关键点：user_list 里**包含只回复楼中楼的用户**，并且带本吧等级，
所以可以用它把“楼中楼作者”的等级补全，不需要再一个个查关注列表。
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, Optional

PC_SALT = b"36770b1f34c9bbf2e7d1a99d2b82fa9e"
PB_PAGE_URL = "https://tieba.baidu.com/c/f/pb/page_pc"
NESTED_URL = "https://tieba.baidu.com/c/f/pb/nestedFloor"


def _sign(params: Dict[str, object]) -> Dict[str, object]:
    data = sorted(params.items(), key=lambda item: item[0])
    md5 = hashlib.md5()
    for key, value in data:
        md5.update(f"{key}={value}".encode())
    md5.update(PC_SALT)
    signed = dict(data)
    signed["sign"] = md5.hexdigest()
    return signed


def _level_from_user(user: Dict) -> tuple:
    """从用户对象里取本吧等级。

    普通字段 level_id 有时是 0（楼中楼作者常见），真正的等级藏在
    user_show_info.feed_head.main_data[].custom.data 里（style=forum_level）。
    """
    if not isinstance(user, dict):
        return "", ""
    level = user.get("level_id")
    if level:
        return str(level), user.get("level_name") or ""
    info = user.get("user_show_info") or {}
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except Exception:  # noqa: BLE001
            info = {}
    head = info.get("feed_head") or {}
    for item in head.get("main_data") or []:
        custom = item.get("custom") or {}
        if custom.get("style") != "forum_level":
            continue
        try:
            data = json.loads(custom.get("data") or "{}")
        except Exception:  # noqa: BLE001
            continue
        level_id = data.get("level_id")
        if level_id:
            return str(level_id), data.get("level_name") or ""
    return "", ""


def _user_entry(user: Dict, uid: str, level: str, level_name: str) -> Dict[str, str]:
    return {
        "uid": uid,
        "name": user.get("name") or "",
        "nick": user.get("name_show") or "",
        "portrait": str(user.get("portrait") or "").split("?")[0],
        "level": level,
        "level_name": level_name,
    }


def fetch_page_users(
    fetcher,
    tid: str,
    max_pages: int = 200,
    log=None,
) -> Dict[str, Dict[str, str]]:
    """抓新版帖子页的 user_list，返回 {用户ID: {name, level, level_name}}。"""
    users: Dict[str, Dict[str, str]] = {}
    if not tid:
        return users
    page = 1
    total_page = 1
    while page <= max_pages:
        params = _sign({"kz": tid, "pn": page, "r": 0, "lz": 0, "_client_type": 20})
        try:
            payload = fetcher.post_json(PB_PAGE_URL, params, name=f"pb_{tid}_{page}")
        except Exception:  # noqa: BLE001
            break
        if payload.get("error_code"):
            break
        page_info = payload.get("page") or {}
        total_page = int(page_info.get("total_page") or page)
        for item in payload.get("user_list") or []:
            uid = str(item.get("id") or "")
            level, level_name = _level_from_user(item)
            if not uid or not level:
                continue
            if uid not in users:
                users[uid] = _user_entry(item, uid, level, level_name)
        if not page_info.get("has_more") or page >= total_page:
            break
        page += 1
    return users


def fetch_nested_users(fetcher, tid: str, floors, log=None) -> Dict[str, Dict[str, str]]:
    """抓每层楼中楼作者（新版 nestedFloor 接口），返回 {用户ID: 等级信息}。

    page_pc 的 user_list 不一定包含楼中楼作者；nestedFloor 每次返回 10 条，
    用 offset 翻页。作者的 level_id 常为 0，真实等级在 user_show_info 里。
    """
    users: Dict[str, Dict[str, str]] = {}
    if not tid:
        return users
    for floor in floors:
        if not getattr(floor, "reply_num", 0) or not getattr(floor, "pid", ""):
            continue
        offset = 0
        for _ in range(60):
            params = _sign(
                {"post_id": floor.pid, "thread_id": tid, "offset": offset, "_client_type": 20}
            )
            try:
                payload = fetcher.post_json(NESTED_URL, params, name=f"nested_{floor.pid}_{offset}")
            except Exception:  # noqa: BLE001
                break
            if payload.get("error_code"):
                break
            data = payload.get("data") or {}
            posts = data.get("post_list") or []
            for post in posts:
                author = post.get("author") or {}
                uid = str(author.get("id") or "")
                if not uid or uid in users:
                    continue
                level, level_name = _level_from_user(author)
                if level:
                    users[uid] = _user_entry(author, uid, level, level_name)
            page = data.get("page") or {}
            if not page.get("has_more") or not posts:
                break
            new_offset = int(page.get("offset") or (offset + len(posts)))
            if new_offset <= offset:
                break
            offset = new_offset
    return users


def fill_thread_levels(thread, fetcher, log=None) -> int:
    """用新版网页接口给楼层/楼中楼作者补全等级，返回补全的人数。

    先查 page_pc 的 user_list；楼中楼作者不在其中的，再用 nestedFloor 逐层查。
    匹配顺序：用户ID → 头像 → 用户名 → 昵称。
    """
    tid = thread.meta.tid
    mapping = fetch_page_users(fetcher, tid, log=log)

    def apply(users: Dict[str, Dict[str, str]]) -> int:
        by_name = {}
        by_nick = {}
        by_portrait = {}
        for info in users.values():
            if info.get("name"):
                by_name.setdefault(info["name"], info)
            if info.get("nick"):
                by_nick.setdefault(info["nick"], info)
            if info.get("portrait"):
                by_portrait.setdefault(info["portrait"], info)

        def lookup(author_id: str, username: str, nick: str, portrait: str) -> Optional[Dict[str, str]]:
            portrait_key = str(portrait or "").split("?")[0]
            return (
                users.get(author_id)
                or (by_portrait.get(portrait_key) if portrait_key else None)
                or by_name.get(username)
                or by_nick.get(nick)
                or by_name.get(nick)
                or None
            )

        count = 0
        for floor in thread.floors:
            info = lookup(floor.author_id, floor.author_name, floor.author, floor.portrait)
            if not info:
                continue
            if not floor.author_id and info.get("uid"):
                floor.author_id = info["uid"]
            if not floor.level:
                floor.level = info["level"]
                count += 1
            if not floor.badge:
                floor.badge = info["level_name"]
        for comment in thread.comments:
            info = lookup(comment.author_id, comment.author_name, comment.author, comment.portrait)
            if not info:
                continue
            if not comment.author_id and info.get("uid"):
                comment.author_id = info["uid"]
            if not comment.level:
                comment.level = info["level"]
                count += 1
        return count

    filled = apply(mapping) if mapping else 0

    # 还有没补到的楼中楼 → 用 nestedFloor 逐层查（只查有缺口的楼层）
    floors_need = []
    for floor in thread.floors:
        if not getattr(floor, "reply_num", 0):
            continue
        if any(not comment.level and comment.floor_no == floor.post_no for comment in thread.comments):
            floors_need.append(floor)
    if floors_need:
        nested = fetch_nested_users(fetcher, tid, floors_need, log=log)
        if nested:
            mapping.update(nested)
            filled += apply(nested)
    return filled

