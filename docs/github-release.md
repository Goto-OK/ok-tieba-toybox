# GitHub 发布清单

适用版本：v1.7.3 及后续版本。

## 1. 仓库公开前

### 清理敏感数据

确认仓库和 Git 历史中没有：

```text
Cookie
BDUSS
STOKEN
TIEBA_SID
WebView2 profile
浏览器导出 Cookie
真实用户数据
xlsx / 日志 / 快照
```

建议扫描：

```bash
git log -p --all | findstr /i "BDUSS STOKEN TIEBA_SID cookie"
```

如果历史中存在真实 Cookie，不能只删当前文件，需要重写历史并更换已泄露的凭据。

### 确认忽略规则

`.gitignore` 必须覆盖：

```text
.build/
dist/
*.xlsx
logs/
cookie*.json
*.cookie
*.key
snapshots/*.jsonl
```

### 确认许可证

- 开源：保留 `LICENSE`，推荐 MIT（当前使用 MIT）；
- 不开源：不要添加 MIT，改为 All rights reserved；
- 第三方组件：保留 `THIRD_PARTY_NOTICES.md`；
- 作者署名：在 `LICENSE`、README、`pyproject.toml`、关于页中保持一致。

## 2. README

必须包含：

- 版本号；
- 一句话介绍；
- 下载和运行方式；
- 功能列表；
- 登录与 Cookie 说明；
- 隐私说明链接；
- 依赖；
- 构建方式；
- 已知限制；
- 免责声明；
- 许可证。

建议放 2~4 张截图，但截图不能包含 Cookie、账号、真实用户隐私。

## 3. Release 资产

推荐只上传：

```text
贴吧回复统计_v1.7.3_绿色版.zip
SHA256SUMS-1.7.3.txt
```

不要把 exe、zip、`_internal` 提交进 Git 仓库。

Release 说明可以直接使用：

```text
docs/release-notes-v1.7.3.md
```

## 4. 版本和 Tag

```text
版本号：v1.7.3
Tag：v1.7.3
标题：贴吧楼层回复统计 v1.7.3
```

版本号唯一来源：

```text
tieba_reply_stats/version.py
```

修改后运行：

```bash
python scripts/write_version_info.py
```

## 5. 发布前检查

```bash
python -m ruff check .
python -m mypy
python -m pytest
python tests/selftest.py
```

Windows 构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_desktop.ps1 -Version 1.7.3
```

确认：

```text
--selftest 通过
绿色包可解压
exe 可启动
WebView2 登录窗口可打开（如环境支持）
```

## 6. 校验文件

Windows PowerShell：

```powershell
Get-FileHash -Algorithm SHA256 "dist\贴吧回复统计_v1.7.3_绿色版.zip"
Get-FileHash -Algorithm SHA256 "dist\贴吧回复统计_v1.7.3\贴吧回复统计.exe"
```

写入：

```text
dist/SHA256SUMS-1.7.3.txt
```

## 7. GitHub 仓库设置

建议填写：

```text
Description: Windows 贴吧楼层/楼中楼统计与 Excel 导出工具
Topics: tieba, excel, statistics, tkinter, windows, python, webview2
```

开启：

```text
Issues
Discussions（可选）
Security advisories
Dependabot alerts
```

## 8. Issue / PR 模板

建议包含：

```text
版本
系统
复现步骤
错误文本
脱敏截图
是否使用登录
```

禁止在 Issue 中粘贴 Cookie。

## 9. 代码签名

当前 exe 没有受信任代码签名证书。

可选：

```text
购买 OV / EV 代码签名证书
继续使用 SHA256 校验
```

自签名证书不能消除 SmartScreen 提示，不要写成“受信任签名”。

## 10. 发布后

- 检查 Release 附件是否可下载；
- 检查 SHA256 是否与附件一致；
- 检查 README 链接是否有效；
- 把 CHANGELOG 的“未发布”整理到对应版本；
- 在 `docs/status.md` 记录成品版本和构建时间；
- 不覆盖旧版本 Release 资产。
