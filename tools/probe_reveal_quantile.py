# -*- coding: utf-8 -*-
"""为什么 PC 的 `p10×1.06` 在手机端**不生效**？—— 量出「手机端真正该看的分位」

## 两端的 `ratio` 量纲不同（这是全部原因）

· **PC**：分母 = **该格自己的模板亮度** ⇒ `ratio = 格子亮度 / 自己模板亮度`
  ⇒ 雾格 = 美术 × 0.667 / 自己模板 ⇒ **雾格恒 ≈0.65（与格子美术无关！）**
  ⇒ 雾是**一个常数** ⇒ 取本帧 **p10**（≈雾的floor）就够 ⇒ ×1.06 盖住整条雾带 ✓
· **手机端**（v1.35 起）：分母 = **本图模板亮度中位** ⇒ `ratio = 格子亮度 / 全图中位`
  ⇒ 雾格 = **0.667 × 自己美术亮度 / 全图中位** ⇒ **雾格随"这格美术多亮"摊开**
  （真机草原帧实测 0.685~0.761，宽达 26%）
  ⇒ 雾是**一段分布** ⇒ p10 只给出**雾的下沿**，×1.06 仍然远低于雾的**上沿** ✗✗
  ⇒ 所以 `max(0.80, p10×1.06)` 里永远是 0.80 那条腿在起作用（相对腿恒不生效）

## 本脚本量出：手机端「雾上沿」落在本帧 ratio 分布的哪个分位

用**最大跳变**把本帧 ratio 切成「雾簇 / 已揭示簇」（无需真值）：
  雾上沿 = 低簇最大值；已揭示下沿 = 高簇最小值；阈值候选 = 雾上沿 × 1.06
对照：p10×1.06（PC 口径，手机端默认地板 0.80）落在哪。

## ⚠ 与 `probe_reveal_rel_binds.py` 的关系
后者回答「相对项现在生不生效」（答案：**不生效**，见 v1.60 门禁 ⑯）；
本脚本回答「**如果要用相对法，手机端该取哪个分位**」——结论：**约 80 分位（雾的上沿）**，
而不是 PC 的 p10（雾的下沿）。⚠ **本轮没改这个**（用户口径=照抄 PC），记为下一轮候选。

## ⚠⚠ 别用"取第一个能认出的 code"来选模板集（本脚本已按图名实测消歧）
第一版探针按 `CODES` 顺序取第一个 ≥20 格的 code ⇒ 对 S10002 的帧也用 S00003 模板集
⇒ ratio 分母错、数字全废（草原帧 p10：0.578(错) vs 0.623(对)）✗

## ⚠ 本脚本的选帧口径（与 `probe_reveal_rel_binds.py` **故意不同**，别当成同一个 corpus）
它只要求「认出 ≥20 格 **且** 有一个叫"营地"的格」⇒ **会收进若干非棋盘帧**
（结算面板 / 选图界面也可能被硬认成 35 格）。这是**有意的**：
本脚本问的是"**ratio 分布的形态**"（雾簇 vs 已揭示簇在哪），那张表看的是**形状**，
个别杂帧不改变"雾上沿落在 ~80 分位"这个结论；而 `probe_reveal_rel_binds.py` 问的是
"某一帧的判定会不会变"，那里必须**只收真棋盘帧**（它自己带 `board_hidden` 闸门）✓

用法：python tools\\probe_reveal_quantile.py
"""
import glob
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
_V = os.path.join(PROJ, '_verify')
_FB = os.path.abspath(os.path.join(PROJ, '..', '_fb'))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
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
import explore_loop as EL                   # noqa: E402

V = _V
FB = _FB
SKIP = ('slot', 'toast', 'zip', 'bar_zoom', 'crop', 'zoom', 'check', 'ovl_',
        'mgas_', 'select', 'menu', 'bag', 'vault', 'settle',
        'ui_v', 'dlg', 'stuck', 'blocked', 'user_game', 'game_login')
_CANDS = ('S00003', 'S10002', 'S00002', 'S00001', 'S10001', 'S10003')
# 真值（门禁里的人工标注）
TRUTH = {
    'board_grassland_r0.png': {(5, 6), (4, 7), (5, 7)},
    'board_grassland_live.png': {(1, 6), (1, 7), (2, 7)},
}


def pick_code(img):
    """⭐ 先按图名**实测消歧**选 code，再只跑那一个（避免用错模板集 ⇒ ratio 分母错 ✗）"""
    cands = list(_CANDS)
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


def pct_rank(rs, v):
    """v 在该分布里的分位（0~1）"""
    n = sum(1 for x in rs if x < v)
    return n / float(len(rs)) if rs else 0.0


def main():
    paths = []
    for base in (V, FB):
        for f in glob.glob(os.path.join(base, '**', '*.png'), recursive=True):
            n = os.path.basename(f).lower()
            if any(k in n for k in SKIP):
                continue
            paths.append(f)
    paths = sorted(set(paths))
    print('%-34s %4s %6s %6s %6s %6s %6s %6s  %s'
          % ('帧', '格', 'p10', '雾上沿', '雾上沿分位', '×1.06', '已揭下沿', '0.80', '判定'))
    rows = []
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            continue
        h, w = img.shape[:2]
        if h < 1000 or not (0.4 < w / float(h) < 0.75):
            continue
        code, st = pick_code(img)
        if not st:
            continue
        n = len(st)
        rs = sorted(float(v.get('ratio') or 0) for v in st.values())
        p10 = rs[max(0, int(len(rs) * SP.REVEAL_REL_Q) - 1)]
        # 最大跳变切簇
        gaps = [(rs[i + 1] - rs[i], i) for i in range(len(rs) - 1)]
        g, gi = max(gaps) if gaps else (0.0, 0)
        fog_top = rs[gi]                 # 低簇最大
        rev_bot = rs[gi + 1]             # 高簇最小
        cand = fog_top * SP.REVEAL_REL_K
        # 真值可用时直接算，否则用切簇结果
        truth = TRUTH.get(os.path.basename(p))
        if truth is not None:
            keys = sorted(st)
            rev = sorted(float(st[k].get('ratio') or 0) for k in keys if k in truth)
            fog = sorted(float(st[k].get('ratio') or 0) for k in keys if k not in truth)
            if fog and rev:
                fog_top, rev_bot = fog[-1], rev[0]
                cand = fog_top * SP.REVEAL_REL_K
        rows.append((os.path.relpath(p, V), code, n, p10, fog_top, rev_bot, cand,
                     pct_rank(rs, fog_top), g, truth is not None))
    rows.sort(key=lambda r: -r[4])
    for r in rows:
        ok = '✓ 落在空档' if r[4] < r[5] and r[6] > r[4] else '⚠ 越界'
        print('%-34s %4d %6.3f %6.3f %10.2f %6.3f %8.3f %6.2f  %s%s'
              % (r[0][:34], r[2], r[3], r[4], r[7], r[6], r[5], 0.80, ok,
                 '  [真值]' if r[9] else ''))
    print()
    print('=' * 104)
    pct = [r[7] for r in rows]
    cands = [r[6] for r in rows]
    print('「雾上沿」在本帧 ratio 分布里的分位：中位 %.2f（范围 %.2f~%.2f）'
          % (float(np.median(pct)), min(pct), max(pct)))
    print('「雾上沿 × %.2f」阈值：中位 %.3f（范围 %.3f~%.3f）'
          % (SP.REVEAL_REL_K, float(np.median(cands)), min(cands), max(cands)))
    print('对照：PC 的 p10×1.06 在手机端恒 < 地板 %.2f ⇒ **相对腿不生效**' % SP.REVEAL_REL_FLOOR)
    print('=' * 104)
    print('⇒ 结论：手机端的「雾」是**一段分布**（不是 PC 的常数）⇒ 该取的是**雾的上沿**')
    print('   （实测落在本帧 **%.0f 分位**附近），而 PC 用 p10 取的是**雾的下沿**。'
          % (float(np.median(pct)) * 100))
    print('   * 若把 p10 改成「雾上沿估计」并 ×%.2f ⇒ 阈值中位 %.3f（与经验标定的 0.80 同量级 ✓）'
          % (SP.REVEAL_REL_K, float(np.median(cands))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
