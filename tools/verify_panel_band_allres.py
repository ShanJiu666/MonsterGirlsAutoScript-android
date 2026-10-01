# -*- coding: utf-8 -*-
"""verify_panel_band_allres.py · 宝库/商人面板 **OCR 搜索带** 的 9 分辨率审计（v1.20 新增）

## 背景（v1.20 修的真 bug）

`buypanels._items()` 在**归一化帧**按 `BAND` 裁一段做 OCR，条目 `cy` 再由
`dlg_items()` **加 C** 变成弹窗系，最后 `_btn` / `_back_btn` 按**弹窗系** y 带筛选。

⇒ 判据元素在**归一化系**里的位置 = `dlg_y − C`，而
   `C = 960 + (shift − H/2)/kx` **随分辨率变**（9:16 ⇒ 0，真机 1264×2780 ⇒ 227.7）。

旧 `BAND = (300, 1560)` 的上界是按 9:16（C=0）定的 ⇒ 在**宽屏矮胖**（C<0，元素下移）
上盖不住：1200×1920 上购买钮归一化 y = **1594**、价格 **1637** ⇒ 全部 OCR 不到
⇒ `_btn` 恒 `(None,None,None)` ⇒ `no_select_btn` ⇒ **整层不买不选**（静默失效）。

⇒ 与 v1.19 摇色子同一族病（搜索带写死在 9:16 上）。本工具把这个结论钉成断言。

## 断言

    ① 每个**判据元素**在每个分辨率上必须落在 BAND 内
    ② BAND 下界必须 ≤ 300（再往上是被 toRef 丢弃的弹性区，取不到）
    ③ 旧上界 1560 **确实**盖不住宽屏（= 证明修的是真 bug，防"改回去"）
    ④ 9:16 基线上 C=0 ⇒ BAND 改动不得影响基线行为（回归防护）
    ⑤ 宽屏最坏值与新上界之间留有余量（文案行数浮动）

用法：python tools/verify_panel_band_allres.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
PYD = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
sys.path.insert(0, PYD)
os.environ.setdefault('MAPBOT_ROOT', PYD)
os.environ.setdefault('MAPBOT_RUNS', os.path.join(ROOT, 'mapbot_pc', 'runs'))
os.environ.setdefault('MAPBOT_DT', os.path.join(ROOT, 'data', 'server_datatable.json'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import buypanels as BP          # noqa: E402

REF_W, REF_H = 1080, 1920
RES = [(720, 1280, '9:16 低'), (1080, 1920, '9:16 基线'), (1440, 2560, '9:16 高'),
       (1080, 2340, '20:18'), (1080, 2400, '20:9'), (1170, 2532, 'iPhone'),
       (1200, 1920, '5:4 宽'), (1264, 2780, '真机RMX3800'), (1280, 2772, '真机Redmi')]

# 判据元素：(名字, dlg_y, 用途) —— 都是**被 OCR 后按 y 带筛选**的，不是 tap_dlg 直点
ELEMS = [
    ('购买钮', 1498, '_btn 带 1360~1660（弹窗系）'),
    ('价格', 1541, '_btn 数字价（同带）'),
    ('返回.判据下', 1120, 'VAULT_BACK_ZONE 1240−120'),
    ('返回.判据上', 1360, 'VAULT_BACK_ZONE 1240+120'),
    ('返回.兜底上界', 1520, '_back_btn 文字兜底 900~1520'),
    ('确定.下界', 800, '_confirm cy>800'),
]
OLD_BAND = (300, 1560)        # v1.20 之前的值（保留用于断言③）
MARGIN = 40                   # 新上界与最坏值之间必须留的余量


def c_of(W, H):
    k = W / REF_W
    shift = H - REF_H * k
    return 960 + (shift - H / 2) / k


def main():
    BAND = BP.BAND
    fails = []
    print('=' * 96)
    print('宝库/商人面板 OCR 搜索带 BAND = %s  （9 分辨率审计）' % (BAND,))
    print('=' * 96)
    print('%-16s %6s %-30s | %s' % ('判据元素', 'dlg_y', '用途',
                                    '  '.join('%-10s' % l for _, _, l in RES)))
    worst = 0.0
    for name, dy, why in ELEMS:
        cells = []
        for (W, H, label) in RES:
            ny = dy - c_of(W, H)
            worst = max(worst, ny)
            ok = BAND[0] <= ny <= BAND[1]
            cells.append('%-10s' % ('%6.0f%s' % (ny, 'OK' if ok else 'XX')))
            if not ok:
                fails.append('BAND 盖不住 %s @%s（归一化 y=%.0f）' % (name, label, ny))
        print('%-16s %6d %-30s | %s' % (name, dy, why[:29], '  '.join(cells)))

    print()
    # ② 下界：再往上是被 toRef 丢弃的弹性区
    if BAND[0] > 300:
        fails.append('BAND 下界 %d > 300：会伸进被 toRef 丢弃的弹性区' % BAND[0])
    else:
        print('[ok] BAND 下界 %d ≤ 300（不伸进被 toRef 丢弃的弹性区）' % BAND[0])

    # ③ 旧上界确实盖不住宽屏（证明修的是真 bug）
    old_bad = [l for (W, H, l) in RES
               if 1498 - c_of(W, H) > OLD_BAND[1]]
    if not old_bad:
        fails.append('旧上界 %d 竟盖住了所有分辨率 ⇒ 这条断言失去意义（要么 bug 不存在，要么常量被改）'
                     % OLD_BAND[1])
    else:
        print('[ok] 旧上界 %d 确实盖不住：%s（= v1.20 修的是真 bug）'
              % (OLD_BAND[1], '、'.join(old_bad)))

    # ④ 9:16 基线 C=0
    c9 = c_of(1080, 1920)
    if abs(c9) > 1e-6:
        fails.append('9:16 基线 C 应为 0，实为 %.3f（锚定模型公式被改？）' % c9)
    else:
        print('[ok] 9:16 基线 C=0（与 PC 口径一致，dlg 系与归一化系同值）')

    # ⑤ 余量
    if worst > BAND[1] - MARGIN:
        fails.append('上界余量不足：最坏 %.0f，新上界 %d，余量 %d < %d'
                     % (worst, BAND[1], BAND[1] - worst, MARGIN))
    else:
        print('[ok] 余量 %dpx：最坏判据元素 %.0f ≤ 上界 %d（文案行数浮动有空间）'
              % (BAND[1] - worst, worst, BAND[1]))

    print()
    if fails:
        print('FAIL %d' % len(fails))
        for f in fails:
            print('  - %s' % f)
        return 1
    print('ALL PASS (%d 分辨率 × %d 判据元素）' % (len(RES), len(ELEMS)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
