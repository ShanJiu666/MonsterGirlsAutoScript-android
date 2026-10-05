# -*- coding: utf-8 -*-
"""⭐ 最终组合验证：**全格按地板纠 revealed** + **visible 加"地板判亮"的块**

## 为什么"visible 加亮块"必须配"地板纠 revealed"
`矿洞 13:38` 的 `1,6`（魔晶矿，带 recommend 图标）：
    `observed=True`（**ratio 0.84 说它亮**）但 `floor=65`（**地板说是雾**）✗
⇒ 若只加 visible、不纠 revealed ⇒ 模型把 `1,6` 当候选 ⇒ **首步就点它** ⇒ 真机点不动 ✗
⇒ 两者**必须配对**：先按地板把 `1,6` 纠成雾，再让 visible 只收"**地板判亮**"的块 ✓

## 本脚本四组对照（判据一律用**帧内 floor**，不用 ratio）
  ① 现状
  ② visible 加"**ratio 口径**的亮块"（= 我上一脚本的②，首步会踩雾格 ✗）
  ③ 全格按地板纠 revealed（不改 visible）
  ④ ③ + visible 加"**地板口径**的亮块"  ← **期望方案**

用法：python D:\\MGAS\\_tmpman\\verify_final_fix.py
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
T = os.environ.get('MGAS_CAL_DIR') or os.path.abspath(os.path.join(PROJ, '..', '_tmpman', 'cal'))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, _PY)
sys.path.insert(0, T)
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
import mapsim as MS                         # noqa: E402
import mapsolve as MV                       # noqa: E402
import explore_loop as EL                   # noqa: E402
from probe_floor_calib import floor_of              # noqa: E402

CASES = (
    ('矿洞 13:38', 'r_133809_0.png', (2, 2),
     {(1, 6): ['recommend'], (4, 2): ['boss']}),
    ('矿洞 13:36', 'r_133620_0.png', (1, 4),
     {(1, 5): ['recommend'], (4, 5): ['boss']}),
)


def prep(frame, camp_rc, marks, floor_all):
    img = cv2.imread(os.path.join(T, frame))
    bd = SP.Board('S30001')
    st = bd.state(img)
    fl = {k: floor_of(bd, img, k[0], k[1]) for k in st}
    vals = sorted(v for v in fl.values() if v is not None)
    hist = {}
    for v in vals:
        hist[round(v)] = hist.get(round(v), 0) + 1
    mode = max(sorted(hist), key=lambda x: (hist[x], -x))
    thr = max(mode * 1.35, mode + 12.0)
    obs = {k: dict(v) for k, v in st.items()}
    for k, ml in marks.items():
        if k in obs:
            obs[k]['marks'] = list(ml)
    if floor_all:
        for k, v in obs.items():
            if fl.get(k) is not None:
                v['revealed'] = bool(fl[k] > thr)
    return obs, fl, thr, bd, img


def build(obs, camp_rc, marks):
    camp_px = EL.cell_center(*camp_rc)
    cells = EL._cells_for_model(
        {'obs': obs, 'spawn': camp_px, 'camp': camp_px, 'done': [],
         'marks': {k: {'marks': list(v)} for k, v in marks.items()}},
        {'st': obs}, log=None, tag='p', mark_revealed=False, drop_done=False)
    sim = MS.MapSim.from_observation(cells, SP.spot_rows())
    return MV.Problem(sim), cells


def solve(prob, lit_blocks):
    """`lit_blocks`：要并进 visible 的块集合（None = 不改）"""
    ch = MV._build_cache(prob)
    if lit_blocks is not None:
        bit = ch['bit']
        m = 0
        for bi in lit_blocks:
            m |= bit.get(bi, 0)
        ch['empty_adj'] = ch.get('empty_adj', 0) | m
    prob._cache = ch
    rep = {}
    cost, plan = MV.solve(prob, max_states=60000, max_secs=8, report=rep)
    out = ['%d,%d' % rc for rc, bi, w in prob.cells_for_plan(plan or [])]
    return cost, out


def main():
    for tag, frame, camp, marks in CASES:
        print('=' * 100)
        print('%s   %s' % (tag, frame))
        # ① 现状
        obs0, fl, thr, bd, img = prep(frame, camp, marks, False)
        prob0, cells0 = build(obs0, camp, marks)
        c0, o0 = solve(prob0, None)
        # ② 只加 ratio 口径的亮块
        prob1, cells1 = build(obs0, camp, marks)
        lit_ratio = {bi for bi, b in prob1.blocks.items() if getattr(b, 'observed', False)}
        c1, o1 = solve(prob1, lit_ratio)
        # ③ 全格按地板
        obs2, _, _, _, _ = prep(frame, camp, marks, True)
        prob2, cells2 = build(obs2, camp, marks)
        c2, o2 = solve(prob2, None)
        # ④ 地板 + 地板口径的亮块
        prob3, cells3 = build(obs2, camp, marks)
        lit_floor = {bi for bi, b in prob3.blocks.items() if getattr(b, 'observed', False)}
        c3, o3 = solve(prob3, lit_floor)

        def stat(out):
            nfog = 0
            for s in out:
                r0, c0 = [int(x) for x in s.split(',')]
                if fl.get((r0, c0)) is not None and fl[(r0, c0)] <= thr:
                    nfog += 1
            fok = None
            if out:
                r0, c0 = [int(x) for x in out[0].split(',')]
                fok = bool(fl.get((r0, c0)) is not None and fl[(r0, c0)] > thr)
            return nfog, fok

        print('  阈值 floor=%.0f（众数 %.0f）' % (thr, mode_of(fl)))
        for label, c, o in (('① 现状', c0, o0),
                            ('② 只加 ratio 口径亮块', c1, o1),
                            ('③ 全格按地板纠 revealed', c2, o2),
                            ('④ ③ + 加**地板口径**亮块 ← 期望', c3, o3)):
            nfog, fok = stat(o)
            print('  %-32s cost=%-5s steps=%-3s 雾格数=%-2s 首步真亮=%-6s'
                  % (label, c, len(o), nfog, fok))
            print('      %s' % (o,))
    return 0


def mode_of(fl):
    vals = sorted(v for v in fl.values() if v is not None)
    hist = {}
    for v in vals:
        hist[round(v)] = hist.get(round(v), 0) + 1
    return max(sorted(hist), key=lambda x: (hist[x], -x))


if __name__ == '__main__':
    sys.exit(main())
