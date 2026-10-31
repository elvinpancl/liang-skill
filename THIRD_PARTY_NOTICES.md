# Third-party notices

`liang-skill` 中部分内容校准资源，基于本机已安装的 XBuilderLAB 项目工作树进行改名、适配和整合：

- 内容校准资源：原项目 `XBuilderLAB/cheat-on-content`，MIT License。完整许可见 `LICENSES/XBUILDERLAB-CONTENT-MIT.txt`；独立安装核心时见 `skills/liang-content/LICENSE-MIT.txt`。

这些派生文件继续保留原 MIT 许可与通知。

视频相关 skill 另用到以下第三方内容：

- 视频动效与剪映导出：原项目 `Vincentwei1021/video-shotcraft`（提交 `43bd349a136651865ecfa6ea1cf012f6e957d304`），Apache License 2.0。`skills/liang-promo-jianying/scripts/vendor/mac_draft.py` 原样收录；`skills/liang-promo-beat/assets/hf-lib/` 中 3D 场景与部分转场的数学配方移植自其 Remotion 示例，文件头注明出处。许可全文见各自目录的 `LICENSE-video-shotcraft`、`LICENSE-shotcraft`。
- 剪映草稿生成依赖 `pyJianYingDraft`（Apache License 2.0），由使用者自行安装，本仓库不收录其代码。GSAP 由使用者的工程自带，本仓库不收录。

本仓库其余原创部分适用根目录 `LICENSE`。

## 小红书公开页解析

`skills/liang-content/adapters/perf-data/xhs-explore/` 的公开页解析能力包含来自 [SingularGuyLeBorn/xhs-analytics](https://github.com/SingularGuyLeBorn/xhs-analytics) 的适配，适用 MIT License。完整许可及版权声明见该目录的 `LICENSE-xhs-analytics-MIT.txt`。

该适配器的上游说明还列出了 NanmiCoder/MediaCrawler 和 ReaJason/xhs，作为接口路径与字段的参考；这些项目的许可不由本仓库根许可证替代。

## xkcd 字体

`skills/liang-content/scripts/xkcd-font.css` 内嵌的字体来自 [ipython/xkcd-font](https://github.com/ipython/xkcd-font)，字体元数据署名为 ipython/xkcd-font contributors，适用 Creative Commons Attribution-NonCommercial 3.0 Unported（CC BY-NC 3.0）。完整许可见同目录 `LICENSE-xkcd-font-CC-BY-NC-3.0.txt`，许可链接为 https://creativecommons.org/licenses/by-nc/3.0/ 。本次发布保留原字体资源，未修改字形；它不受核心代码的 MIT 许可覆盖。
