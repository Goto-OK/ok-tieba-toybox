"""Client-protobuf user posts (new PC "查发言" source).

Endpoint: POST http://tiebac.baidu.com/c/u/feed/userpost?cmd=303002
Request:  UserPostReqIdl { data { user_id=1, rn=2, is_thread=4,
                                  need_content=5, pn=26, common=27 } }
Response: UserPostResIdl { error=1, data=2 { post_list=1 repeated } }

`is_thread=1` returns the user's thread-style posts (with content), deep
pagination by `pn` (60 items per page in practice). More complete than the
old `myThread` feed, and it carries the first-post content.
"""

from __future__ import annotations

import urllib.request
import uuid
from typing import Dict, List

USERPOST_URL = "http://tiebac.baidu.com/c/u/feed/userpost?cmd=303002"
CLIENT_VERSION = b"12.64.1.1"
USER_AGENT = "bdtb for Android 12.64.1.1"


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
            value = data[index:index + length]
            index += length
        elif wire == 5:
            value = data[index:index + 4]
            index += 4
        elif wire == 1:
            value = data[index:index + 8]
            index += 8
        else:
            return
        yield number, wire, value


def _msg(data: bytes, number: int):
    for num, wire, value in _fields(data):
        if num == number and wire == 2:
            return value
    return None


def _num(data: bytes, number: int):
    for num, wire, value in _fields(data):
        if num == number and wire == 0:
            return value
    return None


def _text(data: bytes, number: int) -> str:
    value = _msg(data, number)
    if value is None:
        return ""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("gb18030", "replace")


def _content_text(post: bytes) -> str:
    text = ""
    for field in (49, 46):
        parts: List[str] = []
        for number, wire, value in _fields(post):
            if number == field and wire == 2:
                part = _text(value, 2)
                if part:
                    parts.append(part)
        if parts:
            text = "".join(parts).strip()
            break
    return text


def build_request(uid: int, pn: int = 1, rn: int = 20, is_thread: int = 1, bduss: str = "") -> bytes:
    """Encode UserPostReqIdl bytes (without the multipart wrapper)."""
    common = b"".join([
        _fv(1, 2),
        _fb(2, CLIENT_VERSION),
    ])
    if bduss:
        common += _fb(10, bduss.encode())
    data = b"".join([
        _fv(1, uid),
        _fv(2, rn),
        _fv(4, is_thread),
        _fv(5, 1),
        _fv(26, pn),
        _fv(33, 0),
        _fb(27, common),
    ])
    return _fb(1, data)


def _request(fetcher, uid: int, pn: int, rn: int = 20, is_thread: int = 1) -> bytes:
    bduss = fetcher.cookie_dict().get("BDUSS", "")
    payload = build_request(uid, pn, rn, is_thread, bduss)
    boundary = "----tbp" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="data"; filename="blob"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        USERPOST_URL,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "x_bd_data_type": "protobuf",
        },
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read()


def parse_response(raw: bytes) -> List[Dict]:
    data = None
    for number, wire, value in _fields(raw):
        if number == 2 and wire == 2:
            data = value
            break
    if not data:
        return []
    posts: List[Dict] = []
    for number, wire, value in _fields(data):
        if number != 1 or wire != 2:
            continue
        post = {
            "tid": str(_num(value, 2) or ""),
            "pid": str(_num(value, 3) or ""),
            "ts": int(_num(value, 5) or 0),
            "forum": _text(value, 6),
            "title": _text(value, 7),
            "content": _content_text(value),
            "reply_num": _num(value, 17) or 0,
            "uid": str(_num(value, 18) or ""),
            "username": _text(value, 10),
            "nickname": _text(value, 35),
            "portrait": _text(value, 19),
        }
        if post["tid"]:
            posts.append(post)
    return posts


def fetch_user_threads(fetcher, uid: str, max_pages: int = 3) -> List[Dict]:
    """Fetch the user's thread-style posts (newest first)."""
    if not uid:
        return []
    try:
        uid_int = int(uid)
    except (TypeError, ValueError):
        return []
    posts: List[Dict] = []
    seen = set()
    for pn in range(1, max_pages + 1):
        try:
            raw = _request(fetcher, uid_int, pn)
        except Exception:  # noqa: BLE001
            break
        page = parse_response(raw)
        if not page:
            break
        for post in page:
            key = post["pid"] or f"{post['tid']}:{post['title']}"
            if key in seen:
                continue
            seen.add(key)
            posts.append(post)
    return posts
