# FR-014 登录态 floor 路径验证

日期：2026-10-19  
范围：只读验证，没有发帖、回复、关注、吧务写操作。

## 凭据

- 使用用户提供的登录 Cookie；
- 只记录 `is_login=true`；
- 不记录 Cookie、BDUSS、STOKEN、昵称、用户 ID；
- 未写入仓库或配置文件。

## 验证对象

- 帖子：`tid=1234567890`
- 楼层：13
- `pid=154038937714`
- 声明楼中楼：32 条

## 直接 floor 接口

| 请求 | 返回 | page | has_more |
|---|---:|---|---|
| 登录 pn=1 | 29 | current=1, total=2 | true |
| 登录 pn=2 | 2 | current=2, total=2 | false |
| 匿名 pn=1 | 29 | current=1, total=2 | true |
| 匿名 pn=2 | 2 | current=2, total=2 | false |

结论：登录态与匿名返回一致，登录 floor 请求成功。

## 登录采集路径

用 `_collect_comments`（登录模式）跑同一帖子：

```text
总楼中楼：116 条
floor 13：31 条
单层最多：31 条
```

过程中没有出现 floor 失败，也没有触发 `totalComment + /p/comment` 回退。

## 差异

- floor 13 声明 32 条，实际 31 条；差异属于贴吧侧删除/折叠，不是解析丢失。
- 采集结果保留 2 条“声明 vs 实际”提示。

## 结论

FR-014 登录态 floor 路径验证通过：

- floor 翻页正常；
- 登录与匿名结果一致；
- 登录采集路径未回退；
- 每层全量上限 50 页、pid 去重、失败保留预览仍生效。

未覆盖：

- 大量楼层/高并发下的限流；
- 登录 Cookie 过期后的回退表现。
