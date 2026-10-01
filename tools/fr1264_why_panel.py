# -*- coding: utf-8 -*-
"""why_panel.py · 拆开看 live_01 那帧 is_battle_panel 到底哪一条判据触发了

期望：`首领战斗胜利` 走**严格等值**不该算结算面板；`回放战斗` / `关闭(y>=1100)` 才是。
但 live_hunt 报 True ⇒ 要定位是哪一条 + 那条的文本/coords。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAPBOT = r'D:\MGAS\mapbot_pc'
sys.path.insert(0, MAPBOT)
os.chdir(MAPBOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402
import explore_loop as EL                    # noqa: E402
from rapidocr_onnxruntime import RapidOCR   # noqa: E402

eng = RapidOCR()
K = 1280 / 1920.0        # 720×1280 ⇒ k=0.6667


def main():
    p = r'D:\MGAS\_tmpman\live7555\live_01.png'
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    H, W = img.shape[:2]
    res, _ = eng(img)
    items = [{'text': t.strip(), 'cx': sum(q[0] for q in b) / 4,
              'cy': sum(q[1] for q in b) / 4, 'conf': float(s)}
             for b, t, s in (res or [])]
    print('帧 %dx%d  OCR %d 条' % (W, H, len(items)))
    print()
    print('—— 关键：这些 cx/cy 是**设备系**(720×1280)，但 is_battle_panel 期望**参考系**(1080×1920)')
    print('   live_hunt 传的是 ref_items（已 /k 换算），这里逐条判：')
    ref_items = [{'text': i['text'], 'cx': i['cx'] / K, 'cy': i['cy'] / K, 'conf': i['conf']}
                 for i in items]

    # ① 底部关闭
    cl = EL.bottom_close(ref_items)
    print('① bottom_close →', (cl['text'], round(cl['cx']), round(cl['cy'])) if cl else None)
    # ② 回放战斗
    rb = [i for i in ref_items if '回放战斗' in i['text']]
    print('② 含「回放战斗」的条目 →', [(i['text'], round(i['cx']), round(i['cy'])) for i in rb])
    # ③ 严格等值战斗胜利/失败
    ex = [i for i in ref_items if i['text'].strip() in ('战斗胜利', '战斗失败')]
    print('③ 严格等值「战斗胜利/失败」→', [(i['text'], round(i['cx']), round(i['cy'])) for i in ex])

    print()
    print('is_battle_panel(ref_items) =', EL.is_battle_panel(ref_items))
    print('is_battle_panel(设备系 items) =', EL.is_battle_panel(items))
    print()
    print('全部 OCR（设备系）：')
    for i in sorted(items, key=lambda z: z['cy']):
        print('   %-30s (%4.0f,%4.0f) conf %.2f' % (i['text'][:28], i['cx'], i['cy'], i['conf']))


if __name__ == '__main__':
    main()
