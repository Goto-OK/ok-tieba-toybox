#!/usr/bin/env python3
"""贴吧楼层回复统计 —— 图形界面（给不想用命令行的用户）。

直接运行：python tieba_gui.py
打包后双击 exe 即可。
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

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
    CollectError,
    CollectOptions,
    collect_thread,
    enrich_user_levels,
    extract_tid,
)
from tieba_reply_stats.compare import MODES, compare_threads
from tieba_reply_stats.config_backup import preview as backup_preview
from tieba_reply_stats.config_backup import read_backup, write_backup
from tieba_reply_stats.cookie_store import clear_cookie, load_cookie, save_cookie
from tieba_reply_stats.errors import friendly_error
from tieba_reply_stats.export import export_workbook
from tieba_reply_stats.fetch import CaptchaError, Fetcher, FetchError, ThreadGoneError, parse_cookie_input
from tieba_reply_stats.filters import FIELD_OPTIONS, LEVEL_OPTIONS, MARK_OPTIONS, filter_users
from tieba_reply_stats.follow_probe import candidate_bars, probe_forums
from tieba_reply_stats.pbapi import fill_thread_levels
from tieba_reply_stats.post_cache import DEFAULT_LIMIT_MB, MAX_LIMIT_MB, MIN_LIMIT_MB
from tieba_reply_stats.post_cache import cache as post_cache
from tieba_reply_stats.profile import (
    cached_user_posts,
    clear_post_cache,
    fetch_user_profile,
    resolve_user,
)
from tieba_reply_stats.report import (
    export_user_posts,
    export_user_report,
    posts_base,
    report_base,
)
from tieba_reply_stats.safe_delete import remove_file as safe_remove_file
from tieba_reply_stats.safe_delete import remove_tree as safe_remove_tree
from tieba_reply_stats.settings import APP_DIR, SETTINGS_PATH, load_settings, save_settings
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
from tieba_reply_stats.theme import map_color, resolve_palette
from tieba_reply_stats.version import __version__ as VERSION

APP_TITLE = "贴吧楼层回复统计"




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
    return os.path.join(desktop, f"贴吧回复统计_{datetime.now():%Y%m%d_%H%M}.xlsx")


def resource_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _optional_int(text: str) -> Optional[int]:
    try:
        return int(str(text).strip())
    except ValueError:
        return None


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.running = False
        self.last_output: str | None = None
        self.last_outputs: List[str] = []
        self.last_threads: list = []
        self._auto_filled = False
        self._profile_topic_limit = 50
        self._lookup_normalize_job: Optional[str] = None
        self._emoji_window: Optional[tk.Toplevel] = None
        self.blacklist = load_blacklist()
        self.settings = load_settings()
        post_cache().set_limit_mb(int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB)))
        self.palette = resolve_palette(
            str(self.settings.get("theme_mode", "light")),
            str(self.settings.get("accent", "blue")),
        )
        self.mode_var = tk.StringVar(value="guest")

        self._build_ui()
        self._apply_theme()
        self._apply_table_density()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)
        saved_geometry = str(self.settings.get("window_geometry") or "")
        if saved_geometry:
            try:
                self.root.geometry(saved_geometry)
            except tk.TclError:
                pass
        self._set_output(default_output_path())
        self.root.after(120, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<F1>", lambda _event: self._open_usage_window())
        self.root.bind("<Escape>", self._on_escape)

        saved = load_cookie()
        if saved:
            self.cookie_var.set(saved)
            self._sync_login_from_cookie()
            self._append_log("已自动填入上次保存的登录信息（如果失效，请重新粘贴一次）。", "muted")
        if self.settings.get("follow_enhance"):
            self.mode_var.set("login")
            if not parse_cookie_input(self.cookie_var.get()).get("BDUSS"):
                self._append_log("抓取增强已开启，但尚未填写 BDUSS；请先填写后再开始统计。", "muted")
        else:
            self.mode_var.set("guest")
        self._apply_mode_ui()
        self._apply_risk_ui()
        self._apply_proxy()
        self._restore_last_result()
        self.root.after(300, self._maybe_onboarding)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} v{VERSION}")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        try:
            scale = float(self.root.tk.call("tk", "scaling")) / (96 / 72)
        except (tk.TclError, ValueError):
            scale = 1.0
        if scale >= 1.45:
            base_w, base_h = 1240, 860
        elif scale >= 1.2:
            base_w, base_h = 1100, 840
        else:
            base_w, base_h = 980, 820
        width = max(900, min(base_w, screen_w - 80))
        height = max(720, min(base_h, screen_h - 100))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(900 if scale >= 1.2 else 840, screen_w - 40), min(680, screen_h - 80))
        self.root.configure(bg="#eef1f5")

        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TButton", padding=(8, 4), font=("Microsoft YaHei UI", 9))
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Card.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Main.TNotebook", background="#e2e8f0")
        style.configure("Sub.TNotebook", background="#eef1f5")
        style.configure(
            "Main.TNotebook.Tab",
            padding=(16, 7),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "Main.TNotebook.Tab",
            background=[("selected", "#ffffff")],
            foreground=[("selected", "#1F4E79")],
        )
        style.configure(
            "Sub.TNotebook.Tab",
            padding=(9, 3),
            font=("Microsoft YaHei UI", 9),
        )
        style.map(
            "Sub.TNotebook.Tab",
            background=[("selected", "#ffffff")],
            foreground=[("selected", "#1F4E79")],
        )

        header = tk.Frame(self.root, bg="#ffffff", padx=18, pady=12)
        header.pack(fill="x")
        tk.Label(
            header,
            text=APP_TITLE,
            bg="#ffffff",
            fg="#1F4E79",
            font=("Microsoft YaHei UI", 17, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="粘贴贴吧帖子链接，自动统计每个用户的楼层回复并导出 Excel",
            bg="#ffffff",
            fg="#6b7280",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(3, 0))

        status = tk.Frame(self.root, bg="#ffffff", padx=16, pady=8)
        status.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="准备就绪")
        tk.Label(
            status,
            textvariable=self.status_var,
            bg="#ffffff",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
            anchor="w",
        ).pack(side="left")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=180)

        self.body = tk.Frame(self.root, bg="#eef1f5")
        self.body.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(self.body, style="Main.TNotebook")
        self.notebook.pack(side="left", fill="both", expand=True)

        self.tab_posts = tk.Frame(self.notebook, bg="#eef1f5")
        self.tab_lookup = tk.Frame(self.notebook, bg="#eef1f5")
        self.tab_settings = tk.Frame(self.notebook, bg="#eef1f5")
        self.notebook.add(self.tab_posts, text="  帖子统计  ")
        self.notebook.add(self.tab_lookup, text="  查用户  ")
        self.notebook.add(self.tab_settings, text="  设置  ")

        self.post_nb = ttk.Notebook(self.tab_posts, style="Sub.TNotebook")
        self.post_nb.pack(fill="both", expand=True, padx=4, pady=4)
        self.tab_fetch = tk.Frame(self.post_nb, bg="#eef1f5")
        self.tab_grid = tk.Frame(self.post_nb, bg="#eef1f5")
        self.tab_people = tk.Frame(self.post_nb, bg="#eef1f5")
        self.post_nb.add(self.tab_fetch, text="  抓取  ")
        self.post_nb.add(self.tab_grid, text="  表格查看  ")
        self.post_nb.add(self.tab_people, text="  参与者  ")

        body = tk.Frame(self.tab_fetch, bg="#eef1f5", padx=16, pady=8)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=0)
        body.rowconfigure(5, weight=1)

        text_font = ("Microsoft YaHei UI", 10)

        # 1. 链接
        box = ttk.LabelFrame(body, text=" 帖子链接 ", style="Card.TLabelframe")
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        self.url_text = tk.Text(
            box,
            height=3,
            wrap="word",
            font=text_font,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#c9d2df",
            highlightcolor="#1F4E79",
            padx=8,
            pady=6,
        )
        self.url_text.grid(row=0, column=0, sticky="ew")
        self.url_text.bind("<Control-Return>", self._start_from_key)
        tk.Label(
            box,
            text="每行一个链接，也可以直接粘贴帖子 ID（如 1234567890）",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        # 2. 选项
        options = ttk.LabelFrame(body, text=" 选项 ", style="Card.TLabelframe")
        options.grid(row=1, column=0, sticky="new", pady=(6, 0))
        self.comments_var = tk.BooleanVar(value=True)
        self.exclude_op_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options,
            text="抓取楼中楼回复（推荐；关闭后只统计每层主楼，速度更快）",
            variable=self.comments_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Checkbutton(
            options,
            text="统计时不把 1 楼（楼主主帖）算作回复",
            variable=self.exclude_op_var,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=2)
        self.export_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options,
            text="同时导出 Excel（取消勾选则只在软件里看参与者，随时可以点「导出 Excel」补）",
            variable=self.export_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=2)

        delay_row = tk.Frame(options)
        delay_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        tk.Label(delay_row, text="请求间隔：").pack(side="left")
        self.delay_var = tk.StringVar(value="0.8")
        ttk.Spinbox(
            delay_row,
            from_=0.3,
            to=5.0,
            increment=0.1,
            width=5,
            textvariable=self.delay_var,
        ).pack(side="left")
        tk.Label(delay_row, text=" 秒（越小越快，越大越稳；被拦截时调大一些）", fg="#8a94a6").pack(
            side="left"
        )
        tk.Label(delay_row, text="  楼中楼：").pack(side="left")
        self.comment_depth_var = tk.StringVar(value="全部")
        ttk.Combobox(
            delay_row,
            values=("全部", "每层 10", "每层 50", "每层 100"),
            textvariable=self.comment_depth_var,
            width=9,
            state="readonly",
        ).pack(side="left")
        tk.Label(delay_row, text=" 并发 ").pack(side="left")
        self.comment_concurrency_var = tk.StringVar(value="1")
        ttk.Spinbox(delay_row, from_=1, to=3, width=3, textvariable=self.comment_concurrency_var).pack(
            side="left"
        )

        # 3. 保存位置
        out_box = ttk.LabelFrame(body, text=" 保存到 ", style="Card.TLabelframe")
        out_box.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        out_box.columnconfigure(0, weight=1)
        self.output_var = tk.StringVar()
        ttk.Entry(out_box, textvariable=self.output_var, font=text_font).grid(row=0, column=0, sticky="ew")
        ttk.Button(out_box, text="浏览…", command=self._choose_output, width=8).grid(
            row=0, column=1, padx=(8, 0)
        )

        # 4. 登录 / 关注增强
        cookie_box = ttk.LabelFrame(body, text=" 登录 / 关注增强 ", style="Card.TLabelframe")
        cookie_box.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.cookie_box = cookie_box
        cookie_box.columnconfigure(0, weight=1)
        self.cookie_var = tk.StringVar()
        self.login_method_var = tk.StringVar(value="bduss")

        method_row = tk.Frame(cookie_box, bg="#eef1f5")
        method_row.grid(row=0, column=0, columnspan=4, sticky="w", pady=(2, 4))
        tk.Label(method_row, text="登录方式：", bg="#eef1f5", fg="#475569").pack(side="left")
        self.login_bduss_radio = ttk.Radiobutton(
            method_row,
            text="仅 BDUSS（推荐）",
            value="bduss",
            variable=self.login_method_var,
            command=self._on_login_method_changed,
        )
        self.login_bduss_radio.pack(side="left", padx=(4, 8))
        self.login_cookie_radio = ttk.Radiobutton(
            method_row,
            text="完整 Cookie（验证码时）",
            value="cookie",
            variable=self.login_method_var,
            command=self._on_login_method_changed,
        )
        self.login_cookie_radio.pack(side="left")

        self.bduss_frame = tk.Frame(cookie_box, bg="#eef1f5")
        self.bduss_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.bduss_frame.columnconfigure(1, weight=1)
        tk.Label(self.bduss_frame, text="BDUSS：", bg="#eef1f5", fg="#475569").grid(row=0, column=0, sticky="w")
        self.bduss_var = tk.StringVar()
        self.bduss_entry = ttk.Entry(
            self.bduss_frame, textvariable=self.bduss_var, show="•", font=text_font
        )
        self.bduss_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(
            self.bduss_frame, text="从剪贴板粘贴", command=self._paste_bduss, width=14
        ).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(
            self.bduss_frame, text="如何获取？", command=self._show_bduss_help, width=10
        ).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(self.bduss_frame, text="应用", command=self._apply_bduss, width=7).grid(
            row=0, column=4, padx=(6, 0)
        )
        ttk.Button(self.bduss_frame, text="清除", command=self._clear_bduss, width=7).grid(
            row=0, column=5, padx=(6, 0)
        )
        self.remember_bduss_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self.bduss_frame,
            text="记住 BDUSS（用 Windows 账户加密，仅本机可用）",
            variable=self.remember_bduss_var,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(3, 0))
        tk.Label(
            self.bduss_frame,
            text="只发送 BDUSS，不发送浏览器里的其他 Cookie；验证码时切换完整 Cookie。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).grid(row=2, column=0, columnspan=6, sticky="w")

        self.cookie_frame = tk.Frame(cookie_box, bg="#eef1f5")
        self.cookie_frame.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.cookie_frame.columnconfigure(1, weight=1)
        tk.Label(self.cookie_frame, text="Cookie：", bg="#eef1f5", fg="#475569").grid(
            row=0, column=0, sticky="w"
        )
        self.cookie_entry = ttk.Entry(self.cookie_frame, textvariable=self.cookie_var, show="•", font=text_font)
        self.cookie_entry.grid(row=0, column=1, sticky="ew")
        self.cookie_paste_btn = ttk.Button(
            self.cookie_frame, text="从剪贴板粘贴", command=self._paste_cookie, width=14
        )
        self.cookie_paste_btn.grid(row=0, column=2, padx=(8, 0))
        self.cookie_help_btn = ttk.Button(
            self.cookie_frame, text="如何获取？", command=self._show_cookie_help, width=10
        )
        self.cookie_help_btn.grid(row=0, column=3, padx=(6, 0))
        self.cookie_apply_btn = ttk.Button(
            self.cookie_frame, text="应用", command=self._apply_cookie, width=7
        )
        self.cookie_apply_btn.grid(row=0, column=4, padx=(6, 0))
        self.cookie_clear_btn = ttk.Button(
            self.cookie_frame, text="清除", command=self._clear_cookie, width=7
        )
        self.cookie_clear_btn.grid(row=0, column=5, padx=(6, 0))
        self.remember_cookie_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self.cookie_frame,
            text="记住完整 Cookie（用 Windows 账户加密，仅本机可用；可能包含其他 Cookie）",
            variable=self.remember_cookie_var,
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(3, 0))
        self.cookie_frame.grid_remove()
        self.cookie_controls = [
            self.login_bduss_radio,
            self.login_cookie_radio,
            self.bduss_entry,
            self.cookie_entry,
            self.cookie_paste_btn,
            self.cookie_help_btn,
            self.cookie_apply_btn,
            self.cookie_clear_btn,
        ]
        self.login_method_var.trace_add("write", lambda *_: self._on_login_method_changed())

        # 5. 按钮
        buttons = tk.Frame(body, bg="#eef1f5")
        buttons.grid(row=4, column=0, sticky="ew", pady=(6, 4))
        self.start_btn = tk.Button(
            buttons,
            text="开始统计",
            command=self._on_start,
            bg="#1F4E79",
            fg="white",
            activebackground="#2E75B6",
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 11, "bold"),
            state="disabled",
        )
        self.start_btn.pack(side="left")
        self.stop_btn = tk.Button(
            buttons,
            text="停止",
            command=self._on_stop,
            bg="#e5e9f0",
            fg="#334155",
            activebackground="#d5dbe5",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
            state="disabled",
        )
        self.stop_btn.pack(side="left", padx=(10, 0))
        self.help_btn = tk.Button(
            buttons,
            text="使用说明",
            command=self._open_readme,
            bg="#eef1f5",
            fg="#1F4E79",
            activebackground="#eef1f5",
            relief="flat",
            padx=10,
            pady=8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 10, "underline"),
        )
        self.help_btn.pack(side="right")

        # 6. 日志
        log_box = ttk.LabelFrame(body, text=" 运行日志 ", style="Card.TLabelframe")
        log_box.grid(row=5, column=0, sticky="nsew", pady=(0, 8))
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_box,
            height=16,
            wrap="word",
            font=("Microsoft YaHei UI", 9),
            relief="flat",
            highlightthickness=1,
            highlightbackground="#c9d2df",
            bg="#fbfcfe",
            padx=8,
            pady=6,
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.tag_configure("title", foreground="#1F4E79", font=("Microsoft YaHei UI", 9, "bold"))
        self.log_text.tag_configure("ok", foreground="#15803d")
        self.log_text.tag_configure("err", foreground="#b91c1c")
        self.log_text.tag_configure("muted", foreground="#6b7280")

        self._build_grid_tab()
        self._build_people_tab()
        self._build_lookup_tab()
        self._build_settings_tab()

        self.url_text.focus_set()
        self.root.update_idletasks()
        self.start_btn.configure(state="normal")
        self._append_log("把帖子链接粘贴到上面，然后点「开始统计」。", "muted")

    # ------------------------------------------------------------- actions
    def _set_output(self, path: str) -> None:
        self.output_var.set(path)

    def _choose_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择保存位置",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
            initialfile=os.path.basename(self.output_var.get() or "贴吧回复统计.xlsx"),
            initialdir=os.path.dirname(self.output_var.get() or ""),
        )
        if path:
            self._set_output(path)

    def _on_login_method_changed(self) -> None:
        method = self.login_method_var.get()
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
        if self.remember_bduss_var.get():
            if save_cookie(self.cookie_var.get()):
                self.status_var.set("BDUSS 已加密保存")
            else:
                self.status_var.set("BDUSS 保存失败，本次仍可使用")
        else:
            clear_cookie()
            self.status_var.set("BDUSS 仅本次使用")
        self._append_log("登录方式：仅 BDUSS", "muted")

    def _apply_cookie(self) -> None:
        raw = self.cookie_var.get().strip()
        if not raw:
            messagebox.showwarning("需要 Cookie", "请粘贴完整 Cookie。", parent=self.root)
            self.cookie_entry.focus_set()
            return
        if not parse_cookie_input(raw).get("BDUSS"):
            messagebox.showwarning("Cookie 不完整", "完整 Cookie 里没有 BDUSS。", parent=self.root)
            return
        if self.remember_cookie_var.get():
            if save_cookie(raw):
                self.status_var.set("完整 Cookie 已加密保存")
            else:
                self.status_var.set("完整 Cookie 保存失败，本次仍可使用")
        else:
            clear_cookie()
            self.status_var.set("完整 Cookie 仅本次使用")
        self._append_log("登录方式：完整 Cookie", "muted")

    def _remember_current_login(self) -> bool:
        if self.login_method_var.get() == "bduss":
            return bool(self.remember_bduss_var.get())
        return bool(self.remember_cookie_var.get())

    def _current_cookie_text(self) -> str:
        if self.login_method_var.get() == "bduss":
            value = self._extract_bduss(self.bduss_var.get())
            return f"BDUSS={value}" if value else ""
        return self.cookie_var.get().strip()

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

    def _clear_cookie(self) -> None:
        self.cookie_var.set("")
        self.bduss_var.set("")
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

    def _open_result(self) -> None:
        raw = self.last_outputs or ([self.last_output] if self.last_output else [])
        paths = [path for path in raw if isinstance(path, str) and os.path.isfile(path)]
        if not paths:
            return
        if len(paths) > 1:
            choice = self._ask_choice(
                "打开拆分文件",
                f"共 {len(paths)} 个文件，选择打开方式。",
                [("只打开第一个", False), ("全部打开", True), ("取消", None)],
                default=0,
            )
            if choice is None:
                return
            if not choice:
                paths = paths[:1]
        failed = []
        for path in paths:
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                failed.append(path)
        if failed:
            messagebox.showerror(
                "部分文件打不开", "打不开：" + chr(10) + chr(10).join(failed), parent=self.root
            )

    # ------------------------------------------------------- 参与者与查用户
    def _aggregate_users(self, threads=None):
        buckets = {}
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
                if not bucket["level"] and item["level"]:
                    bucket["level"] = item["level"]
                if not bucket["badge"] and item["badge"]:
                    bucket["badge"] = item["badge"]
        users = list(buckets.values())
        for user in users:
            user["aliases"] = sorted(a for a in user.get("aliases", ()) if a and a != user["name"])
        users.sort(key=lambda item: (-item["total"], -item["floor"], item["name"]))
        return users

    def _build_people_tab(self) -> None:
        self._profile_cache: Dict[str, Dict[str, Any]] = {}
        self._batch_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self.people_users: List[Dict[str, Any]] = []
        bar = tk.Frame(self.tab_people, bg="#ffffff", padx=12, pady=8)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="点一行查看这个人的发言和关注的贴吧",
            bg="#ffffff",
            fg="#6b7280",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Label(bar, text="   抓取条数：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.post_count_var = tk.StringVar(value="50")
        self.post_count_box = ttk.Spinbox(
            bar, from_=5, to=1000, increment=10, width=6, textvariable=self.post_count_var
        )
        self.post_count_box.pack(side="left")
        self.post_date_mode_var = tk.StringVar(value="近期")
        self.post_date_mode_box = ttk.Combobox(
            bar, values=("近期", "指定日期"), textvariable=self.post_date_mode_var, width=9, state="readonly"
        )
        self.post_date_mode_box.pack(side="left", padx=(6, 0))
        self.post_date_mode_box.bind("<<ComboboxSelected>>", lambda _event: self._on_post_date_changed())
        self.post_start_var = tk.StringVar()
        self.post_end_var = tk.StringVar()
        self.post_date_row = tk.Frame(self.tab_people, bg="#ffffff", padx=12, pady=4)
        self.post_start_parts = self._date_group(self.post_date_row, "开始", 3)
        self.post_end_parts = self._date_group(self.post_date_row, "结束")
        tk.Label(
            self.post_date_row, text="  时间偏向：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)
        ).pack(side="left")
        self.post_prefer_var = tk.StringVar(value="优先最近")
        self.post_prefer_box = ttk.Combobox(
            self.post_date_row,
            values=("优先最近", "优先最早"),
            textvariable=self.post_prefer_var,
            width=12,
            state="readonly",
        )
        self.post_prefer_box.pack(side="left")
        for _var in (*self.post_start_parts, *self.post_end_parts):
            _var.trace_add("write", lambda *_: self._on_post_parts_changed())
        self.post_date_mode_var.trace_add("write", lambda *_: self._on_post_date_changed())
        self.post_start_var.set(self._group_date(self.post_start_parts))
        self.post_end_var.set(self._group_date(self.post_end_parts))
        tk.Label(bar, text="   范围：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.people_range_var = tk.StringVar(value="全部帖子")
        self.people_range_box = ttk.Combobox(
            bar, textvariable=self.people_range_var, width=56, state="readonly"
        )
        self.people_range_box.pack(side="left")
        self.people_range_box.bind("<<ComboboxSelected>>", lambda _event: self._on_people_range_changed())

        bar2 = tk.Frame(self.tab_people, bg="#ffffff", padx=12, pady=4)
        bar2.pack(fill="x")
        tk.Label(bar2, text="操作：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.batch_btn = ttk.Button(bar2, text="一键红绿灯", command=self._batch_refresh_marks, width=10)
        self.batch_btn.pack(side="left")
        self.include_follows_var = tk.BooleanVar(value=False)
        self.include_follows_check = ttk.Checkbutton(
            bar2,
            text="包含关注（慢）",
            variable=self.include_follows_var,
            command=self._on_include_follows_changed,
        )
        self.include_follows_check.pack(side="left", padx=(6, 0))
        self.resume_batch_btn = ttk.Button(
            bar2, text="继续未完成", command=self._resume_batch, width=12, state="disabled"
        )
        self.remark_btn = ttk.Button(
            bar2, text="重新标记（本地）", command=self._remark_local_marks, width=14
        )
        self.remark_btn.pack(side="left", padx=(6, 0))
        self._batch_running = False
        self._batch_plan: List[Dict[str, Any]] = []
        self._batch_pending: List[Dict[str, Any]] = []
        self._batch_cancel = False
        self._marks_stale = False
        self.refresh_people_btn = ttk.Button(
            bar2, text="刷新列表", command=self._refresh_people, width=8
        )
        self.refresh_people_btn.pack(side="left", padx=(6, 0))
        ttk.Button(bar2, text="打开主页", command=self._open_current_profile, width=10).pack(
            side="left", padx=(6, 0)
        )
        self.people_hint = tk.Label(bar2, text="", bg="#ffffff", fg="#8a94a6", font=("Microsoft YaHei UI", 9))
        self.people_hint.pack(side="right")

        filter_bar = tk.Frame(self.tab_people, bg="#ffffff", padx=10, pady=6)
        filter_bar.pack(fill="x", padx=10)
        tk.Label(filter_bar, text="关键词：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.people_field_var = tk.StringVar(value="全部字段")
        self.people_field_box = ttk.Combobox(
            filter_bar,
            values=FIELD_OPTIONS,
            textvariable=self.people_field_var,
            width=9,
            state="readonly",
        )
        self.people_field_box.pack(side="left")
        self.people_keyword_var = tk.StringVar()
        self.people_keyword_entry = ttk.Entry(filter_bar, textvariable=self.people_keyword_var, width=16)
        self.people_keyword_entry.pack(side="left", padx=(4, 0))
        tk.Label(filter_bar, text=" 等级 ", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.people_level_var = tk.StringVar(value="全部")
        self.people_level_box = ttk.Combobox(
            filter_bar, values=LEVEL_OPTIONS, textvariable=self.people_level_var, width=9, state="readonly"
        )
        self.people_level_box.pack(side="left")
        self.people_custom_frame = tk.Frame(filter_bar, bg="#ffffff")
        self.people_min_var = tk.StringVar()
        self.people_max_var = tk.StringVar()
        self.people_min_entry = ttk.Entry(self.people_custom_frame, textvariable=self.people_min_var, width=4)
        self.people_min_entry.pack(side="left")
        tk.Label(self.people_custom_frame, text="~", bg="#ffffff", fg="#475569").pack(side="left")
        self.people_max_entry = ttk.Entry(self.people_custom_frame, textvariable=self.people_max_var, width=4)
        self.people_max_entry.pack(side="left")
        tk.Label(filter_bar, text=" 标记 ", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.people_mark_var = tk.StringVar(value="全部")
        self.people_mark_box = ttk.Combobox(
            filter_bar, values=MARK_OPTIONS, textvariable=self.people_mark_var, width=6, state="disabled"
        )
        self.people_mark_box.pack(side="left")
        self.people_reset_btn = ttk.Button(
            filter_bar, text="清除筛选", command=self._reset_people_filters, width=10
        )
        self.people_reset_btn.pack(side="left", padx=(8, 0))

        for var in (
            self.people_field_var,
            self.people_keyword_var,
            self.people_level_var,
            self.people_mark_var,
            self.people_min_var,
            self.people_max_var,
        ):
            var.trace_add("write", lambda *_: self._on_people_filter_changed())

        paned = ttk.PanedWindow(self.tab_people, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.people_paned = paned
        self._people_sash_set = False
        paned.bind("<Configure>", self._on_people_paned_configure)
        left = tk.Frame(paned)
        right = tk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        columns = ("mark", "name", "username", "uid", "level", "floor", "comment", "total")
        self.people_columns = columns
        self._people_col_filters: Dict[str, set] = {}
        self._people_sort: tuple = ("", False)
        headings = {
            "mark": "标记",
            "name": "昵称",
            "username": "用户名",
            "uid": "用户ID",
            "level": "等级",
            "floor": "楼层",
            "comment": "楼中楼",
            "total": "合计",
        }
        widths = {
            "mark": 50,
            "name": 135,
            "username": 80,
            "uid": 80,
            "level": 50,
            "floor": 45,
            "comment": 50,
            "total": 45,
        }
        self.people_pager = tk.Frame(left, bg="#ffffff")
        self.people_pager.pack(side="bottom", fill="x", pady=(4, 0))
        self._people_page = 0
        self.people_page_label = tk.Label(
            self.people_pager, text="", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 8)
        )
        self.people_page_label.pack(side="left")
        def page_command(value):
            return lambda: self._people_go(value)

        for text, delta in (("首页", "first"), ("上一页", -1), ("下一页", 1), ("末页", "last")):
            ttk.Button(
                self.people_pager,
                text=text,
                width=5 if text in ("首页", "末页") else 6,
                command=page_command(delta),
            ).pack(side="left", padx=(4, 0))
        tree_wrap = tk.Frame(left, bg="#ffffff")
        tree_wrap.pack(fill="both", expand=True)
        self.people_tree = ttk.Treeview(tree_wrap, columns=columns, show="headings")
        for col in columns:
            mark = "  ▼" if col in ("mark", "name", "username", "uid") else ""
            command = (
                partial(self._filter_people_column, col)
                if col in ("name", "username", "uid")
                else partial(self._sort_people, col)
            )
            self.people_tree.heading(col, text=headings[col] + mark, command=command)
            self.people_tree.column(col, width=widths[col], anchor="center" if col != "name" else "w")
        self.people_tree.tag_configure("ban", background=self.palette["danger_bg"])
        self.people_tree.tag_configure("warn", background=self.palette["warning_bg"])
        self.people_tree.tag_configure("safe", background=self.palette["safe_bg"])
        scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.people_tree.yview)
        xscroll = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.people_tree.xview)
        self.people_tree.configure(yscrollcommand=scroll.set, xscrollcommand=xscroll.set)
        self.people_tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)
        self.people_tree.bind("<<TreeviewSelect>>", self._on_person_select)
        self.people_tree.bind("<Control-c>", lambda _event: self._copy_person_row())
        self.people_tree.bind("<Button-3>", self._person_menu)
        self._person_popup = tk.Menu(self.people_tree, tearoff=0)
        self._person_popup.add_command(label="复制整行", command=self._copy_person_row)
        self._person_popup.add_command(label="复制当前页", command=self._copy_people_page)
        self._person_popup.add_command(label="复制昵称", command=lambda: self._copy_person_field("name"))
        self._person_popup.add_command(
            label="复制用户名", command=lambda: self._copy_person_field("username")
        )
        self._person_popup.add_command(label="复制用户ID", command=lambda: self._copy_person_field("uid"))
        self._person_popup.add_separator()
        self._person_popup.add_command(label="浏览器打开主页", command=self._open_current_profile)

        traffic = tk.Frame(right, bg="#fbfcfe")
        traffic.pack(fill="x", padx=6, pady=(2, 0))
        tk.Label(traffic, text="红绿灯：", bg="#fbfcfe", fg="#6b7280", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.traffic_labels = {}
        for key, color in (("ban", "#dc2626"), ("warn", "#f59e0b"), ("safe", "#16a34a")):
            label = tk.Label(traffic, text="●", fg="#d1d5db", bg="#fbfcfe", font=("Microsoft YaHei UI", 14))
            label.pack(side="left", padx=(2, 0))
            self.traffic_labels[key] = (label, color)
        self.traffic_text = tk.Label(
            traffic, text="", bg="#fbfcfe", fg="#6b7280", font=("Microsoft YaHei UI", 9)
        )
        self.traffic_text.pack(side="left", padx=(8, 0))

        profile_bar = tk.Frame(right, bg="#fbfcfe")
        profile_bar.pack(fill="x", padx=6, pady=(4, 4))
        self.profile_status = tk.Label(
            profile_bar,
            text="选择左边一个人查看详情",
            anchor="w",
            bg="#fbfcfe",
            fg="#6b7280",
            font=("Microsoft YaHei UI", 9),
        )
        self.profile_status.pack(side="left", fill="x", expand=True)
        self.profile_topic_btn = ttk.Button(
            profile_bar, text="继续抓主题", command=self._continue_profile_topics, width=12
        )
        self.profile_topic_btn.pack(side="right", padx=(0, 4))
        self.profile_topic_btn.pack_forget()
        ttk.Button(profile_bar, text="刷新资料", command=self._reload_profile, width=8).pack(
            side="right"
        )

        profile_footer = tk.Frame(right, bg="#fbfcfe")
        profile_footer.pack(side="bottom", fill="x", padx=6, pady=(4, 4))
        profile_actions = tk.Frame(profile_footer, bg="#fbfcfe")
        profile_actions.pack(fill="x")
        self.profile_report_btn = ttk.Button(
            profile_actions, text="导出此人报告", command=self._export_profile_report, width=16
        )
        self.profile_posts_btn = ttk.Button(
            profile_actions, text="导出发言", command=self._export_profile_posts, width=10
        )
        self.profile_follow_btn = ttk.Button(
            profile_actions, text="加载公开关注", command=self._reload_profile_follow, width=16
        )
        self.profile_probe_btn = ttk.Button(
            profile_actions, text="探测候选关注", command=self._probe_profile_forums, width=16
        )
        self.profile_forum_note = tk.Label(
            profile_footer,
            text="",
            bg="#fbfcfe",
            fg="#b45309",
            wraplength=700,
            justify="left",
            font=("Microsoft YaHei UI", 8),
        )
        self.profile_forum_note.pack(fill="x", pady=(2, 0))

        body_paned = ttk.PanedWindow(right, orient="horizontal")
        body_paned.pack(fill="both", expand=True, padx=6)
        forum_frame = tk.Frame(body_paned)
        post_frame = tk.Frame(body_paned)
        body_paned.add(forum_frame, weight=1)
        body_paned.add(post_frame, weight=2)

        tk.Label(
            forum_frame,
            text="关注贴吧",
            bg="#fbfcfe",
            fg="#475569",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        self.profile_forum_tree = ttk.Treeview(
            forum_frame, columns=("bar", "level", "source"), show="headings", height=12
        )
        self.profile_forum_tree.heading("bar", text="贴吧")
        self.profile_forum_tree.heading("level", text="等级")
        self.profile_forum_tree.heading("source", text="来源")
        self.profile_forum_tree.column("bar", width=110, anchor="w")
        self.profile_forum_tree.column("level", width=45, anchor="center")
        self.profile_forum_tree.column("source", width=70, anchor="center")
        self.profile_forum_tree.pack(fill="both", expand=True)
        self.profile_forum_tree.bind("<Double-1>", lambda _event: self._open_profile_forum())
        self._configure_colors(self.profile_forum_tree)
        self._make_sortable(
            self.profile_forum_tree,
            {"bar": "贴吧", "level": "等级", "source": "来源"},
            {"level"},
        )
        self._bind_loaded_filter(
            self.profile_forum_tree,
            {"bar": ("贴吧", False), "level": None, "source": ("来源", False)},
        )
        self._profile_forum_names: Dict[str, str] = {}

        tk.Label(
            post_frame,
            text="发言",
            bg="#fbfcfe",
            fg="#475569",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        self.profile_post_tree = ttk.Treeview(
            post_frame, columns=("time", "type", "bar", "title", "content"), show="headings", height=12
        )
        self.profile_post_tree.heading("time", text="日期")
        self.profile_post_tree.heading("type", text="类型")
        self.profile_post_tree.heading("bar", text="贴吧")
        self.profile_post_tree.heading("title", text="标题")
        self.profile_post_tree.heading("content", text="内容")
        self.profile_post_tree.column("time", width=75, anchor="center")
        self.profile_post_tree.column("type", width=52, anchor="center")
        self.profile_post_tree.column("bar", width=100, anchor="w")
        self.profile_post_tree.column("title", width=180, anchor="w")
        self.profile_post_tree.column("content", width=220, anchor="w")
        self.profile_post_tree.pack(fill="both", expand=True)
        self.profile_post_tree.bind("<Double-1>", lambda _event: self._open_profile_post())
        self._configure_colors(self.profile_post_tree)
        self._make_sortable(
            self.profile_post_tree,
            {"time": "日期", "type": "类型", "bar": "贴吧", "title": "标题", "content": "内容"},
            {"time"},
        )
        self._bind_loaded_filter(
            self.profile_post_tree,
            {
                "time": ("日期", True),
                "type": ("类型", False),
                "bar": ("贴吧", False),
                "title": ("标题", False),
                "content": ("内容", False),
            },
        )
        self._profile_post_urls: Dict[str, str] = {}

        self.post_nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

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
        import ctypes

        ctypes.windll.user32.SetFocus(self._emoji_edit)

    def _create_inline_edit(self) -> bool:
        if getattr(self, "_emoji_edit", None):
            return True
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
        import ctypes

        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(edit)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(edit, buffer, length + 1)
        text = buffer.value.strip()
        if text:
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
        win.bind("<Escape>", lambda _event: win.destroy())
        win.focus_set()

    def _insert_emoji(self, char: str, win=None) -> None:
        self.lookup_entry.insert("insert", char)
        self.lookup_entry.focus_set()
        if win is not None:
            win.destroy()

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
                for item in (user.get("name", ""), user.get("username", ""), user.get("uid", ""), level)
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
            if key in ("mark", "name", "username", "uid"):
                self._filter_people_column(key, (event.x_root, event.y_root))
            return
        row = self.people_tree.identify_row(event.y)
        if row:
            self.people_tree.selection_set(row)
            try:
                self._person_popup.tk_popup(event.x_root, event.y_root)
            finally:
                self._person_popup.grab_release()

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

    def _on_lookup_query_changed(self, *_args) -> None:
        if getattr(self, "_normalizing_query", False):
            return
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
        raw = self.lookup_query_var.get()
        decoded = decode_display(raw)
        if decoded == raw:
            return
        try:
            pos = self.lookup_entry.index("insert")
            new_pos = len(decode_display(raw[:pos]))
        except (tk.TclError, AttributeError):
            new_pos = len(decoded)
        self._normalizing_query = True
        try:
            self.lookup_query_var.set(decoded)
            self.lookup_entry.icursor(new_pos)
        finally:
            self._normalizing_query = False

    def _build_lookup_tab(self) -> None:
        page = self.tab_lookup
        query = tk.Frame(page, bg="#ffffff", padx=12, pady=8)
        query.pack(fill="x")
        self.lookup_query_bar = query
        tk.Label(query, text="查询方式：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.lookup_mode_var = tk.StringVar(value="用户名")
        ttk.Combobox(
            query,
            values=("用户名", "用户ID", "昵称"),
            textvariable=self.lookup_mode_var,
            width=8,
            state="readonly",
        ).pack(side="left")
        tk.Label(query, text="  内容：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.lookup_query_var = tk.StringVar()
        entry = ttk.Entry(query, textvariable=self.lookup_query_var, width=34, font=("Microsoft YaHei UI", 10))
        self.lookup_entry = entry
        entry.pack(side="left", padx=(4, 0))
        entry.bind("<Return>", lambda _event: self._on_lookup())
        self.lookup_query_var.trace_add("write", self._on_lookup_query_changed)
        self.emoji_btn = tk.Button(
            query,
            text="😀",
            command=self._open_emoji_panel,
            font=("Segoe UI Emoji", 12),
            width=3,
            relief="flat",
            bg="#eef1f5",
            activebackground="#dbeafe",
            cursor="hand2",
        )
        self.emoji_btn.pack(side="left", padx=(6, 0))
        tk.Button(
            query,
            text="查询",
            command=self._on_lookup,
            bg="#1F4E79",
            fg="#ffffff",
            activebackground="#163b5c",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left", padx=(8, 0))

        options = tk.Frame(page, bg="#ffffff", padx=12, pady=4)
        options.pack(fill="x")
        self.lookup_options = options
        tk.Label(options, text="条数：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 8)).pack(
            side="left"
        )
        self.lookup_count_var = tk.StringVar(value="50")
        ttk.Spinbox(options, from_=5, to=1000, increment=10, width=6, textvariable=self.lookup_count_var).pack(
            side="left"
        )
        tk.Label(options, text="  日期：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 8)).pack(
            side="left"
        )
        self.lookup_date_mode_var = tk.StringVar(value="近期")
        self.lookup_date_mode_box = ttk.Combobox(
            options,
            values=("近期", "指定日期"),
            textvariable=self.lookup_date_mode_var,
            width=9,
            state="readonly",
        )
        self.lookup_date_mode_box.pack(side="left")
        self.lookup_date_mode_box.bind("<<ComboboxSelected>>", lambda _event: self._on_lookup_date_changed())
        self.lookup_status = tk.Label(
            options, text="", bg="#ffffff", fg="#8a94a6", font=("Microsoft YaHei UI", 8)
        )
        self.lookup_status.pack(side="right")

        date_row = tk.Frame(page, bg="#ffffff", padx=12, pady=2)
        self.lookup_date_row = date_row
        self.lookup_start_var = tk.StringVar()
        self.lookup_end_var = tk.StringVar()
        self.lookup_start_parts = self._date_group(date_row, "开始", 3)
        self.lookup_end_parts = self._date_group(date_row, "结束")
        tk.Label(
            date_row, text="  时间偏向：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 8)
        ).pack(side="left")
        self.lookup_prefer_var = tk.StringVar(value="优先最近")
        ttk.Combobox(
            date_row,
            values=("优先最近", "优先最早"),
            textvariable=self.lookup_prefer_var,
            width=10,
            state="readonly",
        ).pack(side="left")
        for _var in (*self.lookup_start_parts, *self.lookup_end_parts):
            _var.trace_add("write", lambda *_: self._on_lookup_parts_changed())
        self.lookup_start_var.set(self._group_date(self.lookup_start_parts))
        self.lookup_end_var.set(self._group_date(self.lookup_end_parts))

        summary = tk.Frame(page, bg="#eef1f5", padx=12, pady=4)
        summary.pack(fill="x")
        self.lookup_summary = summary
        self.lookup_info = tk.Label(
            summary,
            text="输入用户名 / 用户ID / 昵称，点「查询」查看资料、关注和发言。",
            anchor="w",
            bg="#eef1f5",
            fg="#64748b",
            font=("Microsoft YaHei UI", 9),
            wraplength=590,
            justify="left",
        )
        self.lookup_info.pack(side="left", fill="x", expand=True)
        traffic = tk.Frame(summary, bg="#eef1f5")
        traffic.pack(side="right", padx=(8, 0))
        tk.Label(
            traffic, text="红绿灯：", bg="#eef1f5", fg="#6b7280", font=("Microsoft YaHei UI", 8)
        ).pack(side="left")
        self.lookup_traffic_labels = {}
        for key, color in (
            ("ban", self.palette["danger"]),
            ("warn", self.palette["warning"]),
            ("safe", self.palette["safe"]),
        ):
            label = tk.Label(
                traffic,
                text="●",
                fg=self.palette["disabled_text"],
                bg="#eef1f5",
                font=("Microsoft YaHei UI", 12),
            )
            label.pack(side="left", padx=(2, 0))
            self.lookup_traffic_labels[key] = (label, color)
        self.lookup_traffic_text = tk.Label(
            traffic, text="", bg="#eef1f5", fg="#6b7280", font=("Microsoft YaHei UI", 8)
        )
        self.lookup_traffic_text.pack(side="left", padx=(8, 0))

        bottom = tk.Frame(page, bg="#eef1f5", padx=10, pady=6)
        bottom.pack(side="bottom", fill="x")
        self.lookup_bottom = bottom
        self.lookup_report_btn = ttk.Button(
            bottom, text="导出此人报告", command=self._export_lookup_report, width=14
        )
        self.lookup_posts_btn = ttk.Button(
            bottom, text="导出发言", command=self._export_lookup_posts, width=10
        )
        self.lookup_probe_btn = ttk.Button(
            bottom, text="探测候选关注", command=self._probe_lookup_forums, width=14
        )
        ttk.Button(bottom, text="复制全部", command=self._copy_lookup, width=10).pack(side="right")
        self.lookup_forum_note = tk.Label(
            bottom,
            text="",
            bg="#eef1f5",
            fg="#b45309",
            wraplength=620,
            justify="left",
            font=("Microsoft YaHei UI", 8),
        )
        self.lookup_forum_note.pack(side="left", fill="x", expand=True)

        paned = ttk.PanedWindow(page, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.lookup_paned = paned
        left = tk.Frame(paned)
        right = tk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=2)
        tk.Label(
            left,
            text="关注的贴吧",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        self.lookup_forum_tree = ttk.Treeview(
            left, columns=("bar", "level", "source"), show="headings", height=14
        )
        self.lookup_forum_tree.heading("bar", text="贴吧")
        self.lookup_forum_tree.heading("level", text="等级")
        self.lookup_forum_tree.heading("source", text="来源")
        self.lookup_forum_tree.column("bar", width=130, anchor="w")
        self.lookup_forum_tree.column("level", width=50, anchor="center")
        self.lookup_forum_tree.column("source", width=70, anchor="center")
        self.lookup_forum_tree.pack(fill="both", expand=True)
        self.lookup_forum_tree.bind("<Double-1>", lambda _event: self._open_lookup_forum())
        self._configure_colors(self.lookup_forum_tree)
        self._make_sortable(
            self.lookup_forum_tree,
            {"bar": "贴吧", "level": "等级", "source": "来源"},
            {"level"},
        )
        self._bind_loaded_filter(
            self.lookup_forum_tree,
            {"bar": ("贴吧", False), "level": None, "source": ("来源", False)},
        )

        tk.Label(
            right,
            text="发言",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        post_wrap = tk.Frame(right, bg="#eef1f5")
        post_wrap.pack(fill="both", expand=True)
        self.lookup_post_tree = ttk.Treeview(
            post_wrap, columns=("time", "type", "bar", "title", "content"), show="headings", height=14
        )
        self.lookup_post_tree.heading("time", text="日期")
        self.lookup_post_tree.heading("type", text="类型")
        self.lookup_post_tree.heading("bar", text="贴吧")
        self.lookup_post_tree.heading("title", text="标题")
        self.lookup_post_tree.heading("content", text="内容")
        self.lookup_post_tree.column("time", width=90, anchor="center")
        self.lookup_post_tree.column("type", width=55, anchor="center")
        self.lookup_post_tree.column("bar", width=100, anchor="w")
        self.lookup_post_tree.column("title", width=230, anchor="w")
        self.lookup_post_tree.column("content", width=300, anchor="w")
        post_xscroll = ttk.Scrollbar(post_wrap, orient="horizontal", command=self.lookup_post_tree.xview)
        self.lookup_post_tree.configure(xscrollcommand=post_xscroll.set)
        self.lookup_post_tree.grid(row=0, column=0, sticky="nsew")
        post_xscroll.grid(row=1, column=0, sticky="ew")
        post_wrap.rowconfigure(0, weight=1)
        post_wrap.columnconfigure(0, weight=1)
        self.lookup_post_tree.bind("<Double-1>", lambda _event: self._open_lookup_post())
        self._configure_colors(self.lookup_post_tree)
        self._make_sortable(
            self.lookup_post_tree,
            {"time": "日期", "type": "类型", "bar": "贴吧", "title": "标题", "content": "内容"},
            {"time"},
        )
        self._bind_loaded_filter(
            self.lookup_post_tree,
            {
                "time": ("日期", True),
                "type": ("类型", False),
                "bar": ("贴吧", False),
                "title": ("标题", False),
                "content": ("内容", False),
            },
        )
        self._lookup_post_urls: Dict[str, str] = {}
        self._lookup_forum_names: Dict[str, str] = {}
        self._lookup_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._lookup_topic_limit = 50
        self.lookup_topic_btn = ttk.Button(
            bottom, text="继续抓主题", command=self._continue_lookup_topics, width=12
        )
        self._lookup_generation = 0
        self.lookup_date_mode_var.trace_add("write", lambda *_: self._on_lookup_date_changed())
        for _var in (self.lookup_count_var, self.lookup_prefer_var):
            _var.trace_add("write", lambda *_: self._on_lookup_date_changed())
        self._toggle_lookup_dates()

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

    def _set_lookup_text(self, content: str) -> None:
        for tree in (self.lookup_forum_tree, self.lookup_post_tree):
            for item in tree.get_children():
                tree.delete(item)
        self.lookup_info.configure(text=content)

    def _on_lookup(self) -> None:
        self._normalize_lookup_query()
        query = self.lookup_query_var.get().strip()
        if not query:
            self.lookup_status.configure(text="先输入要查询的内容")
            return
        raw_query = query
        query = decode_display(query).strip() or query
        encoded_query = display_text(raw_query).lower()
        self._lookup_generation = getattr(self, "_lookup_generation", 0) + 1
        generation = self._lookup_generation
        mode = self.lookup_mode_var.get()
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
        cache_key = (
            f"{query}|{mode}|{count}|{start_date}|{end_date}|"
            f"{self.lookup_prefer_var.get()}|{self.mode_var.get()}|{self._lookup_topic_limit}"
        )
        hit = self._lookup_cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < 60:
            self._render_lookup(hit[1])
            self.lookup_status.configure(text=f"{hit[1].get('username') or ''} · 缓存结果")
            return
        self.lookup_status.configure(text="查询中…")
        self._set_lookup_text("查询中，请稍候…")

        def worker():
            try:
                fetcher = Fetcher(cookie=self._request_cookie(), delay=0.3, verbose=False)
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
                            f"按「{mode}」没有找到这个人（昵称可能不唯一，试试用户名或用户ID）",
                        )
                    )
                    return
                profile = fetch_user_profile(
                    fetcher,
                    info["uid"],
                    info["username"],
                    info["portrait"],
                    "",
                    count,
                    start_date,
                    end_date,
                    "start" if "最早" in self.lookup_prefer_var.get() else "end",
                    topic_max_pages=self._lookup_topic_limit,
                )
                if generation != self._lookup_generation:
                    return
                profile["nickname"] = profile.get("nickname") or info.get("nickname") or ""
                if profile.get("ok"):
                    if len(self._lookup_cache) >= 200:
                        self._lookup_cache.clear()
                    self._lookup_cache[cache_key] = (time.monotonic(), profile)
                self._post(("lookup_ready", profile, ""))
            except Exception as error:  # noqa: BLE001
                if generation == self._lookup_generation:
                    self._post(("lookup_ready", None, str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def _probe_profile_forums(self) -> None:
        if getattr(self, "_probe_running", False):
            self._probe_stop.set()
            return
        user = getattr(self, "_profile_user", None)
        profile = getattr(self, "_profile_data", None)
        if not user or not profile:
            return
        self._start_probe(user, profile, self.profile_probe_btn)

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

    def _render_lookup(self, profile) -> None:
        forum_tree = self.lookup_forum_tree
        post_tree = self.lookup_post_tree
        for tree in (forum_tree, post_tree):
            for item in tree.get_children():
                tree.delete(item)
        self._lookup_forum_names = {}
        self._lookup_post_urls = {}
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

        for index, forum in enumerate(combined):
            iid = str(index)
            forum_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    forum["name"],
                    f"Lv.{forum['level']}" if forum.get("level") else "-",
                    forum.get("source") or "",
                ),
                tags=self._row_tags(forum["name"], "forum"),
            )
            self._lookup_forum_names[iid] = forum["name"]
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
                ),
                tags=self._row_tags(post.get("bar"), "posts"),
            )
            self._lookup_post_urls[iid] = post.get("url") or ""
        forum_note = self._forum_note(profile)
        if self.mode_var.get() == "guest":
            forum_note += "（免登录：关注列表可能不完整）"
        self.lookup_forum_note.configure(text=forum_note)

        info = (
            f"昵称 {display_text(profile.get('nickname')) or '未知'} | 用户名 {profile.get('username') or '未知'} | "
            f"ID {profile.get('user_id') or '未知'} | 发言 {len(posts)} 条 | 关注 {len(combined)} 个"
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
            traffic_note += " · ⚠ 关注列表隐藏，未命中警告时标黄"
        try:
            self.lookup_traffic_text.configure(text=traffic_note)
        except tk.TclError:
            pass
        if hit_level:
            info += f" | 命中{label}：{hit_bar}"
        if hidden_follows and self._risk_enabled():
            info += " | ⚠ 关注列表隐藏，未命中警告时标黄"
        note = self._post_source_note(profile)
        if note:
            info += " | " + note
        self.lookup_info.configure(text=info)
        self.lookup_status.configure(
            text=(f"{profile.get('username') or ''} · {len(posts)} 条发言" + (f" · {note}" if note else ""))
        )
        self.lookup_report_btn.pack(side="left", padx=(0, 6))
        self.lookup_posts_btn.pack(side="left", padx=(0, 6))
        sources = profile.get("post_sources") or {}
        if sources.get("topic_truncated"):
            self.lookup_topic_btn.configure(
                text=f"继续抓主题（已 {sources.get('topic_pages') or 50} 页）"
            )
            self.lookup_topic_btn.pack(side="left", padx=(0, 6))
        else:
            self.lookup_topic_btn.pack_forget()
        if self._hidden_follows(profile):
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

    def _open_participants(self) -> None:
        if not self.last_threads:
            messagebox.showinfo("还没有数据", "先点「开始统计」抓一个帖子，再查看参与者。", parent=self.root)
            return
        self._refresh_people()
        self.notebook.select(self.tab_posts)
        self.post_nb.select(self.tab_people)

    def _sort_people(self, column: str) -> None:
        if getattr(self, "_batch_running", False):
            return
        if column not in ("mark", "level", "floor", "comment", "total"):
            return
        current, reverse = self._people_sort
        self._people_sort = (column, (not reverse) if current == column else False)
        self._people_page = 0
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
        if column == "uid":
            return user.get("uid") or "-"
        return ""

    def _filter_people_column(self, column: str, anchor: Optional[tuple] = None) -> None:
        if getattr(self, "_batch_running", False):
            return
        values = sorted({self._people_column_value(user, column) for user in self.people_users})
        chosen = self._filter_text_dialog(
            {"mark": "标记", "name": "昵称", "username": "用户名", "uid": "用户ID"}.get(column, column),
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
            values[3] = str(user.get("uid") or "-")
            level = str(user.get("level") or "")
            if level:
                values[4] = f"Lv.{level}"
            self.people_tree.item(
                iid,
                values=values,
                tags=(str(user.get("mark_level") or ""),)
                if user.get("mark_level") and self.settings.get("color_people", True)
                else (),
            )
        except tk.TclError:
            pass

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
            min_level=_optional_int(self.people_min_var.get()),
            max_level=_optional_int(self.people_max_var.get()),
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
        self._profile_cache = {}
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
                    user["uid"] or "-",
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
        self.profile_status.configure(text="选择左边一个人查看详情")
        for tree in (self.profile_forum_tree, self.profile_post_tree):
            for item in tree.get_children():
                tree.delete(item)

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

    def _on_people_paned_configure(self, event=None) -> None:
        if getattr(self, "_people_sash_set", False):
            return
        if event is not None and event.width < 500:
            return
        self._people_sash_set = True
        self.root.after_idle(self._set_people_sash)

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

    def _open_current_profile(self) -> None:
        selection = self.people_tree.selection()
        if not selection:
            return
        try:
            user = self.people_users[int(selection[0])]
        except (IndexError, ValueError):
            return
        username = user.get("username") or ""
        if username:
            webbrowser.open("https://tieba.baidu.com/home/main?un=" + quote(username))

    # ------------------------------------------------------------- risk marks
    def _risk_enabled(self) -> bool:
        return bool(self.settings.get("risk_enabled", False))

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
        if hasattr(self, "people_mark_box"):
            self.people_mark_box.configure(state="readonly" if enabled else "disabled")
            if not enabled:
                self.people_mark_var.set("全部")

    def _on_include_follows_changed(self) -> None:
        if getattr(self, "_batch_running", False):
            return
        if self.include_follows_var.get() and not self.settings.get("follow_enhance"):
            self.include_follows_var.set(False)

    def _on_follow_toggle(self) -> None:
        enabled = bool(self.follow_enhance_var.get())
        self.settings["follow_enhance"] = enabled
        if enabled:
            self._set_mode("login")
            if not parse_cookie_input(self.cookie_var.get()).get("BDUSS"):
                if self._ask_go_fill_bduss():
                    self._go_to_login()
        else:
            self._set_mode("guest")
        save_settings(self.settings)

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
            text="抓取增强已开启，但还没有填写 BDUSS。现在去抓取页填写吗？",
            bg="#eef1f5",
            fg="#334155",
            font=("Microsoft YaHei UI", 9),
            justify="left",
            wraplength=360,
        ).pack(fill="x", padx=14, pady=(14, 8))
        row = tk.Frame(win, bg="#eef1f5")
        row.pack(fill="x", padx=14, pady=(0, 12))

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
        width, height = 420, 150
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

    def _set_mode(self, mode: str, persist: bool = True) -> None:
        mode = mode if mode in ("guest", "login") else "guest"
        self.mode_var.set(mode)
        if persist:
            self.settings["mode"] = mode
            save_settings(self.settings)
        self._apply_mode_ui()

    def _build_settings_tab(self) -> None:
        wrap = tk.Frame(self.tab_settings, bg="#eef1f5")
        wrap.pack(fill="both", expand=True, padx=6, pady=6)
        sidebar = tk.Frame(wrap, bg="#ffffff", width=118)
        sidebar.pack(side="left", fill="y", padx=(0, 6))
        sidebar.pack_propagate(False)
        self.settings_nav = tk.Listbox(
            sidebar,
            activestyle="none",
            exportselection=False,
            font=("Microsoft YaHei UI", 9),
            bg="#ffffff",
            fg="#334155",
            selectbackground="#dbeafe",
            selectforeground="#1F4E79",
            relief="flat",
            highlightthickness=0,
        )
        self.settings_nav.pack(fill="both", expand=True)
        inner = tk.Frame(wrap, bg="#eef1f5")
        inner.pack(side="left", fill="both", expand=True)
        self.settings_inner = inner
        self.tab_general = tk.Frame(inner, bg="#eef1f5")
        self.tab_appearance = tk.Frame(inner, bg="#eef1f5")
        self.tab_blacklist = tk.Frame(inner, bg="#eef1f5")
        self.tab_storage = tk.Frame(inner, bg="#eef1f5")
        self.tab_about = tk.Frame(inner, bg="#eef1f5")
        self.settings_pages = [
            self.tab_general,
            self.tab_appearance,
            self.tab_blacklist,
            self.tab_storage,
            self.tab_about,
        ]
        self._build_general_tab()
        self._build_appearance_tab()
        self._build_storage_tab()
        self._build_about_tab()
        for label in ("常规", "外观", "本地标记", "结果与存储", "关于 / 帮助"):
            self.settings_nav.insert("end", f"  {label}")
        self.settings_nav.bind("<<ListboxSelect>>", self._on_settings_nav)
        self.settings_nav.selection_set(0)
        self._show_settings_page(0)

        box = tk.Frame(self.tab_blacklist, bg="#eef1f5", padx=16, pady=12)
        box.pack(fill="both", expand=True)
        tk.Label(
            box,
            text="本地标记：每行一个贴吧名（带不带“吧”都行），命中后按 警告 > 可疑 > 安全 标记。",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(0, 8))
        self.blacklist_editors = {}
        for key, title in (("safe", "安全（绿色）"), ("warn", "可疑（黄色）"), ("ban", "警告（红色）")):
            frame = ttk.LabelFrame(box, text=f" {title} ")
            frame.pack(fill="both", expand=True, pady=4)
            editor = tk.Text(frame, height=6, wrap="word", font=("Microsoft YaHei UI", 9))
            editor.pack(fill="both", expand=True, padx=6, pady=6)
            editor.insert("1.0", chr(10).join(self.blacklist.get(key, [])))
            self.blacklist_editors[key] = editor
        bar = tk.Frame(box, bg="#eef1f5")
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="保存本地标记", command=self._save_blacklist_from_tab).pack(side="left")
        ttk.Button(bar, text="导入 Excel", command=self._import_blacklist).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="导出 Excel", command=self._export_blacklist).pack(side="left", padx=(8, 0))
        self.settings_hint = tk.Label(
            bar, text="", bg="#eef1f5", fg="#15803d", font=("Microsoft YaHei UI", 9)
        )
        self.settings_hint.pack(side="left", padx=(10, 0))

    def _show_settings_page(self, index: int) -> None:
        for position, page in enumerate(self.settings_pages):
            if position == index:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()

    def _on_settings_start_changed(self) -> None:
        self.settings["settings_start"] = "last" if self.settings_start_var.get() == "上次分类" else "general"
        save_settings(self.settings)

    def _on_main_tab_changed(self, _event=None) -> None:
        if self.notebook.select() != str(self.tab_settings):
            return
        index = 0
        if self.settings.get("settings_start") == "last":
            index = getattr(self, "_last_settings_index", 0)
        if 0 <= index < self.settings_nav.size():
            self.settings_nav.selection_clear(0, "end")
            self.settings_nav.selection_set(index)
            self._show_settings_page(index)

    def _on_settings_nav(self, _event=None) -> None:
        selection = self.settings_nav.curselection()
        if selection:
            self._last_settings_index = selection[0]
            self._show_settings_page(selection[0])

    def _build_appearance_tab(self) -> None:
        box = tk.Frame(self.tab_appearance, bg="#eef1f5", padx=14, pady=10)
        box.pack(fill="both", expand=True)
        tk.Label(
            box,
            text="主题与强调色只影响应用内容区；系统文件选择框和系统提示框保持系统样式。",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        theme_box = ttk.LabelFrame(box, text=" 配色 ")
        theme_box.pack(fill="x", pady=(0, 6))
        row = tk.Frame(theme_box, bg="#eef1f5")
        row.pack(anchor="w", fill="x", padx=8, pady=(6, 3))
        tk.Label(row, text="模式：", width=14, anchor="w", bg="#eef1f5", fg="#475569").pack(side="left")
        self.theme_mode_var = tk.StringVar(
            value={"light": "浅色", "dark": "深色", "system": "跟随系统"}.get(
                self.settings.get("theme_mode", "light"), "浅色"
            )
        )
        self.theme_combo = ttk.Combobox(
            row,
            values=("浅色", "深色", "跟随系统"),
            textvariable=self.theme_mode_var,
            width=10,
            state="readonly",
        )
        self.theme_combo.pack(side="left")
        self.theme_mode_var.trace_add("write", lambda *_: self._on_theme_changed())
        row2 = tk.Frame(theme_box, bg="#eef1f5")
        row2.pack(anchor="w", fill="x", padx=8, pady=(2, 4))
        tk.Label(row2, text="强调色：", width=14, anchor="w", bg="#eef1f5", fg="#475569").pack(side="left")
        self.accent_var = tk.StringVar(
            value={
                "blue": "蓝色",
                "green": "绿色",
                "purple": "紫色",
                "orange": "橘黄",
                "pink": "粉色",
                "cyan": "青色",
                "red": "红色",
            }.get(self.settings.get("accent", "blue"), "蓝")
        )
        self.accent_combo = ttk.Combobox(
            row2,
            values=("蓝色", "绿色", "紫色", "橘黄", "粉色", "青色", "红色"),
            textvariable=self.accent_var,
            width=10,
            state="readonly",
        )
        self.accent_combo.pack(side="left")
        self.accent_var.trace_add("write", lambda *_: self._on_accent_changed())
        note = ttk.LabelFrame(box, text=" 说明 ")
        note.pack(fill="x")
        tk.Label(
            note,
            text="跟随系统只在启动时读取 Windows 设置；运行中切换系统主题，重启后生效。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
            wraplength=740,
            justify="left",
        ).pack(anchor="w", padx=8, pady=6)

    def _on_theme_changed(self) -> None:
        mode = {"浅色": "light", "深色": "dark", "跟随系统": "system"}.get(
            self.theme_mode_var.get(), "light"
        )
        self.settings["theme_mode"] = mode
        save_settings(self.settings)
        self._apply_theme()

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

    def _theme_widget_tree(self, widget, old_palette=None) -> None:
        palette = self.palette
        for option in (
            "bg",
            "fg",
            "activebackground",
            "activeforeground",
            "selectbackground",
            "selectforeground",
            "highlightbackground",
            "insertbackground",
            "disabledforeground",
        ):
            try:
                current = widget.cget(option)
            except tk.TclError:
                continue
            value = str(current)
            token_order = ("accent", "accent_hover", "selection_bg", "selection_text")
            old_token = ""
            current_token = ""
            for token in token_order:
                if old_palette and value.lower() == str(old_palette.get(token) or "").lower():
                    old_token = token
                    break
                if value.lower() == str(palette.get(token) or "").lower():
                    current_token = token
                    break
            try:
                text = str(widget.cget("text")) if "text" in widget.keys() else ""
            except tk.TclError:
                text = ""
            if widget.winfo_class() == "Label" and text in ("红", "黄", "绿", "白"):
                new = value
            elif old_token:
                new = palette[old_token]
            elif current_token:
                new = palette[current_token]
            else:
                new = map_color(option, value, palette)
            klass = widget.winfo_class()
            if value.startswith("System"):
                if option in ("bg", "background"):
                    new = palette["surface"] if klass in ("Text", "Entry", "Listbox") else palette["window_bg"]
                elif option in ("fg", "foreground"):
                    new = palette["text"]
                elif option == "insertbackground":
                    new = palette["text"]
            if new != current:
                try:
                    widget.configure(**{option: new})
                except tk.TclError:
                    pass
        try:
            if widget.winfo_class() in ("Text", "Entry", "Listbox"):
                widget.configure(
                    bg=palette["surface"],
                    fg=palette["text"],
                    insertbackground=palette["text"],
                    selectbackground=palette["selection_bg"],
                    selectforeground=palette["selection_text"],
                )
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._theme_widget_tree(child, old_palette)

    def _apply_theme(self) -> None:
        old_palette = dict(self.palette) if hasattr(self, "palette") else None
        palette = resolve_palette(
            str(self.settings.get("theme_mode", "light")),
            str(self.settings.get("accent", "blue")),
        )
        self.palette = palette
        self.root.configure(bg=palette["window_bg"])
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TFrame",
            background=palette["window_bg"],
        )
        style.configure("TLabel", background=palette["window_bg"], foreground=palette["text"])
        style.configure(
            "TLabelframe",
            background=palette["window_bg"],
            bordercolor=palette["border"],
            lightcolor=palette["border"],
            darkcolor=palette["border"],
        )
        style.configure(
            "TLabelframe.Label",
            background=palette["window_bg"],
            foreground=palette["text"],
        )
        style.configure(
            "TCheckbutton",
            background=palette["window_bg"],
            foreground=palette["text"],
            indicatorbackground=palette["surface"],
            indicatorforeground=palette["surface"],
            upperbordercolor=palette["border"],
            lowerbordercolor=palette["border"],
        )
        style.map(
            "TCheckbutton",
            indicatorbackground=[("selected", palette["accent"]), ("!selected", palette["surface"])],
            indicatorforeground=[("selected", palette["accent_text"]), ("!selected", palette["surface"])],
        )
        style.configure(
            "TRadiobutton",
            background=palette["window_bg"],
            foreground=palette["text"],
            indicatorbackground=palette["surface"],
            indicatorforeground=palette["surface"],
            upperbordercolor=palette["border"],
            lowerbordercolor=palette["border"],
        )
        style.map(
            "TRadiobutton",
            indicatorbackground=[("selected", palette["accent"]), ("!selected", palette["surface"])],
            indicatorforeground=[("selected", palette["accent_text"]), ("!selected", palette["surface"])],
        )
        style.configure(
            "TButton",
            background=palette["button_bg"],
            foreground=palette["button_text"],
            bordercolor=palette["border"],
            lightcolor=palette["button_bg"],
            darkcolor=palette["button_bg"],
        )
        style.map(
            "TButton",
            background=[("active", palette["button_hover"]), ("disabled", palette["disabled_bg"])],
            foreground=[("disabled", palette["disabled_text"])],
        )
        style.configure(
            "TEntry",
            fieldbackground=palette["surface"],
            foreground=palette["text"],
            insertcolor=palette["text"],
            bordercolor=palette["border"],
        )
        style.configure(
            "TCombobox",
            fieldbackground=palette["surface"],
            foreground=palette["text"],
            background=palette["button_bg"],
            arrowcolor=palette["text"],
            bordercolor=palette["border"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette["surface"]), ("!disabled", palette["surface"])],
            foreground=[("readonly", palette["text"])],
            selectbackground=[("readonly", palette["selection_bg"])],
            selectforeground=[("readonly", palette["selection_text"])],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=palette["surface"],
            foreground=palette["text"],
            background=palette["button_bg"],
            arrowcolor=palette["text"],
            bordercolor=palette["border"],
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("!disabled", palette["surface"])],
            foreground=[("!disabled", palette["text"])],
        )
        style.configure(
            "Treeview",
            background=palette["table_bg"],
            fieldbackground=palette["table_bg"],
            foreground=palette["text"],
            bordercolor=palette["border"],
        )
        style.configure(
            "Treeview.Heading",
            background=palette["table_header_bg"],
            foreground=palette["table_header_text"],
            bordercolor=palette["border"],
        )
        style.map(
            "Treeview",
            background=[("selected", palette["selection_bg"])],
            foreground=[("selected", palette["selection_text"])],
        )
        style.configure("TNotebook", background=palette["window_bg"], bordercolor=palette["border"])
        style.configure(
            "TNotebook.Tab",
            background=palette["button_bg"],
            foreground=palette["text_secondary"],
            padding=(9, 3),
        )
        style.configure(
            "TNotebook.Tab",
            background=palette["button_bg"],
            foreground=palette["text_secondary"],
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", palette["surface"])],
            foreground=[("selected", palette["accent"])],
        )
        style.configure("Main.TNotebook", background=palette["window_bg"])
        style.configure(
            "Main.TNotebook.Tab",
            background=palette["button_bg"],
            foreground=palette["text_secondary"],
            padding=(16, 7),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "Main.TNotebook.Tab",
            background=[("selected", palette["surface"])],
            foreground=[("selected", palette["accent"])],
        )
        style.configure("Sub.TNotebook", background=palette["window_bg"])
        style.configure(
            "Sub.TNotebook.Tab",
            background=palette["button_bg"],
            foreground=palette["text_secondary"],
            padding=(9, 3),
            font=("Microsoft YaHei UI", 9),
        )
        style.map(
            "Sub.TNotebook.Tab",
            background=[("selected", palette["surface"])],
            foreground=[("selected", palette["accent"])],
        )
        style.configure(
            "TScrollbar",
            background=palette["button_bg"],
            troughcolor=palette["surface_alt"],
            bordercolor=palette["border"],
            lightcolor=palette["button_bg"],
            darkcolor=palette["button_bg"],
            arrowcolor=palette["text_secondary"],
        )
        style.map("TScrollbar", background=[("active", palette["button_hover"])])
        for element in ("Vertical.Scrollbar.trough", "Vertical.Scrollbar.thumb"):
            style.configure(
                element,
                background=palette["button_bg"],
                troughcolor=palette["surface_alt"],
                bordercolor=palette["border"],
                lightcolor=palette["button_bg"],
                darkcolor=palette["button_bg"],
                arrowcolor=palette["text_secondary"],
            )
        for element in ("Horizontal.Scrollbar.trough", "Horizontal.Scrollbar.thumb"):
            style.configure(
                element,
                background=palette["button_bg"],
                troughcolor=palette["surface_alt"],
                bordercolor=palette["border"],
                lightcolor=palette["button_bg"],
                darkcolor=palette["button_bg"],
                arrowcolor=palette["text_secondary"],
            )
        style.configure(
            "Vertical.TScrollbar",
            background=palette["button_bg"],
            troughcolor=palette["surface_alt"],
            arrowcolor=palette["text_secondary"],
            bordercolor=palette["border"],
            lightcolor=palette["button_bg"],
            darkcolor=palette["button_bg"],
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=palette["button_bg"],
            troughcolor=palette["surface_alt"],
            arrowcolor=palette["text_secondary"],
            bordercolor=palette["border"],
            lightcolor=palette["button_bg"],
            darkcolor=palette["button_bg"],
        )
        style.configure(
            "TProgressbar",
            background=palette["accent"],
            troughcolor=palette["surface_alt"],
        )
        self.root.option_add("*TCombobox*Listbox.background", palette["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", palette["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", palette["selection_bg"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", palette["selection_text"])

        self._theme_widget_tree(self.root, old_palette)

        if hasattr(self, "log_text"):
            self.log_text.tag_configure("title", foreground=palette["accent"])
            self.log_text.tag_configure("ok", foreground=palette["safe"])
            self.log_text.tag_configure("err", foreground=palette["danger"])
            self.log_text.tag_configure("muted", foreground=palette["text_muted"])

        def all_trees(widget):
            found = []
            if isinstance(widget, ttk.Treeview):
                found.append(widget)
            for child in widget.winfo_children():
                found.extend(all_trees(child))
            return found

        for tree in all_trees(self.root):
            tree.tag_configure("ban", background=palette["danger_bg"])
            tree.tag_configure("warn", background=palette["warning_bg"])
            tree.tag_configure("safe", background=palette["safe_bg"])
            tree.tag_configure("odd", background=palette["table_alt"])
        for key, value in (("ban", "danger"), ("warn", "warning"), ("safe", "safe")):
            entry = getattr(self, "lookup_traffic_labels", {}).get(key)
            if entry:
                entry[0].configure(fg=palette[value])
        pass

    def _build_storage_tab(self) -> None:
        box = tk.Frame(self.tab_storage, bg="#eef1f5", padx=14, pady=10)
        box.pack(fill="both", expand=True)

        save_box = ttk.LabelFrame(box, text=" 保存与恢复 ")
        save_box.pack(fill="x", pady=(0, 6))
        self.save_result_var = tk.BooleanVar(value=bool(self.settings.get("save_result", True)))
        ttk.Checkbutton(
            save_box,
            text="保存最近结果",
            variable=self.save_result_var,
            command=self._on_save_result_toggle,
        ).pack(anchor="w", padx=8, pady=(4, 0))
        self.encrypt_var = tk.BooleanVar(value=bool(self.settings.get("encrypt_result", False)))
        ttk.Checkbutton(
            save_box,
            text="加密保存结果（DPAPI，仅当前 Windows 用户可读）",
            variable=self.encrypt_var,
            command=self._on_encrypt_toggle,
        ).pack(anchor="w", padx=8, pady=(2, 0))
        row = tk.Frame(save_box, bg="#eef1f5")
        row.pack(anchor="w", fill="x", padx=8, pady=(4, 2))
        tk.Label(row, text="启动时恢复：", width=14, anchor="w", bg="#eef1f5", fg="#475569").pack(side="left")
        self.restore_mode_var = tk.StringVar(
            value="询问" if self.settings.get("restore_mode") == "ask" else "自动"
        )
        ttk.Combobox(
            row,
            values=("自动", "询问"),
            textvariable=self.restore_mode_var,
            width=6,
            state="readonly",
        ).pack(side="left")
        self.restore_mode_var.trace_add("write", lambda *_: self._on_restore_mode_changed())
        tk.Label(
            save_box,
            text="结果只保存最近一次，不保存 Cookie 和本地标记。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=8, pady=(2, 4))

        log_box = ttk.LabelFrame(box, text=" 运行日志 ")
        log_box.pack(fill="x", pady=(0, 6))
        self.log_enabled_var = tk.BooleanVar(value=bool(self.settings.get("log_enabled", False)))
        ttk.Checkbutton(
            log_box,
            text="保存运行日志（默认关闭，不含 Cookie/正文）",
            variable=self.log_enabled_var,
            command=self._on_log_toggle,
        ).pack(anchor="w", padx=8, pady=(4, 0))
        tk.Label(
            log_box,
            text="日志目录：%APPDATA%\\TiebaReplyStats\\logs",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=8, pady=(2, 4))

        cache_box = ttk.LabelFrame(box, text=" 发言缓存 ")
        cache_box.pack(fill="x", pady=(0, 6))
        cache_row = tk.Frame(cache_box, bg="#eef1f5")
        cache_row.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(cache_row, text="上限：", bg="#eef1f5", fg="#475569").pack(side="left")
        self.cache_limit_var = tk.StringVar(
            value=str(int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB)))
        )
        self.cache_limit_box = ttk.Spinbox(
            cache_row,
            from_=MIN_LIMIT_MB,
            to=MAX_LIMIT_MB,
            increment=50,
            width=7,
            textvariable=self.cache_limit_var,
            command=self._on_cache_limit_changed,
        )
        self.cache_limit_box.pack(side="left")
        self.cache_limit_box.bind("<FocusOut>", lambda _event: self._on_cache_limit_changed())
        self.cache_limit_box.bind("<Return>", lambda _event: self._on_cache_limit_changed())
        tk.Label(cache_row, text="MB", bg="#eef1f5", fg="#475569").pack(side="left")
        ttk.Button(cache_row, text="清除发言缓存", command=self._clear_post_cache, width=14).pack(
            side="right"
        )
        self.cache_stats_label = tk.Label(
            cache_box,
            text="",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
        )
        self.cache_stats_label.pack(fill="x", padx=8, pady=(2, 4))
        self._refresh_cache_stats()

        maint_box = ttk.LabelFrame(box, text=" 数据位置与维护 ")
        maint_box.pack(fill="x")
        data_row = tk.Frame(maint_box, bg="#eef1f5")
        data_row.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(
            data_row,
            text=f"数据：{APP_DIR}",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(data_row, text="打开", command=lambda: self._open_folder(APP_DIR), width=8).pack(
            side="right"
        )
        temp_row = tk.Frame(maint_box, bg="#eef1f5")
        temp_row.pack(fill="x", padx=8, pady=(2, 2))
        tk.Label(
            temp_row,
            text="临时：%TEMP%\\TiebaReplyStats",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            temp_row,
            text="打开",
            command=lambda: self._open_folder(os.path.join(os.environ.get("TEMP", ""), "TiebaReplyStats")),
            width=8,
        ).pack(side="right")
        buttons = tk.Frame(maint_box, bg="#eef1f5")
        buttons.pack(fill="x", padx=8, pady=(4, 2))
        ttk.Button(buttons, text="删除当前结果", command=self._clear_result, width=14).pack(side="left")
        self.old_files_label = tk.Label(
            buttons, text="", bg="#eef1f5", fg="#8a94a6", font=("Microsoft YaHei UI", 8)
        )
        self.old_files_label.pack(side="left", padx=(10, 0))
        ttk.Button(buttons, text="清理旧版本残留", command=self._cleanup_old_results, width=14).pack(side="right")
        self._refresh_old_files_label()
        danger = tk.Frame(maint_box, bg="#eef1f5")
        danger.pack(fill="x", padx=8, pady=(6, 4))
        tk.Button(
            danger,
            text="清空所有本地数据",
            command=self._clear_all_data,
            bg="#ffdede",
            fg="#dc2626",
            activebackground="#fecaca",
            activeforeground="#7f1d1d",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Label(
            maint_box,
            text="清空所有本地数据不会删除你导出的 Excel 或 Markdown；恢复默认设置在「常规」。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=8, pady=(0, 4))

    def _on_cache_limit_changed(self) -> None:
        try:
            value = int(float(self.cache_limit_var.get().strip()))
        except (TypeError, ValueError):
            value = int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB))
        value = max(MIN_LIMIT_MB, min(MAX_LIMIT_MB, value))
        old = int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB))
        if value < old:
            if not messagebox.askokcancel(
                "降低发言缓存上限",
                "降低上限会立即清除部分发言缓存，之后查询可能变慢。\n"
                "不会删除 Excel、本地标记或最近结果。\n\n继续？",
                parent=self.root,
            ):
                self.cache_limit_var.set(str(old))
                return
        self.cache_limit_var.set(str(value))
        self.settings["post_cache_limit_mb"] = value
        save_settings(self.settings)
        post_cache().set_limit_mb(value)
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

    def _build_about_tab(self) -> None:
        box = tk.Frame(self.tab_about, bg="#eef1f5", padx=14, pady=10)
        box.pack(fill="both", expand=True)
        tk.Label(
            box,
            text=f"{APP_TITLE} v{VERSION}",
            bg="#eef1f5",
            fg="#1F4E79",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            box,
            text="默认匿名 · 结果只存本机 · 不保存 STOKEN · 支持浅色/深色",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(2, 8))

        help_box = ttk.LabelFrame(box, text=" 帮助与诊断 ")
        help_box.pack(fill="x", pady=(0, 6))
        help_row = tk.Frame(help_box, bg="#eef1f5")
        help_row.pack(anchor="w", padx=8, pady=(6, 2))
        ttk.Button(help_row, text="打开使用说明", command=self._open_usage_window, width=14).pack(side="left")
        ttk.Button(help_row, text="第三方许可", command=self._open_notice, width=12).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(help_row, text="复制诊断信息", command=self._copy_diagnostics, width=14).pack(
            side="left", padx=(8, 0)
        )
        tk.Label(
            help_box,
            text="第三方组件：Python / PyInstaller / lxml / openpyxl / Tcl-Tk，各自按其许可证分发。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(2, 4))

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

    def _on_log_toggle(self) -> None:
        self.settings["log_enabled"] = bool(self.log_enabled_var.get())
        save_settings(self.settings)

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
            self.status_var.set("没有需要清理的旧版本残留")
            return
        if not messagebox.askyesno(
            "清理旧版本残留",
            f"删除 {len(files)} 个旧版本残留文件？不会影响当前结果。",
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
        self._append_log(f"已清理旧版本残留：{len(files)} 个", "muted")

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
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.focus_set()

    def _open_folder(self, path: str) -> None:
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as error:
            messagebox.showerror("打不开目录", friendly_error(error), parent=self.root)

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

    def _ask_choice(self, title: str, message: str, choices, default: int = 0):
        """带明确按钮文案的模态选择框；choices=[(label,value),...]，None 表示取消。"""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg="#ffffff")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
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
                ttk.Button(buttons, text=label, command=command(value), width=12).pack(
                    side="right", padx=(8, 0)
                )
        win.bind("<Return>", lambda _event: finish(choices[default][1]))
        win.bind("<Escape>", lambda _event: finish(None))
        win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
        win.update_idletasks()
        width, height = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 3)
        self._theme_widget_tree(win)
        win.geometry(f"+{x}+{y}")
        self.root.wait_window(win)
        return result["value"]

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
        text.configure(state="normal")
        text.insert("1.0", content or "使用说明文件未找到。")
        text.configure(state="disabled")
        self._theme_widget_tree(win)
        win.bind("<Escape>", lambda _event: win.destroy())
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.focus_set()

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
        self.settings = load_settings()
        self.settings["onboarding_seen"] = keep_onboarding
        self.settings["window_geometry"] = keep_geometry
        save_settings(self.settings)
        self.risk_var.set(True)
        self.follow_enhance_var.set(False)
        self._set_mode("guest")
        self._apply_risk_ui()
        self._append_log("设置已恢复默认（结果、标记、BDUSS 保留）。", "muted")

    def _clear_all_data(self) -> None:
        if not messagebox.askyesno(
            "清空软件数据（不会删除导出文件）",
            "会删除：最近结果、保存的 BDUSS、本地标记、设置、临时文件、日志。\n"
            "不会删除：导出的 Excel、Markdown 或你保存到其他位置的文件。\n\n继续？",
            parent=self.root,
        ):
            return
        if simpledialog.askstring("确认清空", "输入“清空”后继续：", parent=self.root) != "清空":
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
        post_cache().set_limit_mb(int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB)))
        if hasattr(self, "cache_limit_var"):
            self.cache_limit_var.set(str(int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB))))
        self.blacklist = {"safe": [], "warn": [], "ban": []}
        self.last_threads = []
        self.last_output = None
        self.cookie_var.set("")
        self.save_result_var.set(True)
        self.encrypt_var.set(False)
        self.log_enabled_var.set(False)
        self.restore_mode_var.set("自动")
        self.risk_var.set(True)
        self.follow_enhance_var.set(False)
        self._set_mode("guest")
        self._apply_risk_ui()
        self.open_btn.configure(state="disabled")
        for key, editor in getattr(self, "blacklist_editors", {}).items():
            editor.delete("1.0", "end")
        self._refresh_people()
        self._refresh_grid()
        self._refresh_old_files_label()
        self._append_log("软件数据已清空；导出文件未受影响。", "ok")

    def _build_general_tab(self) -> None:
        box = tk.Frame(self.tab_general, bg="#eef1f5", padx=14, pady=10)
        box.pack(fill="both", expand=True)
        risk_box = ttk.LabelFrame(box, text=" 本地标记（红绿灯） ")
        risk_box.pack(fill="x", pady=(0, 6))
        self.risk_var = tk.BooleanVar(value=bool(self.settings.get("risk_enabled", False)))
        ttk.Checkbutton(
            risk_box,
            text="启用本地标记与红绿灯",
            variable=self.risk_var,
            command=self._on_risk_toggle,
        ).pack(anchor="w")
        tk.Label(
            risk_box,
            text="仅用于本地记录，请勿用于挂人、骚扰或公开曝光。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=20, pady=(2, 0))

        enhance_box = ttk.LabelFrame(box, text=" 抓取增强（可选） ")
        enhance_box.pack(fill="x", pady=(0, 6))
        self.follow_enhance_var = tk.BooleanVar(value=bool(self.settings.get("follow_enhance", False)))
        ttk.Checkbutton(
            enhance_box,
            text="启用公开关注 / 隐藏关注检测（需要 BDUSS）",
            variable=self.follow_enhance_var,
            command=self._on_follow_toggle,
        ).pack(anchor="w")
        tk.Label(
            enhance_box,
            text="默认关闭；开启后红绿灯可选“包含关注（慢）”。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=20, pady=(2, 0))
        mode_row = tk.Frame(enhance_box, bg="#eef1f5")
        mode_row.pack(anchor="w", padx=20, pady=(4, 0))
        tk.Label(mode_row, text="关注加载：", bg="#eef1f5", fg="#475569").pack(side="left")
        self.follow_load_mode_var = tk.StringVar(
            value="手动" if self.settings.get("follow_load_mode") == "manual" else "自动"
        )
        ttk.Combobox(
            mode_row,
            values=("自动", "手动"),
            textvariable=self.follow_load_mode_var,
            width=6,
            state="readonly",
        ).pack(side="left")
        self.follow_load_mode_var.trace_add("write", lambda *_: self._on_follow_load_mode_changed())

        fetch_box = ttk.LabelFrame(box, text=" 抓取行为 ")
        fetch_box.pack(fill="x", pady=(0, 6))
        self.auto_refresh_var = tk.BooleanVar(value=bool(self.settings.get("auto_refresh_old", False)))
        ttk.Checkbutton(
            fetch_box,
            text="再次抓取时自动刷新已抓帖子",
            variable=self.auto_refresh_var,
            command=self._on_fetch_settings_changed,
        ).pack(anchor="w", padx=8, pady=(4, 0))
        removed_row = tk.Frame(fetch_box, bg="#eef1f5")
        removed_row.pack(anchor="w", fill="x", padx=8, pady=(4, 0))
        tk.Label(
            removed_row, text="输入框已移除的旧帖：", width=18, anchor="w", bg="#eef1f5", fg="#475569"
        ).pack(side="left")
        self.removed_action_var = tk.StringVar(
            value={"keep": "保留旧结果", "remove": "移除旧结果", "ask": "每次询问"}.get(
                self.settings.get("removed_thread_action", "keep"), "保留旧结果"
            )
        )
        ttk.Combobox(
            removed_row,
            values=("保留旧结果", "移除旧结果", "每次询问"),
            textvariable=self.removed_action_var,
            width=10,
            state="readonly",
        ).pack(side="left")
        self.removed_action_var.trace_add("write", lambda *_: self._on_fetch_settings_changed())
        proxy_row = tk.Frame(fetch_box, bg="#eef1f5")
        proxy_row.pack(anchor="w", fill="x", padx=8, pady=(4, 0))
        tk.Label(proxy_row, text="网络代理：", width=18, anchor="w", bg="#eef1f5", fg="#475569").pack(side="left")
        self.proxy_mode_var = tk.StringVar(
            value={"system": "跟随系统", "none": "不使用", "custom": "自定义"}.get(
                self.settings.get("proxy_mode", "system"), "跟随系统"
            )
        )
        ttk.Combobox(
            proxy_row,
            values=("跟随系统", "不使用", "自定义"),
            textvariable=self.proxy_mode_var,
            width=8,
            state="readonly",
        ).pack(side="left")
        self.proxy_url_var = tk.StringVar(value=self.settings.get("proxy_url", ""))
        ttk.Entry(proxy_row, textvariable=self.proxy_url_var, width=32).pack(side="left", padx=(6, 0))
        self.proxy_mode_var.trace_add("write", lambda *_: self._on_proxy_changed())
        self.proxy_url_var.trace_add("write", lambda *_: self._on_proxy_changed())
        batch_row = tk.Frame(fetch_box, bg="#eef1f5")
        batch_row.pack(anchor="w", fill="x", padx=8, pady=(4, 0))
        tk.Label(batch_row, text="一键红绿灯并发：", width=18, anchor="w", bg="#eef1f5", fg="#475569").pack(side="left")
        self.batch_concurrency_var = tk.StringVar(value=str(self.settings.get("batch_concurrency", 1)))
        ttk.Combobox(
            batch_row,
            values=("1", "2", "3"),
            textvariable=self.batch_concurrency_var,
            width=4,
            state="readonly",
        ).pack(side="left")
        self.batch_concurrency_var.trace_add("write", lambda *_: self._on_batch_concurrency_changed())
        tk.Label(batch_row, text="（含关注时强制 1）", bg="#eef1f5", fg="#8a94a6", font=("Microsoft YaHei UI", 8)).pack(
            side="left", padx=(6, 0)
        )

        ui_box = ttk.LabelFrame(box, text=" 界面 ")
        ui_box.pack(fill="x", pady=(0, 6))
        start_row = tk.Frame(ui_box, bg="#eef1f5", padx=8, pady=4)
        start_row.pack(anchor="w", fill="x")
        tk.Label(start_row, text="打开设置时停在：", width=18, anchor="w", bg="#eef1f5", fg="#475569").pack(side="left")
        self.settings_start_var = tk.StringVar(
            value="上次分类" if self.settings.get("settings_start") == "last" else "常规"
        )
        ttk.Combobox(
            start_row,
            values=("常规", "上次分类"),
            textvariable=self.settings_start_var,
            width=8,
            state="readonly",
        ).pack(side="left")
        self.settings_start_var.trace_add("write", lambda *_: self._on_settings_start_changed())

        default_box = ttk.LabelFrame(box, text=" 默认设置 ")
        default_box.pack(fill="x", pady=(0, 6))
        default_row = tk.Frame(default_box, bg="#eef1f5")
        default_row.pack(anchor="w", padx=8, pady=(6, 4))
        ttk.Button(
            default_row, text="恢复默认设置", command=self._restore_defaults, width=14
        ).pack(side="left")
        tk.Label(
            default_box,
            text="只重置设置，保留最近结果、本地标记、BDUSS 和导出文件。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=8, pady=(0, 4))

        backup_box = ttk.LabelFrame(box, text=" 设置备份 / 恢复 ")
        backup_box.pack(fill="x", pady=(0, 6))
        ttk.Button(backup_box, text="备份设置", command=self._backup_config, width=12).pack(
            side="left", padx=(8, 8), pady=4
        )
        ttk.Button(backup_box, text="恢复设置", command=self._restore_config, width=12).pack(
            side="left", pady=4
        )
        tk.Label(
            backup_box,
            text="只含设置和本地标记，不含 Cookie",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left", padx=(10, 0))

        color_box = ttk.LabelFrame(box, text=" 表格颜色 ")
        color_box.pack(fill="x", pady=(0, 6))
        self.setting_vars = {}
        for key, text in (
            ("color_people", "在参与者列表里标色"),
            ("color_forum", "在「关注的贴吧」表格里标色"),
            ("color_posts", "在「发言」表格里标色"),
        ):
            var = tk.BooleanVar(value=bool(self.settings.get(key, True)))
            ttk.Checkbutton(color_box, text=text, variable=var, command=self._on_settings_changed).pack(
                anchor="w", padx=8, pady=3
            )
            self.setting_vars[key] = var
        self.general_hint = tk.Label(
            box,
            text="改完立即生效（已打开的数据会自动重画）",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 9),
        )
        self.general_hint.pack(anchor="w", pady=(10, 0))
        for block in (risk_box, color_box, fetch_box, enhance_box, ui_box, default_box, backup_box):
            block.pack_forget()
        for block in (risk_box, color_box, fetch_box, enhance_box, ui_box, default_box, backup_box):
            block.pack(fill="x", pady=(0, 6), before=self.general_hint)

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

    def _on_batch_concurrency_changed(self) -> None:
        try:
            value = int(self.batch_concurrency_var.get())
        except ValueError:
            value = 1
        self.settings["batch_concurrency"] = max(1, min(3, value))
        save_settings(self.settings)

    def _on_fetch_settings_changed(self) -> None:
        self.settings["auto_refresh_old"] = bool(self.auto_refresh_var.get())
        value = {"保留旧结果": "keep", "移除旧结果": "remove", "每次询问": "ask"}.get(
            self.removed_action_var.get(), "keep"
        )
        self.settings["removed_thread_action"] = value
        save_settings(self.settings)

    def _on_settings_changed(self) -> None:
        for key, var in getattr(self, "setting_vars", {}).items():
            self.settings[key] = bool(var.get())
        save_settings(self.settings)
        selection = self.people_tree.selection() if hasattr(self, "people_tree") else ()
        if selection:
            try:
                user = self.people_users[int(selection[0])]
            except (IndexError, ValueError):
                user = None
            if user:
                cached = getattr(self, "_profile_cache", {}).get(user["uid"] or f"name:{user['name']}")
                if cached:
                    self._render_profile(user, cached)
        if getattr(self, "_last_lookup_profile", None):
            self._render_lookup(self._last_lookup_profile)
        self.general_hint.configure(text="已保存")

    def _backup_config(self) -> None:
        path = filedialog.asksaveasfilename(
            title="备份设置",
            defaultextension=".json",
            filetypes=[("JSON 配置", "*.json"), ("ZIP 压缩包", "*.zip")],
            initialfile="贴吧统计设置.json",
            parent=self.root,
        )
        if not path:
            return
        try:
            saved = write_backup(path, self.settings, self.blacklist)
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("备份失败", friendly_error(error), parent=self.root)
            return
        self._append_log(f"设置已备份：{saved}", "ok")
        messagebox.showinfo(
            "备份完成",
            "已保存到：" + chr(10) + saved,
            parent=self.root,
        )

    def _restore_config(self) -> None:
        path = filedialog.askopenfilename(
            title="恢复设置",
            filetypes=[("设置备份", "*.json *.zip"), ("所有文件", "*.*")],
            parent=self.root,
        )
        if not path:
            return
        try:
            data = read_backup(path)
        except ValueError as error:
            messagebox.showerror("无法恢复", friendly_error(error), parent=self.root)
            return
        if not messagebox.askyesno(
            "恢复设置",
            backup_preview(data) + chr(10) + chr(10) + "会覆盖当前设置和本地标记，继续吗？",
            parent=self.root,
        ):
            return
        try:
            import tempfile

            write_backup(
                os.path.join(tempfile.gettempdir(), "tieba-config-before-restore.json"),
                self.settings,
                self.blacklist,
            )
        except Exception:  # noqa: BLE001
            pass
        self.settings.update(data["settings"])
        save_settings(self.settings)
        self.blacklist = data["blacklist"]
        save_blacklist(self.blacklist)
        self._on_mark_rules_changed()
        follow = bool(self.settings.get("follow_enhance", False))
        if follow and not parse_cookie_input(self.cookie_var.get()).get("BDUSS"):
            follow = False
            self.settings["follow_enhance"] = False
        if hasattr(self, "follow_enhance_var"):
            self.follow_enhance_var.set(follow)
        self.mode_var.set("login" if follow else "guest")
        self.risk_var.set(bool(self.settings.get("risk_enabled", False)))
        for key, var in getattr(self, "setting_vars", {}).items():
            var.set(bool(self.settings.get(key, True)))
        for key, editor in getattr(self, "blacklist_editors", {}).items():
            editor.delete("1.0", "end")
            editor.insert("1.0", chr(10).join(self.blacklist.get(key, [])))
        self._apply_mode_ui()
        self._apply_risk_ui()
        self._refresh_people()
        if getattr(self, "_last_lookup_profile", None):
            self._render_lookup(self._last_lookup_profile)
        self._append_log("配置已恢复。", "ok")
        self.status_var.set("配置已恢复")

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

    def _build_grid_tab(self) -> None:
        bar = tk.Frame(self.tab_grid, bg="#ffffff", padx=12, pady=7)
        bar.pack(fill="x")
        tk.Label(bar, text="帖子：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.grid_thread_var = tk.StringVar()
        self.grid_thread_box = ttk.Combobox(
            bar, textvariable=self.grid_thread_var, width=38, state="readonly"
        )
        self.grid_thread_box.pack(side="left")
        self.grid_thread_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_grid())
        self.manage_results_btn = ttk.Button(
            bar, text="管理帖子结果", command=self._open_manage_results, width=12
        )
        self.manage_results_btn.pack(side="left", padx=(6, 0))

        right = tk.Frame(bar, bg="#ffffff")
        right.pack(side="right")
        self.open_btn = tk.Button(
            right,
            text="打开 Excel",
            command=self._open_result,
            bg="#e5e9f0",
            fg="#334155",
            activebackground="#d5dbe5",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
            state="disabled",
        )
        self.open_btn.pack(side="right")
        self.export_btn = tk.Button(
            right,
            text="导出 Excel",
            command=self._export_now,
            bg="#1F4E79",
            fg="#ffffff",
            activebackground="#163b5c",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.export_btn.pack(side="right", padx=(0, 8))
        self.table_density_var = tk.StringVar(
            value="紧凑" if self.settings.get("table_density") == "compact" else "舒适"
        )
        ttk.Combobox(
            right,
            values=("舒适", "紧凑"),
            textvariable=self.table_density_var,
            width=5,
            state="readonly",
        ).pack(side="right", padx=(0, 10))
        tk.Label(right, text="密度", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 8)).pack(
            side="right"
        )
        self.table_density_var.trace_add("write", lambda *_: self._on_table_density_changed())

        hint_bar = tk.Frame(self.tab_grid, bg="#ffffff", padx=12, pady=2)
        hint_bar.pack(fill="x")
        self.grid_hint = tk.Label(
            hint_bar,
            text="表格可排序、双击打开链接、Ctrl+C 复制 · 界面直接显示单色 emoji，导出保留原样",
            bg="#ffffff",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        )
        self.grid_hint.pack(side="left")

        self.grid_nb = ttk.Notebook(self.tab_grid, style="Sub.TNotebook")
        self.grid_nb.pack(fill="both", expand=True, padx=8, pady=8)

    def _apply_table_density(self) -> None:
        compact = self.settings.get("table_density") == "compact"
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=25 if compact else 31)

    def _on_table_density_changed(self) -> None:
        self.settings["table_density"] = "compact" if self.table_density_var.get() == "紧凑" else "comfortable"
        save_settings(self.settings)
        self._apply_table_density()

    def _update_grid_selector(self) -> None:
        if not hasattr(self, "grid_thread_box"):
            return
        values = ["全部帖子（汇总）"]
        for index, thread in enumerate(self.last_threads, start=1):
            title = display_text(thread.meta.title or thread.meta.tid)
            values.append(f"{index}. {title}")
        self.grid_thread_box.configure(values=values)
        current = self.grid_thread_var.get()
        if current not in values:
            self.grid_thread_var.set(values[1] if len(values) > 1 else values[0])

    def _selected_grid_threads(self):
        if not self.last_threads:
            return []
        value = self.grid_thread_var.get()
        if value.startswith("全部"):
            return list(self.last_threads)
        for index, thread in enumerate(self.last_threads, start=1):
            if value.startswith(f"{index}. "):
                return [thread]
        return [self.last_threads[0]]

    def _aggregate_threads(self, threads):
        buckets = {}
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
                if not bucket["level"] and item["level"]:
                    bucket["level"] = item["level"]
                if not bucket["badge"] and item["badge"]:
                    bucket["badge"] = item["badge"]
        users = list(buckets.values())
        for user in users:
            user["aliases"] = sorted(a for a in user.get("aliases", ()) if a and a != user["name"])
        users.sort(key=lambda item: (-item["total"], -item["floor"], item["name"]))
        return users

    def _refresh_grid(self) -> None:
        for tab in list(self.grid_nb.tabs()):
            self.grid_nb.forget(tab)
        if not self.last_threads:
            self.grid_hint.configure(text="还没有数据")
            return
        self._update_grid_selector()
        threads = self._selected_grid_threads()
        all_mode = len(threads) > 1 or self.grid_thread_var.get().startswith("全部")
        include_op = getattr(self, "last_include_op", True)

        def user_url(item):
            if item.get("username"):
                return "https://tieba.baidu.com/home/main?un=" + quote(item["username"])
            portrait = str(item.get("portrait") or "").split("?")[0]
            if portrait:
                return "https://tieba.baidu.com/home/main?id=" + quote(portrait)
            return ""

        stats = self._aggregate_threads(threads)
        if all_mode:
            headers = ["#", "昵称", "用户名", "用户ID", "等级", "头衔", "参与帖子", "楼层", "楼中楼", "合计"]
            user_rows = [
                [
                    index,
                    self._display_name(item),
                    display_text(item["username"]),
                    item["uid"],
                    item["level"],
                    display_text(item["badge"]),
                    item["threads"],
                    item["floor"],
                    item["comment"],
                    item["total"],
                ]
                for index, item in enumerate(stats, start=1)
            ]
        else:
            headers = ["#", "昵称", "用户名", "用户ID", "等级", "头衔", "楼层", "楼中楼", "合计"]
            user_rows = [
                [
                    index,
                    self._display_name(item),
                    display_text(item["username"]),
                    item["uid"],
                    item["level"],
                    display_text(item["badge"]),
                    item["floor"],
                    item["comment"],
                    item["total"],
                ]
                for index, item in enumerate(stats, start=1)
            ]
        self._add_grid_tab(
            self.grid_nb,
            "回复统计",
            headers,
            user_rows,
            urls=[user_url(item) for item in stats],
            default_sort="合计",
            default_reverse=True,
        )

        if all_mode:
            per_rows = []
            per_urls = []
            for thread_index, thread in enumerate(threads, start=1):
                title = display_text(thread.meta.title or thread.meta.tid)
                for item in thread.user_stats(include_op):
                    per_rows.append(
                        [
                            f"{thread_index}. {title}",
                            self._display_name(item),
                            display_text(item["username"]),
                            item["uid"],
                            item["level"],
                            display_text(item["badge"]),
                            item["floor_count"],
                            item["comment_count"],
                            item["total"],
                        ]
                    )
                    per_urls.append(user_url(item))
            self._add_grid_tab(
                self.grid_nb,
                "分帖统计",
                ["帖子", "昵称", "用户名", "用户ID", "等级", "头衔", "楼层", "楼中楼", "合计"],
                per_rows,
                urls=per_urls,
                default_sort="合计",
                default_reverse=True,
            )

        floor_rows = []
        floor_urls = []
        comment_rows = []
        comment_urls = []
        for thread_index, thread in enumerate(threads, start=1):
            title = display_text(thread.meta.title or thread.meta.tid)
            for floor in thread.floors:
                prefix = [f"{thread_index}. {title}"] if all_mode else []
                floor_rows.append(
                    prefix
                    + [
                        floor.post_no,
                        display_text(floor.author),
                        display_text(floor.author_name),
                        floor.author_id,
                        floor.level,
                        display_text(floor.badge),
                        display_text(floor.content),
                    ]
                )
                floor_urls.append(f"https://tieba.baidu.com/p/{thread.meta.tid}?pid={floor.pid}")
            for comment in thread.comments:
                prefix = [f"{thread_index}. {title}"] if all_mode else []
                comment_rows.append(
                    prefix
                    + [
                        comment.floor_no,
                        display_text(comment.author),
                        display_text(comment.author_name),
                        comment.author_id,
                        comment.level,
                        display_text(comment.content),
                    ]
                )
                comment_urls.append(f"https://tieba.baidu.com/p/{thread.meta.tid}?pid={comment.pid}")
        floor_headers = (["帖子"] if all_mode else []) + [
            "楼层",
            "昵称",
            "用户名",
            "用户ID",
            "等级",
            "头衔",
            "内容",
        ]
        comment_headers = (["帖子"] if all_mode else []) + [
            "所在楼层",
            "回复者",
            "用户名",
            "用户ID",
            "等级",
            "内容",
        ]
        self._add_grid_tab(
            self.grid_nb,
            "楼层明细",
            floor_headers,
            floor_rows,
            urls=floor_urls,
            default_sort="楼层",
        )
        self._add_grid_tab(
            self.grid_nb,
            "楼中楼明细",
            comment_headers,
            comment_rows,
            urls=comment_urls,
            default_sort="所在楼层",
        )
        warn_count = sum(len(thread.warnings) for thread in threads)
        if warn_count:
            self.grid_hint.configure(text=f"⚠ 数据可能不完整：{warn_count} 条警告；导出说明里也会记录")
        else:
            self.grid_hint.configure(
                text="表格可排序、双击打开链接、Ctrl+C 复制 · 界面直接显示单色 emoji，导出保留原样"
            )
        self._add_compare_tab()

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
        "类型", "标记", "昵称", "回复者", "用户名", "用户ID", "头衔",
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

    def _filter_loaded_tree(
        self, tree, column: str, title: str, date_column: bool = False, anchor: Optional[tuple] = None
    ) -> None:
        if not tree.get_children():
            return
        chosen: Any
        if date_column:
            current = None
            chosen = self._filter_date_dialog(title, current, anchor)
            if chosen is None:
                return
            start_date, end_date = chosen
            for iid in list(tree.get_children()):
                value = tree.set(iid, column)[:10]
                if (start_date and value < start_date) or (end_date and value > end_date):
                    tree.delete(iid)
            return
        values = sorted({tree.set(iid, column) for iid in tree.get_children()})
        chosen = self._filter_text_dialog(title, values, None, anchor)
        if chosen is None:
            return
        for iid in list(tree.get_children()):
            if tree.set(iid, column) not in chosen:
                tree.delete(iid)

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

    def _add_grid_tab(
        self,
        notebook,
        title: str,
        headers: List[str],
        rows: List[list],
        urls: Optional[List[str]] = None,
        default_sort: Optional[str] = None,
        default_reverse: bool = False,
    ) -> None:
        all_rows = [list(row) for row in rows]
        all_urls = list(urls or [])
        frame = tk.Frame(notebook)
        notebook.add(frame, text=f"  {title}  ")
        columns = [str(index) for index in range(len(headers))]
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        widths = {
            "#": 48,
            "昵称": 170,
            "用户名": 110,
            "用户ID": 110,
            "帖子": 190,
            "等级": 60,
            "头衔": 100,
            "楼层": 60,
            "楼中楼": 70,
            "合计": 60,
            "所在楼层": 78,
            "回复者": 130,
            "内容": 260,
        }
        for index, header in enumerate(headers):
            tree.heading(columns[index], text=header + ("  ▼" if self._header_filterable(header) else ""))
            width = widths.get(header, 90)
            tree.column(
                columns[index],
                width=width,
                minwidth=max(44, width // 2),
                stretch=index == len(headers) - 1,
                anchor="w" if header in ("内容", "昵称", "帖子", "回复者") else "center",
            )
        tree.tag_configure("odd", background=self.palette["table_alt"])
        tree.links = {}  # type: ignore[attr-defined]
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        pager = tk.Frame(frame, bg="#ffffff")
        pager.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        page_label = tk.Label(pager, text="", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9))
        page_label.pack(side="left")
        page_size_var = tk.StringVar(value=str(self.settings.get("page_size", 1000)))
        ttk.Combobox(
            pager,
            values=("100", "500", "1000", "2000"),
            textvariable=page_size_var,
            width=6,
            state="readonly",
        ).pack(side="left", padx=(8, 0))
        state: Dict[str, Any] = {"page": 0, "column": None, "reverse": False}
        filters: Dict[int, Any] = {}
        row_index = {id(row): index for index, row in enumerate(all_rows)}

        def visible_rows():
            if not filters:
                return all_rows
            result = []
            for row in all_rows:
                keep = True
                for index, selected in filters.items():
                    header = headers[index] if index < len(headers) else ""
                    value = "" if index >= len(row) or row[index] is None else str(row[index])
                    if header == "日期":
                        start_date, end_date = selected
                        day = value[:10]
                        if start_date and (not day or day < start_date):
                            keep = False
                            break
                        if end_date and (not day or day > end_date):
                            keep = False
                            break
                    elif selected and value not in selected:
                        keep = False
                        break
                if keep:
                    result.append(row)
            return result

        def page_size() -> int:
            try:
                return max(1, int(page_size_var.get()))
            except ValueError:
                return 1000

        def render() -> None:
            for item in tree.get_children():
                tree.delete(item)
            rows = visible_rows()
            size = page_size()
            pages = max(1, (len(rows) + size - 1) // size)
            state["page"] = min(max(0, state["page"]), pages - 1)
            start_index = state["page"] * size
            for offset, row in enumerate(rows[start_index : start_index + size]):
                values = ["" if value is None else value for value in row]
                tags = ("odd",) if (start_index + offset) % 2 else ()
                iid = tree.insert("", "end", values=values, tags=tags)
                index = row_index.get(id(row), start_index + offset)
                tree.links[iid] = all_urls[index] if index < len(all_urls) else ""  # type: ignore[attr-defined]
            note = f"，筛选后 {len(rows)} 行" if filters else ""
            page_label.configure(text=f"第 {state['page'] + 1}/{pages} 页，共 {len(rows)} 行{note}")
            for button, target in ((first_btn, 0), (prev_btn, state["page"] - 1), (next_btn, state["page"] + 1), (last_btn, pages - 1)):
                button.configure(state="normal" if 0 <= target < pages and target != state["page"] else "disabled")
            if pages <= 1:
                pager.grid_remove()
            else:
                pager.grid()

        def go(page: int) -> None:
            state["page"] = page
            render()

        first_btn = ttk.Button(pager, text="首页", width=5, command=lambda: go(0))
        prev_btn = ttk.Button(pager, text="上一页", width=6, command=lambda: go(state["page"] - 1))
        next_btn = ttk.Button(pager, text="下一页", width=6, command=lambda: go(state["page"] + 1))
        last_btn = ttk.Button(pager, text="末页", width=5, command=lambda: go(10**9))
        for button in (first_btn, prev_btn, next_btn, last_btn):
            button.pack(side="left", padx=(4, 0))
        def on_page_size_changed(*_args) -> None:
            self.settings["page_size"] = page_size()
            save_settings(self.settings)
            go(0)

        page_size_var.trace_add("write", on_page_size_changed)

        def open_row(_event=None) -> None:
            selection = tree.selection()
            if selection:
                url = tree.links.get(selection[0])  # type: ignore[attr-defined]
                if url:
                    webbrowser.open(url)

        def copy_row(_event=None) -> None:
            selection = tree.selection()
            if selection:
                self.root.clipboard_clear()
                self.root.clipboard_append("\t".join(str(v) for v in tree.item(selection[0], "values")))

        tree.bind("<Double-1>", open_row)
        tree.bind("<Control-c>", copy_row)
        menu = tk.Menu(tree, tearoff=0)

        def copy_value(index: int) -> None:
            selection = tree.selection()
            if selection:
                values = tree.item(selection[0], "values")
                if index < len(values):
                    self._copy_text(str(values[index]))

        menu.add_command(label="复制整行", command=copy_row)
        menu.add_command(
            label="复制当前页",
            command=lambda: self._copy_tree_page(tree),
        )
        for title, index in (
            ("复制昵称", next((i for i, h in enumerate(headers) if h in ("昵称", "回复者")), -1)),
            ("复制用户名", next((i for i, h in enumerate(headers) if h == "用户名"), -1)),
            ("复制用户ID", next((i for i, h in enumerate(headers) if h == "用户ID"), -1)),
        ):
            if index >= 0:
                menu.add_command(label=title, command=partial(copy_value, index))
        menu.add_separator()
        menu.add_command(label="打开链接", command=open_row)

        def open_filter(index: int, anchor: Optional[tuple] = None) -> None:
            if index < 0 or index >= len(headers) or not self._header_filterable(headers[index]):
                return
            header = headers[index]
            chosen: Any
            if header == "日期":
                chosen = self._filter_date_dialog(header, filters.get(index), anchor)
            else:
                values = sorted({str(row[index]) if index < len(row) and row[index] is not None else ""
                                 for row in all_rows})
                chosen = self._filter_text_dialog(header, values, filters.get(index), anchor)
            if chosen is None:
                return
            if chosen and any(chosen):
                filters[index] = chosen
            else:
                filters.pop(index, None)
            state["page"] = 0
            render()

        def show_menu(event) -> None:
            if tree.identify_region(event.x, event.y) == "heading":
                column = tree.identify_column(event.x)
                try:
                    index = int(column[1:]) - 1
                except (ValueError, IndexError):
                    return
                open_filter(index, (event.x_root, event.y_root))
                return
            row = tree.identify_row(event.y)
            if row:
                tree.selection_set(row)
                try:
                    menu.tk_popup(event.x_root, event.y_root)
                finally:
                    menu.grab_release()

        tree.bind("<Button-3>", show_menu)

        def apply_sort(column: str, reverse: bool) -> None:
            state["column"] = column
            state["reverse"] = reverse
            index = int(column)

            header = headers[index] if index < len(headers) else ""
            mark_order = {"警告": 3, "可疑": 2, "安全": 1, "": 0, "-": 0}
            def key(row):
                value = row[index] if index < len(row) else ""
                if header == "标记":
                    for key, rank in mark_order.items():
                        if key and key in str(value):
                            return (0, rank)
                    return (0, 0)
                try:
                    return (0, float(value))
                except (TypeError, ValueError):
                    return (1, str(value))

            paired = list(zip(all_rows, all_urls + [""] * max(0, len(all_rows) - len(all_urls))))
            paired.sort(key=lambda item: key(item[0]), reverse=reverse)
            all_rows[:] = [item[0] for item in paired]
            all_urls[:] = [item[1] for item in paired]
            row_index.clear()
            row_index.update({id(row): index for index, row in enumerate(all_rows)})
            state["page"] = 0
            render()
            for position, header in enumerate(headers):
                arrow = ""
                if columns[position] == column:
                    arrow = " ▼" if reverse else " ▲"
                tree.heading(columns[position], text=header + arrow)

        sortable = {"日期", "标记", "等级", "楼层", "楼中楼", "合计", "所在楼层", "#"}

        def sort_by(column: str) -> None:
            index = int(column)
            if index >= len(headers) or headers[index] not in sortable:
                return
            if state["column"] == column:
                apply_sort(column, not bool(state["reverse"]))
            else:
                apply_sort(column, False)

        def make_command(index: int) -> Callable[[], None]:
            column = columns[index]
            header = headers[index]
            if self._header_filterable(header) and header not in ("日期", "标记"):
                return lambda: open_filter(index)
            return lambda: sort_by(column)

        for index, header in enumerate(headers):
            tree.heading(columns[index], command=make_command(index))
        if default_sort in headers:
            apply_sort(columns[headers.index(default_sort)], default_reverse)
        else:
            render()

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

    def _split_export_threads(self, threads, limit: int = 500_000):
        parts = []
        current: list = []
        rows = 0
        for thread in threads:
            size = len(thread.floors) + len(thread.comments)
            if current and rows + size > limit:
                parts.append(current)
                current = []
                rows = 0
            current.append(thread)
            rows += size
        if current:
            parts.append(current)
        return parts

    def _export_now(self) -> None:
        if not self.last_threads:
            self.status_var.set("还没有可导出的数据")
            self._append_log("导出前需要先抓取帖子。", "muted")
            return
        threads = self._selected_grid_threads()
        if len(self.last_threads) > 1 and not self.grid_thread_var.get().startswith("全部"):
            scope = self._ask_choice(
                "导出帖子范围",
                "选择这次导出的帖子范围。",
                [("当前表格", True), ("全部帖子", False), ("取消", None)],
                default=0,
            )
            if scope is None:
                return
            threads = list(self.last_threads) if scope is False else threads
        if self._people_filter_active():
            scope = self._ask_choice(
                "导出用户范围",
                "当前有参与者筛选，选择导出哪些用户。",
                [("当前筛选用户", True), ("全部用户", False), ("取消", None)],
                default=0,
            )
            if scope is None:
                return
            if scope is True:
                filtered_ids = {thread.meta.tid for thread in self._filtered_threads()}
                threads = [thread for thread in threads if thread.meta.tid in filtered_ids]
                if not any(thread.floors or thread.comments for thread in threads):
                    messagebox.showinfo("没有结果", "当前筛选没有可导出的用户。", parent=self.root)
                    return
        if not threads:
            messagebox.showinfo("没有结果", "当前范围没有可导出的帖子。", parent=self.root)
            return
        initial = self.last_output or default_output_path()
        path = filedialog.asksaveasfilename(
            title="导出 Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial),
            parent=self.root,
        )
        if not path:
            return
        visible = self._visible_people()
        scope_user = "当前筛选用户" if self._people_filter_active() else "全部用户"
        warnings = [f"{thread.meta.title or thread.meta.tid}：{len(thread.warnings)} 条"
                    for thread in threads if thread.warnings]
        empty = [thread.meta.title or thread.meta.tid for thread in threads if not (thread.floors or thread.comments)]
        meta = {
            "软件版本": VERSION,
            "帖子范围": "当前表格范围" if len(threads) < len(self.last_threads) else "全部帖子",
            "帖子数": str(len(threads)),
            "用户范围": scope_user,
            "筛选后人数": str(len(visible)),
            "实际导出用户数": str(len(visible) if scope_user == "当前筛选用户" else len(self.people_users)),
            "筛选条件": self._filter_summary(),
            "关注增强": "开" if self.settings.get("follow_enhance") else "关",
            "包含关注": "是" if self.include_follows_var.get() else "否",
            "数据警告": "；".join(warnings) if warnings else "无",
            "空帖子": "；".join(empty) if empty else "无",
        }
        parts = self._split_export_threads(self._expand_large_threads(threads))
        paths = []
        try:
            for index, part in enumerate(parts, start=1):
                if index == 1:
                    part_path = path
                else:
                    root, ext = os.path.splitext(path)
                    part_path = f"{root}_part{index}{ext or '.xlsx'}"
                part_meta = dict(meta)
                part_meta["分片"] = f"{index}/{len(parts)}"
                export_workbook(
                    part_path,
                    part,
                    include_op=getattr(self, "last_include_op", True),
                    meta=part_meta,
                )
                paths.append(part_path)
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("导出失败", friendly_error(error), parent=self.root)
            return
        self.last_output = paths[0]
        self.open_btn.configure(state="normal")
        self._append_log("已导出 Excel：" + "；".join(paths), "ok")
        messagebox.showinfo(
            "导出完成",
            "已保存到：" + chr(10) + chr(10).join(paths) + chr(10) + chr(10) + "现在打开第一个吗？",
            parent=self.root,
        )
        self._open_result()

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
                fetcher = Fetcher(cookie=self._request_cookie(), delay=0.3, verbose=False)
                options = CollectOptions(verbose=True, log=self._log_from_thread)
                for thread in self.last_threads:
                    filled = fill_thread_levels(thread, fetcher, self._log_from_thread)
                    if filled:
                        self._append_log(f"  新版网页接口补全等级：{filled} 处", "muted")
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

    def _request_cookie(self) -> dict:
        if self.mode_var.get() == "guest":
            return {}
        return parse_cookie_input(self._current_cookie_text())

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
        mark_box = getattr(self, "people_mark_box", None)
        if mark_box is not None:
            try:
                mark_box.configure(state=readonly if self._risk_enabled() else "disabled")
            except tk.TclError:
                pass

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
        prefer = "start" if "最早" in self.post_prefer_var.get() else "end"

        include_follows = bool(self.include_follows_var.get() and self.settings.get("follow_enhance"))
        guest = self.mode_var.get() == "guest"
        cookie = {} if guest else parse_cookie_input(self.cookie_var.get())
        concurrency = 1 if include_follows else max(1, min(3, int(self.settings.get("batch_concurrency", 1) or 1)))

        def resolve(user):
            name = str(user.get("name") or "").strip()
            if not (user.get("uid") or user.get("username")) and not name:
                return {"ok": False, "skipped": True, "error": "缺少用户ID"}
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
                if not (uid or username):
                    info = resolve_user(fetcher, name, "昵称") if name else {}
                    if info.get("uid"):
                        uid = info.get("uid") or ""
                        username = info.get("username") or ""
                        user["uid"] = uid
                        user["username"] = username
                        user["portrait"] = info.get("portrait") or user.get("portrait") or ""
                    elif not user.get("portrait"):
                        return {"ok": False, "skipped": True, "error": "昵称无法唯一定位"}
                    # 没有 uid/username 但保留 portrait 时，仍可用 portrait 查发言。
                cached_posts = cached_user_posts(uid, count, start_date, end_date, prefer)
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
                    for index, (user, future) in enumerate(zip(users, futures)):
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

    def _hidden_follows(self, profile) -> bool:
        return bool(profile.get("followed_private")) or profile.get("priv_like") == 3

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

    def _remark_local_marks(self) -> None:
        if getattr(self, "_batch_running", False):
            return
        if not self._risk_enabled():
            return
        users = self._visible_people()
        if not users:
            self.people_hint.configure(text="当前筛选没有用户")
            return
        count = self._post_count()
        start_date, end_date = self._date_params()
        prefer = "start" if "最早" in self.post_prefer_var.get() else "end"
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
    ) -> None:
        key = user["uid"] or f"name:{user['name']}"
        cached = None if (force or force_follow) else getattr(self, "_profile_cache", {}).get(key)
        if cached and (cached.get("follow_loaded") or not force_follow):
            self._render_profile(user, cached)
            return
        self.profile_status.configure(text=f"正在查询 {display_text(user['name'])} …")
        for tree in (self.profile_forum_tree, self.profile_post_tree):
            for item in tree.get_children():
                tree.delete(item)
        count = self._post_count()
        start_date, end_date = self._date_params()
        bar_name = self._user_bar(user)
        prefer = "start" if "最早" in self.post_prefer_var.get() else "end"
        topic_limit = int(topic_max_pages or getattr(self, "_profile_topic_limit", 50) or 50)
        self._profile_topic_limit = topic_limit
        cached_posts = None
        if not force and not force_follow:
            cached_posts = cached_user_posts(user["uid"], count, start_date, end_date, prefer)

        def worker():
            try:
                fetcher = Fetcher(cookie=self._request_cookie(), delay=0.3, verbose=False)
                uid = str(user.get("uid") or "")
                username = str(user.get("username") or "")
                portrait = str(user.get("portrait") or "")
                if not (uid or username) and user.get("name"):
                    info = resolve_user(fetcher, str(user["name"]), "昵称")
                    if info.get("uid"):
                        uid = str(info.get("uid") or "")
                        username = str(info.get("username") or "")
                        portrait = str(info.get("portrait") or portrait)
                        user["uid"] = uid
                        user["username"] = username
                        user["portrait"] = portrait
                    elif not portrait:
                        profile = {"ok": False, "error": "昵称无法唯一定位"}
                        self._post(("profile_ready", key, user, profile))
                        return
                local_cached = cached_posts
                if local_cached is None and uid:
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
                    cached_posts=local_cached,
                )
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
        self._load_profile(user, force=True, topic_max_pages=limit)

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

    def _configure_colors(self, tree) -> None:
        tree.tag_configure("ban", background=self.palette["danger_bg"])
        tree.tag_configure("warn", background=self.palette["warning_bg"])
        tree.tag_configure("safe", background=self.palette["safe_bg"])

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
            item["source"] = "公开" if forums else "隐藏恢复"
            merged[name] = item
        if not forums:
            for forum in profile.get("like_forum") or []:
                name = forum.get("name")
                if name and name not in merged:
                    merged[name] = {"name": name, "level": 0, "level_name": "", "source": "精选"}
        if bar_name and bar_level:
            name = bar_name[:-1] if bar_name.endswith("吧") and len(bar_name) > 2 else bar_name
            level_int = int(bar_level or 0)
            if name and level_int > 0:
                existing = merged.get(name)
                if existing is None:
                    merged[name] = {"name": name, "level": level_int, "level_name": "", "source": "等级"}
                elif not existing.get("level"):
                    existing["level"] = level_int
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
                }
            elif existing.get("source") != "公开":
                if int(forum.get("level") or 0) > int(existing.get("level") or 0):
                    existing["level"] = int(forum.get("level") or 0)
                existing["source"] = "候选确认"
        return sorted(merged.values(), key=lambda item: int(item.get("level") or 0), reverse=True)

    def _forum_note(self, profile, bar_name: str = "", bar_level: str = "") -> str:
        forums = profile.get("followed_forums") or []
        hidden = profile.get("hidden_forums") or []
        if forums:
            return f"共 {len(forums)} 个（完整）"
        if hidden or profile.get("like_forum"):
            count = len(self._merge_forum_lists(profile, bar_name, bar_level))
            note = f"对方隐藏了完整关注列表，已从等级头衔/精选恢复 {count} 个，可能不全"
            probed = len(profile.get("probed_forums") or [])
            if probed:
                note += f"；候选确认 {probed} 个"
            if self._hidden_follows(profile):
                note += "（风险提示：关注列表隐藏，未命中警告时标黄）"
            return note
        if profile.get("followed_private"):
            return "对方设置了隐私，关注列表不可见（风险提示：关注列表隐藏，未命中警告时标黄）"
        return "没有查到关注列表"

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

    def _export_profile_posts(self) -> None:
        user = getattr(self, "_profile_user", None)
        profile = getattr(self, "_profile_data", None)
        if not user or not profile:
            messagebox.showinfo("还没有资料", "先点开一个参与者。", parent=self.root)
            return
        self._export_posts_for(user, profile, *self._date_params())

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

    def _export_posts_for(self, user, profile, start: str, end: str) -> None:
        sources = profile.get("post_sources") or {}
        if sources.get("topic_truncated"):
            if not messagebox.askokcancel(
                "主题覆盖未到开始日期",
                "主题流已达到本次页数上限，导出的主题可能不完整。\n"
                "仍按现有缓存覆盖导出？",
                parent=self.root,
            ):
                return
        uid = str(user.get("uid") or profile.get("user_id") or "")
        cached = post_cache().get_user(uid) if uid else None
        posts = list(profile.get("recent_posts") or [])
        if cached and cached.get("posts"):
            posts = list(cached["posts"])
        cache_start = cache_end = ""
        if cached:
            oldest = int(cached.get("oldest_ts") or 0)
            newest = int(cached.get("newest_ts") or 0)
            if oldest:
                cache_start = datetime.fromtimestamp(oldest).strftime("%Y-%m-%d")
            if newest:
                cache_end = datetime.fromtimestamp(newest).strftime("%Y-%m-%d")
        chosen = self._post_range_dialog(user, start, end, cache_start, cache_end)
        if chosen is None:
            return
        chosen_start, chosen_end = chosen
        filtered = []
        for post in posts:
            day = str(post.get("time") or "")
            if chosen_start and day and day < chosen_start:
                continue
            if chosen_end and day and day > chosen_end:
                continue
            filtered.append(post)
        if not filtered:
            messagebox.showinfo("没有发言", "选定范围内没有缓存发言。", parent=self.root)
            return
        initial = posts_base(user, profile) + ".xlsx"
        path = filedialog.asksaveasfilename(
            title="导出发言",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
            initialfile=initial,
            parent=self.root,
        )
        if not path:
            return
        base = os.path.splitext(path)[0]
        try:
            coverage = {
                "reply": f"{cache_start or '未记录'} ~ {cache_end or '未记录'}",
                "topic": "缓存内已有主题",
            }
            output = export_user_posts(base, user, filtered, chosen_start, chosen_end, coverage)
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("导出失败", friendly_error(error), parent=self.root)
            return
        self._append_log(f"发言已导出：{output}", "ok")
        messagebox.showinfo("导出完成", "已生成：" + chr(10) + output, parent=self.root)

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

    def _render_profile(self, user, profile) -> None:
        forum_tree = self.profile_forum_tree
        post_tree = self.profile_post_tree
        for tree in (forum_tree, post_tree):
            for item in tree.get_children():
                tree.delete(item)
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
        if level and not user.get("level"):
            user["level"] = level
            iid = user.get("_iid")
            if iid is not None:
                try:
                    values = list(self.people_tree.item(iid, "values"))
                    values[4] = f"Lv.{level}"
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
            self.profile_topic_btn.configure(
                text=f"继续抓主题（已 {sources.get('topic_pages') or 50} 页）"
            )
            self.profile_topic_btn.pack(side="right", padx=(0, 4))
        else:
            self.profile_topic_btn.pack_forget()
        if profile.get("follow_loaded") is False:
            self.profile_follow_btn.pack(side="left", padx=(0, 6))
        else:
            self.profile_follow_btn.pack_forget()
        if self._hidden_follows(profile):
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
                    forum.get("source") or "",
                ),
                tags=self._row_tags(forum["name"], "forum"),
            )
            self._profile_forum_names[iid] = forum["name"]

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
                ),
                tags=self._row_tags(post.get("bar"), "posts"),
            )
            self._profile_post_urls[iid] = post.get("url") or ""
        forum_note = self._forum_note(profile, self._user_bar(user), level or "")
        if profile.get("follow_loaded") is False:
            forum_note += "（未加载公开关注）"
        elif self.mode_var.get() == "guest":
            forum_note += "（匿名尝试：公开关注可能失败/不完整）"
        self.profile_forum_note.configure(text=forum_note)

        # 本地标记：默认关闭；免登录只看本帖发言，登录才看关注列表
        if not self._risk_enabled():
            hit_level, hit_bar = "", ""
            hidden_follows = False
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
        risk = " · 关注列表隐藏，未命中警告时标黄" if hidden_follows else ""
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
                if hit_level:
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
            f"{display_text(user['name'])} | {user['username'] or '-'} | ID {user['uid'] or '-'} | "
            f"Lv.{level or '-'} | 发言 {len(posts)} | 关注 {len(combined)}"
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
            status += " · ⚠ 关注列表隐藏，未命中警告时标黄"
        note = self._post_source_note(profile)
        if note:
            status += " · " + note
        self.profile_status.configure(text=status)

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
        except OSError:
            pass

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
        try:
            self._refresh_people()
            self._refresh_grid()
        except Exception:  # noqa: BLE001
            pass
        self.status_var.set(f"已恢复 {len(threads)} 个帖子（{len(self._aggregate_users())} 位用户）")

    def _start_from_key(self, _event=None):
        self._on_start()
        return "break"

    def _on_start(self) -> None:
        if self.running:
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
        if removed and self.settings.get("removed_thread_action") == "remove":
            self.last_threads = [thread for thread in self.last_threads if thread.meta.tid not in removed]
            existing = {thread.meta.tid for thread in self.last_threads}
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
        cookie_text = "" if mode == "guest" else self._current_cookie_text()
        cookie = parse_cookie_input(cookie_text)
        if mode == "login" and not cookie.get("BDUSS"):
            messagebox.showwarning(
                "需要 BDUSS",
                "登录模式至少需要 BDUSS。请选择「仅 BDUSS」填写，或切换到「完整 Cookie」。",
                parent=self.root,
            )
            if self.login_method_var.get() == "bduss":
                self.bduss_entry.focus_set()
            else:
                self.cookie_entry.focus_set()
            return
        if mode == "guest":
            self._append_log("本次使用免登录模式：公开帖子，楼中楼按设置补全", "muted")
        elif self._remember_current_login():
            if save_cookie(cookie_text):
                self._append_log("已记住登录信息（本机加密保存），下次会自动填入。", "muted")
            else:
                self._append_log("登录信息保存失败，本次仍可正常使用。", "muted")

        options = CollectOptions(
            mode=mode,
            include_comments=self.comments_var.get(),
            comment_depth=self._comment_depth_value(),
            comment_concurrency=max(1, min(3, int(self.comment_concurrency_var.get() or 1))),
            enrich_levels=True,
            pb_levels=True,
            verbose=True,
            log=self._log_from_thread,
            should_stop=self.stop_event.is_set,
        )
        include_op = not self.exclude_op_var.get()
        self.last_include_op = include_op

        self.stop_event.clear()
        self._write_log("fetch_start", threads=len(urls))
        self._set_running(True)
        self._append_log(f"\n开始统计 {len(urls)} 个帖子，请耐心等待…", "title")
        self.worker = threading.Thread(
            target=self._run_worker,
            args=(urls, output, options, cookie, delay, include_op, export),
            daemon=True,
        )
        self.worker.start()

    def _on_stop(self) -> None:
        if not self.running:
            return
        self.stop_event.set()
        self.stop_btn.configure(state="disabled")
        self.status_var.set("正在停止…")

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
        active = self.running or getattr(self, "_batch_running", False)
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
        self._batch_cancel = True
        self.status_var.set("正在停止…")
        self._append_log("正在停止任务并保存已完成部分…", "muted")
        self.root.after(100, self._wait_close)

    def _wait_close(self) -> None:
        worker_alive = bool(self.worker and self.worker.is_alive())
        batch_alive = bool(getattr(self, "_batch_running", False))
        if worker_alive or batch_alive:
            self.root.after(100, self._wait_close)
            return
        self._persist_result(self.last_threads)
        self.root.destroy()

    # ------------------------------------------------------------- worker
    def _run_worker(self, urls, output, options, cookie, delay, include_op, export=True) -> None:
        completed = []
        try:
            fetcher = Fetcher(cookie=cookie, delay=delay, verbose=False)
            for index, url in enumerate(urls, start=1):
                self._post(("log", f"\n[{index}/{len(urls)}] {url}", "title"))
                try:
                    thread = collect_thread(url, fetcher, options)
                except CaptchaError:
                    raise
                except CollectCancelled:
                    raise
                except (ThreadGoneError, FetchError, CollectError, ValueError) as error:
                    self._post(("log", f"  ✗ 抓取失败：{error}", "err"))
                    continue
                completed.append(thread)
                self._write_log(
                    "thread_done",
                    tid=thread.meta.tid,
                    floors=len(thread.floors),
                    comments=len(thread.comments),
                )
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

            if not completed:
                self._post(
                    ("error", "没有抓到任何帖子。\n\n可能原因：帖子被删、链接不对，或者被安全验证拦截。")
                )
                return

            if export:
                export_workbook(output, completed, include_op=include_op)
                self._post(("done", output, len(completed), list(completed)))
            else:
                self._post(("done", None, len(completed), list(completed)))
        except CaptchaError as error:
            self._post(("captcha", str(error)))
        except CollectCancelled:
            if completed:
                if export:
                    export_workbook(output, completed, include_op=include_op)
                self._post(("cancelled_partial", output if export else None, len(completed), list(completed)))
            else:
                self._post(("cancelled",))
        except Exception as error:  # noqa: BLE001 - 界面上要给出可读信息
            self._write_log("error", error=type(error).__name__)
            self._post(("log", traceback.format_exc(), "muted"))
            self._post(("error", friendly_error(error)))

    def _post(self, message: tuple) -> None:
        self.log_queue.put(message)

    def _log_from_thread(self, message: str) -> None:
        self._post(("log", message, None))

    def _poll_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                self._handle_message(message)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _handle_message(self, message: tuple) -> None:
        kind = message[0]
        if kind == "log":
            _, text, tag = message
            self._append_log(text, tag)
        elif kind == "done":
            _, output, count, threads = message
            self.last_output = output
            self.last_threads = self._merge_threads(threads or [])
            self._persist_result(self.last_threads)
            self._auto_filled = False
            self._set_running(False)
            self.status_var.set(f"完成 · {len(self.last_threads)} 个帖子 / {len(self._aggregate_users())} 位用户")
            try:
                self._reset_people_filters()
                self._refresh_people()
                self._refresh_grid()
            except Exception:  # noqa: BLE001
                pass
            if output:
                self.open_btn.configure(state="normal")
                self._append_log(f"\n完成！共 {count} 个帖子，文件已保存：\n{output}", "ok")
                messagebox.showinfo(
                    "完成",
                    f"统计完成，共 {count} 个帖子。\n\n文件已保存到：\n{output}\n\n"
                    "切到「参与者」选项卡可以点开每个人，查看他的发言和关注的贴吧。",
                    parent=self.root,
                )
                self._open_result()
            else:
                self.open_btn.configure(state="disabled")
                self._append_log(f"\n完成！共 {count} 个帖子（按设置未导出 Excel）。", "ok")
                messagebox.showinfo(
                    "完成",
                    f"统计完成，共 {count} 个帖子。\n\n按设置没有导出 Excel，可以切到「参与者」看结果，"
                    "或点「导出 Excel」现在生成。",
                    parent=self.root,
                )
        elif kind == "cancelled_partial":
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
        elif kind == "probe_done":
            _, profile, results, button = message
            self._probe_running = False
            button.configure(state="normal", text="探测候选关注")
            profile["probed_forums"] = results
            self._append_log(f"候选探测完成：确认 {len(results)} 个关注。", "ok")
            if profile is getattr(self, "_last_lookup_profile", None):
                self._render_lookup(profile)
            elif profile is getattr(self, "_profile_data", None):
                self._render_profile(self._profile_user, profile)
        elif kind == "batch_profile":
            _, index, user, profile = message
            self._batch_done = max(getattr(self, "_batch_done", 0), index + 1)
            key = user.get("uid") or f"name:{user['name']}"
            if profile and profile.get("ok"):
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
        elif kind == "batch_done":
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
        elif kind == "profile_ready":
            _, key, user, profile = message
            self._profile_cache[key] = profile
            selection = self.people_tree.selection()
            if selection:
                try:
                    current = self.people_users[int(selection[0])]
                except (IndexError, ValueError):
                    current = None
                if current and (current["uid"] or f"name:{current['name']}") == key:
                    self._render_profile(user, profile)
        elif kind == "enrich_done":
            self._enriching = False
            self._refresh_people()
            self.people_hint.configure(text="等级已补全，Excel 已更新")
            self._append_log("等级补全完成，Excel 已重新导出。", "ok")
        elif kind == "enrich_error":
            self._enriching = False
            self.people_hint.configure(text="补全失败")
            self._append_log(f"补全等级失败：{message[1]}", "err")
        elif kind == "levels_filled":
            self._auto_filling = False
            self._refresh_people()
            with_level = sum(1 for user in self.people_users if user.get("level"))
            self.people_hint.configure(text=f"共 {len(self.people_users)} 人 · 有等级 {with_level}")
        elif kind == "levels_error":
            self._auto_filling = False
            self.people_hint.configure(text="等级补全失败，可点「刷新」重试")
        elif kind == "lookup_ready":
            _, profile, error = message
            if error:
                self._set_lookup_text("查询失败：" + friendly_error(error))
                self.lookup_status.configure(text="查询失败")
            else:
                self._render_lookup(profile)
        elif kind == "cancelled":
            self._set_running(False)
            self.status_var.set("已停止")
            self._append_log("\n已停止，没有生成文件。", "err")
        elif kind == "captcha":
            _, detail = message
            self._set_running(False)
            self.status_var.set("被安全验证拦截")
            self._append_log("抓取失败：" + detail, "err")
            if self.login_method_var.get() == "bduss":
                self.login_method_var.set("cookie")
                self._on_login_method_changed()
                self.cookie_entry.focus_set()
                self._append_log(
                    "仅 BDUSS 未能通过验证，已切换到完整 Cookie。请从浏览器复制完整 Cookie 后重试。",
                    "err",
                )
                messagebox.showwarning(
                    "需要完整 Cookie",
                    "贴吧要求安全验证，仅 BDUSS 无法通过。已切换到「完整 Cookie」。"
                    "请点「如何获取？」，在浏览器完成验证并复制完整 Cookie，粘贴后再点「开始统计」。",
                    parent=self.root,
                )
            else:
                self._append_log(
                    "完整 Cookie 仍被拦截：请在浏览器完成验证，更新完整 Cookie 后重试。",
                    "err",
                )
                self.cookie_entry.focus_set()
                messagebox.showwarning(
                    "被安全验证拦截",
                    "贴吧要求安全验证，当前完整 Cookie 也未能通过。"
                    "请在浏览器完成验证，重新复制完整 Cookie 后再试。",
                    parent=self.root,
                )
        elif kind == "error":
            _, detail = message
            self._set_running(False)
            self.status_var.set("出错了")
            self._append_log(f"\n✗ {detail}", "err")
            messagebox.showerror("出错了", detail.split("\n\n")[0], parent=self.root)

    def _set_running(self, running: bool) -> None:
        self.running = running
        if running:
            self.start_btn.configure(state="disabled", bg="#9aa7b8")
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
            self.stop_btn.configure(state="disabled")
            try:
                self.progress.stop()
            except tk.TclError:
                pass
            self.progress.pack_forget()

    def _append_log(self, text: str, tag: str | None = None) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag or ())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


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
