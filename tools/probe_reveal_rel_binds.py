# -*- coding: utf-8 -*-
"""⭐ v1.60 的**相对项到底有没有生效**？＋ 两臂（绝对 0.80 vs 相对法）逐格差

## 这条为什么要单独有一个探针
v1.60 照抄了 PC 的**两趟相对法**：`revealed ⟺ ratio ≥ max(地板, p10 × 1.06)`。
但"抄了"不等于"生效了" —— 相对项生效的**充要条件**是：
    `p10 × REVEAL_REL_K > REVEAL_REL_FLOOR`   ⟺   `p10 > 0.80 / 1.06 = 0.7547`
若所有真机帧的 p10 都低于它，则 `max()` 永远选地板 ⇒ **spots 层行为 == v1.36 的绝对 0.80**，
真正在修"已揭示被判成雾"的是**第二层**（`_cells_for_model` 的 `ratio ≥ 0.75` 覆写）。
⇒ 不问这一句，下一个人会以为"改成相对法就好了" ✗

## ⚠⚠ 上一版探针的 bug（本脚本是修正版，别退回）
第一版按 `CODES` 顺序试，**取第一个能认出 ≥20 格的 code**（且 `>` 比较保留先到的）
⇒ 对 S10002/S00002 的帧也用了 **S00003** 的模板集 ⇒ **ratio 分母错、数字全部作废** ✗
  实例：草原帧 r0 在 S00003 下 p10=0.578、在正确的 S10002 下 p10=**0.623**
本版：**先按图名实测消歧选 code**（复用 `explore_loop._disambiguate_map`），
选完**只跑那一个 code** ✓

用法：python tools\\probe_reveal_rel_binds.py
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


def pick_code(img):
    """用**真实帧实测**选 code（含图名歧义消歧那条真逻辑）；返回 (code, st) 或 (None, {})

    ⚠ 只按"认出 ≥20 格 + 有营地"收帧**还不够** —— 结算面板/选图界面也可能被硬认成 35 格
    ⇒ 本脚本还要过 `board_hidden()` 闸门（见 `main`），否则"真棋盘帧"这句话是假的 ✗
    """
    cands = ['S00003', 'S10002', 'S00002', 'S00001', 'S10001', 'S10003']
    if len(cands) > 1:
        try:
            c = EL._disambiguate_map(img, '?', cands, log=None)
            if c:
                cands = [c] + [x for x in cands if x != c]
        except Exception:                   # noqa: BLE001
            pass
    for code in cands:
        try:
            st = SP.Board(code).state(img)
        except Exception:                   # noqa: BLE001
            continue
        if len(st) >= 20 and any(v.get('name') == '营地' for v in st.values()):
            return code, st
    return None, {}


def main():
    thr_rel = 0.80
    print('v1.60 相对项生效条件：p10 × %.2f > 地板 %.2f  ⟺  p10 > %.4f\n'
          % (SP.REVEAL_REL_K, SP.REVEAL_REL_FLOOR, SP.REVEAL_REL_FLOOR / SP.REVEAL_REL_K))
    paths = []
    for base in (V, FB):
        for f in glob.glob(os.path.join(base, '**', '*.png'), recursive=True):
            n = os.path.basename(f).lower()
            if any(k in n for k in SKIP):
                continue
            paths.append(f)
    paths = sorted(set(paths))
    rows, binds, total_diff, nboard = [], 0, 0, 0
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
        # ⭐ 只收**真棋盘帧**：面板挡住棋盘的帧不算（上一版漏了这道闸门 ⇒ "36 张真棋盘帧"
        #   那句话当时是**不成立**的 —— 里面混着结算/选图帧 ✗）
        try:
            if EL.board_hidden({'st': st,
                                'light': [1] * sum(1 for v in st.values()
                                                   if v.get('revealed')),
                                'gray': [1] * sum(1 for v in st.values()
                                                  if not v.get('revealed'))}):
                continue
        except Exception:                   # noqa: BLE001
            pass
        nboard += 1
        rs = sorted(float(v.get('ratio') or 0) for v in st.values())
        p10 = rs[max(0, int(len(rs) * SP.REVEAL_REL_Q) - 1)]
        rel = p10 * SP.REVEAL_REL_K
        thr = max(SP.REVEAL_REL_FLOOR, rel)
        # 两臂：v1.36 绝对 0.80 vs v1.60 实际（state() 已经用相对法算过 revealed）
        A = {k: float(v.get('ratio') or 0) >= thr_rel for k, v in st.items()}
        B = {k: bool(v.get('revealed')) for k, v in st.items()}
        diff = [k for k in A if A[k] != B[k]]
        total_diff += len(diff)
        if rel > SP.REVEAL_REL_FLOOR:
            binds += 1
        rows.append((os.path.relpath(p, V), code, len(st), p10, rel, thr, diff))
    rows.sort(key=lambda r: -r[3])
    print('%-36s %-8s %4s %7s %7s %7s %s'
          % ('帧', 'code', '格数', 'p10', 'p10×K', '阈值', '两臂逐格差'))
    for r in rows[:16]:
        print('%-36s %-8s %4d %7.3f %7.3f %7.3f %s'
              % (r[0][:36], r[1], r[2], r[3], r[4], r[5],
                 ('%d 格 %s' % (len(r[6]), r[6])) if r[6] else '—'))
    print()
    print('=' * 100)
    print('真棋盘帧 %d 张：相对项**生效**（p10×K > 地板）的 = %d 张' % (nboard, binds))
    print('两臂（绝对 0.80 vs 相对法）逐格差合计 = %d 格' % total_diff)
    print('=' * 100)
    if binds == 0:
        print('⇒ 手头 %d 张真棋盘帧上，相对项**一次都没超过地板 0.80** ⇒ v1.60 的 `spots` 层'
              % nboard)
        print('   在这一批帧上与 v1.36 的绝对 0.80 **逐格等价**（结构照抄 PC ✓，本机无实证）。')
        print('   ⚠ 要让它真正生效，需要一张「整盘偏亮」的帧：p10 > %.4f'
              % (SP.REVEAL_REL_FLOOR / SP.REVEAL_REL_K))
        print('     （= 全盘过半格 ratio 都 >0.75，即几乎全盘已揭示 —— 真机少见）')
    else:
        print('⇒ 有 %d 张帧上相对项真的抬高了阈值 ⇒ v1.60 的 spots 层与 v1.36 确有差异 ✓' % binds)
    return 0


if __name__ == '__main__':
    sys.exit(main())
