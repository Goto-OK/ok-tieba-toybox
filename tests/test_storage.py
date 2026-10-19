import os
import sqlite3
from datetime import datetime

import pytest

from tieba_reply_stats import storage
from tieba_reply_stats.models import Comment, Floor, ThreadData, ThreadMeta


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "last_result.db"))
    monkeypatch.setattr(storage, "ENC_PATH", str(tmp_path / "last_result.enc"))


def _thread(tid="123"):
    return ThreadData(
        meta=ThreadMeta(tid=tid, title="标题", forum="吧", url="https://tieba.baidu.com/p/" + tid),
        floors=[
            Floor(
                post_no=1,
                pid="p1",
                author="昵称",
                author_name="un",
                author_id="42",
                posted_at=datetime(2026, 1, 1, 12, 0),
                content="内容",
                reply_num=1,
                level="5",
                badge="头衔",
            )
        ],
        comments=[
            Comment(
                floor_no=1,
                floor_author="昵称",
                pid="c1",
                author="回复者",
                author_name="u2",
                author_id="43",
                content="回复",
                level="3",
            )
        ],
        warnings=["警告"],
        complete=False,
    )


def test_roundtrip_plain(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    path = storage.save_threads([_thread()], "1.0")
    assert path.endswith("last_result.db")
    threads, meta = storage.load_threads()
    assert meta["schema_version"] == "1"
    assert len(threads) == 1
    assert threads[0].meta.title == "标题"
    assert threads[0].floors[0].posted_at == datetime(2026, 1, 1, 12, 0)
    assert threads[0].comments[0].content == "回复"
    assert threads[0].warnings == ["警告"]
    assert threads[0].complete is False


def test_empty(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert storage.load_threads() == ([], {})


def test_incompatible_and_archive(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    conn = sqlite3.connect(storage.DB_PATH)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '999')")
    conn.commit()
    conn.close()
    with pytest.raises(storage.IncompatibleResult):
        storage.load_threads()
    moved = storage.archive_incompatible()
    assert moved and os.path.isfile(moved)
    assert not os.path.isfile(storage.DB_PATH)


def test_clear(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    storage.save_threads([_thread()], "1.0")
    assert storage.clear()
    assert not os.path.exists(storage.DB_PATH)
    assert not os.path.exists(storage.ENC_PATH)


@pytest.mark.skipif(os.name != "nt", reason="DPAPI only on Windows")
def test_roundtrip_encrypted(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    try:
        path = storage.save_threads([_thread()], "1.0", encrypted=True)
    except OSError:
        pytest.skip("DPAPI unavailable")
    assert path.endswith("last_result.enc")
    assert os.path.isfile(storage.ENC_PATH)
    threads, _ = storage.load_threads()
    assert threads[0].meta.tid == "123"
