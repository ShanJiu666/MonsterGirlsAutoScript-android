# -*- coding: utf-8 -*-
"""mapsim.py · **地图模拟器**（探索棋盘：揭格 / 连锁消除 / 目标与点序）

⚠ 这不是 `headless_battle`（战斗数值模拟器），本文件只模拟**探索地图**这一层：
   棋盘布局、可见性（雾）、点击规则、连通消除、标记/商人/宝库目标、以及"点哪一格"的策略。

规则来源（1:1 移植 `audit_work/_game_all_MainScripts_20260924.cs`）：
  · 点击地块（行 45185）：
        if (data.SpecialSpot == 0)  -> GetConnectedPlainBlocks(...)  # 整片连通空地一起消耗
        else                        -> FinishBlock(...)              # 开面板（战斗/商人/宝库…）
  · 连通空地（行 45205 GetConnectedPlainBlocks）：BFS，5 行 7 列，4 邻域，
        只吃 `SpotSize <= 1 && SpecialSpot == 0 && saga == null` 的块；同块的所有格子一起入队
  · 消耗地块（行 47708 RemoveBlock）→ SetBlockVisible()（行 47743）重算可用性
  · 地块属性（行 82943 起）：`AreaSpotDataItem.SpecialSpot / SpotSize / PrefixNum / MinBattleStep…`
        ⇒ 本模拟器**直接用真实地块表**（`spots.spot_rows()`），不手抄常量

可见性（雾）：源码里 `isVisible` 由服务端状态驱动，客户端只负责渲染压暗（`disableColor`）。
    我们的视觉管线实测口径：
        · 已揭示格 亮度比 ≥0.85；未揭示 = 同一张美术 ×0.65（可识别但**点不动**）
        · 标记（首领/红装/点赞/幸运草）**即使在未揭示格上也画出来**（所以"点不动的 boss"存在）
    ⇒ 模拟器就用这套口径（与探索循环看到的完全一致）。

用法：
    python mapsim.py --sample runs/m1_r006.png      # 用一张真实截图建盘，跑一遍当前策略
    python mapsim.py --bench 40                     # 从 runs/ 采样建盘，跑 N 局统计
    python mapsim.py --selftest                     # 规则自检（连通消除/可见性）
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
import glob
import io
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROWS, COLS = 5, 7
NCELL = ROWS * COLS


def cell_of(r, c):
    return (r - 1) * COLS + (c - 1)          # 内部 0 基；对外 r/c 用 1 基（跟 explore_loop 一致）


def rc_of(idx):
    return idx // COLS + 1, idx % COLS + 1


def _neighbours(idx):
    """4 邻格的 cell 索引（越界的不返回）"""
    r, c = idx // COLS, idx % COLS
    out = []
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < ROWS and 0 <= cc < COLS:
            out.append(rr * COLS + cc)
    return out


# 小助手 app 官方分类：普通地块（绿）后缀列表 —— 这些是空地（连锁消除，只花 SpotSize）
# 空地后缀（点它**连锁消除** ⇒ 只花 1 点 ✓）
# ⚠ 002（海螺）**不是空地** ✗ —— 它是内容格（点它弹面板 ⇒ 战斗 ×2 ✓）
#   2026-09-27 用户报「非要去点 24 的战斗格子」= 我把 002 当空地 ⇒ 单价 1 点 ⇒ 求解器无所谓 ✗
PLAIN_SUFFIX = {'000', '001'}
# ⭐ v1.06：雾格「剪影占比」阈值 —— 与 `spots.FOG_SIL_MIN` **同值**（真机实测：雾下有物体
#   0.064~0.292 / 平坦 0.014~0.016，4 倍空档 ⇒ 0.04 稳 ✓）。这里**故意复制常量**而不是
#   import spots（`spots` 会在 import 时读数据表，而 mapsim 要保持"纯逻辑模块"可在无表环境跑 ✓）
FOG_SIL_MIN = 0.04
# ⚠⚠ v1.62【手机端**单方面不移植** PC 那条，记录在此防重试】—— PC `9129a78` 加了
#   `CONTENT_SCORE_MIN = 0.85`（"高置信内容地块 ⇒ 拦连锁"）。手机端当年判定不能搬：
#     · 只看 score ⇒ 在矿洞帧上**拦错 8/10 个**（雾格的宝箱/矿箱也能到 0.93~0.97）
#     · 加地板闸门 ⇒ 判据对了但**对 6 张真机帧零影响**（纯冗余）
#     · "决定性反证"：真机 `(4,2)` 模型说 `矿箱堆 score=0.933`，实点却是**首领格** ✗
#   ⛔⛔ **v1.70 更正（2026-10-06）—— 上面这三条的前提是错的，别再照它撤回**：
#     · ⚠ **PC 从来没撤过这条**！`git show HEAD:mapsim.py` 里
#       **`CONTENT_SCORE_MIN = 0.85` 仍在第 74 行、第 216 行在用**（PC HEAD=`88e4784`）
#       ⇒ 当年"撤回"是**手机端自己的决定**，不是 PC 撤了 ✓
#       （旧措辞"已撤回的 **PC** 改动"会让人以为 PC 撤了 —— 那句是**错的** ✗）
#     · 第 3 条反证**用错了样本**：`矿箱堆`=`S30001_101` 是**战斗格**（`EventNum 3-3`）
#       ⇒ `Block.plain` 分支② `is_fight_spot` **早就把它拦了** ⇒ 它**从来不是**
#       关于"**非战斗**内容格"的证据 ✗✗
#     · 第 1 条错在**判据形状**（"只看 score 就拦"确实会拦错纯雾格）；第 2 条错在
#       地板闸门仍按 ratio/score 判 ⇒ "零影响"是判据不对，不是"改了没用" ✗
#   ⇒ 真依据见下面 v1.70 那段（**数据表**判据 + 三重证据 + PC 端模型当裁判）✓
#   ⚠ 门禁 `v1.62c` 撤回守门**仍然有效**：它钉的是"**只看分数就拦**"，已证伪 ✗ ——
#     它**不是**"v1.70 不许存在"的证据 ✓
#
# ⭐⭐⭐ v1.70【雾格「剪影平坦」之后**再查一次数据表** —— 用户真机报的规划错就是它】
#   用户 2026-10-06 原话（这把 06:18，规划只给 3 步、无视 55 那个拦住连锁的单格）：
#     「**为什么无视 55 这个拦住连锁的单格**？」＋「**不要怀疑，我亲眼看见他就是矿箱**」
#   ⇒ 用户看到的是**地面真值**：`(5,5)` 就是矿箱 ⇒ 它**必须**拦住连锁 ✓
#
#   ## 病根（**不是识图错，是模型层拿到正确答案却扔了**）
#     分类器读得**完全正确**：`(5,5)` = `002 / 矿箱 / score 0.958 / ratio 0.527`
#     可分支⑤（雾格剪影，`:325`）**在查数据表之前就 return 了** ✗
#     ⇒ `fog_flat=True` ⇒ `plain=True` ⇒ 模型把**一个矿箱**当成空地
#     ⇒ `(5,5)` 被并进 16 格的连通空地片 ⇒ 求解器以为"点 `2,7` 一步连消一片"
#       ⇒ 计划 `['2,5','2,7','3,1'] cost 11` ✗（正确应为 `cost 13`）
#
#   ## 为什么这不是 v1.62 撤回的那条 E（**判据形状完全不同**，别混）
#     · E 是「**只看 score** ≥0.85 ⇒ 拦」⇒ 矿洞帧上拦错 8/10（纯雾格也被拦）
#     · 本闸门**只在**「已进到分支⑤」时生效 ⇒ 前提是**雾格 + 剪影平坦**
#       （剪影说有东西的早被分支④拦掉了 ✓），再加**数据表**判据 + **分数下限**
#     · E 的"决定性反证"（`(4,2)` 模型说 `矿箱堆`、实点是首领格）**对本闸门不成立**：
#       `矿箱堆`=`S30001_101` 是**战斗格**（`EventNum 3-3`）⇒ 分支② `is_fight_spot`
#       **早就把它拦了** ⇒ 本闸门根本看不到它 ✓（所以那条反证**用错了样本**）
#
#   ## 实测（探针全留在 `_tmpman/`，可复跑）
#     · 全语料 6 张真机帧 + 1 张 `_verify` 帧：95 个雾块
#       ⇒ **不加分数下限**改 16 块（16.8%）；**加了 0.85 下限**改 **13 块** ✓（下面就是理由）
#     · **按分数分层**：`score ≥0.85` 的 59 块里改 **15** 块（25.4%）；
#       `<0.50` 的 16 块里改 13 块 —— 而那 13 块**全部来自同一张坏帧**
#       （`r_152223_0.png`：系统「请选择要使用的应用」对话框盖住棋盘下半 ⇒ 那些格子
#        是对话框像素、不是棋盘格）⇒ **低分格没有证据价值** ⇒ 用分数下限排除 ✓
#     · **肉眼核验**：把 16 个受影响格裁成 3×3 邻域拼图（`_tmpman/cell55/sheet16.png`）
#       ⇒ 高分那 13 格**全是肉眼可见的内容物**（宝箱/矿箱/露天矿/传承祭坛/矿箱堆）✓
#     ⇒ 分数下限取 **0.85**，与 `spots.BUY_SCORE_MIN`（v1.67 商人/宝库那条）
#       **同一个数**：本项目的既定口径 —— **低分乱猜没资格代表"这是内容格"** ✓
#     ⚠ 缺 `score`（老调用/合成盘/内存 dump）⇒ **不拦**（fail-open ✓，与 v1.64 金币
#       闸门"读不到就不拉黑"同口径）
FOG_TABLE_GATE = (_os.environ.get('MAPBOT_FOG_TABLE') or '1').strip().lower() not in (
    '0', 'off', 'false', 'no', 'n')


def _env_float(name, dflt):
    """读一个浮点环境变量；**解析失败/没设 ⇒ 用默认值**（绝不在 import 期抛异常 ✗）"""
    try:
        _v = _os.environ.get(name)
        return float(_v) if _v not in (None, '') else float(dflt)
    except Exception:           # noqa: BLE001
        return float(dflt)


FOG_TABLE_SCORE_MIN = _env_float('MAPBOT_FOG_TABLE_MIN', 0.85)


def _fog_content_by_table(b):
    """v1.70 闸门：雾格（剪影平坦）**再查一次数据表** —— 表说它不是空地 ⇒ 拦连锁

    三条**全中**才拦（缺一不拦 ⇒ fail-open ✓，与 v1.64 金币闸门"读不到就不拉黑"同口径）：
      ① 开关开着（`MAPBOT_FOG_TABLE`，默认开）
      ② 该格有分类置信度 `score` 且 `>= FOG_TABLE_SCORE_MIN`（默认 0.85）
         —— **读不到分数 ⇒ 不拦** ✓（老调用/合成盘/内存 dump 都没有这个字段）
      ③ `spots.is_plain_spot(sid)` 说它**不是**空地（数据表 `SpecialSpot/SpotSize`）

    ⚠ 为什么必须有 ② 这道分数下限：低分格的名字是**乱猜的**（v1.06 注释实测：整套模板
      中位分只有 0.276，平坦格被猜成「岩石/巨大木桩」）⇒ 拿乱猜的名字去拦连锁
      **比不拦更糟**（会把真能连消的空地拦住 ⇒ 连锁全断）。实测证据：本闸门在
      `score <0.50` 的格子上改动的 13 个，**全部来自同一张坏帧**（系统对话框盖住棋盘）
      ⇒ 那些低分格没有证据价值 ✓
    """
    if not FOG_TABLE_GATE:
        return False
    try:
        _sc = (b.spot or {}).get('score')
        if _sc is None or float(_sc) < FOG_TABLE_SCORE_MIN:
            return False
    except Exception:           # noqa: BLE001
        return False            # 分数读不出来/不是数 ⇒ 不拦 ✓
    try:
        import spots as _sp     # 局部导入：本模块**故意不**在顶层 import spots ✓
        return not _sp.is_plain_spot(b.sid)
    except Exception:           # noqa: BLE001
        return False            # 数据表拿不到 ⇒ 不拦 ✓


# ⭐ 运行时学习（跨图共享 ✓）：点下去**连锁**的 = 空地 ✓；**弹面板**的 = 内容格 ✓
PLAIN_SEEN = {}     # suffix -> True
PANEL_SEEN = {}     # suffix -> True


def learn_tile(sid, plain):
    """循环点完一格后回报"是连锁还是面板" ⇒ 越跑越准 ✓"""
    suf = str(sid or '').split('_')[-1]
    if not suf:
        return
    if plain:
        PLAIN_SEEN[suf] = True
        PANEL_SEEN.pop(suf, None)
    else:
        PANEL_SEEN[suf] = True
        PLAIN_SEEN.pop(suf, None)


class Block:
    """一个地块（可能占多格，但探索图里绝大多数是 1 格）"""

    def __init__(self, idx, spot, revealed=False, mark=None, gone=False):
        self.idx = idx
        self.sid = spot.get('sid') if isinstance(spot, dict) else str(spot)
        self.name = spot.get('name') if isinstance(spot, dict) else str(spot)
        self.special = int(spot.get('SpecialSpot') or 0) if isinstance(spot, dict) else 0
        # ⚠⚠ v1.62：**曾**在这里加过 `score`/`weight`/`floor_lit` 三个字段，供
        #   PC `9129a78` 那条「高置信内容地块拦连锁」用 —— 该条**已完整撤回**
        #   （理由见 `Block.plain` 的长注释），故这三个字段**也一并撤回**，
        #   不留死字段 ✓（`tools/probe_e_decide.py` 证明它对规划零影响）
        self.size = int(spot.get('SpotSize') or 1) if isinstance(spot, dict) else 1
        # ⭐⭐⭐ v1.51【尺寸受**实际占几格**约束】—— 抄 PC 端 `1d6b687`
        #   PC 用户口径（原话）：「**16 为什么是 18 体？两块不应该是 4 体吗**」✓
        #   ⇒ 块的大小不能只看数据表 `SpotSize`（海边小屋模板写 9 ✓），
        #     还要受**这一块实际占了几格**约束：数据表 9 + 实际 2 格
        #     ⇒ 应按 **2 格**计价（战斗 ⇒ 2×2 = **4 体** ✓；原来按 9 算 ⇒ 18 体 ✗）
        #   ⚠ 与"按分数降级"**不同**（那条已被用户否掉 ✗「别随意降门槛」）——
        #     这里**不碰分数**，只用"块实际占几格"这个**几何事实** ✓
        #   回归影响：单格内容格 ⇒ min(表值,1)=1 ✓；真 4 格游乐设施 ⇒ min(5,4)=4 ✓
        if isinstance(spot, dict):
            _obs_cells = spot.get('cells')
            if isinstance(_obs_cells, (list, tuple)) and len(_obs_cells) > 0:
                self.size = max(1, min(self.size, len(_obs_cells)))
        self.revealed = revealed          # 已揭示（不压暗、可点）
        # ⭐⭐⭐ v1.51【观测值】—— **建块时从观测读到的 revealed，此后永不改动**（抄 PC）
        #   为什么要单独存一份：`_infer_revealed()` / `reveal_neighbours()` 会用
        #   **邻接推演**把某些块的 `revealed` 改成 True（"邻格是空地 ⇒ 该块被揭示"）——
        #   可一旦模型对"哪些格已消耗"的判断有偏差（真机 23:30 那把：4 格被推断成
        #   已消耗并被删出模型 ⇒ board<0 ⇒ 求解器当成空地），它**旁边的雾格**就会被
        #   推演成"已揭示/可点" ⇒ **计划里出现点不动的格** ✗✗
        #   ⇒ `mapsolve.Problem.block_revealed` 用这个 `observed` 做**观测闸门**，
        #     推演出来的 revealed **不再有资格**让一个块"变成可点" ✓
        self.observed = bool(revealed)
        # ⭐⭐⭐ v1.51【营地标记】—— 抄 PC 端（用户口径：「营地应该最好认吧，稳定是
        #   揭示状态的，**先固定下来营地**？」）
        #   为什么必须喂给模型：`mapsolve.Problem` 原来**只按块名含"营地"**找营地，
        #   而营地格经常被多格块吞掉 ⇒ `Problem.camp = None` ⇒ 揭示规则
        #   「与**营地**或已消耗格 4 邻接」**没有起点** ⇒ 求解器 `exhausted`（无解）
        #   ⇒ **整张图干等/退图** ✗✗
        #   ⇒ 循环侧认出来后给那一格打 `camp=True`，这里接住它 ✓
        self.camp = bool(spot.get('camp')) if isinstance(spot, dict) else False
        # ⭐⭐⭐ v1.51【营地到底是哪一格】（可多格块）—— 抄 PC 端
        #   离线铁证（r_233023_0.png）：营地格 (2,1) 属于 4 格块 `巨大沙堡`
        #   (1,1)(2,1)(2,2)(2,3) ⇒ 若拿**整块**当"揭示源"，boss(1,2) 与 (1,1)/(2,2)
        #   相邻 ⇒ 被捷径判"可点" ⇒ 又排进计划（真机就是雾格）✗✗
        #   ⇒ 只记带 camp 标记的那一格 ✓
        self.camp_cells = ([int(x) for x in (spot.get('camp_cells') or [])]
                           if isinstance(spot, dict) else [])
        self.mark = mark                  # 'boss' | 'redEquip' | 'recommend' | 'clover' | None
        self.gone = gone                  # 已消耗
        self.cells = []                   # 占用的格子（0 基 cell 索引）
        # ⭐⭐ 2026-09-28：**「这一块是不是当前配置下的目标」**（来自 targets_cfg 白名单 ✓）
        #   True/False = 调用方明确给了结论（explore_loop 走这条 ✓）
        #   None       = 没给（老调用如 mapevolve）⇒ 退回 `mark or is_buy` 老口径 ✓
        self.want = (spot.get('want') if isinstance(spot, dict) and 'want' in spot else None)
        # ⭐ v1.06：留着原始 spot dict —— `fog_sil`（雾格剪影占比）等字段要用它判定 ✓
        self.spot = dict(spot) if isinstance(spot, dict) else {'sid': str(spot)}
        # ⭐ v1.03/v1.05：**雾下剪影**（按格实测，不是一刀切 ✓）
        self.fog_object = bool(spot.get('fog_object')) if isinstance(spot, dict) else False
        self.fog_flat = bool(spot.get('fog_flat')) if isinstance(spot, dict) else False
        # ⭐⭐ v1.44【拉黑标】—— 求解器据此**既不点它、也不借它走路** ✓
        #   来自 `explore_loop._cells_for_model`（v0.99 就在打这个标了，但**只用于点序过滤**，
        #   求解器侧一直没收 ⇒ 拉黑块**被规划进去、还被借作通路** ✗）
        #   根因（学 PC 端 d81c42c 的完整论证）：
        #     拉黑块**事后**从点序里剔除 ⇒ 求解器算**连通性/代价**时仍按"能走"算过一遍
        #     ⇒ 剔除后计划出现断档 / 绕路不合理 ✗
        #   ⚠ 语义：**留在模型里**（`board >= 0` ⇒ 不是"已消耗"⇒ 不参与空地连锁 ✓，
        #     v0.99 那条结论依然成立），只是**不可点、不可借道** ✓
        self.blocked = bool(spot.get('blocked')) if isinstance(spot, dict) else False

    @property
    def plain(self):
        """空地（点它触发**连锁消除**，固定 1 点体力）

        ⭐⭐⭐ 2026-09-28 用户口径（**真机已证，决定性**）：
            「只连锁草地，不连锁其他的」＋「(1,5) 只揭开 3 格 (1,5)(1,6)(1,7)，
              被宝箱、海螺和出生地挡住了」

        两条硬修正：
          ① **营地（出生地）不是空地** —— 不可点，而且**阻断连锁** ✗
             旧版 `PLAIN_SUFFIX` 含 '000'（营地）⇒ 营地被当成空地
             ⇒ 把 (1,5)、(2,4)、(3,5) 三个各自独立的草地片**通过营地粘成一片** ✗
             ⇒ solver 以为"点哪个都一样"，挑了片最小的 (1,5)（它只连 3 格）
             ⇒ 够不到 boss ⇒ 被迫多插一步 (4,5)（真机上那格已被连带消掉、点了零反应）✗✗
          ② **删掉旧兜底 `special==0 and size<=1 ⇒ True`** —— 它把 1 格的内容格
             （宝箱/海螺/岩石…）也当成了空地 ✗；改成只认**草地**（名字含「草」）
        实测（`_why_15c.py`，C 口径）：点 (1,5) ⇒ 片恰为 3 格 ✓ 与用户描述逐字吻合
        """
        # ⛔⛔⛔ v1.66【**拉黑块 = 非空地（阻断连锁穿透）** —— 用户真机猜测**已证实**】
        #   用户 2026-10-06 原话：
        #     「最近一次的日志，规划出了问题，**我猜测是把拉黑的方块认为已经可以连锁通过了**？
        #       也可能是把宝箱认为可以连锁通过了」
        #   ⇒ **前半句猜对了** ✓（后半句只对"雾里的宝箱"，见下面 `fog_flat` 那支）
        #
        #   ## 真机铁证（2026-10-06 00:07，47 行日志）
        #     L31 `{"solver":"blocked_cells_tagged","n":1,"cells":["2,4"]}`  ⇒ 拉黑**打上了** ✓
        #     L37 `plan_block i=0 cell="2,5" plain=true group=["1,1","1,4","1,5",…,"+13"] gn=19`
        #     ⇒ 计划第一步的连通空地片 **19 格**，而 `2,4` 就在这片里（`group` 只显示前 6 格）
        #     L39 `{"solver":"ok","cost":5,"steps":2,"order":["2,5","5,1"]}`
        #     L41 `{"tap":"fogged_noop","cell":"5,1","ratio":0.655,"streak":1}`
        #     ⇒ 模型以为「点 `2,5` ⇒ 19 格连片全消 ⇒ `4,1` 被消耗 ⇒ `5,1` 变可点」
        #       ⇒ 第二步直接排了 `5,1`；**可真机点下去它还是雾**（0.655）✗✗
        #     ⇒ 连片被高估 = 揭示推演被高估 = 计划第二步点了点不动的格
        #
        #   ## 为什么 v1.44 打了 `blocked` 标还是漏（**这是本条的真正病根**）
        #     `Block.blocked` 的注释（`:170-177`）写着语义是「**不可点、不可借道**」，
        #     可**代码里从来没有实现"不可借道"** ✗：
        #       · `mapsim.connected_plain()`（`:802`）只判 `blk.plain`
        #       · `mapsolve.Problem.plain_group()`（`:445`）只判 `_nb_b.plain`
        #       · `mapsolve._build_cache` 的 `REP` / `PLAIN_GROUP_MASK`（`:545-558`）
        #         **都是从 `plain_group` 推出来的** ⇒ 三处一起漏 ✓
        #     ⇒ 拉黑格**照样被并进连通空地片** ⇒ 片被撑大 + 连锁被算成能穿透它 ✗✗
        #     ⚠ `solve().visible(m)` 里那条 `out &= ~blocked_mask`（`:719`）只挡掉了
        #       "**把它当候选动作**"，挡不住"**它当通路**" —— 两件事，别混 ✓
        #
        #   ## 修法：一处收口 —— 拉黑 ⇒ `plain` 恒 False
        #     这正是 v0.99 注释（`explore_loop.py:1013-1015`）写下的**正确语义**：
        #       「拉黑格 = **一个不可点的普通内容格**（游戏里它同样**阻断连锁穿透** ✓）」
        #     ⇒ 自动同时修好四件事（都是 `plain` 的下游 ✓）：
        #       `connected_plain` / `plain_group` / `REP` / `PLAIN_GROUP_MASK`
        #     ⚠ 代价字段不受影响：拉黑块被 `blocked_mask` 排除在候选之外（永不入选），
        #       而 `h()` 只数 `targets_mask` ⇒ `block_cost` 走 `size` 分支也无副作用 ✓
        #     ⚠ `targets` 也不受影响：`_cells_for_model` 同时写了 `target=False`
        #       ⇒ `row['want']=False` ⇒ 不进 `targets_mask` ✓（双保险早就在 ✓）
        #     ⚠ PC 端**有同一个洞**（`mapbot_pc/mapsim.py:168` 的 `plain` 也没判 blocked）
        #       —— 本条**只在手机端落地**，PC 仓不动（两端平行独立开发 ✓）
        if getattr(self, 'blocked', False):
            return False          # 拉黑块：不可点、**不可借道**（阻断连锁穿透 ✓）
        # ⛔⛔ v1.58【战斗保护提到最前 —— 移植 PC `mapbot_pc/mapsim.py:171-185`】
        #   PC 用户口径（原话，真机两次）：
        #     「**42 为什么能连锁？这不是战斗地块吗**」
        #     「**模型都认出这是海边小屋了，怎么还会认为是空地**」✗
        #   PC 真机铁证（`runs/r_200646_0.png` 第 3 张图）：
        #     计划第1步 `(4,2)` = `S00003_301`「海边小屋」score 0.757、ratio **1.19（已揭示✓）**
        #     数据表 `SpotSize=6 / EventNum=6-6` ⇒ **战斗地块** ⇒ 正确定价 **6×2 = 12 体** ✓
        #     且**不连锁** ✗ —— 可模型给出 `plain=True` ✗ ⇒ `block_cost = 1` ✗
        #     ⇒ 还被算进"草地连锁"⇒ 计划第一步的代价与后续推演**全错** ✗✗
        #   根因（**手机端原来就是这个形状** ✗）：下面"雾格剪影"那一支
        #     **提前 return、完全不看名字/类型**（本意是"雾里名字不可信 ⇒ 改看剪影平坦度"，
        #     但它**排在战斗保护之前** ✗）
        #   ⇒ **战斗保护提到最前**：任何分支都不许把战斗型地块判成空地 ✓
        try:
            import spots as _sp0
            if _sp0.is_fight_spot(self.sid):
                return False
        except Exception:       # noqa: BLE001
            pass
        if '营地' in (self.name or ''):
            return False                     # 出生地：不可点 + 阻断连锁 ✓
        # ⭐⭐⭐ 2026-10-01 v1.03【雾格剪影一票否决】——用户口径「优化识别模型，认出雾格里那块
        #   不能穿过」：雾格剪影占比 ≥ `spots.FOG_SIL_MIN`(0.04) ⇒ 底下**有东西** ⇒ 不是空地
        #   （真机同帧实测：有物体 0.064~0.292 / 平坦 0.014~0.016，4 倍空档 ✓）
        #   ⚠ 只对**雾格**生效（`state()` 只在 ratio<0.78 时打这个标）；揭开后按真实分类建模 ✓
        # ⛔⛔ v1.59（2026-10-04）【**补 `not observed` 闸门** —— 治真机「两格空地各点一次」】
        #   用户口径（原话）：「**目标和营地之间有两个空地，明明点一个空地就能直接打目标，
        #   结果手机端规划非要两个都点**」✗
        #   真机日志铁证（v1.59 新加的 `plan_blocks` 诊断，Redmi 25053RT47C）：
        #     step1 `{"cell":"3,4","sid":"S30001_001","name":"岩地","plain":true,"group":["3,4"]}`
        #     step2 `{"cell":"3,3","sid":"S30001_001","name":"岩地","plain":false, ...}`
        #     `{"solver":"ok","cost":7,"steps":4,"order":["3,4","3,3","3,2","2,1"]}`
        #   ⇒ **相邻两格、同一个 sid**，却一个判空地一个判非空地 ⇒ `plain_group` 走不过去
        #     ⇒ **连锁断裂** ⇒ 每格各点一次 ⇒ 本该 2 步变成 **4 步** ✗✗
        #   根因：`fog_object` 的语义是「**雾下**剪影」（`_from_anchors` 里按
        #     `row['fog_sil'] >= FOG_SIL_MIN` 设，**没看观测状态**）；可**已揭示**的岩地
        #     本身就有纹理 ⇒ 剪影照样高 ⇒ 被判成"雾下有物体" ⇒ 非空地 ✗✗
        #     （逐行对拍 PC `mapbot_pc/mapsim.py:182-229`：判据顺序手机端与 PC **一模一样**，
        #       PC 那条也**没带** `not observed` ⇒ 差异**不在 `plain`**，在**谁把
        #       `fog_object` 设成了 True** —— 手机端把**已揭示**格也算出了剪影 ✓）
        #     ⚠ 见下面**同函数相邻**那条剪影分支（`not observed` + `fog_sil is not None`）：
        #       它**本来就带**闸门 ⇒ 这里少一条正是漏改的样子 ✓
        #   修法：**雾下**剪影才挡连锁；**已揭示**格的分类（sid/name）可信，
        #     不该被剪影推翻 ✓
        #     ⚠ 这不是发明新规则 —— 是**对齐 PC 的实际行为**（PC 那条只在雾格触发，
        #       否则它 `:202` 分支就不必专门加 `not observed` 了 ✓）
        #     ⚠ 真雾格（observed=False）**照旧挡连锁**（机制 M54 不许失效，见下 ✓）
        if getattr(self, 'fog_object', False) and not getattr(self, 'observed', False):
            return False          # **雾下**有物体 ⇒ 非空地（挡连锁 ✓）
        # ─────────────────────────────────────────────────────────────────────────
        # ⚠⚠⚠ v1.62【**撤回** PC `9129a78` 的「高置信内容地块拦连锁」—— 留档，别再试】
        #   PC 那条：`score ≥ 0.85` 且非本图地面 ⇒ 非空地（拦连锁）。
        #   PC 依据（`runs/acc2/r_153038_0.png`）：`(4,1)` 宝箱 **score=1.0** 但
        #     `fog_sil` 只有 0.04（**宝箱美术亮 ⇒ 剪影法漏掉**）⇒ 误判"平坦空地" ✗
        #
        #   ## 手机端为什么**不能照抄**（v1.62 实测，两轮证据都留了探针）
        #     ① 直接搬（只看 score）⇒ **拦错 8/10 个**（`tools/probe_e_effect.py`）：
        #        `5,4`/`5,7` 宝箱、`1,4` 蘑菇丛、`3,5`/`4,2` 矿箱堆、`4,7` 露天矿
        #        全是 **floor=65~74（纯雾）** 却被 score 0.93~0.97 命中
        #     ② 加**地板闸门**（只拦"地板判亮"的）⇒ 判据对了，但
        #        **对 6 张真机帧零影响**（`tools/probe_e_decide.py`：逐块比 `plain`
        #        ⇒ **0 个块改变**、规划逐字相同）—— 因为手机端"真亮的内容格"
        #        **早就被更早的分支拦掉了**（`2,1` 矿箱三个条件全满足，
        #        可它 `plain` 早已是 False ✓）⇒ 纯冗余
        #
        #   ## ⭐ 决定性反证：**雾格上的高分名字不可信**（真机日志铁证）
        #     本轮那把（13:38）模型给 `(4,2)` 的判读是
        #       `{"cell":"4,2","name":"矿箱堆","sid":"S30001_101","score":0.933}`
        #     可真机点下去是 **`开打 · 首领格`（标记 ['boss']）** —— **名字是错的** ✗✗
        #     ⇒ `score ≥ 0.9` **不代表雾格上的名字对** ⇒ 不带地板闸门就拦，
        #       会把真能连锁穿过的格子拦住 ⇒ **连锁全断（比原问题更糟）** ✗
        #     ⚠ PC 那边量纲不同（PC 的 `state()` 只对已揭示格给高分）
        #   ⇒ 结论：**手机端不搬这条** ✓ 真要有用得先有"雾格名字可信度"的独立判据
        #     —— 那是另一个课题（本轮回合已记录在 `PC修复移植单.md`）
        #   ⚠ 下面那条 `fog_object` 挡连锁的判据**是原有的**（v1.58 加的 `not observed`
        #     闸门）—— 撤回 E 时**不要连它一起删** ✓（本行历史上踩过一次重复插入）
        # ⭐⭐⭐ v1.06【雾格平坦 ⇒ 当空地】：对**雾格**来说"名字"很不可信（真机这盘整套模板
        #   中位分只有 0.276，平坦格被猜成「岩石/巨大木桩」✗）⇒ 雾格的 plain 只认剪影实测：
        #     有物体（fog_object）⇒ 非空地 ｜ 平坦（fog_flat）⇒ 空地
        #   ⚠ 仅当该格**有剪影值**（= 它是雾格）时接管；揭开后走下面按名字/后缀的老逻辑 ✓
        # ⚠⚠⚠ v1.58【加 `not observed` —— 移植 PC `mapbot_pc/mapsim.py:198-203`】
        #   这一支**只看真雾格**（观测时未揭示 ✓）；**已揭示的格必须**按名字/类型判断 ✓
        #   PC 真机反例（`r_200646_0.png`）：(4,2) ratio=**1.19（已揭示）** 却带着剪影值
        #     ⇒ 旧写法（只看 `fog_sil is not None`）会**绕过一切判断** ⇒ `plain=True` ✗✗
        #   → 与上面"战斗保护提到最前"是**同一场事故的两半**，必须一起改 ✓
        #   ⚠ 负样本必须守住：**真雾格 + 剪影平坦 ⇒ 仍 `plain=True`**
        #     （别把这一支整个删掉 —— 那是另一个机制 M54，删了会连锁穿过雾里的障碍 ✗）
        # ⭐⭐⭐ v1.70【剪影说"平坦"之后**再查一次数据表**】—— 见文件头 `FOG_TABLE_GATE`
        #   那段长注释（病根：`(5,5)` 矿箱被当空地、无视它拦住连锁 ✗）
        #   ⚠ **只加"否决"、不改"放行"**：`fog_flat and 表说非空地` ⇒ False；
        #     其余一切情形**原样返回** `fog_flat` ✓（真雾格平坦 ⇒ 仍是空地，M54 不失效 ✓）
        if (not getattr(self, 'observed', False)) and self.spot.get('fog_sil') is not None:
            if bool(getattr(self, 'fog_flat', False)) and _fog_content_by_table(self):
                return False
            return bool(getattr(self, 'fog_flat', False))
        suf = str(self.sid or '').split('_')[-1]
        # ⚠ v1.05：og_flat（雾格平坦⇒当空地）**暂不启用** —— 集成路径里剪影值与独立原型
        #   不一致（疑似 state() 内部对帧做过缩放/几何换算），修好再开 ✓ 先把值记进日志备查 ✓
        suf = str(self.sid or '').split('_')[-1]
        # ⭐⭐⭐ v1.48【战斗型地块**永远不许**当空地】—— 学 PC 端 `74a5e72`
        #   （PC 用户原话：「**为什么还是要去打战斗格子？这样不是会贵吗**」）
        #   PC 端真机根因（acc1 `gui_20261003_140308` 第 2 张图，离线逐格对账实证）：
        #     `A* 计划 = [(2,6, cost=1), (2,5, 1), (3,1, 6)]` ⇒ 总价 8
        #     ⇒ 那个**要打的战斗格 (2,6) 被算成 1 体** ✗（应按 格数×2 = 6 ✓）
        #     ⇒ 模型以为"打架不要钱"⇒ 放着绕路(12)不走、偏走打架那条(8) ✗✗
        #   原因就在下面那条**「运行时学到」**的捷径（`PLAIN_SEEN`）：
        #     只要有一次把战斗型地块误学成空地，**该类型全部格子**都变成 1 体 ✗
        #     ⇒ 与 `block_cost` 的**类型定价**（v1.43 的 `is_fight_spot`）**互相矛盾** ✗✗
        #   ⇒ 数据表 `EventNum` 说了算：战斗型 ⇒ **绝不可能是空地** ✓
        #   ⚠ 放在**雾格分支之后**（雾格分类很不可信 —— v1.06 注释：「整套模板中位分只有
        #     0.276，平坦格被猜成岩石/巨大木桩」，那时按剪影判才稳 ✓）
        #     ⇒ 只对**已揭示**的格子生效，那里的分类分数通常 ≥0.9（真机实测分布）✓
        try:
            import spots as _sp
            if _sp.is_fight_spot(self.sid):
                return False
        except Exception:       # noqa: BLE001
            pass
        # ⭐ 运行时学到的优先（点过、知道是连锁还是弹面板 ✓）
        if suf in PLAIN_SEEN:
            return True
        if suf in PANEL_SEEN:
            return False
        if suf in PLAIN_SUFFIX and suf != '000':
            return True
        return '草' in (self.name or '')     # ⭐ 只连锁草地（用户口径）

    @property
    def is_merchant(self):
        return self.name in ('旅行商人',)

    @property
    def is_vault(self):
        return self.name in ('黄金宝库',)

    @property
    def is_buy(self):
        return self.is_merchant or self.is_vault

    def __repr__(self):
        return '<B%d %s%s%s>' % (self.idx, self.name,
                                 '/mark=%s' % self.mark if self.mark else '',
                                 '/gone' if self.gone else
                                 ('' if self.revealed else '/fog'))


class MapSim:
    """探索地图模拟器（只做揭格/消耗/目标判定；战斗与掉落不在这一层）"""

    def __init__(self, board=None, blocks=None):
        self.board = list(board or [-1] * NCELL)      # cell -> block idx
        self.blocks = {b.idx: b for b in (blocks or [])}
        for b in self.blocks.values():
            b.cells = [i for i, v in enumerate(self.board) if v == b.idx]
        self.clicks = 0
        self.stamina = 0            # ⭐ 累计体力（源码口径，见 charge()）
        self.log = []
        # ⭐⭐⭐ v1.58【`obs_cells` —— 手机端**不再赋值** ⇒ `EMPTY_ADJ` 闸门**不生效**】
        #   ⚠⚠ 这是**用户拍板的口径**：**对齐 PC 的「实际行为」**（PC 真机跑的就是没有闸门那一版）。
        #   依据（《PC规划算法对照报告》D-4，已实测）：
        #     · PC `_build_cache` 里**写了**这道闸门（`mapsolve.py:424-429`），注释说
        #       "只有拿到观测格集合时才启用"；但 PC 的 `MapSim.from_observation`（`:296-389`）
        #       与 `_from_anchors`（`:391-489`）**从不给 `sim.obs_cells` 赋值**
        #       ⇒ 探针实测 `obs_cells = None` ⇒ **PC 真机路径上这道闸门是死代码** ✓
        #     · PC 唯一赋值点在 `from_memory_dump`（`mapsim.py:568-573`），而那段在 `try` 里
        #       引用了该函数**不存在的局部变量 `cells`** ⇒ 恒走 `except` ⇒ `set()` ✓
        #     · 而手机端 v1.51 **真的赋了值**（探针实测 35 个格索引）⇒ 闸门**启用** ⇒
        #       "被剔出模型的格"不能再当揭示源 ⇒ 模型里可能留下**永远不可达的目标**
        #       ⇒ `exhausted`（探针 B/C 实测：camp 打标成功、`camp_nb` 非零，仍
        #          `reason=exhausted expanded=16/18`）✗
        #   ⇒ 手机端对齐 PC 的**行为**（不启用），默认就是 `None` ✓
        #   ⚠⚠ 与它**成对**出现的 `Block.observed`（M8 `block_revealed` 的观测闸门）
        #     **必须留着** ✓ —— 那是**另一个**机制（判"块内观测里有没有已揭示的格"），
        #     不依赖 `sim.obs_cells`；别把两半一起删 ✗（v1.51 就是只搬了一半）
        self.obs_cells = None

    # ---------- 体力（源码 82956-82992） ----------
    @staticmethod
    def block_cost(b):
        """普通格 = SpotSize；战斗格 = SpotSize*2（战斗/探索产出都是 ×2）

        ⭐⭐ 2026-09-27 用户明确口径（与 `mapsolve` 同口径，2026-09-28 补同步）：
            「空白格都是 1 点，且不管连锁多少其他挨着的空白格」
            ⇒ **空地固定 1 点**（不是 Σ SpotSize ✗）
            「最小的战斗格子都要花 4 点（1 乘 2 的）」⇒ 战斗格 = SpotSize × 2
        ⚠ 2026-09-28 才发现：`_fix_blank_cost_1.py` 当年**只改了 mapsolve.py、
          漏了 mapsim.py** ⇒ 模拟器按"整片 Σ"、求解器按"固定 1 点"
          ⇒ 策略评估与最优解**不可比**（苹果比橘子，"基线多花 16%"是虚的）。
        """
        if getattr(b, 'plain', False):
            return 1
        size = int(getattr(b, 'size', 1) or 1)
        # ⭐⭐⭐ v1.58 与 `mapsolve` 同口径：**先按地块类型**判是不是战斗型
        #   **原样移植 PC `mapbot_pc/mapsim.py:278-288`**（PC commit `a7df4af` 的正文写明
        #   「修法（**三处同步**，口径一致 ✓）」）：
        #     `EventNum` > 1-1 ⇒ 战斗 ⇒ `size×2` ✓（临时标记 `拦路` 在**规划时**还没有 ✗）
        #   ⚠ 手机端原来是**既没有类型定价、mark 元组也缺 `'拦路'`** ✗
        #     ⇒ EffPolicy / 离线对拍 / `model_cost` 审计把"要打的架"按**探索价**算
        #     ⇒ 选出"看起来便宜、实际更贵"的路（PC 用户原话：
        #        「**为什么还是要去打战斗格子？这样不是会贵吗**」）✗
        try:
            import spots as _sp             # ⚠ 本模块**故意不 import spots**（数据靠参数传 ✓）
            if _sp.is_fight_spot(getattr(b, 'sid', None)):   # 局部导入：首次后走缓存，零开销 ✓
                return size * 2
        except Exception:       # noqa: BLE001
            pass
        if getattr(b, 'mark', None) in ('boss', 'redEquip', 'recommend', 'battle',
                                        '拦路'):
            return size * 2
        return size

    def charge(self, cost):
        self.stamina += int(cost)
        return cost

    # ---------- 构造 ----------
    @classmethod
    def from_observation(cls, cells, spot_table, group=True):
        """从「一次真实观测」建盘

        cells: {(r, c): {'sid':..., 'name':..., 'revealed':bool, 'marks':[...]}}
               （探索循环 `cells_of()` / `spots.Board.state()` 的输出）
        spot_table: spots.spot_rows() —— 真实地块表（拿 SpecialSpot/SpotSize）
        group: 把**相邻且同 sid** 的格子归成一个块（游戏里 2×2 大地块就是这样 ✓）
               —— 不归组的话，一个 4 格地块会被拆成 4 个块，体力/揭示都会算错 ✗

        ⭐⭐⭐ 2026-09-28 新增（用户真机报 `r_224535_0`「(1,1) 前面应该有个 (3,1) 宝箱」）：
            **只要格子带 `anchor` 字段 ⇒ 一律按它归组**（`_from_anchors`），不再用
            「相邻 + 同 sid」猜 ✗。原因（真机像素铁证 `runs/_zoom_1535_corner.png`）：
              左上角是**两棵独立的竖排椰树** 椰树#1=(1,1)+(2,1) / 椰树#2=(1,2)+(2,2)，
              旧规则把它们**并成一块** ⇒ ① boss 只算一次点击（4 点，实际要 8 点：
              真机连打两场战斗 ✓）② 被并后的块直接挨着已消草地 (1,3) ⇒ 规划以为
              「不用 (3,1) 就能点 boss」⇒ 真机 `tap: fogged_noop at (1,1)` 点不动 ✗✗
              按 anchor 归组后：椰树#1 的格 = (1,1)+(2,1)，与草地 (1,3) **不邻接**
              ⇒ boss 只能靠 (3,1) 宝箱（1 点，邻 (2,1)）或椰树#2 解锁 ⇒ solver 选出
              `(2,4)→(3,1)宝箱→(3,5)→(4,5)商人→(1,1)boss` = 8 点 / 5 步 ✓
              （与用户「(1,1) 前面应该有个 (3,1)」逐字吻合 ✓）。
            `anchor` 由 `spots.Board.state()`（alpha 真实占格 + 掩膜 NCC）给出 —— 是
            比"相邻同 sid"可靠得多的**真机占格**结论 ✓
        """
        if any(isinstance(v, dict) and v.get('anchor') for v in cells.values()):
            return cls._from_anchors(cells, spot_table)
        board = [-1] * NCELL
        # ⭐⭐⭐ v1.58【观测格集合 `obs_cells` —— 手机端**不给它赋值**（抄 PC 真机的实际行为）】
        #   v1.51 曾在这里攒 `obs_cells` 并交给 `sim.obs_cells` ⇒ 把 `EMPTY_ADJ` 闸门**真启用**了；
        #   而 PC 真机路径上**从不赋值**（唯一赋值点在 `from_memory_dump`，那句引用了
        #   该函数不存在的局部变量 ⇒ 恒异常被吞 ⇒ `set()`）⇒ PC 那道闸门是**死代码** ✓
        #   ⇒ 按用户口径**对齐 PC 的实际行为**：这里不再攒、不再赋值
        #     （闸门代码留在 `mapsolve._build_cache` 里不动，只是永远拿到 `None` ⇒ 不生效 ✓）
        #   ⚠ 详细依据与"为什么不能启用"的实测见 `MapSim.__init__` 里 `self.obs_cells` 那段注释 ✓
        idx_of = {}
        blocks = []
        for (r, c) in sorted(cells):
            sid = cells[(r, c)].get('sid') or cells[(r, c)].get('name')
            # ⚠ 只有 **SpotSize>1 的大地块**才跨格；1 格地块（草地/海螺…）各自独立 ✗
            #   （否则相邻同 sid 的草地会被并成一大块，块数/体力/揭示全算错）
            size = int((spot_table.get(sid) or {}).get('SpotSize') or 1)
            if group and size > 1:
                for (dr, dc) in ((-1, 0), (0, -1)):
                    nb = (r + dr, c + dc)
                    if nb in idx_of and (cells.get(nb, {}).get('sid') or
                                         cells.get(nb, {}).get('name')) == sid:
                        bi = idx_of[nb]
                        board[cell_of(r, c)] = bi
                        blocks[bi].cells.append(cell_of(r, c))
                        idx_of[(r, c)] = bi
                        if cells[(r, c)].get('marks'):
                            blocks[bi].mark = (cells[(r, c)]['marks'] or [None])[0]
                        break
                else:
                    size = 1        # 合并失败 → 当作独立块
                if board[cell_of(r, c)] >= 0:
                    continue
            row = dict(spot_table.get(sid) or spot_table.get(cells[(r, c)].get('name')) or {})
            if not row:
                # ⚠ 认不出地块时：**带标记的格绝不能当空地**（否则会被当成连锁揭示的一部分白白消耗）
                has_mark = bool(cells[(r, c)].get('marks'))
                row = {'SpecialSpot': 1 if has_mark else 0, 'SpotSize': 1}
            row = dict(row)
            row['sid'] = sid
            row['name'] = cells[(r, c)].get('name') or sid
            if 'target' in cells[(r, c)]:              # ⭐ 目标白名单（targets_cfg）✓
                row['want'] = bool(cells[(r, c)].get('target'))
            # ⭐⭐⭐ v1.51 抄 PC（与 `_from_anchors` 那条**同步** ✓）：
            #   · `camp` / `camp_cells` ⇒ `Problem.camp` 的兜底锚点（营地被吞时必须有 ✓）
            #   · `cells`               ⇒ `Block.size` 按**实际格数**封顶 ✓
            if cells[(r, c)].get('camp'):
                row['camp'] = True
                row['camp_cells'] = [cell_of(r, c)]
            row['cells'] = [cell_of(r, c)]
            # ⭐ v1.44 拉黑标（与 `_from_anchors` 那条**同步** ✓）：
            #   row 是从数据表构造的 ⇒ 观测字段必须**显式搬过来**，否则到不了 Block ✗
            if 'blocked' in cells[(r, c)]:
                row['blocked'] = bool(cells[(r, c)].get('blocked'))
            b = Block(len(blocks), row, revealed=bool(cells[(r, c)].get('revealed')),
                      mark=((cells[(r, c)].get('marks') or [None])[0]))
            board[cell_of(r, c)] = b.idx
            b.cells = [cell_of(r, c)]
            idx_of[(r, c)] = b.idx
            blocks.append(b)
        _sim = cls(board, blocks)
        # ⚠ v1.58：**故意不赋值 `obs_cells`** —— 见本函数开头与 `__init__` 里的说明
        #   （PC 真机路径上这道 `EMPTY_ADJ` 闸门是死代码 ⇒ 手机端也对齐"不启用" ✓）
        return _sim

    @classmethod
    def _from_anchors(cls, cells, spot_table):
        """⭐ 按 `anchor` 字段归组建盘（真机占格；见 `from_observation` 的说明）

        · 每个 **anchor 值** = 一个地块；`cells` = 所有 anchor 指向它的格（含成员格 ✓）
        · 块尺寸/SpecialSpot 一律**查地块表**（成员格只是占格信息，不参与算尺寸）
        · 标记：锚点优先，成员格兜底（boss 图标可能画在成员格上）
        """
        grp = {}
        for k, v in cells.items():
            a = tuple(v.get('anchor') or k)
            # ⭐⭐⭐ v1.51【分组键 = `(anchor, sid)`】—— 抄 PC 端 `279d311`
            #   PC 根因修复（用户口径：「**只有相连的空地才能连锁**」✓）
            #   真机实证（`runs/r_184822_0.png`）：同一 anchor 里混了 **001 草地** 与
            #   **211 巨大沙堡** ⇒ 块 sid 取 head 的 `_001` ⇒ `plain=True` ⇒
            #   **`plain_group` 连锁穿过它** ✗ ⇒ 模型"草地片"=18 格、**10 格非草地**
            #   （含 boss (1,4) 椰树、宝箱 (4,3) 0.999 …）⇒ 模型以为
            #   "点 (4,1) 一步连锁吃整片（含 boss）"⇒ **计划直接点雾里的 boss
            #   ⇒ 漏打 boss** ✗✗
            #   ⇒ 同 anchor 内不同 sid ⇒ **各建一块** ✓
            #     （不动函数体、不重新缩进 ⇒ 出错面最小 ✓；每组仍按原路径完成
            #      row → Block() → board[] → blocks.append 的全套记账 ✓）
            _sid_k = str(v.get('sid') or '')
            grp.setdefault((a, _sid_k), []).append(k)
        board = [-1] * NCELL
        blocks = []
        for _key in sorted(grp):
            a = _key[0]                          # ⭐ 键 = (anchor, sid) ✓
            members = sorted(grp[_key])
            head = dict(cells.get(a) or cells[members[0]] or {})
            sid = (_key[1] or head.get('sid') or head.get('name'))     # ⭐ 用本组的 sid ✓
            row = dict(spot_table.get(sid) or {})
            marks = list(head.get('marks') or [])
            for m in members:
                for mk in (cells[m].get('marks') or []):
                    if mk not in marks:
                        marks.append(mk)
            if not row:
                # ⚠ 认不出地块时：**带标记的格绝不能当空地**（同 from_observation ✓）
                has_mark = bool(marks)
                row = {'SpecialSpot': 1 if has_mark else 0, 'SpotSize': 1}
            row = dict(row)
            grew = head.get('revealed')
            if grew is None:
                grew = any(cells[m].get('revealed') for m in members)
            # ⭐⭐⭐ v1.06 修**多格块丢剪影**（真机 A/B 抓出来的真根因）：
            #   块的代表格（anchor）**常常是平坦的那一格**，而成员的剪影各不相同 ——
            #   真机铁血高地实证：`(5,3)` 属于 6 格块 anchor=(3,2)，anchor 剪影 0.016（平坦）
            #   但 `(5,3)` 自己 0.271（下面是大木桩！）⇒ 旧代码只读 anchor ⇒
            #   整块被当成空地 ⇒ **连锁穿过大木桩** ✗✗（= 用户最初报的那个现象）
            #   ⇒ 取**成员里剪影最大的那个**（只要有任一成员看出有东西，整块就非空地 ✓）
            _sils = [float(cells[m].get('fog_sil')) for m in members
                     if cells[m].get('fog_sil') is not None]
            if _sils:
                row['fog_sil'] = max(_sils)
                # ⭐⭐⭐⭐ v1.62【**优先用观测里已经判好的 `fog_object`**】—— 照抄 PC `f3b0f4e`
                #   PC 原文：「别再拿模块常量重算一遍，**否则第 1 条白做** ✗」
                #   为什么：`spots.state()` 现在按**本帧众数**判 `fog_object`
                #     （矿洞岩地纹理 0.114 ⇒ 阈值 0.183 ⇒ 判"平坦=空地" ✓）
                #     而这里若还用**模块常量** `FOG_SIL_MIN(0.04)` 重算 ⇒ 又把它判回
                #     "有东西" ⇒ **前面那一改等于没做** ✗✗
                #   ⇒ 用观测值；观测没给（老调用/合成盘）才退回模块常量 ✓（向后兼容）
                _fobj_obs = [bool((cells.get(m) or {}).get('fog_object')) for m in members
                             if (cells.get(m) or {}).get('fog_object') is not None]
                if _fobj_obs:
                    row['fog_object'] = any(_fobj_obs)   # 任一成员有东西 ⇒ 整块非空地 ✓
                else:
                    row['fog_object'] = bool(row['fog_sil'] >= FOG_SIL_MIN)
                row['fog_flat'] = not row['fog_object']
            # ⚠⚠ v1.62：**曾**在这里搬过 `score`/`Weight`/`floor_lit` 三个字段
            #   （PC `9129a78` 那条要用）—— 该条**已完整撤回**，字段一并撤回 ✓
            # ⭐⭐⭐ v1.70【`score` **加回来** —— 现在有真实用途了（不再是死字段 ✓）】
            #   用途：`Block.plain` 分支⑤ 的雾格数据表闸门要用它做**分数下限**
            #   （见文件头 `FOG_TABLE_GATE` 那段 + `_fog_content_by_table()`）✓
            #   ⚠ 与 v1.62 的区别：那次搬的是**E 条判据本身**（只看分数就拦，已证伪 ✗）；
            #     这次只搬**一个字段**，判据是"数据表 + 分数下限"，形状完全不同 ✓
            #   取**成员里最大**的（任一成员认得出内容物 ⇒ 整块可信 ✓，与 `fog_sil` 同口径）
            _scs = [float(cells[m].get('score')) for m in members
                    if cells[m].get('score') is not None]
            if _scs:
                row['score'] = max(_scs)
            # ⭐⭐⭐ v1.74【`floor_lit` 也要搬下来 —— 治"假亮格能隔空直接点"】
            #   用户 2026-10-06 原话（真机 15:21 那把）：**「为什么能直接点 13？
            #   13 没有紧挨着出生地啊」** ⇒ 用户看图，`(1,3)` 根本不挨着营地 ✓
            #   ## 真机铁证（`board_r0_152127.png` 离线复算，逐格可查）
            #     `(1,3)` = `S30001_016 黄金宝库`、`ratio 0.823`、**`floor_lit=False`**
            #       · `ratio ≥ REVEAL_RATIO_MIN(0.80)` ⇒ 判 `revealed=True`
            #         ⇒ `observed=True` ⇒ 进 `_build_cache.obs_lit` ⇒ `solve().visible()`
            #         **直接放行**（`camp_nb=False / empty_adj=False` ⇒ 与"挨不挨着营地"无关）✗
            #       · 而**地板法说它是雾**（`floor_lit=False`）—— 地板正是为治
            #         "ratio 不可靠"而加的（v1.62）⇒ 两者冲突时**地板更可信** ✓
            #     ⇒ 即"**一个被误判成亮的雾格，能隔着整个棋盘被直接点**" ✗✗
            #   ## 为什么字段必须显式搬（本项目的老坑，v1.70 刚踩过一次）
            #     `row` 是**从地块表单独构造**的 ⇒ 观测字段不搬就**到不了 `Block`**；
            #     实测确认：`_cells_for_model` 的产物里 `floor_lit` **35 格全有**，
            #     而 `Block.spot` 里**既没有 `floor` 也没有 `floor_lit`** ✗
            #   ⚠ 取成员的**或**（任一成员地板判亮 ⇒ 整块算亮）——
            #     与 `fog_object` 的 `any` 同口径；比"取最小值"更安全（宁可不点 ✗）
            _fls = [bool((cells.get(m) or {}).get('floor_lit')) for m in members
                    if (cells.get(m) or {}).get('floor_lit') is not None]
            if _fls:
                row['floor_lit'] = any(_fls)
            row['sid'] = sid
            row['name'] = head.get('name') or sid
            if 'target' in head:                       # ⭐ 目标白名单（targets_cfg）✓
                row['want'] = bool(head.get('target'))
            # ⭐ v1.44 拉黑标（与单格那条**同步** ✓，见 Block.blocked 的说明）
            if 'blocked' in head:
                row['blocked'] = bool(head.get('blocked'))
            # ⭐⭐⭐ v1.51 抄 PC：这三个字段要在**成员上聚合**再搬进 row ✗ 只看 head 会漏
            #   （`row` 是**单独从地块表构造**的 ⇒ 观测字段必须显式搬，否则到不了 Block ✗）
            #   · `cells` ⇒ `Block.size` 按**实际格数**封顶（治「16 为什么是 18 体」✓）
            #   · `camp` / `camp_cells` ⇒ `Problem.camp` 的兜底锚点 ——
            #     ⚠⚠ **真机铁证（PC 离线复算 r_233023_0.png）**：营地格 (2,1) 属于多格块
            #       `巨大沙堡`（anchor=(1,1)）⇒ **走的就是这条路**，而 `head` 是**锚点那一格**、
            #       `camp=True` 常常打在**成员格**上 ⇒ 只看 head ⇒ `Block.camp=False`
            #       ⇒ `Problem.camp=None` ⇒ 揭示链**没有起点** ⇒ 求解器 `exhausted`
            #       （**整张图干等/退图**）✗✗
            #     ⇒ **锚点或任一成员带 camp 标记 ⇒ 标到整块上** ✓
            #     ⇒ 而 `camp_cells` 只收**真正带标记的那几格**（不是整块 ✓，
            #        否则 boss 会被整块邻接误判"开局可点" ✗）
            row['cells'] = [tuple(x) for x in members]
            if head.get('camp') or any((cells.get(m) or {}).get('camp') for m in members):
                row['camp'] = True
                row['camp_cells'] = [cell_of(*m) for m in members
                                     if (cells.get(m) or {}).get('camp')]
            b = Block(len(blocks), row, revealed=bool(grew),
                      mark=(marks[0] if marks else None))
            b.cells = [cell_of(*m) for m in members
                       if 0 <= m[0] - 1 < ROWS and 0 <= m[1] - 1 < COLS]
            for c in b.cells:
                board[c] = b.idx
            blocks.append(b)
        _sim2 = cls(board, blocks)
        # ⚠ v1.58：**故意不赋值 `obs_cells`**（`_from_anchors` 这条路也一起关掉）——
        #   依据同 `from_observation`：PC 真机路径上 `EMPTY_ADJ` 闸门是死代码，
        #   手机端对齐 PC 的**实际行为** ⇒ 不启用 ✓（`Block.observed` 不受影响，照旧 ✓）
        return _sim2

    @classmethod
    def from_memory_dump(cls, bin_path, spot_table):
        """从**游戏内存窗口**里直接建盘（比截图建盘干净：拿到完整 blockBoard + 每块的存档字段）

        存档字段（`SaveData.ExploreMap.MapBlock`）：
            iDs=地块ID（查地块表） / battleEvent=战斗事件（含 isBossFight、equipStar 等）
            goldenVault / shop / heritage / relic / saga / gamble / rune / foretellInfo …
        可见性：存档里没有逐格可见标志 ⇒ 按游戏的连锁规则**反推**
            （被消耗格 = blockBoard 里 -1；与空格 4 邻接的格 = 已揭示）
        """
        import re
        d = open(bin_path, 'rb').read()
        best = None
        for m in re.finditer(rb'"blockBoard":\[([0-9,\-]+)\]', d):
            arr = [int(x) for x in m.group(1).split(b',') if x != b'']
            if len(arr) == NCELL and len(set(arr)) > 5 and (best is None or
                                                            len(set(arr)) > len(set(best[1]))):
                best = (m.start(), arr)
        if best is None:
            return None
        off, board = best
        # ⚠ 必须取**同一份存档副本**里的 blockList：dump 里往往有好几份快照，
        #   向前找最近的那个 `"blockList":[`（序列化顺序是 blockList 在 blockBoard 前面）
        bl = []
        m2 = None
        for cand in re.finditer(rb'"blockList":\[', d[:off]):
            m2 = cand
        if m2:
            j = m2.end() - 1
            depth, in_str, esc = 0, False, False
            for e in range(j, len(d)):
                ch = d[e:e + 1]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == b'\\':
                        esc = True
                    elif ch == b'"':
                        in_str = False
                    continue
                if ch == b'"':
                    in_str = True
                elif ch == b'[':
                    depth += 1
                elif ch == b']':
                    depth -= 1
                    if depth == 0:
                        try:
                            bl = json.loads(d[j:e + 1].decode('utf-8', 'replace'))
                        except Exception as ex:     # noqa: BLE001
                            print('[mapsim] blockList 解析失败: %r（切片 %.1f KB）'
                                  % (ex, (e + 1 - j) / 1024.0))
                            bl = []
                        break
        blocks = []
        for idx in sorted(set(v for v in board if v >= 0)):
            info = bl[idx] if idx < len(bl) else {}
            sid = info.get('iDs')
            # ⚠ 存档里普通地块的 iDs 常常是空的（只有特殊块才有 ID）⇒ 视为空地
            row = dict(spot_table.get(sid) or {})
            if not row:
                row = {'SpecialSpot': 0, 'SpotSize': 1}
            row = dict(row)
            row['sid'] = sid
            row['name'] = (spot_table.get(sid) or {}).get('Name') or ('空地' if not sid else sid)
            ev = info.get('battleEvent') or {}
            mark = None
            if ev.get('isBossFight'):
                mark = 'boss'
            b = Block(idx, row, revealed=False, mark=mark)
            b.save = info
            # ⚠ 别再按 goldenVault/shop 字段改名：**每个** block 的存档里都有
            #   `goldenVault:{"currentLevel":0}` 这个空结构 ⇒ 会把整盘都叫成黄金宝库。
            #   地块名一律以地块表的 Name 为准（S00003_000=营地、…_001=草地、宝库/商人表里也有）。
            blocks.append(b)
        sim = cls(board, blocks)
        sim._infer_revealed()
        # ⚠ 开局满盘（没有任何已消耗格）时反推不出可见性 ⇒ 按游戏表现补：**营地 + 它的 4 邻格已揭示**
        if not sim.visible():
            camp = None
            for b in sim.blocks.values():
                if '营地' in (b.name or ''):
                    camp = b
                    break
            if camp is not None:
                for i in list(camp.cells) + [j for i in camp.cells
                                             for j in _neighbours(i)]:
                    bi = sim.board[i] if 0 <= i < NCELL else -1
                    if bi >= 0:
                        sim.blocks[bi].revealed = True
        return sim

    def _infer_revealed(self):
        """按游戏连锁规则反推可见性：与空格（已消耗）4 邻接的格 = 已揭示"""
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0:
                continue
            b = self.blocks[bi]
            if b.revealed or b.gone:
                continue
            r, c = i // COLS, i % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < ROWS and 0 <= cc < COLS):
                    continue
                if self.board[rr * COLS + cc] < 0:
                    b.revealed = True
                    break

    # ---------- 观测 ----------
    def visible(self):
        """当前"能点"的格子 = 未消耗且已揭示"""
        return [rc_of(i) for i in range(NCELL)
                if self.board[i] >= 0 and not self.blocks[self.board[i]].gone
                and self.blocks[self.board[i]].revealed]

    def fogged(self):
        return [rc_of(i) for i in range(NCELL)
                if self.board[i] >= 0 and not self.blocks[self.board[i]].gone
                and not self.blocks[self.board[i]].revealed]

    def fogged_marks(self):
        """未揭示但带标记的格（boss 常常这样：看得到标记、点不动）"""
        out = []
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0:
                continue
            b = self.blocks[bi]
            if not b.gone and not b.revealed and b.mark:
                out.append((rc_of(i), b.mark))
        return out

    def targets(self, want=('mark', 'buy')):
        """目标集合（跟探索循环一致：标记格 ∪ 商人/宝库）

        ⚠ 按**地块**去重：多格大块（blockSize>1，例如 2×2 的 boss 块）只算一个目标，
          锚点取该块最左上的格子（跟真机里"一格代表整块"一致）
        """
        out = []
        seen = set()
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0 or bi in seen:
                continue
            b = self.blocks[bi]
            if b.gone:
                continue
            hit = ('mark' in want and b.mark) or ('buy' in want and b.is_buy)
            if hit:
                seen.add(bi)
                out.append(rc_of(b.cells[0] if b.cells else i))
        return sorted(set(out))

    def done(self):
        """目标都清完了吗（商人/宝库要看是否已消耗）"""
        return not self.targets()

    # ---------- 规则（1:1 移植） ----------
    def connected_plain(self, start_cell):
        """源码 GetConnectedPlainBlocks：BFS 4 邻域，整片连通空地一起返回（块索引集合）"""
        bi = self.board[start_cell]
        if bi < 0:
            return set()
        b = self.blocks[bi]
        if not b.plain:
            return set()
        got, seen_cells, q = {bi}, set(), []

        def enqueue_block(idx):
            for j in range(NCELL):
                if self.board[j] == idx and j not in seen_cells:
                    seen_cells.add(j)
                    q.append(j)

        enqueue_block(bi)
        while q:
            cur = q.pop(0)
            r, c = cur // COLS, cur % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < ROWS and 0 <= cc < COLS):
                    continue
                nidx = rr * COLS + cc
                if nidx in seen_cells:
                    continue
                nb = self.board[nidx]
                if nb < 0:
                    continue
                blk = self.blocks[nb]
                if blk.gone:
                    continue
                # ⭐⭐ 2026-09-28 用户口径：连锁**能穿过雾**（不再要求 revealed）——
                #   真机证据：(1,5) 一次揭开 (1,5)(1,6)(1,7)，而 (1,6)/(1,7) 当时
                #   还是雾格 ⇒ 旧判据 `blk.revealed` 把片截断成 1 格 ✗
                #   （穿透仍只限 `plain`=草地 ⇒ 宝箱/海螺/岩石/营地照旧阻断 ✓）
                if blk.plain:
                    if nb not in got:
                        got.add(nb)
                        enqueue_block(nb)
                    seen_cells.add(nidx)
                    q.append(nidx)
        return got

    def click(self, rc):
        """点一格（1 基行列）。返回 ('plain', 消耗的块数) / ('panel', 块) / ('noop', 原因)"""
        r, c = rc
        idx = cell_of(r, c)
        if not (1 <= r <= ROWS and 1 <= c <= COLS):
            return ('noop', 'out_of_board')
        bi = self.board[idx]
        if bi < 0:
            return ('noop', 'empty')
        b = self.blocks[bi]
        if b.gone:
            return ('noop', 'gone')
        if '营地' in (b.name or ''):
            # ⭐ 2026-09-28：出生地**不可点**（点了只弹一个无用面板，不消耗、不揭示；
            #   explore_loop 已把它当"已完成"直接排除 ✓）
            return ('noop', 'camp')
        if not b.revealed:
            return ('noop', 'fogged')          # 未揭示 = 点不动（实测）
        self.clicks += 1
        if b.plain:
            grp = self.connected_plain(idx)
            # ⭐ 2026-09-28 修：空地**固定 1 点**（连锁吃掉多少格都一样，用户 2026-09-27 口径）。
            #   旧代码 `charge(Σ block_cost)` 与 mapsolve.step_cost 的"固定 1 点"不一致 ✗
            self.charge(1)
            for k in grp:
                self.blocks[k].gone = True
                for j in range(NCELL):
                    if self.board[j] == k:
                        self.board[j] = -1
            self._reveal_neighbours()
            self.log.append(('plain', rc, len(grp), len(self.visible())))
            return ('plain', len(grp))
        # 非空地：开面板。这里只把"面板结果"告诉策略层（战斗/购买由外层决定）
        self.charge(self.block_cost(b))
        self.log.append(('panel', rc, b.name, b.mark))
        return ('panel', b)

    def resolve_panel(self, rc, do_buy=True, do_fight=True):
        """面板处理结果（模拟外层策略）：商人/宝库买完 → 消耗；战斗格打完 → 消耗"""
        r, c = rc
        bi = self.board[cell_of(r, c)]
        if bi < 0:
            return None
        b = self.blocks[bi]
        if b.is_buy:
            if not do_buy:
                return None
            b.gone = True
        elif do_fight:
            b.gone = True                  # 打完这一格就消耗掉（实测：战斗格打完会消失/变新遭遇）
        if b.gone:
            for j in range(NCELL):
                if self.board[j] == bi:
                    self.board[j] = -1
            self._reveal_neighbours()
        return b

    def _reveal_neighbours(self):
        """消耗地块后：相邻格解锁为「已揭示」（实测：RemoveBlock → SetBlockVisible 连锁揭示）"""
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0:
                continue
            b = self.blocks[bi]
            if b.gone or b.revealed:
                continue
            r, c = i // COLS, i % COLS
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < ROWS and 0 <= cc < COLS):
                    continue
                if self.board[rr * COLS + cc] < 0:       # 邻居是空格（刚被消耗）⇒ 解锁
                    b.revealed = True
                    break

    # ---------- 指标 ----------
    def stats(self):
        return {'clicks': self.clicks,
                'stamina': self.stamina,
                'left_targets': len(self.targets()),
                'left_cells': sum(1 for i in range(NCELL) if self.board[i] >= 0),
                'visible': len(self.visible())}

    def render(self):
        """文字棋盘：已揭示=大写首字，未揭示=小写，空格='.'，标记加 *"""
        lines = []
        for r in range(1, ROWS + 1):
            row = []
            for c in range(1, COLS + 1):
                i = cell_of(r, c)
                bi = self.board[i]
                if bi < 0:
                    row.append(' .')
                    continue
                b = self.blocks[bi]
                ch = (b.name or '?')[0]
                if not b.revealed:
                    ch = ch.lower()
                if b.mark:
                    ch = ch.upper() if b.revealed else ch
                row.append(('%s%s' % ('*' if b.mark else '', ch))[-2:])
            lines.append(' '.join(row))
        return '\n'.join(lines)


    def spawn_cell(self):
        """出生地 = 「营地」那一格（跟真机一样从地块名认；认不出就退回第一个已揭示格）"""
        for i in range(NCELL):
            bi = self.board[i]
            if bi < 0:
                continue
            b = self.blocks[bi]
            if not b.gone and '营地' in (b.name or ''):
                return rc_of(i)
        vis = self.visible()
        return vis[0] if vis else (1, 1)


# ---------------- 策略层（把 explore_loop 的规则搬进来，作为基线） ----------------
class BaselinePolicy:
    """探索循环当前策略的等价实现（用于离线评估）"""

    name = 'baseline：目标=标记∪商人宝库 / 直线开路 / 严格交替'

    def __init__(self, max_click=60):
        self.max_click = max_click
        self.black = set()

    @staticmethod
    def _line(a, b):
        """Bresenham 直线取格（跟 explore_loop.line_cells 同一套）"""
        (r0, c0), (r1, c1) = a, b
        dr, dc = abs(r1 - r0), abs(c1 - c0)
        sr = 1 if r1 >= r0 else -1
        sc = 1 if c1 >= c0 else -1
        err = dr - dc
        r, c = r0, c0
        out = []
        for _ in range(dr + dc + 3):
            out.append((r, c))
            if (r, c) == (r1, c1):
                break
            e2 = 2 * err
            if e2 > -dc:
                err -= dc
                r += sr
            if e2 < dr:
                err += dr
                c += sc
        return out

    def run(self, sim, spawn=None, verbose=False, cost_first=False):
        """cost_first=True：直线上的开路格**按体力成本排序**（便宜优先），同成本按离目标近

        ⭐ 2026-09-25 用离线最优解当标尺验证：基线只比理论最优多花 ~13-32% 体力，
          而两次"重写"（纯贪心 / 直线成本重写）都明显更差 ✗ ⇒ 骨架保留，只加这一条纪律。
        """
        spawn = spawn or sim.spawn_cell()
        while sim.clicks < self.max_click and not sim.done():
            vis = [p for p in sim.visible() if p not in self.black]
            tgs = sim.targets()
            if not tgs:
                break
            # ① 目标自己能点 → 直接点（商人/宝库顺手买掉；战斗格打完消耗）
            for t in tgs:
                if t in vis:
                    kind, info = sim.click(t)
                    if kind == 'panel':
                        sim.resolve_panel(t, do_buy=True, do_fight=True)
                    break
            else:
                # ② 目标点不动（未揭示）→ 沿「出生地→目标」直线开路
                road = []
                for t in tgs:
                    for p in self._line(spawn, t):
                        if p in vis and p not in road and p != t:
                            road.append(p)
                # ③ 走廊兜底（|d(出生地,格)+d(格,目标)-d(出生地,目标)| ≤ 2，跟真机一致）
                if not road:
                    for t in tgs:
                        d_st = abs(spawn[0] - t[0]) + abs(spawn[1] - t[1])
                        near = sorted(
                            (p for p in vis if p not in road),
                            key=lambda p: (abs(abs(p[0] - spawn[0]) + abs(p[1] - spawn[1])
                                               + abs(p[0] - t[0]) + abs(p[1] - t[1]) - d_st) > 2,
                                           abs(p[0] - t[0]) + abs(p[1] - t[1])))
                        if near:
                            road.append(near[0])
                pick = road[0] if road else (vis[0] if vis else None)
                if cost_first and road:
                    # ⭐ 便宜优先：1 格空地(1 体) 永远排在大块内容格(4~8 体) 前面
                    def _cost(p):
                        bi = sim.board[(p[0] - 1) * COLS + (p[1] - 1)]
                        return sim.block_cost(sim.blocks[bi]) if bi >= 0 else 99
                    road = sorted(road, key=_cost)
                    pick = road[0]
                if pick is None:
                    break
                kind, info = sim.click(pick)
                if kind == 'noop':
                    self.black.add(pick)          # 点不动（雾/空）→ 本地拉黑，别再选它
                elif kind == 'panel':
                    # ⚠ 非目标面板：
                    #   · 商人/宝库 → 买掉并消耗 ✓
                    #   · 带战斗标记 → 打完消耗 ✓
                    #   · **其他内容格（宝箱/海螺/巨大沙堡/椰树…）→ 点了会消耗掉、并连锁揭示** ✓
                    #     （真机就是这么开路的；只有「营地」点了不消耗 ⇒ 必须拉黑，否则死循环）
                    b = info
                    if b.is_buy:
                        sim.resolve_panel(pick, do_buy=True, do_fight=False)
                    elif b.mark:
                        sim.resolve_panel(pick, do_buy=False, do_fight=True)
                    elif '营地' in (b.name or ''):
                        self.black.add(pick)
                    else:
                        sim.resolve_panel(pick, do_buy=False, do_fight=True)
        return sim.stats()


# ---------------- 从真实截图采样建盘 ----------------
def sim_from_shot(path, spots_mod, limits=None):
    """用我们的分类器把一张真实截图变成模拟器棋盘（真实布局 ✓）"""
    from spots import imread
    img = imread(path)
    if img is None:
        return None
    st = None
    for code in ('S00003', 'S00002', 'S00001'):
        try:
            st = spots_mod.Board(code).state(img)
            if st:
                break
        except Exception:       # noqa: BLE001
            st = None
    if not st:
        return None
    cells = {}
    for (r, c), v in st.items():
        if v.get('anchor') != (r, c):
            continue
        cells[(r, c)] = {'sid': v.get('sid'), 'name': v.get('name'),
                         'revealed': bool(v.get('revealed')),
                         'marks': list(v.get('marks') or [])}
    # ⭐ 标记（首领/红装/点赞/幸运草）是**另一个模板匹配器**扫出来的，不在分类器输出里 —— 必须合并
    # ⭐ v1.45：改走定点窗口版（旧版全图 105 次匹配 ≈ 10s，这里只是离线建盘，但没必要白等）
    try:
        import marks as marks_mod
        for (r, c), mv in (marks_mod.scan_board_fast(img, thr=0.85) or {}).items():
            if (r, c) in cells:
                got = list(cells[(r, c)].get('marks') or [])
                for m in (mv.get('marks') or []):
                    if m not in got:
                        got.append(m)
                cells[(r, c)]['marks'] = got
    except Exception:       # noqa: BLE001
        pass
    if len(cells) < 12:
        return None
    return MapSim.from_observation(cells, spots_mod.spot_rows())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', help='用这张截图建盘并跑一遍基线策略')
    ap.add_argument('--mem', help='从游戏内存窗口 .bin 建盘（真实存档棋盘）')
    ap.add_argument('--bench', type=int, default=0, help='从 runs/ 采样 N 张建盘跑基线策略')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    import spots as spots_mod

    if a.mem:
        sim = MapSim.from_memory_dump(a.mem, spots_mod.spot_rows())
        if sim is None:
            print('这个 dump 里没有普通棋盘（可能只有传送门那种）')
            return
        print('=== 从存档内存建盘：%s ===' % os.path.basename(a.mem))
        print(sim.render())
        print('出生地:', sim.spawn_cell(), '（存档里没有营地名 ⇒ 退回第一个已揭示格）')
        print('可点格:', sim.visible())
        print('目标:', sim.targets(), ' 未揭示带标记:', sim.fogged_marks())
        st = BaselinePolicy().run(sim)
        print('基线策略跑完:', st)
        print('前 15 步:', sim.log[:15])
        return

    if a.selftest:
        # 自检：一块空地点击 → 只吃连通的那一片；未揭示格点不动
        spots = {'草地': {'SpecialSpot': 0, 'SpotSize': 1, 'sid': 'P'},
                 '宝箱': {'SpecialSpot': 3, 'SpotSize': 1, 'sid': 'C'},
                 '首领': {'SpecialSpot': 5, 'SpotSize': 1, 'sid': 'B'}}
        cells = {}
        for r in range(1, ROWS + 1):
            for c in range(1, COLS + 1):
                if (r, c) == (1, 1):
                    cells[(r, c)] = {'sid': 'P', 'name': '草地', 'revealed': True}
                elif (r, c) == (1, 2):
                    cells[(r, c)] = {'sid': 'C', 'name': '宝箱', 'revealed': True}
                elif (r, c) == (3, 3):
                    cells[(r, c)] = {'sid': 'B', 'name': '营地', 'revealed': True,
                                     'marks': ['boss']}
                else:
                    cells[(r, c)] = {'sid': 'P', 'name': '草地', 'revealed': False}
        sim = MapSim.from_observation(cells, spots)
        print('自检棋盘：')
        print(sim.render())
        print('可点格:', sim.visible())
        print('未揭示但带标记:', sim.fogged_marks())
        kind, info = sim.click((1, 1))
        print('点(1,1) →', kind, info, '（应当只吃连通空地）')
        kind, info = sim.click((5, 7))
        print('点未揭示的(5,7) →', kind, info, '（应当是 fogged 点不动）')
        print('点完可点格:', sim.visible())
        return

    if a.sample:
        sim = sim_from_shot(a.sample, spots_mod)
        if sim is None:
            print('建盘失败（截图里可用格子太少）')
            return
        print('=== 从 %s 建盘 ===' % os.path.basename(a.sample))
        print(sim.render())
        print('目标:', sim.targets())
        print('点不动的标记:', sim.fogged_marks())
        pol = BaselinePolicy()
        st = pol.run(sim)
        print('基线策略跑完:', st)
        return

    if a.bench:
        base = _MAPBOT_ROOT
        # ⚠ 要用「开局那几轮」的截图（棋盘还满着）；中途的截图大量格已被消耗，统计没意义
        files = []
        for pat in ('runs/**/m*_r000.png', 'runs/**/m*_r001.png', 'runs/**/m*_r002.png'):
            files += glob.glob(os.path.join(base, pat), recursive=True)
        random.seed(7)
        random.shuffle(files)
        rows, ok = [], 0
        for f in files:
            if ok >= a.bench:
                break
            sim = sim_from_shot(f, spots_mod)
            if sim is None:
                continue
            ok += 1
            before = sim.stats()
            st = BaselinePolicy().run(sim)
            rel = os.path.relpath(f, base).replace('\\', '/')
            rows.append((rel, before['left_cells'], before['left_targets'],
                         st['clicks'], st['left_targets']))
        if not rows:
            print('没采到可用棋盘')
            return
        import statistics
        print('采样 %d 局（基线策略）：' % len(rows))
        print('  %-30s %6s %6s %7s %8s' % ('截图', '剩余格', '目标数', '点击数', '剩余目标'))
        for r in rows[:20]:
            print('  %-30s %6d %6d %7d %8d' % r)
        clicks = [r[3] for r in rows]
        left = [r[4] for r in rows]
        tgt = [r[2] for r in rows]
        witht = [r for r in rows if r[2] > 0]
        print('  总样本 %d；其中「有目标」的 %d 局' % (len(rows), len(witht)))
        if witht:
            print('  有目标局：平均点击 %.1f（中位 %.1f，最多 %d）；未清完 %d/%d'
                  % (statistics.mean([r[3] for r in witht]),
                     statistics.median([r[3] for r in witht]),
                     max(r[3] for r in witht),
                     sum(1 for r in witht if r[4] > 0), len(witht)))
        print('  全部局：平均点击 %.1f；平均目标数 %.1f；未清完目标的局数 %d/%d'
              % (statistics.mean(clicks), statistics.mean(tgt),
                 sum(1 for x in left if x > 0), len(rows)))


if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
