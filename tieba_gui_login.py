"""登录 / Cookie / WebView2 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional

from tieba_reply_stats import webview2
from tieba_reply_stats.cookie_store import clear_cookie, save_cookie
from tieba_reply_stats.fetch import CaptchaError, Fetcher, parse_cookie_input
from tieba_reply_stats.settings import save_settings

BDUSS_HELP = """只填 BDUSS 时，这样复制：

1. 用 Chrome 或 Edge 打开贴吧页面，确认已登录。
2. 按 F12，打开开发者工具。
3. 点「应用 / Application」→「存储 / Storage」→「Cookie / Cookies」→ https://tieba.baidu.com
4. 在列表里找到名为 BDUSS 的一项，复制它的「值 / Value」。
5. 粘贴到本窗口的 BDUSS 输入框，点「应用」。
6. 勾选「记住 BDUSS」后，下次打开自动填入。

只复制 BDUSS 的值，不要复制整行 Cookie。
BDUSS 等同于登录凭证，只在自己的电脑上使用，不要发给别人。
"""


COOKIE_HELP = """需要 Cookie 时，这样复制：

1. 用 Chrome 或 Edge 打开目标帖子，确认能正常看到楼层。
2. 按键盘上的 F12，打开开发者工具。
3. 点顶部的「网络 / Network」标签，然后按 F5 刷新页面。
4. 在左侧列表里点第一个以帖子数字开头的请求（类型是 document）。
5. 在右侧找到「标头 / Headers」→「请求标头 / Request Headers」，
   里面有一行 Cookie:，把它冒号后面的整段内容复制下来。
6. 粘贴到本窗口的「完整 Cookie」输入框（也可以复制后点「从剪贴板粘贴」），
   然后点「开始统计」。
7. 需要下次自动填入时，勾选「记住完整 Cookie」再点「应用」。

为什么不能全自动读取？
浏览器从 2024 年起对 Cookie 做了「应用绑定加密」，只有浏览器自己能解密，
而且还锁着 Cookie 文件，其他程序读不了。所以需要你手动复制一次，
之后由本程序用 Windows 账户加密保存在本机，下次自动使用。

提示：
- Cookie 相当于账号凭证，只在自己的电脑上使用，不要发给别人。
- Cookie 一般能用几个月；如果提示验证失败，就重新复制一次。
- 如果 Cookie 也一直提示验证失败，可以换个网络（比如手机热点）再试。
"""


class LoginMixin:
    """登录 / Cookie / WebView2 相关方法，从 App 拆出。"""

    _login_probe_token: Any
    _guest_cookie: Any
    _last_webview_match: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _on_login_method_changed(self) -> None:
        method = self.login_method_var.get()
        if hasattr(self, "_refresh_webview_status"):
            self._refresh_webview_status()
        if not getattr(self, "_login_fields_expanded", True):
            return
        if method == "cookie":
            self.bduss_frame.grid_remove()
            self.cookie_frame.grid()
        else:
            self.cookie_frame.grid_remove()
            self.bduss_frame.grid()


    def _extract_bduss(self, raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""
        cookies = parse_cookie_input(text)
        if cookies.get("BDUSS"):
            return str(cookies["BDUSS"]).strip()
        if text.upper().startswith("BDUSS="):
            return text.split("=", 1)[1].strip()
        if ";" not in text and " " not in text:
            return text
        return ""


    def _paste_bduss(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return
        value = self._extract_bduss(text)
        if not value:
            messagebox.showwarning("不是 BDUSS", "剪贴板里没有识别到 BDUSS。", parent=self.root)
            return
        self.login_method_var.set("bduss")
        self.bduss_var.set(value)
        self._apply_bduss()


    def _apply_bduss(self) -> None:
        value = self._extract_bduss(self.bduss_var.get())
        if not value:
            messagebox.showwarning("需要 BDUSS", "请填写 BDUSS。", parent=self.root)
            self.bduss_entry.focus_set()
            return
        self.bduss_var.set(value)
        self.cookie_var.set(f"BDUSS={value}")
        self._full_cookie_cache = ""
        self._login_source = "手动粘贴"
        self._last_webview_match = None
        self._login_probe_token += 1
        if self.remember_bduss_var.get():
            if save_cookie(self.cookie_var.get()):
                self.status_var.set("BDUSS 已加密保存")
            else:
                self.status_var.set("BDUSS 保存失败，本次仍可使用")
        else:
            clear_cookie()
            self.status_var.set("BDUSS 仅本次使用")
        self._refresh_webview_status()
        self._append_log("登录方式：仅 BDUSS", "muted")


    def _cookie_completeness(self, cookies: Dict[str, str]) -> List[str]:
        missing: List[str] = []
        if not str(cookies.get("STOKEN") or "").strip():
            missing.append("STOKEN（关注检测可能不完整）")
        if not str(cookies.get("TIEBAUID") or "").strip() and not str(
            cookies.get("TIEBA_SID") or ""
        ).strip():
            missing.append("TIEBAUID/TIEBA_SID（贴吧身份字段可能缺失）")
        if not str(cookies.get("BAIDUID") or "").strip():
            missing.append("BAIDUID（匿名标识缺失）")
        return missing


    def _start_cookie_probe(self, cookies: Dict[str, str], token: int) -> None:
        if self._network_task_active():
            return
        self.status_var.set("正在预检登录信息…")
        missing = self._cookie_completeness(cookies)

        def worker() -> None:
            warning = ""
            logged = False
            try:
                probe = Fetcher(cookie=cookies, delay=0, verbose=False)
            except Exception as error:  # noqa: BLE001
                self._post(("manual_cookie_probe", token, f"预检初始化失败：{error}", False, missing))
                return
            try:
                probe.get("https://tieba.baidu.com/")
                info = probe.get("https://tieba.baidu.com/f/user/json_userinfo")
                try:
                    payload = json.loads(info.text)
                except (TypeError, ValueError):
                    warning = "预检返回无法解析，未能确认登录态"
                else:
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if not isinstance(data, dict):
                        data = payload if isinstance(payload, dict) else {}
                    logged = bool(
                        data.get("user_id")
                        or data.get("user_name")
                        or data.get("name")
                    )
                    if not logged:
                        warning = "预检未确认登录态，Cookie 可能已失效或只有 BDUSS"
            except CaptchaError:
                warning = "预检仍被验证码拦截，Cookie 可能不可用"
            except Exception as error:  # noqa: BLE001
                warning = f"预检失败：{error}"
            finally:
                probe.close()
            self._post(("manual_cookie_probe", token, warning, logged, missing))

        threading.Thread(target=worker, daemon=True).start()


    def _apply_cookie(self) -> None:
        raw = self.cookie_var.get().strip()
        if not raw:
            messagebox.showwarning("需要 Cookie", "请粘贴完整 Cookie。", parent=self.root)
            self.cookie_entry.focus_set()
            return
        if not webview2.has_login_cookie(parse_cookie_input(raw)):
            messagebox.showwarning(
                "Cookie 不完整",
                "完整 Cookie 里没有 BDUSS/TIEBA_SID，无法确认登录态。",
                parent=self.root,
            )
            return
        self._full_cookie_cache = raw
        self._login_source = "手动粘贴"
        self._last_webview_match = None
        self.login_method_var.set("cookie")
        self._on_login_method_changed()
        if self.remember_cookie_var.get():
            if save_cookie(raw):
                self.status_var.set("完整 Cookie 已加密保存")
            else:
                self.status_var.set("完整 Cookie 保存失败，本次仍可使用")
        else:
            clear_cookie()
            self.status_var.set("完整 Cookie 仅本次使用")
        self._refresh_webview_status()
        self._append_log("登录方式：完整 Cookie", "muted")
        self._login_probe_token += 1
        self._start_cookie_probe(parse_cookie_input(raw), self._login_probe_token)


    def _remember_current_login(self) -> bool:
        if self.login_method_var.get() == "bduss":
            return bool(self.remember_bduss_var.get())
        return bool(self.remember_cookie_var.get())


    def _current_cookie_text(self) -> str:
        if self.login_method_var.get() == "bduss":
            value = self._extract_bduss(self.bduss_var.get())
            return f"BDUSS={value}" if value else ""
        return self.cookie_var.get().strip()


    def _sync_bduss_from_cookie(self, *_args) -> None:
        """完整 Cookie 变化时，同步提取 BDUSS，便于切换到仅 BDUSS。"""
        raw = self.cookie_var.get().strip()
        if not raw:
            return
        cookies = parse_cookie_input(raw)
        value = cookies.get("BDUSS", "")
        if value and set(cookies) != {"BDUSS"}:
            self._full_cookie_cache = raw
        if value and self.bduss_var.get() != value:
            self.bduss_var.set(value)


    def _sync_login_from_cookie(self) -> None:
        raw = self.cookie_var.get().strip()
        if not raw:
            return
        cookies = parse_cookie_input(raw)
        if cookies.get("BDUSS") and set(cookies) == {"BDUSS"}:
            self.login_method_var.set("bduss")
            self.bduss_var.set(str(cookies["BDUSS"]))
            self.remember_bduss_var.set(True)
        else:
            self.login_method_var.set("cookie")
            self.remember_cookie_var.set(True)
            self._full_cookie_cache = raw


    def _clear_cookie(self) -> None:
        self.cookie_var.set("")
        self.bduss_var.set("")
        self._full_cookie_cache = ""
        self._login_source = ""
        self._last_webview_match = None
        self._login_probe_token += 1
        if clear_cookie():
            self._append_log("已清除本机保存的 Cookie。", "muted")
        else:
            self._append_log("已清空输入框（没有可删除的已保存 Cookie）。", "muted")


    def _paste_cookie(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(
                "剪贴板是空的",
                "先在浏览器里复制 Cookie，再点这个按钮。\n\n"
                "复制方法：F12 → 网络/Network → 刷新 → 点第一个帖子请求 → "
                "标头/Headers → 请求标头里的 Cookie，复制冒号后面的整段。",
                parent=self.root,
            )
            return
        text = text.strip()
        if text.lower().startswith("cookie:"):
            text = text.split(":", 1)[1].strip()
        # 只保留有效的 k=v 片段
        keep = [part.strip() for part in re.split(r"[;\n\r]+", text) if "=" in part]
        if not keep:
            messagebox.showwarning(
                "剪贴板内容不像 Cookie", "剪贴板里没有找到 k=v 形式的 Cookie，请重新复制。", parent=self.root
            )
            return
        self.cookie_var.set("; ".join(keep))
        self._append_log("已从剪贴板粘贴 Cookie。", "ok")


    def _show_bduss_help(self) -> None:
        messagebox.showinfo("如何获取 BDUSS", BDUSS_HELP, parent=self.root)
        self.bduss_entry.focus_set()


    def _clear_bduss(self) -> None:
        self.bduss_var.set("")
        if self.login_method_var.get() == "bduss":
            self.cookie_var.set("")
        clear_cookie()
        self.status_var.set("已清除 BDUSS")
        self._append_log("已清除 BDUSS。", "muted")


    def _show_cookie_help(self) -> None:
        messagebox.showinfo("如何获取完整 Cookie", COOKIE_HELP, parent=self.root)
        self.cookie_entry.focus_set()


    def _login_result_text(self, action: str) -> str:
        if getattr(self, "last_threads", None):
            return f"{action}。重新开始统计时，已完成的帖子不会重抓。"
        return f"{action}。请回到抓取页，粘贴帖子链接后点「开始统计」。"


    def _ask_go_fill_bduss(self) -> bool:
        win = tk.Toplevel(self.root)
        win.title("需要 BDUSS")
        win.configure(bg="#eef1f5")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        result = {"go": False}
        tk.Label(
            win,
            text="关注检测已开启，但还没有完成登录。现在去抓取页填写吗？",
            bg="#eef1f5",
            fg="#334155",
            font=("Microsoft YaHei UI", 9),
            justify="left",
            wraplength=360,
        ).pack(fill="x", padx=14, pady=(14, 8))
        row = tk.Frame(win, bg="#eef1f5")
        row.pack(side="bottom", fill="x", padx=14, pady=(0, 12))

        def choose(go: bool) -> None:
            result["go"] = go
            win.destroy()

        ttk.Button(row, text="稍后", command=lambda: choose(False), width=9).pack(side="right")
        ttk.Button(row, text="去填写", command=lambda: choose(True), width=9).pack(
            side="right", padx=(0, 6)
        )
        win.protocol("WM_DELETE_WINDOW", lambda: choose(False))
        win.bind("<Escape>", lambda _event: choose(False))
        self._theme_widget_tree(win)
        win.update_idletasks()
        width, height = 420, max(140, win.winfo_reqheight() + 16)
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.focus_set()
        self.root.wait_window(win)
        return bool(result["go"])


    def _go_to_login(self) -> None:
        self.notebook.select(self.tab_posts)
        self.post_nb.select(self.tab_fetch)
        self.root.update_idletasks()
        target = self.bduss_entry if self.login_method_var.get() == "bduss" else self.cookie_entry
        target.focus_set()


    def _toggle_login_fields(self) -> None:
        self._set_login_fields_expanded(not getattr(self, "_login_fields_expanded", True))


    def _set_login_fields_expanded(self, expanded: bool) -> None:
        self._login_fields_expanded = bool(expanded)
        if not hasattr(self, "login_method_row"):
            return
        if self._login_fields_expanded:
            self.login_method_row.grid()
            self.login_switch_row.grid()
            if self.login_method_var.get() == "bduss":
                self.bduss_frame.grid()
                self.cookie_frame.grid_remove()
            else:
                self.cookie_frame.grid()
                self.bduss_frame.grid_remove()
            self.login_toggle_btn.configure(text="收起")
        else:
            self.login_method_row.grid_remove()
            self.bduss_frame.grid_remove()
            self.cookie_frame.grid_remove()
            self.login_switch_row.grid_remove()
            self.login_toggle_btn.configure(text="展开")


    def _refresh_webview_status(self) -> None:
        if not hasattr(self, "webview_status_var"):
            return
        is_login = self.mode_var.get() == "login"
        mode = "登录" if is_login else "游客"
        available = webview2.available()
        if not available:
            login_state = "WebView2 不可用"
        elif webview2.login_profile_exists():
            login_state = "已保存本机登录态"
        else:
            login_state = "未保存本机登录态"
        if not is_login:
            login_info = "游客匿名 Cookie"
            has_login = False
        elif self.login_method_var.get() == "bduss":
            login_info = "仅 BDUSS" if self.bduss_var.get().strip() else "未填写"
            has_login = bool(self.bduss_var.get().strip())
        else:
            has_login = webview2.has_login_cookie(
                parse_cookie_input(self.cookie_var.get())
            )
            login_info = "完整 Cookie" if has_login else "未填写"
        self.webview_status_var.set(
            f"当前模式：{mode}\n当前登录信息：{login_info}\n内置登录：{login_state}"
        )
        if hasattr(self, "login_baidu_btn"):
            use_saved = (
                is_login
                and not has_login
                and webview2.login_profile_exists()
                and bool(self.settings.get("webview_remember_login", False))
            )
            if use_saved:
                self.login_baidu_btn.configure(
                    text="使用已保存的内置登录",
                    command=self._reuse_internal_login,
                )
            else:
                self.login_baidu_btn.configure(
                    text=(
                        "登录百度并获取 BDUSS"
                        if self.login_method_var.get() == "bduss"
                        else "登录百度并获取完整 Cookie"
                    ),
                    command=self._login_baidu,
                )
        if hasattr(self, "login_summary_var"):
            if not is_login:
                summary = "游客模式 · 匿名 Cookie"
            elif login_info == "未填写":
                summary = "登录信息未填写"
            else:
                summary = f"{login_info} · 已就绪"
            self.login_summary_var.set(summary)
        if hasattr(self, "login_source_label"):
            source = str(getattr(self, "_login_source", "") or "")
            match: Optional[bool] = None
            if has_login and webview2.login_profile_exists() and source in (
                "手动粘贴",
                "已保存 Cookie",
                "内置浏览器",
            ):
                if source == "内置浏览器" and self._last_webview_match is not None:
                    match = self._last_webview_match
                else:
                    current_cookies = parse_cookie_input(self.cookie_var.get())
                    if source == "内置浏览器" and self._full_cookie_cache:
                        current_cookies = parse_cookie_input(self._full_cookie_cache)
                    match = webview2.match_profile_fingerprint(current_cookies)
            self.login_source_label.unbind("<Button-1>")
            if match is False:
                self.login_source_label.configure(
                    text=(
                        f"当前登录来源：{source} · "
                        "内置登录：可能不是同一会话（点此沿用）"
                    ),
                    fg="#b45309",
                    cursor="hand2",
                )
                self.login_source_label.bind(
                    "<Button-1>", lambda _event: self._reuse_internal_login()
                )
            elif source:
                self.login_source_label.configure(
                    text=f"当前登录来源：{source}",
                    fg="#8a94a6",
                    cursor="",
                )
            else:
                self.login_source_label.configure(text="")
        can_open = available and is_login and not self._network_task_active()
        if hasattr(self, "webview_open_btn"):
            self.webview_open_btn.configure(state="normal" if can_open else "disabled")
        if hasattr(self, "webview_clear_btn"):
            can_clear = available and not self._network_task_active()
            self.webview_clear_btn.configure(state="normal" if can_clear else "disabled")
        if hasattr(self, "follow_enhance_check"):
            self.follow_enhance_check.configure(
                state="normal" if has_login and not self._network_task_active() else "disabled"
            )
        if hasattr(self, "follow_load_box"):
            self.follow_load_box.configure(
                state="readonly" if has_login and self.follow_enhance_var.get() else "disabled"
            )
        if hasattr(self, "follow_enhance_status"):
            self.follow_enhance_status.configure(
                text=(
                    "已具备登录信息"
                    if has_login
                    else "需要登录信息：先点「登录百度」或「手动填写」"
                )
            )
        if not has_login and getattr(self, "follow_enhance_var", None) is not None:
            if self.follow_enhance_var.get():
                self.follow_enhance_var.set(False)
                self.settings["follow_enhance"] = False
                save_settings(self.settings)


    def _on_webview_remember_changed(self) -> None:
        enabled = bool(self.webview_remember_var.get())
        if not enabled and webview2.login_profile_exists():
            if messagebox.askyesno(
                "关闭记住内置登录",
                "关闭后不会自动复用已保存的登录态。\n是否现在一并清除 WebView2 登录？",
                parent=self.root,
                default=messagebox.NO,
            ):
                if not webview2.clear_login_profile():
                    messagebox.showwarning(
                        "暂未清除",
                        "WebView2 登录目录可能正在使用，请稍后手动清除。",
                        parent=self.root,
                    )
                    enabled = True
                    self.webview_remember_var.set(True)
            else:
                enabled = True
                self.webview_remember_var.set(True)
        self.settings["webview_remember_login"] = enabled
        save_settings(self.settings)
        self._refresh_webview_status()


    def _go_manage_login(self) -> None:
        if self.mode_var.get() != "login":
            self._set_mode("login")
        self.notebook.select(self.tab_posts)
        self.post_nb.select(self.tab_fetch)
        self._set_login_fields_expanded(True)
        self.root.update_idletasks()
        target = self.bduss_entry if self.login_method_var.get() == "bduss" else self.cookie_entry
        target.focus_set()


    def _login_baidu(self) -> None:
        if not webview2.available():
            messagebox.showwarning(
                "WebView2 不可用",
                "未检测到 WebView2 Runtime，请使用「手动填写」。",
                parent=self.root,
            )
            return
        if self.mode_var.get() != "login":
            self._set_mode("login")
        self._set_login_fields_expanded(True)
        target = "bduss" if self.login_method_var.get() == "bduss" else "cookie"
        self._auto_get_login(
            target,
            url="https://passport.baidu.com/v2/?login",
        )


    def _save_login_fingerprint(self, cookies: dict, force: bool = False) -> None:
        if not webview2.login_profile_exists():
            return
        if not force and not bool(self.settings.get("webview_remember_login", False)):
            return
        if not webview2.save_profile_fingerprint(cookies):
            self._append_log("登录来源指纹保存失败，下次可能无法判断是否同一会话。", "warn")


    def _adopt_webview_login(self, cookies: dict, target: str) -> None:
        full = "; ".join(f"{key}={value}" for key, value in cookies.items())
        if target == "bduss" and cookies.get("BDUSS"):
            self._full_cookie_cache = ""
            self.login_method_var.set("bduss")
            self.bduss_var.set(str(cookies.get("BDUSS") or ""))
            self.cookie_var.set(f"BDUSS={cookies.get('BDUSS') or ''}")
        else:
            self._full_cookie_cache = full
            self.login_method_var.set("cookie")
            self.cookie_var.set(full)
            self._webview_cookie_session = True
        self._login_source = "内置浏览器"
        self._login_probe_token += 1
        self._on_login_method_changed()
        self._set_login_fields_expanded(False)
        if hasattr(self, "_refresh_webview_status"):
            self._refresh_webview_status()


    def _switch_baidu_account(self) -> None:
        if not webview2.available():
            messagebox.showwarning(
                "WebView2 不可用",
                "未检测到 WebView2 Runtime，无法切换百度账号。",
                parent=self.root,
            )
            return
        if self._network_task_active() or getattr(self, "_webview_running", False):
            messagebox.showinfo("请稍后", "当前有任务或内置窗口正在运行。", parent=self.root)
            return
        if not messagebox.askyesno(
            "切换百度账号",
            "将打开一个临时干净的内置窗口登录新账号。\n"
            "新账号成功登录前，旧登录和旧内置会话都会保留。\n\n继续？",
            parent=self.root,
            default=messagebox.NO,
        ):
            return
        temp_profile = webview2.prepare_switch_profile()
        self._webview_running = True
        self.status_var.set("正在打开切换账号窗口…")
        center = self._webview_center()

        def worker():
            try:
                result = webview2.open_verification(
                    "https://passport.baidu.com/v2/?login",
                    center=center,
                    persistent=True,
                    require_login=True,
                    profile_dir=temp_profile,
                )
                raw = result.get("cookies") if isinstance(result, dict) else result
                cookies = webview2.filter_cookies(raw, anonymous=False)
                if not webview2.has_login_cookie(cookies):
                    raise RuntimeError("没有读取到登录 Cookie（BDUSS/TIEBA_SID），可能尚未登录")
                self._post(("switch_login_done", cookies, "", ""))
            except Exception as error:  # noqa: BLE001
                self._post(("switch_login_done", {}, str(error), ""))

        threading.Thread(target=worker, daemon=True).start()


    def _reuse_internal_login(self) -> None:
        if self.mode_var.get() != "login":
            self._set_mode("login")
        target = "bduss" if self.login_method_var.get() == "bduss" else "cookie"
        url = (getattr(self, "_current_urls", []) or ["https://tieba.baidu.com/"])[0]
        self._auto_get_login(target, url=url)


    def _manual_fill_login(self) -> None:
        self._set_mode("login")
        self.login_method_var.set("cookie")
        self._set_login_fields_expanded(True)
        self._on_login_method_changed()
        try:
            self.notebook.select(self.tab_posts)
            self.post_nb.select(self.tab_fetch if hasattr(self, "tab_fetch") else 0)
        except tk.TclError:
            pass
        self.cookie_entry.focus_set()
        self._append_log("请手动粘贴完整 Cookie，然后点「应用」。", "muted")


    def _open_internal_login(self) -> None:
        if self.mode_var.get() != "login":
            messagebox.showinfo(
                "仅登录模式可用",
                "请先在抓取页切换到登录模式，或从游客验证码选择改用登录。",
                parent=self.root,
            )
            return
        if not webview2.available():
            messagebox.showwarning(
                "WebView2 不可用",
                "未检测到 WebView2 Runtime，请改用手动完整 Cookie。",
                parent=self.root,
            )
            return
        entry = self._ask_choice(
            "打开内置登录",
            "只开放以下百度入口，不提供任意网址。",
            [
                ("百度登录", "login"),
                ("当前帖子验证页", "thread"),
                ("贴吧首页", "home"),
                ("取消", "cancel"),
            ],
            default=0,
        )
        if not entry or entry == "cancel":
            return
        if entry == "login":
            target_url = "https://passport.baidu.com/v2/?login"
        elif entry == "home":
            target_url = "https://tieba.baidu.com/"
        else:
            target_url = (getattr(self, "_current_urls", []) or ["https://tieba.baidu.com/"])[0]
        self._start_webview_cookie_flow(anonymous=False, url=target_url)


    def _auto_get_login(self, target: str, url: str = "") -> None:
        if self.mode_var.get() != "login":
            messagebox.showinfo("仅登录模式可用", "请先切换到登录模式。", parent=self.root)
            return
        if not webview2.available():
            messagebox.showwarning(
                "WebView2 不可用",
                "未检测到 WebView2 Runtime，请手动粘贴 BDUSS 或完整 Cookie。",
                parent=self.root,
            )
            return
        if self._network_task_active() or getattr(self, "_webview_running", False):
            messagebox.showinfo("请稍后", "当前有任务或内置窗口正在运行。", parent=self.root)
            return
        if not messagebox.askyesno(
            "自动获取登录信息",
            "将打开内置百度登录窗口。\n"
            "登录完成后读取完整 Cookie"
            + ("，只提取 BDUSS。" if target == "bduss" else "。")
            + "\nCookie 默认只在内存；开启“记住内置登录”时 WebView2 会话会保留在本机。\n\n继续？",
            parent=self.root,
            default=messagebox.NO,
        ):
            return
        target_url = url or (getattr(self, "_current_urls", []) or ["https://tieba.baidu.com/"])[0]
        if not webview2.is_allowed_url(target_url):
            target_url = "https://tieba.baidu.com/"
        self._webview_running = True
        self.status_var.set("正在打开内置登录…")
        url = target_url
        center = self._webview_center()
        persistent = bool(self.settings.get("webview_remember_login", False))
        target_value = target

        def worker():
            try:
                result = webview2.open_verification(
                    url,
                    center=center,
                    persistent=persistent,
                    require_login=True,
                )
                raw = result.get("cookies") if isinstance(result, dict) else result
                cookies = webview2.filter_cookies(raw, anonymous=False)
                if not webview2.has_login_cookie(cookies):
                    raise RuntimeError("没有读取到登录 Cookie（BDUSS/TIEBA_SID），可能尚未登录")
                effective_target = (
                    "cookie"
                    if target_value == "bduss" and not cookies.get("BDUSS")
                    else target_value
                )
                warning = ""
                probe = Fetcher(cookie=cookies, delay=0, verbose=False)
                try:
                    probe.get("https://tieba.baidu.com/")
                except CaptchaError:
                    warning = "预检仍被验证码拦截，Cookie 可能不可用"
                except Exception as error:  # noqa: BLE001
                    warning = f"预检失败：{error}"
                finally:
                    probe.close()
                self._post(
                    ("auto_login_done", effective_target, cookies, "", warning)
                )
            except Exception as error:  # noqa: BLE001
                self._post(("auto_login_done", target_value, {}, str(error), ""))

        threading.Thread(target=worker, daemon=True).start()


    def _clear_internal_login(self) -> None:
        if self._network_task_active() or getattr(self, "_webview_running", False):
            messagebox.showinfo("请稍后", "抓取、补全或内置窗口进行中，暂时不能清除内置登录。", parent=self.root)
            return
        choice = self._ask_choice(
            "清除 WebView2 保存的登录",
            "只清除内置 WebView2 的百度登录态。\n"
            "当前 Cookie 输入框和缓存是否一并清除，请选择。",
            [
                ("只清除 WebView2 登录态", "webview"),
                ("同时清除当前登录信息", "all"),
                ("取消", "cancel"),
            ],
            default=0,
        )
        if not choice or choice == "cancel":
            return
        if not webview2.clear_login_profile():
            messagebox.showerror(
                "清除失败",
                "WebView2 登录目录可能正在使用。请关闭内置窗口和本软件后重试。",
                parent=self.root,
            )
            return
        if choice == "all":
            self._clear_cookie()
            self._guest_cookie = {}
            self.cookie_var.set("")
            self.bduss_var.set("")
            self._full_cookie_cache = ""
        self._append_log("已清除 WebView2 保存的登录。", "ok")
        self._refresh_webview_status()


    def _webview_center(self) -> tuple[int, int]:
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx() + self.root.winfo_width() // 2 - 490
            y = self.root.winfo_rooty() + self.root.winfo_height() // 2 - 380
            return max(0, x), max(0, y)
        except tk.TclError:
            return 0, 0


    def _start_webview_cookie_flow(self, anonymous: bool, url: str = "") -> None:
        scope = (
            "只读取匿名 Cookie，不读取 BDUSS/STOKEN"
            if anonymous
            else "读取完整 Cookie，可能包含 BDUSS/STOKEN"
        )
        storage = (
            "Cookie 只在内存中使用，不写日志、不导出。"
            if anonymous
            else "Cookie 默认只在内存中使用；若开启“记住内置登录”，"
            "WebView2 登录态会写入本机独立目录。"
        )
        if not messagebox.askyesno(
            "读取验证 Cookie？",
            "内置验证完成后，软件将" + scope + "。\n"
            + storage
            + "\n\n继续？",
            parent=self.root,
            default=messagebox.NO,
        ):
            self._append_log("用户取消读取验证 Cookie。", "muted")
            return
        target_url = url or (getattr(self, "_current_urls", []) or ["https://tieba.baidu.com/"])[0]
        if not webview2.is_allowed_url(target_url):
            messagebox.showwarning(
                "地址不允许",
                "内置窗口只允许百度贴吧登录/验证页面。",
                parent=self.root,
            )
            return
        self._webview_running = True
        self.status_var.set("正在打开内置验证窗口…")
        center = self._webview_center()

        def worker():
            try:
                result = webview2.open_verification(
                    target_url,
                    center=center,
                    persistent=(not anonymous)
                    and bool(self.settings.get("webview_remember_login", False)),
                    require_login=not anonymous,
                )
                raw_cookies = result.get("cookies") if isinstance(result, dict) else result
                cookies = webview2.filter_cookies(raw_cookies, anonymous=anonymous)
                if not cookies:
                    raise RuntimeError("没有读取到可用 Cookie")
                warning = ""
                if not anonymous:
                    probe = Fetcher(cookie=cookies, delay=0, verbose=False)
                    try:
                        probe.get("https://tieba.baidu.com/")
                    except CaptchaError:
                        warning = "预检仍被验证码拦截，Cookie 可能不可用"
                    except Exception as error:  # noqa: BLE001
                        warning = f"预检失败：{error}"
                    finally:
                        probe.close()
                self._post(("embedded_done", cookies, "", warning))
            except Exception as error:  # noqa: BLE001
                self._post(("embedded_done", {}, str(error), ""))

        threading.Thread(target=worker, daemon=True).start()


    def _request_cookie(self) -> dict:
        if self.mode_var.get() == "guest":
            return dict(getattr(self, "_guest_cookie", {}) or {})
        return parse_cookie_input(self._current_cookie_text())

