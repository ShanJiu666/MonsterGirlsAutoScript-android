# -*- coding: utf-8 -*-
"""scale_mismatch.py · 定位「同坐标不同分」的根因：真标记在 720×1280 上**画得更小**

铁证对照（都把坐标换算到参考系 1080×1920）：
  PC 正样本 dice_ok_0.png : 0.92/0.92 @ (614,936)  缩放 **4.5**
  真机 720×1280 那次      : 0.451/0.411 @ (614,936) 缩放 **4.5**（同坐标同尺度，分数差一半）

同一尺度下分数差一倍 ⇒ **不是尺度选错**，而是那一块像素**长得不一样**。
本脚本：
  ① 取 dice_ok_0 在 (614,936) 的真标记块，按 4.5 缩放画出来 = 期望外观
  ② 把「参考系 (614,936)@4.5」换算到 720×1280 设备系
  ③ 扫真机帧在该点附近的**各尺度**分数，找真机实际的绘制尺寸
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

K = 1280 / 1920.0        # 720×1280 ⇒ 参考→设备：×0.6667
REF_CX, REF_CY, REF_S = 614, 936, 4.5


def main():
    print('① PC 正样本：', )
    pos = os.path.join(MAPBOT, 'runs', 'dice_ok_0.png')
    if not os.path.exists(pos):
        pos = os.path.join(MAPBOT, 'dice_ok_0.png')
    img = cv2.imdecode(np.fromfile(pos, dtype=np.uint8), cv2.IMREAD_COLOR)
    print('   %s  %s' % (pos, img.shape if img is not None else '缺'))
    if img is None:
        return
    tpl = cv2.imdecode(np.fromfile(badge_mod.REWARD_TPL, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    s = REF_S
    th, tw = tpl.shape[:2]
    w, h = int(round(tw * s)), int(round(th * s))
    x0, y0 = int(REF_CX - w / 2), int(REF_CY - h / 2)
    crop = img[max(0, y0):y0 + h, max(0, x0):x0 + w]
    out = os.path.join(HERE, 'mark_pc_expected.png')
    if crop.size:
        cv2.imencode('.png', cv2.resize(crop, (w * 2, h * 2),
                                        interpolation=cv2.INTER_NEAREST))[1].tofile(out)
        print('   真标记块 %dx%d（参考系，缩放 %.1f）→ %s' % (w, h, s, out))
        print('   换算到 720×1280 设备系应为 %dx%d' % (round(w * K), round(h * K)))

    print()
    print('② 真机实况帧里，同一位置附近的分数（把设备坐标当参考系直接扫是错的，')
    print('   正确做法：把 720×1280 帧**放大**到参考系再扫，或按 K 反算坐标）')
    live = r'D:\MGAS\_tmpman\live7555\live_01.png'
    img2 = cv2.imdecode(np.fromfile(live, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img2 is None:
        print('   缺实况帧')
        return
    print('   实况帧 %dx%d' % (img2.shape[1], img2.shape[0]))
    # 720×1280 → 参考系 1080×1920
    up = cv2.resize(img2, (1080, 1920), interpolation=cv2.INTER_CUBIC)
    out = os.path.join(HERE, 'live01_up_to_ref.png')
    cv2.imencode('.png', up)[1].tofile(out)
    print('   已放大到参考系 → %s' % out)

    print()
    print('③ 参考系 (614,936) 附近 (小窗口) 各尺度最佳分数：')
    box = (REF_CX - 120, REF_CY - 120, REF_CX + 120, REF_CY + 120)
    for sc in [round(2.0 + 0.1 * i, 2) for i in range(30)]:    # 2.0~4.9
        h2 = badge_mod.find_reward_mark(up, box=box, scales=[sc],
                                        shape_min=0.0, color_min=0.0, top=1)
        if h2:
            a, b, cx, cy, s2 = h2[0]
            if a > 0.30 or b > 0.30:
                print('   缩放 %.1f → 形状 %.3f 配色 %.3f  @(%d,%d)'
                      % (sc, a, b, cx, cy))


if __name__ == '__main__':
    main()
