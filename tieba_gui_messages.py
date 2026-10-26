"""后台消息处理器 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import time
import webbrowser
from tkinter import messagebox
from typing import Any

from tieba_reply_stats import webview2
from tieba_reply_stats.cookie_store import save_cookie
from tieba_reply_stats.errors import friendly_error
from tieba_reply_stats.fetch import parse_cookie_input, pause_requests
from tieba_reply_stats.settings import save_settings


class MessageMixin:
    """后台消息处理器，从 App._handle_message 拆出。"""

    root: Any
    status_var: Any
    login_method_var: Any
    _simulated_restore: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _handle_captcha_message(self, message: tuple) -> None:
        _, detail, partial = message
        if partial:
            self.last_threads = self._merge_threads(partial)
            self._persist_result(self.last_threads)
            self._refresh_people()
            self._refresh_grid()
            self._append_log(
                f"验证码中断：已保留 {len(self.last_threads)} 个已完成帖子。",
                "warn",
            )
        self._set_running(False)
        self.status_var.set("被安全验证拦截")
        self._append_log("抓取失败：" + detail, "err")
        if getattr(self, "_simulated_captcha", False):
            self._simulated_captcha = False
            mode = self.mode_var.get()
            if mode == "guest":
                dialog_text = (
                    "当前是游客模式。\n"
                    "真实流程会读取匿名 Cookie，不读取 BDUSS/STOKEN。"
                )
            elif self.login_method_var.get() == "bduss":
                cached = bool(getattr(self, "_full_cookie_cache", ""))
                dialog_text = (
                    "本次实际只发送了 BDUSS。\n"
                    + (
                        "真实流程会提示改用已保存的完整 Cookie。"
                        if cached
                        else "当前没有完整 Cookie 缓存。"
                    )
                )
            else:
                dialog_text = (
                    "当前使用完整 Cookie。\n"
                    "真实流程会读取完整 Cookie，并检查 BDUSS。"
                )
            self._ask_choice(
                "模拟验证码",
                dialog_text
                + "\n\n模拟模式：不打开 WebView2、不读取 Cookie、不修改登录状态。",
                [("结束模拟", "stop")],
            )
            restore = getattr(self, "_simulated_restore", None)
            self._simulated_restore = None
            if restore:
                self.mode_var.set(restore[0])
                self.login_method_var.set(restore[1])
                self._on_login_method_changed()
                self._apply_mode_ui()
            self.status_var.set("模拟验证码已结束（未联网）")
            self._append_log("模拟验证码已结束，未发出请求。", "muted")
            self._refresh_log_summary()
            return
        mode = self.mode_var.get()
        current_cookie_mode = mode == "login" and self.login_method_var.get() == "cookie"
        use_bduss = mode == "login" and self.login_method_var.get() == "bduss"
        cached_cookie = bool(getattr(self, "_full_cookie_cache", ""))
        if use_bduss and cached_cookie:
            dialog_text = (
                "本次实际只发送了 BDUSS。\n"
                "软件检测到你之前保存过完整 Cookie，可能是仅 BDUSS 不够用。\n\n"
                "是否改用完整 Cookie 重试？"
            )
        elif use_bduss:
            dialog_text = (
                "本次实际只发送了 BDUSS，且没有可用的完整 Cookie。\n"
                "验证码通常需要完整 Cookie。"
            )
        elif mode == "guest":
            if webview2.available():
                dialog_text = (
                    "当前是游客模式。\n"
                    "完成验证后软件会自动读取匿名 Cookie，不会读取 BDUSS/STOKEN。"
                )
            else:
                dialog_text = (
                    "当前是游客模式，且未检测到 WebView2 Runtime。\n"
                    "可以改用登录模式（完整 Cookie）继续。"
                )
        else:
            dialog_text = (
                "当前请求需要完整 Cookie。\n"
                "完成验证后软件会读取完整 Cookie，仅用于本次抓取。"
            )
        choices = []
        if use_bduss and cached_cookie:
            choices.append(("改用已保存的完整 Cookie", "cached_cookie"))
        if webview2.available():
            choices.append(
                (
                    "打开内置验证（自动读匿名 Cookie）"
                    if mode == "guest"
                    else (
                        "重新打开内置验证并更新完整 Cookie"
                        if current_cookie_mode
                        else "打开内置验证并读取完整 Cookie"
                    ),
                    "embedded",
                )
            )
        choices.extend(
            [
                (
                    "重新手动粘贴完整 Cookie"
                    if current_cookie_mode
                    else "转到登录模式（完整 Cookie）",
                    "login",
                ),
                ("停止本次", "stop"),
            ]
        )
        choice = self._ask_choice(
            "被安全验证拦截",
            dialog_text,
            choices,
            default=0,
        )
        if choice == "cached_cookie":
            self.login_method_var.set("cookie")
            self.cookie_var.set(self._full_cookie_cache)
            self._on_login_method_changed()
            self._set_login_fields_expanded(False)
            self.login_toggle_btn.focus_set()
            self.status_var.set("登录信息已就绪")
            self._append_log("已改用缓存的完整 Cookie，请重新开始。", "ok")
            messagebox.showinfo(
                "已切换完整 Cookie",
                self._login_result_text("已改用之前保存的完整 Cookie"),
                parent=self.root,
            )
            self._refresh_log_summary()
            return
        if choice == "login":
            source = "manual"
            if mode == "guest" and webview2.available():
                source = self._ask_choice(
                    "改用登录模式（完整 Cookie）",
                    "选择获取完整 Cookie 的方式。\n"
                    "内置验证会读取完整 Cookie；手动方式只打开浏览器，不自动读取。",
                    [
                        ("打开内置验证并读取完整 Cookie", "embedded"),
                        ("手动粘贴完整 Cookie", "manual"),
                    ],
                    default=0,
                )
                if source is None:
                    return
            self.mode_var.set("login")
            self.login_method_var.set("cookie")
            self._on_login_method_changed()
            if mode == "guest":
                self.settings["follow_enhance"] = True
                if hasattr(self, "follow_enhance_var"):
                    self.follow_enhance_var.set(True)
                save_settings(self.settings)
                self._apply_risk_ui()
                self._append_log("已自动开启关注检测。", "muted")
            if source == "embedded":
                self._start_webview_cookie_flow(anonymous=False)
            else:
                url = (getattr(self, "_current_urls", []) or ["https://tieba.baidu.com/"])[0]
                try:
                    webbrowser.open(url)
                except Exception:  # noqa: S110, BLE001
                    pass
                self.cookie_entry.focus_set()
                self._append_log(
                    "已切换到登录模式（完整 Cookie）。手动粘贴完整 Cookie 后重新开始。",
                    "err",
                )
        elif choice == "embedded":
            self._start_webview_cookie_flow(
                anonymous=self.mode_var.get() == "guest"
            )
        self._refresh_log_summary()


    def _handle_webview_test_done(self, message: tuple) -> None:
        _, error = message
        self._webview_running = False
        if error:
            self.status_var.set("内置验证窗口测试失败")
            messagebox.showwarning(
                "测试失败",
                f"内置验证窗口启动失败：\n{error}",
                parent=self.root,
            )
            return
        self.status_var.set("内置验证窗口测试完成")
        messagebox.showinfo(
            "测试完成",
            "内置验证窗口已成功打开并关闭。\n"
            "本测试会打开真实帖子页面，但不读取 Cookie、不修改登录状态。",
            parent=self.root,
        )


    def _handle_embedded_done(self, message: tuple) -> None:
        _, cookies, error, warning = message
        self._webview_running = False
        if error or not cookies:
            self.status_var.set("内置验证失败")
            self._append_log(f"内置验证窗口失败：{error or '没有可用 Cookie'}", "err")
            messagebox.showwarning(
                "内置验证未完成",
                (error or "没有读取到可用 Cookie。")
                + "\n可以改用「转到登录模式（完整 Cookie）」。",
                parent=self.root,
            )
            self._refresh_log_summary()
            return
        if self.mode_var.get() == "guest":
            self._guest_cookie = dict(cookies)
            self.status_var.set("游客验证会话已就绪")
            self._append_log("已获取匿名验证会话，保持游客模式。", "ok")
            messagebox.showinfo(
                "游客验证会话已获取",
                "已读取匿名 Cookie，未读取 BDUSS/STOKEN。\n"
                + self._login_result_text("模式仍为游客"),
                parent=self.root,
            )
        else:
            if not webview2.has_login_cookie(cookies):
                self._append_log(
                    "内置窗口未登录百度账号：没有读取到 BDUSS/TIEBA_SID。", "err"
                )
                messagebox.showwarning(
                    "尚未登录",
                    "没有读取到登录 Cookie（BDUSS/TIEBA_SID），"
                    "不能当作完整 Cookie 登录成功。\n"
                    "请重新打开内置登录并登录百度账号。",
                    parent=self.root,
                )
                self._refresh_webview_status()
                self._refresh_log_summary()
                return
            self._webview_cookie_session = True
            self._login_source = "内置浏览器"
            self._last_webview_match = (
                webview2.match_profile_fingerprint(cookies)
                if webview2.login_profile_exists()
                else None
            )
            self._save_login_fingerprint(cookies)
            cookie_text = "; ".join(f"{k}={v}" for k, v in cookies.items())
            self.cookie_var.set(cookie_text)
            self._full_cookie_cache = cookie_text
            self.login_method_var.set("cookie")
            self._on_login_method_changed()
            self._set_login_fields_expanded(False)
            self.login_toggle_btn.focus_set()
            self.status_var.set("登录信息已就绪")
            self._append_log("已从内置验证窗口读取完整 Cookie。", "ok")
            messagebox.showinfo(
                "验证完成",
                self._login_result_text("已读取完整 Cookie"),
                parent=self.root,
            )
            if warning:
                self._append_log(f"登录预检警告：{warning}", "warn")
                messagebox.showwarning(
                    "预检未通过",
                    warning + "\n\nCookie 已填入，但开始抓取后仍可能被拦截。",
                    parent=self.root,
                )
        self._offer_retry_incomplete("登录信息")
        self._refresh_webview_status()
        self._refresh_log_summary()


    def _handle_auto_login_done(self, message: tuple) -> None:
        _, target, cookies, error, warning = message
        self._webview_running = False
        if error or not cookies:
            self.status_var.set("登录信息获取失败")
            self._append_log(f"自动获取登录失败：{error or '没有可用 Cookie'}", "err")
            rolled_back = False
            if self.settings.get("follow_enhance") and not webview2.has_login_cookie(
                parse_cookie_input(self.cookie_var.get())
            ):
                self.settings["follow_enhance"] = False
                if hasattr(self, "follow_enhance_var"):
                    self.follow_enhance_var.set(False)
                save_settings(self.settings)
                self._set_mode("guest")
                rolled_back = True
                self._append_log("登录无效，已关闭关注检测并切回游客。", "warn")
            messagebox.showwarning(
                "自动获取失败",
                (error or "没有读取到可用 Cookie。")
                + (
                    "\n已关闭关注检测并切回游客。"
                    if rolled_back
                    else "\n可以改用手动粘贴。"
                ),
                parent=self.root,
            )
            self._refresh_webview_status()
            self._refresh_log_summary()
            return
        self._login_source = "内置浏览器"
        self._last_webview_match = (
            webview2.match_profile_fingerprint(cookies)
            if webview2.login_profile_exists()
            else None
        )
        self._save_login_fingerprint(cookies)
        cookie_text = "; ".join(f"{k}={v}" for k, v in cookies.items())
        self._full_cookie_cache = cookie_text
        if target == "bduss":
            self.login_method_var.set("bduss")
            self.bduss_var.set(str(cookies.get("BDUSS") or ""))
            self.cookie_var.set(f"BDUSS={cookies.get('BDUSS') or ''}")
            self._on_login_method_changed()
            self._set_login_fields_expanded(False)
            self.login_toggle_btn.focus_set()
            self._append_log("已自动获取 BDUSS。", "ok")
            messagebox.showinfo(
                "BDUSS 已获取",
                self._login_result_text("已从内置登录提取 BDUSS"),
                parent=self.root,
            )
        else:
            self._webview_cookie_session = True
            self.login_method_var.set("cookie")
            self.cookie_var.set(cookie_text)
            self._on_login_method_changed()
            self._set_login_fields_expanded(False)
            self.login_toggle_btn.focus_set()
            self._append_log("已自动获取完整 Cookie。", "ok")
            messagebox.showinfo(
                "完整 Cookie 已获取",
                self._login_result_text("已从内置登录读取完整 Cookie"),
                parent=self.root,
            )
        self.status_var.set(
            "登录信息已获取" if not warning else "登录信息已获取（预检未通过）"
        )
        if warning:
            self._append_log(f"登录预检警告：{warning}", "warn")
            messagebox.showwarning(
                "预检未通过",
                warning + "\n\nCookie 已填入，但开始抓取后仍可能被拦截。",
                parent=self.root,
            )
        self._offer_retry_incomplete("登录信息")
        self._refresh_webview_status()
        self._refresh_log_summary()


    def _handle_switch_login_done(self, message: tuple) -> None:
        _, cookies, error, warning = message
        self._webview_running = False
        if error or not cookies:
            webview2.clear_switch_profile()
            self.status_var.set("切换账号失败")
            self._append_log(f"切换账号失败：{error or '没有可用 Cookie'}", "err")
            messagebox.showwarning(
                "切换账号失败",
                (error or "没有读取到可用 Cookie。")
                + "\n旧登录和旧内置会话已保留。",
                parent=self.root,
            )
            self._refresh_webview_status()
            return
        remember = bool(self.settings.get("webview_remember_login", False))
        try:
            if remember:
                webview2.replace_login_profile(webview2.switch_profile_dir())
                self._save_login_fingerprint(cookies, force=True)
                self._last_webview_match = None
            else:
                webview2.clear_switch_profile()
                self._last_webview_match = (
                    webview2.match_profile_fingerprint(cookies)
                    if webview2.login_profile_exists()
                    else None
                )
        except Exception as switch_error:  # noqa: BLE001
            webview2.clear_switch_profile()
            self.status_var.set("切换账号失败")
            self._append_log(f"切换账号失败：{switch_error}", "err")
            messagebox.showwarning(
                "切换账号失败",
                f"{switch_error}\n旧登录和旧内置会话已保留。",
                parent=self.root,
            )
            self._refresh_webview_status()
            return
        target = "bduss" if self.login_method_var.get() == "bduss" else "cookie"
        self._adopt_webview_login(cookies, target)
        if self._remember_current_login():
            save_cookie(self._current_cookie_text())
        if not remember and webview2.login_profile_exists():
            if messagebox.askyesno(
                "清除旧内置登录",
                "新账号已登录，但“记住内置登录”未开启。\n"
                "旧的内置登录仍是旧账号。是否清除旧内置登录？",
                parent=self.root,
                default=messagebox.YES,
            ):
                if webview2.clear_login_profile():
                    self._last_webview_match = None
                else:
                    messagebox.showwarning(
                        "旧内置登录未清除",
                        "旧内置登录目录仍被占用；当前账号已切换，旧目录保留。",
                        parent=self.root,
                    )
        self.status_var.set("已切换百度账号")
        self._append_log("已切换百度账号并更新当前登录。", "ok")
        if warning:
            self._append_log(f"登录预检警告：{warning}", "warn")
        self._offer_retry_incomplete("登录信息")
        self._refresh_webview_status()
        self._refresh_log_summary()

    def _handle_message_log(self, message: tuple) -> None:
        _, text, tag = message
        self._append_log(text, tag)


    def _handle_message_stage(self, message: tuple) -> None:
        self.status_var.set(message[1])


    def _handle_message_done(self, message: tuple) -> None:
        _, output, count, threads, timings = message
        self._last_stage_times = dict(timings) if self.identity_timing_var.get() else {}
        if self.identity_timing_var.get():
            for key in ("抓取", "合并", "用户ID", "贴吧ID", "保存", "导出", "总耗时"):
                if key in timings:
                    self._append_log(f"  {key}耗时：{timings[key]:.1f} 秒", "muted")
        self.last_output = output
        self.last_threads = self._merge_threads(threads or [])
        self._persist_result(self.last_threads)
        self._auto_filled = False
        self._profile_cache.clear()
        try:
            self._reset_people_filters()
            self._refresh_people()
            self._refresh_grid()
            if str(getattr(self, "_last_identity_strategy", "full")) == "detail":
                self.post_nb.select(self.tab_people)
        except Exception:  # noqa: S110, BLE001
            pass
        self._set_running(False)
        identity_missing = int(getattr(self, "_identity_missing", 0) or 0)
        tieba_missing = int(getattr(self, "_tieba_uid_missing", 0) or 0)
        incomplete_threads = [
            thread for thread in self.last_threads if not getattr(thread, "complete", True)
        ]
        timing_enabled = bool(self.identity_timing_var.get())
        total_seconds = float(timings.get("总耗时") or 0) if timing_enabled else 0.0
        missing_label = (
            "待补充" if str(getattr(self, "_last_identity_strategy", "full")) in ("skip", "detail", "user_id") else "失败"
        )
        status = f"完成 · {len(self.last_threads)} 个帖子 / {len(self._aggregate_users())} 位用户"
        last_strategy = str(getattr(self, "_last_identity_strategy", "full"))
        if identity_missing:
            status += f" · 身份待补充 {identity_missing} 条"
        if tieba_missing:
            if last_strategy in ("skip", "detail", "user_id"):
                status += f" · 贴吧ID待补充 {tieba_missing} 人"
            else:
                status += f" · 贴吧ID失败 {tieba_missing} 人"
        if incomplete_threads:
            status += f" · 不完整 {len(incomplete_threads)} 帖"
        self.status_var.set(status)
        self._refresh_cache_stats_if_visible()
        self._refresh_log_summary()
        if output:
            self.open_btn.configure(state="normal")
            self._append_log(f"\n完成！共 {count} 个帖子，文件已保存：\n{output}", "ok")
            messagebox.showinfo(
                "全部完成",
                f"统计完成，共 {count} 个帖子。\n\n文件已保存到：\n{output}\n\n"
                + (f"总耗时：{total_seconds:.1f} 秒。\n\n" if timing_enabled else "")
                + (
                    f"有 {len(incomplete_threads)} 个帖子只抓到部分内容，"
                    "可在参与者页点「重试失败部分」。\n\n"
                    if incomplete_threads
                    else ""
                )
                + (f"贴吧ID{missing_label} {tieba_missing} 人。\n\n" if tieba_missing else "")
                + "切到「参与者」选项卡可以点开每个人，查看他的发言和关注的贴吧。",
                parent=self.root,
            )
            self._open_result()
        else:
            self.open_btn.configure(state="disabled")
            self._append_log(f"\n完成！共 {count} 个帖子（按设置未导出 Excel）。", "ok")
            messagebox.showinfo(
                "全部完成",
                f"统计完成，共 {count} 个帖子。\n\n按设置没有导出 Excel，可以切到「参与者」看结果，"
                "或点「导出 Excel」现在生成。\n\n"
                + (f"总耗时：{total_seconds:.1f} 秒。" if timing_enabled else "")
                + (
                    f"\n\n有 {len(incomplete_threads)} 个帖子只抓到部分内容，"
                    "可在参与者页点「重试失败部分」。"
                    if incomplete_threads
                    else ""
                )
                + (f"\n\n贴吧ID{missing_label} {tieba_missing} 人。" if tieba_missing else ""),
                parent=self.root,
            )


    def _handle_message_cancelled_partial(self, message: tuple) -> None:
        _, output, count, threads = message
        self.last_output = output
        self.last_threads = threads or []
        self._auto_filled = False
        self._set_running(False)
        self.status_var.set("已停止（已导出完成部分）" if output else "已停止")
        if output:
            self.open_btn.configure(state="normal")
            self._append_log(f"\n已停止，先导出了 {count} 个已完成帖子的结果：\n{output}", "err")
        else:
            self.open_btn.configure(state="disabled")
            self._append_log(f"\n已停止，完成了 {count} 个帖子的抓取（未导出 Excel）。", "err")
        self._refresh_log_summary()


    def _handle_message_probe_done(self, message: tuple) -> None:
        _, profile, results, button = message
        self._probe_running = False
        button.configure(state="normal", text="探测候选关注")
        profile["probed_forums"] = results
        if results:
            summary = f"候选探测完成：确认 {len(results)} 个关注。"
            self._append_log(summary, "ok")
        else:
            summary = "候选探测完成：没有确认新的关注。"
            self._append_log(summary, "muted")
        if profile is getattr(self, "_last_lookup_profile", None):
            self._render_lookup(profile)
            self.lookup_status.configure(text=summary)
        elif profile is getattr(self, "_profile_data", None):
            self._render_profile(self._profile_user, profile)
            self.profile_status.configure(text=summary)


    def _handle_message_batch_profile(self, message: tuple) -> None:
        _, index, user, profile = message
        self._batch_done = max(getattr(self, "_batch_done", 0), index + 1)
        key = user.get("uid") or f"name:{user['name']}"
        if profile and profile.get("ok"):
            profile["_ui_cached_at"] = time.time()
            self._profile_cache[key] = profile
            self._batch_success = getattr(self, "_batch_success", 0) + 1
        elif profile and profile.get("skipped"):
            self._batch_skip = getattr(self, "_batch_skip", 0) + 1
            user["mark_error"] = str(profile.get("error") or "跳过")
        else:
            self._batch_fail = getattr(self, "_batch_fail", 0) + 1
        self._apply_batch_mark(user, profile)
        if getattr(self, "_batch_total", 0):
            live = f"批量查询 {self._batch_done}/{self._batch_total}…"
            if getattr(self, "_batch_skip", 0):
                live += f" · 跳过 {self._batch_skip}"
            if getattr(self, "_batch_fail", 0):
                live += f" · 失败 {self._batch_fail}"
            self.people_hint.configure(text=live)


    def _handle_message_batch_done(self, message: tuple) -> None:
        cancelled = getattr(self, "_batch_cancel", False)
        self._batch_running = False
        self._batch_cancel = False
        self.status_var.set("准备就绪")
        self.batch_btn.configure(text="一键红绿灯")
        self._set_people_controls_enabled(True)
        self.remark_btn.state(["!disabled"])
        self.refresh_people_btn.state(["!disabled"])
        self.include_follows_check.configure(
            state="normal" if self.settings.get("follow_enhance") and self._risk_enabled() else "disabled"
        )
        done = getattr(self, "_batch_done", 0)
        total = getattr(self, "_batch_total", 0)
        if cancelled and done < total:
            self._batch_pending = list(self._batch_plan[done:])
            resume_text = f"继续未完成（{done}/{total}）"
            self.resume_batch_btn.configure(
                state="normal", text=resume_text, width=max(12, len(resume_text) + 8)
            )
            self.resume_batch_btn.pack(side="left", padx=(6, 0), after=self.batch_btn)
        else:
            self._batch_pending = []
            self.resume_batch_btn.configure(state="disabled", text="继续未完成")
            self.resume_batch_btn.pack_forget()
        summary = f"已刷新 {done}/{total} 人的红绿灯"
        if getattr(self, "_batch_skip", 0):
            summary += f" · 跳过 {self._batch_skip}（缺少身份/昵称不唯一）"
        if getattr(self, "_batch_fail", 0):
            summary += f" · 失败 {self._batch_fail}"
        self.people_hint.configure(text=summary)
        self._append_log(
            ("已停止" if cancelled else "完成") + f"一键红绿灯：刷新 {done} 人。",
            "muted" if cancelled else "ok",
        )
        self._refresh_cache_stats_if_visible()


    def _handle_message_profile_ready(self, message: tuple) -> None:
        _, key, user, profile = message
        profile["_ui_cached_at"] = time.time()
        self._profile_cache[key] = profile
        selection = self.people_tree.selection()
        if selection:
            try:
                current = self.people_users[int(selection[0])]
            except (IndexError, ValueError):
                current = None
            if current and (current["uid"] or f"name:{current['name']}") == key:
                self._render_profile(user, profile)
        self._refresh_cache_stats_if_visible()


    def _handle_message_enrich_done(self, message: tuple) -> None:
        self._enriching = False
        self._refresh_people()
        self.people_hint.configure(text="等级已补全，Excel 已更新")
        self._append_log("等级补全完成，Excel 已重新导出。", "ok")


    def _handle_message_enrich_error(self, message: tuple) -> None:
        self._enriching = False
        self.people_hint.configure(text="补全失败")
        self._append_log(f"补全等级失败：{message[1]}", "err")


    def _handle_message_identity_ask(self, message: tuple) -> None:
        _, missing_uid, missing_tieba = message
        strategy, remember = self._ask_identity_strategy(missing_uid, missing_tieba)
        if remember:
            label = {
                "full": "补全用户ID + 贴吧ID",
                "skip": "跳过补全",
                "user_id": "只补用户ID",
                "detail": "详情再补",
            }.get(strategy, "每次询问")
            self.identity_strategy_var.set(label)
            self._save_identity_strategy()
        self._identity_choice_queue.put((strategy, remember))


    def _handle_message_identity_supplement_progress(self, message: tuple) -> None:
        _, done, total = message
        self.people_hint.configure(text=f"正在补全身份 {done}/{total}…")
        if done % 10 == 0:
            self._refresh_supplement_rows()


    def _handle_message_identity_supplement_done(self, message: tuple) -> None:
        _, done_strategy, manual_timings = message
        self._set_supplement_running(False)
        self._refresh_people()
        self._refresh_grid()
        timing_enabled = bool(self.identity_timing_var.get())
        seconds = float(manual_timings.get("总耗时") or 0) if timing_enabled else 0.0
        self.people_hint.configure(
            text=(
                f"身份补全完成 · 本次 {seconds:.1f} 秒 · 需要重新导出"
                if timing_enabled
                else "身份补全完成 · 需要重新导出"
            )
        )
        messagebox.showinfo(
            "身份已更新",
            (
                f"身份补全完成，本次耗时 {seconds:.1f} 秒。\n"
                if timing_enabled
                else "身份补全完成。\n"
            )
            + "请重新导出 Excel 以包含新的贴吧ID。",
            parent=self.root,
        )


    def _handle_message_incomplete_retry_done(self, message: tuple) -> None:
        self._set_supplement_running(False)
        self._refresh_people()
        self._refresh_grid()
        self.people_hint.configure(text="失败部分重试完成，需要重新导出")
        messagebox.showinfo(
            "重试完成",
            "失败页/失败楼中楼已重试。请重新导出 Excel。",
            parent=self.root,
        )


    def _handle_message_incomplete_retry_stopped(self, message: tuple) -> None:
        self._set_supplement_running(False)
        self._refresh_people()
        self.people_hint.configure(text="重试已停止，已完成部分已保留")


    def _handle_message_incomplete_retry_error(self, message: tuple) -> None:
        self._set_supplement_running(False)
        self._refresh_people()
        self.people_hint.configure(
            text=f"重试失败：{friendly_error(RuntimeError(message[1]))}"
        )


    def _handle_message_identity_supplement_stopped(self, message: tuple) -> None:
        self._set_supplement_running(False)
        self._refresh_people()
        self.people_hint.configure(text="补全已停止，已完成部分已保留")


    def _handle_message_identity_supplement_error(self, message: tuple) -> None:
        self._set_supplement_running(False)
        self._refresh_people()
        self.people_hint.configure(text=f"补全失败：{friendly_error(RuntimeError(message[1]))}")


    def _handle_message_identity_remember(self, message: tuple) -> None:
        label = {
            "full": "补全用户ID + 贴吧ID",
            "skip": "跳过补全",
            "user_id": "只补用户ID",
            "detail": "详情再补",
        }.get(message[1], "每次询问")
        self.identity_strategy_var.set(label)
        self._save_identity_strategy()


    def _handle_message_levels_filled(self, message: tuple) -> None:
        self._auto_filling = False
        self._refresh_people()
        with_level = sum(1 for user in self.people_users if user.get("level"))
        self.people_hint.configure(text=f"共 {len(self.people_users)} 人 · 有等级 {with_level}")


    def _handle_message_levels_error(self, message: tuple) -> None:
        self._auto_filling = False
        self.people_hint.configure(text="等级补全失败，可点「刷新」重试")


    def _handle_message_lookup_ready(self, message: tuple) -> None:
        _, profile, error = message
        if error:
            self._set_lookup_text("查询失败：" + friendly_error(error))
            self.lookup_status.configure(text="查询失败")
        else:
            self._render_lookup(profile)


    def _handle_message_levels_ready(self, message: tuple) -> None:
        _, level_kind, profile, forums, results = message
        self._apply_level_results(level_kind, profile, forums, results)


    def _handle_message_links_ready(self, message: tuple) -> None:
        _, result, error = message
        self._render_links(result, error)


    def _handle_message_love_ready(self, message: tuple) -> None:
        _, result, error = message
        self._render_love(result, error)


    def _handle_message_cancelled(self, message: tuple) -> None:
        self._set_running(False)
        self.status_var.set("已停止")
        self._append_log("\n已停止，没有生成文件。", "err")
        self._refresh_log_summary()


    def _handle_message_manual_cookie_probe(self, message: tuple) -> None:
        _, token, warning, logged, missing = message
        if token != self._login_probe_token:
            return
        if warning:
            self.status_var.set("登录信息预检未通过")
            self._append_log(f"登录预检：{warning}", "warn")
        else:
            self.status_var.set(
                "登录信息预检通过（可能不完整）" if missing else "登录信息预检通过"
            )
            self._append_log("登录信息预检通过。", "ok")
            if missing:
                self._append_log("Cookie 可能不完整：缺少 " + "；".join(missing), "warn")
        self._refresh_log_summary()


    def _handle_message_rate_limit_ask(self, message: tuple) -> None:
        _, detail, retry_after, _url = message
        wait = int(retry_after or 30)
        self.status_var.set("被限流，等待选择")
        self._append_log(f"被限流：{detail}", "warn")
        choice = self._ask_choice(
            "被限流",
            f"服务端返回限流，建议至少等待 {wait} 秒。\n"
            "等待后只继续当前未完成帖子，已完成帖子不会重抓。",
            [
                (f"等待 {wait} 秒后继续", str(wait)),
                ("暂停 2 分钟", "120"),
                ("暂停 5 分钟", "300"),
                ("停止本次", "stop"),
            ],
            default=0,
        )
        self._rate_choice_queue.put(choice or "stop")


    def _handle_message_rate_limit(self, message: tuple) -> None:
        _, detail, retry_after = message
        self._set_running(False)
        self.status_var.set("被限流")
        self._append_log("抓取失败：" + detail, "warn")
        wait = int(retry_after or 30)
        choice = self._ask_choice(
            "被限流",
            f"服务端返回限流，建议至少等待 {wait} 秒。\n"
            "等待后可重新开始；已完成的数据不会丢失。",
            [
                (f"等待 {wait} 秒后重试", "wait"),
                ("暂停 2 分钟", "120"),
                ("暂停 5 分钟", "300"),
                ("停止本次", "stop"),
            ],
            default=0,
        )
        if choice in ("wait", "120", "300"):
            seconds = wait if choice == "wait" else int(choice)
            pause_requests(seconds)
            self._append_log(f"已设置请求暂停 {seconds} 秒。", "muted")
            self.root.after(
                int(seconds * 1000),
                lambda: self.status_var.set("暂停结束，可以重新开始"),
            )
        self._refresh_log_summary()


    def _handle_message_error(self, message: tuple) -> None:
        _, detail = message
        self._set_running(False)
        self.status_var.set("出错了")
        self._append_log(f"\n✗ {detail}", "err")
        self._refresh_log_summary()
        messagebox.showerror("出错了", detail.split("\n\n")[0], parent=self.root)

