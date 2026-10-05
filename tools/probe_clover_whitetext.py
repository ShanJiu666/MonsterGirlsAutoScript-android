# -*- coding: utf-8 -*-
"""v1.63 标定（B14）④：**直接量白字位置** —— 定手机端 HUD 幸运草读数的 x 区间

## 为什么不用颜色判
上一脚本实测：**幸运草和大拇指那两列都有绿色「+」按钮**
（4.2% vs 4.6%，分不开 ✗）⇒ 颜色判**不可用**。
⇒ 改量**白色数字像素**的 x 分布（HUD 上数字都是白字带黑描边）✓

## 做法
  ① 取 HUD 数字那一行（y 60~120，1080×1920 系）
  ② 找"接近白色"的像素（`min(B,G,R) > 190`）
  ③ 按 x 聚成簇 ⇒ 每簇 = 一个数字块 ⇒ 打印簇心 x 与宽度
  ④ 与 PC 的 ×1.5 换算值比对（幸运草 694 / 大拇指 906 / 金币 651）

用法：python android_autoexplore\\tools\\probe_clover_whitetext.py
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

K = 1080.0 / 720.0
EXPECT = {'clover': 462.5 * K, 'coin': 434.0 * K, 'thumb': 604.0 * K}


def clusters(mask_row):
    """把一维布尔数组按连续 True 段聚簇，返回 [(x0, x1, center, width)]"""
    out, i, n = [], 0, len(mask_row)
    while i < n:
        if not mask_row[i]:
            i += 1
            continue
        j = i
        while j < n and mask_row[j]:
            j += 1
        out.append((i, j - 1, (i + j - 1) / 2.0, j - i))
        i = j
    return out


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有帧目录 ⇒ 跳过')
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        band = img[60:120, :]
        b, g, r = (band[:, :, 0].astype(np.int16), band[:, :, 1].astype(np.int16),
                   band[:, :, 2].astype(np.int16))
        white = (np.minimum(np.minimum(b, g), r) > 190)
        colsum = white.sum(axis=0) >= 3          # 这一列至少 3 个白像素
        cl = [c for c in clusters(colsum) if c[3] >= 4]
        print('=' * 96)
        print('%s   白字簇（x0~x1, 心, 宽）：' % fn)
        for x0, x1, ctr, w in cl:
            tag = ''
            for k, ex in EXPECT.items():
                if abs(ctr - ex) < 45:
                    tag = ' ← 接近 PC 的 %s(×1.5=%.0f)' % (k, ex)
            print('   %4d~%-4d 心=%6.1f 宽=%-4d%s' % (x0, x1, ctr, w, tag))
    print()
    print('=' * 96)
    print('期望（PC × 1.5）：' + '  '.join('%s=%.0f' % (k, v) for k, v in EXPECT.items()))
    print('⇒ 找到与 **幸运草期望值 694** 对应的那一簇 ⇒ 那就是它的读数位置 ✓')
    print('⚠ 若某帧这一行没有白字簇（HUD 不在 60~120）⇒ 该帧不参与标定 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
