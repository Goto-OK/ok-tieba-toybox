#!/usr/bin/env python3
"""贴吧楼层回复统计 —— 图形界面（给不想用命令行的用户）。

直接运行：python tieba_gui.py
打包后双击 exe 即可。
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from tieba_reply_stats.blacklist import (
    classify,
    load_blacklist,
    marker,
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
from tieba_reply_stats.cookie_store import clear_cookie, load_cookie, save_cookie
from tieba_reply_stats.export import export_workbook
from tieba_reply_stats.fetch import CaptchaError, Fetcher, FetchError, ThreadGoneError, parse_cookie_input
from tieba_reply_stats.pbapi import fill_thread_levels
from tieba_reply_stats.profile import fetch_user_profile, resolve_user
from tieba_reply_stats.settings import load_settings, save_settings
from tieba_reply_stats.version import __version__ as VERSION

APP_TITLE = "贴吧楼层回复统计"

_EMOJI_CODE_RE = re.compile(r"\[U\+([0-9A-Fa-f]{4,6})\]")


def _is_emoji_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0x2B00 <= code <= 0x2BFF
        or 0xFE00 <= code <= 0xFE0F
        or code == 0x200D
    )


def encode_display(value) -> str:
    """把 emoji 换成 [U+XXXX] 代码，Tk 8.6 才能正常显示。"""
    out = []
    for ch in str(value or ""):
        out.append(f"[U+{ord(ch):04X}]" if _is_emoji_char(ch) else ch)
    return "".join(out)


def decode_display(value) -> str:
    """把 [U+XXXX] 还原成 emoji，用于回查。"""
    return _EMOJI_CODE_RE.sub(lambda match: chr(int(match.group(1), 16)), str(value or ""))


COOKIE_HELP = """需要 Cookie 时，这样复制：

1. 用 Chrome 或 Edge 打开目标帖子，确认能正常看到楼层。
2. 按键盘上的 F12，打开开发者工具。
3. 点顶部的「网络 / Network」标签，然后按 F5 刷新页面。
4. 在左侧列表里点第一个以帖子数字开头的请求（类型是 document）。
5. 在右侧找到「标头 / Headers」→「请求标头 / Request Headers」，
   里面有一行 Cookie:，把它冒号后面的整段内容复制下来。
6. 粘贴到本窗口的「Cookie」输入框（也可以复制后点「从剪贴板粘贴」），
   然后点「开始统计」。
7. 保持「记住 Cookie」勾选，下次打开程序会自动填入，不用再复制。

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


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.running = False
        self.last_output: str | None = None
        self.last_threads: list = []
        self._auto_filled = False
        self.blacklist = load_blacklist()
        self.settings = load_settings()
        self.mode_chosen = bool(self.settings.get("mode_chosen", False))
        self.mode_var = tk.StringVar(value=str(self.settings.get("mode", "guest")))

        self._build_ui()
        self._set_output(default_output_path())
        self.root.after(120, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        saved = load_cookie()
        if saved:
            self.cookie_var.set(saved)
            self._append_log("已自动填入上次保存的 Cookie（如果失效，请重新粘贴一次）。", "muted")
        self._apply_mode_ui()
        self._apply_risk_ui()
        self.root.after(250, self._maybe_choose_mode)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} v{VERSION}")
        self.root.geometry("880x780")
        self.root.minsize(840, 720)
        self.root.configure(bg="#eef1f5")

        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Card.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))

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
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=200)
        self.progress.pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        self.tab_posts = tk.Frame(self.notebook, bg="#eef1f5")
        self.tab_lookup = tk.Frame(self.notebook, bg="#eef1f5")
        self.tab_settings = tk.Frame(self.notebook, bg="#eef1f5")
        self.notebook.add(self.tab_posts, text="  帖子统计  ")
        self.notebook.add(self.tab_lookup, text="  查成分  ")
        self.notebook.add(self.tab_settings, text="  设置  ")

        self.post_nb = ttk.Notebook(self.tab_posts)
        self.post_nb.pack(fill="both", expand=True, padx=4, pady=4)
        self.tab_fetch = tk.Frame(self.post_nb, bg="#eef1f5")
        self.tab_grid = tk.Frame(self.post_nb, bg="#eef1f5")
        self.tab_people = tk.Frame(self.post_nb, bg="#eef1f5")
        self.post_nb.add(self.tab_fetch, text="  抓取  ")
        self.post_nb.add(self.tab_grid, text="  表格查看  ")
        self.post_nb.add(self.tab_people, text="  参与者  ")

        self._build_mode_bar(self.tab_fetch)

        body = tk.Frame(self.tab_fetch, bg="#eef1f5", padx=16, pady=12)
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
        tk.Label(
            box,
            text="每行一个链接，也可以直接粘贴帖子 ID（如 1234567890）",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        # 2. 选项
        options = ttk.LabelFrame(body, text=" 选项 ", style="Card.TLabelframe")
        options.grid(row=1, column=0, sticky="new", pady=(10, 0))
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

        # 3. 保存位置
        out_box = ttk.LabelFrame(body, text=" 保存到 ", style="Card.TLabelframe")
        out_box.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        out_box.columnconfigure(0, weight=1)
        self.output_var = tk.StringVar()
        ttk.Entry(out_box, textvariable=self.output_var, font=text_font).grid(row=0, column=0, sticky="ew")
        ttk.Button(out_box, text="浏览…", command=self._choose_output, width=8).grid(
            row=0, column=1, padx=(8, 0)
        )

        # 4. Cookie
        cookie_box = ttk.LabelFrame(
            body, text=" Cookie（被安全验证拦截时填写，粘贴一次后会自动记住） ", style="Card.TLabelframe"
        )
        cookie_box.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        cookie_box.columnconfigure(0, weight=1)
        self.cookie_var = tk.StringVar()
        self.cookie_entry = ttk.Entry(cookie_box, textvariable=self.cookie_var, show="•", font=text_font)
        self.cookie_entry.grid(row=0, column=0, sticky="ew")
        self.cookie_paste_btn = ttk.Button(
            cookie_box, text="从剪贴板粘贴", command=self._paste_cookie, width=14
        )
        self.cookie_paste_btn.grid(row=0, column=1, padx=(8, 0))
        self.cookie_help_btn = ttk.Button(
            cookie_box, text="如何获取？", command=self._show_cookie_help, width=10
        )
        self.cookie_help_btn.grid(row=0, column=2, padx=(6, 0))
        self.cookie_clear_btn = ttk.Button(cookie_box, text="清除", command=self._clear_cookie, width=7)
        self.cookie_clear_btn.grid(row=0, column=3, padx=(6, 0))
        self.remember_var = tk.BooleanVar(value=True)
        self.remember_check = ttk.Checkbutton(
            cookie_box,
            text="记住 Cookie（用 Windows 账户加密保存在本机，只自己能用；下次自动填入）",
            variable=self.remember_var,
        )
        self.remember_check.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.cookie_controls = [
            self.cookie_entry,
            self.cookie_paste_btn,
            self.cookie_help_btn,
            self.cookie_clear_btn,
            self.remember_check,
        ]

        # 5. 按钮
        buttons = tk.Frame(body, bg="#eef1f5")
        buttons.grid(row=4, column=0, sticky="ew", pady=(12, 8))
        self.start_btn = tk.Button(
            buttons,
            text="开始统计",
            command=self._on_start,
            bg="#1F4E79",
            fg="white",
            activebackground="#2E75B6",
            activeforeground="white",
            relief="flat",
            padx=22,
            pady=8,
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
            pady=8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 10),
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

    def _clear_cookie(self) -> None:
        self.cookie_var.set("")
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

    def _show_cookie_help(self) -> None:
        messagebox.showinfo("如何获取 Cookie", COOKIE_HELP, parent=self.root)
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
        if self.last_output and os.path.isfile(self.last_output):
            try:
                os.startfile(self.last_output)  # type: ignore[attr-defined]
            except OSError as error:
                messagebox.showerror(
                    "打不开文件", f"{error}\n\n文件位置：{self.last_output}", parent=self.root
                )

    # ------------------------------------------------------- 参与者与成分
    def _aggregate_users(self):
        buckets = {}
        for thread in self.last_threads:
            for item in thread.user_stats():
                key = item["uid"] or f"name:{item['name']}"
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
                    },
                )
                bucket["floor"] += item["floor_count"]
                bucket["comment"] += item["comment_count"]
                bucket["total"] += item["total"]
                if not bucket["username"] and item["username"]:
                    bucket["username"] = item["username"]
                if not bucket["portrait"] and item["portrait"]:
                    bucket["portrait"] = item["portrait"]
                if not bucket["level"] and item["level"]:
                    bucket["level"] = item["level"]
                if not bucket["badge"] and item["badge"]:
                    bucket["badge"] = item["badge"]
        users = list(buckets.values())
        users.sort(key=lambda item: (-item["total"], -item["floor"], item["name"]))
        return users

    def _build_people_tab(self) -> None:
        self._profile_cache: Dict[str, Dict[str, Any]] = {}
        self.people_users: List[Dict[str, Any]] = []
        bar = tk.Frame(self.tab_people, bg="#ffffff", padx=12, pady=8)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="点一行查看这个人的最近发言和关注的贴吧",
            bg="#ffffff",
            fg="#6b7280",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Label(bar, text="   条数：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.post_count_var = tk.StringVar(value="50")
        ttk.Spinbox(bar, from_=5, to=1000, increment=10, width=6, textvariable=self.post_count_var).pack(
            side="left"
        )
        self.post_date_mode_var = tk.StringVar(value="近期")
        ttk.Combobox(
            bar, values=("近期", "指定日期"), textvariable=self.post_date_mode_var, width=9, state="readonly"
        ).pack(side="left", padx=(6, 0))
        self.post_start_var = tk.StringVar()
        self.post_end_var = tk.StringVar()
        self.post_date_row = tk.Frame(self.tab_people, bg="#ffffff", padx=12, pady=4)
        self.post_start_parts = self._date_group(self.post_date_row, "开始", 3)
        self.post_end_parts = self._date_group(self.post_date_row, "结束")
        tk.Label(
            self.post_date_row, text="  贴近：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)
        ).pack(side="left")
        self.post_prefer_var = tk.StringVar(value="贴近结束日期")
        ttk.Combobox(
            self.post_date_row,
            values=("贴近结束日期", "贴近开始日期"),
            textvariable=self.post_prefer_var,
            width=12,
            state="readonly",
        ).pack(side="left")
        for _var in (*self.post_start_parts, *self.post_end_parts):
            _var.trace_add("write", lambda *_: self._on_post_parts_changed())
        self.post_date_mode_var.trace_add("write", lambda *_: self._on_post_date_changed())
        self.post_start_var.set(self._group_date(self.post_start_parts))
        self.post_end_var.set(self._group_date(self.post_end_parts))
        self.batch_btn = ttk.Button(bar, text="一键红绿灯", command=self._batch_refresh_marks, width=10)
        self.batch_btn.pack(side="left", padx=(8, 0))
        self._batch_running = False
        self._batch_cancel = False
        ttk.Button(bar, text="刷新", command=self._refresh_people, width=6).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="在浏览器打开主页", command=self._open_current_profile, width=16).pack(
            side="left", padx=(8, 0)
        )
        self.people_hint = tk.Label(bar, text="", bg="#ffffff", fg="#8a94a6", font=("Microsoft YaHei UI", 9))
        self.people_hint.pack(side="right")

        paned = ttk.PanedWindow(self.tab_people, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.people_paned = paned
        left = tk.Frame(paned)
        right = tk.Frame(paned)
        paned.add(left, weight=2)
        paned.add(right, weight=3)

        columns = ("mark", "name", "username", "uid", "level", "floor", "comment", "total")
        self.people_columns = columns
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
            "mark": 70,
            "name": 120,
            "username": 100,
            "uid": 110,
            "level": 55,
            "floor": 48,
            "comment": 58,
            "total": 48,
        }
        self.people_tree = ttk.Treeview(left, columns=columns, show="headings")
        for col in columns:
            self.people_tree.heading(col, text=headings[col])
            self.people_tree.column(col, width=widths[col], anchor="center" if col != "name" else "w")
        self.people_tree.tag_configure("ban", background="#ffdede")
        self.people_tree.tag_configure("warn", background="#fff4cc")
        self.people_tree.tag_configure("safe", background="#e3f6e3")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.people_tree.yview)
        self.people_tree.configure(yscrollcommand=scroll.set)
        self.people_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.people_tree.bind("<<TreeviewSelect>>", self._on_person_select)
        self.people_tree.bind("<Control-c>", lambda _event: self._copy_person_row())
        self.people_tree.bind("<Button-3>", self._person_menu)
        self._person_popup = tk.Menu(self.people_tree, tearoff=0)
        self._person_popup.add_command(label="复制整行", command=self._copy_person_row)
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

        self.profile_status = tk.Label(
            right,
            text="选择左边一个人查看详情",
            anchor="w",
            bg="#fbfcfe",
            fg="#6b7280",
            font=("Microsoft YaHei UI", 9),
        )
        self.profile_status.pack(fill="x", padx=6, pady=(4, 4))

        body_paned = ttk.PanedWindow(right, orient="horizontal")
        body_paned.pack(fill="both", expand=True, padx=6)
        forum_frame = tk.Frame(body_paned)
        post_frame = tk.Frame(body_paned)
        body_paned.add(forum_frame, weight=1)
        body_paned.add(post_frame, weight=2)

        tk.Label(
            forum_frame,
            text="关注的贴吧（双击打开）",
            bg="#fbfcfe",
            fg="#475569",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        self.profile_forum_tree = ttk.Treeview(
            forum_frame, columns=("bar", "level"), show="headings", height=12
        )
        self.profile_forum_tree.heading("bar", text="贴吧")
        self.profile_forum_tree.heading("level", text="等级")
        self.profile_forum_tree.column("bar", width=130, anchor="w")
        self.profile_forum_tree.column("level", width=50, anchor="center")
        self.profile_forum_tree.pack(fill="both", expand=True)
        self.profile_forum_tree.bind("<Double-1>", lambda _event: self._open_profile_forum())
        self._configure_colors(self.profile_forum_tree)
        self._make_sortable(self.profile_forum_tree, {"bar": "贴吧", "level": "等级"})
        self.profile_forum_note = tk.Label(
            forum_frame,
            text="",
            bg="#fbfcfe",
            fg="#b45309",
            wraplength=260,
            justify="left",
            font=("Microsoft YaHei UI", 8),
        )
        self.profile_forum_note.pack(fill="x", pady=(2, 0))
        self._profile_forum_names: Dict[str, str] = {}

        tk.Label(
            post_frame,
            text="最近发言（双击打开帖子）",
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
        self.post_start_var.set(self._group_date(self.post_start_parts))
        self.post_end_var.set(self._group_date(self.post_end_parts))
        if self.post_date_mode_var.get() == "指定日期":
            self._on_post_date_changed()

    def _on_post_date_changed(self) -> None:
        self._toggle_date_entries()
        user = self._selected_person() if hasattr(self, "people_tree") else None
        if user and self.last_threads:
            self._load_profile(user, force=True)

    def _on_lookup_parts_changed(self, *_args) -> None:
        self.lookup_start_var.set(self._group_date(self.lookup_start_parts))
        self.lookup_end_var.set(self._group_date(self.lookup_end_parts))
        if self.lookup_date_mode_var.get() == "指定日期":
            self._on_lookup_date_changed()

    def _on_lookup_date_changed(self) -> None:
        self._toggle_lookup_dates()
        if self.lookup_query_var.get().strip():
            self._on_lookup()

    def _toggle_lookup_dates(self) -> None:
        enabled = self.lookup_date_mode_var.get() == "指定日期"
        try:
            if enabled:
                if not self.lookup_date_row.winfo_ismapped():
                    self.lookup_date_row.pack(fill="x", before=self.lookup_paned)
            else:
                self.lookup_date_row.pack_forget()
        except tk.TclError:
            pass

    def _make_sortable(self, tree, headers) -> None:
        """点表头在升序/降序之间切换。"""
        state: Dict[str, Any] = {"column": None, "reverse": False}

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
            tree.heading(col, text=title, command=lambda c=col: sort_by(c))

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
        row = self.people_tree.identify_row(event.y)
        if row:
            self.people_tree.selection_set(row)
            try:
                self._person_popup.tk_popup(event.x_root, event.y_root)
            finally:
                self._person_popup.grab_release()

    def _auto_fill_levels(self) -> None:
        """切到参与者时，如果还有缺等级的，自动在后台补一次（不用手动点）。"""
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

    def _build_lookup_tab(self) -> None:
        bar = tk.Frame(self.tab_lookup, bg="#ffffff", padx=12, pady=8)
        bar.pack(fill="x")
        tk.Label(bar, text="查询方式：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.lookup_mode_var = tk.StringVar(value="用户名")
        ttk.Combobox(
            bar,
            values=("用户名", "用户ID", "昵称"),
            textvariable=self.lookup_mode_var,
            width=8,
            state="readonly",
        ).pack(side="left")
        tk.Label(bar, text="  内容：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.lookup_query_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.lookup_query_var, width=24, font=("Microsoft YaHei UI", 10))
        entry.pack(side="left", padx=(4, 0))
        entry.bind("<Return>", lambda _event: self._on_lookup())
        tk.Label(bar, text="  条数：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.lookup_count_var = tk.StringVar(value="50")
        ttk.Spinbox(bar, from_=5, to=1000, increment=10, width=6, textvariable=self.lookup_count_var).pack(
            side="left"
        )
        self.lookup_date_mode_var = tk.StringVar(value="近期")
        ttk.Combobox(
            bar,
            values=("近期", "指定日期"),
            textvariable=self.lookup_date_mode_var,
            width=9,
            state="readonly",
        ).pack(side="left", padx=(6, 0))
        self.lookup_start_var = tk.StringVar()
        self.lookup_end_var = tk.StringVar()
        self.lookup_date_row = tk.Frame(self.tab_lookup, bg="#ffffff", padx=12, pady=4)
        self.lookup_start_parts = self._date_group(self.lookup_date_row, "开始", 3)
        self.lookup_end_parts = self._date_group(self.lookup_date_row, "结束")
        tk.Label(
            self.lookup_date_row, text="  贴近：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)
        ).pack(side="left")
        self.lookup_prefer_var = tk.StringVar(value="贴近结束日期")
        ttk.Combobox(
            self.lookup_date_row,
            values=("贴近结束日期", "贴近开始日期"),
            textvariable=self.lookup_prefer_var,
            width=12,
            state="readonly",
        ).pack(side="left")
        for _var in (*self.lookup_start_parts, *self.lookup_end_parts):
            _var.trace_add("write", lambda *_: self._on_lookup_parts_changed())
        self.lookup_start_var.set(self._group_date(self.lookup_start_parts))
        self.lookup_end_var.set(self._group_date(self.lookup_end_parts))
        self.lookup_date_mode_var.trace_add("write", lambda *_: self._on_lookup_date_changed())
        ttk.Button(bar, text="查询", command=self._on_lookup, width=8).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="复制全部", command=self._copy_lookup, width=8).pack(side="left", padx=(6, 0))
        self.lookup_status = tk.Label(
            bar, text="", bg="#ffffff", fg="#8a94a6", font=("Microsoft YaHei UI", 9)
        )
        self.lookup_status.pack(side="right")

        self.lookup_traffic_labels = {}
        for key, color in (("ban", "#dc2626"), ("warn", "#f59e0b"), ("safe", "#16a34a")):
            label = tk.Label(bar, text="●", fg="#d1d5db", bg="#ffffff", font=("Microsoft YaHei UI", 14))
            label.pack(side="right", padx=(0, 2))
            self.lookup_traffic_labels[key] = (label, color)
        self.lookup_traffic_text = tk.Label(
            bar, text="", bg="#ffffff", fg="#6b7280", font=("Microsoft YaHei UI", 9)
        )
        self.lookup_traffic_text.pack(side="right", padx=(0, 8))

        self.lookup_info = tk.Label(
            self.tab_lookup, text="", anchor="w", bg="#eef1f5", fg="#334155", font=("Microsoft YaHei UI", 10)
        )
        self.lookup_info.pack(fill="x", padx=12, pady=(0, 4))

        paned = ttk.PanedWindow(self.tab_lookup, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.lookup_paned = paned
        left = tk.Frame(paned)
        right = tk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=2)
        tk.Label(
            left,
            text="关注的贴吧（双击打开贴吧）",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        self.lookup_forum_tree = ttk.Treeview(left, columns=("bar", "level"), show="headings", height=14)
        self.lookup_forum_tree.heading("bar", text="贴吧")
        self.lookup_forum_tree.heading("level", text="等级")
        self.lookup_forum_tree.column("bar", width=150, anchor="w")
        self.lookup_forum_tree.column("level", width=55, anchor="center")
        self.lookup_forum_tree.pack(fill="both", expand=True)
        self.lookup_forum_tree.bind("<Double-1>", lambda _event: self._open_lookup_forum())
        self._configure_colors(self.lookup_forum_tree)
        self._make_sortable(self.lookup_forum_tree, {"bar": "贴吧", "level": "等级"})
        self.lookup_forum_note = tk.Label(
            left,
            text="",
            bg="#eef1f5",
            fg="#b45309",
            wraplength=280,
            justify="left",
            font=("Microsoft YaHei UI", 8),
        )
        self.lookup_forum_note.pack(fill="x", pady=(2, 0))
        self._lookup_forum_names: Dict[str, str] = {}

        tk.Label(
            right,
            text="最近发言（双击打开帖子）",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        self.lookup_post_tree = ttk.Treeview(
            right, columns=("time", "type", "bar", "title", "content"), show="headings", height=14
        )
        self.lookup_post_tree.heading("time", text="日期")
        self.lookup_post_tree.heading("type", text="类型")
        self.lookup_post_tree.heading("bar", text="贴吧")
        self.lookup_post_tree.heading("title", text="标题")
        self.lookup_post_tree.heading("content", text="内容")
        self.lookup_post_tree.column("time", width=80, anchor="center")
        self.lookup_post_tree.column("type", width=55, anchor="center")
        self.lookup_post_tree.column("bar", width=110, anchor="w")
        self.lookup_post_tree.column("title", width=220, anchor="w")
        self.lookup_post_tree.column("content", width=260, anchor="w")
        self.lookup_post_tree.pack(fill="both", expand=True)
        self.lookup_post_tree.bind("<Double-1>", lambda _event: self._open_lookup_post())
        self._configure_colors(self.lookup_post_tree)
        self._make_sortable(
            self.lookup_post_tree,
            {"time": "日期", "type": "类型", "bar": "贴吧", "title": "标题", "content": "内容"},
        )
        self._lookup_post_urls: Dict[str, str] = {}

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
        query = self.lookup_query_var.get().strip()
        if not query:
            messagebox.showinfo("请输入", "先输入要查询的内容。", parent=self.root)
            return
        raw_query = query
        query = decode_display(query).strip() or query
        encoded_query = encode_display(raw_query).lower()
        mode = self.lookup_mode_var.get()
        try:
            count = int(self.lookup_count_var.get())
        except ValueError:
            count = 20
        count = max(5, min(1000, count))
        date_mode = self.lookup_date_mode_var.get()
        start_date = self.lookup_start_var.get().strip() if date_mode == "指定日期" else ""
        end_date = self.lookup_end_var.get().strip() if date_mode == "指定日期" else ""
        self.lookup_status.configure(text="查询中…")
        self._set_lookup_text("查询中，请稍候…")

        def worker():
            try:
                fetcher = Fetcher(cookie=parse_cookie_input(self.cookie_var.get()), delay=0.3, verbose=False)
                info = {}
                if mode == "昵称":
                    # 先在当前抓到的参与者里找（最可靠，避免昵称搜索接口搜不到）
                    for user in getattr(self, "people_users", []):
                        real_name = (user.get("name") or "").strip()
                        if (
                            real_name.lower() == query.lower()
                            or encode_display(real_name).lower() == encoded_query
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
                    "start" if "开始" in self.lookup_prefer_var.get() else "end",
                )
                profile["nickname"] = profile.get("nickname") or info.get("nickname") or ""
                self._post(("lookup_ready", profile, ""))
            except Exception as error:  # noqa: BLE001
                self._post(("lookup_ready", None, str(error)))

        threading.Thread(target=worker, daemon=True).start()

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
                values=(forum["name"], f"Lv.{forum['level']}" if forum.get("level") else "-"),
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
        self.lookup_forum_note.configure(text=self._forum_note(profile))

        info = (
            f"昵称 {encode_display(profile.get('nickname')) or '未知'} | 用户名 {profile.get('username') or '未知'} | "
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
        # 查用户页只做资料查看，不参与本地标记
        hit_level, hit_bar = "", ""
        hidden_follows = False
        label = {"ban": "禁止", "warn": "警告", "safe": "安全"}.get(hit_level, "")
        for key, (traffic_label, traffic_color) in getattr(self, "lookup_traffic_labels", {}).items():
            traffic_label.configure(fg=traffic_color if key == hit_level else "#d1d5db")
        risk = " · 关注列表隐藏，未命中禁止时标黄" if hidden_follows else ""
        try:
            self.lookup_traffic_text.configure(
                text=(
                    (f"{label}：{hit_bar}" if hit_bar and hit_bar != "关注列表隐藏" else label)
                    if hit_level
                    else "查用户页不参与本地标记"
                )
                + risk
            )
        except tk.TclError:
            pass
        if hit_level:
            info += f" | 命中{label}：{hit_bar}"
        if hidden_follows:
            info += " | ⚠ 关注列表隐藏，未命中禁止时标黄"
        self.lookup_info.configure(text=info)
        self.lookup_status.configure(text=f"{profile.get('username') or ''} · {len(posts)} 条发言")

    def _open_participants(self) -> None:
        if not self.last_threads:
            messagebox.showinfo("还没有数据", "先点「开始统计」抓一个帖子，再查看参与者。", parent=self.root)
            return
        self._refresh_people()
        self.notebook.select(self.tab_posts)
        self.post_nb.select(self.tab_people)

    def _refresh_people(self) -> None:
        users = self._aggregate_users()
        self.people_users = users
        self._profile_cache = {}
        for item in self.people_tree.get_children():
            self.people_tree.delete(item)
        for index, user in enumerate(users):
            user["_iid"] = str(index)
            self.people_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "⚪" if self._risk_enabled() else "",
                    encode_display(user["name"]),
                    user["username"] or "-",
                    user["uid"] or "-",
                    f"Lv.{user['level']}" if user["level"] else "-",
                    user["floor"],
                    user["comment"],
                    user["total"],
                ),
            )
        with_level = sum(1 for user in users if user.get("level"))
        self.people_hint.configure(text=f"v{VERSION} · 共 {len(users)} 人 · 有等级 {with_level}")
        self.profile_status.configure(text="选择左边一个人查看详情")
        for tree in (self.profile_forum_tree, self.profile_post_tree):
            for item in tree.get_children():
                tree.delete(item)

    def _on_person_select(self, _event=None) -> None:
        selection = self.people_tree.selection()
        if not selection:
            return
        try:
            user = self.people_users[int(selection[0])]
        except (IndexError, ValueError):
            return
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
        if hasattr(self, "batch_btn"):
            self.batch_btn.configure(state="normal" if enabled else "disabled")

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
    def _build_mode_bar(self, parent) -> None:
        bar = tk.Frame(parent, bg="#ffffff", padx=16, pady=8)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="使用方式：",
            bg="#ffffff",
            fg="#334155",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left")
        ttk.Radiobutton(
            bar, text="免登录", value="guest", variable=self.mode_var, command=self._on_mode_select
        ).pack(side="left", padx=(4, 0))
        ttk.Radiobutton(
            bar,
            text="登录（Cookie）",
            value="login",
            variable=self.mode_var,
            command=self._on_mode_select,
        ).pack(side="left", padx=(12, 0))
        self.mode_hint = tk.Label(bar, text="", bg="#ffffff", fg="#6b7280", font=("Microsoft YaHei UI", 8))
        self.mode_hint.pack(side="left", padx=(12, 0))

    def _apply_mode_ui(self) -> None:
        login = self.mode_var.get() == "login"
        state = "normal" if login else "disabled"
        for widget in getattr(self, "cookie_controls", []):
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        if hasattr(self, "mode_hint"):
            self.mode_hint.configure(
                text="完整楼中楼 · 关注列表 · 完整资料"
                if login
                else "公开帖子 · 每层前 10 条楼中楼 · 红绿灯只看发言"
            )

    def _on_mode_select(self) -> None:
        mode = self.mode_var.get()
        self._set_mode(mode)
        self._append_log(f"已切换为{'登录' if mode == 'login' else '免登录'}模式", "muted")

    def _set_mode(self, mode: str, persist: bool = True) -> None:
        mode = mode if mode in ("guest", "login") else "guest"
        self.mode_var.set(mode)
        if persist:
            self.settings["mode"] = mode
            self.settings["mode_chosen"] = True
            save_settings(self.settings)
        self._apply_mode_ui()

    def _maybe_choose_mode(self) -> None:
        if self.mode_chosen:
            return
        self._show_mode_dialog()

    def _show_mode_dialog(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("选择使用方式")
        win.configure(bg="#ffffff")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        frame = tk.Frame(win, bg="#ffffff", padx=20, pady=16)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="选择使用方式",
            bg="#ffffff",
            fg="#1f2937",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            frame,
            text="之后可在「抓取」页顶部随时切换。",
            bg="#ffffff",
            fg="#6b7280",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(2, 10))
        choice = tk.StringVar(value=self.mode_var.get())
        cards = tk.Frame(frame, bg="#ffffff")
        cards.pack(fill="x")
        for value, title, desc in (
            ("guest", "免登录（推荐）", "公开帖子；楼中楼每层前 10 条；红绿灯只看发言"),
            ("login", "登录（Cookie）", "完整楼中楼、关注列表、完整资料；需要 BDUSS"),
        ):
            row = tk.Frame(
                cards,
                bg="#f8fafc",
                highlightthickness=1,
                highlightbackground="#e2e8f0",
                padx=10,
                pady=8,
            )
            row.pack(fill="x", pady=4)
            ttk.Radiobutton(row, text=title, value=value, variable=choice).pack(anchor="w")
            tk.Label(
                row,
                text=desc,
                bg="#f8fafc",
                fg="#64748b",
                font=("Microsoft YaHei UI", 8),
            ).pack(anchor="w", padx=20)
        remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="记住选择（下次不再询问）", variable=remember).pack(
            anchor="w", pady=(10, 8)
        )
        buttons = tk.Frame(frame, bg="#ffffff")
        buttons.pack(fill="x")

        def finish(mode: str) -> None:
            chosen = bool(remember.get())
            self.mode_chosen = chosen
            self.settings["mode"] = mode
            self.settings["mode_chosen"] = chosen
            save_settings(self.settings)
            self.mode_var.set(mode)
            self._apply_mode_ui()
            self._append_log(f"已选择{'登录' if mode == 'login' else '免登录'}模式", "muted")
            win.destroy()

        ttk.Button(buttons, text="先免登录", command=lambda: finish("guest")).pack(side="left")
        ttk.Button(buttons, text="使用所选模式", command=lambda: finish(choice.get())).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", lambda: finish("guest"))
        win.update_idletasks()
        width, height = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 3)
        win.geometry(f"+{x}+{y}")

    def _build_settings_tab(self) -> None:
        inner = ttk.Notebook(self.tab_settings)
        inner.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab_general = tk.Frame(inner, bg="#eef1f5")
        self.tab_blacklist = tk.Frame(inner, bg="#eef1f5")
        self.tab_help = tk.Frame(inner, bg="#eef1f5")
        inner.add(self.tab_general, text="  通用  ")
        inner.add(self.tab_blacklist, text="  黑名单  ")
        inner.add(self.tab_help, text="  使用说明  ")
        self._build_general_tab()

        box = tk.Frame(self.tab_blacklist, bg="#eef1f5", padx=16, pady=12)
        box.pack(fill="both", expand=True)
        tk.Label(
            box,
            text="黑名单：每行一个贴吧名（带不带“吧”都行），命中后按 红 > 黄 > 绿 标记。",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(0, 8))
        self.blacklist_editors = {}
        for key, title in (("safe", "安全（绿色）"), ("warn", "警告（黄色）"), ("ban", "禁止（红色）")):
            frame = ttk.LabelFrame(box, text=f" {title} ")
            frame.pack(fill="both", expand=True, pady=4)
            editor = tk.Text(frame, height=6, wrap="word", font=("Microsoft YaHei UI", 9))
            editor.pack(fill="both", expand=True, padx=6, pady=6)
            editor.insert("1.0", "\n".join(self.blacklist.get(key, [])))
            self.blacklist_editors[key] = editor
        bar = tk.Frame(box, bg="#eef1f5")
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="保存黑名单", command=self._save_blacklist_from_tab).pack(side="left")
        ttk.Button(bar, text="导入 Excel", command=self._import_blacklist).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="导出 Excel", command=self._export_blacklist).pack(side="left", padx=(8, 0))
        self.settings_hint = tk.Label(
            bar, text="", bg="#eef1f5", fg="#15803d", font=("Microsoft YaHei UI", 9)
        )
        self.settings_hint.pack(side="left", padx=(10, 0))
        self._build_help_tab()

    def _build_general_tab(self) -> None:
        box = tk.Frame(self.tab_general, bg="#eef1f5", padx=16, pady=12)
        box.pack(fill="both", expand=True)
        tk.Label(
            box,
            text="表格标色：命中黑名单时，给对应表格的行加背景色（红 / 黄 / 绿）。",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(0, 10))
        risk_box = ttk.LabelFrame(box, text=" 本地标记（红绿灯） ")
        risk_box.pack(fill="x", pady=(0, 10))
        self.risk_var = tk.BooleanVar(value=bool(self.settings.get("risk_enabled", False)))
        ttk.Checkbutton(
            risk_box,
            text="启用本地标记与红绿灯（默认关闭）",
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

        self.setting_vars = {}
        for key, text in (
            ("color_people", "在参与者列表里标色"),
            ("color_forum", "在「关注的贴吧」表格里标色"),
            ("color_posts", "在「最近发言」表格里标色"),
        ):
            var = tk.BooleanVar(value=bool(self.settings.get(key, True)))
            ttk.Checkbutton(box, text=text, variable=var, command=self._on_settings_changed).pack(
                anchor="w", pady=4
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

    def _build_help_tab(self) -> None:
        frame = tk.Frame(self.tab_help, bg="#eef1f5", padx=10, pady=10)
        frame.pack(fill="both", expand=True)
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

    def _save_blacklist_from_tab(self) -> None:
        data = {
            key: [line.strip() for line in editor.get("1.0", "end").splitlines() if line.strip()]
            for key, editor in self.blacklist_editors.items()
        }
        if save_blacklist(data):
            self.blacklist = data
            self.settings_hint.configure(text="已保存")
            self._append_log("黑名单已保存。", "ok")
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
            title="导出黑名单",
            defaultextension=".xlsx",
            initialfile="贴吧黑名单.xlsx",
            filetypes=[("Excel 表格", "*.xlsx")],
        )
        if not path:
            return
        if export_blacklist_xlsx(path, self._blacklist_from_editors()):
            self.settings_hint.configure(text=f"已导出：{os.path.basename(path)}")
            self._append_log(f"黑名单已导出：{path}", "ok")
        else:
            messagebox.showerror("导出失败", "无法写入文件，请换个位置重试。", parent=self.root)

    def _import_blacklist(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="导入黑名单",
            filetypes=[("Excel 表格", "*.xlsx"), ("所有文件", "*.*")],
        )
        if not path:
            return
        data = import_blacklist_xlsx(path)
        total = sum(len(value) for value in data.values())
        if not total:
            messagebox.showwarning(
                "没有读到数据",
                "格式应为两列：\n第一列 类别（安全 / 警告 / 禁止）\n第二列 贴吧名\n\n"
                "可以用「导出 Excel」生成模板后再填。",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "确认导入",
            f"读到：安全 {len(data['safe'])} 个、警告 {len(data['warn'])} 个、"
            f"禁止 {len(data['ban'])} 个。\n\n会覆盖当前黑名单，继续吗？",
            parent=self.root,
        ):
            return
        if save_blacklist(data):
            self.blacklist = data
            for key, editor in self.blacklist_editors.items():
                editor.delete("1.0", "end")
                editor.insert("1.0", "\n".join(data[key]))
            self.settings_hint.configure(text="已导入")
            self._append_log(f"黑名单已导入：{path}", "ok")
        else:
            messagebox.showerror("导入失败", "保存失败，请检查配置目录权限。", parent=self.root)

    def _build_grid_tab(self) -> None:
        bar = tk.Frame(self.tab_grid, bg="#ffffff", padx=12, pady=8)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="表格可排序、双击打开链接、Ctrl+C 复制",
            bg="#ffffff",
            fg="#6b7280",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        self.export_btn = tk.Button(
            bar,
            text="导出 Excel",
            command=self._export_now,
            bg="#e5e9f0",
            fg="#334155",
            activebackground="#d5dbe5",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 10),
        )
        self.export_btn.pack(side="left", padx=(10, 0))
        self.open_btn = tk.Button(
            bar,
            text="打开 Excel",
            command=self._open_result,
            bg="#e5e9f0",
            fg="#334155",
            activebackground="#d5dbe5",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
            font=("Microsoft YaHei UI", 10),
            state="disabled",
        )
        self.open_btn.pack(side="left", padx=(8, 0))
        self.grid_hint = tk.Label(
            bar, text="抓取完成后这里会显示表格", bg="#ffffff", fg="#8a94a6", font=("Microsoft YaHei UI", 9)
        )
        self.grid_hint.pack(side="right")

        self.grid_nb = ttk.Notebook(self.tab_grid)
        self.grid_nb.pack(fill="both", expand=True, padx=8, pady=8)

    def _refresh_grid(self) -> None:
        for tab in list(self.grid_nb.tabs()):
            self.grid_nb.forget(tab)
        if not self.last_threads:
            self.grid_hint.configure(text="还没有数据")
            return
        thread = self.last_threads[0]
        include_op = getattr(self, "last_include_op", True)
        stats = thread.user_stats(include_op)

        def user_url(item):
            if item.get("username"):
                return "https://tieba.baidu.com/home/main?un=" + quote(item["username"])
            portrait = str(item.get("portrait") or "").split("?")[0]
            if portrait:
                return "https://tieba.baidu.com/home/main?id=" + quote(portrait)
            return ""

        user_rows = [
            [
                index,
                item["name"],
                item["username"],
                item["uid"],
                item["level"],
                item["badge"],
                item["floor_count"],
                item["comment_count"],
                item["total"],
            ]
            for index, item in enumerate(stats, start=1)
        ]
        self._add_grid_tab(
            self.grid_nb,
            "回复统计",
            ["#", "昵称", "用户名", "用户ID", "等级", "头衔", "楼层", "楼中楼", "合计"],
            user_rows,
            urls=[user_url(item) for item in stats],
        )
        floor_rows = [
            [
                floor.post_no,
                floor.author,
                floor.author_name,
                floor.author_id,
                floor.level,
                floor.badge,
                floor.content,
            ]
            for floor in thread.floors
        ]
        self._add_grid_tab(
            self.grid_nb,
            "楼层明细",
            ["楼层", "昵称", "用户名", "用户ID", "等级", "头衔", "内容"],
            floor_rows,
            urls=[f"https://tieba.baidu.com/p/{thread.meta.tid}?pid={floor.pid}" for floor in thread.floors],
        )
        comment_rows = [
            [
                comment.floor_no,
                comment.author,
                comment.author_name,
                comment.author_id,
                comment.level,
                comment.content,
            ]
            for comment in thread.comments
        ]
        self._add_grid_tab(
            self.grid_nb,
            "楼中楼明细",
            ["所在楼层", "回复者", "用户名", "用户ID", "等级", "内容"],
            comment_rows,
            urls=[
                f"https://tieba.baidu.com/p/{thread.meta.tid}?pid={comment.pid}"
                for comment in thread.comments
            ],
        )
        self.grid_hint.configure(text=f"帖子：{thread.meta.title or thread.meta.tid}")

    def _add_grid_tab(
        self, notebook, title: str, headers: List[str], rows: List[list], urls: Optional[List[str]] = None
    ) -> None:
        urls = list(urls or [])
        frame = tk.Frame(notebook)
        notebook.add(frame, text=f"  {title}  ")
        columns = [str(index) for index in range(len(headers))]
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for index, header in enumerate(headers):
            tree.heading(columns[index], text=header)
            if header == "内容":
                width = 240
            elif header in ("用户ID", "用户名"):
                width = 110
            else:
                width = 80
            tree.column(columns[index], width=width, anchor="w" if header in ("内容", "昵称") else "center")
        tree.links = {}  # type: ignore[attr-defined]
        for row_index, row in enumerate(rows):
            values = ["" if value is None else value for value in row]
            iid = tree.insert("", "end", values=values)
            tree.links[iid] = urls[row_index] if row_index < len(urls) else ""  # type: ignore[attr-defined]
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

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
        menu.add_command(label="打开链接", command=open_row)
        menu.add_command(label="复制整行", command=copy_row)

        def show_menu(event) -> None:
            row = tree.identify_row(event.y)
            if row:
                tree.selection_set(row)
                try:
                    menu.tk_popup(event.x_root, event.y_root)
                finally:
                    menu.grab_release()

        tree.bind("<Button-3>", show_menu)

        sort_state: Dict[str, Any] = {"column": None, "reverse": False}

        def sort_by(column: str) -> None:
            if sort_state["column"] == column:
                sort_state["reverse"] = not sort_state["reverse"]
            else:
                sort_state["column"] = column
                sort_state["reverse"] = False
            reverse = bool(sort_state["reverse"])

            def key(item):
                value = tree.set(item, column)
                try:
                    return (0, float(value))
                except ValueError:
                    return (1, str(value))

            items = list(tree.get_children())
            items.sort(key=key, reverse=reverse)
            for position, item in enumerate(items):
                tree.move(item, "", position)
            for index, header in enumerate(headers):
                arrow = ""
                if columns[index] == column:
                    arrow = " ▼" if reverse else " ▲"
                tree.heading(columns[index], text=header + arrow)

        def make_command(column: str) -> Callable[[], None]:
            return lambda: sort_by(column)

        for index, header in enumerate(headers):
            tree.heading(columns[index], command=make_command(columns[index]))

    def _open_blacklist_dialog(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("贴吧黑名单设置")
        win.geometry("640x580")
        win.configure(bg="#f5f7fa")
        tk.Label(
            win,
            text="每行一个贴吧名（带不带“吧”都可以）。用户在这些吧发过言，就会打上对应颜色标记。",
            bg="#f5f7fa",
            fg="#6b7280",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        body = tk.Frame(win, bg="#f5f7fa")
        body.pack(fill="both", expand=True, padx=12)
        editors = {}
        for key, title in (("safe", "安全（绿色）"), ("warn", "警告（黄色）"), ("ban", "禁止（红色）")):
            frame = ttk.LabelFrame(body, text=f" {title} ")
            frame.pack(fill="both", expand=True, pady=4)
            text = tk.Text(frame, height=4, wrap="word", font=("Microsoft YaHei UI", 9))
            text.pack(fill="both", expand=True, padx=6, pady=6)
            text.insert("1.0", "\n".join(self.blacklist.get(key, [])))
            editors[key] = text

        def save() -> None:
            data = {
                key: [line.strip() for line in editor.get("1.0", "end").splitlines() if line.strip()]
                for key, editor in editors.items()
            }
            if save_blacklist(data):
                self.blacklist = data
                self._append_log("黑名单已保存。", "ok")
                win.destroy()
            else:
                messagebox.showerror("保存失败", "无法写入黑名单配置文件。", parent=win)

        ttk.Button(win, text="保存", command=save).pack(pady=10)

    def _export_now(self) -> None:
        if not self.last_threads:
            messagebox.showinfo("还没有数据", "先点「开始统计」抓一个帖子。", parent=self.root)
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
        try:
            export_workbook(path, self.last_threads, include_op=getattr(self, "last_include_op", True))
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("导出失败", str(error), parent=self.root)
            return
        self.last_output = path
        self.open_btn.configure(state="normal")
        self._append_log(f"已导出 Excel：{path}", "ok")
        messagebox.showinfo("导出完成", f"已保存到：\n{path}\n\n现在打开吗？", parent=self.root)
        self._open_result()

    def _enrich_levels_now(self) -> None:
        if not self.last_threads:
            messagebox.showinfo("还没有数据", "先点「开始统计」抓一个帖子。", parent=self.root)
            return
        if getattr(self, "_enriching", False):
            return
        self._enriching = True
        self.people_hint.configure(text="正在补全等级，请稍候…")

        def worker():
            try:
                fetcher = Fetcher(cookie=parse_cookie_input(self.cookie_var.get()), delay=0.3, verbose=False)
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

    def _batch_refresh_marks(self) -> None:
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
        self._batch_running = True
        self._batch_cancel = False
        self._batch_done = 0
        self._batch_total = len(self.people_users)
        self.batch_btn.configure(text="停止查询")
        self.people_hint.configure(text=f"批量查询 0/{self._batch_total}…")
        users = list(self.people_users)
        count = self._post_count()
        start_date, end_date = self._date_params()
        prefer = "start" if "开始" in self.post_prefer_var.get() else "end"

        def worker():
            fetcher = Fetcher(cookie=parse_cookie_input(self.cookie_var.get()), delay=0.3, verbose=False)
            guest = self.mode_var.get() == "guest"
            for index, user in enumerate(users):
                if self._batch_cancel:
                    break
                if guest:
                    profile = {"ok": True, "guest_only": True}
                elif user.get("uid") or user.get("username"):
                    try:
                        profile = fetch_user_profile(
                            fetcher,
                            user.get("uid") or "",
                            user.get("username") or "",
                            user.get("portrait") or "",
                            self._user_bar(user),
                            count,
                            start_date,
                            end_date,
                            prefer,
                        )
                    except Exception as error:  # noqa: BLE001
                        profile = {"ok": False, "error": str(error)}
                else:
                    profile = {"ok": False, "error": "缺少用户ID"}
                self._post(("batch_profile", index, user, profile))
            self._post(("batch_done",))

        threading.Thread(target=worker, daemon=True).start()

    def _hidden_follows(self, profile) -> bool:
        return bool(profile.get("followed_private")) or profile.get("priv_like") == 3

    def _profile_hit(self, profile, extra_bars=None):
        if not self._risk_enabled():
            return "", ""
        if self.mode_var.get() == "guest":
            bars = [bar for bar in (extra_bars or []) if bar]
            return classify(bars, getattr(self, "blacklist", {}))
        bars = [post.get("bar") for post in profile.get("recent_posts") or [] if post.get("bar")]
        bars += [forum["name"] for forum in self._merge_forum_lists(profile)]
        if extra_bars:
            bars += [bar for bar in extra_bars if bar]
        hit_level, hit_bar = classify(bars, getattr(self, "blacklist", {}))
        if self._hidden_follows(profile) and hit_level != "ban":
            if hit_level != "warn":
                hit_bar = "关注列表隐藏"
            hit_level = "warn"
        return hit_level, hit_bar

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
        hit_level = ""
        if profile.get("ok"):
            hit_level, _ = self._profile_hit(profile, [self._user_bar(user)])
        label = {"ban": "禁止", "warn": "警告", "safe": "安全"}.get(hit_level, "")
        hidden = self._hidden_follows(profile) if profile.get("ok") else False
        try:
            values = list(self.people_tree.item(iid, "values"))
            if hit_level:
                values[0] = f"{marker(hit_level)} {label}" + (" ⚠" if hidden else "")
            else:
                values[0] = "⚪"
            if level:
                values[4] = f"Lv.{level}"
            self.people_tree.item(
                iid,
                values=values,
                tags=(hit_level,) if hit_level and self.settings.get("color_people", True) else (),
            )
        except tk.TclError:
            pass

    def _load_profile(self, user, force: bool = False) -> None:
        key = user["uid"] or f"name:{user['name']}"
        cached = None if force else getattr(self, "_profile_cache", {}).get(key)
        if cached:
            self._render_profile(user, cached)
            return
        self.profile_status.configure(text=f"正在查询 {encode_display(user['name'])} …")
        for tree in (self.profile_forum_tree, self.profile_post_tree):
            for item in tree.get_children():
                tree.delete(item)
        count = self._post_count()
        start_date, end_date = self._date_params()
        bar_name = self._user_bar(user)

        def worker():
            try:
                fetcher = Fetcher(cookie=parse_cookie_input(self.cookie_var.get()), delay=0.3, verbose=False)
                profile = fetch_user_profile(
                    fetcher,
                    user["uid"],
                    user["username"],
                    user["portrait"],
                    bar_name,
                    count,
                    start_date,
                    end_date,
                    "start" if "开始" in self.post_prefer_var.get() else "end",
                )
            except Exception as error:  # noqa: BLE001
                profile = {"ok": False, "error": str(error)}
            self._post(("profile_ready", key, user, profile))

        threading.Thread(target=worker, daemon=True).start()

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
        tree.tag_configure("ban", background="#ffdede")
        tree.tag_configure("warn", background="#fff4cc")
        tree.tag_configure("safe", background="#dcfce7")

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
        merged = {forum["name"]: dict(forum) for forum in base if forum.get("name")}
        if not forums:
            for forum in profile.get("like_forum") or []:
                name = forum.get("name")
                if name and name not in merged:
                    merged[name] = {"name": name, "level": 0, "level_name": ""}
        if bar_name and bar_level:
            name = bar_name[:-1] if bar_name.endswith("吧") and len(bar_name) > 2 else bar_name
            level_int = int(bar_level or 0)
            if name and level_int > 0:
                existing = merged.get(name)
                if existing is None:
                    merged[name] = {"name": name, "level": level_int, "level_name": ""}
                elif not existing.get("level"):
                    existing["level"] = level_int
        return sorted(merged.values(), key=lambda item: int(item.get("level") or 0), reverse=True)

    def _forum_note(self, profile, bar_name: str = "", bar_level: str = "") -> str:
        forums = profile.get("followed_forums") or []
        hidden = profile.get("hidden_forums") or []
        if forums:
            return f"共 {len(forums)} 个（完整）"
        if hidden or profile.get("like_forum"):
            count = len(self._merge_forum_lists(profile, bar_name, bar_level))
            note = f"对方隐藏了完整关注列表，已从等级头衔/精选恢复 {count} 个，可能不全"
            if self._hidden_follows(profile):
                note += "（风险提示：关注列表隐藏，未命中禁止时标黄）"
            return note
        if profile.get("followed_private"):
            return "对方设置了隐私，关注列表不可见（风险提示：关注列表隐藏，未命中禁止时标黄）"
        return "没有查到关注列表"

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
                text=f"查询失败：{profile.get('error') or '未知错误'}（可能是 Cookie 失效或对方设置了隐私）"
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

        posts = profile.get("recent_posts") or []
        combined = self._merge_forum_lists(profile, self._user_bar(user), level or "")

        for index, forum in enumerate(combined):
            iid = str(index)
            forum_tree.insert(
                "",
                "end",
                iid=iid,
                values=(forum["name"], f"Lv.{forum['level']}" if forum.get("level") else "-"),
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
        self.profile_forum_note.configure(text=self._forum_note(profile, self._user_bar(user), level or ""))

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
        label = {"ban": "禁止", "warn": "警告", "safe": "安全"}.get(hit_level, "")
        for traffic_key, (traffic_label, traffic_color) in getattr(self, "traffic_labels", {}).items():
            traffic_label.configure(fg=traffic_color if traffic_key == hit_level else "#d1d5db")
        risk = " · 关注列表隐藏，未命中禁止时标黄" if hidden_follows else ""
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
            f"{encode_display(user['name'])} | {user['username'] or '-'} | ID {user['uid'] or '-'} | "
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
            status += " · ⚠ 关注列表隐藏，未命中禁止时标黄"
        self.profile_status.configure(text=status)

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
            messagebox.showwarning(
                "缺少链接",
                "请先粘贴至少一个帖子链接，例如：\nhttps://tieba.baidu.com/p/1234567890",
                parent=self.root,
            )
            return
        if bad:
            messagebox.showwarning(
                "有内容无法识别",
                "下面这些不是有效的帖子链接，将被忽略：\n\n" + "\n".join(bad[:6]),
                parent=self.root,
            )

        export = self.export_var.get()
        output = self.output_var.get().strip() or default_output_path()
        if export:
            if not output.lower().endswith(".xlsx"):
                output += ".xlsx"
            self._set_output(output)
            if os.path.exists(output) and not messagebox.askyesno(
                "文件已存在", f"这个文件已经存在：\n{output}\n\n要覆盖它吗？", parent=self.root
            ):
                return
        else:
            output = ""

        try:
            delay = float(self.delay_var.get())
        except ValueError:
            delay = 0.8
        delay = min(5.0, max(0.3, delay))

        cookie = parse_cookie_input(self.cookie_var.get())
        mode = self.mode_var.get()
        if mode == "login" and not cookie.get("BDUSS"):
            answer = messagebox.askyesnocancel(
                "登录模式需要 Cookie",
                """登录模式至少需要 BDUSS。

是：去填写 Cookie
否：切换为免登录模式
取消：先不抓取""",
                parent=self.root,
            )
            if answer is True:
                self.cookie_entry.focus_set()
            elif answer is False:
                self._set_mode("guest")
            return
        if mode == "guest":
            self._append_log("本次使用免登录模式：公开帖子，楼中楼每层前 10 条", "muted")
        if cookie and self.remember_var.get():
            if save_cookie(self.cookie_var.get().strip()):
                self._append_log("已记住 Cookie（本机加密保存），下次会自动填入。", "muted")
            else:
                self._append_log("Cookie 保存失败，本次仍可正常使用。", "muted")

        options = CollectOptions(
            mode=mode,
            include_comments=self.comments_var.get(),
            enrich_levels=True,
            pb_levels=True,
            verbose=True,
            log=self._log_from_thread,
            should_stop=self.stop_event.is_set,
        )
        include_op = not self.exclude_op_var.get()
        self.last_include_op = include_op

        self.stop_event.clear()
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

    def _on_close(self) -> None:
        if self.running and not messagebox.askyesno("仍在抓取", "还没抓完，确定要退出吗？", parent=self.root):
            return
        self.stop_event.set()
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
            self._post(("error", f"{type(error).__name__}: {error}\n\n{traceback.format_exc()}"))

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
            self.last_threads = threads or []
            self._auto_filled = False
            self._set_running(False)
            self.status_var.set("完成")
            try:
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
                    "切到「参与者」选项卡可以点开每个人，查看他的最近发言和关注的贴吧。",
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
        elif kind == "batch_profile":
            _, index, user, profile = message
            self._batch_done = max(getattr(self, "_batch_done", 0), index + 1)
            key = user.get("uid") or f"name:{user['name']}"
            if profile and profile.get("ok"):
                self._profile_cache[key] = profile
            self._apply_batch_mark(user, profile)
            if getattr(self, "_batch_total", 0):
                self.people_hint.configure(text=f"批量查询 {self._batch_done}/{self._batch_total}…")
        elif kind == "batch_done":
            cancelled = getattr(self, "_batch_cancel", False)
            self._batch_running = False
            self._batch_cancel = False
            self.batch_btn.configure(text="一键红绿灯")
            done = getattr(self, "_batch_done", 0)
            total = getattr(self, "_batch_total", 0)
            self.people_hint.configure(text=f"已刷新 {done}/{total} 人的红绿灯")
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
                self._set_lookup_text(f"查询失败：{error}")
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
            self._append_log(f"\n✗ {detail}", "err")
            self._append_log(
                "请点「如何获取？」，按说明复制 Cookie，粘贴后点「从剪贴板粘贴」或直接粘贴，再点「开始统计」。",
                "err",
            )
            self.cookie_entry.focus_set()
            messagebox.showwarning(
                "被安全验证拦截",
                "贴吧要求安全验证，直接抓取被拦住了。\n\n"
                "解决办法：\n"
                "1. 点「如何获取？」按说明在浏览器里复制 Cookie；\n"
                "2. 粘贴到 Cookie 输入框（或点「从剪贴板粘贴」）；\n"
                "3. 再点「开始统计」。\n\n"
                "粘贴一次后程序会自动记住，以后不用再弄。",
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


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
