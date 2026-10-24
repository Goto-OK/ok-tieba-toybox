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
- 不再向 `docs/history/` 下的旧规范增加新规则。

## 动手前必须先问

- 任何改动、优化、重构、规范/文档修改，以及我主动想到的小点子，先提出方案；
- 一次问清并让用户三选一：
  - 只写规范；
  - 规范 + 代码；
  - 先不做；
- 未得到选择前，不写规范、不改文档、不改代码、不打包；
- 选“只写规范”：只改 `SPEC.md`；
- 选“规范 + 代码”：先写 `SPEC.md`，随后直接改代码，不再二次确认；
- 选“先不做”：不动文件；
- 不允许“先做后说”；
- 超出批准范围重新询问。

## 硬规则

- **默认不动任何文件**；
- 只有用户明确同意后才写规范/代码；
- 只改需求指定的代码片段，不擅自重构无关模块；
- 需求模糊时先提问，禁止脑补；
- 接口能力/上限/字段/认证必须有证据；未验证标“待验证”；
- 每轮更新 `docs/status.md`；
- 只有明确说“出 exe / 出 APK”才构建。

## UI 改动流程

任何可见 UI 改动，先做文字原型，再让用户三选一：

1. 在对话里给出文字版界面：
   - 窗口层级；
   - 行/列布局；
   - 控件顺序；
   - 空/有数据/错误状态；
   - 最小尺寸和缩放注意点；
2. 一次问清：只写规范 / 规范+代码 / 先不做；
3. 选“只写规范”：只写 `SPEC.md`；
4. 选“规范+代码”：写 `SPEC.md` 后直接改 `.py`，不再二次确认；
5. 选“先不做”：不动文件；
6. 原型后续变更，也重新确认。

## 测试顺序

1. **先测源码**：`python tieba_gui.py`，源码始终是最新代码；
2. 源码通过后，再按需打包 exe 做接近用户的验收；
3. 旧 exe 可能落后于源码，不能拿旧 exe 判断新功能；
4. 涉及 UI/Emoji/DPI 的问题，优先源码复现，再打包确认；
5. 测试记录写入 `docs/test-cases.md`。

## 更新文档维护

- 每次改代码后，在 `CHANGELOG.md` 的 `[未发布]` 下追加用户能看懂的条目；
- 只写行为变化，不写 commit hash、函数名或内部重构；
- 一个功能只写一条，合并重复项；
- 版本发布时：
  1. 更新 `tieba_reply_stats/version.py`；
  2. 运行 `python scripts/write_version_info.py`；
  3. 把 `[未发布]` 整理为 `[x.y.z] - YYYY-MM-DD（未打包/已打包）`；
  4. 新建 `docs/release-notes-vx.y.z.md`；
  5. 更新 `docs/status.md`；
- `CHANGELOG.md` 只保留最近 2~3 个版本，旧版本移到 `docs/changelog-archive.md`；
- 用户版更新说明写“用户会感知的变化”，技术版写接口/内部修复；
- 纯规范改动不进入用户版更新说明，除非影响用户行为；
- 未验证/未实现项必须写进“已知限制”，不得写成已完成。

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
