from __future__ import annotations

import os

import pytest

from tieba_reply_stats import webview2


def _use_temp_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return webview2.login_profile_dir()


def test_profile_fingerprint_matches_same_cookie(monkeypatch, tmp_path):
    _use_temp_profile(monkeypatch, tmp_path)
    cookies = {
        "BDUSS": "bduss-a",
        "TIEBAUID": "uid-a",
        "TIEBA_SID": "sid-a",
    }
    assert webview2.save_profile_fingerprint(cookies)
    assert webview2.match_profile_fingerprint(cookies) is True
    assert webview2.match_profile_fingerprint({"BDUSS": "bduss-b", "TIEBAUID": "uid-b"}) is False


def test_profile_fingerprint_requires_same_kind(monkeypatch, tmp_path):
    _use_temp_profile(monkeypatch, tmp_path)
    webview2.save_profile_fingerprint({"TIEBAUID": "uid-a", "BDUSS": "bduss-a"})
    assert webview2.match_profile_fingerprint({"BDUSS": "bduss-a"}) is None


def test_profile_fingerprint_missing(monkeypatch, tmp_path):
    _use_temp_profile(monkeypatch, tmp_path)
    assert webview2.match_profile_fingerprint({"BDUSS": "bduss-a"}) is None


def test_replace_login_profile_swaps_directories(monkeypatch, tmp_path):
    profile = _use_temp_profile(monkeypatch, tmp_path)
    os.makedirs(profile)
    open(os.path.join(profile, "old.txt"), "w", encoding="utf-8").write("old")
    temp = webview2.prepare_switch_profile()
    open(os.path.join(temp, "new.txt"), "w", encoding="utf-8").write("new")
    webview2.replace_login_profile(temp)
    assert os.path.isfile(os.path.join(profile, "new.txt"))
    assert not os.path.exists(profile + ".bak")


def test_replace_login_profile_keeps_old_when_backup_move_fails(monkeypatch, tmp_path):
    profile = _use_temp_profile(monkeypatch, tmp_path)
    os.makedirs(profile)
    open(os.path.join(profile, "old.txt"), "w", encoding="utf-8").write("old")
    temp = webview2.prepare_switch_profile()
    open(os.path.join(temp, "new.txt"), "w", encoding="utf-8").write("new")

    original = webview2._replace_with_retry

    def fail_backup(source, target, *args, **kwargs):
        if str(target).endswith(".bak"):
            raise OSError("locked")
        return original(source, target, *args, **kwargs)

    monkeypatch.setattr(webview2, "_replace_with_retry", fail_backup)
    with pytest.raises(RuntimeError):
        webview2.replace_login_profile(temp)

    assert os.path.isfile(os.path.join(profile, "old.txt"))
    assert not os.path.exists(profile + ".bak")


def test_cleanup_profile_backup_restores_when_target_missing(monkeypatch, tmp_path):
    profile = _use_temp_profile(monkeypatch, tmp_path)
    os.makedirs(profile + ".bak")
    open(os.path.join(profile + ".bak", "restored.txt"), "w", encoding="utf-8").write("x")
    webview2.cleanup_profile_backup()
    assert os.path.isfile(os.path.join(profile, "restored.txt"))
    assert not os.path.exists(profile + ".bak")


def test_cleanup_profile_backup_reports_failure(monkeypatch, tmp_path):
    profile = _use_temp_profile(monkeypatch, tmp_path)
    os.makedirs(profile)
    os.makedirs(profile + ".bak")
    messages = []
    monkeypatch.setattr(webview2.shutil, "rmtree", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("locked")))
    monkeypatch.setattr(webview2.time, "sleep", lambda _seconds: None)
    webview2.cleanup_profile_backup(messages.append)
    assert messages and "备份已保留" in messages[0]
    assert os.path.isdir(profile + ".bak")


def test_profile_metadata_contains_no_raw_cookie(monkeypatch, tmp_path):
    profile = _use_temp_profile(monkeypatch, tmp_path)
    webview2.save_profile_fingerprint({"TIEBAUID": "uid-secret", "BDUSS": "bduss-secret"})
    path = os.path.join(profile, webview2.PROFILE_META_NAME)
    text = open(path, encoding="utf-8").read()
    assert "uid-secret" not in text
    assert "bduss-secret" not in text
