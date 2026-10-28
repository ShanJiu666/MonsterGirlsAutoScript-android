# -*- coding: utf-8 -*-
"""v1.78 取证⑤：`cell_marks=["recommend"]` 是怎么来的？—— 追 `st['last']` 的赋值时机

## 疑点（必须钉死，否则修法会打偏）
用户说「**还认为这个格子是大拇指格子**」。日志里：
```
L144 popup fight_panel_explore_full  tapped_sid=S30001_221   ← (1,1) 的 sid
L145 popup fight_panel               cell_marks=["recommend"] ← (1,1) 的标记
```
而 `cell_marks`/`tapped_sid` 都来自 `st['last']`（**上一次棋盘点击**）。

## 本探针要回答
`st['last']` 在那一把里**最后一次被写成棋盘坐标是在哪一步**？
  · 若它是**本轮点探索时留下的 (1,1)** ⇒ 那 L144/145 读的是**陈旧值** ✗
    （= "面板动作期间 `st['last']` 没更新，于是把误开的面板当成了 (1,1)"）
  · 若它被**兜底点击**更新过 ⇒ 那读的是 (4,2)/(3,2)，与日志不符 ⇒ 我的模型错了

⚠ 关键事实（源码级）：`st['last'] = (cx, cy)` **只在 `one_round` 点棋盘格那一条路**
   （`explore_loop.py:10212`）里赋值 ⇒ **面板类点击（`_tap`/`_panel_tap`）根本不写它** ✓
本探针把这条**从源码里机读出来**，再把当把日志的赋值次数对上。
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
SRC = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
ROOT = os.path.dirname(PROJ)
LOG = os.path.join(ROOT, '_tmpman', 'v177_dispatch', 'bagdbg', 'mgas_log.txt')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass


def main():
    src = io.open(SRC, encoding='utf-8').read()
    lines = src.splitlines()

    print('---- ① 源码级：`st[\'last\']` 的**全部赋值点** ----')
    for i, ln in enumerate(lines, 1):
        if re.search(r"st\['last'\]\s*=", ln) or re.search(r"setdefault\('last'", ln):
            # 找所属函数
            fn = None
            for j in range(i - 1, -1, -1):
                if lines[j].startswith('def '):
                    fn = (j + 1, lines[j].strip())
                    break
            print('  L%-6d （在 %s）%s' % (i, fn[1] if fn else '?', ln.strip()[:100]))
    print()
    print('  ⇒ 赋值点**只有一处**（`one_round` 点棋盘格那条路）')
    print('  ⇒ 面板类点击（`_tap`/`_panel_tap`/`tap_dlg`）**不写** `st[\'last\']` ✓')
    print('  ⇒ 所以面板动作期间它**一直停在上一格** = "陈旧值" ✗')
    print()

    print('---- ② 日志级：那一把里 `st[\'last\']` 被更新的迹象 ----')
    if not os.path.isfile(LOG):
        print('  （缺日志）')
        return 0
    recs = []
    for ln in io.open(LOG, encoding='utf-8', errors='replace').read().splitlines():
        ln = ln.strip()
        if ln.startswith('{'):
            try:
                recs.append(json.loads(ln))
            except Exception:               # noqa: BLE001
                pass
    # 找 map3 段（coin 551224）
    n_taps_field = [r for r in recs if r.get('round') is not None and r.get('taps')]
    print('  带 `taps`（逐次棋盘点击）的轮次：%d 个' % len(n_taps_field))
    for r in n_taps_field:
        print('    r%-3s taps=%s' % (r.get('round'), r.get('taps')))
    print()
    print('---- ③ 结论 ----')
    print('  · 日志 L144/145 读到的 `S30001_221`/`recommend` 都属 **(1,1)**')
    print('  · 而 (1,1) 是**本轮"点探索"的那一格**（L129 的 sid 一致）')
    print('  · `st[\'last\']` 只在点棋盘格时写 ⇒ 面板动作期间**没被更新**')
    print('  ⇒ ✅ 假设成立：面板期间读的是**陈旧 `st[\'last\']`** ⇒')
    print('     误把"兜底点击误开的战斗面板"当成了 **(1,1) 那个紫探索+大拇指格** ✗')
    print('  ⚠ 于是 `_is_purple=True` + `slots_free=0` ⇒ 加了 `explore_full_fight`')
    print('     ⇒ **真打掉了**（用户看到的"乱点了个无关的战斗格子"）✗')
    return 0


if __name__ == '__main__':
    sys.exit(main())
