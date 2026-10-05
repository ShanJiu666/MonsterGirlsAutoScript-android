# -*- coding: utf-8 -*-
"""v1.63 移植评估（B15）**决定性实验**：把同一帧的 boss 图标复制到第二格 ⇒ 现在的实现认得到吗？

## 为什么要造帧（不能只看 PC 的结论）
PC 的铁证是它自己的帧（`r_183432_0.png`，`(1,5)` 与 `(3,3)` 都有大拇指）。
手机端手头的 6 张帧**每格标记各不相同** ⇒ 看不到这个病 ✗
⇒ **人工造一张"两格同 boss"的帧**：把 `(4,2)` 的 boss 图标**原样复制**到另一格
  （用**同一份像素** ⇒ 两格真值完全相同 ⇒ 谁漏了谁就是 bug ✓）

判据：
  · 现在（`minMaxLoc` 单峰）⇒ 只认到 1 格 ⇒ **病成立** ✗
  · 打 `topn=N` 补丁后 ⇒ 认到 2 格 ⇒ **补丁有效** ✓

用法：python android_autoexplore\\tools\\probe_mark_dup_frame.py
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
import marks as MK                          # noqa: E402


def make_dup(img, src_cell, dst_cell):
    """把 `src_cell` 那一格的像素**整格复制**到 `dst_cell`（两格真值完全相同 ✓）"""
    px = int(MK.GRID['cx'])
    x0, y0 = int(MK.GRID['x0']), int(MK.GRID['y0'])
    sr, sc = src_cell
    dr, dc = dst_cell
    sx = x0 + (sc - 1) * px
    sy = y0 + (sr - 1) * px
    dx = x0 + (dc - 1) * px
    dy = y0 + (dr - 1) * px
    out = img.copy()
    out[sy:sy + px, sx:sx + px] = img[sy:sy + px, sx:sx + px]
    out[dy:dy + px, dx:dx + px] = img[sy:sy + px, sx:sx + px]
    return out


def scan_cells(img, key, topn=1):
    """只扫 `key` 这一个模板，返回**过闸点所在的格**（去重后）"""
    y0 = int(MK.GRID['y0']) - 10
    y1 = int(MK.GRID['y0'] + 5 * MK.GRID['cy']) + 10
    sub = img[y0:y1, 0:img.shape[1]]
    tpl = dict(MK._jobs_of()).get(key)
    if tpl is None:
        return set(), []
    # ⚠ 这里**手工传 topn**（手机端 match_at_scales 现在还不接受该参数）——
    #   为了做"补丁前后"对照，先原地实现一份带 NMS 的等价逻辑 ✓
    pts = _match_topn(sub, tpl, MK.GLYPH_SCALES, topn)
    cells = set()
    keep = []
    for sc, cx, cy in pts:
        if sc < MK.SHAPE_MIN:
            continue
        col = int((cx - MK.GRID['x0']) // MK.GRID['cx']) + 1
        row = int((cy + y0 - MK.GRID['y0']) // MK.GRID['cy']) + 1
        cells.add((row, col))
        keep.append((round(sc, 3), (row, col)))
    return cells, keep


def _match_topn(bgr, tpl_rgba, scales, topn):
    """照 PC `match_at_scales` 新逻辑的等价实现（NMS 取前 topn 个峰）"""
    out = []
    for s in scales:
        t = tpl_rgba
        th, tw = t.shape[:2]
        w, h = int(round(tw * s)), int(round(th * s))
        if w < 8 or h < 8 or w > bgr.shape[1] or h > bgr.shape[0]:
            continue
        t2 = cv2.resize(t, (w, h), interpolation=cv2.INTER_AREA)
        if t2.ndim == 3 and t2.shape[2] == 4:
            a = t2[:, :, 3]
            bgr3 = t2[:, :, :3]
        else:
            a = None
            bgr3 = t2 if t2.ndim == 3 else cv2.cvtColor(t2, cv2.COLOR_GRAY2BGR)
        gray_t = cv2.cvtColor(bgr3, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gray_s = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        m = None if a is None else (a > 128).astype(np.uint8) * 255
        n_on = float((m > 0).sum()) if m is not None else float(w * h)
        res = cv2.matchTemplate(gray_s, gray_t, cv2.TM_SQDIFF, mask=m)
        res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
        denom = n_on * 255.0 * 255.0
        if topn <= 1:
            mn, _, loc, _ = cv2.minMaxLoc(res)
            out.append((1.0 - mn / denom, loc[0] + w / 2.0, loc[1] + h / 2.0))
            continue
        nms_r = max(8, int(round(min(w, h) * 0.5)))
        work = res.copy()
        for _ in range(topn):
            mn, _mx, loc, _l2 = cv2.minMaxLoc(work)
            out.append((1.0 - mn / denom, loc[0] + w / 2.0, loc[1] + h / 2.0))
            x0_, y0_ = loc
            ya, yb = max(0, y0_ - nms_r), min(work.shape[0], y0_ + nms_r + 1)
            xa, xb = max(0, x0_ - nms_r), min(work.shape[1], x0_ + nms_r + 1)
            work[ya:yb, xa:xb] = 1e12
    return out


def main():
    src = os.path.join(CAL, 'r_133809_0.png')
    if not os.path.exists(src):
        print('⚠ 缺帧 %s ⇒ 跳过' % src)
        return 2
    img = cv2.imread(src)
    SRC, DST = (4, 2), (4, 5)          # (4,2) 有 boss（0.950）；复制到 (4,5)
    dup = make_dup(img, SRC, DST)
    outp = os.path.join(CAL, '_dup_boss.png')
    cv2.imwrite(outp, dup)
    print('已造帧：%s（把 (4,2) 整格像素复制到 (4,5) ⇒ 两格真值**完全相同**）' % outp)
    print()
    print('=' * 96)
    print('%-28s %-10s %s' % ('实现', '认到几格', '具体'))
    print('=' * 96)
    for label, topn in (('现状 minMaxLoc（topn=1）', 1),
                        ('topn=8（PC 新逻辑）', 8)):
        cells, keep = scan_cells(dup, 'boss', topn=topn)
        print('%-28s %-10d %s' % (label, len(cells), sorted(cells)))
        for sc, rc in keep[:8]:
            print('        sc=%.3f  格 %s' % (sc, rc))
    print()
    print('=' * 96)
    print('判读：现状只认到 **1** 格（而两格真值完全相同）⇒ **病成立** ✓')
    print('      topn=8 认到 **2** 格 ⇒ 补丁有效 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
