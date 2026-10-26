"""通用对话框 mixin（从 tieba_gui.py 拆出）。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict

from tieba_gui_utils import resource_dir
from tieba_reply_stats.errors import friendly_error


class DialogsMixin:
    """通用选择框与提示窗口，从 App 拆出。"""

    _active_choice_window: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

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


