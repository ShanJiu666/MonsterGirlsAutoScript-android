# -*- coding: utf-8 -*-
"""v1.76 取证⑤：**把分箱变粗，会不会把真内容物放成空地**？（接力单的警告要验）

接力单原话：
> ⚠ 但**不能简单抬高阈值**（真内容物 `1,1 矿箱 0.131`、`2,4 矿箱堆 0.232`、
> `5,7 旅行商人 0.105` 也会被判成空地 ⇒ 连锁穿过去）

本探针逐格列出：细箱（现口径）与粗箱两臂下，每格的
  `name` / `score` / `fog_sil` / `fog_object`(⇒plain) / **数据表是否空地**（v1.70 闸门）
⇒ 直接看「翻成空地」的格里有没有**高分内容物**（`score>=0.85` ⇒ 会被 v1.70 闸门兜住 ✓）
   以及**低分内容物**（`<0.85` ⇒ 闸门兜不住，只能靠剪影 ✗）。

用法：python android_autoexplore\\tools\\probe_fog_risk.py 帧 [帧...]
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, PYDIR)
os.environ.setdefault('MAPBOT_ROOT', ASSETS)
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
import numpy as np                          # noqa: E402
import spots as SP                          # noqa: E402

KK = float(getattr(SP, 'FOG_SIL_MODE_K', 1.6))
FLOOR = float(SP.FOG_SIL_MIN)
GATE_MIN = 0.85          # v1.70 闸门分数下限


def pick_code(im):
    best, key = None, None
    for c in sorted(set((SP.map_table() or {}).values())):
        try:
            st = SP.Board(c).state(im, thr=0.0)
        except Exception:                   # noqa: BLE001
            continue
        n = len(st or {})
        hi = sum(1 for v in (st or {}).values() if float(v.get('score') or 0) >= 0.85)
        if key is None or (hi, n) > key:
            best, key = c, (hi, n)
    return best


def mode_of(vals, nd):
    h = {}
    for v in vals:
        h[round(v, nd)] = h.get(round(v, nd), 0) + 1
    return max(sorted(h), key=lambda x: (h[x], -x))


def is_plain_table(sid):
    try:
        return bool(SP.is_plain_spot(sid))
    except Exception:                       # noqa: BLE001
        return None


def main():
    for fp in sys.argv[1:]:
        if not os.path.exists(fp):
            continue
        im = cv2.imdecode(np.fromfile(fp, dtype=np.uint8), cv2.IMREAD_COLOR)
        code = pick_code(im)
        st = SP.Board(code).state(im, thr=0.0)
        sils = {k: float(v['fog_sil']) for k, v in st.items()
                if isinstance(k, tuple) and isinstance(v, dict)
                and v.get('fog_sil') is not None}
        if not sils:
            print('%s：无 fog_sil' % os.path.basename(fp))
            continue
        vals = list(sils.values())
        thr_f = max(FLOOR, mode_of(vals, 3) * KK)
        thr_c = max(FLOOR, mode_of(vals, 2) * KK)
        print('=' * 104)
        print('%s  code=%s  细箱阈值=%.4f  粗箱阈值=%.4f' % (os.path.basename(fp), code, thr_f, thr_c))
        flipped = []
        for k in sorted(sils):
            a = sils[k] >= thr_f        # 细箱：True = 有东西 = 非空地
            b = sils[k] >= thr_c
            if a != b:
                flipped.append(k)
        print('  「非空地 → 空地」（= 连锁**恢复**穿过它）的格 %d 个：' % len(flipped))
        for k in flipped:
            v = st.get(k) or {}
            nm = str(v.get('name') or '')
            sc = float(v.get('score') or 0)
            pl = is_plain_table(v.get('sid'))
            gate = (sc >= GATE_MIN and pl is False)
            print('    %-6s fog_sil=%.4f score=%.3f  %-14s 表说空地=%s  v1.70闸门兜住=%s%s'
                  % ('%d,%d' % k, sils[k], sc, nm, pl, gate,
                     '  ⛔ **低分内容物，闸门兜不住**' if (not gate and pl is False
                                                          and sc < GATE_MIN) else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
