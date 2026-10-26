# 贴吧用户-贴吧 快照数据

这个目录存放**离线快照**：某个用户在某个吧的等级 / 经验 / 是否关注。

> 本文中的 uid、用户名、昵称、吧名、帖子 tid 均为脱敏示例，不对应真实用户。

用途：给"候选吧名单 + 等级检查"做数据基础。对方隐藏关注列表时，实时接口拿不到完整列表，
但历史抓到的这些记录可以回答"他以前在 X 吧是什么等级"。

## 文件

### `user_bars.jsonl`

每行一条记录：

```json
{"ts":"2026-01-01T00:00:00+08:00","uid":"100000001","bar":"示例吧","level":13,"exp":null,"source":"thread_floor","pid":"100000000001"}
```

| 字段 | 说明 |
|---|---|
| `ts` | 抓取时间（带时区） |
| `uid` | 贴吧数字用户 ID |
| `bar` | 吧名（不带“吧”后缀；本身带“吧”的名字保持原样） |
| `level` | 该用户在吧内的等级；`null` 表示只知道关注、不知道等级 |
| `exp` | 经验值（目前只有 `follow_self` 快照有） |
| `source` | 数据来源，见下表 |
| `pid` | 仅 `thread_floor` 有，楼层 pid |

| source | 含义 | 覆盖范围 |
|---|---|---|
| `follow_self` | 用本机 Cookie 拉的**自己**完整关注列表 | 完整，带等级+经验 |
| `thread_floor` | 帖子里该用户作为楼层的等级 | 单吧（帖子所在吧） |
| `panel` | 用户面板 `honor.grade` | 不完整，通常 5~10 个吧 |
| `like_forum` | 客户端 profile 的 `likeForum` | 固定 6 个吧，通常无等级 |

### `users.jsonl`

用户资料快照：

```json
{"ts":"...","uid":"100000001","username":"example_user","nickname":"示例昵称","post_num":123,"priv_like":3,"fans":12,"concern":34,"source":"panel+profile"}
```

`priv_like=3` 表示对方隐藏了关注列表。

## 采集

```bash
python tools/collect_snapshot.py \
  --threads 1234567890,1234567891 \
  --users 100000002,100000001
```

- `--threads`：帖子 tid，抓楼层作者在该吧的等级；
- `--users`：用户 uid 或用户名，抓面板 + 客户端 profile；
- 数据会与已有文件合并（按 `uid+bar+source` 去重，保留较新的）。

## 查询

```bash
python tools/snapshot_query.py --uid 100000002 --bars 示例吧,测试吧
```

只回答快照里**已有**的 bar；没抓过的 bar 返回“未知”。

## 注意

- 快照是**历史数据**，等级/经验可能已经变化；
- 隐藏关注**无法**通过任何公开接口枚举完整列表，快照只能覆盖抓到过的吧；
- 想扩大覆盖：多抓目标用户发过言的帖子、多跑 `--users`、定期增量更新。
