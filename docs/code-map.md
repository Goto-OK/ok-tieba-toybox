# 代码地图

最后更新：2026-10-26

规范以 [../SPEC.md](../SPEC.md) 为准；本文只说明代码位置。

## 1. 入口与 GUI 模块

| 文件 | 作用 |
|---|---|
| `tieba_gui.py` | GUI 入口、`App` 主类、消息轮询 |
| `tieba_gui_layout.py` | 主窗口与各标签页版面构建 |
| `tieba_gui_messages.py` | 后台消息 kind 处理器 |
| `tieba_gui_settings.py` | 设置页构建 |
| `tieba_gui_settings_runtime.py` | 设置应用、备份、界面模式 |
| `tieba_gui_grid.py` | 回复统计/分帖/楼层/楼中楼表格 |
| `tieba_gui_lookup.py` | 查用户页 |
| `tieba_gui_workers.py` | 抓取生命周期与 worker |
| `tieba_gui_links.py` | 链接解析页 |
| `tieba_gui_logging.py` | 日志写入与后台线程安全日志 |
| `tieba_gui_export.py` | Excel/报告导出 |
| `tieba_gui_compare.py` | 多帖对比页与导出 |
| `tieba_gui_dialogs.py` | 通用选择框、提示窗口 |
| `tieba_gui_theme.py` | 主题应用 |
| `tieba_gui_people.py` | 参与者、筛选、分页、区间对话 |
| `tieba_gui_identity.py` | 身份补全与批量标记 |
| `tieba_gui_tools.py` | 日志、测试中心、使用说明、数据清理 |
| `tieba_gui_profile.py` | 用户资料/关注页 |
| `tieba_gui_login.py` | 登录、Cookie、WebView2 |
| `tieba_gui_utils.py` | GUI 共用小工具 |
| `tieba_stats.py` | 命令行包装 |
| `scripts/build_desktop.ps1` | Windows 构建 |
| `scripts/build_android.ps1` | Android 构建（暂停） |

GUI 的 `App` 通过 mixin 组合上述模块；模块只依赖 `tieba_reply_stats` 和同层 GUI 工具，不反向 import `tieba_gui.py`。

## 2. 核心包

| 模块 | 作用 |
|---|---|
| `fetch.py` | HTTP、Cookie、超时、重试、代理 |
| `parse.py` | 网页楼层/楼中楼解析 |
| `page_pb.py` | 匿名 `page` / `floor` protobuf、楼中楼补全 |
| `pbapi.py` | `page_pc` / `nestedFloor` 补等级 |
| `profile.py` | 资料、公开关注、隐藏恢复、发言 |
| `post_cache.py` | 热内存 + 冷 SQLite 发言缓存 |
| `profile_pb.py` | 客户端 profile protobuf |
| `userpost_pb.py` | 客户端 userpost protobuf |
| `follow_probe.py` | 隐藏关注候选探测 |
| `lookup_supplement.py` | 查用户当前主题/回抓主题补全 |
| `link_parser.py` | 官方帖子链接解析 |
| `third_party.py` | 恋文公开数据适配（发言/等级） |
| `collect.py` | 抓取编排、身份/等级补全、匿名/关注增强分流 |
| `models.py` | Floor / Comment / ThreadData / 用户汇总 |
| `filters.py` | 参与者关键词/等级/标记筛选 |
| `compare.py` | 多帖对比 |
| `report.py` | 单用户报告 Excel + Markdown |
| `config_backup.py` | 设置备份/恢复 |
| `blacklist.py` | 本地标记、优先级、导入导出、合并 |
| `settings.py` | 设置默认值、类型校验、持久化 |
| `theme.py` | 浅色/深色/系统、强调色、颜色映射 |
| `safe_delete.py` | 白名单路径删除、拒绝越界/链接 |
| `cookie_store.py` | Windows DPAPI Cookie |
| `storage.py` | 最近结果 SQLite / DPAPI / 恢复 |
| `errors.py` | 统一错误文案 |
| `export.py` | Excel 导出、导出说明、拆分 |
| `version.py` | 版本唯一来源 |
| `cli.py` | 基础命令行 |

## 3. 测试

当前：149 个 pytest 用例；设置 `TIEBA_SKIP_WEBVIEW2_CHECK=1`（CI 的做法）时 149 全过，未设置时 148 通过 + 1 跳过（本机无 WebView2 环境检查）；`tests/selftest.py` 通过。

| 范围 | 文件 |
|---|---|
| GUI/竞态/身份 | `test_gui_race.py`、`test_identity_strategy.py`、`test_profile_fingerprint.py`、`test_profile_identity.py`、`test_profile_posts.py`、`test_post_cache.py`、`test_risk_order.py` |
| GUI 视觉 | `test_emoji.py`、`test_theme.py` |
| protobuf/解析 | `test_page_pb.py`、`test_profile_pb.py`、`test_userpost_pb.py`、`test_parse_comments.py`、`test_floor_depth.py` |
| 抓取/模式 | `test_modes.py`、`test_follow_probe.py`、`test_identity_and_links.py` |
| 导出/报告/对比 | `test_posts_export.py`、`test_export_split.py`、`test_report.py`、`test_compare.py` |
| 筛选/标记 | `test_filters.py`、`test_blacklist.py` |
| 存储/设置/安全 | `test_settings.py`、`test_storage.py`、`test_config_backup.py`、`test_safe_delete.py`、`test_errors.py`、`test_version.py` |
| 离线端到端 | `tests/selftest.py` |

## 4. 脚本

| 文件 | 作用 |
|---|---|
| `scripts/build_desktop.ps1` | PyInstaller 构建、selftest |
| `scripts/build_android.ps1` | Gradle 构建（暂停） |
| `scripts/sync_android.py` | 核心包同步到 Android |
| `scripts/write_version_info.py` | 生成 version_info |

## 5. Android

- `android/project/app/src/main/python/tieba_reply_stats/` 是生成副本；
- 禁止手改，改源码后执行 `python scripts/sync_android.py`；
- Android 已暂停，不跟进新功能。

## 6. 数据与工具

| 路径 | 说明 |
|---|---|
| `sample/` | 示例 Excel |
| `snapshots/` | 离线快照与示例 |
| `tools/` | 快照采集/查询、wheel 下载 |
| `assets/` | 图标、版本信息 |
| `使用说明.txt` | 用户手册 |
| `CHANGELOG.md` | 版本记录 |
