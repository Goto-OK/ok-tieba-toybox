from types import SimpleNamespace

from tieba_reply_stats import page_pb
from tieba_reply_stats.models import Comment, Floor, ThreadData, ThreadMeta


def row(pid, floor_no=13):
    return {
        "pid": pid,
        "author": "a",
        "author_name": "a",
        "author_id": "1",
        "portrait": "",
        "time": 0,
        "content": "",
        "reply_to": "",
        "is_op": False,
        "level": "",
    }


def make_thread(preview=10, reply_num=32):
    comments = [
        Comment(floor_no=13, floor_author="op", pid=f"p{i}", author="a") for i in range(1, preview + 1)
    ]
    floor = Floor(post_no=13, pid="f13", author="op", reply_num=reply_num)
    return ThreadData(meta=ThreadMeta(tid="1"), floors=[floor], comments=comments)


def test_depth_10_skips_when_preview_full(monkeypatch):
    calls = []
    monkeypatch.setattr(page_pb, "fetch_floor_page", lambda *args, **kwargs: calls.append(args) or {})
    thread = make_thread()
    options = SimpleNamespace(include_comments=True, comment_depth=10, comment_concurrency=1, log=None)
    page_pb.fill_comments_anon(thread, None, options)
    assert len(thread.comments) == 10
    assert calls == []


def test_depth_50_fills_to_total(monkeypatch):
    def fake(fetcher, tid, pid, pn, bduss=""):
        if pn == 1:
            return {"comments": [row(f"p{i}") for i in range(11, 40)], "has_more": True}
        return {"comments": [row(f"p{i}") for i in range(40, 51)], "has_more": False}

    monkeypatch.setattr(page_pb, "fetch_floor_page", fake)
    thread = make_thread(reply_num=60)
    options = SimpleNamespace(include_comments=True, comment_depth=50, comment_concurrency=1, log=None)
    page_pb.fill_comments_anon(thread, None, options)
    assert len(thread.comments) == 50


def test_all_fills_to_reply_num_and_dedupes(monkeypatch):
    def fake(fetcher, tid, pid, pn, bduss=""):
        if pn == 1:
            return {"comments": [row(f"p{i}") for i in range(11, 40)], "has_more": True}
        return {"comments": [row("p39")] + [row(f"p{i}") for i in range(40, 51)], "has_more": False}

    monkeypatch.setattr(page_pb, "fetch_floor_page", fake)
    thread = make_thread()
    options = SimpleNamespace(include_comments=True, comment_depth=0, comment_concurrency=1, log=None)
    page_pb.fill_comments_anon(thread, None, options)
    assert len(thread.comments) == 32
    assert len({c.pid for c in thread.comments}) == 32


def test_comments_disabled_skips(monkeypatch):
    calls = []
    monkeypatch.setattr(page_pb, "fetch_floor_page", lambda *args, **kwargs: calls.append(args) or {})
    thread = make_thread()
    options = SimpleNamespace(include_comments=False, comment_depth=0, comment_concurrency=1, log=None)
    page_pb.fill_comments_anon(thread, None, options)
    assert calls == []
