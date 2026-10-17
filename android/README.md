# 贴吧统计 Android 版（Chaquopy + WebView）

这是把 `tieba_reply_stats` 核心打包进 Android 的版本：

```
Android Activity（Java）
  └─ WebView  →  http://127.0.0.1:<port>
        └─ Python（Chaquopy）本地 HTTP 服务
              ├─ 抓取/解析/楼中楼/等级
              ├─ profile / userpost protobuf
              └─ openpyxl 导出 Excel
```

## 安装

- 系统要求：Android 7.0（API 24）及以上，arm64 手机；
- 安装 `贴吧统计_debug.apk`（需要允许“安装未知来源应用”）；
- 这是 **debug 签名**，仅用于自己测试；要分发需要自己生成 release 签名。

## 使用

1. 打开 App；
2. 「抓取」页粘贴贴吧 Cookie（含 `BDUSS`），点「保存 Cookie」；
3. 粘贴帖子链接（每行一个），设置最多页数 / 是否抓楼中楼 / 是否导出；
4. 点「开始统计」，看运行日志和进度；
5. 「参与者」页点某个人看关注贴吧 + 最近发言；
6. 「表格」页看回复统计 / 楼层明细 / 楼中楼明细；
7. 「查成分」页按用户名 / 用户ID / 昵称查询；
8. 「设置」页维护黑名单（红/黄/绿）和表格标色；
9. 「下载 Excel」保存到手机的下载目录。

Cookie 保存在 App 私有目录 `files/cookie.json`（明文，仅本机可用）。

## 游客模式（无 Cookie）

Cookie 可以留空，直接抓公开帖子：
- 楼层、每层前 10 条楼中楼、参与者、等级；
- 用户最近发言、基本信息。
完整楼中楼（超过 10 条）、关注列表、完整资料仍需 Cookie。

## 已知限制（第一版）## 已知限制（第一版）

- 无后台服务：App 退到后台久了，长任务可能被系统暂停；
- 大帖子（几万楼）会占较多内存，建议先用「最多页数」限制；
- Android 版界面是手机网页，功能比 Windows 桌面版少（暂无快照、一键红绿灯批量、导入导出 Excel 等）；
- `lxml` 在 Android 不可用，项目里带了一个基于 BeautifulSoup 的 `lxml.html` 兼容层（只实现解析用到的 XPath 子集）；
- 如果启动后白屏，用 `adb logcat -s TiebaStats python.stdout python.stderr` 看错误。

## 重新构建

需要 JDK 17、Android SDK（platform 34、build-tools 34）、Gradle 8.7。

```bash
# Windows（本机路径示例）
set JAVA_HOME=E:\android-build\jdk-17.0.12+7
set ANDROID_HOME=E:\android-build\sdk
E:\android-build\gradle-8.7\bin\gradle.bat -p E:\android-build\tieba-app :app:assembleDebug
```

APK 输出：

```
E:\android-build\tieba-app\app\build\outputs\apk\debug\app-debug.apk
```

更新 Python 代码后，需要把 `tieba-reply-stats/tieba_reply_stats` 重新复制到：

```
android/app/src/main/python/tieba_reply_stats
```

## 目录

```
app/src/main/java/com/tieba/stats/MainActivity.java   启动 Python + WebView
app/src/main/python/android_server.py                 本地 HTTP 服务和 API
app/src/main/python/lxml/                             lxml.html 兼容层
app/src/main/python/tieba_reply_stats/                核心代码
app/src/main/python/web/index.html                    手机网页界面
```
