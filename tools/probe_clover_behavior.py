# -*- coding: utf-8 -*-
"""v1.63 行为验证（B14）：`clover_count()` 在**真机 HUD 形状**的 OCR 条目上读得对不对

## 为什么用"合成条目"而不是真 OCR
手机端 OCR 在 Java 壳里（`mapbot._AndroidOcr`）⇒ **离线跑不了** ✗
但**坐标是真机测出来的**（`tools/probe_clover_row.py` 分行量白字簇，6 张帧）：
    行1(cy≈40)：PID:162332 @(200,40) ｜ Ver:1.0.2.7 @(390,40) ｜ **357731** @(650,40) ← 金币
    行2(cy≈94)：**2037/2100** @(337,94) ← 体力 ｜ **1** @(693,94) ← 幸运草 ｜ **0** @(905,94) ← 大拇指
⇒ 用这些**真实坐标**造条目 ⇒ 检验 `clover_count` 会不会误取金币/体力 ✓

用法：python android_autoexplore\\tools\\probe_clover_behavior.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, _PY)
os.environ.setdefault('MAPBOT_ROOT', _ASSETS)
os.environ.pop('MAPBOT_ANDROID', None)

import types                                 # noqa: E402


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

import explore_loop as EL                   # noqa: E402

# 真机 HUD 坐标（`probe_clover_row.py` 实测）
def hud(items_clover):
    return [
        {'text': 'PID:162332', 'cx': 200, 'cy': 40},
        {'text': 'Ver:1.0.2.7', 'cx': 390, 'cy': 40},
        {'text': '357731', 'cx': 650, 'cy': 40},        # ← 金币（第 1 行；不许误取 ✗）
        {'text': '2037/2100', 'cx': 337, 'cy': 94},      # ← 体力（不许误取 ✗）
        {'text': str(items_clover), 'cx': 693, 'cy': 94},  # ← 幸运草 ✓
        {'text': '0', 'cx': 905, 'cy': 94},              # ← 大拇指（不许误取 ✗）
    ]


def main():
    fails = []
    print('CLOVER_HUD_X = %s  CLOVER_HUD_Y = %s  MIN = %s'
          % (EL.CLOVER_HUD_X, EL.CLOVER_HUD_Y, EL.CLOVER_MIN_REROLL))
    print()
    print('%-10s %-10s %-8s %s' % ('真值', '读出', '期望', '判定'))
    print('-' * 60)
    for want in (1, 3, 5, 7, 8, 9, 12, 100):
        got = EL.clover_count(hud(want))
        ok = (got == want)
        if not ok:
            fails.append((want, got))
        print('%-10s %-10s %-8s %s' % (want, got, want, '✓' if ok else '**✗**'))
    # 读不到 ⇒ None（不猜）
    got = EL.clover_count([])
    print('%-10s %-10s %-8s %s' % ('(空)', got, None, '✓' if got is None else '**✗**'))
    if got is not None:
        fails.append(('empty', got))
    # 只有金币那一行（不该被当幸运草）
    only_coin = [{'text': '357731', 'cx': 650, 'cy': 40}]
    got = EL.clover_count(only_coin)
    print('%-10s %-10s %-8s %s' % ('仅金币行', got, None, '✓' if got is None else '**✗**'))
    if got is not None:
        fails.append(('coin-only', got))
    # 只有体力
    only_stam = [{'text': '2037/2100', 'cx': 337, 'cy': 94}]
    got = EL.clover_count(only_stam)
    print('%-10s %-10s %-8s %s' % ('仅体力', got, None, '✓' if got is None else '**✗**'))
    if got is not None:
        fails.append(('stam-only', got))
    print()
    print('=' * 60)
    if fails:
        print('❌ %d 项不符：%s' % (len(fails), fails))
        return 1
    print('✅ 全部通过：读数正确；金币/体力/大拇指数**不会被误取**；读不到返回 None')
    print('   ⇒ 门槛判定：')
    for v in (1, 7, 8, 9, 12):
        skip = (v is not None and v < EL.CLOVER_MIN_REROLL)
        print('      幸运草 %-3d ⇒ %s' % (v, '**跳过摇色子**' if skip else '照常摇'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
