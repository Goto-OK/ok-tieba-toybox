"""GUI 版面构建 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import os
import tkinter as tk
from functools import partial
from tkinter import ttk
from typing import Any, Dict, List

from tieba_reply_stats.filters import FIELD_OPTIONS, LEVEL_OPTIONS
from tieba_reply_stats.version import __version__ as VERSION

APP_TITLE = "OK的贴吧玩具箱"


class GuiLayoutMixin:
    """版面构建方法，从 App 拆出，便于后续继续拆分。"""

    lookup_entry: Any
    lookup_native_edit: Any
    lookup_native_host: Any
    love_native_edit: Any
    love_native_host: Any
    emoji_btn: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} v{VERSION}")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        try:
            scale = float(self.root.tk.call("tk", "scaling")) / (96 / 72)
        except (tk.TclError, ValueError):
            scale = 1.0
        if scale >= 1.45:
            base_w, base_h = 1500, 960
        elif scale >= 1.2:
            base_w, base_h = 1440, 920
        else:
            base_w, base_h = 1400, 900
        width = max(1100, min(base_w, screen_w - 100))
        height = max(780, min(base_h, screen_h - 120))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(min(1100, screen_w - 40), min(760, screen_h - 80))
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
        tk.Label(
            status,
            text="F1 使用说明 · Ctrl+Enter 开始 · Esc 关闭",
            bg="#ffffff",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
            anchor="e",
        ).pack(side="right", padx=(8, 0))
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=180)

        self.body = tk.Frame(self.root, bg="#eef1f5")
        self.body.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(self.body, style="Main.TNotebook")
        self.notebook.pack(side="left", fill="both", expand=True)

        self.tab_posts = tk.Frame(self.notebook, bg="#eef1f5")
        self.tab_lookup = tk.Frame(self.notebook, bg="#eef1f5")
        self.tab_settings = tk.Frame(self.notebook, bg="#eef1f5")
        self.tab_links = tk.Frame(self.notebook, bg="#eef1f5")
        self.tab_love = tk.Frame(self.notebook, bg="#eef1f5")
        self.notebook.add(self.tab_posts, text="  帖子统计  ")
        self.notebook.add(self.tab_lookup, text="  查用户  ")
        self.notebook.add(self.tab_links, text="  链接解析  ")
        self.notebook.add(self.tab_love, text="  恋文增强（第三方）  ")
        self.notebook.add(self.tab_settings, text="  设置  ")

        self.post_nb = ttk.Notebook(self.tab_posts, style="Sub.TNotebook")
        self.post_nb.pack(fill="both", expand=True, padx=4, pady=4)
        self.tab_fetch = tk.Frame(self.post_nb, bg="#eef1f5")
        self.tab_grid = tk.Frame(self.post_nb, bg="#eef1f5")
        self.tab_people = tk.Frame(self.post_nb, bg="#eef1f5")
        self.post_nb.add(self.tab_fetch, text="  抓取  ")
        self.post_nb.add(self.tab_people, text="  参与者  ")
        self.post_nb.add(self.tab_grid, text="  表格查看  ")

        self.fetch_advanced_summary = tk.Label(
            self.tab_fetch,
            text="",
            anchor="w",
            bg="#fff7e6",
            fg="#92400e",
            font=("Microsoft YaHei UI", 8),
            padx=8,
            pady=3,
        )
        self.fetch_advanced_summary.pack(fill="x", padx=8, pady=(4, 0))
        self.fetch_advanced_summary.pack_forget()
        fetch_page, body = self._make_scrollable_settings_page(self.tab_fetch)
        self.fetch_page = fetch_page
        fetch_page.pack(fill="both", expand=True)
        body.configure(padx=16, pady=8)
        fetch_canvas = next(
            child for child in fetch_page.winfo_children() if isinstance(child, tk.Canvas)
        )
        self.fetch_body = body
        self.fetch_canvas = fetch_canvas
        body.bind(
            "<Enter>",
            lambda _event: self._bind_mousewheel_tree(self.fetch_body, self.fetch_canvas),
            add="+",
        )
        self._bind_mousewheel_tree(body, fetch_canvas)
        self.root.after_idle(
            lambda: self._bind_mousewheel_tree(self.fetch_body, self.fetch_canvas)
        )
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
        url_scroll = ttk.Scrollbar(box, orient="vertical", command=self.url_text.yview)
        url_scroll.grid(row=0, column=1, sticky="ns")
        self.url_text.configure(yscrollcommand=url_scroll.set)
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
        self.delay_row = delay_row
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

        identity_row = tk.Frame(options)
        identity_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 2))
        self.identity_row = identity_row
        tk.Label(identity_row, text="抓取完成后：").pack(side="left")
        self.identity_strategy_var = tk.StringVar(
            value={
                "full": "补全用户ID + 贴吧ID",
                "ask": "每次询问",
                "skip": "跳过补全",
                "user_id": "只补用户ID",
                "detail": "详情再补",
            }.get(str(self.settings.get("identity_strategy", "full")), "补全用户ID + 贴吧ID")
        )
        self.identity_strategy_box = ttk.Combobox(
            identity_row,
            values=("补全用户ID + 贴吧ID", "每次询问", "跳过补全", "只补用户ID", "详情再补"),
            textvariable=self.identity_strategy_var,
            width=20,
            state="readonly",
            exportselection=False,
        )
        self.identity_strategy_box.pack(side="left")
        self.identity_strategy_var.trace_add("write", lambda *_: self._save_identity_strategy())
        self.identity_timing_var = tk.BooleanVar(value=bool(self.settings.get("identity_timing", True)))
        ttk.Checkbutton(
            identity_row,
            text="阶段计时",
            variable=self.identity_timing_var,
            command=self._save_identity_strategy,
        ).pack(side="left", padx=(10, 0))
        tk.Label(identity_row, text="  贴吧ID并发：").pack(side="left")
        self.identity_concurrency_var = tk.StringVar(
            value=str(self.settings.get("identity_concurrency", 3))
        )
        self.identity_concurrency_box = ttk.Combobox(
            identity_row,
            values=("3", "5"),
            textvariable=self.identity_concurrency_var,
            width=3,
            state="readonly",
        )
        self.identity_concurrency_box.pack(side="left")
        self.identity_risk_label = tk.Label(
            identity_row,
            text="",
            bg="#ffffff",
            fg="#b91c1c",
            font=("Microsoft YaHei UI", 8),
        )
        self.identity_risk_label.pack(side="left", padx=(6, 0))
        self.identity_concurrency_var.trace_add(
            "write", lambda *_: self._save_identity_strategy()
        )
        self._update_identity_risk_hint()
        self.risk_summary_label = tk.Label(
            options,
            text="",
            bg="#ffffff",
            fg="#b91c1c",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
            justify="left",
        )
        self.risk_summary_label.grid(row=5, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 2))
        self.delay_var.trace_add("write", lambda *_: self._update_risk_summary())
        self.comment_concurrency_var.trace_add(
            "write", lambda *_: self._update_risk_summary()
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
        cookie_box = ttk.LabelFrame(body, text=" 登录 ", style="Card.TLabelframe")
        cookie_box.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.cookie_box = cookie_box
        cookie_box.columnconfigure(0, weight=1)
        self.cookie_var = tk.StringVar()
        self.login_method_var = tk.StringVar(value="bduss")

        login_header = tk.Frame(cookie_box, bg="#eef1f5")
        login_header.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(2, 2))
        self.login_summary_var = tk.StringVar(value="登录信息未配置")
        summary_frame = tk.Frame(login_header, bg="#eef1f5")
        summary_frame.pack(side="left", fill="x", expand=True)
        tk.Label(
            summary_frame,
            textvariable=self.login_summary_var,
            bg="#eef1f5",
            fg="#334155",
            font=("Microsoft YaHei UI", 9),
            anchor="w",
        ).pack(anchor="w")
        self.login_source_label = tk.Label(
            summary_frame,
            text="",
            bg="#eef1f5",
            fg="#b45309",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
        )
        self.login_source_label.pack(anchor="w")
        self.login_baidu_btn = ttk.Button(
            login_header,
            text="登录百度并获取",
            command=self._login_baidu,
            width=22,
        )
        self.login_baidu_btn.pack(side="right", padx=(8, 0))
        self.login_toggle_btn = ttk.Button(
            login_header,
            text="展开",
            command=self._toggle_login_fields,
            width=6,
        )
        self.login_toggle_btn.pack(side="right", padx=(8, 0))

        method_row = tk.Frame(cookie_box, bg="#eef1f5")
        method_row.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 4))
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
        self.bduss_frame.grid(row=2, column=0, columnspan=4, sticky="ew")
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
        self.cookie_var.trace_add("write", self._sync_bduss_from_cookie)
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
        self.cookie_frame.grid(row=2, column=0, columnspan=4, sticky="ew")
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
        self.login_switch_row = tk.Frame(cookie_box, bg="#eef1f5")
        self.login_switch_row.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        ttk.Button(
            self.login_switch_row,
            text="切换百度账号",
            command=self._switch_baidu_account,
            width=14,
        ).pack(side="left")
        tk.Label(
            self.login_switch_row,
            text="会替换当前登录；旧登录在新账号成功前保留。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left", padx=(8, 0))
        self.login_switch_row.grid_remove()
        self.login_method_row = method_row
        self.login_fields_widgets = [
            method_row,
            self.bduss_frame,
            self.cookie_frame,
            self.login_switch_row,
        ]
        self._login_fields_expanded = False
        self.cookie_controls = [
            self.login_bduss_radio,
            self.login_cookie_radio,
            self.bduss_entry,
            self.cookie_entry,
            self.cookie_paste_btn,
            self.cookie_help_btn,
            self.cookie_apply_btn,
            self.cookie_clear_btn,
            self.login_baidu_btn,
        ]
        self.login_method_var.trace_add("write", lambda *_: self._on_login_method_changed())
        self._set_login_fields_expanded(False)

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
        self.pause_btn = tk.Button(
            buttons,
            text="暂停",
            command=self._on_pause,
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
        self.pause_btn.pack(side="left", padx=(10, 0))
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
        self._build_links_tab()
        self._build_love_tab()
        self._build_settings_tab()
        self._apply_ui_mode(persist=False)

        self.url_text.focus_set()
        self.root.update_idletasks()
        self.start_btn.configure(state="normal")
        self._append_log("把帖子链接粘贴到上面，然后点「开始统计」。", "muted")


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
            bar,
            from_=5,
            to=1000,
            increment=10,
            width=7,
            textvariable=self.post_count_var,
            state="normal",
            takefocus=True,
        )
        self.post_count_box.pack(side="left")
        self.post_count_box.bind(
            "<FocusIn>",
            lambda _event: self.post_count_box.selection_range(0, "end"),
            add="+",
        )
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

        bar3 = tk.Frame(self.tab_people, bg="#ffffff", padx=12, pady=4)
        bar3.pack(fill="x")
        tk.Label(bar3, text="身份 / 修复：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.retry_incomplete_btn = ttk.Button(
            bar3, text="重试失败部分", command=self._retry_incomplete_threads, width=12
        )
        self.retry_incomplete_btn.pack(side="left", padx=(0, 0))
        self.supplement_btn = ttk.Button(
            bar3, text="补全身份", command=self._supplement_identity_manual, width=10
        )
        self.supplement_btn.pack(side="left", padx=(6, 0))
        self.people_hint = tk.Label(bar3, text="", bg="#ffffff", fg="#8a94a6", font=("Microsoft YaHei UI", 9))
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
        self.people_mark_var = tk.StringVar(value="全部")
        self.people_reset_btn = ttk.Button(
            filter_bar, text="清除筛选", command=self._reset_people_filters, width=10
        )
        self.people_reset_btn.pack(side="left", padx=(8, 0))

        for var in (
            self.people_field_var,
            self.people_keyword_var,
            self.people_level_var,
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

        columns = ("mark", "name", "username", "tieba_uid", "uid", "level", "floor", "comment", "total")
        self.people_columns = columns
        self._people_col_filters: Dict[str, set] = {}
        self._people_sort: tuple = ("", False)
        headings = {
            "mark": "标记",
            "name": "昵称",
            "username": "用户名",
            "tieba_uid": "贴吧ID",
            "uid": "用户ID",
            "level": "等级",
            "floor": "楼层",
            "comment": "楼中楼",
            "total": "合计",
        }
        self._people_headings = headings
        widths = {
            "mark": 50,
            "name": 135,
            "username": 80,
            "tieba_uid": 85,
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
            mark = "  ▼" if col in ("name", "username", "tieba_uid", "uid") else ""
            command = (
                partial(self._filter_people_column, col)
                if col in ("name", "username", "tieba_uid", "uid")
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
        self._person_popup.add_command(label="复制贴吧ID", command=lambda: self._copy_person_field("tieba_uid"))
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
        self.profile_cache_label = tk.Label(
            right,
            text="",
            anchor="w",
            bg="#fbfcfe",
            fg="#2563eb",
            font=("Microsoft YaHei UI", 8),
        )
        self.profile_action_bar = tk.Frame(right, bg="#fbfcfe")
        self.profile_action_bar.pack(fill="x", padx=6, pady=(0, 4))
        profile_action_bar = self.profile_action_bar
        self.profile_topic_btn = ttk.Button(
            profile_action_bar, text="继续抓主题", command=self._continue_profile_topics
        )
        self.profile_topic_btn.pack(side="right", padx=(0, 4))
        self.profile_topic_btn.pack_forget()
        ttk.Button(profile_action_bar, text="刷新资料", command=self._reload_profile, width=8).pack(
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
        profile_forum_wrap = tk.Frame(forum_frame, bg="#fbfcfe")
        profile_forum_wrap.pack(fill="both", expand=True)
        self.profile_forum_tree = ttk.Treeview(
            profile_forum_wrap, columns=("bar", "level", "level_source", "source"), show="headings", height=12
        )
        self.profile_forum_tree.heading("bar", text="贴吧")
        self.profile_forum_tree.heading("level", text="等级")
        self.profile_forum_tree.heading("level_source", text="等级来源")
        self.profile_forum_tree.heading("source", text="关注来源")
        self.profile_forum_tree.column("bar", width=100, anchor="w")
        self.profile_forum_tree.column("level", width=45, anchor="center")
        self.profile_forum_tree.column("level_source", width=90, anchor="center")
        self.profile_forum_tree.column("source", width=80, anchor="center")
        profile_forum_yscroll = ttk.Scrollbar(
            profile_forum_wrap, orient="vertical", command=self.profile_forum_tree.yview
        )
        self.profile_forum_tree.configure(yscrollcommand=profile_forum_yscroll.set)
        self.profile_forum_tree.pack(side="left", fill="both", expand=True)
        profile_forum_yscroll.pack(side="right", fill="y")
        self.profile_forum_tree.bind("<Double-1>", lambda _event: self._open_profile_forum())
        self._configure_colors(self.profile_forum_tree)
        self._make_sortable(
            self.profile_forum_tree,
            {"bar": "贴吧", "level": "等级", "level_source": "等级来源", "source": "关注来源"},
            {"level"},
        )
        self._bind_loaded_filter(
            self.profile_forum_tree,
            {"bar": ("贴吧", False), "level": None, "level_source": ("等级来源", False), "source": ("关注来源", False)},
        )
        self._profile_forum_names: Dict[str, str] = {}

        tk.Label(
            post_frame,
            text="发言",
            bg="#fbfcfe",
            fg="#475569",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        profile_post_wrap = tk.Frame(post_frame, bg="#fbfcfe")
        profile_post_wrap.pack(fill="both", expand=True)
        self.profile_post_tree = ttk.Treeview(
            profile_post_wrap, columns=("time", "type", "bar", "title", "content", "source"), show="headings", height=12
        )
        self.profile_post_tree.heading("time", text="日期")
        self.profile_post_tree.heading("type", text="类型")
        self.profile_post_tree.heading("bar", text="贴吧")
        self.profile_post_tree.heading("title", text="标题")
        self.profile_post_tree.heading("content", text="内容")
        self.profile_post_tree.heading("source", text="数据来源")
        self.profile_post_tree.column("time", width=75, anchor="center")
        self.profile_post_tree.column("type", width=52, anchor="center")
        self.profile_post_tree.column("bar", width=100, anchor="w")
        self.profile_post_tree.column("title", width=180, anchor="w")
        self.profile_post_tree.column("content", width=220, anchor="w")
        self.profile_post_tree.column("source", width=95, anchor="center")
        self.profile_post_tree["displaycolumns"] = ("time", "type", "bar", "title", "content")
        profile_post_yscroll = ttk.Scrollbar(
            profile_post_wrap, orient="vertical", command=self.profile_post_tree.yview
        )
        self.profile_post_tree.configure(yscrollcommand=profile_post_yscroll.set)
        self.profile_post_tree.pack(side="left", fill="both", expand=True)
        profile_post_yscroll.pack(side="right", fill="y")
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
            values=("用户名", "贴吧ID", "昵称", "用户ID"),
            textvariable=self.lookup_mode_var,
            width=10,
            state="readonly",
        ).pack(side="left")
        tk.Label(query, text="  内容：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        self.lookup_query_var = tk.StringVar()
        self.lookup_entry = None
        self.lookup_native_edit = None
        self.lookup_native_host = None
        self.emoji_btn = None
        query_button = tk.Button(
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
        )
        query_button.pack(side="right", padx=(8, 0))
        if os.name == "nt" and self._create_lookup_native_edit():
            self.lookup_query_var.trace_add("write", self._on_lookup_query_changed)
            self.root.after(120, self._poll_native_lookup_text)
        else:
            self._build_lookup_fallback_entry(query, query_button)

        options = tk.Frame(page, bg="#ffffff", padx=12, pady=4)
        options.pack(fill="x")
        self.lookup_options = options
        tk.Label(options, text="条数：", bg="#ffffff", fg="#475569", font=("Microsoft YaHei UI", 8)).pack(
            side="left"
        )
        self.lookup_count_var = tk.StringVar(value="50")
        self.lookup_count_box = ttk.Spinbox(
            options,
            from_=5,
            to=1000,
            increment=10,
            width=7,
            textvariable=self.lookup_count_var,
            state="normal",
            takefocus=True,
        )
        self.lookup_count_box.pack(side="left")
        self.lookup_count_box.bind(
            "<FocusIn>",
            lambda _event: self.lookup_count_box.selection_range(0, "end"),
            add="+",
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
            text="查询方式：用户名 / 贴吧ID / 昵称 / 用户ID。贴吧ID是个人主页显示的ID。",
            anchor="w",
            bg="#eef1f5",
            fg="#64748b",
            font=("Microsoft YaHei UI", 9),
            wraplength=590,
            justify="left",
        )
        self.lookup_info.pack(fill="x")
        self.lookup_info.bind("<Button-3>", lambda _event: self._copy_lookup_summary())
        summary_bottom = tk.Frame(summary, bg="#eef1f5")
        summary_bottom.pack(fill="x", pady=(2, 0))
        self.lookup_copy_btn = ttk.Button(
            summary_bottom, text="复制摘要", command=self._copy_lookup_summary, width=9
        )
        self.lookup_copy_btn.pack(side="right", padx=(6, 0))
        traffic = tk.Frame(summary_bottom, bg="#eef1f5")
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
                fg="#d1d5db",
                bg="#eef1f5",
                font=("Microsoft YaHei UI", 14),
            )
            label.pack(side="left", padx=(2, 0))
            self.lookup_traffic_labels[key] = (label, color)
        self.lookup_traffic_text = tk.Label(
            traffic, text="", bg="#eef1f5", fg="#6b7280", font=("Microsoft YaHei UI", 8)
        )
        self.lookup_traffic_text.pack(side="left", padx=(8, 0))
        self.lookup_summary.bind(
            "<Configure>",
            lambda event: self.lookup_info.configure(wraplength=max(300, event.width - 24)),
        )

        cache_row = tk.Frame(page, bg="#eef1f5", padx=12)
        self.lookup_cache_row = cache_row
        self.lookup_cache_label = tk.Label(
            cache_row,
            text="",
            anchor="w",
            bg="#eef1f5",
            fg="#2563eb",
            font=("Microsoft YaHei UI", 8),
        )
        self.lookup_cache_label.pack(side="left")

        bottom = tk.Frame(page, bg="#eef1f5", padx=10, pady=6)
        bottom.pack(side="bottom", fill="x")
        self.lookup_bottom = bottom
        self.lookup_report_btn = ttk.Button(
            bottom, text="导出此人报告", command=self._export_lookup_report, width=14
        )
        self.lookup_posts_btn = ttk.Button(
            bottom, text="导出发言", command=self._export_lookup_posts, width=10
        )
        self.lookup_open_profile_btn = ttk.Button(
            bottom, text="打开主页", command=self._open_lookup_profile, width=10
        )
        self.lookup_open_profile_btn.pack(side="left", padx=(6, 0))
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
        lookup_forum_wrap = tk.Frame(left, bg="#eef1f5")
        lookup_forum_wrap.pack(fill="both", expand=True)
        self.lookup_forum_tree = ttk.Treeview(
            lookup_forum_wrap, columns=("bar", "level", "level_source", "source"), show="headings", height=14
        )
        self.lookup_forum_tree.heading("bar", text="贴吧")
        self.lookup_forum_tree.heading("level", text="等级")
        self.lookup_forum_tree.heading("level_source", text="等级来源")
        self.lookup_forum_tree.heading("source", text="关注来源")
        self.lookup_forum_tree.column("bar", width=120, anchor="w")
        self.lookup_forum_tree.column("level", width=50, anchor="center")
        self.lookup_forum_tree.column("level_source", width=90, anchor="center")
        self.lookup_forum_tree.column("source", width=80, anchor="center")
        lookup_forum_yscroll = ttk.Scrollbar(
            lookup_forum_wrap, orient="vertical", command=self.lookup_forum_tree.yview
        )
        self.lookup_forum_tree.configure(yscrollcommand=lookup_forum_yscroll.set)
        self.lookup_forum_tree.pack(side="left", fill="both", expand=True)
        lookup_forum_yscroll.pack(side="right", fill="y")
        self.lookup_forum_tree.bind("<Double-1>", lambda _event: self._open_lookup_forum())
        self._configure_colors(self.lookup_forum_tree)
        self._make_sortable(
            self.lookup_forum_tree,
            {"bar": "贴吧", "level": "等级", "level_source": "等级来源", "source": "关注来源"},
            {"level"},
        )
        self._bind_loaded_filter(
            self.lookup_forum_tree,
            {"bar": ("贴吧", False), "level": None, "level_source": ("等级来源", False), "source": ("关注来源", False)},
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
            post_wrap, columns=("time", "type", "bar", "title", "content", "source"), show="headings", height=14
        )
        self.lookup_post_tree.heading("time", text="日期")
        self.lookup_post_tree.heading("type", text="类型")
        self.lookup_post_tree.heading("bar", text="贴吧")
        self.lookup_post_tree.heading("title", text="标题")
        self.lookup_post_tree.heading("content", text="内容")
        self.lookup_post_tree.heading("source", text="数据来源")
        self.lookup_post_tree.column("time", width=90, anchor="center")
        self.lookup_post_tree.column("type", width=55, anchor="center")
        self.lookup_post_tree.column("bar", width=100, anchor="w")
        self.lookup_post_tree.column("title", width=230, anchor="w")
        self.lookup_post_tree.column("content", width=300, anchor="w")
        self.lookup_post_tree.column("source", width=100, anchor="center")
        self.lookup_post_tree["displaycolumns"] = ("time", "type", "bar", "title", "content")
        post_xscroll = ttk.Scrollbar(post_wrap, orient="horizontal", command=self.lookup_post_tree.xview)
        post_yscroll = ttk.Scrollbar(post_wrap, orient="vertical", command=self.lookup_post_tree.yview)
        self.lookup_post_tree.configure(xscrollcommand=post_xscroll.set, yscrollcommand=post_yscroll.set)
        self.lookup_post_tree.grid(row=0, column=0, sticky="nsew")
        post_yscroll.grid(row=0, column=1, sticky="ns")
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

