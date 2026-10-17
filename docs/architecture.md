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
  → totalComment（每层前 10 条）
  → /p/comment 补足（翻页）
  → page_pc / nestedFloor 补等级、作者 ID
  → ThreadData
```

### 3.2 抓帖子（游客态）

```text
URL → extract_tid
  → POST /c/f/pb/page?cmd=302001（protobuf，无 BDUSS）
  → 每页：floors + sub_post_list（每层 ≤10）+ user_list
  → 翻页至 total_page
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
bars = 发言吧 + 关注吧 + 隐藏恢复吧
  → classify(ban > warn > safe)
  → 若关注隐藏且未命中 ban：升级为 warn 并加 ⚠
  → 行标记 + 行底色
```

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
