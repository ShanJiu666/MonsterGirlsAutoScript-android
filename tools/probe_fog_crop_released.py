# -*- coding: utf-8 -*-
"""v1.76 取证⑧：把「修复后会放成空地」的格**裁出来看**（v1.70 的"肉眼核验"同款手法）

帧74/75 上，粗分箱放行的格里只有一格是数据表说"非空地"且分数低到 v1.70 闸门兜不住的：
`(5,7)` 被分类器读成「旅行商人」但 `score` 只有 0.49/0.60（**低分 = 名字不可信**）。
本探针把 `(5,7)` 连同它的 3×3 邻域裁成拼图，**人眼判它到底是什么** ——
    · 若是**平地/岩石纹理** ⇒ 那个"误放"是**表查错了**（低分乱猜）⇒ 粗分箱**纯赚** ✓
    · 若真是**箱子/商人** ⇒ 误放是真的 ⇒ 需要额外闸门 ✗

用法：python android_autoexplore\\tools\\probe_fog_crop_released.py
输出：_tmpman/fogrel/<帧>__r_c__分数.png + 一张拼图 sheet.png
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.dirname(PROJ)
OUT = os.path.join(ROOT, '_tmpman', 'fogrel')
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
import spots as SP                          # noqa: E402

FRAMES = [
    (os.path.join(ROOT, '_tmpman', 'frame74_board_r0_152127.png'), 'S30001', (5, 7)),
    (os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155226.png'), 'S30001', (5, 7)),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    tiles = []
    for fp, code, rc in FRAMES:
        if not os.path.exists(fp):
            continue
        im = cv2.imdecode(np.fromfile(fp, dtype=np.uint8), cv2.IMREAD_COLOR)
        st = SP.Board(code).state(im, thr=0.0)
        v = st.get(rc) or {}
        G = SP.GRID
        r, c = rc
        cx = int(G['x0'] + (c - 1) * G['cx'] + G['cx'] / 2)
        cy = int(G['y0'] + (r - 1) * G['cy'] + G['cy'] / 2)
        # 3×3 邻域
        x0, x1 = cx - int(G['cx'] * 1.5), cx + int(G['cx'] * 1.5)
        y0, y1 = cy - int(G['cy'] * 1.5), cy + int(G['cy'] * 1.5)
        x0, y0 = max(0, x0), max(0, y0)
        sub = im[y0:y1, x0:x1].copy()
        tag = '%s__%d_%d__%s' % (os.path.basename(fp)[:24], r, c,
                                 str(v.get('score')).replace('.', 'p'))
        p = os.path.join(OUT, tag + '.png')
        cv2.imencode('.png', sub)[1].tofile(p)
        # 单格放大 4×（看清纹理）
        s2 = im[cy - int(G['cy'] / 2):cy + int(G['cy'] / 2),
                cx - int(G['cx'] / 2):cx + int(G['cx'] / 2)]
        s2 = cv2.resize(s2, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        p2 = os.path.join(OUT, tag + '__cell4x.png')
        cv2.imencode('.png', s2)[1].tofile(p2)
        print('%-40s %s name=%s score=%s fog_sil=%s ratio=%s floor=%s'
              % (os.path.basename(fp)[:38], '%d,%d' % rc, v.get('name'),
                 v.get('score'), v.get('fog_sil'), v.get('ratio'),
                 v.get('floor_lit')))
        print('   邻域 → %s' % p)
        print('   单格4x → %s' % p2)
        tiles.append(s2)
    if tiles:
        H = max(t.shape[0] for t in tiles)
        W = sum(t.shape[1] for t in tiles) + 20 * (len(tiles) - 1)
        sheet = np.full((H, W, 3), 255, np.uint8)
        x = 0
        for t in tiles:
            sheet[:t.shape[0], x:x + t.shape[1]] = t
            x += t.shape[1] + 20
        sp = os.path.join(OUT, 'sheet.png')
        cv2.imencode('.png', sheet)[1].tofile(sp)
        print('拼图 → %s' % sp)
    return 0


if __name__ == '__main__':
    sys.exit(main())
