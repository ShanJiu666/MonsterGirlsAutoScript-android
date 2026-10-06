# -*- coding: utf-8 -*-
"""v1.76 取证：`fog_sil` 众数**平局** ⇒ 阈值塌回 0.04（接力单 §3 那条「独立未决」）

## 接力单原文（2026-10-06 会话接力 §3）
> **⚠ 一条独立未决：`fog_sil` 众数平局 ⇒ 阈值塌回 0.04**（v1.70 闸门之外的另一条）：
> 某帧众数取样 = `[(0.114, 5), (0.0, 5), (0.115, 4)]` ⇒ **平局** ⇒ `argmax` 取到 **0.0**
> ⇒ `_fog_sil_thr = 0.04`（远低于岩地纹理 0.114）⇒ **整片"岩地"被判 `fog_object=True`**
> ⇒ `plain=False` ⇒ 不能连锁 ⇒ 一格一格点（用户报「规划怎么又犯老毛病了，忘记了连锁机制，
> 挨个去点」）。对照实验：阈值改 0.1824 ⇒ **15 格改判**。
> ⚠ 但**不能简单抬高阈值**（真内容物 `1,1 矿箱 0.131`、`2,4 矿箱堆 0.232`、
> `5,7 旅行商人 0.105` 也会被判成空地 ⇒ 连锁穿过去）⇒ 建议**平局取较大值**或
> **只对"名字像空地"的格统计众数**；**未改** ✓

## 本探针问三件事（**只取证、不改代码**）
  ① 现网可拿到的每一帧，`fog_sil` 直方图的**前二名**是谁、**是否平局**？
  ② 平局时现口径（`max(sorted(h), key=(count, -val))` ⇒ 取**较小**值）给出的阈值是多少？
     「平局取较大值」又会给多少？逐格 `fog_object` 差几格？
  ③ ⭐ 关键反证：**改了之后，真内容物会不会被判成空地**（接力单点名的那三个格）？

用法：python android_autoexplore\\tools\\probe_fog_sil_tie.py [帧目录...]
      不给目录 ⇒ 自动扫 `_verify/` + `_tmpman/cal/` + `_tmpman/` 下所有棋盘帧。
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.abspath(os.path.join(PROJ, '..'))
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


# 候选图名（`Board(code)` 要按图选模板集）—— 与 `probe_fog_sil_calib.py` 同口径
CODES = ('S30001', 'S10002', 'S00002', 'S00003', 'S20003', 'S10001')


def _frames(argv):
    if argv:
        dirs = argv
    else:
        dirs = [os.path.join(PROJ, '_verify'),
                os.path.join(ROOT, '_tmpman', 'cal'),
                os.path.join(ROOT, '_tmpman')]
    out = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for dp, _dn, fns in os.walk(d):
            for fn in fns:
                low = fn.lower()
                if not low.endswith('.png'):
                    continue
                if ('board' not in low and not low.startswith('r_')
                        and 'frame' not in low):
                    continue
                if low.startswith('_'):
                    continue
                out.append(os.path.join(dp, fn))
    return sorted(set(out))


def _mode_pick(hist, tie='small'):
    """复刻 `spots.py:891` 的众数挑选，但把**平局**方向做成可切换。

    现网写法：`max(sorted(h), key=lambda x: (h[x], -x))`
      ⇒ 平局（次数相同）时 `(cnt,-v)` 比较 → `-v` 大者胜 → **v 小者胜**（取较小值）
    """
    if tie == 'small':
        return max(sorted(hist), key=lambda x: (hist[x], -x))
    return max(sorted(hist), key=lambda x: (hist[x], x))     # 平局取较大值


def main():
    frames = _frames(sys.argv[1:])
    print('扫描 %d 个候选帧……' % len(frames))
    n_tie = 0
    n_ok = 0
    for fp in frames:
        img = cv2.imread(fp)
        if img is None:
            continue
        # 先按图名/尺寸挑模板集：逐个试，取"能认出最多格"的那个（与 calib 探针同法，
        # ⚠ 但它自己的坑（对 S10002 也用 S00003 模板）已在 README 记账 ⇒ 这里只在
        #   **同一帧内**比较口径差，选错 code 不影响②③的相对结论，故沿用）
        best = None
        for code in CODES:
            try:
                st = SP.Board(code).state(img)
            except Exception:               # noqa: BLE001
                continue
            sils = {k: float(v['fog_sil']) for k, v in st.items()
                    if isinstance(k, tuple) and isinstance(v, dict)
                    and v.get('fog_sil') is not None}
            if not sils:
                continue
            if best is None or len(sils) > len(best[1]):
                best = (st, sils, code)
        if best is None:
            continue
        st, sils, code = best
        hist = {}
        for v in sils.values():
            hist[round(v, 3)] = hist.get(round(v, 3), 0) + 1
        ranked = sorted(hist.items(), key=lambda kv: (-kv[1], kv[0]))
        top_cnt = ranked[0][1]
        tied = [k for k, c in ranked if c == top_cnt]
        is_tie = len(tied) > 1
        m_small = _mode_pick(hist, 'small')
        m_large = _mode_pick(hist, 'large')
        kk = float(getattr(SP, 'FOG_SIL_MODE_K', 1.6))
        base = float(getattr(SP, 'FOG_SIL_MIN', 0.04))
        thr_small = max(base, m_small * kk)
        thr_large = max(base, m_large * kk)
        rel = os.path.relpath(fp, ROOT)
        tag = '⚠平局' if is_tie else '  '
        diff = [k for k in sils if (sils[k] >= thr_small) != (sils[k] >= thr_large)]
        print('%s %-58s code=%s 格=%2d  top=%s'
              % (tag, rel[:58], code, len(sils),
                 ','.join('%.3f×%d' % (k, c) for k, c in ranked[:3])))
        if is_tie:
            n_tie += 1
            print('      ⚠ **平局**：%s（次数都是 %d）' % (tied, top_cnt))
            print('      · 现口径（取小）众数=%.4f ⇒ 阈值=%.4f' % (m_small, thr_small))
            print('      · 取大       众数=%.4f ⇒ 阈值=%.4f' % (m_large, thr_large))
            print('      · 逐格 `fog_object` 差 **%d 格**' % len(diff))
            for k in sorted(diff)[:16]:
                nm = (st.get(k) or {}).get('name')
                print('          %-6s %-12s fog_sil=%.4f  小口径=%s 大口径=%s'
                      % ('%d,%d' % k, nm, sils[k],
                         sils[k] >= thr_small, sils[k] >= thr_large))
                # ⭐③ 反证：这一格**是内容物**却被大口径判成"空地"了吗？
                if sils[k] < thr_large and nm and nm not in ('岩地', '草地', '沙地', None):
                    print('          ⛔⛔ **内容物被判成空地**（`%s`）⇒ 连锁会穿过去 ✗' % nm)
        else:
            n_ok += 1
    print('=' * 92)
    print('平局帧 %d 个 / 非平局帧 %d 个' % (n_tie, n_ok))
    return 0


if __name__ == '__main__':
    sys.exit(main())
