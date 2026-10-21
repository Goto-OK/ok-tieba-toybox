"""参与者筛选（FR-009）：纯函数，便于离线测试。"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

EMOJI_CODE_RE = re.compile(r"\[U\+([0-9A-Fa-f]{4,6})\]")
LEVEL_OPTIONS = ("全部", "Lv.1-3", "Lv.4-6", "Lv.7-9", "Lv.10+", "无等级", "自定义")
FIELD_OPTIONS = ("全部字段", "昵称", "用户名", "用户ID")
MARK_OPTIONS = ("全部", "警告", "可疑", "安全", "白")


def decode_display(text: str) -> str:
    def repl(match: re.Match) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    return EMOJI_CODE_RE.sub(repl, text or "")


def _level_value(user: Dict) -> int:
    try:
        return int(str(user.get("level") or "").strip())
    except ValueError:
        return 0


def _level_match(user: Dict, level: str, min_level: Optional[int], max_level: Optional[int]) -> bool:
    value = _level_value(user)
    if level == "全部":
        return True
    if level == "无等级":
        return value <= 0
    if level == "自定义":
        low = 1 if min_level is None else min_level
        high = 999 if max_level is None else max_level
        if low > high:
            low, high = high, low
        return low <= value <= high
    if level == "Lv.1-3":
        return 1 <= value <= 3
    if level == "Lv.4-6":
        return 4 <= value <= 6
    if level == "Lv.7-9":
        return 7 <= value <= 9
    if level == "Lv.10+":
        return value >= 10
    return True


def _mark_match(user: Dict, mark: str) -> bool:
    if mark == "全部":
        return True
    # 当前显示标记优先；兼容旧数据的 hit 字段。
    hit = str(user.get("mark_level") or user.get("hit") or "")
    mapping = {"警告": "ban", "可疑": "warn", "安全": "safe", "白": "", "红": "ban", "黄": "warn", "绿": "safe"}
    return hit == mapping.get(mark, "")


def filter_users(
    users: List[Dict],
    keyword: str = "",
    level: str = "全部",
    mark: str = "全部",
    min_level: Optional[int] = None,
    max_level: Optional[int] = None,
    field: str = "全部字段",
) -> List[Dict]:
    text = decode_display((keyword or "").strip()).casefold()
    if field not in FIELD_OPTIONS:
        field = "全部字段"
    result = []
    for user in users:
        name = str(user.get("name") or "")
        username = str(user.get("username") or "")
        uid = str(user.get("uid") or "")
        aliases = [str(value or "") for value in user.get("aliases") or []]
        if text:
            if field == "昵称":
                values = [name, decode_display(name)] + aliases + [decode_display(a) for a in aliases]
            elif field == "用户名":
                values = [username]
            elif field == "用户ID":
                values = [uid]
            else:
                values = [name, decode_display(name), username, uid] + aliases + [
                    decode_display(a) for a in aliases
                ]
            if text not in " ".join(values).casefold():
                continue
        if not _level_match(user, level, min_level, max_level):
            continue
        if not _mark_match(user, mark):
            continue
        result.append(user)
    return result
