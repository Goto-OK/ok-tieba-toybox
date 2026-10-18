"""Android entry point: local HTTP server + JSON API for the WebView UI."""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_VERSION = "1.0-android"
HOME = os.environ.get("HOME") or "."
os.environ["APPDATA"] = HOME
os.environ.setdefault("TMPDIR", HOME)

from tieba_reply_stats.blacklist import classify, load_blacklist, marker, save_blacklist
from tieba_reply_stats.collect import CollectOptions, collect_thread
from tieba_reply_stats.export import export_workbook
from tieba_reply_stats.fetch import (
    CaptchaError,
    FetchError,
    Fetcher,
    ThreadGoneError,
    parse_cookie_input,
)
from tieba_reply_stats.profile import fetch_user_profile, resolve_user

LOCK = threading.Lock()
STATE = {
    "running": False,
    "stop": False,
    "done": 0,
    "total": 0,
    "error": "",
    "logs": [],
    "threads": [],
    "output": "",
    "last_started": 0.0,
}
COOKIE_FILE = os.path.join(HOME, "cookie.json")
SETTINGS_FILE = os.path.join(HOME, "web_settings.json")


# ------------------------------------------------------------------ helpers
def _log(text: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {text}"
    with LOCK:
        STATE["logs"].append(line)
        if len(STATE["logs"]) > 400:
            STATE["logs"] = STATE["logs"][-400:]


def _load_cookie() -> str:
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as handle:
            return str(json.load(handle).get("cookie") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def _save_cookie(cookie: str) -> None:
    try:
        with open(COOKIE_FILE, "w", encoding="utf-8") as handle:
            json.dump({"cookie": cookie}, handle, ensure_ascii=False)
    except OSError:
        pass


def _load_web_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"color_forum": True, "color_posts": True}


def _save_web_settings(data: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
    except OSError:
        pass


def _people_rows() -> list:
    merged = {}
    for thread in STATE["threads"]:
        for item in thread.user_stats(True):
            key = item.get("uid") or f"name:{item.get('name')}"
            row = merged.get(key)
            if row is None:
                row = {
                    "uid": item.get("uid") or "",
                    "name": item.get("name") or "",
                    "username": item.get("username") or "",
                    "portrait": item.get("portrait") or "",
                    "level": item.get("level") or "",
                    "badge": item.get("badge") or "",
                    "floor": 0,
                    "comment": 0,
                    "total": 0,
                    "bars": [],
                }
                merged[key] = row
            row["floor"] += item.get("floor_count") or 0
            row["comment"] += item.get("comment_count") or 0
            row["total"] += item.get("total") or 0
            if not row["level"] and item.get("level"):
                row["level"] = item["level"]
            if not row["username"] and item.get("username"):
                row["username"] = item["username"]
            if thread.meta.forum and thread.meta.forum not in row["bars"]:
                row["bars"].append(thread.meta.forum)
    blacklist = load_blacklist()
    for row in merged.values():
        hit, bar = classify(row["bars"], blacklist)
        row["hit"] = hit
        row["hit_bar"] = bar
        row["mark"] = marker(hit) + (f" { {'ban': '禁止', 'warn': '警告', 'safe': '安全'}.get(hit, '') }".strip() if hit else "")
    return sorted(merged.values(), key=lambda item: -item["total"])


def _grid_rows(kind: str) -> list:
    rows = []
    if kind == "users":
        for index, item in enumerate(_people_rows(), start=1):
            rows.append([index, item["name"], item["username"], item["uid"], item["level"],
                         item["badge"], item["floor"], item["comment"], item["total"]])
    elif kind == "floors":
        for thread in STATE["threads"]:
            for floor in thread.floors:
                rows.append([floor.post_no, floor.author, floor.author_name, floor.author_id,
                             floor.level, floor.badge, floor.content])
    elif kind == "comments":
        for thread in STATE["threads"]:
            for comment in thread.comments:
                rows.append([comment.floor_no, comment.author, comment.author_name,
                             comment.author_id, comment.level, comment.content])
    return rows


def _profile_payload(profile: dict) -> dict:
    forums = profile.get("followed_forums") or profile.get("hidden_forums") or []
    merged = {}
    for forum in forums:
        merged[forum.get("name")] = forum
    for forum in profile.get("like_forum") or []:
        merged.setdefault(forum.get("name"), {"name": forum.get("name"), "level": 0})
    forum_rows = sorted(
        [{"name": name, "level": item.get("level") or 0} for name, item in merged.items() if name],
        key=lambda item: -int(item.get("level") or 0),
    )
    return {
        "ok": True,
        "user_id": profile.get("user_id") or "",
        "username": profile.get("username") or "",
        "nickname": profile.get("nickname") or "",
        "fans": profile.get("fans"),
        "concern": profile.get("concern"),
        "post_num": profile.get("post_num"),
        "priv_like": profile.get("priv_like"),
        "hidden": bool(profile.get("followed_private")) or profile.get("priv_like") == 3,
        "forums": forum_rows,
        "posts": [
            {
                "time": post.get("time") or "",
                "type": post.get("type") or "",
                "bar": post.get("bar") or "",
                "title": post.get("title") or "",
                "content": post.get("content") or "",
                "url": post.get("url") or "",
            }
            for post in (profile.get("recent_posts") or [])
        ],
    }


def _run_job(payload: dict) -> None:
    urls = payload.get("urls") or []
    cookie = payload.get("cookie") or ""
    export = bool(payload.get("export", True))
    include_op = not bool(payload.get("exclude_op", False))
    try:
        with LOCK:
            STATE.update({"running": True, "stop": False, "done": 0, "error": "",
                          "threads": [], "output": "", "logs": [], "total": len(urls)})
        _log(f"开始抓取，共 {len(urls)} 个帖子" + ("" if cookie else "（游客模式：无 Cookie）"))
        fetcher = Fetcher(cookie=parse_cookie_input(cookie), delay=0.6, verbose=False)
        options = CollectOptions(
            mode="login" if cookie else "guest",
            max_pages=int(payload.get("max_pages") or 0),
            include_comments=bool(payload.get("comments", True)),
            max_comment_pages=int(payload.get("max_comment_pages") or 30),
            verbose=True,
            log=_log,
            should_stop=lambda: STATE["stop"],
        )
        threads = []
        for index, url in enumerate(urls, start=1):
            if STATE["stop"]:
                break
            _log(f"[{index}/{len(urls)}] {url}")
            try:
                thread = collect_thread(url, fetcher, options)
            except CaptchaError as error:
                _log(f"被安全验证拦截：{error}")
                break
            except (ThreadGoneError, FetchError, ValueError) as error:
                _log(f"抓取失败：{error}")
                continue
            threads.append(thread)
            with LOCK:
                STATE["threads"] = list(threads)
                STATE["done"] = index
        output = ""
        if export and threads:
            output = os.path.join(HOME, f"贴吧统计_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
            export_workbook(output, threads, include_op=include_op)
            with LOCK:
                STATE["output"] = output
            _log(f"已导出：{output}")
        _log("完成" if not STATE["stop"] else "已停止")
    except Exception as error:  # noqa: BLE001
        with LOCK:
            STATE["error"] = f"{type(error).__name__}: {error}"
        _log("出错：" + STATE["error"])
        traceback.print_exc()
    finally:
        with LOCK:
            STATE["running"] = False


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "TiebaStats/" + APP_VERSION

    def log_message(self, fmt, *args):  # noqa: A003
        pass

    def _send(self, status: int, body: bytes, content_type="text/html; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload, status=200):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (ValueError, json.JSONDecodeError):
            return {}

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            index_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
            try:
                with open(index_path, "rb") as handle:
                    self._send(200, handle.read())
            except OSError:
                self._send(500, b"index.html missing")
            return
        if path == "/api/health":
            self._json({"ok": True, "app": APP_VERSION, "home": HOME, "threads": len(STATE["threads"])})
            return
        if path == "/api/status":
            with LOCK:
                payload = {
                    "running": STATE["running"],
                    "done": STATE["done"],
                    "total": STATE["total"],
                    "error": STATE["error"],
                    "logs": list(STATE["logs"]),
                    "output": STATE["output"],
                    "people": len(_people_rows()) if STATE["threads"] else 0,
                    "threads": len(STATE["threads"]),
                }
            self._json(payload)
            return
        if path == "/api/cookie":
            cookie = _load_cookie()
            self._json({"cookie": cookie, "has": bool(cookie)})
            return
        if path == "/api/people":
            self._json({"people": _people_rows()})
            return
        if path == "/api/grid":
            kind = (query.get("kind") or ["users"])[0]
            self._json({"rows": _grid_rows(kind)})
            return
        if path == "/api/person":
            uid = (query.get("uid") or [""])[0]
            name = (query.get("name") or [""])[0]
            bar = (query.get("bar") or [""])[0]
            self._person(uid, name, bar)
            return
        if path == "/api/lookup":
            mode = (query.get("mode") or ["用户名"])[0]
            text = (query.get("q") or [""])[0]
            self._lookup(mode, text, query)
            return
        if path == "/api/blacklist":
            self._json(load_blacklist())
            return
        if path == "/api/settings":
            self._json(_load_web_settings())
            return
        if path == "/api/export":
            self._export_file()
            return
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        data = self._body_json()

        if path == "/api/start":
            cookie = str(data.get("cookie") or "").strip()
            if data.get("remember", True) and cookie:
                _save_cookie(cookie)
            if not cookie:
                cookie = _load_cookie()
            if STATE["running"]:
                self._json({"ok": False, "error": "正在抓取中"}, 400)
                return
            urls = data.get("urls") or []
            if isinstance(urls, str):
                urls = [item.strip() for item in urls.replace("，", ",").split(",") if item.strip()]
            urls = [str(item).strip() for item in urls if str(item).strip()]
            if not urls:
                self._json({"ok": False, "error": "请填写帖子链接"}, 400)
                return
            payload = dict(data)
            payload["urls"] = urls
            payload["cookie"] = cookie
            threading.Thread(target=_run_job, args=(payload,), daemon=True).start()
            self._json({"ok": True})
            return
        if path == "/api/stop":
            with LOCK:
                STATE["stop"] = True
            self._json({"ok": True})
            return
        if path == "/api/cookie":
            cookie = str(data.get("cookie") or "").strip()
            if cookie:
                _save_cookie(cookie)
            self._json({"ok": True})
            return
        if path == "/api/blacklist":
            result = {"safe": data.get("safe") or [], "warn": data.get("warn") or [],
                      "ban": data.get("ban") or []}
            ok = save_blacklist(result)
            self._json({"ok": ok})
            return
        if path == "/api/settings":
            current = _load_web_settings()
            for key in ("color_forum", "color_posts"):
                if key in data:
                    current[key] = bool(data[key])
            _save_web_settings(current)
            self._json({"ok": True, "settings": current})
            return
        self._json({"ok": False, "error": "not found"}, 404)

    # -------------------------------------------------------------- handlers
    def _fetcher(self):
        cookie = _load_cookie()
        return Fetcher(cookie=parse_cookie_input(cookie), delay=0.4, verbose=False)

    def _person(self, uid: str, name: str, bar: str):
        fetcher = self._fetcher()
        if fetcher is None:
            self._json({"ok": False, "error": "请先保存 Cookie"}, 400)
            return
        count = int(self.headers.get("X-Count") or 50) if self.headers.get("X-Count") else 50
        try:
            profile = fetch_user_profile(fetcher, uid, name, "", bar, max(5, min(200, count)))
            self._json(_profile_payload(profile))
        except Exception as error:  # noqa: BLE001
            self._json({"ok": False, "error": str(error)}, 500)

    def _lookup(self, mode: str, text: str, query: dict):
        fetcher = self._fetcher()
        if fetcher is None:
            self._json({"ok": False, "error": "请先保存 Cookie"}, 400)
            return
        if not text:
            self._json({"ok": False, "error": "请输入查询内容"}, 400)
            return
        try:
            info = resolve_user(fetcher, text, mode)
            if not info.get("uid"):
                self._json({"ok": False, "error": "没有找到这个人"}, 404)
                return
            count = int((query.get("count") or ["50"])[0])
            start = (query.get("start") or [""])[0]
            end = (query.get("end") or [""])[0]
            profile = fetch_user_profile(
                fetcher, info.get("uid") or "", info.get("username") or "",
                info.get("portrait") or "", "", max(5, min(1000, count)), start, end,
            )
            payload = _profile_payload(profile)
            payload["nickname"] = payload.get("nickname") or info.get("nickname") or ""
            self._json(payload)
        except Exception as error:  # noqa: BLE001
            self._json({"ok": False, "error": str(error)}, 500)

    def _export_file(self):
        with LOCK:
            threads = list(STATE["threads"])
        if not threads:
            self._json({"ok": False, "error": "还没有数据"}, 400)
            return
        path = os.path.join(HOME, f"贴吧统计_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
        try:
            export_workbook(path, threads)
        except Exception as error:  # noqa: BLE001
            self._json({"ok": False, "error": str(error)}, 500)
            return
        with open(path, "rb") as handle:
            body = handle.read()
        filename = urllib.parse.quote(os.path.basename(path))
        self._send(200, body,
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


def start_server(home: str) -> int:
    global HOME
    HOME = home or HOME
    os.environ["HOME"] = HOME
    os.environ["APPDATA"] = HOME
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return int(server.server_address[1])
