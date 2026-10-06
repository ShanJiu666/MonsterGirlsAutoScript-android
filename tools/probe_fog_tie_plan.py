# -*- coding: utf-8 -*-
"""v1.76 取证④：**模型级后果** —— 阈值塌回 0.04 到底让计划变成什么样？

接力单那条未决只给了"逐格 `fog_object` 差 15 格"，**没给规划后果**。本探针补上
（照 `probe_plan_vs_pc.py` 的公平口径：手机端自己的模板集 + 项目自己的消歧判据 +
真实标记 ⇒ `_cells_for_model` ⇒ `mapsim`/`mapsolve`）：

对每帧跑**两臂**：
  · 臂 A（现状）：`spots` 现口径取众数（0.001 箱 / 平局取小）
  · 臂 B（粗分箱）：把众数取在 **0.01** 粒度上（同一视觉簇自然合并）
     —— 只改 `state()` 里的分箱粒度，其它一字不动

比较：阈值 / `fog_object` 格数 / `plain=False` 格数 / `cost` / 点序 / 目标数。
⚠ 若两臂点序不同 ⇒ 这条未决**确实影响规划**（不只是"多判几格"）。

用法：python android_autoexplore\\tools\\probe_fog_tie_plan.py
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
V = os.path.join(PROJ, '_verify')
CAL = os.path.join(os.path.dirname(PROJ), '_tmpman', 'cal')
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
import mapsolve as MV                       # noqa: E402
import spots as SP                          # noqa: E402

_TMP = os.path.join(os.path.dirname(PROJ), '_tmpman')
FRAMES = [
    # ⭐ 这两张正是**平局塌回 0.04** 的帧（v1.74/v1.75 那两把的真机帧）
    os.path.join(_TMP, 'frame74_board_r0_152127.png'),
    os.path.join(_TMP, 'frame75_board_r0_155226.png'),
    os.path.join(CAL, 'r_133620_0.png'),
    os.path.join(CAL, 'r_133809_0.png'),
    os.path.join(CAL, 'r_180326_0.png'),
    os.path.join(V, 'fr1264_r0_board.png'),
    os.path.join(V, 'phone_redmi_grassland', 'board_grassland_r0.png'),
    os.path.join(V, 'phone_friend_nubia_nx809j', 'board_hidden_r2.png'),
    os.path.join(V, 'phone_friend_rmx3800', 'board_hidden_r0.png'),
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
            bd = SP.Board(c)
            st = bd.state(im, thr=0.0)
        except Exception:                   # noqa: BLE001
            continue
        n = len(st or {})
        hi = sum(1 for v in (st or {}).values() if float(v.get('score') or 0) >= 0.85)
        if key is None or (hi, n) > key:
            best, key = c, (hi, n)
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


def repo_fog(st, nd):
    """复刻 `spots.py:883-901` 的第二趟，只把**分箱粒度**参数化（nd=3 现口径 / 2 粗箱）"""
    kk = float(getattr(SP, 'FOG_SIL_MODE_K', 1.6))
    floor = float(SP.FOG_SIL_MIN)
    sils = {k: float(v['fog_sil']) for k, v in st.items()
            if isinstance(k, tuple) and isinstance(v, dict)
            and v.get('fog_sil') is not None}
    for v in st.values():
        if isinstance(v, dict) and 'fog_object' in v:
            v['fog_object'] = bool(float(v['fog_sil']) >= floor)
            v['fog_flat'] = not v['fog_object']
    if not sils:
        return None, 0
    h = {}
    for s in sils.values():
        h[round(s, nd)] = h.get(round(s, nd), 0) + 1
    mode = max(sorted(h), key=lambda x: (h[x], -x))
    thr = max(floor, float(mode) * kk)
    nobj = 0
    for v in st.values():
        if isinstance(v, dict) and v.get('fog_sil') is not None:
            v['fog_object'] = bool(float(v['fog_sil']) >= thr)
            v['fog_flat'] = not v['fog_object']
            nobj += int(v['fog_object'])
    return thr, nobj


def plain_grid(sim):
    out = {}
    for r in range(1, 6):
        for c in range(1, 8):
            bi = sim.board[(r - 1) * 7 + (c - 1)]
            out['%d,%d' % (r, c)] = (None if bi < 0 else bool(sim.blocks[bi].plain))
    return out


def run_plan(st, mk, im_shape):
    try:
        cp = EL.find_camp_cell(st)
    except Exception:                       # noqa: BLE001
        cp = None
    if cp is None:
        cp = EL.cell_center(2, 2)
    cells = EL._cells_for_model(
        {'obs': st, 'spawn': cp, 'camp': cp, 'done': [], 'marks': mk},
        {'st': st}, log=None, tag='tie', mark_revealed=False, drop_done=False)
    sim = MS.MapSim.from_observation(cells, SP.spot_rows())
    prob = MV.Problem(sim)
    rep = {}
    cost, pl = MV.solve(prob, max_states=60000, max_secs=8, report=rep)
    order = ['%d,%d' % rc for rc, bi, w in prob.cells_for_plan(pl or [])]
    return cost, order, plain_grid(sim), len(prob.targets)


def main():
    print('%-30s %-8s %-9s %-9s %s' % ('帧', 'code', '窗(细/粗)', 'obj(细/粗)', '规划对比'))
    ndiff = 0
    for fp in FRAMES:
        if not os.path.exists(fp):
            continue
        im = cv2.imdecode(np.fromfile(fp, dtype=np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            continue
        code, key = pick_code(im)
        if code is None:
            continue
        g = grid_for(im.shape[:2])
        st = SP.Board(code, grid=g).state(im, thr=0.0)
        if not st:
            continue
        mk = norm_marks(MK.scan_board_fast(im))     # ⭐ 真实标记（没有目标 ⇒ 计划为空 ✗）
        for _k, _v in mk.items():
            if _k in st:
                st[_k]['marks'] = list(_v['marks'])
        res = {}
        for nd, lab in ((3, 'fine'), (2, 'coarse')):
            st2 = {k: dict(v) for k, v in st.items()}
            thr, nobj = repo_fog(st2, nd)
            cost, order, plains, tgt = run_plan(st2, mk, im.shape[:2])
            nplain = sum(1 for v in plains.values() if v is False)
            res[lab] = dict(thr=thr, nobj=nobj, cost=cost, order=order,
                            plains=plains, nplain=nplain, tgt=tgt)
        a, b = res['fine'], res['coarse']
        same = (a['cost'] == b['cost'] and a['order'] == b['order'])
        if not same:
            ndiff += 1
        print('%-30s %-8s %6.4f/%-6.4f %4d/%-4d  cost %-5s/%-5s 步%d/%d plain %d/%d %s'
              % (os.path.basename(fp)[:30], code, a['thr'], b['thr'], a['nobj'],
                 b['nobj'], a['cost'], b['cost'], len(a['order']), len(b['order']),
                 a['nplain'], b['nplain'], '⚠ 不同' if not same else '同'))
        if not same:
            print('      细箱：%s' % a['order'][:8])
            print('      粗箱：%s' % b['order'][:8])
            chg = [k for k in a['plains'] if a['plains'][k] != b['plains'][k]]
            print('      `plain` 改变 %d 格：%s' % (len(chg), sorted(chg)))
    print('=' * 96)
    print('两臂**规划不同**的帧：%d' % ndiff)
    return 0


if __name__ == '__main__':
    sys.exit(main())
