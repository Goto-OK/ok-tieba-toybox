from tieba_reply_stats import profile_pb
from tieba_reply_stats.profile_pb import _fb, _fv, _msg, _num, _text


def _user_blob() -> bytes:
    priv = _fv(2, 3)  # like=3 -> hidden
    like_forum = _fb(1, "测试吧".encode()) + _fv(2, 99)
    return b"".join(
        [
            _fv(2, 1001),
            _fb(3, "alice".encode()),
            _fb(4, "Alice".encode()),
            _fb(5, "tb.1.abc?t=123".encode()),
            _fv(30, 11),
            _fv(31, 22),
            _fv(37, 33),
            _fb(45, priv),
            _fb(47, like_forum),
        ]
    )


def build_response() -> bytes:
    return _fb(2, _fb(1, _user_blob()))


def test_build_request_fields():
    request = profile_pb.build_request(1001, "BDUSS_VALUE")
    data = _msg(request, 1)
    assert _num(data, 1) == 1001
    assert _num(data, 2) == 1
    common = _msg(data, 9)
    assert _text(common, 10) == "BDUSS_VALUE"


def test_parse_profile_response():
    profile = profile_pb.parse_response(build_response())
    assert profile["uid"] == 1001
    assert profile["username"] == "alice"
    assert profile["nickname"] == "Alice"
    assert profile["portrait"] == "tb.1.abc"
    assert profile["fans"] == 11
    assert profile["concern"] == 22
    assert profile["post_num"] == 33
    assert profile["priv_like"] == 3
    assert profile["forums"] == [{"name": "测试吧", "fid": 99}]


def test_parse_invalid_response():
    assert profile_pb.parse_response(b"") == {}
    assert profile_pb.parse_response(b'{"error": 1}') == {}
