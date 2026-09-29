# -*- coding: utf-8 -*-
"""measure_layout.py · 量「游戏在当前分辨率下到底怎么渲染」（分辨率适配实验用）

输入一张截图，输出：
  A. 内容区 bbox（非纯黑区域）——判断游戏是「留黑边」还是「全屏铺满」
  B. OCR 全部文字 + 中心坐标 —— 和 1080×1920 基线的地标逐个对比
     ⇒ 判断游戏是「等比缩放渲染」还是「重排 UI」

用法：
  python measure_layout.py <截图.png> [参照json]
  不带参照就只打印；带参照（先前存过的 OCR 结果）会做差值对比。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import numpy as np  # noqa: E402
from rapidocr_onnxruntime import RapidOCR  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def content_bbox(img):
    """非纯黑内容的 bbox（容忍 JPEG/PNG 噪声：亮度 < 10 算黑）"""
    g = img.mean(axis=2)
    rows = np.where(g.max(axis=1) > 10)[0]
    cols = np.where(g.max(axis=0) > 10)[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    return [int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1]


def main():
    path = sys.argv[1]
    ref_path = sys.argv[2] if len(sys.argv) > 2 else None
    import cv2
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    H, W = img.shape[:2]
    print('截图 %s  %dx%d' % (os.path.basename(path), W, H))

    bb = content_bbox(img)
    if bb is None:
        print('⚠ 整张图接近全黑')
    else:
        x0, y0, x1, y1 = bb
        print('A. 内容区 bbox = [%d,%d][%d,%d]  %dx%d  (占比 %.3f x %.3f)'
              % (x0, y0, x1, y1, x1 - x0, y1 - y0, (x1 - x0) / W, (y1 - y0) / H))
        ar = (x1 - x0) / float(y1 - y0)
        print('   内容宽高比 = %.4f  (9:16=%.4f)' % (ar, 9 / 16.0))

    ocr = RapidOCR()
    res, _ = ocr(img)
    items = []
    for box, txt, conf in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        cx, cy = sum(xs) / 4.0, sum(ys) / 4.0
        items.append({'t': txt, 'x': round(cx, 1), 'y': round(cy, 1),
                      'w': round(max(xs) - min(xs), 1), 'conf': round(float(conf), 2)})
    items.sort(key=lambda d: (d['y'], d['x']))
    out = {'screen': [W, H], 'content_bbox': bb, 'items': items}
    jpath = os.path.join(HERE, 'layout_%dx%d.json' % (W, H))
    with open(jpath, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('B. OCR %d 条（已存 %s）' % (len(items), os.path.basename(jpath)))
    for it in items:
        print('   (%6.1f,%6.1f) w=%5.1f c=%.2f  %s' % (it['x'], it['y'], it['w'], it['conf'], it['t']))

    if ref_path and os.path.exists(ref_path):
        ref = json.load(open(ref_path, encoding='utf-8'))
        print('C. 与参照（%dx%d）对比：同名地标坐标差' % tuple(ref['screen']))
        rmap = {}
        for it in ref['items']:
            rmap.setdefault(it['t'], []).append(it)
        for it in items:
            cands = rmap.get(it['t'])
            if not cands:
                continue
            best = min(cands, key=lambda r: abs(r['x'] - it['x']) + abs(r['y'] - it['y']))
            print('   %-14s (%6.1f,%6.1f) → (%6.1f,%6.1f)  Δ=(%+6.1f,%+6.1f)'
                  % (it['t'][:14], best['x'], best['y'], it['x'], it['y'],
                     it['x'] - best['x'], it['y'] - best['y']))


if __name__ == '__main__':
    main()
