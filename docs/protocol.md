# 接口与协议

本项目**没有百度官方开放 API**，使用的是贴吧网页端和客户端的内部接口。
以下记录它们的用法、字段和限制，便于维护和排错。

## 1. 贴吧上游接口

| 接口 | 方法 | 认证 | 用途 | 备注 |
|---|---|---|---|---|
| `https://tieba.baidu.com/p/{tid}?pn={n}` | GET | Cookie | 网页楼层 | 无 Cookie 常 403 |
| `https://tieba.baidu.com/p/totalComment?tid=&fid=&pn=` | GET | Cookie | 楼中楼 JSON | 每层最多 10 条 |
| `https://tieba.baidu.com/p/comment?tid=&pid=&pn=` | GET | Cookie | 楼中楼 HTML | 翻页补足 |
| `https://tieba.baidu.com/c/f/pb/page_pc` | POST | PC sign + Cookie | 新 PC 帖子页用户/等级 | 参数 `kz,pn,r,lz,_client_type` |
| `https://tieba.baidu.com/c/f/pb/nestedFloor` | POST | PC sign + Cookie | 按层翻楼中楼 | `post_id,thread_id,offset` |
| `https://tiebac.baidu.com/c/f/pb/page?cmd=302001` | POST | **可匿名** | 客户端楼层/楼中楼/用户 | protobuf，见 §2 |
| `https://tiebac.baidu.com/c/u/user/profile?cmd=303012` | POST | BDUSS | 用户资料 likeForum | protobuf，见 §3 |
| `https://tiebac.baidu.com/c/u/feed/userpost?cmd=303002` | POST | **可匿名** | 用户发言深分页 | protobuf，见 §4 |
| `https://tiebac.baidu.com/home/get/panel?un=` | GET | 可匿名 | 面板等级/关注数 | `honor.grade` 部分关注 |
| `https://tiebac.baidu.com/c/f/forum/like` | POST | BDUSS + APP sign | 关注列表 | 查别人常返回空 |
| `https://tieba.baidu.com/i/sys/user_json` | GET | 可匿名 | 用户名/ID 互转 | `un=` 或 `uid=` |
| `https://tieba.baidu.com/mo/q/search/user?word=` | GET | 可匿名 | 昵称搜索 | 不可靠，优先参与者 |

### 1.1 签名

- **PC sign**：参数按 key 排序拼 `k=v`，md5 后追加盐
  `36770b1f34c9bbf2e7d1a99d2b82fa9e`；
- **APP sign**：同上，盐为 `tiebaclient!!!`；
- **protobuf 接口**：使用 `multipart/form-data`，字段 `data` 为二进制，
  头 `x_bd_data_type: protobuf`，**不需要 sign**。

## 2. 客户端帖子页 protobuf

```text
POST https://tiebac.baidu.com/c/f/pb/page?cmd=302001
Content-Type: multipart/form-data; boundary=-*_r1999
x_bd_data_type: protobuf
```

### 2.1 请求 `PbPageReqIdl`

| 字段 | 编号 | 类型 | 说明 |
|---|---|---|---|
| `data` | 1 | message | 外层 |
| `common` | 25 | CommonReq | `_client_type=2`、`_client_version="12.64.1.1"` |
| `kz` | 4 | int64 | 帖子 tid |
| `lz` | 5 | int32 | 只看楼主 |
| `r` | 6 | int32 | 排序 |
| `with_floor` | 8 | int32 | 是否带楼中楼 |
| `floor_rn` | 9 | int32 | 每层楼中楼数量（最大 10） |
| `rn` | 13 | int32 | 每页楼层数 |
| `pn` | 18 | int32 | 页码 |
| `floor_sort_type` | 74 | int32 | 楼中楼排序 |

### 2.2 响应 `PbPageResIdl`

| 字段 | 编号 | 说明 |
|---|---|---|
| `error` | 1 | `errorno/errmsg` |
| `data.page` | 3 | `current_page=3,total_page=5,has_more=6` |
| `data.post_list` | 6 | 楼层列表 |
| `data.thread` | 8 | 标题/作者/回复数/吧名/fid |
| `data.user_list` | 13 | 用户（含 `level_id`） |

`Post` 关键字段：`id=1, floor=3, time=4, content=5, sub_post_number=13,
sub_post_list=15, author_id=19, author=23`。  
`SubPostList`：`id=1, content=2, time=3, author_id=4, author=6 floor, author=7`。

## 2.3 按层翻楼中楼（匿名可用）

```text
POST https://tiebac.baidu.com/c/f/pb/floor?cmd=302002
Content-Type: multipart/form-data; boundary=-*_r1999
x_bd_data_type: protobuf
```

请求 `PbFloorReqIdl.data`：

| 字段 | 编号 | 说明 |
|---|---|---|
| `common` | 9 | `_client_type=2`、`_client_version`；登录时带 BDUSS |
| `kz` | 1 | 帖子 tid |
| `pid` | 2 | 楼层 pid（`is_comment=false`） |
| `spid` | 3 | 楼中楼 pid（`is_comment=true`） |
| `pn` | 4 | 页码 |
| `sort` | 19 | 排序 |

响应 `PbFloorResIdl.data`：`page=1`、`post=3`、`subpost_list=4`（评论列表）。

实测：无 BDUSS 也能翻页；某层 32 条回复时，`pn=1` 返回 29 条、`pn=2` 返回 2 条，`has_more=false`。
因此免登录可以抓完整楼中楼，不必受 `page` 接口每层 10 条预览的限制。

证据：`aiotieba 4.8.1` 的 `get_comments` 源码 + 2026-10-19 匿名实测
（tid=1234567890，floor 13，reply_num=32，pn=1 返回 29，pn=2 返回 2）。

登录态补充实测（2026-10-19）：同一楼层带 BDUSS 返回 29 + 2 条，与匿名一致；
`_collect_comments` 登录路径走 floor 后总计 116 条、floor 13 为 31 条，未触发网页回退。

## 3. 用户资料 protobuf

```text
POST https://tiebac.baidu.com/c/u/user/profile?cmd=303012
```

请求 `ProfileReqIdl.data`：`uid=1, need_post_count=2, pn=6, common=9`。  
响应 `User`（`data.user=1`）关键字段：

| 字段 | 编号 | 说明 |
|---|---|---|
| `id` | 2 | 用户 ID |
| `name` | 3 | 用户名 |
| `name_show` | 4 | 昵称 |
| `portrait` | 5 | 头像 |
| `level_id` | 23 | 等级 |
| `fans_num` | 30 | 粉丝 |
| `concern_num` | 31 | 关注数 |
| `post_num` | 37 | 发帖数 |
| `priv_sets` | 45 | 隐私位，`like=2` 为隐藏 |
| `likeForum` | 47 | 精选关注（固定约 6 个） |
| `tieba_uid` | 120 | 另一种 UID |

注意：`likeForum` **不是完整关注列表**；隐藏关注仍无法完整枚举。

## 4. 用户发言 protobuf

```text
POST https://tiebac.baidu.com/c/u/feed/userpost?cmd=303002
```

请求 `UserPostReqIdl.data`：`user_id=1, rn=2, is_thread=4, need_content=5,
pn=26, common=27`。  
`is_thread=1` 才会返回帖子列表（实测每页约 60 条）。

响应 `data.post_list=1`，`PostInfoList` 关键字段：

| 字段 | 编号 | 说明 |
|---|---|---|
| `forum_name` | 6 | 吧名 |
| `title` | 7 | 标题 |
| `create_time` | 5 | 时间戳 |
| `post_id` | 3 | 楼层 ID |
| `thread_id` | 2 | 主题 ID |
| `user_id` | 18 | 作者 ID |
| `first_post_content` | 49 | 正文片段 |
| `content` | 46 | 正文片段 |

## 5. 本地 HTTP API（Android）

服务只监听 `127.0.0.1`，由 App 内 WebView 调用。

### GET

| 路径 | 说明 |
|---|---|
| `/` | 手机网页 |
| `/api/health` | 版本、HOME、线程数 |
| `/api/status` | 运行状态、进度、日志、导出路径 |
| `/api/cookie` | 读取已保存 Cookie |
| `/api/people` | 参与者列表 + 红绿灯 |
| `/api/grid?kind=users\|floors\|comments` | 三张表 |
| `/api/person?uid=&name=&bar=` | 用户详情 |
| `/api/lookup?mode=&q=&count=&start=&end=` | 查成分 |
| `/api/blacklist` | 读取黑名单 |
| `/api/settings` | 读取设置 |
| `/api/export` | 下载当前 Excel |

### POST（JSON）

| 路径 | 参数 |
|---|---|
| `/api/start` | `urls[]`、`mode`（`guest`/`login`）、`cookie`、`max_pages`、`comments`、`export`；`mode=login` 时 Cookie 必须含 `BDUSS` |
| `/api/stop` | 无 |
| `/api/cookie` | `cookie` |
| `/api/blacklist` | `safe[]`、`warn[]`、`ban[]` |
| `/api/settings` | `color_forum`、`color_posts` |

## 6. 限制

- `page` 预览每层最多 10 条，这是 `floor_rn` 上限；`floor` 接口可翻页抓全；
- 隐藏关注列表无法完整获取；
- 高频请求会触发百度安全验证；默认间隔 ≥0.3 秒；
- 接口无文档、可能变更，升级前先跑 `tests/selftest.py` 和真实帖子冒烟。
