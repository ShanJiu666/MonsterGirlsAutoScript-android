# -*- coding: utf-8 -*-
"""十张真实图 · **规划级**对拍：手机端模型/求解器  vs  PC 端模型/求解器

## 它回答什么
「手机端的规划跟 PC 一样吗？」—— 尤其用来验证 `mapsim.Block.plain` 的改动
（ v1.70 雾格数据表闸门）有没有把手机端**对齐**到 PC。

## 方法（公平性很关键）
拿**同一张 PNG 喂两端是不公平的**（两端模板资源不同：562 vs 86、`px` 96 vs 144
—— `AGENTS.md` §v1.62 记着这条）。所以本工具：
  ① 手机端用**自己的**模板集跑出观测 `st`（`Board.state`）
  ② 用**项目自己的消歧判据**选地图 code（`高分格数 → 格数`，同
     `explore_loop._disambiguate_map`）—— **不猜图名**
  ③ 用 `marks.scan_board_fast` 取**真实标记**（没有目标 ⇒ 规划为空，比不出东西）
  ④ `explore_loop._cells_for_model(...)` ⇒ 模型输入 `cells`
  ⑤ **把 `cells` 原样落盘**，PC 端喂**同一份** ⇒ 比的是**纯模型层 + 求解器** ✓

## 三段必须**分开进程**跑
两端模块同名（`mapsim`/`spots`/`mapsolve`）⇒ 同进程里 `import spots` 会**静默**
拿到先导入的那一端的 ✗（本脚本里带 `assert 'mapbot_pc' in …` 自检）

## 用法
    python tools/probe_plan_vs_pc.py                # 一条命令（自己起两个子进程）
    python tools/probe_plan_vs_pc.py --side mobile  # 或手工分三段
    python tools/probe_plan_vs_pc.py --side pc
    python tools/probe_plan_vs_pc.py --side compare

产物（默认 `<仓>/../_tmpman/plan_vs_pc/`，可用 `MGAS_PLAN_CMP_DIR` 覆盖）：
    plan_cells.py    手机端产出的模型输入（PC 端喂这一份）
    mobile.json      手机端 cost/点序/逐格 plain（**闸门开与关各一份**）
    pc.json          PC 端 cost/点序/逐格 plain

判定：**手机端（闸门开） vs PC 应当逐帧一致**；
      ⭐ 最有说服力的对照是「手机端（闸门**关**） vs PC」——
      若那里**不一致**、而开着一致 ⇒ 正说明本次改动把手机端**对齐到了 PC** ✓
"""
import argparse
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)                       # android_autoexplore/
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
PC_DIR = os.environ.get('MGAS_PC_SRC') or os.path.join(
    os.path.dirname(PROJ), 'mapbot_pc')
OUTDIR = os.environ.get('MGAS_PLAN_CMP_DIR') or os.path.join(
    os.path.dirname(PROJ), '_tmpman', 'plan_vs_pc')

# 候选帧：**真实整盘帧**（1080×1920 参考系；缺的自动跳过）
V = os.path.join(PROJ, '_verify')
CAL = os.path.join(os.path.dirname(PROJ), '_tmpman', 'cal')
FRAMES = [
    os.path.join(CAL, 'r_133620_0.png'),        # 矿洞 13:36
    os.path.join(CAL, 'r_133809_0.png'),        # 矿洞 13:38（v1.62/v1.70 的关键帧）
    os.path.join(CAL, 'r_145515_0.png'),
    os.path.join(CAL, 'r_150207_0.png'),
    os.path.join(CAL, 'r_180326_0.png'),
    os.path.join(CAL, 'r_152223_0.png'),        # ⚠ 系统对话框盖住棋盘（坏帧，留作负样本）
    os.path.join(CAL, '_dup_boss.png'),         # 造帧：把 boss 图标整格复制（v1.63 牙齿）
    os.path.join(V, 'fr1264_r0_board.png'),     # 遗忘之海
    os.path.join(V, 'dev_board_r0.png'),
    os.path.join(V, 'phone_redmi_grassland', 'board_grassland_r0.png'),
    os.path.join(V, 'phone_redmi_grassland', 'board_grassland_live.png'),
    os.path.join(V, 'phone_friend_nubia_nx809j', 'board_hidden_r2.png'),
    os.path.join(V, 'phone_friend_nubia_nx729j', 'board_hidden_r0.png'),
    os.path.join(V, 'phone_friend_rmx3800', 'board_hidden_r0.png'),
    os.path.join(V, 'phone_stamina_0930', 'bagdbg', 'iron_highland_fog_dev.png'),
]


def _u8():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:       # noqa: BLE001
        pass


def _grid_for(shape, spots_mod):
    """按 `RefMapper` 同款缩放建网格（1080 宽时退化为原样 ✓）"""
    H, W = shape
    k = W / 1080.0
    sh = H - 1920.0 * k
    G = dict(spots_mod.GRID)
    return {'x0': G['x0'] * k, 'y0': G['y0'] * k + sh, 'cx': G['cx'] * k,
            'cy': G['cy'] * k, 'pitch': G['cx'] * k}


# ------------------------------------------------------------------ mobile
def side_mobile():
    _u8()
    sys.path.insert(0, PYDIR)
    os.environ['MAPBOT_ROOT'] = ASSETS
    os.makedirs(OUTDIR, exist_ok=True)

    import cv2 as cv                                             # noqa: E402
    import numpy as np                                           # noqa: E402
    import explore_loop as EL                                    # noqa: E402
    import marks as MK                                           # noqa: E402
    import mapsim as MS                                          # noqa: E402
    import mapsolve as MV                                        # noqa: E402
    import spots as SP                                           # noqa: E402
    assert 'android_autoexplore' in SP.__file__, SP.__file__

    codes = sorted(set((SP.map_table() or {}).values()))
    print('手机端 mapsim =', MS.__file__)
    print('可选 code（%d）：%s' % (len(codes), codes))
    print()

    def pick_code(im):
        best, key = None, None
        for c in codes:
            bd = EL.board_for(code=c)
            if bd is None:
                continue
            try:
                st = bd.state(im)
            except Exception:       # noqa: BLE001
                continue
            n = len(st or {})
            hi = sum(1 for v in (st or {}).values()
                     if float(v.get('score') or 0) >= 0.85)
            if key is None or (hi, n) > key:
                best, key = c, (hi, n)
        return best, key

    def norm_marks(mk):
        out = {}
        for k, v in (mk or {}).items():
            if isinstance(k, str) and ',' in k:
                try:
                    k = tuple(int(x) for x in k.split(','))
                except Exception:       # noqa: BLE001
                    continue
            if not (isinstance(k, tuple) and len(k) == 2):
                continue
            ml = (v.get('marks') if isinstance(v, dict) else v) or []
            if ml:
                out[k] = {'marks': list(ml)}
        return out

    def plains_of(sim, mod):
        out = {}
        for r in range(1, 6):
            for c in range(1, 8):
                bi = sim.board[(r - 1) * 7 + (c - 1)]
                out['%d,%d' % (r, c)] = (None if bi < 0
                                         else bool(sim.blocks[bi].plain))
        return out

    DATA, MOB = {}, {}
    for fr in FRAMES:
        name = os.path.basename(fr)
        if not os.path.exists(fr):
            print('%-34s 缺帧（跳过）' % name)
            continue
        im = cv.imdecode(np.fromfile(fr, dtype=np.uint8), cv.IMREAD_COLOR)
        code, key = pick_code(im)
        if code is None:
            print('%-34s 所有 code 都认不出（跳过）' % name)
            continue
        g = _grid_for(im.shape[:2], SP)
        st = SP.Board(code, grid=g).state(im, thr=0.0)
        mk = norm_marks(MK.scan_board_fast(im))
        for _k, _v in mk.items():
            if _k in st:
                st[_k]['marks'] = list(_v['marks'])
        try:
            cp = EL.find_camp_cell(st)
        except Exception:       # noqa: BLE001
            cp = None
        if cp is None:
            cp = EL.cell_center(2, 2)

        cells = EL._cells_for_model(
            {'obs': st, 'spawn': cp, 'camp': cp, 'done': [], 'marks': mk},
            {'st': st}, log=None, tag='p10', mark_revealed=False, drop_done=False)

        def plan(gate):
            MS.FOG_TABLE_GATE = gate
            sim = MS.MapSim.from_observation(cells, SP.spot_rows())
            prob = MV.Problem(sim)
            rep = {}
            cost, pl = MV.solve(prob, max_states=60000, max_secs=8, report=rep)
            order = ['%d,%d' % rc for rc, bi, w
                     in prob.cells_for_plan(pl or [])]
            return (cost, order, plains_of(sim, MS), len(prob.targets),
                    rep.get('reason'))

        c_on, o_on, p_on, tgt, why = plan(True)
        c_off, o_off, p_off, _t2, _w2 = plan(False)
        MS.FOG_TABLE_GATE = True

        DATA[name] = {'code': code, 'cells': cells, 'n_cells': len(cells),
                      'n_marks': len(mk)}
        MOB[name] = {'code': code, 'pick_key': list(key), 'n_cells': len(cells),
                     'n_marks': len(mk), 'camp': list(cp), 'targets': tgt,
                     'cost': c_on, 'order': o_on, 'plain': p_on,
                     'cost_off': c_off, 'order_off': o_off, 'plain_off': p_off,
                     'reason': why}
        print('%-34s code=%-8s 判据=%-11s 格=%-3d 标记=%-2d 目标=%-2d '
              'cost(关)=%-5s cost(开)=%-5s 步=%-2d %s'
              % (name, code, key, len(cells), len(mk), tgt, c_off, c_on,
                 len(o_on), o_on[:5]))

    with open(os.path.join(OUTDIR, 'plan_cells.py'), 'w', encoding='utf-8') as f:
        f.write('# -*- coding: utf-8 -*-\n')
        f.write('# 手机端产出的模型输入（逐帧）—— PC 端喂同一份\n')
        f.write('DATA = ' + repr(DATA) + '\n')
    with open(os.path.join(OUTDIR, 'mobile.json'), 'w', encoding='utf-8') as f:
        json.dump(MOB, f, ensure_ascii=False, indent=1)
    print()
    print('已落盘 %s（%d 帧有效）' % (OUTDIR, len(DATA)))
    sys.stdout.flush()


# ------------------------------------------------------------------ pc
def side_pc():
    _u8()
    sys.path.insert(0, OUTDIR)
    sys.path.insert(0, PC_DIR)
    import mapsim as PCS                                         # noqa: E402
    import mapsolve as PCV                                       # noqa: E402
    import spots as PCSP                                         # noqa: E402

    assert 'mapbot_pc' in PCS.__file__, PCS.__file__
    assert 'mapbot_pc' in PCSP.__file__, PCSP.__file__
    import plan_cells as D                                       # noqa: E402
    print('PC mapsim =', PCS.__file__)
    print('喂入 %d 帧（与手机端**同一份** cells）' % len(D.DATA))
    print()

    rows = PCSP.spot_rows()
    OUT = {}
    for name, rec in D.DATA.items():
        sim = PCS.MapSim.from_observation(rec['cells'], rows)
        prob = PCV.Problem(sim)
        rep = {}
        cost, pl = PCV.solve(prob, max_states=60000, max_secs=8, report=rep)
        order = ['%d,%d' % rc for rc, bi, w in prob.cells_for_plan(pl or [])]
        plains = {}
        for r in range(1, 6):
            for c in range(1, 8):
                bi = sim.board[(r - 1) * 7 + (c - 1)]
                plains['%d,%d' % (r, c)] = (None if bi < 0
                                            else bool(sim.blocks[bi].plain))
        OUT[name] = {'code': rec['code'], 'cost': cost, 'order': order,
                     'plain': plains, 'targets': len(prob.targets),
                     'reason': rep.get('reason')}
        print('%-34s code=%-8s cost=%-5s 步=%-2d 目标=%-2d %s'
              % (name, rec['code'], cost, len(order), len(prob.targets),
                 order[:5]))
    with open(os.path.join(OUTDIR, 'pc.json'), 'w', encoding='utf-8') as f:
        json.dump(OUT, f, ensure_ascii=False, indent=1)
    print()
    print('已落盘 %s/pc.json' % OUTDIR)
    sys.stdout.flush()


# ------------------------------------------------------------------ compare
def side_compare():
    _u8()
    M = json.load(open(os.path.join(OUTDIR, 'mobile.json'), encoding='utf-8'))
    P = json.load(open(os.path.join(OUTDIR, 'pc.json'), encoding='utf-8'))

    print('=' * 118)
    print('十张真实图 · 规划级对拍（同一份观测 ⇒ 手机端模型/求解器 vs PC 端模型/求解器）')
    print('=' * 118)
    print('%-32s %-7s %-4s %-24s %-24s %s'
          % ('帧', 'code', '标记', '手机端（闸门开）', 'PC 端', '判定'))
    print('-' * 118)
    rows = []
    n_same = 0
    for name in M:
        a, b = M[name], P.get(name)
        if b is None:
            continue
        pa = '%s / %s步 %s' % (a['cost'], len(a['order']),
                               ','.join(x.replace(',', '.') for x in a['order'][:4]))
        pb = '%s / %s步 %s' % (b['cost'], len(b['order']),
                               ','.join(x.replace(',', '.') for x in b['order'][:4]))
        same = (a['cost'] == b['cost'] and a['order'] == b['order'])
        dpl = [k for k in a['plain']
               if a['plain'][k] is not None and a['plain'][k] != b['plain'].get(k)]
        n_same += 1 if same else 0
        rows.append((name, a, b, same, dpl))
        print('%-32s %-7s %-4d %-24s %-24s %s'
              % (name[:32], a['code'], a['n_marks'], pa, pb,
                 ('**一致** ✓' if same else '**不同** ⚠')
                 + ('' if not dpl else '｜plain 差 %d 格' % len(dpl))))
    print('-' * 118)
    print('规划完全一致：%d / %d 帧' % (n_same, len(rows)))
    print()

    print('=== ★ 关键对照：手机端（闸门**关**）vs PC（PC 自己有闸门）===')
    n_off = 0
    for name, a, b, _s, _d in rows:
        if a['cost_off'] == b['cost'] and a['order_off'] == b['order']:
            n_off += 1
        else:
            print('  · %-28s 手机(关) cost=%-5s %-34s | PC cost=%-5s %s'
                  % (name[:28], a['cost_off'], a['order_off'][:3],
                     b['cost'], b['order'][:4]))
    print('  一致 %d / %d 帧' % (n_off, len(rows)))
    print('  ⇒ 这里**不一致**、而「手机(开) vs PC」一致 ⇒ 正说明本次改动'
          '把手机端**对齐到了 PC** ✓（不是"碰巧一样"）')
    print()

    print('=== 附：闸门在手机端自己身上的影响（关 -> 开）===')
    n_ch = 0
    for name, a, _b, _s, _d in rows:
        ch = [k for k in a['plain_off'] if a['plain_off'][k] is not None
              and a['plain_off'][k] != a['plain'].get(k)]
        s = (a['cost_off'] == a['cost'] and a['order_off'] == a['order'])
        n_ch += 0 if s else 1
        print('  %-32s 关=%-16s 开=%-16s %s（%d 格 plain 被改）'
              % (name[:32], 'cost=%s/%d步' % (a['cost_off'], len(a['order_off'])),
                 'cost=%s/%d步' % (a['cost'], len(a['order'])),
                 '规划不变' if s else '**规划变了**', len(ch)))
        # ⚠ cost/步数**相同也可能规划不同**（点的是别的格）⇒ 变了就把点序也打出来
        if not s:
            print('       关：%s' % a['order_off'])
            print('       开：%s' % a['order'])
    print('  闸门让规划发生变化的帧：%d / %d' % (n_ch, len(rows)))
    print('  ⚠ 规划没变 ≠ 闸门没生效：闸门改的是"内容格拦不拦连锁"，'
          '最优解本来不穿那些格时规划自然不变 ✓')
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description='十张真实图 · 规划级对端对拍')
    ap.add_argument('--side', choices=['mobile', 'pc', 'compare'],
                    help='只跑某一段（两端模块同名 ⇒ 必须分开进程）')
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)
    if a.side == 'mobile':
        side_mobile()
    elif a.side == 'pc':
        side_pc()
    elif a.side == 'compare':
        side_compare()
    else:
        # 一条命令：自己起两个子进程。⚠ **不让父进程捕获子进程输出**（不走管道），
        #   子进程各写自己的文件，最后由 compare 读 ✓
        for s in ('mobile', 'pc'):
            print('########## %s ##########' % s, flush=True)
            rc = subprocess.call([sys.executable, os.path.abspath(__file__),
                                  '--side', s])
            if rc != 0:
                raise SystemExit('side=%s 失败 exit=%s' % (s, rc))
        print('########## compare ##########', flush=True)
        side_compare()


if __name__ == '__main__':
    main()
