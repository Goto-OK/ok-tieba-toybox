from tieba_reply_stats.errors import friendly_error


def test_captcha():
    assert "安全验证" in friendly_error(RuntimeError("被安全验证拦截"))


def test_429():
    assert "限流" in friendly_error(RuntimeError("HTTP 429"))


def test_generic():
    text = friendly_error(RuntimeError("boom"))
    assert "操作失败" in text
    assert "traceback" not in text.lower()
