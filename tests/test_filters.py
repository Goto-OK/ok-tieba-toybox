from tieba_reply_stats.filters import filter_users

USERS = [
    {"name": "小明", "username": "ming", "uid": "1", "level": "12", "hit": "ban"},
    {"name": "小红", "username": "hong", "uid": "2", "level": "5", "hit": "safe"},
    {"name": "无等级", "username": "none", "uid": "3", "level": "", "hit": ""},
    {"name": "表情[U+1F608]", "username": "emoji", "uid": "4", "level": "8", "hit": "warn"},
]


def test_keyword_matches_name_username_uid_and_code():
    assert [u["uid"] for u in filter_users(USERS, keyword="ming")] == ["1"]
    assert [u["uid"] for u in filter_users(USERS, keyword="2")] == ["2"]
    assert [u["uid"] for u in filter_users(USERS, keyword="[U+1F608]")] == ["4"]


def test_level_ranges_and_none():
    assert [u["uid"] for u in filter_users(USERS, level="Lv.1-3")] == []
    assert [u["uid"] for u in filter_users(USERS, level="Lv.4-6")] == ["2"]
    assert [u["uid"] for u in filter_users(USERS, level="Lv.7-9")] == ["4"]
    assert [u["uid"] for u in filter_users(USERS, level="Lv.10+")] == ["1"]
    assert [u["uid"] for u in filter_users(USERS, level="无等级")] == ["3"]


def test_custom_level_range():
    assert [u["uid"] for u in filter_users(USERS, level="自定义", min_level=5, max_level=12)] == [
        "1",
        "2",
        "4",
    ]


def test_mark_filter():
    assert [u["uid"] for u in filter_users(USERS, mark="警告")] == ["1"]
    assert [u["uid"] for u in filter_users(USERS, mark="可疑")] == ["4"]


def test_mark_filter_prefers_displayed_mark_level():
    users = [{"uid": "1", "mark_level": "warn", "hit": "ban"}]
    assert [u["uid"] for u in filter_users(users, mark="可疑")] == ["1"]
    assert filter_users(users, mark="警告") == []
    assert [u["uid"] for u in filter_users(USERS, mark="安全")] == ["2"]
    assert [u["uid"] for u in filter_users(USERS, mark="白")] == ["3"]


def test_combined():
    result = filter_users(USERS, keyword="小", level="Lv.10+", mark="警告")
    assert [u["uid"] for u in result] == ["1"]


def test_merge_blacklists_priority():
    from tieba_reply_stats.blacklist import merge_blacklists

    merged = merge_blacklists(
        {"safe": ["北京吧"], "warn": [], "ban": []},
        {"safe": ["上海吧"], "warn": ["北京吧"], "ban": ["上海吧"]},
    )
    assert "北京" in merged["warn"]
    assert "上海" in merged["ban"]
    assert "北京" not in merged["safe"]


def test_user_stats_latest_nickname_and_aliases():
    from tieba_reply_stats.models import Floor, ThreadData, ThreadMeta

    thread = ThreadData(meta=ThreadMeta(tid="1"))
    thread.floors.append(Floor(1, "p1", "旧昵称", author_name="u", author_id="42"))
    thread.floors.append(Floor(2, "p2", "新昵称", author_name="u", author_id="42"))
    stats = thread.user_stats()
    assert len(stats) == 1
    assert stats[0]["name"] == "新昵称"
    assert "旧昵称" in stats[0]["aliases"]


def test_field_selector_limits_match_target():
    assert [u["uid"] for u in filter_users(USERS, keyword="ming", field="用户名")] == ["1"]
    assert filter_users(USERS, keyword="ming", field="昵称") == []
    assert [u["uid"] for u in filter_users(USERS, keyword="2", field="用户ID")] == ["2"]
    assert [u["uid"] for u in filter_users(USERS, keyword="小红", field="全部字段")] == ["2"]


def test_nickname_field_includes_aliases():
    users = [{"name": "现名", "username": "u", "uid": "9", "aliases": ["旧名"]}]
    assert [u["uid"] for u in filter_users(users, keyword="旧名", field="昵称")] == ["9"]
