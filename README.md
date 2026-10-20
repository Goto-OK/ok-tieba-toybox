# 贴吧统计（tieba-reply-stats）

输入贴吧帖子链接，抓取**主题楼层 + 楼中楼**，按用户汇总，导出 Excel；  
默认匿名使用，不需要 Cookie；可选「关注增强」读取公开关注列表。

> 当前源码：**1.7.0**；规范：**1.7.0**

支持浅色 / 深色 / 跟随系统、蓝色/绿色/紫色/橘黄/粉色/青色/红色强调色。　详细改动见 [CHANGELOG.md](CHANGELOG.md)

---

## 快速开始

### Windows 桌面版（推荐）

1. 双击 `贴吧回复统计.exe`；
2. 粘贴帖子链接（每行一个，也可以直接填帖子 ID）；
3. 选择是否抓楼中楼、是否导出 Excel；
4. 点「开始统计」。

默认匿名（不需要 Cookie）：

- 公开帖子的楼层、完整楼中楼、参与者、等级；
- 发言、基本资料；
- 红绿灯只看本帖发言。

可选「设置 → 高级 → 关注增强」：

- 需要 `BDUSS`；
- 只读取公开关注列表；
- 红绿灯按“发言 + 关注”判定；
- 隐藏关注仍然读不全。

### 命令行（基础）

```bash
python tieba_stats.py https://tieba.baidu.com/p/1234567890 -o 统计.xlsx
python tieba_stats.py <url1> <url2> --no-comments
python tieba_stats.py <url> --cookie "BDUSS=xxx"  # 仅基础抓取
```

### Android（暂停）

Android 旧 APK 保留，但已暂停更新，不再承诺与桌面版功能同步。  
当前只维护 Windows 桌面版和命令行。

---

## 功能

- **楼层抓取**：自动识别总页数，逐页抓取；
- **楼中楼**：默认客户端 protobuf + floor 逐层翻页抓全；
- **按用户统计**：楼层数、楼中楼数、合计、等级、头衔、首次出现楼层；
- **参与者**：点人查看关注贴吧、发言（主题帖 + 回复，带正文）；
- **查用户**：用户名 / 用户ID / 昵称查询，支持条数与日期范围；
- **本地标记**：安全 / 可疑 / 警告三级，默认开启；支持 Excel 导入导出；
- **参与者筛选**：关键词 / 等级 / 标记组合筛选，导出可选全部或当前筛选；
- **多帖对比**：交集 / 并集 / 仅在 A / A−B；
- **单用户报告**：Excel + Markdown；
- **设置备份**：设置 + 本地标记，JSON / ZIP，不含 Cookie；
- **全量楼中楼**：默认匿名 floor 翻页，可设每层上限和并发；
- **隐藏关注探测**：关注列表隐藏时，可按候选吧确认 `is_follow`，标注“候选确认”；
- **表格查看**：回复统计 / 楼层明细 / 楼中楼明细，可排序、可打开链接；
- **导出 Excel**：多 sheet、超链接、冻结、筛选、合计行；
- **多帖切换**：表格/参与者可切换单帖或全部帖子；再次抓取只补新帖；
- **Emoji 昵称**：支持直接显示、面板选择、粘贴和 `[U+XXXX]` 代码；
- **Android（暂停）**：旧 APK 保留，不再跟进新功能；
- **命令行（基础）**：只做抓取/导出，不跟 GUI 新功能。

---

## 游客模式（无 Cookie）

使用贴吧客户端 protobuf 接口：

```text
POST https://tiebac.baidu.com/c/f/pb/page?cmd=302001
```

无登录态可返回公开帖子的楼层、每层前 10 条楼中楼、用户列表和等级。  
限制：每层最多 10 条楼中楼；完整关注列表、完整资料仍需 Cookie。

---

## 项目结构

```text
tieba-reply-stats/
├─ tieba_reply_stats/       核心包（抓取、解析、protobuf、导出）
├─ tieba_gui.py             Windows 桌面 GUI（tkinter）
├─ tieba_stats.py           命令行入口
├─ tests/                   selftest + HTML/JSON fixtures
├─ tools/                   快照采集、查询、wheel 下载
├─ scripts/                 构建 / 同步脚本
├─ docs/                    需求、架构、协议、发布文档
├─ snapshots/               用户-贴吧等级快照（本地数据，默认不入库）
├─ assets/                  图标、版本信息
├─ android/                 Android 工程、APK、说明
├─ sample/                  示例 Excel
└─ 使用说明.txt              面向用户的完整说明
```

核心模块：

| 模块 | 作用 |
|---|---|
| `fetch.py` | HTTP、Cookie、重试、缓存 |
| `parse.py` | 网页 HTML 解析（lxml） |
| `page_pb.py` | 客户端帖子 protobuf（游客模式） |
| `pbapi.py` | `page_pc` / `nestedFloor`，补等级和 ID |
| `profile.py` | 用户资料、关注列表、发言 |
| `profile_pb.py` | 客户端 profile protobuf |
| `userpost_pb.py` | 客户端 userpost protobuf |
| `collect.py` | 抓取编排、等级补全 |
| `models.py` | Floor / Comment / ThreadData |
| `export.py` | Excel 导出 |
| `blacklist.py` | 三级名单与 Excel 导入导出 |
| `settings.py` | 通用设置 |

---

## 开发

```bash
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
python -m ruff check .              # 代码规范检查
python -m mypy                     # 类型检查
python -m pytest                   # 单元测试（离线）
python tests/selftest.py           # 端到端自测（离线 fixtures）
python tieba_gui.py                # 桌面 GUI
python tieba_stats.py --help       # CLI
```

版本号只有一个来源：`tieba_reply_stats/version.py` 的 `__version__`；
`pyproject.toml` 动态读取，`assets/version_info.txt` 由构建脚本生成。

依赖：`openpyxl`、`lxml`（Android 使用自带的 `lxml.html` 兼容层，基于 BeautifulSoup）。
运行时版本锁定在 `requirements.lock`，开发工具锁定在 `requirements-dev.lock`。

### 构建

```powershell
# 桌面 exe（如果执行策略阻止 .ps1，用 powershell -ExecutionPolicy Bypass -File 运行）
./scripts/build_desktop.ps1

# Android APK（需要 JDK 17 + Android SDK 34 + Gradle 8.7）
./scripts/build_android.ps1 -JavaHome "E:\android-build\jdk-17.0.12+7" `
    -AndroidSdk "E:\android-build\sdk" -Gradle "E:\android-build\gradle-8.7\bin\gradle.bat"
```

同步核心到 Android 工程：

```bash
python scripts/sync_android.py
```

---

## 文档

- [历史文档（只读）](docs/history/README.md)
- [历史架构（只读）](docs/history/architecture.md)
- [接口与协议](docs/protocol.md)
- [发布流程](docs/release.md)
- [开发规范](docs/standards.md)
- [参与开发](CONTRIBUTING.md)
- [收尾规范（实现唯一依据）](SPEC.md)
- [文档索引](docs/README.md)
- [历史界面规范（只读）](docs/history/ui-spec.md)
- [代码地图](docs/code-map.md)
- [手工验收用例](docs/test-cases.md)
- [实现状态](docs/status.md)
- [更新日志](CHANGELOG.md)
- [用户使用说明](使用说明.txt)
- [Android 说明](android/README.md)
- [快照数据说明](snapshots/README.md)

---

## 限制与声明

- 本项目使用的是贴吧**网页/客户端内部接口**，不是百度官方开放 API；接口可能变更或限流；
- 请控制抓取频率，不要用于商业采集或骚扰；
- Cookie 是账号凭证，只保存在本机（Windows 用 DPAPI）；不要提交到仓库或发给他人；
- 隐藏关注列表无法完整枚举，只能部分恢复；
- 游客模式会按设置补全楼中楼；深度可选全部 / 10 / 50 / 100。

## 许可证

[MIT](LICENSE)
