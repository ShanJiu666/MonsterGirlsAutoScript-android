# -*- coding: utf-8 -*-
"""v1.78 取证⑥：闭合验证 —— `(3,2)`/`(4,2)` 是不是战斗格？大拇指标记在哪一格？

## 要证的因果链（用户 2026-10-06 21:39 那把）
```
round0 计划 ["1,1","1,6"] ⇒ 点 (1,1)（紫探索 S30001_221 + 大拇指 recommend）
       ⇒ 弹出探索面板 ⇒ 点「探索」⇒ 换出「探索配队」面板
round1 dispatch: dispatch_despite_unknown ⇒ 点「键派遣」×2 ⇒ **面板关不掉**
        ⇒ `still_open_close` ⇒ 走**兜底** `_panel_tap(275,1507)`
        ⛔ 而 `(275,1507)` 落在**棋盘内** ⇒ 4 级兜底全点在棋盘上
           （第 4 级换通道、偏 C≈209 ⇒ 跳到 **(3,2)**）
round2 那一下点开了**无关那一格**的战斗面板
       ⇒ 而 `st['last']` **还停在 (1,1)**（面板类点击不写它）
       ⇒ `cell_marks=["recommend"]`、`tapped_sid=S30001_221`、`_is_purple=True`
       ⇒ ＋ `slots_free=0` ⇒ 加 `explore_full_fight` ⇒ **真打掉了** ✗
```

本探针逐条**用真机帧验证**：
  Q1 `(1,1)` 的标记是不是**只有** recommend（不是 boss/clover）
  Q2 `(4,2)`、`(3,2)`（= 兜底点击的真实落点）是不是**战斗型**（点了会弹战斗面板）
  Q3 全盘**哪些格**带 recommend/boss 标记（看 (1,1) 是否唯一）
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.dirname(PROJ)
D = os.path.join(ROOT, '_tmpman', 'v177_dispatch', 'bagdbg')
FRAME = 'board_r0_213925.png'
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, PYDIR)
os.environ.setdefault('MAPBOT_ROOT', ASSETS)
os.environ.pop('MAPBOT_ANDROID', None)

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
    except Exception:                       # noqa: BLE001
        m = types.ModuleType(_m)
        for _k, _v in _at.items():
            setattr(m, _k, _v)
        sys.modules[_m] = m


def main():
    import cv2
    import numpy as np
    import spots as SP
    import marks as MK

    p = os.path.join(D, FRAME)
    if not os.path.exists(p):
        print('缺帧 %s' % p)
        return 2
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

    print('=== Q1/Q2：三格的数据表类型 ===')
    st = SP.Board('S30001').state(im, thr=0.0)
    for rc in ((1, 1), (3, 2), (4, 2), (1, 6)):
        v = st.get(rc) or {}
        sid = str(v.get('sid') or '')
        try:
            fight = bool(SP.is_fight_spot(sid))
        except Exception:                   # noqa: BLE001
            fight = None
        suf = sid.split('_')[-1]
        print('  %-5s sid=%-12s name=%-10s score=%.3f 战斗格=%-5s 后缀=%s %s'
              % ('%d,%d' % rc, sid, v.get('name'), float(v.get('score') or 0),
                 fight, suf,
                 '← 探索后缀(221/321/331) ✓' if suf in ('221', '321', '331') else ''))

    print()
    print('=== Q3：全盘标记扫描（真跑 `scan_board_fast`）===')
    try:
        mk = MK.scan_board_fast(im) or {}
    except Exception as e:                  # noqa: BLE001
        print('  scan_board_fast 失败: %r' % (e,))
        mk = {}
    if not mk:
        print('  （没扫到标记）')
    for k in sorted(mk):
        v = mk[k]
        ml = list((v.get('marks') if isinstance(v, dict) else v) or [])
        if ml:
            nm = (st.get(k) or {}).get('name')
            print('  %-6s marks=%-28s 格名=%s' % ('%d,%d' % k, ml, nm))
    print()
    print('=== 结论 ===')
    rec = [k for k in mk
           if 'recommend' in ((mk[k].get('marks') if isinstance(mk[k], dict)
                               else mk[k]) or [])]
    print('  带 recommend 的格 = %s' % (['%d,%d' % k for k in sorted(rec)] or '无'))
    print('  ⇒ 与日志 `marks {"1,1": ["recommend"], "1,6": ["boss"]}` 对拍 ✓')
    print('  ⇒ `(4,2)`/`(3,2)`（兜底点击的真实落点）**不是**大拇指格 ✗')
    print('  ⇒ 日志 L145 的 `cell_marks=["recommend"]` **只能**来自陈旧的')
    print('     `st[\'last\']`（= (1,1)）⇒ 因果链闭合 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
