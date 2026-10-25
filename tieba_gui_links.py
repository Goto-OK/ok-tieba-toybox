from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List

from tieba_reply_stats.fetch import Fetcher
from tieba_reply_stats.link_parser import parse_links


class LinksMixin:
    """链接解析页方法，从 App 拆出。"""

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _build_links_tab(self) -> None:
        page = self.tab_links
        top = tk.Frame(page, bg="#ffffff", padx=12, pady=8)
        top.pack(fill="x")
        tk.Label(
            top,
            text="每行一个帖子链接（支持主题 / 楼层 / 楼中楼）",
            bg="#ffffff",
            fg="#475569",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w")
        links_wrap = tk.Frame(top, bg="#ffffff")
        links_wrap.pack(fill="x", pady=(4, 4))
        self.links_text = tk.Text(links_wrap, height=6, wrap="none", font=("Consolas", 9))
        links_yscroll = ttk.Scrollbar(links_wrap, orient="vertical", command=self.links_text.yview)
        links_xscroll = ttk.Scrollbar(links_wrap, orient="horizontal", command=self.links_text.xview)
        self.links_text.configure(yscrollcommand=links_yscroll.set, xscrollcommand=links_xscroll.set)
        self.links_text.grid(row=0, column=0, sticky="nsew")
        links_yscroll.grid(row=0, column=1, sticky="ns")
        links_xscroll.grid(row=1, column=0, sticky="ew")
        links_wrap.rowconfigure(0, weight=1)
        links_wrap.columnconfigure(0, weight=1)
        bar = tk.Frame(top, bg="#ffffff")
        bar.pack(fill="x")
        ttk.Button(bar, text="从剪贴板导入", command=self._links_from_clipboard).pack(side="left")
        ttk.Button(bar, text="开始解析", command=self._start_links).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="停止", command=self._stop_links).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="打开选中链接", command=self._open_links_link).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="导出 Excel", command=self._export_links).pack(side="left", padx=(8, 0))
        self.links_status = tk.Label(
            bar, text="", bg="#ffffff", fg="#64748b", font=("Microsoft YaHei UI", 9)
        )
        self.links_status.pack(side="right")

        wrap = tk.Frame(page, bg="#eef1f5")
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.links_tree = ttk.Treeview(
            wrap,
            columns=("time", "type", "bar", "title", "content", "floor", "link"),
            show="headings",
            height=18,
        )
        for key, title, width in (
            ("time", "日期", 120),
            ("type", "类型", 60),
            ("bar", "贴吧", 100),
            ("title", "标题", 220),
            ("content", "内容", 300),
            ("floor", "楼层", 60),
            ("link", "链接", 260),
        ):
            self.links_tree.heading(key, text=title)
            self.links_tree.column(key, width=width, anchor="center" if key in ("time", "type", "floor") else "w")
        yscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.links_tree.yview)
        xscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.links_tree.xview)
        self.links_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.links_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self._links_urls: Dict[str, str] = {}
        self.links_tree.bind("<Double-1>", lambda _event: self._open_links_link())
        self._links_rows: List[Dict] = []
        self._links_errors: List[Dict] = []
        self._links_stop = threading.Event()
        self._links_running = False


    def _open_links_link(self) -> None:
        selection = self.links_tree.selection()
        if selection:
            url = self._links_urls.get(selection[0], "")
            if url:
                webbrowser.open(url)


    def _links_from_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return
        self.links_text.delete("1.0", "end")
        self.links_text.insert("1.0", text)


    def _stop_links(self) -> None:
        self._links_stop.set()
        self.links_status.configure(text="正在停止…")


    def _start_links(self) -> None:
        if self._links_running:
            return
        raw = self.links_text.get("1.0", "end").strip()
        if not raw:
            self.links_status.configure(text="请先粘贴链接")
            return
        self._links_running = True
        self._links_stop.clear()
        self._links_rows = []
        self._links_errors = []
        self._links_urls = {}
        for item in self.links_tree.get_children():
            self.links_tree.delete(item)
        self.links_status.configure(text="解析中…")

        def worker():
            try:
                fetcher = Fetcher(cookie={}, delay=0.3, verbose=False)
                result = parse_links(
                    raw,
                    fetcher,
                    should_stop=self._links_stop.is_set,
                )
                self._post(("links_ready", result, ""))
            except Exception as error:  # noqa: BLE001
                self._post(("links_ready", None, str(error)))

        threading.Thread(target=worker, daemon=True).start()


    def _render_links(self, result: Dict, error: str) -> None:
        self._links_running = False
        if result is None:
            self.links_status.configure(text=f"失败：{error}")
            return
        self._links_rows = list(result.get("rows") or [])
        self._links_errors = list(result.get("errors") or [])
        for index, row in enumerate(self._links_rows):
            iid = str(index)
            self.links_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    row.get("time") or "",
                    row.get("type") or "",
                    row.get("bar") or "",
                    row.get("title") or "",
                    row.get("content") or "",
                    row.get("floor") or "",
                    row.get("url") or "",
                ),
            )
            self._links_urls[iid] = row.get("url") or ""
        extra = f" / 失败 {len(self._links_errors)}" if self._links_errors else ""
        self.links_status.configure(
            text=f"链接 {result.get('links', 0)} / 主题 {result.get('threads', 0)} / 成功 {len(self._links_rows)}{extra}"
        )


    def _export_links(self) -> None:
        if not self._links_rows:
            self.links_status.configure(text="没有可导出的结果")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出链接解析",
            defaultextension=".xlsx",
            initialfile="链接解析.xlsx",
            filetypes=[("Excel 表格", "*.xlsx")],
        )
        if not path:
            return
        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = "链接解析"
            headers = ["日期", "类型", "贴吧", "标题", "内容", "楼层", "链接"]
            ws.append(headers)
            for row in self._links_rows:
                ws.append(
                    [
                        row.get("time") or "",
                        row.get("type") or "",
                        row.get("bar") or "",
                        row.get("title") or "",
                        row.get("content") or "",
                        row.get("floor") or "",
                        row.get("url") or "",
                    ]
                )
            ws2 = wb.create_sheet("说明")
            ws2.append(["链接数", len(self._links_rows) + len(self._links_errors)])
            ws2.append(["成功", len(self._links_rows)])
            ws2.append(["失败", len(self._links_errors)])
            ws2.append(["数据来源", "官方主题抓取"])
            wb.save(path)
            self.links_status.configure(text="已导出 Excel")
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("导出失败", str(error), parent=self.root)

