"""设置页构建 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Any

from tieba_gui_layout import APP_TITLE
from tieba_reply_stats.post_cache import DEFAULT_LIMIT_MB, MAX_LIMIT_MB, MIN_LIMIT_MB
from tieba_reply_stats.settings import APP_DIR
from tieba_reply_stats.version import __version__ as VERSION


class SettingsMixin:
    """设置页构建方法，从 App 拆出。"""

    settings: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

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
        mode_bar = tk.Frame(inner, bg="#eef1f5", padx=10, pady=6)
        mode_bar.pack(fill="x")
        tk.Label(
            mode_bar,
            text="界面模式：",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        self.ui_mode_var = tk.StringVar(
            value="advanced" if self.settings.get("ui_mode") == "advanced" else "simple"
        )
        ttk.Radiobutton(
            mode_bar,
            text="简洁模式",
            value="simple",
            variable=self.ui_mode_var,
            command=self._on_ui_mode_selected,
        ).pack(side="left", padx=(4, 8))
        ttk.Radiobutton(
            mode_bar,
            text="高级模式",
            value="advanced",
            variable=self.ui_mode_var,
            command=self._on_ui_mode_selected,
        ).pack(side="left")
        self.ui_mode_hint = tk.Label(
            mode_bar,
            text="简洁模式隐藏调参和高风险操作",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        )
        self.ui_mode_hint.pack(side="left", padx=(12, 0))

        self.tab_general_page, self.tab_general = self._make_scrollable_settings_page(inner)
        self.tab_login_page, self.tab_login = self._make_scrollable_settings_page(inner)
        self.tab_appearance_page, self.tab_appearance = self._make_scrollable_settings_page(inner)
        self.tab_blacklist_page, self.tab_blacklist = self._make_scrollable_settings_page(inner)
        self.tab_storage_page, self.tab_storage = self._make_scrollable_settings_page(inner)
        self.tab_about_page, self.tab_about = self._make_scrollable_settings_page(inner)
        self.settings_pages = [
            self.tab_general_page,
            self.tab_login_page,
            self.tab_appearance_page,
            self.tab_blacklist_page,
            self.tab_storage_page,
            self.tab_about_page,
        ]
        self._settings_canvases = {
            page: next(
                child for child in page.winfo_children() if isinstance(child, tk.Canvas)
            )
            for page in self.settings_pages
        }
        self._build_general_tab()
        self._build_login_tab()
        self._build_appearance_tab()
        self._build_storage_tab()
        self._build_about_tab()
        for label in ("常规", "登录与验证", "外观", "本地标记", "结果与存储", "关于 / 帮助"):
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
            editor_wrap = tk.Frame(frame)
            editor_wrap.pack(fill="both", expand=True, padx=6, pady=6)
            editor = tk.Text(editor_wrap, height=6, wrap="word", font=("Microsoft YaHei UI", 9))
            editor_scroll = ttk.Scrollbar(editor_wrap, orient="vertical", command=editor.yview)
            editor.configure(yscrollcommand=editor_scroll.set)
            editor.pack(side="left", fill="both", expand=True)
            editor_scroll.pack(side="right", fill="y")
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
        for page, body in (
            (self.tab_general_page, self.tab_general),
            (self.tab_login_page, self.tab_login),
            (self.tab_appearance_page, self.tab_appearance),
            (self.tab_blacklist_page, self.tab_blacklist),
            (self.tab_storage_page, self.tab_storage),
            (self.tab_about_page, self.tab_about),
        ):
            self._bind_mousewheel_tree(body, self._settings_canvases[page])


    def _build_login_tab(self) -> None:
        box = tk.Frame(self.tab_login, bg="#eef1f5", padx=14, pady=10)
        box.pack(fill="both", expand=True)

        login_box = ttk.LabelFrame(box, text=" 登录信息 ")
        login_box.pack(fill="x", pady=(0, 6))
        self.webview_status_var = tk.StringVar(value="")
        tk.Label(
            login_box,
            textvariable=self.webview_status_var,
            justify="left",
            anchor="w",
            bg="#eef1f5",
            fg="#334155",
            font=("Microsoft YaHei UI", 9),
            wraplength=720,
        ).pack(fill="x", padx=8, pady=(6, 4))
        mode_row = tk.Frame(login_box, bg="#eef1f5")
        mode_row.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(mode_row, text="当前模式：", bg="#eef1f5", fg="#475569").pack(side="left")
        ttk.Radiobutton(
            mode_row,
            text="游客模式",
            value="guest",
            variable=self.mode_var,
            command=self._on_settings_mode_selected,
        ).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(
            mode_row,
            text="登录模式",
            value="login",
            variable=self.mode_var,
            command=self._on_settings_mode_selected,
        ).pack(side="left")

        button_row = tk.Frame(login_box, bg="#eef1f5")
        button_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(
            button_row,
            text="去抓取页管理登录",
            command=self._go_manage_login,
            width=18,
        ).pack(side="left")

        self.webview_remember_var = tk.BooleanVar(
            value=bool(self.settings.get("webview_remember_login", False))
        )
        ttk.Checkbutton(
            login_box,
            text="登录后记住内置登录（本机，高风险：会保存登录态）",
            variable=self.webview_remember_var,
            command=self._on_webview_remember_changed,
        ).pack(anchor="w", padx=8, pady=(2, 0))
        tk.Label(
            login_box,
            text="只影响本软件的 WebView2，不影响系统浏览器；共享电脑不要开启。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=28, pady=(0, 6))

        internal_box = ttk.LabelFrame(box, text=" 内置登录（WebView2） ")
        internal_box.pack(fill="x", pady=(0, 6))
        self.webview_clear_btn = ttk.Button(
            internal_box,
            text="清除 WebView2 保存的登录",
            command=self._clear_internal_login,
            width=26,
        )
        self.webview_clear_btn.pack(anchor="w", padx=8, pady=(6, 4))
        tk.Label(
            internal_box,
            text="只清除本软件 WebView2 的百度登录态；不影响系统浏览器。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=8, pady=(0, 6))

        enhance_box = ttk.LabelFrame(box, text=" 关注检测（可选） ")
        enhance_box.pack(fill="x", pady=(0, 6))
        self.follow_enhance_var = tk.BooleanVar(value=bool(self.settings.get("follow_enhance", False)))
        self.follow_enhance_check = ttk.Checkbutton(
            enhance_box,
            text="启用公开关注 / 隐藏关注检测（高风险）",
            variable=self.follow_enhance_var,
            command=self._on_follow_toggle,
        )
        self.follow_enhance_check.pack(anchor="w", padx=8, pady=(6, 0))
        self.follow_enhance_status = tk.Label(
            enhance_box,
            text="需要登录信息",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        )
        self.follow_enhance_status.pack(anchor="w", padx=28, pady=(2, 0))
        mode_row = tk.Frame(enhance_box, bg="#eef1f5")
        mode_row.pack(anchor="w", padx=8, pady=(4, 6))
        self.follow_load_row = mode_row
        tk.Label(mode_row, text="关注加载：", bg="#eef1f5", fg="#475569").pack(side="left")
        self.follow_load_mode_var = tk.StringVar(
            value="手动" if self.settings.get("follow_load_mode") == "manual" else "自动"
        )
        self.follow_load_box = ttk.Combobox(
            mode_row,
            values=("自动", "手动"),
            textvariable=self.follow_load_mode_var,
            width=6,
            state="readonly",
        )
        self.follow_load_box.pack(side="left")
        self.follow_load_mode_var.trace_add("write", lambda *_: self._on_follow_load_mode_changed())

        note_box = ttk.LabelFrame(box, text=" 说明 ")
        note_box.pack(fill="x", pady=(0, 6))
        self.follow_note_box = note_box
        tk.Label(
            note_box,
            text="游客的匿名 Cookie 只在内存中，不写入本机。\n"
            "登录模式开启“记住内置登录”后，WebView2 登录态才会写入本机独立目录。\n"
            "关注检测需要登录信息；仅 BDUSS 可能不足以获取关注列表。",
            justify="left",
            anchor="w",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 8),
            wraplength=720,
        ).pack(fill="x", padx=8, pady=6)
        self.mode_var.trace_add("write", lambda *_: self._refresh_webview_status())
        self._refresh_webview_status()


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
        self.accent_combo.configure(postcommand=self._prepare_accent_popup)
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


    def _build_storage_tab(self) -> None:
        box = tk.Frame(self.tab_storage, bg="#eef1f5", padx=14, pady=10)
        box.pack(fill="both", expand=True)

        save_box = ttk.LabelFrame(box, text=" 最近结果 ")
        save_box.pack(fill="x", pady=(0, 6))
        self.save_result_var = tk.BooleanVar(value=bool(self.settings.get("save_result", True)))
        ttk.Checkbutton(
            save_box,
            text="保存最近结果",
            variable=self.save_result_var,
            command=self._on_save_result_toggle,
        ).pack(anchor="w", padx=8, pady=(4, 0))
        self.encrypt_var = tk.BooleanVar(value=bool(self.settings.get("encrypt_result", False)))
        self.encrypt_check = ttk.Checkbutton(
            save_box,
            text="加密保存结果（DPAPI，仅当前 Windows 用户可读）",
            variable=self.encrypt_var,
            command=self._on_encrypt_toggle,
        )
        self.encrypt_check.pack(anchor="w", padx=8, pady=(2, 0))
        row = tk.Frame(save_box, bg="#eef1f5")
        row.pack(anchor="w", fill="x", padx=8, pady=(4, 2))
        self.save_restore_row = row
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
        result_buttons = tk.Frame(save_box, bg="#eef1f5")
        result_buttons.pack(fill="x", padx=8, pady=(2, 4))
        self.old_result_buttons = result_buttons
        ttk.Button(result_buttons, text="删除当前结果", command=self._clear_result, width=14).pack(side="left")
        ttk.Button(
            result_buttons, text="清理旧版本结果", command=self._cleanup_old_results, width=14
        ).pack(side="left", padx=(6, 0))
        self.old_files_label = tk.Label(
            result_buttons, text="", bg="#eef1f5", fg="#8a94a6", font=("Microsoft YaHei UI", 8)
        )
        self.old_files_label.pack(side="left", padx=(10, 0))
        self._refresh_old_files_label()

        log_box = ttk.LabelFrame(box, text=" 运行日志 ")
        log_box.pack(fill="x", pady=(0, 6))
        self.log_box = log_box
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
        ).pack(anchor="w", padx=8, pady=(2, 2))
        log_buttons = tk.Frame(log_box, bg="#eef1f5")
        log_buttons.pack(fill="x", padx=8, pady=(0, 2))
        ttk.Button(log_buttons, text="查看日志", command=self._view_logs, width=10).pack(side="left")
        ttk.Button(
            log_buttons, text="打开日志目录", command=self._open_logs_dir, width=12
        ).pack(side="left", padx=(6, 0))
        ttk.Button(log_buttons, text="删除日志", command=self._delete_logs, width=10).pack(
            side="left", padx=(6, 0)
        )
        self.log_summary_label = tk.Label(
            log_box, text="", bg="#eef1f5", fg="#8a94a6", font=("Microsoft YaHei UI", 8), anchor="w"
        )
        self.log_summary_label.pack(fill="x", padx=8, pady=(0, 4))
        self._refresh_log_summary()

        cache_box = ttk.LabelFrame(box, text=" 发言缓存 ")
        cache_box.pack(fill="x", pady=(0, 6))
        self.cache_box = cache_box
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
        )
        self.cache_limit_box.pack(side="left")
        self.cache_limit_box.bind("<Return>", lambda _event: self._commit_cache_limit())
        tk.Label(cache_row, text="MB", bg="#eef1f5", fg="#475569").pack(side="left")
        ttk.Button(cache_row, text="应用上限", command=self._commit_cache_limit, width=9).pack(
            side="left", padx=(6, 0)
        )
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

        maint_box = ttk.LabelFrame(box, text=" 数据位置 ")
        maint_box.pack(fill="x", pady=(0, 6))
        data_row = tk.Frame(maint_box, bg="#eef1f5")
        data_row.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(
            data_row,
            text=f"应用数据：{APP_DIR}",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            data_row, text="打开数据目录", command=lambda: self._open_folder(APP_DIR), width=13
        ).pack(side="right")
        temp_row = tk.Frame(maint_box, bg="#eef1f5")
        temp_row.pack(fill="x", padx=8, pady=(2, 4))
        tk.Label(
            temp_row,
            text="临时文件：%TEMP%\\TiebaReplyStats",
            bg="#eef1f5",
            fg="#475569",
            font=("Microsoft YaHei UI", 8),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            temp_row,
            text="打开临时目录",
            command=lambda: self._open_folder(os.path.join(os.environ.get("TEMP", ""), "TiebaReplyStats")),
            width=13,
        ).pack(side="right")

        danger_box = ttk.LabelFrame(box, text=" 危险操作 ")
        danger_box.pack(fill="x")
        danger = tk.Frame(danger_box, bg="#eef1f5")
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
            danger_box,
            text="会删除结果、BDUSS、标记、设置、临时文件和日志；不会删除导出的 Excel/Markdown。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=8, pady=(0, 4))


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
        self.proxy_row = proxy_row
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
        self.batch_row = batch_row
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

        fill_box = ttk.LabelFrame(box, text=" 查用户补全主题 ")
        fill_box.pack(fill="x", pady=(0, 6))
        self.lookup_fill_box = fill_box
        self.lookup_fill_var = tk.BooleanVar(value=bool(self.settings.get("lookup_fill_threads", False)))
        ttk.Checkbutton(
            fill_box,
            text="查用户时回抓 feed 主题（慢，默认关闭）",
            variable=self.lookup_fill_var,
            command=self._on_lookup_fill_changed,
        ).pack(anchor="w", padx=8, pady=(4, 0))
        fill_row = tk.Frame(fill_box, bg="#eef1f5")
        fill_row.pack(anchor="w", fill="x", padx=8, pady=(4, 0))
        tk.Label(fill_row, text="每主题页数：", bg="#eef1f5", fg="#475569").pack(side="left")
        self.lookup_fill_pages_var = tk.StringVar(
            value="完整主题" if self.settings.get("lookup_fill_pages") == "full" else "第 1 页"
        )
        self.lookup_fill_pages_box = ttk.Combobox(
            fill_row, values=("第 1 页", "完整主题"), textvariable=self.lookup_fill_pages_var, width=8, state="readonly"
        )
        self.lookup_fill_pages_box.pack(side="left")
        self.lookup_fill_pages_box.bind("<<ComboboxSelected>>", lambda _event: self._on_lookup_fill_changed())
        tk.Label(fill_row, text="  最多补主题数：", bg="#eef1f5", fg="#475569").pack(side="left")
        self.lookup_fill_limit_var = tk.StringVar(value=str(self.settings.get("lookup_fill_limit", 50)))
        self.lookup_fill_limit_box = ttk.Spinbox(
            fill_row, from_=1, to=10000, increment=10, width=7, textvariable=self.lookup_fill_limit_var, state="normal"
        )
        self.lookup_fill_limit_box.pack(side="left")
        self.lookup_fill_limit_box.bind("<FocusOut>", lambda _event: self._on_lookup_fill_changed())
        self.lookup_fill_comments_var = tk.BooleanVar(value=bool(self.settings.get("lookup_fill_comments", False)))
        ttk.Checkbutton(
            fill_row,
            text="楼层 + 楼中楼",
            variable=self.lookup_fill_comments_var,
            command=self._on_lookup_fill_changed,
        ).pack(side="left", padx=(8, 0))
        fill_all_row = tk.Frame(fill_box, bg="#eef1f5")
        fill_all_row.pack(anchor="w", fill="x", padx=8, pady=(4, 4))
        self.lookup_fill_all_var = tk.BooleanVar(value=bool(self.settings.get("lookup_fill_all", False)))
        ttk.Checkbutton(
            fill_all_row,
            text="补全所有 feed 主题（特慢，完整主题、不限数量）",
            variable=self.lookup_fill_all_var,
            command=self._on_lookup_fill_changed,
        ).pack(anchor="w")
        tk.Label(
            fill_all_row,
            text="默认只补第 1 页、最多 50 个主题；勾选后可能耗时几分钟。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=20)

        level_box = ttk.LabelFrame(box, text=" 恋文等级补充（第三方，实验性） ")
        level_box.pack(fill="x", pady=(0, 6))
        self.love_level_var = tk.BooleanVar(value=bool(self.settings.get("love_level_enabled", False)))
        ttk.Checkbutton(
            level_box,
            text="用恋文补充已知贴吧等级（默认关闭）",
            variable=self.love_level_var,
            command=self._on_love_level_changed,
        ).pack(anchor="w", padx=8, pady=(4, 0))
        tk.Label(
            level_box,
            text="只查已知吧；第三方等级可能滞后或不准确；需要贴吧ID或用户名。",
            bg="#eef1f5",
            fg="#8a94a6",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", padx=20, pady=(2, 4))

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
        for block in (risk_box, color_box, fetch_box, ui_box, default_box, backup_box):
            block.pack_forget()
        for block in (risk_box, color_box, fetch_box, ui_box, default_box, backup_box):
            block.pack(fill="x", pady=(0, 6), before=self.general_hint)

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
            text="作者：OK · GitHub：Goto-OK",
            bg="#eef1f5",
            fg="#64748b",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(2, 2))
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

