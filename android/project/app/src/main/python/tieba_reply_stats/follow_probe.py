"""按候选吧探测用户是否关注（FR-015）。

接口：
  GET  /f/commit/share/fnameShareApi?fname=...   -> fid
  POST /c/f/forum/getUserForumLevelInfo          -> is_follow / level

匿名实测可用；不依赖 aiotieba。
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, Iterable, List, Optional

FID_URL = "http://tieba.baidu.com/f/commit/share/fnameShareApi"
LEVEL_URL = "http://tiebac.baidu.com/c/f/forum/getUserForumLevelInfo"
CLIENT_VERSION = "22.12.1.0"

_fid_cache: Dict[str, int] = {}


def clean_name(name: str) -> str:
    text = (name or "").strip()
    if text.endswith("吧") and len(text) > 2:
        text = text[:-1]
    return text


def candidate_bars(
    user: Dict,
    profile: Dict,
    blacklist: Dict[str, List[str]],
    limit: int = 30,
) -> List[str]:
    """只从本帖发言、最近发言、本地标记里取候选，排除已知关注。"""
    known = set()
    for key in ("followed_forums", "hidden_forums", "like_forum", "probed_forums"):
        for forum in profile.get(key) or []:
            name = clean_name(forum.get("name") or "")
            if name:
                known.add(name.lower())

    result: List[str] = []
    seen = set()

    def add(name: str) -> None:
        text = clean_name(name)
        key = text.lower()
        if not text or key in known or key in seen:
            return
        seen.add(key)
        result.append(text)

    for bar in user.get("bars") or []:
        add(bar)
    for post in profile.get("recent_posts") or []:
        add(post.get("bar") or "")
    for level in ("ban", "warn", "safe"):
        for bar in blacklist.get(level) or []:
            add(bar)
    return result[:limit]


def resolve_fid(fetcher, fname: str) -> int:
    key = clean_name(fname).lower()
    if key in _fid_cache:
        return _fid_cache[key]
    data = fetcher.get_json(f"{FID_URL}?fname={urllib_quote(fname)}&ie=utf-8")
    if data.get("no") not in (0, "0", None):
        raise RuntimeError(f"解析吧失败：{data.get('error') or data.get('no')}")
    fid = int((data.get("data") or {}).get("fid") or 0)
    if not fid:
        raise RuntimeError("fid 为 0")
    _fid_cache[key] = fid
    return fid


def urllib_quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text, safe="")


def _sign_form(data: Dict) -> Dict:
    items = [(key, str(value)) for key, value in data.items()]
    digest = hashlib.md5()
    for key, value in sorted(items):
        digest.update(f"{key}={value}".encode())
    digest.update(b"tiebaclient!!!")
    signed = dict(data)
    signed["sign"] = digest.hexdigest()
    return signed


def probe_forum(fetcher, fname: str, portrait: str) -> Dict:
    fid = resolve_fid(fetcher, fname)
    data = fetcher.post_json(
        LEVEL_URL,
        _sign_form(
            {
                "BDUSS": fetcher.cookie_dict().get("BDUSS", ""),
                "_client_version": CLIENT_VERSION,
                "forum_id": fid,
                "friend_portrait": portrait,
            }
        ),
    )
    if data.get("error_code") not in (0, "0", None):
        raise RuntimeError(f"探测失败：{data.get('error_msg') or data.get('error_code')}")
    payload = data.get("data") or {}
    info = payload.get("user_forum_info") or payload
    return {
        "name": clean_name(fname),
        "is_follow": bool(info.get("is_follow")),
        "follow_days": int(info.get("follow_days") or 0),
        "level": int(info.get("level_id") or info.get("level") or 0),
        "level_name": info.get("level_name") or "",
    }


def probe_forums(
    fetcher,
    uid: str,
    portrait: str,
    candidates: Iterable[str],
    log: Optional[Callable[[str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> List[Dict]:
    results: List[Dict] = []
    items = list(candidates)
    for index, bar in enumerate(items, start=1):
        if should_stop and should_stop():
            break
        if log:
            log(f"  探测关注 {index}/{len(items)}：{bar}")
        try:
            info = probe_forum(fetcher, bar, portrait)
        except Exception as error:  # noqa: BLE001
            if log:
                log(f"    跳过 {bar}：{error}")
            continue
        if info["is_follow"]:
            results.append(info)
    return results
