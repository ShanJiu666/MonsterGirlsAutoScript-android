import numpy as np
import cv2
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
p = r'D:/幻想少女公会/android_autoexplore/_verify/agree_check.png'
img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
reg = img[1690:1830, 0:160]
# 找亮黄色块（BGR: B低 G高 R高）
mask = (reg[:, :, 2] > 200) & (reg[:, :, 1] > 180) & (reg[:, :, 0] < 140)
ys, xs = np.where(mask)
if len(xs) == 0:
    print('没找到黄色块')
else:
    print('黄色块 bbox: x %d~%d  y %d~%d（绝对坐标）'
          % (xs.min(), xs.max(), 1690 + ys.min(), 1690 + ys.max()))
    print('中心: (%d, %d)' % ((xs.min() + xs.max()) // 2, 1690 + (ys.min() + ys.max()) // 2))
# 同时打印该区域每 10px 的颜色采样，帮助定位
for yy in range(1700, 1821, 20):
    row = []
    for xx in range(10, 111, 20):
        b, g, r = img[yy, xx]
        row.append('%3d,%3d,%3d' % (r, g, b))
    print('y=%d  ' % yy + ' | '.join(row))
