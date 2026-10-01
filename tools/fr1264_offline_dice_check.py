# -*- coding: utf-8 -*-
"""offline_dice_check.py · v1.19 离线验收（不依赖设备）
用 1264×2780 的**真结算帧**（rec/f0044_0061.6.png 设备原帧），
把它归一化成 1080×1920 参考帧，跑 badge.find_reward_mark 三路，看能不能找到奖励图标。
对比旧 box（840~1140）必然找不到 vs 新 box（锚定关闭）能找到。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAPBOT = r'D:\MGAS\mapbot_pc'
sys.path.insert(0, MAPBOT)
os.chdir(MAPBOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402
import badge as badge_mod                    # noqa: E402
import explore_loop as EL                    # noqa: E402

REF_W, REF_H, TOP = 1080, 1920, 300
K, SHIFT = 1264 / 1080.0, 2780 - 1920 * (1264 / 1080.0)
SRC = os.path.join(HERE, 'rec', 'f0044_0061.6.png')


def dev2ref_y(y):
    return y / K if y <= TOP * K else (y - SHIFT) / K


def dev2ref_x(x):
    return x / K


def to_ref(img):
    """设备帧 → 参考帧（照抄 RefMapper.toRef 的两段拼接）
    顶块 (0,0,W,300kx)→(0,0,1080,300)；锚底区 (0,300kx+shift,W,H)→(0,300,1080,1920)
    """
    H, W = img.shape[:2]
    out = np.zeros((REF_H, REF_W, 3), np.uint8)
    top_src_h = int(round(TOP * K))
    out[0:TOP, :] = cv2.resize(img[0:top_src_h, :], (REF_W, TOP),
                               interpolation=cv2.INTER_AREA)
    sy0 = top_src_h + int(round(SHIFT))
    if sy0 < H:
        out[TOP:, :] = cv2.resize(img[sy0:H, :], (REF_W, REF_H - TOP),
                                  interpolation=cv2.INTER_AREA)
    return out


def main():
    if not os.path.exists(SRC):
        print('缺真帧 %s' % SRC)
        return
    img = cv2.imdecode(np.fromfile(SRC, dtype=np.uint8), cv2.IMREAD_COLOR)
    print('真帧: %dx%d' % (img.shape[1], img.shape[0]))
    ref = to_ref(img)
    cv2.imencode('.png', ref)[1].tofile(os.path.join(HERE, 'v119_ref_from_device.png'))
    print('已归一化 → v119_ref_from_device.png (1080x1920)')

    # 关闭按钮：设备 (675,2219) ⇒ 参考 (577, 1440.7)
    items = [{'text': '关闭', 'cx': dev2ref_x(675), 'cy': dev2ref_y(2219), 'conf': 1.0},
             {'text': '自动跳过', 'cx': dev2ref_x(673), 'cy': dev2ref_y(2362), 'conf': 1.0},
             {'text': '回放战斗', 'cx': dev2ref_x(677), 'cy': dev2ref_y(1966), 'conf': 1.0}]
    print()
    print('① 新 band（锚定关闭）:')
    print('   box =', EL._reward_box(items))
    new_hits = badge_mod.find_reward_mark(ref, box=EL._reward_box(items))
    print('   find_reward_mark →', new_hits)
    for thr in (0.70, 0.60, 0.50, 0.40):
        h = badge_mod.find_reward_mark(ref, box=EL._reward_box(items), shape_min=thr,
                                       color_min=thr)
        print('   阈值 %.2f → %s' % (thr, h))

    print()
    print('② 旧 box（写死 840~1140，真机必然盖不到）:')
    old = (40, 840, 1020, 1140)
    print('   box =', old)
    old_hits = badge_mod.find_reward_mark(ref, box=old)
    print('   find_reward_mark →', old_hits)
    print('   旧 box 与奖励行真机位置（参考 636~980）的关系: 重叠=%s'
          % (not (1140 < 636 or 840 > 980)))
    print('   ⇒ 旧 box y 840~1140，奖励行 636~980 ⇒ **只压到 840~980 一小段**；'
          '且 x 40~1020 与骰子实际 x 111~396 大体重叠但 y 大半错位')


if __name__ == '__main__':
    main()
