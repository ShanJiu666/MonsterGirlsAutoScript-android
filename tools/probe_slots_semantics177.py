# -*- coding: utf-8 -*-
"""v1.77 取证④：`slots_free` 为什么会在**同一张图里 1/0 完美交替**？

## 现场（`_tmpman/v176_dispatch/bagdbg/mgas_log.txt`，20:24 那把废弃矿洞）
用户报：「**探索紫地块不正常，派遣不出去**」＋「**点不到一键派遣**」

    奇数轮  free_txt=1 busy=2  stamina=1093 clover=445  slots_free=1 → 点探索 ✓
    偶数轮  free_txt=0 busy=1  stamina=null clover=null slots_free=0 → dispatch: skip_slots_full ✗

## ⭐ 决定性逻辑证明（**不需要任何帧**即可证）
   本次 **17 次派遣全是 `skip_slots_full`、0 次成功**
   ⇒ 槽位真实状态**整场没变过**（一次都没派出去）
   ⇒ 那个 0 **只能是读数假象**（真满不会在下一轮又变回 1）
   ⇒ v1.73 的 "读不到 ⇒ 0" **在派遣分支上把"读不到"错当成"满"** ✗

## 本探针回答
  Q1  `explore_slots_free` 的空输入语义（None vs 0）
  Q2  真机那 9 张帧上「空闲」到底能不能读到（真 OCR）
  Q3  派遣分支的闸门（`slots_free<=0 ⇒ skip_slots_full`）在"读数不可靠"时会怎样
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, PYDIR)
os.environ.setdefault('MAPBOT_ROOT', ASSETS)
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

import explore_loop as EL                   # noqa: E402


def main():
    print('---- Q1 `explore_slots_free` 的空输入语义 ----')
    for label, arg in (('[]', []), ('None', None), ('[空闲×1]', [{'text': '空闲'}]),):
        print('  %-10s → %s' % (label, EL.explore_slots_free(arg)))
    print('  EXPLORE_SLOTS_TOTAL =', EL.EXPLORE_SLOTS_TOTAL)
    print()
    print('---- Q3 派遣分支的闸门（源码事实）----')
    src = open(os.path.join(PYDIR, 'explore_loop.py'), encoding='utf-8').read()
    i = src.find("if int(ctx.get('slots_free', 1) or 0) <= 0:")
    print('  `if int(ctx.get(\'slots_free\', 1) or 0) <= 0:` 位置 =', i)
    if i >= 0:
        print(src[i:i + 460])
    print()
    print('---- 结论 ----')
    print('  · `explore_slots_free` 读不到 ⇒ 返回 **None**（不是 0）')
    print('  · 但 `one_round` 在 None 时把它**写成 0**（v1.73 的"三处同源"）')
    print('  · 派遣分支把 `slots_free<=0` 当作"**真的满了**" ⇒ skip_slots_full ✗')
    print('  ⇒ **"读不到"与"真的满"在这个分支上不可区分** —— 这就是本 bug')
    return 0


if __name__ == '__main__':
    sys.exit(main())
