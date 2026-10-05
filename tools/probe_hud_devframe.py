# -*- coding: utf-8 -*-
"""v1.64 验收②：用**真机截图**（1280×2772 / 选图界面）反算回**参考系**，验证 HUD 取数窗口

## 为什么需要它
`coin_count` / `clover_count` 的窗口是**离线按 1080×1920 参考系帧**标定的
（`tools/probe_clover_row.py`），**没在"设备帧 → 参考系"这条链上验过** ✗
本脚本拿一张**新拍的真机截图**，按 `RefMapper` 的**同一条公式**反算回参考系，
再和 `COIN_HUD_X/Y` / `CLOVER_HUD_X/Y` 对拍 ✓

## 映射（照抄 `RefMapper.java`，顶块段）
    kx    = screenW / REF_W            （1280/1080 = 1.18519）
    shift = screenH - REF_H*kx         （2772 - 2275.6 = 496.4，>0 ⇒ anchored ✓）
    **顶块**（refY ≤ TOP_SPLIT_REF=300）：devY = refY*kx + topInset
    ⇒ 反算：refY = (devY - topInset)/kx ；refX = devX/kx
    ⚠⚠ `topInset` = 真机**状态栏/挖孔**安全区（本机实测 ~124~132px）
      ⇒ **不减它，整块会下移 ~105 参考像素 ⇒ 正好错过窗口** ✗

## 自洽判据（本脚本的核心）
  第 1 行（金币）与第 2 行（幸运草）**各自**反解出的 `topInset` 必须**几乎相等** ✓
  ⇒ 说明「设备帧 HUD 位置」与「参考系标定位置」是**同一套映射**，
    我的窗口（在参考系里量的）**拿到设备帧上依然成立** ✓

## 真值（肉眼读的这张截图）
    金币 = **165531**（< 50 万 ⇒ 闸门应当**不买**）
    幸运草 = **1**（< 8 ⇒ 应当**不摇色子 + 剔纯大拇指目标**）

用法：python android_autoexplore\\tools\\probe_hud_devframe.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_DEV_PNG = os.environ.get('MGAS_DEV_FRAME') or os.path.abspath(
    os.path.join(PROJ, '..', '_tmpman', '_dev_screen.png'))
_OUT = os.path.join(os.path.abspath(os.path.join(PROJ, '..', '_tmpman')),
                    '_hud_devframe_out.txt')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402

REF_W, REF_H = 1080, 1920
TOP_SPLIT_REF = 300
#: 参考系里两行的**标定 y**（`tools/probe_clover_row.py` 实测）
REF_ROW1_Y = 40        # 金币（第 1 行）
REF_ROW2_Y = 94        # 幸运草（第 2 行）


def row_profile(img, y0, y1, th=190):
    """每个设备行的「近白像素数」（用于找文字行的峰）"""
    prof = []
    for y in range(y0, y1):
        band = img[y:y + 1, :]
        b, g, r = (band[:, :, 0].astype(np.int16), band[:, :, 1].astype(np.int16),
                   band[:, :, 2].astype(np.int16))
        mn = np.minimum(np.minimum(b, g), r)
        prof.append(int((mn > th).sum()))
    return prof


def clusters(mask, min_w=4):
    out, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        if j - i >= min_w:
            out.append((i, j - 1, (i + j - 1) / 2.0, j - i))
        i = j
    return out


def white_cols(band, th=190, min_rows=2):
    b, g, r = (band[:, :, 0].astype(np.int16), band[:, :, 1].astype(np.int16),
               band[:, :, 2].astype(np.int16))
    white = (np.minimum(np.minimum(b, g), r) > th)
    return white.sum(axis=0) >= min_rows


def two_peaks(prof, base, min_gap=25):
    """在 profile 里找两个峰（返回偏移量）—— 峰 = 文字行的中心"""
    idx = [i for i, v in enumerate(prof) if v >= 120]      # 有字的行
    if not idx:
        return []
    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= min_gap:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    peaks = []
    for g in groups:
        best = max(g, key=lambda i: prof[i])
        peaks.append(base + best)
    return peaks


def main():
    lines = []

    def P(s):
        lines.append(s)

    if not os.path.exists(_DEV_PNG):
        P('⚠ 缺真机截图 %s' % _DEV_PNG)
    else:
        img = cv2.imread(_DEV_PNG)
        if img is None:
            P('⚠ 读不了 %s' % _DEV_PNG)
        else:
            h, w = img.shape[:2]
            kx = w / float(REF_W)
            shift = h - REF_H * kx
            P('设备帧 %dx%d ⇒ kx=%.5f  shift=%.1f（>0 ⇒ anchored 顶块锚顶+其余锚底 ✓）'
              % (w, h, kx, shift))
            P('参考系 %dx%d ｜ 顶块段 refY ≤ %d' % (REF_W, REF_H, TOP_SPLIT_REF))
            P('')

            # HUD 在设备帧顶部 ~130~270（上面 0~125 是纯黑状态栏）
            prof = row_profile(img, 100, 300)
            peaks = two_peaks(prof, base=100)
            P('设备帧 HUD 白字行峰：%s' % peaks)
            if len(peaks) >= 2:
                d1, d2 = peaks[0], peaks[1]
                i1 = d1 - REF_ROW1_Y * kx
                i2 = d2 - REF_ROW2_Y * kx
                P('  行1 设备 y=%d ⇒ 按参考 y=%-3d 反解 topInset = %.1f' % (d1, REF_ROW1_Y, i1))
                P('  行2 设备 y=%d ⇒ 按参考 y=%-3d 反解 topInset = %.1f' % (d2, REF_ROW2_Y, i2))
                P('  ⭐ 两个 topInset 之差 = %.1f px ⇒ %s'
                  % (abs(i1 - i2),
                     '**自洽 ✓**（同一套映射；我的参考系窗口在设备帧上依然成立）'
                     if abs(i1 - i2) <= 12 else '**不自洽 ✗**（映射或标定有错）'))
                inset = (i1 + i2) / 2.0
                P('  取 topInset ≈ %.0f（文档记 Redmi 实测 132）' % inset)
                P('')
                # 真机实测：窗口在设备帧里落在哪
                for lbl, ry, rx in (('金币  COIN_HUD', (15, 65), (595, 715)),
                                    ('幸运草 CLOVER_HUD', (70, 120), (655, 735))):
                    dy0 = ry[0] * kx + inset
                    dy1 = ry[1] * kx + inset
                    dx0 = rx[0] * kx
                    dx1 = rx[1] * kx
                    P('  %s：参考 y%-9s x%-10s ⇒ 设备 y %.0f~%.0f  x %.0f~%.0f'
                      % (lbl, str(ry), str(rx), dy0, dy1, dx0, dx1))
                P('    ⇒ 行1 峰 %d 落在金币 y 窗内：%s' % (d1, 15 * kx + inset <= d1 <= 65 * kx + inset))
                P('    ⇒ 行2 峰 %d 落在幸运草 y 窗内：%s'
                  % (d2, 70 * kx + inset <= d2 <= 120 * kx + inset))
                P('')
                # x 方向：量两行的簇心，换算回参考系，和窗口对拍
                for lbl, dyy, rx in (('行1(金币)', d1, (595, 715)),
                                     ('行2(幸运草)', d2, (655, 735))):
                    band = img[max(0, dyy - 22):dyy + 22, :]
                    wc = clusters(white_cols(band))
                    refx = [ctr / kx for _a, _b, ctr, _wd in wc]
                    hit = [v for v in refx if rx[0] <= v <= rx[1]]
                    P('  %s 参考系 x 簇心：%s' % (lbl, ' '.join('%.0f' % v for v in refx)))
                    P('    窗口 x%s 命中 %d 个：%s'
                      % (str(rx), len(hit), ' '.join('%.0f' % v for v in hit) or '（无）'))
                P('')
            # 真值对照
            P('══ 阈值对照（这张截图的肉眼真值）══')
            P('  金币 165531 < 500000 ⇒ `coin_allows_buy` 应为 **False**（不买商人/宝库）')
            P('  幸运草 1   < 8      ⇒ 应 `skip_low_clover` + 剔掉纯大拇指目标')
    txt = '\n'.join(lines)
    try:
        io.open(_OUT, 'w', encoding='utf-8').write(txt)
    except Exception:       # noqa: BLE001
        pass
    print(txt)
    return 0


if __name__ == '__main__':
    sys.exit(main())
