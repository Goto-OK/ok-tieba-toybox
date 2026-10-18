"""Look up known user->bar levels from the offline snapshot.

Usage:
    python tools/snapshot_query.py --uid 100000002 --bars 原神,示例吧,yy小说吧
"""

from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "snapshots", "user_bars.jsonl")


def load_rows(path: str):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", required=True)
    parser.add_argument("--bars", required=True, help="comma separated bar names")
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args()

    rows = [row for row in load_rows(args.db) if str(row.get("uid")) == str(args.uid)]
    index: dict[str, dict] = {}
    for row in rows:
        bar = row.get("bar")
        if not bar:
            continue
        current = index.get(bar)
        if current is None or (row.get("level") or 0) > (current.get("level") or 0):
            index[bar] = row

    bars = [item.strip() for item in args.bars.split(",") if item.strip()]
    print(f"uid={args.uid}  snapshot rows={len(rows)}  distinct bars={len(index)}")
    for bar in bars:
        row = index.get(bar)
        if not row:
            print(f"  {bar:<16} 未知（快照里没有）")
            continue
        level = row.get("level")
        exp = row.get("exp")
        level_text = f"Lv.{level}" if level not in (None, "") else "等级未知"
        exp_text = f"exp {exp}" if exp is not None else "exp 未知"
        print(f"  {bar:<16} {level_text:<8} {exp_text:<10} source={row.get('source')}  ts={row.get('ts')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
