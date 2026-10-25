"""表格/网格页 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from functools import partial
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from tieba_gui_utils import display_text
from tieba_reply_stats.settings import save_settings


class GridMixin:
    """表格/网格页方法，从 App 拆出。"""

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

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


    def _refresh_grid(self) -> None:
        for tab in list(self.grid_nb.tabs()):
            self.grid_nb.forget(tab)
        self._update_grid_selector()
        if not self.last_threads:
            self.grid_hint.configure(text="还没有数据")
            return
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
            headers = ["#", "昵称", "用户名", "贴吧ID", "用户ID", "等级", "头衔", "参与帖子", "楼层", "楼中楼", "合计"]
            user_rows = [
                [
                    index,
                    self._display_name(item),
                    display_text(item["username"]),
                    self._tieba_uid_cell(item),
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
            headers = ["#", "昵称", "用户名", "贴吧ID", "用户ID", "等级", "头衔", "楼层", "楼中楼", "合计"]
            user_rows = [
                [
                    index,
                    self._display_name(item),
                    display_text(item["username"]),
                    self._tieba_uid_cell(item),
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
                            self._tieba_uid_cell(item),
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
                ["帖子", "昵称", "用户名", "贴吧ID", "用户ID", "等级", "头衔", "楼层", "楼中楼", "合计"],
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
                        self._tieba_uid_obj_cell(floor),
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
                        self._tieba_uid_obj_cell(comment),
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
            "贴吧ID",
            "用户ID",
            "等级",
            "头衔",
            "内容",
        ]
        comment_headers = (["帖子"] if all_mode else []) + [
            "所在楼层",
            "回复者",
            "用户名",
            "贴吧ID",
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
            ("复制贴吧ID", next((i for i, h in enumerate(headers) if h == "贴吧ID"), -1)),
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

            paired = list(
                zip(
                    all_rows,
                    all_urls + [""] * max(0, len(all_rows) - len(all_urls)),
                    strict=False,
                )
            )
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

        for index, _header in enumerate(headers):
            tree.heading(columns[index], command=make_command(index))
        if default_sort in headers:
            apply_sort(columns[headers.index(default_sort)], default_reverse)
        else:
            render()

