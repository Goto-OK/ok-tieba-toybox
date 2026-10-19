# aiotieba 能力梳理（研究稿）

状态：研究稿，未实现。  
依据：本机安装的 `aiotieba 4.8.1` 源码（`site-packages/aiotieba`）。

## 1. 先说结论

- **aiotieba 不是百度官方项目**，是第三方（lumina37）写的 Python SDK；
- 它封装的是**贴吧官方客户端/网页的内部接口**，所以能读到很多公开接口读不到的东西；
- 百度**没有对外开放的官方贴吧 API**；
- “查询被删除的发言”确实可以，但**不是普通用户能力**，而是**吧务后台能力**；
- 需要：**吧务权限 + 登录态（通常要 STOKEN）**，不是只有 BDUSS 就行。

## 2. 删除内容相关接口

| 方法 | 作用 | 认证 | 说明 |
|---|---|---|---|
| `get_bawu_postlogs` | 吧务后台帖子管理日志 | 登录 + STOKEN | 看谁在什么时候删/屏蔽了什么 |
| `get_recovers` | 吧务后台恢复列表 | 登录 + 吧务权限 | 可按用户筛选被删内容 |
| `get_recover_info` | 删除内容详情 | 登录 + 吧务权限 | 按 tid / pid 取标题和正文 |
| `recover` | 恢复 / 屏蔽 | 登录 + STOKEN | **写操作**，本项目暂不使用 |
| `del_post` / `del_thread` | 删除回复 / 主题 | 登录 + 吧务权限 | **写操作**，本项目暂不使用 |

### 2.1 后台日志 `get_bawu_postlogs`

- 路径：`GET https://tieba.baidu.com/bawu2/platform/listPostLog`
- 参数：`word`（吧名）、`pn`、`op_type`、`svalue`/`stype`（按被删用户或操作人）、`begin`/`end`；
- 返回 `BawuPostLog`：
  - `title` 标题
  - `text` 文本内容
  - `medias` 媒体
  - `tid` / `pid`
  - `op_type` 操作类型
  - `post_time` 发帖时间
  - `op_user_name` 操作人
  - `op_time` 操作时间
  - `post_portrait` 被删用户头像

### 2.2 恢复列表 `get_recovers`

- 路径：`GET https://tieba.baidu.com/mo/q/manage/getRecoverList`
- 参数：`forum_id`、`pn`、`rn`、`type=1`、`sub_type=1`、可选 `uid`（被删用户）
- 返回 `Recover`：
  - `text` 文本
  - `tid` / `pid`
  - `user` 作者
  - `post` 回复信息（回复类型时）
  - `thread` 主题信息（主题类型时）
  - `op_show_name` 操作人
  - `op_time` 操作时间
  - `content_type` 主题/回复
  - `is_hide` 是否屏蔽

### 2.3 删除详情 `get_recover_info`

- 路径：`GET https://tieba.baidu.com/mo/q/bawu/getRecoverInfo`
- 参数：`forum_id`、`thread_id`、`post_id`、`type=1`、`sub_type`（回复=2，主题=1）
- 返回 `RecoverInfo`：
  - `title` 标题
  - `contents` 正文片段
  - `tid` / `pid`
  - `user` 作者

## 2.4 STOKEN 是什么、在哪找

### 是什么

- `BDUSS`：贴吧登录态的主 Cookie，证明“你是这个账号”；
- `STOKEN`：百度账号的安全令牌，用于吧务后台等敏感操作；
- 两者经常一起出现，但 **STOKEN 权限更高、更敏感**；
- 它不是独立的 API Key，就是 Cookie 里的一个字段：`STOKEN=...`。

### 在哪找（桌面浏览器）

1. 用 Chrome / Edge 登录 `tieba.baidu.com`；
2. 按 `F12` 打开开发者工具；
3. 选 `Application`（应用）→ `Storage` → `Cookies` → `https://tieba.baidu.com`；
4. 在列表里找 `STOKEN`，复制它的 `Value`。

如果列表里没有：

1. 切到 `Network`（网络）→ 刷新页面；
2. 点第一个 `tieba.baidu.com` 请求；
3. 看 `Request Headers` → `Cookie`，里面找 `STOKEN=...`。

注意：

- 有些账号/登录态可能没有 STOKEN；没有就重新登录一次再试；
- STOKEN 会过期，重新登录会变；
- **不要截图、不要发聊天、不要提交到仓库**；
- 软件里应单独保存（DPAPI），且不进入配置备份。

## 3. 限制与风险

- **只有吧务能用**：只能查自己管理的吧；
- **不是所有删除都能查**：受后台保留时间、删除类型、系统删帖等限制；
- **需要 STOKEN**：比 BDUSS 更敏感，不能和普通 Cookie 混在一起；
- **写操作危险**：`recover` / `del_*` 会改变贴吧内容，本项目只考虑只读；
- **隐私与合规**：删除内容仍包含用户发言，不能批量抓取、公开传播或用于骚扰；
- **接口可能变**：这些是内部网页接口，不是稳定开放 API。

## 4. “吃透”计划（规范阶段）

1. **能力清单**：把 99 个 API 按“匿名 / BDUSS / STOKEN”“只读 / 写”分类；
2. **删除内容只读能力**：
   - 按用户查被删回复；
   - 查删除日志；
   - 取详情（标题/正文）；
3. **安全规范**：
   - STOKEN 单独字段、DPAPI 保存、日志脱敏；
   - 明确“只读”，不实现恢复/删除；
   - 使用前做吧务权限探测；
4. **产品规范**：
   - 独立“吧务”入口，还是并入查用户；
   - 结果如何展示、导出；
   - 保留时间与失败提示；
5. **测试**：
   - 用脱敏 JSON/HTML fixture；
   - 不把真实删除内容写进仓库。

## 5. 待确认

- 使用者是否有吧务权限和 STOKEN；
- 只做“按用户查被删发言”，还是也做“全吧删除日志”；
- 是否严格只读（推荐），还是未来考虑恢复；
- 功能入口放哪里。
