from tieba_reply_stats import userpost_pb
from tieba_reply_stats.userpost_pb import _fb, _fv, _msg, _num, _text


def _content(text: str) -> bytes:
    return _fb(2, text.encode())


def build_response() -> bytes:
    post = b"".join([
        _fv(2, 123),                 # thread_id
        _fv(3, 111),                 # post_id
        _fv(5, 1700000000),          # create_time
        _fb(6, "测试吧".encode()),    # forum_name
        _fb(7, "测试标题".encode()),  # title
        _fv(17, 5),                  # reply_num
        _fv(18, 1001),               # user_id
        _fb(10, "alice".encode()),   # user_name
        _fb(35, "Alice".encode()),   # name_show
        _fb(49, _content("正文")),
    ])
    return _fb(2, _fb(1, post))


def test_build_request_fields():
    request = userpost_pb.build_request(1001, pn=2, rn=20)
    data = _msg(request, 1)
    assert _num(data, 1) == 1001
    assert _num(data, 2) == 20
    assert _num(data, 4) == 1
    assert _num(data, 5) == 1
    assert _num(data, 26) == 2


def test_parse_userpost_response():
    posts = userpost_pb.parse_response(build_response())
    assert len(posts) == 1
    post = posts[0]
    assert post["tid"] == "123"
    assert post["pid"] == "111"
    assert post["forum"] == "测试吧"
    assert post["title"] == "测试标题"
    assert post["content"] == "正文"
    assert post["uid"] == "1001"
    assert post["username"] == "alice"
    assert post["nickname"] == "Alice"


def test_parse_empty_response():
    assert userpost_pb.parse_response(b"") == []
