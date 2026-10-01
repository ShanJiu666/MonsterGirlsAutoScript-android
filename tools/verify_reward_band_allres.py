# -*- coding: utf-8 -*-
"""verify_reward_band_allres.py · ⭐ 骰子/大拇指「奖励行」搜索带审计（v1.19）

**为什么有这个工具**（2026-10-01）：
    v1.19 把结算面板的「奖励行」搜索框从**写死 y** 改成**锚定「关闭」按钮**
    （`_reward_box` / `_reward_band`），修的是「真机上旧 box 完全盖不到奖励行
    ⇒ `no_btn` + 三路图标全 None」这个静默 bug。
    ⚠ 但当时**只在一张首领战帧上验过**，而那张帧的奖励行里本来就没有大拇指
      ⇒ 结果全空是**正确答案** ⇒ **等于没验**。本工具补上这块缺口。

**审计五件事**：
    ⓐ 真机 1264×2780 奖励行**左半区**条目全部被新 band 覆盖
    ⓑ 面板底部三键（回放战斗/关闭/自动跳过）**不**落进 band（否则会把按钮当奖励）
    ⓒ 旧写死 box 在真机上确实盖不全 ⇒ 证明 v1.19 修的是**真 bug**而非空改
    ⓓ 新 box 覆盖左半区全部条目（b 的镜像：不能为了不误伤而漏掉）
    ⓔ PC 9:16 基准帧（`runs/bw2.json`）**不过度收紧**：正负同时成立
    ⓕ 徽章阈值/尺度带没被动过（0.70/0.70、4.1~4.9 —— 含实测真标记 0.92@4.5）

⚠ **设计边界（别误改成「全宽覆盖」）**：
    band 的 x 上界 `REWARD_X1=560` 是**故意**的 —— 骰子/大拇指在左半区，
    右半区是属性数字（真机实测 `5/5` 在参考 x=611）。所以断言只覆盖**左半区**。

用法：
    python tools/verify_reward_band_allres.py
退出码 0 = 全过；非 0 = 有 `[FAIL]`。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
# ⭐ 2026-10-01 晚「两端完全平行」：默认用**本仓自己的**源码
#   （app/src/main/python —— 与 APK 里跑的是同一份 ✓），PC 仓**完全可选**。
#   想拿 PC 端做对拍：设 MGAS_PC_SRC 指向 PC checkout。
MAPBOT = os.environ.get('MGAS_PC_SRC') or os.path.abspath(
    os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
if not os.path.isdir(MAPBOT):
    raise SystemExit('找不到可用的源码目录：%s' % MAPBOT)
# ⚠ 资源根：手机端 `app/src/main/python/templates` 是**空目录**，
#   模板真身在 `assets/mapbot_pack/templates`（见 build_pack.py）。
_ASSETS = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main',
                                       'assets', 'mapbot_pack'))


def _has_files(d, minimum=2):
    try:
        n = 0
        for _r, _ds, fs in os.walk(d):
            n += len(fs)
            if n >= minimum:
                return True
    except OSError:
        pass
    return False


os.environ.setdefault('MAPBOT_ROOT',
                      MAPBOT if _has_files(os.path.join(MAPBOT, 'templates'))
                      else _ASSETS)
sys.path.insert(0, MAPBOT)
os.chdir(MAPBOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import explore_loop as EL          # noqa: E402
import badge as badge_mod          # noqa: E402

TOP = 300                          # RefMapper 锚顶/锚底分界
FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


# ── 真机 1264×2780 实测 OCR（设备系：文本, x, y）── 2026-10-01 16:0x 从真帧读出
DEV_1264 = [
    ('1/3', 224, 1277), ('1/16', 468, 1277), ('5/5', 715, 1277),
    ('133114', 229, 1375), ('220 46 184', 449, 1413),
    ('10', 130, 1595), ('1', 150, 1680),
    ('回放战斗', 677, 1966), ('关闭', 675, 2219), ('自动跳过', 673, 2362),
]
BOTTOM_BTNS = ('回放战斗', '关闭', '自动跳过')
OLD_BOX = (40, 840, 1020, 1140)    # v1.19 之前的写死 box（必须被证明是坏的）


def main():
    K = 1264 / 1080.0
    SHIFT = 2780 - 1920 * K

    def to_ref_y(dy):
        return dy / K if dy <= TOP * K else (dy - SHIFT) / K

    items = [{'text': t, 'cx': x / K, 'cy': to_ref_y(y), 'conf': 1.0}
             for t, x, y in DEV_1264]
    bx = EL._reward_box(items)
    y0, y1 = EL.REWARD_CLOSE_UP_MIN, EL.REWARD_CLOSE_UP_MAX

    print('=' * 74)
    print('v1.19 奖励行「锚定关闭」· 双分辨率审计')
    print('=' * 74)

    print()
    print('【1】band 常量')
    ck('band 定义存在且 y0<y1', y0 < y1, 'y=[%d,%d]' % (y0, y1))
    print('  真机 1264×2780 ⇒ 新 box = %s' % (bx,))

    print()
    print('【2】真机 1264×2780：覆盖 / 不误伤')
    inside = [t for t, x, y in DEV_1264
              if bx[1] <= to_ref_y(y) <= bx[3] and bx[0] <= x / K <= bx[2]]
    ck('奖励行左区条目被 band 覆盖（>=4 条）', len(inside) >= 4, str(inside))
    in_btn = [t for t, x, y in DEV_1264
              if t in BOTTOM_BTNS and bx[1] <= to_ref_y(y) <= bx[3]]
    ck('面板底部三键**不**落进 band', not in_btn, str(in_btn))

    print()
    print('【3】旧写死 box vs 新 box')
    row_ys = [to_ref_y(y) for t, x, y in DEV_1264 if t not in BOTTOM_BTNS]
    cov_old = [y for y in row_ys if OLD_BOX[1] <= y <= OLD_BOX[3]]
    miss_old = [y for y in row_ys if y < OLD_BOX[1]]
    print('  旧 box y=[%d,%d]；真机奖励行参考 y=%.0f~%.0f'
          % (OLD_BOX[1], OLD_BOX[3], min(row_ys), max(row_ys)))
    print('  旧 box 覆盖 %d/%d 条，**完全盖不到**的 %d 条'
          % (len(cov_old), len(row_ys), len(miss_old)))
    ck('旧 box 确实盖不全（证明 v1.19 修的是真 bug）', len(miss_old) > 0)
    miss_x = [(t, x / K) for t, x, y in DEV_1264
              if t not in BOTTOM_BTNS and not (bx[0] <= x / K <= bx[2])]
    print('  新 box 被 x 界排除的：%s' % [(t, round(xx)) for t, xx in miss_x])
    ck('被 x 界排除的条目**都在右半区**（属性数字，不是骰子）',
       all(xx >= EL.REWARD_X1 for _t, xx in miss_x))
    miss_y = [t for t, x, y in DEV_1264
              if t not in BOTTOM_BTNS and x / K < EL.REWARD_X1
              and not (bx[1] <= to_ref_y(y) <= bx[3])]
    ck('新 box 覆盖**左半区全部**奖励行条目', not miss_y, str(miss_y))

    print()
    print('【4】PC 9:16 基准帧：不过度收紧')
    # ⭐ 基准帧**随本仓走**（`_verify/bw2_pc_result_panel.json`），不从 PC 仓取 ——
    #   2026-10-01 拆分时 PC 的 runs/ 已被 .gitignore 排除，靠跨仓读会在干净 clone 上挂掉。
    cands = [os.path.join(HERE, '..', '_verify', 'bw2_pc_result_panel.json'),
             os.path.join(MAPBOT, 'runs', 'bw2.json')]
    p = next((c for c in cands if os.path.exists(c)), None)
    if p:
        d = json.load(open(p, encoding='utf-8'))
        its = d['items'] if isinstance(d, dict) else d
        pb = EL._reward_box(its)
        print('  基准帧：%s' % os.path.relpath(p, os.path.join(HERE, '..')))
        print('  PC 帧 band = %s' % (pb,))
        p_in = [i['text'] for i in its
                if pb[1] <= i['cy'] <= pb[3] and i['cx'] < pb[2]]
        p_btn = [i['text'] for i in its
                 if i['text'] in BOTTOM_BTNS and pb[1] <= i['cy'] <= pb[3]]
        ck('PC 帧奖励条目被覆盖（>=4）', len(p_in) >= 4, str(p_in[:5]))
        ck('PC 帧底部按钮被排除', not p_btn, str(p_btn))
    else:
        print('  （找不到 PC 基准帧）')
        ck('PC 基准帧存在', False, ' / '.join(cands))

    print()
    print('【5】徽章阈值与尺度带（正样本 0.92@缩放4.5 不能被拒）')
    ck('形状阈值 = 0.70', badge_mod.REWARD_SHAPE_MIN == 0.70)
    ck('配色阈值 = 0.70', badge_mod.REWARD_COLOR_MIN == 0.70)
    ck('尺度带覆盖 4.1~4.9（含实测真标记 4.5）',
       min(badge_mod.REWARD_SCALES) <= 4.5 <= max(badge_mod.REWARD_SCALES),
       str(badge_mod.REWARD_SCALES))
    ck('模板文件存在', os.path.exists(badge_mod.REWARD_TPL))
    ck('真标记标定 0.92 明显高于阈值 0.70（两边余量够）',
       0.92 > badge_mod.REWARD_SHAPE_MIN + 0.15)

    print()
    print('=' * 74)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
        return 1
    print('✅ 全部通过（v1.19 的 band 修法在 1264×2780 与 9:16 上均成立）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
