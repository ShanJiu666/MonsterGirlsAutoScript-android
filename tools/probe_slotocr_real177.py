# -*- coding: utf-8 -*-
"""v1.77 取证③：用**真 OCR 引擎**读真机帧，看槽位行到底出什么文本

前两个探针只裁图/看日志。本探针把 `board_r*.png` 喂**真的 RapidOCR**（本机装了
`rapidocr_onnxruntime`），复现"轮首全屏 OCR"的读数，回答：

  Q1  那一帧上**有没有**「空闲」二字？（帧上肉眼可见 ⇒ OCR 应该读到）
  Q2  读到的话，`explore_slots_free` 会不会给出 >0？（判据本身对不对）
  Q3  若 Q2 是 0/None，是**文本没读到**还是**判据筛掉了**？

⚠ 端侧 OCR 与 PC 的 RapidOCR 是**同一个 ONNX 引擎**（`_AndroidOcr` docstring 明说
   "口径与全屏 OCR 完全一致"）⇒ 本机复现有参考价值；但**不作为最终定论**
   （端侧跑 0.75 倍缩放 + 不同运行时；最终以真机日志为准 ✓）
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
ROOT = os.path.dirname(PROJ)
FRAMES = os.path.join(ROOT, '_tmpman', 'v176_dispatch', 'bagdbg')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass


def main():
    import cv2
    import numpy as np
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as e:                  # noqa: BLE001
        print('没装 rapidocr_onnxruntime：%r' % (e,))
        return 2
    eng = RapidOCR(use_cls=False)
    files = sorted(f for f in os.listdir(FRAMES)
                   if f.startswith('board_r') and f.endswith('.png'))
    print('用真 OCR 读 %d 张真机帧（端侧同款引擎）\n' % len(files))
    for fn in files:
        p = os.path.join(FRAMES, fn)
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            continue
        res, _ = eng(p)
        items = []
        for box, text, conf in (res or []):
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            items.append({'text': text, 'conf': float(conf),
                          'cx': int(sum(xs) / 4), 'cy': int(sum(ys) / 4)})
        free = [i for i in items if '空闲' in (i.get('text') or '')]
        timers = [i for i in items
                  if ':' in (i.get('text') or '')
                  and 860 <= i['cy'] <= 1020]
        row = [i for i in items if 860 <= i['cy'] <= 1020]
        print('%-26s 条目=%-3d  槽位行(860~1020)条目=%d  「空闲」=%d  倒计时=%d'
              % (fn, len(items), len(row), len(free), len(timers)))
        for i in sorted(row, key=lambda z: z['cx']):
            print('      y=%-5d x=%-5d conf=%.2f %r'
                  % (i['cy'], i['cx'], i['conf'], i['text'][:36]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
