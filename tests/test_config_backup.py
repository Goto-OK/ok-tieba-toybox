import pytest

from tieba_reply_stats.config_backup import read_backup, write_backup

SETTINGS = {"mode": "login", "color_forum": True, "risk_enabled": True}
BLACKLIST = {"safe": ["好吧"], "warn": [], "ban": ["坏吧"]}


def test_json_roundtrip(tmp_path):
    path = write_backup(str(tmp_path / "backup.json"), SETTINGS, BLACKLIST)
    data = read_backup(path)
    assert data["settings"]["mode"] == "login"
    assert data["blacklist"]["ban"] == ["坏吧"]


def test_zip_roundtrip(tmp_path):
    path = write_backup(str(tmp_path / "backup.zip"), SETTINGS, BLACKLIST)
    data = read_backup(path)
    assert data["blacklist"]["safe"] == ["好吧"]


def test_invalid_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"kind": "other"}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_backup(str(path))
