# -*- coding: utf-8 -*-
"""离线 OCR 一张 PNG，把所有识别文本打出来（用于验证悬浮条有没有被截进画面）。

用法：python _verify/_ocr_png.py <png> [关键词...]
命中关键词 -> 打印 HIT，返回码 10；没命中 -> 返回 0。
"""
import sys
import io

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np
import cv2
from rapidocr_onnxruntime import RapidOCR

engine = RapidOCR()


def main():
    if len(sys.argv) < 2:
        print('用法: python _ocr_png.py <png> [关键词...]')
        return 2
    path = sys.argv[1]
    keys = sys.argv[2:]
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        print('读不出图:', path)
        return 2
    print('图像: %dx%d' % (img.shape[1], img.shape[0]))
    res, _ = engine(img)
    items = []
    for box, txt, score in (res or []):
        cx = sum(p[0] for p in box) / 4
        cy = sum(p[1] for p in box) / 4
        items.append((cy, cx, txt, score))
    items.sort()
    print('OCR %d 条' % len(items))
    for cy, cx, txt, score in items:
        print('  (%4d,%4d) %.2f  %s' % (cx, cy, score, txt))
    if keys:
        blob = '\n'.join(t for _, _, t, _ in items)
        for k in keys:
            if k in blob:
                print('HIT: 关键词 %r 出现在截图里' % k)
                return 10
        print('MISS: 关键词 %s 都没出现' % keys)
    return 0


if __name__ == '__main__':
    sys.exit(main())
