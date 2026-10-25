from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from tieba_reply_stats.settings import save_settings
from tieba_reply_stats.theme import map_color, resolve_palette


class ThemeMixin:
    """主题应用方法，从 App 拆出。"""

    palette: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def _on_theme_changed(self) -> None:
        mode = {"浅色": "light", "深色": "dark", "跟随系统": "system"}.get(
            self.theme_mode_var.get(), "light"
        )
        self.settings["theme_mode"] = mode
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
                # 只更新备用颜色，不能因为切主题就把无结果的查用户红绿灯点亮。
                self.lookup_traffic_labels[key] = (entry[0], palette[value])
        if getattr(self, "_last_lookup_profile", None):
            self._render_lookup(self._last_lookup_profile)
        else:
            self._reset_lookup_traffic()

