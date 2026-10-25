#!/usr/bin/env python3
"""根据 tieba_reply_stats/version.py 生成 assets/version_info.txt。"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "tieba_reply_stats", "version.py")
TARGET = os.path.join(ROOT, "assets", "version_info.txt")

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404B0',
          [
            StringStruct('CompanyName', 'OK'),
            StringStruct('FileDescription', 'OK的贴吧玩具箱'),
            StringStruct('FileVersion', '{version}'),
            StringStruct('InternalName', 'ok_tieba_toybox'),
            StringStruct('OriginalFilename', 'OK的贴吧玩具箱.exe'),
            StringStruct('ProductName', 'OK的贴吧玩具箱'),
            StringStruct('ProductVersion', '{version}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def read_version() -> str:
    text = open(VERSION_FILE, encoding="utf-8").read()
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("无法从 version.py 读取 __version__")
    return match.group(1)


def main() -> int:
    version = read_version()
    parts = (version.split(".") + ["0", "0", "0"])[:3]
    try:
        major, minor, patch = (int(item) for item in parts)
    except ValueError:
        raise SystemExit(f"版本号不是 x.y.z：{version}") from None
    content = TEMPLATE.format(major=major, minor=minor, patch=patch, version=version)
    with open(TARGET, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print(f"写入 {TARGET}（{version}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
