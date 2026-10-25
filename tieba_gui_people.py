"""参与者/报表/区间对话 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import re
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

from tieba_gui_utils import display_text, optional_int
from tieba_reply_stats.filters import filter_users
from tieba_reply_stats.profile import cached_user_posts
from tieba_reply_stats.storage import clear as clear_stored_result
from tieba_reply_stats.storage import save_threads
from tieba_reply_stats.version import __version__ as VERSION


class PeopleReportMixin:
    """参与者/报表/区间对话方法，从 App 拆出。"""

    last_threads: Any
    last_output: Any
    last_outputs: Any
    _people_page: Any
    people_users: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _aggregate_users(self, threads=None):
        buckets: Dict[str, Dict[str, Any]] = {}
        for thread in (self.last_threads if threads is None else threads):
            for item in thread.user_stats():
                key = (
                    f"uid:{item['uid']}"
                    if item.get("uid")
                    else (
                        f"portrait:{str(item.get('portrait') or '').split('?')[0]}"
                        if item.get("portrait")
                        else (f"name:{item['username']}" if item.get("username") else f"anon:{item['name']}")
                    )
                )
                bucket = buckets.setdefault(
                    key,
                    {
                        "name": item["name"],
                        "username": item["username"],
                        "uid": item["uid"],
                        "tieba_uid": item.get("tieba_uid") or "",
                        "portrait": item["portrait"],
                        "level": item["level"],
                        "badge": item["badge"],
                        "floor": 0,
                        "comment": 0,
                        "total": 0,
                        "aliases": set(),
                    },
                )
                bucket["floor"] += item["floor_count"]
                bucket["comment"] += item["comment_count"]
                bucket["total"] += item["total"]
                if item.get("name") and item["name"] != bucket["name"]:
                    bucket["aliases"].add(bucket["name"])
                    bucket["name"] = item["name"]
                bucket["aliases"].update(item.get("aliases") or [])
                if not bucket["username"] and item["username"]:
                    bucket["username"] = item["username"]
                if not bucket["portrait"] and item["portrait"]:
                    bucket["portrait"] = item["portrait"]
                if not bucket["tieba_uid"] and item.get("tieba_uid"):
                    bucket["tieba_uid"] = item["tieba_uid"]
                if not bucket["level"] and item["level"]:
                    bucket["level"] = item["level"]
                if not bucket["badge"] and item["badge"]:
                    bucket["badge"] = item["badge"]
        users = list(buckets.values())
        for user in users:
            user["aliases"] = sorted(a for a in user.get("aliases", ()) if a and a != user["name"])
        users.sort(key=lambda item: (-item["total"], -item["floor"], item["name"]))
        return users


    def _refresh_people(self) -> None:
        values = ["全部帖子"]
        for index, thread in enumerate(self.last_threads, start=1):
            values.append(f"{index}. {display_text(thread.meta.title or thread.meta.tid)}")
        if hasattr(self, "people_range_box"):
            self.people_range_box.configure(values=values)
            if self.people_range_var.get() not in values:
                self.people_range_var.set("全部帖子")
        previous = {
            str(user.get("uid") or user.get("username") or user.get("name") or ""): user
            for user in getattr(self, "people_users", [])
        }
        users = self._aggregate_users(self._people_threads())
        for user in users:
            key = str(user.get("uid") or user.get("username") or user.get("name") or "")
            old = previous.get(key)
            if not old:
                continue
            for field in ("mark_level", "hit", "mark_bar", "mark_hidden", "mark_at", "mark_error"):
                if field in old:
                    user[field] = old[field]
            if not user.get("level") and old.get("level"):
                user["level"] = old["level"]
        self.people_users = users
        self._people_index = {id(user): index for index, user in enumerate(users)}
        for index, user in enumerate(users):
            user["_iid"] = str(index)
        filtered = filter_users(
            users,
            keyword=self.people_keyword_var.get(),
            field=self.people_field_var.get(),
            level=self.people_level_var.get(),
            mark=self.people_mark_var.get() if self._risk_enabled() else "全部",
            min_level=optional_int(self.people_min_var.get()),
            max_level=optional_int(self.people_max_var.get()),
        )
        for column, selected in self._people_col_filters.items():
            if selected:
                filtered = [
                    user for user in filtered
                    if self._people_column_value(user, column) in selected
                ]
        sort_column, sort_reverse = getattr(self, "_people_sort", ("", False))
        if sort_column:
            def sort_key(user):
                if sort_column == "mark":
                    order = {"警告": 3, "可疑": 2, "安全": 1, "": 0}
                    value = self._people_column_value(user, sort_column)
                    return order.get(value, 0)
                if sort_column == "level":
                    return int(user.get("level") or 0)
                return int(user.get(sort_column) or 0)
            filtered.sort(key=sort_key, reverse=bool(sort_reverse))
        page_size = max(1, int(self.settings.get("page_size", 1000) or 1000))
        pages = max(1, (len(filtered) + page_size - 1) // page_size)
        self._people_page = min(max(0, getattr(self, "_people_page", 0)), pages - 1)
        start = self._people_page * page_size
        for item in self.people_tree.get_children():
            self.people_tree.delete(item)
        for user in filtered[start : start + page_size]:
            index = self._people_index[id(user)]
            self.people_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    self._person_mark_cell(user),
                    self._display_name(user),
                    user["username"] or "-",
                    self._tieba_uid_cell(user),
                    self._person_uid_text(user),
                    f"Lv.{user['level']}" if user["level"] else "-",
                    user["floor"],
                    user["comment"],
                    user["total"],
                ),
            )
        if hasattr(self, "people_page_label"):
            self.people_page_label.configure(
                text=f"第 {self._people_page + 1}/{pages} 页 · 筛选后 {len(filtered)} / 共 {len(users)} 人"
            )
        with_level = sum(1 for user in filtered if user.get("level"))
        mode_note = ""
        if self._risk_enabled():
            mode_note = " · 红绿灯：仅发言" if self.mode_var.get() == "guest" else " · 红绿灯：发言+关注"
        warning_count = sum(len(thread.warnings) for thread in self.last_threads)
        warning_note = f" · ⚠ {warning_count} 条数据警告" if warning_count else ""
        stale_note = " · 标记规则已变更，可点重新标记（本地）" if getattr(self, "_marks_stale", False) else ""
        self.people_hint.configure(
            text=f"v{VERSION} · 当前 {len(filtered)} / 共 {len(users)} 人 · 有等级 {with_level}{mode_note}{warning_note}{stale_note}"
        )
        if hasattr(self, "retry_incomplete_btn"):
            incomplete = any(not getattr(thread, "complete", True) for thread in self.last_threads)
            if incomplete:
                self.retry_incomplete_btn.state(["!disabled"])
            else:
                self.retry_incomplete_btn.state(["disabled"])
        if hasattr(self, "supplement_btn"):
            missing_identity = any(
                (not user.get("uid") and (user.get("username") or user.get("portrait")))
                or (user.get("uid") and not user.get("tieba_uid"))
                for user in self.people_users
            )
            self.supplement_btn.configure(state="normal" if missing_identity else "disabled")
        self.profile_status.configure(text="选择左边一个人查看详情")
        self._set_profile_cache_note("")
        for tree in (self.profile_forum_tree, self.profile_post_tree):
            for item in tree.get_children():
                tree.delete(item)


    def _open_manage_results(self) -> None:
        if not self.last_threads:
            messagebox.showinfo("还没有数据", "先抓取帖子，再管理帖子结果。", parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.title("管理帖子结果")
        win.geometry("620x420")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg="#eef1f5")
        tk.Label(
            win,
            text="勾选要删除的帖子结果；只删结果，不删原帖、Excel 或本地标记。",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))
        body = tk.Frame(win, bg="#ffffff")
        body.pack(fill="both", expand=True, padx=12)
        canvas = tk.Canvas(body, bg="#ffffff", highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg="#ffffff")
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(1, width=event.width))
        variables = []
        for index, thread in enumerate(self.last_threads, start=1):
            var = tk.BooleanVar(value=False)
            variables.append(var)
            title = display_text(thread.meta.title or thread.meta.tid)
            count = len(thread.user_stats())
            ttk.Checkbutton(
                inner,
                text=f"{index}. {title}    {count} 人",
                variable=var,
            ).pack(anchor="w", padx=6, pady=3)
        footer = tk.Frame(win, bg="#eef1f5")
        footer.pack(fill="x", padx=12, pady=10)
        cancel_btn = ttk.Button(footer, text="取消", command=win.destroy, width=8)
        cancel_btn.pack(side="right")
        def select_all(value: bool) -> None:
            for var in variables:
                var.set(value)

        ttk.Button(
            footer,
            text="全选",
            command=lambda: select_all(True),
            width=8,
        ).pack(side="left")
        ttk.Button(
            footer,
            text="取消全选",
            command=lambda: select_all(False),
            width=10,
        ).pack(side="left", padx=(6, 0))

        def delete_selected() -> None:
            selected = [index for index, var in enumerate(variables) if var.get()]
            if not selected:
                messagebox.showinfo("没有选择", "先勾选要删除的帖子结果。", parent=win)
                return
            if not messagebox.askyesno(
                "删除帖子结果",
                f"删除 {len(selected)} 个帖子结果？删除后不可撤销，不影响原帖、Excel 或本地标记。",
                parent=win,
                default=messagebox.NO,
            ):
                return
            remaining = [thread for index, thread in enumerate(self.last_threads) if index not in selected]
            try:
                if self.settings.get("save_result", True):
                    if remaining:
                        save_threads(
                            remaining,
                            VERSION,
                            encrypted=bool(self.settings.get("encrypt_result", False)),
                        )
                    else:
                        if not clear_stored_result():
                            raise OSError("无法删除当前结果文件")
            except Exception as error:  # noqa: BLE001
                messagebox.showerror("保存失败", f"删除未执行：{error}", parent=win)
                return
            active = self.grid_thread_var.get()
            active_tid = None
            if not active.startswith("全部"):
                for old_thread in self.last_threads:
                    if active.endswith(display_text(old_thread.meta.title or old_thread.meta.tid)):
                        active_tid = old_thread.meta.tid
                        break
            self.last_threads = remaining
            if not remaining:
                self.last_output = None
                self.open_btn.configure(state="disabled")
            elif active.startswith("全部"):
                self._update_grid_selector()
            elif active_tid in {thread.meta.tid for thread in remaining}:
                self._update_grid_selector()
                for index, thread in enumerate(remaining, start=1):
                    if thread.meta.tid == active_tid:
                        self.grid_thread_var.set(
                            f"{index}. {display_text(thread.meta.title or thread.meta.tid)}"
                        )
                        break
            else:
                self.grid_thread_var.set("")
                self._update_grid_selector()
            self._refresh_people()
            self._refresh_grid()
            self._append_log(f"已删除 {len(selected)} 个帖子结果。", "muted")
            win.destroy()

        ttk.Button(footer, text="删除选中", command=delete_selected, width=10).pack(
            side="right", padx=(0, 6)
        )
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.update_idletasks()
        width = max(620, win.winfo_width())
        height = max(420, win.winfo_height())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        cancel_btn.focus_set()


    def _aggregate_threads(self, threads):
        buckets: Dict[str, Dict[str, Any]] = {}
        for thread in threads:
            for item in thread.user_stats():
                key = (
                    f"uid:{item['uid']}"
                    if item.get("uid")
                    else (
                        f"portrait:{str(item.get('portrait') or '').split('?')[0]}"
                        if item.get("portrait")
                        else (f"name:{item['username']}" if item.get("username") else f"anon:{item['name']}")
                    )
                )
                bucket = buckets.setdefault(
                    key,
                    {
                        "name": item["name"],
                        "username": item["username"],
                        "uid": item["uid"],
                        "tieba_uid": item.get("tieba_uid") or "",
                        "portrait": item["portrait"],
                        "level": item["level"],
                        "badge": item["badge"],
                        "floor": 0,
                        "comment": 0,
                        "total": 0,
                        "threads": 0,
                        "aliases": set(),
                    },
                )
                bucket["floor"] += item["floor_count"]
                bucket["comment"] += item["comment_count"]
                bucket["total"] += item["total"]
                bucket["threads"] += 1
                if item.get("name") and item["name"] != bucket["name"]:
                    bucket["aliases"].add(bucket["name"])
                    bucket["name"] = item["name"]
                bucket["aliases"].update(item.get("aliases") or [])
                if not bucket["username"] and item["username"]:
                    bucket["username"] = item["username"]
                if not bucket["portrait"] and item["portrait"]:
                    bucket["portrait"] = item["portrait"]
                if not bucket["tieba_uid"] and item.get("tieba_uid"):
                    bucket["tieba_uid"] = item["tieba_uid"]
                if not bucket["level"] and item["level"]:
                    bucket["level"] = item["level"]
                if not bucket["badge"] and item["badge"]:
                    bucket["badge"] = item["badge"]
        users = list(buckets.values())
        for user in users:
            user["aliases"] = sorted(a for a in user.get("aliases", ()) if a and a != user["name"])
        users.sort(key=lambda item: (-item["total"], -item["floor"], item["name"]))
        return users


    def _filter_text_dialog(
        self, title: str, values: List[str], selected, anchor: Optional[tuple] = None
    ) -> Optional[set]:
        win = tk.Toplevel(self.root)
        win.title("筛选：" + title)
        win.configure(bg="#ffffff")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        frame = tk.Frame(win, bg="#ffffff", padx=12, pady=10)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="筛选：" + title, bg="#ffffff", fg="#1f2937",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        search = tk.StringVar()
        tk.Entry(frame, textvariable=search, width=38).pack(fill="x", pady=(6, 6))
        tk.Label(
            frame,
            text="单击切换选中，可多选",
            bg="#ffffff",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(0, 3))
        listbox = tk.Listbox(frame, selectmode="multiple", width=42, height=14, exportselection=False)
        listbox.pack(fill="both", expand=True)
        for value in values:
            listbox.insert("end", value)
        chosen = set(str(v) for v in selected) if selected else set(values)
        for index, value in enumerate(values):
            if value in chosen:
                listbox.selection_set(index)

        def take_selection() -> set:
            return {str(listbox.get(i)) for i in listbox.curselection()}

        select_all_btn: Optional[ttk.Button] = None

        def update_select_all_label() -> None:
            if select_all_btn is None:
                return
            size = listbox.size()
            selected = len(listbox.curselection())
            select_all_btn.configure(text="取消全选" if size and selected >= size else "全选")

        def toggle_all() -> None:
            size = listbox.size()
            if not size:
                return
            if len(listbox.curselection()) >= size:
                listbox.selection_clear(0, "end")
            else:
                listbox.selection_set(0, "end")
            update_select_all_label()

        def refresh(*_args) -> None:
            nonlocal chosen
            chosen = take_selection()
            query = search.get().strip().lower()
            listbox.delete(0, "end")
            for value in values:
                if not query or query in value.lower():
                    listbox.insert("end", value)
            for index, value in enumerate(listbox.get(0, "end")):
                if value in chosen:
                    listbox.selection_set(index)
            update_select_all_label()

        search.trace_add("write", refresh)
        listbox.bind("<<ListboxSelect>>", lambda _event: update_select_all_label())
        result: Dict[str, Any] = {"value": None}
        buttons = tk.Frame(frame, bg="#ffffff")
        buttons.pack(fill="x", pady=(8, 0))

        def apply() -> None:
            result["value"] = take_selection()
            win.destroy()

        def clear_filter() -> None:
            result["value"] = set()
            win.destroy()

        select_all_btn = ttk.Button(buttons, text="全选", command=toggle_all, width=8)
        select_all_btn.pack(side="left")
        ttk.Button(buttons, text="清除筛选", command=clear_filter, width=10).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="取消", command=lambda: win.destroy(), width=8).pack(side="right")
        ttk.Button(buttons, text="应用", command=apply, width=8).pack(side="right", padx=(0, 6))
        update_select_all_label()
        self._place_filter_window(win, anchor, 380)
        self.root.wait_window(win)
        return result["value"]


    def _filter_date_dialog(
        self, title: str, selected, anchor: Optional[tuple] = None
    ) -> Optional[tuple]:
        win = tk.Toplevel(self.root)
        win.title("筛选：" + title)
        win.configure(bg="#ffffff")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        frame = tk.Frame(win, bg="#ffffff", padx=14, pady=12)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="日期范围（留空表示不限）", bg="#ffffff", fg="#1f2937",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        start_var = tk.StringVar(value=(selected or ("", ""))[0])
        end_var = tk.StringVar(value=(selected or ("", ""))[1])
        row = tk.Frame(frame, bg="#ffffff")
        row.pack(fill="x", pady=(8, 8))
        tk.Label(row, text="开始", bg="#ffffff", fg="#475569").pack(side="left")
        tk.Entry(row, textvariable=start_var, width=12).pack(side="left", padx=(4, 10))
        tk.Label(row, text="结束", bg="#ffffff", fg="#475569").pack(side="left")
        tk.Entry(row, textvariable=end_var, width=12).pack(side="left", padx=(4, 0))
        preset = tk.Frame(frame, bg="#ffffff")
        preset.pack(fill="x", pady=(0, 8))
        for label, days in (("全部", 0), ("近7天", 7), ("近30天", 30), ("近90天", 90)):
            def apply_preset(value=days) -> None:
                if not value:
                    start_var.set("")
                    end_var.set("")
                    return
                today = datetime.now()
                start_var.set((today - timedelta(days=value)).strftime("%Y-%m-%d"))
                end_var.set(today.strftime("%Y-%m-%d"))
            ttk.Button(preset, text=label, command=apply_preset, width=7).pack(side="left", padx=(0, 4))
        result: Dict[str, Any] = {"value": None}
        buttons = tk.Frame(frame, bg="#ffffff")
        buttons.pack(fill="x")

        def apply() -> None:
            for value in (start_var.get().strip(), end_var.get().strip()):
                if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    messagebox.showerror("日期格式", "日期请用 YYYY-MM-DD。", parent=win)
                    return
            result["value"] = (start_var.get().strip(), end_var.get().strip())
            win.destroy()

        def clear() -> None:
            result["value"] = ("", "")
            win.destroy()

        ttk.Button(buttons, text="取消", command=lambda: win.destroy(), width=8).pack(side="right")
        ttk.Button(buttons, text="应用", command=apply, width=8).pack(side="right", padx=(0, 6))
        ttk.Button(buttons, text="清空", command=clear, width=8).pack(side="left")
        self._place_filter_window(win, anchor, 430)
        self.root.wait_window(win)
        return result["value"]


    def _remark_local_marks(self) -> None:
        if getattr(self, "_batch_running", False):
            return
        if not self._risk_enabled():
            return
        if not self._has_mark_rules():
            self.people_hint.configure(text="没有本地标记规则，请先在设置→本地标记中填写")
            self._focus_local_marks()
            return
        users = self._visible_people()
        if not users:
            self.people_hint.configure(text="当前筛选没有用户")
            return
        count = self._post_count()
        start_date, end_date = self._date_params()
        prefer = (
            "start"
            if self.post_date_mode_var.get() == "指定日期" and "最早" in self.post_prefer_var.get()
            else "end"
        )
        marked = 0
        missing = 0
        for user in users:
            uid = user.get("uid") or ""
            posts = cached_user_posts(uid, count, start_date, end_date, prefer) if uid else None
            if posts is None:
                missing += 1
                continue
            profile = {
                "ok": True,
                "recent_posts": posts,
                "bar_level": str(user.get("level") or ""),
                "follow_loaded": False,
                "followed_forums": [],
                "hidden_forums": [],
                "post_sources": {"cached": True},
            }
            self._apply_batch_mark(user, profile)
            marked += 1
        self._marks_stale = missing > 0
        self._refresh_people()
        note = f"重新标记完成 {marked}/{len(users)} 人"
        if missing:
            note += f" · 缓存不足 {missing} 人（未联网）"
        self.people_hint.configure(text=note)


    def _post_range_dialog(self, user, start: str, end: str, cache_start: str, cache_end: str):
        win = tk.Toplevel(self.root)
        win.title("导出发言")
        win.configure(bg="#ffffff")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        frame = tk.Frame(win, bg="#ffffff", padx=18, pady=14)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="导出发言",
            bg="#ffffff",
            fg="#1f2937",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            frame,
            text=f"用户：{user.get('name') or user.get('username') or user.get('uid') or ''}",
            bg="#ffffff",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(4, 10))
        mode = tk.StringVar(value="current")
        tk.Radiobutton(
            frame,
            text=f"当前查询范围：{start or '不限'} ~ {end or '不限'}",
            value="current",
            variable=mode,
            bg="#ffffff",
            anchor="w",
        ).pack(fill="x", anchor="w")
        tk.Radiobutton(
            frame,
            text=f"已缓存回复范围：{cache_start or '无'} ~ {cache_end or '无'}（连续）",
            value="cache",
            variable=mode,
            bg="#ffffff",
            anchor="w",
        ).pack(fill="x", anchor="w")
        tk.Radiobutton(
            frame, text="自定义", value="custom", variable=mode, bg="#ffffff", anchor="w"
        ).pack(fill="x", anchor="w")
        custom = tk.Frame(frame, bg="#ffffff")
        custom.pack(fill="x", padx=(24, 0), pady=(2, 8))
        tk.Label(custom, text="开始", bg="#ffffff", fg="#475569").pack(side="left")
        start_var = tk.StringVar(value=cache_start or start)
        tk.Entry(custom, textvariable=start_var, width=12).pack(side="left", padx=(4, 10))
        tk.Label(custom, text="结束", bg="#ffffff", fg="#475569").pack(side="left")
        end_var = tk.StringVar(value=cache_end or end)
        tk.Entry(custom, textvariable=end_var, width=12).pack(side="left", padx=(4, 0))
        tk.Label(
            frame,
            text="只导出缓存已有发言，不自动联网补抓；内容为接口片段，最多 120 字。",
            bg="#ffffff",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
            wraplength=440,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))
        result: Dict[str, Any] = {"value": None}
        buttons = tk.Frame(frame, bg="#ffffff")
        buttons.pack(fill="x")

        def finish(value) -> None:
            result["value"] = value
            win.destroy()

        ttk.Button(buttons, text="取消", command=lambda: finish(None), width=8).pack(side="right")
        ttk.Button(buttons, text="导出", command=lambda: finish(mode.get()), width=8).pack(
            side="right", padx=(0, 8)
        )
        self._center_toplevel(win)
        self.root.wait_window(win)
        if not result["value"]:
            return None
        if result["value"] == "current":
            return start, end
        if result["value"] == "cache":
            if not cache_start and not cache_end:
                messagebox.showinfo("没有缓存", "当前用户还没有可导出的发言缓存。", parent=self.root)
                return None
            return cache_start, cache_end
        chosen_start = start_var.get().strip()
        chosen_end = end_var.get().strip()
        for value in (chosen_start, chosen_end):
            if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                messagebox.showerror("日期格式", "日期请用 YYYY-MM-DD。", parent=self.root)
                return None
        return chosen_start, chosen_end

    def _on_people_paned_configure(self, event=None) -> None:
        if getattr(self, "_people_sash_set", False):
            return
        if event is not None and event.width < 500:
            return
        self._people_sash_set = True
        self.root.after_idle(self._set_people_sash)

