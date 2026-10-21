"""HTML / JSON 解析：把贴吧页面变成楼层与楼中楼。

贴吧桌面版结构大致是：

    <div class="l_post j_l_post" data-field="{...json...}" data-pid="123">
      <a class="p_author_name">用户名</a>
      <div class="d_post_content j_d_post_content" id="post_content_123">正文</div>
      <div class="core_reply j_lzl_wrapper"> ... 楼中楼容器 ... </div>
    </div>

data-field 里的 JSON 包含 author / content / signature 三段，是最稳定的数据源，
因此解析以它为主，辅以 class / id 选择器；为了兼容改版，还保留了纯正则兜底。
"""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import lxml.html

from .models import Comment, Floor, ThreadMeta

IMG_MARK = "[图片]"
EMOJI_RE = re.compile(r'<img[^>]*class="[^"]*BDE_Smiley[^"]*"[^>]*>', re.I)
IMG_RE = re.compile(r"<img[^>]*>", re.I)
BR_RE = re.compile(r"<br\s*/?>", re.I)
TAG_RE = re.compile(r"<[^>]+>")
ATTR_ALT_RE = re.compile(r'alt="([^"]*)"', re.I)
REPLY_TO_RE = re.compile(r"回复\s*(?:<a[^>]*>)?\s*@?([^<>:@：\n]{1,40}?)\s*(?:</a>)?\s*[:：]")
AT_RE = re.compile(r"@([\w\u4e00-\u9fa5·\-]{1,30})")
DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
SHORT_DATE_RE = re.compile(r"(\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?")


# --------------------------------------------------------------------- helpers
def strip_html(fragment: str) -> str:
    """把贴吧正文 HTML 片段转成可读纯文本。"""
    if not fragment:
        return ""
    text = str(fragment)
    text = BR_RE.sub("\n", text)

    def _emoji(match: "re.Match[str]") -> str:
        alt = ATTR_ALT_RE.search(match.group(0))
        return alt.group(1) if alt else ""

    text = EMOJI_RE.sub(_emoji, text)
    text = IMG_RE.sub(IMG_MARK, text)
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", text)
    text = TAG_RE.sub("", text)
    text = html_lib.unescape(text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_datetime(value) -> Optional[datetime]:
    """解析贴吧时间：'2023-05-01 12:30'、Unix 时间戳、'05-01 12:30' 等。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            if value > 1_000_000_000:
                return datetime.fromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_datetime(int(text))

    match = DATE_RE.search(text)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        hour = int(match.group(4) or 0)
        minute = int(match.group(5) or 0)
        second = int(match.group(6) or 0)
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None

    match = SHORT_DATE_RE.search(text)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        hour, minute = int(match.group(3)), int(match.group(4))
        second = int(match.group(5) or 0)
        try:
            return datetime(datetime.now().year, month, day, hour, minute, second)
        except ValueError:
            return None
    return None


def to_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _loads(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _make_tree(html_text: str):
    try:
        return lxml.html.document_fromstring(html_text)
    except Exception:  # noqa: BLE001 - lxml 对残缺 HTML 有时会直接报错
        return None


def _xpath_text(tree, expressions: Iterable[str]) -> str:
    if tree is None:
        return ""
    for expression in expressions:
        try:
            found = tree.xpath(expression)
        except Exception:  # noqa: BLE001
            continue
        for item in found:
            text = item.text_content().strip() if hasattr(item, "text_content") else str(item).strip()
            if text:
                return text
    return ""


# ------------------------------------------------------------------- thread page
def parse_thread_page(html_text: str, url: str = "", tid: str = "") -> Tuple[ThreadMeta, List[Floor]]:
    """解析一页帖子，返回 (元信息, 楼层列表)。"""
    meta = ThreadMeta(tid=tid, url=url)
    if not html_text or not html_text.strip():
        return meta, []

    tree = _make_tree(html_text)
    meta.fid = _extract_fid(html_text)
    meta.total_page = _extract_total_page(html_text, tree)
    meta.reply_num = _extract_reply_num(html_text)
    meta.title = _extract_title(tree) or _title_from_html(html_text)
    meta.forum = _xpath_text(
        tree,
        [
            '//a[contains(@class,"card_title_fname")]',
            '//a[contains(@class,"card_title")]',
            '//*[contains(@class,"forum_name")]',
        ],
    )

    return meta, _extract_floors(tree, html_text)


def _extract_title(tree) -> str:
    return _xpath_text(
        tree,
        [
            '//h1[contains(@class,"core_title_txt")]/@title',
            '//h1[contains(@class,"core_title")]/@title',
            '//h1[contains(@class,"core_title_txt")]',
            '//h1[contains(@class,"core_title")]',
        ],
    )


def _title_from_html(html_text: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html_text, re.S | re.I)
    if not match:
        return ""
    title = html_lib.unescape(match.group(1)).strip()
    title = re.sub(r"_百度贴吧$", "", title)
    title = re.sub(r"^【.*?】", "", title).strip()
    head, sep, tail = title.rpartition("_")
    if sep and tail.endswith("吧"):
        return head.strip()
    return title


def _extract_fid(html_text: str) -> str:
    for pattern in (r'"fid"\s*:\s*"?(\d+)"?', r'"forum_id"\s*:\s*"?(\d+)"?'):
        match = re.search(pattern, html_text)
        if match:
            return match.group(1)
    return ""


def _extract_total_page(html_text: str, tree) -> int:
    match = re.search(r'"total_page"\s*:\s*(\d+)', html_text)
    if match:
        return to_int(match.group(1))
    match = re.search(r"共\s*(\d+)\s*页", html_text)
    if match:
        return to_int(match.group(1))
    if tree is not None:
        pages = [1]
        for href in tree.xpath('//a[contains(@href,"pn=")]/@href'):
            found = re.search(r"pn=(\d+)", href)
            if found:
                pages.append(to_int(found.group(1)))
        return max(pages)
    return 0


def _extract_reply_num(html_text: str) -> int:
    match = re.search(r'"reply_num"\s*:\s*"?(\d+)"?', html_text)
    return to_int(match.group(1)) if match else 0


def _extract_floors(tree, html_text: str) -> List[Floor]:
    nodes = []
    if tree is not None:
        nodes = tree.xpath('//*[@data-field][contains(@class,"l_post")]')
        if not nodes:
            nodes = [
                node for node in tree.xpath("//*[@data-field]") if "post_no" in (node.get("data-field") or "")
            ]

    floors: List[Floor] = []
    seen = set()
    for node in nodes:
        floor = _floor_from_node(node, tree)
        if floor is None:
            continue
        key = floor.pid or f"no:{floor.post_no}"
        if key in seen:
            continue
        seen.add(key)
        floors.append(floor)

    if not floors:
        # 纯正则兜底：页面可能结构大改，但 data-field 仍带 post_no
        for raw in re.findall(r'data-field="([^"]*)"', html_text):
            data = _loads(html_lib.unescape(raw))
            if "post_no" not in (data.get("content") or {}):
                continue
            floor = _floor_from_field(data, "", tree)
            if floor is None:
                continue
            key = floor.pid or f"no:{floor.post_no}"
            if key in seen:
                continue
            seen.add(key)
            floors.append(floor)

    floors.sort(key=lambda item: item.post_no)
    return floors


def _floor_from_node(node, tree) -> Optional[Floor]:
    data = _loads(node.get("data-field"))
    content = data.get("content") or {}
    if "post_no" not in content:
        return None

    pid = str(content.get("post_id") or node.get("data-pid") or "")
    content_html = ""
    parts = node.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " d_post_content ")]')
    if not parts:
        parts = node.xpath('.//div[contains(@class,"j_d_post_content")]')
    if not parts and tree is not None and pid:
        parts = tree.xpath(f'//*[@id="post_content_{pid}"]')
    if parts:
        for hint in parts[0].xpath('.//*[contains(@class,"j_mylzl_guide")]'):
            parent = hint.getparent()
            if parent is not None:
                parent.remove(hint)
        content_html = lxml.html.tostring(parts[0], encoding="unicode")

    # 等级与头衔：<div class="d_badge_lv">9</div> <div class="d_badge_title">瘟疫摇篮</div>
    level = ""
    lv_nodes = node.xpath('.//div[contains(@class,"d_badge_lv")]')
    if lv_nodes:
        level = lv_nodes[0].text_content().strip()
    if not level:
        badge_a = node.xpath('.//a[contains(@class,"user_badge")]')
        if badge_a:
            match = re.search(r"(\d+)级", badge_a[0].get("title") or "")
            if match:
                level = match.group(1)
    badge = ""
    badge_nodes = node.xpath('.//div[contains(@class,"d_badge_title")]')
    if badge_nodes:
        badge = badge_nodes[0].text_content().strip()

    floor = _floor_from_field(data, content_html, tree, level=level, badge=badge)
    if floor is None:
        return None

    # 发布时间：新版页面 data-field 里没有 date，改从 tail-info 里取
    if floor.posted_at is None:
        for span in node.xpath('.//span[contains(@class,"tail-info")]'):
            parsed = parse_datetime(span.text_content().strip())
            if parsed is not None:
                floor.posted_at = parsed
                break

    if floor.author == "匿名用户":
        author = node.xpath('.//a[contains(@class,"p_author_name")]')
        if author:
            floor.author = author[0].text_content().strip() or floor.author
    return floor


def _floor_from_field(
    data: dict, content_html: str, tree, level: str = "", badge: str = ""
) -> Optional[Floor]:
    content = data.get("content") or {}
    author = data.get("author") or {}
    post_no = to_int(content.get("post_no"))
    if not post_no:
        return None

    pid = str(content.get("post_id") or "")
    # 用户名（原始，如“吧友1384”）与昵称（user_nickname，浏览时最先看到）
    author_name = str(author.get("user_name") or "").strip()
    display_name = str(author.get("user_nickname") or "").strip() or author_name
    if not display_name:
        display_name = str(author.get("name_show") or author.get("nick_name") or "").strip()
    author_id = str(author.get("user_id") or "")

    if not content_html and pid and tree is not None:
        parts = tree.xpath(f'//*[@id="post_content_{pid}"]')
        if parts:
            content_html = lxml.html.tostring(parts[0], encoding="unicode")

    return Floor(
        post_no=post_no,
        pid=pid,
        author=display_name or "匿名用户",
        author_name=author_name,
        author_id=author_id,
        portrait=str(author.get("portrait") or ""),
        posted_at=parse_datetime(content.get("date")),
        content=strip_html(content_html),
        reply_num=to_int(content.get("comment_num") or content.get("reply_num")),
        is_op=bool(to_int(content.get("is_lz"))),
        is_deleted="该楼层疑似违规已被系统折叠" in strip_html(content_html),
        level=level,
        badge=badge,
    )


# ------------------------------------------------------------------- comments
def parse_comments_page(payload: str, floor: Floor) -> Tuple[List[Comment], bool]:
    """解析 /p/comment 的返回：JSON 或 HTML 片段都支持；返回 (评论, 是否有下一页)。"""
    if not payload or not payload.strip():
        return [], False

    stripped = payload.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = None
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"[\w$.]+\s*\(\s*(\{.*\})\s*\)\s*;?\s*$", stripped, re.S)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    data = None
        if data is not None:
            comments = [
                comment
                for comment in (_comment_from_json(item, floor) for item in _walk_comment_objects(data))
                if comment is not None
            ]
            return comments, False

    comments = _comments_from_html(payload, floor)
    return comments, _page_has_next(payload)


def parse_total_comment(payload: dict, floors_by_pid: Dict[str, Floor]) -> Dict[str, List[Comment]]:
    """解析 totalComment 接口（新版 JSON），返回 {pid: [评论]}。

    返回结构：{"data":{"comment_list":{"<post_id>":{
      "comment_num":N,"comment_list_num":M,"comment_info":[{...评论...}]}}}}
    注意：该接口每个楼最多返回前 10 条（comment_list_num<=10），缺的由 /p/comment 补齐。
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}
    comment_list = data.get("comment_list")
    if not isinstance(comment_list, dict):
        return {}

    result: Dict[str, List[Comment]] = {}
    for pid_str, bucket in comment_list.items():
        floor = floors_by_pid.get(pid_str) or floors_by_pid.get(str(pid_str))
        if floor is None or not isinstance(bucket, dict):
            continue
        comments: List[Comment] = []
        for raw in bucket.get("comment_info") or []:
            if isinstance(raw, dict):
                comment = _comment_from_total(raw, floor)
                if comment is not None:
                    comments.append(comment)
        if comments:
            result[floor.pid] = comments
    return result


def _comment_from_total(raw: dict, floor: Floor) -> Optional[Comment]:
    """解析 totalComment 里的单条评论。"""
    pid = str(raw.get("comment_id") or "")
    content_html = str(raw.get("content") or "")
    if not content_html and not pid:
        return None
    prefix, cleaned = _strip_reply_prefix(content_html)
    reply_to = prefix or str(raw.get("cite_name") or "").strip()
    username = str(raw.get("username") or "").strip()
    name = str(raw.get("show_nickname") or "").strip() or username
    return Comment(
        floor_no=floor.post_no,
        floor_author=floor.author,
        pid=pid,
        author=name or "匿名用户",
        author_name=username,
        author_id=str(raw.get("user_id") or ""),
        posted_at=parse_datetime(raw.get("now_time")),
        content=strip_html(cleaned),
        reply_to=reply_to,
        is_op=bool(to_int(raw.get("is_thread_author"))),
    )


def _strip_reply_prefix(content_html: str) -> Tuple[str, str]:
    """去掉楼中楼正文开头的「回复 某某 :」，返回 (被回复人, 剩余正文)。"""
    match = REPLY_TO_RE.search(content_html)
    if match:
        # 只有「回复」前面没有实质文字（可能只是 <span> 之类的标签）时才当作回复前缀
        if not strip_html(content_html[: match.start()]).strip():
            reply_to = html_lib.unescape(match.group(1)).strip()
            return reply_to, content_html[match.end() :].lstrip()
    return "", content_html


def _walk_comment_objects(node) -> Iterable[dict]:
    if isinstance(node, dict):
        inner = node.get("comment")
        if isinstance(inner, dict) and "content" in inner:
            merged = dict(inner)
            merged.setdefault("author", node.get("author"))
            yield merged
            return
        if ("pid" in node or "comment_id" in node) and "content" in node:
            yield node
            return
        for value in node.values():
            yield from _walk_comment_objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_comment_objects(value)


def _comment_from_json(item: dict, floor: Floor) -> Optional[Comment]:
    return _comment_from_dict(item, floor)


def _comment_from_dict(data: dict, floor: Floor) -> Optional[Comment]:
    """兼容各种 JSON 评论结构的通用解析。"""
    pid = str(data.get("pid") or data.get("comment_id") or data.get("id") or "")
    content_html = str(data.get("content") or data.get("content_text") or "")
    if not content_html and not pid:
        return None

    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    username = str(
        data.get("username") or data.get("user_name") or (author or {}).get("user_name") or ""
    ).strip()
    name = str(data.get("show_nickname") or (author or {}).get("user_nickname") or "").strip() or username
    uid = str(data.get("user_id") or (author or {}).get("user_id") or "")
    posted = (
        data.get("now_time")
        or data.get("create_time")
        or data.get("date")
        or data.get("condate")
        or data.get("time")
    )
    reply_to = str(data.get("cite_name") or data.get("reply_to") or data.get("reply_user") or "").strip()
    prefix, cleaned = _strip_reply_prefix(content_html)
    if prefix:
        reply_to = prefix
    elif not reply_to:
        match = AT_RE.search(strip_html(content_html))
        if match:
            reply_to = match.group(1)

    return Comment(
        floor_no=floor.post_no,
        floor_author=floor.author,
        pid=pid,
        author=name or "匿名用户",
        author_name=username,
        author_id=uid,
        portrait=str(data.get("portrait") or (author or {}).get("portrait") or ""),
        posted_at=parse_datetime(posted),
        content=strip_html(cleaned),
        reply_to=reply_to,
        is_op=bool(to_int(data.get("is_lz"))),
    )


def _comment_card_identity(node) -> Tuple[str, str, str]:
    """从 j_user_card 取 (username, uid, portrait)，兼容多种改版属性。"""
    username = ""
    uid = ""
    portrait = ""
    anchors = node.xpath('.//a[contains(@class,"j_user_card") or contains(@class,"at")]')
    if not anchors:
        anchors = node.xpath(".//a[@username or @data-username or @user_id or @data-user-id]")
    for anchor in anchors:
        username = username or str(
            anchor.get("username")
            or anchor.get("data-username")
            or anchor.get("user_name")
            or anchor.get("un")
            or ""
        ).strip()
        uid = uid or str(
            anchor.get("user_id")
            or anchor.get("data-user-id")
            or anchor.get("uid")
            or ""
        ).strip()
        portrait = portrait or str(anchor.get("portrait") or "").strip()
        raw = anchor.get("data-field") or anchor.get("data")
        if raw:
            try:
                data = json.loads(html_lib.unescape(raw))
            except (TypeError, ValueError):
                data = None
            if isinstance(data, dict):
                username = username or str(
                    data.get("user_name") or data.get("username") or data.get("un") or ""
                ).strip()
                uid = uid or str(data.get("user_id") or data.get("uid") or "").strip()
                portrait = portrait or str(data.get("portrait") or "").strip()
        href = str(anchor.get("href") or "")
        if href:
            query = parse_qs(urlparse(href).query)
            username = username or str((query.get("un") or [""])[0] or "").strip()
            href_id = str((query.get("id") or [""])[0] or "").strip()
            if href_id:
                if href_id.isdigit():
                    uid = uid or href_id
                else:
                    portrait = portrait or href_id
        if username and (uid or portrait):
            break
    return username, uid, unquote(portrait)


def _comments_from_html(payload: str, floor: Floor) -> List[Comment]:
    """解析新版 /p/comment 返回的 HTML 片段。

    结构：<li class="lzl_single_post j_lzl_s_p" data-field='{"spid":..,"showname":..,"user_name":..}'>
           <a name="spid"></a> ... <span class="lzl_content_main">正文</span>
           <span class="lzl_time">时间</span>
    """
    tree = None
    try:
        tree = lxml.html.fragment_fromstring(payload, create_parent="div")
    except Exception:  # noqa: BLE001
        tree = None
    if tree is None:
        return []

    comments: List[Comment] = []
    nodes = tree.xpath('//li[contains(@class,"lzl_single_post")]')
    if not nodes:
        nodes = tree.xpath('//*[contains(@class,"lzl_single_post")]')

    seen = set()
    for index, node in enumerate(nodes, start=1):
        data = _loads(node.get("data-field"))
        pid = str(data.get("spid") or "")
        if not pid:
            anchor = node.xpath(".//a[@name]")
            if anchor:
                pid = anchor[0].get("name") or ""
        author = str(data.get("showname") or "").strip()
        username = str(data.get("user_name") or "").strip()
        user_id = str(data.get("user_id") or data.get("uid") or "").strip()
        portrait = str(data.get("portrait") or "").strip()
        card_username, card_uid, card_portrait = _comment_card_identity(node)
        username = username or card_username
        user_id = user_id or card_uid
        portrait = portrait or card_portrait
        at = node.xpath('.//a[contains(@class,"j_user_card") or contains(@class,"at")]')
        if not author and at:
            author = at[0].text_content().strip()
        if not author:
            author = username

        content_nodes = node.xpath('.//*[contains(@class,"lzl_content_main")]')
        content_html = lxml.html.tostring(content_nodes[0], encoding="unicode") if content_nodes else ""
        time_nodes = node.xpath('.//*[contains(@class,"lzl_time")]')
        when = time_nodes[0].text_content().strip() if time_nodes else ""

        if not pid and not content_html:
            continue
        if not pid:
            pid = f"{floor.post_no}-{index}"
        if pid in seen:
            continue
        seen.add(pid)
        reply_to, cleaned = _strip_reply_prefix(content_html)

        comments.append(
            Comment(
                floor_no=floor.post_no,
                floor_author=floor.author,
                pid=pid,
                author=author or "匿名用户",
                author_name=username,
                author_id=user_id,
                portrait=portrait,
                posted_at=parse_datetime(when),
                content=strip_html(cleaned),
                reply_to=reply_to,
                is_op=False,
            )
        )
    return comments


def _page_has_next(payload: str) -> bool:
    # 新版分页：<li class="lzl_li_pager" data-field='{"total_num":N,"total_page":P}'>
    match = re.search(r'total_page["\']?\s*[:=]\s*"?(\d+)"?', payload)
    if match:
        return to_int(match.group(1)) > 1
    return "下一页" in payload
