import json
from pathlib import Path

from tieba_reply_stats import settings as settings_module


def _use_tmp(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings_module, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", str(tmp_path / "settings.json"))


def test_defaults(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    loaded = settings_module.load_settings()
    assert "mode" not in loaded
    assert "mode_chosen" not in loaded
    assert loaded["risk_enabled"] is True
    assert loaded["follow_enhance"] is False
    assert loaded["page_size"] == 1000
    assert loaded["theme_mode"] == "light"
    assert loaded["accent"] == "blue"
    assert loaded["skin"] == "default"


def test_roundtrip(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert settings_module.save_settings(
        {
            "follow_enhance": True,
            "risk_enabled": False,
            "batch_concurrency": 3,
            "page_size": 500,
            "proxy_mode": "custom",
            "proxy_url": "http://127.0.0.1:8080",
            "theme_mode": "dark",
            "accent": "green",
            "skin": "bluefish",
        }
    )
    loaded = settings_module.load_settings()
    assert loaded["follow_enhance"] is True
    assert loaded["risk_enabled"] is False
    assert loaded["batch_concurrency"] == 3
    assert loaded["page_size"] == 500
    assert loaded["proxy_mode"] == "custom"
    assert loaded["theme_mode"] == "dark"
    assert loaded["accent"] == "green"
    assert loaded["skin"] == "bluefish"
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["proxy_url"] == "http://127.0.0.1:8080"


def test_invalid_values_fall_back(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    (tmp_path / "settings.json").write_text(
        '{"batch_concurrency": 9, "page_size": 7, "risk_enabled": "false"}',
        encoding="utf-8",
    )
    loaded = settings_module.load_settings()
    assert loaded["batch_concurrency"] == 1
    assert loaded["page_size"] == 1000
    assert loaded["risk_enabled"] is False
