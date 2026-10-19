# 凭据说明：Cookie、BDUSS、STOKEN

## 1. 一句话

- **Cookie 是整段字符串**；
- **BDUSS 是登录态的核心字段**；
- **STOKEN 是敏感操作的安全令牌**，属于 Cookie 的一部分。

## 2. 关系

```text
Cookie: BAIDUID=...; BDUSS=...; STOKEN=...; PSTM=...; ...
```

| 字段 | 作用 | 普通抓取 | 吧务删除内容 |
|---|---|---|---|
| `BDUSS` | 证明登录账号 | **必需** | 必需 |
| `STOKEN` | 敏感操作令牌 | 通常不需要 | **必需** |
| `BAIDUID` | 浏览器/设备标识 | 可选 | 可选 |
| `PSTM` | 时间戳 | 可选 | 可选 |
| 其他 | 统计/风控 | 可选 | 可选 |

## 3. 我们说的“Cookie”指什么

指浏览器 `Cookie` 请求头里的**整段**：

```text
BDUSS=xxx; STOKEN=xxx; BAIDUID=xxx
```

不是某一个单独的值。

## 4. 实际需要多少

### 普通抓取（登录模式）

- 代码只校验 `BDUSS`；
- 请求时会把用户粘贴的整段 Cookie 都带上；
- 只贴 `BDUSS=...` 通常也能登录，但**整段更稳**，也更接近真实浏览器；
- 只贴 BDUSS 的好处是少暴露 STOKEN，坏处是吧务功能用不了。

### 吧务删除内容（FR-013）

- 必须有吧务权限；
- 必须有 `STOKEN`；
- 可以从整段 Cookie 自动解析；
- 没有时手动补。

### 免登录模式

- 不读取、不发送任何 Cookie；
- 不需要 BDUSS / STOKEN。

## 5. 软件行为

- 登录 Cookie 输入框：接受整段或只写 `BDUSS=...`；
- `parse_cookie_input` 会拆成 `name -> value`；
- 普通请求带上全部字段；
- 登录校验只看 `BDUSS`；
- 吧务功能额外检查 `STOKEN`；
- 所有凭据本机 DPAPI 保存，不写日志、不导出、不进配置备份。

## 5.5 安全性与用户接受度

### 方便程度

```text
整段 Cookie（一次复制） > 只填 BDUSS（要定位一行） > 免登录（不用填）
```

### 安全程度（最小权限原则）

```text
免登录（无凭据） > 只填 BDUSS（单一登录态） > 整段 Cookie（含 STOKEN 等）
```

但要强调：

- **BDUSS 不是只读令牌**，它本身就是登录态，能代表账号做很多事；
- 只是相比“整段 Cookie 还带 STOKEN”，暴露面小一些；
- 整段 Cookie 里如果有 STOKEN，泄露后还能操作吧务后台，风险更高。

### 用户接受度

- 整段 Cookie：操作最少，但“一大串”看着吓人，用户会担心把账号交出去；
- 只填 BDUSS：多一步，但可以明确告诉用户“不交出 STOKEN”，信任感更好；
- 免登录：接受度最高，代价是每层楼中楼只有前 10 条。

### 产品建议

- 默认：免登录；
- 登录：推荐只填 `BDUSS`，并说明“普通抓取不需要 STOKEN”；
- 吧务：再单独要 `STOKEN`（或从整段 Cookie 自动解析）；
- 不要求普通用户为了抓帖子交出整段 Cookie。

## 6. 安全建议

- 只做普通抓取：可以只贴 `BDUSS=...`，减少暴露；
- 要用吧务功能：再贴整段（含 STOKEN）；
- 不要把整段 Cookie / STOKEN 发聊天、截图、提交仓库；
- STOKEN 会过期，重新登录会变；
- BDUSS / STOKEN 通常是 HttpOnly，`document.cookie` 可能读不到，用开发者工具看。

## 7. 常见误解

- “STOKEN 是另一个 API” → 不是，它是 Cookie 字段；
- “有 STOKEN 就不需要 Cookie” → 不是，HTTP 仍然要发 Cookie；
- “Cookie 就是 BDUSS” → 不准确，BDUSS 只是其中一项；
- “免登录也要 Cookie” → 不需要，免登录模式不发送 Cookie。
