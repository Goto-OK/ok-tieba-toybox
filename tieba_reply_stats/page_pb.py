"""Anonymous Tieba app protobuf: `/c/f/pb/page?cmd=302001`.

This endpoint returns public thread floors and the first 10 comments per floor
**without any login cookie**, unlike the web HTML pages (which return 403).

Request layout (PbPageReqIdl):
  data = 1 {
    common = 25 { _client_type = 1, _client_version = 2, BDUSS = 10 }
    kz = 4, lz = 5, r = 6, with_floor = 8, floor_rn = 9,
    rn = 13, pn = 18, floor_sort_type = 74
  }

Response (PbPageResIdl):
  error = 1, data = 2 {
    page = 3, post_list = 6 repeated, thread = 8, user_list = 13 repeated
  }
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

from .fetch import CAPTCHA_MARKERS, CaptchaError, RateLimitError, _retry_after_seconds, wait_request_gate
from .models import Comment, Floor, ThreadData, ThreadMeta

PAGE_URL = "https://tiebac.baidu.com/c/f/pb/page?cmd=302001"
CLIENT_VERSION = b"12.64.1.1"
USER_AGENT = "bdtb for Android 12.64.1.1"
REPLY_PREFIX_RE = re.compile(r"^回复\s*@?([^:：\n]{1,40})\s*[:：]\s*")


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _fv(number: int, value: int) -> bytes:
    return _varint((number << 3) | 0) + _varint(value)


def _fb(number: int, payload: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(payload)) + payload


def _read_varint(data: bytes, index: int):
    result = 0
    shift = 0
    while True:
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, index
        shift += 7


def _fields(data: bytes):
    index = 0
    while index < len(data):
        try:
            key, index = _read_varint(data, index)
        except IndexError:
            return
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, index = _read_varint(data, index)
        elif wire == 2:
            length, index = _read_varint(data, index)
            value = data[index : index + length]
            index += length
        elif wire == 5:
            value = data[index : index + 4]
            index += 4
        elif wire == 1:
            value = data[index : index + 8]
            index += 8
        else:
            return
        yield number, wire, value


def _msg(data: bytes, number: int) -> Optional[bytes]:
    for num, wire, value in _fields(data):
        if num == number and wire == 2:
            return value
    return None


def _msgs(data: bytes, number: int) -> List[bytes]:
    return [value for num, wire, value in _fields(data) if num == number and wire == 2]


def _num(data: bytes, number: int) -> int:
    for num, wire, value in _fields(data):
        if num == number and wire == 0:
            return value
    return 0


def _text(data: bytes, number: int) -> str:
    value = _msg(data, number)
    if value is None:
        return ""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("gb18030", "replace")


def _content_text(container: bytes, field: int) -> str:
    parts: List[str] = []
    for blob in _msgs(container, field):
        kind = _num(blob, 1)
        text = _text(blob, 2)
        src = _text(blob, 4)
        if kind == 0 and text:
            parts.append(text)
        elif kind == 3 or src:
            parts.append("[图片]")
        elif text:
            parts.append(text)
    return "".join(parts).strip()


def _content_from_msg(message: bytes, field: int) -> str:
    return _content_text(message, field)


def _parse_user(blob: bytes) -> Dict:
    priv = _msg(blob, 45) or b""
    return {
        "uid": str(_num(blob, 2) or ""),
        "tieba_uid": _text(blob, 120) or "",
        "username": _text(blob, 3),
        "nickname": _text(blob, 4),
        "portrait": _text(blob, 5).split("?")[0],
        "level": _num(blob, 23),
        "is_bawu": _num(blob, 25),
        "fans": _num(blob, 30),
        "concern": _num(blob, 31),
        "post_num": _num(blob, 37),
        "priv_like": _num(priv, 2),
    }


def _parse_thread(blob: bytes) -> Dict:
    author = _msg(blob, 18) or b""
    return {
        "tid": str(_num(blob, 1) or ""),
        "title": _text(blob, 3),
        "reply_num": _num(blob, 4),
        "fid": str(_num(blob, 27) or ""),
        "fname": _text(blob, 28),
        "first_post_id": str(_num(blob, 40) or ""),
        "create_time": _num(blob, 45),
        "author_id": str(_num(blob, 56) or _num(author, 2) or ""),
        "author": _parse_user(author) if author else {},
        "first_post_content": _content_from_msg(blob, 142),
    }


def _parse_page(blob: bytes) -> Dict:
    return {
        "current": _num(blob, 3) or 1,
        "total": _num(blob, 5) or 1,
        "has_more": _num(blob, 6),
    }


def _parse_floor(post: bytes, thread: Dict, users: Dict[str, Dict]) -> Dict:
    author = _msg(post, 23) or b""
    author_info = _parse_user(author) if author else {}
    uid = str(_num(post, 19) or author_info.get("uid") or "")
    if uid in users:
        merged = dict(users[uid])
        merged.update({key: value for key, value in author_info.items() if value})
        author_info = merged
    pid = str(_num(post, 1) or "")
    content = _content_text(post, 5)
    if not content and pid == thread.get("first_post_id"):
        content = thread.get("first_post_content") or ""
    return {
        "post_no": _num(post, 3),
        "pid": pid,
        "author": author_info.get("nickname") or author_info.get("username") or "匿名用户",
        "author_name": author_info.get("username") or "",
        "author_id": uid,
        "tieba_uid": author_info.get("tieba_uid") or "",
        "portrait": author_info.get("portrait") or "",
        "time": _num(post, 4),
        "content": content,
        "reply_num": _num(post, 13),
        "level": author_info.get("level") or 0,
        "is_op": bool(uid and uid == thread.get("author_id")),
    }


def _parse_comments(post: bytes, floor: Dict, thread: Dict, users: Dict[str, Dict]) -> List[Dict]:
    result = []
    sub_container = _msg(post, 15) or b""
    for sub in _msgs(sub_container, 2):
        uid = str(_num(sub, 4) or "")
        author = _msg(sub, 7) or b""
        author_info = _parse_user(author) if author else {}
        if uid in users:
            merged = dict(users[uid])
            merged.update({key: value for key, value in author_info.items() if value})
            author_info = merged
        text = _content_text(sub, 2)
        reply_to = ""
        match = REPLY_PREFIX_RE.match(text)
        if match:
            reply_to = match.group(1).strip()
            text = text[match.end() :].lstrip()
        result.append(
            {
                "floor_no": floor["post_no"],
                "pid": str(_num(sub, 1) or ""),
                "author": author_info.get("nickname") or author_info.get("username") or "匿名用户",
                "author_name": author_info.get("username") or "",
                "author_id": uid,
                "tieba_uid": author_info.get("tieba_uid") or "",
                "portrait": author_info.get("portrait") or "",
                "time": _num(sub, 3),
                "content": text,
                "reply_to": reply_to,
                "level": author_info.get("level") or 0,
                "is_op": bool(uid and uid == thread.get("author_id")),
            }
        )
    return result


def build_request(
    tid: str,
    pn: int = 1,
    rn: int = 30,
    with_comments: bool = True,
    comment_rn: int = 10,
    bduss: str = "",
) -> bytes:
    """Encode PbPageReqIdl bytes (without the multipart wrapper)."""
    common = b"".join(
        [
            _fv(1, 2),
            _fb(2, CLIENT_VERSION),
        ]
    )
    if bduss:
        common += _fb(10, bduss.encode())
    data = b"".join(
        [
            _fb(25, common),
            _fv(4, int(tid)),
            _fv(5, 0),
            _fv(6, 0),
            _fv(8, 1 if with_comments else 0),
            _fv(9, comment_rn),
            _fv(13, rn),
            _fv(18, pn),
            _fv(74, 0),
        ]
    )
    return _fb(1, data)


def _request(
    fetcher,
    tid: str,
    pn: int,
    rn: int,
    with_comments: bool,
    comment_rn: int,
    bduss: Optional[str] = None,
) -> bytes:
    if bduss is None:
        bduss = fetcher.cookie_dict().get("BDUSS", "") if fetcher is not None else ""
    payload = build_request(tid, pn, rn, with_comments, comment_rn, bduss)
    boundary = "-*_r1999"
    body = (
        (f'--{boundary}\r\nContent-Disposition: form-data; name="data"; filename="file"\r\n\r\n').encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        PAGE_URL,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "x_bd_data_type": "protobuf",
        },
    )
    wait_request_gate()
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        body = error.read() if error.fp else b""
        text = body[:6000].decode("utf-8", "ignore")
        if error.code in (403, 412) or any(marker in text for marker in CAPTCHA_MARKERS):
            raise CaptchaError("游客模式请求被百度安全验证拦截。") from error
        if error.code == 429:
            raise RateLimitError(
                "游客模式请求被限流（HTTP 429）。",
                _retry_after_seconds(error.headers),
            ) from error
        raise


def fetch_page(
    fetcher,
    tid: str,
    pn: int = 1,
    with_comments: bool = True,
    rn: int = 30,
    comment_rn: int = 10,
    bduss: Optional[str] = None,
) -> Dict:
    raw = _request(fetcher, tid, pn, rn, with_comments, comment_rn, bduss)
    return parse_response(raw, with_comments)


def parse_response(raw: bytes, with_comments: bool = True) -> Dict:
    """Decode a PbPageResIdl response into a plain dict."""
    error = _msg(raw, 1) or b""
    code = _num(error, 1)
    if code:
        raise RuntimeError(f"贴吧接口错误 {code}: {_text(error, 2)}")
    data = _msg(raw, 2) or b""
    thread = _parse_thread(_msg(data, 8) or b"")
    page = _parse_page(_msg(data, 3) or b"")
    users: Dict[str, Dict] = {}
    for blob in _msgs(data, 13):
        user = _parse_user(blob)
        if user["uid"]:
            users[user["uid"]] = user
    floors = [_parse_floor(post, thread, users) for post in _msgs(data, 6)]
    comments: List[Dict] = []
    if with_comments:
        for post in _msgs(data, 6):
            floor = _parse_floor(post, thread, users)
            comments.extend(_parse_comments(post, floor, thread, users))
    return {
        "thread": thread,
        "page": page,
        "users": users,
        "floors": floors,
        "comments": comments,
        "forum": _text(_msg(data, 2) or b"", 2),
    }


def _to_datetime(timestamp: int) -> Optional[datetime]:
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(timestamp)
    except (OverflowError, OSError, ValueError):
        return None


def _merge_page(thread: ThreadData, data: Dict, seen_floors: set) -> None:
    seen_comments = {comment.pid for comment in thread.comments if comment.pid}
    for row in data["floors"]:
        if not row["post_no"] or row["pid"] in seen_floors:
            continue
        seen_floors.add(row["pid"])
        thread.floors.append(
            Floor(
                post_no=row["post_no"],
                pid=row["pid"],
                author=row["author"],
                author_name=row["author_name"],
                author_id=row["author_id"],
                tieba_uid=row.get("tieba_uid", ""),
                portrait=row["portrait"],
                posted_at=_to_datetime(row["time"]),
                content=row["content"],
                reply_num=row["reply_num"],
                is_op=row["is_op"],
                level=str(row["level"]) if row["level"] else "",
            )
        )
    for row in data["comments"]:
        if row["pid"] and row["pid"] in seen_comments:
            continue
        if row["pid"]:
            seen_comments.add(row["pid"])
        thread.comments.append(
            Comment(
                floor_no=row["floor_no"],
                floor_author="",
                pid=row["pid"],
                author=row["author"],
                author_name=row["author_name"],
                author_id=row["author_id"],
                tieba_uid=row.get("tieba_uid", ""),
                portrait=row["portrait"],
                posted_at=_to_datetime(row["time"]),
                content=row["content"],
                reply_to=row["reply_to"],
                is_op=row["is_op"],
                level=str(row["level"]) if row["level"] else "",
            )
        )


def resume_thread_anon(url: str, thread: ThreadData, fetcher, options) -> ThreadData:
    """只补失败页和失败楼中楼，不重抓已完成页。"""
    tid = thread.meta.tid
    seen_floors = {floor.pid for floor in thread.floors}
    for pn in list(dict.fromkeys(thread.failed_pages)):
        try:
            data = fetch_page(fetcher, tid, pn, options.include_comments, 30, 10, bduss="")
            _merge_page(thread, data, seen_floors)
            thread.failed_pages.remove(pn)
        except (CaptchaError, RateLimitError) as error:
            thread.complete = False
            thread.warnings.append(f"重试第 {pn} 页仍失败：{error}")
            break
        except Exception as error:  # noqa: BLE001
            thread.complete = False
            thread.warnings.append(f"重试第 {pn} 页失败：{error}")
            break
    if thread.failed_comment_floors and options.include_comments:
        fill_comments_anon(
            thread,
            fetcher,
            options,
            only_floors=set(thread.failed_comment_floors),
        )
    thread.complete = not thread.failed_pages and not thread.failed_comment_floors
    return thread


def collect_thread_anon(
    url: str,
    fetcher,
    options,
    resume_thread: Optional[ThreadData] = None,
) -> ThreadData:
    """Collect a thread through the anonymous app endpoint."""
    from .collect import extract_tid

    tid = extract_tid(url)
    if resume_thread is not None:
        return resume_thread_anon(url, resume_thread, fetcher, options)
    first = fetch_page(fetcher, tid, 1, options.include_comments, 30, 10, bduss="")
    thread = first["thread"]
    page = first["page"]
    meta = ThreadMeta(
        tid=tid,
        fid=thread.get("fid") or "",
        title=thread.get("title") or "",
        forum=thread.get("fname") or first.get("forum") or "",
        url=url,
        total_page=page.get("total") or 1,
        reply_num=thread.get("reply_num") or 0,
        mode="guest",
    )
    floors: List[Floor] = []
    comments: List[Comment] = []
    seen_floors = set()

    def add_page(data: Dict) -> None:
        for row in data["floors"]:
            if not row["post_no"] or row["pid"] in seen_floors:
                continue
            seen_floors.add(row["pid"])
            floors.append(
                Floor(
                    post_no=row["post_no"],
                    pid=row["pid"],
                    author=row["author"],
                    author_name=row["author_name"],
                    author_id=row["author_id"],
                    tieba_uid=row.get("tieba_uid", ""),
                    portrait=row["portrait"],
                    posted_at=_to_datetime(row["time"]),
                    content=row["content"],
                    reply_num=row["reply_num"],
                    is_op=row["is_op"],
                    level=str(row["level"]) if row["level"] else "",
                )
            )
        for row in data["comments"]:
            comments.append(
                Comment(
                    floor_no=row["floor_no"],
                    floor_author="",
                    pid=row["pid"],
                    author=row["author"],
                    author_name=row["author_name"],
                    author_id=row["author_id"],
                    tieba_uid=row.get("tieba_uid", ""),
                    portrait=row["portrait"],
                    posted_at=_to_datetime(row["time"]),
                    content=row["content"],
                    reply_to=row["reply_to"],
                    is_op=row["is_op"],
                    level=str(row["level"]) if row["level"] else "",
                )
            )

    if options.log:
        options.log(f"  游客模式：{meta.forum or '?'} · {meta.title or tid}")
    add_page(first)

    total = page.get("total") or 1
    max_pages = options.max_pages or total
    warnings: List[str] = []
    failed_pages: List[int] = []
    complete = True
    for pn in range(2, min(total, max_pages) + 1):
        if options.should_stop and options.should_stop():
            break
        try:
            add_page(fetch_page(fetcher, tid, pn, options.include_comments, 30, 10, bduss=""))
        except (CaptchaError, RateLimitError) as error:
            complete = False
            failed_pages.append(pn)
            warnings.append(f"第 {pn} 页未抓完：{error}")
            if options.log:
                options.log(f"  第 {pn} 页被拦截，保留已完成页：{error}")
            break
        except Exception as error:  # noqa: BLE001
            complete = False
            failed_pages.append(pn)
            warnings.append(f"第 {pn} 页失败：{error}")
            if options.log:
                options.log(f"  第 {pn} 页失败：{error}")
            break

    floors.sort(key=lambda item: item.post_no)
    thread_data = ThreadData(
        meta=meta,
        floors=floors,
        comments=comments,
        warnings=warnings,
        complete=complete,
        failed_pages=failed_pages,
    )
    fill_comments_anon(thread_data, fetcher, options)
    comments = thread_data.comments
    comments.sort(key=lambda item: (item.floor_no, item.pid))
    for floor in floors:
        for comment in comments:
            if comment.floor_no == floor.post_no and not comment.floor_author:
                comment.floor_author = floor.author
    if options.log:
        options.log(f"  完成：{len(floors)} 楼 / {len(comments)} 条楼中楼（免登录）")
    return thread_data


FLOOR_URL = "https://tiebac.baidu.com/c/f/pb/floor?cmd=302002"


def build_floor_request(tid: str, pid: str, pn: int = 1, bduss: str = "") -> bytes:
    common = b"".join([_fv(1, 2), _fb(2, CLIENT_VERSION)])
    if bduss:
        common += _fb(10, bduss.encode())
    data = b"".join(
        [
            _fb(9, common),
            _fv(1, int(tid)),
            _fv(2, int(pid)),
            _fv(4, pn),
            _fv(19, 0),
        ]
    )
    return _fb(1, data)


def _floor_request(fetcher, tid: str, pid: str, pn: int, bduss: str = "") -> bytes:
    payload = build_floor_request(tid, pid, pn, bduss)
    boundary = "-*_r1999"
    body = (
        (f'--{boundary}\r\nContent-Disposition: form-data; name="data"; filename="file"\r\n\r\n').encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        FLOOR_URL,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "x_bd_data_type": "protobuf",
        },
    )
    wait_request_gate()
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        body = error.read() if error.fp else b""
        text = body[:6000].decode("utf-8", "ignore")
        if error.code in (403, 412) or any(marker in text for marker in CAPTCHA_MARKERS):
            raise CaptchaError("游客模式请求被百度安全验证拦截。") from error
        if error.code == 429:
            raise RateLimitError(
                "游客模式请求被限流（HTTP 429）。",
                _retry_after_seconds(error.headers),
            ) from error
        raise


def parse_floor_response(raw: bytes) -> Dict:
    error = _msg(raw, 1) or b""
    code = _num(error, 1)
    if code:
        raise RuntimeError(f"贴吧接口错误 {code}: {_text(error, 2)}")
    data = _msg(raw, 2) or b""
    page = _parse_page(_msg(data, 1) or b"")
    post = _msg(data, 3) or b""
    floor_no = _num(post, 3)
    comments: List[Dict] = []
    for sub in _msgs(data, 4):
        fake_post = _fb(15, _fb(2, sub))
        comments.extend(_parse_comments(fake_post, {"post_no": floor_no}, {}, {}))
    has_more = bool(page.get("has_more")) or int(page.get("total") or 0) > int(page.get("current") or 0)
    return {"comments": comments, "page": page, "has_more": has_more}


def fetch_floor_page(fetcher, tid: str, pid: str, pn: int = 1, bduss: str = "") -> Dict:
    raw = _floor_request(fetcher, tid, pid, pn, bduss)
    return parse_floor_response(raw)


def fill_comments_anon(
    thread: ThreadData,
    fetcher,
    options,
    only_floors: Optional[set] = None,
) -> None:
    """用 floor 接口把免登录楼中楼补全（按总条数上限 + 并发）。"""
    from concurrent.futures import ThreadPoolExecutor

    if not getattr(options, "include_comments", True):
        return
    depth = int(getattr(options, "comment_depth", 0) or 0)
    concurrency = max(1, min(3, int(getattr(options, "comment_concurrency", 1) or 1)))
    existing: Dict[int, set] = {}
    for comment in thread.comments:
        if comment.pid:
            existing.setdefault(comment.floor_no, set()).add(comment.pid)

    def desired_total(floor: Floor) -> int:
        total = int(floor.reply_num or 0)
        if depth:
            total = min(total, depth)
        return total

    floors = [
        floor
        for floor in thread.floors
        if len(existing.get(floor.post_no, ())) < desired_total(floor)
        and (only_floors is None or floor.post_no in only_floors)
    ]
    if not floors:
        return
    if options.log:
        options.log(f"  楼中楼补全：{len(floors)} 层（并发 {concurrency}）")

    def work(floor: Floor):
        need = desired_total(floor) - len(existing.get(floor.post_no, ()))
        if need <= 0:
            return []
        result: List[Dict] = []
        seen = set(existing.get(floor.post_no, ()))
        pn = 1
        while pn <= 50 and len(result) < need:
            if getattr(options, "should_stop", None) and options.should_stop():
                break
            try:
                page = fetch_floor_page(fetcher, thread.meta.tid, floor.pid, pn, bduss="")
            except (CaptchaError, RateLimitError) as error:
                thread.complete = False
                if floor.post_no not in thread.failed_comment_floors:
                    thread.failed_comment_floors.append(floor.post_no)
                thread.warnings.append(f"第 {floor.post_no} 层楼中楼未抓完：{error}")
                break
            except Exception as error:  # noqa: BLE001
                thread.complete = False
                if floor.post_no not in thread.failed_comment_floors:
                    thread.failed_comment_floors.append(floor.post_no)
                thread.warnings.append(f"第 {floor.post_no} 层楼中楼失败：{error}")
                break
            for row in page["comments"]:
                if len(result) >= need:
                    break
                pid = row["pid"]
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                row["floor_no"] = floor.post_no
                row["floor_author"] = floor.author
                result.append(row)
            if not page["has_more"]:
                break
            pn += 1
        if len(result) >= need and floor.post_no in thread.failed_comment_floors:
            thread.failed_comment_floors.remove(floor.post_no)
        return result

    rows = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for part in pool.map(work, floors):
            rows.extend(part)
    for row in rows:
        thread.comments.append(
            Comment(
                floor_no=row["floor_no"],
                floor_author=row.get("floor_author") or "",
                pid=row["pid"],
                author=row["author"],
                author_name=row["author_name"],
                author_id=row["author_id"],
                tieba_uid=row.get("tieba_uid", ""),
                portrait=row["portrait"],
                posted_at=_to_datetime(row["time"]),
                content=row["content"],
                reply_to=row["reply_to"],
                is_op=row["is_op"],
                level=str(row["level"]) if row["level"] else "",
            )
        )
    thread.comments.sort(key=lambda item: (item.floor_no, item.pid))
