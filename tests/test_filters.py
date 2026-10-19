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
    assert [u["uid"] for u in filter_users(USERS, mark="红")] == ["1"]
    assert [u["uid"] for u in filter_users(USERS, mark="黄")] == ["4"]
    assert [u["uid"] for u in filter_users(USERS, mark="绿")] == ["2"]
    assert [u["uid"] for u in filter_users(USERS, mark="白")] == ["3"]


def test_combined():
    result = filter_users(USERS, keyword="小", level="Lv.10+", mark="红")
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
