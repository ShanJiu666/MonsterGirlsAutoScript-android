# -*- coding: utf-8 -*-
"""v1.62 第三步验证：手机端**有没有**"连锁穿过宝箱/内容地块"这个病？

## 为什么要单独验证（不能因为 PC 改了就跟风改）
PC `9129a78` 的 E 条治的是：**宝箱美术是亮的 ⇒ 剪影法（只抓"比雾底暗"的东西）整个漏掉**
⇒ 判它"平坦=空地" ⇒ 模型让连锁**穿过宝箱** ⇒ 计划走不通 ✗
（PC 用户原话：「**这张图没认出宝箱吗，中间有宝箱拦住连锁了**」）

但手机端 `Block.plain` **已经与 PC 分叉**（有 v1.48 战斗保护 / v1.05 雾格分支 /
`PLAIN_SUFFIX` 兜底）⇒ **不能假设手机端同病** ✗
⇒ 本脚本用**真机帧**直接问：有没有"高置信内容地块（score ≥ 0.85、非地面）"被判成 `plain=True`？

## 判据
  · 从真机帧跑真流水线 → `MapSim` → 逐块查 `Block.plain`
  · 对每个 `plain=True` 的块，回查它的 `score` / `name` / 数据表 `Weight`
  · 若存在"score ≥ 0.85 且非本图地面填充块（Weight < 40000）"却 `plain=True`
    ⇒ **手机端同病** ⇒ 该搬 E ✓
  · 若一个都没有 ⇒ 手机端**不犯这个病**（旧判据够用）⇒ **不搬**，只登记 ✓

用法：python android_autoexplore\\tools\\probe_plain_chain.py
"""
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
import targets_cfg as TC                    # noqa: E402
import mapsim as MS                         # noqa: E402
import explore_loop as EL                   # noqa: E402


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有标定帧目录 `%s` ⇒ **跳过**（不报假绿）' % CAL)
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    if not files:
        print('⚠ `%s` 里没有标定帧 ⇒ **跳过**' % CAL)
        return 2
    rows = SP.spot_rows() or {}
    plain_names = set(getattr(TC, 'PLAIN_NAMES', ()) or ())
    total_bad = 0
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        c = EL.cells_of(img, mapname=None, code='S30001')
        st = c['st']
        # 找营地（有就用；没有让 from_observation 自己判）
        camp = None
        for k, v in sorted(st.items()):
            if isinstance(v, dict) and str(v.get('name') or '') == '营地':
                camp = k
                break
        sim = MS.MapSim.from_observation(st, SP.spot_rows())
        bad = []
        for bi, b in sorted(sim.blocks.items()):
            if not getattr(b, 'plain', False):
                continue
            nm = str(getattr(b, 'name', '') or '')
            sid = str(getattr(b, 'sid', '') or '')
            try:
                w = int((rows.get(sid) or {}).get('Weight') or 0)
            except Exception:               # noqa: BLE001
                w = 0
            # 用格的 score（Block 目前可能没有 score 字段 ⇒ 从观测取）
            scs = []
            for m in (getattr(b, 'cells', None) or []):
                rc = (m // 7, m % 7)
                v = st.get((rc[0] + 1, rc[1] + 1))
                if isinstance(v, dict) and v.get('score') is not None:
                    scs.append(float(v['score']))
            sc = max(scs) if scs else 0.0
            is_ground = (w >= 40000) or (nm in plain_names)
            if (not is_ground) and sc >= 0.85:
                bad.append((('%d,%d' % (bi, bi)), nm, sid, w, round(sc, 3)))
        print('=' * 92)
        print('%-18s  块 %d ｜ plain 块 %d ｜ ⚠ 高置信非地面却 plain 的：%d'
              % (fn, len(sim.blocks),
                 sum(1 for b in sim.blocks.values() if getattr(b, 'plain', False)),
                 len(bad)))
        for row in bad[:10]:
            print('     %-10s %-10s %-14s Weight=%-6d score=%s' % row)
        total_bad += len(bad)
    print()
    print('=' * 92)
    if total_bad:
        print('⇒ ⚠ **手机端同病**（共 %d 处）⇒ 该搬 PC 的 E 条（内容地块拦连锁）✓'
              % total_bad)
    else:
        print('⇒ ✅ **手机端没这个病**（所有 plain 块要么是本图地面、要么 score < 0.85）')
        print('   ⇒ E 条**不必搬**（手机端的 `PLAIN_SUFFIX` + 战斗保护已够用）✓')
        print('   ⚠ 但 PC 那条「`Weight ⇒ 地面`」判据更稳（不靠号段/名字）⇒ 可作**保守加固**另行评估')
    return 0


if __name__ == '__main__':
    sys.exit(main())
