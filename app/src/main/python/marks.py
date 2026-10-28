# -*- coding: utf-8 -*-
"""marks.py · 地块标记的视觉识别（模板匹配）

模板来自游戏 UI 包（`game.bundle` → AreaBlock.prefab 的 bossIcon/recommendIcon/
cloverIcon/redEquipIcon 四个 Image 的精灵，见 prefab_icons.py 的导出）：
    top_int_BOSS_0001   = 首领
    mid_ico_tuijian_0002= 大拇指（推荐 = 掉你追踪中的装备/符文）
    DL_siyecao          = 幸运草（宝藏战）
    mid_ico_map_0001    = 红装（SS 装）

用法:
    python marks.py runs/board_clean.png            # 多尺度扫描，打印每格命中的标记
    python marks.py runs/board_clean.png --scales 1.5 5 0.25
"""

# ─────────────────────────────────────────────────────────────────────────────
# 【Android 适配补丁 · 由 android_autoexplore/tools/port_android.py 注入，勿手改】
# Chaquopy 里 __file__ 指向 APK 内只读资源，模板/数据表在 filesDir/mapbot_pack
#  ⇒ 资源根一律走环境变量，未设置时回退 PC 原行为（便于与 PC 对拍）
import os as _os

_MAPBOT_ROOT = _os.environ.get('MAPBOT_ROOT') or _os.path.dirname(_os.path.abspath(__file__))
_MAPBOT_RUNS = _os.environ.get('MAPBOT_RUNS') or _os.path.join(_MAPBOT_ROOT, 'runs')
_MAPBOT_DT = _os.environ.get('MAPBOT_DT') or _os.path.join(_MAPBOT_ROOT, 'server_datatable.json')
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np

TPL_DIR = os.path.join(_MAPBOT_ROOT, 'templates', 'marks')
MARKS = [('boss', 'bossIcon__top_int_BOSS_0001.png'),
         ('recommend', 'recommendIcon__mid_ico_tuijian_0002.png'),
         ('clover', 'cloverIcon__DL_siyecao.png'),
         ('redEquip', 'redEquipIcon__mid_ico_map_0001.png')]

GRID = dict(x0=36.0, y0=1002.0, cx=144.0, cy=144.0, cols=7, rows=5)
# ⭐ 2026-09-25 实机重新标定（旧值 x0=21 y0=941 148.3x154.3 是错的，第 1 行偏 56px）：
#   地块贴图设计 30x30、格距 32px，游戏按 4.5 倍画 ⇒ 屏幕格距 32*4.5 = 144.0，
#   棋盘左上 = (36, 1002)，单格贴图 135x135 居中在 144 里。重现见 fit_art.py。


# 按类型的门槛（2026-09-26）：clover 收紧，挡掉误报的幸运草
TYPE_MIN = {'clover': (0.90, 0.75),
            'boss': (0.90, 0.85)}   # ⭐ boss 也要严（防普通格被误标 ✗ 用户 2026-09-27）
# ⭐ 标记只可能出现在格心 ±65px（1080p ✓ 四标记样本实测 ✓ = 0.45 格）
MARK_BOX_REF = 65.0
MARK_MARGIN = 0.06      # ⭐ 同格多标记：与最高分相差 ≤0.06 的类型也算命中 ✓
SHAPE_MIN = 0.80           # ⭐ 形状下限（噪声 ≤0.86 但配色差 ✗；真标记 0.82~0.97 ✓）
COLOR_MIN = 0.68           # ⭐ 配色下限（NCC，对雾格变暗不敏感 ✓；噪声 0.45~0.65 ✗）
GLYPH_KEEP = 1.0           # （保留：1.0 = 不裁剪；裁过 0.62 反而更差 ✗）          # ⭐ 只保留模板中间 62%（挖掉共有的沙地圆角底纹 ✓）
GLYPH_SCALES = [round(3.8 + 0.1 * i, 2) for i in range(15)]   # ⭐ 真标记尺度 3.8~5.2

# ⭐⭐⭐ v1.63 **每个模板每帧取几个候选峰**（治「一图只能认一个标记」✗）—— 照抄 PC
#   用户口径（PC 原话）：「**能不能认得一个格子里有四个标志那种**」
#   几何账：格 144px / 图标 64px ⇒ 2×2 = **4 个**（PC 720 系：格 96 / 图标 36 ⇒ 同样 2×2 ✓）
#   真机样本：PC `runs/acc2/anno_src.png` 的 `(2,1)` = `redEquip,boss,recommend,clover` ✓
#   ⇒ 取 8 给"同格 4 个 + 邻近格同类型"留余量（NMS 会抑制重叠，不会爆量 ✓）
#
#   ⚠ 手机端**已实证有病**（v1.63 造帧实验，`tools/probe_mark_dup_frame.py`）：
#     把 `(4,2)` 的 boss 像素**整格复制**到 `(4,5)`（两格真值**完全相同**）：
#       · 旧行为（`topn=1`）⇒ **只认到 1 格** ✗ ｜ `topn=8` ⇒ **认到 2 格** ✓
#     逐类型聚类（`tools/probe_mark_positions.py`，6 张真机帧）：
#       **`boss`/`redEquip` 每帧只聚出 1 个位置**（`boss` **正是目标**）✗
MARK_TOPN = 8

# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐⭐ v1.45 提速（施工单 ①）：**参考系定点窗口搜索**
# ⭐⭐⭐ v1.68 **修窗**：v1.45 的窗口只盖住了 2×2 图标块的**左上角一个**（见下）
#
# 为什么可以这么改（真机帧实测，2026-10-04）：
#   ① 参考系是「顶块锚顶 + 其余锚底」，两段斜率**都是 kx** ⇒ 参考系内尺寸恒定，
#      标记的真尺度只落在 **3.8 ~ 5.0** 附近；
#   ② 标记不是"随便落在格心附近"，而是**格子美术里的固定位置**。
# 于是「整条 1080×740 棋盘带 × 15 尺度 × 7 模板 = 105 次全图匹配」可以换成
# 「35 格 × 每格一个小窗 × 5 尺度」= 匹配面积降到约 1/40。
#
# ⛔⛔⛔ **v1.45 的窗口偏移是错的，v1.68 修正**（用户 2026-10-06 报「刚刚那把没有
#   识别到幸运草标志」⇒ 定位到本层）：
#     · v1.45 写的是 `MARK_OFF_REF = (-36,-36)`，注释还断言
#       「标记模板中心的落点相对格心**恒为** (-36,-36)」—— **这个断言是错的** ✗
#       它只对**四种图标里最左上那一个**成立（boss）✓
#     · 真实几何（用户 2026-10-06 明确口径 ＋ PC 标注帧实测**双向印证**）：
#       一个格子里有 **2×2 = 四个图标**，相对**格心**的落点：
#         左上 (-36,-36) = **boss** 首领
#         右上 (+22,-36) = **红装** redEquip
#         左下 (-36,+23) = **幸运草** clover
#         右下 (+22,+22) = **大拇指** recommend
#       ⇒ 整块的**块心 = (-7,-7)**，四角相对块心最远 **±29px**
#     · ⚠ PC 自己的注释早就写明了这件事（`mapbot_pc/marks.py`：
#       「格 96px / 图标 36px ⇒ **2×2 = 4 个**」），而手机端 v1.45 却按**单个图标**取了
#       偏移 ⇒ 窗口（±14）永远只在 boss 那一角打转 ⇒ **幸运草/红装/大拇指一律认不到** ✗
#     · 为什么一直没被发现：**boss 是四个里唯一"永远也认得到"的**（它就在旧窗中心）
#       ⇒ 日志看着一直有输出、门禁也绿（旧对拍基准 `scan_board` 是全图版，
#         它的"多报"被当成噪声解释掉了）⇒ **静默失效、fail-open** ✓
#
# ⭐ v1.68 定案参数（`tools/` 侧 13 张真机/标注帧全量对拍得出，见 README §6.66）：
#     · `MARK_OFF_REF = (-7,-7)`（块心）
#     · `FAST_SEARCH_R = 32.0`（±29 实测极值 + 3px 余量）
#     · `FAST_SCALES` 改成 **(3.8,4.1,4.4,4.7,5.0)**：
#       实测幸运草的最优落在 **4.9**（旧 5 档最高只到 4.6 ⇒ 差一点）；
#       ⚠ 试过砍到 3 档提速 ⇒ **三张真机帧当场丢 boss** ✗ ⇒ 不许再砍 ✗
#     · 判据：13 帧 **零丢格**、**零误报**、PC 标注真值格 `(2,1)` 的
#       `redEquip,boss,recommend,clover` **四个全认到** ✓；
#       最差余量 **+0.034**（现状 +0.033）⇒ 不贴边 ✓
#     · 代价：标记扫描一段约 **1.7×**（约 +0.9s/图）—— 换来的是幸运草能认到 ✓
#
# ⚠ 约束（用户 2026-10-04 定）：**纯视觉 + 全分辨率**。本层全部工作在 1080×1920
#   参考系里、只用视觉，不读内存；窗口/偏移都是**参考系常量**，与设备分辨率无关
#   （RefMapper 已经把任何设备归一到参考系）⇒ 全分辨率零特例 ✓
#
# ⚠ 与旧 `scan_board` 的**唯一语义差异**：旧版对每个 (模板,尺度) 只取**全图最优那一处**，
#   若那处不在格心附近就整档丢弃（会漏掉"别处有更高分噪声"的格子）；新版本**逐格取最好**，
#   因此**可能多找到**本来被噪声压掉的真标记（是"更少漏"的方向，不是误报方向）。
#   闸门（SHAPE_MIN / COLOR_MIN / TYPE_MIN）一个字没改 ⇒ 噪声照样过不去。
MARK_OFF_REF = (-7, -7)            # ⭐ v1.68：2×2 图标块的**块心**相对格心的偏移
FAST_SCALES = (3.8, 4.1, 4.4, 4.7, 5.0)    # ⭐ v1.68：补上 4.7/5.0（实测幸运草最优 4.9）
FAST_SEARCH_R = 32.0               # ⭐ v1.68：四角最远 ±29px + 3px 余量（旧值 14 只够 boss）


def _crop_glyph(tpl, keep=GLYPH_KEEP):
    h, w = tpl.shape[:2]
    nh, nw = max(4, int(h * keep)), max(4, int(w * keep))
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    return tpl[y0:y0 + nh, x0:x0 + nw].copy()


def load_tpls():
    """加载标记模板（**带模块级缓存**）

    ⭐ v1.45：原来每次调用都重新读盘 + PNG 解码（实测 2.4ms/次，而 `scan_board` 每轮都调一次）。
    模板在运行期不会变 ⇒ 缓存安全。缓存键带上 `TPL_DIR`/`_MAPBOT_ROOT`，
    这样门禁里改环境变量/临时换目录时**不会拿到别的目录的旧模板** ✓
    想强制重载（极少用）：`load_tpls.cache_clear()`。
    """
    _key = (TPL_DIR, _MAPBOT_ROOT)
    _hit = _TPL_CACHE.get(_key)
    if _hit is not None:
        return _hit
    out = _load_tpls_raw()
    _TPL_CACHE[_key] = out
    return out


_TPL_CACHE = {}


def _load_tpls_raw():
    out = {}
    for key, fn in MARKS:
        p = os.path.join(TPL_DIR, fn)
        if not os.path.exists(p):
            continue
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        out[key] = img
    # ⭐ 2026-09-26：额外加载「实测裁出来」的幸运草模板
    #   （幻少那台 recommend 会压过 clover ⇒ 用真实像素重裁一个，自匹配 0.978/0.931 ✓）
    _live = os.path.join(_MAPBOT_ROOT,
                         'templates', 'clover_live.png')
    if os.path.exists(_live):
        _img = cv2.imdecode(np.fromfile(_live, dtype=np.uint8),
                            cv2.IMREAD_UNCHANGED)
        if _img is not None and _img.ndim == 3 and _img.shape[2] == 4:
            out['clover_live'] = _img
    # ⭐ 2026-09-26：把 `templates/<类型>_*.png` 全部当作该类型的**样本变体** ✓
    #   （用户确认过的实拍样本裁出来的模板，比游戏原始小图标更能分清大拇指/幸运草 ✓）
    import glob as _glob
    _tdir = os.path.join(_MAPBOT_ROOT, 'templates')
    _variants = {}
    for _f in _glob.glob(os.path.join(_tdir, '*.png')):
        _base = os.path.basename(_f)[:-4]
        _typ = _base.split('_')[0]
        if _typ in out and _base != _typ:
            try:
                _im = cv2.imdecode(np.fromfile(_f, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if _im is not None and _im.ndim == 3 and _im.shape[2] == 4:
                    _variants.setdefault(_typ, []).append(_im)
            except Exception:       # noqa: BLE001
                pass
    for _typ, _lst in _variants.items():
        out[_typ + '_v'] = _lst        # 变体列表（scan_board 会取最高分 ✓）


    return out


def match_at_scales(bgr, tpl_rgba, scales, topn=1, min_score=None):
    """多尺度模板匹配，返回 [(score, scale, cx, cy, w, h)]（score 越大越像）

    ⚠ 2026-09-25 加防御：调用方可能塞进 4 通道图（带 alpha 的 PNG）或灰度图，
      OpenCV 会报 `type == _templ.type()` 直接崩。这里统一成 3 通道 float32；
      掩码统一成 CV_8U（OpenCV 只认 8U/32F，且必须和模板同尺寸）。

    ⭐⭐⭐⭐ v1.63 **`topn`（同一尺度返回几个峰）** —— 照抄 PC 未提交改动
      （PC `marks.py:match_at_scales`，配合 `MARK_TOPN = 8`）
      治「**一图/一格只能认一个标记**」✗

      ## 根因
        `cv2.minMaxLoc(res)` ⇒ **每个尺度只回 1 个点**（= 该尺度上的**全局最优**）
        ⇒ 同一模板出现在**两格**时，分高的那格**在每个尺度上都赢**
        ⇒ 另一格**连候选都不是** ⇒ 不被当目标 ⇒ 计划以为清完了 ✗✗

      ## ⭐ 手机端**已实证有病**（v1.63 造帧实验，`tools/probe_mark_dup_frame.py`）
        把矿洞帧 `(4,2)` 那一格的像素**整格复制**到 `(4,5)`（两格真值**完全相同**）：
          · 现状（`topn=1`）⇒ **只认到 1 格**（`(4,2)`）✗
          · `topn=8`      ⇒ **认到 2 格**（`(4,2)` + `(4,5)`）✓
        逐类型聚类（`tools/probe_mark_positions.py`，6 张真机帧）：
          · **`boss` / `redEquip`：每帧只聚出 1 个位置** ✗（而 `boss` **正是目标**）
          · `recommend`：多尺度**偶然**给出 2~3 个位置（时好时坏）
        ⇒ 这段"同格多标记按位置保留"的聚合（`_dedup_candidates`，注释里写着
          `保 4 标记格`）**本来就是为多标记写的，却因上游只给 1 个点而从来没派上用场** ✗

      ## 实现
        `topn > 1` 时做**非极大值抑制**：按分数取峰，抑制掉与已选峰距离 < `nms_r`
        的邻居，直到取满 `topn` 个或低于 `min_score`
      ⚠ **默认 `topn=1` = 老行为**（逐位不变）⇒ 不影响没传参的调用方 ✓
      ⚠ `min_score`（默认 None）**只用于提前停止**；真正的门槛仍由调用方
        （`scan_board_fast` 的 `thr` / `TYPE_MIN`）把关 ⇒ 不改变判据语义 ✓
      ⚠ 抑制半径按**模板尺寸**算（同一图标在不同尺度上重叠 ⇒ 只留最好的那个）✓
    """
    if bgr is None:
        return []
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    elif bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
    th, tw = tpl_rgba.shape[:2]
    rgb = tpl_rgba[:, :, :3].astype(np.float32)
    alpha = np.where(tpl_rgba[:, :, 3] > 32, 255, 0).astype(np.uint8)
    H, W = bgr.shape[:2]
    src = bgr.astype(np.float32)
    out = []
    for s in scales:
        w, h = int(round(tw * s)), int(round(th * s))
        if w < 6 or h < 6 or w >= W or h >= H:
            continue
        t = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_LINEAR)
        m = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_NEAREST)
        if int((m > 0).sum()) < 20:
            continue
        res = cv2.matchTemplate(src, t, cv2.TM_SQDIFF, mask=m)
        res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
        denom = float((m > 0).sum()) * 255.0 * 255.0        # 0=完全一致
        if int(topn) <= 1:
            # ---- 老路径：全局最优 1 个（**逐位不变** ✓）----
            mn, _, mnloc, _ = cv2.minMaxLoc(res)
            out.append((1.0 - mn / denom, float(s),
                        mnloc[0] + w / 2.0, mnloc[1] + h / 2.0, w, h))
            continue
        # ---- 新路径：非极大值抑制取前 topn 个峰（照抄 PC）----
        nms_r = max(8, int(round(min(w, h) * 0.5)))
        work = res.copy()
        for _ in range(int(topn)):
            mn, _mx, loc, _l2 = cv2.minMaxLoc(work)
            score = 1.0 - mn / denom
            if min_score is not None and score < float(min_score):
                break
            out.append((score, float(s), loc[0] + w / 2.0, loc[1] + h / 2.0, w, h))
            x0_, y0_ = loc
            ya, yb = max(0, y0_ - nms_r), min(work.shape[0], y0_ + nms_r + 1)
            xa, xb = max(0, x0_ - nms_r), min(work.shape[1], x0_ + nms_r + 1)
            work[ya:yb, xa:xb] = 1e12
    return out


def color_score(bgr, tpl_rgba, cx, cy, scale):
    """掩码区域的**逐通道配色一致性**（0~1，越大越像）

    ⚠ 2026-09-25 加：boss 与 redEquip 两个图标都是"沙地底 + 红色记号"，
      纯形状分（TM_SQDIFF）会把 boss 格也认成 redEquip（实测每张图都串）✗。
      源码里两者配色其实不同：boss 深红 (179,62,62)、redEquip 亮红 (230,80,80) + 金色 (255,236,140)
      ⇒ 逐通道算零均值相关，取平均，就能分开。
    """
    if bgr is None or tpl_rgba is None:
        return 0.0
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    elif bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
    th, tw = tpl_rgba.shape[:2]
    w, h = int(round(tw * scale)), int(round(th * scale))
    if w < 6 or h < 6:
        return 0.0
    t = cv2.resize(tpl_rgba[:, :, :3].astype(np.float32), (w, h),
                   interpolation=cv2.INTER_LINEAR)
    m = cv2.resize(np.where(tpl_rgba[:, :, 3] > 32, 255, 0).astype(np.uint8), (w, h),
                   interpolation=cv2.INTER_NEAREST) > 0
    x0, y0 = int(round(cx - w / 2.0)), int(round(cy - h / 2.0))
    sub = bgr[y0:y0 + h, x0:x0 + w]
    if sub.shape[0] != h or sub.shape[1] != w or int(m.sum()) < 20:
        return 0.0

    def ncc(a, b):
        a = a.astype(np.float32) - float(a.mean())
        b = b.astype(np.float32) - float(b.mean())
        if a.std() < 1e-6 or b.std() < 1e-6:
            return 0.0
        return float((a / a.std() * (b / b.std())).mean())

    return float(np.mean([ncc(sub[:, :, i][m], t[:, :, i][m]) for i in range(3)]))


MATCH_MIN = 0.85          # 形状分下限（原阈值）


def scan(img_path, scales, thr):
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    tpls = load_tpls()
    res = {}
    for key, tpl in tpls.items():
        hits = [r for r in match_at_scales(img, tpl, scales) if r[0] >= thr]
        hits.sort(reverse=True)
        keep = []
        for h in hits:
            cx, cy = h[2], h[3]
            r = int((cy - GRID['y0']) // GRID['cy']) + 1
            c = int((cx - GRID['x0']) // GRID['cx']) + 1
            if not (1 <= r <= 5 and 1 <= c <= 7):
                continue
            if any(abs(cx - k[2]) < 60 and abs(cy - k[3]) < 60 for k in keep):
                continue            # 同一图标多尺度重复命中
            keep.append((h[0], h[1], cx, cy, r, c))
        res[key] = keep
    return img, res


def default_scales():
    return [round(2.0 + 0.25 * i, 3) for i in range(17)]      # 2.0 .. 6.0


def _jobs_of(tpls=None):
    """(类型名, RGBA 模板) 列表：列表型变体逐个展开、归到基础类型 ✓

    ⭐ v1.45：从 `scan_board` 里抽出来（纯重构，行为不变），供 `scan_board_fast` 共用。
    ⭐ v1.68：**按 (基础类型, 模板字节) 去重** —— `clover_live.png` 会被加载**两次**
      （一次作 `out['clover_live']`、一次被 `templates/*.png` 的 glob 当 `clover` 的
      样本变体再收一遍），两个模板**逐字节相同**（md5 均 `0e0c6395f867`）、
      `base_name` 也同为 `clover` ⇒ 每个尺度、每格都**白算一遍**（7 个里废 1 个）✗
      ⚠ 去重是**逐位等价**的：两者对同一 (格, 尺度) 的 `best`/闸门/候选元组完全相同，
        而 `_dedup_candidates` 本来就按**名字**保留先到者 ⇒ 结果一字不差 ✓
        （`probe_z.py` 实测：去重前后 13 帧结果全等 ✓）
    """
    _all = tpls if tpls is not None else load_tpls()
    out = []
    _seen = set()
    for _k, _v in _all.items():
        for _t in (_v if isinstance(_v, list) else [_v]):
            _name = _k.replace('_v', '') if isinstance(_v, list) else _k
            _sig = (_name.replace('_live', '').replace('_desk', '').replace('_real', ''),
                    _t.shape, np.ascontiguousarray(_t).tobytes())
            if _sig in _seen:
                continue
            _seen.add(_sig)
            out.append((_name, _t))
    return out


def _dedup_candidates(out):
    """收尾：同格多标记按**位置**区分 ✓（纯重构，逐字搬自 `scan_board` 尾部）

    ⭐ 2026-09-27：clover ↔ recommend 这对要分得更开才算两个真标记 ✓
      实测（用户报）同一格的**同一个大拇指徽章**上，幸运草模板能偏 ~20px 命中 ✗
      ⇒ 被当成第二个标记 ⇒ 白摇一次色子（耗幸运草 ✗）
      徽章宽约 58px ⇒ 这对要求分开 ≥35px ✓；其余组合仍 18px ✓（保 4 标记格 ✓）
    """
    for _cell, _d in out.items():
        _cand = _d.pop('_cand', [])
        if not _cand:
            continue
        _cand.sort(reverse=True)
        _keep, _pos = [], []
        _STRICT = {('clover', 'recommend'), ('recommend', 'clover')}
        for _tot, _name, _sc, _cs, _px, _py in _cand:
            _dup = False
            for _i2, (qx, qy) in enumerate(_pos):
                _gap = 35 if (_keep[_i2], _name) in _STRICT else 18
                if abs(_px - qx) < _gap and abs(_py - qy) < _gap:
                    _dup = True
                    break
            if _dup:
                continue
            if _name not in _keep:
                _keep.append(_name)
                _pos.append((_px, _py))
        _d['marks'] = _keep
        _d['best'] = round(_cand[0][0], 3)
    return out


def scan_board(img, thr=None, scales=None, region=None, use_color=True):
    """整盘扫描标记 -> {(row,col): {'marks': [...], 'at': (cx,cy), 'score': s}}

    region: 只搜棋盘区域 (x0,y0,x1,y1)，默认按 GRID 算，避免 HUD 误命中
    use_color: ⭐ 用**形状 + 配色**双判（2026-09-25 加）——boss 与 redEquip 形状极像，
        只用形状分每张图都会把 boss 格也认成 redEquip（用户报的"我游戏里没看到红装"）

    ⚠ v1.45：本函数是**旧实现**，全图 105 次匹配（~10s/次），保留作**对拍基准**。
      热路径已改用 `scan_board_fast`（见下）。
    """
    thr = SHAPE_MIN if thr is None else thr   # ⭐ 默认用形状下限（原来写死 0.90 ⇒ 幻少全漏 ✗）
    scales = scales or GLYPH_SCALES          # ⭐ 收紧到真标记的尺度区间
    if region is None:
        region = (0, int(GRID['y0']) - 10, img.shape[1],
                  int(GRID['y0'] + 5 * GRID['cy']) + 10)
    x0, y0, x1, y1 = region
    sub = img[y0:y1, x0:x1]
    out = {}
    _jobs = _jobs_of()
    for key, tpl in _jobs:
        # ⭐⭐⭐ v1.63 **每模板取多个候选点**（旧行为只取 1 个 ⇒ 一图只能认一个标记 ✗）
        #   ⇒ `topn=MARK_TOPN`：NMS 取前 N 个峰；`min_score=thr*0.9` **只用于提前停止**
        #     （真正的门槛判据仍是下面的 `if sc < thr: continue` 与 `TYPE_MIN` ✓）
        for sc, s, cx, cy, w, h in match_at_scales(sub, tpl, scales,
                                                   topn=MARK_TOPN, min_score=thr * 0.9):
            if sc < thr:
                continue
            gx, gy = cx + x0, cy + y0
            r = int((gy - GRID['y0']) // GRID['cy']) + 1
            c = int((gx - GRID['x0']) // GRID['cx']) + 1
            if not (1 <= r <= 5 and 1 <= c <= 7):
                continue
            # ⭐ 2026-09-27：标记只在格心 ±MARK_BOX 内（用户建议 ✓ 挡误报 ✓）
            _box = MARK_BOX_REF * (float(GRID['cx']) / 144.0)
            _ccx = GRID['x0'] + (c - 0.5) * GRID['cx']
            _ccy = GRID['y0'] + (r - 0.5) * GRID['cy']
            if abs(gx - _ccx) > _box or abs(gy - _ccy) > _box:
                continue
            cs = color_score(img, tpl, gx, gy, s) if use_color else 1.0
            if use_color and cs < COLOR_MIN:
                continue            # 配色不像 ⇒ 多半是另一个图标（boss↔redEquip 串味）
            # ⭐ 2026-09-26 用户指出：**一格可以同时有多个标记**
            #   （幻少实测 2-3 格「既是首领又是幸运草」✓）
            #   ⇒ 先把所有过闸候选都记下来，最后按「与本格最高分相差 ≤MARK_MARGIN」决定保留谁 ✓
            base_name = key.replace('_live', '').replace('_desk', '').replace('_real', '')
            # 按类型门槛（clover 更严，挡掉误报）
            _tmin = TYPE_MIN.get(base_name)
            if _tmin and (sc < _tmin[0] or cs < _tmin[1]):
                continue
            d = out.setdefault((r, c), {'marks': [], 'at': (int(gx), int(gy)),
                                        'score': round(sc, 3), 'color': round(cs, 3),
                                        '_cand': []})
            d['_cand'].append((sc + cs, base_name, round(sc, 3), round(cs, 3),
                               int(gx), int(gy)))
            d['score'] = max(d['score'], round(sc, 3))
            d['color'] = round(max(d.get('color') or 0, cs), 3)
    # 收尾：同格多标记按**位置**区分 ✓（v1.45 抽成 `_dedup_candidates`，逐字同源）
    return _dedup_candidates(out)


# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐⭐ v1.45：定点窗口版（热路径用它）
# ══════════════════════════════════════════════════════════════════════════

# (模板, 尺度) → (缩放后 rgb, 掩膜 m, nmask)。⭐ **逐位等价**记忆化：
#   `cv2.resize` 是确定性纯函数（同输入 + 同 interpolation 必得同输出，含浮点舍入），
#   缓存里存的正是那三个中间量，而 `matchTemplate` 与所有闸门判据的代码**一行不动** ✓
# ⚠ 缓存**不需要**清理逻辑：模板来自 `load_tpls()` 的**模块级缓存**，
#   运行期不会被回收、内容也不变（`load_tpls.cache_clear()` 全仓无人调用）。
_TPL_PREP = {}


def _tpl_prep(tpl_rgba, s):
    """(模板, 尺度) → (缩放后 rgb, 掩膜 m, nmask)。⭐ 逐位等价记忆化

    ⚠ 这三个量**只依赖 (模板, 尺度)**，与是哪一格**完全无关**。
      而 `scan_board_fast` 是 35 格 × 6 模板（v1.68 已去重 7→6）× 5 尺度 = **1050 次**调用，
      不同 (模板, 尺度) 组合只有 6×5 = **30 个** ⇒ **1020 次（97%）是重复计算**
      （每次 ≈ 1.6M 次乘法加法，真机上不便宜）。
    ⚠ key 用 `id(tpl_rgba)`：模板数组来自模块级 `load_tpls()` 缓存 ⇒ 运行期**不会被回收**、
      地址不会复用；再带上 `shape` 兜底，任何意外都不会串到别的模板上 ✓
    """
    key = (id(tpl_rgba), tpl_rgba.shape, s)
    hit = _TPL_PREP.get(key)
    if hit is not None:
        return hit
    th, tw = tpl_rgba.shape[:2]
    w, h = int(round(tw * s)), int(round(th * s))
    rgb = cv2.resize(tpl_rgba[:, :, :3].astype(np.float32), (w, h),
                     interpolation=cv2.INTER_LINEAR)
    m = cv2.resize(np.where(tpl_rgba[:, :, 3] > 32, 255, 0).astype(np.uint8), (w, h),
                   interpolation=cv2.INTER_NEAREST)
    nmask = int((m > 0).sum())
    val = (rgb, m, nmask)
    _TPL_PREP[key] = val
    return val


def _match_window(img, tpl_rgba, s, ecx, ecy, half):
    """在 **格心 (ecx,ecy) ± half** 这个小窗里做一次带掩码 TM_SQDIFF

    返回 (score, cx, cy) 或 None（窗口越界/模板太小 ⇒ 与原版"越界不报"一致）。

    ⚠ 窗的取法：要让**模板中心**落在 [ecx±half]，等价于模板**左上角**落在
      [ecx−half−w/2, ecx+half−w/2] ⇒ 裁 `2*half + w` 宽的一小块。
      这与旧版「全图搜 + 事后按 MARK_BOX 过滤」覆盖的是**同一批合法位置** ✓
    """
    th, tw = tpl_rgba.shape[:2]
    w, h = int(round(tw * s)), int(round(th * s))
    if w < 6 or h < 6:
        return None
    x0 = int(round(ecx - half - w / 2.0))
    y0 = int(round(ecy - half - h / 2.0))
    cw, ch = int(2 * half) + w, int(2 * half) + h
    H, W = img.shape[:2]
    if x0 < 0 or y0 < 0 or x0 + cw > W or y0 + ch > H:
        return None
    sub = img[y0:y0 + ch, x0:x0 + cw]
    if sub.size == 0:
        return None
    # ⭐ 这三个量只与 (模板, 尺度) 有关 ⇒ 记忆化（逐位等价，见 `_tpl_prep` 注释）
    rgb, m, nmask = _tpl_prep(tpl_rgba, s)
    if nmask < 20:
        return None
    res = cv2.matchTemplate(sub.astype(np.float32), rgb, cv2.TM_SQDIFF, mask=m)
    res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
    mn, _mx, mnloc, _mxl = cv2.minMaxLoc(res)
    # 与 `match_at_scales` 同一套归一化（0=完全一致）⇒ 分数口径完全一致 ✓
    sc = 1.0 - mn / (float(nmask) * 255.0 * 255.0)
    return (float(sc), x0 + mnloc[0] + w / 2.0, y0 + mnloc[1] + h / 2.0)


def scan_board_fast(img, thr=None, scales=None, use_color=True, tpls=None,
                    offset=None, search_r=None, cell_stats=None):
    """⭐⭐⭐ v1.45 参考系**定点窗口**标记扫描（热路径版）

    与 `scan_board` 的差异（已论证，见文件顶 MARK_OFF_REF 那段注释）：
      · 只扫 **35 个格心 ± search_r**（不是整条 1080×740 棋盘带）；
      · 尺度只取 `FAST_SCALES`（实测真标记尺度区间，15 档 → 5 档）；
      · 逐格取最好（旧版每档只取全图最优 ⇒ 会被别处的噪声把真标记压掉，会漏）。
    闸门（thr / COLOR_MIN / TYPE_MIN / 多标记去重）**一个字没改** ⇒ 不会因此多报。

    `cell_stats`（可选，dict）：把每格的最高形状分与耗时塞进去（诊断/标定用）。
    """
    thr = SHAPE_MIN if thr is None else thr
    scales = tuple(scales if scales is not None else FAST_SCALES)
    half = float(FAST_SEARCH_R if search_r is None else search_r)
    off = MARK_OFF_REF if offset is None else offset
    out = {}
    if img is None:
        return out
    jobs = _jobs_of(tpls)
    rows, cols = int(GRID['rows']), int(GRID['cols'])
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            _ccx, _ccy = cell_center(r, c)
            ecx, ecy = _ccx + off[0], _ccy + off[1]
            _best_any = 0.0
            for key, tpl in jobs:
                best = None
                for s in scales:
                    got = _match_window(img, tpl, s, ecx, ecy, half)
                    if got is None:
                        continue
                    if best is None or got[0] > best[0]:
                        best = got + (s,)
                if best is None:
                    continue
                sc, gx, gy, s = best
                if sc > _best_any:
                    _best_any = sc
                if sc < thr:
                    continue
                cs = color_score(img, tpl, gx, gy, s) if use_color else 1.0
                if use_color and cs < COLOR_MIN:
                    continue
                base_name = key.replace('_live', '').replace('_desk', '').replace('_real', '')
                _tmin = TYPE_MIN.get(base_name)
                if _tmin and (sc < _tmin[0] or cs < _tmin[1]):
                    continue
                d = out.setdefault((r, c), {'marks': [], 'at': (int(gx), int(gy)),
                                            'score': round(sc, 3), 'color': round(cs, 3),
                                            '_cand': []})
                d['_cand'].append((sc + cs, base_name, round(sc, 3), round(cs, 3),
                                   int(gx), int(gy)))
                d['score'] = max(d['score'], round(sc, 3))
                d['color'] = round(max(d.get('color') or 0, cs), 3)
            if cell_stats is not None:
                cell_stats['%d,%d' % (r, c)] = round(_best_any, 3)
    return _dedup_candidates(out)


def probe_top_fast(img, scales=None, tpls=None, offset=None, search_r=None):
    """⭐ v1.45：`probe_top` 的**定点窗口版**（诊断用，语义等价、快 ~9 倍）

    与 `probe_top` 同一件事：**每个标记模板各自最好的那处**（不设闸门、给裸分），
    供反馈包分清「真没有标记」 vs 「有标记但被机身偏暗压到闸门之下」。
    只是把搜索范围收到**格心窗口**（标记只可能在那儿）——对诊断而言更贴题
    （旧版全图找出来的最高分常常落在棋盘外/别格，反而看不出"这一格差多少"）。

    ⚠ 同样**只做诊断，不参与任何判定**（调用方别拿它当命中用 ✗）
    """
    if img is None:
        return []
    scales = tuple(scales if scales is not None else GLYPH_SCALES)
    half = float(FAST_SEARCH_R if search_r is None else search_r)
    off = MARK_OFF_REF if offset is None else offset
    rows, cols = int(GRID['rows']), int(GRID['cols'])
    jobs = _jobs_of(tpls)
    best_per = {}
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            _ccx, _ccy = cell_center(r, c)
            ecx, ecy = _ccx + off[0], _ccy + off[1]
            for key, tpl in jobs:
                base = key.replace('_live', '').replace('_desk', '').replace('_real', '')
                cur = best_per.get(base)
                for s in scales:
                    got = _match_window(img, tpl, s, ecx, ecy, half)
                    if got is None:
                        continue
                    sc, gx, gy = got
                    if cur is None or sc > cur[0]:
                        cur = (sc, s, gx, gy, r, c, key)
                if cur is not None:
                    best_per[base] = cur
    out = []
    for base, (sc, s, gx, gy, r, c, key) in best_per.items():
        tpl = None
        for k2, t2 in jobs:
            if k2 == key:
                tpl = t2
                break
        cs = color_score(img, tpl, gx, gy, s) if tpl is not None else 0.0
        out.append({'tpl': base, 'shape': round(float(sc), 3), 'color': round(float(cs), 3),
                    'rc': '%d,%d' % (r, c), 'scale': round(float(s), 2)})
    out.sort(key=lambda d: -d['shape'])
    return out


def probe_top(img, top=1, scales=None, region=None):
    """⭐ 2026-10-02 v1.22 诊断用：**每个标记模板各自最好的那处**（不设闸门，给裸分）

    用途：反馈包里出现 `marks_scan: none` 时，一眼分清两件完全不同的事 ——
        · **棋盘上真没有标记**（每个模板的最好分都很低）
        · **有标记，但被机身偏暗/偏色压到闸门之下**（形状 0.74 / 配色 0.84 这种"近失"）
      （2026-10-02 两个 nubia 包的疑问正是后者：真机帧 boss 形状分只有 0.741@(2,4)，
       而 boss 闸门要 0.90 —— **肉眼看得见图标、代码扫不到** ✗）

    ⚠ **只做诊断，不参与任何判定**（返回裸分；调用方别拿它当命中用 ✗）
    ⚠ 必须**按模板分别取最好**（不是全局 top-N）—— 全局 top-N 会被别的类型刷屏，
      "boss 到底差多少"这个最关键的信息反而看不见 ✗（2026-10-02 踩过一次）
    """
    if img is None:
        return []
    scales = scales or GLYPH_SCALES      # ⚠ 必须与 scan_board 同口径（否则"近失"看不到）
    if region is None:
        region = (0, int(GRID['y0']) - 10, img.shape[1],
                  int(GRID['y0'] + 5 * GRID['cy']) + 10)
    x0, y0, x1, y1 = region
    sub = img[y0:y1, x0:x1]
    rows = []
    for key, tpl in load_tpls().items():
        if isinstance(tpl, list):
            tpl = tpl[0]
        best = None
        for sc, s, cx, cy, w, h in match_at_scales(sub, tpl, scales):
            gx, gy = cx + x0, cy + y0
            r = int((gy - GRID['y0']) // GRID['cy']) + 1
            c = int((gx - GRID['x0']) // GRID['cx']) + 1
            if not (1 <= r <= 5 and 1 <= c <= 7):
                continue
            if best is None or sc > best[0]:
                best = (sc, s, gx, gy, key, r, c)
        if best is not None:
            sc, s, gx, gy, key, r, c = best
            rows.append({'tpl': key, 'shape': round(sc, 3),
                         'color': round(color_score(img, tpl, gx, gy, s), 3),
                         'rc': '%d,%d' % (r, c), 'scale': round(s, 2)})
    rows.sort(key=lambda d: -d['shape'])
    return rows


def cell_center(row, col):
    return (int(GRID['x0'] + (col - 0.5) * GRID['cx']),
            int(GRID['y0'] + (row - 0.5) * GRID['cy']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img')
    ap.add_argument('--scales', nargs=3, type=float, default=[1.5, 6.0, 0.25],
                    metavar=('START', 'END', 'STEP'))
    ap.add_argument('--thr', type=float, default=0.90)
    args = ap.parse_args()
    s0, s1, st = args.scales
    scales = []
    x = s0
    while x <= s1 + 1e-9:
        scales.append(round(x, 3))
        x += st
    img, res = scan(args.img, scales, args.thr)
    print('图片:', args.img, '尺度 %d 档 %s..%s  阈值 %.2f' % (len(scales), s0, s1, args.thr))
    total = 0
    for key in ('boss', 'recommend', 'clover', 'redEquip'):
        hits = res.get(key, [])
        total += len(hits)
        print('%-10s 命中 %d' % (key, len(hits)))
        for sc, s, cx, cy, r, c in hits[:6]:
            print('     score=%.3f 缩放=%.2f 位置=(%d,%d)  格=(%d行,%d列)' % (sc, s, cx, cy, r, c))
    print('合计命中', total)


if __name__ == '__main__':
    main()
