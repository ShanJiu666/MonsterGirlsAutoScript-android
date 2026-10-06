# -*- coding: utf-8 -*-
"""v1.76 取证⑦：**模型层真误差** —— 修复会不会把真内容格放成空地？

前面的比较用的是"逐格 fog_sil 阈值"，那是**中间量**。本探针直接量**最终后果**：
跑完整流水线（`_cells_for_model` → `mapsim.MapSim`），然后逐格问：

    `Block.plain == True`（模型当作空地/可连锁） **且** 数据表说它不是空地
        ⇒ **误放**（solver 会以为连锁能穿过一个内容物）✗

两臂：
  A 现口径（`spots` 原样：0.001 箱）
  C 粗分箱 0.01

同时报"症状"：数据表说是空地、却被判 `plain=False`（= 连锁断 = 用户报的"挨个去点"）。

⚠ 闸门状态按**生产默认**（`MAPBOT_FOG_TABLE` 缺省开），两臂一致 —— 这才是真机行为。

用法：python android_autoexplore\\tools\\probe_fog_plain_errors.py
"""
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
import explore_loop as EL                   # noqa: E402
import marks as MK                          # noqa: E402
import mapsim as MS                         # noqa: E402
import spots as SP                          # noqa: E402

FRAMES = [
    os.path.join(ROOT, '_tmpman', 'frame74_board_r0_152127.png'),
    os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155226.png'),
    os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155553.png'),
    os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155753.png'),
    os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155922.png'),
    os.path.join(ROOT, '_tmpman', 'frame75_board_r0_155652.png'),
    os.path.join(ROOT, '_tmpman', 'cal', 'r_133620_0.png'),
    os.path.join(ROOT, '_tmpman', 'cal', 'r_133809_0.png'),
    os.path.join(ROOT, '_tmpman', 'cal', 'r_180326_0.png'),
    os.path.join(PROJ, '_verify', 'fr1264_r0_board.png'),
    os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_r0.png'),
    os.path.join(PROJ, '_verify', 'phone_friend_nubia_nx809j', 'board_hidden_r2.png'),
    os.path.join(PROJ, '_verify', 'phone_friend_rmx3800', 'board_hidden_r0.png'),
]


def grid_for(shape):
    H, W = shape
    k = W / 1080.0
    sh = H - 1920.0 * k
    G = dict(SP.GRID)
    return {'x0': G['x0'] * k, 'y0': G['y0'] * k + sh, 'cx': G['cx'] * k,
            'cy': G['cy'] * k, 'pitch': G['cx'] * k}


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


def norm_marks(mk):
    out = {}
    for k, v in (mk or {}).items():
        if isinstance(k, str) and ',' in k:
            try:
                k = tuple(int(x) for x in k.split(','))
            except Exception:               # noqa: BLE001
                continue
        if not (isinstance(k, tuple) and len(k) == 2):
            continue
        ml = (v.get('marks') if isinstance(v, dict) else v) or []
        if ml:
            out[k] = {'marks': list(ml)}
    return out


def apply_rule(st, nd):
    """复刻 `spots.py:883-901`，只把分箱粒度参数化；其余（含 K=1.6）一字不动"""
    kk = float(getattr(SP, 'FOG_SIL_MODE_K', 1.6))
    floor = float(SP.FOG_SIL_MIN)
    sils = {k: float(v['fog_sil']) for k, v in st.items()
            if isinstance(k, tuple) and isinstance(v, dict)
            and v.get('fog_sil') is not None}
    if not sils:
        return None
    h = {}
    for s in sils.values():
        h[round(s, nd)] = h.get(round(s, nd), 0) + 1
    mode = max(sorted(h), key=lambda x: (h[x], -x))
    thr = max(floor, float(mode) * kk)
    for v in st.values():
        if isinstance(v, dict) and v.get('fog_sil') is not None:
            v['fog_object'] = bool(float(v['fog_sil']) >= thr)
            v['fog_flat'] = not v['fog_object']
    return thr


def run(st, mk, shape):
    try:
        cp = EL.find_camp_cell(st)
    except Exception:                       # noqa: BLE001
        cp = None
    if cp is None:
        cp = EL.cell_center(2, 2)
    cells = EL._cells_for_model(
        {'obs': st, 'spawn': cp, 'camp': cp, 'done': [], 'marks': mk},
        {'st': st}, log=None, tag='err', mark_revealed=False, drop_done=False)
    sim = MS.MapSim.from_observation(cells, SP.spot_rows())
    errs, broken = [], []
    for r in range(1, 6):
        for c in range(1, 8):
            bi = sim.board[(r - 1) * 7 + (c - 1)]
            if bi < 0:
                continue
            b = sim.blocks[bi]
            obs = cells.get((r, c)) or {}
            try:
                tbl_plain = bool(SP.is_plain_spot(obs.get('sid')))
            except Exception:               # noqa: BLE001
                continue
            if b.plain and not tbl_plain:
                errs.append(('%d,%d' % (r, c), obs.get('name'),
                             round(float(obs.get('score') or 0), 3)))
            if (not b.plain) and tbl_plain:
                broken.append(('%d,%d' % (r, c), obs.get('name')))
    return errs, broken


def main():
    tot = {'A': [0, 0], 'C': [0, 0]}
    print('=' * 104)
    print('%-30s %-8s | %-34s | %s' % ('帧', 'code', 'A 现口径（误放 / 症状）', 'C 粗分箱（误放 / 症状）'))
    print('=' * 104)
    for fp in FRAMES:
        if not os.path.exists(fp):
            continue
        im = cv2.imdecode(np.fromfile(fp, dtype=np.uint8), cv2.IMREAD_COLOR)
        code, _k = pick_code(im)
        if code is None:
            continue
        g = grid_for(im.shape[:2])
        st0 = SP.Board(code, grid=g).state(im, thr=0.0)
        if not st0:
            continue
        mk = norm_marks(MK.scan_board_fast(im))
        for _k2, _v2 in mk.items():
            if _k2 in st0:
                st0[_k2]['marks'] = list(_v2['marks'])
        res = {}
        for tag, nd in (('A', 3), ('C', 2)):
            st = {k: dict(v) for k, v in st0.items()}
            thr = apply_rule(st, nd)
            errs, broken = run(st, mk, im.shape[:2])
            res[tag] = (thr, errs, broken)
            tot[tag][0] += len(errs)
            tot[tag][1] += len(broken)
        print('%-30s %-8s | 误放 %-2d 症状 %-2d (thr %.4f)          | 误放 %-2d 症状 %-2d (thr %.4f)'
              % (os.path.basename(fp)[:30], code,
                 len(res['A'][1]), len(res['A'][2]), res['A'][0] or 0,
                 len(res['C'][1]), len(res['C'][2]), res['C'][0] or 0))
        for tag in ('A', 'C'):
            for nm, name, sc in res[tag][1]:
                print('        [%s] 误放 %-6s %-12s score=%s' % (tag, nm, name, sc))
    print('=' * 104)
    print('合计：A 误放 %d / 症状 %d    C 误放 %d / 症状 %d'
          % (tot['A'][0], tot['A'][1], tot['C'][0], tot['C'][1]))
    sys.stdout.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
