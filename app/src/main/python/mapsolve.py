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


def _is_fight_block(b):
    """⭐ v1.43：这一块按**地块类型**是不是"要打一场架"（`EventNum` 首段 > 1）

    ⚠ 本模块**故意不 import spots**（地块数据靠参数传，避免循环依赖）；
      这里**局部导入**，首次之后走模块缓存 ⇒ 零开销 ✓（与 PC 端 `mapsim.block_cost` 同款）
    """
    try:
        import spots as _sp
        return bool(_sp.is_fight_spot(getattr(b, 'sid', None)))
    except Exception:       # noqa: BLE001
        return False


def rc_of(idx):
    """cell 索引 -> 1 基 (r, c)（与 `mapsim.rc_of` 同口径）"""
    return idx // COLS + 1, idx % COLS + 1


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
        # ⭐⭐⭐ v1.51【观测地基】—— 抄 PC（这是"观测闸门"那一族的前提）
        #   `obs_consumed`：**观测里本来就是空的格**（`board<0`）——
        #     用于区分「观测时就已经消耗」和「搜索推演过程中才消耗」：
        #     · 前者（观测消耗）揭示过的块，**观测里本应看得见** ⇒ 若观测说是雾，
        #       说明"它被消耗"是模型自己的推断（幻影）⇒ **不许据此判"可点"** ✓
        #     · 后者（推演消耗）是**多步揭示链**的正常推演 ⇒ **必须放行**，
        #       否则目标一旦藏在雾里就永远不可达 ⇒ `exhausted`（无解、整图干等）✗✗
        #   （这两条是 PC 用真机帧 A/B 出来的：只做前者 ⇒ 无解；只做后者 ⇒ 点雾格 ✓）
        self.obs_consumed = {c for c in range(NCELL) if self.board[c] < 0}
        #   `obs_cells`：**观测里真的有哪几格**（`MapSim.from_observation` 记的）——
        #     `_build_cache` 的 `EMPTY_ADJ` 用它做闸门：观测里没有的格
        #     **不许当"已消耗"** ✓（⚠ 拿不到 ⇒ 闸门不启用，行为一字不变 ✓）
        self.obs_cells = set(getattr(sim, 'obs_cells', None) or ())
        for b in self.blocks.values():
            if '营地' in (b.name or ''):
                self.camp = b.idx
        # ⭐⭐⭐ v1.51 兜底：按块名找不到营地时，用观测里**明确标了 camp** 的块 ✓
        #   （用户口径：「营地应该最好认吧，稳定是揭示状态的，**先固定下来营地**？」）
        #   为什么必须有这条：营地格常被多格块吞掉 ⇒ 块名不是"营地" ⇒ `camp=None`
        #   ⇒ 揭示规则「与营地/已消耗格 4 邻」**没有起点** ⇒ 求解器 `exhausted`（无解）
        #   ⇒ **整张图干等/退图** ✗✗（PC 真机 23:30 那把铁证）
        if self.camp is None:
            for b in self.blocks.values():
                if getattr(b, 'camp', False):
                    self.camp = b.idx
                    break
        # ⭐⭐⭐ v1.51 **营地的揭示源 = 营地那一格**（不是整个多格块）—— 抄 PC
        #   离线铁证：营地 (2,1) 属于 4 格块 `巨大沙堡` ⇒ 拿整块当揭示源时，
        #   boss(1,2)（与 (1,1)/(2,2) 相邻）会被判"可点" ⇒ 又排进计划、真机是雾格 ✗✗
        #   ⇒ 优先用 `Block.camp_cells`（真正带 camp 标记的格）；没有就退回整块 ✓
        self.camp_cells = set()
        if self.camp is not None:
            _cb2 = self.blocks.get(self.camp)
            self.camp_cells = (set(getattr(_cb2, 'camp_cells', None) or ())
                               or set(self.cells_of.get(self.camp, ())))
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
        """「已消耗的格」= 观测里**本来就是空的格**（`board < 0`）+ 本状态吃掉的格

        ⭐⭐ 2026-09-30 修（保真度核心，离线对拍抓到）：
            旧实现只算 `state` ⇒ 从**空集**起步 ⇒ 模型以为"一步都没走过"，
            于是 `visible()` 只剩「营地四邻」⇒ 已经走出去的地图完全看不见 ✗✗
            —— 真机表现就是「每轮都从营地重新起步、走法明显不是最优」。
            而"哪一格已经空了"**观测里本来就有**（消耗掉的格没有地块美术 ⇒
            `MapSim.from_observation` 建盘时 board = -1 ✓）
            ⇒ 必须并进来 ✓
        """
        out = {c for c in range(NCELL) if self.board[c] < 0}
        for bi in state:
            out.update(self.cells_of.get(bi, ()))
        return out

    def block_revealed(self, bi, consumed):
        """块 bi 在「已消耗格集合 = consumed」下**是否已揭示**（能点）

        ⭐ 2026-09-30 新增。揭示规则（真机 + `mapsim._reveal_neighbours` 同口径）：
            块已揭示 ⟺ 块内某格与「营地的任一格」或「任一已消耗格的任一格」4 邻接
          （营地开局自带揭示 ✓）
        """
        if bi < 0:
            return False
        if self.camp is not None and bi == self.camp:
            return True
        # ⭐⭐⭐ v1.51【观测闸门】—— 抄 PC，治「**计划去点雾格**」
        #   原来这条判据**纯邻接推演**（只与营地/已消耗格 4 邻接），**完全不看观测**：
        #   只要模型相信"某个格已被消耗"（哪怕它其实还是雾），它**旁边的雾格**就会被判
        #   "已揭示/可点" ⇒ 计划里出现点不动的格 ⇒ 真机 `fogged_noop` 空转 ⇒
        #   **整条计划错位、漏目标** ✗✗
        #   真机铁证（PC gui_20261002_232950）：
        #     #11 done_cells_dropped: 4 格 (1,1 2,1 2,2 2,3)  ← 被推断成"已消耗"并删出模型
        #     #12 solver ok: order ["1,2","2,4"]
        #     #13/#14 tap: fogged_noop (1,2) ratio 0.665 / (2,4) ratio 0.717  ← 真机是雾 ✗
        #   ⇒ 块内必须**在观测里就有一格是已揭示的**（`Block.observed`，
        #     由建块时的观测值固定，`_infer_revealed()` 推演出来的**不算**）才允许判"可点" ✓
        #   ⚠ 方向安全：观测说"已亮"但实际点不动（如被面板挡）仍会在计划里 —— 那是
        #     `tap` 的 nochange/拉黑逻辑管的（这里只管"观测说它是雾"的那一类）✓
        _bb = self.blocks.get(bi)
        _obs = bool(getattr(_bb, 'observed', False)) if _bb is not None else True
        # ⚠ 营地揭示源只认"营地那一格"（见 __init__ 说明 ✓）
        camp_cells = self.camp_cells or ()
        for c in self.cells_of.get(bi, ()):
            r, cc = c // COLS, c % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, ccc = r + dr, cc + dc
                if not (0 <= rr < ROWS and 0 <= ccc < COLS):
                    continue
                n = rr * COLS + ccc
                if n in camp_cells:
                    return True
                # ⚠⚠⚠ 2026-10-01 修**格索引 / 块索引 空间混用**（实测 1556 块里 382 个假阳性）：
                #   `n` 已经是**格索引**、`consumed` 也是**格索引**集合 ⇒ 判据就该是 `n in consumed`
                #   （该邻格本身已被消耗 ⇒ 本块紧邻消耗格 ⇒ 会被揭示 ✓ 语义正确，
                #     也与 explore_loop._infer_chain_consumed 的反推律同口径）
                #   旧写法取 `nb = self.board[n]`（**块 id**）再 `nb in consumed`（**格 id** 集）——
                #   两个索引空间数值范围都是 0..34，肉眼无法区分 ⇒ 只要「邻格所属块的编号」
                #   数值上撞上「某个已消耗格的编号」就误判已揭示 ⇒ 求解器以为点得动，
                #   真机上其实是雾格 ⇒ `fogged_noop` 空转、整条计划错位、漏目标。
                #   另：`board[n] < 0` 的情形已被上面的 `consumed_cells` 全量收集（board<0 ⇔ n∈consumed），
                #   不需要在这里再单独判一次。
                if n in consumed:
                    # ⭐⭐⭐ v1.51 **观测闸门**（只对"观测时就已经消耗"的邻格生效）：
                    #   观测里就空的邻格 ⇒ 它对本块的揭示**在观测里本该看得见**；
                    #   若观测说本块是雾，那"该邻格已消耗"就是模型的推断（幻影）
                    #   ⇒ **不许放行** ✗（PC 真机 23:30 那把：4 格被推断成已消耗
                    #     并删出模型 ⇒ 相邻雾格被判可点 ⇒ 计划点雾格 ✗✗）
                    #   反之：`n` 是**搜索推演中**才消耗的 ⇒ **放行**
                    #   （多步揭示链必须能推演 ✓，否则目标藏雾里就永远不可达 ✗）
                    if n in self.obs_consumed and not _obs:
                        continue
                    return True
        return False

    def cells_for_plan(self, acts):
        """把搜索出来的 `[(block_idx, 体力)…]` 翻成**每一步真的能点的格**

        ⭐⭐ 2026-09-30 修（离线对拍抓到的核心 bug）：
            `Problem.visible()` 会把**一整片连通空地**去重成"片内最小 idx 的代表块"
            （`REP`）—— 规划语义上是对的（点片里任意一格都连锁消掉整片 ✓），
            但**代表块本身不一定是"已经揭示"的那一块** ✗
            ⇒ 真机点它 = `fogged_noop`；而且点不动 ⇒ 这片空地在下一帧里边界不变、
              揭示集不变 ⇒ **后面整条计划全部错位**（空转 + 漏目标）✗✗
            实测（`_bench_online.py` 60 张盘）：不修时 30/60 张真的清不完目标。
            ⇒ 修法：**逐步推演模型状态**，每一步在目标块（片）里挑一个
              "当下已揭示"的格；片里必有一个已揭示格（否则它进不了 visible ✓）

        返回 [((r, c), block_idx, 体力)…]（1 基行列，与 visible()/rc_of 同坐标系 ✓）
        """
        consumed = set(self.consumed_cells(frozenset()))   # ⭐ 含观测里本来就是空的格 ✓
        out = []
        for bi, w in acts:
            b = self.blocks.get(bi)
            if b is None:
                continue
            # ⭐ 空地：候选格 = **整片**的所有格（bi 只是"片内最小 idx 的代表块"，
            #   它自己很可能还没揭示 ⇒ 必须从整片里挑一个已揭示的格 ✓）
            if b.plain:
                cells = []
                for gb in self.plain_group(bi):
                    cells.extend(self.cells_of.get(gb, ()))
            else:
                cells = list(self.cells_of.get(bi, ()))
            if not cells:
                continue
            pick = None
            for c in cells:
                if self.block_revealed(self.board[c], consumed):
                    pick = c
                    break
            if pick is None:                  # 兜底：整片都没揭示（不该发生）
                pick = cells[0]
            out.append((rc_of(pick), bi, w))
            # ⚠⚠ 2026-10-01 修：原来 `consumed |= (self.plain_group(bi) if b.plain else {bi})`
            #   —— `plain_group` 返回的是**块 id**、`{bi}` 也是**块 id**，
            #   而 `consumed` 全程是**格索引**（`block_revealed` 按格判）⇒ 又一处空间混用 ✗
            #   ⇒ 本步真正被占用的**格**是 `cells`（候选格全部在片内、空地片已全部连锁消耗 ✓）
            #   改用 `cells` 后语义自洽，也顺带覆盖"多格块只点了一格、其余成员仍算已揭示"的漏洞。
            consumed |= set(cells)
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
        ⭐⭐ v1.44【**拉黑块既不可点、也不借它走路**】（学 PC 端 d81c42c）
        """
        vis = set()

        # ⭐ v1.44：拉黑掩码（`Block.blocked` ⇒ 由 explore_loop 的观测 `blocked` 传来 ✓）
        _blk = {bi for bi, b in self.blocks.items() if getattr(b, 'blocked', False)}

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
        # ⭐ v1.44：拉黑块**既不是候选动作、也不能当通路** ✓
        #   （根因：拉黑块原本只"事后从点序剔除"⇒ 求解器算连通性/代价时仍按能走算
        #    ⇒ 计划出现断档/绕路不合理 ✗ —— 与 PC 端 d81c42c 同一个问题）
        if _blk:
            vis -= _blk
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
        # ⭐⭐⭐ v1.51【按**地块类型**判定战斗价】—— 抄 PC（**必须放在这里**）
        #   PC 原话：「战斗格 = **格数×2**」⇒ **按地块类型**判 ✓
        #   原来只看 `b.mark` ✗ —— 而 `拦路` 是**规划完之后**才贴的标记
        #   （循环发现"计划路径穿过非空地"时才标）⇒ 规划那一刻**它没有标记**
        #   ⇒ 要打的架被按"内容格·探索"计价（3 而非 6 ✗）⇒ 平局时选了要打的那条 ✗✗
        #   真机事故（PC acc1 gui_20261003_140308 第 2 张图，详见 `spots.is_fight_spot` 注释）
        #   ⇒ 先问数据表（`EventNum` > 1-1 即战斗型 ✓），表里查不到才退回标记判据 ✓
        #   ⚠⚠ **我之前把这条只写在 `step_cost()` 里** ✗ —— v1.51 让 `step_cost`
        #     委托给本函数后，那条分支就**丢了**（门禁 v1.43 ② 当场抓到 ✓）
        #     ⇒ 定价细节**只留在本函数一处**（单一真相源 ✓）
        try:
            import spots as _sp                 # ⚠ 本模块**故意不 import spots**（数据靠参数传 ✓）
            if _sp.is_fight_spot(getattr(b, 'sid', None)):   # 局部导入：首次后走缓存，零开销 ✓
                return size * 2
        except Exception:                       # noqa: BLE001
            pass
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
        # ⭐ v1.51：**委托给 `block_cost`**（抄 PC 的写法）——
        #   原来这里把定价逻辑**又抄了一遍** ⇒ **两个真相源** ✗
        #   （改一处、另一处不会跟着变 —— 正是 PC 用 `fixed.cross_check_layout`
        #     防的那类病：同一份数据抄两遍必然漂移 ✓）
        #   ⚠ 定价细节**只留在 `block_cost` 一处**（含 v1.43 的 `is_fight_spot` 判据、
        #     v1.48 的 `is_fight_spot ⇒ plain=False` 相互配合 ✓）
        return self.block_cost(self.blocks[bi])

    def done(self, state):
        return not (self.targets - set(state))


def _build_cache(prob):
    """⭐ 2026-09-29 深夜优化：把 Problem 编译成**位掩码 + 预计算表**（缓存在 prob 上）

    三个性能杠杆（语义与旧版逐点等价，最优体力值不变）：
      1. 状态 frozenset → **int 位掩码**（块 ≤35 个）：哈希/比较/并集 O(n)→O(1)
      2. **A\* 启发** h(state) = Σ 未消耗目标的体力。可采纳且一致：
         目标全是非空地块（空地连锁不吃内容块）⇒ 每个未消耗目标必须被单独点掉、
         各花 block_cost(t) ⇒ 真优解花费 ≥ g + h；且点目标这条边 w=cost(t)=h 下降量。
      3. **空地等价组去重**：同一整片空地的成员块 step 结果相同 ⇒ 只展开代表块
         （片内最小 idx），分支数不再随片大小膨胀。
    """
    blocks = prob.blocks
    idxs = sorted(blocks)
    bit = {bi: 1 << k for k, bi in enumerate(idxs)}
    # 每块的格子位掩码（cell 位）
    cell_bit = {i: 1 << i for i in range(NCELL)}
    block_cells_mask = {bi: 0 for bi in idxs}
    for c, bi in enumerate(prob.board):
        if bi >= 0:
            block_cells_mask[bi] |= cell_bit[c]
    # 块级邻接：NB_MASK[bi] = 与 bi 任一格 4 邻接的其他块位掩码（含雾块 ✓）
    NB_MASK = {bi: 0 for bi in idxs}
    for bi in idxs:
        for c in prob.cells_of.get(bi, ()):
            r, cc = c // COLS, c % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, ccc = r + dr, cc + dc
                if 0 <= rr < ROWS and 0 <= ccc < COLS:
                    nb = prob.board[rr * COLS + ccc]
                    if nb >= 0 and nb != bi:
                        NB_MASK[bi] |= bit[nb]
    # 整片空地组（按块并集，含穿雾穿草地口径 —— 直接复用旧逻辑预计算一次 ✓）
    PLAIN_GROUP_MASK = {}
    for bi in idxs:
        grp = prob.plain_group(bi)
        m = 0
        for x in grp:
            m |= bit[x]
        PLAIN_GROUP_MASK[bi] = m
    # 等价代表：同片空地取最小 idx；非空地 = 自己
    REP = {}
    for bi in idxs:
        if prob.blocks[bi].plain:
            REP[bi] = min(x for x in (prob.plain_group(bi)))
        else:
            REP[bi] = bi
    cost = {bi: prob.step_cost(frozenset(), bi) for bi in idxs}
    camp = prob.camp
    camp_mask = bit[camp] if camp is not None else 0
    # ⭐⭐⭐ v1.51 **营地的"开局已揭示"只能来自营地那一格的 4 邻**（不是整块的 4 邻）—— 抄 PC
    #   离线铁证（r_233023_0.png，用户报「规划错了」那把）：
    #     营地格 (2,1) 被 4 格块 `巨大沙堡` (1,1)(2,1)(2,2)(2,3) 吞掉 ⇒
    #     用**整块**算邻接 ⇒ boss(1,2)、紫金格(2,4) 都进了 `camp_nb` ⇒ 开局就被当成
    #     "已揭示/可点" ⇒ 计划 = `[(1,2),(2,4)]`（真机两格 ratio 0.665/0.717 **都是雾**）
    #     ⇒ `fogged_noop` 空转、整条计划错位 ✗✗
    #   ⇒ 用 `prob.camp_cells`（真正带 camp 标记的格）算邻接；
    #     没有该信息（单格营地的常规情形）才退回整块口径 ⇒ 对老盘行为不变 ✓
    camp_nb = 0
    _ccells = set(getattr(prob, 'camp_cells', None) or ())
    if camp is not None:
        # ⭐⭐⭐ v1.55【营地邻接 = 营地块的邻居 ∪ 营地格的邻居，**再按观测滤雾**】
        #   ⚠⚠ **真机 + 离线都抓到的 bug**（手机端"没有规划"的第二处根因）：
        #     我 v1.51 抄 PC 时只用了 `camp_cells`（**营地那一格**）——
        #     而营地格若在**多格块的角上**（4 邻全是自己那块），
        #     它一个"别人的块"都邻接不到 ⇒ **`camp_nb = 0`** ✗✗
        #     ⇒ `visible(空状态) = camp_nb | empty_adj = 0` ⇒ `expanded:1` / `exhausted`
        #     而 `Problem.visible()` 用的是**整块**的邻居 ⇒ 两份**算出来不一样** ✗
        #     （离线实测：`Problem.visible()` = 4 个候选，`camp_nb` = 0 ⇒ 求解器仍无解）
        #   ⇒ 两边统一：**用整块的邻居**（保证"开局一定有点能点的格" ✓
        #      —— 用户口径原话：「不可能出现开局没有一个地方能点的情况」✓）
        #   但 PC 当初改成 `camp_cells` 是有理由的（它的注释）：
        #     「用**整块**算邻接 ⇒ boss(1,2)、紫金格(2,4) 都进了 `camp_nb` ⇒
        #       开局就被当成"已揭示/可点"（真机两格 ratio 0.665/0.717 **都是雾**）✗✗」
        #   ⇒ 所以**加一道观测闸门**：只把 **`Block.observed`（建块时观测说已揭示）**
        #     的邻块算进来 ✓ —— 两个目标同时满足：
        #       · 块角营地也有候选（不再 0）✓
        #       · 雾格不会被当成"开局可点" ✓
        _camp_block_cells = set(prob.cells_of.get(camp, ()))
        for _c0 in (_ccells | _camp_block_cells):
            _r0, _q0 = _c0 // COLS, _c0 % COLS
            for _dr, _dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                _rr, _qq = _r0 + _dr, _q0 + _dc
                if 0 <= _rr < ROWS and 0 <= _qq < COLS:
                    _nb = prob.board[_rr * COLS + _qq]
                    if _nb < 0 or _nb == camp:
                        continue
                    # ⭐ 观测闸门：观测说它是雾 ⇒ 不算"开局可点" ✓
                    if not bool(getattr(prob.blocks.get(_nb), 'observed', True)):
                        continue
                    camp_nb |= bit[_nb]
    # ⭐⭐ 2026-09-30：「观测里本来就是空的格」（已消耗）⇒ 它的邻居块**现在就已经揭示**。
    #   全知盘（新生成的盘）没有任何 -1 ⇒ EMPTY_ADJ = 0，行为一字不变 ✓
    #   观测盘（真机 / 在线推演）则有 -1 ⇒ 模型终于知道"已经走到哪了" ✓
    EMPTY_ADJ = 0
    _obs_cells = set(getattr(prob, 'obs_cells', None) or ())
    for c, bi in enumerate(prob.board):
        if bi >= 0:
            continue
        # ⭐⭐⭐ v1.51 闸门：**观测里根本没有这一格 ⇒ 不许拿它当"已消耗"去揭示邻居**
        #   （PC 真机 23:30 那把：4 格被 `_infer_chain_consumed` 推断成已消耗并
        #     **删出观测** ⇒ 这里 `board<0` ⇒ `EMPTY_ADJ` 把它们的邻居判成
        #     "开局已揭示" ⇒ **计划点雾格** ✗）
        #   ⚠ 只有拿到观测格集合时才启用（老调用/全知盘没有 ⇒ 行为一字不变 ✓）
        if _obs_cells and c not in _obs_cells:
            continue
        r, cc = c // COLS, c % COLS
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            rr, ccc = r + dr, cc + dc
            if 0 <= rr < ROWS and 0 <= ccc < COLS:
                nb = prob.board[rr * COLS + ccc]
                if nb >= 0:
                    EMPTY_ADJ |= bit[nb]
    EMPTY_ADJ &= ~camp_mask
    targets_mask = 0
    for t in prob.targets:
        targets_mask |= bit[t]
    tcost = {bit[t]: cost[t] for t in prob.targets}     # ⭐ 键 = 单 bit（与 h() 一致）
    # ⭐⭐⭐ v1.51【拉黑掩码】—— 抄 PC `d81c42c`
    #   ⚠⚠ **这是我 v1.44 漏掉的那一环**：拉黑块（`Block.blocked`）
    #     **既不是候选动作、也不借它走路** ✓
    #   我 v1.44 只改了 `Problem.visible()`（集合版），可 **`solve()` 用的是它自己那份
    #   **位掩码版 `visible(m)`** ⇒ 那次修**根本没进求解器** ✗✗（门禁也测错了函数）
    #   ⇒ 掩码必须建在这里、由 `solve()` 消费 ✓
    blocked_mask = 0
    for bi in idxs:
        if getattr(prob.blocks[bi], 'blocked', False):
            blocked_mask |= bit[bi]
    return {'bit': bit, 'bits': [bit[bi] for bi in idxs],
            'blocked_mask': blocked_mask,
            'NB_MASK': {bit[k]: v for k, v in NB_MASK.items()},   # ⭐ 键 = 单 bit
            'PLAIN_GROUP_MASK': PLAIN_GROUP_MASK, 'REP': REP,
            'cost': cost, 'camp_mask': camp_mask, 'camp_nb': camp_nb,
            'empty_adj': EMPTY_ADJ,
            'targets_mask': targets_mask, 'tcost': tcost,
            'idx_of_bit': {v: k for k, v in bit.items()}, 'bit_keyed': True}


def solve(prob, max_states=400000, report=None, max_secs=None):
    """A\*（按体力边权 + Σ剩余目标体力启发）求**最省体力**地清完所有目标

    -> (最小体力, [(block_idx, 体力)…])；无解返回 (None, None)
    语义与旧 Dijkstra 完全一致（最优体力值唯一），只是**快一个数量级以上**：
      2026-09-29 深夜优化：frozenset→int 位掩码 / A\* 启发 / 空地等价组去重（见 _build_cache）
    report / max_states / max_secs 语义不变（fail-open 口径不变 ✓）
    """
    import time as _time
    if report is None:
        report = {}
    report.update({'pushed': 0, 'expanded': 0, 'max_states': max_states,
                   'reason': 'exhausted', 'cost': None, 'n_targets': len(prob.targets)})
    _t0 = _time.time() if max_secs else None
    ch = getattr(prob, '_cache', None)
    if ch is None:
        ch = _build_cache(prob)
        prob._cache = ch
    bit, NB, PGM, REP, cost = ch['bit'], ch['NB_MASK'], ch['PLAIN_GROUP_MASK'], ch['REP'], ch['cost']
    # NB_MASK 的键统一成「单 bit」：把块键表换成 bit 键
    if 'bit_keyed' not in ch:
        ch['NB_MASK'] = {ch['bit'][k]: v for k, v in NB.items()}
        ch['bit_keyed'] = True
    NB = ch['NB_MASK']
    idx_of_bit = ch['idx_of_bit']
    targets_mask = ch['targets_mask']
    tcost = ch['tcost']
    camp_mask = ch['camp_mask']
    camp_nb = ch['camp_nb']
    empty_adj = ch.get('empty_adj', 0)

    def visible(m):
        # ⭐ 起手可见 = 营地四邻 ∪ **观测里已经空掉的格的邻块**（= 已经走出去的地图 ✓）
        out = camp_nb | empty_adj
        mm = m
        while mm:
            low = mm & -mm
            out |= NB.get(low, 0)
            mm ^= low
        out &= ~m & ~camp_mask
        # ⭐⭐⭐ v1.51【拉黑块一律不是候选】—— 抄 PC `d81c42c`
        #   ⚠⚠ 这里才是**真正生效的地方**：`solve()` 用的是**本函数**（位掩码版），
        #     不是 `Problem.visible()`（集合版）✗
        #   ⇒ 我 v1.44 只改了集合版 ⇒ **拉黑在求解器里一直没生效**（黑名单形同虚设）
        #     PC 用户口径：「**能不能一开始就不规划这个拉黑的**」✓
        #     拉黑块**既不点它、也不借它走路**（连通性/代价都不按"能走"算 ✓）
        out &= ~ch.get('blocked_mask', 0)
        ded = 0
        while out:
            low = out & -out
            bi = idx_of_bit[low]
            ded |= bit[REP[bi]]
            out ^= low
        return ded

    def h(m):
        s = 0
        t = targets_mask & ~m
        while t:
            low = t & -t
            s += tcost[low] if low in tcost else tcost[idx_of_bit[low]]
            t ^= low
        return s

    start = 0
    if not (targets_mask & ~start):
        report.update({'reason': 'ok', 'cost': 0})
        return 0, []
    h0 = h(start)
    dist = {start: 0}
    prev = {start: None}                 # mask -> (prev_mask, block_idx, cost)
    pq = [(h0, 0, start)]                # (f=g+h, 计数器, mask)
    cnt = 1
    n = 0
    best_goal = None
    while pq:
        f, _c, st = heapq.heappop(pq)
        g = dist.get(st)
        if g is not None and f - h(st) > g:      # 过期条目（A* 惰性删除）
            continue
        report['expanded'] += 1
        if not (targets_mask & ~st):
            best_goal = st
            report['reason'] = 'ok'
            break
        vm = visible(st)
        while vm:
            low = vm & -vm
            vm ^= low
            bi = idx_of_bit[low]
            ns = st | PGM[bi]
            if ns == st:
                continue
            w = cost[bi]
            nd = g + w
            old = dist.get(ns)
            if old is None or nd < old:
                dist[ns] = nd
                prev[ns] = (st, bi, w)
                heapq.heappush(pq, (nd + h(ns), cnt, ns))
                cnt += 1
                n += 1
                report['pushed'] = n
                if n > max_states:
                    report['reason'] = 'max_states'
                    return None, None
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
