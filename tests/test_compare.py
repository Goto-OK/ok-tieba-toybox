import pytest

from tieba_reply_stats.compare import compare_threads
from tieba_reply_stats.models import Floor, ThreadData, ThreadMeta


def make_thread(tid, users):
    floors = []
    for index, (name, uid, count) in enumerate(users, start=1):
        for _ in range(count):
            floors.append(
                Floor(post_no=index, pid=f"{tid}-{index}", author=name, author_id=uid, author_name=name)
            )
    return ThreadData(meta=ThreadMeta(tid=str(tid), title=f"帖{tid}"), floors=floors)


A = make_thread(1, [("小明", "1", 3), ("小红", "2", 1)])
B = make_thread(2, [("小明", "1", 2), ("小刚", "3", 4)])


def test_intersection():
    result = compare_threads([A, B], [0, 1], "交集")
    assert [row["uid"] for row in result["rows"]] == ["1"]


def test_union():
    result = compare_threads([A, B], [0, 1], "并集")
    assert {row["uid"] for row in result["rows"]} == {"1", "2", "3"}


def test_only_a_and_diff():
    only = compare_threads([A, B], [0, 1], "仅在 A")
    assert [row["uid"] for row in only["rows"]] == ["2"]
    diff = compare_threads([A, B], [0, 1], "A − B")
    assert [row["uid"] for row in diff["rows"]] == ["2"]


def test_requires_two():
    with pytest.raises(ValueError):
        compare_threads([A], [0], "交集")
