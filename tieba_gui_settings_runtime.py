"""设置页运行时 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, List

from tieba_reply_stats.blacklist import save_blacklist
from tieba_reply_stats.config_backup import preview as backup_preview
from tieba_reply_stats.config_backup import read_backup, write_backup
from tieba_reply_stats.errors import friendly_error
from tieba_reply_stats.fetch import parse_cookie_input
from tieba_reply_stats.post_cache import DEFAULT_LIMIT_MB, MAX_LIMIT_MB, MIN_LIMIT_MB
from tieba_reply_stats.post_cache import cache as post_cache
from tieba_reply_stats.settings import save_settings


class SettingsRuntimeMixin:
    """设置页运行时逻辑，从 App 拆出。"""

    blacklist: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)



    def _make_scrollable_settings_page(self, parent) -> tuple:
        outer = tk.Frame(parent, bg="#eef1f5")
        canvas = tk.Canvas(outer, bg="#eef1f5", highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg="#eef1f5")
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )

        def on_wheel(event) -> None:
            first, last = canvas.yview()
            if event.delta > 0 and first <= 0.0:
                return
            if event.delta < 0 and last >= 1.0:
                return
            canvas.yview_scroll(int(-event.delta / 120), "units")

        canvas.bind("<MouseWheel>", on_wheel)
        body.bind("<MouseWheel>", on_wheel)
        return outer, body


    def _show_settings_page(self, index: int) -> None:
        for position, page in enumerate(self.settings_pages):
            if position == index:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        self._set_cache_stats_timer(index == 4)


    def _on_settings_start_changed(self) -> None:
        self.settings["settings_start"] = "last" if self.settings_start_var.get() == "上次分类" else "general"
        save_settings(self.settings)


    def _on_settings_nav(self, _event=None) -> None:
        selection = self.settings_nav.curselection()
        if selection:
            self._last_settings_index = selection[0]
            self._show_settings_page(selection[0])


    def _on_settings_mode_selected(self) -> None:
        mode = self.mode_var.get()
        if mode == "guest" and bool(self.settings.get("follow_enhance", False)):
            if not messagebox.askyesno(
                "切换到游客模式",
                "游客模式不使用关注检测。\n切换会关闭关注检测，是否继续？",
                parent=self.root,
                default=messagebox.NO,
            ):
                self.mode_var.set("login")
                return
            self.settings["follow_enhance"] = False
            if hasattr(self, "follow_enhance_var"):
                self.follow_enhance_var.set(False)
            save_settings(self.settings)
        self._set_mode(mode)
        self._refresh_webview_status()


    def _commit_cache_limit(self) -> None:
        now = time.monotonic()
        if getattr(self, "_cache_limit_busy", False) or now < getattr(
            self, "_cache_limit_guard_until", 0
        ):
            current = str(int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB)))
            try:
                if self.cache_limit_var.get() != current:
                    self.cache_limit_var.set(current)
            except tk.TclError:
                pass
            return
        self._cache_limit_busy = True
        box = getattr(self, "cache_limit_box", None)
        try:
            if box is not None:
                box.configure(state="disabled")
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
        finally:
            if box is not None:
                try:
                    box.configure(state="normal")
                except tk.TclError:
                    pass
            self._cache_limit_busy = False
            self._cache_limit_guard_until = time.monotonic() + 0.35




    def _hidden_advanced_settings(self) -> List[str]:
        names: List[str] = []
        if str(self.settings.get("follow_load_mode") or "auto") == "manual":
            names.append("关注加载：手动")
        strategy = str(self.settings.get("identity_strategy") or "full")
        labels = {
            "ask": "身份策略：询问",
            "skip": "身份策略：跳过",
            "user_id": "身份策略：只补用户ID",
            "detail": "身份策略：详情再补",
        }
        if strategy in labels:
            names.append(labels[strategy])
        try:
            concurrency = int(self.settings.get("identity_concurrency", 3))
        except (TypeError, ValueError):
            concurrency = 3
        if concurrency != 3:
            names.append(f"身份并发 {concurrency}")
        try:
            batch = int(self.settings.get("batch_concurrency", 1))
        except (TypeError, ValueError):
            batch = 1
        if batch > 1:
            names.append(f"红绿灯并发 {batch}")
        if str(self.settings.get("proxy_mode") or "system") == "custom":
            names.append("自定义代理")
        if bool(self.settings.get("lookup_fill_threads")):
            names.append("查用户回抓主题")
        if bool(self.settings.get("log_enabled")):
            names.append("运行日志")
        if bool(self.settings.get("encrypt_result")):
            names.append("结果加密")
        try:
            cache_mb = int(self.settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB))
        except (TypeError, ValueError):
            cache_mb = DEFAULT_LIMIT_MB
        if cache_mb != DEFAULT_LIMIT_MB:
            names.append(f"缓存上限 {cache_mb} MB")
        try:
            comment_concurrency = int(self.comment_concurrency_var.get() or 1)
        except (TypeError, ValueError):
            comment_concurrency = 1
        if comment_concurrency > 1:
            names.append(f"楼中楼并发 {comment_concurrency}")
        try:
            delay = float(self.delay_var.get() or 0.8)
        except (TypeError, ValueError):
            delay = 0.8
        if abs(delay - 0.8) > 0.001:
            names.append(f"请求间隔 {delay:g} 秒")
        if str(self.comment_depth_var.get() or "全部") != "全部":
            names.append(f"楼中楼：{self.comment_depth_var.get()}")
        return names


    def _refresh_advanced_summary(self) -> None:
        if not hasattr(self, "ui_mode_var"):
            return
        simple = self.ui_mode_var.get() != "advanced"
        names = self._hidden_advanced_settings() if simple else []
        if not simple or not names:
            self.fetch_advanced_summary.pack_forget()
            self.fetch_advanced_summary.unbind("<Button-1>")
            self.ui_mode_hint.configure(
                text="简洁模式隐藏调参和高风险操作", cursor=""
            )
            self.ui_mode_hint.unbind("<Button-1>")
            return
        shown = "、".join(names[:2])
        if len(names) > 2:
            shown += f" 等 {len(names)} 项"
        text = f"高级设置生效中：{shown}  [管理]"
        self.fetch_advanced_summary.configure(text=text)
        self.fetch_advanced_summary.pack(
            fill="x", padx=8, pady=(4, 0), before=self.fetch_page
        )
        self.fetch_advanced_summary.configure(cursor="hand2")
        self.fetch_advanced_summary.bind(
            "<Button-1>", lambda _event: self._manage_advanced_settings()
        )
        self.ui_mode_hint.configure(text=text, cursor="hand2")
        self.ui_mode_hint.bind(
            "<Button-1>", lambda _event: self._manage_advanced_settings()
        )


    def _manage_advanced_settings(self) -> None:
        if self.ui_mode_var.get() == "advanced":
            self.notebook.select(self.tab_settings)
            return
        if not messagebox.askyesno(
            "开启高级模式",
            "高级模式会显示更多选项和高风险操作。\n不会自动改变现有设置。\n\n继续？",
            parent=self.root,
            default=messagebox.NO,
        ):
            return
        self.ui_mode_var.set("advanced")
        self._apply_ui_mode()


    def _reset_hidden_behavior_settings(self) -> None:
        self.follow_load_mode_var.set("自动")
        self.identity_strategy_var.set("补全用户ID + 贴吧ID")
        self.identity_timing_var.set(False)
        self.identity_concurrency_var.set("3")
        self.batch_concurrency_var.set("1")
        self.proxy_mode_var.set("跟随系统")
        self.proxy_url_var.set("")
        self.lookup_fill_var.set(False)
        self.lookup_fill_all_var.set(False)
        self.comment_concurrency_var.set("1")
        self.delay_var.set("0.8")
        self.comment_depth_var.set("全部")
        self.settings.update(
            {
                "follow_load_mode": "auto",
                "identity_strategy": "full",
                "identity_timing": False,
                "identity_concurrency": 3,
                "batch_concurrency": 1,
                "proxy_mode": "system",
                "proxy_url": "",
                "lookup_fill_threads": False,
                "lookup_fill_all": False,
            }
        )
        save_settings(self.settings)


    def _apply_ui_mode(self, persist: bool = True) -> None:
        simple = self.ui_mode_var.get() != "advanced"
        self.settings["ui_mode"] = "simple" if simple else "advanced"
        if persist:
            save_settings(self.settings)
        self._capture_ui_pack_state()
        pack_widgets = getattr(self, "_ui_pack_widgets", [])

        if simple:
            self.identity_row.grid_remove()
            self.delay_row.grid_remove()
            for widget in pack_widgets:
                widget.pack_forget()
        else:
            self.identity_row.grid()
            self.delay_row.grid()
            self._restore_ui_pack_widgets()
        self._refresh_advanced_summary()


    def _on_ui_mode_selected(self) -> None:
        target = self.ui_mode_var.get()
        current = "advanced" if self.settings.get("ui_mode") == "advanced" else "simple"
        if target == current:
            return
        if target == "advanced":
            if not messagebox.askyesno(
                "开启高级模式",
                "高级模式会显示更多选项和高风险操作。\n不会自动改变现有设置。\n\n继续？",
                parent=self.root,
                default=messagebox.NO,
            ):
                self.ui_mode_var.set(current)
                return
            self._apply_ui_mode()
            return

        names = self._hidden_advanced_settings()
        if names:
            detail = "\n".join(f"- {name}" for name in names)
            choice = self._ask_choice(
                "切回简洁模式",
                "以下高级设置仍在生效：\n\n"
                + detail
                + "\n\n切回简洁模式不会自动关闭它们。",
                [
                    ("保留设置并切换", "keep"),
                    ("关闭行为类设置并切换", "close"),
                    ("取消", "cancel"),
                ],
                default=0,
            )
            if not choice or choice == "cancel":
                self.ui_mode_var.set(current)
                return
            if choice == "close":
                self._reset_hidden_behavior_settings()
        self._apply_ui_mode()


    def _apply_settings_to_ui(self, reset_mode: bool = True) -> None:
        settings = self.settings
        if hasattr(self, "risk_var"):
            self.risk_var.set(bool(settings.get("risk_enabled", True)))
        if hasattr(self, "follow_enhance_var"):
            self.follow_enhance_var.set(bool(settings.get("follow_enhance", False)))
        if hasattr(self, "follow_load_mode_var"):
            self.follow_load_mode_var.set(
                "手动" if settings.get("follow_load_mode") == "manual" else "自动"
            )
        if hasattr(self, "webview_remember_var"):
            self.webview_remember_var.set(bool(settings.get("webview_remember_login", False)))
        if hasattr(self, "_refresh_webview_status"):
            self._refresh_webview_status()
        if hasattr(self, "auto_refresh_var"):
            self.auto_refresh_var.set(bool(settings.get("auto_refresh_old", False)))
        if hasattr(self, "identity_strategy_var"):
            self.identity_strategy_var.set(
                {
                    "full": "补全用户ID + 贴吧ID",
                    "ask": "每次询问",
                    "skip": "跳过补全",
                    "user_id": "只补用户ID",
                    "detail": "详情再补",
                }.get(str(settings.get("identity_strategy", "full")), "补全用户ID + 贴吧ID")
            )
            self.identity_timing_var.set(bool(settings.get("identity_timing", True)))
            self.identity_concurrency_var.set(str(settings.get("identity_concurrency", 3)))
        if hasattr(self, "lookup_fill_var"):
            self.lookup_fill_var.set(bool(settings.get("lookup_fill_threads", False)))
            self.lookup_fill_pages_var.set(
                "完整主题" if settings.get("lookup_fill_pages") == "full" else "第 1 页"
            )
            self.lookup_fill_limit_var.set(str(settings.get("lookup_fill_limit", 50)))
            self.lookup_fill_all_var.set(bool(settings.get("lookup_fill_all", False)))
            self.lookup_fill_comments_var.set(bool(settings.get("lookup_fill_comments", False)))
            all_topics = bool(settings.get("lookup_fill_all", False))
            try:
                self.lookup_fill_pages_box.configure(state="disabled" if all_topics else "readonly")
                self.lookup_fill_limit_box.configure(state="disabled" if all_topics else "normal")
            except tk.TclError:
                pass
        if hasattr(self, "love_level_var"):
            self.love_level_var.set(bool(settings.get("love_level_enabled", False)))
        if hasattr(self, "removed_action_var"):
            self.removed_action_var.set(
                {"keep": "保留旧结果", "remove": "移除旧结果", "ask": "每次询问"}.get(
                    settings.get("removed_thread_action", "keep"), "保留旧结果"
                )
            )
        if hasattr(self, "proxy_mode_var"):
            self.proxy_mode_var.set(
                {"system": "跟随系统", "none": "不使用", "custom": "自定义"}.get(
                    settings.get("proxy_mode", "system"), "跟随系统"
                )
            )
        if hasattr(self, "proxy_url_var"):
            self.proxy_url_var.set(str(settings.get("proxy_url") or ""))
        if hasattr(self, "batch_concurrency_var"):
            self.batch_concurrency_var.set(str(settings.get("batch_concurrency", 1)))
        if hasattr(self, "settings_start_var"):
            self.settings_start_var.set(
                "上次分类" if settings.get("settings_start") == "last" else "常规"
            )
        if hasattr(self, "theme_mode_var"):
            self.theme_mode_var.set(
                {"light": "浅色", "dark": "深色", "system": "跟随系统"}.get(
                    settings.get("theme_mode", "light"), "浅色"
                )
            )
        if hasattr(self, "accent_var"):
            self.accent_var.set(
                {
                    "blue": "蓝色",
                    "green": "绿色",
                    "purple": "紫色",
                    "orange": "橘黄",
                    "pink": "粉色",
                    "cyan": "青色",
                    "red": "红色",
                }.get(settings.get("accent", "blue"), "蓝色")
            )
        if hasattr(self, "table_density_var"):
            self.table_density_var.set(
                "紧凑" if settings.get("table_density") == "compact" else "舒适"
            )
        if hasattr(self, "save_result_var"):
            self.save_result_var.set(bool(settings.get("save_result", True)))
        if hasattr(self, "encrypt_var"):
            self.encrypt_var.set(bool(settings.get("encrypt_result", False)))
        if hasattr(self, "log_enabled_var"):
            self.log_enabled_var.set(bool(settings.get("log_enabled", False)))
        if hasattr(self, "restore_mode_var"):
            self.restore_mode_var.set("询问" if settings.get("restore_mode") == "ask" else "自动")
        if hasattr(self, "cache_limit_var"):
            limit = int(settings.get("post_cache_limit_mb", DEFAULT_LIMIT_MB))
            self.cache_limit_var.set(str(limit))
            post_cache().set_limit_mb(limit)
        for key, var in getattr(self, "setting_vars", {}).items():
            var.set(bool(settings.get(key, True)))
        if reset_mode:
            self._set_mode("guest")
        self._apply_risk_ui()
        self._apply_theme()
        self._apply_table_density()
        self._apply_proxy()


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
        except Exception:  # noqa: S110, BLE001
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
        self._apply_settings_to_ui(reset_mode=False)
        for key, editor in getattr(self, "blacklist_editors", {}).items():
            editor.delete("1.0", "end")
            editor.insert("1.0", chr(10).join(self.blacklist.get(key, [])))
        self._apply_mode_ui()
        self._refresh_people()
        if getattr(self, "_last_lookup_profile", None):
            self._render_lookup(self._last_lookup_profile)
        self._append_log("配置已恢复。", "ok")
        self.status_var.set("配置已恢复")


    def _configure_colors(self, tree) -> None:
        tree.tag_configure("ban", background=self.palette["danger_bg"])
        tree.tag_configure("warn", background=self.palette["warning_bg"])
        tree.tag_configure("safe", background=self.palette["safe_bg"])


