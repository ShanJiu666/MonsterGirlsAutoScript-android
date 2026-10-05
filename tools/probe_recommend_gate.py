# -*- coding: utf-8 -*-
"""v1.63b 行为验证：幸运草 <8 ⇒ **本图剔掉"纯大拇指"目标**（用户口径）

用户原话（2026-10-05）：
  「**而且我发现幸运草低于8还是摇色子，改成低于8这张图的大拇指目标都拉黑不去打**」

## 判据（真值来自**用户口径**，不是被测代码）
  · 草 `< 8` ⇒ **纯 recommend 格**必须被剔 ✗
  · 草 `< 8` ⇒ **带 boss / clover / redEquip 的格必须保留** ✓
    （那格另有价值，不能因为顺带带了个大拇指就整格丢掉）
  · 草 `≥ 8` ⇒ **一律不剔**（照常打）
  · 草读不到（None）⇒ **一律不剔**（fail-open：宁可白打一格，
    也别因一次 OCR 失败就整图漏掉所有大拇指 ✓）

## 为什么能离线测
剔选逻辑是**纯函数式的**（对 `marked` + `mk` 做筛选）⇒
本脚本用**真机帧真值**（`r_133809_0.png`：`(1,6)=recommend`、`(4,2)=boss`）
＋ 合成盘（一格多标记）覆盖全部分支 ✓

用法：python android_autoexplore\\tools\\probe_recommend_gate.py
"""
import os
import sys

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

import types                                 # noqa: E402


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

import explore_loop as EL                   # noqa: E402


def apply_gate(marked_cells, mk, clover):
    """**照抄 `one_round` 里那段 v1.63b 的逻辑**（用于离线验判据，不改源码 ✓）

    `marked_cells`：[(r,c)…]（相当于 `marked` 的格坐标视角）
    `mk`：{格: {'marks': [...]}}（`scan_board_fast` 的真实格式 ✓）
    返回 (保留的格, 剔掉的格)
    """
    if clover is None or int(clover) >= EL.CLOVER_MIN_REROLL:
        return list(marked_cells), []
    kept, dropped = [], []
    for rc in marked_cells:
        vv = mk.get(rc) or {}
        mks = list(vv.get('marks') or []) if isinstance(vv, dict) else list(vv or [])
        if mks and all(m == 'recommend' for m in mks):
            dropped.append(rc)
        else:
            kept.append(rc)
    return kept, dropped


def main():
    fails = []
    # 真机帧真值（`r_133809_0.png`：1,6=recommend ｜ 4,2=boss）
    MK_REAL = {(1, 6): {'marks': ['recommend']}, (4, 2): {'marks': ['boss']}}
    # 合成：一格多标记（大拇指 + 首领）⇒ **必须保留**
    MK_MULTI = {(2, 2): {'marks': ['recommend', 'boss']},
                (3, 3): {'marks': ['recommend']},
                (4, 4): {'marks': ['clover']}}
    print('CLOVER_MIN_REROLL = %s' % EL.CLOVER_MIN_REROLL)
    print()
    print('=== 真机帧口径（1,6=recommend ｜ 4,2=boss）===')
    print('%-8s %-30s %-24s %s' % ('草', '保留', '剔掉', '判定'))
    for clv, want_keep, want_drop in (
            (1, [(4, 2)], [(1, 6)]),
            (7, [(4, 2)], [(1, 6)]),
            (8, [(1, 6), (4, 2)], []),
            (12, [(1, 6), (4, 2)], []),
            (None, [(1, 6), (4, 2)], []),       # 读不到 ⇒ 不剔 ✓
    ):
        kept, drop = apply_gate([(1, 6), (4, 2)], MK_REAL, clv)
        ok = (sorted(kept) == sorted(want_keep)) and (sorted(drop) == sorted(want_drop))
        if not ok:
            fails.append(('real', clv, kept, drop))
        print('%-8s %-30s %-24s %s' % (clv, kept, drop, '✓' if ok else '**✗**'))
    print()
    print('=== ⚠ 一格多标记：**带 boss 的就算有大拇指也必须保留** ===')
    print('%-8s %-30s %-24s %s' % ('草', '保留', '剔掉', '判定'))
    for clv, want_keep, want_drop in (
            (5, [(2, 2), (4, 4)], [(3, 3)]),
            (None, [(2, 2), (3, 3), (4, 4)], []),
    ):
        kept, drop = apply_gate([(2, 2), (3, 3), (4, 4)], MK_MULTI, clv)
        ok = (sorted(kept) == sorted(want_keep)) and (sorted(drop) == sorted(want_drop))
        if not ok:
            fails.append(('multi', clv, kept, drop))
        print('%-8s %-30s %-24s %s' % (clv, kept, drop, '✓' if ok else '**✗**'))
    print()
    print('=' * 78)
    if fails:
        print('❌ %d 项不符：%s' % (len(fails), fails))
        return 1
    print('✅ 全部通过：草 <8 ⇒ 只剔**纯大拇指**格；')
    print('   带 boss/clover 的格**照旧保留**；草够或读不到 ⇒ 一律不剔 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
