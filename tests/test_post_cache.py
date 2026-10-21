from tieba_reply_stats import post_cache


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
    cache.clear()
    assert cache.get_page("u1", "reply", 1) is None
    assert cache.get_user("u1") is None
