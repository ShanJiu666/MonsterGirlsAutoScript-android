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
DEFAULT_ON = (PSEUDO_MARK, '旅行商人', '黄金宝库', PSEUDO_EXPLORE)

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


def is_target(name, sid, marks=None, cfg=None):
    """⭐ 该格是不是「当前配置下要拿的目标」"""
    d = cfg or current()
    if marks:
        for m in marks:
            if m in MARK_KEYS and enabled(PSEUDO_MARK, d):
                return True
    if is_explore_tile(sid) and enabled(PSEUDO_EXPLORE, d):
        return True
    if name and enabled(name, d):
        return True
    return False


def enabled_names(cfg=None):
    """勾上的**地块名**（不含伪类型）—— 给弹窗处理用（点了要认得这个面板 ✓）"""
    d = cfg or current()
    return set(k for k, v in (d.get('types') or {}).items()
               if v and not k.startswith('★'))


# ---------------- GUI 清单（按类别分组） ----------------

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

    out = [('标记 / 探索类别（跨方块，不看名字）',
            [(PSEUDO_MARK, '首领 / 红装SS / 大拇指 / 幸运草 / 战斗兜底'),
             (PSEUDO_EXPLORE, '紫橙探索格（ID 后缀 221/321/331）')]),
           ('商店 / 大奖励', [(nm, desc) for nm, desc in
                              zip(sorted(shop), fmt(shop))]),
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
