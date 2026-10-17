"""Collect user -> bar level snapshots from Tieba.

Standalone data-collection tool (no GUI coupling, no release build).

Sources:
  * thread floors        (user posted in bar -> level in that bar)
  * panel honor.grade    (followed bars, partial)
  * client profile proto (likeForum, 6 bars + privacy flag)
  * self follow list     (full list with level / exp, own account only)

Output:
  snapshots/user_bars.jsonl
  snapshots/users.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tieba_reply_stats import cookie_store  # noqa: E402
from tieba_reply_stats.collect import CollectOptions, collect_thread  # noqa: E402
from tieba_reply_stats.fetch import Fetcher, parse_cookie_input  # noqa: E402
from tieba_reply_stats.pbapi import fill_thread_levels  # noqa: E402
from tieba_reply_stats.profile import fetch_panel  # noqa: E402

APP_SALT = b"tiebaclient!!!"
DEFAULT_DB = os.path.join(ROOT, "snapshots")


# --------------------------------------------------------------------- protobuf

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


def _profile_request(uid: int, bduss: str) -> bytes:
    common = b"".join([
        _fv(1, 2),
        _fb(2, b"12.64.1.1"),
        _fb(10, bduss.encode()),
    ])
    data = b"".join([
        _fv(1, uid),
        _fv(2, 1),
        _fv(6, 1),
        _fb(9, common),
    ])
    return _fb(1, data)


def fetch_profile(uid: int, bduss: str) -> Dict:
    """Client protobuf profile: privacy flag + likeForum (fixed 6 entries)."""
    boundary = "----snap" + uuid.uuid4().hex
    payload = _profile_request(uid, bduss)
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="data"; filename="blob"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        "http://tiebac.baidu.com/c/u/user/profile",
        data=body,
        headers={
            "User-Agent": "bdtb for Android 12.64.1.1",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "x_bd_data_type": "protobuf",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    top = list(_fields(raw))
    data = None
    for num, wire, value in top:
        if num == 2 and wire == 2:
            data = value
            break
    if not data:
        return {}
    user = _msg(data, 1)
    if not user:
        return {}
    priv = _msg(user, 45) or b""
    forums = []
    for num, wire, value in _fields(user):
        if num == 47 and wire == 2:
            name = _text(value, 1)
            if name:
                forums.append({"name": name, "fid": _num(value, 2)})
    return {
        "uid": _num(user, 2),
        "name": _text(user, 3),
        "nickname": _text(user, 4),
        "post_num": _num(user, 37),
        "priv_like": _num(priv, 2),
        "fans": _num(user, 30),
        "concern": _num(user, 31),
        "forums": forums,
    }


# --------------------------------------------------------------------- follow list

def _sign(params: Dict[str, object]) -> Dict[str, object]:
    data = sorted((str(k), str(v)) for k, v in params.items())
    md5 = hashlib.md5()
    for key, value in data:
        md5.update(f"{key}={value}".encode())
    md5.update(APP_SALT)
    signed = dict(data)
    signed["sign"] = md5.hexdigest()
    return signed


def fetch_self_follows(fetcher: Fetcher) -> List[Dict]:
    """Full own follow list (level + cur_score). Only works for the cookie owner."""
    bduss = fetcher.cookie_dict().get("BDUSS", "")
    if not bduss:
        return []
    forums: List[Dict] = []
    page = 1
    while page <= 5:
        params = _sign({
            "BDUSS": bduss,
            "_client_version": "12.64.1.1",
            "page_no": page,
            "page_size": 400,
        })
        request = urllib.request.Request(
            "https://tiebac.baidu.com/c/f/forum/like",
            data=urllib.parse.urlencode(params).encode(),
            headers={
                "User-Agent": "bdtb for Android 12.64.1.1",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(request, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        forum_list = payload.get("forum_list") or {}
        items: List[Dict] = []
        for key in ("non-gconforum", "gconforum"):
            if isinstance(forum_list.get(key), list):
                items.extend(forum_list[key])
        if not items:
            break
        for item in items:
            if item.get("name"):
                forums.append({
                    "name": item["name"],
                    "level": int(item.get("level_id") or 0),
                    "exp": int(item.get("cur_score") or 0),
                    "fid": item.get("id"),
                })
        if len(items) < 400:
            break
        page += 1
    return forums


# --------------------------------------------------------------------- storage

def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_jsonl(path: str) -> List[Dict]:
    rows = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def _write_jsonl(path: str, rows: Iterable[Dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def merge_rows(existing: List[Dict], new_rows: List[Dict], keys) -> List[Dict]:
    merged: Dict[tuple, Dict] = {}
    for row in existing + new_rows:
        key = tuple(row.get(k) for k in keys)
        if not key or not all(key):
            continue
        old = merged.get(key)
        if old is None or row.get("ts", "") >= old.get("ts", ""):
            merged[key] = row
    return sorted(merged.values(), key=lambda r: (str(r.get("uid")), str(r.get("bar")), str(r.get("ts"))))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", default="", help="comma separated tid list")
    parser.add_argument("--users", default="", help="comma separated uid / username")
    parser.add_argument("--out", default=DEFAULT_DB)
    parser.add_argument("--max-floors", type=int, default=60)
    args = parser.parse_args()

    fetcher = Fetcher(cookie=parse_cookie_input(cookie_store.load_cookie()), delay=0.35, verbose=False)
    bduss = fetcher.cookie_dict().get("BDUSS", "")
    ts = _now()
    bar_rows: List[Dict] = []
    user_rows: List[Dict] = []

    def add_bar(uid, bar, level, exp=None, source="", extra=None):
        if not uid or not bar:
            return
        bar = str(bar)
        if source == "thread_floor" and bar.endswith("吧") and len(bar) > 2:
            bar = bar[:-1]
        if level in (None, "", 0, "0") and source != "like_forum":
            return
        row = {"ts": ts, "uid": str(uid), "bar": str(bar),
               "level": int(level) if level not in (None, "") else None,
               "exp": int(exp) if exp not in (None, "") else None, "source": source}
        if extra:
            row.update(extra)
        bar_rows.append(row)

    def add_user(uid, username="", nickname="", post_num=None, priv_like=None,
                 fans=None, concern=None, source=""):
        if not uid:
            return
        user_rows.append({
            "ts": ts, "uid": str(uid), "username": username or "",
            "nickname": nickname or "", "post_num": post_num, "priv_like": priv_like,
            "fans": fans, "concern": concern, "source": source,
        })

    # 1. self follow list (full)
    try:
        follows = fetch_self_follows(fetcher)
    except Exception as error:  # noqa: BLE001
        print("[warn] self follows:", error)
        follows = []

    # self uid from user_json
    self_uid = ""
    try:
        me = fetcher.get_json("https://tieba.baidu.com/i/sys/user_json?ie=utf-8")
        self_uid = str(me.get("id") or "")
        add_user(self_uid, me.get("raw_name") or "", (me.get("creator") or {}).get("name_show") or "",
                 source="user_json")
    except Exception as error:  # noqa: BLE001
        print("[warn] self id:", error)

    for forum in follows:
        add_bar(self_uid, forum["name"], forum["level"], forum.get("exp"), source="follow_self")

    # 2. threads -> floor authors' level in that bar
    thread_ids = [item.strip() for item in args.threads.split(",") if item.strip()]
    for tid in thread_ids:
        url = f"https://tieba.baidu.com/p/{tid}"
        try:
            options = CollectOptions(max_pages=1, include_comments=False, verbose=False)
            thread = collect_thread(url, fetcher, options)
        except Exception as error:  # noqa: BLE001
            print(f"[warn] thread {tid}:", error)
            continue
        forum = thread.meta.forum
        try:
            fill_thread_levels(thread, fetcher, lambda _message: None)
        except Exception as error:  # noqa: BLE001
            print(f"[warn] levels {tid}:", error)
        print(f"[thread] {tid} {forum}: {len(thread.floors)} floors")
        for floor in thread.floors[: args.max_floors]:
            add_bar(floor.author_id, forum, floor.level, source="thread_floor",
                    extra={"pid": floor.pid})
            add_user(floor.author_id, floor.author_name, floor.author, source="thread_floor")

    # 3. seed users: panel + profile proto
    users = [item.strip() for item in args.users.split(",") if item.strip()]
    for value in users:
        target_uid = value if value.isdigit() else ""
        username = "" if value.isdigit() else value
        resolved = {}
        try:
            key = "uid" if target_uid else "un"
            resolved = fetcher.get_json(
                f"https://tieba.baidu.com/i/sys/user_json?{key}={urllib.parse.quote(value)}&ie=utf-8"
            )
            target_uid = target_uid or str(resolved.get("id") or "")
            username = username or resolved.get("raw_name") or ""
        except Exception as error:  # noqa: BLE001
            print("[warn] resolve", value, error)
        if not target_uid:
            continue
        panel = {}
        try:
            panel = fetch_panel(fetcher, username)
        except Exception as error:  # noqa: BLE001
            print("[warn] panel", username, error)
        for forum in panel.get("forums") or []:
            add_bar(target_uid, forum["name"], forum.get("level"), source="panel")
        try:
            profile = fetch_profile(int(target_uid), bduss)
        except Exception as error:  # noqa: BLE001
            print("[warn] profile", target_uid, error)
            profile = {}
        known_levels = {
            row["bar"]: row["level"]
            for row in bar_rows
            if row.get("uid") == str(target_uid) and row.get("level")
        }
        for forum in profile.get("forums") or []:
            add_bar(target_uid, forum["name"], known_levels.get(forum["name"]), source="like_forum")
        add_user(
            target_uid,
            username,
            profile.get("nickname") or (resolved.get("creator") or {}).get("name_show") or "",
            post_num=profile.get("post_num") or panel.get("post_num"),
            priv_like=profile.get("priv_like"),
            fans=profile.get("fans"),
            concern=profile.get("concern"),
            source="panel+profile",
        )
        print(f"[user] {username or target_uid}: panel={len(panel.get('forums') or [])} "
              f"likeForum={len(profile.get('forums') or [])} priv_like={profile.get('priv_like')}")

    # 4. merge + write
    bar_path = os.path.join(args.out, "user_bars.jsonl")
    user_path = os.path.join(args.out, "users.jsonl")
    bar_rows = [row for row in bar_rows if row.get("uid") and row.get("bar")]
    merged_bars = merge_rows(_load_jsonl(bar_path), bar_rows, ("uid", "bar", "source"))
    merged_users = merge_rows(_load_jsonl(user_path), user_rows, ("uid",))
    _write_jsonl(bar_path, merged_bars)
    _write_jsonl(user_path, merged_users)
    print(f"\nwrote {len(merged_bars)} bar rows -> {bar_path}")
    print(f"wrote {len(merged_users)} user rows -> {user_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
