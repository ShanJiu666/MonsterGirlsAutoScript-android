# -*- coding: utf-8 -*-
"""v1.63 核对（B11b）：手机端 `popups()` 里**战斗分支 vs 探索分支**的结构

## 为什么要核
PC 的真根因是「**紫/橙格的面板标题被识别成「战斗事件」⇒ 被战斗分支先接住**」
⇒ 既没探索、也没打 ✗（`slots_free>0` 时战斗分支里那条"槽满才打"不成立 ⇒ `mk=[]`
  ⇒ 掉进 `if not mk:` ⇒ **面板被关掉**）

PC 修法：在战斗分支**最前面**加一条 —— 紫/橙格 + 有空闲槽 ⇒ **改走探索** ✓

⇒ 手机端要不要加，取决于**两件事**：
  ① 两个分支的**先后顺序**（战斗在前才有这个病）
  ② 那两块代码**是不是兄弟**（不是嵌套 ⇒ 战斗分支 return 后探索分支才有机会）

用法：python android_autoexplore\\tools\\probe_popup_order.py
"""
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
P = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')


def main():
    s = io.open(P, encoding='utf-8').read()
    lines = s.splitlines()
    i = s.index('def popups(')
    j = s.index('\ndef ', i + 10)
    seg = s[i:j]
    base = s[:i].count('\n') + 1
    print('`popups()` 从 L%d 开始，共 %d 行' % (base, seg.count('\n')))
    print()
    print('=== 顶层分支（`    if ...` / `    elif ...`，缩进 4 空格）===')
    for m in re.finditer(r'^    (if|elif) (.*)$', seg, re.M):
        ln = base + seg[:m.start()].count('\n')
        print('  L%-6d %-5s %s' % (ln, m.group(1), m.group(2)[:96]))
    print()
    # 找"战斗"与"探索"两个入口
    print('=== 关键字命中位置 ===')
    for pat, label in ((r"_fe_title or _fe_btn", '战斗分支入口'),
                       (r"fb\(items, L\['expl'\]\)", '探索分支入口(标题)'),
                       (r"_dlg_panel_btn\(ditems, L\['ebtn'\]\)", '探索分支入口(按钮)'),
                       (r"_is_purple", '紫格判据')):
        for m in re.finditer(pat, seg):
            ln = base + seg[:m.start()].count('\n')
            print('  L%-6d %-22s %s' % (ln, label, lines[ln - 1].strip()[:80]))
    print()
    print('=' * 90)
    print('判读：**战斗分支的行号 < 探索分支的行号** ⇒ 与 PC 同构（有被战斗抢先的风险）')
    print('      且两处都要是**顶层 if**（兄弟关系）⇒ 战斗分支 return 后探索才有机会')
    return 0


if __name__ == '__main__':
    sys.exit(main())
