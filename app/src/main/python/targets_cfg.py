# -*- coding: utf-8 -*-
"""targets_cfg.py · 「目标方块类型」白名单（用户 2026-09-28 要求）

用户原话：
    「能做到勾选某一种类型的方块，后续就会专门去拿那个方块，不勾选就不拿么。
     比如取消勾选商人，规划里就不规划商人。加上要打一种新方块，后续规划就会去打」

设计要点
--------
· **配置文件**：`runs[/<tag>]/target_types.json`
      {"version": 1, "types": {"★标记格": true, "旅行商人": true, "宝箱": false, ...},
       "updated": "2026-09-28 23:20"}
· **key = 地块名**（真实地块表 `Area_Spot.Name`，跨地图通用 ✓）＋ 两个**伪类型**：
      `★标记格`      = 首领(boss)/红装(redEquip)/大拇指(recommend)/幸运草(clover)/战斗兜底(battle)
      `★紫橙探索格`  = 地块 ID 后缀 ∈ {221,321,331}（小助手官方分类 ✓）
· **默认值 = 现行口径**（保证不勾也能跑出老行为 ✓）：
      ★标记格 ✓ / 旅行商人 ✓ / 黄金宝库 ✓ / ★紫橙探索格 ✓，其余一律 ✗
· ⭐ **新方块**（地块表里新增、用户没配过的名字）默认 **✗（不拿）**；
  在 GUI 里勾上 ⇒ 立刻进规划 ✓（这就是"加上要打一种新方块，后续规划就会去打"）
· ⚠ 未知/未配 key 一律当 **False**（宁可不拿，也不乱点 ✗）

谁在用
------
· `explore_loop.py`：① 组 `marked`（目标像素列表）时逐格问 `is_target()` ✓
                     ② 喂给 soluer 的 cells 带 `target=True/False` ⇒ `Block.want` ⇒ `Problem.targets` ✓
                     ③ 弹窗处理：勾上的名字动态并入「要点/要关闭」名单 ✓
· `bot_gui.py`：勾选框面板（按类别分组）+ 落盘 ✓
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

import json
import os
import time

HERE = _MAPBOT_ROOT

PSEUDO_MARK = '★标记格'
PSEUDO_EXPLORE = '★紫橙探索格'
# ⭐ v2.22 用户口径（2026-10-26）：
#   「特殊方块默认勾选：旅行商人、黄金宝库、限时礼包、预言石碑」
#   ⇒ 拉黑类里勾商人/宝库（宝箱怪与祭坛默认拉黑）；
#     可点类里勾限时礼包/预言石碑（勇者之墓默认不专门拿）。
DEFAULT_ON = (PSEUDO_MARK, '旅行商人', '黄金宝库', '限时礼包', '预言石碑',
              PSEUDO_EXPLORE)

# ⭐⭐⭐ 2026-10-01 用户口径（**最终版**）：
#   「这个功能之后要做成**勾选就主动去处理，不勾选就拉黑**，能自由选择」
#   ⇒ 不再用硬编码黑名单 ✗，而是**由勾选配置推导**：
#        · 地块名在 `types` 里 **勾了(True)**  ⇒ 主动去处理它（进目标 ✓）
#        · 地块名在 `types` 里 **没勾(False/缺)** ⇒ **拉黑**：不进目标、
#          也不作为"内容格"排进点序（免得为了连通去点它、白弹一次面板 ✗）
#   · `SPECIAL_NAMES` = 会被 `catalog()` 列进「商店 / 大奖励」组的那些名字
#     （商人/宝库/宝箱怪/勇者之墓/祭坛/礼包/石碑…）⇒ 只有**这一组**享受
#     "不勾 = 拉黑"语义；普通拾取格/建筑不勾只是"不去拿"，仍可当路 ✓
SPECIAL_NAMES = {
    '旅行商人', '黄金宝库', '金属宝箱怪', '机巧宝箱怪',
    '勇者之墓', '传承祭坛', '限时礼包', '预言石碑',
}

# ⭐⭐⭐⭐⭐ v1.78【**两类特殊方块，两种「不勾」语义** —— 从 PC 移植（PC 2026-10-09 用户口径）】
#   用户原话：「**把窗口的其他特殊方块解锁吧，现在勾选是设定为会当成目标去拿，
#     不勾选就不专门去拿，但是如果挡了最优的路，也会去点
#     （不同于之前的不勾选拉黑了）**」＋（问要不要也用在商人/宝库上）答：
#     「**只对那 6 个生效**」✓ ＋「**俩宝箱怪和祭坛也和商人宝库一样吧**」✓
#
#   | 类别     | 成员                                                  | 不勾的含义                |
#   |----------|-------------------------------------------------------|---------------------------|
#   | 拉黑类   | 旅行商人 / 黄金宝库 / 金属宝箱怪 / 机巧宝箱怪 / 传承祭坛 | **拉黑**：不点、也不借道 ✗ |
#   | 可点类   | 勇者之墓 / 限时礼包 / 预言石碑                          | **不专门拿，挡路会点** ✓  |
#
#   ⚠ 为什么宝箱怪/祭坛归**拉黑类**（和商人/宝库同类）：它们都属「**要点面板做取舍**」——
#     · 金属/机巧宝箱怪 ⇒ 要**花幸运草**买装备（mimic_flow）
#     · 传承祭坛       ⇒ 要**花金币**买传承装备
#     ⇒ 没勾就是「**不想为它花资源**」⇒ 当踏脚石点一下会**白弹面板**（还得关掉）✗
#   ★ 而 勇者之墓/限时礼包/预言石碑 是**免费**的（点开就白拿 / 只做选择，不花资源）
#     ⇒ 挡路时顺手点一下**有收益**、没损失 ⇒ 归「可点类」✓
#
#   ⚠ 用户 2026-10-03 确认过商人/宝库的口径：「取消勾选会让他们进入拉黑状态吗？」⇒ **会** ✓
#   ⛔ 注意与旧口径的区别：旧口径把 SPECIAL_NAMES **整组**都当拉黑类 ✗
#     ⇒ 勇者之墓/限时礼包/预言石碑**不勾就完全不能踩** ⇒ 白白多绕路 ✗
BLOCK_NAMES = {
    '旅行商人', '黄金宝库',                       # 花金币（老口径 ✓）
    '金属宝箱怪', '机巧宝箱怪', '传承祭坛',        # ⭐ 2026-10-09 新增（也要花资源 ✓）
}
PICK_IF_BLOCKING = SPECIAL_NAMES - BLOCK_NAMES     # = 勇者之墓/限时礼包/预言石碑（免费 ✓）

# ⭐⭐⭐⭐⭐ v1.78【**界面显示顺序必须固定**（PC 用户报：「为什么特殊方块的勾选位置一直在变？」）】
#   ---- 病 ----
#     PC 原来写 _order = list(TC.BLOCK_NAMES) + sorted(TC.SPECIAL_NAMES - TC.BLOCK_NAMES)
#       ↑ BLOCK_NAMES 是 **set** ⇒ list(set) 的顺序**不保证** ✗✗
#     Python 的字符串哈希**每个进程都随机**（PEP 456 安全特性）
#     ⇒ **每开一次窗口，这几个勾选框的顺序都不一样** ✗
#   ---- 后果（**不只是难看**）----
#     用户**记不住位置** ⇒ 极易**点错框**（想点「金属宝箱怪」点到「机巧宝箱怪」）
#     ⇒ 这正是「勾了宝箱怪却没买」的**合理来源之一** ✓
#     （两个名字只差两个字，位置又天天变 ⇒ 看串很正常 ✗）
#   ---- 修法 ----
#     加一个**显式有序**元组 DISPLAY_ORDER 给界面用；
#     ⚠ **集合本身保留**（BLOCK_NAMES / PICK_IF_BLOCKING 都是成员测试用，
#       改动它们会波及 is_blocked 等一堆代码 ⇒ 不动 ✓）
#     顺序口径：**先拉黑类**（花资源的，用户最常改）、再可点类；
#       类内按「用户关心的程度」排（宝箱怪靠前 —— PC 用户报的就是它 ✓）
DISPLAY_ORDER = (
    # ── 拉黑类（勾了才会去买；不勾 = 完全拉黑）──
    '旅行商人', '金属宝箱怪', '机巧宝箱怪', '黄金宝库', '传承祭坛',
    # ── 可点类（勾了 = 专门去拿；不勾 = 挡路也会点）──
    '勇者之墓', '限时礼包', '预言石碑',
)
# ⭐⭐⭐ v1.46 删两个**数据表里根本不存在**的名字（学 PC 端 `1e9afce` + `b5f08a6`）：
#   · `献祭宝箱怪` —— 查 `Area_Spot` 全部 482 行：它虽在 15 个区域有条目，
#     但 **`MaxNum = 0`** ⇒ **游戏根本不会生成它** ✗（对比：金属宝箱怪 ≥11/MaxNum=1、
#     机巧宝箱怪 ≥21/MaxNum=1 ⇒ 这两个才会出 ✓）⇒ 用户"从来没见过"是正常的 ✓
#   · `预言石板` —— **数据表里没这个名字**，真名是 **`预言石碑`** ✓（已有，重复项）
#   ⇒ 清单里的幽灵项会让勾选排多出两个永远勾不动的框 ✗ ⇒ 删掉 ✓


# ⭐⭐⭐ v1.46【拉黑要带**置信度门槛**】—— 学 PC 端 `is_blocked_cell`（真机事故）
#   PC 端事故：boss 格被当「用户拉黑」永久剔除 ⇒ 规划里根本没有它 ⇒
#     **14 点体力的首领不打了**（用户原话报「紫探索块且有大拇指直接打了就关闭」）。
#   根因：老口径 `is_blocked(name)` **只判名字**、不看认得准不准 ⇒
#     同一帧里 5,1/5,2/5,5 都是 **0.30~0.32 的乱猜**，照样被当成"用户拉黑了它" ✗✗
#   ⇒ **低置信度的分类结果没有资格代表「用户拉黑了它」** —— 拉黑是用户的明确意图，
#     不该由一个 0.3 分的猜测来代替 ✓
#   门槛 0.70 的依据（PC 端实测分布）：真识别 **≥0.994** 与乱猜 **≤0.397** 之间几乎是空的
#     （35 格里：28 格 ≥0.9、4 格 ≤0.4、**中间 0 格**）⇒ 0.70 离两侧都远，稳 ✓
BLOCKED_SCORE_MIN = 0.70


def is_blocked(name, cfg=None):
    """这个名字是不是**拉黑**地块 ⇒ 用户口径：**拉黑类特殊方块，没勾选就拉黑** ✓

    ⭐⭐⭐⭐⭐ v1.78 **语义变更（从 PC 抄的口径，别改回去）** —— 用户原话：
      「**把窗口的其他特殊方块解锁吧，现在勾选是设定为会当成目标去拿，
        不勾选就不专门去拿，但是如果挡了最优的路，也会去点**」
      ＋「**只对那 6 个生效**」＋「**俩宝箱怪和祭坛也和商人宝库一样吧**」
    ⇒ 只有 BLOCK_NAMES（旅行商人/黄金宝库/金属宝箱怪/机巧宝箱怪/传承祭坛）
      享受「不勾 = 拉黑」；其余（勇者之墓/限时礼包/预言石碑）不勾只是「不专门拿」，
      **仍然可当路/当踏脚石** ✓（它们是免费的 ⇒ 挡路时顺手点一下有收益 ✓）
    ⚠ 勾上了 ⇒ 立即变成主动处理，无需改代码 ✓（用户要求「能自由选择」✓）
    ⚠⚠ **本函数只看名字、不看置信度** ⇒ 有 score 时请用 is_blocked_cell() ✓
    """
    n = str(name or '')
    if not n:
        return False
    for k in BLOCK_NAMES:                   # ⭐ 只有这一组享受「不勾 = 拉黑」
        if k in n:
            return not enabled(k, cfg)      # 没勾 ⇒ 拉黑 ✓ ／ 勾了 ⇒ 主动处理 ✓
    return False                            # 其余特殊方块：不勾也**不是拉黑** ✓


def is_blocked_cell(cell, cfg=None):
    """这一格是不是**真的**被拉黑（比 `is_blocked` 多一道置信度门槛）★ v1.46

    `cell` = `{'name':…, 'score':…}`（`spots.Board.state()` 的单格产物 ✓）
    ⚠ 老口径 `is_blocked(name)` **只判名字**、不看认得准不准 ⇒ 低分乱猜也会中招 ✗
    ⚠ **不认得准 ⇒ 一律不拉黑**（宁可多点一格，也别把 boss 静默丢掉 ✓）
    """
    name = (cell or {}).get('name')
    if not is_blocked(name, cfg):
        return False
    try:
        sc = float((cell or {}).get('score') or 0.0)
    except (TypeError, ValueError):
        sc = 0.0
    return sc >= BLOCKED_SCORE_MIN

# 算作「标记格」的标记名（与 marks.py 的口径一致；battle = 认不出但带标记的兜底 ✓）
MARK_KEYS = ('boss', 'redEquip', 'recommend', 'clover', 'battle')

# 这些名字**不进清单**（空地 = 揭格用的，不是"要拿的方块"）
PLAIN_NAMES = ('草地', '沙地', '雪地', '岩地', '海底')

_CACHE = {'cfg': None, 'path': None}


def cfg_path(tag=None, base=None):
    """配置文件路径（多开隔离：runs/<tag>/target_types.json ✓）"""
    root = base or _MAPBOT_RUNS
    return os.path.join(root, tag, 'target_types.json') if tag \
        else os.path.join(root, 'target_types.json')


def load(path=None, tag=None, base=None):
    """读配置（读不到 ⇒ 默认值，并把文件**写出来**方便用户直接改 ✓）"""
    p = path or cfg_path(tag, base)
    d = {'version': 1, 'types': {}}
    try:
        with open(p, encoding='utf-8') as f:
            raw = json.load(f)
        if isinstance(raw, dict) and isinstance(raw.get('types'), dict):
            d = {'version': 1, 'types': {str(k): bool(v) for k, v in raw['types'].items()}}
        elif isinstance(raw, dict):                     # 兼容"直接写 {key: bool}"
            d = {'version': 1, 'types': {str(k): bool(v) for k, v in raw.items()}}
    except Exception:                                   # noqa: BLE001
        d = {'version': 1, 'types': {}}
    for k in DEFAULT_ON:                                # 默认口径兜底（新装/删过都能跑）
        d['types'].setdefault(k, True)
    _CACHE['cfg'], _CACHE['path'] = d, p
    try:                                                # ⭐ mtime 记下来（供 current 判陈旧 ✓）
        _CACHE['mtime'] = os.path.getmtime(p)
    except Exception:                                   # noqa: BLE001
        _CACHE['mtime'] = None
    if not os.path.exists(p):
        save(d, p)
    return d


def save(cfg, path=None):
    p = path or _CACHE.get('path') or cfg_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        cfg = dict(cfg or {})
        cfg['version'] = 1
        cfg['updated'] = time.strftime('%Y-%m-%d %H:%M')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        _CACHE['cfg'], _CACHE['path'] = cfg, p
        return True
    except Exception:                                   # noqa: BLE001
        return False


def current():
    """当前配置 —— ⭐⭐⭐ v1.46 **mtime 感知**（学 PC 端 `0578bb6`，用户口径）

    PC 端用户口径（原话）：「**之后取消拉黑也能随时改计划吧？**」✓

    ⚠ 原来的坑：`_CACHE` **只读一次、没有 mtime 校验** ✗ ⇒
      界面上改了「特殊方块」勾选 ⇒ **跑着的循环根本不知道** ✗
      ⇒ 必须**重启循环**才生效 ✗✗（用户以为随时能改 ✗）
    ⇒ 现在每次询问都先比一下文件 mtime ✓（一次 stat，微秒级 ⇒ 可忽略 ✓）：
        文件被改过 ⇒ 立即重读 ✓ ⇒ **下一轮规划就用新口径** ✓
    """
    try:
        p = _CACHE.get('path') or cfg_path()
        _mt = os.path.getmtime(p)
        if _CACHE.get('mtime') != _mt:
            return load(p)                  # 文件变了 ⇒ 重读（并刷新 mtime ✓）
    except Exception:                       # noqa: BLE001
        pass
    return _CACHE.get('cfg') or load()


def enabled(key, cfg=None):
    """某个 key（地块名 / 伪类型）是否勾选 —— 未配过 = False ✓"""
    d = cfg or current()
    try:
        return bool((d.get('types') or {}).get(str(key)))
    except Exception:                                   # noqa: BLE001
        return False


def suffix_of(sid):
    s = str(sid or '')
    return s.split('_')[-1] if '_' in s else s


def is_explore_tile(sid):
    """紫/橙探索格（ID 后缀 221/321/331）—— 小助手官方分类 ✓"""
    try:
        import spots as _sp
        return suffix_of(sid) in tuple(_sp.EXPLORE_SUFFIX)
    except Exception:                                   # noqa: BLE001
        return suffix_of(sid) in ('221', '321', '331')


#: ⭐⭐⭐⭐ v1.78 **「靠名字当目标」的最低匹配置信度** —— 从 PC 移植（治「先打巨大沙堡」✗）
#:   ---- PC 的病（真机铁证）----
#:     5,6 被认成 S00003_014 限时礼包，**score 只有 0.441**
#:       （候选挤在一起：0.441 / 0.392 / 0.38 ⇒ 分类器**自己都不确定** ✗）
#:     而「限时礼包」在配置里是**勾选**的 ⇒ is_target 判它 True ⇒
#:     求解器**当然要去拿它** ⇒ 排进计划 ⇒ 点它 ⇒ 实际打的是**整座巨大沙堡**
#:     （S00003_211，SpotSize=4 / EventNum=4-4 ⇒ 4 场战斗）✗✗
#:   ---- 为什么门槛**只能**加在「名字」那一支 ----
#:     ⚠⚠ PC 第一版想给 is_target **全体**加门槛 ⇒ 数据一量发现**会废掉探索格** ✗
#:       实测（全量 loop_log）：目标格 152 个，低分(<0.85) 43 个 —— 但**其中 43 个
#:       几乎全是探索格** ✗ 探索格 score 实测 **0.39~0.73**（靠 **sid 后缀** 221/321/331
#:       判定，**本来就不靠名字** ⇒ 低分是正常的 ✓）
#:   ---- 口径 ----
#:     · score >= 0.85 ⇒ 名字可信 ⇒ 照旧按名字当目标 ✓
#:     · score < 0.85 ⇒ **名字不可信** ⇒ 不因它当目标
#:       （该格仍可作**踏脚石/开路步**，只是不再「专门去拿」✓）
#:     ⚠ **fail-open**：score 传 None / 缺失 ⇒ **不拦**（宁可多拿，别漏拿 ✓）
#:       —— 老调用点不传 score ⇒ 行为与修前**完全一致** ✓
NAME_SCORE_MIN = 0.85

def is_target(name, sid, marks=None, cfg=None, score=None):
    """⭐ 该格是不是「当前配置下要拿的目标」

    ⚠ 2026-10-01：**拉黑地块一律不是目标**（哪怕它在配置里被勾上了 ✓ ——
    用户口径「把有弹窗的地块拉黑，暂时不要点」，黑名单优先级最高 ✓）
    """
    d = cfg or current()
    # ⚠⚠ 2026-10-01 修**静默丢配置**：`is_blocked(name, cfg)` 本来支持 cfg 形参，
    #   这里却只传 name ⇒ 它内部回落到 `enabled(k, None)` → `current()` → **模块级 _CACHE**
    #   ⇒ 显式传入的 `cfg`（多开/多账号隔离、测试回放、GUI 预览）在这条判据上**被忽略**。
    #   实测：缓存里「旅行商人」=OFF、显式 cfg 里 =ON 时，`is_target(...)` 仍返回 False
    #        （而 `enabled(name, cfg)` 本身是对的）。
    # ⇒ 传下去 d，让 is_blocked 与本函数其余判据用**同一份**配置 ✓
    if is_blocked(name, d):
        return False
    if marks:
        for m in marks:
            if m in MARK_KEYS and enabled(PSEUDO_MARK, d):
                return True
    if is_explore_tile(sid) and enabled(PSEUDO_EXPLORE, d):
        return True
    if name and enabled(name, d):
        # ⭐⭐⭐ v1.78 **名字可信度门槛**（从 PC 移植；只挡「靠名字」这一支 ✓）
        #   ⚠ 门槛**绝不能**提到函数开头 —— 那会把探索格（score 0.39~0.73）全废掉 ✗
        #   ⚠ **fail-open**：score 是 None / 转不了 float ⇒ **不拦**（保守 ✓）
        if score is not None:
            try:
                if float(score) < NAME_SCORE_MIN:
                    return False
            except (TypeError, ValueError):
                pass
        return True
    return False


def enabled_names(cfg=None):
    """勾上的**地块名**（不含伪类型）—— 给弹窗处理用（点了要认得这个面板 ✓）"""
    d = cfg or current()
    return set(k for k, v in (d.get('types') or {}).items()
               if v and not k.startswith('★'))




# ⭐⭐⭐⭐⭐ v1.78【**每个特殊方块的说明**（界面悬停/说明卡用）—— 从 PC 移植】
#   ⚠ 文案里的 SP 号码与「面板叫什么」是**数据表 + 真机实测**得来的，别凭印象改：
#     SP=2 金属/机巧宝箱怪 ｜ SP=3 勇者之墓 ｜ SP=4 传承祭坛
#     SP=5 限时礼包 ｜ SP=7 预言石碑 ｜ SP=9 黄金宝库
DESC = {
    '旅行商人':
        '【旅行商人】SP=2\n'
        '· 面板叫「旅行商人」，卖 4 件商品，**用金币**买\n'
        '· 买完**地块不消失**（要靠脚本自己记「这格买过了」）\n'
        '· ⚠ 金币 < 50 万 ⇒ **自动拉黑**（不买、也不规划）',
    '黄金宝库':
        '【黄金宝库】SP=9\n'
        '· 面板叫「黄金宝库」，花金币**逐层解锁**（3 层），每层选 1 件奖励\n'
        '· 优先天赋果实 / 幸运草\n'
        '· ⚠ 金币 < 50 万 ⇒ **自动拉黑**（不买、也不规划）',
    '金属宝箱怪':
        '【金属宝箱怪】SP=2\n'
        '· 面板叫「金属宝箱怪」，卖 4 件（2 装备 + 2 符文），**用幸运草**买\n'
        '· 价格 = 1<<(品阶-1)：C=1 / B=2 / A=4 / **S=8**（不出 SS）\n'
        '· 脚本**只买 8 草的装备**（第 1 列；不刷、不买符文）\n'
        '· ⚠ 幸运草 < 8 ⇒ **不买**',
    '机巧宝箱怪':
        '【机巧宝箱怪】SP=2\n'
        '· 与金属宝箱怪同构，但给**传承装备**（Heritage=true）\n'
        '· ⚠ 面板**尚未真机实测**（金属的已实测）\n'
        '· ⚠ 幸运草 < 8 ⇒ **不买**',
    '传承祭坛':
        '【传承祭坛】SP=4\n'
        '· 花**金币**买传承装备（右下角价格 **== 30000 才买** ✓）\n'
        '· 用默认选中的第 1 件（不筛、不刷新）\n'
        '· ⚠ 与商人/宝库同类：不勾 = **完全拉黑**（不点、不借道）',
    '勇者之墓':
        '【勇者之墓】SP=3\n'
        '· 面板叫「英灵使者」，三选一（属性挑战），**零成本**（不花金币/体力）\n'
        '· 三行都点得动；脚本**优先选成功率 100%** 的那行\n'
        '· ⚠ **暗格点不动** ⇒ 要先揭开\n'
        '· ✅ 免费 ⇒ 不勾只是「不专门拿」，**挡路也会点**（有收益、无损失）',
    '限时礼包':
        '【限时礼包】SP=5\n'
        '· 面板叫「限时超值礼包」，3 档\n'
        '· 第 1 档「免费」= 红宝石×20（**脚本只点这个**）\n'
        '· 第 2 档要 6 幸运草、第 3 档用户说不点\n'
        '· ✅ 免费 ⇒ 不勾只是「不专门拿」，**挡路也会点**',
    '预言石碑':
        '【预言石碑】SP=7\n'
        '· 面板叫「预言石板」，**多选**（本次可选 N 个，OCR 读的那句）\n'
        '· 选择策略：①「掉宝」最优先 ②「幸运/和平·金属宝箱怪/元素」会**停脚本**\n'
        '  ③ 其余按品阶（品阶越高越优先）'
        '· 预言**下次开图才生效**\n'
        '· ✅ 免费（只做选择）⇒ 不勾只是「不专门拿」，**挡路也会点**',
}


def describe(key):
    """某个特殊方块的**说明文字**（界面用）—— 从 PC 移植

    ⚠ 兜底分支会**如实报类别**（拉黑类 / 可点类）—— 因为这两类的「不勾」语义不同，
      界面上必须让用户看得见，否则就是一整族「勾了没生效」的误解 ✗
    """
    k = str(key or '')
    if k in DESC:
        return DESC[k]
    d = current()
    on = bool(enabled(k, d))
    role = ('拉黑类（不勾 = 完全拉黑）' if k in BLOCK_NAMES
            else '可点类（不勾 = 不专门拿，挡路会点）')
    return '%s\n· 类别：%s\n· 当前：%s' % (k, role, '已勾选 ✓' if on else '未勾选')
# ---------------- GUI 清单（按类别分组） ----------------

def _shop_desc(nm, shop):
    """商店/大奖励某一项的说明文字 —— 优先用 DESC（PC 那份文案），否则退回格数

    ⚠ 用 DESC 而不是只写「N 格」：这几类的**「不勾」语义不同**（拉黑类 / 可点类），
      界面上必须让用户看得见，否则就是一整族「勾了没生效 / 不勾却被踩」的误解 ✗
    """
    if nm in DESC:
        return DESC[nm]
    role = "拉黑类" if nm in BLOCK_NAMES else ""
    szs = "/".join(str(x) for x in sorted(shop.get(nm) or []))
    return "%s（%s格）%s" % (nm, szs, ("· " + role) if role else "")

def catalog():
    """-> [ (组名, [ (key, 说明文字), ... ]), ... ]（顺序固定，方便勾选）

    分组依据（来自真实地块表）：
      · 商店/大奖励   = SpecialSpot ∈ {2,3,4,5,6,7,9}（商人/宝库/宝箱怪/勇者之墓/祭坛/礼包/石碑）
      · 可拾取产出格  = SpecialSpot ≥ 1 且 1 格（宝箱/海螺/木箱…点它弹面板拿东西）
      · 多格建筑      = SpecialSpot == 0 且 SpotSize > 1（椰树/游乐设施…点它开战/探索）
    """
    rows = {}
    try:
        import spots as _sp
        rows = _sp.spot_rows()
    except Exception:                                   # noqa: BLE001
        rows = {}
    shop, pick, big = {}, {}, {}
    for _sid, r in rows.items():
        nm = r.get('Name')
        if not nm or nm in PLAIN_NAMES or nm == '营地':
            continue
        sp = int(r.get('SpecialSpot') or 0)
        sz = int(r.get('SpotSize') or 1)
        if sp in (2, 3, 4, 5, 6, 7, 9):
            shop.setdefault(nm, set()).add(sz)
        elif sp == 1 and sz == 1:
            pick.setdefault(nm, set()).add(sz)
        elif sp == 0 and sz > 1:
            big.setdefault(nm, set()).add(sz)

    def fmt(d):
        return ['%s（%s格）' % (nm, '/'.join(str(x) for x in sorted(v)))
                for nm, v in sorted(d.items())]

    # ⭐⭐⭐⭐⭐ v1.78【「商店 / 大奖励」按 DISPLAY_ORDER 固定顺序 —— 从 PC 移植】
    #   ---- PC 的病（用户原话）：「**为什么特殊方块的勾选位置一直在变？**」----
    #     原来按字典序排 ⇒ 传承祭坛跑到最前、两个宝箱怪挨着黄金宝库 ⇒
    #     用户**记不住位置** ⇒ 想点「金属宝箱怪」却点到「机巧宝箱怪」
    #     （名字只差两个字）✗ ⇒ 这是「勾了宝箱怪却没买」的来源之一 ✓
    #   ---- 修法 ----
    #     ① DISPLAY_ORDER 里的**先按那个顺序**排（拉黑类在前、可点类在后 ✓）
    #     ② 不在 DISPLAY_ORDER 里的（数据表新增/冷门 SP）**按名字排在最后** ✓
    #        —— 绝不能因为漏登记就**丢掉**某个方块（那会让用户以为勾选项消失了 ✗）
    _shop_keys = ([k for k in DISPLAY_ORDER if k in shop]
                  + sorted(k for k in shop if k not in DISPLAY_ORDER))
    out = [('标记 / 探索类别（跨方块，不看名字）',
            [(PSEUDO_MARK, '首领 / 红装SS / 大拇指 / 幸运草 / 战斗兜底'),
             (PSEUDO_EXPLORE, '紫橙探索格（ID 后缀 221/321/331）')]),
           ('商店 / 大奖励', [(nm, _shop_desc(nm, shop)) for nm in _shop_keys]),
           ('可拾取产出格（点它弹面板拿东西）', [(nm, desc) for nm, desc in
                                              zip(sorted(pick), fmt(pick))]),
           ('多格建筑（点它开战/探索）', [(nm, desc) for nm, desc in
                                    zip(sorted(big), fmt(big))])]
    return out


def summary(cfg=None, maxlen=8):
    """一行摘要（日志/界面用）"""
    d = cfg or current()
    on = [k for k, v in (d.get('types') or {}).items() if v]
    offN = len([1 for k, v in (d.get('types') or {}).items() if not v])
    head = '、'.join(on[:maxlen]) + ('…' if len(on) > maxlen else '')
    return '目标方块 %d 种：%s（未勾 %d 种不拿）' % (len(on), head or '（空！什么都不拿）', offN)


if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    d = load()
    print('配置文件：%s' % _CACHE['path'])
    print(summary(d))
    for g, items in catalog():
        print('\n[%s]  (%d)' % (g, len(items)))
        for k, desc in items:
            print('   [%s] %-12s %s' % ('✓' if enabled(k, d) else ' ', k, desc))
