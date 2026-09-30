# -*- coding: utf-8 -*-
"""buypanels.py · 「买完」流程：旅行商人 / 黄金宝库（坐标全部实机实测 2026-09-25）

## 旅行商人（`GoldGambleBlockPanel`）
面板标题「旅行商人」(688,601)，X 关闭 (983,602)。用户口径：**买 4 次**。
实机验证过的循环：购买(895,1255) → 返回(539,1212)，重复 4 次 → 关闭 X。
（效果：依次在四个档位购买，每次消耗的金币递增）

## 黄金宝库（`GoldenVaultBlockPanel`，源码 57315 起）
5x5 的 25 件宝物，分 3 圈：外圈 16 件(1 层) / 内圈 8 件(2 层) / 正中心 1 件(3 层)，
**每层只能拿一件**；要拿下一层必须先花金币解锁：
    10000 解锁第 1 层 → 选一件领 → 20000 解锁第 2 层 → 选一件领
    → 40000 解锁第 3 层 → 选中心那件领 → 「完成」结算      合计 70000 金币
图标坐标：x = 251 + 144*c，y = 746 + 144*r（5x5，实测 135x135 一格）
按钮（购买/选择/完成都是它）：(896,1444)；标题「黄金宝库」(692,383)，X (983,384)

用法:
    from buypanels import merchant_flow, vault_flow
    merchant_flow(bot, log)
    vault_flow(bot, log)

## ⭐⭐ 坐标口径（2026-09-30 v0.61 修正，真机事故）
本模块所有常数（标题/按钮/5×5 格子/X/返回/空白）都是**PC 实测值**，而 PC 上
「弹窗空间 == 参考系」（C=0）⇒ 这些常数其实是**居中弹窗系**坐标。
真机上弹窗**锚设备屏幕中心**，与棋盘的「顶块锚顶 + 其余锚底」不是同一坐标系：
    真机 1280×2772 ⇒ C = RefMapper.dialogShift() = 209.44
    「选择奖励/购买」按钮 (895,1444)： b.tap → dev 2208 ／ b.tap_dlg → dev 1960
    差 **248px**，而按钮才 ~110px 高 ⇒ 旧写法（全走 b.tap）**每一击都落在按钮外面**，
    真机症状就是「黄金宝库买完 0 个 / 点不掉」（旅行商人同理）。
⇒ 现在**统一走弹窗系**：`_items()` 把 OCR 条目经 `dlg_items()` 映射到弹窗系，
  所有点击走 `bot.tap_dlg()`，图标模板匹配用 `bot.img_dlg()`。
  PC 侧 `dlg_items()` 恒等、`tap_dlg()`/`img_dlg()` 退化为 `tap()`/`img()` ⇒ **行为一字不变** ✓

⚠ 归一化帧会**整段丢掉**弹窗系 y ∈ (202, 509)（toRef 丢弃的弹性区）⇒ 标题「黄金宝库」
  (383) 与 X (384) 在归一化帧**根本不存在**，别再用 `_has(it, 标题)` 判面板存在性
  （旧代码为此补了 `_has_dlg` 的整帧弹窗 OCR，每次 ≈2s）。现在用**右下角按钮文字**判
  （它落在弹窗系 1444 ⇒ 归一化帧 1235，band 内看得见），`_has_dlg` 只作兜底。
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

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:                                    # ⭐ v0.61：两端共用一套「弹窗系」API
    from mapbot import dlg_items, dlg_shift      # noqa: F401
except Exception:                       # noqa: BLE001  老版 mapbot 没有 ⇒ 退化为恒等
    def dlg_items(items):
        return items

    def dlg_shift():
        return 0.0

MERCHANT = {'title': '旅行商人', 'x': (983, 602), 'buy': (895, 1255),
            'back': (539, 1212), 'times': 4}


def say(*a, **k):
    """本模块的日志出口。

    ⚠⚠ 2026-10-01 v0.97 修**真机崩溃**：本文件里只有一处用到 `say`（第 736 行附近那条
      "读不到按钮 ⇒ 标定坐标保底"），但**从来没导入过它** ⇒ 走到那条分支就
      `NameError: name 'say' is not defined` ⇒ **整条宝库流程当场中断**
      （真机 22:50 实测：第 2 圈连点 4 次「购买」后崩，面板停在「恭喜获得 装备」+「返回」
        的界面上，只能靠 `ensure_closed` 收尾 ✗）
      ⇒ 现在自带兜底：拿得到 `explore_loop.say` 就用它（两端日志口径一致 ✓），
        拿不到就 `print`（端上照样进 logcat ✓）。**惰性取**，避免循环导入 ✓
    """
    try:
        _el = sys.modules.get('explore_loop')
        _f = getattr(_el, 'say', None) if _el is not None else None
        if _f is not None:
            return _f(*a, **k)
    except Exception:       # noqa: BLE001
        pass
    print(*a)


# ⭐ v0.97：真机「返回」按钮的**专用判据窗口**（与 `VAULT['back']` 那个"兜底落点"解耦）
#   实测两处：奖励展示时的「返回」在弹窗系 (538, 1212)（PC 值）/ (538, 1267)（真机帧 OCR）
#   ⇒ 取中 (539, 1240) 作中心，容差放宽
VAULT_BACK_ZONE = (539, 1240)

# ⭐⭐⭐ 2026-10-01 **真机帧实测重标定**（vault4_dlg.png，用户停在宝库面板抓帧，
#   我把每个常量画在帧上逐个核对 —— 三个都是错的 ✗）：
#     常量        旧值          真机实际（帧上所见）                    后果
#     blank      (540,1700)   那里是**面板外**（底部格子区）⇒ 落点压在宝箱/棋盘上 ✗
#     back       (539,1212)   落在**第 4 行格子上**（不是「返回」按钮）✗
#     buy        (895,1444)   真机按钮文字在 y=**1498**（旧值偏上 54px）✗
#     x          (983, 384)   ✓ 正确（右上角 X）
#   ⇒ 「点空白处关详情」在真机上等于**在棋盘上乱点**（用户报「点一下左上角格子、
#     关闭宝库界面」的元凶之一 ✗）
#   ⇒ 现在：blank 取**面板内、网格下方、说明文字右侧**的安全空白；buy 用实测 1498
VAULT = {'title': '黄金宝库', 'x': (983, 384),
         'buy': (895, 1498),          # ⭐ 真机实测（旧 1444 偏上 54px）
         # ⚠ `back`（最后兜底）——**绝不能落在奖励格上**（旧 1212 / 试过的 1034 都在格子里 ✗
         #   ⇒ 等于替用户点了那格奖励）。真机帧像素核对：奖励展示时的「返回」在面板中下部，
         #   而**安全空白区**实测是 y 1560~1620 / x 540~780（std≈13~0 ✓）
         #   ⇒ 兜底取与 `blank` 同区的 (660,1590)；正常路径始终走 `_back_btn()` 的文字匹配 ✓
         'back': (660, 1590),
         # ⭐ `blank`（收起奖励详情用）——**按像素纹理选的，不是目测**（真机帧 vault4_dlg.png）：
         #   在 y 1560~1620 那条带里逐列算纹理 std：
         #     x 540~780 → std **13.0**（最平坦 = 真空白 ✓）
         #     x 780~900 → std 43~67（= 金币按钮/图标，有内容 ✗）
         #   旧值 (540,1700) 在**面板外**（点到棋盘 ✗）、我试的 (760,1560)/(780,1600) 都贴到按钮 ✗
         #   ⇒ 取 **(660, 1590)**：网格下方、说明文字右侧、金币按钮左侧的真空白 ✓
         'blank': (660, 1590),
         'gx0': 251, 'gy0': 746, 'pitch': 144, 'cols': 5, 'rows': 5
         # 真机帧实测网格：x 251~827（pitch 144）、y 746~1322 ⇒ 外框 179~899 / 674~1394 ✓
         }
VAULT_RING = {1: (0, 0), 2: (1, 1), 3: (2, 2)}      # 每层代表格（0 基 行,列）


BAND = (300, 1560)      # 归一化帧里要 OCR 的 y 段 ⇒ 弹窗系 (300+C, 1560+C) ≈ (509, 1769)
                        # （再往上就是被 toRef 丢掉的弹性区，取不到；再往下是底部导航，取了反而误导）


def _items(bot):
    """面板 OCR 条目，**坐标已换算到居中弹窗系**（与下面所有常数同一口径）。

    ⚠ PC 版 `Bot.ocr()` 用的是**上一次截图**（缓存旧图），点完不重新截图会读到点击前的画面
      （2026-09-25 踩过：宝库面板已开却判成没开）⇒ PC 上必须先 `snap`。
      端侧 `Bot.ocr()` 走 `api.ocrJson` **自己抓当前帧**（`Bot.ocr_grabs = True`）⇒ 省掉那次
      snap（真机上一次 snap = toRef + PNG 编码 ≈ 0.3s，一个宝库面板要调它十几次）。
    """
    if not getattr(bot, 'ocr_grabs', False):
        bot.snap('bp')
    return dlg_items(bot.ocr(min_conf=0.35, band=BAND, tag='panel'))


def _has(items, *labels):
    for lb in labels:
        for it in items:
            if lb in it['text']:
                return it
    return None


def _has_dlg(bot, *labels):
    """兜底的存在性判断：走**弹窗帧** OCR（坐标即弹窗系）。

    ⚠⚠ 2026-09-30 更正：这里原本写着「标题在归一化帧落到 y≈175，只是跑到 band 外」
      —— **不对**。归一化帧（`toRef`）会把弹窗系 y ∈ (202, 509) 这一段**整段丢掉**
      （见 `RefMapper.toRef` 的"两段拼接"），标题 383 落在丢带里 ⇒ 归一化帧**根本没有它**。
      所以任何 `_has(it, 标题)` 的判据在真机上是恒 False 的（v0.32 那次只修分支不修闸门
      才无效，见 09-29 日报）。

    ⭐ v0.61 起，正常路径**不再需要它**：面板存在性改用右下角按钮文字判（`_present`），
      因为按钮在弹窗系 1444（归一化帧 1235）**落在 band 内、看得见**，而且是免费的
      （`_items` 那一帧里就有）。只有「连按钮文字都认不出来」时才补这一手（≈2s）。
    PC 版 Bot 没有 ocr_dlg ⇒ 返回 None（PC 恒 C=0，也不需要）。"""
    ocr_dlg = getattr(bot, 'ocr_dlg', None)
    if ocr_dlg is None:
        return None
    try:
        items = ocr_dlg(min_conf=0.4)
    except Exception:       # noqa: BLE001
        return None
    for lb in labels:
        for it in items:
            if lb in (it.get('text') or '').replace(' ', ''):
                return it
    return None


def _present(bot, it):
    """面板还在不在？

    优先级（先便宜后贵）：
      ① 右下角那颗按钮的文字（购买/选择/离开/完成/领取/确定）—— 免费：就在 `it` 里，
         弹窗系 1444 ⇒ 归一化帧 1235，在 BAND 内 ⇒ 真机上也认得出来 ✓
      ② 标题（只有 C=0 的 PC/9:16 上才可能在帧里）
      ③ 兜底：整帧弹窗 OCR（≈2s，只在①②都没有时才付这个钱）
    """
    if _btn(it)[0]:
        return True
    if _has(it, VAULT['title']) or _has(it, '黄全宝库'):
        return True
    return bool(_has_dlg(bot, VAULT['title'], '黄全宝库'))


def _confirm(bot, log, tag=''):
    """处理可能的确认/奖励弹窗：只点「确定」，绝不点「取消」"""
    for _ in range(2):
        it = _items(bot)
        ok = None
        for t in it:
            if t['text'].strip() == '确定' and t['cy'] > 800:
                ok = t
                break
        if not ok:
            return False
        bot.tap_dlg(ok['cx'], ok['cy'], wait=2.0)
        log.append({'buy_confirm': tag, 'at': (ok['cx'], ok['cy'])})
    return True


def merchant_flow(bot, log):
    """旅行商人：购买 → 返回，重复 4 次 → 关 X（2026-09-25 实机验证过）"""
    bought = 0
    for i in range(MERCHANT['times']):
        it = _items(bot)
        if _has(it, '金币不足', '钻石不足'):
            log.append({'merchant': 'no_money', 'i': i})
            break
        buy = _has(it, '购买')
        if not buy and i > 0:
            break
        bot.tap_dlg(*MERCHANT['buy'], wait=2.0)
        _confirm(bot, log, 'merchant%d' % i)
        it = _items(bot)
        back = _has(it, '返回')
        at = (back['cx'], back['cy']) if back else MERCHANT['back']
        bot.tap_dlg(at[0], at[1], wait=1.6)
        bought += 1
        log.append({'merchant': 'bought', 'i': i, 'back': at})
    bot.tap_dlg(*MERCHANT['x'], wait=2.0)
    log.append({'merchant': 'done', 'bought': bought})
    return bought


# ⭐⭐⭐ 2026-10-01 用户口径定案（别再改回去）：
#   「**同挡位优先天赋果实，不是越大越好**」
#   · 档位**只由数量决定**（同一层里数量就是档位）：草 1/2/4/8、果 5/10/20/50 ✓
#   · **同档位 ⇒ 天赋果实优先**（草在低档时不会因为种类被抬高 ✗）
#   · 「幸运草」就是「四叶草」（用户 2026-10-01 明确：「幸运草应该就是四叶草，我一般这么叫」，
#     游戏 `GoldenVault` 表里也只有 `D00002_000,四叶草` 一项）⇒ **同一个物品的两个叫法**，
#     绝不能再当成两样东西排序 ✗（此前我写「幸运草 > 四叶草 > 果实」是错的，已作废）
#   · 与用户「优先幸运草和四叶草」的关系：那句是"**草/果优先于神石/装备/符文**"的意思 ✓
#     ⇒ 非草非果的档位取 (0, 0)，永远不会赢过草/果 ✓
VAULT_PRIORITY = ('四叶草', '天赋果实')

# 「具体奖励」图标模板（从 main_sprites.bundle 导出，见 item_icons.py）
#   天赋果实 = Special_Item D00002_001 / 四叶草(幸运草) = D00002_000
ITEM_TPL_DIR = os.path.join(_MAPBOT_ROOT, 'templates', 'items')
ITEM_TPL = {'天赋果实': ['D00002_001.png'],
            '四叶草': ['D00002_000.png', 'D00002_000_2.png']}
ICON_FILL = 0.94          # 图标占格子间距的比例（实测 135/144 ✓）
_ICON_SRC = 30            # 图标源图 30px（从 main_sprites.bundle 导出时就是这个尺寸）
# ⭐ 图标命中阈值（实测真命中 0.73~0.97，误命中 ≤0.35 ✓）
# ⚠⚠ 2026-10-01 **严重回归修复**：我把它误删了（改 `_icon_scales()` 时连 `ICON_SCALE`/`ICON_THR`
#   一起换掉，`ICON_THR` 却仍被 `vault_pick` 使用）⇒ 宝库一进购买流程就
#   `NameError: name 'ICON_THR' is not defined`（真机 18:35 铁证：`vault:buy` 点了「购买」
#   之后每一轮都崩 ⇒ **宝库买不成、卡在面板上、最后强制脱困退图** ✗）
#   ⇒ 教训：**删常量前必须全文件搜引用**（本轮回归套件没覆盖到"常量是否定义"这类错误 ✗，
#     已补一条守门：`ICON_THR` 必须既有定义又有使用 ✓）
ICON_THR = 0.55


def _icon_scales():
    """图标缩放候选 —— **由格子间距 pitch 推出来**（分辨率无关 ✓），并扫 ±25%

    ⚠⚠ 2026-10-01 用户报「第二圈有个幸运草，但没识别出来就没选」：
      原来写死 `ICON_SCALE = 4.5` 且只试 4.3 / 4.5 / 4.7（±4.4%）⇒ 真机上只要图标实际尺寸
      差出这个范围（面板缩放、图标内边距与 PC 不同…）就**整批落到阈值以下**
      ⇒ `vault_pick` 报 `no_icon_hit` ⇒ 退成「随意选」⇒ 幸运草被漏 ✗
      ⇒ 现在：基准 = `pitch × ICON_FILL / 30`，再从 -25% 扫到 +20%（9 档）✓
      （pitch 本身是弹窗系常数 ⇒ 换分辨率时它跟着面板走 ⇒ 这是"自适应"的关键 ✓）
    """
    base = VAULT['pitch'] * ICON_FILL / float(_ICON_SRC)
    return tuple(round(base * f, 3)
                 for f in (0.75, 0.80, 0.85, 0.90, 0.95, 1.0, 1.05, 1.12, 1.20))


_ICON_SCALES_WIDE = tuple(round(VAULT['pitch'] * ICON_FILL / float(_ICON_SRC) * f, 3)
                          for f in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6))

QTY_OFF = (32, 22, 50, 50)   # 数量角标：相对格中心的 (dx, dy, w, h)

_TPL_CACHE = {}


def _load_item_tpl(wide=False):
    """{名称: [(灰度模板, 掩码, w, h) ...]}（多尺度 + 模板同名多文件）

    ⚠ 尺度由 `_icon_scales()` 给出（自适应 ✓）；`wide=True` 用更宽的一轮兜底 ✓
    """
    key = 'tpl_wide' if wide else 'tpl'
    if key in _TPL_CACHE:
        return _TPL_CACHE[key]
    import cv2
    import numpy as np
    out = {}
    _scales = _ICON_SCALES_WIDE if wide else _icon_scales()
    for name, files in ITEM_TPL.items():
        lst = []
        for fn in files:
            p = os.path.join(ITEM_TPL_DIR, fn)
            if not os.path.exists(p):
                continue
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if img is None or img.ndim < 3:
                continue
            for s in _scales:
                w, h = int(round(img.shape[1] * s)), int(round(img.shape[0] * s))
                g = cv2.cvtColor(cv2.resize(img[:, :, :3], (w, h),
                                            interpolation=cv2.INTER_AREA),
                                 cv2.COLOR_BGR2GRAY).astype(np.float32)
                m = cv2.resize(img[:, :, 3], (w, h),
                               interpolation=cv2.INTER_NEAREST) > 128
                if int(m.sum()) < 50:
                    continue
                v = g[m]
                v = v - v.mean()
                sd = v.std()
                if sd < 1e-6:
                    continue
                lst.append(((v / sd).astype(np.float32), m, w, h))
        if lst:
            out[name] = lst
    _TPL_CACHE[key] = out
    return out


def match_item_icon(img, cx, cy, wide=False, top=0):
    """该格是不是优先图标 -> (最好分数, 名称)（灰度掩码 NCC，对背景/亮度不敏感）

    ⭐ 2026-10-01：尺度自适应（见 `_icon_scales`）；搜索偏移 ±4 → **±7**
    （真机格子中心与理论值会有几像素偏差）；`top>0` 时返回**低于阈值的候选**
    供诊断（用户报「幸运草没识别出来」时要能看见分数 ✓）
    """
    import cv2
    import numpy as np
    tpls = _load_item_tpl(wide=wide)
    best, bestname = -1.0, None
    _rank = []
    for name, lst in tpls.items():
        _bn, _bs = None, -1.0
        for (tv, m, w, h) in lst:
            for dx in (-7, 0, 7):
                for dy in (-7, 0, 7):
                    x0 = int(cx - w / 2 + dx)
                    y0 = int(cy - h / 2 + dy)
                    sub = img[y0:y0 + h, x0:x0 + w]
                    if sub.shape[0] != h or sub.shape[1] != w:
                        continue
                    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                    pv = g[m]
                    pv = pv - pv.mean()
                    sd = pv.std()
                    if sd < 1e-6:
                        continue
                    sc = float((pv / sd * tv).mean())
                    if sc > _bs:
                        _bs, _bn = sc, name
                    if sc > best:
                        best, bestname = sc, name
        if _bn:
            _rank.append((round(_bs, 3), _bn))
    if top and _rank:
        return best, bestname, sorted(_rank, reverse=True)[:top]
    return best, bestname


def _qty_tmp_path():
    """数量角标临时 PNG 的路径 —— **必须先保证目录真的存在**。

    ⚠ 2026-09-29 安卓端踩坑（用户报「卡在黄金宝库购买界面」的真凶）：
      原来写死 `dirname(__file__)/runs`。端上这个根是**只读资源包** `files/mapbot_pack/`
      （只有 `templates/` 与数据表，**没有 `runs/`**）⇒ `cv2.imencode(...).tofile()` 抛
      `FileNotFoundError` ⇒ 黄金宝库每轮 `vault_pick` 都炸 ⇒ 3 轮后 `too_many_errors`
      ⇒ 收工离场，把游戏留在购买面板 ✗
    现在统一用 `mapbot.RUNS`（PC/安卓同一个口径，且安卓侧已 makedirs），再兜
    `MAPBOT_RUNS` 环境变量、模块旁的 runs、系统临时目录，每层都 makedirs。
    """
    cands = []
    try:
        from mapbot import RUNS as _R
        if _R:
            cands.append(_R)
    except Exception:
        pass
    if os.environ.get('MAPBOT_RUNS'):
        cands.append(os.environ['MAPBOT_RUNS'])
    cands.append(os.path.join(_MAPBOT_ROOT, 'runs'))
    for d in cands:
        try:
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, '_qty.png')
        except Exception:
            continue
    import tempfile
    return os.path.join(tempfile.gettempdir(), '_qty.png')


def read_qty(bot, cx, cy):
    """读图标右下角的数量角标（实测放大 8 倍 OCR 置信度 0.99~1.00）

    ⚠ v0.61：cx/cy 是**弹窗系**坐标 ⇒ 必须取弹窗帧（`bot.img_dlg()`）来裁这一小块，
      否则在真机上会从错 248px 的地方裁（读到的"数量"来自别的格子）。
    """
    import cv2
    import numpy as np
    from mapbot import _ocr
    img = bot.img_dlg()
    dx, dy, w, h = QTY_OFF
    x0, y0 = int(cx + dx), int(cy + dy)
    sub = img[y0:y0 + h, x0:x0 + w]
    if sub.size == 0:
        return None
    big = cv2.resize(sub, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)
    tmp = _qty_tmp_path()
    cv2.imencode('.png', big)[1].tofile(tmp)
    res, _ = _ocr()(tmp)
    for it in (res or []):
        t = it[1].strip().replace('x', '').replace('X', '').replace('*', '')
        if t.isdigit() and 1 <= len(t) <= 4 and float(it[2]) >= 0.5:
            return int(t)
    return None



# 「四叶草(=口语"幸运草"，同一物品) / 天赋果实」在同一层里出现的**数量** ⇒ 档位
# （游戏 `GoldenVault` 表：草 1/2/4/8、果 5/10/20/50，按 Level 分档 ✓）
VAULT_TIER = {
    '四叶草': {1: 1, 2: 2, 4: 3, 8: 4},
    '天赋果实': {5: 1, 10: 2, 20: 3, 50: 4},
    '幸运草': {1: 1, 2: 2, 4: 3, 8: 4},     # 同一物品的口语别名（OCR/界面可能这么显示 ✓）
}


# 同档位的**平分决胜**（仅此才看种类）：**天赋果实优先**（用户 2026-10-01 口径 ✓）
PREF_FRUIT = 1
PREF_CLOVER = 0


def vault_tier_of(name, qty):
    """(名称, 数量) → (档位, 平分决胜)；排序键取最大 ⇒ **先比档位，同档天赋果实优先** ✓

    ⭐⭐⭐ 2026-10-01 用户口径（原话：「**同挡位优先天赋果实，不是越大越好**」）：
      ① **档位只由数量决定**（同一层里的数量就是档位）—— 8 草(档4) 与 50 果(档4) 同档，
         与 20 果(档3) 比时 **8 草胜**（档位高者胜 = 数量说话 ✓）
      ② **同档位 ⇒ 天赋果实优先**（`PREF_FRUIT=1` > `PREF_CLOVER=0` ✓）
         ⚠ 此前写过「同档草优先」和「数量越大越好」两种错法，都已作废 ✗
      ③ 非草非果（神石/装备/符文）⇒ (0, 0)：既进不了高档位，也赢不过草/果的同档 ✓
         （这就是用户「优先幸运草和四叶草」的实际含义：**草/果 优先于其它奖励** ✓）
    未知数量 ⇒ 近似：草按数量、果按 数量/6.25（= 8:50 的比值 ✓）
    ⚠⚠ 2026-10-01 修（离线执行测试发现的隐患）：近似公式**必须夹到已知档位区间内**，
      否则 `read_qty` 把「草」的数量误读成 50（或读成 999）时
      `t = 50` ⇒ 档位 **50.0** ⇒ **误判为远超最高的第 4 档** ⇒ 把垃圾选成最优 ✗
      （实测：打了 read_qty 桩返回 50 时，四叶草被算成 `档50.00`）
      现在：近似值夹进 [1, 4]（游戏只有 4 档 ✓），且**大于最高档数量**时判为"读错" ⇒ 降到 0 档
      比较保守 ⇒ 不会因为一个 OCR 误读就把别的真奖励挤掉 ✓
    """
    nm = name or ''
    q = int(qty or 0)
    _prio = PREF_FRUIT if '果' in nm else (
        PREF_CLOVER if ('幸运草' in nm or '四叶草' in nm) else 0)
    for key, tbl in VAULT_TIER.items():
        if key in nm:
            t = tbl.get(q)
            if t is None:                       # 表外数量 ⇒ 近似（**必须夹到 1~4 档** ✓）
                _qmax = max(tbl)                # 该物品的最高档数量（草 8 / 果 50）
                if q <= 0 or q > _qmax:
                    # 数量读错（> 最高档）或没读到 ⇒ **保守当 0 档**（不冒充当高档 ✓）
                    t = 0.0
                else:
                    t = (q / 6.25) if '果' in nm else float(q)
                    t = max(1.0, min(4.0, t))   # 夹进 4 档区间 ✓
            return (float(t), _prio)
    return (0.0, 0)          # 其它物品（神石/装备/符文）不进这个比较 ✓


def _probe_name(bot, at, wait=1.5):
    """⭐ 2026-10-01 用户口径兜底：**点开这一格看它的名字**，再点空白处收起详情 ✓

    返回读到的名称串（读不到 → None）。全程弹窗系（宝库面板锚设备中心 ✓）。
    ⚠ 只用于「图标模板一个都没命中」的兜底路径 ⇒ 正常路径零额外开销、零额外点击 ✓
    """
    try:
        bot.tap_dlg(at[0], at[1], wait=wait)
    except Exception:       # noqa: BLE001
        return None
    it = _items(bot)                       # 详情面板：文字集中在面板左/上，名称最显眼
    nm = ''
    for t in sorted(it, key=lambda z: (z['cy'], z['cx'])):
        s = (t['text'] or '').strip()
        if not s or len(s) > 12:
            continue
        # 跳过 UI 词与纯数字（价格/数量）
        if s in ('购买', '选择奖励', '离开', '完成', '领取', '确定', '确认', '返回',
                 '取消', '关闭', '宝库', '黄金宝库'):
            continue
        if s.replace(',', '').replace('+', '').isdigit():
            continue
        if any(k in s for k in ('幸运草', '四叶草', '天赋果实', '果实')):
            nm = s                        # 玩家要的三样：直接定案 ✓
            break
        if not nm and any('\u4e00' <= ch <= '\u9fff' for ch in s):
            nm = s                        # 其它中文名（神石/装备/符文…）也留着做兜底 ✓
    try:
        bot.tap_dlg(*VAULT['blank'], wait=1.1)     # 收起详情（实测有效 ✓）
    except Exception:       # noqa: BLE001
        pass
    return nm or None


def _vault_dump(name, img):
    """把宝库面板帧落盘（**认不出图标时**才调，零成本不拖正常路径 ✓）

    安卓真机：优先落 `/sdcard/Download/autoexplore/bagdbg/`（release 包不可 run-as，
    私有 `runs/` 拿不出来 ✗）；PC：落 `RUNS/vaultdbg/` ✓
    """
    try:
        import cv2
        cands = ['/sdcard/Download/autoexplore/bagdbg']
        try:
            from mapbot import RUNS as _R
            if _R:
                cands.append(os.path.join(_R, 'vaultdbg'))
        except Exception:
            pass
        for d in cands:
            try:
                os.makedirs(d, exist_ok=True)
                p = os.path.join(d, str(name) + '.png')
                cv2.imencode('.png', img)[1].tofile(p)
                return p
            except Exception:
                continue
    except Exception:
        pass
    return None


def vault_pick(bot, log, level, max_probe=25):
    """在某一层里挑一件奖励（**用户口径：不点开详情，直接认图标**）

    1. 只扫该层那一圈格子（d=2 → 16 格 / d=1 → 8 格 / d=0 → 1 格）
    2. 图标模板匹配 → 认「天赋果实 / 四叶草(幸运草)」
    3. 命中的格子再 OCR 右下角数量角标 → **取数量最多的那件**
    4. 一个都没命中就随便取该圈第一格兜底
    ⭐ 用户口径（2026-09-25）：**第一轮只能选最外一圈、第二轮中间一圈、第三轮只有中间一格**
       ⇒ 第三轮不用扫，直接点中心
    """
    cells = vault_ring(level)[:max_probe]
    it = _items(bot)
    if not _present(bot, it):
        return (cells[0] if cells else VAULT['buy']), '?'
    img = bot.img_dlg()                     # ⚠ 弹窗系坐标 ⇒ 必须用弹窗帧
    # ⭐⭐⭐ 2026-10-01 v0.98【第一步：用**颜色检测**拿到"这一圈真实存在的奖励格"】
    #   真机实测（vault_no_hit_L2.png）：面板高度随提示文案变 ⇒ 网格比常数 `gy0=746` **低 ~51px**
    #   ⇒ 旧代码在格子上方 51px 处裁窗口 ⇒ 全盘 NCC 0.12~0.31 ⇒ 认不出草/果 ⇒ 逐格点开读名（乱点）✗
    #   彩色底（蓝/紫）= 有奖励的格（空格/已领格是棕色）⇒ 检测它的中心既修了裁图、也修了点击位置 ✓
    _rad = {}
    try:
        _tiles = vault_tiles(img)
    except Exception:       # noqa: BLE001
        _tiles = []
    if _tiles:
        log.append({'vault': 'tiles_detected', 'n': len(_tiles),
                    'at': [[x, y, w, h] for (x, y, w, h) in _tiles[:20]],
                    'const_first': [VAULT['gx0'], VAULT['gy0']]})
        cells = [(x, y) for (x, y, _w, _h) in _tiles]
        for (x, y, w, h) in _tiles:
            _rad[(x, y)] = int(min(w, h) * 0.36)
    if len(cells) == 1:                     # 第三轮：只有核心一格，无需扫描
        log.append({'vault': 'center_only', 'at': cells[0]})
        return cells[0], '核心'
    # ⭐⭐⭐ 2026-10-01 v0.98【第二步：**按颜色认种类**（尺度无关、真机区分度 0.35+ vs 0.005）】
    #   「天赋果实」= 洋红粉（R>150 且 B>0.55R）｜「四叶草/幸运草」= 绿（G 明显最大）
    #   ⇒ 认出就直接按档位选一件（用户口径：**识别到天赋果实和幸运草就直接选这俩其中一个** ✓）
    #   ⇒ 不再走"点开格子读名"那条会被用户看成乱点的路 ✓
    try:
        _color_hits = []
        for _p in cells:
            _kk, _fr = sprite_kind(img, _p[0], _p[1],
                                   _rad.get(_p, int(VAULT['pitch'] * 0.36)))
            if _kk:
                _color_hits.append((_p[0], _p[1], _kk,
                                    round(_fr['pink'], 3), round(_fr['green'], 3)))
        if _color_hits:
            log.append({'vault': 'color_hit', 'n': len(_color_hits),
                        'hits': _color_hits})           # [x, y, 名称, pink, green]
            _cr = []
            for (x, y, _kk, _pk, _gr) in _color_hits:
                _q = read_qty(bot, x, y)
                _t = vault_tier_of(_kk, _q)
                _cr.append((_t, _q, _kk, (x, y)))
                log.append({'vault': 'color_tier', 'name': _kk, 'qty': _q, 'at': (x, y),
                            'tier': round(_t[0], 2), 'pref': _t[1],
                            'pink': _pk, 'green': _gr})
            _cr.sort(key=lambda z: z[0], reverse=True)
            _t0, _q0, _k0, _at0 = _cr[0]
            log.append({'vault': 'pick_color', 'name': _k0, 'qty': _q0, 'at': _at0,
                        'tier': round(_t0[0], 2),
                        'why': '颜色判种（尺度无关）＋先比档位(数量)、同档天赋果实优先 ✓'})
            return _at0, '%s×%d(色判)' % (_k0, _q0 or 0)
        log.append({'vault': 'color_none', 'cells': len(cells)})
    except Exception as _ec:        # noqa: BLE001
        log.append({'vault': 'color_error', 'e': repr(_ec)[:80]})
    cands = []
    _near = []
    for (x, y) in cells:
        _r = match_item_icon(img, x, y, top=2)
        sc, name = _r[0], _r[1]
        if len(_r) > 2 and _r[2]:
            _near.append({'at': (x, y), 'top': _r[2]})
        if name and sc >= ICON_THR:
            qty = read_qty(bot, x, y)
            cands.append((qty if qty else 0, round(sc, 3), name, (x, y)))
    # ⭐ 2026-10-01 诊断（用户报「幸运草没识别出来」）：把**每一格的最好分数**都记下来 ——
    #   低于阈值时也能看出"是差一点（0.4~0.55）"还是"根本没对上（<0.2）"，从而区分
    #   「尺寸不对」与「模板/图不对」✓（logcat 里 `vault_debug` 一行即可判 ✓）
    log.append({'vault_debug': 'cells', 'level': level, 'n': len(cells),
                'thr': ICON_THR, 'scales': list(_icon_scales()),
                'near': _near[:8]})
    if not cands:                           # ⭐ 兜底：宽尺度再扫一轮（尺寸差很多时救回来 ✓）
        for (x, y) in cells:
            sc2, name2 = match_item_icon(img, x, y, wide=True)
            if name2 and sc2 >= ICON_THR:
                qty2 = read_qty(bot, x, y)
                cands.append((qty2 if qty2 else 0, round(sc2, 3), name2, (x, y)))
        if cands:
            log.append({'vault': 'icon_hit_wide', 'n': len(cands)})
    # ⭐ 2026-09-27：按**档位**比；⭐ 2026-10-01 用户口径：同档 **幸运草 > 四叶草 > 天赋果实**
    for c in cands:
        c_t = vault_tier_of(c[2], c[0])
        log.append({'vault': 'icon_hit', 'name': c[2], 'qty': c[0], 'score': c[1],
                    'tier': round(c_t[0], 2), 'pref': c_t[1], 'at': c[3]})
    if cands:
        cands.sort(key=lambda c: vault_tier_of(c[2], c[0]), reverse=True)
        q, sc, name, at = cands[0]
        _t = vault_tier_of(name, q)
        log.append({'vault': 'pick_best', 'name': name, 'qty': q, 'at': at,
                    'tier': round(_t[0], 2), 'pref': _t[1],
                    'why': '先比档位(数量)；同档 天赋果实优先 ✓'})
        return at, '%s×%d(档%.2f)' % (name, q, _t[0])
    # ⭐⭐⭐ 2026-10-01 用户口径：「宝库要给它一个兜底：**如果识别不到，就点击进去看是什么**，
    #   如果有幸运草或者四叶草或者天赋果实就选，没有就选择默认或者其它的」
    #   ⇒ 图标全不中时不"随便点第一格"，而是**逐格点开详情 → OCR 读名称** ⇒ 认得就选 ✓
    # ⭐⭐⭐ 2026-10-01 用户报「点一下左上角的奖励格子，关闭宝库界面」⇒ 兜底路径重做：
    #   旧写法**逐格点开详情**（16 格 × (点击+2 次 OCR+收起详情) ≈ **40 秒**），
    #   而「收起详情」点的 `blank` 在真机上落在**面板外**（旧值 (540,1700)）
    #   ⇒ 每格都在棋盘上点一下 = 用户看到的**乱点/关掉面板** ✗✗
    #   新口径（省时 + 不乱点）：
    #     ① 只对**分数最接近阈值的前 3 格**点开详情（不再 16 格全点）✓
    #     ② 收起详情点**面板内安全空白**（VAULT['blank'] 已按真机帧修正 ✓）
    #     ③ 全部读不到名字 ⇒ 才回落"取第一格"（保持旧兜底语义 ✓）
    log.append({'vault': 'no_icon_hit', 'cells': len(cells)})
    try:
        _p = _vault_dump('vault_no_hit_L%d' % level, img)
        if _p:
            log.append({'vault': 'dump', 'path': _p})
    except Exception:       # noqa: BLE001
        pass
    # 候选 = 先算每格的分数，再按分数降序取**前 3 格**去点开详情（分数高的更可能是草/果 ✓）
    # ⚠ 2026-10-01 修：我第一版写成
    #     `sorted(((_r[0], _at) for _r, _at in [(match_item_icon(...)[0], (x,y)) ...]))`
    #   那是**先解包成 (分数, 坐标)、又当成 (分数, 坐标) 再解包一次** ✗
    #   ⇒ `TypeError: 'float' object is not subscriptable`（真机每轮崩、卡在"正在开箱" ✗）
    #   现在写成两步、变量名自解释，杜绝这类解包错误 ✓
    _scored = []
    for (_x, _y) in cells:
        _sc1 = match_item_icon(img, _x, _y)[0]        # 只要分数（名字此处不用 ✓）
        _scored.append((float(_sc1 or 0), (_x, _y)))
    _scored.sort(key=lambda z: z[0], reverse=True)
    _ranked = _scored[:3]                             # ⭐ 只探前 3 格（旧写法 16 格 ≈40 秒 ✗）
    _want = []
    for _i, (_sc3, _at) in enumerate(_ranked):        # _sc3 = float 分数，_at = (x,y) ✓
        nm = _probe_name(bot, _at)
        log.append({'vault': 'probe', 'i': _i, 'at': _at,
                    'score': round(float(_sc3), 3), 'name': nm})
        if not nm:
            continue
        for _k, _prio in (('幸运草', 3), ('四叶草', 2), ('天赋果实', 1), ('果实', 1)):
            if _k in nm:
                _want.append((_prio, _at, _k, nm))
                break
        # ⭐ v0.97 用户报「购买第一层后**点击了好几个奖励**才选择奖励」⇒ 已经探到想要的就收手：
        #   分数最高的那格先探（最可能是草/果），探到了就**不再点开其它格**（少几下乱点 ✓）
        if _want:
            log.append({'vault': 'probe_early_stop', 'i': _i, 'of': len(_ranked)})
            break
    if _want:
        _want.sort(reverse=True)
        _prio, _at, _k, nm = _want[0]
        log.append({'vault': 'probe_pick', 'name': nm, 'kind': _k, 'prio': _prio,
                    'at': _at, 'why': '图标没中 ⇒ 点开前 3 格读名，草/果优先 ✓'})
        return _at, '%s(读名✓)' % nm
    log.append({'vault': 'probe_none'})
    return (cells[0] if cells else VAULT['buy']), '随意'



def vault_ring(k):
    """第 k 层（1 外层 16 / 2 内层 8 / 3 核心 1）的格子坐标列表

    5x5 里按到中心的切比雪夫距离分层：d=2 → 16 格，d=1 → 8 格，d=0 → 1 格
    """
    gx, gy, p = VAULT['gx0'], VAULT['gy0'], VAULT['pitch']
    d = {1: 2, 2: 1, 3: 0}[max(1, min(3, k))]
    out = []
    for r in range(5):
        for c in range(5):
            if max(abs(r - 2), abs(c - 2)) == d:
                out.append((gx + c * p, gy + r * p))
    return out


def _tile_mask(img):
    """「有奖励的格子」掩码 = **高饱和的彩色格子底**（蓝/紫/绿/红都算），排除棕色空格底

    ⚠ v0.98 定标（真机两帧）：只用"蓝底"（`b-g>25`）会**漏掉绿/红/黄底**的奖励格
      ⇒ 用「饱和度 + 非棕」更全；空格/已领格是棕色底（`r>b+30 & g>b+10`）⇒ 被排除 ✓
    """
    import numpy as np
    b = img[:, :, 0].astype(int)
    g = img[:, :, 1].astype(int)
    r = img[:, :, 2].astype(int)
    mx = np.maximum(np.maximum(b, g), r)
    mn = np.minimum(np.minimum(b, g), r)
    sat = mx - mn
    brown = (r > b + 30) & (g > b + 10) & (sat < 95)
    return ((sat > 60) & (mx > 120) & (~brown)).astype('uint8')


def vault_tiles(img, min_area=4000, min_side=100, max_side=185):
    """当前这圈**可选的奖励格**（彩色底）中心/尺寸 —— **检测出来的，不是写死的网格常数**

    ⚠⚠ 2026-10-01 v0.98 真机根因（用户报「宝库选择奖励界面纯在乱点」）：
      面板高度随提示文案/按钮文案变（真机实测这屏提示是两行）⇒ 网格整体比
      `VAULT['gy0']=746` **低 ~51px**（实测行中心 942 / 1085 / 1231，常数 890 / 1034 / 1178）
      ⇒ 旧代码在格子**上方 51px** 的地方裁 135px 窗口去认图标 ⇒ 全盘 NCC 掉到 **0.12~0.31**
        （真机 log 实测）⇒ `no_icon_hit` ⇒ 退成"逐格点开读名" ⇒ **东点一下西点一下** ✗
      而"有奖励的格子"一定有**彩色底**（空格/已领格是棕色底）⇒ 直接检测它们，
      既拿到**真实格心**（顺便修了点击位置）又拿到"这一圈有哪些格" ✓
    ⚠ 彩色掩码会把**同一个格子切成两块**（精灵本身也高饱和）⇒ 按中心距离 60px 去重、留大块 ✓
    """
    import cv2
    try:
        m = _tile_mask(img)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
        n, _lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    except Exception:       # noqa: BLE001
        return []
    raw = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a > min_area and min_side <= w <= max_side and min_side <= h <= max_side \
                and y > 700 and x < 960:          # 弹窗帧：网格在面板中下部、左侧 ✓
            raw.append((int(round(cent[i][0])), int(round(cent[i][1])), int(w), int(h), int(a)))
    raw.sort(key=lambda z: -z[4])                 # 大块优先 ⇒ 去重时留它 ✓
    out = []
    for (x, y, w, h, _a) in raw:
        if any(abs(x - q[0]) < 60 and abs(y - q[1]) < 60 for q in out):
            continue
        out.append((x, y, w, h))
    out.sort(key=lambda z: (z[1], z[0]))          # 从上到下、从左到右 ✓
    return out


def sprite_colors(img, cx, cy, r):
    """格子里的**精灵**（去掉格子底色）颜色占比 -> {'pink':粉/洋红, 'green':绿, 'n':精灵像素数}

    ⭐ 真机实测（vault_no_hit_L2.png）区分度很好：
        粉果实×10   pink **0.574**   （洋红：R>150 且 B>0.55R 且 R-G>40）
        绿四叶草    green **0.356**  （绿：G-R>25 且 G-B>25 且 G>110）
        红宝石      pink  **0.005** ← 用"洋红"而不是"红"，把红宝石/装备排除掉了 ✓
        白水晶/紫水晶 pink ≤0.05 / green 0 ✓
    """
    import numpy as np
    r = int(r)
    sub = img[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
    if sub.size < 400:
        return {'pink': 0.0, 'green': 0.0, 'n': 0}
    px = sub.reshape(-1, 3).astype(int)
    q = px // 8
    key = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
    vals, cnt = np.unique(key, return_counts=True)
    bg = vals[cnt.argmax()]
    bgc = np.array([(bg // 10000) * 8, ((bg // 100) % 100) * 8, (bg % 100) * 8])
    sp = px[np.abs(px - bgc).sum(axis=1) > 90]          # 去掉格子底色 ⇒ 剩下的就是精灵
    if len(sp) < 80:
        return {'pink': 0.0, 'green': 0.0, 'n': int(len(sp))}
    B, G, R = sp[:, 0], sp[:, 1], sp[:, 2]
    pink = float(((R > 150) & (B > 0.55 * R) & ((R - G) > 40)).mean())
    green = float((((G - R) > 25) & ((G - B) > 25) & (G > 110)).mean())
    return {'pink': pink, 'green': green, 'n': int(len(sp))}


# ⭐ 阈值（真机两帧实测标定，2026-10-01 v0.98）：
#   真「粉果实×10」pink **0.571** ｜ 真「绿四叶草」green **0.356**
#   误命中：红宝石/棕装备/水晶 pink **0.16~0.18**、green **0.00**
#   ⇒ pink 取 0.35（把红宝石那批 0.16~0.18 干净排除 ✓）、green 取 0.25（真值 0.356，余量足 ✓）
SPRITE_PINK_THR = 0.35
SPRITE_GREEN_THR = 0.25


def sprite_kind(img, cx, cy, r):
    """该格按**颜色**判是什么 -> ('天赋果实'/'四叶草', 占比) 或 (None, 占比)

    ⚠ 阈值必须按真机实测标定：只用"红"会把**红宝石/棕装备**（pink 0.16~0.18）也算成
      「天赋果实」✗ —— 所以判据是**洋红**（粉果实：R>150 且 B>0.55R）而不是"红"，
      阈值再定在 0.35（真值 0.571）⇒ 两帧真机数据零误命中 ✓
    """
    fr = sprite_colors(img, cx, cy, r)
    if fr['pink'] >= SPRITE_PINK_THR and fr['pink'] >= fr['green']:
        return '天赋果实', fr
    if fr['green'] >= SPRITE_GREEN_THR:
        return '四叶草', fr
    return None, fr


def _btn(it):
    """读面板右下角那颗按钮 ——**位置每次都可能不一样**，所以必须每轮 OCR 定位。

    ⭐⭐⭐ 2026-10-01 真机帧实测（用户停在宝库面板抓帧）：
        `购买` @dlg(**895, 1498**) ｜ 价格 `10000` @dlg(914, **1541**)
      而旧 y 带写死 `1400 ~ 1530` ⇒ 按钮文字落在 1498 时**勉强命中**、价格 1541 **在带外**；
      面板布局随文案变化（「选择奖励/离开/完成/领取」行数不同）就会整体掉出带外
      ⇒ `label=None` ⇒ `vault_flow` 走 `no_select_btn` ⇒ **跳过整层**（不买不选）✗
      ⇒ 用户报「第一层还没选择奖励就乱点了 / 选了默认没选天赋果实」的机制之一 ✓
      修法：y 带放宽到 **1360 ~ 1660**（覆盖实测 1498/1541 及三种文案的浮动 ✓）×
            x 带放宽到 **700 ~ 1040** ✓

    -> (label, cost, (cx,cy))；label ∈ 购买/选择奖励/离开/完成/领取
    """
    label, cost, pos = None, None, None
    KEYS = ('购买', '选择', '离开', '完成', '领取', '确定')
    for t in it:
        if not (1360 < t['cy'] < 1660 and 700 < t['cx'] < 1040):
            continue
        s = t['text'].strip()
        if any(k in s for k in KEYS):
            label = s
            pos = (t['cx'], t['cy'])
        elif s.replace(',', '').replace('+', '').isdigit() and len(s) >= 4:
            cost = int(s.replace(',', '').replace('+', ''))
            if pos is None:
                pos = (t['cx'], t['cy'])
    return label, cost, pos


def _back_btn(it):
    """中间那颗「返回」——按**文本 + 专用位置窗口**认，别用「不含离开」这种条件：
    领完奖励时「恭喜获得」+「返回」和右下角「离开」会同时出现，
    用 `not _has(it,'离开')` 会把「返回」漏掉（用户 2026-09-25 报「选择奖励后没有点返回」）

    ⚠⚠ 2026-10-01 v0.97 修真机根因（用户本轮报「**选择后不点返回就直接点购买**」）：
      位置判据原先锚在 `VAULT['back']` 上 —— 而 v0.88 把 `VAULT['back']` 从 (539,1212)
      改成了**面板内安全空白 (660,1590)**（那是给"兜底点一下收起详情"用的坐标）
      ⇒ 判据窗口跟着漂到 x 530~790 / y 1500~1680，而真机「返回」实测在 **dlg(538,1267)**
      ⇒ `_back_btn` **恒返回 None** ⇒ `vault_flow` 既收不掉奖励展示、又照样去点「购买」✗
      ⇒ 现在：`VAULT_BACK_ZONE` 专用窗口（±170/±120，覆盖 1212~1267 与布局浮动）
        + 一条"面板中下部任意「返回」"的文字兜底 ✓
    """
    for t in it:
        if '返回' not in (t.get('text') or ''):
            continue
        if abs(t['cx'] - VAULT_BACK_ZONE[0]) < 170 \
                and abs(t['cy'] - VAULT_BACK_ZONE[1]) < 120:
            return t
        if 900 < t['cy'] < 1520 and 330 < t['cx'] < 760:
            return t                          # 文字兜底（面板挪动/文案行数变了也认得出 ✓）
    return None


def _reward_showing(it):
    """现在是不是**奖励展示态**（模态：「恭喜获得 …」/ 屏幕上还有「返回」）

    ⭐ v0.97：奖励展示是**模态**的 —— 此时点「购买」只会白点（真机被连点 4 次 ✗）。
      所以整个宝库流程里有一条硬规矩：**看到「返回/恭喜获得」就先把它们收掉，
      收不干净就本轮收工（下一轮再来），绝不去点购买** ✓
    """
    if _has(it, '恭喜获得'):
        return True
    return bool(_back_btn(it))



def _dismiss(bot, log, tries=3):
    """收起奖励展示（中间「返回」）/ 确认弹窗（只点确定）

    ⭐ v0.97：返回值 = **还看得见「返回」/「恭喜获得」吗**（True = 没收拾干净）
      —— 调用方必须用它挡住下一圈的「购买」：奖励展示是模态的，
      此时点购买只有两个下场：白点，或者**把面板点乱**（真机连点 4 次 ✗）。
    """
    for _ in range(tries):
        it = _items(bot)
        bk = _back_btn(it)
        if bk:
            bot.tap_dlg(bk['cx'], bk['cy'], wait=2.2)
            log.append({'vault': 'back', 'at': (bk['cx'], bk['cy'])})
            continue
        ok = None
        for t in it:
            if t['text'].strip() in ('确定', '确认') and t['cy'] > 700:
                ok = t
                break
        if ok:
            bot.tap_dlg(ok['cx'], ok['cy'], wait=2.2)
            log.append({'vault': 'confirm', 'at': (ok['cx'], ok['cy'])})
            continue
        return False
    it = _items(bot)
    return bool(_reward_showing(it))


def vault_flow(bot, log):
    """黄金宝库买完 —— **按 1→2→3 圈依次走一遍**（用户 2026-09-25 定案）

    为什么按圈遍历而不是「数自己买了几次」：中途接手时计数从 0 开始，
    会一直去点第 1 圈 → 死循环（用户：「你刚刚是一直重复第一圈」）。
    按圈遍历时，某一圈点错了也只是**空操作**（游戏 `OnFuncButtonClicked` 会检查
    `selectingIndex` 必须属于当前层，不属于就直接 return），不会误领，下一圈继续。

    每一圈：
      ① 按钮是「购买」→ 先点它解锁（10000 外层 / 20000 内层 / 40000 核心）
      ② 按钮是「选择奖励」→ 在**这一圈**里挑（优先天赋果实/四叶草，比右下角数量）
         → 点中选那格 → 点这颗按钮
      ③ 出现「返回」→ 点掉，回到宝库面板
    三圈走完按钮变「离开」→ 点它；还开着就点右上 X 兜底。
    """
    acts = []
    for ring in (1, 2, 3):
        # ① 需要时先解锁这一圈（⭐ 复用最后一帧：没买成时不必再 OCR 一次）
        it = None
        _buy_clicks = []                      # ⭐ v0.97：本圈点过的「购买」价格 ⇒ 防连点
        for _ in range(4):
            it = _items(bot)
            if _reward_showing(it):           # ⭐ v0.97：奖励展示/「返回」是**模态**
                if _dismiss(bot, log):        #   此时点购买只会白点 ⇒ 必须先收掉
                    log.append({'vault': 'reward_stuck', 'ring': ring})
                it = None
                continue
            label, cost, pos = _btn(it)
            if label and '购买' in label:
                if cost is not None and cost in _buy_clicks:
                    # ⭐⭐⭐ v0.97 真机修（用户报「选择后不点返回就直接点购买」）：同一个价格的
                    #   「购买」又出现了 ⇒ 上一次点击**根本没生效**（被模态/钱不够/点空）
                    #   ⇒ 绝不再点（旧写法 `for _ in range(4)` 会连点 4 次 ✗）：
                    #     收起面板、这圈放弃、交给下一轮 ✓
                    log.append({'vault': 'buy_no_effect', 'ring': ring, 'cost': cost})
                    say('      · 宝库第 %d 层：点了「购买」没生效 ⇒ 不再连点（先收起面板 ✓）' % ring)
                    _dismiss(bot, log)
                    it = None
                    break
                _buy_clicks.append(cost)
                bot.tap_dlg(*(pos or VAULT['buy']), wait=2.6)
                _confirm(bot, log, 'vault_buy%d' % ring)
                log.append({'vault': 'buy', 'ring': ring, 'cost': cost, 'at': pos})
                acts.append('buy%d' % ring)
                it = None                     # 画面变了 ⇒ 这一帧作废
                continue
            break                             # 不是「购买」⇒ it 就是当前帧，直接复用
        if it is None:
            it = _items(bot)
        if not _present(bot, it):
            log.append({'vault': 'panel_gone', 'ring': ring})
            break
        label, cost, pos = _btn(it)
        if label and '离开' in label:
            bot.tap_dlg(pos[0], pos[1], wait=2.4)
            log.append({'vault': 'leave'})
            break
        if not (label and ('选择' in label or '领取' in label)):
            # ⭐⭐⭐ 2026-10-01 用户报「第一层还没选择奖励就乱点了 / 选了默认没选天赋果实」：
            #   旧写法这里**直接 `continue` 跳过整层** ⇒ 既不点「选择奖励」也不挑格子
            #   ⇒ 游戏保持**默认选中**的格子 ⇒ 用户看到的"选了默认、没选果实" ✗✗
            #   ⇒ 改成：**读不到按钮就先做保底动作**，绝不静默跳过一整层 ✓
            #     ① 先按真机标定坐标点一次「选择奖励/购买」（VAULT['buy']，实测 895,1498 ✓）
            #     ② 再挑一格（图标认不出 ⇒ `vault_pick` 自带 `_probe_name` 点开详情读名 ✓）
            #     ③ 然后重新读按钮，读到就正常点 ✓
            # ⚠⚠ v0.97 补闸门：这条"标定坐标保底"**必须先确认屏幕上没有奖励展示/返回** ——
            #   否则等于闭着眼睛点「购买」（真机连点 4 次就是这么来的 ✗）
            if _reward_showing(it):
                log.append({'vault': 'fallback_blocked_by_reward', 'ring': ring})
                if _dismiss(bot, log):
                    say('      · 宝库第 %d 层：奖励展示收不掉 ⇒ 本轮到此为止（不去点购买 ✓）' % ring)
                    return acts
                continue
            log.append({'vault': 'no_select_btn_fallback', 'ring': ring, 'label': label})
            say('      · 宝库第 %d 层：读不到按钮文字 ⇒ 用标定坐标保底（不跳过整层 ✓）' % ring)
            _pick_fb, _name_fb = vault_pick(bot, log, ring)
            if ring < 3:
                bot.tap_dlg(_pick_fb[0], _pick_fb[1], wait=1.7)
            log.append({'vault': 'claim_fallback', 'ring': ring,
                        'pick': _pick_fb, 'name': _name_fb})
            it = _items(bot)
            label, cost, pos = _btn(it)
            if not (label and ('选择' in label or '领取' in label)):
                bot.tap_dlg(*VAULT['buy'], wait=2.6)      # 标定坐标兜底 ✓
                acts.append('claim%d_fb' % ring)
                _dismiss(bot, log)
                continue
        # ② 在**这一圈**里挑一件 + 点按钮
        pick, name = vault_pick(bot, log, ring)
        if ring < 3:
            # ⚠ 第 3 圈（中心格）**游戏会自动选中**（源码 RefreshDefaultSelectingIndex：
            #   currentLevel==3 时 selectingIndex=12），再点一次等于点已选中的格子 →
            #   会弹出该奖励的详情面板、把右下角按钮盖住（用户 2026-09-25 报「点两下中间的」）
            bot.tap_dlg(pick[0], pick[1], wait=1.7)
        it2 = _items(bot)
        l2, _c2, p2 = _btn(it2)
        if not (l2 and ('选择' in l2 or '领取' in l2)):
            # 按钮读不到 → 多半是详情面板盖住了，点空白处关掉再读一次
            bot.tap_dlg(*VAULT['blank'], wait=1.6)
            it2 = _items(bot)
            l2, _c2, p2 = _btn(it2)
        at = p2 if (l2 and ('选择' in l2 or '领取' in l2)) else pos
        bot.tap_dlg(at[0], at[1], wait=2.6)
        log.append({'vault': 'claim', 'ring': ring, 'pick': pick, 'name': name,
                    'btn': l2, 'at': at})
        acts.append('claim%d' % ring)
        # ③ 收起奖励展示 —— ⭐ v0.97：**必须收干净**才允许进下一圈，
        #   否则下一圈又会去点「购买」（= 用户报的「选择后不点返回就直接点购买」✗）
        if _dismiss(bot, log):
            _dismiss(bot, log)
            if _reward_showing(_items(bot)):
                log.append({'vault': 'stuck_reward_after_claim', 'ring': ring})
                say('      · 宝库第 %d 层：奖励展示收不掉 ⇒ 本轮到此为止（不去点购买 ✓）' % ring)
                return acts
    # 收尾：返回 → 离开 → X
    _dismiss(bot, log)
    it = _items(bot)
    label, _c, pos = _btn(it)
    if label and '离开' in label:
        bot.tap_dlg(pos[0], pos[1], wait=2.4)
        log.append({'vault': 'leave'})
    it = _items(bot)
    if _present(bot, it):
        bot.tap_dlg(*VAULT['x'], wait=2.0)
        log.append({'vault': 'x_close'})
    _confirm(bot, log, 'vault_after')
    log.append({'vault': 'done', 'acts': acts})
    return acts


def ensure_closed(bot, log):
    """兜底：把还开着的面板 X 掉（只认 x≈493 / x≈1024 的真关闭符）"""
    closed = 0
    for _ in range(3):
        it = _items(bot)
        x = None
        for t in it:
            if t['text'].strip() in ('X', 'x', '\u00d7', '\u2715', '\u2716') and \
                    min(abs(t['cx'] - 493), abs(t['cx'] - 1024)) <= 80:
                x = t
                break
        if not x:
            break
        bot.tap_dlg(x['cx'], x['cy'], wait=1.8)
        closed += 1
    if closed:
        log.append({'ensure_closed': closed})
    return closed
