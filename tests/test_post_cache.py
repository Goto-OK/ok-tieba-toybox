from tieba_reply_stats import post_cache
from tieba_reply_stats.profile import cached_user_posts


def _post(day: str, ts: int) -> dict:
    return {"time": day, "ts": ts}


def test_cache_falls_back_when_temp_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def fail():
        raise FileNotFoundError("no temp")

    monkeypatch.setattr(post_cache.tempfile, "gettempdir", fail)
    cache = post_cache.PostCache()
    try:
        assert str(tmp_path) in cache._path
    finally:
        cache.close()


def test_post_cache_roundtrip():
    cache = post_cache.cache()
    cache.clear()
    cache.put_page("u1", "reply", 1, {"data": {"list": [1]}})
    assert cache.get_page("u1", "reply", 1) == {"data": {"list": [1]}}
    cache.put_user("u1", {"posts": [{"pid": "1"}]}, priority=post_cache.PRIORITY_LOW)
    assert cache.get_user("u1")["posts"][0]["pid"] == "1"
    stats = cache.stats()
    assert stats["cold_users"] >= 1
    assert stats["cold_pages"] >= 1
    assert stats["cold_posts"] >= 1
    cache.clear()
    assert cache.get_page("u1", "reply", 1) is None
    assert cache.get_user("u1") is None


def test_cache_eviction_is_observable():
    cache = post_cache.cache()
    cache.clear()
    cache._limit_mb = 0
    cache.put_user("evict-me", {"posts": []}, priority=post_cache.PRIORITY_LOW)
    assert cache.take_eviction_notice() >= 1
    cache.clear()
    cache._limit_mb = post_cache.DEFAULT_LIMIT_MB


def test_cached_user_posts_rejects_wider_end():
    cache = post_cache.cache()
    cache.clear()
    cache.put_user(
        "u2",
        {
            "posts": [_post("2025-01-01", 1735689600)],
            "start_date": "",
            "end_date": "2025-01-31",
            "replies_exhausted": True,
            "topic_exhausted": True,
        },
        priority=post_cache.PRIORITY_LOW,
    )
    assert cached_user_posts("u2", 1, "", "2025-06-30") is None


def test_cached_user_posts_rejects_earlier_start():
    cache = post_cache.cache()
    cache.clear()
    cache.put_user(
        "u3",
        {
            "posts": [_post("2025-02-01", 1738368000)],
            "start_date": "2025-02-01",
            "end_date": "",
            "replies_exhausted": True,
            "topic_exhausted": True,
        },
        priority=post_cache.PRIORITY_LOW,
    )
    assert cached_user_posts("u3", 1, "2025-01-01", "") is None


def test_cached_user_posts_allows_no_start_query():
    cache = post_cache.cache()
    cache.clear()
    cache.put_user(
        "u6",
        {
            "posts": [_post("2025-02-01", 1738368000)],
            "coverage_start": "2025-02-01",
            "coverage_end": "2025-02-01",
            "replies_exhausted": True,
            "topic_exhausted": True,
        },
        priority=post_cache.PRIORITY_LOW,
    )
    assert cached_user_posts("u6", 1, "", "") is not None


def test_cached_user_posts_rejects_larger_count_without_complete_feeds():
    cache = post_cache.cache()
    cache.clear()
    cache.put_user(
        "u4",
        {
            "posts": [_post("2025-03-01", 1740787200)],
            "start_date": "",
            "end_date": "",
            "replies_exhausted": True,
            "topic_exhausted": False,
        },
        priority=post_cache.PRIORITY_LOW,
    )
    assert cached_user_posts("u4", 50, "", "") is None


def test_cached_user_posts_accepts_complete_cache():
    cache = post_cache.cache()
    cache.clear()
    cache.put_user(
        "u5",
        {
            "posts": [_post("2025-03-01", 1740787200)],
            "start_date": "",
            "end_date": "",
            "replies_exhausted": True,
            "topic_exhausted": True,
        },
        priority=post_cache.PRIORITY_LOW,
    )
    assert cached_user_posts("u5", 50, "", "") is not None
