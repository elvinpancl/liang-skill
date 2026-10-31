"""剪映文字字体。

剪映 Mac 11.4 实测（2026-10-21）：
- 字库里没有的字体，把 ttf 打包进草稿不生效；文字素材的 font_path 直接指向
  系统字体文件（例如 Lantinghei.ttc）才显示。
- ttc 按第 0 个字形渲染。兰亭黑的第 0 个是中黑。
- 用户在字体面板另选字体后，回不到这个系统字体，只能重新生成草稿。

改写必须在 script.save() 之后、macify 之前：macify 会把 draft_content.json
同步成 draft_info.json。
"""

from __future__ import annotations

import json
from pathlib import Path


def patch_text_fonts(content_path: str | Path, mapping: dict[str, tuple[str, str]]) -> int:
    """mapping：文字素材 id → (字体文件绝对路径, 显示名)。返回改写条数，数量不符直接报错。"""
    content_path = Path(content_path)
    data = json.loads(content_path.read_text(encoding="utf-8"))
    patched = 0
    for text in data["materials"]["texts"]:
        if text["id"] not in mapping:
            continue
        path, title = mapping[text["id"]]
        content = json.loads(text["content"])
        for style in content["styles"]:
            style["font"] = {"id": "", "path": path}
        text["content"] = json.dumps(content, ensure_ascii=False)
        text.update(font_path=path, font_id="", font_resource_id="", font_name=title,
                    font_title=title, font_source_platform=0, fonts=[])
        patched += 1
    if patched != len(mapping):
        raise RuntimeError(f"字体改写数量不符：{patched}/{len(mapping)}")
    content_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return patched
