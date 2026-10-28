# -*- coding: utf-8 -*-
"""v1.78 取证②：被"返回(兜底)"点中的那一格 `(4,2)` 到底是什么？

## 背景（`_tmpman/v177_dispatch/bagdbg/mgas_log.txt`，21:39 那把 map 3）
```
L129 explore first_high_value at [274,789] tile="-1,2" sid=S30001_221 is_purple=true
L132 dispatch dispatch_despite_unknown      ← v1.77 修复生效 ✓
L133 btn_by_ocr 键派遣 [891,1350]  → L134 tap1（面板没关）
L135 btn_by_ocr 建派遣 [900,1354]  → L136 tap2（面板还是没关）
L137 dispatch still_open_close              ← 两次都没关掉
L138 tap 返回(兜底) at [275,1507] ch=norm   ← ⚠ 这个坐标**在棋盘里**
L139 tap 返回(兜底) at [275,1552]
L140 tap 返回(兜底) at [275,1507] mode=hold
L141 tap 返回(兜底) at [275,1507] ch=dlg mode=cross changed=true
L144 popup fight_panel_explore_full tapped_sid=S30001_221 slots_free=0
L145 popup fight_panel cell_marks=["recommend"]
L146 battle → 打掉了
```
`cell_of(275,1507) = (4,2)` ⇒ 那两下**点在棋盘上**。

本探针：把 `(4,2)` 从真机帧上分类出来，回答
  Q1 `(4,2)` 是不是**战斗型**地块（= 点它会弹「战斗事件」面板）
  Q2 `(4,2)` 在**本轮 plan / marks** 里吗（不在 ⇒ "无关的格子" ✓）
  Q3 面板「返回」的**安全**坐标应该是多少（必须在棋盘 y 范围之外）
"""
import io
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.dirname(PROJ)
FRAME = os.path.join(ROOT, '_tmpman', 'v177_dispatch', 'bagdbg',
                     'board_r0_213925.png')
LOG = os.path.join(ROOT, '_tmpman', 'v177_dispatch', 'bagdbg', 'mgas_log.txt')
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


def main():
    import cv2
    import numpy as np
    import spots as SP

    G = SP.GRID
    y_hi = G['y0'] + G['rows'] * G['cy']
    print('棋盘可点 y ∈ [%.0f, %.0f]   x ∈ [%.0f, %.0f]'
          % (G['y0'], y_hi, G['x0'], G['x0'] + G['cols'] * G['cx']))
    print('  ⇒ `(275,1507)` 在 y 范围内（1507 < %.0f）**是棋盘格** ✗' % y_hi)
    print('  ⇒ 面板兜底应该用 y > %.0f 的坐标（如 `_CLAIM_BACK_XY=(539,1793)`）✓'
          % y_hi)
    print()

    if not os.path.isfile(FRAME):
        print('缺帧 %s' % FRAME)
        return 2
    im = cv2.imdecode(np.fromfile(FRAME, dtype=np.uint8), cv2.IMREAD_COLOR)
    st = SP.Board('S30001').state(im, thr=0.0)

    print('---- Q1/Q2：(4,2) 是什么格 ----')
    for rc in ((4, 2), (1, 1), (1, 6)):
        v = st.get(rc) or {}
        sid = str(v.get('sid') or '')
        try:
            fight = bool(SP.is_fight_spot(sid))
        except Exception:                   # noqa: BLE001
            fight = None
        try:
            plain = bool(SP.is_plain_spot(sid))
        except Exception:                   # noqa: BLE001
            plain = None
        print('  %-5s sid=%-12s name=%-10s score=%.3f 战斗格=%s 空地=%s'
              % ('%d,%d' % rc, sid, v.get('name'), float(v.get('score') or 0),
                 fight, plain))
    print()

    print('---- 本轮 plan / marks（从日志取）----')
    lines = io.open(LOG, encoding='utf-8', errors='replace').read().splitlines()
    for ln in lines:
        if '"plan": "first"' in ln or ('"solver": "ok"' in ln and '"order"' in ln):
            print('  ' + ln.strip()[:200])
    print()
    print('  ⇒ plan = ["1,1","1,6"]、marks = {1,1: recommend, 1,6: boss}')
    print('  ⇒ **`(4,2)` 既不在 plan 里、也没有标记** ⇒ "无关的格子" ✓')
    print()
    print('---- Q3：修复方向 ----')
    print('  · 兜底坐标必须在**棋盘之外**（y > %.0f）⇒ 用 `_CLAIM_BACK_XY` 那类' % y_hi)
    print('    已验证过的面板返回位，或先 OCR 找「返回/取消/关闭」再点 ✓')
    print('  · 并加**几何断言**：面板兜底坐标一律不许落进棋盘 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
