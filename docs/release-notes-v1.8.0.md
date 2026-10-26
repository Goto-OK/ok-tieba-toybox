# OK的贴吧玩具箱 v1.8.0

Windows 贴吧楼层、楼中楼与用户分析工具。

作者：OK  
AI 协作：DeepSeek

## 版本说明

- 版本：1.8.0
- 状态：已打包，未发布
- 前一个正式发布：1.7.3
- 本版本是 1.7.3 之后的结构重构与健壮性修复版本

## 重点变化

### 数据安全与恢复

- 用户资料、发言、关注探测接口统一使用 HTTPS；
- 内置登录备份清理/恢复失败会重试 3 次，失败时保留 `.bak` 并写入启动警告和运行日志，不再静默丢弃；
- 畸形 protobuf 截断数据改为报错，不再越界读取或静默返回空结果；
- 页数硬上限固定为 500，避免服务端总页数驱动无限翻页；
- 楼中楼跨页按 pid 去重；
- 停止按钮可以关闭身份补全弹窗；
- 补全等级的后台线程不再直接操作 Tk 控件。

### 登录与验证码

- 登录更新后，未完成的帖子会排队重试；
- 重试按钮在恢复旧结果后正确恢复可用；
- 真实双账号切换与验证码后读取完整 Cookie 已完成人工复核。

### 工程与可维护性

- GUI 主类拆分为 20 个职责模块，App 主类降到约 2,300 行；
- `_build_ui`、参与者页、查用户页、登录区、资料详情等长方法拆分为多个构建器；
- 日志内核拆出为 `tieba_gui_logging.py`；
- 通用辅助函数集中到 `tieba_gui_utils.py`；
- ruff 启用 bugbear、C90、S；mypy 覆盖全部 GUI 模块；
- 修复 pip 安装包缺少 GUI 拆分模块的问题，wheel 已实际安装并验证 `import tieba_gui`。

## 验证

```text
ruff check . --no-cache   通过
mypy                      51 个源文件通过
pytest                    146 passed
tests/selftest.py         通过
CI                        success
```

## 下载与安装

本版本已在本机构建，尚未上传 GitHub Release。构建目录：

```text
dist/OK的贴吧玩具箱_v1.8.0/
    OK的贴吧玩具箱.exe
    _internal/
```

绿色包与校验文件（两个 zip 内容相同，任选一个下载）：

```text
dist/ok-tieba-toybox_v1.8.0.zip
dist/OK的贴吧玩具箱_v1.8.0.zip
dist/SHA256SUMS-1.8.0.txt
```

必须保留 `_internal` 目录，不能只复制 exe。

## 已知限制

- 当前 exe 未做代码签名，SmartScreen 可能提示未知发布者；
- 真实账号环境、验证码频率与接口行为仍可能受百度服务端限制；
- Android 不跟进本版本 UI；
- CLI 不跟 GUI 新功能。
