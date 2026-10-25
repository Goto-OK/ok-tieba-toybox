"""日志/测试中心/使用说明/数据清理 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any, List

from tieba_gui_utils import resource_dir
from tieba_reply_stats import webview2
from tieba_reply_stats.blacklist import save_blacklist
from tieba_reply_stats.cookie_store import clear_cookie
from tieba_reply_stats.post_cache import cache as post_cache
from tieba_reply_stats.profile import clear_post_cache
from tieba_reply_stats.safe_delete import remove_file as safe_remove_file
from tieba_reply_stats.safe_delete import remove_tree as safe_remove_tree
from tieba_reply_stats.settings import APP_DIR, SETTINGS_PATH, load_settings, save_settings
from tieba_reply_stats.storage import clear as clear_stored_result
from tieba_reply_stats.storage import old_files as stored_old_files
from tieba_reply_stats.version import __version__ as VERSION


class ToolsMixin:
    """日志/测试中心/使用说明/数据清理方法，从 App 拆出。"""

    _full_cookie_cache: Any
    blacklist: Any
    last_threads: Any
    last_output: Any
    last_outputs: Any
    _last_lookup_profile: Any
    _login_source: Any
    _profile_data: Any
    _profile_user: Any
    _webview_cookie_session: Any
    _usage_window: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _logs_dir(self) -> str:
        return os.path.join(APP_DIR, "logs")


    def _log_files(self) -> List[str]:
        folder = self._logs_dir()
        if not os.path.isdir(folder):
            return []
        paths = [
            os.path.join(folder, name)
            for name in os.listdir(folder)
            if name.startswith("app-") and name.endswith(".log")
        ]
        paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        return paths


    def _refresh_log_summary(self) -> None:
        label = getattr(self, "log_summary_label", None)
        if label is None:
            return
        files = self._log_files()
        total = 0
        for path in files:
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
        if not files:
            label.configure(text="日志：暂无")
        else:
            label.configure(text=f"日志：{len(files)} 个 / {total / 1024:.1f} KB")


    def _open_logs_dir(self) -> None:
        folder = self._logs_dir()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as error:
            messagebox.showerror("打开失败", str(error), parent=self.root)
            return
        self._open_folder(folder)


    def _delete_logs(self) -> None:
        files = self._log_files()
        if not files:
            messagebox.showinfo("没有日志", "当前没有可删除的日志。", parent=self.root)
            return
        if not messagebox.askyesno(
            "删除日志",
            f"删除全部 {len(files)} 个日志文件？\n不会改变“保存运行日志”开关。",
            parent=self.root,
            default=messagebox.NO,
        ):
            return
        deleted = 0
        for path in files:
            try:
                os.remove(path)
                deleted += 1
            except OSError:
                continue
        self._refresh_log_summary()
        self._append_log(f"已删除日志：{deleted} 个", "muted")


    def _view_logs(self) -> None:
        files = self._log_files()
        if not files:
            messagebox.showinfo(
                "没有日志", "还没有日志。先开启“保存运行日志”并运行一次抓取。", parent=self.root
            )
            return
        win = tk.Toplevel(self.root)
        win.title("运行日志")
        win.transient(self.root)
        win.geometry("820x560")
        win.minsize(620, 400)
        win.configure(bg="#eef1f5")
        body = tk.Frame(win, bg="#eef1f5", padx=10, pady=10)
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg="#eef1f5", width=210)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        tk.Label(left, text="日志文件", bg="#eef1f5", fg="#475569", anchor="w").pack(fill="x")
        listbox = tk.Listbox(left, exportselection=False, activestyle="none")
        listbox.pack(fill="both", expand=True, pady=(4, 0))

        right = tk.Frame(body, bg="#eef1f5")
        right.pack(side="left", fill="both", expand=True)
        text = tk.Text(right, wrap="none", state="disabled", bg="#ffffff", fg="#111827")
        y_scroll = ttk.Scrollbar(right, orient="vertical", command=text.yview)
        x_scroll = ttk.Scrollbar(right, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        footer = tk.Frame(win, bg="#eef1f5", padx=10)
        footer.pack(fill="x", pady=(0, 10))

        def selected_path() -> str:
            selection = listbox.curselection()
            return files[int(selection[0])] if selection else ""

        def show_file(path: str) -> None:
            if not path:
                return
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    content = handle.read(512 * 1024)
            except OSError as error:
                content = f"读取失败：{error}"
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("end", content)
            text.configure(state="disabled")

        def on_select(_event=None) -> None:
            show_file(selected_path())

        def delete_current() -> None:
            path = selected_path()
            if not path:
                return
            if not messagebox.askyesno(
                "删除当前日志",
                f"删除 {os.path.basename(path)}？",
                parent=win,
                default=messagebox.NO,
            ):
                return
            try:
                os.remove(path)
            except OSError as error:
                messagebox.showerror("删除失败", str(error), parent=win)
                return
            self._refresh_log_summary()
            reload_list()

        def reload_list() -> None:
            listbox.delete(0, "end")
            current_files = self._log_files()
            files[:] = current_files
            for path in files:
                listbox.insert("end", os.path.basename(path))
            if files:
                listbox.selection_set(0)
                show_file(files[0])
            else:
                text.configure(state="normal")
                text.delete("1.0", "end")
                text.insert("end", "没有日志。")
                text.configure(state="disabled")

        for path in files:
            listbox.insert("end", os.path.basename(path))
        listbox.selection_set(0)
        show_file(files[0])
        listbox.bind("<<ListboxSelect>>", on_select)

        ttk.Button(footer, text="打开日志目录", command=self._open_logs_dir, width=12).pack(side="left")
        ttk.Button(footer, text="删除当前日志", command=delete_current, width=12).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(footer, text="关闭", command=win.destroy, width=8).pack(side="right")
        self._center_toplevel(win, 820, 560)
        try:
            self._theme_widget_tree(win)
        except Exception:  # noqa: BLE001
            pass


    def _on_log_toggle(self) -> None:
        self.settings["log_enabled"] = bool(self.log_enabled_var.get())
        save_settings(self.settings)


    def _show_test_center(self, _event=None) -> None:
        if self._network_task_active() or getattr(self, "_active_choice_window", None):
            return
        win = tk.Toplevel(self.root)
        win.title("测试中心")
        win.configure(bg="#eef1f5")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        tk.Label(
            win,
            text="测试中心（不会写设置、不会覆盖结果）",
            bg="#eef1f5",
            fg="#1f2937",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(
            win,
            text="真实百度验证码无法自动触发；模拟测试不联网。",
            bg="#eef1f5",
            fg="#64748b",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=16, pady=(0, 10))

        def run(action) -> None:
            win.grab_release()
            win.destroy()
            action()

        ttk.Button(
            win,
            text="模拟游客验证码（可继续操作）",
            command=lambda: run(lambda: self._show_test_captcha_dialog("guest")),
            width=38,
        ).pack(fill="x", padx=16, pady=2)
        ttk.Button(
            win,
            text="模拟登录：完整 Cookie（可继续操作）",
            command=lambda: run(lambda: self._show_test_captcha_dialog("cookie")),
            width=38,
        ).pack(fill="x", padx=16, pady=2)
        ttk.Button(
            win,
            text="模拟登录：仅 BDUSS（可继续操作）",
            command=lambda: run(lambda: self._show_test_captcha_dialog("bduss")),
            width=38,
        ).pack(fill="x", padx=16, pady=2)
        ttk.Button(
            win,
            text="运行离线检查（PASS/FAIL）",
            command=lambda: run(self._show_offline_test_results),
            width=38,
        ).pack(fill="x", padx=16, pady=2)
        ttk.Button(
            win,
            text="测试内置验证窗口（不读取 Cookie）",
            command=lambda: run(self._test_embedded_verification),
            width=38,
        ).pack(fill="x", padx=16, pady=2)
        ttk.Button(
            win,
            text="打开内置登录（仅登录模式）",
            command=lambda: run(self._open_internal_login),
            width=38,
        ).pack(fill="x", padx=16, pady=2)
        ttk.Button(
            win,
            text="关闭",
            command=win.destroy,
            width=38,
        ).pack(fill="x", padx=16, pady=(10, 14))
        win.update_idletasks()
        width = max(420, win.winfo_reqwidth())
        height = max(240, win.winfo_reqheight())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.lift()
        win.focus_force()


    def _show_offline_test_results(self) -> None:
        results = self._offline_checks()
        win = tk.Toplevel(self.root)
        win.title("离线检查结果")
        win.configure(bg="#eef1f5")
        win.transient(self.root)
        win.grab_set()
        body = tk.Frame(win, bg="#eef1f5", padx=12, pady=10)
        body.pack(fill="both", expand=True)
        text = tk.Text(body, width=78, height=max(8, len(results) + 4), wrap="word")
        text.pack(fill="both", expand=True)
        text.insert("end", "测试项\t结果\t说明\n")
        for name, status, detail in results:
            text.insert("end", f"{name}\t{status}\t{detail}\n")
        text.configure(state="disabled")
        ttk.Button(body, text="关闭", command=win.destroy).pack(anchor="e", pady=(8, 0))
        win.update_idletasks()
        width = max(620, win.winfo_reqwidth())
        height = max(300, win.winfo_reqheight())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.lift()


    def _show_test_captcha_dialog(self, scenario: str) -> None:
        """测试模式：展示真实按钮，用假 Cookie 走后续界面，不联网。"""
        if scenario == "guest":
            message = (
                "当前是游客模式（测试）。\n"
                "真实流程会读取匿名 Cookie，不读取 BDUSS/STOKEN。"
            )
            choices = [
                ("模拟读取匿名 Cookie", "guest_embed"),
                ("改用登录模式（完整 Cookie）", "login"),
                ("停止本次", "stop"),
            ]
        elif scenario == "bduss":
            cached = bool(getattr(self, "_full_cookie_cache", ""))
            message = (
                "本次实际只发送了 BDUSS（测试）。\n"
                + ("有完整 Cookie 缓存，可改用。" if cached else "当前没有完整 Cookie 缓存。")
            )
            choices = [("模拟读取完整 Cookie", "full_embed")]
            if cached:
                choices.append(("改用已保存的完整 Cookie", "cached"))
            choices.extend([("手动粘贴完整 Cookie", "manual"), ("停止本次", "stop")])
        else:
            message = (
                "当前使用完整 Cookie（测试）。\n"
                "真实流程会读取完整 Cookie，并检查 BDUSS/TIEBA_SID。"
            )
            choices = [
                ("模拟读取完整 Cookie", "full_embed"),
                ("手动粘贴完整 Cookie", "manual"),
                ("停止本次", "stop"),
            ]
        choice = self._ask_choice("被安全验证拦截（测试模式）", message, choices)
        if not choice or choice == "stop":
            return
        if choice == "login":
            self._set_mode("login", persist=False)
            self.login_method_var.set("cookie")
            self._on_login_method_changed()
            self._append_log("测试：已切到登录模式，未写设置。", "muted")
            self.cookie_entry.focus_set()
            return
        if choice == "manual":
            self._set_mode("login", persist=False)
            self.login_method_var.set("cookie")
            self._on_login_method_changed()
            self.cookie_entry.focus_set()
            self._append_log("测试：请手动粘贴完整 Cookie。", "muted")
            return
        if choice == "cached":
            self._set_mode("login", persist=False)
            self.login_method_var.set("cookie")
            self.cookie_var.set(self._full_cookie_cache)
            self._on_login_method_changed()
            self.cookie_entry.focus_set()
            self._append_log("测试：已改用缓存的完整 Cookie。", "muted")
            return
        self._set_mode("guest" if choice == "guest_embed" else "login", persist=False)
        if choice == "guest_embed":
            self._guest_cookie = {"BAIDUID": "TEST_GUEST"}
            self._append_log("测试：已写入假匿名 Cookie，保持游客。", "muted")
            messagebox.showinfo("测试结果", "已模拟匿名 Cookie；不会联网。", parent=self.root)
            return
        fake = {"BDUSS": "TEST_BDUSS", "TIEBA_SID": "TEST_TIEBA_SID", "STOKEN": "TEST_STOKEN"}
        text = "; ".join(f"{key}={value}" for key, value in fake.items())
        self._login_source = "测试"
        self._full_cookie_cache = text
        if scenario == "bduss":
            self.login_method_var.set("bduss")
            self.bduss_var.set(fake["BDUSS"])
            self.cookie_var.set(f"BDUSS={fake['BDUSS']}")
        else:
            self.login_method_var.set("cookie")
            self.cookie_var.set(text)
            self.bduss_var.set(fake["BDUSS"])
        self._on_login_method_changed()
        self._webview_cookie_session = False
        self._append_log("测试：已写入假完整 Cookie，未联网、未写设置。", "muted")
        messagebox.showinfo(
            "测试结果",
            "已模拟完整 Cookie。\n不会预检、不会联网、不会自动开始抓取。",
            parent=self.root,
        )


    def _test_embedded_verification(self) -> None:
        if getattr(self, "_webview_running", False):
            messagebox.showinfo("正在测试", "内置验证窗口已经打开。", parent=self.root)
            return
        if not webview2.available():
            messagebox.showinfo(
                "内置验证窗口不可用",
                "未检测到 pywebview 或 WebView2 Runtime。\n"
                "仍可使用「转到登录模式（完整 Cookie）」。",
                parent=self.root,
            )
            return
        self._webview_running = True
        self.status_var.set("正在打开内置验证窗口（测试）…")
        center = self._webview_center()
        url = (getattr(self, "_current_urls", []) or ["https://tieba.baidu.com/"])[0]

        def worker():
            try:
                webview2.open_window(url, center=center)
                self._post(("webview_test_done", ""))
            except Exception as error:  # noqa: BLE001
                self._post(("webview_test_done", str(error)))

        threading.Thread(target=worker, daemon=True).start()


    def _copy_diagnostics(self) -> None:
        lines = [
            f"version={VERSION}",
            f"data_dir={APP_DIR}",
            f"follow_enhance={bool(self.settings.get('follow_enhance'))}",
            f"save_result={bool(self.settings.get('save_result'))}",
            f"encrypt_result={bool(self.settings.get('encrypt_result'))}",
            f"risk_enabled={bool(self.settings.get('risk_enabled'))}",
            f"page_size={self.settings.get('page_size')}",
        ]
        self.root.clipboard_clear()
        self.root.clipboard_append(chr(10).join(lines))
        self.status_var.set("诊断信息已复制（不含 Cookie/昵称/正文）")


    def _open_usage_window(self) -> None:
        existing = getattr(self, "_usage_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                existing.focus_set()
                return
        except tk.TclError:
            pass
        win = tk.Toplevel(self.root)
        self._usage_window = win
        win.title("使用说明")
        win.configure(bg="#eef1f5")
        win.geometry("780x640")
        win.minsize(600, 420)
        win.transient(self.root)
        frame = tk.Frame(win, bg="#eef1f5", padx=10, pady=8)
        frame.pack(fill="both", expand=True)
        top = tk.Frame(frame, bg="#eef1f5")
        top.pack(fill="x", pady=(0, 6))
        tk.Label(
            top,
            text="使用说明",
            bg="#eef1f5",
            fg="#1F4E79",
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(side="left")
        ttk.Button(top, text="关闭", command=win.destroy, width=8).pack(side="right")
        text = tk.Text(
            frame,
            wrap="word",
            font=("Microsoft YaHei UI", 9),
            relief="flat",
            padx=10,
            pady=8,
            bg="#fbfcfe",
            state="disabled",
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        content = ""
        try:
            path = os.path.join(resource_dir(), "使用说明.txt")
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    content = handle.read()
        except OSError:
            content = ""
        shortcuts = (
            "快捷键\n"
            "  F1           打开使用说明\n"
            "  Ctrl+Enter   从链接输入框开始抓取\n"
            "  Ctrl+C       复制选中行\n"
            "  Esc          关闭当前弹窗\n"
            "  双击         打开选中项\n\n"
        )
        text.configure(state="normal")
        text.insert("1.0", shortcuts + (content or "使用说明文件未找到。"))
        text.configure(state="disabled")
        self._theme_widget_tree(win)
        self._center_toplevel(win, 780, 640)
        win.bind("<Escape>", lambda _event: win.destroy())
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.focus_set()


    def _clear_all_data(self) -> None:
        if not messagebox.askyesno(
            "清空软件数据（不会删除导出文件）",
            "会删除：最近结果、保存的 BDUSS、本地标记、设置、临时文件、日志、"
            "内置 WebView2 登录态。\n"
            "不会删除：导出的 Excel、Markdown、你保存到其他位置的文件，"
            "以及系统浏览器里的百度登录。\n\n继续？",
            parent=self.root,
        ):
            return
        if self._network_task_active() or getattr(self, "_webview_running", False):
            messagebox.showinfo("请稍后", "抓取、补全或内置窗口进行中，暂时不能清空。", parent=self.root)
            return
        if simpledialog.askstring("确认清空", "输入“清空”后继续：", parent=self.root) != "清空":
            return
        if not webview2.clear_login_profile():
            messagebox.showerror(
                "清空失败",
                "WebView2 登录目录正在使用，无法删除。请关闭内置窗口后重试。",
                parent=self.root,
            )
            return
        clear_stored_result()
        clear_post_cache()
        post_cache().close()
        try:
            for path in stored_old_files():
                safe_remove_file(path)
            for path in (os.path.join(APP_DIR, "cookie.bin"), SETTINGS_PATH):
                safe_remove_file(path)
            safe_remove_tree(os.path.join(APP_DIR, "logs"))
            temp_dir = os.path.join(os.environ.get("TEMP", ""), "TiebaReplyStats")
            if os.path.isdir(temp_dir):
                safe_remove_tree(temp_dir, [temp_dir])
        except (OSError, ValueError) as error:
            post_cache().reopen()
            messagebox.showerror("清空失败", f"路径校验失败，已停止：{error}", parent=self.root)
            return
        post_cache().reopen()
        clear_cookie()
        save_blacklist({"safe": [], "warn": [], "ban": []})
        self._on_mark_rules_changed()
        save_settings({})
        self.settings = load_settings()
        self.blacklist = {"safe": [], "warn": [], "ban": []}
        self.last_threads = []
        self.last_output = None
        self.cookie_var.set("")
        self.bduss_var.set("")
        self._guest_cookie = {}
        self._full_cookie_cache = ""
        self._webview_cookie_session = False
        self._last_lookup_profile = None
        self._profile_user = None
        self._profile_data = None
        self._lookup_cache.clear()
        self._profile_cache.clear()
        self._apply_settings_to_ui()
        self._refresh_webview_status()
        self._set_lookup_text("软件数据已清空。")
        self.open_btn.configure(state="disabled")
        for _key, editor in getattr(self, "blacklist_editors", {}).items():
            editor.delete("1.0", "end")
        self._update_grid_selector()
        self._refresh_people()
        self._refresh_grid()
        self._refresh_old_files_label()
        self._refresh_log_summary()
        self._append_log("软件数据已清空；导出文件未受影响。", "ok")







