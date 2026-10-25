# 安全问题报告

## 支持版本

当前只维护最新源码版本：

```text
v1.7.3
```

旧版本和旧 exe 不保证修复。

## 报告方式

请优先使用 GitHub 仓库的 **Security → Report a vulnerability**（私密报告）。

如果仓库未开启私密报告，可以新建 Issue，但**不要**在 Issue 中附带：

- 完整 Cookie；
- BDUSS；
- STOKEN；
- TIEBA_SID；
- WebView2 profile；
- 真实账号、手机号或其他个人信息；
- 可被直接利用的账号凭据。

可以只提供：

```text
版本
操作系统
复现步骤
错误文本
脱敏截图
```

## 不在范围内

- 百度贴吧接口本身的行为；
- 验证码无法自动通过；
- 第三方「恋文」服务不可用；
- 用户自己的网络、代理或 WebView2 Runtime 问题；
- 用户把 Cookie 发到公开 Issue 导致的泄露。

## 安全建议

- 不要在共享电脑开启“记住内置登录”；
- 不要提交 Cookie、日志、`profile-meta.json`；
- 从 GitHub Releases 下载，并核对 `SHA256SUMS`；
- 当前 exe 未使用受信任代码签名，SmartScreen 提示不等于文件一定有问题，但仍应核对来源和哈希。
