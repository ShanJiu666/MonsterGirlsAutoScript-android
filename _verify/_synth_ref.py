# -*- coding: utf-8 -*-
"""_synth_ref.py · 按「y 锚定模型」从 1080×2400 实拍图合成 1080×1920 参考帧，跑 PC 分类器验证

模型（2026-09-29 实测）：
  · 顶部块（参考 y ≤ 300）：设备 y 一致（顶 HUD 锚顶）
  · 其余（参考 y > 300）：设备 y = 参考 y + (H − 1920)（锚底，纯平移、不缩放）
  · x：1:1（宽度=设计稿 1080）
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
MAPBOT = r'D:\幻想少女公会\tools\mapbot'
sys.path.insert(0, MAPBOT)
os.chdir(MAPBOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import spots as SP  # noqa: E402

SRC = sys.argv[1] if len(sys.argv) > 1 else r'D:/幻想少女公会/android_autoexplore/_verify/inmap_2400.png'
CODE = sys.argv[2] if len(sys.argv) > 2 else 'S00003'
TOP = 300
SHIFT = 480                       # 2400 − 1920

img = cv2.imdecode(np.fromfile(SRC, dtype=np.uint8), cv2.IMREAD_COLOR)
H, W = img.shape[:2]
print('源图 %dx%d  模型: 顶块 0~%d 原样, 其余 −%d' % (W, H, TOP, SHIFT))

ref = np.zeros((1920, 1080, 3), dtype=np.uint8)
ref[0:TOP] = img[0:TOP]                                   # 顶块
ref[TOP:1920] = img[TOP + SHIFT:TOP + SHIFT + (1920 - TOP)]  # 锚底区纯平移
out = os.path.join(HERE, 'synth_ref_1920.png')
cv2.imencode('.png', ref)[1].tofile(out)
print('合成参考帧 →', out)

st = SP.Board(CODE).state(ref)
ok = sum(1 for v in st.values() if v.get('score') is not None)
sc = sorted((v.get('score') or 0) for v in st.values())
med = sc[len(sc) // 2] if sc else 0
names = {}
for k, v in st.items():
    names[v.get('name') or '?'] = names.get(v.get('name') or '?', 0) + 1
print('分类: %d/35 格有分  中位分 %.3f' % (ok, med))
print('名字分布:', names)
revealed = sum(1 for v in st.values() if v.get('revealed'))
print('revealed:', revealed)
