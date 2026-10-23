import pytest

from tieba_reply_stats import page_pb, profile_pb, settings
from tieba_reply_stats.collect import CollectOptions, enrich_tieba_uids
from tieba_reply_stats.export import _tieba_cell
from tieba_reply_stats.fetch import FetchError, RequestGate
from tieba_reply_stats.models import Floor, ThreadData, ThreadMeta


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


def test_identity_defaults():
    assert settings.DEFAULTS["identity_strategy"] == "full"
    assert settings.DEFAULTS["identity_timing"] is True
    assert settings.DEFAULTS["identity_remember_choice"] is True
    assert settings.DEFAULTS["identity_concurrency"] == 3
