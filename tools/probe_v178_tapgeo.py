# -*- coding: utf-8 -*-
"""v1.78 取证④：那 4 下「返回(兜底)」在**设备上**到底点到了哪里？

用户原话：「**探索完乱点了个无关的战斗格子打掉了，然后还认为这个格子是大拇指格子**」

## 为什么要算这个
`_panel_tap(275,1507)` 的阶梯有 **4 级**，其中第 4 级会**换通道**（`ch=dlg`）：
    ladder = [(x,y,ch,'again'), (x,y+45,ch,'below'), (x,y,ch,'hold'),
              (x,y, **换通道**, 'cross')]
而两个通道的 y 映射**不一样**（`RefMapper.devY` vs `devYDialog`，差 C）：
    devY(y)       = y*kx + shift          （锚底段）
    devYDialog(y) = screenH/2 + (y-960)*kx
⇒ **同一个参考 y 在两条通道上落到设备的两个不同高度** ⇒ 换通道那一下会**偏移 C** ✗

本探针把这 4 级的**设备坐标**与**反算回参考系的落点**都算出来，
再用 `cell_of` 判断有没有落进棋盘。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
os.environ.setdefault('MAPBOT_ROOT', ASSETS)
os.environ.pop('MAPBOT_ANDROID', None)
sys.path.insert(0, PYDIR)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass

# 真机 Redmi 25053RT47C 实测参数（日志里 C=209 ⇒ 由这里推出）
SCREEN_W, SCREEN_H = 1280, 2772
REF_W, REF_H = 1080, 1920
TOP_SPLIT = 300


def main():
    kx = SCREEN_W / float(REF_W)
    shift = SCREEN_H - REF_H * kx
    top_inset = 132.0                       # 文档记 Redmi 实测（不影响本算）
    print('设备 %dx%d   kx=%.4f   shift=%.1f   topInset=%.1f'
          % (SCREEN_W, SCREEN_H, kx, shift, top_inset))
    C = REF_H / 2.0 + (shift - SCREEN_H / 2.0) / kx
    print('dialogShift C = %.1f   （真机日志里 `"C": 209` ⇒ 与这里一致 ✓）' % C)

    def dev_y_norm(y):
        return y * kx + shift

    def dev_y_dlg(y):
        return SCREEN_H / 2.0 + (y - REF_H / 2.0) * kx

    def ref_y_from_dev(dy):
        """设备 y → 参考 y（锚底段反算，即 `toRef` 用的那一段）"""
        return TOP_SPLIT + (dy - (TOP_SPLIT * kx + shift)) / kx

    # 棋盘几何
    import types
    for _m, _at in (('rapidocr_onnxruntime', {'RapidOCR': type('RapidOCR', (), {'__init__': lambda *a, **k: None})}),
                    ('airtest', {'core': None}), ('airtest.core', {}),
                    ('airtest.core.api', {'connect_device': lambda *a, **k: None,
                                          'snapshot': lambda *a, **k: None,
                                          'touch': lambda *a, **k: None,
                                          'swipe': lambda *a, **k: None,
                                          'keyevent': lambda *a, **k: None,
                                          'exists': lambda *a, **k: None,
                                          'Template': object}),
                    ('airtest.core.cv', {'Template': object}),
                    ('java', {}), ('java.android', {}), ('java.lang', {}),
                    ('java.util', {}), ('java.util.concurrent', {})):
        try:
            __import__(_m)
        except Exception:                   # noqa: BLE001
            m = types.ModuleType(_m)
            for _k, _v in _at.items():
                setattr(m, _k, _v)
            sys.modules[_m] = m
    import spots as SP
    import explore_loop as EL
    G = SP.GRID
    y0, y1 = G['y0'], G['y0'] + G['rows'] * G['cy']
    print('棋盘参考系 y ∈ [%.0f, %.0f]  ⇒ 设备 y ∈ [%.0f, %.0f]'
          % (y0, y1, dev_y_norm(y0), dev_y_norm(y1)))
    print()

    ladder = [(275, 1507, 'norm', 'again'), (275, 1552, 'norm', 'below'),
              (275, 1507, 'norm', 'hold'), (275, 1507, 'dlg', 'cross')]
    print('-' * 96)
    print('%-6s %-10s %-18s %-12s %-12s %s'
          % ('级', '模式', '参考(面板系)坐标', '设备 y', '回算参考 y', '落点 cell_of'))
    print('-' * 96)
    for i, (x, y, ch, mode) in enumerate(ladder, 1):
        dy = dev_y_dlg(y) if ch == 'dlg' else dev_y_norm(y)
        ry = ref_y_from_dev(dy)
        rc = EL.cell_of(x, ry)
        inb = (1 <= rc[0] <= G['rows'] and 1 <= rc[1] <= G['cols'])
        print('%-6d %-10s (%4d,%4d) %-4s %-8.0f %-12.0f %s %s'
              % (i, mode, x, y, ch, dy, ry, rc,
                 '⛔**在棋盘内**' if inb else '面板区 ✓'))
    print('-' * 96)
    print()
    print('⚠ 结论：**第 4 级（换通道 cross）会偏 C≈%.0f px** ⇒ 落点与 1~3 级不同；' % C)
    print('   若其中任何一级落进棋盘 ⇒ 那一下点的是**棋盘格**、会误开那一格的战斗面板 ✗')
    print()
    print('✅ 安全的兜底应当：① 用**棋盘外**的坐标，或 ② 直接 `b.back()`（系统返回键）——')
    print('   返回键**不可能**点到棋盘 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
