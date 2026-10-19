# 代码地图

最后更新：2026-10-20  
规范以 [../SPEC.md](../SPEC.md) 为准；本文只说明代码位置。

## 1. 入口

| 文件 | 作用 |
|---|---|
| `tieba_gui.py` | Windows tkinter GUI |
| `tieba_stats.py` | 命令行包装 |
| `scripts/build_desktop.ps1` | Windows 构建 |
| `scripts/build_android.ps1` | Android 构建（暂停） |

## 2. 核心包

| 模块 | 作用 |
|---|---|
| `fetch.py` | HTTP、Cookie、超时、重试、代理 |
| `parse.py` | 网页楼层/楼中楼解析 |
| `page_pb.py` | 匿名 `page` / `floor` protobuf、楼中楼补全 |
| `pbapi.py` | `page_pc` / `nestedFloor` 补等级 |
| `profile.py` | 资料、公开关注、隐藏恢复、最近发言 |
| `profile_pb.py` | 客户端 profile protobuf |
| `userpost_pb.py` | 客户端 userpost protobuf |
| `follow_probe.py` | 隐藏关注候选探测 |
| `collect.py` | 抓取编排、匿名/关注增强分流 |
| `models.py` | Floor / Comment / ThreadData / 用户汇总 |
| `filters.py` | 参与者关键词/等级/标记筛选 |
| `compare.py` | 多帖对比 |
| `report.py` | 单用户报告 Excel + Markdown |
| `config_backup.py` | 配置备份/恢复 |
| `blacklist.py` | 本地标记、优先级、导入导出、合并 |
| `settings.py` | 设置默认值、类型校验、持久化 |
| `theme.py` | 浅色/深色/系统、强调色、内置蓝鱼、颜色映射 |
| `skin_store.py` | 自定义皮肤 ZIP 导入、校验、读取 |
| `cookie_store.py` | Windows DPAPI Cookie |
| `storage.py` | 最近结果 SQLite / DPAPI / 恢复 |
| `errors.py` | 统一错误文案 |
| `export.py` | Excel 导出、导出说明、拆分 |
| `version.py` | 版本唯一来源 |
| `cli.py` | 基础命令行 |

## 3. GUI 结构

`tieba_gui.py` 按职责分块：

- 初始化 / 主窗口 / 状态栏；
- 抓取页；
- 表格查看（回复统计、分帖、楼层、楼中楼、对比）；
- 参与者页（筛选、分页、红绿灯、资料面板）；
- 查用户页；
- 设置页（左侧分类）；
- 对话框 / 快捷键 / 单实例；
- 持久化 / 导出 / 日志 / 主题。

## 4. 测试

| 文件 | 覆盖 |
|---|---|
| `tests/selftest.py` | 离线抓取/导出端到端 |
| `tests/test_page_pb.py` | page protobuf |
| `tests/test_profile_pb.py` | profile protobuf |
| `tests/test_userpost_pb.py` | userpost protobuf |
| `tests/test_modes.py` | 抓取模式分流 |
| `tests/test_settings.py` | 设置持久化 |
| `tests/test_blacklist.py` | 标记优先级 |
| `tests/test_filters.py` | 筛选、身份、曾用昵称 |
| `tests/test_compare.py` | 多帖对比 |
| `tests/test_report.py` | 用户报告 |
| `tests/test_config_backup.py` | 配置备份 |
| `tests/test_follow_probe.py` | 候选探测 |
| `tests/test_floor_depth.py` | 楼中楼深度/去重 |
| `tests/test_storage.py` | SQLite/DPAPI/清理 |
| `tests/test_errors.py` | 错误文案 |
| `tests/test_version.py` | 版本一致性 |

当前：68 个 pytest 通过，selftest 通过。

## 5. 脚本

| 文件 | 作用 |
|---|---|
| `scripts/build_desktop.ps1` | PyInstaller 构建、selftest |
| `scripts/build_android.ps1` | Gradle 构建（暂停） |
| `scripts/sync_android.py` | 核心包同步到 Android |
| `scripts/write_version_info.py` | 生成 version_info |

## 6. Android

- `android/project/app/src/main/python/tieba_reply_stats/` 是生成副本；
- 禁止手改，改源码后执行 `python scripts/sync_android.py`；
- Android 已暂停，不跟进新功能。

## 7. 数据与工具

| 路径 | 说明 |
|---|---|
| `sample/` | 示例 Excel |
| `snapshots/` | 脱敏离线快照 |
| `tools/` | 快照采集/查询、wheel 下载 |
| `assets/` | 图标、版本信息 |
| `使用说明.txt` | 用户手册 |
| `CHANGELOG.md` | 版本记录 |
