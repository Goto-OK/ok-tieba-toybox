# 项目工作约定

本文件给后续会话/代理使用，目的是少读无关上下文、不返工。

## 启动时读什么

1. 先读 [SPEC.md](SPEC.md)（唯一实现依据）；
2. 需要判断做没做，读 [docs/status.md](docs/status.md)；
3. 需要改代码，再读目标章节 + [docs/code-map.md](docs/code-map.md)；
4. `docs/` 其余文件是历史资料；与 `SPEC.md` 冲突时以 `SPEC.md` 为准；
5. 不要默认通读 `docs/` 全部文件。

## 修改意见先归类

| 类型 | 归属 |
|---|---|
| 功能行为、统计口径、批量逻辑、按钮/文案 | `SPEC.md` |
| Cookie / BDUSS / 公开关注 | `docs/credentials.md` + `SPEC.md` |
| 接口字段、签名、分页 | `docs/protocol.md` |
| 测试、构建、版本 | `docs/standards.md` / `docs/release.md` |
| 状态、成品 | `docs/status.md` |
| 历史设计过程 | `docs/` 下历史文档，只读 |

规则：

- 一条规则只写一次正文，其他位置只放链接；
- 先改 `SPEC.md`，再改代码；
- 不再向 `requirements.md` / `ui-spec.md` 增加新规则。

## 硬规则

- **默认只改规范，不改代码**；
- 只有用户明确说“开始实现 / 改代码 / 动手”才改 `.py`；
- 只改需求指定的代码片段，不擅自重构无关模块；
- 需求模糊时先提问，禁止脑补；
- 接口能力/上限/字段/认证必须有证据；未验证标“待验证”；
- 每轮更新 `docs/status.md`；
- 只有明确说“出 exe / 出 APK”才构建。

## UI 改动流程

任何可见 UI 改动，先做文字原型，再等用户批准：

1. 在对话里给出文字版界面：
   - 窗口层级；
   - 行/列布局；
   - 控件顺序；
   - 空/有数据/错误状态；
   - 最小尺寸和缩放注意点；
2. 明确问用户“按这个做吗”；
3. 只有用户回复“可以 / 按这个做 / 开始”后，才改 `.py`；
4. 未批准时只改 `SPEC.md`，不写代码；
5. 原型后续变更，也重新确认。

## 测试顺序

1. **先测源码**：`python tieba_gui.py`，源码始终是最新代码；
2. 源码通过后，再按需打包 exe 做接近用户的验收；
3. 旧 exe 可能落后于源码，不能拿旧 exe 判断新功能；
4. 涉及 UI/Emoji/DPI 的问题，优先源码复现，再打包确认；
5. 测试记录写入 `docs/test-cases.md`。

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
- Android 核心副本由同步脚本生成，禁止手改；
- 不提交 Cookie、`dist/`、`.build/`、APK、xlsx、快照数据。
