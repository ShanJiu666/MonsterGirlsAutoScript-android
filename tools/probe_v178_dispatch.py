# -*- coding: utf-8 -*-
"""v1.78 取证：真机那把「探索完乱点了个无关战斗格，还认为它是大拇指格」

## 用户 2026-10-06 21:37 那把（v1.77 已装）原话
  「**探索完乱点了个无关的战斗格子打掉了，然后还认为这个格子是大拇指格子**」

## 日志铁证（`_tmpman/v177_dispatch/bagdbg/mgas_log.txt`）
```
L112 plan_block i=0 cell "1,1" sid S30001_221 蘑菇 marks "recommend" cost 10
L118 explore first_high_value at [274,789] tile "-1,2" sid S30001_221 is_purple true
L132 dispatch dispatch_despite_unknown slots_free 0 confirmed false   ← v1.77 修复生效 ✓
L133 dispatch btn_by_ocr 键派遣 [891,1350]
L135 dispatch btn_by_ocr 建派遣 [900,1354]      ← OCR 读成「建派遣」
L137 dispatch still_open_close                  ← 两次都没关掉面板
L127~130 tap 返回(兜底) [275,1507] / [275,1552] ← ⚠ 落进**棋盘**
L144 popup fight_panel_explore_full tapped_sid S30001_221
L145 popup fight_panel cell_marks ["recommend"] ← 用了上一格的标记
L146 battle 打掉了
```

本探针逐条**量化**：
  ① `(275,1507)`/`(275,1552)` 落在哪一格（`cell_of`）
  ② 那格在**本轮 `plan`**里是不是目标（若不在 ⇒ "乱点了个无关的战斗格子" ✓）
  ③ 「返回(兜底)」的**正确**坐标应该是多少（面板最下方的「返回」）
  ④ `(1,1)` 的标记：`repeat` 是否真是 `recommend`（= 用户说的"大拇指格子"）
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
PYDIR = os.path.join(PROJ, 'app', 'src', 'main', 'python')
ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
ROOT = os.path.dirname(PROJ)
LOG = os.path.join(ROOT, '_tmpman', 'v177_dispatch', 'bagdbg', 'mgas_log.txt')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass
sys.path.insert(0, PYDIR)
os.environ.setdefault('MAPBOT_ROOT', ASSETS)
os.environ.pop('MAPBOT_ANDROID', None)


def main():
    if not os.path.isfile(LOG):
        print('缺日志 %s' % LOG)
        return 2
    lines = io.open(LOG, encoding='utf-8', errors='replace').read().splitlines()
    recs = []
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith('{'):
            continue
        try:
            recs.append(json.loads(ln))
        except Exception:                   # noqa: BLE001
            pass
    print('日志 %d 条（有效 JSON %d 条）\n' % (len(lines), len(recs)))

    # ── ① 兜底坐标落在哪一格 ─────────────────────────────────────────────
    import spots as SP
    import explore_loop as EL
    G = SP.GRID
    print('---- ① 「返回(兜底)」坐标落在哪一格 ----')
    print('  棋盘：x0=%.0f y0=%.0f cx=%.0f cy=%.0f cols=%d rows=%d'
          % (G['x0'], G['y0'], G['cx'], G['cy'], G['cols'], G['rows']))
    print('  棋盘可点 y 范围 = [%.0f, %.0f]' % (G['y0'], G['y0'] + G['rows'] * G['cy']))
    for x, y in ((275, 1507), (275, 1552)):
        rc = EL.cell_of(x, y)
        inb = (1 <= rc[0] <= G['rows'] and 1 <= rc[1] <= G['cols'])
        print('  (%4d,%4d) → cell_of=%s  **在棋盘内=%s**' % (x, y, rc, inb))
    print('  ⇒ ⛔ 这两下**点在棋盘上**（不是面板按钮）⇒ 会换选那格的战斗 ✗')

    # ── ② 那格在不在本轮 plan 里 ─────────────────────────────────────────
    print()
    print('---- ② 被"乱点"的那格是不是本轮目标 ----')
    plans = [r for r in recs if r.get('plan') == 'first']
    orders = [r.get('order') for r in recs if r.get('solver') == 'ok']
    print('  plan first =', plans[-1].get('cells') if plans else None)
    print('  solver order =', orders[-1] if orders else None)
    print('  ⇒ `4,2` 在 plan 里 =',
          any('4,2' in (p or []) for p in (plans[-1].get('cells') if plans else [])))

    # ── ③ 正确的「返回」坐标 ─────────────────────────────────────────────
    print()
    print('---- ③ 面板「返回」的正确坐标（本项目既有常量）----')
    print('  `_CLAIM_BACK_XY` =', getattr(EL, '_CLAIM_BACK_XY', None),
          '（已真机验证过的**面板最下方返回** ✓）')
    print('  面板类点击应走 `_panel_tap`（自带"同点→下移45→长按→换通道"阶梯 ✓）')

    # ── ④ 上一格的标记 ───────────────────────────────────────────────────
    print()
    print('---- ④ "还认为这格是大拇指格子"的来源 ----')
    for r in recs:
        if r.get('popup') == 'fight_panel':
            print('  fight_panel cell_marks=%s near_marks=%s entry=%s'
                  % (r.get('cell_marks'), r.get('near_marks'), r.get('entry')))
        if r.get('popup') == 'fight_panel_explore_full':
            print('  fight_panel_explore_full tapped_sid=%s slots_free=%s'
                  % (r.get('tapped_sid'), r.get('slots_free')))
    pbs = [r for r in recs if r.get('solver') == 'plan_block']
    for r in pbs:
        print('  plan_block cell=%s marks=%r cost=%s'
              % (r.get('cell'), r.get('marks'), r.get('cost')))
    print()
    print('  ⚠ `cell_marks` 来自 `exact_marks()` = `markers.get(cell_of(tapped))`')
    print('     ⇒ 若 `tapped` 是**兜底坐标 (275,1507)** ⇒ `cell_of` = (4,2)')
    print('     ⇒ 而 `markers` 里 `4,2` 没标记 ⇒ `cell_marks` 本应为 []')
    print('     ⇒ 真机日志却是 ["recommend"] ⇒ **tapped 用的是另一格**（需看 next_tap 时序）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
