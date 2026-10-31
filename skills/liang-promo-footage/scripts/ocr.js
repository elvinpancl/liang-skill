// 用 macOS 系统的 Vision 框架识别图片里的中英文。
// 用法：osascript -l JavaScript ocr.js 图1.jpg 图2.jpg ...
// 输出：每张图一段，以「== 文件名」开头；同一行上的文字块用「 | 」连接，行按从上到下排。
ObjC.import('Foundation');
ObjC.import('Vision');
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
    for (let i = 0; i < res.count; i++) {
      const o = res.objectAtIndex(i);
      const cand = o.topCandidates(1).objectAtIndex(0);
      const bb = o.boundingBox;
      items.push({ y: bb.origin.y + bb.size.height / 2, x: bb.origin.x, t: cand.string.js });
    }
    items.sort((a, b) => (Math.abs(a.y - b.y) > 0.008 ? b.y - a.y : a.x - b.x));
    const lines = [];
    let cur = [], cy = null;
    for (const it of items) {
      if (cy !== null && Math.abs(it.y - cy) <= 0.008) cur.push(it.t);
      else { if (cur.length) lines.push(cur.join(' | ')); cur = [it.t]; cy = it.y; }
    }
    if (cur.length) lines.push(cur.join(' | '));
    out.push('== ' + p.split('/').pop() + '\n' + lines.join('\n'));
  }
  return out.join('\n');
}
