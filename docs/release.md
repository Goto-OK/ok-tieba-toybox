# 发布流程

## 1. 版本规则

- 采用语义化版本：`MAJOR.MINOR.PATCH`；
- 用户可见功能 → MINOR；修复 → PATCH；
- 版本号只有一个来源：`tieba_reply_stats/version.py` 的 `__version__`；
- `pyproject.toml` 动态读取该值；
- `assets/version_info.txt` 由 `scripts/write_version_info.py` 生成（构建脚本会自动调用）。

## 2. 发布前检查

```bash
python -m compileall tieba_reply_stats tieba_gui.py
python -m pytest
python tests/selftest.py
```

- 无 Cookie 抓一个公开帖子，确认游客模式可用；
- 有 Cookie 抓一个含楼中楼的帖子，确认楼中楼/等级/查成分正常；
- 抓取完成后确认“身份补全”结束、参与者 ID 无待补全；
- 检查导出发言、表头筛选、一键红绿灯标记刷新；
- 更新 `CHANGELOG.md`。
- `dist/贴吧回复统计_v1.7.1` 已于 2026-10-23 重建；如再次改源码，发布前必须重新构建。
- 发布压缩包：`dist/贴吧回复统计_v1.7.1_绿色版.zip`；解压后保留完整目录（`_internal` 必需）。
- 当前 exe 使用本地自签名证书，`UnknownError / UntrustedRoot`，不能替代受信任代码签名证书。

## 2.1 1.7.1 发布门禁 / 版本冻结

- 1.7.0 已冻结，不覆盖旧包；
- 当前候选版本：`1.7.1`，已重建 exe/绿色包；
- 1.7.1 必须重新跑 47 项人工验收；通过后才允许打正式发布标签；
- 1.7.1 验收发现的新问题进入 `1.7.2`，不得覆盖已冻结的 1.7.1 包；
- 修复版本流程：改 `tieba_reply_stats/version.py` → 重建 → 重跑自动测试/相关人工用例 → 发布；
- 新功能进入 `1.8.0`；
- 发布前生成并附上 `SHA256SUMS.txt`；
- 自签名 exe 只能标注“本地自签名”，不得写成“受信任签名”。

## 2.2 1.7.3 当前候选

- 当前版本：`1.7.3`，已打包绿色版；
- 发布目录：`dist/OK的贴吧玩具箱_v1.7.3`；
- 绿色包：`dist/OK的贴吧玩具箱_v1.7.3_绿色版.zip`；
- 校验：`dist/SHA256SUMS-1.7.3.txt`；
- 用户版更新说明：`docs/release-notes-v1.7.3.md`；
- 技术版更新：`CHANGELOG.md` 的 `[1.7.3]`；
- 真实登录、验证码、WebView2 跨重启仍需人工验收；
- 1.7.1 为已冻结旧成品，不覆盖。

## 3. 桌面版

```powershell
./scripts/build_desktop.ps1 -Version 1.7.3
# 若提示“禁止运行脚本”：
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_desktop.ps1 -Version 1.7.3
```

脚本会：

1. 读取/校验版本号；
2. 准备 `.build\venv` 并安装 PyInstaller；
3. 构建 `--onedir --windowed`；
4. 复制到 `dist\OK的贴吧玩具箱_v<版本>`；
5. 复制 `使用说明.txt`、启动 bat；
6. 运行 `--selftest`。

手工安装到发布目录（当前习惯）：

```text
OK的贴吧玩具箱_v1.7.3/
├─ OK的贴吧玩具箱.exe
├─ _internal/
├─ 使用说明.txt
├─ 启动.bat
└─ 以管理员身份运行.bat
```

然后：

- 运行 exe `--selftest`，确认退出码 0；
- 更新桌面快捷方式指向新 exe，并设置 `IconLocation = exe,0`；
- 重新生成 `OK的贴吧玩具箱_v1.7.3_绿色版.zip`；
- 旧版本目录保留一个，其余清理。

## 4. Android 版（暂停）

当前暂停 Android 发布；以下流程仅作历史参考，不作为本次发布要求。

前置：JDK 17、Android SDK 34、Gradle 8.7（路径见 `scripts/build_android.ps1` 参数）。

```powershell
./scripts/build_android.ps1
```

脚本会：

1. `python scripts/sync_android.py` 同步核心；
2. `gradle :app:assembleDebug`；
3. 复制 APK 到 `dist\贴吧统计_debug.apk`。

真机验证：

- 安装 APK；
- 启动后应进入网页界面；
- 无 Cookie 抓公开帖；
- 有 Cookie 抓楼中楼；
- 下载 Excel 到手机；
- 失败时 `adb logcat -s TiebaStats python.stdout python.stderr`。

## 5. 发布检查清单

- [ ] 版本号、version_info 已更新
- [ ] CHANGELOG 已更新
- [ ] selftest 通过
- [ ] 游客模式冒烟通过
- [ ] 匿名 + 关注增强冒烟通过
- [ ] exe `--selftest` 返回 0
- [ ] 快捷方式图标正常
- [ ] zip 已重新生成
- [ ] APK 已更新（仅当恢复 Android 时）
- [ ] 旧版本目录清理

## 6. 回滚

- 源码：切回上一个 git tag/commit；
- 桌面：快捷方式指回上一个版本目录；
- Android：安装上一个 APK（debug 签名可覆盖安装）。
