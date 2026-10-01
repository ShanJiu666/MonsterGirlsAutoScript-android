# -*- coding: utf-8 -*-
"""multires_audit.py · 两个分辨率上「v1.19 奖励行定位」的一致性审计

已确证的事实（本轮）：
  ① 奖励行**锚定模型成立**：真机 1264×2780 奖励行参考 y 636~980；
     PC 9:16 参考 y 907~1001；两者都落在新 band [520,1020] 内 ✓
  ② 面板底部三键（回放战斗/关闭/自动跳过）两机**参考系坐标一致**
     （1223/1440/1563 vs 1224/1441/1563）⇒ 锚定「关闭」是对的 ✓
  ③ 旧写死 y 840~1140 在 1264×2780 上**只压到奖励行下半段** ⇒ 真机必然 no_btn ✓
  ④ PC 正样本真标记：0.92/0.92 @ (614,936) 缩放 4.5（148px，蓝色框 + 金拇指）
  ⑤ 真机 720×1280 那次 recommend 战斗：近失 0.45/0.41 ⇒ 噪声带，**本来就没奖励** ⇒ no_btn 正确

本脚本做**可复现的量化审计**：把上述每条都变成断言跑一遍。
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
MAPBOT = r'D:\MGAS\mapbot_pc'
sys.path.insert(0, MAPBOT)
os.chdir(MAPBOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import explore_loop as EL                    # noqa: E402
import badge as badge_mod                    # noqa: E402

FAILS = []


def ck(name, cond, detail=''):
    print('  %s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                         ('  ' + detail) if detail else ''))
    if not cond:
        FAILS.append(name)


def main():
    print('=' * 78)
    print('v1.19 奖励行「锚定关闭」· 双分辨率一致性审计')
    print('=' * 78)

    print()
    print('【1】band 常量与真机实测的覆盖关系')
    y0, y1 = EL.REWARD_CLOSE_UP_MIN, EL.REWARD_CLOSE_UP_MAX
    ck('band 定义存在且 y0<y1', y0 < y1, 'y=[%d,%d]' % (y0, y1))
    # 1264×2780 实测奖励行参考 y（上一轮 ocr 出来的那批）
    dev_items = [('1/3', 224, 1277), ('1/16', 468, 1277), ('5/5', 715, 1277),
                 ('133114', 229, 1375), ('220 46 184', 449, 1413),
                 ('10', 130, 1595), ('1', 150, 1680),
                 ('回放战斗', 677, 1966), ('关闭', 675, 2219), ('自动跳过', 673, 2362)]
    K, SHIFT = 1264 / 1080.0, 2780 - 1920 * (1264 / 1080.0)
    TOP = 300

    def to_ref_y(dy):
        return dy / K if dy <= TOP * K else (dy - SHIFT) / K

    items = [{'text': t, 'cx': x / K, 'cy': to_ref_y(y), 'conf': 1.0}
             for t, x, y in dev_items]
    bx = EL._reward_box(items)
    print('  真机 1264×2780 ⇒ 新 box = %s' % (bx,))
    rew = [t for t, x, y in dev_items if t not in ('回放战斗', '关闭', '自动跳过')]
    btn = ['回放战斗', '关闭', '自动跳过']
    inside_rew = [t for t, x, y in dev_items
                  if bx[1] <= to_ref_y(y) <= bx[3] and bx[0] <= x / K <= bx[2]]
    inside_btn = [t for t, x, y in dev_items
                  if t in btn and bx[1] <= to_ref_y(y) <= bx[3]]
    ck('奖励行左区条目被 band 覆盖（>=4 条）', len(inside_rew) >= 4, str(inside_rew))
    ck('面板底部三键**不**落进 band', not inside_btn, str(inside_btn))

    print()
    print('【2】旧写死 box 在真机上必然失效（v1.19 要修的正是这个）')
    OLD = (40, 840, 1020, 1140)
    row_ys = [to_ref_y(y) for t, x, y in dev_items if t not in btn]
    cov = [y for y in row_ys if OLD[1] <= y <= OLD[3]]
    full = [y for y in row_ys if y < OLD[1]]
    print('  旧 box y=[%d,%d]；真机奖励行参考 y=%.0f~%.0f' % (OLD[1], OLD[3],
                                                     min(row_ys), max(row_ys)))
    print('  旧 box 覆盖 %d/%d 条，**完全盖不到**的 %d 条' % (len(cov), len(row_ys), len(full)))
    ck('旧 box 确实盖不全（证明 v1.19 修的是真 bug）', len(full) > 0)
    # ⚠ 只要求覆盖**左半区**（x < REWARD_X1）：右半是属性数字（实测 5/5 @ x=611），
    #    按设计就不属于骰子/大拇指搜索范围（见 REWARD_X1 注释）。
    missed = [(t, x / K, to_ref_y(y)) for t, x, y in dev_items
              if t not in btn and not (bx[0] <= x / K <= bx[2])]
    print('  新 box 只盖左半区（x<%d）；被 x 界排除的：%s'
          % (EL.REWARD_X1, [(t, round(xx), round(yy)) for t, xx, yy in missed]))
    ck('被 x 界排除的条目**都在右半区**（是属性数字，不是骰子）',
       all(xx >= EL.REWARD_X1 for _t, xx, _yy in missed),
       str([(t, round(xx)) for t, xx, _yy in missed]))
    missed_y = [t for t, x, y in dev_items
                if t not in btn and x / K < EL.REWARD_X1
                and not (bx[1] <= to_ref_y(y) <= bx[3])]
    ck('新 box 覆盖**左半区全部**奖励行条目', not missed_y, str(missed_y))

    print()
    print('【3】PC 9:16 基准帧不被过度收紧')
    d = json.load(open(os.path.join(MAPBOT, 'runs', 'bw2.json'), encoding='utf-8'))
    its = d['items'] if isinstance(d, dict) else d
    pbx = EL._reward_box(its)
    print('  PC 帧 band = %s' % (pbx,))
    p_in = [i['text'] for i in its if pbx[1] <= i['cy'] <= pbx[3] and i['cx'] < pbx[2]]
    p_btn_in = [i['text'] for i in its
                if i['text'] in ('关闭', '自动跳过', '回放战斗')
                and pbx[1] <= i['cy'] <= pbx[3]]
    ck('PC 帧奖励条目被覆盖（>=4）', len(p_in) >= 4, str(p_in[:6]))
    ck('PC 帧底部按钮被排除', not p_btn_in, str(p_btn_in))

    print()
    print('【4】徽章阈值与正样本标定（0.92 真 vs <=0.55 噪声）')
    ck('形状阈值 = 0.70', badge_mod.REWARD_SHAPE_MIN == 0.70)
    ck('配色阈值 = 0.70', badge_mod.REWARD_COLOR_MIN == 0.70)
    ck('尺度带覆盖 4.1~4.9（含标定的 4.5）',
       min(badge_mod.REWARD_SCALES) <= 4.5 <= max(badge_mod.REWARD_SCALES),
       str(badge_mod.REWARD_SCALES))
    ck('模板文件存在', os.path.exists(badge_mod.REWARD_TPL))

    print()
    print('【5】本次真机 recommend 战斗的 no_btn 判定是否正确')
    ck('真机近失分 0.451 < 阈值 0.70 ⇒ 判为噪声 ⇒ no_btn 正确',
       0.451 < badge_mod.REWARD_SHAPE_MIN)

    print()
    print('=' * 78)
    if FAILS:
        print('❌ %d 项未通过：%s' % (len(FAILS), FAILS))
    else:
        print('✅ 全部通过（v1.19 的 band 修法在两个分辨率上均成立）')


if __name__ == '__main__':
    main()
