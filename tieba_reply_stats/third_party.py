"""恋文（第三方）公开数据适配器。

只做只读请求，不发送 Cookie/BDUSS，不写入官方缓存。
接口并非百度官方 API，随时可能变化。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

BASE_URL = "https://tb.anova.me"
USER_AGENT = "TiebaReplyStats/1.7.2 (+https://tb.anova.me/)"
TIMEOUT = 15


def _get(path: str, params: Dict[str, object]) -> Dict:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in ("", None)})
    url = f"{BASE_URL}{path}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        raw = response.read()
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as error:
        raise ValueError("第三方返回不是有效 JSON") from error
    if not isinstance(data, dict):
        raise ValueError("第三方返回格式异常")
    return data


def _identity(uid: str, username: str, nickname: str = "") -> Dict[str, str]:
    if uid:
        return {"uid": uid}
    if username:
        return {"username": username}
    if nickname:
        return {"nickname": nickname}
    raise ValueError("需要贴吧ID、用户名或昵称")


def fetch_posts_page(
    uid: str,
    username: str = "",
    page: int = 1,
    *,
    use_old: bool = False,
    nickname: str = "",
) -> Dict:
    """读取一页第三方发言。

    返回 ``{"items": [...], "has_next": bool, "source": "new"/"old"}``。
    """
    path = "/getPosts" if use_old else "/getPostsNew"
    params: Dict[str, object] = dict(_identity(uid.strip(), username.strip(), nickname.strip()))
    params["page"] = max(1, int(page))
    data = _get(path, params)
    posts = data.get("posts")
    if not isinstance(posts, list):
        posts = []
    items: List[Dict] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        href = str(post.get("href") or "")
        items.append(
            {
                "title": str(post.get("title") or ""),
                "content": str(post.get("content") or ""),
                "href": href,
                "nickname": str(post.get("nickname") or ""),
                "portrait": str(post.get("portrait") or ""),
                "source": "old" if use_old else "new",
            }
        )
    has_next = bool(data.get("hasNext")) if not use_old else bool(items)
    return {"items": items, "has_next": has_next, "source": "old" if use_old else "new", "message": str(data.get("msg") or "")}


def fetch_level(uid: str, fname: str, username: str = "") -> Optional[Dict]:
    """查询已知吧等级；uid 必须是 tieba_uid。"""
    if not fname:
        return None
    params: Dict[str, object] = dict(_identity(uid.strip(), username.strip()))
    params["fname"] = fname
    data = _get("/getLevel", params)
    result = data.get("result")
    if not isinstance(result, list) or not result:
        return None
    first = result[0]
    if not isinstance(first, dict):
        return None
    try:
        level = int(first.get("level") or 0)
    except (TypeError, ValueError):
        return None
    return {
        "level": level,
        "exp": first.get("exp"),
        "like": first.get("like"),
        "fname": str(first.get("fname") or fname),
        "nickname": str((data.get("user") or {}).get("nickname") or ""),
        "portrait": str((data.get("user") or {}).get("avatar") or ""),
    }


def fetch_all_levels(username: str) -> List[Dict]:
    """旧版等级接口：按用户名返回该用户有等级的全部吧。"""
    name = (username or "").strip()
    if not name:
        return []
    data = _get("/getLevelOld", {"username": name})
    result = data.get("result")
    if not isinstance(result, list):
        return []
    rows: List[Dict] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        fname = str(item.get("fname") or "").strip()
        try:
            level = int(item.get("level") or 0)
        except (TypeError, ValueError):
            continue
        if not fname or level <= 0:
            continue
        rows.append(
            {
                "name": fname,
                "level": level,
                "level_source": "恋文（第三方）",
                "source": "恋文等级",
            }
        )
    return rows


def parse_post_link(href: str) -> Dict[str, str]:
    """从贴吧链接提取 tid / pid / 规范化链接。"""
    import re

    text = (href or "").strip()
    match = re.search(r"tieba\.baidu\.com/p/(\d+)", text, re.I)
    if not match:
        match = re.search(r"/p/(\d+)", text)
    if not match:
        return {}
    tid = match.group(1)
    pid_match = re.search(r"[?&#]pid=(\d+)", text, re.I)
    pid = pid_match.group(1) if pid_match else ""
    url = f"https://tieba.baidu.com/p/{tid}"
    if pid:
        url += f"?pid={pid}"
    return {"tid": tid, "pid": pid, "url": url}
