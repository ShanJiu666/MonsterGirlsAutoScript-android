# -*- coding: utf-8 -*-
"""v1.77 取证②：真机帧上**直接跑 OCR**，看槽位行到底读成什么

用户在真机上报「**探索紫地块不正常，派遣不出去**」＋「**点不到一键派遣**」。
日志铁证（`_tmpman/v176_dispatch/bagdbg/mgas_log.txt`）每张图都死循环：
    round N    free_txt:1 busy:2  slots_free=1 → explore（点探索 ✓）
    round N+1  free_txt:0 busy:1  slots_free=0 → dispatch: skip_slots_full ✗（关面板）
⚠ 但同期的 `board_r*.png` 上**明明有「空闲」**（见 `_tmpman/slotrow177/*band2x.png`）
⇒ 要区分两种可能：
  (a) 那一轮的帧**真的没有**「空闲」（比如面板盖住了）—— 那是"时序"问题
  (b) 帧上有，只是 `b.ocr` 在**本轮这一帧**上漏读了 —— 那是"判据/裁带"问题

本探针把每张 `board_r*.png` 当成本轮帧，直接用**生产同款** `Bot.ocr` 跑一遍，
打印：① 命中「空闲」的条目数 ② 倒计时数 ③ `explore_slots_free` 的结论
     ④ 那些条目在参考系里的 y（看有没有落在槽位行 880~1000）
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.dirname(PROJ)
FRAMES = os.path.join(ROOT, '_tmpman', 'v176_dispatch', 'bagdbg')
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


for _m, _at in (('airtest', {'core': None}), ('airtest.core', {}),
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
import explore_loop as EL                   # noqa: E402


def main():
    if not os.path.isdir(FRAMES):
        print('缺帧目录')
        return 2
    files = sorted(f for f in os.listdir(FRAMES) if f.startswith('board_r'))
    print('帧 %d 张\n' % len(files))
    for fn in files:
        im = cv2.imdecode(np.fromfile(os.path.join(FRAMES, fn), dtype=np.uint8),
                          cv2.IMREAD_COLOR)
        if im is None:
            continue
        # 用生产同款的 OCR 入口（只 OCR，不驱动设备）
        try:
            items = EL.ocr_image(im) if hasattr(EL, 'ocr_image') else None
        except Exception as e:              # noqa: BLE001
            items = None
            print('%s  ocr_image 失败: %r' % (fn, e))
        if items is None:
            continue
        free = [i for i in items if '空闲' in (i.get('text') or '')]
        nfree, info = EL.explore_slots_free(items)
        # 打印槽位行附近的条目
        band = [i for i in items
                if 860 <= float(i.get('cy') or 0) <= 1020]
        print('%-26s 条目=%-3d  「空闲」=%-2d  倒计时=%s  → explore_slots_free=%s'
              % (fn, len(items), len(free), info, nfree))
        for i in band:
            print('      y=%-5s x=%-5s %r'
                  % (i.get('cy'), i.get('cx'), (i.get('text') or '')[:40]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
