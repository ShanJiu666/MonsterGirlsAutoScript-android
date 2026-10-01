# -*- coding: utf-8 -*-
"""bubble_real_frame.py · 用 **bot 自己的帧**（走 MediaProjection + maskOverlay）验气泡是否被涂掉

前面的 live_*.png 是 `adb exec-out screencap` 的**原始截图**，绕过 MediaProjection，
所以悬浮条可见 —— 那不代表 bot 真正喂给 OCR 的帧。
本脚本用 bot 存在 runs/ 的归一化帧（它自己抓的）复核。
"""
import os
import sys
import glob

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


def check(img, name):
    H, W = img.shape[:2]
    res, _ = eng(img)
    items = [{'text': t.strip(), 'cx': sum(q[0] for q in b) / 4,
              'cy': sum(q[1] for q in b) / 4, 'conf': float(s)}
             for b, t, s in (res or [])]
    panel = EL.is_battle_panel(items)
    trig = [i for i in items if i['text'].strip() in ('战斗胜利', '战斗失败')]
    print('%s  %dx%d  is_battle_panel=%s  严格等值命中=%s'
          % (name, W, H, panel,
             [(t['text'], round(t['cx']), round(t['cy'])) for t in trig] or '无'))
    if trig:
        y = trig[0]['cy']
        row = [(i['text'], round(i['cx']), round(i['cy'])) for i in items
               if abs(i['cy'] - y) < 40]
        print('     同行: %s' % row)
    return panel


def main():
    # ① 上一轮录制的 1264×2780 真机帧（归一化前是设备帧；先按文件分辨率判断）
    cand = []
    for pat in (r'D:\MGAS\_tmpman\fr1264\rec\*.png',
                r'D:\MGAS\mapbot_pc\runs\*.png',
                r'D:\MGAS\android_autoexplore\_verify\*.png'):
        cand += glob.glob(pat)
    cand = [c for c in cand if os.path.getsize(c) > 20000]
    print('候选帧 %d 张' % len(cand))
    bad = []
    for i, p in enumerate(sorted(cand)[-25:]):
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        if check(img, os.path.basename(p)):
            bad.append(p)
        print()
    print('=' * 70)
    print('其中 %d 张被误判成结算面板' % len(bad))
    for p in bad:
        print('   %s' % p)


if __name__ == '__main__':
    main()
