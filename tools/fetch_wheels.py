"""下载 PyInstaller 离线 wheels（构建 exe 用）。

用法：python tools/fetch_wheels.py [输出目录]
默认输出到 项目根/.build/wheels。
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://pypi.tuna.tsinghua.edu.cn"
WANTED = [
    ("pyinstaller", "6.22.3", "win_amd64"),
    ("pyinstaller-hooks-contrib", "2026.8", None),
    ("pefile", "2024.8.26", None),
    ("pywin32-ctypes", "0.2.3", None),
    ("altgraph", "0.17.5", None),
    ("packaging", "26.3", None),
    ("setuptools", "84.0.0", None),
]
HDRS = {"Accept": "application/vnd.pypi.simple.v1+json", "User-Agent": "pip/26.2"}


def get_json(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url, dest):
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pip/26.2"})
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read()
            with open(dest, "wb") as handle:
                handle.write(data)
            return True
        except Exception as error:  # noqa: BLE001
            print(f"  retry {attempt}: {type(error).__name__} {str(error)[:80]}")
            time.sleep(2)
    return False


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    wheel_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", ".build", "wheels")
    wheel_dir = os.path.abspath(wheel_dir)
    os.makedirs(wheel_dir, exist_ok=True)

    for pkg, want, only in WANTED:
        try:
            data = get_json(f"{BASE}/simple/{pkg}/")
        except Exception as error:  # noqa: BLE001
            print(f"=== {pkg} index ERR {error}")
            continue
        candidates = [
            item for item in data.get("files", [])
            if item.get("filename", "").endswith(".whl") and want in item.get("filename", "")
        ]
        if only:
            candidates = [item for item in candidates if only in item.get("filename", "")]
        if not candidates:
            print(f"=== {pkg} NO MATCH")
            continue

        def score(item):
            name = item.get("filename", "")
            if name.endswith("py3-none-any.whl"):
                return 0
            if "win_amd64" in name:
                return 1
            return 2

        candidates.sort(key=score)
        wheel = candidates[0]
        name = wheel["filename"]
        url = wheel.get("url") or wheel.get("path") or ""
        if not url.startswith("http"):
            url = urllib.parse.urljoin(BASE + "/simple/", url)
        dest = os.path.join(wheel_dir, name)
        if os.path.isfile(dest):
            print(f"{pkg}: have {name}")
            continue
        print(f"{pkg}: downloading {name}")
        print("  ", "OK" if download(url, dest) else "FAILED")

    print("\n--- wheels ---")
    for name in sorted(os.listdir(wheel_dir)):
        print(" ", name, os.path.getsize(os.path.join(wheel_dir, name)))


if __name__ == "__main__":
    main()
