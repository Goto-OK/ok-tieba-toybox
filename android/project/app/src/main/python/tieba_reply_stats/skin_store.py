"""S2-C 自定义轻皮肤：只允许 JSON + PNG/JPG，不执行代码。"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from typing import Dict, Optional

from .settings import APP_DIR

SKIN_ROOT = os.path.join(APP_DIR, "skins")
CUSTOM_DIR = os.path.join(SKIN_ROOT, "custom")
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
MAX_FILES = 40
ALLOWED_FILES = {".json", ".png"}
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLOR_KEYS = {
    "window_bg",
    "surface",
    "surface_alt",
    "border",
    "text",
    "text_secondary",
    "text_muted",
    "accent",
    "accent_hover",
    "accent_text",
    "selection_bg",
    "selection_text",
    "table_bg",
    "table_alt",
    "table_header_bg",
    "table_header_text",
    "log_bg",
    "log_text",
    "danger",
    "danger_bg",
    "warning",
    "warning_bg",
    "safe",
    "safe_bg",
    "button_bg",
    "button_hover",
    "button_text",
    "disabled_bg",
    "disabled_text",
    "banner_bg",
    "banner_text",
}


class SkinError(ValueError):
    pass


def read_custom() -> Optional[Dict]:
    manifest = os.path.join(CUSTOM_DIR, "skin.json")
    if not os.path.isfile(manifest):
        return None
    try:
        with open(manifest, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    colors = data.get("colors") or {}
    if not isinstance(colors, dict):
        colors = {}
    assets = data.get("assets") or {}
    result: Dict = {
        "name": str(data.get("name") or "自定义皮肤"),
        "mode": data.get("mode") if data.get("mode") in ("light", "dark") else "light",
        "colors": {key: value for key, value in colors.items() if key in COLOR_KEYS and isinstance(value, str)},
        "assets": {},
    }
    for key in ("header", "side", "empty"):
        value = assets.get(key)
        if not value:
            continue
        path = os.path.realpath(os.path.join(CUSTOM_DIR, value))
        if path.startswith(os.path.realpath(CUSTOM_DIR) + os.sep) and os.path.isfile(path):
            result["assets"][key] = path
    return result


def asset(kind: str) -> Optional[str]:
    custom = read_custom()
    if custom:
        return custom["assets"].get(kind)
    return None


def _safe_members(zf: zipfile.ZipFile):
    members = []
    total = 0
    if len(zf.infolist()) > MAX_FILES:
        raise SkinError("皮肤文件数量过多")
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise SkinError("皮肤包含不安全路径")
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_FILES:
            raise SkinError(f"皮肤包含不允许的文件：{name}")
        if info.file_size > MAX_FILE:
            raise SkinError(f"单文件过大：{name}")
        total += info.file_size
        if total > MAX_TOTAL:
            raise SkinError("皮肤包过大")
        members.append(info)
    return members


def _validate_manifest(data: Dict, base: str) -> Dict:
    if not isinstance(data, dict):
        raise SkinError("skin.json 格式错误")
    if data.get("schema") != 1:
        raise SkinError("不支持的皮肤版本")
    colors = data.get("colors") or {}
    if not isinstance(colors, dict):
        raise SkinError("colors 必须是对象")
    clean = {}
    for key, value in colors.items():
        if key not in COLOR_KEYS:
            continue
        if not isinstance(value, str) or not COLOR_RE.match(value):
            raise SkinError(f"颜色格式错误：{key}")
        clean[key] = value.upper()
    assets = data.get("assets") or {}
    if not isinstance(assets, dict):
        raise SkinError("assets 必须是对象")
    clean_assets = {}
    for key in ("header", "side", "empty"):
        value = assets.get(key)
        if not value:
            continue
        path = os.path.realpath(os.path.join(base, value))
        if not path.startswith(os.path.realpath(base) + os.sep):
            raise SkinError("图片路径越界")
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() != ".png":
            raise SkinError(f"图片不存在或格式不对：{key}")
        clean_assets[key] = os.path.relpath(path, base)
    return {
        "schema": 1,
        "name": str(data.get("name") or "自定义皮肤")[:60],
        "mode": data.get("mode") if data.get("mode") in ("light", "dark") else "light",
        "colors": clean,
        "assets": clean_assets,
    }


def import_zip(zip_path: str) -> Dict:
    if not zipfile.is_zipfile(zip_path):
        raise SkinError("不是有效的 ZIP 文件")
    os.makedirs(SKIN_ROOT, exist_ok=True)
    temp = tempfile.mkdtemp(prefix="skin_", dir=SKIN_ROOT)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = _safe_members(zf)
            for info in members:
                target = os.path.realpath(os.path.join(temp, info.filename))
                if not target.startswith(os.path.realpath(temp) + os.sep):
                    raise SkinError("皮肤包含不安全路径")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)
        manifest_path = os.path.join(temp, "skin.json")
        if not os.path.isfile(manifest_path):
            # 允许 ZIP 里套一层目录
            candidates = [
                os.path.join(root, "skin.json")
                for root, _dirs, files in os.walk(temp)
                if "skin.json" in files
            ]
            if len(candidates) != 1:
                raise SkinError("找不到唯一的 skin.json")
            manifest_path = candidates[0]
        base = os.path.dirname(manifest_path)
        with open(manifest_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        clean = _validate_manifest(data, base)
        old = CUSTOM_DIR + ".old"
        if os.path.isdir(old):
            shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(CUSTOM_DIR):
            os.replace(CUSTOM_DIR, old)
        shutil.copytree(base, CUSTOM_DIR)
        with open(os.path.join(CUSTOM_DIR, "skin.json"), "w", encoding="utf-8") as handle:
            json.dump(clean, handle, ensure_ascii=False, indent=2)
        shutil.rmtree(old, ignore_errors=True)
        return read_custom() or {}
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def clear_custom() -> None:
    shutil.rmtree(CUSTOM_DIR, ignore_errors=True)
