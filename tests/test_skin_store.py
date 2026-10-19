import json
import zipfile
from pathlib import Path

import pytest

from tieba_reply_stats import skin_store


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(skin_store, "SKIN_ROOT", str(tmp_path / "skins"))
    monkeypatch.setattr(skin_store, "CUSTOM_DIR", str(tmp_path / "skins" / "custom"))


def _zip(tmp_path, files):
    path = tmp_path / "skin.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return str(path)


def _manifest(colors=None):
    return json.dumps(
        {
            "schema": 1,
            "name": "测试皮肤",
            "mode": "dark",
            "colors": colors or {"accent": "#123456", "window_bg": "#101010"},
            "assets": {"header": "header.png", "empty": "empty.png"},
        },
        ensure_ascii=False,
    )


def test_import_and_read(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    path = _zip(tmp_path, {"skin.json": _manifest(), "header.png": png, "empty.png": png})
    data = skin_store.import_zip(path)
    assert data["name"] == "测试皮肤"
    assert data["mode"] == "dark"
    assert data["colors"]["accent"] == "#123456"
    assert Path(data["assets"]["header"]).is_file()
    assert skin_store.read_custom()["name"] == "测试皮肤"
    skin_store.clear_custom()
    assert skin_store.read_custom() is None


def test_reject_path_traversal(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    path = _zip(tmp_path, {"../evil.png": b"x"})
    with pytest.raises(skin_store.SkinError):
        skin_store.import_zip(path)


def test_reject_bad_color(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    path = _zip(tmp_path, {"skin.json": _manifest({"accent": "red"})})
    with pytest.raises(skin_store.SkinError):
        skin_store.import_zip(path)
