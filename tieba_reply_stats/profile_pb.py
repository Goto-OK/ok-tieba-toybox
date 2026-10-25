"""Minimal client-protobuf helpers for Tieba user profile.

Endpoint: POST https://tiebac.baidu.com/c/u/user/profile?cmd=303012
Body: multipart/form-data, field ``data`` = ProfileReqIdl bytes,
header ``x_bd_data_type: protobuf``; no sign required.

Returns a dict with id / username / nickname / post_num / fans / concern /
privacy flag / likeForum (fixed ~6 entries).
"""

from __future__ import annotations

import urllib.request
import uuid
from typing import Dict, List, Optional

PROFILE_URL = "https://tiebac.baidu.com/c/u/user/profile?cmd=303012"
TIEBA_UID_URL = "https://tiebac.baidu.com/c/u/user/getUserByTiebaUid?cmd=309702"
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


def _num(data: bytes, number: int) -> Optional[int]:
    for num, wire, value in _fields(data):
        if num == number and wire == 0:
            return value
    return None


def _text(data: bytes, number: int) -> Optional[str]:
    value = _msg(data, number)
    if value is None:
        return None
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("gb18030", "replace")


def build_request_portrait(portrait: str, bduss: str = "") -> bytes:
    common = b"".join(
        [
            _fv(1, 2),
            _fb(2, CLIENT_VERSION),
            _fb(10, bduss.encode()),
        ]
    )
    data = b"".join(
        [
            _fv(2, 1),
            _fv(15, 1),
            _fb(9, common),
            _fb(16, portrait.encode()),
        ]
    )
    return _fb(1, data)


def build_request(uid: int, bduss: str) -> bytes:
    common = b"".join(
        [
            _fv(1, 2),
            _fb(2, CLIENT_VERSION),
            _fb(10, bduss.encode()),
        ]
    )
    data = b"".join(
        [
            _fv(1, uid),
            _fv(2, 1),
            _fv(6, 1),
            _fb(9, common),
        ]
    )
    return _fb(1, data)


def build_request_tieba_uid(tieba_uid: str, bduss: str = "") -> bytes:
    common = b"".join(
        [
            _fv(1, 2),
            _fb(2, CLIENT_VERSION),
            _fb(10, bduss.encode()),
        ]
    )
    data = b"".join(
        [
            _fb(1, common),
            _fb(2, str(tieba_uid).encode()),
        ]
    )
    return _fb(1, data)


def _post_proto(request_url: str, payload: bytes) -> bytes:
    boundary = "----tbpb" + uuid.uuid4().hex
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="data"; filename="blob"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        request_url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "x_bd_data_type": "protobuf",
        },
    )
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read()


def fetch_profile_by_tieba_uid(fetcher, tieba_uid: str) -> Dict:
    """用用户可见的 tieba_uid 反查内部 user_id。"""
    text = str(tieba_uid or "").strip()
    if not text.isdigit():
        return {}
    bduss = fetcher.cookie_dict().get("BDUSS", "")
    try:
        raw = _post_proto(TIEBA_UID_URL, build_request_tieba_uid(text, bduss))
    except Exception:  # noqa: BLE001
        return {}
    return parse_response(raw)


def fetch_profile(fetcher, uid: str = "", portrait: str = "") -> Dict:
    """Return profile info from the client protobuf endpoint; {} on failure.

    portrait 可直接反查 uid，无需 BDUSS；这是楼中楼只有 portrait 时的关键兜底。
    """
    if not uid and not portrait:
        return {}
    bduss = fetcher.cookie_dict().get("BDUSS", "")
    if uid:
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            return {}
        payload = build_request(uid_int, bduss)
    else:
        payload = build_request_portrait(portrait, bduss)
    boundary = "----tbpb" + uuid.uuid4().hex
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="data"; filename="blob"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        PROFILE_URL,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "x_bd_data_type": "protobuf",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            raw = response.read()
    except Exception:  # noqa: BLE001
        return {}
    return parse_response(raw)


def parse_response(raw: bytes) -> Dict:
    """Decode a ProfileResIdl response; {} when it is not a profile."""
    if not raw or raw[:1] == b"{":
        return {}
    data = None
    for number, wire, value in _fields(raw):
        if number == 2 and wire == 2:
            data = value
            break
    if not data:
        return {}
    user = _msg(data, 1)
    if not user:
        return {}
    priv = _msg(user, 45) or b""
    forums: List[Dict] = []
    for number, wire, value in _fields(user):
        if number == 47 and wire == 2:
            name = _text(value, 1)
            if name:
                forums.append({"name": name, "fid": _num(value, 2)})
    return {
        "uid": _num(user, 2),
        "tieba_uid": _text(user, 120) or "",
        "username": _text(user, 3) or "",
        "nickname": _text(user, 4) or "",
        "portrait": (_text(user, 5) or "").split("?")[0],
        "post_num": _num(user, 37),
        "priv_like": _num(priv, 2),
        "fans": _num(user, 30),
        "concern": _num(user, 31),
        "forums": forums,
    }
