# -*- coding: utf-8 -*-
"""v1.78 取证③：把涉及的三格**裁出来看**（判"还认为这格是大拇指格子"对不对）

用户 2026-10-06 21:39 那把（`_tmpman/v177_dispatch/bagdbg/`）原话：
  「**探索完乱点了个无关的战斗格子打掉了，然后还认为这个格子是大拇指格子**」

日志里那一把的判定：
```
L127 marks = {"1,1": ["recommend"], "1,6": ["boss"]}
L123 plan_block cell "1,1" sid S30001_221 荧光蘑菇 marks "recommend" cost 10
L129 explore first_high_value at [274,789] tile "-1,2" sid S30001_221 is_purple true
L138~141 tap 返回(兜底) [275,1507]×3 / [275,1552]×1   ← cell_of = (4,2) **在棋盘里**
L144 popup fight_panel_explore_full tapped_sid S30001_221
L145 popup fight_panel cell_marks ["recommend"]
L146 battle → 打掉了
```
本探针把 `(1,1)` / `(1,6)` / `(4,2)` 连邻域裁出来 ⇒ **人眼判**：
  · `(1,1)` 到底有没有**大拇指图标**（有 ⇒ `recommend` 是对的；没有 ⇒ 标记误报 ✗）
  · `(4,2)`（被兜底点中的那格）长什么样
输出：`_tmpman/v178crop/*.png`
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.dirname(PROJ)
D = os.path.join(ROOT, '_tmpman', 'v177_dispatch', 'bagdbg')
OUT = os.path.join(ROOT, '_tmpman', 'v178crop')
FRAMES = ['board_r0_213723.png', 'board_r0_213824.png', 'board_r0_213925.png']
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, PYDIR)
os.environ.setdefault('MAPBOT_ROOT', ASSETS)
os.environ.pop('MAPBOT_ANDROID', None)


def _noop(*a, **k):
    return None


import types                                  # noqa: E402
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
        m = types.ModuleType(_m)
        for _k, _v in _at.items():
            setattr(m, _k, _v)
        sys.modules[_m] = m


def main():
    import cv2
    import numpy as np
    import spots as SP
    os.makedirs(OUT, exist_ok=True)
    G = SP.GRID

    def center(rc):
        r, c = rc
        return (int(G['x0'] + (c - 1) * G['cx'] + G['cx'] / 2),
                int(G['y0'] + (r - 1) * G['cy'] + G['cy'] / 2))

    tiles = []
    for fn in FRAMES:
        p = os.path.join(D, fn)
        if not os.path.exists(p):
            continue
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        st = SP.Board('S30001').state(im, thr=0.0)
        for rc in ((1, 1), (1, 6), (4, 2)):
            cx, cy = center(rc)
            h = int(G['cx'] / 2)
            sub = im[cy - h:cy + h, cx - h:cx + h]
            if sub.size == 0:
                continue
            big = cv2.resize(sub, None, fx=3, fy=3,
                             interpolation=cv2.INTER_NEAREST)
            v = st.get(rc) or {}
            tag = '%s__%d_%d__%s__%s' % (fn[:20], rc[0], rc[1],
                                         str(v.get('sid')), str(v.get('name')))
            op = os.path.join(OUT, tag + '.png')
            cv2.imencode('.png', big)[1].tofile(op)
            print('%-52s sid=%-12s name=%-8s score=%.3f → %s'
                  % ('%d,%d' % rc, v.get('sid'), v.get('name'),
                     float(v.get('score') or 0), os.path.basename(op)))
            # 拼图（只看第二张 map3 的三格）
            if fn == 'board_r0_213925.png':
                tiles.append((big, '%d,%d %s' % (rc[0], rc[1], v.get('name'))))
        print('  ---- %s ----' % fn)
    if tiles:
        H = max(t[0].shape[0] for t in tiles) + 40
        W = sum(t[0].shape[1] for t in tiles) + 20 * (len(tiles) - 1)
        sheet = np.full((H, W, 3), 255, np.uint8)
        x = 0
        for img, label in tiles:
            sheet[40:40 + img.shape[0], x:x + img.shape[1]] = img
            cv2.putText(sheet, label.encode('ascii', 'replace').decode(),
                        (x + 4, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (0, 0, 0), 1, cv2.LINE_AA)
            x += img.shape[1] + 20
        sp = os.path.join(OUT, 'sheet_map3.png')
        cv2.imencode('.png', sheet)[1].tofile(sp)
        print('\n拼图 → %s' % sp)
    print('目录 → %s' % OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
