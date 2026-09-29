import numpy as np
import cv2
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
p = r'D:/幻想少女公会/android_autoexplore/_verify/inmap_2400.png'
img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
H, W = img.shape[:2]
print('size', W, H)

# 棋盘格特征：格子内部是「灰调沙色/米色」，和上方世界场景（蓝天/大海/沙滩）不同。
# 用行方差 + 主色统计找棋盘的上下边界：棋盘区每行颜色种类少、且含大量 (200~230) 灰米色。
g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
# 每行「接近格子灰米色(190~215)」的像素占比
frac = ((g[:, 30:1050] > 180) & (g[:, 30:1050] < 225)).mean(axis=1)
# 找连续 >0.5 的最长段（棋盘 720px 高）
best, cur_start, cur_len, best_len, best_start = None, None, 0, 0, 0
for y in range(H):
    if frac[y] > 0.5:
        if cur_start is None:
            cur_start = y
        cur_len = y - cur_start + 1
        if cur_len > best_len:
            best_len, best_start = cur_len, cur_start
    else:
        cur_start, cur_len = None, 0
print('棋盘灰米色主段: y %d ~ %d  (高 %d)' % (best_start, best_start + best_len - 1, best_len))
print('预测(参考+480): 1482 ~ 2202')

# 左边界：在该段中部一行，找从左到右第一列「非深棕边框」的格子列
mid = best_start + best_len // 2
row = g[mid]
xs = np.where((row > 180) & (row < 225))[0]
if len(xs):
    print('y=%d 行灰米色 x 范围: %d ~ %d' % (mid, xs.min(), xs.max()))
print('预测 x: 36 ~ 1044（格距 144 × 7）')
