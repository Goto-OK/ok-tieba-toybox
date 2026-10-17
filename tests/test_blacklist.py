from tieba_reply_stats.blacklist import classify, marker


DATA = {"safe": ["好吧"], "warn": ["有点坏"], "ban": ["坏吧"]}


def test_priority_ban_over_warn_and_safe():
    level, bar = classify(["好吧", "有点坏", "坏"], DATA)
    assert level == "ban"
    assert bar == "坏"


def test_priority_warn_over_safe():
    assert classify(["好吧", "有点坏"], DATA)[0] == "warn"


def test_safe_only():
    assert classify(["好"], DATA)[0] == "safe"


def test_no_hit():
    assert classify(["无关"], DATA) == ("", "")


def test_normalization():
    assert classify([" 坏 吧 "], DATA)[0] == "ban"
    assert classify(["有点坏吧"], DATA)[0] == "warn"


def test_marker():
    assert marker("ban") == "🔴"
    assert marker("warn") == "🟡"
    assert marker("safe") == "🟢"
    assert marker("") == "⚪"
