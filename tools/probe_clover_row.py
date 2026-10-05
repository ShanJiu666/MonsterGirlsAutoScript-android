# -*- coding: utf-8 -*-
"""v1.63 标定（B14）⑥：**分行**量 HUD 白字簇 ⇒ 精确定位手机端幸运草读数窗口

## 图上看到的事实（`_clover_annot_r_180326_0.png`）
  · 第 1 行（y 约 25~55）：`PID:162332` ｜ `Ver:1.0.2.7` ｜ 金币图标 ｜ **357731**
  · 第 2 行（y 约 75~110）：体力条 `2037/2100` ｜ 四叶草图标 ｜ **幸运草数** ｜
    金币图标 ｜ **大拇指数** ｜ 大拇指图标
  ⇒ **幸运草数在第 2 行**，紧跟在四叶草图标右边 ✓
  ⚠ 上一脚本把两行**混在一起**量（y 60~120）⇒ 定不准 ✗

## 本脚本
  ① 按**两行**分别量白字簇（第 1 行 y 20~60 / 第 2 行 y 70~115）
  ② 找"紧跟在**绿色加号左边**"的那一簇 = 幸运草数（用绿色列做锚）
  ③ 输出各帧的簇心 ⇒ 定 `CLOVER_HUD_X`

用法：python android_autoexplore\\tools\\probe_clover_row.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
CAL = os.environ.get('MGAS_CAL_DIR') or os.path.abspath(
    os.path.join(PROJ, '..', '_tmpman', 'cal'))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402


def clusters(mask, min_w=4):
    out, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        if j - i >= min_w:
            out.append((i, j - 1, (i + j - 1) / 2.0, j - i))
        i = j
    return out


def white_cols(band):
    b, g, r = (band[:, :, 0].astype(np.int16), band[:, :, 1].astype(np.int16),
               band[:, :, 2].astype(np.int16))
    white = (np.minimum(np.minimum(b, g), r) > 190)
    return white.sum(axis=0) >= 2


def green_cols(band):
    b, g, r = (band[:, :, 0].astype(np.int16), band[:, :, 1].astype(np.int16),
               band[:, :, 2].astype(np.int16))
    green = (g > 150) & (g - r > 40) & (g - b > 40)
    return green.sum(axis=0) >= 3


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有帧目录 ⇒ 跳过')
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    ROWS = (('行1(PID/金币)', 20, 62), ('行2(体力/幸运草/大拇指)', 70, 118))
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        print('=' * 96)
        print(fn)
        for label, y0, y1 in ROWS:
            band = img[y0:y1, :]
            wc = clusters(white_cols(band))
            gc = clusters(green_cols(band))
            print('  %s' % label)
            print('     白字簇: %s' % ' '.join('%d~%d(%d)' % (a, b, c) for a, b, c, _ in wc))
            print('     绿簇  : %s' % ' '.join('%d~%d(%d)' % (a, b, c) for a, b, c, _ in gc))
            # 找"紧跟在绿簇左边"的白字簇 = 该列的读数值
            hits = []
            for ga, gb, gc_, _ in gc:
                for wa, wb, wc_, _ in wc:
                    if 0 < (ga - wb) <= 40 and wa < ga:
                        hits.append((wc_, wa, wb, ga))
            for ctr, wa, wb, ga in hits:
                print('     ★ 「绿加号左侧」的数字簇：x %d~%d 心=%.1f（绿在 %d）'
                      % (wa, wb, ctr, ga))
    print()
    print('=' * 96)
    print('⇒ `★` 那几行里，**行2 且 x≈660~700** 的就是**幸运草**（体力条/金币/大拇指要排除）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
