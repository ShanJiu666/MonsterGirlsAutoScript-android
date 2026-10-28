# -*- coding: utf-8 -*-
"""把 `mgas_log.txt` 压成**一眼能看的分图摘要**（治"日志太多太杂、找不到规划步数"）

用户 2026-10-06 原话：「**我找不到那张图具体规划的步数，日志里太多太杂**」

## 这个工具做什么
按 `map` 切段，每张图打印**一条时间线**，只留"决策/动作"这些**能复盘**的行：
    · `solver ok`      → **规划了几步、点序是什么**（原来得自己在几百行里翻 ✗）
    · `plan first`     → 本图实际采用的点序
    · `round`          → 轮次 / 体力 / 槽位读数
    · `explore`        → 点探索（含 tile / sid / is_purple）
    · `dispatch`       → 派遣（含**为什么跳过**）
    · `tap`            → 面板类点击（含 changed / mode）
    · `popup`          → 弹了什么面板（含 cell_marks —— "以为是大拇指格"就在这里）
    · `battle`         → 开打/结果
    · `finish`/`stop`  → 怎么结束的
    · `taps`（在 round 行里）→ **逐次棋盘点击**（格/时刻/changed/sid/cost）

⚠ 全程**只读**：不改游戏、不写设备、不加载 OCR。
用法：
    python tools/summarize_log.py <mgas_log.txt> [--all]
    --all 连"噪音行"也打（默认只打上面那些关键行）
"""
import argparse
import io
import json
import os
import re
import sys

KEYS = ('solver', 'plan', 'round', 'round_end', 'explore', 'dispatch', 'tap',
        'popup', 'battle', 'wait_end', 'finish', 'stop', 'map', 'collect',
        'dice', 'coin_gate', 'clover_gate', 'unstick', 'enter', 'pre_gate')
NOISE = ('obs_merge', 'board_blink', 'shot', 'capture_path', 'fog_wait',
         'claim_none', 'pre', 'marks_scan', 'targets_ghost', 'settle_tpl',
         'auto_skip')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log')
    ap.add_argument('--all', action='store_true', help='连噪音行也打')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                       # noqa: BLE001
        pass
    if not os.path.isfile(a.log):
        print('找不到 %s' % a.log)
        return 2
    lines = io.open(a.log, encoding='utf-8', errors='replace').read().splitlines()

    cur_map = 0
    kept = 0
    total = 0
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s.startswith('{'):
            continue
        total += 1
        try:
            d = json.loads(s)
        except Exception:                   # noqa: BLE001  （被 [:300] 截断的行）
            # ⚠ 截断行也要能看出"它是什么"，否则等于看不见 ✗
            k = s.split('"')[1] if '"' in s else '?'
            if a.all or k in KEYS:
                print('  L%-5d [%-14s] ⚠ 截断: %s' % (i, k, s[:120]))
                kept += 1
            continue
        if 'map' in d and isinstance(d.get('map'), int):
            cur_map = d['map']
            print()
            print('=' * 96)
            print('【map %s】%s' % (cur_map, json.dumps(
                {k: v for k, v in d.items() if k != 'map'}, ensure_ascii=False)[:150]))
            print('=' * 96)
            continue
        k = next((x for x in d.keys()), '?')
        if not a.all and k in NOISE:
            continue
        if not a.all and k not in KEYS:
            continue

        # ── 每种事件挑**最值得看**的字段 ──────────────────────────────────
        if k == 'solver' and d.get('solver') == 'ok':
            print('  L%-5d ★规划  %s 步  点序=%s'
                  % (i, d.get('steps'), d.get('order')))
        elif k == 'plan':
            print('  L%-5d 采用  %s → %s' % (i, d.get('plan'), d.get('cells')))
        elif k == 'solver':
            extra = {x: y for x, y in d.items() if x != 'solver'}
            print('  L%-5d [solver.%-18s] %s'
                  % (i, str(d.get('solver'))[:18],
                     json.dumps(extra, ensure_ascii=False)[:120]))
        elif k == 'round':
            taps = d.get('taps') or []
            print('  L%-5d r%-3s 体力=%-5s 槽位=%s free=%s'
                  % (i, d.get('round'), d.get('stamina'),
                     d.get('slots'), d.get('slots_free')))
            if taps:
                print('          逐次棋盘点击: %s' % (taps,))
            mk = d.get('marks')
            if mk:
                print('          标记: %s' % (mk,))
        elif k == 'explore':
            print('  L%-5d 探索  at=%s tile=%s sid=%s 紫=%s'
                  % (i, d.get('at'), d.get('tile'), d.get('sid'),
                     d.get('is_purple')))
        elif k == 'dispatch':
            print('  L%-5d 派遣  %s %s'
                  % (i, d.get('dispatch'),
                     json.dumps({x: y for x, y in d.items()
                                 if x not in ('dispatch', 'note')},
                                ensure_ascii=False)[:110]))
        elif k == 'tap':
            print('  L%-5d 点击  %-14s at=%s ch=%s mode=%s changed=%s'
                  % (i, str(d.get('tap'))[:14], d.get('at'), d.get('ch'),
                     d.get('mode'), d.get('changed')))
        elif k == 'popup':
            print('  L%-5d 弹窗  %-22s cell_marks=%s near=%s'
                  % (i, str(d.get('popup'))[:22], d.get('cell_marks'),
                     d.get('near_marks')))
        elif k == 'battle':
            print('  L%-5d 战斗  %s marks=%s'
                  % (i, d.get('battle'), d.get('marks')))
        elif k in ('finish', 'stop', 'wait_end'):
            print('  L%-5d %-8s %s'
                  % (i, k, json.dumps({x: y for x, y in d.items() if x != k},
                                      ensure_ascii=False)[:120]))
        else:
            print('  L%-5d [%-12s] %s'
                  % (i, k, json.dumps({x: y for x, y in d.items() if x != k},
                                      ensure_ascii=False)[:120]))
        kept += 1
    print()
    print('=' * 96)
    print('共 %d 行 JSON，其中打出 %d 行（--all 可看全部）' % (total, kept))
    return 0


if __name__ == '__main__':
    sys.exit(main())
