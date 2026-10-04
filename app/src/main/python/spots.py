# -*- coding: utf-8 -*-
"""spots.py · 地块识别（逐格分类）—— 2026-09-25 重写

原理（已实机标定，见 fit_art.py 与 tools/mapbot/README.md）：
  * 每个地块 = **一整张格子贴图**（地面+物件画在一起），设计尺寸 30x30/格、
    格距 32px；多格地块就是更大一张（94x30 = 3 格，靠 SpotShape 对齐）。
  * `AreaBlock.FreshBlock` → `SetNativeSize()`，屏幕缩放 = **4.5 倍**
    ⇒ 屏幕格距 = 32*4.5 = **144.0 px**，单格贴图 135x135。
  * 于是不需要盲扫模板：**把每格像素切出来，跟该图的候选贴图逐帧比相似度**
    （灰度零均值归一化互相关，对迷雾的灰化/明暗变化不变），取最高分。
  * 结果既能用来找「旅行商人 / 黄金宝库」，也能顺手认出每一格是什么地块。

用法:
    python spots.py board runs/board_clean.png --map 夏日海滩       # 打印整盘分类
    python spots.py target runs/board_clean.png --map 夏日海滩      # 只报商人/宝库格
    python spots.py live --map 夏日海滩                             # 抓当前屏幕再分类
    python spots.py base --map 夏日海滩 --write                     # 重新标定几何
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

ROOT = _MAPBOT_ROOT
UNIT = os.path.join(ROOT, 'templates', 'unit')
RUNS = _MAPBOT_RUNS
DT = _MAPBOT_DT

# ⭐ 2026-09-25 实机标定：设计格距 32px × 缩放 4.5 = 144.0；左上角 (36, 1002)
GRID = dict(x0=36.0, y0=1002.0, pitch=144.0, cx=144.0, cy=144.0, cols=7, rows=5)
SCALE = 4.5
DESIGN_PITCH = 32.0
DESIGN_TILE = 30.0
INNER = 3.0          # 裁掉设计尺寸的外圈像素（透明圆角，避免干扰）

# ⭐⭐ v1.35【`ratio` 分母口径开关】—— 治「同一台机，夏日海滩能跑、广袤草原跑不了」
#   'map'  （**默认**）= 分母取**本图全部地块模板亮度的中位** ⇒ 各图 ratio 分布同形
#                      ⇒ 同一道 0.75 阈值通吃所有图，且新图不用再标定 ✓
#   'cell'            = 旧口径（分母取该格所属地块自己的模板亮度）
#                      ⚠ 保留只为**离线对拍与回滚**；它配写死 0.75 会量纲错位 ✗
#   （真机实测 2026-10-02：Redmi/1280×2772，雾格绝对亮度 139.5
#      沙滩 139.5/201=0.694 ✓ ／ 草原 139.5/183=0.762 ✗ 越过 0.75 被误判成已揭示）
RATIO_DEN = (os.environ.get('MAPBOT_RATIO_DEN', 'map') or 'map').strip().lower()

# ⭐⭐⭐ v1.60【「已揭示」判定改**两趟相对法** —— 照抄 PC `mapbot_pc/spots.py:705-736`】
#   用户口径：「**照抄就行**」⇒ 结构逐字抄 PC；**只有一处数值是手机端标定的**（见下 ⚠）。
#
#   ── PC 原文（`mapbot_pc/spots.py:705-736`，摘要，逐字见 PC 仓）────────────────
#     # ── ⭐⭐⭐ 2026-10-02「已揭示」改**相对本帧基准**判定（两趟法）──────────
#     #   根因：`ratio >= 0.75` 是**绝对阈值**，而那一帧的 ratio 分布是
#     #       0.70 0.72 0.70 0.71 0.65 0.71 0.65   ← 第4行整排已揭示都只有 0.70~0.72
#     #   ⇒ 改用**本帧自身的雾格基准**（10 分位）×1.06，并保底 0.66：
#     #       雾格恒在基准附近 ⇒ 判为未揭示；明显高于基准 ⇒ 已揭示 ✓
#     #   ⚠ **必须两趟**（先收齐全盘 ratio 再判定）—— 逐格算时拿不到分布。
#     _base = 本帧 ratio 的 **10 分位**        # p10
#     _rev  = max(0.66, _base * 1.06)          # 地板 0.66、系数 1.06
#     revealed ⟺ ratio >= _rev
#
#   ## ⚠⚠ 手机端唯一的分叉：**地板不是 0.66，是 0.80**（有实测，不是口味）
#     PC 的 0.66 之所以安全，是因为 PC 的 `ratio` 分母 = **该格自己的模板亮度**
#     ⇒ 雾格恒定 ≈0.65（项目 §5/§7 实测），雾带**很窄**（p10≈0.63 ⇒ ×1.06=0.67 就盖住整条雾带）。
#     手机端 v1.35 起分母 = **本图模板亮度中位**（治"换图就废"）⇒ 雾带按**格子美术亮度**
#     摊开（真机草原帧实测 0.685~0.761，宽达 p10 的 **1.26 倍**）⇒ PC 的 ×1.06 远盖不住。
#     实测（`_tmpman/probe_v160_reveal.py`，6 张真机帧逐格回代；草原两帧有人工标注真值）：
#
#       | 口径 | 草原帧A(35格,真值3格) | 草原帧B(35格,真值3格) |
#       |---|---|---|
#       | 地板 0.66（PC 逐字） | **FP 28 格**（雾格 0.685~0.735 全被判已揭示）✗✗ | **FP 23 格** ✗✗ |
#       | 地板 0.80（本行默认） | FP 0 / FN 0 ✓ | FP 0 / FN 0 ✓ |
#
#     ⇒ 0.66 在手机端**不是保守/宽松之别，是直接坏掉**（28/35 格雾格被当已揭示 ⇒
#       下游 `_infer_chain_consumed` 会把整盘雾格反推成"已消耗"⇒ 模型空掉 ✗✗）
#     ⇒ 默认取 **0.80**（= v1.36 两帧真机标定的干净带中段，见下）——
#       **相对部分（p10×1.06）照样生效**：偏亮帧的 p10 高 ⇒ 阈值被抬起 ⇒ 不会整盘误判 ✓
#     ⚠ 想现场复现 PC 逐字口径做 A/B：`MAPBOT_REVEAL_FLOOR=0.66`（**只用于对拍取证**，
#        别拿去跑真机 ✗ —— 上表就是它的实测后果）
#
#   ## 手机端真机帧回代（同一探针，逐格）
#     · 广袤草原 A/B：p10=0.606/0.663 ⇒ 相对部分算出 0.642/0.702 ⇒ **都低于地板**
#       ⇒ 判定 = 地板 0.80 ⇒ 与 v1.36 行为一致，**零回归** ✓
#     · realme RMX3800（偏暗机型，雾格 0.361~0.472）：p10=0.386 ⇒ 相对部分 0.409
#       ⇒ 地板 0.80 仍然兜住（不然会整盘判已揭示 ✗）✓
#     ⇒ **相对部分的价值**：当整盘偏亮（雾格自己就到 0.85+）时，绝对阈值会整盘误判；
#       相对法跟着本帧抬高 ⇒ 这才是 PC 那条修法的本意 ✓
REVEAL_REL_Q = float(os.environ.get('MAPBOT_REVEAL_REL_Q', '0.10') or 0.10)     # 照抄 PC：10 分位
REVEAL_REL_K = float(os.environ.get('MAPBOT_REVEAL_REL_K', '1.06') or 1.06)     # 照抄 PC：×1.06
# ⚠ 唯一的分叉：地板。PC = 0.66；手机端 = 0.80（实测见上表，可用 MAPBOT_REVEAL_FLOOR 覆盖）
REVEAL_REL_FLOOR = float(os.environ.get('MAPBOT_REVEAL_FLOOR', '0.80') or 0.80)

# ⭐⭐ v1.36【「已揭示」阈值 + 双证据兜底】—— 0.75 踩线，0.80 才站得稳
#   ⚠ **v1.60 起它的角色变了**：不再是"逐格主判据"，而是
#     ① **两趟相对法的地板**（`REVEAL_REL_FLOOR` 的默认值就是它这个 0.80）；
#     ② **两趟法抛异常时的兜底**（`REVEAL_RATIO_MIN`，正常路径走不到 ✓）
#   下面这段标定结论（干净带 0.78~0.85 ⇒ 取 0.80）**原样有效**，是上面那个 0.80 的依据 ✓
#   ## 为什么不能再用 0.75（2026-10-02 两帧真机实测，Redmi/1280×2772，广袤草原）
#   同一台机、同一张图、同一套代码，两帧的分布**不一样**：
#     帧A（12:45 诊断帧）：雾格 ratio 上界 **0.762** ← 越过 0.75 ⇒ 1 格误判成已揭示
#     帧B（13:2x 现抓）  ：雾格 ratio 上界 **0.722** ← 安全
#   汇总 70 格：**已揭示格最低 0.855**、**雾格最高 0.761** ⇒ 两类**不重叠**，
#   中间有 **0.094 的干净带**；而 **0.75 落在雾格那一侧**（离 0.761 只差 0.011）
#   ⇒ 阈值卡在雾格分布的漂移区间上，**每帧都可能踩线** ✗✗
#   干净区间实测 = **0.78 ~ 0.85**（取中段 0.80，余量两边都有 ✓）
#   ⚠ **只有 2 帧样本**（真机每张图要扣 25 体力，抓帧机会少）⇒
#     0.80 是"当前证据下的最优"，**不是"已充分验证"** ⇒ 留开关可现场回滚 ✓
#
#   ## 双证据兜底（`REVEAL_EVIDENCE=dual`）
#   亮度是**连续量**、雾格与已揭示格之间没有硬间隔 ⇒ 单靠它永远会被某些帧的
#   边缘格咬住。第二条独立证据 = **雾格剪影**（`FOG_SIL_MIN=0.04`，4 倍空档）：
#     · 剪影 **≥ 0.04** = 雾下**有东西** ⇒ 那必然**还没揭示**（东西还盖在雾里）
#     · 剪影 **< 0.04** = 雾下**平坦空地** ⇒ 空地本来就没东西，不该被雾"压住"
#   实测能兜住帧A 那个唯一误判格（`2,3` ratio=0.761 剪影=0.0643 ≥0.04 ⇒ 判未揭示 ✓）
#   ⚠ 剪影**不能单独**判已揭示：已揭示格剪影 0.0138~0.1868 与雾格**重叠**
#     （盖图标的宝箱剪影 0.18 比不少雾格还高）⇒ 只作"否决"用，不作"通过"用 ✓
#   ⇒ 规则：`已揭示 = (ratio ≥ 0.80) 或 (ratio ≥ DUAL_LO 且 剪影 < FOG_SIL_MIN)`
#   ⚠ 默认仍走**纯亮度**（`single`）：两帧样本不足以证明双证据在所有盘型都更稳，
#     先积累真机反馈再切（`MAPBOT_REVEAL_EVIDENCE=dual` 现场可开）✓
#   ⚠⚠ v1.60：上面这条规则里的 `ratio ≥ 0.80` 已**换成本帧相对法**（见文件顶部 v1.60 段），
#     `REVEAL_RATIO_MIN` 从此只当**两趟法抛异常时的兜底**（正常路径走不到它 ✓）——
#     值**仍是 0.80**（v1.36 真机标定），门禁仍守着它，别当成主判据又改回去 ✗
REVEAL_RATIO_MIN = float(os.environ.get('MAPBOT_REVEAL_RATIO_MIN', '0.80') or 0.80)
REVEAL_EVIDENCE = (os.environ.get('MAPBOT_REVEAL_EVIDENCE', 'single') or 'single').strip().lower()
# 双证据里的"低置信亮度带"：在这个区间里改用剪影裁决（实测干净带下沿 0.78）
DUAL_BAND_LO = float(os.environ.get('MAPBOT_DUAL_BAND_LO', '0.74') or 0.74)

# ⭐⭐ 2026-09-27：多格地块的**真实占格必须由 alpha 推导**（不能按 (dw+2)/32 的矩形外框 ✗）
#   实测 S00003_111：画布 62x62（2×2 外框）但 alpha 只覆盖 **3 格 L 形**（右上整片透明）。
#   旧代码把缺的那格也算进模板 ⇒ 而那格实际住着**邻居**（图1 (2,5) 是 103 游乐设施）
#   ⇒ 模板里混进了别人的美术 ⇒ NCC 被稀释到 0.554，被 0.80 门槛砍掉
#     ⇒ 这就是用户报的「战斗地块没识别出来是哪个」（0.554 → 掩膜后 **0.942** ✓）
#   旁证：真盘 dump 里 S00003_111 的 blockSize = **3**（而 201/202/203 是 4）✓
#   旁证2：图1 (2,4) 的大块 bbox 278x278 却只占 3 格 —— L 形的包围盒本来就是 2×2 ✓
_CELL_COV_MIN = 0.10     # alpha 在某 32px 设计格内覆盖率 > 该值 ⇒ 算它占该格 ✓
_MASK_FILL_MAX = 0.97    # alpha 整幅填充率 < 该值 ⇒ 非矩形覆盖 ⇒ 匹配时走掩膜 ✓
SAT_MAX = 40.0           # ⭐ 区域里「高饱和」像素 = clover/boss/redEquip **图标** ⇒ 匹配前剔除
                         #   （雾是灰的、美术也被灰化；图标是鲜绿/鲜红 ⇒ 饱和度天然可分 ✓
                         #     实测图2 (3,6) 被 clover 压住：0.768 → 剔除后 **0.819** ✓）

# ⭐⭐ 2026-09-28：**模板帧采样**（修「棋盘识别 46~68 秒/帧」，用户报「识别为什么这么慢」）
#   模板库 33 sid × **640 张动画帧**全量入库 ⇒ 每帧识别 = 640 模板 × 全盘所有合法摆放位置 NCC；
#   1 格组走矩阵乘（快），**多格非矩形贴图走掩膜 NCC 纯 python 循环**（423×423 大图、
#   每次 2~5ms、几千次调用）⇒ 46~68s 的大头。
#   动画帧间只有水波/装饰微动 ⇒ **每 sid 取前 3 帧** ⇒ 模板 640→~99（-85%）⇒ 识别 ~8-12s。
#   ⚠ MAPBOT_TPL_FRAMES=0 恢复全量（旧口径，若分类分数异常用它回退排查 ✓）
_TPL_FRAMES = max(0, int(os.environ.get('MAPBOT_TPL_FRAMES', '3') or '0'))


def _foot_from_alpha(alpha, dw, dh):
    """贴图 alpha → **真实占格**偏移 [(dr, dc), ...]（按 32px 设计格切）

    画布恒为 `n*32 - 2`（多格贴图外圈各留 1px）⇒ 设计格边界正好在 x=32*j ✓
    """
    ncy = max(1, int(round(dh / DESIGN_PITCH)))
    ncx = max(1, int(round(dw / DESIGN_PITCH)))
    H, W = alpha.shape[:2]
    out = []
    for i in range(ncy):
        for j in range(ncx):
            y0 = int(round(i * DESIGN_PITCH))
            y1 = min(int(round((i + 1) * DESIGN_PITCH)), H)
            x0 = int(round(j * DESIGN_PITCH))
            x1 = min(int(round((j + 1) * DESIGN_PITCH)), W)
            if y1 <= y0 or x1 <= x0:
                continue
            if float((alpha[y0:y1, x0:x1] > 127.5).mean()) > _CELL_COV_MIN:
                out.append((i, j))
    return tuple(out) or ((0, 0),)

# 需要「买完」的特殊地块（用户 2026-09-24 指定；主循环只用前两个）
BUY_OUT_NAMES = ('旅行商人', '黄金宝库')


def imread(path, flags=cv2.IMREAD_UNCHANGED):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)


def map_table():
    """Area_Spot -> {图名: S码}（同一图名的多行取一致前缀）"""
    d = json.load(open(DT, encoding='utf-8'))
    out = {}
    for r in d['Area_Spot'].values():
        ids = r.get('IDs') or ''
        name = (r.get('AreaName') or '').strip()
        if not ids.startswith('S') or not name:
            continue
        out.setdefault(name, ids.split('_')[0])
    return out




# ⭐ 名字覆盖（用户实测指正 ✓ 优先于数据表 ✓）
#   S00003_102：官方表写的是"海边杂物"，但用户屏幕上显示「海边游客」✓ 以用户为准 ✓
#   （只影响显示/日志 ✓ 不影响分类与费用 ✓）
NAME_FIX = {
    'S00003_102': '海边游客',
}


def _cached(fn):
    """⭐ 2026-09-28：数据表缓存 —— spot_rows()/map_table() 每次 json.load 全表
    （3.95MB，实测 0.05 秒/次）；explore_loop 每轮 cells_of/state/eff_order 多处调用
    ⇒ 累计可省。表是静态的 ⇒ 模块级缓存安全 ✓（显式 _cached_clear() 可清）"""
    _box = {}

    def wrapper():
        if 'v' not in _box:
            _box['v'] = fn()
        return _box['v']

    wrapper.clear_cache = _box.clear
    return wrapper


@_cached
def spot_rows():
    """{IDs: Area_Spot 行}"""
    with open(DT, encoding='utf-8') as f:    # ⚠ v1.20 显式关闭
        d = json.load(f)
    out = {r['IDs']: r for r in d['Area_Spot'].values()}
    for _k, _v in NAME_FIX.items():      # 套用名字覆盖 ✓
        if _k in out:
            out[_k] = dict(out[_k], Name=_v)
    return out


@_cached
def map_table():
    """Area_Spot -> {图名: S码}（同一图名的多行取一致前缀）"""
    with open(DT, encoding='utf-8') as f:    # ⚠ v1.20 显式关闭（端上靠 GC 回收会刷 ResourceWarning 噪音）
        d = json.load(f)
    out = {}
    for r in d['Area_Spot'].values():
        ids = r.get('IDs') or ''
        name = (r.get('AreaName') or '').strip()
        if not ids.startswith('S') or not name:
            continue
        out.setdefault(name, ids.split('_')[0])
    return out


FOG_SIL_MIN = 0.04        # 雾下"有东西"的剪影占比阈值（真机实测：有物体 0.064~0.292 / 平坦 0.014~0.016）


def fog_silhouette(img, r, c, board):
    """雾格剪影占比（0~1）—— 「雾底下有没有东西」的**尺度无关**判据

    做法：取该格图像 → 只留中间 80%（躲开外框/圆角）→ 雾底 = 中位亮度 →
    剪影掩码 = 明显暗于雾底（`median − max(12, 2.2·MAD)`，MAD 是稳健方差，抗纹理噪声）→
    开运算去毛刺 → 最大连通块/总面积（占比）。

    实测（1280×2772 真机帧，铁血高地，见 `_tmpman/fog_silhouette.py`）：
      有物体：0.292 岩石图腾 / 0.271 巨大木桩 / 0.169 宝箱(2,2) / 0.064 岩石 …
      平  坦：0.014~0.016（雾格里的空地）
    ⇒ 阈值 0.04：**判"非空地"** ⇒ 连锁到此为止（不再靠"雾格一律挡"的一刀切 ✓）
    """
    import cv2
    import numpy as np
    G = board.grid if board is not None else GRID
    cx = int(G['x0'] + (c - 1) * (G.get('cx') or G.get('pitch') or 144)
             + (G.get('cx') or G.get('pitch') or 144) / 2)
    cy = int(G['y0'] + (r - 1) * (G.get('cy') or G.get('pitch') or 144)
             + (G.get('cy') or G.get('pitch') or 144) / 2)
    half = int((G.get('cx') or 144) / 2)
    sub = img[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
    if sub.size == 0:
        return 0.0
    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = int(g.shape[0] * 0.10)
    if g.shape[0] > 3 * m and g.shape[1] > 3 * m:
        g = g[m:g.shape[0] - m, m:g.shape[1] - m]
    med = float(np.median(g))
    mad = float(np.median(np.abs(g - med))) or 1.0
    mask = ((med - g) > max(12.0, 2.2 * mad)).astype('uint8')
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    return float(mask.mean())


def code_of(mapname):
    mt = map_table()
    if mapname in mt:
        return mt[mapname]
    for k, v in mt.items():
        if mapname and (mapname in k or k in mapname):
            return v
    return None


class Board:
    """一格分类器：把候选地块贴图预转成矩阵，逐格算 NCC"""

    def __init__(self, code, scale=SCALE, inner=INNER, maxframes=0, grid=None):
        self.code = code
        self.scale = scale
        self.inner = inner
        # ⭐ 分辨率自适应：几何可外部注入（不传则用全局 GRID ⇒ 行为与旧版完全一致 ✓）
        self.grid = dict(GRID)
        if grid:
            self.grid.update({k: v for k, v in grid.items() if v is not None})
        # 残缺几何补齐（缺 rows/cols/pitch 也不会崩 ✓）
        self.grid.setdefault('cols', GRID.get('cols', 7))
        self.grid.setdefault('rows', GRID.get('rows', 5))
        self.grid.setdefault('pitch', self.grid.get('cx') or GRID.get('pitch', 144.0))
        # ⭐ 格距优先取几何里的 cx/pitch（显式传入或全局 GRID 都算 ✓）
        #   参考分辨率下 GRID.cx = 144 = 4.5×32 ⇒ 与旧行为完全一致 ✓（零回归 ✓）
        _cx = self.grid.get('cx') or self.grid.get('pitch')
        if _cx:
            self.px = float(_cx)
        else:
            self.px = scale * DESIGN_PITCH      # 屏幕格距（144.0）
        self.k = int(round(inner / DESIGN_PITCH * self.px))
        self.entries = []                       # (sid, dw, dh, frame_idx, cw, ch)
        self.groups = {}                        # (dw,dh) -> {'idx','mat','plain_idx','mask_idx'}
        self.foot = {}                          # sid -> ((dr,dc),...) 真实占格（由 alpha 推 ✓）
        self.midx = {}                          # entry 下标 -> (pos, gt) 掩膜 NCC 用
        tmp = {}
        for d in sorted(glob.glob(os.path.join(UNIT, code, '*'))):
            sid = os.path.basename(d)
            files = sorted(glob.glob(os.path.join(d, '*.png')))
            # ⭐ 2026-09-28 帧采样（_TPL_FRAMES，默认每 sid 前 3 帧 ✓ 显式 maxframes 优先 ✓）
            _mf = maxframes or _TPL_FRAMES
            if _mf:
                files = files[:_mf]
            for fi, f in enumerate(files):
                im = imread(f)
                if im is None or im.ndim < 3 or im.shape[2] < 4:
                    continue
                dh, dw = im.shape[:2]
                # 模板美术尺寸 × (px/DESIGN_PITCH) ✓ 与 _region 同一公式 ✓
                #   （屏幕美术 135px 居中在 144 格距里 ⇒ 设计 30px × 4.5 = 135 ✓）
                w = int(round(dw / DESIGN_PITCH * self.px))
                h = int(round(dh / DESIGN_PITCH * self.px))
                if w < 8 or h < 8:
                    continue
                # ⭐ 真实占格（同 sid 的多帧取并集，防动画帧 alpha 有缺 ✓）
                if sid in self.foot:
                    _f = _foot_from_alpha(im[:, :, 3], dw, dh)
                    if len(_f) > len(self.foot[sid]):
                        self.foot[sid] = _f
                else:
                    self.foot[sid] = _foot_from_alpha(im[:, :, 3], dw, dh)
                # 2026-09-27：彩色方案实测代价过高（7.4s/次 + 540MB ✗）⇒ 已取消 ✓ 恢复灰度 ✓
                g = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
                g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA)
                # ⭐ 非矩形覆盖的多格贴图 ⇒ 记掩膜（只取 alpha 真正覆盖的像素做 NCC ✓）
                #   否则缺的那格会把邻居的美术算进来 ⇒ 分数被稀释（0.554 vs 0.942）
                sel = gt = None
                full = cv2.resize(im[:, :, 3], (w, h), interpolation=cv2.INTER_AREA) > 127.5
                if ((dw > DESIGN_PITCH * 1.5 or dh > DESIGN_PITCH * 1.5)
                        and float(full.mean()) < _MASK_FILL_MAX):
                    m = full.copy()
                    gc = g
                    if self.k:
                        m = m[self.k:-self.k, self.k:-self.k]
                        gc = g[self.k:-self.k, self.k:-self.k]
                    pos = np.flatnonzero(m.reshape(-1))
                    if pos.size > 200:
                        sel = pos.astype(np.int32)
                        # ⚠ 必须用**同样内缩过**的灰度取值（pos 是内缩坐标系 ✓）
                        gt = gc.reshape(-1)[pos].copy()
                if self.k:
                    g = g[self.k:-self.k, self.k:-self.k]
                v = g.reshape(-1)
                v = v - v.mean()
                sd = v.std()
                if sd < 1e-6:
                    continue
                key = (dw, dh)
                tmp.setdefault(key, []).append(((v / sd).astype(np.float32), sid, fi, sel, gt))
        for (dw, dh), lst in sorted(tmp.items()):
            idx = []
            mats = []
            for v, sid, fi, sel, gt in lst:
                idx.append(len(self.entries))
                self.entries.append((sid, dw, dh, fi,
                                     int(round((dw + 2) / DESIGN_PITCH)),
                                     int(round((dh + 2) / DESIGN_PITCH))))
                mats.append(v)
                if sel is not None and gt is not None:
                    self.midx[idx[-1]] = (sel, gt)
            ix = np.array(idx)
            ismask = np.array([int(i) in self.midx for i in ix], dtype=bool)
            self.groups[(dw, dh)] = {
                'idx': ix, 'mat': np.stack(mats),
                'plain_idx': ix[~ismask],                      # 矩形覆盖 ⇒ 走矩阵乘 ✓
                'mask_idx': [int(i) for i in ix[ismask]],      # 非矩形 ⇒ 走掩膜 NCC ✓
            }
        self.sids = [e[0] for e in self.entries]
        # ⭐ v1.45（施工单 ④）：`scores()` 写入、`objects()` 复用的**逐位置最优**缓存。
        #   只在"同一次 state() 调用"内有效（scores 每次开头都会重建）；留着旧值也不会被误用，
        #   因为 `objects()` 会核对"是不是同一张 img 对象" ✓
        self._pos_cache = None
        self._pos_cache_img = None

    def footprint(self, sid):
        """该地块的**真实占格**偏移 [(dr,dc)...]（alpha 推导；无则退回矩形占位 ✓）"""
        fp = self.foot.get(sid)
        if fp:
            return fp
        cw, ch = self._tpl_size(sid)
        return tuple((i, j) for i in range(ch) for j in range(cw))

    def cells_of(self, sid, anchor):
        """锚点 + 真实占格 ⇒ 该块实际覆盖的格子列表 ✓（成员格不再按矩形外框算 ✗）"""
        ar, ac = int(anchor[0]), int(anchor[1])
        return [(ar + dr, ac + dc) for dr, dc in self.footprint(sid)]

    def _mscore(self, ent, g, sat):
        """**掩膜 NCC**：只比贴图 alpha 真正覆盖到的像素，并剔除高饱和的图标像素 ✓

        ⭐ 2026-09-28：灰度/饱和度由 scores() 位置层算一次共享传入（同位置多个掩膜
        模板不再各 cvtColor 一遍 ✓ 数学完全等价 ✓）"""
        sel, gt = self.midx[ent]
        if self.k:
            g = g[self.k:-self.k, self.k:-self.k]
            sat = sat[self.k:-self.k, self.k:-self.k]
        gf = g.reshape(-1)
        if gf.size <= int(sel.max()):
            return 0.0
        ok = sat.reshape(-1)[sel] < SAT_MAX
        if int(ok.sum()) < 200:
            ok = np.ones_like(ok)               # 全被图标盖住 ⇒ 没法剔，退回不剔 ✓
        a = gt[ok]
        b = gf[sel][ok]
        a = a - a.mean()
        b = b - b.mean()
        d = float(np.linalg.norm(a) * np.linalg.norm(b))
        return float(a @ b / d) if d > 1e-9 else 0.0

    def _region(self, img, r, c, dw, dh):
        """贴图左上角落在第 (r,c) 格的左上角 + 4.5px 内缩（135 贴图居中在 144 格距里）"""
        px = self.px
        pad = (px - DESIGN_TILE * self.scale) / 2.0
        x0 = self.grid['x0'] + (c - 1) * px + pad
        y0 = self.grid['y0'] + (r - 1) * px + pad
        w = int(round(dw / DESIGN_PITCH * px))
        h = int(round(dh / DESIGN_PITCH * px))
        xi, yi = int(round(x0)), int(round(y0))
        if xi < 0 or yi < 0 or xi + w > img.shape[1] or yi + h > img.shape[0]:
            return None
        return img[yi:yi + h, xi:xi + w]

    def _vec(self, sub):
        # 与模板一致：灰度 ✓（彩色方案实测代价过高已取消 ✓）
        g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if g.ndim == 3:
            for _ch in range(g.shape[2]):
                _c = g[:, :, _ch]
                g[:, :, _ch] = (_c - _c.mean()) / (_c.std() + 1e-6)
        if self.k:
            g = g[self.k:-self.k, self.k:-self.k]
        v = g.reshape(-1)
        v = v - v.mean()
        sd = v.std()
        if sd < 1e-6:
            return None, 0.0
        return v / sd, float(sd)

    def scores(self, img, topn=3):
        """逐格分类（含多格贴图的所有摆放位置）-> {(r,c): [(score, sid, frame, off) ...]}

        ⭐ 2026-09-27 重写：候选**只投给该贴图真正覆盖的格**（`cells_of`）✗ 不再按矩形外框投。
           理由：111 的 L 形缺右上格，旧代码会把候选投到那格（实际住着邻居 103）。
           同时：非矩形覆盖的多格贴图改走**掩膜 NCC**（`_mscore`）✓

        ⭐⭐ v1.45 提速（施工单 ④）：顺手把**多格模板的逐位置最优**记进 `self._pos_cache`，
           供同一次 `state()` 里的 `objects()` **直接复用**（它原来把这些像素匹配**整个重算了一遍**）。
           ⚠ 语义完全不变：缓存值的算法与 `objects()` 里那段**逐字同序**
             （先 plain 的 argmax，再掩膜严格大于）⇒ 连"平分时留谁"都一样 ✓
        """
        best = {}
        rows, cols = self.grid['rows'], self.grid['cols']
        # ⭐ v1.45：本次调用的位置缓存（只给**多格模板**用；单格模板 objects() 不看）
        _pc = {}
        self._pos_cache = _pc
        self._pos_cache_img = img
        for (dw, dh), grp in self.groups.items():
            cw = int(round((dw + 2) / DESIGN_PITCH))
            ch = int(round((dh + 2) / DESIGN_PITCH))
            _multi_grp = (cw * ch > 1)
            plain, masks = grp.get('plain_idx'), grp.get('mask_idx') or []
            for rr in range(1, rows - ch + 2):
                for cc in range(1, cols - cw + 2):
                    sub = self._region(img, rr, cc, dw, dh)
                    if sub is None:
                        continue
                    got = []
                    _pbest = None                  # (score, sid) —— plain 的 argmax
                    _msc = []                      # [(score, sid)] —— 掩膜逐个
                    if plain is not None and plain.size:
                        v, _sd = self._vec(sub)
                        if v is not None and v.size == grp['mat'].shape[1]:
                            sc = grp['mat'] @ v / v.size
                            _ord = np.argsort(-sc)[:topn]
                            for oi in _ord:
                                e = self.entries[grp['idx'][oi]]
                                got.append((float(sc[oi]), e[0], e[3]))
                            _oi0 = int(_ord[0])     # argsort 首个 = argmax（与 np.argmax 同口径）
                            _e0 = self.entries[grp['idx'][_oi0]]
                            _pbest = (float(sc[_oi0]), _e0[0])
                    if masks:
                        # ⭐ 2026-09-28：灰度/饱和度**位置层算一次共享** —— 同一位置的
                        #   多个掩膜模板不再各 cvtColor 一遍（数值完全等价 ✓ 纯提速 ✓）
                        gsub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                        satf = (sub.max(axis=2).astype(np.float32)
                                - sub.min(axis=2).astype(np.float32))
                        for ent in masks:
                            e = self.entries[ent]
                            _ms = self._mscore(ent, gsub, satf)
                            got.append((_ms, e[0], e[3]))
                            _msc.append((_ms, e[0]))
                    if not got:
                        continue
                    if _multi_grp:
                        # ⭐ v1.45：**与 objects() 逐字同序**复算出"该位置最优"
                        _bs2, _bsid2 = (-9.0, None) if _pbest is None else _pbest
                        for _ms2, _sid2 in _msc:
                            if _ms2 > _bs2:
                                _bs2, _bsid2 = _ms2, _sid2
                        if _bsid2 is not None:
                            _pc[(dw, dh, rr, cc)] = (_bs2, _bsid2)
                    got.sort(reverse=True)
                    for s, sid, fi in got[:topn]:
                        for (r, c) in self.cells_of(sid, (rr, cc)):
                            if 1 <= r <= rows and 1 <= c <= cols:
                                best.setdefault((r, c), []).append((s, sid, fi, (rr, cc)))
        for k in best:
            best[k] = sorted(best[k], reverse=True)[:topn]
        return best

    def objects(self, sc, thr=0.75, img=None):
        """把逐格分类整合成「物件」：同 ID + 摆放一致的多格贴图合并成一个物件

        -> {(r,c): {'sid':.., 'score':.., 'cells':[(r,c)...], 'anchor':(r,c)}}
        """
        out = {}
        seen = set()
        # ⭐⭐ 2026-09-27 修（用户报「识别错格子」的核心 ✓）：
        #   原来只做"逐格最高分优先"的贪心 ✗ ⇒ 1 格模板会抢走多格地块的上半格
        #   （实测 m1_r007 格(2,4)：海螺 0.956 抢走 ⇒ 1×2 的椰树整块消失 ✗
        #     ⇒ 费用模型把 4 点的战斗格当成 2 点的海螺 ⇒ 求解器"走它不亏"✗）
        #   ⇒ 先算出**多格模板**的最佳摆放 ✓，若其"覆盖各格平均分"够高 ⇒ 让它们**优先占位** ✓
        _multi = []
        # ⭐⭐ v1.45 提速（施工单 ④）：`scores()` 刚把**同一张帧**的逐位置最优算过一遍
        #   （见那边的 `self._pos_cache`）⇒ 这里**直接取值**，不再把多格模板的像素匹配整个重算。
        #   ⚠ 等价性：缓存值的算法与下面那段**逐字同序**（先 plain argmax、再掩膜严格大于）⇒
        #     结果逐格一致；只有 `img` 与 `scores()` 当时那张**同一个对象**时才敢用（否则回退原算）。
        _pc = {}
        if img is not None and getattr(self, '_pos_cache_img', None) is img \
                and getattr(self, '_pos_cache', None):
            _pc = self._pos_cache
        for (dw, dh), grp in (getattr(self, 'groups', {}) if img is not None else {}).items():
            cw = int(round((dw + 2) / DESIGN_PITCH))
            ch = int(round((dh + 2) / DESIGN_PITCH))
            if cw * ch <= 1:
                continue                       # 只关心多格模板 ✓
            plain, masks = grp.get('plain_idx'), grp.get('mask_idx') or []
            rows_, cols_ = self.grid['rows'], self.grid['cols']
            for r in range(1, rows_ + 1):
                for c in range(1, cols_ + 1):
                    rr, cc = r - ch + 1, c - cw + 1
                    if not (1 <= rr <= rows_ - ch + 1 and 1 <= cc <= cols_ - cw + 1):
                        continue
                    if _pc:
                        # 这条路径上"有没有、是多少"都已在 scores() 里判过 ✓
                        _hit = _pc.get((dw, dh, rr, cc))
                        if _hit is None:
                            continue
                        _bs, _bsid = _hit
                        _multi.append((_bs, _bsid, (rr, cc), (cw, ch)))
                        continue
                    sub = self._region(img, rr, cc, dw, dh)
                    if sub is None:
                        continue
                    _bs, _bsid = -9.0, None
                    # ① 矩形覆盖的模板：一次矩阵乘 ✓
                    if plain is not None and plain.size:
                        v, _sd = self._vec(sub)
                        if v is not None and v.size == grp['mat'].shape[1]:
                            sc2 = grp['mat'] @ v / v.size
                            oi = int(np.argmax(sc2))
                            _bs, _bsid = float(sc2[oi]), self.entries[grp['idx'][oi]][0]
                    # ② 非矩形覆盖（alpha 有空洞）⇒ 掩膜 NCC，逐个比 ✓
                    if masks:
                        # ⭐ 2026-09-28 修（真机 [warn] 地块分类失败: _mscore() missing
                        #   'sat'）：§30 共享灰度改造漏了这处调用 ⇒ objects() 每摆位抛
                        #   TypeError ⇒ cells_of 整体失败 ⇒ 全盘 26 格全 gray（识别崩 ✗，
                        #   21:22 重启首轮暴露）。同 scores() 的位置层共享算法补上。
                        gsub = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                        satf = (sub.max(axis=2).astype(np.float32)
                                - sub.min(axis=2).astype(np.float32))
                        for ent in masks:
                            sm = self._mscore(ent, gsub, satf)
                            if sm > _bs:
                                _bs, _bsid = sm, self.entries[ent][0]
                    if _bsid is None:
                        continue
                    _multi.append((_bs, _bsid, (rr, cc), (cw, ch)))
        _multi.sort(reverse=True)
        for _sc2, _sid2, (_rr, _cc), (_cw, _ch) in _multi:
            _cells2 = self.cells_of(_sid2, (_rr, _cc))   # ⭐ 真实占格（L 形只 3 格 ✓）
            if any(x in seen for x in _cells2):
                continue
            # 该处单格最高分（用于比较 ✓）
            _best_single = 0.0
            for x in _cells2:
                _l = sc.get(x)
                if _l:
                    _best_single = max(_best_single, _l[0][0])
            # 多格模板若比"单格最高分"差不太多 ⇒ 认定它是本体 ✓（阈值 0.25 实测可分出 ✓）
            if _sc2 + 0.25 < _best_single:
                continue
            for x in _cells2:
                seen.add(x)
                out[x] = {'sid': _sid2, 'score': round(_sc2, 3),
                          'anchor': (_rr, _cc), 'cells': _cells2,
                          'size': (_cw, _ch)}
        for (r, c), lst in sorted(sc.items(), key=lambda kv: -kv[1][0][0]):
            if (r, c) in seen:
                continue
            v, sid, _fi, (ar, ac) = lst[0]
            if v < thr:
                continue
            cw, ch = self._tpl_size(sid)
            cells = self.cells_of(sid, (ar, ac))         # ⭐ 真实占格 ✓
            for cc in cells:
                seen.add(cc)
                out[cc] = {'sid': sid, 'score': round(v, 3), 'anchor': (ar, ac),
                           'cells': cells, 'size': (cw, ch)}
        return out

    def patch(self, img, r, c, dw=30, dh=30):
        return self._region(img, r, c, dw, dh)

    # ---------- 综合状态（分类 + 已揭示判定） ----------
    def state(self, img, thr=None, attr=True):
        # ⭐ 2026-09-27 门槛随分辨率自适应：0.80 是 1080p（px=144）标定的 ✓
        #   小分辨率下 NCC 天然偏低（720p 实测 0.13~0.17 ✗）⇒ 按格距比例缩放 ✓
        if thr is None:
            thr = 0.80 * (float(self.px) / 144.0)
            thr = max(0.12, min(0.80, thr))
        """逐格状态：分类 + 亮度比值（判断是否已揭示）

        实测（2026-09-25，find_buy.png）：
          * **整盘美术一开始就画出来了**，未揭示的格被 `AreaBlock.SetEnable(false)` 的
            `disableColor=(170,170,170)` 乘暗 ⇒ 亮度比 ≈ 0.65；已揭示 ≈ 1.00。
            （NCC 对亮度/对比度不变，所以**暗格也能认出是什么地块**）
          * 暗格点不动（`Button.enabled=false`），只有亮格能点。

        ⭐ 2026-09-26 修正：多格地块的**成员格归属**（`attr=True` 自动做）
        旧逻辑只看每格自己的 top1 ⇒ 一个 2×3 的紫/橙大块会出两个错：
          ① 分成 5~6 个独立目标（点哪一格弹的都是同一块的面板 ⇒ 重复弹面板/白点）
          ② 成员格里"裁剪里没有本体美术"的那格（实测 findA3 的 (1,7) 只有石板底纹）
             自己 top1 会变成空地 001（0.910 压过大块的 0.794）⇒ 整块丢一格，
             且被当 1 点体力的空地拿去开路（实际点它同样弹面板）
        ⇒ 先 `explore_blocks()` 从**任意成员格**的候选里还原大块的摆放位置，
          再把这个 footprint 里所有格的 sid/anchor/cells 改成同一个大块 ✓
          （`attr=False` 可退回旧行为，调试对拍时用 ✓）

        -> {(r,c): {'sid','name','score','ratio','revealed','anchor','cells','size',
                    'block_score','top':[...]}}
        """
        sc = self.scores(img, topn=STATE_TOPN)
        blocks = self.explore_blocks(sc) if attr else []
        objs = self.objects(sc, thr=thr, img=img)
        rows = spot_rows()
        owner = {}                      # 成员格 -> 所属大块（用于归属修正 ✓）
        for b in blocks:
            # ⚠ 绝不覆盖强匹配的商人/宝库（2026-09-25 卡死事故的教训 ✓）
            if any(_is_strong_buy(objs.get(k), rows) for k in b['cells']):
                continue
            for k in b['cells']:
                owner[k] = b
        out = {}
        for (r, c), lst in sc.items():
            k = (r, c)
            v, sid, _fi, _off = lst[0]
            blk = owner.get(k)
            o = objs.get(k)
            # ⭐ 2026-09-27 修 bug：`o` 这条分支原先只改了 anc/cells/size，**漏改 eff**
            #   ⇒ 物件 footprint 的成员格会带着"该格自己的 raw top1"的 sid 返回，
            #     与同一块内其它格自相矛盾。实测 夏季海滩 巨大沙堡(211) 的成员格：
            #       (3,5) sid=211 ✓  (4,5) sid=003 宝箱 ✗  (4,6) sid=014 限时礼包 ✗  (4,7) sid=211 ✓
            #     ⇒ 下游把 cells 摊平时凭空多出 宝箱/限时礼包 各一个（2/84 张图受影响）。
            #   与上方 owner 那条守卫保持一致：**绝不覆盖强匹配的商人/宝库** ✓
            if blk:
                anc, cells, size = blk['anchor'], blk['cells'], blk['size']
                eff = blk['sid']                  # 归属修正后的地块 ID
            elif o:
                anc, cells, size = o['anchor'], o['cells'], o['size']
                eff = sid if _is_strong_buy(o, rows) else o['sid']
            else:
                anc, cells, size = None, [k], (1, 1)
                eff = sid
            sub = self._region(img, r, c, 30, 30)
            ratio = 0.0
            if sub is not None:
                g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                if self.k:
                    g = g[self.k:-self.k, self.k:-self.k]
                # ⭐⭐ v1.35：分母用**本图模板亮度中位**（`MAPBOT_RATIO_DEN=map`）
                #   旧口径（逐格 `_tpl_luma(eff)`）配写死 0.75 ⇒ 两个量纲对不上 ✗
                #   ⇒ 沙滩 ratio 0.694 能跑，**草原 0.762 被误判成已揭示** ✗✗
                #   （真机实测：Redmi/1280×2772，雾格绝对亮度 139.5）
                #   ⚠ `MAPBOT_RATIO_DEN=cell` = 退回旧口径（留作离线对拍/回滚开关 ✓）
                _den = (self._map_luma_ref() if RATIO_DEN == 'map'
                        else self._tpl_luma(eff))
                ratio = float(g.mean()) / max(1e-6, _den)
            # ⭐⭐ v1.36【双证据】：先把剪影算出来，供 `revealed` 与连锁判据**共用一份**
            #   （原来剪影在下面单独算一遍；这里上移是为了让 `revealed` 能用双证据裁决 ✓）
            _sil = None
            if ratio and ratio < 0.78:
                try:
                    _sil = fog_silhouette(img, r, c, self)
                except Exception:       # noqa: BLE001
                    _sil = None
            # ⭐⭐⭐ v1.36/v1.60「已揭示」判定的**来历**（v1.60 起这段的"绝对 0.80"已换成相对法）：
            #   2026-09-27 定的 0.75 是按"雾≈0.65 / 已揭示≈1.0"的空档拍的；
            #   2026-10-02 两帧真机实测（Redmi/1280×2772 广袤草原，70 格）：
            #     已揭示最低 **0.855**、雾格最高 **0.761** ⇒ 不重叠，干净带 **0.78~0.85**
            #     而 **0.75 离雾格上界只差 0.011** ⇒ 雾格分布一漂就踩线 ⇒ 实测有 1 格被咬 ✗
            #   ⇒ 当时移到干净带中段 0.80 —— ⚠ **v1.60 起它不是主判据了**（见下）：
            #     绝对阈值治不了"**部分揭开的盘 / 整盘偏亮偏暗的机型**"（PC 原文那个病）
            #     ⇒ 改**本帧相对法** ✓
            # ⭐⭐⭐ v1.60【揭示判定 = **两趟相对法**】—— **照抄 PC** `mapbot_pc/spots.py:722-736`
            #   判据：`revealed ⟺ ratio ≥ max(REVEAL_REL_FLOOR, 第10分位 × REVEAL_REL_K)`
            #   ⚠ 这里**只是占位**（`revealed=False`）：真实判定在下面**第二趟**里统一做
            #     （逐格算时拿不到全盘分布 ⇒ PC 原文「**必须两趟**」✓）
            #   ⚠ `rev_evidence`：'rel'（相对法）/'fallback'（异常兜底）/'dual'（剪影双证据）
            out[k] = {'sid': eff, 'name': (rows.get(eff) or {}).get('Name'),
                      'score': round(float(v), 3), 'ratio': round(ratio, 3),
                      'revealed': False, 'rev_evidence': None,
                      'anchor': anc, 'cells': cells, 'size': size,
                      'block_score': (round(blk['score'], 3) if blk else None),
                      'top': [(round(float(s), 3), s2, anch)
                              for s, s2, _f, anch in lst]}
            # ⭐⭐⭐ 2026-10-01 v1.03【雾格剪影识别】——用户口径「优化识别模型，认出雾格里那块不能穿过」：
            #   雾格（ratio≈0.65）**底下的真身只能靠剪影认**：分类器隔着雾猜名字，真机实测会把
            #   挡连锁的物体猜成「草地」（score 还 0.95 ✗）⇒ 规划以为连锁能穿过它 ✗✗
            #   而"雾底 + 暗剪影"是**看得见**的：真机同帧实测（1280×2772 设备帧，铁血高地）
            #     · 有物体的雾格 剪影占比 **0.064 ~ 0.292**（(2,2) 宝箱=0.169、(3,1) 石碑=0.292…）
            #     · 平坦雾格   剪影占比 **0.014 ~ 0.016**
            #   ⇒ 中间有 4 倍空档，阈值 0.04 判「雾下有没有东西」稳 ✓（判**非空地** ⇒ 连锁到此为止）
            if _sil is not None:
                sil = _sil
                out[k]['fog_sil'] = sil
                out[k]['fog_object'] = bool(sil >= FOG_SIL_MIN)
                # ⭐ v1.05：**平坦**（剪影很小）= 雾下是空地 ⇒ 交给模型当 plain 用
                #   （雾格上的模板名字很不可信：真机这盘中位分只有 0.276，平坦格还被
                #    猜成「岩石/巨大木桩」✗ ⇒ 雾格的"是不是空地"以**剪影实测**为准 ✓）
                out[k]['fog_flat'] = bool(sil < FOG_SIL_MIN)
        # ── ⭐⭐⭐ v1.60「已揭示」= **两趟相对法**（照抄 PC `mapbot_pc/spots.py:722-736`）──
        #   第二趟：先收齐全盘 ratio ⇒ 用**本帧自己的雾格基准**判每一格
        #     `_base` = 本帧 ratio 的 **10 分位**（照抄 PC；雾格恒在基准附近）
        #     `_thr`  = `max(REVEAL_REL_FLOOR, _base × REVEAL_REL_K)`
        #   ⚠⚠ **手机端地板是 0.80，不是 PC 的 0.66**（实测依据见文件顶部 v1.60 段：
        #     0.66 在真机草原帧上会把 **28/35 格雾格**判成已揭示 ✗✗）
        #   ⚠ PC 在第一个 `if` 里还带 `isinstance(k, tuple)` 过滤（`out` 混进非格键时清掉）——
        #     手机端 `state()` 的键**恒为 (r,c)**（`scores()` 只投格键）⇒ 那条清理分支
        #     在这里是死代码，**不抄**（抄了反而多一个假分支）✓
        try:
            _rs = sorted(float(v.get('ratio') or 0.0) for v in out.values())
            if _rs:
                _base = _rs[max(0, int(len(_rs) * REVEAL_REL_Q) - 1)]
                _thr = max(REVEAL_REL_FLOOR, _base * REVEAL_REL_K)
                for _v2 in out.values():
                    _v2['revealed'] = float(_v2.get('ratio') or 0) >= _thr
                    _v2['rev_evidence'] = 'rel'
            else:
                # 空帧（一格都没认出来）：保持 False ⇒ 不能凭空说"已揭示" ✓
                for _v2 in out.values():
                    _v2['rev_evidence'] = 'rel'
        except Exception:                                   # noqa: BLE001
            # 兜底（PC 原文：`_v['revealed'] = ratio >= 0.75`）——
            #   手机端用 `REVEAL_RATIO_MIN`（0.80，v1.36 真机标定）当兜底，理由见顶部注释 ✓
            for _v2 in out.values():
                _v2['revealed'] = (float(_v2.get('ratio') or 0)
                                   >= REVEAL_RATIO_MIN)
                _v2['rev_evidence'] = 'fallback'
        # ⭐⭐ v1.36 的**双证据**（`MAPBOT_REVEAL_EVIDENCE=dual`，默认 `single` 不开）：
        #   只对"相对法判未揭示、但亮度落在低置信带"的格**改用剪影裁决** ——
        #   剪影小 = 雾下平坦空地 ⇒ 空地本来没东西，不该被雾压住 ⇒ 算已揭示 ✓
        #   剪影大 = 雾下有东西 ⇒ 必然还没揭示（东西还盖在雾里）✓
        #   ⚠ 剪影只作**否决/补救**，不能单独判已揭示（已揭示格剪影与雾格重叠，见顶部）✓
        if REVEAL_EVIDENCE == 'dual':
            for _v2 in out.values():
                _rn = float(_v2.get('ratio') or 0)
                _sn = _v2.get('fog_sil')
                if (not _v2.get('revealed')) and _sn is not None \
                        and _rn >= DUAL_BAND_LO:
                    _v2['revealed'] = bool(_sn < FOG_SIL_MIN)
                    _v2['rev_evidence'] = 'dual'
        return out

    # ---------- 紫/橙探索大块（2026-09-26 新） ----------
    def _tpl_size(self, sid):
        """该地块贴图占几格 -> (cols, rows)（缓存 ✓）"""
        sz = getattr(self, '_szmap', None)
        if sz is None:
            sz = self._szmap = {}
        if sid not in sz:
            cw = ch = 1
            for e in self.entries:
                if e[0] == sid:
                    cw, ch = e[4], e[5]
                    break
            sz[sid] = (cw, ch)
        return sz[sid]

    def explore_blocks(self, sc, min_score=None, suffix=None):
        """从逐格候选里还原「紫/橙探索大块」⇒ **一个大块只出一条记录** ✓

        为什么要这一层（见 `state()` 的 ① ② 两条）：
          一个大块的美术只覆盖部分成员格，逐格看永远不可能一致；只有回到
          **贴图的摆放位置（anchor + size）** 才能把整块一次性捞出来。

        算法：
          ① 扫所有格的所有候选，取 sid 后缀 ∈ 紫/橙 且 score ≥ min_score 的
          ② 用 (sid, anchor) 聚合成"摆放位置"，分数取成员里的最大值，
             并记 votes = 有多少个不同的格投了它（票数越多越可信 ✓）
          ③ 按分数降序贪心：**与已占用格重叠的摆放丢弃** ⇒ 天然去重 ✓

        -> [{'sid','anchor','cells','size','score','votes'}]（分数降序）
        """
        suf = tuple(suffix if suffix is not None else EXPLORE_SUFFIX)
        if min_score is None:                 # 常量在类之后定义 ⇒ 不能写在默认参数里 ✗
            min_score = EXPLORE_BLOCK_MIN
        rows_n, cols_n = int(self.grid['rows']), int(self.grid['cols'])
        place = {}
        for k, lst in sc.items():
            for s, sid, _fi, anch in lst:
                if not isinstance(sid, str) or sid.split('_')[-1] not in suf:
                    continue
                if s < min_score:
                    continue
                try:
                    ar, ac = int(anch[0]), int(anch[1])
                except (TypeError, ValueError, IndexError):
                    continue
                cw, ch = self._tpl_size(sid)
                if ar < 1 or ac < 1 or ar + ch - 1 > rows_n or ac + cw - 1 > cols_n:
                    continue                      # 摆放超出棋盘 ⇒ 不合法 ✗
                rec = place.get((sid, (ar, ac)))
                if rec is None:
                    place[(sid, (ar, ac))] = {'score': float(s), 'votes': {k}}
                else:
                    rec['score'] = max(rec['score'], float(s))
                    rec['votes'].add(k)
        out = []
        used = set()
        for (sid, anc), rec in sorted(place.items(),
                                      key=lambda kv: (-kv[1]['score'], kv[0])):
            cw, ch = self._tpl_size(sid)
            cells = self.cells_of(sid, anc)      # ⭐ 真实占格（非矩形外框 ✓）
            if any(cc in used for cc in cells):
                continue                          # 被更高分的大块占了 ⇒ 丢弃 ✓
            used.update(cells)
            out.append({'sid': sid, 'anchor': anc, 'cells': cells,
                        'size': (cw, ch), 'score': round(rec['score'], 3),
                        'votes': len(rec['votes'])})
        return out

    def _map_luma_ref(self):
        """⭐⭐ v1.35【本图模板亮度中位】—— `ratio` 的**统一分母**（治"换张图就废"）

        ## 为什么必须改（2026-10-02 真机实测，Redmi 25053RT47C / 1280×2772）
        旧口径：`ratio = 格子亮度 / _tpl_luma(该格所属地块)`，
        再拿**写死的 0.75** 判"已揭示 vs 雾格" ⇒ **两个量纲对不上** ✗
          · 模板亮度中位：夏日海滩 S00003 = **201**、广袤草原 S10002 = **183**（差 18 灰阶）
          · 真机同一帧的雾格绝对亮度 139.5：
              沙滩 ratio = 139.5/201 = **0.694** ⇒ <0.75 判雾格 ✓（能跑）
              草原 ratio = 139.5/183 = **0.762** ⇒ ≥0.75 **被误判成"已揭示"** ✗
        ⇒ 32 个雾格全被当成能点的格子，但每格都贴在地毯边缘 ⇒ 点不动
          ⇒ 反复点同一个 boss 撞 `fogged_noop` ⇒ `finish: no_progress` 退图 ✗✗

        ## 新口径
        分母换成**本图全部地块模板亮度的中位** `L_map`（一张图一个数，自动算 ✓）
        ⇒ 每张图的 `ratio` 分布形状一致，**同一道阈值 0.75 就能通吃所有图** ✓
        ⇒ 以后新增地图**不需要再标定阈值**（分母自动跟着变）✓

        ⚠ 保留 `_tpl_luma(sid)` 供**逐格相对比较**用（不动它，避免影响别的判据）✓
        ⚠ 缓存：每 Board 实例算一次（几十个模板，几十毫秒）✓
        """
        if getattr(self, '_map_luma', None):
            return self._map_luma
        vals = []
        try:
            base = os.path.join(UNIT, self.code)
            for sid in sorted(os.listdir(base)):
                d = os.path.join(base, sid)
                if not os.path.isdir(d):
                    continue
                fs = sorted(glob.glob(os.path.join(d, '*.png')))
                if not fs:
                    continue
                im = imread(fs[0], cv2.IMREAD_UNCHANGED)
                if im is None or im.ndim != 3:
                    continue
                gg = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
                ww = int(round(im.shape[1] / DESIGN_PITCH * self.px))
                hh = int(round(im.shape[0] / DESIGN_PITCH * self.px))
                gg = cv2.resize(gg, (ww, hh), interpolation=cv2.INTER_AREA)
                if self.k:
                    gg = gg[self.k:-self.k, self.k:-self.k]
                if gg.size:
                    vals.append(float(gg.mean()))
        except Exception:       # noqa: BLE001
            vals = []
        # ⚠ 兜底：模板读不出来时退回**逐格口径的中位**（旧行为，不会更差 ✓）
        if not vals:
            try:
                vals = [self._tpl_luma(s) for s in sorted(self._rows.keys())]
                vals = [v for v in vals if v and v > 1e-6]
            except Exception:       # noqa: BLE001
                vals = []
        self._map_luma = float(np.median(vals)) if vals else 1.0
        if self._map_luma <= 1e-6:
            self._map_luma = 1.0
        return self._map_luma

    def _tpl_luma(self, sid):
        """该地块首帧贴图的平均亮度（用来算亮度比；缓存）"""
        if not hasattr(self, '_luma'):
            self._luma = {}
        if sid not in self._luma:
            files = sorted(glob.glob(os.path.join(UNIT, self.code, sid, '*.png')))
            v = 1.0
            if files:
                im = imread(files[0], cv2.IMREAD_UNCHANGED)
                if im is not None and im.ndim == 3:
                    g = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
                    w = int(round(im.shape[1] / DESIGN_PITCH * self.px))
                    h = int(round(im.shape[0] / DESIGN_PITCH * self.px))
                    g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA)
                    if self.k:
                        g = g[self.k:-self.k, self.k:-self.k]
                    v = float(g.mean())
            self._luma[sid] = v
        return self._luma[sid]


def ascii_board(img, cell=30):
    """把棋盘画成文字图（我看不了图片，用这个"看"）。每格取中心 60x60 的均色。"""
    pal = [((255, 236, 179), 'a'),   # 沙地浅黄
           ((220, 200, 150), 'b'),
           ((150, 150, 150), '.'),
           ((110, 110, 110), ','),
           ((80, 80, 80), ':'),
           ((255, 255, 255), 'W'),
           ((230, 200, 60), 'Y'),
           ((200, 80, 60), 'R'),
           ((80, 140, 220), 'B'),
           ((90, 180, 90), 'G'),
           ((150, 90, 200), 'P')]

    def ch(bgr):
        b, g, r = [float(v) for v in bgr]
        best, bd = '?', 1e18
        for (pr, pg, pb), cc in pal:
            d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if d < bd:
                bd, best = d, cc
        return best

    # ⚠ 2026-10-01 修 NameError：本函数是**模块级**的（不是 Board 的方法），
    #   原来写 `self.grid[...]` ⇒ 一调用就 NameError（state_cmd 走这里 ⇒ 诊断命令必崩）
    # ⇒ 改用模块级 GRID（Board 构造时也是从它拷的同一份几何 ✓）。
    px = GRID['pitch']
    lines = []
    for r in range(1, GRID['rows'] + 1):
        rowtxt = []
        for c in range(1, GRID['cols'] + 1):
            x = int(GRID['x0'] + (c - 1) * px + px / 2)
            y = int(GRID['y0'] + (r - 1) * px + px / 2)
            patch = img[max(0, y - 30):y + 30, max(0, x - 30):x + 30]
            if patch.size == 0:
                rowtxt.append('   ?    ')
                continue
            h, w = patch.shape[:2]
            sub = []
            for yy in range(3):
                s = ''
                for xx in range(3):
                    p = patch[yy * h // 3:(yy + 1) * h // 3, xx * w // 3:(xx + 1) * w // 3]
                    s += ch([int(v.mean()) for v in cv2.split(p)])
                sub.append(s)
            rowtxt.append('/'.join(sub))
        lines.append(' '.join(rowtxt))
    return lines


def names_of(sids):
    rows = spot_rows()
    return {s: ((rows.get(s) or {}).get('Name') or '?') for s in sids}


_PLAIN_CACHE = {}


def is_plain_spot(sid):
    """该地块是不是「空地」（Area_Spot: SpecialSpot==0 且 SpotSize==1）——点它才能揭一片"""
    if sid not in _PLAIN_CACHE:
        row = spot_rows().get(sid) or {}
        try:
            _PLAIN_CACHE[sid] = (int(row.get('SpecialSpot') or 0) == 0 and
                                 int(row.get('SpotSize') or 1) == 1)
        except Exception:           # noqa: BLE001
            _PLAIN_CACHE[sid] = False
    return _PLAIN_CACHE[sid]


_FIGHT_CACHE = {}


def is_fight_spot(sid):
    """⭐⭐ v1.43【这一格是不是"要打一场架"的地块】—— 按**地块类型**判，不看临时标记

    ⭐⭐⭐ 为什么必须有它（学 PC 端 a7df4af 的真机事故，逻辑完全一致）：
      计划里第一步要打的那格（PC 端是 `S00003_111` 海边杂物，格数 3），
      它的「拦路」标记是**规划完之后才贴上去的**（循环发现"计划路径穿过非空地"才标）⇒
      **规划那一刻它没有标记** ⇒ 被当"内容格·探索"按 `size` 计价（实际应为 `size×2`）⇒
      ⇒ "打这一架(3)"和"绕路揭 4 格(1×4=4)"看起来差不多 ⇒ **平局时选了要打的那条** ✗✗
      ⇒ 必须按**地块类型**定价，而不是看规划期还不存在的标记 ✓

    判据来自数据表 `Area_Spot.EventNum`（本机 482 行实测）：
      · 草地 `1-1`、海螺 `1-1`、宝箱 `1-1`、岩石 `1-1`、勇者之墓 `1-1` ⇒ **不打** ✓
      · 海边杂物 `3-3`、游乐设施 `4-4`、巨大沙堡 `8-8`、海边小屋 `9-9` ⇒ **要打** ✓
      · 营地（空）/ 商人 / 宝箱怪 等 `0-0` 或空 ⇒ 不打 ✓
    ⇒ 规则：`EventNum` 非空且**首段数字 > 1** ⇒ 战斗型 ✓
    """
    sid = str(sid)
    if sid in _FIGHT_CACHE:
        return _FIGHT_CACHE[sid]
    try:
        row = (spot_rows() or {}).get(sid) or {}
        ev = str(row.get('EventNum') or '').strip()
        if not ev:
            _FIGHT_CACHE[sid] = False
        else:
            _FIGHT_CACHE[sid] = int(ev.split('-')[0]) > 1
    except Exception:           # noqa: BLE001
        _FIGHT_CACHE[sid] = False
    return _FIGHT_CACHE[sid]


def board_cmd(a):
    code = a.code or code_of(a.mapname)
    if not code:
        print('FAIL: 需要 --map 或 --code')
        return 1
    img = imread(a.img, cv2.IMREAD_COLOR) if a.img else None
    if img is None:
        print('FAIL: 读不到图', a.img)
        return 1
    b = Board(code)
    sc = b.scores(img)
    objs = b.objects(sc, thr=a.thr)
    nm = names_of(set(b.sids))
    print('=== 棋盘文字图（每格 3x3 主色，行1在第一条） ===')
    for i, ln in enumerate(ascii_board(img), 1):
        print('  r%d  %s' % (i, ln))
    print('=== 逐格分类（图 %s：%d 个地块 / %d 帧 / %d 种尺寸） ==='
          % (code, len(set(b.sids)), len(b.entries), len(b.groups)))
    for r in range(1, 6):
        for c in range(1, 8):
            lst = sc.get((r, c))
            if not lst:
                print('  (%d,%d)  --' % (r, c))
                continue
            top = lst[0]
            rest = ' '.join('%s:%.2f' % (s, v) for v, s, _f, _o in lst[1:])
            own = objs.get((r, c))
            tag = ''
            if own and own['anchor'] == (r, c):
                tag = '  ★物件%s %s' % (own['size'], own['cells'])
            elif own:
                tag = '  (属物件锚点%s)' % (own['anchor'],)
            print('  (%d,%d)  %-12s %-8s %.3f  摆放=%s  |%s%s'
                  % (r, c, top[1], nm.get(top[1], '?'), top[0], top[3], rest, tag))
    return 0


def target_cmd(a):
    code = a.code or code_of(a.mapname)
    if not code:
        print('FAIL: 需要 --map 或 --code')
        return 1
    img = imread(a.img, cv2.IMREAD_COLOR) if a.img else None
    if img is None:
        print('FAIL: 读不到图', a.img)
        return 1
    rows = spot_rows()
    want = {sid for sid, r in rows.items()
            if sid.startswith(code) and (r.get('Name') in BUY_OUT_NAMES)}
    b = Board(code)
    sc = b.scores(img)
    print('目标地块（%s）：%s  阈值 %.2f'
          % (code, {rows[s]['Name']: s for s in sorted(want)}, a.thr))
    hits = 0
    for (r, c), lst in sorted(sc.items(), key=lambda kv: -kv[1][0][0]):
        v, sid, _f, _off = lst[0]
        if sid in want and v >= a.thr:
            hits += 1
            print('  命中 格(%d,%d)  %s %s  score=%.3f' % (r, c, sid, rows[sid]['Name'], v))
    if not hits:
        print('  0 命中')
    return 0


def verify_cmd(a):
    """用 probe_spots.py 采到的「面板真值」回归分类器 -> 命中率 + 明细"""
    with open(a.probe, encoding='utf-8') as f:    # ⚠ v1.20 显式关闭
        d = json.load(f)
    code = a.code or d.get('code') or code_of(d.get('map'))
    rows = spot_rows()
    allnames = {r.get('Name') for r in rows.values()}
    b = Board(code)
    cache = {}
    ok = bad = skip = 0
    for rec in d['records']:
        if rec.get('kind') != 'content':
            continue
        truth = [t for t in (rec.get('truth') or []) if t in allnames]
        if not truth:
            skip += 1
            continue
        png = os.path.join(RUNS, rec['pre_png'])
        if not os.path.exists(png):
            continue
        if png not in cache:
            cache[png] = b.scores(imread(png, cv2.IMREAD_COLOR))
        lst = cache[png].get(tuple(rec['cell']))
        if not lst:
            continue
        v, sid, _f, _o = lst[0]
        got = rows.get(sid, {}).get('Name')
        good = got in truth
        ok += good
        bad += (not good)
        print('  %s 格%-8s 分类=%-12s(%-6s) %.3f  真值=%-8s  %s'
              % ('OK ' if good else 'xx ', rec['cell'], sid, got, v, '/'.join(truth),
                 rec['pre_png']))
    tot = ok + bad
    print('命中 %d/%d（跳过无真值 %d）' % (ok, tot, skip))
    return 0


def live_cmd(a):
    from mapbot import Bot
    b0 = Bot(log_prefix='spots')
    p = b0.snap('spots_live')
    print('截图', p)
    a.img = p
    return board_cmd(a) if a.board else target_cmd(a)


def calib_cmd(a):
    """重新标定几何：给定一张已知含 N 个相同地块的截图，扫 pitch/原点"""
    print('几何：设计格距 32px × 缩放 %.1f = 屏幕格距 %.1f；左上 (%.0f, %.0f)；单格贴图 %.0fx%.0f'
          % (SCALE, SCALE * DESIGN_PITCH, GRID['x0'], GRID['y0'],
             DESIGN_TILE * SCALE, DESIGN_TILE * SCALE))
    print('重现：python fit_art.py scale <截图> --probe S00003_001  # 找缩放')
    print('      python fit_art.py peaks <截图> --probe S00003_001  # 峰间距=格距')
    return 0


def state_cmd(a):
    """打印整盘状态（我看不了图，靠这个"看"）：每格 地块/分数/亮度比/可否点"""
    code = a.code or code_of(a.mapname)
    img = imread(a.img, cv2.IMREAD_COLOR) if a.img else None
    if img is None:
        print('FAIL: 读不到图', a.img)
        return 1
    b = Board(code)
    st = b.state(img, thr=a.thr)
    print('=== 状态（%s）: 名/分数/亮度比/亮暗 ===' % (a.img or 'live'))
    for r in range(1, 6):
        cells = []
        for c in range(1, 8):
            v = st.get((r, c))
            if not v:
                cells.append('%-22s' % '-')
                continue
            cells.append('%-8s%.2f %.2f%s' % ((v['name'] or '?')[:8], v['score'], v['ratio'],
                                              '亮' if v['revealed'] else '暗'))
        print('  r%d %s' % (r, ' | '.join(cells)))
    print('=== 标记 ===')
    for (r, c), v in sorted(st.items()):
        if v['anchor'] != (r, c):
            continue
        tag = []
        if v['name'] in BUY_OUT_NAMES:
            tag.append('★买完')
        if v['revealed']:
            tag.append('已揭示')
        print('  (%d,%d) %-12s %-8s %.3f 比%.2f %s'
              % (r, c, v['sid'], v['name'], v['score'], v['ratio'], ' '.join(tag)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')
    for name in ('board', 'target'):
        p = sub.add_parser(name)
        p.add_argument('img', nargs='?')
        p.add_argument('--map', dest='mapname')
        p.add_argument('--code')
        p.add_argument('--thr', type=float, default=0.80)
        p.add_argument('--board', action='store_true')
    p = sub.add_parser('live')
    p.add_argument('--map', dest='mapname')
    p.add_argument('--code')
    p.add_argument('--thr', type=float, default=0.80)
    p.add_argument('--board', action='store_true')
    p = sub.add_parser('verify')
    p.add_argument('--probe', default=os.path.join(RUNS, 'probe_spots.json'))
    p.add_argument('--code')
    p = sub.add_parser('state')
    p.add_argument('img', nargs='?')
    p.add_argument('--map', dest='mapname')
    p.add_argument('--code')
    p.add_argument('--thr', type=float, default=0.80)
    p = sub.add_parser('calib')
    p.add_argument('--write', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'board':
        return board_cmd(a)
    if a.cmd == 'target':
        return target_cmd(a)
    if a.cmd == 'state':
        return state_cmd(a)
    if a.cmd == 'live':
        return live_cmd(a)
    if a.cmd == 'verify':
        return verify_cmd(a)
    if a.cmd == 'calib':
        return calib_cmd(a)
    ap.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())


def aplus_event_names(map_code):
    """某张图里「A 级以上（紫/橙/红）的探索事件地块」的中文名集合

    判据（游戏 Area_Spot 表）：
        SpecialSpot == 1        # 探索事件类（会弹事件 ✓）
        MinBattleStep ∈ {A,S,SS}  # 档位 ≥ A ⇒ 紫以上 ✓
    例：夏日海滩(S00003) ⇒ {'木桶'(A), '贝壳'(S)} ✓
    """
    out = set()
    for sid, r in spot_rows().items():
        if not sid.startswith(map_code + '_'):
            continue
        if int(r.get('SpecialSpot') or 0) != 1:
            continue
        if (r.get('MinBattleStep') or '').upper() in ('A', 'S', 'SS'):
            nm = r.get('Name')
            if nm:
                out.add(nm)
    return out


def event_tile_names(map_code):
    """某张图里**所有会产出事件的地块**（EventNum 非空 ✓）的中文名集合

    这些地块点开会弹「探索 / 战斗」面板 ✓；面板里若显示紫/橙/红掉落 ⇒ 点探索 ✓
    （点开面板只是预览、不消耗 ✓ ⇒ 可以放心逐个探 ✓）
    """
    out = set()
    for sid, r in spot_rows().items():
        if not sid.startswith(map_code + '_'):
            continue
        ev = str(r.get('EventNum') or '').strip()
        if ev and ev not in ('0-0', '0'):
            nm = r.get('Name')
            if nm:
                out.add(nm)
    return out


PURPLE_SUFFIX = ('221', '321')      # 紫地块（小助手官方判定 ✓）
ORANGE_SUFFIX = ('331',)            # 橙地块
EXPLORE_SUFFIX = PURPLE_SUFFIX + ORANGE_SUFFIX   # 紫以上 ⇒ 能进探索格子 ✓

# ⭐ 2026-09-26：紫/橙大块归属修正的分数线
#   实测（findA3.png）真大块成员分数 0.794，而"看起来不清"的格子会瞎猜到 0.21/0.30
#   ⇒ 0.70 干净分开 ✓（探索循环里原本就是用的 0.70，保持一致）
EXPLORE_BLOCK_MIN = 0.70
STATE_TOPN = 5          # state() 保留每格前 N 个候选（大块归属要用后面的候选 ✓
                        #  矩阵乘那步本来就全算 ⇒ topn 只影响 argsort，代价可忽略 ✓）

# 商人/宝库的识别门槛（与 explore_loop.BUY_SCORE_MIN 一致 ✓ 这里兜底给 spots 内部用）
BUY_SCORE_MIN = 0.85


def _is_strong_buy(o, rows=None):
    """这个物件是不是**强匹配的商人/宝库**（永不覆盖 ⇒ 2026-09-25 卡死事故）"""
    if not o:
        return False
    if float(o.get('score') or 0) < BUY_SCORE_MIN:
        return False
    rows = rows if rows is not None else spot_rows()
    return (rows.get(o.get('sid')) or {}).get('Name') in BUY_OUT_NAMES


def purple_event_names(map_code):
    """⭐ 某张图里能填「探索格子」的地块名（**紫/橙**：ID 后缀 221/321/331 ✓）

    依据：幻少小助手 AreaBlockView 里的官方分类
        紫地块 = 后缀 221 / 321 ；橙地块 = 331
        （木桶 006 / 贝壳 007 属于「宝箱与装备」⇒ 进不了探索格子 ✗）
    夏日海滩 ⇒ 游乐设施(221) / 巨大沙堡(321) / 海边小屋(331) ✓
    """
    out = set()
    for sid, r in spot_rows().items():
        if not sid.startswith(map_code + '_'):
            continue
        if sid.split('_')[-1] in EXPLORE_SUFFIX:
            nm = r.get('Name')
            if nm:
                out.add(nm)
    return out


def _old_purple_event_names(map_code):
    """某张图里「**固定紫/橙探索**」的地块名集合

    判据（游戏 Area_Spot 表）：
        EventNum 非空（会产出事件 ✓）
        且 MinBattleStep ∈ {A, S}（档位 ≥ A ⇒ 探索事件固定紫/橙 ✓）
    夏日海滩 ⇒ {木桶, 限时礼包, 黄金宝库, 游乐设施, 巨大沙堡, 异界之门,
                贝壳, 传承祭坛, 预言石碑, 海边小屋} ✓
    """
    out = set()
    for sid, r in spot_rows().items():
        if not sid.startswith(map_code + '_'):
            continue
        ev = str(r.get('EventNum') or '').strip()
        if not ev or ev in ('0-0', '0'):
            continue
        if (r.get('MinBattleStep') or '').upper() in ('A', 'S', 'SS'):
            nm = r.get('Name')
            if nm:
                out.add(nm)
    return out
