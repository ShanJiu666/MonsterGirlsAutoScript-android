# -*- coding: utf-8 -*-
"""marks.py · 地块标记的视觉识别（模板匹配）

模板来自游戏 UI 包（`game.bundle` → AreaBlock.prefab 的 bossIcon/recommendIcon/
cloverIcon/redEquipIcon 四个 Image 的精灵，见 prefab_icons.py 的导出）：
    top_int_BOSS_0001   = 首领
    mid_ico_tuijian_0002= 大拇指（推荐 = 掉你追踪中的装备/符文）
    DL_siyecao          = 幸运草（宝藏战）
    mid_ico_map_0001    = 红装（SS 装）

用法:
    python marks.py runs/board_clean.png            # 多尺度扫描，打印每格命中的标记
    python marks.py runs/board_clean.png --scales 1.5 5 0.25
"""

# ─────────────────────────────────────────────────────────────────────────────
# 【Android 适配补丁 · 由 android_autoexplore/tools/port_android.py 注入，勿手改】
# Chaquopy 里 __file__ 指向 APK 内只读资源，模板/数据表在 filesDir/mapbot_pack
#  ⇒ 资源根一律走环境变量，未设置时回退 PC 原行为（便于与 PC 对拍）
import os as _os

_MAPBOT_ROOT = _os.environ.get('MAPBOT_ROOT') or _os.path.dirname(_os.path.abspath(__file__))
_MAPBOT_RUNS = _os.environ.get('MAPBOT_RUNS') or _os.path.join(_MAPBOT_ROOT, 'runs')
_MAPBOT_DT = _os.environ.get('MAPBOT_DT') or _os.path.join(_MAPBOT_ROOT, 'server_datatable.json')
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np

TPL_DIR = os.path.join(_MAPBOT_ROOT, 'templates', 'marks')
MARKS = [('boss', 'bossIcon__top_int_BOSS_0001.png'),
         ('recommend', 'recommendIcon__mid_ico_tuijian_0002.png'),
         ('clover', 'cloverIcon__DL_siyecao.png'),
         ('redEquip', 'redEquipIcon__mid_ico_map_0001.png')]

GRID = dict(x0=36.0, y0=1002.0, cx=144.0, cy=144.0, cols=7, rows=5)
# ⭐ 2026-09-25 实机重新标定（旧值 x0=21 y0=941 148.3x154.3 是错的，第 1 行偏 56px）：
#   地块贴图设计 30x30、格距 32px，游戏按 4.5 倍画 ⇒ 屏幕格距 32*4.5 = 144.0，
#   棋盘左上 = (36, 1002)，单格贴图 135x135 居中在 144 里。重现见 fit_art.py。


# 按类型的门槛（2026-09-26）：clover 收紧，挡掉误报的幸运草
TYPE_MIN = {'clover': (0.90, 0.75),
            'boss': (0.90, 0.85)}   # ⭐ boss 也要严（防普通格被误标 ✗ 用户 2026-09-27）
# ⭐ 标记只可能出现在格心 ±65px（1080p ✓ 四标记样本实测 ✓ = 0.45 格）
MARK_BOX_REF = 65.0
MARK_MARGIN = 0.06      # ⭐ 同格多标记：与最高分相差 ≤0.06 的类型也算命中 ✓
SHAPE_MIN = 0.80           # ⭐ 形状下限（噪声 ≤0.86 但配色差 ✗；真标记 0.82~0.97 ✓）
COLOR_MIN = 0.68           # ⭐ 配色下限（NCC，对雾格变暗不敏感 ✓；噪声 0.45~0.65 ✗）
GLYPH_KEEP = 1.0           # （保留：1.0 = 不裁剪；裁过 0.62 反而更差 ✗）          # ⭐ 只保留模板中间 62%（挖掉共有的沙地圆角底纹 ✓）
GLYPH_SCALES = [round(3.8 + 0.1 * i, 2) for i in range(15)]   # ⭐ 真标记尺度 3.8~5.2


def _crop_glyph(tpl, keep=GLYPH_KEEP):
    h, w = tpl.shape[:2]
    nh, nw = max(4, int(h * keep)), max(4, int(w * keep))
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    return tpl[y0:y0 + nh, x0:x0 + nw].copy()


def load_tpls():
    out = {}
    for key, fn in MARKS:
        p = os.path.join(TPL_DIR, fn)
        if not os.path.exists(p):
            continue
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        out[key] = img
    # ⭐ 2026-09-26：额外加载「实测裁出来」的幸运草模板
    #   （幻少那台 recommend 会压过 clover ⇒ 用真实像素重裁一个，自匹配 0.978/0.931 ✓）
    _live = os.path.join(_MAPBOT_ROOT,
                         'templates', 'clover_live.png')
    if os.path.exists(_live):
        _img = cv2.imdecode(np.fromfile(_live, dtype=np.uint8),
                            cv2.IMREAD_UNCHANGED)
        if _img is not None and _img.ndim == 3 and _img.shape[2] == 4:
            out['clover_live'] = _img
    # ⭐ 2026-09-26：把 `templates/<类型>_*.png` 全部当作该类型的**样本变体** ✓
    #   （用户确认过的实拍样本裁出来的模板，比游戏原始小图标更能分清大拇指/幸运草 ✓）
    import glob as _glob
    _tdir = os.path.join(_MAPBOT_ROOT, 'templates')
    _variants = {}
    for _f in _glob.glob(os.path.join(_tdir, '*.png')):
        _base = os.path.basename(_f)[:-4]
        _typ = _base.split('_')[0]
        if _typ in out and _base != _typ:
            try:
                _im = cv2.imdecode(np.fromfile(_f, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if _im is not None and _im.ndim == 3 and _im.shape[2] == 4:
                    _variants.setdefault(_typ, []).append(_im)
            except Exception:       # noqa: BLE001
                pass
    for _typ, _lst in _variants.items():
        out[_typ + '_v'] = _lst        # 变体列表（scan_board 会取最高分 ✓）


    return out


def match_at_scales(bgr, tpl_rgba, scales):
    """多尺度模板匹配，返回 [(score, scale, cx, cy, w, h)]（score 越大越像）

    ⚠ 2026-09-25 加防御：调用方可能塞进 4 通道图（带 alpha 的 PNG）或灰度图，
      OpenCV 会报 `type == _templ.type()` 直接崩。这里统一成 3 通道 float32；
      掩码统一成 CV_8U（OpenCV 只认 8U/32F，且必须和模板同尺寸）。
    """
    if bgr is None:
        return []
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    elif bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
    th, tw = tpl_rgba.shape[:2]
    rgb = tpl_rgba[:, :, :3].astype(np.float32)
    alpha = np.where(tpl_rgba[:, :, 3] > 32, 255, 0).astype(np.uint8)
    H, W = bgr.shape[:2]
    src = bgr.astype(np.float32)
    out = []
    for s in scales:
        w, h = int(round(tw * s)), int(round(th * s))
        if w < 6 or h < 6 or w >= W or h >= H:
            continue
        t = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_LINEAR)
        m = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_NEAREST)
        if int((m > 0).sum()) < 20:
            continue
        res = cv2.matchTemplate(src, t, cv2.TM_SQDIFF, mask=m)
        res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
        mn, _, mnloc, _ = cv2.minMaxLoc(res)
        norm = mn / (float((m > 0).sum()) * 255.0 * 255.0)      # 0=完全一致
        out.append((1.0 - norm, float(s), mnloc[0] + w / 2.0, mnloc[1] + h / 2.0, w, h))
    return out


def color_score(bgr, tpl_rgba, cx, cy, scale):
    """掩码区域的**逐通道配色一致性**（0~1，越大越像）

    ⚠ 2026-09-25 加：boss 与 redEquip 两个图标都是"沙地底 + 红色记号"，
      纯形状分（TM_SQDIFF）会把 boss 格也认成 redEquip（实测每张图都串）✗。
      源码里两者配色其实不同：boss 深红 (179,62,62)、redEquip 亮红 (230,80,80) + 金色 (255,236,140)
      ⇒ 逐通道算零均值相关，取平均，就能分开。
    """
    if bgr is None or tpl_rgba is None:
        return 0.0
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    elif bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
    th, tw = tpl_rgba.shape[:2]
    w, h = int(round(tw * scale)), int(round(th * scale))
    if w < 6 or h < 6:
        return 0.0
    t = cv2.resize(tpl_rgba[:, :, :3].astype(np.float32), (w, h),
                   interpolation=cv2.INTER_LINEAR)
    m = cv2.resize(np.where(tpl_rgba[:, :, 3] > 32, 255, 0).astype(np.uint8), (w, h),
                   interpolation=cv2.INTER_NEAREST) > 0
    x0, y0 = int(round(cx - w / 2.0)), int(round(cy - h / 2.0))
    sub = bgr[y0:y0 + h, x0:x0 + w]
    if sub.shape[0] != h or sub.shape[1] != w or int(m.sum()) < 20:
        return 0.0

    def ncc(a, b):
        a = a.astype(np.float32) - float(a.mean())
        b = b.astype(np.float32) - float(b.mean())
        if a.std() < 1e-6 or b.std() < 1e-6:
            return 0.0
        return float((a / a.std() * (b / b.std())).mean())

    return float(np.mean([ncc(sub[:, :, i][m], t[:, :, i][m]) for i in range(3)]))


MATCH_MIN = 0.85          # 形状分下限（原阈值）


def scan(img_path, scales, thr):
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    tpls = load_tpls()
    res = {}
    for key, tpl in tpls.items():
        hits = [r for r in match_at_scales(img, tpl, scales) if r[0] >= thr]
        hits.sort(reverse=True)
        keep = []
        for h in hits:
            cx, cy = h[2], h[3]
            r = int((cy - GRID['y0']) // GRID['cy']) + 1
            c = int((cx - GRID['x0']) // GRID['cx']) + 1
            if not (1 <= r <= 5 and 1 <= c <= 7):
                continue
            if any(abs(cx - k[2]) < 60 and abs(cy - k[3]) < 60 for k in keep):
                continue            # 同一图标多尺度重复命中
            keep.append((h[0], h[1], cx, cy, r, c))
        res[key] = keep
    return img, res


def default_scales():
    return [round(2.0 + 0.25 * i, 3) for i in range(17)]      # 2.0 .. 6.0


def scan_board(img, thr=None, scales=None, region=None, use_color=True):
    """整盘扫描标记 -> {(row,col): {'marks': [...], 'at': (cx,cy), 'score': s}}

    region: 只搜棋盘区域 (x0,y0,x1,y1)，默认按 GRID 算，避免 HUD 误命中
    use_color: ⭐ 用**形状 + 配色**双判（2026-09-25 加）——boss 与 redEquip 形状极像，
        只用形状分每张图都会把 boss 格也认成 redEquip（用户报的"我游戏里没看到红装"）
    """
    thr = SHAPE_MIN if thr is None else thr   # ⭐ 默认用形状下限（原来写死 0.90 ⇒ 幻少全漏 ✗）
    scales = scales or GLYPH_SCALES          # ⭐ 收紧到真标记的尺度区间
    if region is None:
        region = (0, int(GRID['y0']) - 10, img.shape[1],
                  int(GRID['y0'] + 5 * GRID['cy']) + 10)
    x0, y0, x1, y1 = region
    sub = img[y0:y1, x0:x1]
    out = {}
    _all = load_tpls()
    _jobs = []
    for _k, _v in _all.items():
        if isinstance(_v, list):
            for _t in _v:
                _jobs.append((_k.replace('_v', ''), _t))     # 变体 → 归到基础类型 ✓
        else:
            _jobs.append((_k, _v))
    for key, tpl in _jobs:
        for sc, s, cx, cy, w, h in match_at_scales(sub, tpl, scales):
            if sc < thr:
                continue
            gx, gy = cx + x0, cy + y0
            r = int((gy - GRID['y0']) // GRID['cy']) + 1
            c = int((gx - GRID['x0']) // GRID['cx']) + 1
            if not (1 <= r <= 5 and 1 <= c <= 7):
                continue
            # ⭐ 2026-09-27：标记只在格心 ±MARK_BOX 内（用户建议 ✓ 挡误报 ✓）
            _box = MARK_BOX_REF * (float(GRID['cx']) / 144.0)
            _ccx = GRID['x0'] + (c - 0.5) * GRID['cx']
            _ccy = GRID['y0'] + (r - 0.5) * GRID['cy']
            if abs(gx - _ccx) > _box or abs(gy - _ccy) > _box:
                continue
            cs = color_score(img, tpl, gx, gy, s) if use_color else 1.0
            if use_color and cs < COLOR_MIN:
                continue            # 配色不像 ⇒ 多半是另一个图标（boss↔redEquip 串味）
            # ⭐ 2026-09-26 用户指出：**一格可以同时有多个标记**
            #   （幻少实测 2-3 格「既是首领又是幸运草」✓）
            #   ⇒ 先把所有过闸候选都记下来，最后按「与本格最高分相差 ≤MARK_MARGIN」决定保留谁 ✓
            base_name = key.replace('_live', '').replace('_desk', '').replace('_real', '')
            # 按类型门槛（clover 更严，挡掉误报）
            _tmin = TYPE_MIN.get(base_name)
            if _tmin and (sc < _tmin[0] or cs < _tmin[1]):
                continue
            d = out.setdefault((r, c), {'marks': [], 'at': (int(gx), int(gy)),
                                        'score': round(sc, 3), 'color': round(cs, 3),
                                        '_cand': []})
            d['_cand'].append((sc + cs, base_name, round(sc, 3), round(cs, 3),
                               int(gx), int(gy)))
            d['score'] = max(d['score'], round(sc, 3))
            d['color'] = round(max(d.get('color') or 0, cs), 3)
    # 收尾：同格多标记按**位置**区分 ✓（用户：幸运草紧挨着首领、在它右边 ✓）
    for _cell, _d in out.items():
        _cand = _d.pop('_cand', [])
        if not _cand:
            continue
        _cand.sort(reverse=True)
        _keep, _pos = [], []
        # ⭐ 2026-09-27：clover ↔ recommend 这对要分得更开才算两个真标记 ✓
        #   实测（用户报）同一格的**同一个大拇指徽章**上，幸运草模板能偏 ~20px 命中 ✗
        #   ⇒ 被当成第二个标记 ⇒ 白摇一次色子（耗幸运草 ✗）
        #   徽章宽约 58px ⇒ 这对要求分开 ≥35px ✓；其余组合仍 18px ✓（保 4 标记格 ✓）
        _STRICT = {('clover', 'recommend'), ('recommend', 'clover')}
        for _tot, _name, _sc, _cs, _px, _py in _cand:
            _dup = False
            for _i2, (qx, qy) in enumerate(_pos):
                _gap = 35 if (_keep[_i2], _name) in _STRICT else 18
                if abs(_px - qx) < _gap and abs(_py - qy) < _gap:
                    _dup = True
                    break
            if _dup:
                continue
            if _name not in _keep:
                _keep.append(_name)
                _pos.append((_px, _py))
        _d['marks'] = _keep
        _d['best'] = round(_cand[0][0], 3)
    return out


def probe_top(img, top=1, scales=None, region=None):
    """⭐ 2026-10-02 v1.22 诊断用：**每个标记模板各自最好的那处**（不设闸门，给裸分）

    用途：反馈包里出现 `marks_scan: none` 时，一眼分清两件完全不同的事 ——
        · **棋盘上真没有标记**（每个模板的最好分都很低）
        · **有标记，但被机身偏暗/偏色压到闸门之下**（形状 0.74 / 配色 0.84 这种"近失"）
      （2026-10-02 两个 nubia 包的疑问正是后者：真机帧 boss 形状分只有 0.741@(2,4)，
       而 boss 闸门要 0.90 —— **肉眼看得见图标、代码扫不到** ✗）

    ⚠ **只做诊断，不参与任何判定**（返回裸分；调用方别拿它当命中用 ✗）
    ⚠ 必须**按模板分别取最好**（不是全局 top-N）—— 全局 top-N 会被别的类型刷屏，
      "boss 到底差多少"这个最关键的信息反而看不见 ✗（2026-10-02 踩过一次）
    """
    if img is None:
        return []
    scales = scales or GLYPH_SCALES      # ⚠ 必须与 scan_board 同口径（否则"近失"看不到）
    if region is None:
        region = (0, int(GRID['y0']) - 10, img.shape[1],
                  int(GRID['y0'] + 5 * GRID['cy']) + 10)
    x0, y0, x1, y1 = region
    sub = img[y0:y1, x0:x1]
    rows = []
    for key, tpl in load_tpls().items():
        if isinstance(tpl, list):
            tpl = tpl[0]
        best = None
        for sc, s, cx, cy, w, h in match_at_scales(sub, tpl, scales):
            gx, gy = cx + x0, cy + y0
            r = int((gy - GRID['y0']) // GRID['cy']) + 1
            c = int((gx - GRID['x0']) // GRID['cx']) + 1
            if not (1 <= r <= 5 and 1 <= c <= 7):
                continue
            if best is None or sc > best[0]:
                best = (sc, s, gx, gy, key, r, c)
        if best is not None:
            sc, s, gx, gy, key, r, c = best
            rows.append({'tpl': key, 'shape': round(sc, 3),
                         'color': round(color_score(img, tpl, gx, gy, s), 3),
                         'rc': '%d,%d' % (r, c), 'scale': round(s, 2)})
    rows.sort(key=lambda d: -d['shape'])
    return rows


def cell_center(row, col):
    return (int(GRID['x0'] + (col - 0.5) * GRID['cx']),
            int(GRID['y0'] + (row - 0.5) * GRID['cy']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('--scales', nargs=3, type=float, default=[1.5, 6.0, 0.25],
                    metavar=('START', 'END', 'STEP'))
    ap.add_argument('--thr', type=float, default=0.90)
    args = ap.parse_args()
    s0, s1, st = args.scales
    scales = []
    x = s0
    while x <= s1 + 1e-9:
        scales.append(round(x, 3))
        x += st
    img, res = scan(args.img, scales, args.thr)
    print('图片:', args.img, '尺度 %d 档 %s..%s  阈值 %.2f' % (len(scales), s0, s1, args.thr))
    total = 0
    for key in ('boss', 'recommend', 'clover', 'redEquip'):
        hits = res.get(key, [])
        total += len(hits)
        print('%-10s 命中 %d' % (key, len(hits)))
        for sc, s, cx, cy, r, c in hits[:6]:
            print('     score=%.3f 缩放=%.2f 位置=(%d,%d)  格=(%d行,%d列)' % (sc, s, cx, cy, r, c))
    print('合计命中', total)


if __name__ == '__main__':
    main()
