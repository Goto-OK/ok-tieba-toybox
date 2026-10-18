"""离线自测：用本地样本页面跑通 抓取 → 解析 → 统计 → 导出 全流程。

运行：
    python tests/selftest.py            # 只跑断言
    python tests/selftest.py --render   # 额外生成示例工作簿到 sample/
"""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)
sys.path.insert(0, BASE)

import build_fixtures  # noqa: E402

from tieba_reply_stats.collect import CollectOptions, collect_thread, extract_tid  # noqa: E402
from tieba_reply_stats.export import export_workbook  # noqa: E402
from tieba_reply_stats.fetch import Fetcher, parse_cookie_input  # noqa: E402
from tieba_reply_stats.models import Floor  # noqa: E402
from tieba_reply_stats.parse import parse_comments_page, parse_datetime, strip_html  # noqa: E402

TID = build_fixtures.TID
URL = f"https://tieba.baidu.com/p/{TID}"


class FixtureFetcher(Fetcher):
    """不联网，按 URL 返回本地样本。"""

    def __init__(self, fixtures):
        super().__init__(delay=0, retries=1, verbose=False)
        self.online = False
        self.fixtures = fixtures

    def _fetch_bytes(self, url, headers, data=None):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if "totalComment" in parsed.path:
            text = self.fixtures.get(f"total_{query.get('pn', ['1'])[0]}.json", "")
        elif "/p/comment" in parsed.path:
            pid = query.get("pid", [""])[0]
            pn = query.get("pn", ["1"])[0]
            text = self.fixtures.get(f"comment_{pid}_{pn}.html", "")
        else:
            text = self.fixtures.get(f"page_{query.get('pn', ['1'])[0]}.html", "")
        return text.encode("utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


def load_fixtures() -> dict:
    folder = os.path.join(BASE, "fixtures")
    if not os.path.isfile(os.path.join(folder, "page_1.html")):
        build_fixtures.main()
    fixtures = {}
    for name in os.listdir(folder):
        with open(os.path.join(folder, name), "r", encoding="utf-8") as handle:
            fixtures[name] = handle.read()
    return fixtures


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def test_helpers():
    check(extract_tid("https://tieba.baidu.com/p/1234567890?pn=3") == "1234567890", "extract_tid 链接")
    check(extract_tid("1234567890") == "1234567890", "extract_tid 纯数字")
    cookies = parse_cookie_input("BDUSS=abc; STOKEN=def=ghi; ")
    check(cookies == {"BDUSS": "abc", "STOKEN": "def=ghi"}, f"cookie 解析：{cookies}")
    check(parse_datetime("2024-05-01 10:00").hour == 10, "日期解析")
    check(strip_html("a<br>b<img class=\"BDE_Smiley\" alt=\"哈哈\">") == "a\nb哈哈", "HTML 清洗")


def test_collect():
    fetcher = FixtureFetcher(load_fixtures())
    thread = collect_thread(URL, fetcher, CollectOptions(verbose=False))

    check(thread.meta.tid == TID, "tid")
    check(thread.meta.title == "测试帖子标题", f"标题：{thread.meta.title!r}")
    check(thread.meta.forum == "测试吧", f"吧名：{thread.meta.forum!r}")
    check(len(thread.floors) == 6, f"楼层数：{len(thread.floors)}")
    check(len(thread.comments) == 15, f"楼中楼数：{len(thread.comments)}")

    floors = {f.post_no: f for f in thread.floors}
    check(floors[1].author == "小A" and floors[1].author_name == "用户A" and floors[1].is_op, "1 楼昵称/用户名/楼主")
    check(floors[1].reply_num == 12, f"1 楼 comment_num：{floors[1].reply_num}")
    check(floors[1].level == "12" and floors[1].badge == "知名人士", f"1 楼等级/头衔：{floors[1].level!r}/{floors[1].badge!r}")
    check(floors[1].posted_at is not None and floors[1].posted_at.hour == 10, "1 楼时间（从 tail-info 取）")
    check(floors[2].content == "> 引用内容\n回复内容哈哈", f"2 楼正文：{floors[2].content!r}")
    check(floors[3].content == "=1+1", f"3 楼正文：{floors[3].content!r}")
    check(floors[6].author == "匿名用户", f"6 楼作者：{floors[6].author!r}")
    check(floors[5].author == "小A" and floors[5].author_name == "用户A", f"5 楼昵称/用户名：{floors[5].author!r}/{floors[5].author_name!r}")

    # 1 楼应抓满 12 条（totalComment 10 条 + /p/comment 补 2 条）
    floor1_comments = [c for c in thread.comments if c.floor_no == 1]
    check(len(floor1_comments) == 12, f"1 楼评论数：{len(floor1_comments)}")

    by_pid = {c.pid: c for c in thread.comments}
    check(by_pid["10002"].reply_to == "用户B", f"被回复人：{by_pid['10002'].reply_to!r}")
    check(by_pid["20001"].reply_to == "用户B", f"被回复人 2：{by_pid['20001'].reply_to!r}")
    check(by_pid["10002"].author == "用户C", "楼中楼作者")
    check(by_pid["10001"].author == "昵称B" and by_pid["10001"].author_name == "用户B", "楼中楼昵称/用户名")

    stats = {s["name"]: s for s in thread.user_stats()}
    check(stats["用户B"]["total"] == 11, f"用户B 合计：{stats['用户B']['total']}")
    check(stats["小A"]["total"] == 3 and stats["小A"]["username"] == "用户A", f"用户A 合计/用户名：{stats['小A']}")
    check(stats["用户C"]["total"] == 2, f"用户C 合计：{stats['用户C']['total']}")
    check(stats["用户D"]["total"] == 2, "用户D 合计")
    check(stats["用户E"]["total"] == 2, "用户E 合计")
    check(stats["匿名用户"]["total"] == 1, "匿名用户合计")
    check(stats["用户B"]["level"] == "9", f"用户B 等级：{stats['用户B']['level']!r}")
    check(sum(s["total"] for s in stats.values()) == 21, "回复总数 21")

    no_op = {s["name"]: s for s in thread.user_stats(include_op=False)}
    check(no_op["小A"]["floor_count"] == 1 and no_op["小A"]["total"] == 2, "排除 1 楼")

    # 楼中楼作者的等级：能对上楼层作者时应补上
    check(by_pid["10001"].level == "9", f"楼中楼等级：{by_pid['10001'].level!r}")


def test_parse_fallback():
    """楼中楼页面没有 data-field 时，仍能按 HTML 结构解析。"""
    fixtures = load_fixtures()
    payload = re.sub(r"data-field='[^']*'", "", fixtures["comment_222222_1.html"])
    floor = Floor(post_no=2, pid="222222", author="用户B", author_id="1002", posted_at=None, content="")
    comments, _has_next = parse_comments_page(payload, floor)
    check(len(comments) == 2, f"兜底解析数量：{len(comments)}")
    check(comments[0].author == "小A", f"兜底解析作者：{comments[0].author!r}")
    check(comments[0].content == "谢谢分享" and comments[0].reply_to == "用户B", f"兜底解析内容：{comments[0].content!r}")


def test_export(render: bool):
    from openpyxl import load_workbook

    fetcher = FixtureFetcher(load_fixtures())
    thread = collect_thread(URL, fetcher, CollectOptions(verbose=False))

    sample_dir = os.path.join(ROOT, "sample")
    os.makedirs(sample_dir, exist_ok=True)
    path = os.path.join(sample_dir, "贴吧回复统计示例.xlsx")
    export_workbook(path, [thread])
    check(os.path.isfile(path), "文件已生成")

    book = load_workbook(path)
    check(
        book.sheetnames == ["回复统计", "楼层明细", "楼中楼明细", "帖子信息"],
        f"工作表：{book.sheetnames}",
    )

    stats_sheet = book["回复统计"]
    check(stats_sheet["A1"].value == "排名", "表头")
    check(stats_sheet["B1"].value == "昵称" and stats_sheet["C1"].value == "用户名", "昵称/用户名列")
    check(stats_sheet["E1"].value == "等级" and stats_sheet["F1"].value == "头衔", "等级/头衔列")
    check(stats_sheet["B2"].value == "用户B", f"排名第一：{stats_sheet['B2'].value!r}")
    check(stats_sheet["E2"].value == "Lv.9", f"回复统计等级：{stats_sheet['E2'].value!r}")
    check(stats_sheet["I2"].value == 11, "合计值")

    floor_sheet = book["楼层明细"]
    check(floor_sheet["E1"].value == "等级", "楼层明细等级列")
    check(floor_sheet["E2"].value == "Lv.12", f"楼层等级：{floor_sheet['E2'].value!r}")
    check(floor_sheet["I4"].value == "=1+1" and floor_sheet["I4"].data_type == "s", "公式样文本")
    check(floor_sheet["B6"].value == "小A" and floor_sheet["C6"].value == "用户A", "楼层昵称/用户名")

    comment_sheet = book["楼中楼明细"]
    check(comment_sheet["F1"].value == "等级", "楼中楼等级列")
    check(comment_sheet["I1"].value == "内容", "楼中楼内容列在最后")
    check(comment_sheet["I2"].value not in (None, ""), f"楼中楼内容不为空：{comment_sheet['I2'].value!r}")

    # 多帖导出
    second = collect_thread(URL, fetcher, CollectOptions(verbose=False))
    path2 = os.path.join(sample_dir, "多帖汇总示例.xlsx")
    export_workbook(path2, [thread, second])
    book2 = load_workbook(path2)
    check(book2.sheetnames[0] == "总览", "总览")
    check("用户总榜" in book2.sheetnames, "用户总榜")
    check("1·回复统计" in book2.sheetnames, "分帖工作表")

    if render:
        print(f"示例文件：{path}")
        print(f"多帖示例：{path2}")


def main() -> int:
    render = "--render" in sys.argv
    test_helpers()
    print("[ok] 辅助函数")
    test_collect()
    print("[ok] 抓取 + 解析 + 统计（含等级/楼中楼）")
    test_parse_fallback()
    print("[ok] 无 data-field 的兜底解析")
    test_export(render)
    print("[ok] Excel 导出（已回读校验）")
    print("全部自测通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
