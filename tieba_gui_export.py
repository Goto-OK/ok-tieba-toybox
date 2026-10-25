from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Any

from tieba_gui_utils import default_output_path
from tieba_reply_stats.errors import friendly_error
from tieba_reply_stats.export import export_workbook
from tieba_reply_stats.post_cache import cache as post_cache
from tieba_reply_stats.report import export_user_posts, posts_base
from tieba_reply_stats.version import __version__ as VERSION


def display_text(value) -> str:
    return str(value or "")


class ExportMixin:
    """导出/打开结果方法，从 App 拆出。"""

    last_output: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

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
        if self._network_task_active():
            messagebox.showinfo(
                "正在处理",
                "抓取、补全或重试仍在进行，完成后才能导出。",
                parent=self.root,
            )
            return
        self._export_now_actual()


    def _export_now_actual(self) -> None:
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
        all_users = list(getattr(self, "people_users", []))
        pending_tieba = sum(
            1 for user in all_users if not user.get("tieba_uid") and (user.get("uid") or user.get("username"))
        )
        timing_enabled = bool(getattr(self, "identity_timing_var", tk.BooleanVar(value=True)).get())
        stage_times = getattr(self, "_last_stage_times", {}) if timing_enabled else {}
        manual_times = getattr(self, "_manual_timing", {}) if timing_enabled else {}
        meta = {
            "软件版本": VERSION,
            "补全策略": {
                "full": "补全用户ID + 贴吧ID",
                "ask": "每次询问",
                "skip": "跳过补全",
                "user_id": "只补用户ID",
                "detail": "详情再补",
            }.get(
                str(getattr(self, "_last_identity_strategy", self.settings.get("identity_strategy", "full"))),
                "补全用户ID + 贴吧ID",
            ),
            "补全状态": (
                "跳过"
                if str(
                    getattr(
                        self,
                        "_last_identity_strategy",
                        self.settings.get("identity_strategy", "full"),
                    )
                )
                in ("skip", "detail")
                else ("部分" if pending_tieba or getattr(self, "_tieba_uid_missing", 0) else "完成")
            ),
            "补全用户ID失败": str(int(getattr(self, "_identity_missing", 0) or 0)),
            "补全贴吧ID失败": str(int(getattr(self, "_tieba_uid_missing", 0) or 0)),
            "待补充贴吧ID用户": str(pending_tieba),
            "不完整帖子": str(
                sum(1 for thread in self.last_threads if not getattr(thread, "complete", True))
            ),
            "不完整帖子标题": "；".join(
                display_text(thread.meta.title or thread.meta.tid)
                for thread in self.last_threads
                if not getattr(thread, "complete", True)
            )
            or "无",
            "总耗时": (
                f"{float(stage_times.get('总耗时') or 0):.1f} 秒"
                if stage_times.get("总耗时")
                else "未开启"
            ),
            "手动补全耗时": (
                f"{float(manual_times.get('总耗时') or 0):.1f} 秒"
                if manual_times.get("总耗时")
                else "未开启"
            ),
            "手动补全用户ID耗时": (
                f"{float(manual_times.get('用户ID') or 0):.1f} 秒"
                if manual_times
                else "未开启"
            ),
            "手动补全贴吧ID耗时": (
                f"{float(manual_times.get('贴吧ID') or 0):.1f} 秒"
                if manual_times
                else "未开启"
            ),
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
        topics = [post for post in filtered if post.get("type") == "主题帖"]
        replies = [post for post in filtered if post.get("type") == "回复"]
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

        def coverage_text(items, label: str) -> str:
            dates = []
            unknown = 0
            for item in items:
                day = str(item.get("time") or "").strip()
                if day:
                    dates.append(day)
                else:
                    unknown += 1
            if not dates:
                return f"无{label}"
            text = f"{min(dates)} ~ {max(dates)}"
            if unknown:
                text += f"（含 {unknown} 条未知时间）"
            return text

        try:
            coverage = {
                "reply": coverage_text(replies, "回复"),
                "topic": coverage_text(topics, "主题"),
            }
            output = export_user_posts(base, user, filtered, chosen_start, chosen_end, coverage)
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("导出失败", friendly_error(error), parent=self.root)
            return
        self._append_log(f"发言已导出：{output}", "ok")
        messagebox.showinfo("导出完成", "已生成：" + chr(10) + output, parent=self.root)

