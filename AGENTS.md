# 项目工作约定

本文件给后续会话/代理使用，目的是少读无关上下文、不返工。

## 启动时读什么

1. 先读 [docs/spec-index.md](docs/spec-index.md)（规范入口）；
2. 需要判断做没做，读 [docs/status.md](docs/status.md)；
3. 需要改代码，再读目标功能正文 + [docs/code-map.md](docs/code-map.md)；
4. 不要默认通读 `docs/` 全部文件。

## 硬规则

- **默认只改规范，不改代码**；
- 只有用户明确说“开始实现 / 改代码 / 动手”才改 `.py`；
- **只改需求指定的代码片段**，不擅自重构无关模块；
- 需求模糊时先提问，禁止脑补；
- 接口能力/上限/字段/认证必须有证据（源码或实测），未验证标“待验证”；
- 每轮更新 `docs/status.md`（规范 / 源码 / 测试 / 成品）；
- 只有明确说“出 exe / 出 APK”才构建。

## 常用检查

```bash
python -m ruff check .
python -m mypy
python -m pytest
python tests/selftest.py
python scripts/sync_android.py --check
```

## 代码边界

- 核心包：`tieba_reply_stats/`；
- GUI：`tieba_gui.py`；
- Android 核心副本是生成的，禁止手改，用同步脚本；
- 不提交 Cookie、`dist/`、`.build/`、APK、xlsx、快照数据。
