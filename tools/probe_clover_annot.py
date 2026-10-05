# -*- coding: utf-8 -*-
"""v1.63 标定（B14）⑤：把 HUD 那一行按 x 分段裁出来，**逐簇标注** ⇒ 人眼定"哪个是幸运草"

上一脚本量到白字簇（`r_180326`）：
    558~570(564) ｜ 690~695(692) ｜ **716~728(722)** ｜ 900~910(905) ｜ 928~940(934) ｜ 1003~1038
PC ×1.5 期望：金币 651 ｜ 幸运草 694 ｜ 大拇指 906
⇒ 数字对不上（差 28~40px）**不能只用换算** ⇒ 必须**看图定**

用法：python android_autoexplore\\tools\\probe_clover_annot.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
CAL = os.environ.get('MGAS_CAL_DIR') or os.path.abspath(
    os.path.join(PROJ, '..', '_tmpman', 'cal'))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                           # noqa: BLE001
    pass

import cv2                                  # noqa: E402
import numpy as np                          # noqa: E402


def main():
    fn = sys.argv[1] if len(sys.argv) > 1 else 'r_180326_0.png'
    img = cv2.imread(os.path.join(CAL, fn))
    if img is None:
        print('⚠ 没有帧 %s' % fn)
        return 2
    H, W = img.shape[:2]
    # 裁 HUD 两行（y 20~130），放大 2.2×
    band = img[15:135, :]
    big = cv2.resize(band, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_NEAREST)
    # 每 100px（原图 x）画一条竖线 + 标 x 值
    for x in range(0, W, 100):
        bx = int(x * 2.2)
        cv2.line(big, (bx, 0), (bx, big.shape[0]), (0, 200, 255), 2)
        cv2.putText(big, str(x), (bx + 4, 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 200, 255), 2, cv2.LINE_AA)
    # 把已知的白字簇位置用**红框**标出来（心 ±20）
    for ctr in (564, 692, 722, 905, 934, 1020):
        bx = int((ctr - 22) * 2.2)
        bw = int(44 * 2.2)
        cv2.rectangle(big, (bx, 0), (bx + bw, big.shape[0]), (0, 0, 255), 3)
        cv2.putText(big, str(ctr), (bx, big.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
    out = os.path.join(CAL, '_clover_annot_%s' % fn)
    cv2.imwrite(out, big)
    print('→ %s  (%dx%d)' % (out, big.shape[1], big.shape[0]))
    print()
    print('红框 = 白字簇心：564(PID尾) / 692 / **722** / 905 / 934 / 1020')
    print('黄竖线 = 每 100px 刻度')
    print('⇒ 看图定：**"一个数字 + 四叶草加号"**那一簇是幸运草；"数字 + 金币图标"是金币 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
