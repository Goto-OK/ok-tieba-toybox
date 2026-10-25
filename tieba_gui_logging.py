"""GUI 日志内核 mixin（从 tieba_gui_tools.py 拆出）。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from tieba_reply_stats.settings import APP_DIR


class LoggingMixin:
    """日志写入与后台线程安全日志方法。"""

    settings: Any
    log_text: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _write_log(self, event: str, **fields) -> None:
        if not self.settings.get("log_enabled", False):
            return
        try:
            log_dir = os.path.join(APP_DIR, "logs")
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, f"app-{datetime.now():%Y%m%d}.log")
            record = {"time": datetime.now().isoformat(timespec="seconds"), "event": event}
            record.update({key: value for key, value in fields.items() if value not in (None, "")})
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + chr(10))
            files = sorted(
                (os.path.join(log_dir, name) for name in os.listdir(log_dir) if name.startswith("app-")),
                key=os.path.getmtime,
                reverse=True,
            )
            for old in files[7:]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            files = files[:7]
            total = 0
            sizes = {}
            for item in files:
                try:
                    sizes[item] = os.path.getsize(item)
                except OSError:
                    sizes[item] = 0
                total += sizes[item]
            for old in reversed(files):
                if total <= 10 * 1024 * 1024:
                    break
                if old == path:
                    continue
                try:
                    os.remove(old)
                    total -= sizes.get(old, 0)
                except OSError:
                    pass
        except OSError:
            pass


    def _log_from_thread(self, message: str) -> None:
        self._post(("log", message, None))


    def _append_log(self, text: str, tag: str | None = None) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag or ())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

