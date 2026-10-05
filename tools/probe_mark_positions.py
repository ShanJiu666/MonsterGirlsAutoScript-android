# -*- coding: utf-8 -*-
"""v1.63 移植评估（B15）**决定性检查**：`match_at_scales` 的 15 个候选是不是**全在同一位置**？

## 为什么要查这个
PC 的诊断是：`cv2.minMaxLoc(res)` ⇒ **每个尺度只回 1 个点**（= 该尺度上的**全局最优**）
⇒ 同一模板出现在**两格**时，分高的那格**在每个尺度上都赢** ⇒ 只报 1 个位置 ✗

手机端 `GLYPH_SCALES` 有 **15 个尺度** ⇒ 上一探针报 `recommend: 15`。
如果那 15 个点**位置全相同**（只是尺度不同）⇒ **就是 PC 那个病**（一帧一模板只认一处）✓
如果分布在多个位置 ⇒ 说明"多尺度"客观上提供了多个位置 ⇒ 病没那么重 ✓

用法：python android_autoexplore\\tools\\probe_mark_positions.py
"""
import io
import os
import sys
import types
from collections import defaultdict

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
import marks as MK                          # noqa: E402
from marks import _jobs_of, match_at_scales  # noqa: E402


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有帧目录 `%s` ⇒ 跳过' % CAL)
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        y0 = int(MK.GRID['y0']) - 10
        y1 = int(MK.GRID['y0'] + 5 * MK.GRID['cy']) + 10
        sub = img[y0:y1, 0:img.shape[1]]
        print('=' * 96)
        print('%s   尺度数=%d' % (fn, len(MK.GLYPH_SCALES)))
        for key, tpl in _jobs_of():
            pts = [(sc, cx, cy) for sc, s, cx, cy, w, h
                   in match_at_scales(sub, tpl, MK.GLYPH_SCALES)]
            pts = [p for p in pts if p[0] >= MK.SHAPE_MIN]
            if not pts:
                continue
            # 按位置聚类（同一格距内算同一个位置）
            clusters = []
            for sc, cx, cy in sorted(pts, reverse=True):
                for cl in clusters:
                    if abs(cx - cl['x']) < 40 and abs(cy - cl['y']) < 40:
                        cl['n'] += 1
                        cl['scales'].append(sc)
                        break
                else:
                    clusters.append({'x': cx, 'y': cy, 'n': 1, 'scales': [sc],
                                     'best': sc})
            print('  %-12s 过闸 %2d 个点 ⇒ 聚成 **%d 个位置**：%s'
                  % (key, len(pts), len(clusters),
                     ' | '.join('(%.0f,%.0f)×%d 最好%.3f'
                                % (c['x'], c['y'], c['n'], c['best'])
                                for c in sorted(clusters,
                                                key=lambda z: -z['best'])[:5])))
    print()
    print('=' * 96)
    print('判读：**每个类型只聚出 1 个位置** ⇒ 与 PC 同病（一模板只认一处）✓')
    print('      能聚出 2+ 个位置 ⇒ 多尺度客观上给了多个位置，病较轻（但仍可能漏）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
