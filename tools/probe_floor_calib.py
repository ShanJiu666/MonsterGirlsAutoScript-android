# -*- coding: utf-8 -*-
"""手机端 `floor`（四角中位数）标定 —— 定"地板法"的倍数与阈值

## 为什么必须先用手机端帧标定
PC 的 `floor_lit` 判据是：`floor > max(众数 × 1.35, 众数 + 12)`。
  · `floor` 本身是**绝对亮度**（四角中位数），与 `ratio` 的分母无关 ⇒ 可移植 ✓
  · 但 **×1.35 那个倍数是 PC 在「废弃矿洞」帧上标的**，且 PC 的 `px=96`（720p）
    而手机端 `px` 随分辨率变化（本机 1280×2772 ⇒ 缩放后 px 不同）
  ⇒ **不能照抄**，必须按手机端真机帧重新量 ✓

## 本脚本干什么
对每张手机端真机帧：
  ① 按手机端的几何（`spots.Board.px`）算每格 `floor`（四角中位数）
  ② 打印 floor 的**分布直方图**，看"雾簇 / 已揭示簇"分不分得开
  ③ 给定几个候选倍数，报"判亮几格"，并与**逐格看图**的真值对照（人工填）

## ⚠ 帧从哪来（**不在仓里**）
真机帧是**设备私有目录**的 `runs/*.png`（release 包 `run-as` 被拒 ⇒ 要装 **debug** 包
才能 `exec-out run-as ... cat` 取出来）。本脚本默认读 `_tmpman/cal/`：
    D:\\MGAS\\_tmpman\\cal\\*.png
取帧配方见 `tools/probe_device_vs_desktop.py` 文件头（同一套办法）✓
**没有帧就跳过**（不会报假绿）—— 标定结论已经写进 `spots.py` 的 `FLOOR_LIT_K` 注释 ✓

用法：python android_autoexplore\\tools\\probe_floor_calib.py
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
# ⚠ 真机帧**不在仓里**（设备私有目录取出的）⇒ 默认放仓外 `_tmpman/cal/`；
#   没有帧时本脚本会**响亮跳过**（不报假绿 ✓）。可用 `MGAS_CAL_DIR` 覆盖。
CAL = os.environ.get('MGAS_CAL_DIR') or os.path.abspath(
    os.path.join(PROJ, '..', '_tmpman', 'cal'))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, _PY)
os.environ.setdefault('MAPBOT_ROOT', _ASSETS)
os.environ.pop('MAPBOT_ANDROID', None)


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _noop(*a, **k):
    return None


for _m, _at in (('rapidocr_onnxruntime', {'RapidOCR': type('RapidOCR', (), {'__init__': _noop})}),
                ('airtest', {'core': None}), ('airtest.core', {}),
                ('airtest.core.api', {'connect_device': _noop, 'snapshot': _noop,
                                      'touch': _noop, 'swipe': _noop, 'keyevent': _noop,
                                      'exists': _noop, 'Template': object}),
                ('airtest.core.cv', {'Template': object}),
                ('java', {}), ('java.android', {}), ('java.lang', {}),
                ('java.util', {}), ('java.util.concurrent', {})):
    try:
        __import__(_m)
    except Exception:                       # noqa: BLE001
        _stub(_m, **_at)

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402
import spots as SP                          # noqa: E402


def floor_of(bd, img, r, c):
    """照 PC `_floor_luma` 的算法（四角各取中位数 ⇒ 再取四角中位数）

    ⚠ 这是**手机端要新增**的函数，这里先原地实现，用于标定 ✓
    """
    px = int(bd.px)
    inset = max(3, px // 12)
    w = max(6, px // 6)
    x0 = int(bd.grid['x0'] + (c - 1) * px)
    y0 = int(bd.grid['y0'] + (r - 1) * px)
    if x0 < 0 or y0 < 0 or x0 + px > img.shape[1] or y0 + px > img.shape[0]:
        return None
    sub = img[y0:y0 + px, x0:x0 + px]
    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
    vals = []
    for (yy, xx) in ((inset, inset), (inset, px - inset - w),
                     (px - inset - w, inset), (px - inset - w, px - inset - w)):
        blk = g[yy:yy + w, xx:xx + w]
        if blk.size:
            vals.append(float(np.median(blk)))
    return float(np.median(vals)) if vals else None


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有标定帧目录 `%s` ⇒ **跳过**（不报假绿）' % CAL)
        print('   真机帧要用 **debug 包** 从 `files/runs/*.png` 取出来（release 包 run-as 被拒）')
        print('   取帧配方见 `tools/probe_device_vs_desktop.py` 文件头 ✓')
        return 2
    # ⚠ 排除我自己画的标注图（`_` 前缀）—— 否则会拿标注图当输入、算出一堆垃圾 ✗
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    if not files:
        print('⚠ `%s` 里没有标定帧（只有标注图？）⇒ **跳过**' % CAL)
        return 2
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        bd = SP.Board('S30001')
        print('=' * 100)
        print('%s   %dx%d   px=%s  grid x0=%.0f y0=%.0f'
              % (fn, img.shape[1], img.shape[0], bd.px,
                 bd.grid['x0'], bd.grid['y0']))
        floors = {}
        for r in range(1, 6):
            for c in range(1, 8):
                v = floor_of(bd, img, r, c)
                if v is not None:
                    floors[(r, c)] = v
        if not floors:
            print('  ⚠ 量不到 floor（几何不对）')
            continue
        vals = sorted(floors.values())
        hist = {}
        for v in vals:
            hist[round(v)] = hist.get(round(v), 0) + 1
        mode = max(sorted(hist), key=lambda x: (hist[x], -x))
        print('  floor：最小 %.0f  中位 %.0f  最大 %.0f'
              % (vals[0], float(np.median(vals)), vals[-1]))
        print('  众数 = %d（出现 %d 次）' % (mode, hist[mode]))
        # 直方图（每 8 一档）
        buckets = {}
        for v in vals:
            buckets[int(v) // 8 * 8] = buckets.get(int(v) // 8 * 8, 0) + 1
        print('  分布（每 8 一档）:')
        for k in sorted(buckets):
            print('    %4d~%4d | %s %d' % (k, k + 7, '█' * buckets[k], buckets[k]))
        # 候选倍数
        print('  候选阈值（众数×倍数）：')
        for mult in (1.20, 1.25, 1.30, 1.35, 1.40, 1.50, 1.6):
            thr = max(mode * mult, mode + 12.0)
            lit = [k for k, v in floors.items() if v > thr]
            print('    ×%.2f ⇒ 阈值 %6.1f ⇒ 判亮 %2d 格 %s'
                  % (mult, thr, len(lit),
                     ' '.join('%d,%d(%.0f)' % (k[0], k[1], floors[k]) for k in sorted(lit))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
