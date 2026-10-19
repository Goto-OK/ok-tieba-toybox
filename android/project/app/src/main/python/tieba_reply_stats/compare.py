"""多帖参与者对比（FR-010）：纯本地计算。"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

MODES = ("交集", "并集", "仅在 A", "A − B")


def _key(item: Dict) -> str:
    uid = str(item.get("uid") or "").strip()
    if uid and uid != "0":
        return f"uid:{uid}"
    username = str(item.get("username") or "").strip()
    if username:
        return f"name:{username}"
    return f"nick:{item.get('name') or ''}"


def _label(thread) -> str:
    title = getattr(thread.meta, "title", "") or ""
    forum = getattr(thread.meta, "forum", "") or ""
    text = f"{forum} · {title}" if forum and title else (title or forum or thread.meta.tid)
    return text[:40]


def compare_threads(threads: Sequence, selected: Sequence[int], mode: str) -> Dict:
    if len(selected) < 2:
        raise ValueError("至少选择 2 个帖子")
    if mode not in MODES:
        raise ValueError(f"未知对比方式：{mode}")
    maps = []
    for index in selected:
        stats = threads[index].user_stats(True)
        maps.append({_key(item): item for item in stats})

    all_keys: set[str] = set()
    for mapping in maps:
        all_keys.update(mapping)

    rows: List[Dict[str, Any]] = []
    for key in all_keys:
        present = [i for i, mapping in enumerate(maps) if key in mapping]
        if mode == "交集" and len(present) != len(maps):
            continue
        if mode == "仅在 A" and present != [0]:
            continue
        if mode == "A − B" and not (0 in present and 1 not in present):
            continue
        source = maps[present[0]][key]
        counts = [mapping[key]["total"] if key in mapping else 0 for mapping in maps]
        rows.append(
            {
                "name": source.get("name") or "",
                "username": source.get("username") or "",
                "uid": source.get("uid") or "",
                "counts": counts,
                "total": sum(counts),
                "type": mode,
            }
        )
    rows.sort(key=lambda row: (-sum(int(value) for value in row["counts"]), str(row["name"])))
    return {"threads": [_label(threads[index]) for index in selected], "rows": rows}
