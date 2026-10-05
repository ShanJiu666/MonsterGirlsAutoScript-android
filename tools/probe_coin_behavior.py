# -*- coding: utf-8 -*-
"""v1.63b 行为验证：`coin_count` / `coin_allows_buy` / `clover_count` 读得对不对

## 为什么用"合成条目"（真机 HUD 坐标）而不是真 OCR
手机端 OCR 在 Java 壳里（`mapbot._AndroidOcr`）⇒ **离线跑不了** ✗
但坐标是**真机实测的**（`tools/probe_clover_row.py` 分行量白字簇，6 张帧）：
    行1(cy≈40)：PID:162332 @(200,40) ｜ Ver:1.0.2.7 @(390,40) ｜ **金币 357731** @(650,40)
    行2(cy≈94)：**2037/2100** @(337,94) ← 体力 ｜ **幸运草 3** @(693,94) ｜ **大拇指 0** @(905,94)

## 两条硬判据（真值来自**用户口径**，不是被测代码）
  ① `coin_count` 只认**第 1 行**那个数 ⇒ **绝不能**把第 2 行的幸运草/大拇指数当金币 ✗
     （⚠ v1.63 第一版把两行混着量 ⇒ 金币被当幸运草 ✗ 这个坑必须守住）
  ② `coin_allows_buy`：`< 500000` ⇒ False（不买）；`≥ 500000` ⇒ True（正常买）；
     **`None`（读不到）⇒ True**（fail-open，宁可买也别整图不买 ✓）

用法：python android_autoexplore\\tools\\probe_coin_behavior.py
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


def hud(coin, clover=3, thumb=0):
    """真机 HUD 坐标造的条目（`probe_clover_row.py` 实测）"""
    return [
        {'text': 'PID:162332', 'cx': 200, 'cy': 40},
        {'text': 'Ver:1.0.2.7', 'cx': 390, 'cy': 40},
        {'text': str(coin), 'cx': 650, 'cy': 40},        # ← 金币（第 1 行）✓
        {'text': '2037/2100', 'cx': 337, 'cy': 94},      # ← 体力
        {'text': str(clover), 'cx': 693, 'cy': 94},      # ← 幸运草（第 2 行）⚠ 别当金币
        {'text': str(thumb), 'cx': 905, 'cy': 94},       # ← 大拇指 ⚠ 别当金币
    ]


def main():
    fails = []
    print('COIN_HUD_X=%s  COIN_HUD_Y=%s  COIN_MIN_BUY=%s'
          % (EL.COIN_HUD_X, EL.COIN_HUD_Y, EL.COIN_MIN_BUY))
    print('CLOVER_HUD_X=%s  CLOVER_HUD_Y=%s' % (EL.CLOVER_HUD_X, EL.CLOVER_HUD_Y))
    print()

    print('=== ① `coin_count` 读数（真值 = 我喂进去的金币） ===')
    print('%-12s %-10s %-8s %s' % ('金币真值', '读出', '期望', '判定'))
    for want in (0, 1, 499999, 500000, 500001, 357731, 98765432):
        got = EL.coin_count(hud(want))
        ok = (got == want)
        if not ok:
            fails.append(('coin_count', want, got))
        print('%-12s %-10s %-8s %s' % (want, got, want, '✓' if ok else '**✗**'))
    print()

    print('=== ② ⚠⚠ 反取守门：**不能**把第 2 行的幸运草/大拇指数当金币 ===')
    only_row2 = [
        {'text': '2037/2100', 'cx': 337, 'cy': 94},
        {'text': '3', 'cx': 693, 'cy': 94},          # 幸运草
        {'text': '0', 'cx': 905, 'cy': 94},          # 大拇指
    ]
    got = EL.coin_count(only_row2)
    ok = (got is None)
    if not ok:
        fails.append(('coin_row2_leak', None, got))
    print('   只有第 2 行 ⇒ 读出 %-8s 期望 None  %s' % (got, '✓' if ok else '**✗ 串行了**'))
    got = EL.clover_count(only_row2)
    ok2 = (got == 3)
    if not ok2:
        fails.append(('clover_row2', 3, got))
    print('   `clover_count` 同输入 ⇒ %-8s 期望 3     %s' % (got, '✓' if ok2 else '**✗**'))
    # 反向：只有金币那一行时，clover_count 不该读出来
    only_row1 = [{'text': '357731', 'cx': 650, 'cy': 40}]
    got = EL.clover_count(only_row1)
    ok3 = (got is None)
    if not ok3:
        fails.append(('clover_row1_leak', None, got))
    print('   只有第 1 行时 `clover_count` ⇒ %-8s 期望 None  %s'
          % (got, '✓' if ok3 else '**✗ 串行了**'))
    print()

    print('=== ③ `coin_allows_buy`（用户口径：低于 50 万拉黑，高于正常买） ===')
    print('%-12s %-10s %-8s %s' % ('金币', '判定', '期望', '说明'))
    for n, want in ((None, True), (0, False), (499999, False), (500000, True),
                    (500001, True), (1000000, True)):
        got = EL.coin_allows_buy(n)
        ok = (got is want)
        if not ok:
            fails.append(('allows_buy', (n, want), got))
        note = ('读不到 ⇒ 照常买（fail-open ✓）' if n is None
                else ('低于 50 万 ⇒ **不买**' if n < EL.COIN_MIN_BUY else '正常买 ✓'))
        print('%-12s %-10s %-8s %s' % (n, got, want, note))
    print()

    print('=' * 66)
    if fails:
        print('❌ %d 项不符：%s' % (len(fails), fails))
        return 1
    print('✅ 全部通过：金币/幸运草**按行分得清**（不会互相串）；')
    print('   门槛判定正确；读不到 ⇒ 照常买（方向安全 ✓）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
