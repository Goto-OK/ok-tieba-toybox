"""最近一次结果的 SQLite 持久化。"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .cookie_store import _protect, _unprotect
from .models import Comment, Floor, ThreadData, ThreadMeta

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TiebaReplyStats")
DB_PATH = os.path.join(APP_DIR, "last_result.db")
ENC_PATH = os.path.join(APP_DIR, "last_result.enc")
SCHEMA_VERSION = 1


class IncompatibleResult(RuntimeError):
    """文件存在但无法按当前版本读取。"""


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat(timespec="seconds") if value else ""


def _dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _floor_dict(floor: Floor) -> Dict:
    return {
        "post_no": floor.post_no,
        "pid": floor.pid,
        "author": floor.author,
        "author_name": floor.author_name,
        "author_id": floor.author_id,
        "tieba_uid": floor.tieba_uid,
        "tieba_uid_failed": floor.tieba_uid_failed,
        "user_id_failed": floor.user_id_failed,
        "portrait": floor.portrait,
        "posted_at": _iso(floor.posted_at),
        "content": floor.content,
        "reply_num": floor.reply_num,
        "is_op": floor.is_op,
        "is_deleted": floor.is_deleted,
        "level": floor.level,
        "badge": floor.badge,
    }


def _comment_dict(comment: Comment) -> Dict:
    return {
        "floor_no": comment.floor_no,
        "floor_author": comment.floor_author,
        "pid": comment.pid,
        "author": comment.author,
        "author_name": comment.author_name,
        "author_id": comment.author_id,
        "tieba_uid": comment.tieba_uid,
        "tieba_uid_failed": comment.tieba_uid_failed,
        "user_id_failed": comment.user_id_failed,
        "portrait": comment.portrait,
        "posted_at": _iso(comment.posted_at),
        "content": comment.content,
        "reply_to": comment.reply_to,
        "is_op": comment.is_op,
        "level": comment.level,
    }


def thread_to_dict(thread: ThreadData) -> Dict:
    return {
        "meta": {
            "tid": thread.meta.tid,
            "fid": thread.meta.fid,
            "title": thread.meta.title,
            "forum": thread.meta.forum,
            "url": thread.meta.url,
            "total_page": thread.meta.total_page,
            "reply_num": thread.meta.reply_num,
            "mode": thread.meta.mode,
        },
        "floors": [_floor_dict(item) for item in thread.floors],
        "comments": [_comment_dict(item) for item in thread.comments],
        "pages_fetched": thread.pages_fetched,
        "fetched_at": _iso(thread.fetched_at),
        "warnings": list(thread.warnings),
        "complete": thread.complete,
        "failed_pages": list(thread.failed_pages),
        "failed_comment_floors": list(thread.failed_comment_floors),
    }


def thread_from_dict(data: Dict) -> ThreadData:
    meta_data = data.get("meta") or {}
    meta = ThreadMeta(
        tid=str(meta_data.get("tid") or ""),
        fid=str(meta_data.get("fid") or ""),
        title=str(meta_data.get("title") or ""),
        forum=str(meta_data.get("forum") or ""),
        url=str(meta_data.get("url") or ""),
        total_page=int(meta_data.get("total_page") or 0),
        reply_num=int(meta_data.get("reply_num") or 0),
        mode=str(meta_data.get("mode") or ""),
    )
    floors = [
        Floor(
            post_no=int(item.get("post_no") or 0),
            pid=str(item.get("pid") or ""),
            author=str(item.get("author") or ""),
            author_name=str(item.get("author_name") or ""),
            author_id=str(item.get("author_id") or ""),
            tieba_uid=str(item.get("tieba_uid") or ""),
            tieba_uid_failed=bool(item.get("tieba_uid_failed")),
            user_id_failed=bool(item.get("user_id_failed")),
            portrait=str(item.get("portrait") or ""),
            posted_at=_dt(str(item.get("posted_at") or "")),
            content=str(item.get("content") or ""),
            reply_num=int(item.get("reply_num") or 0),
            is_op=bool(item.get("is_op")),
            is_deleted=bool(item.get("is_deleted")),
            level=str(item.get("level") or ""),
            badge=str(item.get("badge") or ""),
        )
        for item in data.get("floors") or []
    ]
    comments = [
        Comment(
            floor_no=int(item.get("floor_no") or 0),
            floor_author=str(item.get("floor_author") or ""),
            pid=str(item.get("pid") or ""),
            author=str(item.get("author") or ""),
            author_name=str(item.get("author_name") or ""),
            author_id=str(item.get("author_id") or ""),
            tieba_uid=str(item.get("tieba_uid") or ""),
            tieba_uid_failed=bool(item.get("tieba_uid_failed")),
            user_id_failed=bool(item.get("user_id_failed")),
            portrait=str(item.get("portrait") or ""),
            posted_at=_dt(str(item.get("posted_at") or "")),
            content=str(item.get("content") or ""),
            reply_to=str(item.get("reply_to") or ""),
            is_op=bool(item.get("is_op")),
            level=str(item.get("level") or ""),
        )
        for item in data.get("comments") or []
    ]
    return ThreadData(
        meta=meta,
        floors=floors,
        comments=comments,
        pages_fetched=int(data.get("pages_fetched") or 0),
        fetched_at=_dt(str(data.get("fetched_at") or "")) or datetime.now(),
        warnings=[str(item) for item in data.get("warnings") or []],
        complete=bool(data.get("complete", True)),
        failed_pages=[int(item) for item in data.get("failed_pages") or []],
        failed_comment_floors=[
            int(item) for item in data.get("failed_comment_floors") or []
        ],
    )


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _init(conn: sqlite3.Connection, app_version: str, saved_at: str) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS threads (
            tid TEXT PRIMARY KEY,
            title TEXT,
            forum TEXT,
            source_url TEXT,
            fetched_at TEXT,
            payload_version INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_threads_fetched ON threads(fetched_at)")
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "app_version": app_version,
        "saved_at": saved_at,
    }
    for key, value in meta.items():
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))


def _validate(conn: sqlite3.Connection) -> None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError as error:
        raise IncompatibleResult("结果文件损坏") from error
    if not row or int(row["value"]) != SCHEMA_VERSION:
        raise IncompatibleResult("结果格式版本不兼容")


def save_threads(threads: List[ThreadData], app_version: str, encrypted: bool = False) -> str:
    """保存最近结果；返回实际文件路径。"""
    if not threads:
        raise ValueError("没有可保存的结果")
    os.makedirs(APP_DIR, exist_ok=True)
    saved_at = datetime.now().isoformat(timespec="seconds")
    fd, temp_path = tempfile.mkstemp(prefix="last_result_", suffix=".db", dir=APP_DIR)
    os.close(fd)
    try:
        conn = _connect(temp_path)
        try:
            _init(conn, app_version, saved_at)
            for thread in threads:
                payload = json.dumps(thread_to_dict(thread), ensure_ascii=False, separators=(",", ":"))
                conn.execute(
                    """INSERT OR REPLACE INTO threads
                    (tid, title, forum, source_url, fetched_at, payload_version, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        thread.meta.tid,
                        thread.meta.title,
                        thread.meta.forum,
                        thread.meta.url,
                        _iso(thread.fetched_at),
                        SCHEMA_VERSION,
                        payload,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        if encrypted:
            with open(temp_path, "rb") as handle:
                raw = handle.read()
            protected = _protect(raw)
            if protected is None:
                raise OSError("DPAPI 加密失败")
            enc_temp = temp_path + ".enc"
            with open(enc_temp, "wb") as handle:
                handle.write(protected)
            os.replace(enc_temp, ENC_PATH)
            try:
                os.remove(DB_PATH)
            except OSError:
                pass
            return ENC_PATH
        os.replace(temp_path, DB_PATH)
        try:
            os.remove(ENC_PATH)
        except OSError:
            pass
        return DB_PATH
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def load_threads() -> Tuple[List[ThreadData], Dict]:
    """读取最近结果；没有时返回空列表。"""
    source = ENC_PATH if os.path.isfile(ENC_PATH) else DB_PATH
    if not os.path.isfile(source):
        return [], {}
    temp_path = ""
    try:
        if source == ENC_PATH:
            with open(source, "rb") as handle:
                raw = _unprotect(handle.read())
            if not raw or not raw.startswith(b"SQLite format 3"):
                raise IncompatibleResult("加密结果无法解密")
            fd, temp_path = tempfile.mkstemp(prefix="last_result_", suffix=".db", dir=APP_DIR)
            os.close(fd)
            with open(temp_path, "wb") as handle:
                handle.write(raw)
            db_path = temp_path
        else:
            db_path = source
        conn = _connect(db_path)
        try:
            _validate(conn)
            meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
            threads = []
            for row in conn.execute("SELECT payload_json FROM threads ORDER BY fetched_at, tid"):
                try:
                    threads.append(thread_from_dict(json.loads(row["payload_json"])))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
            return threads, meta
        finally:
            conn.close()
    except sqlite3.DatabaseError as error:
        raise IncompatibleResult("结果文件损坏") from error
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def archive_incompatible() -> Optional[str]:
    """把不兼容文件改名保留，返回新路径。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    moved = None
    for path, suffix in ((DB_PATH, ".db"), (ENC_PATH, ".enc")):
        if not os.path.isfile(path):
            continue
        target = os.path.join(APP_DIR, f"last_result.incompatible-{stamp}{suffix}")
        try:
            os.replace(path, target)
            moved = target
        except OSError:
            pass
    return moved


def clear() -> bool:
    ok = True
    for path in (DB_PATH, ENC_PATH):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            ok = False
    return ok


def old_files() -> List[str]:
    try:
        names = os.listdir(APP_DIR)
    except OSError:
        return []
    return [os.path.join(APP_DIR, name) for name in names if name.startswith("last_result.incompatible-")]
