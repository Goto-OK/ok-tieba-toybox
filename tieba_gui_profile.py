"""用户资料/关注页 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import ctypes
import os
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from tieba_gui_utils import display_text
from tieba_reply_stats import profile_pb, third_party
from tieba_reply_stats.blacklist import LEVEL_LABEL, classify, marker
from tieba_reply_stats.errors import friendly_error
from tieba_reply_stats.fetch import Fetcher
from tieba_reply_stats.link_parser import parse_links
from tieba_reply_stats.lookup_supplement import merge_current_threads
from tieba_reply_stats.profile import cached_user_posts, fetch_user_profile, resolve_user
from tieba_reply_stats.settings import save_settings


class ProfileMixin:
    """用户资料与关注页方法，从 App 拆出。"""

    love_native_edit: Any
    love_native_host: Any
    _profile_cache: Any
    _lookup_cache: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _create_love_native_edit(self) -> bool:
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
            style = 0x40000000 | 0x10000000 | 0x00010000 | 0x00800000 | 0x00000080
            edit = user32.CreateWindowExW(
                0x00000200, "EDIT", "", style, 0, 0, 100, 28,
                wintypes.HWND(self.love_edit_host.winfo_id()), None, kernel32.GetModuleHandleW(None), None,
            )
            if not edit:
                return False
            self.love_native_edit = edit
            self.love_native_host = self.love_edit_host
            font = gdi32.CreateFontW(
                -16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft YaHei UI"
            )
            self._love_native_font = font
            if font:
                user32.SendMessageW(edit, 0x0030, font, 1)

            def resize(event) -> None:
                user32.MoveWindow(edit, 0, 0, max(40, event.width), max(20, event.height), True)

            self.love_edit_host.bind("<Configure>", resize)
            resize(type("E", (), {"width": 260, "height": 28})())

            user32.CallWindowProcW.restype = ctypes.c_ssize_t
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]

            def on_key(hwnd, msg, wparam, lparam):
                if msg == 0x0100 and wparam == 0x0D:
                    self.root.after_idle(self._start_love)
                    return 0
                return user32.CallWindowProcW(old_proc, hwnd, msg, wparam, lparam)

            proc_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )
            self._love_native_proc = proc_type(on_key)
            set_ptr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            set_ptr.restype = ctypes.c_void_p
            set_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            old_proc = set_ptr(edit, -4, ctypes.cast(self._love_native_proc, ctypes.c_void_p))
            self._love_native_old_proc = old_proc
            self._love_native_user32 = user32
            self.root.bind_all("<Button-1>", self._release_lookup_native_focus, add="+")
            return True
        except Exception:  # noqa: BLE001
            self.love_native_edit = None
            self.love_native_host = None
            return False


    def _love_text(self) -> str:
        edit = getattr(self, "love_native_edit", None)
        user32 = getattr(self, "_love_native_user32", None)
        if edit and user32 is not None:
            length = user32.GetWindowTextLengthW(edit)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(edit, buffer, length + 1)
            return buffer.value
        return self.love_query_var.get()


    def _love_focus(self) -> None:
        edit = getattr(self, "love_native_edit", None)
        user32 = getattr(self, "_love_native_user32", None)
        if edit and user32 is not None:
            user32.SetFocus(edit)
            return
        if self.love_entry is not None:
            self.love_entry.focus_set()


    def _probe_profile_forums(self) -> None:
        if getattr(self, "_probe_running", False):
            self._probe_stop.set()
            return
        user = getattr(self, "_profile_user", None)
        profile = getattr(self, "_profile_data", None)
        if not user or not profile:
            return
        self._start_probe(user, profile, self.profile_probe_btn)


    def _set_profile_cache_note(self, text: str) -> None:
        self.profile_cache_label.configure(text=text)
        if text:
            if not self.profile_cache_label.winfo_manager():
                self.profile_cache_label.pack(
                    fill="x", padx=6, pady=(0, 1), before=self.profile_action_bar
                )
        else:
            self.profile_cache_label.pack_forget()


    def _attach_love_levels(self, profile) -> None:
        if not self.settings.get("love_level_enabled", False):
            return
        username = str(profile.get("username") or "")
        if not username:
            return
        cache = getattr(self, "_all_levels_cache", None)
        if cache is None:
            cache = {}
            self._all_levels_cache = cache
        if username in cache:
            levels = cache[username]
        else:
            try:
                levels = third_party.fetch_all_levels(username)
            except Exception:  # noqa: BLE001
                levels = []
            cache[username] = levels
        if levels:
            profile["level_forums"] = levels


    def _request_love_levels(self, profile, forums, tree, names, kind) -> None:
        if not self.settings.get("love_level_enabled", False):
            return
        uid = str(profile.get("tieba_uid") or "")
        username = str(profile.get("username") or "")
        if not uid and not username:
            return
        missing = [forum for forum in forums if not int(forum.get("level") or 0)]
        if not missing:
            return
        cache = getattr(self, "_level_cache", None)
        if cache is None:
            cache = {}
            self._level_cache = cache
        pending = [forum for forum in missing if (uid or username, forum.get("name")) not in cache]
        pending = pending[:50]
        if not pending:
            return

        def worker():
            results = {}
            for forum in pending:
                name = str(forum.get("name") or "")
                if not name:
                    continue
                try:
                    data = third_party.fetch_level(uid, name, username)
                except Exception:  # noqa: BLE001
                    data = None
                if data and data.get("level"):
                    results[name] = data
                    cache[(uid or username, name)] = data
            if results:
                self._post(("levels_ready", kind, profile, forums, results))

        threading.Thread(target=worker, daemon=True).start()


    def _open_current_profile(self) -> None:
        selection = self.people_tree.selection()
        if not selection:
            return
        try:
            user = self.people_users[int(selection[0])]
        except (IndexError, ValueError):
            return
        username = user.get("username") or ""
        portrait = str(user.get("portrait") or "").split("?")[0]
        if username:
            webbrowser.open("https://tieba.baidu.com/home/main?un=" + quote(username))
        elif portrait:
            webbrowser.open("https://tieba.baidu.com/home/main?id=" + quote(portrait))
        else:
            messagebox.showinfo("无法打开主页", "这个用户缺少用户名和头像标识。", parent=self.root)


    def _build_love_tab(self) -> None:
        page = self.tab_love
        top = tk.Frame(page, bg="#ffffff", padx=12, pady=8)
        top.pack(fill="x")
        row = tk.Frame(top, bg="#ffffff")
        row.pack(fill="x")
        tk.Label(row, text="查询方式：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.love_mode_var = tk.StringVar(value="用户名")
        ttk.Combobox(
            row,
            values=("用户名", "贴吧ID", "昵称"),
            textvariable=self.love_mode_var,
            width=7,
            state="readonly",
        ).pack(side="left", padx=(0, 6))
        tk.Label(row, text="接口：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.love_api_var = tk.StringVar(value="查发言（新）")
        ttk.Combobox(
            row,
            values=("查发言（新）", "查发言（旧）"),
            textvariable=self.love_api_var,
            width=10,
            state="readonly",
        ).pack(side="left", padx=(0, 6))
        tk.Label(row, text="内容：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.love_query_var = tk.StringVar()
        self.love_entry = None
        self.love_edit_host = tk.Frame(row, bg="#ffffff", height=28)
        self.love_edit_host.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.love_edit_host.pack_propagate(False)
        if os.name != "nt" or not self._create_love_native_edit():
            self.love_entry = ttk.Entry(self.love_edit_host, textvariable=self.love_query_var, width=24)
            self.love_entry.pack(fill="x", expand=True)
        self.love_auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="自动连续翻页", variable=self.love_auto_var).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="抓取", command=self._start_love).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="下一页", command=self._next_love).pack(side="left", padx=(4, 0))
        ttk.Button(row, text="停止", command=self._stop_love).pack(side="left", padx=(4, 0))
        ttk.Button(row, text="打开主页", command=self._open_love_profile).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="打开选中链接", command=self._open_love_link).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="导出已加载", command=self._export_love).pack(side="left", padx=(8, 0))
        self.love_status = tk.Label(
            top,
            text="数据来自恋文（第三方）+ 官方主题补全；非百度官方。",
            bg="#ffffff",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        )
        self.love_status.pack(anchor="w", pady=(4, 0))

        wrap = tk.Frame(page, bg="#eef1f5")
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.love_tree = ttk.Treeview(
            wrap,
            columns=("time", "type", "bar", "title", "content", "floor", "link"),
            show="headings",
            height=18,
        )
        for key, title, width in (
            ("time", "日期", 120),
            ("type", "类型", 60),
            ("bar", "贴吧", 100),
            ("title", "标题", 220),
            ("content", "内容", 300),
            ("floor", "楼层", 60),
            ("link", "链接", 260),
        ):
            self.love_tree.heading(key, text=title)
            self.love_tree.column(key, width=width, anchor="center" if key in ("time", "type", "floor") else "w")
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.love_tree.yview)
        xscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.love_tree.xview)
        self.love_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.love_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self._love_urls: Dict[str, str] = {}
        self.love_tree.bind("<Double-1>", lambda _event: self._open_love_link())
        self.love_tree.bind("<Control-c>", lambda _event: self._copy_love_link())
        self.love_menu = tk.Menu(self.love_tree, tearoff=0)
        self.love_menu.add_command(label="打开链接", command=self._open_love_link)
        self.love_menu.add_command(label="复制链接", command=self._copy_love_link)
        self.love_tree.bind(
            "<Button-3>",
            lambda event: self._popup_tree_menu(self.love_tree, self.love_menu, event),
        )
        self._love_rows: List[Dict] = []
        self._love_seen: set = set()
        self._love_page = 0
        self._love_has_next = True
        self._love_running = False
        self._love_stop = threading.Event()


    def _selected_love_url(self) -> str:
        selection = self.love_tree.selection()
        return self._love_urls.get(selection[0], "") if selection else ""


    def _open_love_profile(self) -> None:
        query = self._love_text().strip()
        if not query:
            self.love_status.configure(text="先输入用户名 / 贴吧ID / 昵称")
            return
        mode = self.love_mode_var.get()
        username = ""
        portrait = ""
        if mode == "用户名":
            username = query
        else:
            try:
                fetcher = Fetcher(cookie={}, delay=0.2, verbose=False)
                if mode == "贴吧ID":
                    info = profile_pb.fetch_profile_by_tieba_uid(fetcher, query)
                    username = str(info.get("username") or "")
                    portrait = str(info.get("portrait") or "")
                else:
                    info = resolve_user(fetcher, query, "昵称")
                    username = str(info.get("username") or "")
                    portrait = str(info.get("portrait") or "")
            except Exception as error:  # noqa: BLE001
                self.love_status.configure(text=f"解析主页失败：{error}")
                return
        if not username and not portrait:
            self.love_status.configure(text="没有解析到可打开的主页")
            return
        if username:
            webbrowser.open("https://tieba.baidu.com/home/main?un=" + quote(username))
        else:
            webbrowser.open("https://tieba.baidu.com/home/main?id=" + quote(portrait))


    def _open_love_link(self) -> None:
        url = self._selected_love_url()
        if url:
            webbrowser.open(url)


    def _copy_love_link(self) -> None:
        url = self._selected_love_url()
        if url:
            self._copy_text(url)


    def _stop_love(self) -> None:
        self._love_stop.set()
        self.love_status.configure(text="正在停止…")


    def _start_love(self) -> None:
        query = self._love_text().strip()
        if not query:
            self.love_status.configure(text="请输入贴吧ID或用户名")
            return
        if not getattr(self, "_love_disclaimer_seen", False):
            if not messagebox.askyesno(
                "恋文增强（第三方）",
                "本功能使用恋文（第三方）的公开数据。\n"
                "恋文不是百度官方接口，与本软件无隶属关系。\n"
                "第三方数据可能不完整、滞后或不准确。\n"
                "本功能不发送 Cookie/BDUSS。\n\n继续？",
                parent=self.root,
            ):
                return
            self._love_disclaimer_seen = True
        self._love_rows = []
        self._love_seen = set()
        self._love_urls = {}
        self._love_page = 0
        self._love_has_next = True
        for item in self.love_tree.get_children():
            self.love_tree.delete(item)
        mode = self.love_mode_var.get()
        uid = query if mode == "贴吧ID" else ""
        username = query if mode == "用户名" else ""
        nickname = query if mode == "昵称" else ""
        self._love_identity = (uid, username, nickname)
        self._love_use_old = self.love_api_var.get() == "查发言（旧）"
        self._load_love_page()


    def _next_love(self) -> None:
        if self._love_running or not self._love_has_next:
            return
        self._load_love_page()


    def _load_love_page(self) -> None:
        if self._love_running:
            return
        uid, username, nickname = getattr(self, "_love_identity", ("", "", ""))
        if not uid and not username and not nickname:
            return
        self._love_running = True
        self._love_stop.clear()
        next_page = self._love_page + 1
        self.love_status.configure(text=f"正在抓取第 {next_page} 页…")

        def worker():
            try:
                fetcher = Fetcher(cookie={}, delay=0.3, verbose=False)
                data = third_party.fetch_posts_page(
                    uid,
                    username,
                    next_page,
                    use_old=bool(getattr(self, "_love_use_old", False)),
                    nickname=nickname,
                )
                items = data.get("items") or []
                hrefs = "\n".join(str(item.get("href") or "") for item in items)
                parsed = parse_links(hrefs, fetcher, should_stop=self._love_stop.is_set) if hrefs.strip() else {"rows": [], "errors": []}
                rows_by_pid = {str(row.get("pid") or ""): row for row in parsed.get("rows") or []}
                rows = []
                for item in items:
                    link = third_party.parse_post_link(str(item.get("href") or ""))
                    row = rows_by_pid.get(str(link.get("pid") or ""))
                    if row is None:
                        row = {
                            "pid": link.get("pid") or "",
                            "time": "",
                            "type": "",
                            "bar": "",
                            "title": item.get("title") or "",
                            "content": item.get("content") or "",
                            "floor": "",
                            "url": item.get("href") or "",
                            "source": "恋文（第三方）",
                        }
                    else:
                        row = dict(row)
                    row["source"] = "恋文（第三方）"
                    rows.append(row)
                self._post(("love_ready", {"page": next_page, "rows": rows, "has_next": bool(data.get("has_next")), "error": ""}, ""))
            except Exception as error:  # noqa: BLE001
                self._post(("love_ready", None, str(error)))

        threading.Thread(target=worker, daemon=True).start()


    def _render_love(self, result: Dict, error: str) -> None:
        self._love_running = False
        if result is None:
            self.love_status.configure(text=f"失败：{error}")
            return
        self._love_page = int(result.get("page") or self._love_page)
        self._love_has_next = bool(result.get("has_next"))
        added = 0
        for row in result.get("rows") or []:
            key = str(row.get("pid") or row.get("url") or "")
            if key and key in self._love_seen:
                continue
            if key:
                self._love_seen.add(key)
            self._love_rows.append(row)
            iid = str(len(self._love_rows) - 1)
            self.love_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row.get("time") or "",
                    row.get("type") or "",
                    row.get("bar") or "",
                    row.get("title") or "",
                    row.get("content") or "",
                    row.get("floor") or "",
                    row.get("url") or "",
                ),
            )
            self._love_urls[iid] = row.get("url") or ""
            added += 1
        self.love_status.configure(
            text=(
                f"第 {self._love_page} 页 / 已加载 {len(self._love_rows)} 条 / 本页新增 {added} / "
                f"{'还有更多' if self._love_has_next else '已到末页'}；数据来自恋文（第三方）"
            )
        )
        if self.love_auto_var.get() and self._love_has_next and self._love_page < 100 and not self._love_stop.is_set():
            self.root.after(120, self._next_love)
        elif self._love_page >= 100 and self._love_has_next:
            self.love_status.configure(
                text=f"第 {self._love_page} 页 / 自动补全已到 100 页上限，可手动继续；数据来自恋文（第三方）"
            )


    def _export_love(self) -> None:
        if not self._love_rows:
            self.love_status.configure(text="没有可导出的结果")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出恋文增强",
            defaultextension=".xlsx",
            initialfile="恋文增强.xlsx",
            filetypes=[("Excel 表格", "*.xlsx")],
        )
        if not path:
            return
        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = "恋文增强"
            ws.append(["日期", "类型", "贴吧", "标题", "内容", "楼层", "链接", "数据来源"])
            for row in self._love_rows:
                ws.append(
                    [
                        row.get("time") or "",
                        row.get("type") or "",
                        row.get("bar") or "",
                        row.get("title") or "",
                        row.get("content") or "",
                        row.get("floor") or "",
                        row.get("url") or "",
                        "恋文（第三方）",
                    ]
                )
            info = wb.create_sheet("说明")
            info.append(["数据来源", "恋文（第三方）+ 官方主题补全"])
            info.append(["已加载页", f"1~{self._love_page}"])
            info.append(["已加载条数", len(self._love_rows)])
            info.append(["是否还有更多", "是" if self._love_has_next else "否"])
            wb.save(path)
            self.love_status.configure(text="已导出已加载内容")
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("导出失败", str(error), parent=self.root)


    def _on_love_level_changed(self) -> None:
        enabled = bool(self.love_level_var.get())
        if enabled and not self.settings.get("love_level_enabled", False):
            if not messagebox.askyesno(
                "恋文等级补充（第三方）",
                "数据来自恋文（第三方），非百度官方。\n"
                "恋文等级可能滞后或不准确，只能查询已知贴吧；"
                "需要贴吧ID或用户名。\n"
                "恋文与本软件无隶属关系。\n\n继续？",
                parent=self.root,
            ):
                self.love_level_var.set(False)
                enabled = False
        self.settings["love_level_enabled"] = enabled
        save_settings(self.settings)
        self._profile_cache = {}
        self._lookup_cache = {}
        self._all_levels_cache = {}
        self.general_hint.configure(text="已保存")


    def _profile_hit(self, profile, extra_bars=None):
        if not self._risk_enabled():
            return "", ""
        # 先按发言判定；只有拿到完整关注列表时，关注吧才参与。
        src = profile.get("post_sources") or {}
        if src and src.get("replies_ok") is False and src.get("threads_ok") is not True:
            return "", ""
        bars = [post.get("bar") for post in profile.get("recent_posts") or [] if post.get("bar")]
        bars += [bar for bar in (extra_bars or []) if bar]
        complete_follow = bool(profile.get("follow_loaded")) and not self._hidden_follows(profile)
        if complete_follow and not profile.get("follow_error"):
            bars += [forum["name"] for forum in profile.get("followed_forums") or []]
        return classify(bars, getattr(self, "blacklist", {}))


    def _reload_profile(self) -> None:
        user = self._selected_person() if hasattr(self, "people_tree") else None
        if user and self.last_threads:
            self._load_profile(user, force=True)


    def _load_profile(
        self,
        user,
        force: bool = False,
        force_follow: bool = False,
        topic_max_pages: Optional[int] = None,
        use_page_cache: Optional[bool] = None,
    ) -> None:
        key = user["uid"] or f"name:{user['name']}"
        cached = None if (force or force_follow) else getattr(self, "_profile_cache", {}).get(key)
        if cached and (cached.get("follow_loaded") or not force_follow):
            stored_at = float(cached.get("_ui_cached_at") or 0)
            if stored_at:
                cached["_ui_cache_age_seconds"] = max(0, int(time.time() - stored_at))
            self._render_profile(user, cached)
            return
        self.profile_status.configure(text=f"正在查询 {display_text(user['name'])} …")
        self._set_profile_cache_note("")
        for tree in (self.profile_forum_tree, self.profile_post_tree):
            self._clear_loaded_tree(tree)
        count = self._post_count()
        start_date, end_date = self._date_params()
        bar_name = self._user_bar(user)
        prefer = (
            "start"
            if self.post_date_mode_var.get() == "指定日期" and "最早" in self.post_prefer_var.get()
            else "end"
        )
        topic_limit = int(topic_max_pages or getattr(self, "_profile_topic_limit", 50) or 50)
        self._profile_topic_limit = topic_limit
        cached_posts = None
        if not force and not force_follow:
            cached_posts = cached_user_posts(user["uid"], count, start_date, end_date, prefer)

        def worker():
            profile: Dict[str, Any]
            try:
                fetcher = Fetcher(cookie=self._request_cookie(), delay=0, verbose=False)
                uid = str(user.get("uid") or "")
                username = str(user.get("username") or "")
                portrait = str(user.get("portrait") or "")
                if not uid:
                    info = {}
                    if username:
                        info = resolve_user(fetcher, username, "用户名")
                    elif user.get("name"):
                        info = resolve_user(fetcher, str(user["name"]), "昵称")
                    if not info.get("uid") and not portrait and user.get("name") and username:
                        info = resolve_user(fetcher, str(user["name"]), "昵称")
                    if info.get("uid"):
                        uid = str(info.get("uid") or "")
                        username = str(info.get("username") or username)
                        portrait = str(info.get("portrait") or portrait)
                        user["uid"] = uid
                        user["username"] = username
                        user["portrait"] = portrait
                    elif not portrait:
                        profile = {"ok": False, "error": "用户名/昵称无法唯一定位"}
                        self._post(("profile_ready", key, user, profile))
                        return
                local_cached = cached_posts
                if local_cached is None and uid and not force:
                    local_cached = cached_user_posts(uid, count, start_date, end_date, prefer)
                profile = fetch_user_profile(
                    fetcher,
                    uid,
                    username,
                    portrait,
                    bar_name,
                    count,
                    start_date,
                    end_date,
                    prefer,
                    load_follow=force_follow or self.settings.get("follow_load_mode", "auto") == "auto",
                    topic_max_pages=topic_limit,
                    use_cache=(not force if use_page_cache is None else bool(use_page_cache)),
                    cached_posts=local_cached,
                )
                if profile.get("ok"):
                    self._attach_love_levels(profile)
                    official = list(profile.get("recent_posts") or [])
                    current = merge_current_threads(official, getattr(self, "last_threads", []), profile)
                    posts = official + current["posts"]
                    posts.sort(key=lambda item: int(item.get("ts") or 0), reverse=(prefer != "start"))
                    profile["recent_posts"] = posts[:count]
                    profile["_supplement"] = {
                        "official": len(official),
                        "current": len(current["posts"]),
                        "retrace": 0,
                        "failed": 0,
                        "total": len(posts),
                        "shown": len(profile["recent_posts"]),
                    }
            except Exception as error:  # noqa: BLE001
                profile = {"ok": False, "error": str(error)}
            self._post(("profile_ready", key, user, profile))

        threading.Thread(target=worker, daemon=True).start()


    def _reload_profile_follow(self) -> None:
        user = getattr(self, "_profile_user", None)
        if user:
            self._load_profile(user, force=True, force_follow=True)


    def _continue_profile_topics(self) -> None:
        user = getattr(self, "_profile_user", None)
        if not user:
            return
        choice = self._ask_choice(
            "继续抓主题",
            "主题流已达到本次上限，继续会追加请求；不会重复抓已缓存的页。",
            [
                ("再抓 50 页", "more"),
                ("一直抓到开始日期", "all"),
                ("停止", None),
            ],
            default=0,
        )
        if choice is None:
            self.profile_topic_btn.pack_forget()
            return
        limit = 100000 if choice == "all" else int(getattr(self, "_profile_topic_limit", 50)) + 50
        self._load_profile(
            user, force=True, topic_max_pages=limit, use_page_cache=True
        )


    def _open_profile_forum(self) -> None:
        selection = self.profile_forum_tree.selection()
        if not selection:
            return
        name = self._profile_forum_names.get(selection[0])
        if name:
            webbrowser.open("https://tieba.baidu.com/f?kw=" + quote(name))


    def _open_profile_post(self) -> None:
        selection = self.profile_post_tree.selection()
        if not selection:
            return
        url = self._profile_post_urls.get(selection[0])
        if url:
            webbrowser.open(url)


    def _export_profile_report(self) -> None:
        user = getattr(self, "_profile_user", None)
        profile = getattr(self, "_profile_data", None)
        if not user or not profile:
            messagebox.showinfo("还没有资料", "先点开一个参与者。", parent=self.root)
            return
        mark = None
        if self._risk_enabled():
            level, bar = self._profile_hit(profile, [self._user_bar(user)])
            if level:
                mark = {"level": {"ban": "红", "warn": "黄", "safe": "绿"}.get(level, level), "bar": bar}
        self._choose_report_path(user, profile, mark)


    def _export_profile_posts(self) -> None:
        user = getattr(self, "_profile_user", None)
        profile = getattr(self, "_profile_data", None)
        if not user or not profile:
            messagebox.showinfo("还没有资料", "先点开一个参与者。", parent=self.root)
            return
        self._export_posts_for(user, profile, *self._date_params())


    def _render_profile(self, user, profile) -> None:
        self._set_profile_cache_note("")
        forum_tree = self.profile_forum_tree
        post_tree = self.profile_post_tree
        for tree in (forum_tree, post_tree):
            self._clear_loaded_tree(tree)
        self._profile_forum_names = {}
        self._profile_post_urls = {}

        if not profile.get("ok"):
            self.profile_status.configure(
                text="查询失败：" + friendly_error(RuntimeError(str(profile.get("error") or "未知错误")))
            )
            return

        level = str(profile.get("bar_level") or "").strip()
        if level in ("0", "None"):
            level = ""
        if not level:
            level = str(user.get("level") or "").strip()
            if level in ("0", "None"):
                level = ""

        if level:
            self._apply_level_to_threads(user, level)
        profile_tieba = str(profile.get("tieba_uid") or "")
        had_tieba = bool(user.get("tieba_uid"))
        if profile_tieba:
            user["tieba_uid"] = profile_tieba
            iid = user.get("_iid")
            if iid is not None:
                try:
                    values = list(self.people_tree.item(iid, "values"))
                    values[3] = profile_tieba
                    self.people_tree.item(iid, values=values)
                except tk.TclError:
                    pass
            if not had_tieba and getattr(self, "last_output", None):
                self._append_log("身份已更新，需要重新导出 Excel。", "muted")
                self.profile_status.configure(text="身份已更新，需要重新导出")
        if level and not user.get("level"):
            user["level"] = level
            iid = user.get("_iid")
            if iid is not None:
                try:
                    values = list(self.people_tree.item(iid, "values"))
                    values[5] = f"Lv.{level}"
                    self.people_tree.item(iid, values=values)
                except tk.TclError:
                    pass

        if profile.get("user_id") and not user.get("uid"):
            user["uid"] = str(profile.get("user_id") or "")
        if profile.get("username") and not user.get("username"):
            user["username"] = str(profile.get("username") or "")
        if profile.get("portrait") and not user.get("portrait"):
            user["portrait"] = str(profile.get("portrait") or "")
        self._profile_user = user
        self._profile_data = profile
        self._set_person_mark_row(user)
        posts = profile.get("recent_posts") or []
        combined = self._merge_forum_lists(profile, self._user_bar(user), level or "")
        self.profile_report_btn.pack(side="left", padx=(0, 6))
        self.profile_posts_btn.pack(side="left", padx=(0, 6))
        sources = profile.get("post_sources") or {}
        if sources.get("topic_truncated"):
            topic_text = f"继续抓主题（已 {sources.get('topic_pages') or 50} 页）"
            self.profile_topic_btn.configure(text=topic_text, width=max(12, len(topic_text) + 2))
            self.profile_topic_btn.pack(side="right", padx=(0, 4))
        else:
            self.profile_topic_btn.pack_forget()
        if profile.get("follow_loaded") is False:
            self.profile_follow_btn.pack(side="left", padx=(0, 6))
        else:
            self.profile_follow_btn.pack_forget()
        if self._follow_incomplete(profile):
            self.profile_probe_btn.pack(side="left", padx=(0, 6))
            self.profile_probe_btn.configure(state="normal", text="探测候选关注")
        else:
            self.profile_probe_btn.pack_forget()

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
            self._profile_forum_names[iid] = forum["name"]
        self._request_love_levels(profile, combined, forum_tree, self._profile_forum_names, "profile")

        has_supplement = any(str(post.get("source") or "") not in ("", "官方") for post in posts)
        post_tree["displaycolumns"] = (
            ("time", "type", "bar", "title", "content", "source")
            if has_supplement
            else ("time", "type", "bar", "title", "content")
        )
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
            self._profile_post_urls[iid] = post.get("url") or ""
        forum_note = self._forum_note(profile, self._user_bar(user), level or "")
        if self.mode_var.get() != "guest" and profile.get("follow_loaded") is False:
            forum_note += "（未加载公开关注）"
        self.profile_forum_note.configure(text=forum_note)

        # 本地标记：优先沿用批量结果，避免详情重算把 ⚠ 或等级改掉。
        if not self._risk_enabled():
            hit_level, hit_bar = "", ""
            hidden_follows = False
        elif user.get("mark_level"):
            hit_level = str(user.get("mark_level") or "")
            hit_bar = str(user.get("mark_bar") or "")
            hidden_follows = bool(user.get("mark_hidden")) and self.mode_var.get() != "guest"
        elif self.mode_var.get() == "guest":
            hit_level, hit_bar = classify([self._user_bar(user)], getattr(self, "blacklist", {}))
            hidden_follows = False
        else:
            bars = [post.get("bar") for post in posts if post.get("bar")]
            bars += [forum["name"] for forum in combined]
            hit_level, hit_bar = classify(bars, getattr(self, "blacklist", {}))
            hidden_follows = self._hidden_follows(profile)
            if hidden_follows and hit_level != "ban":
                if hit_level != "warn":
                    hit_bar = "关注列表隐藏"
                hit_level = "warn"
        label = LEVEL_LABEL.get(hit_level, "")
        for traffic_key, (traffic_label, traffic_color) in getattr(self, "traffic_labels", {}).items():
            traffic_label.configure(fg=traffic_color if traffic_key == hit_level else "#d1d5db")
        risk_reason = (
            "关注列表隐藏"
            if self.mode_var.get() != "guest" or hidden_follows
            else "关注列表未加载"
        )
        risk = f" · {risk_reason}，未命中警告时标黄" if hidden_follows else ""
        try:
            self.traffic_text.configure(
                text=(
                    (f"{label}：{hit_bar}" if hit_bar and hit_bar != "关注列表隐藏" else label)
                    if hit_level
                    else "未命中任何名单"
                )
                + risk
            )
        except tk.TclError:
            pass
        iid = user.get("_iid")
        if iid is not None:
            try:
                values = list(self.people_tree.item(iid, "values"))
                if user.get("mark_level"):
                    values[0] = self._person_mark_cell(user)
                elif hit_level:
                    values[0] = f"{marker(hit_level)} {label}" + (" ⚠" if hidden_follows else "")
                else:
                    values[0] = "⚪"
                self.people_tree.item(
                    iid,
                    values=values,
                    tags=(hit_level,) if hit_level and self.settings.get("color_people", True) else (),
                )
            except tk.TclError:
                pass

        status = (
            f"{display_text(user['name'])} | {user['username'] or '-'} | 贴吧ID {self._tieba_uid_cell(user)} | "
            f"用户ID {user['uid'] or '-'} | Lv.{level or '-'} | 发言 {len(posts)} | 关注 {len(combined)}"
        )
        if profile.get("fans") is not None:
            status += f" | 粉丝 {profile['fans']}"
        if profile.get("concern") is not None:
            status += f" | 关注数 {profile['concern']}"
        if profile.get("post_num"):
            status += f" | 发帖 {profile['post_num']}"
        if hit_level:
            status += f" · 命中{label}：{hit_bar}"
        if hidden_follows:
            status += f" · ⚠ {risk_reason}，未命中警告时标黄"
        note = self._post_source_note(profile)
        if note:
            status += " · " + note
        self.profile_status.configure(text=status)
        self._set_profile_cache_note(self._cache_age_note(profile))

