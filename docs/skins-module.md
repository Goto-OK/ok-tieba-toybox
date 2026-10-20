# S2 皮肤模块（暂不启用）

状态：独立模块候选；主程序 1.6.0 不包含、不加载、不打包。

## 目的

把内置鲸鱼女仆、自定义皮肤包、横幅、侧图、角色动画移出主程序，单独测试，避免主程序上下文、依赖、素材和安装包膨胀。

## 边界

- 不进入 `tieba_gui.py` / `tieba_reply_stats` 主包；
- 不参与主程序构建；
- 不默认读取 `%APPDATA%\TiebaReplyStats\skins`；
- 单独目录、单独测试、单独素材许可；
- 主程序只保留 S1：浅色/深色/跟随系统 + 强调色。

## 既有素材

- 鲸鱼女仆：`assets/skins/whalemaid`；
- 自定义皮肤：`skin_store.py`；
- 动画帧：`assets/skins/whalemaid/frames`；
- 许可：见 `THIRD_PARTY_NOTICES.md`。

## 后续讨论

- 是否做成独立插件/可选安装包；
- 是否保留自定义 ZIP；
- 是否保留动画；
- 是否继续内置角色素材。

在决定前，主程序不引用这些文件。
