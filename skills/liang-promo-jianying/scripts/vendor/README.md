# vendor

`mac_draft.py` 原样取自 [Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) 的 `jianying-export/mac_draft.py`，提交 `43bd349a136651865ecfa6ea1cf012f6e957d304`，Apache License 2.0，全文见 `LICENSE-video-shotcraft`。

本 skill 不改这个文件，差异都在 `../jy_install.py` 里：
- 草稿库和注册表路径改为参数或环境变量。
- 进程检测加上 Mac 版剪映的进程名 `VideoFusion-macOS`。
- 拒绝同名安装，不走原文件里「替换旧草稿」的分支。
