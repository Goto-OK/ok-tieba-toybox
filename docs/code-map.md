# 代码地图与整理记录

最后更新：2026-10-19  
原则：只盘点，不擅自重构。任何结构调整都要单独提需求。

## 1. 入口

| 文件 | 作用 |
|---|---|
| `tieba_gui.py` | Windows tkinter GUI，约 2970 行 |
| `tieba_stats.py` | CLI 包装，18 行 |
| `android/project/.../android_server.py` | Android 本地 HTTP 服务 |
| `scripts/build_desktop.ps1` | 桌面构建 |
| `scripts/build_android.ps1` | APK 构建 |

## 2. 核心包

| 模块 | 行数 | 作用 |
|---|---:|---|
| `fetch.py` | 406 | HTTP、Cookie、重试、缓存 |
| `parse.py` | 590 | 网页楼层/楼中楼解析（lxml） |
| `page_pb.py` | 440 | 匿名 `page` protobuf |
| `pbapi.py` | 226 | `page_pc` / `nestedFloor` 补等级 |
| `profile.py` | 497 | 资料、关注、最近发言 |
| `profile_pb.py` | 192 | 客户端 profile protobuf |
| `userpost_pb.py` | 224 | 客户端 userpost protobuf |
| `collect.py` | 432 | 抓取编排、模式分流 |
| `models.py` | 157 | Floor / Comment / ThreadData |
| `export.py` | 489 | Excel 导出 |
| `blacklist.py` | 161 | 本地标记、Excel 导入导出 |
| `settings.py` | 55 | 通用设置 |
| `cookie_store.py` | 133 | Windows DPAPI Cookie |
| `follow_probe.py` | 144 | 隐藏关注候选探测（FR-015） |
| `version.py` | 3 | 版本唯一来源 |
| `cli.py` | 209 | 命令行 |

## 3. 测试

| 文件 | 覆盖 |
|---|---|
| `tests/selftest.py` | 端到端离线抓取/导出 |
| `tests/test_page_pb.py` | page protobuf |
| `tests/test_profile_pb.py` | profile protobuf |
| `tests/test_userpost_pb.py` | userpost protobuf |
| `tests/test_modes.py` | 模式分流 |
| `tests/test_settings.py` | 模式/设置持久化 |
| `tests/test_blacklist.py` | 标记优先级 |
| `tests/test_follow_probe.py` | 候选探测 |
| `tests/test_version.py` | 版本一致性 |

当前：32 个 pytest 通过，selftest 通过。

## 4. 脚本

| 文件 | 作用 |
|---|---|
| `scripts/build_desktop.ps1` | PyInstaller 构建、selftest |
| `scripts/build_android.ps1` | 同步核心、Gradle 构建 |
| `scripts/sync_android.py` | 核心包同步到 Android |
| `scripts/write_version_info.py` | 生成 version_info |

## 5. Android

- `android/project/app/src/main/python/tieba_reply_stats/` 是**生成副本**；
- 不要手改，改源码后执行 `python scripts/sync_android.py`；
- 当前副本 17 个文件，与源码一致；
- Android UI 仍是旧版，模式选择暂缓。

## 6. 数据与工具

| 路径 | 说明 |
|---|---|
| `snapshots/` | 用户-吧等级快照，独立脚本，未接界面 |
| `tools/collect_snapshot.py` | 快照采集 |
| `tools/snapshot_query.py` | 快照查询 |
| `sample/` | 示例 Excel |

## 7. 重复与生成物

- 唯一重复：Android 核心副本（由同步脚本维护）；
- `dist/`、`贴吧回复统计_v*/`、`.build/`、APK、zip 均为构建/发布产物，已在 `.gitignore`；
- `__pycache__/`、pip 临时目录已清理/忽略。

## 8. 本次整理

- 删除 pip 临时目录：`pip-build-tracker-*`、`pip-install-*`、`pip-ephem-wheel-cache-*`；
- `.gitignore` 增加对应规则；
- **没有改任何业务代码**；
- 没有移动文件、没有拆分 GUI。

## 9. 可选的后续整理（需单独批准）

| 候选 | 价值 | 风险 |
|---|---|---|
| 拆分 `tieba_gui.py` | 可维护性 | 高，容易引入回归 |
| 合并 `pbapi` / `page_pb` 等级逻辑 | 减少重复 | 中，影响登录/匿名两条链路 |
| 快照接入界面 | 功能增强 | 中，需要新规范 |
| 清理旧版本目录 | 磁盘空间 | 低，但属于发布产物 |

这些都没有做，等你明确指定。
