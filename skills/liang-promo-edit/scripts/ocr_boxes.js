// 用 macOS 系统的 Vision 框架识别图片里的中英文，带坐标输出。
// 用法：osascript -l JavaScript ocr_boxes.js 图1.jpg 图2.jpg ...
// 输出：每张图一行 JSON：{"file": 文件名, "items": [{"t": 文字, "c": 置信度, "x", "y", "w", "h"}]}
// 坐标是 0–1 的比例，原点在左上角。
ObjC.import('Foundation');
ObjC.import('Vision');
function r3(v) { return Math.round(v * 1000) / 1000; }
function run(argv) {
  const out = [];
  for (const p of argv) {
    const url = $.NSURL.fileURLWithPath(p);
    const handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $.NSDictionary.dictionary);
    const req = $.VNRecognizeTextRequest.alloc.init;
    req.recognitionLevel = 0; // 0 是精确模式
    req.recognitionLanguages = $(['zh-Hans', 'en-US']);
    req.usesLanguageCorrection = false;
    handler.performRequestsError($([req]), null);
    const res = req.results;
    const items = [];
    const n = res ? res.count : 0;
    for (let i = 0; i < n; i++) {
      const o = res.objectAtIndex(i);
      const cand = o.topCandidates(1).objectAtIndex(0);
      const bb = o.boundingBox;
      items.push({
        t: cand.string.js,
        c: r3(cand.confidence),
        x: r3(bb.origin.x),
        y: r3(1 - bb.origin.y - bb.size.height),
        w: r3(bb.size.width),
        h: r3(bb.size.height),
      });
    }
    out.push(JSON.stringify({ file: p.split('/').pop(), items: items }));
  }
  return out.join('\n');
}
