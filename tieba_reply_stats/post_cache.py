"""用户发言缓存：热内存 + 冷 SQLite（仅本次运行）。

缓存对象是“原始页”和“规范化发言”。热内存只放当前用户，冷库放批量结果；
两者都不跨用户、不落业务数据，退出时删除冷库。
"""

from __future__ import annotations

import atexit
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

HOT_MAX_USERS = 3
HOT_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_LIMIT_MB = 200
MIN_LIMIT_MB = 50
MAX_LIMIT_MB = 2000
PRIORITY_LOW = 0
PRIORITY_HIGH = 1


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except (TypeError, ValueError):
        return 0


class PostCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._hot_pages: "OrderedDict[Tuple[str, str, int], tuple[float, Dict]]" = OrderedDict()
        self._hot_users: "OrderedDict[str, tuple[float, Dict]]" = OrderedDict()
        self._hot_bytes = 0
        self._conn: Optional[sqlite3.Connection] = None
        self._path = ""
        self._limit_mb = DEFAULT_LIMIT_MB
        self._closed = False
        self._open()
        atexit.register(self.close)

    # ---------- lifecycle ----------

    def _open(self) -> None:
        os.makedirs(os.path.join(tempfile.gettempdir(), "TiebaReplyStats"), exist_ok=True)
        self._cleanup_stale()
        name = f"post-cache-{os.getpid()}-{uuid.uuid4().hex[:8]}.db"
        self._path = os.path.join(tempfile.gettempdir(), "TiebaReplyStats", name)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pages(
                user_key TEXT NOT NULL,
                kind TEXT NOT NULL,
                page INTEGER NOT NULL,
                payload TEXT NOT NULL,
                updated REAL NOT NULL,
                priority INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(user_key, kind, page)
            );
            CREATE INDEX IF NOT EXISTS idx_pages_updated ON pages(updated);
            CREATE TABLE IF NOT EXISTS users(
                user_key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated REAL NOT NULL,
                priority INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_users_updated ON users(updated);
            """
        )
        self._conn.commit()

    def _cleanup_stale(self) -> None:
        folder = os.path.join(tempfile.gettempdir(), "TiebaReplyStats")
        try:
            for name in os.listdir(folder):
                if not name.startswith("post-cache-") or not name.endswith(".db"):
                    continue
                path = os.path.join(folder, name)
                if os.path.abspath(path) == os.path.abspath(getattr(self, "_path", "")):
                    continue
                try:
                    os.remove(path)
                    for suffix in ("-wal", "-shm"):
                        extra = path + suffix
                        if os.path.exists(extra):
                            os.remove(extra)
                except OSError:
                    continue
        except OSError:
            pass

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            conn, self._conn = self._conn, None
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            if self._path:
                for path in (self._path, self._path + "-wal", self._path + "-shm"):
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except OSError:
                        pass

    def reopen(self) -> None:
        """关闭并重建当前会话缓存（清空所有数据后使用）。"""
        with self._lock:
            self.close()
            self._closed = False
            self._open()

    def clear(self) -> None:
        with self._lock:
            self._hot_pages.clear()
            self._hot_users.clear()
            self._hot_bytes = 0
            if self._conn is not None:
                self._conn.execute("DELETE FROM pages")
                self._conn.execute("DELETE FROM users")
                self._conn.commit()
                try:
                    self._conn.execute("VACUUM")
                except sqlite3.Error:
                    pass

    # ---------- hot memory ----------

    def _trim_hot(self) -> None:
        while len(self._hot_users) > HOT_MAX_USERS:
            self._hot_users.popitem(last=False)
        while self._hot_bytes > HOT_MAX_BYTES and self._hot_pages:
            _, (_, payload) = self._hot_pages.popitem(last=False)
            self._hot_bytes -= _json_size(payload)
        while self._hot_bytes > HOT_MAX_BYTES and self._hot_users:
            _, (_, data) = self._hot_users.popitem(last=False)
            self._hot_bytes -= _json_size(data)

    # ---------- raw pages ----------

    def get_page(self, user_key: str, kind: str, page: int) -> Optional[Dict]:
        if not user_key:
            return None
        key = (user_key, kind, page)
        with self._lock:
            hit = self._hot_pages.pop(key, None)
            if hit is not None:
                self._hot_pages[key] = hit
                return hit[1]
            if self._conn is None:
                return None
            row = self._conn.execute(
                "SELECT payload, updated FROM pages WHERE user_key=? AND kind=? AND page=?",
                (user_key, kind, page),
            ).fetchone()
            if not row:
                return None
            try:
                payload = json.loads(row[0])
            except (TypeError, ValueError):
                return None
            self._hot_pages[key] = (float(row[1]), payload)
            self._hot_bytes += _json_size(payload)
            self._trim_hot()
            return payload

    def put_page(self, user_key: str, kind: str, page: int, payload: Dict, priority: int = PRIORITY_HIGH) -> None:
        if not user_key or not payload:
            return
        now = time.time()
        with self._lock:
            key = (user_key, kind, page)
            old = self._hot_pages.pop(key, None)
            if old:
                self._hot_bytes -= _json_size(old[1])
            if priority != PRIORITY_LOW:
                self._hot_pages[key] = (now, payload)
                self._hot_bytes += _json_size(payload)
                self._trim_hot()
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO pages(user_key,kind,page,payload,updated,priority) VALUES(?,?,?,?,?,?)",
                    (user_key, kind, page, json.dumps(payload, ensure_ascii=False), now, priority),
                )
                self._conn.commit()
            self._enforce_limit()

    # ---------- normalized users ----------

    def get_user(self, user_key: str, promote: bool = True) -> Optional[Dict]:
        if not user_key:
            return None
        with self._lock:
            if promote:
                hit = self._hot_users.pop(user_key, None)
                if hit is not None:
                    self._hot_users[user_key] = hit
                    return hit[1]
            if self._conn is None:
                return None
            row = self._conn.execute(
                "SELECT data, updated FROM users WHERE user_key=?", (user_key,)
            ).fetchone()
            if not row:
                return None
            try:
                data = json.loads(row[0])
            except (TypeError, ValueError):
                return None
            if promote:
                self._hot_users[user_key] = (float(row[1]), data)
                self._hot_bytes += _json_size(data)
                self._trim_hot()
            return data

    def put_user(self, user_key: str, data: Dict, priority: int = PRIORITY_HIGH) -> None:
        if not user_key or not data:
            return
        now = time.time()
        with self._lock:
            old = self._hot_users.pop(user_key, None)
            if old:
                self._hot_bytes -= _json_size(old[1])
            if priority != PRIORITY_LOW:
                self._hot_users[user_key] = (now, data)
                self._hot_bytes += _json_size(data)
                self._trim_hot()
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO users(user_key,data,updated,priority) VALUES(?,?,?,?)",
                    (user_key, json.dumps(data, ensure_ascii=False), now, priority),
                )
                self._conn.commit()
            self._enforce_limit()

    def drop_user(self, user_key: str) -> None:
        with self._lock:
            old = self._hot_users.pop(user_key, None)
            if old:
                self._hot_bytes -= _json_size(old[1])
            for key in list(self._hot_pages):
                if key[0] == user_key:
                    self._hot_bytes -= _json_size(self._hot_pages.pop(key)[1])
            if self._conn is not None:
                self._conn.execute("DELETE FROM pages WHERE user_key=?", (user_key,))
                self._conn.execute("DELETE FROM users WHERE user_key=?", (user_key,))
                self._conn.commit()

    # ---------- size ----------

    def set_limit_mb(self, value: int) -> None:
        self._limit_mb = max(MIN_LIMIT_MB, min(MAX_LIMIT_MB, int(value)))
        self._enforce_limit()

    def limit_mb(self) -> int:
        return self._limit_mb

    def _bytes(self) -> int:
        total = 0
        for path in (self._path, self._path + "-wal", self._path + "-shm"):
            try:
                if path and os.path.exists(path):
                    total += os.path.getsize(path)
            except OSError:
                continue
        return total

    def _enforce_limit(self) -> None:
        if self._conn is None:
            return
        limit = self._limit_mb * 1024 * 1024
        if self._bytes() <= limit:
            return
        # 先删低优先，再删最久未用；按整用户删，避免中间页断档。
        rows = self._conn.execute(
            "SELECT user_key, MIN(priority) AS p, MIN(updated) AS u FROM pages GROUP BY user_key "
            "UNION SELECT user_key, priority AS p, updated AS u FROM users GROUP BY user_key "
            "ORDER BY p ASC, u ASC"
        ).fetchall()
        for user_key, _priority, _updated in rows:
            if self._bytes() <= limit:
                break
            self.drop_user(str(user_key))

    def stats(self) -> Dict[str, int]:
        with self._lock:
            pages = users = posts = 0
            if self._conn is not None:
                pages = int(self._conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
                users = int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
                for (raw,) in self._conn.execute("SELECT data FROM users"):
                    try:
                        posts += len((json.loads(raw) or {}).get("posts") or [])
                    except (TypeError, ValueError):
                        continue
            return {
                "hot_users": len(self._hot_users),
                "hot_bytes": self._hot_bytes,
                "cold_users": users,
                "cold_pages": pages,
                "cold_posts": posts,
                "cold_bytes": self._bytes(),
                "limit_mb": self._limit_mb,
            }


_CACHE = PostCache()


def cache() -> PostCache:
    return _CACHE


def clear_post_cache() -> None:
    _CACHE.clear()


def close_post_cache() -> None:
    _CACHE.close()
