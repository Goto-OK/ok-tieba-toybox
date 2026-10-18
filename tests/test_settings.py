import json
from pathlib import Path

from tieba_reply_stats import settings as settings_module


def _use_tmp(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings_module, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", str(tmp_path / "settings.json"))


def test_mode_defaults_to_guest(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    loaded = settings_module.load_settings()
    assert loaded["mode"] == "guest"
    assert loaded["mode_chosen"] is False
    assert loaded["risk_enabled"] is False


def test_mode_roundtrip(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert settings_module.save_settings(
        {"mode": "login", "mode_chosen": True, "risk_enabled": True}
    )
    loaded = settings_module.load_settings()
    assert loaded["mode"] == "login"
    assert loaded["mode_chosen"] is True
    assert loaded["risk_enabled"] is True
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["mode"] == "login"


def test_invalid_mode_falls_back(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / "settings.json").write_text('{"mode": "bogus"}', encoding="utf-8")
    assert settings_module.load_settings()["mode"] == "guest"
