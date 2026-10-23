from tieba_reply_stats.link_parser import parse_link
from tieba_reply_stats.lookup_supplement import merge_current_threads
from tieba_reply_stats.models import Comment, Floor, ThreadData, ThreadMeta
from tieba_reply_stats.third_party import parse_post_link


def test_parse_link_topic_floor_and_comment():
    topic = parse_link("https://tieba.baidu.com/p/12345")
    assert topic["tid"] == "12345"
    assert topic["pid"] == ""
    floor = parse_link("https://tieba.baidu.com/p/12345?pid=999")
    assert floor["tid"] == "12345"
    assert floor["pid"] == "999"
    assert parse_post_link("https://tieba.baidu.com/p/12345?pid=999")["url"].endswith("pid=999")


def test_merge_current_threads_uses_uid_and_pid_dedup():
    thread = ThreadData(
        meta=ThreadMeta(tid="1", title="t", forum="f"),
        floors=[
            Floor(post_no=1, pid="p1", author="n", author_id="u1"),
            Floor(post_no=2, pid="p2", author="n", author_id="u2"),
        ],
        comments=[
            Comment(floor_no=2, floor_author="n", pid="p3", author="n", author_id="u1"),
        ],
    )
    result = merge_current_threads(
        [{"pid": "p2", "tid": "1"}],
        [thread],
        {"user_id": "u1", "username": "n"},
    )
    assert [row["pid"] for row in result["posts"]] == ["p1", "p3"]
    assert all(row["source"] == "当前已抓主题" for row in result["posts"])
