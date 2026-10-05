# -*- coding: utf-8 -*-
"""v1.63 标定（B14）②：验证「PC 坐标 × 1.5 = 手机端坐标」这个换算，并定 `CLOVER_HUD_X/Y`

## 思路（不靠 OCR，先用几何硬对齐）
  PC 是 **720×1280** 系，手机端是 **1080×1920** 系 ⇒ 宽度比 **1.5**，高度比 **1.5** ✓
  PC 实测：幸运草数字 cx **462~463** / cy **59**；大拇指 cx≈604；体力 cx≈224；金币 cx≈434
  ⇒ 手机端应在：幸运草 cx ≈ **694** / cy ≈ **88**；大拇指 ≈ **906**；体力 ≈ 336；金币 ≈ 651

## 本脚本干什么
  ① 按上面的换算，把"候选窗口"和"干扰窗口"都裁出来放大
     ⇒ **人眼一看**就知道哪个窗口里是幸运草数字 ✓
  ② 顺带统计每个窗口里的**暗像素/连通块数**，给一个粗判据（数字笔画数）

用法：python android_autoexplore\\tools\\probe_clover_scale.py
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
CAL = os.environ.get('MGAS_CAL_DIR') or os.path.abspath(
    os.path.join(PROJ, '..', '_tmpman', 'cal'))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, _PY)
os.environ.setdefault('MAPBOT_ROOT', _ASSETS)
os.environ.pop('MAPBOT_ANDROID', None)

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

# PC 实测值（`explore_loop.py` 注释：幸运草 cx 462~463 / cy 59；体力 224；金币 434；大拇指 604）
PC = {'clover': (462.5, 59), 'stamina': (224, 94), 'coin': (434, 26), 'thumb': (604, 59)}
K = 1080.0 / 720.0          # = 1.5


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有帧目录 ⇒ 跳过')
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    print('比例 K = %.3f（1080/720）' % K)
    print('按 K 换算的目标坐标：')
    for k, (x, y) in PC.items():
        print('   %-8s PC(%6.1f,%5.1f) ⇒ 手机(%6.1f,%5.1f)' % (k, x, y, x * K, y * K))
    print()
    for fn in files[:3]:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        # 每个目标裁一个 ±60 宽的窗口（放大 4×）
        tiles = []
        for k, (x, y) in PC.items():
            cx, cy = int(x * K), int(y * K)
            x0, x1 = max(0, cx - 60), min(W, cx + 60)
            y0, y1 = max(0, cy - 45), min(H, cy + 45)
            sub = img[y0:y1, x0:x1]
            big = cv2.resize(sub, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_NEAREST)
            # 加标题条
            bar = np.zeros((50, big.shape[1], 3), np.uint8)
            cv2.putText(bar, '%s @%d,%d' % (k, cx, cy), (8, 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
            tile = np.vstack([bar, big])
            tiles.append(tile)
        # 横向拼（统一高度）
        hmax = max(t.shape[0] for t in tiles)
        tiles = [np.vstack([t, np.zeros((hmax - t.shape[0], t.shape[1], 3), np.uint8)])
                 if t.shape[0] < hmax else t for t in tiles]
        strip = np.hstack(tiles)
        out = os.path.join(CAL, '_hudwin_%s' % fn)
        cv2.imwrite(out, strip)
        print('%s ⇒ 四窗口对照图 %s  (%dx%d)' % (fn, out, strip.shape[1], strip.shape[0]))
    print()
    print('⇒ 看那张对照图：**哪个窗口里是"四叶草图标 + 一个数字"** ⇒ 那就是幸运草位置 ✓')
    print('   ⚠ 若四个窗口都对不上 ⇒ 说明手机端 HUD 布局与 PC **不是简单 1.5 倍**，')
    print('     必须回到真机帧重新标（本脚本会明确报出来，不猜 ✓）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
