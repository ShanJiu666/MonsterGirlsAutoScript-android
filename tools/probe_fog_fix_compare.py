# -*- coding: utf-8 -*-
"""v1.76 取证⑥：三条候选口径的**全语料决策表**（选哪条修，用这张表说话）

现口径（病）：直方图按 `round(v, 3)` 分箱 ⇒ "岩地"这一**同一个视觉簇**被切成
0.1126/0.1136/0.1137/0.1141/0.1147/0.1148/0.1152 … 各 3~7 票；而"真平坦雾格"恰好都
**精确等于 0.0000** ⇒ 一个箱拿走全部那些票 ⇒ 众数落到 0.0 ⇒ 阈值 = 0.04
（< 岩地纹理 0.11）⇒ **整片岩地判"雾下有东西"** ⇒ `plain=False` ⇒ 连锁全断 ⇒ 一格一格点。

三个候选：
  A 现口径              `round(v,3)` + 平局取小
  B 平局取较大值        `round(v,3)` + `(count, +v)`
  C **粗分箱 0.01**     `round(v,2)` + 平局取小   ← 同一视觉簇自然合并

每帧输出三种口径各自的：阈值 / `fog_object` 格数，以及**两条安全判据**：
  ⛔ 误放（把真内容物放成空地）：取该口径下翻成"空地"的格，查数据表说它不是空地
     ⇒ 分两类：`score>=0.85`（v1.70 闸门**兜得住** ✓）/ `score<0.85`（**兜不住** ✗）
  ✗ 症状未除：仍有"表说是空地、却判雾下有东西"的格（= 连锁仍断）

用法：python android_autoexplore\\tools\\probe_fog_fix_compare.py
"""
import glob
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.dirname(PROJ)
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

KK = float(getattr(SP, 'FOG_SIL_MODE_K', 1.6))
FLOOR = float(SP.FOG_SIL_MIN)
GATE_MIN = 0.85
SKIP = ('slot', 'toast', 'zip', 'bar_zoom', 'crop', 'zoom', 'check', 'ovl_', 'mgas_',
        'select', 'menu', 'bag', 'vault', 'settle', 'ui_v', 'dlg', 'stuck', 'blocked',
        'review', 'cells', 'grid', 'rail', 'hud', 'clover', 'annot', 'small', 'raw')


def pick_code(im):
    best, key = None, None
    for c in sorted(set((SP.map_table() or {}).values())):
        try:
            st = SP.Board(c).state(im, thr=0.0)
        except Exception:                   # noqa: BLE001
            continue
        n = len(st or {})
        hi = sum(1 for v in (st or {}).values() if float(v.get('score') or 0) >= 0.85)
        camp = any((v or {}).get('name') == '营地' for v in (st or {}).values())
        k2 = (camp, hi, n)
        if key is None or k2 > key:
            best, key = c, k2
    return best, key


def rules(vals, sids=None):
    """五条候选 ⇒ {名字: (阈值, 众数)}

    ⚠ `D`/`E` 需要 `sids`（逐格 sid，用来查数据表"这是不是空地"）——
      语义：众数要估的是**本图地面纹理**，所以**只在数据表说是空地的格上取样** ✓
      （这正是接力单建议的那条；比"按名字"更硬 —— 名字在雾里不可信，数据表是游戏规则）
    """
    out = {}
    for name, nd, tie in (('A 现口径', 3, 'small'),
                          ('B 平局取大', 3, 'large'),
                          ('C 粗分箱0.01', 2, 'small')):
        h = {}
        for v in vals:
            h[round(v, nd)] = h.get(round(v, nd), 0) + 1
        if tie == 'small':
            m = max(sorted(h), key=lambda x: (h[x], -x))
        else:
            m = max(sorted(h), key=lambda x: (h[x], x))
        out[name] = (max(FLOOR, float(m) * KK), float(m))
    if sids is not None:
        grd = [v for k, v in sids.items() if v is True]      # True = 表说是空地
        for name, nd in (('D 只算空地(细箱)', 3), ('E 只算空地+粗箱', 2)):
            if not grd:
                out[name] = None
                continue
            h = {}
            for v in grd:
                h[round(v, nd)] = h.get(round(v, nd), 0) + 1
            m = max(sorted(h), key=lambda x: (h[x], -x))
            out[name] = (max(FLOOR, float(m) * KK), float(m))
    # F = 粗分箱 + 平局取大（两条一起上）；G = 细箱但**排除退化值 0.0**
    for name, nd, tie in (('F 粗箱+平局取大', 2, 'large'),):
        h = {}
        for v in vals:
            h[round(v, nd)] = h.get(round(v, nd), 0) + 1
        m = max(sorted(h), key=lambda x: (h[x], x))
        out[name] = (max(FLOOR, float(m) * KK), float(m))
    pos = [v for v in vals if v > 0]
    if pos:
        h = {}
        for v in pos:
            h[round(v, 3)] = h.get(round(v, 3), 0) + 1
        m = max(sorted(h), key=lambda x: (h[x], -x))
        out['G 排除0.0(细箱)'] = (max(FLOOR, float(m) * KK), float(m))
    else:
        out['G 排除0.0(细箱)'] = (FLOOR, 0.0)
    # ⭐ H = **两级众数**：先用粗箱(0.01)定位"地面纹理簇"，再用**簇内出现最多的细值**
    #    作代表 ⇒ 量纲不变、阈值不变 ⇒ 只在"细箱众数被碎片抢走"时才纠正 ✓（最小改动）
    for name, nd in (('H 两级众数', 2),):
        grp = {}
        for v in vals:
            grp.setdefault(round(v, nd), {})
            d = grp[round(v, nd)]
            d[round(v, 3)] = d.get(round(v, 3), 0) + 1
        tot = {k: sum(d.values()) for k, d in grp.items()}
        win = max(sorted(tot), key=lambda x: (tot[x], -x))
        m = max(sorted(grp[win]), key=lambda x: (grp[win][x], -x))
        out[name] = (max(FLOOR, float(m) * KK), float(m))
    return out


def frames():
    """限定一组**已确认的整盘帧**（全语料扫太慢，且多数帧与 fog_sil 无关）"""
    cand = [
        os.path.join(ROOT, '_tmpman', 'frame74_board_r0_152127.png'),
        os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155226.png'),
        os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155553.png'),
        os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155753.png'),
        os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155922.png'),
        os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155652.png'),
        os.path.join(ROOT, '_tmpman', 'cal', 'r_133620_0.png'),
        os.path.join(ROOT, '_tmpman', 'cal', 'r_133809_0.png'),
        os.path.join(ROOT, '_tmpman', 'cal', 'r_180326_0.png'),
        os.path.join(ROOT, '_tmpman', 'cal', 'r_152223_0.png'),
        os.path.join(PROJ, '_verify', 'fr1264_r0_board.png'),
        os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_r0.png'),
        os.path.join(PROJ, '_verify', 'phone_friend_nubia_nx809j', 'board_hidden_r2.png'),
        os.path.join(PROJ, '_verify', 'phone_friend_rmx3800', 'board_hidden_r0.png'),
    ]
    return [p for p in cand if os.path.exists(p)]


def main():
    NAMES = ('A 现口径', 'H 两级众数', 'C 粗分箱0.01')
    tally = {k: dict(frames=0, bad_free=0, bad_free_low=0, still_broken=0, obj=0)
             for k in NAMES}
    detail = []
    for fp in frames():
        im = cv2.imdecode(np.fromfile(fp, dtype=np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            continue
        h, w = im.shape[:2]
        if h < 1000 or not (0.4 < w / float(h) < 0.75):
            continue
        code, key = pick_code(im)
        if code is None or not any((v or {}).get('name') == '营地'
                                   for v in SP.Board(code).state(im, thr=0.0).values()):
            continue
        st = SP.Board(code).state(im, thr=0.0)
        sils = {k: float(v['fog_sil']) for k, v in st.items()
                if isinstance(k, tuple) and isinstance(v, dict)
                and v.get('fog_sil') is not None}
        vals = list(sils.values())
        if len(vals) < 5:
            continue
        # 逐格"表说是空地吗"（True/False/None=查不到）
        sids = {}
        for k in sils:
            v = st.get(k) or {}
            try:
                sids[k] = bool(SP.is_plain_spot(v.get('sid')))
            except Exception:               # noqa: BLE001
                sids[k] = None
        R = rules(vals, sids)
        row = [os.path.basename(fp)[:30], code, len(vals)]
        bad = {}
        for name in NAMES:
            t = tally[name]
            t['frames'] += 1
            got = R.get(name)
            if not got:
                bad[name] = None
                continue
            thr, mode = got
            obj = [k for k in sils if sils[k] >= thr]
            t['obj'] += len(obj)
            free = [k for k in sils if sils[k] < thr]
            bf, bf_lo = [], []
            for k in free:
                if sids.get(k) is False:
                    sc = float((st.get(k) or {}).get('score') or 0)
                    if sc >= GATE_MIN:
                        bf.append(k)
                    else:
                        bf_lo.append(k)
            t['bad_free'] += len(bf)
            t['bad_free_low'] += len(bf_lo)
            broken = sum(1 for k in obj if sids.get(k) is True)
            t['still_broken'] += broken
            bad[name] = (round(thr, 4), len(obj), len(bf), len(bf_lo), broken)
        detail.append((row, bad))

    print('=' * 128)
    print('%-32s %-7s %4s | %s' % ('帧', 'code', '格',
                                   'A:阈值/obj/兜/兜不住/仍断  B 同            C 同            D 同            E 同'))
    print('=' * 128)
    for row, bad in detail:
        cells = []
        for name in NAMES:
            v = bad.get(name)
            cells.append('—' if not v else '%.4f %3d %2d %2d %3d'
                         % (v[0], v[1], v[2], v[3], v[4]))
        a = bad.get('A 现口径')
        e = bad.get('H 两级众数')
        note = ''
        if a and e and e[4] < a[4]:
            note = '  ← H 修好 %d 格连锁' % (a[4] - e[4])
        if a and e and e[3] > a[3]:
            note += '  ⛔ H 多放行 %d 个低分内容物' % (e[3] - a[3])
        print('%-32s %-7s %4d | %s%s' % (row[0], row[1], row[2], '  '.join(cells), note))
    print('=' * 128)
    print('%-20s %6s %8s %10s %12s %10s' % ('口径', '帧数', 'obj合计', '闸门可兜',
                                             '兜不住(⛔)', '仍断(✗)'))
    for name in NAMES:
        t = tally[name]
        print('%-20s %6d %8d %10d %12d %10d'
              % (name, t['frames'], t['obj'], t['bad_free'], t['bad_free_low'],
                 t['still_broken']))
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
