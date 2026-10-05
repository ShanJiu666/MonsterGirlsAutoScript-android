# -*- coding: utf-8 -*-
"""v1.63 标定（B14）③：**不靠 OCR** 定手机端 HUD 幸运草读数窗口

## 为什么不能靠 OCR 标
手机端 OCR 引擎在 **Java 壳里**（`mapbot._AndroidOcr` 调 `api.ocrPng`）
⇒ **离线跑不了** ✗。而 PC 的坐标是 **720 系**（手机端 1080 系 = ×1.5）。

## 本脚本的做法（**几何 + 颜色**，可离线验证 ✓）
  ① 用 ×1.5 换算得到候选窗口（已验证：`clover @693,88` 里正是"数字 + 四叶草加号"）
  ② 在该窗口里数**四叶草绿色像素**（HUD 上幸运草那个加号按钮是亮绿）
     ⇒ 证明"这个 x 段确实是幸运草列"（而不是金币/大拇指列）✓
  ③ 打印每张帧该窗口的形状/绿色占比 ⇒ 作为**标定依据**存档

用法：python android_autoexplore\\tools\\probe_clover_green.py
"""
import io
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

K = 1080.0 / 720.0
# PC 实测列（`explore_loop.py`）：幸运草 cx 462~463 / 金币 434 / 大拇指 604 / 体力 224(在第二行)
COLS = {'clover': 462.5, 'coin': 434.0, 'thumb': 604.0}


def green_ratio(sub):
    """亮绿（四叶草加号按钮）像素占比 —— HUD 上只有那个加号是这种绿"""
    b, g, r = sub[:, :, 0].astype(np.int16), sub[:, :, 1].astype(np.int16), \
        sub[:, :, 2].astype(np.int16)
    m = (g > 150) & (g - r > 40) & (g - b > 40)
    return float(m.mean())


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有帧目录 ⇒ 跳过')
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    print('K = %.3f（1080/720）' % K)
    print()
    print('%-20s %s' % ('帧', ' '.join('%-22s' % k for k in COLS)))
    print('-' * 92)
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        cells = []
        for k, x in COLS.items():
            cx = int(x * K)
            x0, x1 = max(0, cx - 40), min(W, cx + 70)     # 数字在左、加号在右
            y0, y1 = 60, 120                              # HUD 第二行
            sub = img[y0:y1, x0:x1]
            cells.append('%5.1f%% @x%d' % (green_ratio(sub) * 100, cx))
        print('%-20s %s' % (fn, ' '.join('%-22s' % c for c in cells)))
    print()
    print('=' * 92)
    print('判读：**绿色占比高的那一列**就是幸运草（它的加号按钮是亮绿）✓')
    print('      金币/大拇指那两列应当**明显更低**（金币是金色、大拇指是黄色）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
