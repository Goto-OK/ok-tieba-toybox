# 架构与数据流

## 1. 总览

```text
                 ┌──────────────────────────────┐
                 │         入口层                │
                 │  tieba_gui.py (tkinter)      │
                 │  tieba_stats.py (CLI)        │
                 │  android_server.py (HTTP)    │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────▼───────────────┐
                 │       编排层 collect.py       │
                 │  分页 / 楼中楼 / 等级补全      │
                 └──────────────┬───────────────┘
        ┌───────────────┬───────┴────────┬────────────────┐
        │               │                │                │
┌───────▼──────┐ ┌──────▼──────┐ ┌───────▼───────┐ ┌──────▼───────┐
│ parse.py     │ │ page_pb.py  │ │ pbapi.py      │ │ profile*.py  │
│ 网页 HTML    │ │ 客户端 page │ │ page_pc /     │ │ 资料/发言    │
│ (lxml)       │ │ protobuf    │ │ nestedFloor   │ │ protobuf/JSON│
└───────┬──────┘ └──────┬──────┘ └───────┬───────┘ └──────┬───────┘
        └───────────────┴────────────────┴────────────────┘
                                │
                     ┌──────────▼──────────┐
                     │  models.ThreadData  │
                     │  Floor / Comment    │
                     └──────────┬──────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
      ┌───────▼──────┐  ┌──────▼───────┐  ┌──────▼───────┐
      │ export.py    │  │ 黑名单/设置   │  │ 快照 tools/  │
      │ Excel        │  │ blacklist.py │  │ snapshots    │
      └──────────────┘  └──────────────┘  └──────────────┘
```

## 2. 模块职责

| 模块 | 职责 | 依赖 |
|---|---|---|
| `fetch.py` | HTTP 会话、Cookie、gzip、重试、缓存、dump | 标准库 |
| `parse.py` | 帖子 HTML、楼中楼 HTML/JSON 解析 | lxml（Android 用兼容层） |
| `page_pb.py` | 客户端 `/c/f/pb/page` protobuf，游客模式 | 标准库 |
| `pbapi.py` | `page_pc`、`nestedFloor`，补楼层/楼中楼等级与 ID | 标准库 |
| `profile.py` | 用户资料、关注列表、最近发言、用户解析 | fetch + protobuf 模块 |
| `profile_pb.py` | 客户端 profile protobuf（昵称/粉丝/likeForum） | 标准库 |
| `userpost_pb.py` | 客户端 userpost protobuf（深分页发言） | 标准库 |
| `collect.py` | 抓取编排、评论补齐、等级补全、游客分流 | 以上 |
| `models.py` | `Floor` / `Comment` / `ThreadMeta` / `ThreadData` | 无 |
| `export.py` | Excel 工作簿、超链接、样式 | openpyxl |
| `blacklist.py` | 三级名单、匹配、Excel 导入导出 | openpyxl |
| `settings.py` | 通用设置持久化 | 无 |
| `cookie_store.py` | Windows DPAPI Cookie 存储 | pywin32（仅 Windows） |
| `tieba_gui.py` | 桌面界面、事件队列、后台线程 | tkinter |
| `tieba_stats.py` / `cli.py` | 命令行入口 | 标准库 |
| `android_server.py` | 本地 HTTP API + 静态页面 | 标准库 + 核心包 |

## 3. 数据流

### 3.1 抓帖子（登录态）

```text
URL → extract_tid
  → GET /p/{tid}?pn=1
  → parse_thread_page → ThreadMeta + floors
  → 后续页 /p/{tid}?pn=N
  → 每层先走 floor 翻页（302002）
  → 失败再回退 totalComment + /p/comment
  → page_pc / nestedFloor 补等级、作者 ID
  → ThreadData
```

### 3.2 抓帖子（游客态）

```text
URL → extract_tid
  → POST /c/f/pb/page?cmd=302001（protobuf，无 BDUSS）
  → 每页：floors + user_list（sub_post_list 只是前 10 条预览）
  → 对每层 POST /c/f/pb/floor?cmd=302002（protobuf，无 BDUSS）
  → 按 pn 翻页，直到 has_more = false
  → ThreadData
```

### 3.3 用户资料

```text
uid/username/nickname
  → user_json（id/用户名）
  → profile protobuf（昵称/粉丝/关注数/likeForum/隐私位）
  → panel honor.grade（关注吧等级，隐藏时的部分恢复）
  → follow like（公开关注列表）
  → userpost + myThread（主题帖 + 回复）
```

### 3.4 红绿灯

```text
guest:
  bars = 本帖发言吧
  → classify(ban > warn > safe)
  → 无命中 = 白灯
  → 不查关注，不触发“隐藏关注标黄”

login:
  bars = 发言吧 + 关注吧 + 隐藏恢复吧
  → classify(ban > warn > safe)
  → 若关注隐藏且未命中 ban：升级为 warn 并加 ⚠
  → 行标记 + 行底色
```

`_profile_hit` / `_batch_refresh_marks` 都接收 `mode`：
免登录分支不调用资料/关注接口，直接用帖子里的发言吧。

### 3.5 模式选择

```text
启动
  → 读取设置中的 mode（guest / login，默认 guest）
  → 界面渲染模式选择与能力提示
  → 开始抓取：
       guest → 忽略 Cookie，走 page_pb（匿名）
       login → 校验 BDUSS，走网页/登录 protobuf
  → 状态栏 / 日志 / 导出标注本次模式
```

约束：

- 模式由用户显式选择，`collect_thread` 不再根据 `BDUSS` 是否存在隐式分流；
- 免登录模式下不得读取或发送 Cookie；
- 登录模式缺少 `BDUSS` 时直接报错，不降级；
- 结果对象记录 `mode`，供导出和界面显示。

### 3.6 参与者筛选

```text
people_users（完整数据）
  → filter_users(keyword, level_range, mark)
  → 显示子集（iid 仍用原索引）
  → 选中行 → 原用户详情
```

约束：

- 筛选是纯展示层，不修改 `people_users`、不触发网络；
- 关键词匹配昵称/用户名/UID，兼容 `[U+XXXX]`；
- 等级区间和标记条件可组合；
- 标记条件仅在本地标记开启时可用；
- 导出时若筛选生效，由界面询问“全部 / 当前筛选”；无筛选时直接导出全部。

### 3.7 多帖参与者对比

```text
last_threads
  → 每个帖子的 user_stats()
  → 按 uid / username / name 建立索引
  → 四种模式：
       交集：所有帖子都出现
       并集：任意帖子出现
       仅在 A：只在 A 出现
       A − B：在 A、不在 B
  → 对比表（只读，不触发网络）
```

- A、B 为勾选顺序前两个帖子；
- 各帖计数来自该帖的楼层 + 楼中楼；
- 导出只写对比结果。

### 3.8 单用户报告

```text
profile（查用户或参与者缓存）
  → 基本信息 + 关注 + 最近发言 + 本帖参与
  → Excel 工作簿（5 个工作表，按需）
  → Markdown 摘要
  → 同目录、同文件名输出
```

- 本地标记只在启用时写入；
- 免登录时关注表加“可能不完整”；
- 不包含 Cookie。

### 3.9 配置备份 / 恢复

```text
设置 + 本地标记
  → 序列化 JSON（schema_version / kind / exported_at）
  → 直接保存 .json，或打包成 .zip
  → 恢复：读取 → 校验 → 预览 → 临时备份 → 覆盖
```

- 只含设置和本地标记；
- 不支持 Cookie/快照/历史；
- 校验失败不覆盖现有配置。

### 3.10 吧务删除内容（只读）

```text
吧名 + 用户（uid/username/nickname）
  → 解析 uid
  → get_recovers(forum, uid, pn)
  → 列表（Recover：text/tid/pid/user/op_time/content_type/is_hide）
  → 选中一条
  → get_recover_info(forum, tid, pid)
  → 标题 + 正文详情
```

- 只用只读接口；
- 不调用 `recover` / `del_post` / `del_thread`；
- STOKEN 来源：
  整段 Cookie → 自动解析；缺失 → 吧务页手动补；
- STOKEN 只存在凭据层，界面只显示“已检测到/未检测到”，不显示明文；
- 手动 STOKEN 单独 DPAPI 保存，不进入日志/导出/配置备份；
- 无权限、缺 STOKEN、过期分别提示。

### 3.11 全量楼中楼

```text
page（楼层 + 楼中楼预览）
  → 每层判断 reply_num / 深度上限
  → floor 接口 pn=1..N（可配置并发 1~3）
  → 按 pid 去重
  → 登录模式 floor 失败 → totalComment + /p/comment 回退
  → ThreadData.comments
```

- 匿名只走 floor；失败保留预览 + 警告；
- 登录 floor 优先，失败回退网页；
- 单层失败不影响其他层；
- 每层 50 页、单帖 2000 请求上限。

### 3.12 隐藏关注候选探测

```text
profile 显示 followed_private / priv_like=3
  → 汇总候选吧（本帖发言 + 最近发言 + 本地标记）
  → 去重、排除已知公开关注
  → 最多 30 个
  → 逐个 get_user_forum_info(fname, uid)
  → is_follow=True → 加入关注表（来源=候选确认）
  → 标注“推断，仍可能不完整”
```

- 手动触发，不自动；
- 只探测候选，不做全站遍历；
- 结果不写入配置/备份；报告导出按当前关注表包含；
- 红绿灯可用候选确认结果，但隐藏关注风险规则不变。

## 4. 平台差异

| 能力 | Windows | Android |
|---|---|---|
| UI | tkinter（Tk 8.6） | WebView + 本地 HTTP |
| HTML 解析 | lxml | `lxml` 兼容层（BeautifulSoup） |
| Cookie | DPAPI 加密 | App 私有目录明文 |
| 后台 | 线程 | 线程（进程存活期内） |
| Excel | openpyxl | openpyxl（Chaquopy pip） |
| 构建 | PyInstaller onedir | Gradle + Chaquopy |

## 5. 并发与取消

- GUI 用后台线程 + `queue.Queue` 回主线程更新；
- `CollectOptions.should_stop` 回调用于停止；
- Android HTTP 服务用 `ThreadingHTTPServer`，任务状态放全局 `STATE` + 锁；
- 游客模式按页顺序抓取，页间可取消。

## 6. 存储

| 数据 | 位置 |
|---|---|
| Windows 黑名单 | `%APPDATA%\TiebaReplyStats\blacklist.json` |
| Windows 设置 | `%APPDATA%\TiebaReplyStats\settings.json` |
| Windows Cookie | `%APPDATA%\TiebaReplyStats\cookie.bin`（DPAPI） |
| Android Cookie | App `files/cookie.json` |
| Android 设置 | `files/web_settings.json` |
| 快照 | `snapshots/user_bars.jsonl`、`users.jsonl`（默认不入库） |

## 7. 扩展点

- 新数据源：实现与 `fetch_page` 相同的 dict 结构，接入 `collect_thread`；
- 新导出格式：复用 `ThreadData.user_stats()`；
- 新界面：Android `web/index.html` + `android_server.py` 的 API；
- 新名单规则：扩展 `blacklist.classify`（保持优先级）。
