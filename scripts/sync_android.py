#!/usr/bin/env python3
"""把核心包同步到 Android 工程，避免手工复制导致两份代码漂移。

用法：
    python scripts/sync_android.py
    python scripts/sync_android.py --check   # 只检查是否一致
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "tieba_reply_stats")
TARGET = os.path.join(
    ROOT, "android", "project", "app", "src", "main", "python", "tieba_reply_stats"
)


def _ignore(_directory, names):
    return [name for name in names if name == "__pycache__" or name.endswith(".pyc")]


def _hash_tree(folder: str) -> dict[str, str]:
    result = {}
    for current, _dirs, files in os.walk(folder):
        for name in files:
            if name.endswith(".pyc"):
                continue
            path = os.path.join(current, name)
            rel = os.path.relpath(path, folder)
            with open(path, "rb") as handle:
                result[rel] = hashlib.sha256(handle.read()).hexdigest()
    return result


def _check() -> int:
    if not os.path.isdir(TARGET):
        print(f"[check] 目标目录不存在：{TARGET}")
        return 1
    source = _hash_tree(SOURCE)
    target = _hash_tree(TARGET)
    only_source = sorted(set(source) - set(target))
    only_target = sorted(set(target) - set(source))
    changed = sorted(name for name in set(source) & set(target) if source[name] != target[name])
    if not (only_source or only_target or changed):
        print(f"[check] 一致：{len(source)} 个文件")
        return 0
    print(f"[check] 不一致：仅源码 {len(only_source)}，仅目标 {len(only_target)}，内容不同 {len(changed)}")
    for name in (only_source + only_target + changed)[:20]:
        print("  -", name)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只检查，不复制")
    args = parser.parse_args()
    if args.check:
        return _check()

    if not os.path.isdir(SOURCE):
        print(f"找不到源码目录：{SOURCE}")
        return 1
    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET, ignore=_ignore)
    count = sum(len(files) for _root, _dirs, files in os.walk(TARGET))
    print(f"[sync] {SOURCE} -> {TARGET}（{count} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
