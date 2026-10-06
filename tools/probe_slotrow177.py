# -*- coding: utf-8 -*-
"""v1.77 取证：派遣被跳过时，**探索槽那一行到底是什么**？

用户 2026-10-06 原话（两句是同一件事）：
  「**探索紫地块不正常，派遣不出去**」＋「**点不到一键派遣**」

真机日志铁证（`_tmpman/v176_dispatch/bagdbg/mgas_log.txt`，20:24 那把）——每张图都是这个死循环：

    round N    slots {"free_txt":1,"busy":2}  slots_free=1 → explore: first_high_value（点探索 ✓）
    round N+1  slots {"free_txt":0,"busy":1}  slots_free=0 → dispatch: skip_slots_full ✗
                                                             → tap 返回(兜底)(275,1507) 关掉面板 ✗

⚠ 关键观察：失败轮的 `free_txt=0` **同时** `busy` 从 2 掉到 1 ——
   3 个槽里"只读到一个在忙"，本该还有空闲 ⇒ **这是读数失败，不是真的满**。
   本探针把那些帧的槽位行裁出来，**人眼判**：
     · 真满 ⇒ 三格都是倒计时/已完成（没有「空闲」二字）
     · 读失败 ⇒ 明明有「空闲」，OCR/裁带却没读到（或被面板挡住）

同时打印：`explore_slots_free` 的原始条目、`count_slot_timers` 的结果、
以及槽位行在帧里的位置（`layout.REF['slots_x']` / 行带 y）。
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.dirname(PROJ)
OUT = os.path.join(ROOT, '_tmpman', 'slotrow177')
FRAMES = os.path.join(ROOT, '_tmpman', 'v176_dispatch', 'bagdbg')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, PYDIR)
os.environ.setdefault('MAPBOT_ROOT', ASSETS)
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


def main():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.isdir(FRAMES):
        print('缺帧目录 %s' % FRAMES)
        return 2
    # 槽位行搜索带（v1.68 定：上界 y=1000 < 棋盘顶边 GRID.y0=1002 ✓）
    BAND = (0, 880, 1080, 1000)
    for fn in sorted(os.listdir(FRAMES)):
        if not fn.startswith('board_r'):
            continue
        im = cv2.imdecode(np.fromfile(os.path.join(FRAMES, fn), dtype=np.uint8),
                          cv2.IMREAD_COLOR)
        if im is None:
            continue
        H, W = im.shape[:2]
        k = W / 1080.0
        sh = H - 1920.0 * k
        x0, y0, x1, y1 = BAND
        X0, X1 = int(x0 * k), int(x1 * k)
        Y0, Y1 = int(y0 * k + sh), int(y1 * k + sh)
        Y0, Y1 = max(0, Y0), min(H, Y1)
        crop = im[Y0:Y1, X0:X1]
        if crop.size == 0:
            continue
        p = os.path.join(OUT, fn.replace('.png', '__band.png'))
        cv2.imencode('.png', crop)[1].tofile(p)
        # 放大 2× 便于看字
        big = cv2.resize(crop, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
        p2 = os.path.join(OUT, fn.replace('.png', '__band2x.png'))
        cv2.imencode('.png', big)[1].tofile(p2)
        print('%-26s %dx%d  槽位带参考 y=%d~%d → 设备 y=%d~%d' % (fn, W, H, y0, y1, Y0, Y1))
        print('      → %s' % p2)
    print()
    print('裁图目录：%s' % OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
