# -*- coding: utf-8 -*-
"""v1.76 取证②：`fog_sil` 阈值塌回 0.04 时，**模型层到底有多少格不能连锁**？

接力单那条未决只给了"逐格 fog_object 差几格"，**没给模型层后果**。本探针补上：
  ① 现口径 vs 「只对名字像空地的格统计众数」vs 「平局取较大值」三种口径下，
     每帧的阈值 + `fog_object=True` 格数；
  ② ⭐ **模型级**：三种口径各建一个 `mapsim` 棋盘，数 `plain=False` 的格数
     （= 不能连锁的格）⇒ 这才是用户报的「忘记了连锁机制，挨个去点」的**直接度量**；
  ③ ⛔ 反证：口径改了以后，**真内容物**（矿箱/宝箱/祭坛…）有没有被放成空地。

用法：python android_autoexplore\\tools\\probe_fog_sil_thr_effect.py 帧1 帧2 …
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

CODES = ('S30001', 'S10002', 'S00002', 'S00003', 'S20003', 'S10001')
# 「名字像空地」定义（探针自己的判据，**只用于取证**）
PLAINISH = ('岩地', '草地', '沙地', '泥地', '雪地', '石板', '地面', '空地', '泥土')


def pick_best(img):
    best = None
    for code in CODES:
        try:
            st = SP.Board(code).state(img)
        except Exception:                   # noqa: BLE001
            continue
        sils = {k: float(v['fog_sil']) for k, v in st.items()
                if isinstance(k, tuple) and isinstance(v, dict)
                and v.get('fog_sil') is not None}
        if sils and (best is None or len(sils) > len(best[1])):
            best = (st, sils, code)
    return best


def mode_of(hist, tie='small'):
    if tie == 'small':
        return max(sorted(hist), key=lambda x: (hist[x], -x))
    return max(sorted(hist), key=lambda x: (hist[x], x))


def thr_cur(sils, kk):
    h = {}
    for v in sils.values():
        h[round(v, 3)] = h.get(round(v, 3), 0) + 1
    return max(float(SP.FOG_SIL_MIN), mode_of(h, 'small') * kk)


def thr_groundonly(st, sils, kk):
    """只对**名字像空地**的格统计众数（接力单建议②）"""
    h = {}
    for k, v in sils.items():
        nm = str((st.get(k) or {}).get('name') or '')
        if any(p in nm for p in PLAINISH):
            h[round(v, 3)] = h.get(round(v, 3), 0) + 1
    if not h:
        return None
    return max(float(SP.FOG_SIL_MIN), mode_of(h, 'small') * kk)


def main():
    kk = float(getattr(SP, 'FOG_SIL_MODE_K', 1.6))
    for fp in sys.argv[1:]:
        img = cv2.imread(fp)
        if img is None:
            print('读不出 %s' % fp)
            continue
        b = pick_best(img)
        if not b:
            print('%s：认不出' % os.path.basename(fp))
            continue
        st, sils, code = b
        t_cur = thr_cur(sils, kk)
        t_grd = thr_groundonly(st, sils, kk)
        print('=' * 96)
        print('%s  code=%s  有 fog_sil 的格 %d' % (os.path.basename(fp), code, len(sils)))
        for label, thr in (('现口径', t_cur), ('只算空地名字', t_grd)):
            if thr is None:
                print('  %-14s 无从计算' % label)
                continue
            obj = [k for k in sils if sils[k] >= thr]
            print('  %-14s 阈值=%.4f  fog_object=True %2d 格' % (label, thr, len(obj)))
        if t_grd is not None and abs(t_grd - t_cur) > 1e-9:
            chg = [k for k in sils if (sils[k] >= t_cur) != (sils[k] >= t_grd)]
            print('  ⇒ 差 %d 格：' % len(chg))
            for k in sorted(chg)[:20]:
                nm = str((st.get(k) or {}).get('name') or '')
                arrow = '非空地→空地(可连锁)' if sils[k] >= t_cur else '空地→非空地'
                print('     %-6s %-14s fog_sil=%.4f  %s' % ('%d,%d' % k, nm, sils[k], arrow))
    return 0


if __name__ == '__main__':
    sys.exit(main())
