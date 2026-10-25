"""抓取生命周期与 worker mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
import tkinter as tk
import traceback
from tkinter import messagebox
from typing import Any, Dict

from tieba_gui_utils import default_output_path

from tieba_reply_stats import webview2
from tieba_reply_stats.collect import (
    CollectCancelled,
    CollectError,
    CollectOptions,
    collect_thread,
    enrich_identities,
    enrich_tieba_uids,
    extract_tid,
)
from tieba_reply_stats.cookie_store import save_cookie
from tieba_reply_stats.errors import friendly_error
from tieba_reply_stats.export import export_workbook
from tieba_reply_stats.fetch import (
    CaptchaError,
    Fetcher,
    FetchError,
    RateLimitError,
    ThreadGoneError,
    configure_gate,
    parse_cookie_input,
    pause_requests,
    resume_requests,
    set_requests_paused,
    set_stop_checker,
)


class WorkerMixin:
    """抓取生命周期与 worker 方法，从 App 拆出。"""

    last_threads: Any
    worker: Any
    _webview_cookie_session: Any
    _identity_choice_queue: Any
    _rate_choice_queue: Any
    _manual_timing: Any
    _tieba_uid_failed: Any
    _user_id_failed: Any
    _emoji_window: Any
    _active_choice_window: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _start_from_key(self, _event=None):
        self._on_start()
        return "break"


    def _on_start(self) -> None:
        if self.running or getattr(self, "_supplement_running", False):
            return
        raw = self.url_text.get("1.0", "end").strip()
        tokens = [item for item in re.split(r"[\s,，;；]+", raw) if item]
        urls, bad = [], []
        for token in tokens:
            try:
                extract_tid(token)
                urls.append(token)
            except ValueError:
                bad.append(token)
        if not urls:
            self.status_var.set("先粘贴至少一个帖子链接")
            self.url_text.focus_set()
            return
        if bad:
            messagebox.showwarning(
                "有内容无法识别",
                "下面这些不是有效的帖子链接，将被忽略：\n\n" + "\n".join(bad[:6]),
                parent=self.root,
            )

        existing = {thread.meta.tid for thread in self.last_threads}
        current = {extract_tid(url) for url in urls}
        removed = existing - current
        removed_action = self.settings.get("removed_thread_action", "keep")
        if removed and removed_action == "ask":
            choice = self._ask_choice(
                "旧帖处理",
                f"有 {len(removed)} 个已抓过的帖子不在本次输入框中。\n"
                "要移除这些旧结果，还是保留？",
                [("移除旧结果", "remove"), ("保留旧结果", "keep"), ("取消", None)],
                default=0,
            )
            if choice is None:
                return
            removed_action = choice
        if removed and removed_action == "remove":
            self.last_threads = [thread for thread in self.last_threads if thread.meta.tid not in removed]
            existing = {thread.meta.tid for thread in self.last_threads}
            self._append_log(f"已移除 {len(removed)} 个旧帖结果。", "muted")
        if existing and not self.settings.get("auto_refresh_old", False):
            fresh = [url for url in urls if extract_tid(url) not in existing]
            if not fresh:
                messagebox.showinfo("没有新帖", "这些帖子都已抓过；可在设置里开启自动刷新。", parent=self.root)
                return
            if len(fresh) != len(urls):
                self._append_log(f"跳过已抓过的 {len(urls) - len(fresh)} 个帖子。", "muted")
            urls = fresh
        export = self.export_var.get()
        output = self.output_var.get().strip() or default_output_path()
        if export:
            if not output.lower().endswith(".xlsx"):
                output += ".xlsx"
            self._set_output(output)
            if os.path.exists(output) and not messagebox.askyesno(
                "文件已存在",
                f"这个文件已经存在：\n{output}\n\n要覆盖它吗？",
                parent=self.root,
                default=messagebox.NO,
            ):
                return
        else:
            output = ""

        try:
            delay = float(self.delay_var.get())
        except ValueError:
            delay = 0.8
        delay = min(5.0, max(0.3, delay))

        mode = self.mode_var.get()
        cookie = (
            self._request_cookie()
            if mode == "guest"
            else parse_cookie_input(self._current_cookie_text())
        )
        if mode == "login" and self.login_method_var.get() == "bduss" and not cookie.get("BDUSS"):
            messagebox.showwarning(
                "需要 BDUSS",
                "「仅 BDUSS」模式需要填写 BDUSS；也可以切换到「完整 Cookie」。",
                parent=self.root,
            )
            self.bduss_entry.focus_set()
            return
        if mode == "login" and not webview2.has_login_cookie(cookie):
            messagebox.showwarning(
                "需要登录 Cookie",
                "完整 Cookie 里没有 BDUSS/TIEBA_SID，无法确认登录态。\n"
                "请重新获取完整 Cookie，或改用游客模式。",
                parent=self.root,
            )
            self.cookie_entry.focus_set()
            return
        if mode == "guest":
            self._append_log("本次使用免登录模式：公开帖子，楼中楼按设置补全", "muted")
        elif getattr(self, "_webview_cookie_session", False):
            self._append_log("本次完整 Cookie 来自内置验证，不自动保存到本机。", "muted")
            self._webview_cookie_session = False
        elif self._remember_current_login():
            if save_cookie(self._current_cookie_text()):
                self._append_log("已记住登录信息（本机加密保存），下次会自动填入。", "muted")
            else:
                self._append_log("登录信息保存失败，本次仍可正常使用。", "muted")

        options = CollectOptions(
            mode=mode,
            include_comments=self.comments_var.get(),
            comment_depth=self._comment_depth_value(),
            comment_concurrency=max(1, min(3, int(self.comment_concurrency_var.get() or 1))),
            enrich_levels=True,
            enrich_identities=False,
            pb_levels=True,
            verbose=True,
            log=self._log_from_thread,
            should_stop=self.stop_event.is_set,
        )
        include_op = not self.exclude_op_var.get()
        self.last_include_op = include_op

        self._update_risk_summary()
        risk_items = self._high_risk_items()
        if risk_items:
            if not self._ask_choice(
                "高风险设置",
                "本次有以下高风险设置：\n- "
                + "\n- ".join(risk_items)
                + "\n\n可能触发验证码或临时限流，不保证不会受限。",
                [("返回调整", False), ("仍然开始", True)],
                default=0,
            ):
                return

        self._current_urls = list(urls)
        resume_requests()
        configure_gate(float(delay or 0))
        self.stop_event.clear()
        self._task_paused = False
        set_stop_checker(self.stop_event.is_set)
        self._identity_choice_queue = queue.Queue()
        self._rate_choice_queue = queue.Queue()
        self._manual_timing = {}
        self._tieba_uid_failed = set()
        self._user_id_failed = set()
        self._write_log("fetch_start", threads=len(urls))
        self._set_running(True)
        self._append_log(f"\n开始统计 {len(urls)} 个帖子，请耐心等待…", "title")
        base_threads = list(self.last_threads)
        self.worker = threading.Thread(
            target=self._run_worker,
            args=(
                urls,
                output,
                options,
                cookie,
                delay,
                include_op,
                export,
                base_threads,
                self._identity_strategy(),
                int(self.identity_concurrency_var.get() or 3),
            ),
            daemon=True,
        )
        self.worker.start()


    def _on_pause(self) -> None:
        if not self.running:
            return
        paused = not getattr(self, "_task_paused", False)
        self._task_paused = paused
        set_requests_paused(paused)
        self.pause_btn.configure(text="继续" if paused else "暂停")
        if paused:
            self.status_var.set("已暂停；已完成数据保留")
            self._append_log("已暂停，不再发新请求。", "muted")
        else:
            self.status_var.set("已继续抓取")
            self._append_log("已继续抓取。", "muted")


    def _on_stop(self) -> None:
        resume_requests()
        active_choice = getattr(self, "_active_choice_window", None)
        if active_choice is not None:
            try:
                active_choice.destroy()
            except tk.TclError:
                pass
            self._active_choice_window = None
        if getattr(self, "_supplement_running", False):
            self._supplement_stop.set()
            self.stop_btn.configure(state="disabled")
            self.status_var.set("正在停止补全…")
            return
        if not self.running:
            return
        self.stop_event.set()
        self.stop_btn.configure(state="disabled")
        self.status_var.set("正在停止…")


    def _run_worker(
        self,
        urls,
        output,
        options,
        cookie,
        delay,
        include_op,
        export=True,
        base_threads=None,
        identity_strategy="full",
        identity_concurrency=3,
    ) -> None:
        completed = []
        began = time.perf_counter()
        stage_at = began
        timings: Dict[str, float] = {}
        try:
            fetcher = Fetcher(cookie=cookie, delay=0, verbose=False)
            for index, url in enumerate(urls, start=1):
                self._post(("log", f"\n[{index}/{len(urls)}] {url}", "title"))
                try:
                    tid = extract_tid(url)
                except ValueError:
                    tid = ""
                self._write_log("thread_start", tid=tid)
                rate_attempt = 0
                thread = None
                while True:
                    try:
                        thread = collect_thread(url, fetcher, options)
                        break
                    except RateLimitError as error:
                        if rate_attempt >= 3:
                            raise
                        rate_attempt += 1
                        self._post(
                            ("rate_limit_ask", str(error), float(error.retry_after or 0), url)
                        )
                        choice = None
                        while choice is None:
                            try:
                                choice = self._rate_choice_queue.get(timeout=0.2)
                            except queue.Empty:
                                if self.stop_event.is_set():
                                    raise CollectCancelled("已停止") from error
                        if choice == "stop":
                            raise CollectCancelled("已停止") from error
                        pause_requests(float(choice))
                        continue
                    except CaptchaError:
                        raise
                    except CollectCancelled:
                        raise
                    except (ThreadGoneError, FetchError, CollectError, ValueError) as error:
                        self._write_log("thread_error", tid=tid, error=type(error).__name__)
                        self._post(("log", f"  ✗ 抓取失败：{error}", "err"))
                        thread = None
                        break
                if thread is None:
                    continue
                completed.append(thread)
                users = thread.user_stats()
                leveled = sum(1 for item in users if item.get("level"))
                self._write_log(
                    "thread_done",
                    tid=thread.meta.tid,
                    floors=len(thread.floors),
                    comments=len(thread.comments),
                    users=len(users),
                )
                self._write_log("level_done", tid=thread.meta.tid, leveled=leveled, users=len(users))
                title = thread.meta.title or thread.meta.tid
                self._post(
                    (
                        "log",
                        f"  ✓ {title}：{len(thread.floors)} 层 / {len(thread.comments)} 条楼中楼 / "
                        f"{len(thread.user_stats())} 位用户",
                        "ok",
                    )
                )
                for warning in thread.warnings[:3]:
                    self._post(("log", f"    ! {warning}", "muted"))

            timings["抓取"] = time.perf_counter() - stage_at
            stage_at = time.perf_counter()
            if not completed:
                self._post(
                    ("error", "没有抓到任何帖子。\n\n可能原因：帖子被删、链接不对，或者被安全验证拦截。")
                )
                return

            final_threads = []
            by_tid = {str(thread.meta.tid): thread for thread in (base_threads or [])}
            for thread in completed:
                by_tid[str(thread.meta.tid)] = thread
            final_threads = list(by_tid.values())
            timings["合并"] = time.perf_counter() - stage_at
            stage_at = time.perf_counter()

            identity_options = CollectOptions(
                verbose=True,
                log=self._log_from_thread,
                should_stop=self.stop_event.is_set,
            )
            missing_uid = 0
            missing_tieba = 0
            seen_users: Dict[str, Dict[str, object]] = {}
            for thread in final_threads:
                for item in list(thread.floors) + list(thread.comments):
                    uid = str(getattr(item, "author_id", "") or "")
                    key = (
                        f"uid:{uid}"
                        if uid
                        else (
                            f"un:{item.author_name}"
                            if item.author_name
                            else (f"pt:{item.portrait}" if item.portrait else f"nm:{item.author}")
                        )
                    )
                    info = seen_users.setdefault(key, {"uid": uid, "tieba": ""})
                    if getattr(item, "tieba_uid", ""):
                        info["tieba"] = item.tieba_uid
            for info in seen_users.values():
                if not info["uid"]:
                    missing_uid += 1
                elif not info["tieba"]:
                    missing_tieba += 1

            strategy = identity_strategy
            if strategy == "ask" and (missing_uid or missing_tieba):
                self._post(("identity_ask", missing_uid, missing_tieba))
                choice = None
                remember = False
                while choice is None:
                    try:
                        choice, remember = self._identity_choice_queue.get(timeout=0.2)
                    except queue.Empty:
                        if self.stop_event.is_set():
                            choice, remember = "skip", False
                strategy = choice
                if remember:
                    self._post(("identity_remember", strategy))
            elif strategy == "ask":
                strategy = "skip"

            if strategy in ("full", "user_id"):
                self._post(("stage", "抓取完成，正在补全身份…"))
                for thread in final_threads:
                    enrich_identities(thread, fetcher, identity_options, self._log_from_thread)
                self._identity_missing = sum(
                    1
                    for thread in final_threads
                    for item in list(thread.floors) + list(thread.comments)
                    if not item.author_id and (item.author_name or item.portrait)
                )
            else:
                self._identity_missing = missing_uid
            self._write_log(
                "identity_done",
                missing=self._identity_missing,
                users=sum(len(thread.user_stats()) for thread in final_threads),
            )
            if self._identity_missing:
                self._post(
                    ("log", f"  ⚠ 仍有 {self._identity_missing} 条身份待补充（不影响已抓内容）", "err")
                )

            if strategy in ("full", "user_id"):
                self._user_id_failed = {
                    self._identity_fail_key(item)
                    for thread in final_threads
                    for item in list(thread.floors) + list(thread.comments)
                    if not item.author_id and (item.author_name or item.portrait)
                }
            else:
                self._user_id_failed = set()
            self._apply_user_id_failed_states(final_threads)
            timings["用户ID"] = time.perf_counter() - stage_at
            stage_at = time.perf_counter()
            if strategy == "full":
                self._post(("stage", "身份完成，正在补全贴吧ID…"))
                uid_stats = enrich_tieba_uids(
                    final_threads,
                    fetcher,
                    identity_options,
                    self._log_from_thread,
                    progress=lambda done, total: self._post(
                        ("stage", f"正在补全贴吧ID {done}/{total}…")
                    ),
                    concurrency=max(1, int(identity_concurrency or 3)),
                )
                self._tieba_uid_missing = int(uid_stats.get("failed") or 0)
                self._tieba_uid_failed = set(uid_stats.get("failed_uids") or [])
            else:
                self._tieba_uid_missing = missing_tieba
                self._tieba_uid_failed = set()
            self._last_identity_strategy = strategy
            self._apply_tieba_failed_states(final_threads)
            self._write_log("tieba_uid_done", missing=self._tieba_uid_missing, users=len(final_threads))
            timings["贴吧ID"] = time.perf_counter() - stage_at
            stage_at = time.perf_counter()
            self._post(("stage", "正在保存结果…"))
            self._persist_result(final_threads)
            self._write_log("save", threads=len(final_threads), stage="identity")
            timings["保存"] = time.perf_counter() - stage_at
            stage_at = time.perf_counter()

            if export:
                self._post(("stage", "正在生成 Excel…"))
                export_workbook(output, final_threads, include_op=include_op)
                timings["导出"] = time.perf_counter() - stage_at
                stage_at = time.perf_counter()
                self._write_log("export", ok=True, threads=len(final_threads))
                self._write_log(
                    "done",
                    threads=len(final_threads),
                    users=sum(len(thread.user_stats()) for thread in final_threads),
                    exported=True,
                )
                timings["总耗时"] = time.perf_counter() - began
                self._post(("done", output, len(final_threads), list(final_threads), dict(timings)))
            else:
                timings["导出"] = 0.0
                timings["总耗时"] = time.perf_counter() - began
                self._write_log(
                    "done",
                    threads=len(final_threads),
                    users=sum(len(thread.user_stats()) for thread in final_threads),
                    exported=False,
                )
                self._post(("done", None, len(final_threads), list(final_threads), dict(timings)))
        except CaptchaError as error:
            self._write_log("error", error="CaptchaError")
            partial = []
            items = list(completed)
            if getattr(error, "partial", None) is not None:
                items.append(error.partial)
            if items:
                by_tid = {str(thread.meta.tid): thread for thread in (base_threads or [])}
                for thread in items:
                    by_tid[str(thread.meta.tid)] = thread
                partial = list(by_tid.values())
                self._persist_result(partial)
            self._post(("captcha", str(error), list(partial)))
        except RateLimitError as error:
            self._write_log("error", error="RateLimitError")
            self._post(("rate_limit", str(error), float(error.retry_after or 0)))
        except CollectCancelled:
            self._write_log("cancelled", threads=len(completed), exported=bool(export and completed))
            if completed:
                by_tid = {str(thread.meta.tid): thread for thread in (base_threads or [])}
                for thread in completed:
                    by_tid[str(thread.meta.tid)] = thread
                final_threads = list(by_tid.values())
                self._persist_result(final_threads)
                if export:
                    export_workbook(output, final_threads, include_op=include_op)
                    self._write_log("export", ok=True, threads=len(final_threads))
                self._post(
                    (
                        "cancelled_partial",
                        output if export else None,
                        len(final_threads),
                        list(final_threads),
                    )
                )
            else:
                self._post(("cancelled",))
        except Exception as error:  # noqa: BLE001 - 界面上要给出可读信息
            self._write_log("error", error=type(error).__name__)
            self._post(("log", traceback.format_exc(), "muted"))
            self._post(("error", friendly_error(error)))

