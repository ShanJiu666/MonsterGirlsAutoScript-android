# -*- coding: utf-8 -*-
"""v1.62 关键对照：**地板法到底改变了什么**（改前 vs 改后，逐格 + order）

⚠ 上一脚本发现：矿洞 13:38 那把 `cost=18` **改前改后一样** ——
   因为两个目标 `(1,6)`/`(4,2)` **本身就在雾里**（floor 65/74 < 88）
   ⇒ 求解器**必须**开路 ⇒ 绕路是**正确**的，不是 bug ✓
⇒ 那地板法的价值在哪？本脚本**逐帧逐格**对比"改前/改后"的差异，把它量化出来。

对照口径：
  · **改前** = 只用 ratio（`MODEL_REVEAL_RATIO_MIN` 0.75）判 revealed（= v1.61 现状）
  · **改后** = 带标记的格由**地板**说了算（v1.62）
  · **真值** = 帧内 floor（人工看图核对过）

用法：python D:\\MGAS\\_tmpman\\diff_floor_effect.py
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
T = os.environ.get('MGAS_CAL_DIR') or os.path.abspath(os.path.join(PROJ, '..', '_tmpman', 'cal'))
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

# 带标记的格（真机日志里的 marks）
MARKS_BY_FRAME = {
    'r_133809_0.png': {(1, 6): ['recommend'], (4, 2): ['boss']},
    'r_133620_0.png': {(1, 5): ['recommend'], (4, 5): ['boss']},
    'r_145515_0.png': {},
    'r_150207_0.png': {},
}


def main():
    files = [f for f in sorted(os.listdir(T))
             if f.endswith('.png') and not f.startswith('_')]
    for fn in files:
        img = cv2.imread(os.path.join(T, fn))
        if img is None:
            continue
        c = EL.cells_of(img, mapname=None, code='S30001')
        st = c['st']
        thr = EL._floor_thr_now(c)
        marks = MARKS_BY_FRAME.get(fn, {})
        print('=' * 100)
        print('%s   地板阈值=%.1f' % (fn, thr if thr else -1))
        # 只列"ratio 与地板口径**判得不一样**"的格（= 地板法真正改变的那些）
        rows = []
        for k, v in sorted(st.items()):
            if not isinstance(v, dict) or v.get('floor') is None:
                continue
            r_ratio = float(v.get('ratio') or 0) >= EL.MODEL_REVEAL_RATIO_MIN
            r_floor = float(v['floor']) > thr if thr else None
            if r_ratio != r_floor:
                rows.append((k, v, r_ratio, r_floor, k in marks))
        if not rows:
            print('  （ratio 与地板口径**完全一致** ⇒ 这帧没有分歧）')
            continue
        print('  ⚠ 两种口径**判得不一样**的格（这就是地板法改变的量）：')
        print('  %-6s %-10s %-7s %-7s %-7s %-8s %s'
              % ('格', 'name', 'ratio', 'floor', 'ratio判', '地板判', '带标记'))
        for k, v, rr, rf, mk in rows:
            print('  %-6s %-10s %-7s %-7s %-7s %-8s %s'
                  % ('%d,%d' % k, v.get('name'), v.get('ratio'), v.get('floor'),
                     '亮' if rr else '雾', '亮' if rf else '雾',
                     ('是 %s' % (marks.get(k),) if mk else '')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
