# 规范索引

用途：新会话/新任务先读这一份，再按需打开对应分类文档。  
原则：**索引不复制正文，正文只有一个来源。**

## 1. 启动顺序

```text
spec-index.md
→ status.md（判断做没做）
→ 目标功能对应文档（只读相关章节）
```

不要默认通读 `docs/` 全部文件。

## 2. 硬规则

- 默认只改规范，不改代码；
- 只有明确说“开始实现 / 改代码 / 动手”才改 `.py`；
- 只改需求指定的代码片段，不擅自重构无关模块；
- 需求模糊时先提问，禁止脑补；
- 接口能力/上限/字段/认证必须有证据，未验证标“待验证”；
- 每轮更新 `status.md`；
- 只有明确说“出 exe / 出 APK”才构建。

## 3. 文档地图

| 主题 | 唯一正文 | 什么时候读 |
|---|---|---|
| 功能需求 | [requirements.md](requirements.md) | 改功能、加功能、验收 |
| 界面规范 | [ui-spec.md](ui-spec.md) | 改按钮、布局、日志、表格、对话框 |
| 凭据与能力边界 | [credentials.md](credentials.md) | Cookie / BDUSS / 公开关注增强 |
| 接口协议 | [protocol.md](protocol.md) | 抓包、字段、签名、接口证据 |
| 工程规范 | [standards.md](standards.md) | 代码风格、测试、提交 |
| 实现状态 | [status.md](status.md) | 判断规范/源码/测试/成品 |
| 发布流程 | [release.md](release.md) | 出 exe / APK |
| 待办/缺口 | [backlog.md](backlog.md) | 下一步做什么 |
| 研究资料 | [aiotieba-capabilities.md](aiotieba-capabilities.md) | 接口能力调研 |
| 功能草案 | [proposals.md](proposals.md) | 历史设计过程，不作规范 |
| 代码地图 | [code-map.md](code-map.md) | 找模块、看代码边界 |
| 竞品对比 | [market-comparison.md](market-comparison.md) | 横向对比、借鉴优先级 |

## 4. 功能地图

| ID | 功能 | 正文 |
|---|---|---|
| BASE | 抓取、统计、导出、参与者、查用户 | requirements 3.1–3.4 |
| FR-008 | 匿名抓取、关注增强、红绿灯 | requirements 3.6 |
| FR-009 | 参与者筛选 | requirements 3.3 参与者（FR-009） |
| FR-010 | 多帖对比 | requirements 3.8 |
| FR-011 | 单用户报告 | requirements 3.9 |
| FR-012 | 配置备份 / 恢复 | requirements 3.10 |
| FR-013 | ~~吧务删除内容~~（已砍掉） | requirements 3.11 撤销说明 |
| FR-014 | 全量楼中楼 | requirements 3.12 |
| FR-015 | 隐藏关注候选探测 | requirements 3.13 |
| CRED | 凭据分级与能力边界 | credentials + requirements 3.14 |
| UI-001~016 | 按钮、日志、布局、表格、开关、多帖、Emoji、持久化 | ui-spec |
| PROTO | 接口协议与证据 | protocol |
| ENG | 工程规范 | standards |



## 5. 界面规范索引

| ID | 内容 |
|---|---|
| UI-001 | 一键红绿灯按钮文案、宽度、状态 |
| UI-002 | 运行日志位置、最小高度、折叠 |
| UI-003 | 默认窗口、最小窗口、布局 |
| UI-004 | 主导航与子标签 |
| UI-005 | 统一文案 |
| UI-006 | 参与者筛选 |
| UI-007 | 表格与来源列 |
| UI-008 | 查用户 |
| UI-009 | 配置备份 |
| UI-010 | 关注增强 |
| UI-011 | 反馈与状态 |
| UI-012 | 本地标记开关 |
| UI-013 | 多帖切换与导出范围 |
| UI-014 | Emoji 显示与输入 |
| UI-015 | 最近结果持久化 |
| UI-016 | 界面验收 |

## 6. 使用方式

- 只改功能：读 `requirements` 对应 FR + `status`；
- 只改界面：读 `ui-spec` 对应 UI + `status`；
- 只改凭据：读 `credentials` + `requirements` 3.14；
- 只改接口：读 `protocol` 对应接口 + `status`；
- 只做发布：读 `release` + `status`。

## 7. 维护规则

- 新增规范先判断主题，写入唯一正文；
- 索引只加一行链接，不复制正文；
- 同一规则不能在两个文档各写一份；
- 发现重复，先合并到唯一正文，再把另一处改成链接；
- `spec-summary.md` 已废弃，仅保留跳转。

## 8. 修改意见归类

收到修改意见时，先判断“这是行为、界面、凭据、接口，还是工程/状态”，再落到唯一正文。

| 意见类型 | 例子 | 落到哪里 |
|---|---|---|
| 功能行为 | 免登录是否查关注、批量用哪些吧、导出统计口径 | `requirements.md` 对应 FR |
| 界面呈现 | 按钮文字/宽度/截断、日志被挡住、窗口大小、表格列 | `ui-spec.md` 对应 UI |
| 凭据/权限 | Cookie、BDUSS、公开关注增强、隐藏关注边界 | `credentials.md` |
| 接口协议 | 请求字段、签名、分页、返回结构、实测证据 | `protocol.md` |
| 工程 | 测试、构建、版本、代码风格 | `standards.md` / `release.md` |
| 状态 | 做没做、成品版本、已知差距 | `status.md` |
| 代码位置 | 模块职责、重复副本 | `code-map.md` |

具体到“一键红绿灯”：

- “免登录只查发言，不查关注” → `requirements.md` FR-008；
- “按钮显示成‘一键红绿灯（’” → `ui-spec.md` UI-001；
- “日志被窗口挡住” → `ui-spec.md` UI-002；
- “免登录资料页为什么请求关注” → `requirements.md` FR-008 的“资料查看与红绿灯解耦”；
- “有 Cookie 能不能看隐藏关注” → `credentials.md`。

归类规则：

1. 一条规则只写一次正文，其他文档只放链接；
2. 跨“行为 + 界面”时，行为进 requirements，呈现进 ui-spec；
3. 跨“功能 + 凭据”时，功能验收进 requirements，凭据矩阵进 credentials；
4. 新增功能先分配 FR/UI ID，再更新本索引；
5. 影响实现时同步 `status.md`；
6. 发现重复，先合并到唯一正文，再把另一处改成链接。

