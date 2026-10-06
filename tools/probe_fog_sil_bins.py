# -*- coding: utf-8 -*-
"""v1.76 取证③：`fog_sil` 众数为什么会被 0.0 抢走？—— **直方图分箱太细**

## 假设（本探针要证伪/证实）
`spots.py:890` 的直方图按 `round(_s, 3)` 分箱（**0.001 粒度**），然后取众数：
```python
_h2[round(_s, 3)] = _h2.get(round(_s, 3), 0) + 1
_mode2 = max(sorted(_h2), key=lambda x: (_h2[x], -x))
```
矿洞帧上"岩地"这一**同一个视觉簇**的剪影值会散在 **0.1126 / 0.1139 / 0.1141 / 0.1152** …
⇒ 一个簇被**切成 4~5 个箱**，每个箱只有 4~7 票；
而"真平坦雾格"恰好都精确等于 **0.0000**（开运算后掩码全空 ⇒ `mask.mean()==0.0`）
⇒ **一个箱就拿走全部那些票** ⇒ 众数落到 0.0 ⇒ `_fog_sil_thr = max(0.04, 0) = 0.04`
⇒ 岩地（0.113）**远超 0.04** ⇒ 被判"雾下有东西" ⇒ `plain=False` ⇒ **一格一格点** ✗✗

⚠ 这与接力单写的"**平局**"是同一后果的**两种触发**：平局取小 ⇒ 0.0 胜；票多 ⇒ 0.0 胜。
   真正的病根都是"**0.0 自成一箱、而真实簇被切碎**"。

## 本探针做什么
  ① 打印每帧 `fog_sil` 的**细粒度直方图**（前 8 名）+ 0.0 的票数占比
  ② 三种取众数口径的对比：
     · 现口径（0.001 箱 / 平局取小）
     · 粗分箱（`round(v, 2)` ⇒ 0.01 粒度，同一视觉簇自然合并）
     · 只算 `>0` 的值（把"精确 0.0"整体排除）
  ③ 各自的阈值 + `fog_object=True` 格数 + **哪些格从"非空地"变回"空地"**
     （= 连锁恢复的格；⚠ 逐格标出名字，看有没有**内容物被误放**）

用法：python android_autoexplore\\tools\\probe_fog_sil_bins.py 帧1 [帧2 …]
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
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
import explore_loop as EL                   # noqa: E402

CANDS = ['S00003', 'S10002', 'S00002', 'S00001', 'S10001', 'S10003']


def pick_code(img):
    cands = list(CANDS)
    try:
        c = EL._disambiguate_map(img, '?', cands, log=None)
        if c:
            cands = [c] + [x for x in cands if x != c]
    except Exception:                       # noqa: BLE001
        pass
    for code in cands:
        try:
            st = SP.Board(code).state(img)
        except Exception:                   # noqa: BLE001
            continue
        if len(st) >= 20 and any(v.get('name') == '营地' for v in st.values()):
            return code, st
    return None, {}


def mode_fine(vals):
    """现口径：0.001 箱 + 平局取小（逐字复刻 spots.py:888-891）"""
    h = {}
    for s in vals:
        h[round(s, 3)] = h.get(round(s, 3), 0) + 1
    return max(sorted(h), key=lambda x: (h[x], -x)), h


def mode_coarse(vals, nd=2):
    """粗分箱：同一视觉簇合并（0.01 粒度）"""
    h = {}
    for s in vals:
        h[round(s, nd)] = h.get(round(s, nd), 0) + 1
    return max(sorted(h), key=lambda x: (h[x], -x)), h


def mode_pos(vals):
    """只对 >0 的值取众数（精确 0.0 整体排除）"""
    pos = [s for s in vals if s > 0]
    if not pos:
        return 0.0, {}
    h = {}
    for s in pos:
        h[round(s, 3)] = h.get(round(s, 3), 0) + 1
    return max(sorted(h), key=lambda x: (h[x], -x)), h


def main():
    kk = float(getattr(SP, 'FOG_SIL_MODE_K', 1.6))
    floor = float(SP.FOG_SIL_MIN)
    for fp in sys.argv[1:]:
        img = cv2.imread(fp)
        if img is None:
            print('读不出 %s' % fp)
            continue
        code, st = pick_code(img)
        if not st:
            print('%s：认不出真棋盘（跳）' % os.path.basename(fp))
            continue
        sils = {k: float(v['fog_sil']) for k, v in st.items()
                if isinstance(k, tuple) and isinstance(v, dict)
                and v.get('fog_sil') is not None}
        vals = list(sils.values())
        mf, hf = mode_fine(vals)
        mc, _hc = mode_coarse(vals)
        mp, _hp = mode_pos(vals)
        z = sum(1 for v in vals if v == 0.0)
        print('=' * 98)
        print('%s  code=%s  有 fog_sil 的格 %d；**精确 0.0 的 %d 格（%.0f%%）**'
              % (os.path.basename(fp), code, len(vals), z, 100.0 * z / max(1, len(vals))))
        top = sorted(hf.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        print('  细箱前 8：' + '  '.join('%.3f×%d' % (k, c) for k, c in top))
        for label, m in (('现口径 0.001箱/平局取小', mf),
                         ('粗分箱 0.01', mc),
                         ('只算>0', mp)):
            thr = max(floor, float(m) * kk)
            nobj = sum(1 for v in vals if v >= thr)
            print('  %-24s 众数=%.4f ⇒ 阈值=%.4f ⇒ fog_object=True **%2d 格**'
                  % (label, m, thr, nobj))
        thr_cur = max(floor, float(mf) * kk)
        thr_new = max(floor, float(mc) * kk)
        chg = [k for k in sils if (sils[k] >= thr_cur) != (sils[k] >= thr_new)]
        if chg:
            print('  ⇒ 粗分箱后**恢复连锁**的格 %d 个：' % len(chg))
            for k in sorted(chg):
                nm = str((st.get(k) or {}).get('name') or '')
                sc = (st.get(k) or {}).get('score')
                print('     %-6s %-14s fog_sil=%.4f score=%s' % ('%d,%d' % k, nm, sils[k], sc))
    return 0


if __name__ == '__main__':
    sys.exit(main())
