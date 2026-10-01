# -*- coding: utf-8 -*-
"""给 `board_hidden()` 判据②标定阈值：把仓里**所有真机/模拟器实拍棋盘帧**跑一遍，
打印每帧的 ratio 分布（最亮 / 中位 / 最暗 / 压暗数），并按不同相对阈值给出判定。

目的：区分三件长得很像的事
    · **真·面板/遮罩盖住棋盘**（doc 记 m0_r008：整盘压到 0.25~0.35）
    · **刚进图、整盘都是雾格**（雾格 ≈ 0.65；偏暗设备更低，反馈包那台 0.413）
    · **雾格盘 + 一格过亮**（2026-10-02 nubia：最亮格 1.196 ⇒ 旧阈值 0.658 > 雾格 0.650 ⇒ 误判）

⭐ 结论（2026-10-02 v1.21 就是按这张表定的）：
    **雾格/已揭示 = 0.487(realme)~0.61(nubia)**，**真面板/已揭示 = 0.25~0.35**
    ⇒ 阈值取缝中点 **0.42**（对应 `explore_loop.DIM_RATIO_MAX`）
    ⇒ 同时**基准**必须是「已揭示格中位」，不能是「最亮格」（后者会被单格过亮抬高）✗

用法：<py3.11> tools\\fb_calib_boardhidden.py
"""
import glob
import io
import os
import sys
import types

HERE = os.path.abspath(os.path.dirname(__file__))
_PY = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
_ASSETS = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main',
                                       'assets', 'mapbot_pack'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
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


try:
    import rapidocr_onnxruntime        # noqa: F401
except Exception:                      # noqa: BLE001
    _stub('rapidocr_onnxruntime', RapidOCR=type('RapidOCR', (), {'__init__': _noop}))
for _m, _at in (('airtest', {'core': None}), ('airtest.core', {}),
                ('airtest.core.api', {'connect_device': _noop, 'snapshot': _noop,
                                      'touch': _noop, 'swipe': _noop,
                                      'keyevent': _noop, 'exists': _noop,
                                      'Template': object}),
                ('airtest.core.cv', {'Template': object}),
                ('java', {}), ('java.android', {}), ('java.lang', {}),
                ('java.util', {}), ('java.util.concurrent', {})):
    try:
        __import__(_m)
    except Exception:                  # noqa: BLE001
        _stub(_m, **_at)
try:
    import java                       # noqa: F811
    for _s in ('android', 'lang', 'util'):
        if not hasattr(java, _s):
            setattr(java, _s, _stub('java.' + _s))
    if not hasattr(java.util, 'concurrent'):
        java.util.concurrent = _stub('java.util.concurrent')
except Exception:                      # noqa: BLE001
    pass

import numpy as np                                   # noqa: E402
import cv2                                           # noqa: E402
import explore_loop as E                             # noqa: E402

# 只看**棋盘**位置像样的帧（宽高比接近 9:16，且不是菜单/选图/背包全屏）
CANDS = []
for _p in (os.path.join(HERE, '..', '_verify'), r'D:\MGAS\_fb'):
    for _f in glob.glob(os.path.join(_p, '**', '*.png'), recursive=True):
        _n = os.path.basename(_f).lower()
        if any(k in _n for k in ('slot', 'toast', 'zip', 'bar_zoom', 'crop',
                                  'zoom', 'check', 'ovl_', 'mgas_')):
            continue
        CANDS.append(_f)

# doc 里引用的历史基准帧（可能已不在仓里）
DOC = {'m0_r008（doc 记的"结算面板盖中间"基准）': None,
       'nubia 1216×2688（2026-10-02 反馈·棋盘正常）':
           os.path.join(HERE, '..', '_verify', 'phone_friend_nubia_nx809j',
                        'board_hidden_r2.png'),
       'realme 1264×2780（2026-10-01 反馈·棋盘正常）':
           os.path.join(HERE, '..', '_verify', 'phone_friend_rmx3800',
                        'board_hidden_r0.png'),
       'dlg16（真·全盘被遮罩）': os.path.join(HERE, '..', '_verify', 'dlg16.png'),
       'board_now_ref（真机干净基准）':
           os.path.join(HERE, '..', '_verify', 'phone_stamina_0930', 'bagdbg',
                        'board_now_ref.png')}

THRS = (0.55, 0.45, 0.42, 0.40, 0.35, 0.30)


def stat(img, name):
    for _mn in ('夏日海滩', '枯木丛林', None):
        try:
            c = E.cells_of(img, mapname=_mn)
        except Exception:              # noqa: BLE001
            continue
        st = c.get('st') or {}
        if len(st) >= 20:
            return c, st
    return c, st


def main():
    print('=' * 96)
    print('board_hidden() 阈值标定 —— 找「真遮罩」与「整盘雾格」的分界')
    print('=' * 96)
    rows = []
    for tag, p in DOC.items():
        if p and os.path.exists(p):
            _i = cv2.imread(p)
            if _i is not None:
                rows.append((tag, _i))
    for f in sorted(set(CANDS)):
        _i = cv2.imread(f)
        if _i is None:
            continue
        h, w = _i.shape[:2]
        if h < 1000 or not (0.5 < w / float(h) < 0.72):
            continue
        rows.append((os.path.relpath(f, os.path.join(HERE, '..')), _i))

    print('%-46s %5s %6s %6s %6s %6s %6s %s'
          % ('帧', '格数', '最亮', '中位', '最暗', '暗/亮', '空档',
             ' '.join('t%.2f' % t for t in THRS)))
    for tag, img in rows:
        c, st = stat(img, tag)
        rs = [float(v.get('ratio') or 0) for v in st.values()]
        if len(rs) < 20:
            continue
        rs_s = sorted(rs)
        mx = rs_s[-1]
        med = float(np.median(rs))
        lo = rs_s[0]
        # 「亮population 与 暗population 的空档」：把 ratio 按最大跳变切开
        gaps = [(rs_s[i + 1] - rs_s[i], i) for i in range(len(rs_s) - 1)]
        g, gi = max(gaps) if gaps else (0.0, 0)
        out = []
        for t in THRS:
            thr = t * mx
            n = sum(1 for x in rs if x < thr)
            out.append('  H' if n >= 15 else '  .')
        print('%-46s %5d %6.3f %6.3f %6.3f %6.3f %6.3f %s'
              % (tag[:46], len(rs), mx, med, lo, med / mx if mx else 0,
                 g, ' '.join(out)))
    print('\nH = 该相对阈值下会判「棋盘被挡」')
    print('中位/最亮 = 雾格（或被压暗格）占本帧最亮格的比例 —— '
          '雾格≈0.49(本机暗设备)/0.65(标准)，真遮罩≈0.25~0.35')
    return 0


if __name__ == '__main__':
    sys.exit(main())
