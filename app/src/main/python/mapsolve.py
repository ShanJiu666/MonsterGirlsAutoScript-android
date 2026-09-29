# -*- coding: utf-8 -*-
"""mapsolve.py · **最优策略搜索（按体力最省）**（地图/探索层）

⭐ 目标函数 = **消耗体力最少**（用户 2026-09-25：「要按消耗体力最少的方案走」），不是点击次数。

体力公式（源码 82956-82992 MapBlock）：
    singleEnergyConsume  = SpotSize        # 点普通格/空地
    fightEnergyConsume   = SpotSize * 2    # 战斗格
    exploreEnergyConsume = SpotSize * 2    # 探索产出格
    （传送门块 = 0；进图另收 mapExploreEnergyCost = 25，与地图内策略无关）
    实测印证：我们统计里"进图体力 −25"就是这么来的 ✓

为什么能求最优：点击结果是确定性的（空地→连通整片消耗；内容格→消耗该块），
状态只由「已消耗的地块集合」决定 ⇒ 用 **Dijkstra（按体力边权）** 求到目标态的最小体力 ✓

状态：
    state = frozenset(已消耗 block idx)
    可见 = 营地 ∪ 与已消耗格 4 邻接的块；目标 = 带标记 ∪ 商人/宝库（未消耗）
    动作 = 点一个可见未消耗块；代价 = 该块（或整片空地）的体力
    目标态 = 所有目标块都被消耗

用法：
    python mapsolve.py --bench 200 --map 夏日海滩 --difficulty 100
        → 同 200 张盘上对比「基线策略」vs「体力最优」的体力与点击数
"""

# ─────────────────────────────────────────────────────────────────────────────
# 【Android 适配补丁 · 由 android_autoexplore/tools/port_android.py 注入，勿手改】
# Chaquopy 里 __file__ 指向 APK 内只读资源，模板/数据表在 filesDir/mapbot_pack
#  ⇒ 资源根一律走环境变量，未设置时回退 PC 原行为（便于与 PC 对拍）
import os as _os

_MAPBOT_ROOT = _os.environ.get('MAPBOT_ROOT') or _os.path.dirname(_os.path.abspath(__file__))
_MAPBOT_RUNS = _os.environ.get('MAPBOT_RUNS') or _os.path.join(_MAPBOT_ROOT, 'runs')
_MAPBOT_DT = _os.environ.get('MAPBOT_DT') or _os.path.join(_MAPBOT_ROOT, 'server_datatable.json')
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import heapq
import io
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROWS, COLS = 5, 7
NCELL = ROWS * COLS
FIGHT_X2 = {'boss', 'redEquip', 'recommend', 'battle'}      # 战斗格：体力 ×2


class Problem:
    """把一张盘编译成"搜索用"的纯数据（不依赖 MapSim 的可变状态）"""

    def __init__(self, sim):
        self.board = list(sim.board)                       # cell -> block idx
        self.blocks = {b.idx: b for b in sim.blocks.values()}
        self.cells_of = {i: [] for i in self.blocks}
        for c, bi in enumerate(self.board):
            if bi >= 0:
                self.cells_of[bi].append(c)
        self.camp = None
        for b in self.blocks.values():
            if '营地' in (b.name or ''):
                self.camp = b.idx
        self.targets = set()
        for b in self.blocks.values():
            # ⭐⭐⭐ 2026-09-28 用户要求（「勾选某一种方块，后续就专门去拿；不勾就不规划」）：
            #   `Block.want` 由调用方（explore_loop + `targets_cfg` 白名单）明确给出 ⇒ **以它为准** ✓
            #     want=True  ⇒ 进目标（哪怕没标记：宝箱/海螺/多格建筑… ✓）
            #     want=False ⇒ **不进目标**（哪怕挂着 boss 标记、是商人 ⇒ 用户就是不要 ✓）
            #   want=None（老调用：mapevolve 等）⇒ 退回老口径 `mark or is_buy` ✓ 向后兼容
            want = getattr(b, 'want', None)
            hit = (bool(want) if want is not None else bool(b.mark or b.is_buy))
            if hit:
                self.targets.add(b.idx)

    # ---------- 状态派生 ----------
    def consumed_cells(self, state):
        out = set()
        for bi in state:
            out.update(self.cells_of.get(bi, ()))
        return out

    def visible(self, state):
        """可点格 ✓

        ⭐ 2026-09-27 修正（用户三次口径都指向这件事）：
            「最开始就是只有**营地挨着的四个格子**可以点」
            「规划步数去掉点击出生点那格」
            ⇒ **营地本身不可点** ✗（它只是出生点标记 ✓）
            ⇒ 开局可点 = **营地的四个邻居** ✓（地图生成时就是亮的 ✓）
        可点 = ① 与已消耗格 4 邻接的（连锁揭示 ✓）
               ∪ ② 营地的 4 邻接格（开局起手 ✓）
        """
        vis = set()

        def _add_nb(cell):
            r, cc = cell // COLS, cell % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, ccc = r + dr, cc + dc
                if 0 <= rr < ROWS and 0 <= ccc < COLS:
                    bi = self.board[rr * COLS + ccc]
                    # ⭐ 2026-09-28：**营地永久排除**（它不可点，点了只弹个无用面板、
                    #   不消耗不揭示 —— explore_loop 也把它直接当"已完成"排除 ✓）
                    #   否则 solver 可能安排"点营地"当跳板 ⇒ 真机空转一步 ✗
                    if bi >= 0 and bi not in state and bi != self.camp:
                        vis.add(bi)

        # ① 与已消耗格相邻（连锁揭示出来的 ✓）
        for c in self.consumed_cells(state):
            _add_nb(c)
        # ② 营地的四个邻居（开局起手 ✓）—— 营地自己**不加** ✗
        if self.camp is not None:
            for cc2 in self.cells_of.get(self.camp, ()):
                _add_nb(cc2)
        return vis

    def plain_group(self, bi):
        """该空地所在的连通空地整片（源码 GetConnectedPlainBlocks）"""
        if not self.blocks[bi].plain:
            return {bi}
        got, seen, q = {bi}, set(), deque([bi])
        while q:
            cur = q.popleft()
            for c in self.cells_of.get(cur, ()):
                r, cc = c // COLS, c % COLS
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    rr, ccc = r + dr, cc + dc
                    if not (0 <= rr < ROWS and 0 <= ccc < COLS):
                        continue
                    nb = self.board[rr * COLS + ccc]
                    if nb < 0 or nb in got or nb in seen:
                        continue
                    # ⭐⭐⭐ 2026-09-28 用户口径修正（真机已证）：连锁**能穿过雾**，
                    #   但**只穿草地**（`plain` 已把营地/宝箱/海螺/岩石等排除 ✓）。
                    #   证据：用户报「点 (1,5) 只揭开 (1,5)(1,6)(1,7) 三格，被宝箱、
                    #   海螺和出生地挡住」+「(2,4)→(5,4) 两步就完事」；真机体力 7 点
                    #   （1+6），而不是本模型旧版算的 8 点（1+1+6）✗。
                    #   ⚠ 09-27 那条「只穿已揭示」是**误诊**：当时"走不通"的真因是
                    #     起点/可点集合把未揭示格也算进去了（`Problem.visible` 管），
                    #     不是连锁范围 ⇒ 用"截断连锁"去治，压住了症状但让片普遍偏小 ✗
                    _nb_b = self.blocks[nb]
                    if _nb_b.plain:
                        seen.add(nb)
                        got.add(nb)
                        q.append(nb)
        return got

    def step(self, state, bi):
        """点一块 → 新状态（空地整片消耗；其他只消耗自己）"""
        if self.blocks[bi].plain:
            return frozenset(state | self.plain_group(bi))
        return frozenset(state | {bi})

    # ---------- 体力代价 ----------
    @staticmethod
    def block_cost(b):
        """体力（按**数据表口径** ✓ 2026-09-27 第二次修）

        数据表 `Area_Spot`：`SpotSize` = 格数（椰树 2 / 游乐设施 4 / 草地 1）
                            `SpecialSpot` = 0 纯地块（连锁）/ 1~4 特殊（弹面板）
        规则：
          空地（连锁）⇒ **固定 1 点** ✓（用户：「空白格都是 1 点，不管连锁多少」✓）
          内容格 · **探索** ⇒ **SpotSize 点** ✓
          内容格 · **战斗** ⇒ **SpotSize × 2 点** ✓
        ⚠ 上一版"非空地一律 2×Size"✗ ⇒ 内容格费用虚高一倍 ⇒ 规划偏保守 ✗（本次修 ✓）
        """
        size = int(getattr(b, 'size', 1) or 1)
        if getattr(b, 'plain', False):          # 空地：连锁 ⇒ 固定 1 点 ✓
            return 1
        if b.mark in FIGHT_X2:                  # 明确要打的（boss/红装/大拇指/战斗标记）✓
            return size * 2
        return size                             # 内容格：探索 = SpotSize ✓

    def step_cost(self, state, bi):
        """点这一下要花的体力 ✓

        ⭐ 2026-09-27 用户口径：**空地固定 1 点**，连锁吃掉多少格都一样 ✓
           （旧版对空地整片求 ΣSpotSize ✗ ⇒ 4 格游乐设施算 4~8 点 ✗ 与游戏不符 ✗）
        """
        if self.blocks[bi].plain:
            return 1
        return self.block_cost(self.blocks[bi])

    def done(self, state):
        return not (self.targets - set(state))


def solve(prob, max_states=400000, report=None, max_secs=None):
    """Dijkstra（按体力边权）求**最省体力**地清完所有目标

    -> (最小体力, [(block_idx, 体力)…])；无解返回 (None, None)

    report（可选 dict）：把本次搜索的规模信息写进去，便于**量化"状态爆炸"** ✓
      {'pushed': 入队状态数, 'expanded': 出队展开次数,
       'max_states': 上限, 'reason': 'ok' / 'max_states' / 'max_secs' / 'exhausted',
       'cost': 最小体力}
    max_secs（可选）：**墙钟超时**（秒）—— 2026-09-28 加（用户报「进图要等很久」）：
      复杂盘 60k 状态枚举可达 30~60s，而 solver 失败后下轮还会重试 ⇒ 进图后
      几分钟不点格。超时返回 (None, None)（reason='max_secs'）⇒ 调用方
      fail-open 退回 EffPolicy/启发式 ✓ 每 2048 次展开查一次时钟（摊薄开销 ✓）
    """
    import time as _time
    if report is None:
        report = {}
    report.update({'pushed': 0, 'expanded': 0, 'max_states': max_states,
                   'reason': 'exhausted', 'cost': None, 'n_targets': len(prob.targets)})
    _t0 = _time.time() if max_secs else None
    start = frozenset()
    if prob.done(start):
        report.update({'reason': 'ok', 'cost': 0})
        return 0, []
    dist = {start: 0}
    prev = {start: None}                 # state -> (prev_state, action, cost)
    pq = [(0, 0, start)]                 # (体力, 计数器, 状态)  —— 计数器防比较 frozenset
    cnt = 1
    n = 0
    best_goal = None
    while pq:
        d, _c, st = heapq.heappop(pq)
        if d > dist.get(st, 1 << 30):
            continue
        report['expanded'] += 1
        if prob.done(st):
            best_goal = st
            report['reason'] = 'ok'
            break
        for bi in sorted(prob.visible(st)):
            ns = prob.step(st, bi)
            if ns == st:
                continue
            w = prob.step_cost(st, bi)
            nd = d + w
            if nd < dist.get(ns, 1 << 30):
                dist[ns] = nd
                prev[ns] = (st, bi, w)
                heapq.heappush(pq, (nd, cnt, ns))
                cnt += 1
                n += 1
                report['pushed'] = n
                if n > max_states:
                    report['reason'] = 'max_states'
                    return None, None
        # ⭐ 2026-09-28：墙钟超时（每次展开查一次太贵 ⇒ 每 2048 次查 ✓）
        if max_secs and (report['expanded'] & 2047) == 0 \
                and _time.time() - _t0 > max_secs:
            report['reason'] = 'max_secs'
            return None, None
    if best_goal is None:
        report['reason'] = 'exhausted'
        return None, None
    report['cost'] = dist[best_goal]
    acts, cur = [], best_goal
    while prev[cur] is not None:
        p, act, w = prev[cur]
        acts.append((act, w))
        cur = p
    acts.reverse()
    return dist[best_goal], acts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench', type=int, default=0)
    ap.add_argument('--map', default='夏日海滩')
    ap.add_argument('--difficulty', type=int, default=100)
    ap.add_argument('--seed', type=int, default=5000)
    ap.add_argument('--show', type=int, default=0, help='打印前 N 张盘的对比细节')
    a = ap.parse_args()
    import mapgen
    import mapsim
    import statistics

    T = mapgen.load_tables()
    g = mapgen.MapGen(T, a.map, a.difficulty)
    n = max(a.bench, a.show, 1)
    rows = []
    for k in range(n):
        sim = g.gen(seed=a.seed + k)
        prob = Problem(sim)
        opt, acts = solve(prob)
        # 基线策略（同一张盘）
        sim2 = g.gen(seed=a.seed + k)
        st = mapsim.BaselinePolicy().run(sim2)
        rows.append({'targets': len(prob.targets), 'opt': opt,
                     'base': st['clicks'], 'base_st': st['stamina'],
                     'base_left': st['left_targets'], 'acts': acts})
        if k < a.show:
            print('--- seed %d 目标=%d ｜ 最优体力=%s ｜ 基线体力=%d（点击 %d，剩目标 %d）'
                  % (a.seed + k, len(prob.targets), opt, st['stamina'], st['clicks'],
                     st['left_targets']))
            print(sim.render())
            if acts:
                names = ['%s(%d体)' % (prob.blocks[bi].name, w) for bi, w in acts]
                print('   体力最优点序:', ' → '.join(names))
    if a.bench:
        opts = [r['opt'] for r in rows if r['opt'] is not None]
        base = [r['base_st'] for r in rows]
        bclk = [r['base'] for r in rows]
        print()
        print('对比 %d 张盘（%s 难度 %d）：**目标函数 = 体力**' % (len(rows), a.map, a.difficulty))
        if opts:
            print('  体力最优：平均 %.2f 点（中位 %d，最多 %d）；算不出的 %d'
                  % (statistics.mean(opts), statistics.median(opts), max(opts),
                     sum(1 for r in rows if r['opt'] is None)))
        print('  基线策略：平均 %.2f 点体力（中位 %d，最多 %d）；点击 %.2f 次；漏目标 %d/%d'
              % (statistics.mean(base), statistics.median(base), max(base),
                 statistics.mean(bclk),
                 sum(1 for r in rows if r['base_left'] > 0), len(rows)))
        if opts:
            gap = [b - o for b, o in zip(base, opts) if o is not None]
            print('  基线比最优多花体力：平均 %.2f 点（最多 %d）；完全一样的 %d/%d'
                  % (statistics.mean(gap), max(gap), sum(1 for x in gap if x == 0), len(gap)))


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
