from tieba_reply_stats import profile


class FakeFetcher:
    def __init__(self, fail_replies=False):
        self.fail_replies = fail_replies
        self.calls = []

    def get_json(self, url, name=""):
        self.calls.append(url)
        if "type=2" in url:
            if self.fail_replies:
                raise RuntimeError("reply feed down")
            return {
                "data": {
                    "has_more": True,
                    "list": [
                        {
                            "thread_info": {"tid": 1, "title": "帖子", "fname": "吧", "first_post_id": 1},
                            "post_info": {
                                "id": i,
                                "time": 1700000000 + i,
                                "content": [{"text": f"回复{i}"}],
                            },
                        }
                        for i in range(1, 21)
                    ],
                }
            }
        return {"data": {"list": []}}


def test_posts_stop_at_count_and_report_source(monkeypatch):
    monkeypatch.setattr(profile.userpost_pb, "fetch_user_threads", lambda *args, **kwargs: [])
    status = {}
    posts = profile.fetch_user_posts(FakeFetcher(), "p", count=5, status=status)
    assert len(posts) == 5
    assert status["replies_ok"] is True
    assert status["replies_empty"] is False


def test_reply_failure_is_reported(monkeypatch):
    monkeypatch.setattr(profile.userpost_pb, "fetch_user_threads", lambda *args, **kwargs: [])
    status = {}
    posts = profile.fetch_user_posts(FakeFetcher(fail_replies=True), "p", count=5, status=status)
    assert posts == []
    assert status["replies_ok"] is False
    assert "reply feed down" in status["replies_error"]
