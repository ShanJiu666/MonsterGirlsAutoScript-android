# -*- coding: utf-8 -*-
"""bubble_confound.py · 证明「MGAS 悬浮条自己的日志行」把地图帧判成结算面板

实测（live_01.png，720×1280，地图帧）：
  OCR 读到  战斗胜利 (72,1162)  ← 这是 **MGAS 悬浮条气泡**上的 `战斗胜利 ✓ · 首领格`
                                  （同一 y 上还有 `首领格` (193,1162)，正是气泡第二段）
  ⇒ `is_battle_panel` 第③条「严格等值 战斗胜利/失败」被满足 ⇒ **地图帧误判成结算面板** ✗

为什么旧代码防得住、现在防不住：
  - 旧判据用**宽子串** `fb(items, L['win'])`，地图横幅「首领战斗胜利」也会命中
    ⇒ 早就被 v1.18 改成**严格等值**来挡横幅；
  - 但**严格等值**挡不住「悬浮条把一行日志拆成 `战斗胜利` + `首领格` 两段」——
    气泡字体大、OCR 切词，恰好切出一个**恰好等于**「战斗胜利」的碎片。

本脚本量化：把气泡行排除（y ≥ 导航条，或与 `首领格`/`✓` 同行的）后判据应回到 False。
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
import explore_loop as EL                    # noqa: E402
from rapidocr_onnxruntime import RapidOCR   # noqa: E402

eng = RapidOCR()
K = 1280 / 1920.0


def load(p):
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    res, _ = eng(img)
    items = [{'text': t.strip(), 'cx': sum(q[0] for q in b) / 4,
              'cy': sum(q[1] for q in b) / 4, 'conf': float(s)}
             for b, t, s in (res or [])]
    return img.shape[:2], items


def main():
    cases = [r'D:\MGAS\_tmpman\live7555\live_01.png',
             r'D:\MGAS\_tmpman\live7555\live_08.png',
             r'D:\MGAS\_tmpman\live7555\live_12.png']
    print('设备 720×1280，k=%.4f；参考系 1080×1920' % K)
    print()
    for p in cases:
        if not os.path.exists(p):
            continue
        (H, W), items = load(p)
        ref = [{'text': i['text'], 'cx': i['cx'] / K, 'cy': i['cy'] / K,
                'conf': i['conf']} for i in items]
        before = EL.is_battle_panel(ref)
        # 找到触发第③条的那条
        trig = [i for i in ref if i['text'].strip() in ('战斗胜利', '战斗失败')]
        print('%s  is_battle_panel=%s' % (os.path.basename(p), before))
        for t in trig:
            print('   触发③的条目: %r  参考系(%.0f,%.0f)  设备系(%.0f,%.0f)'
                  % (t['text'], t['cx'], t['cy'], t['cx'] * K, t['cy'] * K))
        # 同行还有谁（判断是不是悬浮条气泡）
        if trig:
            y = trig[0]['cy']
            row = [i['text'] for i in ref if abs(i['cy'] - y) < 30]
            print('   同行(参考y≈%.0f)全部文本: %s' % (y, row))
        # 排除气泡带（设备 y >= 1150 ≈ 参考 y >= 1725，悬浮条顶边）后
        cut = [i for i in ref if i['cy'] < 1725]
        after = EL.is_battle_panel(cut)
        print('   剔掉悬浮条带(参考y>=1725)后 is_battle_panel=%s' % after)
        print()


if __name__ == '__main__':
    main()
