"""查用户页 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import ctypes
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Any, Dict, Optional
from urllib.parse import quote

from tieba_gui_utils import decode_display, display_text
from tieba_reply_stats.blacklist import LEVEL_LABEL
from tieba_reply_stats.fetch import Fetcher
from tieba_reply_stats.lookup_supplement import fetch_feed_thread_supplements, merge_current_threads
from tieba_reply_stats.profile import cached_user_posts, fetch_user_profile, resolve_user
from tieba_reply_stats.settings import save_settings


class LookupMixin:
    """查用户页方法，从 App 拆出。"""

    lookup_entry: Any
    lookup_native_host: Any
    lookup_native_edit: Any
    emoji_btn: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _on_lookup_parts_changed(self, *_args) -> None:
        self.lookup_start_var.set(self._group_date(self.lookup_start_parts))
        self.lookup_end_var.set(self._group_date(self.lookup_end_parts))
        if self.lookup_date_mode_var.get() == "指定日期":
            self._on_lookup_date_changed()


    def _on_lookup_date_changed(self) -> None:
        self._toggle_lookup_dates()
        if self.lookup_date_mode_var.get() == "指定日期":
            self.lookup_start_var.set(self._group_date(self.lookup_start_parts))
            self.lookup_end_var.set(self._group_date(self.lookup_end_parts))
        else:
            self.lookup_start_var.set("")
            self.lookup_end_var.set("")
            self.lookup_prefer_var.set("优先最近")
        if hasattr(self, "_lookup_cache"):
            self._lookup_cache.clear()
        if self.lookup_query_var.get().strip():
            self.lookup_status.configure(text="条件已变更，点「查询」生效")


    def _toggle_lookup_dates(self) -> None:
        enabled = self.lookup_date_mode_var.get() == "指定日期"
        try:
            if enabled:
                if not self.lookup_date_row.winfo_ismapped():
                    self.lookup_date_row.pack(fill="x", after=self.lookup_options)
            else:
                self.lookup_date_row.pack_forget()
        except tk.TclError:
            pass


    def _on_lookup_query_changed(self, *_args) -> None:
        if getattr(self, "_normalizing_query", False):
            return
        if not self.lookup_query_var.get().strip():
            self._reset_lookup_traffic()
        pending = getattr(self, "_lookup_normalize_job", None)
        if pending is not None:
            try:
                self.root.after_cancel(pending)
            except tk.TclError:
                pass
        self._lookup_normalize_job = self.root.after(50, self._normalize_lookup_query)


    def _normalize_lookup_query(self) -> None:
        self._lookup_normalize_job = None
        if getattr(self, "_normalizing_query", False):
            return
        raw = self._lookup_text()
        decoded = decode_display(raw)
        if decoded == raw:
            return
        self._normalizing_query = True
        try:
            if self.lookup_native_edit:
                self._set_lookup_query_text(decoded)
            elif self.lookup_entry is not None:
                try:
                    pos = self.lookup_entry.index("insert")
                    new_pos = len(decode_display(raw[:pos]))
                except (tk.TclError, AttributeError):
                    new_pos = len(decoded)
                self.lookup_query_var.set(decoded)
                self.lookup_entry.icursor(new_pos)
            else:
                self.lookup_query_var.set(decoded)
        finally:
            self._normalizing_query = False


    def _build_lookup_fallback_entry(self, parent, query_button) -> None:
        self.emoji_btn = tk.Button(
            parent,
            text="😀",
            command=self._open_emoji_panel,
            font=("Segoe UI Emoji", 12),
            width=3,
            relief="flat",
            bg="#eef1f5",
            activebackground="#dbeafe",
            cursor="hand2",
        )
        self.emoji_btn.pack(side="right", padx=(6, 0))
        entry = ttk.Entry(
            parent,
            textvariable=self.lookup_query_var,
            width=34,
            font=("Microsoft YaHei UI", 10),
        )
        self.lookup_entry = entry
        entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        entry.bind("<Return>", lambda _event: self._on_lookup())
        self.lookup_query_var.trace_add("write", self._on_lookup_query_changed)


    def _create_lookup_native_edit(self) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
            ]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            user32.SendMessageW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]
            user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.MoveWindow.argtypes = [
                wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL
            ]
            gdi32.CreateFontW.restype = wintypes.HFONT
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            host = tk.Frame(self.lookup_query_bar, bg="#ffffff", height=34)
            host.pack(side="left", fill="x", expand=True, padx=(4, 0))
            host.pack_propagate(False)
            style = 0x40000000 | 0x10000000 | 0x00010000 | 0x00800000 | 0x00000080
            edit = user32.CreateWindowExW(
                0x00000200, "EDIT", "", style, 0, 0, 100, 30,
                wintypes.HWND(host.winfo_id()), None, kernel32.GetModuleHandleW(None), None,
            )
            if not edit:
                host.destroy()
                return False
            self.lookup_native_edit = edit
            self.lookup_native_host = host
            font = gdi32.CreateFontW(
                -16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft YaHei UI"
            )
            self._lookup_native_font = font
            if font:
                user32.SendMessageW(edit, 0x0030, font, 1)

            def resize(event) -> None:
                user32.MoveWindow(edit, 0, 0, max(40, event.width), max(20, event.height), True)

            host.bind("<Configure>", resize)
            resize(type("E", (), {"width": 500, "height": 30})())

            user32.CallWindowProcW.restype = ctypes.c_ssize_t
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]

            def on_key(hwnd, msg, wparam, lparam):
                if msg == 0x0100 and wparam == 0x0D:
                    self.root.after_idle(self._on_lookup)
                    return 0
                return user32.CallWindowProcW(old_proc, hwnd, msg, wparam, lparam)

            proc_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )
            self._lookup_native_proc = proc_type(on_key)
            set_ptr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            set_ptr.restype = ctypes.c_void_p
            set_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            old_proc = set_ptr(edit, -4, ctypes.cast(self._lookup_native_proc, ctypes.c_void_p))
            self._lookup_native_old_proc = old_proc
            self._lookup_native_user32 = user32
            self.root.bind_all("<Button-1>", self._release_lookup_native_focus, add="+")
            return True
        except Exception:  # noqa: BLE001
            failed_host: Optional[tk.Frame] = getattr(self, "lookup_native_host", None)
            if failed_host is not None:
                try:
                    failed_host.destroy()
                except tk.TclError:
                    pass
            self.lookup_native_host = None
            self.lookup_native_edit = None
            return False


    def _lookup_text(self) -> str:
        edit = getattr(self, "lookup_native_edit", None)
        if not edit:
            return self.lookup_query_var.get()
        user32 = getattr(self, "_lookup_native_user32", None)
        if user32 is None:
            return self.lookup_query_var.get()
        length = user32.GetWindowTextLengthW(edit)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(edit, buffer, length + 1)
        return buffer.value


    def _set_lookup_query_text(self, text: str) -> None:
        self.lookup_query_var.set(text)
        edit = getattr(self, "lookup_native_edit", None)
        user32 = getattr(self, "_lookup_native_user32", None)
        if edit and user32 is not None:
            buffer = ctypes.create_unicode_buffer(text)
            user32.SendMessageW(edit, 0x000C, 0, ctypes.addressof(buffer))


    def _lookup_focus(self) -> None:
        edit = getattr(self, "lookup_native_edit", None)
        user32 = getattr(self, "_lookup_native_user32", None)
        if edit and user32 is not None:
            user32.SetFocus(edit)
            return
        entry = self.lookup_entry
        if entry is not None:
            entry.focus_set()


    def _release_lookup_native_focus(self, event) -> None:
        """Clicking a Tk widget must take Win32 focus back from child EDITs."""
        widget = getattr(event, "widget", None)
        if widget is None:
            return
        edits = (
            (getattr(self, "lookup_native_edit", None), getattr(self, "_lookup_native_user32", None)),
            (getattr(self, "love_native_edit", None), getattr(self, "_love_native_user32", None)),
        )
        for edit, user32 in edits:
            if not edit or user32 is None:
                continue
            try:
                widget.focus_set()
                user32.SetFocus(widget.winfo_id())
            except (AttributeError, OSError, tk.TclError):
                pass


    def _lookup_insert_text(self, text: str) -> None:
        edit = getattr(self, "lookup_native_edit", None)
        user32 = getattr(self, "_lookup_native_user32", None)
        if edit and user32 is not None:
            buffer = ctypes.create_unicode_buffer(text)
            user32.SendMessageW(edit, 0x00C2, 1, ctypes.addressof(buffer))
            return
        entry = self.lookup_entry
        if entry is not None:
            entry.insert("insert", text)


    def _sync_lookup_text_from_native(self) -> None:
        if not getattr(self, "lookup_native_edit", None):
            return
        text = self._lookup_text()
        if text != self.lookup_query_var.get():
            self.lookup_query_var.set(text)


    def _poll_native_lookup_text(self) -> None:
        if not getattr(self, "lookup_native_edit", None):
            return
        self._sync_lookup_text_from_native()
        self.root.after(120, self._poll_native_lookup_text)


    def _open_lookup_profile(self) -> None:
        profile = getattr(self, "_last_lookup_profile", None)
        if not profile:
            messagebox.showinfo("还没有资料", "先查询一个用户。", parent=self.root)
            return
        username = str(profile.get("username") or "")
        portrait = str(profile.get("portrait") or "").split("?")[0]
        if username:
            webbrowser.open("https://tieba.baidu.com/home/main?un=" + quote(username))
        elif portrait:
            webbrowser.open("https://tieba.baidu.com/home/main?id=" + quote(portrait))
        else:
            messagebox.showinfo("无法打开主页", "这个用户缺少用户名和头像标识。", parent=self.root)


    def _open_lookup_forum(self) -> None:
        selection = self.lookup_forum_tree.selection()
        if not selection:
            return
        name = self._lookup_forum_names.get(selection[0])
        if name:
            webbrowser.open("https://tieba.baidu.com/f?kw=" + quote(name))


    def _open_lookup_post(self) -> None:
        selection = self.lookup_post_tree.selection()
        if not selection:
            return
        url = self._lookup_post_urls.get(selection[0])
        if url:
            webbrowser.open(url)


    def _copy_lookup_summary(self) -> None:
        text = str(self.lookup_info.cget("text") or "")
        if text:
            self._copy_text(text)


    def _copy_lookup(self) -> None:
        lines = []
        for item in self.lookup_forum_tree.get_children():
            lines.append("\t".join(str(v) for v in self.lookup_forum_tree.item(item, "values")))
        lines.append("")
        for item in self.lookup_post_tree.get_children():
            lines.append("\t".join(str(v) for v in self.lookup_post_tree.item(item, "values")))
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.lookup_status.configure(text="已复制")


    def _reset_lookup_traffic(self) -> None:
        try:
            self.lookup_traffic_text.configure(text="")
            for _key, (traffic_label, _color) in getattr(self, "lookup_traffic_labels", {}).items():
                traffic_label.configure(fg="#d1d5db")
        except tk.TclError:
            pass


    def _set_lookup_text(self, content: str) -> None:
        for tree in (self.lookup_forum_tree, self.lookup_post_tree):
            for item in tree.get_children():
                tree.delete(item)
        self._reset_lookup_traffic()
        self.lookup_info.configure(text=content)


    def _supplement_lookup(self, fetcher, profile, count, start_date, end_date):
        original = list(profile.get("recent_posts") or [])
        merged = original
        current_added = 0
        retrace_added = 0
        failed = 0
        current_tids = set()
        try:
            current = merge_current_threads(merged, getattr(self, "last_threads", []), profile)
            current_added = len(current["posts"])
            merged = merged + current["posts"]
            current_tids = {str(t.meta.tid) for t in getattr(self, "last_threads", [])}
        except Exception:  # noqa: BLE001
            current_added = 0
        if self.settings.get("lookup_fill_threads", False):
            try:
                full = bool(self.settings.get("lookup_fill_all", False))
                limit = 0 if full else max(1, int(self.settings.get("lookup_fill_limit", 50) or 50))
                retrace = fetch_feed_thread_supplements(
                    fetcher,
                    merged,
                    profile,
                    limit=limit,
                    full=full,
                    include_comments=bool(self.settings.get("lookup_fill_comments", False)),
                    current_tids=current_tids,
                    log=None,
                )
                retrace_added = len(retrace["posts"])
                failed = int(retrace.get("failed") or 0)
                merged = merged + retrace["posts"]
            except Exception:  # noqa: BLE001
                failed += 1
        seen = set()
        filtered = []
        start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
        for post in merged:
            pid = str(post.get("pid") or "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            day = None
            try:
                day = datetime.strptime(str(post.get("time") or "")[:10], "%Y-%m-%d").date()
            except ValueError:
                pass
            if start and day and day < start:
                continue
            if end and day and day > end:
                continue
            filtered.append(post)
        filtered.sort(key=lambda item: int(item.get("ts") or 0), reverse=True)
        shown = filtered[:count]
        profile["recent_posts"] = shown
        profile["_supplement"] = {
            "official": len(original),
            "current": current_added,
            "retrace": retrace_added,
            "failed": failed,
            "total": len(filtered),
            "shown": len(shown),
        }
        return profile


    def _on_lookup(self) -> None:
        self._sync_lookup_text_from_native()
        self._normalize_lookup_query()
        query = self.lookup_query_var.get().strip()
        if not query:
            self.lookup_status.configure(text="先输入要查询的内容")
            self._reset_lookup_traffic()
            return
        raw_query = query
        query = decode_display(query).strip() or query
        encoded_query = display_text(raw_query).lower()
        self._lookup_generation = getattr(self, "_lookup_generation", 0) + 1
        generation = self._lookup_generation
        mode = self.lookup_mode_var.get()
        if mode == "用户名" and query.isdigit():
            mode = "贴吧ID"
        try:
            count = int(self.lookup_count_var.get())
        except ValueError:
            count = 20
        count = max(5, min(1000, count))
        date_mode = self.lookup_date_mode_var.get()
        if date_mode != "指定日期":
            self.lookup_start_var.set("")
            self.lookup_end_var.set("")
        start_date = self.lookup_start_var.get().strip() if date_mode == "指定日期" else ""
        end_date = self.lookup_end_var.get().strip() if date_mode == "指定日期" else ""
        prefer = (
            "start"
            if date_mode == "指定日期" and "最早" in self.lookup_prefer_var.get()
            else "end"
        )
        cache_key = (
            f"{query}|{mode}|{count}|{start_date}|{end_date}|"
            f"{prefer}|{self.mode_var.get()}|{self._lookup_topic_limit}|"
            f"{self.settings.get('lookup_fill_threads')}|{self.settings.get('lookup_fill_pages')}|"
            f"{self.settings.get('lookup_fill_limit')}|{self.settings.get('lookup_fill_all')}|"
            f"{self.settings.get('lookup_fill_comments')}"
        )
        hit = self._lookup_cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < 60:
            hit[1]["_ui_cache_age_seconds"] = max(0, int(time.monotonic() - hit[0]))
            self._render_lookup(hit[1])
            self.lookup_status.configure(text=f"{hit[1].get('username') or ''} · 缓存结果")
            return
        self.lookup_status.configure(text="查询中…")
        self._set_lookup_cache_note("")
        self._set_lookup_text("查询中，请稍候…")

        def worker():
            try:
                fetcher = Fetcher(cookie=self._request_cookie(), delay=0, verbose=False)
                info = {}
                if mode == "昵称":
                    # 先在当前抓到的参与者里找（最可靠，避免昵称搜索接口搜不到）
                    for user in getattr(self, "people_users", []):
                        real_name = (user.get("name") or "").strip()
                        if (
                            real_name.lower() == query.lower()
                            or display_text(real_name).lower() == encoded_query
                        ):
                            info = {
                                "uid": user.get("uid") or "",
                                "username": user.get("username") or "",
                                "nickname": user.get("name") or "",
                                "portrait": user.get("portrait") or "",
                            }
                            break
                if not info:
                    info = resolve_user(fetcher, query, mode)
                if generation != self._lookup_generation:
                    return
                if not info.get("uid"):
                    self._post(
                        (
                            "lookup_ready",
                            None,
                            f"按「{mode}」没有找到这个人（昵称不唯一；贴吧ID不是内部用户ID）",
                        )
                    )
                    return
                local_cached = cached_user_posts(info["uid"], count, start_date, end_date, prefer)
                profile = fetch_user_profile(
                    fetcher,
                    info["uid"],
                    info["username"],
                    info["portrait"],
                    "",
                    count,
                    start_date,
                    end_date,
                    prefer,
                    topic_max_pages=self._lookup_topic_limit,
                    cached_posts=local_cached,
                )
                if generation != self._lookup_generation:
                    return
                profile["nickname"] = profile.get("nickname") or info.get("nickname") or ""
                profile["tieba_uid"] = profile.get("tieba_uid") or info.get("tieba_uid") or ""
                if profile.get("ok"):
                    self._attach_love_levels(profile)
                if profile.get("ok"):
                    profile = self._supplement_lookup(
                        fetcher, profile, count, start_date, end_date
                    )
                if profile.get("ok"):
                    if len(self._lookup_cache) >= 200:
                        self._lookup_cache.clear()
                    self._lookup_cache[cache_key] = (time.monotonic(), profile)
                self._post(("lookup_ready", profile, ""))
            except Exception as error:  # noqa: BLE001
                if generation == self._lookup_generation:
                    self._post(("lookup_ready", None, str(error)))

        threading.Thread(target=worker, daemon=True).start()


    def _probe_lookup_forums(self) -> None:
        if getattr(self, "_probe_running", False):
            self._probe_stop.set()
            return
        profile = getattr(self, "_last_lookup_profile", None)
        if not profile:
            return
        user: Dict[str, Any] = {
            "uid": profile.get("user_id") or "",
            "portrait": profile.get("portrait") or "",
            "bars": [],
        }
        self._start_probe(user, profile, self.lookup_probe_btn)


    def _set_lookup_cache_note(self, text: str) -> None:
        self.lookup_cache_label.configure(text=text)
        if text:
            if not self.lookup_cache_row.winfo_manager():
                self.lookup_cache_row.pack(fill="x", after=self.lookup_summary)
        else:
            self.lookup_cache_row.pack_forget()


    def _render_lookup(self, profile) -> None:
        forum_tree = self.lookup_forum_tree
        post_tree = self.lookup_post_tree
        for tree in (forum_tree, post_tree):
            self._clear_loaded_tree(tree)
        self._lookup_forum_names = {}
        self._lookup_post_urls = {}
        self._set_lookup_cache_note("")
        if not profile:
            self.lookup_info.configure(text="没有查到这个人。")
            try:
                self.lookup_traffic_text.configure(text="")
                for _key, (traffic_label, _color) in self.lookup_traffic_labels.items():
                    traffic_label.configure(fg=self.palette["disabled_text"])
            except tk.TclError:
                pass
            return
        self._last_lookup_profile = profile

        combined = self._merge_forum_lists(profile)
        posts = profile.get("recent_posts") or []
        has_supplement = any(str(post.get("source") or "") not in ("", "官方") for post in posts)
        post_tree["displaycolumns"] = (
            ("time", "type", "bar", "title", "content", "source")
            if has_supplement
            else ("time", "type", "bar", "title", "content")
        )

        for index, forum in enumerate(combined):
            iid = str(index)
            forum_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    forum["name"],
                    f"Lv.{forum['level']}" if forum.get("level") else "-",
                    forum.get("level_source") or "-",
                    forum.get("source") or "",
                ),
                tags=self._row_tags(forum["name"], "forum"),
            )
            self._lookup_forum_names[iid] = forum["name"]
        self._request_love_levels(profile, combined, forum_tree, self._lookup_forum_names, "lookup")
        for index, post in enumerate(posts):
            iid = str(index)
            post_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    post.get("time") or "",
                    post.get("type") or "",
                    post.get("bar") or "",
                    post.get("title") or "",
                    post.get("content") or "",
                    post.get("source") or "官方",
                ),
                tags=self._row_tags(post.get("bar"), "posts"),
            )
            self._lookup_post_urls[iid] = post.get("url") or ""
        forum_note = self._forum_note(profile)
        self.lookup_forum_note.configure(text=forum_note)

        supplement = profile.get("_supplement") or {}
        supplement_note = ""
        if supplement:
            supplement_note = (
                f" | 官方 {supplement.get('official', 0)} / 当前已抓主题 {supplement.get('current', 0)}"
                f" / 回抓主题 {supplement.get('retrace', 0)} / 失败 {supplement.get('failed', 0)}"
                f" / 合计 {supplement.get('total', len(posts))} / 显示 {supplement.get('shown', len(posts))}"
            )
        info = (
            f"昵称 {display_text(profile.get('nickname')) or '未知'} | 用户名 {profile.get('username') or '未知'} | "
            f"贴吧ID {self._tieba_uid_cell(profile)} | 用户ID {profile.get('user_id') or '未知'} | "
            f"发言 {len(posts)} 条 | 关注 {len(combined)} 个{supplement_note}"
        )
        if profile.get("followed_count"):
            info += f"（对方填 {profile['followed_count']}）"
        if profile.get("fans") is not None:
            info += f" | 粉丝 {profile['fans']}"
        if profile.get("concern") is not None:
            info += f" | 关注数 {profile['concern']}"
        if profile.get("post_num"):
            info += f" | 发帖 {profile['post_num']}"
        if self.mode_var.get() == "guest":
            info += " | 免登录：关注列表可能不完整"
        hit_level, hit_bar = self._profile_hit(profile) if posts else ("", "")
        hidden_follows = self._hidden_follows(profile) if self._risk_enabled() else False
        risk_reason = (
            "关注列表隐藏"
            if self.mode_var.get() != "guest" or hidden_follows
            else "关注列表未加载"
        )
        label = LEVEL_LABEL.get(hit_level, "")
        for key, (traffic_label, traffic_color) in getattr(self, "lookup_traffic_labels", {}).items():
            traffic_label.configure(
                fg=traffic_color if key == hit_level else self.palette["disabled_text"]
            )
        if hit_level:
            traffic_note = f"{label}：{hit_bar}" if hit_bar and hit_bar != "关注列表隐藏" else label
        elif not self._risk_enabled():
            traffic_note = "本地标记已关闭"
        else:
            traffic_note = "未命中"
        if hidden_follows and self._risk_enabled():
            traffic_note += f" · ⚠ {risk_reason}，未命中警告时标黄"
        try:
            self.lookup_traffic_text.configure(text=traffic_note)
        except tk.TclError:
            pass
        if hit_level:
            info += f" | 命中{label}：{hit_bar}"
        if hidden_follows and self._risk_enabled():
            info += f" | ⚠ {risk_reason}，未命中警告时标黄"
        note = self._post_source_note(profile)
        if note:
            info += " | " + note
        self.lookup_info.configure(text=info)
        self._set_lookup_cache_note(self._cache_age_note(profile))
        self.lookup_status.configure(
            text=(f"{profile.get('username') or ''} · {len(posts)} 条发言" + (f" · {note}" if note else ""))
        )
        self.lookup_report_btn.pack(side="left", padx=(0, 6))
        self.lookup_posts_btn.pack(side="left", padx=(0, 6))
        sources = profile.get("post_sources") or {}
        if sources.get("topic_truncated"):
            topic_text = f"继续抓主题（已 {sources.get('topic_pages') or 50} 页）"
            self.lookup_topic_btn.configure(text=topic_text, width=max(12, len(topic_text) + 2))
            self.lookup_topic_btn.pack(side="left", padx=(0, 6))
        else:
            self.lookup_topic_btn.pack_forget()
        if self._follow_incomplete(profile):
            self.lookup_probe_btn.pack(side="left", padx=(6, 0))
            self.lookup_probe_btn.configure(state="normal", text="探测候选关注")
        else:
            self.lookup_probe_btn.pack_forget()


    def _continue_lookup_topics(self) -> None:
        choice = self._ask_choice(
            "继续抓主题",
            "主题流已达到本次上限，继续会追加请求；已缓存的页不会重复抓。",
            [("再抓 50 页", "more"), ("一直抓到开始日期", "all"), ("停止", None)],
            default=0,
        )
        if choice is None:
            self.lookup_topic_btn.pack_forget()
            return
        self._lookup_topic_limit = (
            100000 if choice == "all" else int(getattr(self, "_lookup_topic_limit", 50)) + 50
        )
        self._lookup_cache.clear()
        self._on_lookup()


    def _on_lookup_fill_changed(self) -> None:
        enabled = bool(self.lookup_fill_var.get())
        if enabled and not self.settings.get("lookup_fill_threads", False):
            if not messagebox.askyesno(
                "启用回抓主题",
                "开启后会从官方 feed 提取主题并逐个抓取。\n"
                "每个主题至少一次请求，可能明显变慢；只补当前主题抓不到的内容。\n\n继续？",
                parent=self.root,
            ):
                self.lookup_fill_var.set(False)
                enabled = False
        all_topics = bool(self.lookup_fill_all_var.get())
        if all_topics and not self.settings.get("lookup_fill_all", False):
            if not messagebox.askyesno(
                "补全所有 feed 主题（特慢）",
                "勾选后会抓完整主题，且不限制主题数量。\n"
                "一次查询可能耗时几分钟，并增加触发安全验证的风险。\n\n继续？",
                parent=self.root,
            ):
                self.lookup_fill_all_var.set(False)
                all_topics = False
        try:
            limit = max(1, min(10000, int(self.lookup_fill_limit_var.get())))
        except ValueError:
            limit = 50
        self.settings["lookup_fill_threads"] = enabled
        self.settings["lookup_fill_pages"] = "full" if self.lookup_fill_pages_var.get() == "完整主题" else "1"
        self.settings["lookup_fill_limit"] = limit
        self.settings["lookup_fill_all"] = all_topics
        self.settings["lookup_fill_comments"] = bool(self.lookup_fill_comments_var.get())
        if all_topics:
            self.settings["lookup_fill_pages"] = "full"
        save_settings(self.settings)
        try:
            state = "disabled" if all_topics else "readonly"
            self.lookup_fill_pages_box.configure(state=state)
            self.lookup_fill_limit_box.configure(state="disabled" if all_topics else "normal")
        except tk.TclError:
            pass
        self.general_hint.configure(text="已保存")


    def _export_lookup_report(self) -> None:
        profile = getattr(self, "_last_lookup_profile", None)
        if not profile:
            messagebox.showinfo("还没有资料", "先查询一个用户。", parent=self.root)
            return
        user = {
            "name": profile.get("nickname") or "",
            "username": profile.get("username") or "",
            "uid": profile.get("user_id") or "",
            "level": "",
        }
        self._choose_report_path(user, profile, None)


    def _export_lookup_posts(self) -> None:
        profile = getattr(self, "_last_lookup_profile", None)
        if not profile:
            messagebox.showinfo("还没有资料", "先查询一个用户。", parent=self.root)
            return
        user = {
            "name": profile.get("nickname") or "",
            "username": profile.get("username") or "",
            "uid": profile.get("user_id") or "",
        }
        start = self.lookup_start_var.get().strip() if self.lookup_date_mode_var.get() == "指定日期" else ""
        end = self.lookup_end_var.get().strip() if self.lookup_date_mode_var.get() == "指定日期" else ""
        self._export_posts_for(user, profile, start, end)

