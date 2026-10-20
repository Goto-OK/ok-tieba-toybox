"""设置备份 / 恢复（FR-012）：设置 + 本地标记，JSON / ZIP。"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

KIND = "tieba-reply-stats/backup"
SCHEMA_VERSION = 1
README = "贴吧统计设置备份\n\n包含：通用设置、模式、本地标记。\n不包含 Cookie、快照、抓取历史。\n"


def build_payload(settings: Dict[str, Any], blacklist: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "settings": dict(settings or {}),
        "blacklist": {
            "safe": list((blacklist or {}).get("safe") or []),
            "warn": list((blacklist or {}).get("warn") or []),
            "ban": list((blacklist or {}).get("ban") or []),
        },
    }


def write_backup(path: str, settings: Dict[str, Any], blacklist: Dict[str, Any]) -> str:
    payload = build_payload(settings, blacklist)
    target = Path(path)
    if target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("config.json", json.dumps(payload, ensure_ascii=False, indent=2))
            archive.writestr("README.txt", README)
    else:
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def read_backup(path: str) -> Dict[str, Any]:
    target = Path(path)
    try:
        if target.suffix.lower() == ".zip":
            with zipfile.ZipFile(target) as archive:
                raw = archive.read("config.json").decode("utf-8")
        else:
            raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取备份：{error}")
    if not isinstance(data, dict) or data.get("kind") != KIND:
        raise ValueError("不是本项目生成的备份")
    if int(data.get("schema_version") or 0) != SCHEMA_VERSION:
        raise ValueError("备份版本不支持")
    settings = data.get("settings")
    blacklist = data.get("blacklist")
    if not isinstance(settings, dict) or not isinstance(blacklist, dict):
        raise ValueError("备份内容不完整")
    for key in ("safe", "warn", "ban"):
        if not isinstance(blacklist.get(key), list):
            raise ValueError("本地标记格式错误")
    return {
        "settings": settings,
        "blacklist": {
            "safe": [str(item) for item in blacklist.get("safe") or []],
            "warn": [str(item) for item in blacklist.get("warn") or []],
            "ban": [str(item) for item in blacklist.get("ban") or []],
        },
        "exported_at": data.get("exported_at") or "",
    }


def preview(data: Dict[str, Any]) -> str:
    blacklist = data.get("blacklist") or {}
    count = sum(len(blacklist.get(key) or []) for key in ("safe", "warn", "ban"))
    return (
        f"备份时间：{data.get('exported_at') or '未知'}\n"
        f"本地标记：{count} 个\n"
        f"模式：{(data.get('settings') or {}).get('mode', 'guest')}"
    )
