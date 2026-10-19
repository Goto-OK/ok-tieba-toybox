from tieba_reply_stats import follow_probe


def test_candidate_bars_filters_known_and_dedupes():
    user = {"bars": ["示例吧", "示例吧", "北京"]}
    profile = {
        "followed_forums": [{"name": "北京"}],
        "recent_posts": [{"bar": "上海"}, {"bar": "北京"}],
    }
    blacklist = {"safe": ["广州"], "warn": [], "ban": ["示例吧"]}
    bars = follow_probe.candidate_bars(user, profile, blacklist)
    assert bars == ["示例吧", "上海", "广州"]


def test_candidate_bars_limit():
    user = {"bars": [f"吧{i}" for i in range(40)]}
    bars = follow_probe.candidate_bars(user, {}, {}, limit=30)
    assert len(bars) == 30


class DummyFetcher:
    def __init__(self, is_follow=True):
        self.is_follow = is_follow
        self.calls = []

    def cookie_dict(self):
        return {}

    def post_json(self, url, data):
        self.calls.append((url, data))
        return {
            "error_code": 0,
            "data": {
                "user_forum_info": {
                    "is_follow": 1 if self.is_follow else 0,
                    "follow_days": 10,
                    "level_id": 7,
                    "level_name": "测试",
                }
            },
        }


def test_probe_forum_reads_nested_info(monkeypatch):
    monkeypatch.setattr(follow_probe, "resolve_fid", lambda fetcher, bar: 123)
    info = follow_probe.probe_forum(DummyFetcher(True), "测试吧", "tb.1.x")
    assert info["is_follow"] is True
    assert info["level"] == 7
    assert info["name"] == "测试"


def test_probe_forums_keeps_only_followed(monkeypatch):
    monkeypatch.setattr(follow_probe, "resolve_fid", lambda fetcher, bar: 123)
    results = follow_probe.probe_forums(DummyFetcher(False), "1", "tb.1.x", ["a", "b"])
    assert results == []
