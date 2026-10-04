# -*- coding: utf-8 -*-
"""fixed_ref.py · 手机端「参考系定点层」（提速施工单 ②）

为什么手机端反而**更适合**做这一层
------------------------------------
PC 端为了速度**锁死 720×1280**，所以它的 `fixed.py` 只能服务那一种分辨率 ✗。
手机端相反：任何设备的帧都被 `RefMapper` 归一到 **1080×1920 参考系**（顶块锚顶 +
其余锚底，两段斜率都是 kx）⇒ **参考系里的一套锚点/模板，天然对所有分辨率生效** ✓
这正是用户 2026-10-04 定的约束「不能抛弃全分辨率适应」所允许的形态：
定点化**不做在设备像素上**，而是做在**参考系**上。

它解决什么
----------
一局 ~130s 里 OCR 占 ~50%。其中相当一部分调用**根本不是"读会变的字"**，而是
「这个固定按钮/页签在不在」——实测端侧一次 OCR 1.2~2.5s，而定点模板匹配是**毫秒级**
（PC 端实测同口径：模板 6.8ms vs OCR 3.3s）。

本模块**只提供能力**（锚点 + 快查），不改变任何判定：
调用方一律「**先快查、没命中再走原来的 OCR/多尺度路**」⇒ 最坏情况＝原行为（慢一点），
绝不会因为模板没裁好而把某个面板认没 ✓（这是没有真机可验时的安全底线）

⚠ 仍然**必须 OCR** 的东西：体力数字、倒计时、图名、道具名、价格 ——「内容会变」的
  一律不许模板化（模板化的前提是"位置固定 + 长得固定"）。
"""
from __future__ import annotations

import os

import cv2
import numpy as np

REF_W, REF_H = 1080, 1920

# ── 资源根（与 layout/marks/spots 同口径：Chaquopy 里指向 filesDir/mapbot_pack） ──
_MAPBOT_ROOT = os.environ.get('MAPBOT_ROOT') or os.path.dirname(os.path.abspath(__file__))

# 固定 UI 模板目录（与 `explore_loop._find_ui_tpl` / `_tpl_hit` 同一批资源）
TPL_SUBDIR = ('templates', 'ui')

# ── 常用搜索带（**参考系**坐标，不是设备像素！）─────────────────────────
# ⚠ 限定搜索区能把匹配再快一个数量级；但写错区间会**静默永不命中**，
#   所以 `self_test()` 会检查 y0<y1 且在屏内（学 PC `fixed._check_bands` 的教训）。
BANDS = {
    'nav': (0, 1180, REF_W, REF_H),        # 底部导航条（5 个 tab 中心 y≈1890）
    'hud': (0, 0, REF_W, 200),             # 顶部 HUD（体力/倒计时/图名那一带）
    'panel_btn': (0, 400, REF_W, 1060),    # 图内面板按钮带（开打/探索/派遣）
    'settle': (0, 780, REF_W, 1080),       # 结算面板底部三键
}

_CACHE = {}


def anchors():
    """参考系锚点表：**直接取自 `layout.REF`**（唯一权威，绝不另抄一份 ✗）

    为什么必须同源：抄一份就会出现「两处坐标悄悄不一致」这类最难查的事故
    （PC 端 `fixed.py` 第一版就把设备像素当参考系写过，差 400px）。
    """
    import layout as _ly
    out = {}
    for k, v in _ly.REF.items():
        if isinstance(v, tuple) and len(v) == 2:
            out[k] = tuple(int(x) for x in v)
    return out


def anchor(name):
    """取一个参考系锚点 (x, y)；没有就抛 KeyError（别静默返回 None ✗）"""
    a = anchors()
    if name not in a:
        raise KeyError('未知锚点 %r（可用：%s）' % (name, sorted(a)))
    return a[name]


def tpl_dir():
    """模板目录：**环境变量 `MAPBOT_TPL_UI` 优先**（测试/离线裁模板/发版时用）

    ⚠ 有这个口子很重要：裁完模板要先在**离线帧**上跑正/负样本验一遍，
      那时模板还没进资源包（`assets/mapbot_pack/templates/ui`）⇒ 需要一个"指到别处"的方式。
      没有它就只能把半成品先塞进包里，等于拿运行环境做实验 ✗
    """
    env = os.environ.get('MAPBOT_TPL_UI')
    if env:
        return env
    return os.path.join(_MAPBOT_ROOT, *TPL_SUBDIR)


def tpl_dirs():
    """模板查找顺序（**多个目录，按序命中即用**）

    ① `MAPBOT_TPL_UI`（显式指定 ⇒ 只用它）
    ② 资源包 `assets/mapbot_pack/templates/ui`（随 APK 解包，正式来源）
    ③ ⭐ **公共目录 `/sdcard/Download/autoexplore/templates/ui`**（可用
       `MAPBOT_TPL_PUB` 覆盖）——这一条是**为"不出包也能上新模板"加的**：
       逻辑热更只带 `*.py`（不带 pack），而"从真机帧裁新模板"正是本工程最常见的迭代
       ⇒ 没有这个回退，每裁一个模板都要重打 71MB 整包 ✗
    ⚠ 顺序是"包内优先"：公共目录只做**新增/兜底**，不改包内已有模板的行为
      （想覆盖包内同名模板就走 `MAPBOT_TPL_UI`，那是有意为之的场景）。
    """
    env = os.environ.get('MAPBOT_TPL_UI')
    if env:
        return [env]
    pub = os.environ.get('MAPBOT_TPL_PUB') or '/sdcard/Download/autoexplore/templates/ui'
    return [os.path.join(_MAPBOT_ROOT, *TPL_SUBDIR), pub]


def load(name):
    """读一个 UI 模板（**带缓存**；按 `tpl_dirs()` 顺序找；都没有 ⇒ None，调用方走回退路 ✓）"""
    dirs = tuple(tpl_dirs())
    key = (dirs, name)
    if key in _CACHE:
        return _CACHE[key]
    t = None
    for d in dirs:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        try:
            t = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:       # noqa: BLE001
            t = None
        if t is not None:
            break
    _CACHE[key] = t
    return t


def find(img, name, region=None, scales=(1.0,), thr=0.80):
    """在 `img` 里找固定模板 `name` -> (cx, cy, score) 或 None

    · `region` 给名字（见 `BANDS`）或 (x0,y0,x1,y1)；**强烈建议给**（再快一个数量级）
    · `scales` 默认 **(1.0,)** —— 参考系是等比归一的，单尺度就够；
      给多档只是兜底（长屏非等比压缩那类），别默认扫 6 档白花钱。
    ⚠ 模板**装不进** region 时返回 None（不是"没找到"）——PC 端踩过：
      这种写错会静默永不命中；`FIXED_STRICT=1` 时直接抛出来。
    """
    t = load(name)
    if t is None or img is None:
        return None
    H, W = img.shape[:2]
    box = BANDS.get(region) if isinstance(region, str) else region
    x0, y0, x1, y1 = box or (0, 0, W, H)
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(W, int(x1)), min(H, int(y1))
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    th, tw = t.shape[:2]
    best = None
    for s in scales:
        w, h = int(round(tw * s)), int(round(th * s))
        if w < 8 or h < 8 or w >= sub.shape[1] or h >= sub.shape[0]:
            if os.environ.get('FIXED_STRICT') and s == 1.0:
                raise ValueError('模板 %r(%dx%d) 装不进 region %s（可用 %dx%d）'
                                 % (name, tw, th, box, sub.shape[1], sub.shape[0]))
            continue
        tt = cv2.resize(t, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(sub.astype(np.float32), tt.astype(np.float32),
                                cv2.TM_CCOEFF_NORMED)
        _mn, mx, _mnl, mxl = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (float(mx), mxl[0] + w / 2.0 + x0, mxl[1] + h / 2.0 + y0)
    if best and best[0] >= thr:
        return (int(best[1]), int(best[2]), round(best[0], 3))
    return None


def has(img, name, region=None, thr=0.80):
    """只要"在不在"（省一次元组解包）；模板缺失 ⇒ False（调用方应回退 OCR）"""
    return find(img, name, region=region, thr=thr) is not None


def self_test(verbose=True):
    """自检：① 锚点与 `layout.REF` 同源 ② band 合法且在屏内 ③ 模板自匹配必须命中

    ③ 是关键：模板文件存在**不等于**它能被匹配到（尺寸/通道/region 写错都会静默失效）。
    做法：把模板贴到一张黑底参考帧上、贴在自己裁出来的位置，
    然后要求 `find()` **恰好**把它找回来（学 PC `verify_fastpath.py` 的"正样本必须命中"）。
    """
    ok = True
    if verbose:
        print('=== fixed_ref 自检（参考系 %dx%d）===' % (REF_W, REF_H))
    # ① 同源
    try:
        a = anchors()
        if verbose:
            print('   锚点 %d 个（取自 layout.REF ✓）' % len(a))
    except Exception as e:      # noqa: BLE001
        print('   ✗ 读 layout.REF 失败：%r' % (e,))
        return False
    # ② band
    bad = [(k, v) for k, v in BANDS.items()
           if not (0 <= v[0] < v[2] <= REF_W and 0 <= v[1] < v[3] <= REF_H)]
    if bad:
        ok = False
        for k, v in bad:
            print('   ✗ band %-10s %s 非法（要 0≤x0<x1≤%d 且 0≤y0<y1≤%d）'
                  % (k, v, REF_W, REF_H))
    elif verbose:
        print('   ✓ %d 个 band 全部合法' % len(BANDS))
    # ③ 模板自匹配（遍历**所有**查找目录的并集）
    names = []
    for d in tpl_dirs():
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().endswith('.png') and f not in names:
                    names.append(f)
    names.sort()
    if not names:
        if verbose:
            print('   · 模板目录为空（%s）⇒ 跳过自匹配' % (tpl_dirs(),))
        return ok
    canvas = np.zeros((REF_H, REF_W, 3), dtype=np.uint8)
    for nm in names:
        t = load(nm)
        if t is None:
            ok = False
            print('   ✗ 模板 %s 读不出来' % nm)
            continue
        th, tw = t.shape[:2]
        if th >= REF_H or tw >= REF_W:
            print('   · %s 比参考帧还大 ⇒ 跳过' % nm)
            continue
        px, py = 40, 40
        canvas[py:py + th, px:px + tw] = t
        got = find(canvas, nm, region=(0, 0, px + tw + 8, py + th + 8), thr=0.80)
        canvas[py:py + th, px:px + tw] = 0
        want = (px + tw // 2, py + th // 2)
        if got is None:
            ok = False
            print('   ✗ %s 自匹配**没命中**（模板存在但匹配不到 —— region/尺寸写错？）' % nm)
        elif abs(got[0] - want[0]) > 2 or abs(got[1] - want[1]) > 2:
            ok = False
            print('   ✗ %s 自匹配位置偏：得 %s 期望 %s' % (nm, got, want))
        elif verbose:
            print('   ✓ %-22s 自匹配命中 @%s score=%.3f' % (nm, got[:2], got[2]))
    return ok


if __name__ == '__main__':
    import sys
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    raise SystemExit(0 if self_test() else 1)
