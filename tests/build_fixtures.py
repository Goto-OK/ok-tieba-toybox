"""生成解析自测用的离线页面样本（结构与当前贴吧桌面版一致）。

运行：python tests/build_fixtures.py
产物：tests/fixtures/*.html / *.json
"""

from __future__ import annotations

import html
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "fixtures")

TID = "1234567890"
FID = "12345"
TITLE = "测试帖子标题"
FORUM = "测试吧"


def field(attrs: dict) -> str:
    return html.escape(json.dumps(attrs, ensure_ascii=False), quote=True)


def post_html(
    *,
    post_no,
    pid,
    user_id,
    user_name,
    date,
    comment_num=0,
    is_lz=0,
    content="",
    level="",
    badge="",
    nickname="",
) -> str:
    data = {
        "author": {"user_id": user_id, "user_name": user_name, "user_nickname": nickname or user_name},
        "content": {
            "post_id": int(pid),
            "post_no": post_no,
            "comment_num": comment_num,
            "is_lz": is_lz,
        },
    }
    badge_html = ""
    if level:
        badge_html = (
            f'<div class="p_badge"><a class="user_badge d_badge_bright d_badge_icon2_2" '
            f'title="本吧头衔{level}级，经验值100"><div class="d_badge_title">{badge}</div>'
            f'<div class="d_badge_lv">{level}</div></a></div>'
        )
    return f"""
<div class="l_post l_post_bright j_l_post clearfix" data-field='{field(data)}' data-pid="{pid}">
  <div class="p_author">
    <a class="p_author_name j_user_card" href="/home/main?id={user_id}">{user_name or "匿名用户"}</a>
    {badge_html}
  </div>
  <div class="d_post_content_main">
    <cc>
      <div id="post_content_{pid}" class="d_post_content j_d_post_content">{content}</div>
    </cc>
    <div class="core_reply j_lzl_wrapper">
      <div class="core_reply_tail">
        <div class="post-tail-wrap">
          <span class="tail-info">{post_no}楼</span>
          <span class="tail-info">{date}</span>
        </div>
      </div>
    </div>
  </div>
</div>
"""


def page_html(floors: str, pn: int) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{TITLE}_{FORUM}_百度贴吧</title>
<script>
var PageData = {{"forum":{{"id":{FID},"name":"{FORUM}"}},"thread":{{"id":{TID},"title":"{TITLE}","reply_num":21}},"page":{{"total_page":2,"page_no":{pn}}}}};
</script>
</head>
<body>
<div class="p_breadcrumb">
  <a href="/f?kw=%E6%B5%8B%E8%AF%95" class="card_title_fname">{FORUM}</a>
</div>
<h3 class="core_title_txt" title="{TITLE}">{TITLE}</h3>
<div class="p_postlist">
{floors}
</div>
<div class="pager"><a href="?pn=1">1</a><a href="?pn=2">2</a></div>
</body>
</html>
"""


def comment_html_item(spid, showname, user_name, text, when) -> str:
    data = {"spid": spid, "showname": showname, "user_name": user_name, "portrait": "tb.1.xx"}
    return (
        f"<li class=\"lzl_single_post j_lzl_s_p\" data-field='{field(data)}'>"
        f'<a name="{spid}"></a>'
        f'<a class="at j_user_card" username="{user_name}">{showname}</a>:'
        f'<span class="lzl_content_main">{text}</span>'
        f'<div class="lzl_content_reply"><span class="lzl_time">{when}</span></div>'
        f"</li>"
    )


def comment_page(items: str) -> str:
    return f'<div class="lzl_cnt"><ul class="j_lzl_container">{items}</ul></div>'


def total_json(post_comments: dict) -> str:
    data = {"errno": 0, "errmsg": "success", "data": {"comment_list": {}}}
    for pid, comments in post_comments.items():
        infos = []
        for cid, user_id, username, showname, content, now_time in comments:
            infos.append(
                {
                    "comment_id": int(cid),
                    "user_id": user_id,
                    "username": username,
                    "show_nickname": showname,
                    "content": content,
                    "now_time": now_time,
                    "post_id": int(pid),
                }
            )
        data["data"]["comment_list"][pid] = {
            "comment_num": len(infos),
            "comment_list_num": len(infos),
            "comment_info": infos,
        }
    return json.dumps(data, ensure_ascii=False)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    page1 = page_html(
        floors=(
            post_html(
                post_no=1,
                pid="111111",
                user_id=1001,
                user_name="用户A",
                date="2024-05-01 10:00",
                comment_num=12,
                is_lz=1,
                content="主楼内容，欢迎回复<br>第二行",
                level="12",
                badge="知名人士",
                nickname="小A",
            )
            + post_html(
                post_no=2,
                pid="222222",
                user_id=1002,
                user_name="用户B",
                date="2024-05-01 10:05",
                comment_num=2,
                content='&gt; 引用内容<br>回复内容<img class="BDE_Smiley" alt="哈哈">',
                level="9",
                badge="核心吧友",
            )
            + post_html(
                post_no=3,
                pid="333333",
                user_id=1003,
                user_name="用户C",
                date="2024-05-01 10:10",
                comment_num=0,
                content="=1+1",
                level="1",
                badge="初级粉丝",
            )
            + post_html(
                post_no=4,
                pid="444444",
                user_id=1002,
                user_name="用户B",
                date="2024-05-01 10:20",
                comment_num=1,
                content='&nbsp;图片测试<img src="//tb2.bdstatic.com/pic.jpg">',
                level="9",
                badge="核心吧友",
            )
        ),
        pn=1,
    )
    page2 = page_html(
        floors=(
            post_html(
                post_no=5,
                pid="555555",
                user_id=1001,
                user_name="用户A",
                date="2024-05-02 09:00",
                comment_num=0,
                content="第五层",
                level="12",
                badge="知名人士",
                nickname="小A",
            )
            + post_html(
                post_no=6,
                pid="666666",
                user_id=0,
                user_name="",
                date="2024-05-02 09:10",
                comment_num=0,
                content="匿名回复",
            )
        ),
        pn=2,
    )

    # 楼中楼：1楼共 12 条（totalComment 返回前 10，/p/comment 补 2 条）
    floor1_total = []
    for i in range(1, 11):
        floor1_total.append((f"100{i:02d}", 1002, "用户B", "用户B", f"第{i}层回复", 1714560000 + i))
    floor1_total[0] = ("10001", 1002, "用户B", "昵称B", "第一层回复", 1714560001)
    floor1_total[1] = ("10002", 1003, "用户C", "用户C", "回复 用户B: 第二层回复", 1714560002)
    floor1_total[3] = ("10004", 1004, "用户D", "用户D", "路过", 1714560004)

    floor1_p1 = comment_page(
        "".join(
            comment_html_item(cid, showname, username, content, "2024-05-01 11:%02d" % i)
            for i, (cid, _uid, username, showname, content, _t) in enumerate(floor1_total, start=1)
        )
    )
    floor1_p2 = comment_page(
        comment_html_item("10011", "用户E", "用户E", "第十一层回复", "2024-05-01 11:11")
        + comment_html_item("10012", "用户B", "用户B", "第十二层回复", "2024-05-01 11:12")
    )

    floor2 = [
        ("20001", 1001, "用户A", "小A", "回复 用户B: 谢谢分享", 1714570000),
        ("20002", 1004, "用户D", "用户D", "看看", 1714570001),
    ]
    floor2_p1 = comment_page(
        "".join(
            comment_html_item(cid, showname, username, content, "2024-05-01 11:2%d" % i)
            for i, (cid, _uid, username, showname, content, _t) in enumerate(floor2, start=1)
        )
    )
    floor4_p1 = comment_page(comment_html_item("40001", "用户E", "用户E", "第四层打卡", "2024-05-01 11:30"))

    total1 = total_json(
        {
            "111111": floor1_total,
            "222222": floor2,
            "444444": [
                ("40001", 1005, "用户E", "用户E", "第四层打卡", 1714570002),
            ],
        }
    )
    total2 = total_json({})

    files = {
        "page_1.html": page1,
        "page_2.html": page2,
        "total_1.json": total1,
        "total_2.json": total2,
        "comment_111111_1.html": floor1_p1,
        "comment_111111_2.html": floor1_p2,
        "comment_222222_1.html": floor2_p1,
        "comment_444444_1.html": floor4_p1,
    }
    for name, content in files.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        print("wrote", name)


if __name__ == "__main__":
    main()
