# -*- coding: utf-8 -*-
"""verify_reward_band.py · v1.19 离线验收：新的奖励行 band 在真帧/PC 帧上是否真的盖到东西
用 1264×2780 真机结算帧（设备坐标）反算回参考系，逐条判「在带内 / 在带外」。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAPBOT = r'D:\MGAS\mapbot_pc'
sys.path.insert(0, MAPBOT)
os.chdir(MAPBOT)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

REF_W, REF_H, TOP = 1080, 1920, 300
K, SHIFT = 1264 / 1080.0, 2780 - 1920 * (1264 / 1080.0)


def to_ref_y(devy):
    if devy <= TOP * K:
        return devy / K
    return (devy - SHIFT) / K


def main():
    import explore_loop as EL
    print('常量：REWARD_X1=%d  band y=[%d, %d]'
          % (EL.REWARD_X1, EL.REWARD_CLOSE_UP_MIN, EL.REWARD_CLOSE_UP_MAX))
    print('k=%.4f shift=%.1f' % (K, SHIFT))
    print()
    print('① 1264×2780 真机结算帧（设备坐标 → 参考系）')
    dev_items = [('1/3', 224, 1277), ('1/16', 468, 1277), ('5/5', 715, 1277),
                 ('133114', 229, 1375), ('220 46 184', 449, 1413),
                 ('10', 130, 1595), ('1', 150, 1680),
                 ('回放战斗', 677, 1966), ('关闭', 675, 2219), ('自动跳过', 673, 2362)]
    band_items = [{'text': t, 'cx': x, 'cy': to_ref_y(y), 'conf': 1.0}
                  for t, x, y in dev_items]
    bx0, by0, by1 = EL._reward_band(band_items)
    print('   传入含「关闭」的 items ⇒ band=(%d, %d, %d)  ← 用真实关闭按钮收紧' % (bx0, by0, by1))
    for t, x, y in dev_items:
        ry = to_ref_y(y)
        print('   %-12s dev y=%4d ⇒ 参考 y=%7.1f  x=%4d  %s'
              % (t, y, ry, x, '带内' if by0 <= ry <= by1 else '带外'))
    covered = [t for t, x, y in dev_items
               if by0 <= to_ref_y(y) <= by1 and x < EL.REWARD_X1]
    print('   ⇒ 奖励行左区被覆盖: %s' % covered)

    print()
    print('② PC 9:16 结算帧 runs/bw2.json（本来就是参考系）')
    import json
    import io
    d = json.load(io.open(os.path.join(MAPBOT, 'runs', 'bw2.json'), encoding='utf-8'))
    its = d['items'] if isinstance(d, dict) else d
    bx0, by0, by1 = EL._reward_band(its)
    print('   band=(%d, %d, %d)' % (bx0, by0, by1))
    for it in its:
        if it['cy'] < 400:
            continue
        print('   %-28s (%4d,%4d)  %s'
              % (it['text'][:26], it['cx'], it['cy'],
                 '带内' if by0 <= it['cy'] <= by1 else '带外'))

    print()
    print('③ 地图帧（boss 横幅）不得落进带内')
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    eng = RapidOCR()
    p = os.path.join(r'D:\MGAS\android_autoexplore\_verify', 'fr1264_map_boss_banner.png')
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    res, _ = eng(img)
    map_items = [{'text': t.strip(),
                  'cx': sum(q[0] for q in b) / 4, 'cy': sum(q[1] for q in b) / 4,
                  'conf': float(s)} for b, t, s in (res or [])]
    bx0, by0, by1 = EL._reward_band(map_items)
    inside = [m['text'] for m in map_items
              if by0 <= m['cy'] <= by1 and m['cx'] < EL.REWARD_X1]
    print('   band=(%d, %d, %d)  地图帧落进带内的条目: %s'
          % (bx0, by0, by1, inside))


if __name__ == '__main__':
    main()
