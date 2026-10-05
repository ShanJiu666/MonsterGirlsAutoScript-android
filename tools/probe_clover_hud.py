# -*- coding: utf-8 -*-
"""v1.63 标定（B14）：手机端 HUD 上「幸运草」数字在哪个位置、读不读得到

## 背景（PC 未提交改动 `explore_loop.py`）
  用户口径：「**改成幸运草低于 8 就不摇色子吧**」
  PC 真机背景：幸运草只剩 1 ⇒ 点四叶草 ⇒ 游戏**不弹确认框**
  ⇒ 那道"没弹框就不点确定"的闸门跳掉这一圈 ⇒ **白点 2 次**，
    日志只写 `no_dlg_skip` ⇒ **真因（草不够）被掩盖** ✗
  PC 修法：`clover_count(items)` 从 HUD 读（**与体力同一行同一次 OCR ⇒ 零额外成本**）
  PC 的位置：`CLOVER_HUD_X = (430, 520)` / `CLOVER_HUD_Y = (35, 85)`（**720×1280 系**）

## 本脚本（手机端 1080×1920 系，**必须重新标定**）
  ① 把每张真机帧的**顶部 HUD 条**裁出来放大 ⇒ 人眼看数字都在哪
  ② 打印该带上 OCR 到的**所有数字条目**（cx/cy/文本）⇒ 定 x 区间
  ③ 猜出幸运草读数的 x/y 区间，并与"体力/金币/大拇指"区分开

用法：python android_autoexplore\\tools\\probe_clover_hud.py
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


def ocr_items(img):
    """用手机端真正那条 OCR 路径（`mapbot` 的参考系 + onnx 引擎）

    ⚠ 直接 import `mapbot` 要 java 环境 ⇒ 这里改为**调 `ocr` 模块**（若可用），
      否则退化成"只裁图给人看"（不报假绿 ✓）
    """
    try:
        import ocr as _ocr
        for fname in ('ocr_items', 'run', 'ocr', 'recognize'):
            fn = getattr(_ocr, fname, None)
            if callable(fn):
                try:
                    r = fn(img)
                    if isinstance(r, list):
                        return r
                except Exception:           # noqa: BLE001
                    pass
        return None
    except Exception:                   # noqa: BLE001
        return None


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有帧目录 `%s` ⇒ 跳过' % CAL)
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    if not files:
        print('⚠ 没有帧 ⇒ 跳过')
        return 2
    outp_dir = CAL
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        # HUD 顶条：手机端参考系下 HUD 大约在 y 0~140（1080 宽）
        band = img[0:150, :]
        big = cv2.resize(band, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_NEAREST)
        out = os.path.join(outp_dir, '_hud_%s' % fn)
        cv2.imwrite(out, big)
        print('=' * 92)
        print('%s  %dx%d  ⇒ HUD 裁图 %s' % (fn, W, H, out))
        its = ocr_items(img)
        if its is None:
            print('   ⚠ 拿不到 OCR 条目（`ocr` 模块接口不符）⇒ 只出裁图给人看 ✓')
            continue
        nums = []
        for it in its:
            t = str(it.get('text') or '').replace(' ', '').replace('+', '')
            cy = int(it.get('cy', -1))
            if cy <= 160 and t:
                nums.append((int(it.get('cx', -1)), cy, t))
        for cx, cy, t in sorted(nums, key=lambda z: z[0]):
            flag = '★纯数字' if t.isdigit() else ''
            print('   cx=%-5d cy=%-4d %-18r %s' % (cx, cy, t, flag))
    print()
    print('=' * 92)
    print('⇒ 用上面的 cx 分布定 `CLOVER_HUD_X/Y`；')
    print('   ⚠ PC 的 (430,520)/(35,85) 是 **720×1280 系**，手机端**必须重标** ✗')
    return 0


if __name__ == '__main__':
    sys.exit(main())
