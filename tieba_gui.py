#!/usr/bin/env python3
"""OK的贴吧玩具箱 —— 图形界面（给不想用命令行的用户）。

直接运行：python tieba_gui.py
打包后双击 exe 即可。
"""

from __future__ import annotations

import ctypes
import os
import queue
import re
import sys
import threading
import tkinter as tk
import traceback
from dataclasses import replace
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from tieba_gui_export import ExportMixin
from tieba_gui_grid import GridMixin
from tieba_gui_identity import BatchIdentityMixin
from tieba_gui_layout import APP_TITLE, GuiLayoutMixin
from tieba_gui_links import LinksMixin
from tieba_gui_login import LoginMixin
from tieba_gui_lookup import LookupMixin
from tieba_gui_messages import MessageMixin
from tieba_gui_people import PeopleReportMixin
from tieba_gui_profile import ProfileMixin
from tieba_gui_settings import SettingsMixin
from tieba_gui_settings_runtime import SettingsRuntimeMixin
from tieba_gui_theme import ThemeMixin
from tieba_gui_tools import ToolsMixin
from tieba_gui_workers import WorkerMixin
from tieba_reply_stats import webview2
from tieba_reply_stats.blacklist import (
    LEVEL_LABEL,
    classify,
    load_blacklist,
    marker,
    merge_blacklists,
    save_blacklist,
)
from tieba_reply_stats.blacklist import (
    export_xlsx as export_blacklist_xlsx,
)
from tieba_reply_stats.blacklist import (
    import_xlsx as import_blacklist_xlsx,
)
from tieba_reply_stats.collect import (
    CollectCancelled,
    CollectOptions,
    collect_thread,
)
from tieba_reply_stats.compare import MODES, compare_threads
from tieba_reply_stats.cookie_store import load_cookie
from tieba_reply_stats.errors import friendly_error
from tieba_reply_stats.export import export_workbook
from tieba_reply_stats.fetch import (
    Fetcher,
    configure_gate,
    parse_cookie_input,
    resume_requests,
    set_stop_checker,
)
from tieba_reply_stats.filters import filter_users
from tieba_reply_stats.follow_probe import candidate_bars, probe_forums
from tieba_reply_stats.post_cache import DEFAULT_LIMIT_MB
from tieba_reply_stats.post_cache import cache as post_cache
from tieba_reply_stats.profile import (
    clear_post_cache,
)
from tieba_reply_stats.report import (
    export_user_report,
    report_base,
)
from tieba_reply_stats.safe_delete import remove_file as safe_remove_file
from tieba_reply_stats.settings import load_settings, save_settings
from tieba_reply_stats.storage import (
    IncompatibleResult,
    archive_incompatible,
    load_threads,
    save_threads,
)
from tieba_reply_stats.storage import (
    clear as clear_stored_result,
)
from tieba_reply_stats.storage import (
    old_files as stored_old_files,
)
from tieba_reply_stats.theme import resolve_palette
from tieba_reply_stats.version import __version__ as VERSION

_EMOJI_CODE_RE = re.compile(r"\[U\+([0-9A-Fa-f]{4,6})\]", re.I)

EMOJI_PICKER = (
    "😀", "😁", "😂", "🤣", "😊", "😍", "🤔", "😅",
    "😭", "😡", "👍", "👎", "❤", "🔥", "🎉", "💩",
    "🤡", "👀", "😴", "🤮", "🤤", "🙄", "😳", "😱",
    "🤯", "🥰", "😎", "🤓", "😐", "😑", "🙃", "🙏",
)


def display_text(value) -> str:
    """界面直接显示 emoji；Tk 8.6 以单色字形渲染。"""
    return str(value or "")


def decode_display(value) -> str:
    """把 [U+XXXX] 还原成 emoji，用于回查。"""
    return _EMOJI_CODE_RE.sub(lambda match: chr(int(match.group(1), 16)), str(value or ""))


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


def default_output_path() -> str:
    desktop = ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "Desktop")
        desktop = os.path.expandvars(value)
    except OSError:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.expanduser("~")
    return os.path.join(desktop, f"OK的贴吧玩具箱_{datetime.now():%Y%m%d_%H%M}.xlsx")


def resource_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _optional_int(text: str) -> Optional[int]:
    try:
        return int(str(text).strip())
    except ValueError:
        return None

























class App(GuiLayoutMixin, MessageMixin, SettingsMixin, GridMixin, LookupMixin, WorkerMixin, ExportMixin, BatchIdentityMixin, ThemeMixin, ProfileMixin, ToolsMixin, LoginMixin, LinksMixin, PeopleReportMixin, SettingsRuntimeMixin):
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.running = False
        self.last_output: str | None = None
        self.last_outputs: List[str] = []
        self.last_threads: list = []
        self._pending_retry = False
        self._auto_filled = False
        self._identity_choice_queue: "queue.Queue[tuple]" = queue.Queue()
        self._rate_choice_queue: "queue.Queue[str]" = queue.Queue()
        self._last_stage_times: Dict[str, float] = {}
        self._manual_timing: Dict[str, float] = {}
        self._supplement_stop = threading.Event()
        self._guest_cookie: Dict[str, str] = {}
        self._full_cookie_cache = ""
        self._webview_cookie_session = False
        self._tieba_uid_failed: set[str] = set()
        self._user_id_failed: set[str] = set()
        self._profile_topic_limit = 50
        self._lookup_normalize_job: Optional[str] = None
        self._emoji_window: Optional[tk.Toplevel] = None
        self.lookup_entry: Optional[ttk.Entry] = None
        self.lookup_native_edit: Optional[int] = None
        self.lookup_native_host: Optional[tk.Frame] = None
        self.love_native_edit: Optional[int] = None
        self.love_native_host: Optional[tk.Frame] = None
        self.emoji_btn: Optional[tk.Button] = None
        self.blacklist = load_blacklist()
        self.settings = load_settings()
        post_cache().set_limit_mb(int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB)))
        self.palette = resolve_palette(
            str(self.settings.get("theme_mode", "light")),
            str(self.settings.get("accent", "blue")),
        )
        self.mode_var = tk.StringVar(value="guest")
        self._login_source = ""
        self._last_webview_match: Optional[bool] = None
        self._login_probe_token = 0
        self._active_choice_window: Optional[tk.Toplevel] = None
        self._usage_window: Optional[tk.Toplevel] = None
        webview2.cleanup_profile_backup()
        webview2.clear_switch_profile()

        self._build_ui()
        self._apply_window_icon()
        self._apply_theme()
        self._apply_table_density()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)
        saved_geometry = str(self.settings.get("window_geometry") or "")
        match = re.match(r"(\d+)x(\d+)", saved_geometry)
        if match:
            saved_w, saved_h = int(match.group(1)), int(match.group(2))
            # 旧版本可能记住了窄窗口；小于新默认值时恢复默认尺寸。
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            width = max(1300, min(saved_w, screen_w - 100)) if saved_w >= 1300 else min(1400, screen_w - 100)
            height = max(820, min(saved_h, screen_h - 120)) if saved_h >= 820 else min(900, screen_h - 120)
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 2)
            try:
                self.root.geometry(f"{width}x{height}+{x}+{y}")
            except tk.TclError:
                pass
        self._set_output(default_output_path())
        self.root.after(120, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<F1>", lambda _event: self._open_usage_window())
        self.root.bind("<Control-Shift-C>", self._show_test_center)
        self.root.bind("<Escape>", self._on_escape)

        saved = load_cookie()
        if saved:
            self.cookie_var.set(saved)
            self._sync_login_from_cookie()
            self._login_source = "已保存 Cookie"
            self._append_log("已自动填入上次保存的登录信息（如果失效，请重新粘贴一次）。", "muted")
        if self.settings.get("follow_enhance"):
            self.mode_var.set("login")
            if not parse_cookie_input(self.cookie_var.get()).get("BDUSS"):
                self._append_log("关注检测已开启，但尚未完成登录；请先登录后再开始统计。", "muted")
        else:
            self.mode_var.set("guest")
        self._apply_mode_ui()
        self._refresh_webview_status()
        self._apply_risk_ui()
        self._apply_proxy()
        self._restore_last_result()
        self.root.after(300, self._maybe_onboarding)

    def _apply_window_icon(self) -> None:
        for path in (
            os.path.join(resource_dir(), "assets", "app.ico"),
            os.path.join(resource_dir(), "app.ico"),
        ):
            if not os.path.isfile(path):
                continue
            try:
                self.root.iconbitmap(default=path)
                self.root.iconbitmap(path)
                return
            except tk.TclError:
                continue

    # ------------------------------------------------------------------ UI

    # ------------------------------------------------------------- actions
    def _set_output(self, path: str) -> None:
        self.output_var.set(path)

    def _choose_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择保存位置",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
            initialfile=os.path.basename(self.output_var.get() or "OK的贴吧玩具箱.xlsx"),
            initialdir=os.path.dirname(self.output_var.get() or ""),
        )
        if path:
            self._set_output(path)

















    def _open_readme(self) -> None:
        for name in ("使用说明.txt", "README.md"):
            path = os.path.join(resource_dir(), name)
            if os.path.isfile(path):
                try:
                    os.startfile(path)  # type: ignore[attr-defined]
                    return
                except OSError:
                    break
        messagebox.showinfo(
            "使用说明",
            "1. 粘贴帖子链接（每行一个）\n"
            "2. 选择保存位置\n"
            "3. 点「开始统计」\n"
            "4. 完成后点「打开 Excel」\n\n"
            "如果提示被安全验证拦截，点「如何获取？」，按说明把 Cookie 粘贴进来。",
            parent=self.root,
        )


    # ------------------------------------------------------- 参与者与查用户


    def _on_tab_changed(self, _event=None) -> None:
        try:
            current = self.post_nb.index("current")
            if current == self.post_nb.index(self.tab_people):
                if self.last_threads:
                    self._refresh_people()
                    self._auto_fill_levels()
            elif current == self.post_nb.index(self.tab_grid):
                self._refresh_grid()
        except tk.TclError:
            pass

    def _date_group(self, parent, label: str, months_ago: int = 0):
        import calendar

        base = datetime.now()
        if months_ago:
            year = base.year
            month = base.month - months_ago
            while month <= 0:
                month += 12
                year -= 1
            day = min(base.day, calendar.monthrange(year, month)[1])
            base = base.replace(year=year, month=month, day=day)
        tk.Label(parent, text=f"{label}", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        year_var = tk.StringVar(value=str(base.year))
        month_var = tk.StringVar(value=f"{base.month:02d}")
        day_var = tk.StringVar(value=f"{base.day:02d}")
        ttk.Combobox(
            parent,
            values=[str(year) for year in range(2003, datetime.now().year + 2)],
            textvariable=year_var,
            width=5,
            state="readonly",
        ).pack(side="left")
        tk.Label(parent, text="年", bg="#ffffff").pack(side="left")
        ttk.Combobox(
            parent,
            values=[f"{month:02d}" for month in range(1, 13)],
            textvariable=month_var,
            width=3,
            state="readonly",
        ).pack(side="left")
        tk.Label(parent, text="月", bg="#ffffff").pack(side="left")
        ttk.Combobox(
            parent,
            values=[f"{day:02d}" for day in range(1, 32)],
            textvariable=day_var,
            width=3,
            state="readonly",
        ).pack(side="left")
        tk.Label(parent, text="日", bg="#ffffff").pack(side="left")
        return year_var, month_var, day_var

    def _group_date(self, parts) -> str:
        import calendar

        try:
            year, month = int(parts[0].get()), int(parts[1].get())
            day = min(int(parts[2].get()), calendar.monthrange(year, month)[1])
            return f"{year:04d}-{month:02d}-{day:02d}"
        except (ValueError, IndexError):
            return ""

    def _toggle_date_entries(self) -> None:
        enabled = getattr(self, "post_date_mode_var", None) and self.post_date_mode_var.get() == "指定日期"
        try:
            if enabled:
                if not self.post_date_row.winfo_ismapped():
                    self.post_date_row.pack(fill="x", before=self.people_paned)
            else:
                self.post_date_row.pack_forget()
        except tk.TclError:
            pass

    def _on_post_parts_changed(self, *_args) -> None:
        if getattr(self, "_batch_running", False):
            return
        self.post_start_var.set(self._group_date(self.post_start_parts))
        self.post_end_var.set(self._group_date(self.post_end_parts))
        if self.post_date_mode_var.get() == "指定日期":
            self._on_post_date_changed()

    def _on_post_date_changed(self) -> None:
        if getattr(self, "_batch_running", False):
            return
        self._toggle_date_entries()
        if self.post_date_mode_var.get() == "指定日期":
            self.post_start_var.set(self._group_date(self.post_start_parts))
            self.post_end_var.set(self._group_date(self.post_end_parts))
        else:
            self.post_start_var.set("")
            self.post_end_var.set("")
            self.post_prefer_var.set("优先最近")
        if hasattr(self, "_profile_cache"):
            self._profile_cache.clear()
        self.profile_status.configure(text="条件已变更，点「刷新资料」生效")

    def _open_emoji_panel(self) -> None:
        if os.name == "nt":
            try:
                self._toggle_emoji_inline()
                return
            except Exception:  # noqa: BLE001
                pass
        self._open_emoji_picker()

    def _build_emoji_inline(self) -> tk.Frame:
        frame = tk.Frame(self.tab_lookup, bg="#eef1f5", padx=10, pady=6)
        self._emoji_inline_frame = frame
        tk.Label(
            frame,
            text="输入 Emoji（支持微软输入法 / Win+. / Ctrl+V）",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
        ).pack(fill="x")
        row = tk.Frame(frame, bg="#eef1f5")
        row.pack(fill="x", pady=(2, 4))
        host = tk.Frame(row, bg="#ffffff", height=34)
        host.pack(side="left", fill="x", expand=True)
        host.pack_propagate(False)
        self._emoji_host = host
        ttk.Button(row, text="取消", command=self._hide_emoji_inline, width=8).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(row, text="插入", command=self._commit_emoji_inline, width=8).pack(
            side="right", padx=(6, 0)
        )
        self._theme_widget_tree(frame)
        return frame

    def _toggle_emoji_inline(self) -> None:
        frame = getattr(self, "_emoji_inline_frame", None)
        if frame is not None and frame.winfo_manager():
            self._hide_emoji_inline()
            return
        if frame is None:
            frame = self._build_emoji_inline()
        frame.pack(fill="x", after=self.lookup_query_bar)
        self.root.update_idletasks()
        if not self._create_inline_edit():
            self._hide_emoji_inline()
            self._open_emoji_picker()
            return

        ctypes.windll.user32.SetFocus(self._emoji_edit)

    def _create_inline_edit(self) -> bool:
        if getattr(self, "_emoji_edit", None):
            return True
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
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
        gdi32.CreateFontW.restype = wintypes.HFONT
        gdi32.CreateFontW.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
        ]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        hinst = kernel32.GetModuleHandleW(None)
        style = 0x40000000 | 0x10000000 | 0x00800000 | 0x00000080
        edit = user32.CreateWindowExW(
            0, "EDIT", "", style, 0, 0, 100, 32,
            wintypes.HWND(self._emoji_host.winfo_id()), None, hinst, None,
        )
        if not edit:
            return False
        self._emoji_edit = edit
        font = gdi32.CreateFontW(
            -16, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Segoe UI Emoji"
        )
        self._emoji_edit_font = font
        if font:
            user32.SendMessageW(edit, 0x0030, font, 1)

        def resize(event) -> None:
            user32.MoveWindow(edit, 0, 0, max(10, event.width), max(20, event.height), True)

        self._emoji_host.bind("<Configure>", resize)
        resize(type("E", (), {"width": 600, "height": 32})())
        return True

    def _commit_emoji_inline(self) -> None:
        edit = getattr(self, "_emoji_edit", None)
        if not edit:
            return

        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(edit)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(edit, buffer, length + 1)
        text = buffer.value.strip()
        if text and self.lookup_entry is not None:
            self.lookup_entry.insert("insert", text)
        self._hide_emoji_inline()

    def _hide_emoji_inline(self) -> None:
        frame = getattr(self, "_emoji_inline_frame", None)
        if frame is not None:
            frame.pack_forget()
        edit = getattr(self, "_emoji_edit", None)
        if edit:
            try:
                import ctypes

                ctypes.windll.user32.SetWindowTextW(edit, "")
            except Exception:  # noqa: BLE001
                pass
        if self.lookup_entry is not None:
            self.lookup_entry.focus_set()

    def _open_emoji_picker(self) -> None:
        existing = getattr(self, "_emoji_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                return
        except tk.TclError:
            pass
        win = tk.Toplevel(self.root)
        self._emoji_window = win
        win.title("选择 Emoji")
        win.configure(bg="#eef1f5")
        win.resizable(False, False)
        win.transient(self.root)
        frame = tk.Frame(win, bg="#eef1f5", padx=8, pady=8)
        frame.pack()
        for index, char in enumerate(EMOJI_PICKER):
            def choose(value: str = char) -> None:
                self._insert_emoji(value, win)

            button = tk.Button(
                frame,
                text=char,
                font=("Segoe UI Emoji", 14),
                width=2,
                relief="flat",
                bg="#ffffff",
                activebackground="#dbeafe",
                cursor="hand2",
                command=choose,
            )
            button.grid(row=index // 8, column=index % 8, padx=2, pady=2)
        self._theme_widget_tree(win)
        self._center_toplevel(win)
        win.bind("<Escape>", lambda _event: win.destroy())
        win.focus_set()

    def _insert_emoji(self, char: str, win=None) -> None:
        if self.lookup_entry is not None:
            self.lookup_entry.insert("insert", char)
            self.lookup_entry.focus_set()
        if win is not None:
            win.destroy()




    def _make_sortable(self, tree, headers, sortable=None) -> None:
        """点表头在升序/降序之间切换；sortable 限定真正可排序的列。"""
        state: Dict[str, Any] = {"column": None, "reverse": False}
        allowed = set(sortable) if sortable is not None else set(headers)

        def sort_by(column: str) -> None:
            if state["column"] == column:
                state["reverse"] = not state["reverse"]
            else:
                state["column"] = column
                state["reverse"] = False
            reverse = bool(state["reverse"])

            def key(item):
                value = tree.set(item, column)
                text = value[3:] if value.startswith("Lv.") else value
                try:
                    return (0, float(text))
                except ValueError:
                    return (1, str(value))

            items = list(tree.get_children())
            items.sort(key=key, reverse=reverse)
            for index, item in enumerate(items):
                tree.move(item, "", index)
            for col, title in headers.items():
                arrow = ""
                if col == column:
                    arrow = " ▼" if reverse else " ▲"
                tree.heading(col, text=title + arrow)

        for col, title in headers.items():
            if col in allowed:
                tree.heading(col, text=title, command=lambda c=col: sort_by(c))
            else:
                tree.heading(col, text=title)

    def _selected_person(self):
        selection = self.people_tree.selection()
        if not selection:
            return None
        try:
            return self.people_users[int(selection[0])]
        except (IndexError, ValueError):
            return None

    def _copy_text(self, content: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(content or "")
        self.people_hint.configure(text="已复制到剪贴板")

    def _copy_tree_page(self, tree) -> None:
        lines = []
        for iid in tree.get_children():
            lines.append("	".join(str(value) for value in tree.item(iid, "values")))
        self._copy_text(chr(10).join(lines))

    def _copy_people_page(self) -> None:
        self._copy_tree_page(self.people_tree)

    def _copy_person_row(self) -> None:
        user = self._selected_person()
        if not user:
            return
        level = f"Lv.{user['level']}" if user.get("level") else "-"
        self._copy_text(
            "\t".join(
                str(item)
                for item in (
                    user.get("name", ""),
                    user.get("username", ""),
                    user.get("tieba_uid", ""),
                    user.get("uid", ""),
                    level,
                )
            )
        )

    def _copy_person_field(self, key: str) -> None:
        user = self._selected_person()
        if user:
            self._copy_text(str(user.get(key) or ""))

    def _person_menu(self, event) -> None:
        if getattr(self, "_batch_running", False):
            return
        if self.people_tree.identify_region(event.x, event.y) == "heading":
            column = self.people_tree.identify_column(event.x)
            try:
                index = int(column[1:]) - 1
                key = self.people_columns[index]
            except (ValueError, IndexError):
                return
            if key in ("mark", "name", "username", "tieba_uid", "uid"):
                self._filter_people_column(key, (event.x_root, event.y_root))
            return
        row = self.people_tree.identify_row(event.y)
        if row:
            self.people_tree.selection_set(row)
            try:
                self._person_popup.tk_popup(event.x_root, event.y_root)
            finally:
                self._person_popup.grab_release()


    def _offer_retry_incomplete(self, source: str) -> None:
        targets = [
            thread
            for thread in getattr(self, "last_threads", [])
            if not getattr(thread, "complete", True)
        ]
        if not targets:
            return
        if messagebox.askyesno(
            f"{source}已更新",
            f"有 {len(targets)} 个帖子未完成。\n"
            "是否只重试失败部分（不会重抓已完成页/楼层）？",
            parent=self.root,
            default=messagebox.YES,
        ):
            # 登录更新回调可能仍处于原任务收尾阶段；延后到主循环再启动。
            self._pending_retry = True
            self.root.after(200, self._retry_incomplete_threads)

    def _retry_incomplete_threads(self) -> None:
        if getattr(self, "_supplement_running", False) or self.running:
            self._pending_retry = True
            self._append_log("当前任务尚未结束，稍后重试失败部分。", "muted")
            return
        self._pending_retry = False
        targets = [thread for thread in self.last_threads if not getattr(thread, "complete", True)]
        if not targets:
            messagebox.showinfo("没有失败部分", "当前帖子都是完整的。", parent=self.root)
            return
        mode = self.mode_var.get()
        if mode == "login":
            cookie = self._request_cookie()
            if not webview2.has_login_cookie(cookie):
                messagebox.showwarning(
                    "需要登录 Cookie",
                    "登录模式续抓需要 BDUSS/TIEBA_SID，请先重新获取登录信息。",
                    parent=self.root,
                )
                return
        else:
            cookie = {}
        resume_requests()
        configure_gate(float(self.delay_var.get() or 0.8))
        self._set_supplement_running(True)
        self._supplement_stop.clear()
        set_stop_checker(self._supplement_stop.is_set)
        self.retry_incomplete_btn.state(["disabled"])
        self.people_hint.configure(text=f"正在重试 {len(targets)} 个帖子的失败部分…")

        def worker():
            try:
                fetcher = Fetcher(cookie=cookie, delay=0, verbose=False)
                options = CollectOptions(
                    mode=mode,
                    include_comments=self.comments_var.get(),
                    comment_depth=self._comment_depth_value(),
                    comment_concurrency=max(
                        1, min(3, int(self.comment_concurrency_var.get() or 1))
                    ),
                    verbose=True,
                    log=self._log_from_thread,
                    should_stop=self._supplement_stop.is_set,
                )
                for thread in targets:
                    url = thread.meta.url or f"https://tieba.baidu.com/p/{thread.meta.tid}"
                    collect_thread(url, fetcher, options, resume_thread=thread)
                self._persist_result(self.last_threads)
                self._post(("incomplete_retry_done", len(targets)))
            except CollectCancelled:
                self._persist_result(self.last_threads)
                self._post(("incomplete_retry_stopped",))
            except Exception as error:  # noqa: BLE001
                self._post(("incomplete_retry_error", str(error)))

        threading.Thread(target=worker, daemon=True).start()





























    def _start_probe(self, user, profile, button) -> None:
        uid = str(profile.get("user_id") or user.get("uid") or "")
        portrait = str(profile.get("portrait") or user.get("portrait") or "")
        if not uid or not portrait:
            messagebox.showinfo("缺少资料", "没有用户 ID 或头像，无法探测。", parent=self.root)
            return
        candidates = candidate_bars(user, profile, self.blacklist)
        if not candidates:
            messagebox.showinfo(
                "没有候选吧",
                "本帖发言、发言、本地标记里没有可探测的吧。",
                parent=self.root,
            )
            return
        self._probe_running = True
        self._probe_stop = threading.Event()
        button.configure(state="normal", text="停止探测")
        self._append_log(f"开始探测 {len(candidates)} 个候选吧（最多 30 个）…", "muted")

        def worker() -> None:
            fetcher = Fetcher(cookie={}, delay=0.3, verbose=False)
            results = probe_forums(
                fetcher,
                uid,
                portrait,
                candidates,
                log=self._log_from_thread,
                should_stop=self._probe_stop.is_set,
            )
            self._post(("probe_done", profile, results, button))

        threading.Thread(target=worker, daemon=True).start()

    def _post_source_note(self, profile) -> str:
        src = profile.get("post_sources") or {}
        if src.get("replies_ok") is False:
            return "回复流查询失败，当前只显示主题帖"
        if src.get("replies_empty") and src.get("threads_ok"):
            return "回复流为空，当前只显示主题帖"
        return ""

    def _cache_age_note(self, profile) -> str:
        src = profile.get("post_sources") or {}
        if src.get("cached"):
            age = src.get("cached_age_minutes")
            if age is not None:
                return f"缓存于 {age} 分钟前（刷新资料可强制更新）"
        age_seconds = profile.get("_ui_cache_age_seconds")
        if age_seconds is not None:
            return f"缓存于 {max(0, int(age_seconds) // 60)} 分钟前（刷新资料可强制更新）"
        return ""





    def _apply_level_results(self, kind, profile, forums, results) -> None:
        by_name = {str(forum.get("name") or ""): forum for forum in forums}
        for name, data in results.items():
            forum = by_name.get(name)
            if forum is None:
                continue
            forum["level"] = int(data.get("level") or 0)
            forum["level_source"] = "恋文（第三方）"
            forum["third_party_level"] = True
            for key in ("followed_forums", "hidden_forums", "like_forum", "probed_forums"):
                for saved in profile.get(key) or []:
                    if str(saved.get("name") or "") == name:
                        saved["level"] = forum["level"]
                        saved["level_source"] = "恋文（第三方）"
        tree = self.lookup_forum_tree if kind == "lookup" else self.profile_forum_tree
        names = self._lookup_forum_names if kind == "lookup" else self._profile_forum_names
        for iid, name in list(names.items()):
            forum = by_name.get(name)
            if not forum:
                continue
            try:
                tree.set(iid, "level", f"Lv.{forum['level']}" if forum.get("level") else "-")
                tree.set(iid, "level_source", forum.get("level_source") or "-")
            except tk.TclError:
                pass



    def _open_participants(self) -> None:
        if not self.last_threads:
            messagebox.showinfo("还没有数据", "先点「开始统计」抓一个帖子，再查看参与者。", parent=self.root)
            return
        self._refresh_people()
        self.notebook.select(self.tab_posts)
        self.post_nb.select(self.tab_people)

    def _update_people_sort_headings(self) -> None:
        if not hasattr(self, "people_tree"):
            return
        current, reverse = getattr(self, "_people_sort", ("", False))
        for column, label in getattr(self, "_people_headings", {}).items():
            if column not in ("mark", "level", "floor", "comment", "total"):
                continue
            arrow = ""
            if column == current:
                arrow = "  ▲" if not reverse else "  ▼"
            try:
                self.people_tree.heading(column, text=label + arrow)
            except tk.TclError:
                pass

    def _sort_people(self, column: str) -> None:
        if getattr(self, "_batch_running", False):
            return
        if column not in ("mark", "level", "floor", "comment", "total"):
            return
        current, reverse = self._people_sort
        self._people_sort = (column, (not reverse) if current == column else False)
        self._people_page = 0
        self._update_people_sort_headings()
        self._refresh_people()

    def _people_column_value(self, user, column: str) -> str:
        if column == "mark":
            level = str(user.get("mark_level") or "")
            if not level:
                level, _bar = classify(user.get("bars") or [], self.blacklist)
            return LEVEL_LABEL.get(level, "") if self._risk_enabled() else ""
        if column == "name":
            return self._display_name(user)
        if column == "username":
            return user.get("username") or "-"
        if column == "tieba_uid":
            return self._tieba_uid_cell(user)
        if column == "uid":
            return user.get("uid") or "-"
        return ""

    def _filter_people_column(self, column: str, anchor: Optional[tuple] = None) -> None:
        if getattr(self, "_batch_running", False):
            return
        values = sorted({self._people_column_value(user, column) for user in self.people_users})
        chosen = self._filter_text_dialog(
            {"mark": "标记", "name": "昵称", "username": "用户名", "tieba_uid": "贴吧ID", "uid": "用户ID"}.get(column, column),
            values,
            self._people_col_filters.get(column),
            anchor,
        )
        if chosen is None:
            return
        if chosen:
            self._people_col_filters[column] = chosen
        else:
            self._people_col_filters.pop(column, None)
        self._people_page = 0
        self._refresh_people()

    def _on_people_filter_changed(self) -> None:
        if getattr(self, "_batch_running", False):
            return
        self._people_page = 0
        if getattr(self, "_filter_resetting", False):
            return
        if self.people_level_var.get() == "自定义":
            self.people_custom_frame.pack(side="left", padx=(4, 0))
        else:
            self.people_custom_frame.pack_forget()
        self._refresh_people()

    def _reset_people_filters(self) -> None:
        if getattr(self, "_batch_running", False):
            return
        self._filter_resetting = True
        try:
            self.people_keyword_var.set("")
            self.people_field_var.set("全部字段")
            self.people_level_var.set("全部")
            self.people_mark_var.set("全部")
            self.people_min_var.set("")
            self.people_max_var.set("")
            self._people_col_filters = {}
            self._people_sort = ("", False)
            self.people_custom_frame.pack_forget()
        finally:
            self._filter_resetting = False
        self._update_people_sort_headings()
        self._refresh_people()

    def _display_name(self, item) -> str:
        name = display_text(item.get("name") or "")
        aliases = [display_text(value) for value in item.get("aliases") or []]
        if not aliases:
            return name
        shown = "、".join(aliases[:2])
        if len(aliases) > 2:
            shown += f" 等{len(aliases)}个"
        return f"{name}（曾用：{shown}）"

    def _people_threads(self):
        value = self.people_range_var.get()
        if value.startswith("全部"):
            return list(self.last_threads)
        for index, thread in enumerate(self.last_threads, start=1):
            if value.startswith(f"{index}. "):
                return [thread]
        return list(self.last_threads)

    def _refresh_supplement_rows(self) -> None:
        """只更新已补到的贴吧ID，不重建整张参与者表。"""
        by_uid: Dict[str, str] = {}
        for thread in getattr(self, "last_threads", []):
            for item in list(thread.floors) + list(thread.comments):
                uid = str(getattr(item, "author_id", "") or "")
                tieba_uid_value = str(getattr(item, "tieba_uid", "") or "")
                if uid and tieba_uid_value:
                    by_uid[uid] = tieba_uid_value
        if not by_uid:
            return
        tree = getattr(self, "people_tree", None)
        for user in getattr(self, "people_users", []):
            uid = str(user.get("uid") or "")
            value = by_uid.get(uid)
            if not value or user.get("tieba_uid") == value:
                continue
            user["tieba_uid"] = value
            iid = user.get("_iid")
            if tree is None or iid is None:
                continue
            try:
                values = list(tree.item(iid, "values"))
                if len(values) > 3:
                    values[3] = value
                    tree.item(iid, values=values)
            except tk.TclError:
                pass


    def _tieba_uid_cell(self, item) -> str:
        value = str(item.get("tieba_uid") or "")
        if value:
            return value
        uid = str(item.get("uid") or item.get("user_id") or "")
        if item.get("tieba_uid_failed") or (uid and uid in self._tieba_uid_failed):
            return "-"
        if uid or item.get("username") or item.get("portrait"):
            return "待补充"
        return "-"

    def _apply_tieba_failed_states(self, threads) -> None:
        failed = set(getattr(self, "_tieba_uid_failed", set()) or set())
        for thread in threads or []:
            for item in list(thread.floors) + list(thread.comments):
                uid = str(getattr(item, "author_id", "") or "")
                item.tieba_uid_failed = bool(uid and uid in failed and not item.tieba_uid)

    def _tieba_uid_obj_cell(self, item) -> str:
        value = str(getattr(item, "tieba_uid", "") or "")
        if value:
            return value
        uid = str(getattr(item, "author_id", "") or "")
        if getattr(item, "tieba_uid_failed", False) or (uid and uid in self._tieba_uid_failed):
            return "-"
        if uid or getattr(item, "author_name", "") or getattr(item, "portrait", ""):
            return "待补充"
        return "-"

    def _apply_user_id_failed_states(self, threads) -> None:
        failed = set(getattr(self, "_user_id_failed", set()) or set())
        for thread in threads or []:
            for item in list(thread.floors) + list(thread.comments):
                if not getattr(item, "author_id", ""):
                    item.user_id_failed = self._identity_fail_key(item) in failed

    def _person_uid_text(self, user) -> str:
        uid = str(user.get("uid") or "")
        if uid:
            return uid
        if user.get("user_id_failed") or self._identity_fail_key(user) in self._user_id_failed:
            return "-"
        if user.get("username") or user.get("portrait"):
            return "待补充"
        return "-"

    def _person_mark_cell(self, user) -> str:
        if not self._risk_enabled():
            return ""
        level = str(user.get("mark_level") or "")
        if not level:
            return "⚪"
        label = LEVEL_LABEL.get(level, "")
        suffix = " ⚠" if user.get("mark_hidden") else ""
        return f"{marker(level)} {label}{suffix}"

    def _set_person_mark_row(self, user) -> None:
        iid = user.get("_iid")
        if iid is None:
            return
        try:
            values = list(self.people_tree.item(iid, "values"))
            if not values:
                return
            values[0] = self._person_mark_cell(user)
            values[2] = str(user.get("username") or "-")
            values[3] = self._tieba_uid_cell(user)
            values[4] = self._person_uid_text(user)
            level = str(user.get("level") or "")
            if level:
                values[5] = f"Lv.{level}"
            self.people_tree.item(
                iid,
                values=values,
                tags=(str(user.get("mark_level") or ""),)
                if user.get("mark_level") and self.settings.get("color_people", True)
                else (),
            )
        except tk.TclError:
            pass


    def _people_go(self, value) -> None:
        users = getattr(self, "people_users", [])
        page_size = max(1, int(self.settings.get("page_size", 1000) or 1000))
        pages = max(1, (len(users) + page_size - 1) // page_size)
        if value == "first":
            self._people_page = 0
        elif value == "last":
            self._people_page = pages - 1
        else:
            self._people_page = min(max(0, self._people_page + int(value)), pages - 1)
        self._refresh_people()


    def _set_people_sash(self) -> None:
        try:
            width = max(520, int(self.root.winfo_width() * 0.58))
            self.people_paned.sashpos(0, width)
        except tk.TclError:
            pass

    def _on_people_range_changed(self) -> None:
        if getattr(self, "_batch_running", False):
            return
        self._people_page = 0
        self._refresh_people()

    def _on_person_select(self, _event=None) -> None:
        selection = self.people_tree.selection()
        if not selection:
            return
        try:
            user = self.people_users[int(selection[0])]
        except (IndexError, ValueError):
            return
        self._profile_topic_limit = 50
        self._load_profile(user)


    # ------------------------------------------------------------- risk marks
    def _risk_enabled(self) -> bool:
        return bool(self.settings.get("risk_enabled", False))

    def _has_mark_rules(self) -> bool:
        return any(self.blacklist.get(key) for key in ("safe", "warn", "ban"))

    def _apply_risk_ui(self) -> None:
        enabled = self._risk_enabled()
        if hasattr(self, "people_tree"):
            columns = getattr(self, "people_columns", ())
            display = columns if enabled else [column for column in columns if column != "mark"]
            try:
                self.people_tree.configure(displaycolumns=display)
            except tk.TclError:
                pass
        if hasattr(self, "batch_btn") and not getattr(self, "_batch_running", False):
            self.batch_btn.configure(state="normal" if enabled else "disabled", text="一键红绿灯")
        if hasattr(self, "remark_btn") and not getattr(self, "_batch_running", False):
            self.remark_btn.state(["!disabled"] if enabled else ["disabled"])
        if hasattr(self, "include_follows_check") and not getattr(self, "_batch_running", False):
            allow_follow = enabled and bool(self.settings.get("follow_enhance"))
            self.include_follows_check.configure(state="normal" if allow_follow else "disabled")
            if not allow_follow:
                self.include_follows_var.set(False)


    def _on_include_follows_changed(self) -> None:
        if getattr(self, "_batch_running", False):
            return
        if self.include_follows_var.get() and not self.settings.get("follow_enhance"):
            self.include_follows_var.set(False)

    def _on_follow_toggle(self) -> None:
        enabled = bool(self.follow_enhance_var.get())
        if not enabled:
            self.settings["follow_enhance"] = False
            save_settings(self.settings)
            self._refresh_webview_status()
            return
        has_login = self.mode_var.get() == "login" and webview2.has_login_cookie(
            self._request_cookie()
        )
        if not has_login:
            self.follow_enhance_var.set(False)
            self.settings["follow_enhance"] = False
            save_settings(self.settings)
            messagebox.showinfo(
                "需要登录信息",
                "请先点「登录百度」或「手动填写」完成登录，再启用关注检测。",
                parent=self.root,
            )
            self._refresh_webview_status()
            return
        self.settings["follow_enhance"] = True
        save_settings(self.settings)
        self._refresh_webview_status()



    def _on_follow_load_mode_changed(self) -> None:
        value = "manual" if self.follow_load_mode_var.get() == "手动" else "auto"
        self.settings["follow_load_mode"] = value
        save_settings(self.settings)

    def _on_risk_toggle(self) -> None:
        enabled = bool(self.risk_var.get())
        if enabled:
            ok = messagebox.askyesno(
                "启用本地标记",
                """本地标记只用于你自己的记录，请勿用于挂人、骚扰或公开曝光。

确认启用？""",
                parent=self.root,
            )
            if not ok:
                self.risk_var.set(False)
                return
        self.settings["risk_enabled"] = enabled
        save_settings(self.settings)
        self._apply_risk_ui()
        if getattr(self, "people_users", None):
            self._refresh_people()

    # ------------------------------------------------------------------ mode
    def _apply_mode_ui(self) -> None:
        login = self.mode_var.get() == "login"
        state = "normal" if login else "disabled"
        for widget in getattr(self, "cookie_controls", []):
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        if hasattr(self, "cookie_box"):
            if login:
                self.cookie_box.grid()
            else:
                self.cookie_box.grid_remove()
        if hasattr(self, "mode_hint"):
            self.mode_hint.configure(
                text="完整楼中楼 · 关注列表 · 完整资料"
                if login
                else "公开帖子 · 楼中楼按设置补全 · 红绿灯只看发言"
            )
        self._apply_risk_ui()
        self._update_risk_summary()



    def _set_mode(self, mode: str, persist: bool = True) -> None:
        mode = mode if mode in ("guest", "login") else "guest"
        self.mode_var.set(mode)
        if persist:
            self.settings["mode"] = mode
            save_settings(self.settings)
        self._apply_mode_ui()
        if hasattr(self, "_refresh_webview_status"):
            self._refresh_webview_status()


    def _bind_mousewheel_tree(self, widget, canvas) -> None:
        if isinstance(widget, (tk.Text, tk.Listbox, ttk.Treeview)):
            return

        def on_wheel(event) -> str:
            first, last = canvas.yview()
            if (event.delta > 0 and first <= 0.0) or (event.delta < 0 and last >= 1.0):
                return "break"
            canvas.yview_scroll(int(-event.delta / 120), "units")
            return "break"

        widget.bind("<MouseWheel>", on_wheel)
        for child in widget.winfo_children():
            self._bind_mousewheel_tree(child, canvas)









    def _popup_tree_menu(self, tree, menu, event) -> None:
        row = tree.identify_row(event.y)
        if row:
            tree.selection_set(row)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()














    def _on_main_tab_changed(self, _event=None) -> None:
        if self.notebook.select() != str(self.tab_settings):
            self._set_cache_stats_timer(False)
            return
        index = 0
        if self.settings.get("settings_start") == "last":
            index = getattr(self, "_last_settings_index", 0)
        if 0 <= index < self.settings_nav.size():
            self.settings_nav.selection_clear(0, "end")
            self.settings_nav.selection_set(index)
            self._show_settings_page(index)


    def _focus_local_marks(self) -> None:
        self.notebook.select(self.tab_settings)
        self.root.after_idle(self._show_local_marks_page)

    def _show_local_marks_page(self) -> None:
        self.settings_nav.selection_clear(0, "end")
        self.settings_nav.selection_set(3)
        self._last_settings_index = 3
        self._show_settings_page(3)
        editor = self.blacklist_editors.get("safe")
        if editor is not None:
            editor.focus_set()
            editor.see("1.0")

















    def _prepare_accent_popup(self) -> None:
        """让强调色下拉列表只使用当前主题的选中色，避免残留粉色/橘色行。"""
        try:
            popdown = str(
                self.root.tk.call("ttk::combobox::PopdownWindow", self.accent_combo)
            )
            listbox = f"{popdown}.f.l"
            self.root.tk.call(
                listbox,
                "configure",
                "-background",
                self.palette["surface"],
                "-foreground",
                self.palette["text"],
                "-selectbackground",
                self.palette["selection_bg"],
                "-selectforeground",
                self.palette["selection_text"],
                "-activestyle",
                "none",
            )
        except tk.TclError:
            pass

    def _on_accent_changed(self) -> None:
        accent = {
            "蓝色": "blue",
            "绿色": "green",
            "紫色": "purple",
            "橘黄": "orange",
            "粉色": "pink",
            "青色": "cyan",
            "红色": "red",
        }.get(self.accent_var.get(), "blue")
        self.settings["accent"] = accent
        save_settings(self.settings)
        self._apply_theme()









    def _center_toplevel(self, win: tk.Toplevel, width: int = 0, height: int = 0) -> None:
        win.update_idletasks()
        width = width or win.winfo_reqwidth()
        height = height or win.winfo_reqheight()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        win.geometry(f"+{x}+{y}")



    def _set_cache_stats_timer(self, enabled: bool) -> None:
        timer = getattr(self, "_cache_stats_timer", None)
        if timer is not None:
            try:
                self.root.after_cancel(timer)
            except tk.TclError:
                pass
            self._cache_stats_timer = None
        if enabled:
            self._cache_stats_timer = self.root.after(2000, self._cache_stats_tick)

    def _cache_stats_tick(self) -> None:
        self._cache_stats_timer = None
        self._notify_cache_eviction()
        self._refresh_cache_stats()
        self._cache_stats_timer = self.root.after(2000, self._cache_stats_tick)

    def _notify_cache_eviction(self) -> None:
        if getattr(self, "_cache_eviction_notified", False):
            post_cache().take_eviction_notice()
            return
        count = post_cache().take_eviction_notice()
        if not count:
            return
        self._cache_eviction_notified = True
        text = "缓存已达上限，已淘汰部分旧缓存；不影响本次标记和导出。"
        self.status_var.set(text)
        self._append_log(text, "muted")

    def _refresh_cache_stats_if_visible(self) -> None:
        if getattr(self, "_cache_stats_timer", None) is not None:
            self._refresh_cache_stats()

    def _refresh_cache_stats(self) -> None:
        label = getattr(self, "cache_stats_label", None)
        if label is None:
            return
        try:
            stats = post_cache().stats()
            label.configure(
                text=(
                    f"热内存：{stats['hot_users']} 人 / {stats['hot_bytes'] / 1024 / 1024:.1f} MB；"
                    f"冷库：{stats['cold_users']} 人 / {stats['cold_posts']} 条 / "
                    f"{stats['cold_bytes'] / 1024 / 1024:.1f} MB（上限 {stats['limit_mb']} MB）"
                )
            )
        except Exception as error:  # noqa: BLE001
            label.configure(text=f"缓存状态读取失败：{error}")

    def _clear_post_cache(self) -> None:
        if not messagebox.askyesno(
            "清除发言缓存",
            "清除本次运行的发言缓存？\n不会删除 Excel、本地标记或最近结果。",
            parent=self.root,
        ):
            return
        clear_post_cache()
        for name in ("_lookup_cache", "_profile_cache", "_batch_cache"):
            value = getattr(self, name, None)
            if isinstance(value, dict):
                value.clear()
        self._refresh_cache_stats()
        self._append_log("发言缓存已清除。", "muted")


    def _on_save_result_toggle(self) -> None:
        self.settings["save_result"] = bool(self.save_result_var.get())
        save_settings(self.settings)
        if not self.save_result_var.get():
            clear_stored_result()

    def _on_encrypt_toggle(self) -> None:
        self.settings["encrypt_result"] = bool(self.encrypt_var.get())
        save_settings(self.settings)
        if self.last_threads:
            self._persist_result(self.last_threads)


    def _on_restore_mode_changed(self) -> None:
        self.settings["restore_mode"] = "ask" if self.restore_mode_var.get() == "询问" else "auto"
        save_settings(self.settings)

    def _clear_result(self) -> None:
        if not messagebox.askyesno(
            "删除当前结果",
            "删除本机保存的当前结果？不会删除已导出的 Excel、Markdown 或本地标记；删除后不可撤销。",
            parent=self.root,
            default=messagebox.NO,
        ):
            return
        clear_stored_result()
        self.last_threads = []
        self.last_output = None
        self.open_btn.configure(state="disabled")
        self._refresh_people()
        self._refresh_grid()
        self._append_log("当前结果已删除。", "muted")

    def _cleanup_old_results(self) -> None:
        files = stored_old_files()
        if not files:
            self.status_var.set("没有需要清理的旧版本结果")
            return
        if not messagebox.askyesno(
            "清理旧版本结果",
            f"删除 {len(files)} 个旧版本结果文件？不会影响当前结果。",
            parent=self.root,
            default=messagebox.NO,
        ):
            return
        for path in files:
            try:
                safe_remove_file(path)
            except (OSError, ValueError):
                pass
        self._refresh_old_files_label()
        self._append_log(f"已清理旧版本结果：{len(files)} 个", "muted")

    def _refresh_old_files_label(self) -> None:
        if not hasattr(self, "old_files_label"):
            return
        files = stored_old_files()
        size = 0
        for path in files:
            try:
                size += os.path.getsize(path)
            except OSError:
                pass
        self.old_files_label.configure(
            text=f"旧版本残留：{len(files)} 个，{size / 1024 / 1024:.1f} MB"
        )

    def _open_notice(self) -> None:
        path = os.path.join(resource_dir(), "THIRD_PARTY_NOTICES.md")
        if not os.path.isfile(path):
            messagebox.showinfo("第三方许可", "许可文件未找到。", parent=self.root)
            return
        existing = getattr(self, "_notice_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                existing.focus_set()
                return
        except tk.TclError:
            pass
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError as error:
            messagebox.showerror("打不开许可文件", friendly_error(error), parent=self.root)
            return
        win = tk.Toplevel(self.root)
        self._notice_window = win
        win.title("第三方许可")
        win.geometry("760x600")
        win.minsize(560, 360)
        win.configure(bg="#eef1f5")
        win.transient(self.root)
        frame = tk.Frame(win, bg="#eef1f5", padx=10, pady=8)
        frame.pack(fill="both", expand=True)
        top = tk.Frame(frame, bg="#eef1f5")
        top.pack(fill="x", pady=(0, 6))
        tk.Label(
            top, text="第三方组件与许可", bg="#eef1f5", fg="#1F4E79",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(side="left")
        ttk.Button(top, text="关闭", command=win.destroy, width=8).pack(side="right")
        text = tk.Text(
            frame, wrap="word", font=("Microsoft YaHei UI", 9), relief="flat",
            padx=10, pady=8, bg="#fbfcfe", state="disabled",
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.configure(state="normal")
        text.insert("1.0", content)
        text.configure(state="disabled")
        self._theme_widget_tree(win)
        self._center_toplevel(win, 760, 600)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.focus_set()

    def _open_folder(self, path: str) -> None:
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as error:
            messagebox.showerror("打不开目录", friendly_error(error), parent=self.root)



    def _offline_checks(self) -> list[tuple[str, str, str]]:
        results: list[tuple[str, str, str]] = []

        def check(name: str, condition: bool, detail: str = "") -> None:
            results.append((name, "PASS" if condition else "FAIL", detail))

        check(
            "允许百度登录域名",
            webview2.is_allowed_url("https://passport.baidu.com/v2/?login"),
        )
        check(
            "拒绝非白名单域名",
            not webview2.is_allowed_url("https://example.com/"),
        )
        check(
            "接受 TIEBA_SID 登录态",
            webview2.has_login_cookie({"TIEBA_SID": "test"}),
        )
        check(
            "匿名 Cookie 不算登录",
            not webview2.has_login_cookie({"BAIDUID": "test"}),
        )
        filtered = webview2.filter_cookies(
            [
                {"name": "BDUSS", "value": "secret", "domain": ".baidu.com", "path": "/"},
                {"name": "BAIDUID", "value": "anonymous", "domain": ".baidu.com", "path": "/"},
            ],
            anonymous=True,
        )
        check("游客过滤 BDUSS", "BDUSS" not in filtered and "BAIDUID" in filtered)
        merged = webview2.filter_cookies(
            [
                {"name": "X", "value": "root", "domain": ".baidu.com", "path": "/"},
                {"name": "X", "value": "tieba", "domain": ".tieba.baidu.com", "path": "/p/1"},
            ],
            anonymous=False,
        )
        check("同名 Cookie 取更具体 path", merged.get("X") == "tieba")
        check("WebView2 组件可用", webview2.available(), "仅信息，不强制安装")
        return results



    def _simulate_captcha(self, _event=None, scenario: str = "") -> None:
        """隐藏测试入口：不发网络请求，只走验证码处理流程。"""
        if self._network_task_active() or getattr(self, "_active_choice_window", None):
            return
        restore = None
        if scenario in ("guest", "cookie", "bduss"):
            restore = (
                self.mode_var.get(),
                self.login_method_var.get(),
            )
            if scenario == "guest":
                self.mode_var.set("guest")
            else:
                self.mode_var.set("login")
                self.login_method_var.set(scenario)
                self._on_login_method_changed()
        self._simulated_restore = restore
        self._append_log("模拟验证码：未发出网络请求，仅测试界面流程。", "muted")
        self._simulated_captcha = True
        self._set_running(True)
        self.root.after(
            20,
            lambda: self._handle_message(
                (
                    "captcha",
                    "模拟验证码：未发出网络请求，仅用于测试界面流程。",
                    [],
                )
            ),
        )





    def _ask_choice(self, title: str, message: str, choices, default: int = 0):
        """带明确按钮文案的模态选择框；choices=[(label,value),...]，None 表示取消。"""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg="#ffffff")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        self._active_choice_window = win
        frame = tk.Frame(win, bg="#ffffff", padx=20, pady=16)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text=title,
            bg="#ffffff",
            fg="#1f2937",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            frame,
            text=message,
            bg="#ffffff",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
            wraplength=440,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(8, 14))
        result: Dict[str, Any] = {"value": None}
        buttons = tk.Frame(frame, bg="#ffffff")
        buttons.pack(fill="x")

        def finish(value) -> None:
            result["value"] = value
            win.destroy()

        def command(value):
            return lambda: finish(value)

        for index in range(len(choices) - 1, -1, -1):
            label, value = choices[index]
            if index == default:
                tk.Button(
                    buttons,
                    text=label,
                    command=command(value),
                    bg="#1F4E79",
                    fg="#ffffff",
                    activebackground="#163b5c",
                    activeforeground="#ffffff",
                    relief="flat",
                    padx=14,
                    pady=5,
                    cursor="hand2",
                    font=("Microsoft YaHei UI", 9, "bold"),
                ).pack(side="right", padx=(8, 0))
            else:
                ttk.Button(buttons, text=label, command=command(value)).pack(
                    side="right", padx=(8, 0)
                )
        win.bind("<Return>", lambda _event: finish(choices[default][1]))
        win.bind("<Escape>", lambda _event: finish(None))
        win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
        win.update_idletasks()
        width = max(win.winfo_reqwidth(), buttons.winfo_reqwidth() + 40)
        height = win.winfo_reqheight()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        self._theme_widget_tree(win)
        win.geometry(f"{width}x{height}+{x}+{y}")
        self.root.wait_window(win)
        if getattr(self, "_active_choice_window", None) is win:
            self._active_choice_window = None
        return result["value"]





    def _capture_ui_pack_state(self) -> None:
        if hasattr(self, "_ui_pack_widgets"):
            return
        widgets = [
            self.follow_load_row,
            self.proxy_row,
            self.batch_row,
            self.lookup_fill_box,
            self.cache_box,
            self.log_box,
            self.encrypt_check,
            self.old_result_buttons,
        ]
        options: Dict[Any, Dict[str, Any]] = {}
        next_widgets: Dict[Any, Any] = {}
        for widget in widgets:
            info = dict(widget.pack_info())
            info.pop("in", None)
            info.pop("in_", None)
            options[widget] = info
            siblings = widget.master.pack_slaves()
            try:
                index = siblings.index(widget)
            except ValueError:
                continue
            next_widgets[widget] = siblings[index + 1] if index + 1 < len(siblings) else None
        self._ui_pack_widgets = widgets
        self._ui_pack_options = options
        self._ui_pack_next = next_widgets

    def _restore_ui_pack_widgets(self) -> None:
        self._capture_ui_pack_state()
        for widget in reversed(self._ui_pack_widgets):
            info = dict(self._ui_pack_options.get(widget) or {})
            if not info:
                continue
            next_widget = self._ui_pack_next.get(widget)
            while next_widget is not None and not next_widget.winfo_manager():
                next_widget = self._ui_pack_next.get(next_widget)
            if next_widget is not None and next_widget.winfo_manager():
                widget.pack(**info, before=next_widget)
            else:
                widget.pack(**info)




    def _open_guide_from_banner(self, banner) -> None:
        banner.destroy()
        self._open_usage_window()

    def _maybe_onboarding(self) -> None:
        if self.settings.get("onboarding_seen"):
            return
        self.settings["onboarding_seen"] = True
        save_settings(self.settings)
        banner = tk.Frame(self.root, bg="#fff7e6", padx=14, pady=7)
        banner.pack(fill="x", before=self.notebook)
        tk.Label(
            banner,
            text="首次使用：默认匿名；红绿灯/本地标记只存本机；关注增强默认关闭，可在设置里开启。",
            bg="#fff7e6",
            fg="#7c4a03",
            font=("Microsoft YaHei UI", 9),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            banner,
            text="查看说明",
            command=lambda: self._open_guide_from_banner(banner),
            width=8,
        ).pack(side="right", padx=(6, 0))
        ttk.Button(banner, text="关闭", command=banner.destroy, width=6).pack(side="right", padx=(6, 0))
        self._theme_widget_tree(banner)


    def _restore_defaults(self) -> None:
        if not messagebox.askyesno(
            "恢复默认设置",
            "只重置设置，保留结果、本地标记和 BDUSS。继续？",
            parent=self.root,
            default=messagebox.NO,
        ):
            return
        keep_onboarding = bool(self.settings.get("onboarding_seen"))
        keep_geometry = self.settings.get("window_geometry", "")
        keep_webview_remember = bool(self.settings.get("webview_remember_login", False))
        self.settings = load_settings()
        self.settings["onboarding_seen"] = keep_onboarding
        self.settings["window_geometry"] = keep_geometry
        self.settings["webview_remember_login"] = keep_webview_remember
        save_settings(self.settings)
        self._apply_settings_to_ui()
        self._append_log("设置已恢复默认（结果、标记、BDUSS 保留）。", "muted")



    def _apply_proxy(self) -> None:
        var = getattr(self, "proxy_mode_var", None)
        mode = {"跟随系统": "system", "不使用": "none", "自定义": "custom"}.get(
            var.get() if var is not None else "跟随系统",
            "system",
        )
        if mode == "custom":
            Fetcher.DEFAULT_PROXY = self.proxy_url_var.get().strip() or None
        elif mode == "none":
            Fetcher.DEFAULT_PROXY = ""
        else:
            Fetcher.DEFAULT_PROXY = None

    def _on_proxy_changed(self) -> None:
        mode = {"跟随系统": "system", "不使用": "none", "自定义": "custom"}.get(
            self.proxy_mode_var.get(), "system"
        )
        self.settings["proxy_mode"] = mode
        self.settings["proxy_url"] = self.proxy_url_var.get().strip()
        save_settings(self.settings)
        self._apply_proxy()
        self._update_risk_summary()

    def _on_batch_concurrency_changed(self) -> None:
        try:
            value = int(self.batch_concurrency_var.get())
        except ValueError:
            value = 1
        self.settings["batch_concurrency"] = max(1, min(3, value))
        save_settings(self.settings)



    def _update_risk_summary(self) -> None:
        if not hasattr(self, "risk_summary_label"):
            return
        items = self._high_risk_items()
        self.risk_summary_label.configure(
            text=("风险：" + " · ".join(items)) if items else "风险：无高风险设置"
        )









    def _on_mark_rules_changed(self) -> None:
        self._marks_stale = True
        if hasattr(self, "people_hint"):
            self.people_hint.configure(
                text="标记规则已变更，可点「重新标记（本地）」；不会自动联网"
            )

    def _save_blacklist_from_tab(self) -> None:
        data = {
            key: [line.strip() for line in editor.get("1.0", "end").splitlines() if line.strip()]
            for key, editor in self.blacklist_editors.items()
        }
        if save_blacklist(data):
            self.blacklist = data
            self.settings_hint.configure(text="已保存")
            self._on_mark_rules_changed()
            self._append_log("本地标记已保存。", "ok")
        else:
            self.settings_hint.configure(text="保存失败")

    def _blacklist_from_editors(self) -> dict:
        return {
            key: [line.strip() for line in editor.get("1.0", "end").splitlines() if line.strip()]
            for key, editor in self.blacklist_editors.items()
        }

    def _export_blacklist(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出本地标记",
            defaultextension=".xlsx",
            initialfile="贴吧本地标记.xlsx",
            filetypes=[("Excel 表格", "*.xlsx")],
        )
        if not path:
            return
        if export_blacklist_xlsx(path, self._blacklist_from_editors()):
            self.settings_hint.configure(text=f"已导出：{os.path.basename(path)}")
            self._append_log(f"本地标记已导出：{path}", "ok")
        else:
            messagebox.showerror("导出失败", "无法写入文件，请换个位置重试。", parent=self.root)

    def _import_blacklist(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="导入本地标记",
            filetypes=[("Excel 表格", "*.xlsx"), ("所有文件", "*.*")],
        )
        if not path:
            return
        data = import_blacklist_xlsx(path)
        total = sum(len(value) for value in data.values())
        if not total:
            messagebox.showwarning(
                "没有读到数据",
                "格式应为两列：\n第一列 类别（安全 / 可疑 / 警告）\n第二列 贴吧名\n\n"
                "可以用「导出 Excel」生成模板后再填。",
                parent=self.root,
            )
            return
        existing_total = sum(len(value) for value in self.blacklist.values())
        merged = merge_blacklists(self.blacklist, data)
        merged_total = sum(len(value) for value in merged.values())
        imported_total = total
        choice = self._ask_choice(
            "导入方式",
            f"现有 {existing_total} 条；导入 {imported_total} 条。"
            f"合并后 {merged_total} 条；覆盖后 {imported_total} 条。",
            [("覆盖（默认）", False), ("合并（保留现有）", True), ("取消", None)],
            default=0,
        )
        if choice is None:
            return
        if choice:
            data = merge_blacklists(self.blacklist, data)
        if save_blacklist(data):
            self.blacklist = data
            for key, editor in self.blacklist_editors.items():
                editor.delete("1.0", "end")
                editor.insert("1.0", "\n".join(data[key]))
            self.settings_hint.configure(text="已导入")
            self._on_mark_rules_changed()
            self._append_log(f"本地标记已导入：{path}", "ok")
        else:
            messagebox.showerror("导入失败", "保存失败，请检查配置目录权限。", parent=self.root)



    def _apply_table_density(self) -> None:
        compact = self.settings.get("table_density") == "compact"
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=25 if compact else 31)

    def _on_table_density_changed(self) -> None:
        self.settings["table_density"] = "compact" if self.table_density_var.get() == "紧凑" else "comfortable"
        save_settings(self.settings)
        self._apply_table_density()




        # 参与者对比已确认砍掉，不再创建入口。

    def _add_compare_tab(self) -> None:
        frame = tk.Frame(self.grid_nb)
        self.grid_nb.add(frame, text="  参与者对比  ")
        top = tk.Frame(frame, bg="#ffffff", padx=8, pady=6)
        top.pack(fill="x")
        tk.Label(top, text="勾选帖子：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.compare_vars = []
        for index, thread in enumerate(self.last_threads):
            var = tk.BooleanVar(value=index < 2)
            label = display_text(thread.meta.title or thread.meta.tid)[:16]
            tk.Checkbutton(
                top, text=label, variable=var, bg="#ffffff", anchor="w", font=("Microsoft YaHei UI", 8)
            ).pack(side="left", padx=(2, 0))
            self.compare_vars.append(var)
        self.compare_mode_var = tk.StringVar(value="交集")
        ttk.Combobox(top, values=MODES, textvariable=self.compare_mode_var, width=8, state="readonly").pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(top, text="生成对比", command=self._generate_compare, width=10).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(top, text="导出结果", command=self._export_compare, width=10).pack(
            side="left", padx=(4, 0)
        )
        self.compare_tree = ttk.Treeview(frame, columns=(), show="headings")
        self.compare_tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.compare_result: Optional[tuple] = None

    def _generate_compare(self) -> None:
        selected = [index for index, var in enumerate(self.compare_vars) if var.get()]
        if len(selected) < 2:
            self.grid_hint.configure(text="至少勾选 2 个帖子才能对比")
            return
        try:
            result = compare_threads(self.last_threads, selected, self.compare_mode_var.get())
        except ValueError as error:
            self.grid_hint.configure(text=friendly_error(error))
            return
        headers = ["昵称", "用户名", "用户ID"] + result["threads"] + ["合计", "类型"]
        columns = [str(index) for index in range(len(headers))]
        self.compare_tree.configure(columns=columns)
        for index, header in enumerate(headers):
            self.compare_tree.heading(columns[index], text=header)
            self.compare_tree.column(
                columns[index],
                width=110 if header in ("昵称", "用户名") else 70,
                anchor="w" if header in ("昵称", "用户名") else "center",
            )
        for item in self.compare_tree.get_children():
            self.compare_tree.delete(item)
        rows = []
        for row in result["rows"]:
            values = [
                display_text(row["name"]),
                row["username"],
                row["uid"],
            ] + row["counts"] + [row["total"], row["type"]]
            rows.append([str(value) for value in values])
            self.compare_tree.insert("", "end", values=values)
        self.compare_result = (headers, rows)

    def _compare_label(self, index: int) -> str:
        selected = [i for i, var in enumerate(getattr(self, "compare_vars", [])) if var.get()]
        if index < len(selected):
            thread = self.last_threads[selected[index]]
            return display_text(thread.meta.title or thread.meta.tid)
        return ""

    def _export_compare(self) -> None:
        if not self.compare_result:
            self.grid_hint.configure(text="先生成对比结果")
            return
        from openpyxl import Workbook

        path = filedialog.asksaveasfilename(
            title="导出对比结果",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
            initialfile="参与者对比.xlsx",
            parent=self.root,
        )
        if not path:
            return
        headers, rows = self.compare_result
        book = Workbook()
        sheet = book.active
        sheet.title = "参与者对比"
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        notes = book.create_sheet("导出说明")
        notes.append(["项目", "内容"])
        notes.append(["对比模式", self.compare_mode_var.get()])
        notes.append(["勾选帖子数", str(len(rows))])
        notes.append(["A", self._compare_label(0)])
        notes.append(["B", self._compare_label(1)])
        notes.append(["软件版本", VERSION])
        notes.append(["生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        notes.append(["结果行数", str(len(rows))])
        selected = [i for i, var in enumerate(getattr(self, "compare_vars", [])) if var.get()]
        warnings = sum(len(self.last_threads[i].warnings) for i in selected)
        notes.append(["数据警告", str(warnings) if warnings else "无"])
        book.save(path)
        self._append_log(f"对比结果已导出：{path}", "ok")

    _SORT_ONLY_HEADERS = {"日期", "等级", "楼层", "楼中楼", "合计", "所在楼层", "#"}
    _TEXT_FILTER_HEADERS = {
        "类型", "标记", "昵称", "回复者", "用户名", "贴吧ID", "用户ID", "头衔",
        "内容", "帖子", "贴吧", "标题", "来源",
    }

    def _anchor_point(self, anchor: Optional[tuple]) -> tuple:
        if anchor:
            return int(anchor[0]), int(anchor[1])
        return self.root.winfo_pointerx(), self.root.winfo_pointery()

    def _place_filter_window(self, win, anchor: Optional[tuple], fallback_width: int = 320) -> None:
        x, y = self._anchor_point(anchor)
        win.update_idletasks()
        width = max(fallback_width, win.winfo_width())
        height = max(120, win.winfo_height())
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        left = x
        top = y + 6
        if left + width > screen_w - 8:
            left = max(8, screen_w - width - 8)
        if top + height > screen_h - 8:
            top = max(8, y - height - 6)
        win.geometry(f"{width}x{height}+{left}+{top}")



    def _loaded_filter_state(self, tree) -> dict:
        state = getattr(tree, "_loaded_filter_state", None)
        if state is None:
            state = {"all": list(tree.get_children()), "filters": {}}
            setattr(tree, "_loaded_filter_state", state)  # noqa: B010
        return state

    def _clear_loaded_tree(self, tree) -> None:
        state = getattr(tree, "_loaded_filter_state", None)
        for iid in (state["all"] if state else list(tree.get_children())):
            try:
                tree.delete(iid)
            except tk.TclError:
                pass
        if hasattr(tree, "_loaded_filter_state"):
            delattr(tree, "_loaded_filter_state")

    def _apply_loaded_filters(self, tree) -> None:
        state = self._loaded_filter_state(tree)
        filters = state["filters"]
        for iid in state["all"]:
            tree.detach(iid)
        for iid in state["all"]:
            keep = True
            for column, selected in filters.items():
                value = tree.set(iid, column)
                if isinstance(selected, tuple):
                    start_date, end_date = selected
                    day = value[:10]
                    if (start_date and (not day or day < start_date)) or (
                        end_date and (not day or day > end_date)
                    ):
                        keep = False
                        break
                elif selected and value not in selected:
                    keep = False
                    break
            if keep:
                tree.reattach(iid, "", "end")

    def _filter_loaded_tree(
        self, tree, column: str, title: str, date_column: bool = False, anchor: Optional[tuple] = None
    ) -> None:
        state = self._loaded_filter_state(tree)
        chosen: Any
        if date_column:
            current = state["filters"].get(column)
            chosen = self._filter_date_dialog(title, current, anchor)
            if chosen is None:
                return
            if chosen[0] or chosen[1]:
                state["filters"][column] = chosen
            else:
                state["filters"].pop(column, None)
        else:
            values = sorted({tree.set(iid, column) for iid in state["all"]})
            current = state["filters"].get(column)
            chosen = self._filter_text_dialog(title, values, current, anchor)
            if chosen is None:
                return
            if chosen:
                state["filters"][column] = chosen
            else:
                state["filters"].pop(column, None)
        self._apply_loaded_filters(tree)

    def _bind_loaded_filter(self, tree, mapping: Dict[str, Optional[tuple]]) -> None:
        def event_handler(event):
            if tree.identify_region(event.x, event.y) != "heading":
                return None
            column = tree.identify_column(event.x)
            keys = list(mapping)
            try:
                index = int(column[1:]) - 1
                key = keys[index]
                spec = mapping.get(key)
                if not spec:
                    return None
                title, is_date = spec
            except (ValueError, IndexError, KeyError):
                return None
            self._filter_loaded_tree(tree, key, title, is_date, (event.x_root, event.y_root))
            return "break"

        def left_handler(event):
            if tree.identify_region(event.x, event.y) != "heading":
                return None
            column = tree.identify_column(event.x)
            keys = list(mapping)
            try:
                index = int(column[1:]) - 1
                key = keys[index]
                spec = mapping.get(key)
                if not spec or spec[1]:
                    return None
            except (ValueError, IndexError, KeyError):
                return None
            self._filter_loaded_tree(tree, key, spec[0], False, (event.x_root, event.y_root))
            return "break"

        tree.bind("<Button-3>", event_handler, add="+")
        tree.bind("<Button-1>", left_handler, add="+")

    def _header_filterable(self, header: str) -> bool:
        return header in self._TEXT_FILTER_HEADERS or header == "日期"


    def _people_filter_active(self) -> bool:
        if self.people_keyword_var.get().strip():
            return True
        if self.people_level_var.get() != "全部":
            return True
        if self._risk_enabled() and self.people_mark_var.get() != "全部":
            return True
        if self.people_min_var.get().strip() or self.people_max_var.get().strip():
            return True
        if getattr(self, "_people_col_filters", {}):
            return True
        return False

    def _visible_people(self) -> list:
        users = filter_users(
            self.people_users,
            keyword=self.people_keyword_var.get(),
            field=self.people_field_var.get(),
            level=self.people_level_var.get(),
            mark=self.people_mark_var.get() if self._risk_enabled() else "全部",
            min_level=_optional_int(self.people_min_var.get()),
            max_level=_optional_int(self.people_max_var.get()),
        )
        for column, selected in getattr(self, "_people_col_filters", {}).items():
            if selected:
                users = [
                    user for user in users
                    if self._people_column_value(user, column) in selected
                ]
        return users

    def _filtered_threads(self) -> list:
        from dataclasses import replace

        selected = set()
        filtered = self._visible_people()
        for user in filtered:
            for value in (user.get("uid"), user.get("username"), user.get("name")):
                if value:
                    selected.add(str(value))
        result = []
        for thread in self.last_threads:
            floors = [
                floor
                for floor in thread.floors
                if str(floor.author_id) in selected
                or str(floor.author_name) in selected
                or str(floor.author) in selected
            ]
            comments = [
                comment
                for comment in thread.comments
                if str(comment.author_id) in selected
                or str(comment.author_name) in selected
                or str(comment.author) in selected
            ]
            result.append(replace(thread, floors=floors, comments=comments))
        return result

    def _filter_summary(self) -> str:
        if not self._people_filter_active():
            return "无"
        parts = []
        keyword = self.people_keyword_var.get().strip()
        if keyword:
            parts.append(f"关键词「{keyword}」")
        level = self.people_level_var.get()
        if level and level not in ("全部", "无等级"):
            parts.append(f"等级 {level}")
        elif level == "无等级":
            parts.append("等级 无")
        mark = self.people_mark_var.get()
        if mark and mark != "全部":
            parts.append(f"标记 {mark}")
        for column, selected in getattr(self, "_people_col_filters", {}).items():
            if selected:
                title = {"mark": "标记", "name": "昵称", "username": "用户名", "uid": "用户ID"}.get(column, column)
                parts.append(f"{title}筛选 {len(selected)} 项")
        return "；".join(parts) or "无"

    def _expand_large_threads(self, threads, limit: int = 500_000):
        result: list = []
        for thread in threads:
            size = len(thread.floors) + len(thread.comments)
            if size <= limit:
                result.append(thread)
                continue
            by_floor: Dict[int, List] = {}
            for comment in thread.comments:
                by_floor.setdefault(comment.floor_no, []).append(comment)
            groups: list = []
            part_floors: list = []
            part_comments: list = []
            rows = 0
            for floor in thread.floors:
                comments = by_floor.pop(floor.post_no, [])
                block = 1 + len(comments)
                if block > limit:
                    if part_floors or part_comments:
                        groups.append((part_floors, part_comments))
                        part_floors, part_comments, rows = [], [], 0
                    chunk_size = max(1, limit - 1)
                    for start in range(0, len(comments), chunk_size):
                        groups.append(([floor], comments[start : start + chunk_size]))
                    continue
                if part_floors and rows + block > limit:
                    groups.append((part_floors, part_comments))
                    part_floors, part_comments, rows = [], [], 0
                part_floors.append(floor)
                part_comments.extend(comments)
                rows += block
            for comments in by_floor.values():
                if not comments:
                    continue
                if part_floors or part_comments:
                    groups.append((part_floors, part_comments))
                    part_floors, part_comments, rows = [], [], 0
                chunk_size = max(1, limit)
                for start in range(0, len(comments), chunk_size):
                    groups.append(([], comments[start : start + chunk_size]))
            if part_floors or part_comments:
                groups.append((part_floors, part_comments))
            total = len(groups)
            for index, (floors, comments) in enumerate(groups, start=1):
                meta = replace(
                    thread.meta,
                    title=f"{thread.meta.title or thread.meta.tid}（分片 {index}/{total}）",
                )
                result.append(
                    replace(
                        thread,
                        meta=meta,
                        floors=list(floors),
                        comments=list(comments),
                    )
                )
        return result






    def _user_bar(self, user) -> str:
        """这个用户参与的是哪个吧（多帖子时取他出现过的第一个帖子的吧）。"""
        uid = user.get("uid") or ""
        name = user.get("name") or ""
        for thread in self.last_threads:
            for floor in thread.floors:
                if (uid and floor.author_id == uid) or (not uid and floor.author == name):
                    return thread.meta.forum
            for comment in thread.comments:
                if (uid and comment.author_id == uid) or (not uid and comment.author == name):
                    return thread.meta.forum
        return self.last_threads[0].meta.forum if self.last_threads else ""

    def _post_count(self, fallback: int = 50) -> int:
        try:
            count = int(self.post_count_var.get())
        except (AttributeError, ValueError):
            count = fallback
        return max(5, min(1000, count))

    def _date_params(self):
        if self.post_date_mode_var.get() == "指定日期":
            return self._group_date(self.post_start_parts), self._group_date(self.post_end_parts)
        return "", ""

    def _set_people_controls_enabled(self, enabled: bool) -> None:
        readonly = "readonly" if enabled else "disabled"
        disabled = "normal" if enabled else "disabled"
        for name, state in (
            ("post_count_box", "normal" if enabled else "disabled"),
            ("post_date_mode_box", readonly),
            ("post_prefer_box", readonly),
            ("people_range_box", readonly),
            ("people_field_box", readonly),
            ("people_keyword_entry", "normal" if enabled else "disabled"),
            ("people_level_box", readonly),
            ("people_min_entry", "normal" if enabled else "disabled"),
            ("people_max_entry", "normal" if enabled else "disabled"),
            ("people_reset_btn", disabled),
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(state=state)
                except tk.TclError:
                    pass



    def _hidden_follows(self, profile) -> bool:
        return bool(profile.get("followed_private")) or profile.get("priv_like") == 3

    def _follow_incomplete(self, profile) -> bool:
        """关注列表是否不完整；游客、无 BDUSS、隐藏关注都需要候选探测。"""
        if profile.get("followed_forums"):
            return False
        if profile.get("follow_loaded") and not self._hidden_follows(profile) and not profile.get("follow_error"):
            return False
        return True








    def _apply_level_to_threads(self, user, level: str) -> None:
        """把某个人的本吧等级写回楼层/楼中楼数据，刷新和导出时都不会丢。"""
        level = str(level or "").strip()
        if level in ("", "0", "None"):
            return
        uid = user.get("uid") or ""
        username = user.get("username") or ""
        name = user.get("name") or ""
        portrait = str(user.get("portrait") or "").split("?")[0]
        for thread in self.last_threads:
            for floor in thread.floors:
                match = (
                    (uid and floor.author_id == uid)
                    or (portrait and str(floor.portrait or "").split("?")[0] == portrait)
                    or (not uid and username and floor.author_name == username)
                    or (not uid and not username and floor.author == name)
                )
                if match and not floor.level:
                    floor.level = level
            for comment in thread.comments:
                match = (
                    (uid and comment.author_id == uid)
                    or (portrait and str(comment.portrait or "").split("?")[0] == portrait)
                    or (not uid and username and comment.author_name == username)
                    or (not uid and not username and comment.author == name)
                )
                if match and not comment.level:
                    comment.level = level




    def _row_tags(self, bar, kind: str):
        if not self._risk_enabled():
            return ()
        key = "color_forum" if kind == "forum" else "color_posts"
        if not getattr(self, "settings", {}).get(key, True):
            return ()
        level, _ = classify([bar], getattr(self, "blacklist", {}))
        return (level,) if level else ()

    def _merge_forum_lists(self, profile, bar_name: str = "", bar_level: str = "") -> list:
        forums = profile.get("followed_forums") or []
        hidden = profile.get("hidden_forums") or []
        base = forums or hidden
        merged = {}
        for forum in base:
            name = forum.get("name")
            if not name:
                continue
            item = dict(forum)
            if forums:
                item["source"] = "公开关注"
            elif "BDUSS" in str(profile.get("follow_error") or ""):
                item["source"] = "profile片段"
            else:
                item["source"] = "隐藏关注"
            item["level_source"] = "官方" if int(item.get("level") or 0) > 0 else "-"
            merged[name] = item
        if not forums:
            for forum in profile.get("like_forum") or []:
                name = forum.get("name")
                if name and name not in merged:
                    merged[name] = {
                        "name": name,
                        "level": 0,
                        "level_name": "",
                        "source": "精选",
                        "level_source": "-",
                    }
        if bar_name and bar_level:
            name = bar_name[:-1] if bar_name.endswith("吧") and len(bar_name) > 2 else bar_name
            level_int = int(bar_level or 0)
            if name and level_int > 0:
                existing = merged.get(name)
                if existing is None:
                    merged[name] = {
                        "name": name,
                        "level": level_int,
                        "level_name": "",
                        "source": "等级",
                        "level_source": "主题",
                    }
                elif not existing.get("level"):
                    existing["level"] = level_int
                    existing["level_source"] = "主题"
        for forum in profile.get("probed_forums") or []:
            name = forum.get("name")
            if not name:
                continue
            existing = merged.get(name)
            if existing is None:
                merged[name] = {
                    "name": name,
                    "level": int(forum.get("level") or 0),
                    "level_name": forum.get("level_name") or "",
                    "source": "候选确认",
                    "level_source": "官方" if int(forum.get("level") or 0) > 0 else "-",
                }
            elif existing.get("source") != "公开关注":
                if int(forum.get("level") or 0) > int(existing.get("level") or 0):
                    existing["level"] = int(forum.get("level") or 0)
                existing["source"] = "候选确认"
        if self.settings.get("love_level_enabled", False):
            for forum in profile.get("level_forums") or []:
                name = str(forum.get("name") or "")
                if not name:
                    continue
                existing = merged.get(name)
                if existing is None:
                    merged[name] = {
                        "name": name,
                        "level": int(forum.get("level") or 0),
                        "level_name": "",
                        "source": "恋文等级",
                        "level_source": "恋文（第三方）",
                    }
                elif not int(existing.get("level") or 0):
                    existing["level"] = int(forum.get("level") or 0)
                    existing["level_source"] = "恋文（第三方）"
        return sorted(merged.values(), key=lambda item: int(item.get("level") or 0), reverse=True)

    def _forum_note(self, profile, bar_name: str = "", bar_level: str = "") -> str:
        forums = profile.get("followed_forums") or []
        hidden = profile.get("hidden_forums") or []
        if forums:
            note = f"共 {len(forums)} 个（完整）"
            levels = profile.get("level_forums") or []
            if self.settings.get("love_level_enabled", False) and levels:
                note += f"；恋文等级另列 {len(levels)} 个（非关注）"
            return note
        if hidden or profile.get("like_forum"):
            count = len(self._merge_forum_lists(profile, bar_name, bar_level))
            if self.mode_var.get() == "guest" and not profile.get("follow_loaded"):
                if self._hidden_follows(profile):
                    return f"对方隐藏了完整关注列表，已从 profile 片段补 {count} 个，不完整"
                return f"未加载公开关注，仅从 profile 片段补 {count} 个，不完整"
            if "BDUSS" in str(profile.get("follow_error") or ""):
                note = f"未登录，仅从 profile 片段补 {count} 个关注，不完整"
            else:
                note = f"对方隐藏了完整关注列表，已从等级头衔/精选恢复 {count} 个，可能不全"
            probed = len(profile.get("probed_forums") or [])
            if probed:
                note += f"；候选确认 {probed} 个"
            if self._hidden_follows(profile):
                note += "（风险提示：关注列表隐藏，未命中警告时标黄）"
            return note
        if profile.get("followed_private"):
            return "对方隐藏了完整关注列表（隐私设置），不可见（风险提示：关注列表隐藏，未命中警告时标黄）"
        return "没有查到关注列表"







    def _choose_report_path(self, user, profile, mark) -> None:
        initial = report_base(user, profile) + ".xlsx"
        path = filedialog.asksaveasfilename(
            title="导出用户报告",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
            initialfile=initial,
            parent=self.root,
        )
        if not path:
            return
        base = os.path.splitext(path)[0]
        try:
            xlsx, md = export_user_report(
                base,
                user,
                profile,
                self.last_threads,
                mode="登录" if self.mode_var.get() == "login" else "免登录",
                mark=mark,
            )
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("导出失败", friendly_error(error), parent=self.root)
            return
        self._append_log(f"用户报告已导出：{xlsx}；{md}", "ok")
        messagebox.showinfo(
            "导出完成",
            "已生成：" + chr(10) + xlsx + chr(10) + md,
            parent=self.root,
        )


    def _comment_depth_value(self) -> int:
        text = self.comment_depth_var.get()
        if "10" in text:
            return 10
        if "50" in text:
            return 50
        if "100" in text:
            return 100
        return 0

    def _merge_threads(self, new_threads) -> list:
        merged = {thread.meta.tid: thread for thread in self.last_threads}
        for thread in new_threads:
            merged[thread.meta.tid] = thread
        return list(merged.values())


    def _persist_result(self, threads) -> None:
        if not threads or not self.settings.get("save_result", True):
            return
        try:
            save_threads(
                list(threads),
                VERSION,
                encrypted=bool(self.settings.get("encrypt_result", False)),
            )
        except Exception as error:  # noqa: BLE001
            self._post(("log", f"保存最近结果失败：{error}", "err"))

    def _restore_last_result(self) -> None:
        if not self.settings.get("save_result", True):
            return
        try:
            threads, _meta = load_threads()
        except IncompatibleResult as error:
            archive_incompatible()
            self._append_log(f"上次结果无法恢复：{error}；旧文件已保留。", "err")
            return
        except Exception as error:  # noqa: BLE001
            self._append_log(f"读取上次结果失败：{error}", "err")
            return
        if not threads:
            return
        if self.settings.get("restore_mode", "auto") == "ask":
            if not messagebox.askyesno(
                "恢复上次结果",
                f"发现上次保存的 {len(threads)} 个帖子，恢复吗？",
                parent=self.root,
            ):
                return
        self.last_threads = threads
        self._profile_cache.clear()
        try:
            self._refresh_people()
            self._refresh_grid()
        except Exception:  # noqa: BLE001
            pass
        incomplete = sum(1 for thread in threads if not getattr(thread, "complete", True))
        self.status_var.set(
            f"已恢复 {len(threads)} 个帖子（{len(self._aggregate_users())} 位用户）；"
            + (f"不完整 {incomplete} 帖；" if incomplete else "")
            + "缺失身份可点「补全身份」"
        )


    def _high_risk_items(self) -> List[str]:
        items: List[str] = []
        try:
            if int(self.identity_concurrency_var.get() or 3) >= 5:
                items.append("贴吧ID并发 5（可能触发验证码或临时限流）")
        except (TypeError, ValueError, tk.TclError):
            pass
        try:
            if float(self.delay_var.get() or 0.8) < 0.5:
                items.append("请求间隔小于 0.5 秒")
        except (TypeError, ValueError, tk.TclError):
            pass
        try:
            if int(self.comment_concurrency_var.get() or 1) >= 3:
                items.append("楼中楼并发 3")
        except (TypeError, ValueError, tk.TclError):
            pass
        if self.mode_var.get() == "login":
            items.append("登录抓取")
        if self.settings.get("follow_enhance"):
            items.append("关注检测")
        if getattr(self, "proxy_mode_var", None) is not None and self.proxy_mode_var.get() == "自定义":
            items.append("自定义代理")
        return items



    def _on_escape(self, _event=None):
        grab = self.root.grab_current()
        if grab is not None and isinstance(grab, tk.Toplevel):
            try:
                grab.destroy()
            except tk.TclError:
                pass
            return "break"
        return None

    def _on_close(self) -> None:
        try:
            self.settings["window_geometry"] = self.root.geometry()
            save_settings(self.settings)
        except tk.TclError:
            pass
        active = self._network_task_active()
        if not active:
            self.root.destroy()
            return
        choice = self._ask_choice(
            "任务仍在进行",
            "未导出的已完成部分可能不会保留。",
            [("继续", False), ("停止并退出", True)],
            default=0,
        )
        if not choice:
            return
        self._closing = True
        self.stop_event.set()
        self._supplement_stop.set()
        resume_requests()
        self._batch_cancel = True
        self.status_var.set("正在停止…")
        self._append_log("正在停止任务并保存已完成部分…", "muted")
        self.root.after(100, self._wait_close)

    def _wait_close(self) -> None:
        worker_alive = bool(self.worker and self.worker.is_alive())
        batch_alive = bool(getattr(self, "_batch_running", False))
        supplement_alive = bool(getattr(self, "_supplement_running", False))
        if worker_alive or batch_alive or supplement_alive:
            self.root.after(100, self._wait_close)
            return
        self._persist_result(self.last_threads)
        self.root.destroy()

    # ------------------------------------------------------------- worker

    def _post(self, message: tuple) -> None:
        self.log_queue.put(message)


    def _poll_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                self._handle_message(message)
        except queue.Empty:
            pass
        self._notify_cache_eviction()
        self.root.after(120, self._poll_queue)

    def _handle_message(self, message: tuple) -> None:
        kind = message[0]
        if kind == "log":
            self._handle_message_log(message)
        elif kind == "stage":
            self._handle_message_stage(message)
        elif kind == "done":
            self._handle_message_done(message)
        elif kind == "cancelled_partial":
            self._handle_message_cancelled_partial(message)
        elif kind == "probe_done":
            self._handle_message_probe_done(message)
        elif kind == "batch_profile":
            self._handle_message_batch_profile(message)
        elif kind == "batch_done":
            self._handle_message_batch_done(message)
        elif kind == "profile_ready":
            self._handle_message_profile_ready(message)
        elif kind == "enrich_done":
            self._handle_message_enrich_done(message)
        elif kind == "enrich_error":
            self._handle_message_enrich_error(message)
        elif kind == "identity_ask":
            self._handle_message_identity_ask(message)
        elif kind == "identity_supplement_progress":
            self._handle_message_identity_supplement_progress(message)
        elif kind == "identity_supplement_done":
            self._handle_message_identity_supplement_done(message)
        elif kind == "incomplete_retry_done":
            self._handle_message_incomplete_retry_done(message)
        elif kind == "incomplete_retry_stopped":
            self._handle_message_incomplete_retry_stopped(message)
        elif kind == "incomplete_retry_error":
            self._handle_message_incomplete_retry_error(message)
        elif kind == "identity_supplement_stopped":
            self._handle_message_identity_supplement_stopped(message)
        elif kind == "identity_supplement_error":
            self._handle_message_identity_supplement_error(message)
        elif kind == "identity_remember":
            self._handle_message_identity_remember(message)
        elif kind == "levels_filled":
            self._handle_message_levels_filled(message)
        elif kind == "levels_error":
            self._handle_message_levels_error(message)
        elif kind == "lookup_ready":
            self._handle_message_lookup_ready(message)
        elif kind == "levels_ready":
            self._handle_message_levels_ready(message)
        elif kind == "links_ready":
            self._handle_message_links_ready(message)
        elif kind == "love_ready":
            self._handle_message_love_ready(message)
        elif kind == "cancelled":
            self._handle_message_cancelled(message)
        elif kind == "captcha":
            self._handle_captcha_message(message)
        elif kind == "webview_test_done":
            self._handle_webview_test_done(message)
        elif kind == "embedded_done":
            self._handle_embedded_done(message)
        elif kind == "auto_login_done":
            self._handle_auto_login_done(message)
        elif kind == "switch_login_done":
            self._handle_switch_login_done(message)
        elif kind == "manual_cookie_probe":
            self._handle_message_manual_cookie_probe(message)
        elif kind == "rate_limit_ask":
            self._handle_message_rate_limit_ask(message)
        elif kind == "rate_limit":
            self._handle_message_rate_limit(message)
        elif kind == "error":
            self._handle_message_error(message)
        else:
            self._append_log(f"未知消息类型：{kind}", "warn")

    def _network_task_active(self) -> bool:
        return bool(
            self.running
            or getattr(self, "_supplement_running", False)
            or getattr(self, "_batch_running", False)
        )

    def _set_supplement_running(self, running: bool) -> None:
        self._supplement_running = running
        self.start_btn.configure(
            state="disabled" if running else "normal",
            text="补全中，稍后开始" if running else "开始统计",
        )
        if running:
            self.stop_btn.configure(state="normal")
        else:
            self.stop_btn.configure(state="disabled")
            resume_requests()
            set_stop_checker(self.stop_event.is_set)

    def _set_running(self, running: bool) -> None:
        self.running = running
        if running:
            self.start_btn.configure(state="disabled", bg="#9aa7b8")
            self.pause_btn.configure(state="normal", text="暂停")
            self.stop_btn.configure(state="normal")
            self.open_btn.configure(state="disabled")
            self.status_var.set("正在抓取，请稍候…")
            self.progress.pack(side="right")
            try:
                self.progress.start(12)
            except tk.TclError:
                pass
        else:
            self.start_btn.configure(state="normal", bg="#1F4E79")
            self.pause_btn.configure(state="disabled", text="暂停")
            self.stop_btn.configure(state="disabled")
            self._task_paused = False
            resume_requests()
            try:
                self.progress.stop()
            except tk.TclError:
                pass
            self.progress.pack_forget()
            if getattr(self, "_pending_retry", False):
                self.root.after(200, self._retry_incomplete_threads)



def _selftest() -> int:
    """冻结后的环境自检：解析一段 HTML、生成一个 xlsx，结果写到日志文件。"""
    import tempfile

    out = os.environ.get("TIEBA_SELFTEST_OUT") or os.path.join(tempfile.gettempdir(), "tieba_selftest.xlsx")
    log_path = out + ".txt"
    try:
        from tieba_reply_stats.models import Comment, Floor, ThreadData, ThreadMeta
        from tieba_reply_stats.parse import parse_thread_page

        html = (
            '<div class="l_post" data-field=\'{"author":{"user_id":1,"user_name":"测试用户"},'
            '"content":{"post_id":2,"post_no":1,"reply_num":1,"is_lz":1,"date":"2024-01-01 10:00"}}\'>'
            '<div class="d_post_content">你好</div></div>'
        )
        meta, floors = parse_thread_page(html, "https://tieba.baidu.com/p/1", "1")
        if not floors or floors[0].author != "测试用户":
            raise AssertionError(f"解析异常：{floors!r}")

        thread = ThreadData(
            meta=ThreadMeta(tid="1", title="自检", url="https://tieba.baidu.com/p/1"),
            floors=[
                Floor(
                    post_no=1,
                    pid="2",
                    author="测试用户",
                    author_id="1",
                    posted_at=None,
                    content="你好",
                    reply_num=1,
                    is_op=True,
                )
            ],
            comments=[
                Comment(
                    floor_no=1,
                    floor_author="测试用户",
                    pid="9",
                    author="回复者",
                    author_id="2",
                    posted_at=None,
                    content="回复内容",
                )
            ],
        )
        export_workbook(out, [thread])

        from openpyxl import load_workbook

        book = load_workbook(out)
        if "回复统计" not in book.sheetnames:
            raise AssertionError(f"工作表异常：{book.sheetnames}")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("OK\n" + out + "\n")
        return 0
    except Exception as error:  # noqa: BLE001
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("FAIL\n" + repr(error) + "\n" + traceback.format_exc())
        return 1


_INSTANCE_SOCKET = None


def _focus_existing_window() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        title = f"{APP_TITLE} v{VERSION}"
        handle = user32.FindWindowW(None, title)
        if handle:
            user32.ShowWindow(handle, 9)
            user32.SetForegroundWindow(handle)
    except Exception:  # noqa: BLE001
        pass


def _acquire_instance():
    global _INSTANCE_SOCKET
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 47831))
        sock.listen(1)
    except OSError:
        sock.close()
        return None
    _INSTANCE_SOCKET = sock
    return sock


def main() -> int:
    if "--webview2-verify" in sys.argv:
        index = sys.argv.index("--webview2-verify")
        from tieba_reply_stats.webview2_helper import main as verify_main

        sys.argv = [sys.argv[0], *sys.argv[index + 1 :]]
        return verify_main()
    if "--selftest" in sys.argv:
        return _selftest()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001
            pass
    if _acquire_instance() is None:
        _focus_existing_window()
        messagebox.showinfo("软件已在运行", "已有一个窗口在运行，请使用已有窗口。")
        return 0
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
