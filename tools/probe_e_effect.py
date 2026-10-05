# -*- coding: utf-8 -*-
"""v1.62 关键判读：E 条（内容地块拦连锁）之后，规划 13→18 是**修对了**还是**改坏了**？

## 冲突
  · 只有 B+C+D 时：矿洞 13:38 ⇒ `cost=13 / 3 步`
  · 加上 E 之后：      同一帧 ⇒ `cost=18 / 8 步`  ← 变差了？
⇒ 必须查清 E 到底拦了哪些块、**那些块是不是真的挡连锁**

## 判据（不用任何被测代码的结论，只看**帧内事实**）
  对每个"因 E 而变成非 plain"的块：
    · 它的 `observed`（观测里亮不亮）+ `floor`（地板法）⇒ **它到底是不是雾**
    · 它是**已揭示**的 ⇒ 名字可信 ⇒ 真是内容地块 ⇒ **该拦** ✓（E 对）
    · 它是**雾**的 ⇒ 名字不可信 ⇒ 拦了反而错 ✗（E 过头了）
    · 它是**在雾里但名字指内容地块**的 ⇒ 看 `floor`（地板法）怎么说 ✓

用法：python android_autoexplore\\tools\\probe_e_effect.py
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
import spots as SP                          # noqa: E402
import targets_cfg as TC                    # noqa: E402
import mapsim as MS                         # noqa: E402
import mapsolve as MV                       # noqa: E402
import explore_loop as EL                   # noqa: E402

FRAME = 'r_133809_0.png'
MARKS = {(1, 6): ['recommend'], (4, 2): ['boss']}
CAMP = (2, 2)


def main():
    img = cv2.imread(os.path.join(CAL, FRAME))
    c = EL.cells_of(img, mapname=None, code='S30001')
    st = c['st']
    thr = EL._floor_thr_now(c)
    for k, ml in MARKS.items():
        if k in st:
            st[k]['marks'] = list(ml)
    plain_names = set(getattr(TC, 'PLAIN_NAMES', ()) or ())
    rows = SP.spot_rows() or {}

    print('=' * 100)
    print('%s   地板阈值=%.1f' % (FRAME, thr))
    print('=' * 100)
    print('逐个"高置信非地面"块：E 条会把它判成非 plain ⇒ 看它**到底是不是雾**')
    print()
    print('  %-6s %-11s %-8s %-7s %-7s %-7s %-9s %s'
          % ('块', 'name', 'sid', 'score', 'floor', '真亮?', 'observed', 'E 该拦吗'))
    sim = MS.MapSim.from_observation(st, SP.spot_rows())
    for bi, b in sorted(sim.blocks.items()):
        nm = str(getattr(b, 'name', '') or '')
        sid = str(getattr(b, 'sid', '') or '')
        sc = float(getattr(b, 'score', 0.0) or 0.0)
        try:
            w = int((rows.get(sid) or {}).get('Weight') or 0)
        except Exception:                   # noqa: BLE001
            w = 0
        is_ground = (w >= 40000) or (nm in plain_names)
        if is_ground or sc < 0.85:
            continue
        # 找这一块的代表格
        cells_idx = list(getattr(b, 'cells', None) or sim.cells_of.get(bi, ()) or ())
        rc0 = None
        for m in cells_idx:
            rc0 = (m // 7 + 1, m % 7 + 1)
            break
        v = st.get(rc0) or {}
        fl = v.get('floor')
        lit = (fl is not None and float(fl) > thr)
        obs = bool(v.get('revealed'))
        # E 该不该拦：**已揭示**的内容地块该拦；（这里按地板法给"真亮"口径）
        verdict = '✓ 该拦（真亮的内容格）' if lit else '✗ 不该拦（其实是雾！）'
        print('  %-6s %-11s %-8s %-7.3f %-7s %-7s %-9s %s'
              % ('%d,%d' % rc0, nm, sid.split('_')[-1], sc,
                 ('%.0f' % fl) if fl is not None else '-',
                 '是' if lit else '**否**', '是' if obs else '否', verdict))

    # 规划对照：**关掉 E 那条** vs **开着**
    print()
    print('=' * 100)
    print('规划对照（同一帧）')
    print('=' * 100)

    def run(with_e):
        _orig = MS.Block.plain
        if not with_e:
            # 猴子补丁：把 E 那条判据拿掉（模拟"只有 B+C+D"）
            def _plain_noe(self):
                try:
                    if getattr(self, '_e_off', False):
                        return self._plain_orig()
                except Exception:           # noqa: BLE001
                    pass
                return _orig.fget(self)
            # 更简单：把 CONTENT_SCORE_MIN 抬到 1.1 ⇒ 那条永不命中 ✓
            _old = MS.CONTENT_SCORE_MIN
            MS.CONTENT_SCORE_MIN = 1.1
        try:
            sim2 = MS.MapSim.from_observation(st, SP.spot_rows())
            prob = MV.Problem(sim2)
            rep = {}
            cost, plan = MV.solve(prob, max_states=60000, max_secs=8, report=rep)
            out = ['%d,%d' % rc for rc, bi, w in prob.cells_for_plan(plan or [])]
        finally:
            if not with_e:
                MS.CONTENT_SCORE_MIN = _old
        return cost, out, sim2

    for label, on in (('E 关（只有 B+C+D）', False), ('E 开（本轮）', True)):
        cost, out, sim2 = run(on)
        npl = sum(1 for b in sim2.blocks.values() if getattr(b, 'plain', False))
        nfog = 0
        for s in out:
            rc = tuple(int(x) for x in s.split(','))
            v = st.get(rc) or {}
            if v.get('floor') is not None and float(v['floor']) <= thr:
                nfog += 1
        print('  %-22s cost=%-5s steps=%-3s plain块=%-3s 雾格数=%s'
              % (label, cost, len(out), npl, nfog))
        print('      %s' % (out,))
    return 0


if __name__ == '__main__':
    sys.exit(main())
