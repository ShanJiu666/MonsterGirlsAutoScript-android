# -*- coding: utf-8 -*-
"""v1.62 第二步标定：`fog_sil`（雾下剪影）的**绝对阈值**在手机端矿洞帧上成不成立

## 背景（PC `f3b0f4e` 的诊断，用户原话「**不是最优步数**」/「**有两下无意义点击**」）
`fog_object = fog_sil >= FOG_SIL_MIN(0.04)` 是**绝对阈值**，标定在**铁血高地的草地**上
（平坦 0.014~0.016 / 有物体 0.064~0.292）✓
而**矿洞地面是「岩地」，它自带的雾底岩石纹理就占 0.126** ⇒
旧阈值把**每一格岩地**都判成"雾下有东西" ⇒ `plain=False` ⇒ **连锁全断** ✗✗
⇒ PC 改成 `max(FOG_SIL_MIN, 本帧众数 × 1.6)`。

## 本脚本问：**手机端**的矿洞帧有没有同一个病？
  ① 打印每帧 `fog_sil` 的分布 + 众数
  ② 按"旧绝对阈值 0.04"和"本帧众数×1.6"两种口径，各判几格"雾下有东西"
  ③ 若两者差很多 ⇒ 手机端同样中招 ⇒ 该搬 ✓

用法：python android_autoexplore\\tools\\probe_fog_sil_calib.py
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
import numpy as np                          # noqa: E402
import spots as SP                          # noqa: E402


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有标定帧目录 `%s` ⇒ **跳过**' % CAL)
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    if not files:
        print('⚠ `%s` 里没有标定帧 ⇒ **跳过**' % CAL)
        return 2
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        st = SP.Board('S30001').state(img)
        sils = {k: float(v['fog_sil']) for k, v in st.items()
                if isinstance(v, dict) and v.get('fog_sil') is not None}
        if not sils:
            print('%-20s  没有 fog_sil（全盘无雾？）' % fn)
            continue
        hist = {}
        for v in sils.values():
            hist[round(v, 3)] = hist.get(round(v, 3), 0) + 1
        mode = max(sorted(hist), key=lambda x: (hist[x], -x))
        thr_old = float(getattr(SP, 'FOG_SIL_MIN', 0.04))
        thr_new = max(thr_old, float(mode) * 1.6)
        n_old = sum(1 for v in sils.values() if v >= thr_old)
        n_new = sum(1 for v in sils.values() if v >= thr_new)
        print('=' * 92)
        print('%-20s  有 fog_sil 的格 %d' % (fn, len(sils)))
        print('  众数=%.4f（%d 次）  最小=%.4f  最大=%.4f'
              % (mode, hist[mode], min(sils.values()), max(sils.values())))
        print('  旧口径（绝对 %.2f）判"雾下有东西" %d 格' % (thr_old, n_old))
        print('  新口径（众数×1.6=%.3f）判"雾下有东西" %d 格' % (thr_new, n_new))
        if n_old != n_new:
            print('  ⇒ ⚠ **两者不同**（差 %d 格）⇒ 手机端**同样中招**，该搬 ✓'
                  % abs(n_old - n_new))
            # 列出被判反的格
            chg = [(k, v) for k, v in sorted(sils.items())
                   if (v >= thr_old) != (v >= thr_new)]
            for k, v in chg[:12]:
                nm = (st.get(k) or {}).get('name')
                print('     %-6s %-10s fog_sil=%.4f' % ('%d,%d' % k, nm, v))
        else:
            print('  ⇒ 两者一致 ⇒ 本帧不受影响')
    return 0


if __name__ == '__main__':
    sys.exit(main())
