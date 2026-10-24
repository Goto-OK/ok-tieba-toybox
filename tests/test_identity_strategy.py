import os

import pytest

from tieba_reply_stats import page_pb, profile_pb, settings, webview2
from tieba_reply_stats.collect import CollectOptions, enrich_tieba_uids
from tieba_reply_stats.export import _tieba_cell
from tieba_reply_stats.fetch import CaptchaError, FetchError, RequestGate
from tieba_reply_stats.filters import filter_users
from tieba_reply_stats.models import Floor, ThreadData, ThreadMeta
from tieba_reply_stats.storage import thread_from_dict, thread_to_dict


class FakeFetcher:
    def clone(self):
        return self


def test_tieba_uid_progress_counts_failures(monkeypatch):
    thread = ThreadData(
        meta=ThreadMeta(tid="1"),
        floors=[
            Floor(post_no=1, pid="p1", author="a", author_id="u1"),
            Floor(post_no=2, pid="p2", author="b", author_id="u2"),
        ],
    )
    calls = []

    def fake_profile(fetcher, uid):
        calls.append(uid)
        if uid == "u2":
            raise RuntimeError("boom")
        return {"tieba_uid": "345" if uid == "u1" else ""}

    monkeypatch.setattr(profile_pb, "fetch_profile", fake_profile)
    progress = []
    result = enrich_tieba_uids(
        [thread],
        FakeFetcher(),
        CollectOptions(),
        lambda _msg: None,
        concurrency=3,
        progress=lambda done, total: progress.append((done, total)),
    )

    assert sorted(calls) == ["u1", "u2"]
    assert progress[-1] == (2, 2)
    assert result["failed"] == 1
    assert result["failed_uids"] == ["u2"]


def test_resume_thread_fetches_only_failed_pages(monkeypatch):
    thread = ThreadData(
        meta=ThreadMeta(tid="1", total_page=3, url="https://tieba.baidu.com/p/1"),
        floors=[Floor(post_no=1, pid="p1", author="a", author_id="u1")],
        complete=False,
        failed_pages=[2],
    )
    calls = []

    def fake_page(fetcher, tid, pn, with_comments=True, rn=30, comment_rn=10, bduss=None):
        calls.append(pn)
        return {
            "floors": [
                {
                    "post_no": 31,
                    "pid": "p31",
                    "author": "b",
                    "author_name": "",
                    "author_id": "u2",
                    "portrait": "",
                    "time": "",
                    "content": "x",
                    "reply_num": 0,
                    "is_op": False,
                    "level": "",
                    "tieba_uid": "",
                }
            ],
            "comments": [],
        }

    monkeypatch.setattr(page_pb, "fetch_page", fake_page)
    result = page_pb.resume_thread_anon(
        "https://tieba.baidu.com/p/1",
        thread,
        FakeFetcher(),
        CollectOptions(mode="guest", include_comments=False),
    )

    assert calls == [2, 3]
    assert result.complete is True
    assert result.failed_pages == []
    assert any(floor.pid == "p31" for floor in result.floors)


def test_resume_without_checkpoint_does_not_mark_complete(monkeypatch):
    thread = ThreadData(
        meta=ThreadMeta(tid="1", total_page=3),
        complete=False,
        failed_pages=[],
        failed_comment_floors=[],
    )
    called = []
    monkeypatch.setattr(page_pb, "fetch_page", lambda *a, **k: called.append(1))
    result = page_pb.resume_thread_anon(
        "https://tieba.baidu.com/p/1",
        thread,
        FakeFetcher(),
        CollectOptions(mode="guest", include_comments=False),
    )
    assert called == []
    assert result.complete is False
    assert result.warnings


def test_checkpoint_fields_round_trip():
    thread = ThreadData(
        meta=ThreadMeta(tid="1"),
        floors=[
            Floor(
                post_no=1,
                pid="p1",
                author="a",
                tieba_uid_failed=True,
                user_id_failed=True,
            )
        ],
        complete=False,
        failed_pages=[2],
        failed_comment_floors=[1],
        warnings=["partial"],
    )
    restored = thread_from_dict(thread_to_dict(thread))
    assert restored.complete is False
    assert restored.failed_pages == [2]
    assert restored.failed_comment_floors == [1]
    assert restored.floors[0].tieba_uid_failed is True
    assert restored.floors[0].user_id_failed is True


def test_old_storage_defaults_are_compatible():
    restored = thread_from_dict({"meta": {"tid": "1"}, "floors": [], "comments": []})
    assert restored.complete is True
    assert restored.fetched_pages == []
    assert restored.failed_pages == []
    assert restored.failed_comment_floors == []


def test_tieba_cell_distinguishes_pending_and_failed_identity():
    assert _tieba_cell({"uid": "1"}) == "待补充"
    assert _tieba_cell({"uid": "1", "tieba_uid_failed": True}) == "-"
    assert _tieba_cell({"uid": "1", "tieba_uid": "345"}) == "345"
    assert _tieba_cell({}) == "-"


def test_request_gate_stops_while_paused():
    gate = RequestGate()
    gate.pause(60)
    gate.set_stop_checker(lambda: True)
    with pytest.raises(FetchError):
        gate.wait()


def test_request_gate_stops_while_task_paused():
    gate = RequestGate()
    gate.set_paused(True)
    gate.set_stop_checker(lambda: True)
    with pytest.raises(FetchError):
        gate.wait()


def test_filter_uses_dash_for_failed_tieba_uid():
    users = [
        {"name": "a", "uid": "1", "tieba_uid": "", "tieba_uid_failed": True},
        {"name": "b", "uid": "2", "tieba_uid": ""},
    ]
    assert filter_users(users, keyword="-", field="贴吧ID") == [users[0]]
    assert filter_users(users, keyword="待补充", field="贴吧ID") == [users[1]]


def test_webview2_login_profile_can_be_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = webview2.login_profile_dir()
    assert path.startswith(str(tmp_path))
    assert webview2.clear_login_profile() is True
    os.makedirs(path)
    assert webview2.login_profile_exists() is True
    assert webview2.clear_login_profile() is True
    assert webview2.login_profile_exists() is False


def test_captcha_error_can_carry_partial_thread():
    marker = object()
    error = CaptchaError("拦截", partial=marker)
    assert error.partial is marker
    assert str(error) == "拦截"


def test_webview2_allowed_url():
    assert webview2.is_allowed_url("https://tieba.baidu.com/p/1") is True
    assert webview2.is_allowed_url("https://passport.baidu.com/v2/?login") is True
    assert webview2.is_allowed_url("https://example.com/") is False


def test_webview2_accepts_tieba_sid_as_login_cookie():
    assert webview2.has_login_cookie({"TIEBA_SID": "x"}) is True
    assert webview2.has_login_cookie({"BDUSS": "x"}) is True
    assert webview2.has_login_cookie({"BAIDUID": "x"}) is False


def test_webview2_cookie_filter_prefers_specific_path():
    raw = [
        {"name": "X", "value": "root", "domain": ".baidu.com", "path": "/"},
        {"name": "X", "value": "tieba", "domain": ".tieba.baidu.com", "path": "/p/1"},
    ]
    assert webview2.filter_cookies(raw, anonymous=False)["X"] == "tieba"


def test_webview2_guest_cookie_filter_drops_login_tokens():
    raw = [
        {"name": "BAIDUID", "value": "a", "domain": ".baidu.com"},
        {"name": "BDUSS", "value": "b", "domain": ".baidu.com"},
        {"name": "STOKEN", "value": "c", "domain": ".baidu.com"},
        {"name": "OTHER", "value": "d", "domain": "example.com"},
    ]
    assert webview2.filter_cookies(raw, anonymous=True) == {"BAIDUID": "a"}
    assert webview2.filter_cookies(raw, anonymous=False) == {
        "BAIDUID": "a",
        "BDUSS": "b",
        "STOKEN": "c",
    }


def test_webview_login_is_opt_in():
    assert settings.DEFAULTS["webview_remember_login"] is False


def test_identity_defaults():
    assert settings.DEFAULTS["identity_strategy"] == "full"
    assert settings.DEFAULTS["identity_timing"] is True
    assert settings.DEFAULTS["identity_remember_choice"] is True
    assert settings.DEFAULTS["identity_concurrency"] == 3
