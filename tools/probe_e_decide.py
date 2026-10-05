# -*- coding: utf-8 -*-
"""v1.62 决策留档：E 条（内容地块拦连锁，PC `9129a78`）**为什么被撤回**

## 结论（2026-10-05 定案）
**手机端不搬 E 条**。`mapsim` 里 `CONTENT_SCORE_MIN` / `Block.score` / `Block.weight`
/ `Block.floor_lit` **都已完整删除**，只在 `Block.plain` 留一段"别再试"的长注释。

## 两条实测证据（都在本目录，可复跑）
  ① `probe_e_effect.py` —— **直接照抄 PC（只看 `score ≥ 0.85`）会拦错 8/10 个**：
       矿洞 13:38 帧上被命中的 `5,4`/`5,7` 宝箱、`1,4` 蘑菇丛、`3,5`/`4,2` 矿箱堆、
       `4,7` 露天矿 —— 它们 `floor` 全是 **65~74（纯雾）**，真机点不动
       ⇒ 拦了它们 ⇒ **连锁全断**（比原问题更糟 ✗）
  ② 加**地板闸门**（只拦"地板判亮"的）之后 —— 判据对了，但
       **对 6 张真机帧零影响**：逐块比 `plain` ⇒ **0 个块改变**、规划逐字相同
       ⇒ 因为手机端"真亮的内容格"**早就被 `Block.plain` 里更早的分支拦掉了**
         （`2,1` 矿箱：三个条件全满足，可它 `plain` 早已是 False ✓）⇒ 纯冗余

## ⭐ 决定性反证：**雾格上的高分名字不可信**（真机日志铁证）
  模型给 `(4,2)` 的判读是 `{"name":"矿箱堆","sid":"S30001_101","score":0.933}`
  可真机点下去是 **`开打 · 首领格`（标记 `['boss']`）** —— **名字是错的** ✗✗
  ⇒ `score ≥ 0.9` **不代表雾格上的名字对**；而 PC 那边量纲不同
    （PC 的 `state()` 只对已揭示格给高分）⇒ 这条**不可跨端移植** ✓

## 本脚本现状
E 的代码已删 ⇒ 无法再"开/关对照"。保留文件是为了**记录复跑方式**：
想重做实验就先 `git show 9129a78` 把那条加回去，再跑 `probe_e_effect.py` 与
`probe_e_decide.py`（后者需同步改回引用 `MS.CONTENT_SCORE_MIN`）。
⚠ **别再把它当"待办改进项"** —— 已经证明在手机端无收益 ✓
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(PROJ, 'app', 'src', 'main', 'python'))


def main():
    print(__doc__)
    try:
        import mapsim as MS
        has = hasattr(MS, 'CONTENT_SCORE_MIN')
        print('当前 `mapsim.CONTENT_SCORE_MIN` 存在？ %s（应为 False ⇒ 已撤回 ✓）' % has)
        import io as _io
        src = _io.open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                                    'mapsim.py'), encoding='utf-8').read()
        print('`Block.plain` 里有"撤回"留档注释？ %s'
              % ('撤回** PC `9129a78`' in src or '撤回' in src))
        return 0 if not has else 1
    except Exception as e:          # noqa: BLE001
        print('!! %r' % (e,))
        return 2


if __name__ == '__main__':
    sys.exit(main())

import io
import os
import sys
import types

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
import spots as SP                          # noqa: E402
import mapsim as MS                         # noqa: E402
import mapsolve as MV                       # noqa: E402
import explore_loop as EL                   # noqa: E402

CASES = (
    ('矿洞 13:38', 'r_133809_0.png', (2, 2),
     {(1, 6): ['recommend'], (4, 2): ['boss']}),
    ('矿洞 13:36', 'r_133620_0.png', (1, 4),
     {(1, 5): ['recommend'], (4, 5): ['boss']}),
    ('矿洞 18:03', 'r_180326_0.png', None, {}),
    ('海滩 13:53', 'r_152223_0.png', None, {}),
    ('海滩 14:55', 'r_145515_0.png', None, {}),
    ('海滩 15:02', 'r_150207_0.png', None, {}),
)


def run(frame, camp, marks, e_on):
    img = cv2.imread(os.path.join(CAL, frame))
    c = EL.cells_of(img, mapname=None, code='S30001')
    st = c['st']
    if camp is None:
        for k, v in sorted(st.items()):
            if isinstance(v, dict) and str(v.get('name') or '') == '营地':
                camp = k
                break
    if camp is None:
        return None
    for k, ml in marks.items():
        if k in st:
            st[k]['marks'] = list(ml)
    _old = MS.CONTENT_SCORE_MIN
    if not e_on:
        MS.CONTENT_SCORE_MIN = 1.1           # 让那条永不命中 ⇒ 模拟"没有 E"
    try:
        sim = MS.MapSim.from_observation(st, SP.spot_rows())
        prob = MV.Problem(sim)
        rep = {}
        cost, plan = MV.solve(prob, max_states=60000, max_secs=8, report=rep)
        out = ['%d,%d' % rc for rc, bi, w in prob.cells_for_plan(plan or [])]
        npl = sum(1 for b in sim.blocks.values() if getattr(b, 'plain', False))
    finally:
        MS.CONTENT_SCORE_MIN = _old
    return cost, out, npl


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有标定帧 ⇒ 跳过')
        return 2
    print('=' * 96)
    print('E 条开/关 对照（6 张真机帧）—— 看**规划有没有任何变化**')
    print('=' * 96)
    print('%-14s %-34s %-34s %s' % ('帧', 'E 关', 'E 开', '是否变化'))
    ndiff = 0
    for tag, fn, camp, marks in CASES:
        if not os.path.exists(os.path.join(CAL, fn)):
            continue
        a = run(fn, camp, marks, False)
        b = run(fn, camp, marks, True)
        if a is None or b is None:
            print('%-14s (找不到营地 ⇒ 跳过)' % tag)
            continue
        same = (a[0] == b[0] and a[1] == b[1])
        if not same:
            ndiff += 1
        print('%-14s cost=%-4s %-25s cost=%-4s %-25s %s'
              % (tag, a[0], str(a[1])[:25], b[0], str(b[1])[:25],
                 '同' if same else '**变了**'))
    print()
    print('=' * 96)
    if ndiff == 0:
        print('⇒ ✅ **E 条在手机端对这 6 张真机帧毫无影响**（规划逐字相同）')
        print('   ⇒ 按"不做无用改动"的纪律：**应撤回 E**，只登记结论 ✓')
        print('   ⚠ 但它的**判据本身是对的**（`2,1` 真亮矿箱确实该拦）——')
        print('     只是手机端那条路径上，内容地块**本来**就被剪影/号段挡住了 ⇒ 重复劳动')
    else:
        print('⇒ ⚠ E 条在 **%d/%d** 帧上改变了规划 ⇒ 有实际作用，**该留** ✓'
              % (ndiff, len([1 for t, f, c, m in CASES
                             if os.path.exists(os.path.join(CAL, f))])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
