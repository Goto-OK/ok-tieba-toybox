"""吧务删除内容（FR-013，只读）。

接口：
  GET /mo/q/manage/getRecoverList
  GET /mo/q/bawu/getRecoverInfo

需要登录 + 吧务权限；实际使用通常还要 STOKEN。
"""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlencode

from .follow_probe import resolve_fid

RECOVER_LIST_URL = "https://tieba.baidu.com/mo/q/manage/getRecoverList"
RECOVER_INFO_URL = "https://tieba.baidu.com/mo/q/bawu/getRecoverInfo"


class BawuError(RuntimeError):
    pass


def _text(mapping: Dict, *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _parse_row(item: Dict) -> Dict:
    thread = item.get("thread_info") or {}
    post = item.get("post_info") or {}
    sub = item.get("sub_post_info") or {}
    op = item.get("op_info") or {}
    user = sub or post or thread
    if sub:
        kind = "回复"
        content = _text(sub, "abstract", "content")
        pid = _text(sub, "pid")
    elif post:
        kind = "回复"
        content = _text(post, "abstract", "content")
        pid = _text(post, "pid")
    else:
        kind = "主题"
        content = _text(thread, "abstract", "text", "content")
        pid = ""
    return {
        "kind": kind,
        "title": _text(thread, "title"),
        "content": content,
        "author": _text(user, "user_nickname", "user_name", "name"),
        "username": _text(user, "user_name"),
        "uid": _text(user, "id", "user_id", "uid"),
        "tid": _text(thread, "tid", "thread_id"),
        "pid": pid,
        "op_time": int(op.get("time") or 0),
        "op_name": _text(op, "name"),
        "is_hide": bool(int(item.get("is_frs_mask") or 0)),
    }


def fetch_recovers(
    fetcher,
    fname: str,
    uid: str = "",
    pn: int = 1,
    rn: int = 10,
) -> Dict[str, Any]:
    fid = resolve_fid(fetcher, fname)
    params: Dict[str, Any] = {"rn": rn, "forum_id": fid, "pn": pn, "type": 1, "sub_type": 1}
    if uid:
        params["uid"] = int(uid)
    data = fetcher.get_json(f"{RECOVER_LIST_URL}?{urlencode(params)}")
    if data.get("no") not in (0, "0", None):
        raise BawuError(f"查询失败：{data.get('error') or data.get('no')}")
    payload = data.get("data") or {}
    rows = [_parse_row(item) for item in payload.get("thread_list") or []]
    page = payload.get("page") or {}
    return {
        "rows": rows,
        "current": int(page.get("current_page") or pn),
        "total": int(page.get("total_page") or 1),
    }


def fetch_recover_info(fetcher, fname: str, tid: str, pid: str = "0") -> Dict[str, Any]:
    fid = resolve_fid(fetcher, fname)
    params = {
        "forum_id": fid,
        "thread_id": tid,
        "post_id": pid or 0,
        "type": 1,
        "sub_type": 2 if pid else 1,
    }
    data = fetcher.get_json(f"{RECOVER_INFO_URL}?{urlencode(params)}")
    if data.get("no") not in (0, "0", None):
        raise BawuError(f"获取详情失败：{data.get('error') or data.get('no')}")
    payload = data.get("data") or {}
    thread = payload.get("thread_info") or {}
    user = payload.get("user_info") or {}
    texts: List[str] = []
    for part in thread.get("content_detail") or []:
        if int(part.get("type") or 0) == 1 and part.get("text"):
            texts.append(str(part["text"]))
    return {
        "title": _text(thread, "title"),
        "content": "".join(texts),
        "tid": _text(thread, "thread_id", "tid"),
        "pid": _text(thread, "post_id"),
        "author": _text(user, "user_nickname", "user_name", "name"),
        "username": _text(user, "user_name"),
        "uid": _text(user, "id", "user_id", "uid"),
    }
