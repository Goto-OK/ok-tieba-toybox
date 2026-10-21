from tieba_reply_stats.models import Floor
from tieba_reply_stats.parse import parse_comments_page


def test_comment_keeps_user_id_from_data_field():
    payload = (
        '<li class="lzl_single_post" data-field=\'{"spid":"9","showname":"墨如意",'
        '"user_name":"u123","user_id":"456","portrait":"tb.1.x"}\'>'
        '<span class="lzl_content_main">内容</span>'
        '<span class="lzl_time">2025-01-01 12:00</span></li>'
    )
    floor = Floor(post_no=2, pid="2", author="楼主", author_id="1")
    comments, _ = parse_comments_page(payload, floor)
    assert len(comments) == 1
    assert comments[0].author == "墨如意"
    assert comments[0].author_name == "u123"
    assert comments[0].author_id == "456"


def test_comment_uses_anchor_username_when_data_field_lacks_it():
    payload = (
        '<li class="lzl_single_post" data-field=\'{"spid":"10","showname":"墨如意"}\'>'
        '<a class="at j_user_card" username="u456">墨如意</a>:'
        '<span class="lzl_content_main">内容</span>'
        '<span class="lzl_time">2025-01-01 12:00</span></li>'
    )
    floor = Floor(post_no=2, pid="2", author="楼主", author_id="1")
    comments, _ = parse_comments_page(payload, floor)
    assert comments[0].author == "墨如意"
    assert comments[0].author_name == "u456"
