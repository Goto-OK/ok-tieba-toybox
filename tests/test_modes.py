import pytest

from tieba_reply_stats import page_pb
from tieba_reply_stats.collect import CollectError, CollectOptions, collect_thread
from tieba_reply_stats.fetch import Fetcher
from tieba_reply_stats.models import ThreadData, ThreadMeta

URL = "https://tieba.baidu.com/p/1234567890"


def _fake_page(tid: str):
    return {
        "thread": {
            "tid": tid,
            "title": "测试帖",
            "fname": "测试吧",
            "fid": "1",
            "first_post_id": "1",
            "author_id": "1",
            "author": {},
            "first_post_content": "",
            "reply_num": 0,
        },
        "page": {"current": 1, "total": 1, "has_more": 0},
        "floors": [],
        "comments": [],
        "forum": "测试吧",
    }


def test_login_mode_requires_bduss():
    fetcher = Fetcher(cookie={}, delay=0, verbose=False)
    with pytest.raises(CollectError, match="登录模式"):
        collect_thread(URL, fetcher, CollectOptions(mode="login", verbose=False))


def test_unknown_mode_rejected():
    fetcher = Fetcher(cookie={}, delay=0, verbose=False)
    with pytest.raises(ValueError, match="未知抓取模式"):
        collect_thread(URL, fetcher, CollectOptions(mode="bogus", verbose=False))


def test_guest_mode_uses_anonymous_collector(monkeypatch):
    called = {}

    def fake_anon(url, fetcher, options):
        called["url"] = url
        return ThreadData(meta=ThreadMeta(tid="1234567890", title="测试帖"))

    monkeypatch.setattr(page_pb, "collect_thread_anon", fake_anon)
    fetcher = Fetcher(cookie={"BDUSS": "secret"}, delay=0, verbose=False)
    data = collect_thread(URL, fetcher, CollectOptions(mode="guest", verbose=False))
    assert called["url"] == URL
    assert data.meta.mode == "guest"


def test_guest_never_sends_bduss(monkeypatch):
    seen = []

    def fake_fetch(fetcher, tid, pn=1, with_comments=True, rn=30, comment_rn=10, bduss=None):
        seen.append(bduss)
        return _fake_page(tid)

    monkeypatch.setattr(page_pb, "fetch_page", fake_fetch)
    fetcher = Fetcher(cookie={"BDUSS": "secret"}, delay=0, verbose=False)
    data = page_pb.collect_thread_anon(URL, fetcher, CollectOptions(verbose=False))
    assert seen == [""]
    assert data.meta.mode == "guest"


def test_build_request_can_omit_bduss():
    request = page_pb.build_request("123", bduss="")
    data = page_pb._msg(request, 1)
    common = page_pb._msg(data, 25)
    assert page_pb._text(common, 10) == ""
