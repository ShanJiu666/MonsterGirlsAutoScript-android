# -*- coding: utf-8 -*-
"""live_hunt.py · 在刚抓的实况帧里找「结算面板」，并把奖励行区域裁出来

先 OCR 判是不是结算面板（有「关闭」/「回放战斗」/「战斗胜利」），
是就把奖励行 y 区间（band 内、x<560）整条裁下来存图 + 扫大拇指标记。
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
import badge as badge_mod                    # noqa: E402
import explore_loop as EL                    # noqa: E402
from rapidocr_onnxruntime import RapidOCR   # noqa: E402

eng = RapidOCR()
SRC_DIR = r'D:\MGAS\_tmpman\live7555'
REF_W, REF_H, TOP = 1080, 1920, 300
K = 1280 / 1920.0        # 720×1280 ⇒ k=0.6667
SHIFT = 0.0


def main():
    files = sorted(glob.glob(os.path.join(SRC_DIR, 'live_*.png')))
    if not files:
        print('没有实况帧')
        return
    print('实况帧 %d 张' % len(files))
    for p in files:
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print('  %s 解不开' % os.path.basename(p))
            continue
        H, W = img.shape[:2]
        res, _ = eng(img)
        items = [{'text': t.strip(), 'cx': sum(q[0] for q in b) / 4,
                  'cy': sum(q[1] for q in b) / 4, 'conf': float(s)}
                 for b, t, s in (res or [])]
        panel = EL.is_battle_panel(items)
        texts = ' | '.join(i['text'] for i in items[:14])
        print('  %s  %dx%d  结算面板=%s' % (os.path.basename(p), W, H, '★是' if panel else '否'))
        print('      %s' % texts[:150])
        if not panel:
            continue
        # 设备 720×1280 ⇒ 参考系 1080×1920，k=0.6667，参考 = 设备/k
        ref_items = [{'text': i['text'], 'cx': i['cx'] / K, 'cy': i['cy'] / K,
                      'conf': i['conf']} for i in items]
        bx = EL._reward_box(ref_items)
        print('      新 box(参考系)=%s ⇒ 设备系 y %.0f~%.0f'
              % (bx, bx[1] * K, bx[3] * K))
        y0, y1 = int(bx[1] * K), int(bx[3] * K)
        x0, x1 = int(bx[0] * K), int(bx[2] * K)
        if y1 > H:
            y1 = H
        if y0 < 0:
            y0 = 0
        crop = img[y0:y1, x0:x1]
        if crop.size:
            out = os.path.join(SRC_DIR, 'rewardrow_%s.png' % os.path.basename(p))
            cv2.imencode('.png', crop)[1].tofile(out)
            print('      奖励行裁图 → %s (%dx%d)' % (os.path.basename(out),
                                                    crop.shape[1], crop.shape[0]))
        # 图标通道：整图找（放宽阈值看有没有）
        hits = badge_mod.find_reward_mark(img, box=(0, 0, W, H),
                                         shape_min=0.30, color_min=0.30, top=6)
        print('      全图大拇指标记(≥0.30): %s'
              % (['(%.2f,%.2f)@(%d,%d)x%.1f' % (h[0], h[1], h[2], h[3], h[4])
                  for h in hits] or '无'))


if __name__ == '__main__':
    main()
