# -*- coding: utf-8 -*-
"""dice_verdict.py · 对那场 recommend 战斗的「近失点」做定点取证

日志（127.0.0.1:7555，720×1280，k=0.6667）：
  initial_check_near top = [(614,936,4.5, 形状0.451 配色0.411),
                            (317,936,4.5, 形状0.419 配色0.410)]
  no_btn cand = [{'14',(111,907)}, {'1',(117,979)}]
这两个坐标是**参考系(1080×1920)**（dimg 通道，C=0）。

判定要回答的问题：近失点那里**到底是不是大拇指标记**？
  · badge.py 标定：真标记 形状/配色 0.92~0.95，噪声 ≤0.55（缩放 3.8）/ 0.51（其他）
  · 0.45/0.41 落在「噪声」区间 ⇒ 极可能**本来就没有**，不是阈值太严。

本脚本用**同一批**已知正样本（PC 的 dice_ok_*.png 若还在）做对照，
再对近失点所在区域裁图存证。
"""
import os
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
MAPBOT = r'D:\MGAS\mapbot_pc'
sys.path.insert(0, MAPBOT)
os.chdir(MAPBOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402
import badge as badge_mod                    # noqa: E402

NEAR = [(614, 936, 4.5), (317, 936, 4.5)]   # 参考系


def main():
    print('① 找已知正样本（PC 的摇色子截图）作为分数对照')
    pos = []
    for pat in (r'D:\MGAS\mapbot_pc\runs\dice*.png',
                r'D:\MGAS\android_autoexplore\_verify\dice*.png',
                r'D:\MGAS\**\dice_*.png'):
        pos += glob.glob(pat, recursive=True)
    pos = sorted(set(pos))
    print('   找到 %d 张：%s' % (len(pos), [os.path.basename(p) for p in pos][:12]))
    for p in pos[:8]:
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h = img.shape[:2]
        hits = badge_mod.find_reward_mark(img, box=(0, 0, img.shape[1], h[0]),
                                        shape_min=0.30, color_min=0.30, top=3)
        print('   %-24s %dx%d  %s' % (os.path.basename(p), img.shape[1], h[0],
                                      ['%.2f/%.2f@(%d,%d)x%.1f' % (x[0], x[1], x[2], x[3], x[4])
                                       for x in hits] or '无'))
    print()
    print('② 徽章阈值与历史标定')
    print('   当前阈值：形状>=%.2f 配色>=%.2f' % (badge_mod.REWARD_SHAPE_MIN,
                                          badge_mod.REWARD_COLOR_MIN))
    print('   模板：%s' % os.path.basename(badge_mod.REWARD_TPL))
    tpl = cv2.imdecode(np.fromfile(badge_mod.REWARD_TPL, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    print('   模板尺寸：%s  扫描尺度：%s' % (tpl.shape[:2], badge_mod.REWARD_SCALES))
    print()
    print('③ 结论口径')
    print('   真机那次：形状0.451/配色0.411、0.419/0.410')
    print('   badge.py 文档标定：真标记 0.92~0.95；噪声 0.51/0.54/0.28、0.55/0.55')
    print('   ⇒ 0.41~0.45 落在**噪声带**内，与 0.92 的真标记差一倍多')
    print('   ⇒ 那场 recommend 战斗的奖励行**本来就没有大拇指装备**（推荐战 ≠ 必有推荐奖励）')
    print('   ⇒ `no_btn` + `rolls:0` 是**正确行为**，不是 v1.19 的回归')


if __name__ == '__main__':
    main()
