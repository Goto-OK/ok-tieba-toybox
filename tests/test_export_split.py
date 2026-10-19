from tieba_gui import App
from tieba_reply_stats.models import Comment, Floor, ThreadData, ThreadMeta


def test_single_floor_split_keeps_rows_under_limit():
    thread = ThreadData(
        meta=ThreadMeta(tid="1", title="大帖"),
        floors=[Floor(1, "p1", "作者", "u1", "1", reply_num=25)],
        comments=[
            Comment(1, "作者", f"c{i}", "回复者", "u2", "2", content=str(i))
            for i in range(25)
        ],
    )
    parts = App.__new__(App)._expand_large_threads([thread], limit=10)
    assert len(parts) == 3
    assert all(len(part.floors) + len(part.comments) <= 10 for part in parts)
    assert sum(len(part.comments) for part in parts) == 25
    assert all(part.floors[0].post_no == 1 for part in parts)
