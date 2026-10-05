# -*- coding: utf-8 -*-
"""v1.62 关键取证：`5,4`/`5,7`/`4,7` 这些"雾格但 score 高"的格子，**真机上到底是什么**？

## 为什么要看图（不能只看 score / floor）
  · `score=0.969 宝箱` + `floor=65`（雾）+ `plain=True`（模型让连锁穿过）
  · 两种解释**完全相反**：
      A. 格子真是宝箱（挡连锁）⇒ `plain=True` 是**错的** ⇒ E 条该拦 ✓
         （= PC 那个病：宝箱美术亮 ⇒ 剪影法漏掉 ⇒ 误判平坦空地）
      B. 格子真是雾下平地、只是分类器猜错了 ⇒ `plain=True` 是**对的** ⇒ E 条不该拦
  ⇒ **只有看图能分辨** ✓

## 本脚本
把棋盘裁出来、按 4 倍放大，并在每格写上 `name/score/floor/plain`
⇒ 人眼一对就知道 A 还是 B ✓

用法：python android_autoexplore\\tools\\probe_chain_visual.py [帧名]
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
OUT = os.environ.get('MGAS_VIS_OUT') or os.path.abspath(
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
import targets_cfg as TC                    # noqa: E402
import mapsim as MS                         # noqa: E402


def main():
    fn = sys.argv[1] if len(sys.argv) > 1 else 'r_133809_0.png'
    src = os.path.join(CAL, fn)
    if not os.path.exists(src):
        print('⚠ 没有帧 %s' % src)
        return 2
    img = cv2.imread(src)
    bd = SP.Board('S30001')
    st = bd.state(img)
    px = int(bd.px)
    x0, y0 = int(bd.grid['x0']), int(bd.grid['y0'])
    sim = MS.MapSim.from_observation(st, SP.spot_rows())
    rows = SP.spot_rows() or {}
    plain_names = set(getattr(TC, 'PLAIN_NAMES', ()) or ())
    # 逐格的 plain（按块）
    cell_plain = {}
    for bi, b in sim.blocks.items():
        cells = list(getattr(b, 'cells', None) or sim.cells_of.get(bi, ()) or ())
        for m in cells:
            cell_plain[(m // 7 + 1, m % 7 + 1)] = bool(getattr(b, 'plain', False))

    board = img[y0:y0 + 5 * px, x0:x0 + 7 * px].copy()
    big = cv2.resize(board, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_NEAREST)
    for r in range(1, 6):
        for c in range(1, 8):
            v = st.get((r, c)) or {}
            nm = str(v.get('name') or '?')
            sc = float(v.get('score') or 0)
            fl = v.get('floor')
            pl = cell_plain.get((r, c))
            try:
                w = int((rows.get(v.get('sid')) or {}).get('Weight') or 0)
            except Exception:               # noqa: BLE001
                w = 0
            ground = (w >= 40000) or (nm in plain_names)
            cx, cy = int((c - 0.5) * px * 2), int((r - 0.5) * px * 2)
            # 颜色：plain=True ⇒ 绿框（模型说"连锁能穿过"）；False ⇒ 红框
            col = (0, 220, 0) if pl else (0, 0, 235)
            cv2.rectangle(big, (cx - px, cy - px), (cx + px, cy + px), col, 3)
            cv2.putText(big, '%s %.2f' % (nm[:4], sc), (cx - px + 6, cy - px + 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(big, 'f%.0f W%d' % (fl if fl is not None else -1, w),
                        (cx - px + 6, cy - px + 52),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2, cv2.LINE_AA)
            cv2.putText(big, ('P' if pl else 'x') + ('G' if ground else ''),
                        (cx - px + 6, cy + px - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, col, 3, cv2.LINE_AA)
    cv2.rectangle(big, (0, 0), (big.shape[1], 60), (0, 0, 0), -1)
    cv2.putText(big, '%s  green P=plain(chain passes)  red x=blocked  G=ground(Weight>=40000)'
                % fn, (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
    out = os.path.join(OUT, '_chain_%s' % fn)
    cv2.imwrite(out, big)
    print('→ %s  (%dx%d)' % (out, big.shape[1], big.shape[0]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
