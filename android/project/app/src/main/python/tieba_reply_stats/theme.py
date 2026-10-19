"""S1 外观：浅色/深色/跟随系统 + 强调色。"""

from __future__ import annotations

import os
from typing import Dict

LIGHT: Dict[str, str] = {
    "window_bg": "#eef1f5",
    "surface": "#ffffff",
    "surface_alt": "#f7f9fc",
    "border": "#c9d2df",
    "text": "#1f2937",
    "text_secondary": "#475569",
    "text_muted": "#8a94a6",
    "accent": "#1F4E79",
    "accent_hover": "#163b5c",
    "accent_text": "#ffffff",
    "selection_bg": "#dbeafe",
    "selection_text": "#1F4E79",
    "table_bg": "#ffffff",
    "table_alt": "#f7f9fc",
    "table_header_bg": "#1F4E79",
    "table_header_text": "#ffffff",
    "log_bg": "#fbfcfe",
    "log_text": "#1f2937",
    "danger": "#b91c1c",
    "danger_bg": "#ffdede",
    "warning": "#b45309",
    "warning_bg": "#fff4cc",
    "safe": "#15803d",
    "safe_bg": "#e3f6e3",
    "button_bg": "#e5e9f0",
    "button_hover": "#d5dbe5",
    "button_text": "#334155",
    "disabled_bg": "#eef1f5",
    "disabled_text": "#9aa7b8",
    "banner_bg": "#fff7e6",
    "banner_text": "#7c4a03",
}

DARK: Dict[str, str] = {
    "window_bg": "#15171c",
    "surface": "#1d2027",
    "surface_alt": "#22262f",
    "border": "#343a46",
    "text": "#e6e8ee",
    "text_secondary": "#b3b9c6",
    "text_muted": "#8a92a3",
    "accent": "#3B82F6",
    "accent_hover": "#2563EB",
    "accent_text": "#ffffff",
    "selection_bg": "#243652",
    "selection_text": "#e6e8ee",
    "table_bg": "#1d2027",
    "table_alt": "#22262f",
    "table_header_bg": "#263244",
    "table_header_text": "#e6e8ee",
    "log_bg": "#15171c",
    "log_text": "#d1d5db",
    "danger": "#f87171",
    "danger_bg": "#3a1d1d",
    "warning": "#fbbf24",
    "warning_bg": "#3a2e12",
    "safe": "#4ade80",
    "safe_bg": "#16301f",
    "button_bg": "#2a2f3a",
    "button_hover": "#343b49",
    "button_text": "#e6e8ee",
    "disabled_bg": "#22262f",
    "disabled_text": "#6b7280",
    "banner_bg": "#3a2e12",
    "banner_text": "#fbbf24",
}

BLUEFISH: Dict[str, str] = {
    "window_bg": "#071426",
    "surface": "#0b1f38",
    "surface_alt": "#0e2947",
    "border": "#1b4b73",
    "text": "#d9f3ff",
    "text_secondary": "#9fd4ee",
    "text_muted": "#6aa3c2",
    "accent": "#38bdf8",
    "accent_hover": "#0ea5e9",
    "accent_text": "#04121f",
    "selection_bg": "#123f5e",
    "selection_text": "#e6fbff",
    "table_bg": "#0b1f38",
    "table_alt": "#0e2947",
    "table_header_bg": "#0b2c4a",
    "table_header_text": "#d9f3ff",
    "log_bg": "#071426",
    "log_text": "#c7e9f7",
    "danger": "#fb7185",
    "danger_bg": "#3b1522",
    "warning": "#fbbf24",
    "warning_bg": "#3a2e12",
    "safe": "#34d399",
    "safe_bg": "#0f332a",
    "button_bg": "#103552",
    "button_hover": "#174a70",
    "button_text": "#d9f3ff",
    "disabled_bg": "#0b1f38",
    "disabled_text": "#5c7f96",
    "banner_bg": "#0a2038",
    "banner_text": "#a5f3fc",
}

SKINS = ("default", "bluefish")

ACCENTS = {
    "blue": {"accent": "#1F4E79", "accent_hover": "#163b5c", "selection_bg": "#dbeafe", "selection_text": "#1F4E79"},
    "green": {"accent": "#166534", "accent_hover": "#14532d", "selection_bg": "#dcfce7", "selection_text": "#166534"},
    "purple": {"accent": "#6D28D9", "accent_hover": "#5B21B6", "selection_bg": "#ede9fe", "selection_text": "#5B21B6"},
}

DARK_ACCENTS = {
    "blue": {"accent": "#3B82F6", "accent_hover": "#2563EB", "selection_bg": "#243652", "selection_text": "#e6e8ee"},
    "green": {"accent": "#22C55E", "accent_hover": "#16A34A", "selection_bg": "#173a26", "selection_text": "#e6e8ee"},
    "purple": {"accent": "#A78BFA", "accent_hover": "#8B5CF6", "selection_bg": "#2e2547", "selection_text": "#e6e8ee"},
}

THEME_MODES = ("light", "dark", "system")
ACCENT_KEYS = ("blue", "green", "purple")


def detect_system_theme() -> str:
    if os.name != "nt":
        return "light"
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        finally:
            key.Close()
        return "light" if int(value) else "dark"
    except Exception:  # noqa: BLE001
        return "light"


def resolve_palette(theme_mode: str, accent: str, skin: str = "default") -> Dict[str, str]:
    if skin == "bluefish":
        return dict(BLUEFISH)
    mode = theme_mode if theme_mode in THEME_MODES else "light"
    if mode == "system":
        mode = detect_system_theme()
    palette = dict(DARK if mode == "dark" else LIGHT)
    accents = DARK_ACCENTS if mode == "dark" else ACCENTS
    palette.update(accents.get(accent, accents["blue"]))
    return palette


# 旧界面里写死的颜色 → 主题令牌。按“背景/前景”分别映射，避免白色文字被误映射。
_BG_MAP = {
    "#eef1f5": "window_bg",
    "#ffffff": "surface",
    "#fbfcfe": "log_bg",
    "#f7f9fc": "table_alt",
    "#f5f7fa": "window_bg",
    "#f8fafc": "surface_alt",
    "#e5e9f0": "button_bg",
    "#d5dbe5": "button_hover",
    "#dbeafe": "selection_bg",
    "#e2e8f0": "border",
    "#c9d2df": "border",
    "#9aa7b8": "disabled_text",
    "#fff7e6": "banner_bg",
    "#fee2e2": "danger_bg",
    "#fecaca": "danger_bg",
    "#ffdede": "danger_bg",
    "#fff4cc": "warning_bg",
    "#dcfce7": "safe_bg",
    "#e3f6e3": "safe_bg",
    "#f1f5f9": "surface_alt",
    "#e8eef7": "selection_bg",
}

_FG_MAP = {
    "#1f2937": "text",
    "#334155": "text",
    "#475569": "text_secondary",
    "#6b7280": "text_muted",
    "#64748b": "text_muted",
    "#8a94a6": "text_muted",
    "#1F4E79": "accent",
    "#163b5c": "accent_hover",
    "#2E75B6": "accent_hover",
    "#ffffff": "accent_text",
    "#7c4a03": "banner_text",
    "#b45309": "warning",
    "#b91c1c": "danger",
    "#991b1b": "danger",
    "#dc2626": "danger",
    "#f59e0b": "warning",
    "#16a34a": "safe",
    "#15803d": "safe",
    "#d1d5db": "disabled_text",
}

_BG_OPTIONS = {"bg", "background", "activebackground", "selectbackground", "troughcolor", "highlightbackground"}
_FG_OPTIONS = {"fg", "foreground", "activeforeground", "selectforeground", "insertbackground", "disabledforeground"}


_TOKEN_VALUES: Dict[str, str] = {}
for _palette in (LIGHT, DARK, BLUEFISH):
    for _name, _value in _palette.items():
        if _value.lower() in ("#ffffff", "#f7f9fc"):
            continue
        _TOKEN_VALUES.setdefault(_value.lower(), _name)
for _accents in (ACCENTS, DARK_ACCENTS):
    for _name, _values in _accents.items():
        for _token, _value in _values.items():
            if _value.lower() != "#ffffff":
                _TOKEN_VALUES.setdefault(_value.lower(), _token)


def _preferred_token(option: str, key: str) -> str:
    if key == "#ffffff":
        return "accent_text" if option.lower() in _FG_OPTIONS else "surface"
    if key == "#f7f9fc":
        return "table_alt"
    if key in ("#fbfcfe", "#f5f7fa", "#f8fafc", "#f1f5f9"):
        return "surface_alt"
    return _TOKEN_VALUES.get(key, "")


def map_color(option: str, value: str, palette: Dict[str, str]) -> str:
    if not isinstance(value, str):
        return value
    key = value.strip().lower()
    token = _preferred_token(option, key)
    if token and token in palette:
        return palette[token]
    if option.lower() in _BG_OPTIONS and key in _BG_MAP:
        return palette.get(_BG_MAP[key], value)
    if option.lower() in _FG_OPTIONS and key in _FG_MAP:
        return palette.get(_FG_MAP[key], value)
    return value
