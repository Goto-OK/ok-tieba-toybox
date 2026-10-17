from tieba_reply_stats import page_pb
from tieba_reply_stats.page_pb import _fb, _fv, _msg, _num, _text


def _user(uid: int, name: str, nick: str, level: int = 0) -> bytes:
    blob = _fv(2, uid) + _fb(3, name.encode()) + _fb(4, nick.encode())
    if level:
        blob += _fv(23, level)
    return blob


def _content(text: str) -> bytes:
    return _fb(2, text.encode())


def _comment(pid: int, uid: int, text: str) -> bytes:
    return _fb(2, _fb(2, _content(text)))


def _post(pid: int, floor: int, uid: int, text: str, sub: bytes = b"") -> bytes:
    blob = (
        _fv(1, pid)
        + _fv(3, floor)
        + _fv(4, 1700000000)
        + _fb(5, _content(text))
        + _fv(13, 1)
        + _fv(19, uid)
        + _fb(23, _user(uid, "alice", "Alice", 7))
    )
    if sub:
        blob += _fb(15, sub)
    return blob


def build_response() -> bytes:
    sub = _fb(2, _fb(2, _content("回复 Bob : 你好")) + _fv(1, 222) + _fv(4, 1002)
              + _fv(3, 1700000001) + _fb(7, _user(1002, "bob", "Bob", 5)))
    thread = (
        _fv(1, 123)
        + _fb(3, "测试标题".encode())
        + _fv(4, 12)
        + _fv(27, 99)
        + _fb(28, "测试吧".encode())
        + _fv(40, 111)
        + _fv(45, 1700000000)
        + _fv(56, 1001)
        + _fb(18, _user(1001, "alice", "Alice", 7))
        + _fb(142, _content("首楼内容"))
    )
    page = _fv(3, 1) + _fv(5, 3)
    data = b"".join([
        _fb(2, _fb(2, "测试吧".encode())),
        _fb(3, page),
        _fb(6, _post(111, 1, 1001, "主楼", sub)),
        _fb(8, thread),
        _fb(13, _user(1001, "alice", "Alice", 7)),
        _fb(13, _user(1002, "bob", "Bob", 5)),
    ])
    return _fb(2, data)


def test_build_request_fields():
    request = page_pb.build_request("123", pn=2, rn=30, with_comments=True, comment_rn=5, bduss="BD")
    data = _msg(request, 1)
    assert _num(data, 4) == 123
    assert _num(data, 18) == 2
    assert _num(data, 13) == 30
    assert _num(data, 8) == 1
    assert _num(data, 9) == 5
    assert _text(_msg(data, 25), 10) == "BD"


def test_parse_response_floors_and_comments():
    result = page_pb.parse_response(build_response(), with_comments=True)
    assert result["thread"]["title"] == "测试标题"
    assert result["thread"]["fname"] == "测试吧"
    assert result["thread"]["reply_num"] == 12
    assert result["page"]["total"] == 3
    assert result["forum"] == "测试吧"

    floors = result["floors"]
    assert len(floors) == 1
    floor = floors[0]
    assert floor["post_no"] == 1
    assert floor["author"] == "Alice"
    assert floor["author_name"] == "alice"
    assert floor["level"] == 7
    assert floor["content"] == "主楼"
    assert floor["is_op"] is True

    comments = result["comments"]
    assert len(comments) == 1
    comment = comments[0]
    assert comment["author"] == "Bob"
    assert comment["floor_no"] == 1
    assert comment["reply_to"] == "Bob"
    assert comment["content"] == "你好"
    assert comment["level"] == 5


def test_parse_response_without_comments():
    result = page_pb.parse_response(build_response(), with_comments=False)
    assert result["comments"] == []
