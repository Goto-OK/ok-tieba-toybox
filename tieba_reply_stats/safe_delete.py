"""受限删除：只允许删除应用目录内的明确文件/目录树。"""

from __future__ import annotations

import os
from typing import Iterable

from .settings import APP_DIR

ALLOWED_ROOTS = (os.path.realpath(APP_DIR),)


class UnsafeDelete(ValueError):
    pass


def _check(path: str, roots: Iterable[str]) -> str:
    if not path:
        raise UnsafeDelete("空路径")
    if os.path.islink(path) or getattr(os.path, "isjunction", lambda _p: False)(path):
        raise UnsafeDelete(f"拒绝删除链接：{path}")
    real = os.path.realpath(path)
    for root in roots:
        root_real = os.path.realpath(root)
        if real == root_real or real.startswith(root_real + os.sep):
            return real
    raise UnsafeDelete(f"路径越界：{path}")


def remove_file(path: str, roots: Iterable[str] = ALLOWED_ROOTS) -> None:
    real = _check(path, roots)
    try:
        os.remove(real)
    except FileNotFoundError:
        pass


def remove_tree(path: str, roots: Iterable[str] = ALLOWED_ROOTS) -> None:
    real = _check(path, roots)
    if not os.path.isdir(real):
        return
    with os.scandir(real) as entries:
        for entry in entries:
            if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                raise UnsafeDelete(f"拒绝跟随链接：{entry.path}")
            if entry.is_dir(follow_symlinks=False):
                remove_tree(entry.path, roots)
            else:
                remove_file(entry.path, roots)
    os.rmdir(real)
