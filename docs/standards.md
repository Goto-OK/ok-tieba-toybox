# 开发规范

本文件是项目的“约定”：新增代码、修 bug、发版都按这里执行。  
目标不是追求形式，而是让改动可预测、可测试、可回滚。

## 1. 环境与工具

- Python **3.10+**（CI 用 3.12）；
- 依赖：`openpyxl`、`lxml`（Android 用自带的 BeautifulSoup 兼容层）；
- 开发工具：`pytest`、`ruff`、`mypy`；
- 运行时版本锁定在 `requirements.lock`，开发环境用 `requirements-dev.lock`；
- 统一 UTF-8、LF；`.bat` / `.ps1` 用 CRLF。

```bash
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
```

修改依赖后：更新 `requirements.txt` / `pyproject.toml` 的范围，在干净环境安装，
重新生成两个 `.lock` 文件，并在 CI 验证。

## 2. 代码风格

- 遵循 PEP 8；缩进 4 空格；单行建议 ≤110 字符（`E501` 不强制）；
- 导入顺序：标准库 → 第三方 → 本项目，交给 `ruff` 的 `I` 规则；
- 不用通配符导入；不用 `type(x) is Cls` 决定行为，用显式能力标记
  （例如 `Fetcher.online`）；
- 命名：
  - 模块/函数/变量：`snake_case`
  - 类：`CapWords`
  - 常量：`UPPER_CASE`
  - 私有：`_leading_underscore`
- 公共函数写类型标注；文件开头保留 `from __future__ import annotations`；
- 注释解释“为什么”，不复述代码；中文注释可以。

## 3. 错误处理

- 捕获具体异常，禁止裸 `except:`；
- 只在边界（CLI/GUI/HTTP）把异常转成用户可读信息；
- 不允许静默吞掉错误；至少记录到调用方日志；
- 网络错误、验证码、删帖要区分，提示里说明下一步。

## 4. 日志与隐私

- 核心包不直接 `print`，通过 `CollectOptions.log` 回调输出；
- 日志、异常、截图里**不得出现 Cookie / BDUSS / STOKEN**；
- 提交前检查 `git diff`，确认没有把 Cookie、快照数据、账号信息带进仓库。

## 5. 版本

- 唯一版本源：`tieba_reply_stats/version.py` 的 `__version__`；
- `pyproject.toml` 动态读取；
- `assets/version_info.txt` 由 `scripts/write_version_info.py` 生成，不手改；
- 发版必须同步 `CHANGELOG.md`，规则见 [release.md](release.md)。

## 6. 测试

- 新增解析/协议代码必须能离线测试：
  - 把“构造请求”和“解析响应”拆成 `build_request` / `parse_response`；
  - 用二进制 fixture 或手工编码的字节做断言，不依赖网络。
- 提交前必须通过：

```bash
python -m ruff check .
python -m mypy
python -m pytest
python tests/selftest.py
python scripts/sync_android.py --check
```

- 网络相关功能（游客模式、登录模式、查成分）至少手动冒烟一次；
- 修 bug 时优先补一个能复现的测试。

## 7. 目录与文件

- 核心逻辑只放在 `tieba_reply_stats/`；
- 入口层只做参数/界面/编排，不写解析细节；
- 构建产物、发布目录、APK、快照数据不进 git（见 `.gitignore`）；
- `android/project/app/src/main/python/tieba_reply_stats` 是**生成副本**，
  禁止手改；改完源码执行 `python scripts/sync_android.py`。

## 8. 接口与协议

- 新接口先在 `docs/protocol.md` 记录：URL、方法、参数、认证、限制；
- protobuf 字段编号一旦使用不要改；新增字段用新编号；
- 注释和文档里写清“是否需要 Cookie”“是否匿名可用”。

## 9. Git 约定

- 一个提交只做一件事；提交信息用英文祈使句：
  - `feat: ...` 新功能
  - `fix: ...` 修复
  - `test: ...` 测试
  - `docs: ...` 文档
  - `chore: ...` 工程
- 不提交 `dist/`、`.build/`、`*.apk`、`*.xlsx`、Cookie、日志；
- 发版打 tag：`v1.2.0`；
- 大改动先开分支，完成后合并。

## 10. 完成定义（DoD）

- [ ] `ruff check` 通过
- [ ] `mypy` 通过
- [ ] `pytest` 通过
- [ ] `selftest` 通过
- [ ] 相关文档/CHANGELOG 已更新
- [ ] 没有新增隐私数据或构建产物
- [ ] Android 副本已同步（如改核心）
