# -*- coding: utf-8 -*-
"""layout.py · 坐标抽象层（分辨率无关 ✓）

设计原则
--------
① **参考分辨率 1080×1920**（MuMu 默认竖屏 ✓）—— 所有锚点以它为准写成"比例 + 参考像素" ✓
② `Layout.for_screen(w, h)` 按屏幕缩放 ✓
   · 游戏 UI 是**固定竖屏布局** ⇒ 用统一缩放 k = min(w/1080, h/1920) ✓
     并处理宽高比差异（居中/贴边 ✓ 见 anchor() 的 x_mode/y_mode ✓）
③ ⭐ **在 1080×1920 下，本模块算出的坐标必须与原来的硬编码值逐字节相同** ✓
   （见 `self_test()` ✓ 保证重构零回归 ✓）

命名锚点（原来散落在代码里的写死值 ✓ 全部集中到这里）
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# 【Android 适配补丁 · 由 android_autoexplore/tools/port_android.py 注入，勿手改】
# Chaquopy 里 __file__ 指向 APK 内只读资源，模板/数据表在 filesDir/mapbot_pack
#  ⇒ 资源根一律走环境变量，未设置时回退 PC 原行为（便于与 PC 对拍）
import os as _os

_MAPBOT_ROOT = _os.environ.get('MAPBOT_ROOT') or _os.path.dirname(_os.path.abspath(__file__))
_MAPBOT_RUNS = _os.environ.get('MAPBOT_RUNS') or _os.path.join(_MAPBOT_ROOT, 'runs')
_MAPBOT_DT = _os.environ.get('MAPBOT_DT') or _os.path.join(_MAPBOT_ROOT, 'server_datatable.json')
# ─────────────────────────────────────────────────────────────────────────────


import math

REF_W, REF_H = 1080, 1920

# ── 参考分辨率下的锚点（原硬编码值 ✓ 一个都不许改 ✗）────────────────
REF = {
    # 棋盘（spots.GRID 用的那套 ✓）
    'grid_x0': 36, 'grid_y0': 1002, 'grid_cx': 144, 'grid_cy': 144,
    'grid_cols': 7, 'grid_rows': 5,

    # 地块面板：左「探索」右「战斗」
    'explore_btn': (275, 736),
    'fight_y': 735,
    'fight_x_normal': 806,       # 普通格：右列
    'fight_x_boss': 541,         # 首领格：居中
    'fight_x_left': 275,         # 左列（探索侧 ✓）

    # 派遣面板
    'dispatch_btn': (891, 1507),

    # 通用关闭 / 返回
    'close_x_right': 1024,       # 右上角 X
    'close_x_left': 493,         # 左上角 X
    'back_btn': (539, 1212),     # 面板「返回」
    'close_bag': (984, 191),     # 背包右上角关闭
    'bottom_close': (578, 1440), # 结算面板底部关闭
    'end_adv': (539, 772),       # 结束冒险
    'start_adv': (540, 1828),    # 开始冒险（⚠ 点**图标**不是文字：文字 y0=1869/cy=1890，
                                 #   实测点 1889 会点空、1828 才生效 —— 2026-09-28 修）
    'enter_map': (904, 1618),    # 选图界面「进入地图」

    # 探索槽位行（三个格子的 y ✓）
    'slots_y': 899,
    'slots_x': (240, 356, 473),

    # 骰子入口区（奖励区最左 ✓）
    'dice_x_max': 230,
    'dice_y0': 820, 'dice_y1': 1070,

    # 一些"搜索窗口"的范围
    'panel_y0': 600, 'panel_y1': 920,
    'fight_band_y0': 650, 'fight_band_y1': 860,
    'ocr_mid_band': (130, 980),
    'bottom_min_cy': 1100,
    'claim_max_cy': 1700,
}


def _scale_xy(x, y, w, h):
    """把参考坐标 (x,y) 映射到 w×h 屏幕（统一缩放 + 居中/贴边 ✓）"""
    k = min(w / REF_W, h / REF_H)
    # 横向：以参考宽度缩放后居中（宽屏手机左右留黑边时也正确 ✓）
    ox = (w - REF_W * k) / 2.0
    oy = (h - REF_H * k) / 2.0
    return int(round(x * k + ox)), int(round(y * k + oy))


class Layout:
    """一次会话的布局（按实际屏幕尺寸算好所有锚点 ✓）"""

    def __init__(self, w=REF_W, h=REF_H):
        self.w, self.h = int(w), int(h)
        self.k = min(self.w / REF_W, self.h / REF_H)
        self.ox = (self.w - REF_W * self.k) / 2.0
        self.oy = (self.h - REF_H * self.k) / 2.0

    # ── 基础换算 ───────────────────────────────────────────────
    def pt(self, x, y):
        return _scale_xy(x, y, self.w, self.h)

    def sx(self, x):
        return int(round(x * self.k + self.ox))

    def sy(self, y):
        return int(round(y * self.k + self.oy))

    def s(self, v):
        """长度（格距/半径等）缩放 ✓"""
        return v * self.k

    # ── 命名锚点 ───────────────────────────────────────────────
    def __getattr__(self, name):
        ref = REF.get(name)
        if ref is None:
            raise AttributeError(name)
        if isinstance(ref, tuple):
            return self.pt(*ref)
        return ref        # 标量：调用方自己决定用 sy()/s() 还是原值 ✓

    # 便捷访问（常用 ✓）
    @property
    def grid(self):
        return {'x0': self.sx(REF['grid_x0']), 'y0': self.sy(REF['grid_y0']),
                'cx': self.s(REF['grid_cx']), 'cy': self.s(REF['grid_cy']),
                'cols': REF['grid_cols'], 'rows': REF['grid_rows']}

    def cell_center(self, row, col):
        g = self.grid
        return (int(g['x0'] + (col - 0.5) * g['cx']),
                int(g['y0'] + (row - 0.5) * g['cy']))

    def cell_of(self, x, y):
        g = self.grid
        return (int((y - g['y0']) // g['cy']) + 1,
                int((x - g['x0']) // g['cx']) + 1)

    def fight_btn(self, kind='normal'):
        """战斗按钮：首领格居中 ✓ 其它右列 ✓"""
        x = REF['fight_x_boss'] if kind == 'boss' else REF['fight_x_normal']
        return self.pt(x, REF['fight_y'])

    @property
    def explore_btn(self):
        return self.pt(*REF['explore_btn'])

    @property
    def dispatch_btn(self):
        return self.pt(*REF['dispatch_btn'])

    @property
    def slots(self):
        return [self.pt(x, REF['slots_y']) for x in REF['slots_x']]

    def slots_band(self):
        """三个槽位所在的横向条带 (y0,y1)，用于 OCR 限定区域 ✓"""
        y = self.sy(REF['slots_y'])
        hh = int(self.s(60))
        return (y - hh, y + hh)


# ── 全局默认（1080×1920 ✓ 与旧行为完全一致 ✓）────────────────────
DEFAULT = Layout(REF_W, REF_H)


def for_screen(w, h):
    return Layout(w, h)


def detect_screen(bot_or_size):
    """从 Bot 或 (w,h) 得到 Layout ✓"""
    if isinstance(bot_or_size, (tuple, list)):
        return Layout(*bot_or_size)
    img = bot_or_size.img()
    h, w = img.shape[:2]
    return Layout(w, h)


def self_test(verbose=True):
    """⭐ 零回归自检：1080×1920 下所有锚点必须与参考值**逐字节相同** ✓"""
    L = Layout(REF_W, REF_H)
    bad = []
    for name, ref in REF.items():
        if isinstance(ref, tuple) and len(ref) == 2:      # 只校验坐标点 ✓
            got = L.pt(*ref)
            if got != tuple(ref):
                bad.append((name, ref, got))
    # 棋盘
    g = L.grid
    for k2, v in (('x0', REF['grid_x0']), ('y0', REF['grid_y0']),
                  ('cx', REF['grid_cx']), ('cy', REF['grid_cy'])):
        if g[k2] != v:
            bad.append(('grid.' + k2, v, g[k2]))
    # 常用按钮
    checks = [('explore_btn', L.explore_btn, REF['explore_btn']),
              ('dispatch_btn', L.dispatch_btn, REF['dispatch_btn']),
              ('fight_normal', L.fight_btn('normal'),
               (REF['fight_x_normal'], REF['fight_y'])),
              ('fight_boss', L.fight_btn('boss'), (REF['fight_x_boss'], REF['fight_y']))]
    for name, got, want in checks:
        if tuple(got) != tuple(want):
            bad.append((name, want, got))
    if verbose:
        print('=== layout 零回归自检（1080×1920）===')
        print('   检查项: %d 个锚点 + 棋盘 4 项 + 按钮 4 项' % len(REF))
        if bad:
            for n, want, got in bad:
                print('   ✗ %-18s 期望 %s 实得 %s' % (n, want, got))
        else:
            print('   ✓ 全部与旧硬编码值完全一致')
    return not bad


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 2:
        L = Layout(int(sys.argv[1]), int(sys.argv[2]))
        print('屏幕 %dx%d  缩放 k=%.4f  偏移 (%.1f, %.1f)'
              % (L.w, L.h, L.k, L.ox, L.oy))
        print('  棋盘:', L.grid)
        print('  探索按钮:', L.explore_btn, ' 派遣按钮:', L.dispatch_btn)
        print('  战斗(普通):', L.fight_btn('normal'), ' 战斗(首领):', L.fight_btn('boss'))
        print('  槽位:', L.slots)
    else:
        ok = self_test()
        raise SystemExit(0 if ok else 1)
