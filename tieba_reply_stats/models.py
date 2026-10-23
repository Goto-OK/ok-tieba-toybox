"""数据模型：楼层、楼中楼、帖子元信息。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class Floor:
    """主题楼层（一楼 / 楼中楼的宿主层）。"""

    post_no: int
    pid: str
    author: str  # 显示名（昵称 user_nickname，浏览时最先看到）
    author_name: str = ""  # 用户名（原始 user_name，如 “吧友1384”）
    author_id: str = ""
    tieba_uid: str = ""  # 用户可见的贴吧ID，可为空
    tieba_uid_failed: bool = False  # 已尝试补全但失败
    user_id_failed: bool = False  # 用户ID补全失败
    portrait: str = ""  # 头像标识，用于查询用户资料
    posted_at: Optional[datetime] = None
    content: str = ""
    reply_num: int = 0  # 楼中楼回复数（页面里的 comment_num）
    is_op: bool = False  # 是否楼主
    is_deleted: bool = False
    level: str = ""  # 本吧等级（数字字符串，如 "9"）
    badge: str = ""  # 本吧头衔名（如 "瘟疫摇篮"）

    @property
    def floor_label(self) -> str:
        return f"{self.post_no}楼" if self.post_no else ""


@dataclass
class Comment:
    """楼中楼回复。"""

    floor_no: int
    floor_author: str
    pid: str
    author: str  # 显示名（昵称）
    author_name: str = ""  # 用户名（原始）
    author_id: str = ""
    tieba_uid: str = ""  # 用户可见的贴吧ID，可为空
    tieba_uid_failed: bool = False  # 已尝试补全但失败
    user_id_failed: bool = False  # 用户ID补全失败
    portrait: str = ""  # 头像标识
    posted_at: Optional[datetime] = None
    content: str = ""
    reply_to: str = ""  # 被回复人
    is_op: bool = False
    level: str = ""  # 本吧等级（能对上楼层作者时补全）


@dataclass
class ThreadMeta:
    tid: str = ""
    fid: str = ""
    title: str = ""
    forum: str = ""
    url: str = ""
    total_page: int = 0
    reply_num: int = 0
    mode: str = ""  # guest / login


@dataclass
class ThreadData:
    meta: ThreadMeta
    floors: List[Floor] = field(default_factory=list)
    comments: List[Comment] = field(default_factory=list)
    pages_fetched: int = 0
    fetched_at: datetime = field(default_factory=datetime.now)
    warnings: List[str] = field(default_factory=list)
    complete: bool = True
    failed_pages: List[int] = field(default_factory=list)
    failed_comment_floors: List[int] = field(default_factory=list)

    @property
    def comment_count(self) -> int:
        return len(self.comments)

    @property
    def total_replies(self) -> int:
        return len(self.floors) + len(self.comments)

    def user_stats(self, include_op: bool = True) -> List[dict]:
        """按用户汇总：主题楼层数、楼中楼数、合计、首次出现的楼层、等级、头衔。

        include_op=False 时，1 楼（楼主主帖）不计入回复数，但仍保留在楼层明细里。
        """
        buckets: Dict[str, dict] = {}

        def touch(
            name: str,
            uid: str,
            floor_no: int,
            level: str = "",
            badge: str = "",
            username: str = "",
            portrait: str = "",
            tieba_uid: str = "",
            tieba_uid_failed: bool = False,
            user_id_failed: bool = False,
        ) -> dict:
            level = str(level or "").strip()
            if level in ("0", "None"):
                level = ""
            clean_portrait = str(portrait or "").split("?")[0]
            if uid and uid != "0":
                key = f"uid:{uid}"
            elif clean_portrait:
                key = f"portrait:{clean_portrait}"
            elif username:
                key = f"name:{username}"
            else:
                key = f"anon:{name}"
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "name": name or "匿名用户",
                    "username": username or "",
                    "uid": uid,
                    "tieba_uid": tieba_uid or "",
                    "tieba_uid_failed": bool(tieba_uid_failed),
                    "user_id_failed": bool(user_id_failed),
                    "portrait": portrait or "",
                    "level": level or "",
                    "badge": badge or "",
                    "floor_count": 0,
                    "comment_count": 0,
                    "total": 0,
                    "first_floor": floor_no,
                    "aliases": [],
                }
                buckets[key] = bucket
            if name and name != bucket["name"]:
                if bucket["name"] and bucket["name"] not in bucket["aliases"]:
                    bucket["aliases"].append(bucket["name"])
                bucket["name"] = name
            if not bucket["username"] and username:
                bucket["username"] = username
            if not bucket["portrait"] and portrait:
                bucket["portrait"] = portrait
            if not bucket["tieba_uid"] and tieba_uid:
                bucket["tieba_uid"] = tieba_uid
            if tieba_uid_failed:
                bucket["tieba_uid_failed"] = True
            if user_id_failed:
                bucket["user_id_failed"] = True
            if not bucket["level"] and level:
                bucket["level"] = level
            if not bucket["badge"] and badge:
                bucket["badge"] = badge
            if floor_no and (bucket["first_floor"] == 0 or floor_no < bucket["first_floor"]):
                bucket["first_floor"] = floor_no
            return bucket

        for floor in self.floors:
            if not include_op and floor.post_no == 1:
                continue
            bucket = touch(
                floor.author,
                floor.author_id,
                floor.post_no,
                floor.level,
                floor.badge,
                floor.author_name,
                floor.portrait,
                floor.tieba_uid,
                floor.tieba_uid_failed,
                floor.user_id_failed,
            )
            bucket["floor_count"] += 1
            bucket["total"] += 1

        for comment in self.comments:
            bucket = touch(
                comment.author,
                comment.author_id,
                comment.floor_no,
                level=comment.level,
                username=comment.author_name,
                portrait=comment.portrait,
                tieba_uid=comment.tieba_uid,
                tieba_uid_failed=comment.tieba_uid_failed,
                user_id_failed=comment.user_id_failed,
            )
            bucket["comment_count"] += 1
            bucket["total"] += 1

        for bucket in buckets.values():
            bucket["aliases"] = [name for name in bucket["aliases"] if name and name != bucket["name"]]
        stats = list(buckets.values())
        stats.sort(key=lambda item: (-item["total"], -item["floor_count"], item["first_floor"]))
        return stats
