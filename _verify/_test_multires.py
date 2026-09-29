# -*- coding: utf-8 -*-
"""_test_multires.py · 验证 APK 的「全分辨率」到底能不能用（零体力、零设备）

背景（2026-09-29 用户问「多分辨率都能用了吗」）：
    端上一切坐标/模板走 **1080×1920 参考系**，设备帧由 `RefMapper.toRef()` 归一化。
    查代码时发现旧 `toRef` 的 `dst` 尺寸写成 `1080k × 1920k`，而 `k = min(W/1080, H/1920)`
    ⇒ 在 9:16 屏上 dst 恰好 == src ⇒ **drawBitmap 是 1:1 平移，根本没缩放**：
        1080×1920 → 原样 ✓（"刚好"对）
        720×1280  → 只占画布左上角，右侧/下方空黑 ✗
        1440×2560 → 画到界外被裁 ✗
        1080×2400 → 塞进 1080×1920 的框，纵横不等比 + 底部出界 ✗
    本脚本用**纯数学**把新旧两种 `toRef` 都跑一遍，给出：

      A. 几何自洽性：目标框是否**完整落在画布内**（不裁切）＋ 参考↔设备 往返误差
      B. 端到端：真棋盘图按各分辨率「渲染 → 归一化」后重跑地块分类，与 1080×1920 基线逐格对比
         （⚠ 只对 **9:16** 有意义：只有 9:16 时"游戏在 W×H 上渲染"能被精确模拟）

用法：python android_autoexplore/_verify/_test_multires.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAPBOT = r'D:\幻想少女公会\tools\mapbot'
sys.path.insert(0, MAPBOT)
os.chdir(MAPBOT)                     # spots.py 的模板是相对路径，必须站在 mapbot 目录
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                    # noqa: E402
import numpy as np                            # noqa: E402
import spots as SP                            # noqa: E402

REF_W, REF_H = 1080, 1920
CODE = 'S00003'                              # 等价性验证同款（夏日海滩）

# 候选分辨率
R_916 = [(540, 960), (720, 1280), (900, 1600), (1080, 1920), (1260, 2240), (1440, 2560)]
R_OTHER = [(1080, 2340), (1080, 2400), (1170, 2532), (1200, 1920), (1600, 2560)]


# ───────────────────────── 两种 toRef 的几何（照抄 Java，逐行对应）─────────────────────────

def box_old(W, H):
    k = min(W / REF_W, H / REF_H)
    ox = (W - REF_W * k) / 2.0
    oy = (H - REF_H * k) / 2.0
    return k, ox, oy, REF_W * k, REF_H * k          # k, ox, oy, dstW, dstH


def box_new(W, H):
    s = min(REF_W / W, REF_H / H)
    dx = (REF_W - W * s) / 2.0
    dy = (REF_H - H * s) / 2.0
    return s, dx, dy, W * s, H * s                  # s, dx, dy, dstW, dstH


def contains(x, y, w, h):
    return x >= -0.5 and y >= -0.5 and x + w <= REF_W + 0.5 and y + h <= REF_H + 0.5


def overlaps_canvas(x, y, w, h):
    return (x < REF_W - 0.5) and (y < REF_H - 0.5) and (x + w > 0.5) and (y + h > 0.5)


def scale_old(W, H):
    """旧版实际缩放 = dstW/srcW"""
    k, ox, oy, dw, dh = box_old(W, H)
    return dw / W, dh / H


def scale_new(W, H):
    s, dx, dy, dw, dh = box_new(W, H)
    return dw / W, dh / H


# 参考↔设备 往返（新旧两套公式）
def roundtrip_old(W, H, pts):
    k, ox, oy, _, _ = box_old(W, H)
    err = []
    for (xr, yr) in pts:
        dx_, dy_ = round(xr * k + ox), round(yr * k + oy)
        err.append((abs((dx_ - ox) / k - xr), abs((dy_ - oy) / k - yr)))
    return max(max(e) for e in err)


def roundtrip_new(W, H, pts):
    s, dx, dy, _, _ = box_new(W, H)
    err = []
    for (xr, yr) in pts:
        dx_, dy_ = round((xr - dx) / s), round((yr - dy) / s)
        err.append((abs((dx_ * s + dx) - xr), abs((dy_ * s + dy) - yr)))
    return max(max(e) for e in err)


# ───────────────────────── A. 几何自洽性 ─────────────────────────

PTS = [(20, 1725), (540, 1828), (541, 1890), (903, 1617), (275, 736), (36, 1002), (1004, 1722)]


def part_a():
    print('=' * 108)
    print('A. 几何自洽性：toRef 的目标框是否完整落在 1080×1920 画布内 + 参考↔设备往返误差')
    print('=' * 108)
    hdr = ('%-12s | %-26s | %-26s | %-10s' %
           ('分辨率', '旧 toRef（缩放 / 落点）', '新 toRef（缩放 / 落点）', '往返误差px'))
    print(hdr)
    print('-' * 108)
    bad = []
    for grp, lst in (('9:16', R_916), ('非9:16', R_OTHER)):
        print('── %s ──' % grp)
        for (W, H) in lst:
            k, ox, oy, dw, dh = box_old(W, H)
            s, dx, dy, nw, nh = box_new(W, H)
            so = scale_old(W, H)
            sn = scale_new(W, H)
            ok_old = overlaps_canvas(ox, oy, dw, dh) and contains(ox, oy, dw, dh)
            ok_new = contains(dx, dy, nw, nh)
            eo = roundtrip_old(W, H, PTS)
            en = roundtrip_new(W, H, PTS)
            print('%-12s | %-26s | %-26s | 旧 %.2f / 新 %.2f' % (
                '%dx%d' % (W, H),
                '%.4f,%.4f  (%4.0f,%4.0f) %s' % (so[0], so[1], ox, oy, '✓' if ok_old else '✗裁'),
                '%.4f,%.4f  (%4.0f,%4.0f) %s' % (sn[0], sn[1], dx, dy, '✓' if ok_new else '✗裁'),
                eo, en))
            if not ok_new:
                bad.append('新式裁切: %dx%d' % (W, H))
            if en > 1.0:
                bad.append('新式往返误差过大: %dx%d = %.2f' % (W, H, en))
    print()
    return bad


# ───────────────────────── B. 端到端分类 ─────────────────────────

SAMPLES = [
    os.path.join(HERE, '_pc_input.png'),
    os.path.join(HERE, 'dev_board_r0.png'),
    os.path.join(MAPBOT, 'runs', '_fixtures', 'inmap_a.png'),
]


def baseline_then_resim(img):
    """img: 1080×1920 真盘；返回 (基线 state, 各分辨率重跑 state)"""
    base = SP.Board(CODE).state(img)
    out = {}
    for (W, H) in R_916:
        # ① 模拟"游戏在 W×H 上渲染"：1080×1920 → (W,H)
        ip = cv2.INTER_AREA if (W < REF_W) else cv2.INTER_CUBIC
        dev = cv2.resize(img, (W, H), interpolation=ip)
        # ② 端上 toRef：整屏等比缩放回 1080×1920（9:16 ⇒ dx=dy=0）
        back = cv2.resize(dev, (REF_W, REF_H), interpolation=cv2.INTER_LINEAR)
        out[(W, H)] = SP.Board(CODE).state(back)
    return base, out


def part_b():
    print()
    print('=' * 108)
    print('B. 端到端：真棋盘按各「9:16 分辨率」渲染→归一化→重跑分类，与 1080×1920 基线逐格比对')
    print('=' * 108)
    verdict = []
    for p in SAMPLES:
        if not os.path.exists(p):
            print('（跳过，不存在）%s' % p)
            continue
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print('（跳过，读不出）%s' % p)
            continue
        if (img.shape[1], img.shape[0]) != (REF_W, REF_H):
            img = cv2.resize(img, (REF_W, REF_H), interpolation=cv2.INTER_CUBIC)
        base, out = baseline_then_resim(img)
        print('\n样本 %s   基线 35 格中 score 中位 %.3f' %
              (os.path.basename(p), np.median([v['score'] for v in base.values()])))
        print('  %-12s %-9s %-9s %-9s %-9s  %s' %
              ('分辨率', 'sid变化', 'revealed变', 'name变化', 'Δscore最大', '判定'))
        for (W, H) in R_916:
            st = out[(W, H)]
            d_sid = sum(1 for k in base if base[k]['sid'] != st[k]['sid'])
            d_rev = sum(1 for k in base if bool(base[k]['revealed']) != bool(st[k]['revealed']))
            d_nm = sum(1 for k in base if base[k]['name'] != st[k]['name'])
            d_sc = max(abs(base[k]['score'] - st[k]['score']) for k in base)
            ok = (d_sid == 0 and d_rev == 0 and d_nm == 0)
            print('  %-12s %-9d %-9d %-9d %-9.4f  %s' %
                  ('%dx%d' % (W, H), d_sid, d_rev, d_nm, d_sc, '✓ 全等' if ok else '✗ 有差异'))
            if not ok:
                verdict.append('%s @%dx%d' % (os.path.basename(p), W, H))
    print()
    return verdict


if __name__ == '__main__':
    bad = part_a()
    diff = part_b()
    print('=' * 108)
    if bad:
        print('❌ 几何问题：%s' % bad)
    else:
        print('✅ 几何：所有候选分辨率的目标框都完整落在画布内；参考↔设备往返误差 ≤1px')
    if diff:
        print('❌ 分类有差异：%s' % diff)
    else:
        print('✅ 分类：所有 9:16 分辨率下 35 格 sid/name/revealed **逐格全等**')
    print('=' * 108)
