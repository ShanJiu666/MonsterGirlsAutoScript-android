# -*- coding: utf-8 -*-
"""scan_reward_frames.py · 在 v1.19 录制的 215 张真机帧里找出「真的有推荐大拇指奖励」的帧

背景：上一轮 v1.19 离线验收只在 f0044 上跑，新 box 全空 —— 但那一场是**首领战、奖励行
里没有大拇指装备**，所以「空」是**正确答案**，验收无结论。
⇒ 先在全片里找出**确实有标记**的帧，再在那上面比 新 box vs 旧 box。

做法（两段，避免 215 张全 OCR 太慢）：
  ① 全片 find_reward_mark（整图，不给 box）→ 报告每帧有没有、位置在哪（参考系）
  ② 只对命中的帧做 OCR 拿「关闭」坐标，算出新 box，判定命中点在新 box 内 / 旧 box 内
"""
import os
import sys
import glob
import json

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
K = 1264 / 1080.0
SHIFT = 2780 - 1920 * K


def to_ref(img):
    """设备帧 → 参考帧（照抄 RefMapper.toRef 的两段拼接）"""
    H, W = img.shape[:2]
    out = np.zeros((REF_H, REF_W, 3), np.uint8)
    top_src_h = int(round(TOP * K))
    if top_src_h < H:
        out[0:TOP, :] = cv2.resize(img[0:top_src_h, :], (REF_W, TOP),
                                   interpolation=cv2.INTER_AREA)
    sy0 = top_src_h + int(round(SHIFT))
    if sy0 < H:
        out[TOP:, :] = cv2.resize(img[sy0:H, :], (REF_W, REF_H - TOP),
                                  interpolation=cv2.INTER_AREA)
    return out


def main():
    files = sorted(glob.glob(os.path.join(HERE, 'rec', '*.png')))
    if not files:
        print('没有录像帧')
        return
    print('录像帧 %d 张（%s … %s）' % (len(files), os.path.basename(files[0]),
                                  os.path.basename(files[-1])))
    print('阈值：形状>=%.2f 配色>=%.2f（find_reward_mark 默认）'
          % (badge_mod.REWARD_SHAPE_MIN, badge_mod.REWARD_COLOR_MIN))
    print()
    print('阶段① 整图扫 find_reward_mark（不给 box）')
    hit_frames = []
    for i, p in enumerate(files):
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        ref = to_ref(img)
        hits = badge_mod.find_reward_mark(ref, box=(0, 0, REF_W, REF_H), top=3)
        if hits:
            best = hits[0]
            hit_frames.append((os.path.basename(p), best, len(hits), ref))
            print('  ★ %s  形状 %.3f 配色 %.3f  参考(%d,%d) 缩放 %.2f  共%d个'
                  % (os.path.basename(p), best[0], best[1], best[2], best[3],
                     best[4], len(hits)))
        if (i + 1) % 25 == 0:
            print('    ... 已扫 %d/%d' % (i + 1, len(files)))

    print()
    if not hit_frames:
        print('❌ 整段录像里没有任何一帧带推荐大拇指标记')
        print('   ⇒ 离线无法验收 v1.19 的图标通道（不是代码错，是**素材里没有正样本**）')
        return
    print('阶段② 命中帧逐个比 新 box vs 旧 box（真机 1264×2780）')
    OLD = (40, 840, 1020, 1140)
    try:
        from rapidocr_onnxruntime import RapidOCR
        eng = RapidOCR()
        have_ocr = True
    except Exception as e:                      # noqa: BLE001
        print('  (OCR 不可用: %s) ⇒ 关闭锚点用离线实测常量' % e)
        have_ocr = False

    verdicts = []
    for name, best, n, ref in hit_frames:
        cy = best[3]
        if have_ocr:
            res, _ = eng(ref)
            items = [{'text': t.strip(),
                      'cx': sum(q[0] for q in b) / 4, 'cy': sum(q[1] for q in b) / 4,
                      'conf': float(s)} for b, t, s in (res or [])]
        else:
            items = []
        new_box = EL._reward_box(items) if items else (20, 520, 560, 1020)
        in_new = new_box[1] <= cy <= new_box[3] and new_box[0] <= best[2] <= new_box[2]
        in_old = OLD[1] <= cy <= OLD[3] and OLD[0] <= best[2] <= OLD[2]
        print('  %s  标记参考(%d,%d)  新 box=%s → %s   旧 box=%s → %s'
              % (name, best[2], cy, new_box, '命中 ✓' if in_new else '漏 ✗',
                 OLD, '命中' if in_old else '漏'))
        verdicts.append((name, in_new, in_old, best))

    n_new = sum(1 for v in verdicts if v[1])
    n_old = sum(1 for v in verdicts if v[2])
    print()
    print('汇总：%d 个正样本帧  新 box 命中 %d  旧 box 命中 %d' % (len(verdicts), n_new, n_old))
    if n_new > n_old:
        print('⇒ ✅ v1.19 的「锚定关闭」修法有效：旧写死 y 确实会漏，真机这些帧靠新 box 才能找到')
    elif n_new == len(verdicts) and n_old == 0:
        print('⇒ ✅ 新 box 全中、旧 box 全漏 —— 正是 v1.19 修的那个 bug')
    elif n_new < len(verdicts):
        print('⇒ ⚠ 新 box 在部分正样本上仍漏，需要继续调 REWARD_CLOSE_UP_*')
    with open(os.path.join(HERE, 'reward_scan.json'), 'w', encoding='utf-8') as f:
        json.dump([{'frame': v[0], 'mark': v[3], 'in_new': v[1], 'in_old': v[2]}
                   for v in verdicts], f, ensure_ascii=False, indent=2)
    print('→ reward_scan.json')


if __name__ == '__main__':
    main()
