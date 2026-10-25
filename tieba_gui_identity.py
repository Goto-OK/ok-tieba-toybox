"""身份补全与批量标记 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict

from tieba_reply_stats.collect import (
    CollectCancelled,
    CollectOptions,
    enrich_identities,
    enrich_tieba_uids,
    enrich_user_levels,
)
from tieba_reply_stats.export import export_workbook
from tieba_reply_stats.fetch import (
    Fetcher,
    configure_gate,
    parse_cookie_input,
    resume_requests,
    set_stop_checker,
)
from tieba_reply_stats.pbapi import fill_thread_levels
from tieba_reply_stats.profile import cached_user_posts, fetch_user_profile, resolve_user
from tieba_reply_stats.settings import save_settings


class BatchIdentityMixin:
    """身份补全与批量标记方法，从 App 拆出。"""

    _active_choice_window: Any
    _batch_pending: Any
    _tieba_uid_failed: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _supplement_identity_manual(self) -> None:
        if getattr(self, "_supplement_running", False) or not getattr(self, "last_threads", None):
            return
        users = getattr(self, "people_users", [])
        missing_uid = sum(
            1 for user in users if not user.get("uid") and (user.get("username") or user.get("portrait"))
        )
        missing_tieba = sum(1 for user in users if user.get("uid") and not user.get("tieba_uid"))
        if not missing_uid and not missing_tieba:
            messagebox.showinfo("无需补全", "当前没有可补充的身份。", parent=self.root)
            return
        strategy, remember = self._ask_identity_strategy(
            missing_uid, missing_tieba, allow_detail=False
        )
        if remember:
            self.identity_strategy_var.set(
                {
                    "full": "补全用户ID + 贴吧ID",
                    "skip": "跳过补全",
                    "user_id": "只补用户ID",
                    "detail": "详情再补",
                }.get(strategy, "每次询问")
            )
            self._save_identity_strategy()
        if strategy in ("skip", "detail"):
            return
        resume_requests()
        configure_gate(float(self.delay_var.get() or 0.8))
        self._set_supplement_running(True)
        self._last_identity_strategy = strategy
        self._tieba_uid_failed = set()
        self._supplement_stop.clear()
        set_stop_checker(self._supplement_stop.is_set)
        self.supplement_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.people_hint.configure(text="正在补全身份…")

        def worker():
            try:
                began = time.perf_counter()
                stage_at = began
                timings: Dict[str, float] = {}
                fetcher = Fetcher(cookie=self._request_cookie(), delay=0, verbose=False)
                options = CollectOptions(
                    verbose=True,
                    log=self._log_from_thread,
                    should_stop=self._supplement_stop.is_set,
                )
                for thread in self.last_threads:
                    enrich_identities(thread, fetcher, options, self._log_from_thread)
                self._user_id_failed = {
                    self._identity_fail_key(item)
                    for thread in self.last_threads
                    for item in list(thread.floors) + list(thread.comments)
                    if not item.author_id and (item.author_name or item.portrait)
                }
                self._apply_user_id_failed_states(self.last_threads)
                timings["用户ID"] = time.perf_counter() - stage_at
                stage_at = time.perf_counter()
                if strategy == "full":
                    uid_stats = enrich_tieba_uids(
                        self.last_threads,
                        fetcher,
                        options,
                        self._log_from_thread,
                        progress=lambda done, total: self._post(
                            ("identity_supplement_progress", done, total)
                        ),
                        concurrency=max(1, int(self.identity_concurrency_var.get() or 3)),
                    )
                    self._tieba_uid_failed = set(uid_stats.get("failed_uids") or [])
                self._apply_tieba_failed_states(self.last_threads)
                timings["贴吧ID"] = time.perf_counter() - stage_at
                timings["总耗时"] = time.perf_counter() - began
                self._manual_timing = dict(timings)
                self._persist_result(self.last_threads)
                self._post(("identity_supplement_done", strategy, dict(timings)))
            except CollectCancelled:
                self._persist_result(self.last_threads)
                self._post(("identity_supplement_stopped", dict(timings)))
            except Exception as error:  # noqa: BLE001
                self._post(("identity_supplement_error", str(error)))

        threading.Thread(target=worker, daemon=True).start()


    def _auto_fill_levels(self) -> None:
        """切到参与者时，如果还有缺等级的，自动在后台补一次（不用手动点）。"""
        if self.mode_var.get() == "guest":
            return
        if not parse_cookie_input(self.cookie_var.get()).get("BDUSS"):
            return
        if getattr(self, "_auto_filling", False) or getattr(self, "_auto_filled", False):
            return
        missing = [
            user
            for user in self.people_users
            if not user.get("level") and (user.get("uid") or user.get("username"))
        ]
        if not missing or not self.last_threads:
            return
        self._auto_filling = True
        self._auto_filled = True
        self.people_hint.configure(text=f"正在补全 {len(missing)} 人的等级…")

        def worker():
            try:
                fetcher = Fetcher(cookie=parse_cookie_input(self.cookie_var.get()), delay=0.3, verbose=False)
                options = CollectOptions(verbose=True, log=self._log_from_thread)
                for thread in self.last_threads:
                    fill_thread_levels(thread, fetcher, self._log_from_thread)
                    enrich_user_levels(thread, fetcher, options, self._log_from_thread)
                self._post(("levels_filled",))
            except Exception as error:  # noqa: BLE001
                self._post(("levels_error", str(error)))

        threading.Thread(target=worker, daemon=True).start()


    def _identity_fail_key(self, item) -> str:
        if isinstance(item, dict):
            uid = str(item.get("uid") or "")
            username = str(item.get("username") or "")
            portrait = str(item.get("portrait") or "")
            name = str(item.get("name") or "")
        else:
            uid = str(getattr(item, "author_id", "") or "")
            username = str(getattr(item, "author_name", "") or "")
            portrait = str(getattr(item, "portrait", "") or "")
            name = str(getattr(item, "author", "") or "")
        if uid:
            return f"uid:{uid}"
        if username:
            return f"un:{username}"
        if portrait:
            return f"pt:{portrait}"
        return f"nm:{name}"


    def _ask_identity_strategy(self, missing_uid: int, missing_tieba: int, allow_detail: bool = True):
        """返回 (strategy, remember)；关闭 = skip。"""
        result = {"strategy": "skip", "remember": False}
        win = tk.Toplevel(self.root)
        win.title("抓取完成，选择补全方式" if allow_detail else "补全身份")
        win.configure(bg="#ffffff")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        self._active_choice_window = win
        frame = tk.Frame(win, bg="#ffffff", padx=20, pady=16)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="抓取完成，选择补全方式" if allow_detail else "补全身份",
            bg="#ffffff",
            fg="#1f2937",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            frame,
            text=f"缺用户ID：{missing_uid} 人\n缺贴吧ID：{missing_tieba} 人",
            bg="#ffffff",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
            justify="left",
        ).pack(anchor="w", pady=(6, 10))
        remember_var = tk.BooleanVar(
            value=bool(self.settings.get("identity_remember_choice", True))
        )
        ttk.Checkbutton(frame, text="记住本次选择", variable=remember_var).pack(anchor="w", pady=(0, 8))

        def remember_state() -> bool:
            checked = bool(remember_var.get())
            self.settings["identity_remember_choice"] = checked
            save_settings(self.settings)
            return checked

        def choose(strategy: str) -> None:
            result["strategy"] = strategy
            result["remember"] = remember_state()
            win.destroy()

        choices = [
            ("跳过本次，直接完成" if allow_detail else "跳过本次", "skip"),
            ("只补用户ID", "user_id"),
            ("补全用户ID + 贴吧ID", "full"),
        ]
        if allow_detail:
            choices.append(("详情再补", "detail"))
        def make_command(value: str) -> Callable[[], None]:
            def command() -> None:
                choose(value)

            return command

        for text, strategy in choices:
            ttk.Button(frame, text=text, command=make_command(str(strategy))).pack(
                fill="x", pady=2
            )
        tk.Label(
            frame,
            text="关闭窗口或按 Esc = 跳过本次补全，会先二次确认，不记住选择。",
            bg="#ffffff",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        def on_close() -> None:
            if messagebox.askyesno(
                "跳过本次补全？",
                "关闭将跳过本次补全，并使用现有数据保存/导出。\n不记住本次选择。",
                parent=win,
                default=messagebox.NO,
            ):
                remember_state()
                result["strategy"] = "skip"
                result["remember"] = False
                win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        win.bind("<Escape>", lambda _event: on_close())
        win.update_idletasks()
        width = 460
        height = max(320, win.winfo_reqheight() + 16)
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        self.root.wait_window(win)
        if getattr(self, "_active_choice_window", None) is win:
            self._active_choice_window = None
        self._clear_identity_strategy_selection()
        try:
            self.root.focus_set()
        except tk.TclError:
            pass
        return result["strategy"], result["remember"]


    def _clear_identity_strategy_selection(self) -> None:
        box = getattr(self, "identity_strategy_box", None)
        if box is None:
            return
        try:
            box.selection_clear()
            box.icursor("end")
        except tk.TclError:
            pass


    def _save_identity_strategy(self) -> None:
        value = {
            "补全用户ID + 贴吧ID": "full",
            "每次询问": "ask",
            "跳过补全": "skip",
            "只补用户ID": "user_id",
            "详情再补": "detail",
        }.get(self.identity_strategy_var.get(), "full")
        self.settings["identity_strategy"] = value
        if hasattr(self, "identity_timing_var"):
            self.settings["identity_timing"] = bool(self.identity_timing_var.get())
        if hasattr(self, "identity_concurrency_var"):
            self.settings["identity_concurrency"] = int(self.identity_concurrency_var.get() or 3)
        save_settings(self.settings)
        self._clear_identity_strategy_selection()
        self._update_identity_risk_hint()
        self._update_risk_summary()


    def _update_identity_risk_hint(self) -> None:
        if not hasattr(self, "identity_risk_label"):
            return
        strategy = self._identity_strategy()
        value = str(getattr(self, "identity_concurrency_var", tk.StringVar(value="3")).get())
        unused = strategy in ("skip", "user_id", "detail")
        if hasattr(self, "identity_concurrency_box"):
            self.identity_concurrency_box.configure(state="disabled" if unused else "readonly")
        if unused:
            self.identity_risk_label.configure(text="未使用", fg="#8a94a6")
        elif value == "5":
            self.identity_risk_label.configure(
                text="高风险：可能触发验证码或临时限流", fg="#b91c1c"
            )
        else:
            self.identity_risk_label.configure(text="较稳（默认）", fg="#64748b")


    def _identity_strategy(self) -> str:
        return {
            "补全用户ID + 贴吧ID": "full",
            "每次询问": "ask",
            "跳过补全": "skip",
            "只补用户ID": "user_id",
            "详情再补": "detail",
        }.get(getattr(self, "identity_strategy_var", tk.StringVar(value="")).get(), "full")


    def _enrich_levels_now(self) -> None:
        if not self.last_threads:
            self.status_var.set("还没有可补全等级的数据")
            return
        if getattr(self, "_enriching", False):
            return
        self._enriching = True
        self.people_hint.configure(text="正在补全等级，请稍候…")

        def worker():
            try:
                fetcher = Fetcher(cookie=self._request_cookie(), delay=0, verbose=False)
                options = CollectOptions(verbose=True, log=self._log_from_thread)
                for thread in self.last_threads:
                    filled = fill_thread_levels(thread, fetcher, self._log_from_thread)
                    if filled:
                        self._log_from_thread(f"  新版网页接口补全等级：{filled} 处")
                    enrich_user_levels(thread, fetcher, options, self._log_from_thread)
                if self.last_output:
                    export_workbook(
                        self.last_output,
                        self.last_threads,
                        include_op=getattr(self, "last_include_op", True),
                    )
                self._post(("enrich_done",))
            except Exception as error:  # noqa: BLE001
                self._post(("enrich_error", str(error)))

        threading.Thread(target=worker, daemon=True).start()


    def _batch_refresh_marks(self, resume_users=None) -> None:
        if getattr(self, "_batch_running", False):
            self._batch_cancel = True
            self.batch_btn.configure(text="正在停止…")
            return
        if not self._risk_enabled():
            messagebox.showinfo(
                "本地标记未启用",
                "先在「设置 → 通用」里启用本地标记与红绿灯。",
                parent=self.root,
            )
            return
        if not self._has_mark_rules():
            messagebox.showinfo(
                "没有本地标记规则",
                "先在「设置 → 本地标记」里填写安全/可疑/警告贴吧，再刷红绿灯。",
                parent=self.root,
            )
            self._focus_local_marks()
            return
        if not getattr(self, "people_users", None):
            messagebox.showinfo("还没有数据", "先点「开始统计」抓一个帖子。", parent=self.root)
            return
        users = list(resume_users) if resume_users is not None else self._visible_people()
        if not users:
            messagebox.showinfo("没有可刷新的用户", "当前筛选没有用户。", parent=self.root)
            return
        self._batch_running = True
        self._batch_cancel = False
        self._batch_done = 0
        self._batch_total = len(users)
        self._batch_plan = list(users)
        self._batch_pending = []
        self._marks_stale = False
        self._batch_success = 0
        self._batch_skip = 0
        self._batch_fail = 0
        self.resume_batch_btn.pack_forget()
        self.resume_batch_btn.configure(state="disabled", text="继续未完成")
        self.remark_btn.state(["disabled"])
        self.refresh_people_btn.state(["disabled"])
        self.include_follows_check.state(["disabled"])
        self._set_people_controls_enabled(False)
        self.batch_btn.configure(text="停止查询")
        self.people_hint.configure(text=f"批量查询 0/{self._batch_total}…")
        count = self._post_count()
        start_date, end_date = self._date_params()
        prefer = (
            "start"
            if self.post_date_mode_var.get() == "指定日期" and "最早" in self.post_prefer_var.get()
            else "end"
        )

        include_follows = bool(self.include_follows_var.get() and self.settings.get("follow_enhance"))
        guest = self.mode_var.get() == "guest"
        cookie = {} if guest else parse_cookie_input(self.cookie_var.get())
        concurrency = 1 if include_follows else max(1, min(3, int(self.settings.get("batch_concurrency", 1) or 1)))

        def resolve(user):
            name = str(user.get("name") or "").strip()
            if not any((user.get("uid"), user.get("username"), user.get("portrait"), name)):
                return {"ok": False, "skipped": True, "error": "缺少用户身份"}
            key = (
                f"{user.get('uid') or user.get('username') or name}|{count}|{start_date}|{end_date}|"
                f"{prefer}|{int(include_follows)}|{int(guest)}"
            )
            hit = self._batch_cache.get(key)
            if hit and time.monotonic() - hit[0] < 60:
                return hit[1]
            try:
                fetcher = Fetcher(cookie=cookie, delay=0.3, verbose=False)
                uid = user.get("uid") or ""
                username = user.get("username") or ""
                if not uid:
                    info = {}
                    if username:
                        info = resolve_user(fetcher, username, "用户名")
                    elif name:
                        info = resolve_user(fetcher, name, "昵称")
                    if not info.get("uid") and not user.get("portrait") and name and username:
                        info = resolve_user(fetcher, name, "昵称")
                    if info.get("uid"):
                        uid = info.get("uid") or ""
                        username = info.get("username") or username
                        user["uid"] = uid
                        user["username"] = username
                        user["portrait"] = info.get("portrait") or user.get("portrait") or ""
                    elif not user.get("portrait"):
                        return {"ok": False, "skipped": True, "error": "用户名/昵称无法唯一定位"}
                    # 没有 uid/username 但保留 portrait 时，仍可用 portrait 查发言。
                cached_posts = cached_user_posts(
                    uid, count, start_date, end_date, prefer, promote=False
                )
                if cached_posts is not None and not include_follows:
                    return {
                        "ok": True,
                        "recent_posts": cached_posts,
                        "bar_level": str(user.get("level") or ""),
                        "follow_loaded": False,
                        "followed_forums": [],
                        "hidden_forums": [],
                        "post_sources": {"cached": True},
                    }
                profile = fetch_user_profile(
                    fetcher,
                    uid,
                    user.get("username") or "",
                    user.get("portrait") or "",
                    self._user_bar(user),
                    count,
                    start_date,
                    end_date,
                    prefer,
                    load_follow=include_follows,
                    topic_max_pages=1,
                    use_cache=False,
                    cache_priority=0,
                    cached_posts=cached_posts,
                )
            except Exception as error:  # noqa: BLE001
                return {"ok": False, "error": str(error)}
            if profile.get("ok"):
                if len(self._batch_cache) >= 500:
                    self._batch_cache.clear()
                self._batch_cache[key] = (time.monotonic(), profile)
            return profile

        def worker():
            if concurrency <= 1:
                for index, user in enumerate(users):
                    if self._batch_cancel:
                        break
                    self._post(("batch_profile", index, user, resolve(user)))
            else:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = [pool.submit(resolve, user) for user in users]
                    for index, (user, future) in enumerate(zip(users, futures, strict=False)):
                        if self._batch_cancel:
                            break
                        try:
                            profile = future.result()
                        except Exception as error:  # noqa: BLE001
                            profile = {"ok": False, "error": str(error)}
                        self._post(("batch_profile", index, user, profile))
            self._post(("batch_done",))

        threading.Thread(target=worker, daemon=True).start()


    def _resume_batch(self) -> None:
        if self._batch_pending:
            pending = list(self._batch_pending)
            self._batch_pending = []
            self._batch_refresh_marks(resume_users=pending)


    def _apply_batch_mark(self, user, profile) -> None:
        if not self._risk_enabled():
            return
        iid = user.get("_iid")
        if iid is None:
            return
        level = str(profile.get("bar_level") or "") if profile.get("ok") else ""
        if level in ("0", "None"):
            level = ""
        if not level and profile.get("ok"):
            level = str(user.get("level") or "")
            if level in ("0", "None"):
                level = ""
        if level and not user.get("level"):
            user["level"] = level
        if profile.get("ok"):
            if profile.get("user_id") and not user.get("uid"):
                user["uid"] = str(profile.get("user_id") or "")
            if profile.get("username") and not user.get("username"):
                user["username"] = str(profile.get("username") or "")
            if profile.get("portrait") and not user.get("portrait"):
                user["portrait"] = str(profile.get("portrait") or "")
        hit_level = ""
        hit_bar = ""
        if profile.get("ok"):
            hit_level, hit_bar = self._profile_hit(profile, user.get("bars") or [self._user_bar(user)])
        hidden = self._hidden_follows(profile) if profile.get("ok") else False
        user["mark_level"] = hit_level
        user["hit"] = hit_level
        user["mark_bar"] = hit_bar or ""
        user["mark_hidden"] = bool(hidden)
        user["mark_at"] = time.time()
        user["mark_error"] = str(profile.get("error") or "")
        self._set_person_mark_row(user)

