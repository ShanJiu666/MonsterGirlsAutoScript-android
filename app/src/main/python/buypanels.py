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

# ⭐⭐ v1.37 坐标说明（2026-10-02 真机 OCR 实测，Redmi 25053RT47C / 1280×2772）：
#   `MERCHANT` 里的坐标**只是离线对拍/兜底**，**真机一律走 OCR 定位** ✗
#   —— 面板是**弹窗系**（锚设备屏幕中心），y 会随分辨率整体漂移
#      （1280×2772 实测 shift=496.4；写死的 1255 在真机上压根对不上）✗
#   —— 真机 OCR 实测（**原帧坐标**）：右下角「购买」cx=1061 cy=1771；
#      四个档位下方是「已购买」**状态标签**（cx=257/513/769/1024 cy=1615），
#      **不是按钮** ⇒ 购买入口**只有右下角那一个**，靠"再点一次买下一档"推进 ✓
MERCHANT = {'title': '旅行商人', 'x': (983, 602), 'buy': (895, 1255),
            'back': (539, 1212), 'times': 4}



def _stopped():
    """⏹ 停止位（与 guild_daily._stopped 同一实现，见那里的长注释）"""
    try:
        import sys as _sys
        _el = _sys.modules.get("explore_loop")
        if _el is not None and getattr(_el, "_ANDROID_STOP", False):
            return True
    except Exception:       # noqa: BLE001
        pass
    return False


def _sleep(b, sec):
    """可被「停止」中断的 sleep —— 与 guild_daily._sleep 同一实现（见那里的长注释）"""
    try:
        b._sleep(sec)
        return
    except Exception:       # noqa: BLE001
        pass
    time.sleep(sec)
def _merchant_buy_btn(bot, log, i):
    """⭐ v1.37：找右下角那个「购买」钮（**OCR 定位，绝不写死** ✓）

    ⚠ 为什么不能写死：面板是**弹窗系**（锚设备中心）⇒ 同一份代码在
      1280×2772 / 1264×2780 / 1216×2688 上 y 差好几百像素
      （真机实测写死的 1255 对不上真实的 1771）✗
    ⇒ OCR 出来的坐标是**参考系**，再走 `tap_dlg` 换算到设备 ⇒ 全分辨率成立 ✓

    ⭐⭐ v1.38 修「商人一次都没买就显示买完」—— 选钮选错，点到**说明文字**上：
      真机 v1.37 日志（Redmi/广袤草原）OCR 读到的是
        `['4档','3档','2档','1档','购买','※依次在四个档位购买包罗万象的奖励内容']`
      ⇒ 老代码「含'购买'且不含'已购买'」会同时命中 **`购买`** 和
        **`※依次…购买…`**（**说明文字**，在面板左下角）⇒ 排序后选中了说明文字那行
      ⇒ 实际点到 `(345, 1337)`（x=345 明显不是右下角）⇒ **一下都没买成** ✗
      （我上一版注释写"真机只有右下角一个购买"—— 那是照着**全已购买**的截图下的结论；
        **面板还有 4 档可买时，档位行会各带一个「购买」** ⇒ 结论不成立 ✗）
    ⇒ 现在**三重过滤**：
      ① 排除「已购买」  ② 排除说明文字（含「依次/※/奖励内容/包罗万象」等）
      ③ 仍取**最靠右下**的（右下角总钮是 x 最大那个 ⇒ 真机 1061 vs 说明 443 ✓）
    """
    it = _items(bot)
    cands = []
    for t in it:
        tx = t['text'].strip()
        if '购买' not in tx or '已购买' in tx:
            continue
        # ⭐ v1.38：排除**说明文字**（它也含"购买"二字，但不是按钮 ✗）
        # ⚠ v1.39 补词：真机 OCR 会把说明句**截断**（实测同一条被读成
        #   「※依次在四个档位购买包罗万象的奖励内容」**和**「依次在四个档位购买包罗」两种）
        #   ⇒ 只靠「奖励内容/包罗万象」会漏判 ⇒ **以「依次」为锚**（说明句必有），
        #   再叠加「※ / 每档 / 包罗 / 万象 / 奖励」等碎片词兜底 ✓
        if any(w in tx for w in ('依次', '※', '每档', '奖励', '包罗', '万象',
                                 '包罗万象', '四叶草')):
            continue
        cands.append(t)
    if not cands:
        return None, it
    # 取**最靠右下**的那个（cx 大、cy 大）⇒ 档位行的钮 x 小、右下角总钮 x 大 ✓
    cands.sort(key=lambda t: (t['cy'], t['cx']))
    return cands[-1], it


def _merchant_bought_count(it):
    """⭐ v1.37：这局面板**已购买**的档位数（数「已购买」标签 ✓）

    真机 OCR 实测：每买一档，该档下方就多一个「已购买」标签
    （cx=257/513/769/1024 cy=1615）⇒ **数标签个数**就知道买了几档 ✓
    """
    n = 0
    for t in it:
        if '已购买' in t['text']:
            n += 1
    return n


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


# ⭐ v1.20：上界由 1560 放宽到 **1720**（锚定模型推导，不是目测放宽）
#   BAND 是**归一化帧**的 OCR 搜索带（归一化帧恒 1080×1920），而面板内容
#   **锚设备屏幕中心** ⇒ 同一元素在归一化系里的位置 = dlg_y − C，
#   而 C = 960 + (shift − H/2)/kx 随分辨率变（9:16 ⇒ 0，真机 1264×2780 ⇒ 227.7）。
#     · C > 0（长屏，H > 1920·kx）⇒ 元素在归一化系里**上移** ⇒ 旧 300 下界够用 ✓
#     · C < 0（**宽屏矮胖**，H < 1920·kx，如 1200×1920 的 5:4）⇒ 元素**下移** ⇒ 旧 1560 盖不住：
#         购买钮 dlg 1498 ⇒ 归一化 **1594**、价格 1541 ⇒ **1637** ⇒ 全部 OCR 不到
#         ⇒ `_btn` 恒返回 (None,None,None) ⇒ `no_select_btn` ⇒ **整层不买不选** ✗
#           （与 v1.19 摇色子同族：搜索带写死在 9:16 上，换分辨率静默失效）
#   ⇒ 下界 300 保留（再往上是被 toRef 丢掉的弹性区，取不到），
#     上界 1720 覆盖最坏情况（1200×1920 ⇒ 1637，留 ~83px 余量给文案行数浮动）。
#   ⚠ 这条断言已固化进回归 ㉝ 组（`tools/verify_panel_band_allres.py` × 9 分辨率）
#   ⚠ PC 上 C 恒 0 ⇒ 本改动对 PC **行为零影响**（band 上界只放宽不收紧）
BAND = (300, 1720)      # 归一化帧里要 OCR 的 y 段 ⇒ 弹窗系 (300+C, 1720+C)


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


def _confirm(bot, log, tag='', wait_rounds=6, wait_sec=0.7):
    """处理可能的确认/奖励弹窗：只点「确定」，绝不点「取消」

    v2.62 fix "tapped price but no confirm dialog":
      Old code did ONE OCR then returned False (measured only ~0.7s),
      but the dialog has an open animation -> not drawn yet -> always no dialog.
      Now: poll up to wait_rounds x wait_sec (~4.2s), invalidating the frame
      cache each round (Bot.ocr caches per frame stamp).

    v2.62 also relaxes the predicate:
      - strip spaces before compare (OCR may read with spaces)
      - cy threshold 800 -> 600 (measured button at dlg 1169 / ref 960;
        600 still excludes HUD rows cy<300)
    """
    for _rd in range(1, wait_rounds + 1):
        if _rd > 1:
            try:
                _invalidate(bot)
            except Exception:       # noqa: BLE001
                pass
            try:
                _sleep(bot, wait_sec)
            except Exception:       # noqa: BLE001
                try:
                    time.sleep(wait_sec)
                except Exception:   # noqa: BLE001
                    pass
        it = _items(bot)
        ok = None
        for t in it:
            _s = str(t.get('text') or '').replace(' ', '').strip()
            if _s == '确定' and (t.get('cy') or 0) > 600:
                ok = t
                break
        if ok is None:
            continue
        bot.tap_dlg(ok['cx'], ok['cy'], wait=2.0)
        log.append({'buy_confirm': tag, 'at': (ok['cx'], ok['cy']), 'round': _rd})
        return True
    if log is not None:
        log.append({'buy_confirm': 'not_found', 'tag': tag, 'rounds': wait_rounds})
    return False

def merchant_flow(bot, log):
    """旅行商人：点右下角「购买」→ 逐档推进 → 认到"全买完"就停（2026-10-02 真机重写）

    ⭐⭐ v1.37 重写原因（用户 2026-10-02 真机报「第一次只买了三个格子，第二次又打开买第四格」）：
      旧版**盲点 4 次同一个写死坐标**、靠循环次数记账 ⇒
        ① 某次点击落空（面板在买后会动，`返回` 坐标在 1212/1267 间跳就是证据）
           ⇒ 4 次点击只买成 3 档，却记 `bought=4` ✗
        ② 下轮面板只剩 1 档可买，又盲点 4 次 ⇒ 3 次落空 ✗
        ③ **完全不看「已购买」标签**（真机 OCR 明明读到了 3 个「已购买」）✗
      ⇒ 现在**每买一档都重新 OCR 验证**：数「已购买」标签数，没增加就说明这次没买成 ⇒ 停 ✓
    ⚠ 坐标一律 **OCR 定位 + tap_dlg 换算**（弹窗系），不写死 ✓
    """
    bought = 0
    for i in range(MERCHANT['times']):
        it = _items(bot)
        if _has(it, '金币不足', '钻石不足'):
            log.append({'merchant': 'no_money', 'i': i})
            break
        # ⭐⭐ v1.39【已经在奖励页 ⇒ 先退回商店，不能在这页找购买钮】
        #   真机 v1.38：买完一档后面板变「恭喜获得」奖励页，那页**也有「购买」二字**
        #   （在「依次在四个档位购买包罗」的说明句里）⇒ 旧代码点到了它 ⇒ 完全没买成 ✗
        if _has(it, '恭喜获得'):
            _b0 = _has(it, '返回')
            _a0 = (_b0['cx'], _b0['cy']) if _b0 else MERCHANT['back']
            bot.tap_dlg(_a0[0], _a0[1], wait=1.6)
            log.append({'merchant': 'back_to_shop', 'i': i, 'at': _a0})
            it = _items(bot)
        # ⭐ 先数已买了几档（真机口径：数「已购买」标签 ✓）
        n_bought = _merchant_bought_count(it)
        if n_bought >= MERCHANT['times']:
            log.append({'merchant': 'all_bought', 'i': i, 'bought': n_bought})
            break
        btn, it = _merchant_buy_btn(bot, log, i)
        if btn is None:
            # ⭐ v1.37：`i == 0` 也**必须**停（旧版 `not buy and i > 0` 把第 0 次排除了
            #   ⇒ 第 0 次没得买也照点，空转还记 bought=1 ✗）
            log.append({'merchant': 'no_buy_btn', 'i': i,
                        'texts': [t['text'] for t in it][:12]})
            break
        bot.tap_dlg(btn['cx'], btn['cy'], wait=2.0)
        _confirm(bot, log, 'merchant%d' % i)
        it = _items(bot)
        # ⭐⭐ v1.39【买成功的判据要认「恭喜获得」，不能只数「已购买」】——
        #   真机 v1.38 铁证：第一次点击**确实买成了**（弹出「恭喜获得」奖励页），
        #   可我的验证是数「已购买」标签 ⇒ **奖励页上根本没有这个标签** ⇒ 读成 0
        #   ⇒ `n_before=0 → n_after=0` ⇒ 误判 `tap_no_effect` ⇒ **只买1次就收手** ✗✗
        #   （用户目击：「旅行商人只买了一次就显示购买完成」）
        #   ⇒ 现在**两个信号任一**都算买成：① 弹出「恭喜获得」奖励页  ② 「已购买」标签 +1 ✓
        _got_page = bool(_has(it, '恭喜获得', '恭喜', '获得'))
        n_after = _merchant_bought_count(it)
        _ok = _got_page or (n_after > n_bought)
        log.append({'merchant': 'bought' if _ok else 'tap_no_effect',
                    'i': i, 'btn': (btn['cx'], btn['cy']),
                    'n_before': n_bought, 'n_after': n_after,
                    'got_page': _got_page})
        if not _ok:
            # ⚠ 点了没生效（面板在动 / 金币不够 / 弹窗挡住）⇒ **不重复点**，
            #   再点同一处大概率还是落空（真机实测落空率很高 ✗）⇒ 收手 ✓
            log.append({'merchant': 'stop_no_effect', 'i': i, 'n_bought': n_bought})
            break
        # ⭐ v1.39：买成了要**按实际买到的档数 +1**（奖励页上读不到标签 ⇒ 不能用 n_after）
        bought = n_after if n_after > n_bought else bought + 1
        # ⭐⭐ v1.39【奖励页只点**一次**返回，直接进入下一轮】——
        #   奖励页的「返回」= 回**商店**；商店的「返回」= **关掉面板**。
        #   旧逻辑在"买完后"还要点一次商店的返回 ⇒ **连点两次** ⇒ 第二次把面板关了，
        #   后面 3 档全买不了 ✗（2026-10-02 实跑日志里就出现这个形状）
        #   ⇒ 走奖励页这条路时，点完返回就 `continue`（下一轮开头会重 OCR 商店面板）✓
        if _got_page:
            _back = _has(it, '返回')
            _at = (_back['cx'], _back['cy']) if _back else MERCHANT['back']
            bot.tap_dlg(_at[0], _at[1], wait=1.6)
            log.append({'merchant': 'back_from_got', 'i': i, 'at': _at,
                        'note': '只点这一次返回回商店；下一轮再买（别再点商店返回 ✗）'})
            continue
        back = _has(it, '返回')
        at = (back['cx'], back['cy']) if back else MERCHANT['back']
        bot.tap_dlg(at[0], at[1], wait=1.6)
    # ⭐ 商人面板 X **文字优先**（× / X / 关闭），读不到才用 MERCHANT['x'] 兜底 ✓
    _mx = _find_text_btn(bot, ('×', 'X', 'x', '✕', '✖', '关闭'))
    if _mx:
        bot.tap_dlg(_mx[0], _mx[1], wait=2.0)
        log.append({'merchant': 'close_x', 'at': [_mx[0], _mx[1]], 'src': 'ocr'})
    else:
        bot.tap_dlg(*MERCHANT['x'], wait=2.0)
        log.append({'merchant': 'close_x', 'at': list(MERCHANT['x']),
                    'src': 'anchor_fallback'})
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


def _vault_lattice(x, y, tol=0.62):
    """(x, y) → 宝库 5×5 的 (行, 列)（**0 基**）；**不在点阵上** ⇒ None

    ⚠ 用途：挡掉"长得像格子但不是格子"的东西 —— 真机实测右下角「选择奖励/购买」按钮
      (895,1521) 同样是高饱和彩色块，会被 `_tile_mask` 检成奖励格 ✗
      按钮的行号 = (1521−746)/144 = **5.38**（点阵只有 0~4）⇒ None ⇒ 剔掉 ✓
    ⚠ 容差 0.62 个格距：真机上网格整体比常数低 ~50px（= 0.35 格），仍能对上 ✓
    """
    p = float(VAULT['pitch'] or 144)
    fc = (x - VAULT['gx0']) / p
    fr = (y - VAULT['gy0']) / p
    c, r = int(round(fc)), int(round(fr))
    if not (0 <= c <= 4 and 0 <= r <= 4):
        return None
    if abs(fc - c) > tol or abs(fr - r) > tol:
        return None
    return r, c


def _vault_rc(x, y):
    """检测到的奖励格 → 宝库 5×5 里的 (行, 列)（**0 基**）

    ⚠ 用"最近的理论格"判：真机上网格常比常数 `gy0` 低 ~50px（面板高度随文案变），
      但 `50 < 半格距(72)` ⇒ 最近邻判行列**免疫整体位移** ✓（实测 800→行0 / 942→行1 /
      1085→行2 / 1231→行3 / 1378→行4，逐个对得上 ✓）
    """
    p = float(VAULT['pitch'] or 144)
    c = int(round((x - VAULT['gx0']) / p))
    r = int(round((y - VAULT['gy0']) / p))
    return max(0, min(4, r)), max(0, min(4, c))


def tile_ring(x, y):
    """该格属于第几圈：**1 外圈 / 2 中圈 / 3 核心**（切比雪夫距中心 ✓，与 `vault_ring` 同口径）"""
    r, c = _vault_rc(x, y)
    d = max(abs(r - 2), abs(c - 2))
    return {0: 3, 1: 2, 2: 1}.get(d, 1)


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
        # ⭐⭐⭐ 2026-10-01 v1.09 修**真机 bug**（用户报「**宝库又选不了奖励了**」）：
        #   v0.98 把 `cells` 直接换成"检测到的**全部**彩色格" ⇒ **圈层约束丢了** ✗
        #   真机铁证（logcat）：ring 1/2/3 三次 `pick` **全是同一个格 (540,1089)**（= 正中心），
        #   而游戏只允许选**当前那一圈**（源码 `RefreshDefaultSelectingIndex` 按 currentLevel
        #   定 `selectingIndex`；非本圈的选择 `OnFuncButtonClicked` 直接 return）
        #   ⇒ 点正中心在 1/2 圈 = 空操作 ⇒ 用户看到的就是**选不了奖励** ✗✗
        #   ⇒ 现在按检测格自己的 5×5 行列算圈层，**只留本圈**；本圈一个都没检出才退回理论圈 ✓
        _ring_cells = [p for p in cells if tile_ring(p[0], p[1]) == level]
        if _ring_cells:
            log.append({'vault': 'ring_filter', 'level': level, 'all': len(cells),
                        'ring': len(_ring_cells)})
            cells = _ring_cells
        else:
            log.append({'vault': 'ring_filter_fallback', 'level': level, 'all': len(cells)})
            cells = vault_ring(level)[:max_probe]
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
            # ⭐⭐⭐ 2026-10-01 v1.09 修**按钮被当成奖励格**（真机 logcat 实证）：
            #   右下角那颗「选择奖励/购买」按钮 (895,1521) 同样是**高饱和彩色块**
            #   ⇒ 被 `_tile_mask` 检出、尺寸也刚好落在 100~185 里 ⇒ 混进 cells ✗
            #   后果：`vault_pick` 可能返回**按钮自己的坐标**（真机 ring1 的 pick 就是
            #   (895,1525)）⇒ 点它 = 点按钮、但当时**一个格子都没选** ⇒ 选不了奖励 ✗✗
            #   ⇒ 用**宝库 5×5 点阵**过滤：按钮的行号是 5.41（点阵只有 0~4）⇒ 剔掉 ✓
            if _vault_lattice(int(round(cent[i][0])), int(round(cent[i][1]))) is None:
                continue
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
        # ⭐ 宝库 X **文字优先**，读不到才用 VAULT['x'] 兜底 ✓
        _vx = _find_text_btn(bot, ('×', 'X', 'x', '✕', '✖', '关闭'))
        if _vx:
            bot.tap_dlg(_vx[0], _vx[1], wait=2.0)
        else:
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


# ══════════════════════════════════════════════════════════════════════════════
# ⭐ v1.78【从 PC 端移植：五个特殊地块面板流程】
#   PC 源码位置（**PC 仓只读、未改动**）：mapbot_pc/buypanels.py
#     · 勇者之墓 relic_flow        @2256（PC）
#     · 限时礼包 gift_flow         @2376（PC）
#     · 预言石碑 foretell_flow     @2508（PC）
#     · 金属/机巧宝箱怪 mimic_flow @2974（PC）
#     · 传承祭坛 shrine_flow       @3142（PC）
#   ⚠ 移植口径（**不是照抄**，理由逐条写在各常量旁）：
#     ① **坐标不用 PC 的 720 系，一律换算到手机的 1080×1920 弹窗系**
#        —— PC 那份是 720×1280 设备系（经 _s() 折算过），直接搬来会整体错位 ✗
#        两端同为 9:16 ⇒ **纯等比 ×1.5**。交叉验证：PC 宝库返回 (359,827) ×1.5
#        = (539,1241)，而手机端实测 VAULT_BACK_ZONE = (539,1240) ⇒ **只差 1px** ✓
#     ② 全部走 bot.tap_dlg()（弹窗系）+ _items()（已含 dlg_items 换算）
#     ③ OCR 找按钮的路径**保留**（PC 硬教训：结果框位置随文案行数变，写死就点空 ✗）
#     ④ 手机端没有 RapidOCR（端侧是 Kotlin OcrEngine、固定 0.75 倍口径）
#        ⇒ 宝箱怪那个「放大 3 倍再 OCR」改走 _ocr() 吃临时 PNG（与 read_qty 同款 ✓）
# ══════════════════════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────────────────────────
# ⭐ v1.78【同帧缓存 + 点击作废代理 —— 从 PC 移植】
#   PC 原文（为什么需要它）：
#     bot.ocr() 在 PC 上用 b.img() = **上一次 snap() 的缓存帧**，**不会自己重抓**。
#     凡是「轮询看画面有没有变」的循环，**每轮都必须先 b.snap()**，
#     而「点了一下 ⇒ 画面已经变了」时，**之前那份 OCR 结果必须作废** ——
#     否则下一步读到的是**点击前**的画面 ⇒ 判据全错 ✗
#     （PC 踩过三次：start_fight / _tap_verified / claim_back_poll）
#
# ⚠ 手机端口径差异（**如实写清**）：
#   手机端 Bot.ocr() 走 api.ocrJson **自己抓当前帧**（ocr_grabs=True）⇒
#   `_items()` 里那句 `if not ocr_grabs: snap()` **不会执行**（省掉一次 snap ✓）
#   ⇒ 这里的「作废」在手机上是**语义占位**：真正保证新鲜度的是 frameStamp 缓存
#     （Bot.ocr 的 _ocr_cache 按帧戳失效 ✅）。保留这套代理是**为了 PC 对拍与门禁一致**，
#     且它**没有任何副作用**（只是点完后丢弃一份 dict 里的引用）✓
#   ⛔ 别因为「手机上用不到」就删掉：PC 那份 `_items()` 还会被门禁按 PC 口径驱动
#      （`MAPBOT_ROOT` 指向 PC 仓时 C=0），删了就对不上了 ✗
def _cache_of(bot):
    """每台 bot 一份 OCР 缓存槽（挂在 bot 上，天然多开隔离 ✓）"""
    c = getattr(bot, '_bp_cache', None)
    if c is None:
        c = {'luma': None, 'items': None}
        try:
            bot._bp_cache = c
        except Exception:                                   # noqa: BLE001
            pass
    return c


def _invalidate(bot=None):
    """作废「同一帧的 OCR 结果」—— **点完/截图后必须调** ✓"""
    if bot is not None:
        try:
            _cache_of(bot)['items'] = None
        except Exception:                                   # noqa: BLE001
            pass
        return
    for _c in (_CACHE,):
        _c['items'] = None
        _c['luma'] = None


_CACHE = {'items': None, 'luma': None}


class _TapProxy(object):
    """包一层 Bot：**每次 tap/tap_dlg/snap 都自动作废 OCR 缓存** ✓

    ⚠ 用 object.__setattr__/__getattribute__ —— 不能走普通属性，
      否则 `self._b = bot` 会被自己的 `__getattr__` 绕进去（无限递归 ✗）
    """

    def __init__(self, bot):
        object.__setattr__(self, '_b', bot)

    def __getattr__(self, k):                             # 其余属性原样转发
        return getattr(object.__getattribute__(self, '_b'), k)

    def tap_dlg(self, *a, **kw):
        _invalidate(object.__getattribute__(self, '_b'))
        return object.__getattribute__(self, '_b').tap_dlg(*a, **kw)

    def tap(self, *a, **kw):
        _invalidate(object.__getattribute__(self, '_b'))
        return object.__getattribute__(self, '_b').tap(*a, **kw)

    def snap(self, *a, **kw):
        _invalidate(object.__getattribute__(self, '_b'))
        return object.__getattribute__(self, '_b').snap(*a, **kw)


def _proxy(bot):
    """把 Bot 包成 `_TapProxy`（**幂等**：已经包过就原样返回 ✓）"""
    if getattr(bot, '_bp_proxied', False):
        return bot
    try:
        bot._bp_proxied = True
    except Exception:                                       # noqa: BLE001
        pass
    return _TapProxy(bot)

# 万能关闭点（= explore_loop.UNIVERSAL_CLOSE；PC 的 720 值 (361,1260) ×1.5）✓
# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐⭐ v1.78【本文件坐标策略：**文字优先 → 坐标兜底**，全分辨率可用】
# ══════════════════════════════════════════════════════════════════════════
#   ---- 为什么会有"写死坐标"，为什么它仍然全分辨率可用 ----
#     手机端有 `RefMapper`：`tap()` 走「顶块锚顶 + 其余锚底」，`tap_dlg()` 走「弹窗锚屏幕中心」。
#     两者都把 **1080×1920 参考系常量**换算成设备像素 ⇒ 常量**不是设备像素**，
#     换分辨率时是**纯平移（+微缩放）**，不是重新标定 ✓
#     （`tools/audit_hardcoded_coords.py` 把这类叫 `ref` / `dlg`，只有 `devpx` 才是"换分辨率必错"）
#
#   ---- 那为什么还要"文字优先" ----
#     RefMapper 只保证**几何**自适应；面板的**文案行数**会变 ⇒ 同一颗按钮的 y 会漂
#     （PC 记过：「事件成功后的确认不是固定位置」「结果框的返回随文案行数变高变矮」）
#     而 OCR 读到的是**这一帧的真实位置** ⇒ 永远比常量准 ✓
#     ⇒ 本文件口径：**能 OCR 到文字的一律先 OCR**，常量只做兜底。
#
#   ---- 剩下这 6 处为什么可以保留（逐条，别以为是漏改）----
#     ① `MERCHANT["x"]` / `VAULT["x"]`：**在 `else:` 分支里** —— 上面已经先 `_find_text_btn`
#        找过 ×/X/关闭，找不到才走这里 ⇒ 这就是兜底本身 ✓
#     ② `VAULT["blank"]`（2 处）：「点面板内**安全空白**收起详情」—— 空白处**没有文字可认**，
#        本质就是坐标操作。且它经 `_vault_tap()` 的**面板安全矩形夹取**（把坐标夹进
#        panel x[49,670] y[238,1038]）⇒ **结构性保证点不出去** ✓
#     ③ `VAULT["buy"]`：同样在兜底分支（`if not (label and 选择/领取)`），
#        正常路径点的是 `_btn(it)` 从 OCR 读到的按钮 ✓
#     ④ `UNIV_CLOSE`：**万能关闭位**是用户明确指定的兜底（「点中间最下面可以关闭几乎所有
#        弹窗」「那边点了非常安全」）⇒ 它本身就是"兜底"语义；且 `_univ_close` 已改成
#        **先按文字找按钮、找不到才用它** ✓
#
#   ⚠ 想再加新面板？**先写 OCR 判据，坐标只作 fallback**，并在 `tools/panel_consts.py`
#     登记常量（登记即契约，漏登记 `scan_unregistered()` 会红 ✓）
# ══════════════════════════════════════════════════════════════════════════
UNIV_CLOSE = (541, 1890)


# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐⭐ v2.53【面板收尾：不再用「标题在归一化帧可见」当闸门】
# ══════════════════════════════════════════════════════════════════════════
#   用户 2026-10-26：「怎么现在连 boss 格子都打不了，点开就限时被面板挡住了」
#
#   ---- 病根（读代码即可证）----
#     手机端 `RefMapper.toRef()` 会**丢掉屏幕弹性区**，而**所有面板标题都在那个丢带里**
#     ⇒ 任何「标题可见」的判据在真机**恒 False**
#     ⇒ 而 6 个面板流程的收尾都写着 `if _has(_items(b), 标题): _univ_close(...)`
#        ⇒ **面板永远关不掉** ⇒ 残留面板盖住棋盘
#        ⇒ **后面的格子（boss/商人/…）点不动**（点击落在面板上）✗✗
#     ⇒ 手机端自己的注释早就写过这句（v0.32 那次）：
#        「任何 `_has(it, 标题)` 的判据在真机上是**恒 False** 的」
#
#   ---- 修法 ----
#     ① `panel_still_open()`：**弹窗帧**判（`ocr_dlg`）—— 弹窗帧只裁屏幕中心，
#        **面板标题在里面看得见** ⇒ 这个判据在真机是**真的** ✓
#        （PC / 9:16 无弹窗帧 ⇒ 退回原来的归一化帧标题判据，行为不变 ✓）
#     ② `close_panel()`：**确认面板还开着才动手**（绝不盲点万能点位到棋盘上）
#        顺序：X 关闭符 → 文字按钮（返回/确定/关闭）→ 万能点位
def panel_still_open(bot, title=None):
    """面板**是否还开着** —— 用**弹窗帧**判（标题在归一化帧的丢弃带里，真机恒不可见 ✗）"""
    try:
        _C = dlg_shift()
    except Exception:       # noqa: BLE001
        _C = 0
    if _C and hasattr(bot, 'ocr_dlg'):
        try:
            _dl = list(bot.ocr_dlg(min_conf=0.3, tag='panel_open') or [])
        except Exception:       # noqa: BLE001
            _dl = []
        if _dl:
            # 面板级按钮 = 「返回/关闭/取消」⇒ 面板（或结果框）确实开着 ✓
            _panelish = any((t.get('text') or '').strip() in ('返回', '关闭', '取消')
                            for t in _dl)
            if title:
                _titles = (title,) if isinstance(title, str) else tuple(title)
                if any(any(t in (x.get('text') or '') for x in _dl)
                       for t in _titles):
                    return True
                # 标题没匹配上，但**有面板级按钮**也算开着（结果框换了一层）
                return _panelish
            return _panelish
        # 弹窗帧一条都没读到（OCR 失败）⇒ 退回归一化帧标题判据（保守）
    if title:
        try:
            return _has(_items(bot), title)
        except Exception:       # noqa: BLE001
            return False
    return False


def close_panel(bot, log=None, tag='panel', title=None):
    """**保证把面板关掉**（不依赖标题在归一化帧里可见）✓

    ⚠ 只在**确认面板还开着**时才动手 ⇒ 绝不在棋盘上盲点万能点位 ✓
    """
    try:
        if not panel_still_open(bot, title):
            return 0
    except Exception:       # noqa: BLE001
        return 0
    n = 0
    try:
        n += int(ensure_closed(bot, log) or 0)
    except Exception:       # noqa: BLE001
        pass
    if not n:
        try:
            if _univ_close(bot, log, tag, items=_items(bot)):
                n += 1
        except Exception:       # noqa: BLE001
            pass
    if log is not None:
        log.append({tag: 'close_panel', 'n': n, 'title': title})
    return n

def _univ_close(bot, log, what='', wait=1.6, items=None):
    """关面板：**先认文字按钮 → 再退万能点位** ✓

    ⚠ 万能点位（`UNIV_CLOSE`）是**设计上的固定兜底**（用户口径：「点击中间最下面就可以
      关闭几乎所有弹窗」+「那边点了非常安全，不会有变化」）⇒ 它本身就是"兜底"语义，
      不是我这里图省事写死的坐标 ✓
    ⭐ 但既然调用方通常**手上就有这一帧的 items**，那就先按文字找
      「返回 / 确定 / 关闭 / × 」—— 认到就点它（更准），认不到才用万能点位 ✓
      （传 `items=None` ⇒ 行为与 PC 完全一致，向后兼容 ✓）
    """
    try:
        if items:
            _hit = None
            for _t in items:
                _s = str(_t.get('text') or '').strip().replace(' ', '')
                if _s in ('返回', '确定', '关闭', '×', 'X', 'x', '✕', '✖'):
                    _hit = _t
                    break
            if _hit is not None:
                bot.tap_dlg(int(_hit['cx']), int(_hit['cy']), wait=wait)
                log.append({'close': 'by_text', 'text': _hit.get('text'),
                            'at': (int(_hit['cx']), int(_hit['cy'])), 'what': what})
                return True
        # v2.59: **不再盲点 UNIV_CLOSE**。
        #   UNIV_CLOSE=(541,1890) 走 tap_dlg 换算到真机是 **设备 y≈2488 = 棋盘内**
        #   （弹窗锚屏幕中心：1386+(1890-960)*1.1852），盲点它就是点一个棋盘格
        #   ⇒ 揭格/开面板/白花体力，且 caller 以为"已关面板"⇒ 判据连锁错 ✗✗
        #   认不到文字按钮 ⇒ **如实返回 False**，交给上层判"没关掉"✓
        log.append({'close': 'no_text_btn', 'what': what,
                    'note': '认不到返回/确定/关闭 ⇒ **不盲点**（万能位在本机落在棋盘内）'})
        return False
    except Exception:       # noqa: BLE001
        return False


# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐⭐ v2.52【模态框「确定/确认」按钮 —— **纯 OCR 识别，不写死坐标**】
# ══════════════════════════════════════════════════════════════════════════
#   用户口径（2026-10-26）：
#     「点了勇者之墓，最后的确认弹窗没有识别点击」
#     「不要用固定坐标啊。要识别确认按钮并点击」
#     「安卓端要的是全分辨率啊，不用死坐标，用图片识别等方法点击」
#
#   ---- 为什么**不能**用固定坐标 ----
#     · PC 原文教训：「**事件成功后的确认不是固定位置**」
#       （面板上那个「确定」与结果框那个「确定」差近 200px；
#         结果框的「返回」还随**文案行数/奖励条目数**变高变矮）
#     · 真机实测（2026-10-26 / Redmi 1280×2772 探索地图，**离线复刻端侧 OCR**，
#       同一套 PP-OCRv4 onnx 模型，参考帧 1080×1920）：
#         '事件成功' (540,642) conf=0.997
#         '你获得了勇者的认可。' (528,766) conf=0.994
#         '获得[无色神石]×1' (539,847) conf=0.978
#         **'确定' (539,1002) conf=0.9998**
#       ⇒ 端侧 OCR **完全认得到**「确定」；它在参考系 y=1002（弹窗系 1211、
#         设备像素 1683），**位置随文案行数浮动** ⇒ 只能现场认，不能写死 ✓
#
#   ---- 为什么优先用**弹窗帧**（`ocr_dlg`）而不是归一化帧 ----
#     弹窗帧 = `RefMapper.toDlg()`：把**屏幕中心**裁成 1080×1920（弹窗系坐标）
#     ⇒ ① 模态框自己的按钮一定在里面
#        ② 底层面板的同名「确定」更靠下 ⇒ 可用「离结果标题最近」挑对
#        ③ **不需要写死 y 带**（旧代码的 840~1350 就是硬写的，文案一变就失效 ✗）
#
#   ---- 返回 ----
#     (x, y, src)：src ∈ {'dlg','ref'}
#       'dlg' ⇒ **弹窗系**坐标 ⇒ 必须 `tap_dlg()` 点
#       'ref' ⇒ **参考系**坐标 ⇒ 用 `tap()` 点
#     找不到 ⇒ None
def find_modal_confirm(bot, near_cy=None, words=('确定', '确认', '返回')):
    """在**当前模态框**里找「确定/确认」按钮 —— **纯 OCR，不写死坐标** ✓

    `near_cy`（**弹窗系**）：结果标题的 y ⇒ 按钮就在它下面 ⇒ 取最近的那个 ✓
    """
    b = _proxy(bot)
    # ① 弹窗帧（弹窗系坐标）—— 模态框自己的按钮 ⇒ 不会被底层面板混淆 ✓
    try:
        _C = dlg_shift()
    except Exception:       # noqa: BLE001
        _C = 0
    if _C and hasattr(b, 'ocr_dlg'):
        try:
            _dl = list(b.ocr_dlg(min_conf=0.3, tag='modal_ok') or [])
        except Exception:       # noqa: BLE001
            _dl = []
        _cands = [t for t in _dl
                  if (t.get('text') or '').strip() in words]
        if _cands:
            if near_cy is not None:
                _below = [t for t in _cands if (t.get('cy') or 0) >= near_cy - 40]
                _pick = min(_below or _cands,
                            key=lambda t: abs((t.get('cy') or 0) - near_cy))
            else:
                _pick = _cands[0]
            return (int(_pick['cx']), int(_pick['cy']), 'dlg')
    # ② 归一化帧（参考系坐标）兜底
    try:
        _it = list(b.ocr(min_conf=0.3, tag='modal_ok_ref') or [])
    except Exception:       # noqa: BLE001
        _it = []
    for t in _it:
        if (t.get('text') or '').strip() in words:
            return (int(t['cx']), int(t['cy']), 'ref')
    return None

def _find_text_btn(bot, texts, ymin=0, ymax=1920):
    """OCR 找**某个按钮文字**的真实坐标（**不写死** —— 结果框位置会变）

    ⚠ PC 真机教训（原话）：「**事件成功后的确认不是固定位置**」
      · 面板上的「确定」与结果框的「确定」**差近 200px**（720 系）
      · 结果框的「返回」随**文案行数/奖励条目数**变高变矮
    ⇒ 凡是"结果框/奖励框"里的按钮，**必须每帧 OCR 找** ✓
    """
    if isinstance(texts, str):
        texts = (texts,)
    _best = None
    try:
        it = _items(bot)
    except Exception:       # noqa: BLE001
        return None
    for t in it:
        s = (t.get('text') or '').strip()
        if s not in texts:
            continue
        cy = t.get('cy') or 0
        if not (ymin <= cy <= ymax):
            continue
        score = abs(cy - (ymin + ymax) / 2)
        if _best is None or score < _best[0]:
            _best = (score, t['cx'], t['cy'], s)
    if _best is None:
        return None
    return (_best[1], _best[2], _best[3])


def _tap_text_btn(bot, log, texts, fallback=None, ymin=0, ymax=1920, tag='', wait=2.0):
    """点一个"文字按钮"：**优先 OCR 找**，找不到才用 fallback（写死坐标）

    -> (x, y, src)；src = 'ocr' | 'fallback' | None
    """
    p = _find_text_btn(bot, texts, ymin, ymax)
    if p:
        bot.tap_dlg(p[0], p[1], wait=wait)
        log.append({tag: 'tap_text', 'text': p[2], 'at': [p[0], p[1]], 'src': 'ocr'})
        return (p[0], p[1], 'ocr')
    if fallback:
        bot.tap_dlg(fallback[0], fallback[1], wait=wait)
        log.append({tag: 'tap_text', 'text': str(texts), 'at': list(fallback),
                    'src': 'fallback'})
        return (fallback[0], fallback[1], 'fallback')
    log.append({tag: 'tap_text_none', 'text': str(texts)})
    return (None, None, None)


def _ocr_zoom_file(bot, y0, y1, scale, tag):
    """把当前**弹窗帧**的 y 带裁出来放大 scale 倍再 OCR -> [(cx, text, cy, conf)]

    ⚠ 为什么要放大（PC 原话）：「价格数字太小，整屏 OCR 漏检」
      · PC 实测整屏只读到 2/4 个价格；**放大 3 倍后 4 个全读到** ✓
    ⚠ 端侧 Bot.ocr(img=…) 那条路会把图当**整帧**（缩放 + 贴黑底）⇒ 坐标全错 ✗
      ⇒ 必须走 _ocr() 直吃临时 PNG（与 read_qty 同款 ✓），并把坐标 ÷scale 反算回来 ✓
    """
    import cv2
    from mapbot import _ocr
    try:
        img = bot.img_dlg()
    except Exception:       # noqa: BLE001
        return []
    if img is None or getattr(img, 'size', 0) == 0:
        return []
    band = img[max(0, int(y0)):int(y1), :]
    if band.size == 0:
        return []
    big = cv2.resize(band, None, fx=float(scale), fy=float(scale),
                     interpolation=cv2.INTER_CUBIC)
    tmp = _qty_tmp_path().replace('_qty.png', '_zoom_%s.png' % str(tag))
    try:
        cv2.imencode('.png', big)[1].tofile(tmp)
    except Exception:       # noqa: BLE001
        return []
    try:
        res, _sec = _ocr()(tmp)
    except Exception:       # noqa: BLE001
        return []
    out = []
    for it in (res or []):
        try:
            box, txt, conf = it[0], it[1], float(it[2])
        except Exception:       # noqa: BLE001
            continue
        xs = [q[0] for q in box]
        ys = [q[1] for q in box]
        out.append((int(sum(xs) / 4.0 / scale),
                    str(txt),
                    int(sum(ys) / 4.0 / scale) + int(y0),
                    conf))
    return out

# ──────────────────────────────────────────────────────────────────────────────
# ① 勇者之墓（SpecialSpot=3）→ 面板标题「**英灵使者**」
#    PC 实测：**零成本**（不花钱不花体力），三行任选 → 确定 → 事件成功 + 奖励
#    用户口径（PC 记录的原文）：「**三行都能点，优先点成功率100%的**」
# ──────────────────────────────────────────────────────────────────────────────
RELIC = {
    'title': '英灵使者',
    # v2.64：**全部换成真机实测值**（弹窗系）
    #   旧值是 PC 720 系 ×1.5 推算的，实测全部错位：
    #     旧 rows 落点 dev y = 1215/1446/1678，而真行在 dev y ≈ 947/1139/1333（弹窗系）
    #     旧 ok  落点 dev y = 1955，而「确定」实在 dev y = 2012（差 57px）
    #   ⚠ 这些只是**兜底**（正常路径走 OCR 找到的坐标）
    'rows': [(766, 947), (766, 1139), (767, 1333)],   # 三栏「成功率 N%」文字中心
    'ok': (690, 1488),          # 「确定」按钮中心（实测 conf 1.000）
    'must': (392, 1488),        # 「必定成功」（不该点，仅供诊断）
    'close_x': (983, 453),      # 右上关闭 X
}
# 「成功率 N%」文字的行 y（PC 720 系 593/722/851 ×1.5）—— 把成功率**归到行** ✓
RELIC_SUCC_Y = {890: 0, 1083: 1, 1277: 2}
RELIC_SUCC_TOL = 21             # PC 容差 14 ×1.5
RELIC_WAIT_ROUNDS = 4           # 结果框「确定」最多找几轮
RELIC_WAIT_SEC = 0.8            # 每轮间隔（秒）


def _relic_result_title_cy(bot):
    """结果框的**标题行** y（弹窗系）—— 用来挑「离标题最近」的那个确定按钮 ✓

    标题词：事件成功 / 事件大成功 / 事件失败 / 恭喜获得
    """
    try:
        _dl = list(bot.ocr_dlg(min_conf=0.3, tag='relic_title') or [])
    except Exception:       # noqa: BLE001
        return None
    best = None
    for t in _dl:
        s = (t.get('text') or '').strip()
        if any(w in s for w in ('事件成功', '事件大成功', '事件失败', '恭喜获得')):
            cy = t.get('cy') or 0
            if best is None or cy < best:
                best = cy
    return best

def _relic_close_result(bot, log=None):
    """**带重试**点掉勇者之墓的「结果框」-> (x, y) 或 None

    ⚠ PC 真机事故（原话教训）：「**勇者之墓不能用万能点位关，得点击确认按钮**」
      · 结果框**正在弹出动画中**时，一次性 OCR 读不到「确定」⇒ 万能点位**对它无效** ✗
      ⇒ 每轮**重新取帧 + OCR**，找到「确定/返回」就点 ✓；4 轮都找不到 ⇒ 返回 None
        （**如实报没点掉**，不假装成功 ✓）
    ⚠ 「确定」有**两个位置** ⇒ 搜索带必须**只框结果框那一段**（PC 560~900 ⇒ 手机
      840~1350；面板上那个在 1440 ⇒ 排除掉 ✓）
    """
    for rd in range(1, RELIC_WAIT_ROUNDS + 1):
        if rd > 1:
            try:
                _sleep(bot, RELIC_WAIT_SEC)
            except Exception:       # noqa: BLE001
                pass
        try:
            _invalidate(bot)
        except Exception:           # noqa: BLE001
            pass
        # ⭐⭐⭐ v2.52：不再用**写死的 y 带**（840~1350）——
        #   「事件成功后的确认不是固定位置」（PC 原文），且结果框按钮会随
        #   **文案行数/奖励条目数**变高变矮 ⇒ 写死必失效 ✗
        #   ⇒ 改成**弹窗帧 OCR 现场认**「确定/确认」，并用「离结果标题最近」挑对 ✓
        _near = _relic_result_title_cy(bot)
        p = find_modal_confirm(bot, near_cy=_near, words=('确定', '确认', '返回'))
        if p:
            if p[2] == 'dlg':
                bot.tap_dlg(p[0], p[1], wait=2.0)
            else:
                bot.tap(p[0], p[1], wait=2.0)
            if log is not None:
                log.append({'relic': 'close_result', 'at': [p[0], p[1]],
                            'text': '确定/确认', 'round': rd, 'src': p[2],
                            'near_cy': _near})
            return (p[0], p[1])
    if log is not None:
        log.append({'relic': 'close_result_fail', 'rounds': RELIC_WAIT_ROUNDS})
    return None


def _relic_panel_like(it):
    """勇者之墓面板的**稳定特征**判据（不依赖读不到的标题）

    v2.63（真机实测 2026-10-27）：
      面板标题「英灵使者」在归一化帧里**读不到**（丢弃带）
      ⇒ 只能靠结构特征认面板

    实测 OCR（真正的勇者之墓面板，参考帧 1080x1920）：
      「这些都是历代勇者遗留下来的宝物」（说明文案）
      **「成功率90%」「成功率100%」** x3（三栏）← ★ 这是它**独有**的
      「必定成功」「确定」（底部两个按钮）

    ⚠⚠ 不能用「N级 + 筛选」当判据！（我第一版就是这么错的）
      实测：背包的**装备列表**也是「N级x16 + 筛选x1」，但**成功率=0**
      ⇒ 用那个判据会把**背包误判成勇者之墓** ✗✗

    判据（两条都要）：
      ① 至少 2 个「成功率 N%」（OCR 实测 3/3 全中）
      ② 至少 1 个「必定成功」或「勇者」
    """
    try:
        _n_succ = 0
        _n_hero = 0
        for _t in (it or []):
            _s = str(_t.get('text') or '').replace(' ', '')
            if '成功率' in _s:
                _n_succ += 1
            if '勇者' in _s or '必定成功' in _s:
                _n_hero += 1
        return _n_succ >= 2 and _n_hero >= 1
    except Exception:       # noqa: BLE001
        return False


def relic_flow(bot, log):
    """勇者之墓「英灵使者」：**三选一，零成本** -> acts（空 = 没走完）

    ⚠ 面板存在性判据用**标题**（_has(it, 英灵使者)）而不是方块名「勇者之墓」——
      图上是「勇者之墓」、面板上写「英灵使者」，两者不同名（PC SPECIAL_ALIAS 记着）✓
    ⚠ 只认「成功率 100%」的行；**读不到任何 100% ⇒ 用默认第 1 行**（PC 同口径 ✓）
      理由：不点 = 停在面板上 ⇒ 整盘被盖住 ⇒ 白跑一轮，比选错一行代价大得多
    """
    acts = []
    b = _proxy(bot)
    it = _items(b)
    # v2.63: 标题读不到时靠结构特征兜底（与传承祭均同口径）
    if not (_has(it, RELIC['title']) or _relic_panel_like(it)):
        log.append({'relic': 'panel_missing',
                    'texts': [(t.get('text') or '')[:12] for t in (it or [])][:12]})
        return acts

    # v2.63 CRITICAL: 不能用写死的 RELIC_SUCC_Y 归行!
    #   实测（真机 2026-10-27，弹窗系）：
    #     行0 成功率90%  dlg y=947   旧期望 890  差 +57
    #     行1 成功率100% dlg y=1139  旧期望 1083 差 +56
    #     行2 成功率100% dlg y=1333  旧期望 1277 差 +56
    #   容差只有 21 ⇒ **三行一行都归不进** ⇒ succ 恒空
    #   ⇒ 永远选「默认行1」= 成功率 90% 那行 ✗✗
    #   ⇒ 改成**按 y 排序取索引**（不依赖任何绝对 y，换分辨率/版式都成立 ✓）
    _succ_list = []
    for t in it:
        s = (t.get('text') or '').replace(' ', '')
        if '成功率' not in s:
            continue
        _succ_list.append((int(t.get('cy') or 0),
                          ('100%' in s or '100％' in s), s, t))
    _succ_list.sort(key=lambda x: x[0])       # 按 y 从上到下
    succ = {i: (v[1], v[2]) for i, v in enumerate(_succ_list)}
    log.append({'relic': 'succ', 'rows': {str(k): v[1] for k, v in sorted(succ.items())},
                'ys': [v[0] for v in _succ_list]})

    # ② 选行：**第一个 100%** 的行；都没有 ⇒ 行 1（默认已选中）
    pick = None
    for r in (0, 1, 2):
        if succ.get(r, (False,))[0]:
            pick = r
            break
    if pick is None:
        pick = 0
        say('      · 勇者之墓：读不到 100%% 的行 ⇒ 用默认（行1）【%s】' % (succ,))
    else:
        say('      · 勇者之墓：选第 %d 行（成功率 100%%）' % (pick + 1))
    # v2.63：**点哪一行用实测 OCR 坐标**（不再反查写死的 RELIC_SUCC_Y）
    #   「成功率 N%」那条 OCR 的 (cx,cy) 就是那一行的实际位置
    #   ⇒ 直接点它（PC 记过：行 y 会随文案行数变 ✗）
    _row_item = None
    if 0 <= pick < len(_succ_list):
        _row_item = _succ_list[pick][3]      # 第 4 个元素是 OCR 条目
    if _row_item is not None:
        _rx, _ry = int(_row_item['cx']), int(_row_item['cy'])
        b.tap_dlg(_rx, _ry, wait=1.6)
        log.append({'relic': 'pick_row', 'row': pick + 1, 'at': [_rx, _ry],
                    'src': 'succ_ocr'})
    else:
        log.append({'relic': 'pick_row_skipped', 'row': pick + 1,
                    'note': '读不到任何「成功率」条目 ⇒ 不盲点（行1 本来就是默认选中）'})
    acts.append('pick%d' % (pick + 1))

    # ③ 点「确定」——**优先 OCR**，找不到才用标定坐标 ✓
    # v2.63：只用 OCR找到的「确定」（实测 dlg 1489）；
    #   找不到就多轮重试（面板有弹出动画），不盲点写死坐标 ✗
    p = None
    for _try in range(4):
        if _try > 0:
            try:
                _sleep(b, 0.6)
                _invalidate(b)
            except Exception:       # noqa: BLE001
                pass
        p = _find_text_btn(b, ('确定',))
        if p:
            break
    at = (p[0], p[1]) if p else RELIC['ok']
    b.tap_dlg(at[0], at[1], wait=2.6)
    log.append({'relic': 'ok', 'at': list(at), 'src': 'ocr' if p else 'fallback'})
    acts.append('ok')

    # ④ 读结果（只记日志，不影响流程 ✓）
    it2 = _items(b)
    txts = [(t.get('text') or '') for t in it2]
    joined = ' '.join(txts)
    ok = ('事件成功' in joined) or ('事件大成功' in joined) or ('获得了勇者的认可' in joined)
    fail = '没能获得' in joined
    big = '事件大成功' in joined
    reward = [t for t in txts if '获得[' in t or '获得【' in t]
    has_ok_btn = _find_text_btn(b, ('确定', '返回'), 840, 1590) is not None
    log.append({'relic': 'result', 'ok': bool(ok), 'big': bool(big),
                'fail': bool(fail), 'btn': bool(has_ok_btn), 'reward': reward[:4]})
    say('      · 勇者之墓结果：%s%s'
        % ('★★大成功' if big else ('★成功 ✓' if ok else
                                  ('✗失败' if fail else '？未读到文案')),
           ('  奖励=%s' % reward[:2]) if reward else ''))

    # ⑤ 关结果框（**带重试**）；关不掉就**如实记**，不假装 ✓
    if has_ok_btn or ok or fail or big:
        p2 = _relic_close_result(b, log)
        if p2:
            acts.append('close_result')
        else:
            say('      · ⚠ %d 轮都没找到「确定」⇒ **结果框可能还开着**（如实记录，不冒充已关）'
                % RELIC_WAIT_ROUNDS)
    # ⑥ 收尾：面板还在 ⇒ 万能点位（PC 口径：三个新面板都吃这一下 ✓）
    # v2.53：不靠「标题在归一化帧可见」⇒ 用**弹窗帧**判面板是否还开着
    close_panel(b, log, 'relic_tail', title=RELIC['title'])
    log.append({'relic': 'done', 'acts': acts})
    return acts

# ──────────────────────────────────────────────────────────────────────────────
# ② 限时礼包（SpecialSpot=5）→ 面板标题「**限时超值礼包**」
#    用户口径（PC 原文）：「**720 分辨率下第一个免费按钮是固定坐标，只点最上面那个免费按钮**」
#    ⇒ 只领第 1 档（免费）；第 2 档要 6 幸运草、第 3 档用户说不点 ⇒ **都不碰** ✓
# ──────────────────────────────────────────────────────────────────────────────
GIFT = {
    'title': '限时超值礼包',
    'free1': (770, 791),        # 第 1 档「免费」（PC (513,527) ×1.5）⇒ **只点这个** ✓
    'free3': (770, 1260),       # 第 3 档「免费」（PC (513,840) ×1.5）—— **不点**
    'paid2': (770, 1028),       # 第 2 档「6 草」（PC (513,685) ×1.5）—— **不点**
    'result_back': (540, 1211),  # 结果框「返回」（PC (360,807) ×1.5；仍优先 OCR 找）
}


def gift_flow(bot, log):
    """限时礼包「限时超值礼包」：**只点第 1 档免费** -> acts

    ⚠ 「恭喜获得」是**结果框**，不是面板标题 ⇒ 用它判领到了，用它里面的「返回」收尾 ✓
    """
    acts = []
    b = _proxy(bot)
    it = _items(b)
    if not _has(it, GIFT['title']):
        log.append({'gift': 'panel_missing',
                    'texts': [(t.get('text') or '')[:12] for t in (it or [])][:12]})
        return acts

    # ① 只点第 1 档（固定坐标 —— 用户口径明确说固定坐标 ✓）
    # ⚠ 用户口径是「**720 分辨率下第一个免费按钮是固定坐标，只点最上面那个**」
    #   ⇒ 固定坐标是**用户认可的**主路径。但既然能 OCR，就**先按文字找最上面那个「免费」**：
    #     认到 ⇒ 点它（更准）；认不到 ⇒ 才用 GIFT['free1']（PC ×1.5、过 RefMapper）✓
    _g1 = None
    # ⚠⚠⚠ v2.48 修（用户 2026-10-26「打开限时礼包后不点免费领了红宝石就关掉」）：
    #   旧判据是**精确等值** `text.strip() == "免费"`：
    #     OCR 实际读到的是「免费领取」「免费获得」「免费 」这类**带后缀**的文本
    #     ⇒ 精确等值**一个都匹配不到** ⇒ 走坐标兜底 GIFT["free1"]
    #     ⇒ 而那个坐标在这台机上不准（点到了红宝石按钮）⇒ 花宝石 + 关面板 ✗✗
    #   ⇒ 判据改成**包含「免费」且不含「宝石/钻石/购买」**（排除收费项），
    #     再取**最上面**那个（用户口径「只点最上面那个免费按钮」✓）。
    _FREE_BAD = ("宝石", "钻石", "购买", "¥", "元", "领取需")
    for _t in it:
        _tx = str(_t.get('text') or '').strip()
        if '免费' not in _tx:
            continue
        if any(_b in _tx for _b in _FREE_BAD):
            continue
        if _g1 is None or (_t.get('cy') or 0) < (_g1.get('cy') or 0):
            _g1 = _t
    # ⚠⚠⚠ v2.49【**认不到「免费」就绝不用坐标兜底**】（用户 2026-10-26）
    #   上一版即使认不到也点 GIFT["free1"]=(770,791)，而那个坐标在这台机上
    #   落在「红宝石」按钮上 ⇒ **白花宝石**、还顺手关掉面板 ✗✗
    #   用户口径是「只点最上面那个免费按钮」，从没说"认不到也要点"
    #   ⇒ **fail-safe 方向：认不到 ⇒ 一下都不点**（宁可少领一个免费礼包，
    #     也绝不误花宝石 ✓）。坐标兜底只保留给"有「免费」字样但位置拿不准"的场景。
    if _g1 is None:
        log.append({'gift': 'free_not_found',
                    'texts': [(t.get('text') or '')[:10] for t in (it or [])][:12],
                    'note': '没认出「免费」按钮 ⇒ 不点（防误点红宝石）'})
        say('      · 限时礼包：没认出「免费」按钮 ⇒ 跳过（不点，防花宝石）')
        # v2.53：**必须关掉**（否则残留面板盖住棋盘 ⇒ 后面格子全点不动 ✗）
        close_panel(b, log, 'gift_nofree', title=GIFT['title'])
        log.append({'gift': 'done', 'acts': acts})
        return acts
    _gx, _gy = int(_g1["cx"]), int(_g1["cy"])
    bot.tap_dlg(_gx, _gy, wait=2.4)
    log.append({'gift': 'tap_free1', 'at': [_gx, _gy], 'src': 'ocr_top_free'})
    acts.append('free1')

    # ② 读结果
    it2 = _items(b)
    txts = [(t.get('text') or '') for t in it2]
    joined = ' '.join(txts)
    got = '恭喜获得' in joined
    reward = [t for t in txts if t.strip() in ('货币', '道具', '装备')]
    log.append({'gift': 'result', 'got': bool(got), 'texts': txts[:8],
                'reward': reward[:4]})
    say('      · 限时礼包：%s' % ('★领到 ✓' if got else '（没看到恭喜获得，见日志）'))

    # ③ 收结果框（**优先 OCR** —— 结果框高度随奖励条目数变 ✓）
    if got:
        _tap_text_btn(b, log, ('返回', '确定'), fallback=GIFT['result_back'],
                      ymin=1050, ymax=1350, tag='gift', wait=2.0)
    close_panel(b, log, 'gift_tail', title=GIFT['title'])
    log.append({'gift': 'done', 'acts': acts})
    return acts


# ──────────────────────────────────────────────────────────────────────────────
# ③ 预言石碑（SpecialSpot=9）→ 面板标题「**预言石板**」
#    用户口径（PC 原文）：
#      「**优先选 地图中至少有1名敌人拥有<紫/橙>色位阶的掉宝加护这个加护。
#        其他就按品阶排，优先品质高的**」
#      「**这个预言（幸运）要加个按钮，是否停止脚本（类似出现红装标记）**」
#      「**地图中必定出现金属宝箱怪也要单独拿出来弄个选项，遇到那个是否立即停止脚本**」
#      「**预言石碑停止脚本加上橙色和紫色元素**」← 2026-10-09
# ──────────────────────────────────────────────────────────────────────────────
FORETELL = {
    'title': '预言石板',
    # PC 720 系 620 ⇒ 手机 930（三张卡的点击 y；x 由 OCR 标题给 ✓）
    # 卡片点击 y：实测卡身在 dlg 750~1150 ⇒ 取中心 900（旧值 930 也在范围内，但 900 更正）
    'cards_y': 900,
    # ⭐ v2.02 真机实测：'确定' 在 dlg(542,1390)；旧值 1332 差 58（点空）
    'ok': (542, 1390),          # 「确定」
    'PRIO_DROP': '掉宝',        # ① 最高优先级
    'PRIO_STOP': ('幸运', '和平', '元素'),   # ② 选了要停脚本的优先挑
}
FORETELL_NAMES = (
    '丰收', '藏宝', '武装', '命运', '秘藏', '神兵', '强敌', '路标', '元素',
    '掉宝', '奇遇', '勇者', '机遇', '宝库', '黄金', '传承', '魔法', '财富',
    '伏击', '幸运', '祥和', '圣域', '战场', '精灵', '和平', '奇观',
)
# ⛔⛔ v2.02【**真机实测：卡片标题 y 是 714，不是 659**】
#   ---- 病（用户报：「打开预言石碑不选择预言」）----
#     旧值 `659` 是 **PC 439 ×1.5** 推算的。真机实测（`fp.png` 逐条 OCR）：
#       `dlg(212,714) 秘藏` / `dlg(540,714) 藏宝` / `dlg(868,715) 强敌`
#     而 `_foretell_read_cards()` 的过滤窗是 `659-30 ~ 659+39` = **629~698**
#     ⇒ **三张卡全被过滤掉** ⇒ `cards=[]` ⇒ 走 `cards_timeout` 分支 ⇒
#        「等了 6 轮仍没读到卡片 ⇒ 不盲点，关面板」⇒ **一张都不选** ✗✗
#   ---- 修法 ----
#     标题 y 改 **714**（实测），窗口 `+30/-55` 覆盖「秘藏/强敌」轻微的 y 差 ✓
#   ⚠ 这个常量只用于**识别归属**（判断哪条文字是卡片标题），
#     不影响点击（点击用 `FORETELL["cards_y"]`）✓
# v2.76: 改成参考系基值 + 动态 C（不能写死弹窗系绝对值）
#   真机 1280x2772 ⇒ C=209，标题弹窗系 506+209=715 ✓ 匹配旧值 714
#   模拟 1280x2640 ⇒ C=154，标题弹窗系 506+154=660 ✗ 落在 684~769 外
#   ⇒ 三张卡全读不到 ⇒ cards_timeout ⇒ 一张都不选 ✗
FORETELL_CARD_Y_REF = 506       # 卡片标题的**参考系** y


def _foretell_card_y():
    """卡片标题在**当前弹窗系**的 y = 参考基值 + C"""
    try:
        return FORETELL_CARD_Y_REF + int(round(dlg_shift()))
    except Exception:
        return FORETELL_CARD_Y_REF + 209
FORETELL_CARD_Y_TOL_UP = 30     # 标题识别窗口：上容差
FORETELL_CARD_Y_TOL_DN = 55     # 标题识别窗口：下容差（实测强敌在 715，留余量）
FORETELL_WAIT_ROUNDS = 6        # 等卡片的最多轮数
FORETELL_WAIT_SEC = 0.8         # 每轮间隔（秒）

_FORETELL_VALUE_TIER = {
    '丰收': {100: 2, 200: 3, 300: 4, 500: 5},
    '藏宝': {100: 2, 200: 3, 300: 4, 500: 5},
    '武装': {100: 2, 200: 3, 300: 4, 500: 5},
    '命运': {5: 2, 10: 3, 15: 4, 20: 5},
}
_FORETELL_WORD_TIER = {'蓝': 2, '紫': 3, '橙': 4}
_FORETELL_FIXED_TIER = {
    '掉宝': 4, '宝库': 4, '圣域': 3, '战场': 3, '精灵': 3, '财富': 3,
    '黄金': 3, '传承': 5, '幸运': 5, '祥和': 2, '奇观': 2, '伏击': 4,
    '勇者': 2, '机遇': 2, '魔法': 5, '和平': 3, '强敌': 2, '元素': 2,
    '路标': 2, '秘藏': 2, '神兵': 2, '奇遇': 2,
}


def _foretell_tier(name, eff):
    """一张卡片的**品阶**（数字越大越好）—— 数据表 Foretell 三档 ＋ 数值档

    ⚠ 判据顺序（PC 同款，别调）：① 数值表（+N% / 至少为N点）② 色位阶词 ③ 名字固定表
      ⇒ 都读不到就用 **2**（**不猜高**：猜高会把垃圾卡排到最优 ✗）
    """
    import re as _re
    try:
        m = _re.search(r'\+(\d+)%', eff or '')
        if m and name in _FORETELL_VALUE_TIER:
            return _FORETELL_VALUE_TIER[name].get(int(m.group(1)), 2)
        m2 = _re.search(r'至少为(\d+)点', eff or '')
        if m2 and name in _FORETELL_VALUE_TIER:
            return _FORETELL_VALUE_TIER[name].get(int(m2.group(1)), 2)
        for w, tv in _FORETELL_WORD_TIER.items():
            if ('至少是%s' % w) in (eff or '') or ('%s色位阶' % w) in (eff or ''):
                return tv
        return _FORETELL_FIXED_TIER.get(name, 2)
    except Exception:       # noqa: BLE001
        return 2


def _foretell_read_cards(bot, log=None):
    """读面板上的三张卡（轮询等它们画出来）-> (cards, rounds)

    ⚠ 必须 _invalidate + 重新取帧（PC 原话：「**必须作废同帧缓存**，否则读到旧帧 ✗」）
      —— 卡片是**过动画才出来**的，第一帧常常只有面板底板 ✓
    """
    for rd in range(1, FORETELL_WAIT_ROUNDS + 1):
        if rd > 1:
            try:
                _sleep(bot, FORETELL_WAIT_SEC)
            except Exception:       # noqa: BLE001
                pass
        try:
            _invalidate(bot)
        except Exception:           # noqa: BLE001
            pass
        try:
            it = _items(bot)
        except Exception as _e:     # noqa: BLE001
            if log is not None:
                log.append({'foretell': 'cards_ocr_err', 'round': rd,
                            'e': repr(_e)[:80]})
            continue
        _cY = _foretell_card_y()   # v2.76 动态 C ⇒ 换分辨率也能认到卡牌
        cards = []
        for t in it:
            s = (t.get('text') or '').strip()
            cy = t.get('cy') or 0
            if s not in FORETELL_NAMES:
                continue
            # ⚠ 窗口用常量（方便现场调）—— 旧写法写死 `-30/+39`，
            #   配合错误的 659 ⇒ 整窗偏移 55px ⇒ **一张卡都认不到** ✗
            if not (_cY - FORETELL_CARD_Y_TOL_UP
                    <= cy
                    <= _cY + FORETELL_CARD_Y_TOL_DN):
                continue
            if any(c['name'] == s for c in cards):
                continue                        # 同帧重复
            cards.append({'name': s, 'x': t.get('cx'), 'y': FORETELL['cards_y']})
        if cards:
            cards.sort(key=lambda c: c['x'] or 0)
            # 每张卡的**效果文字**（卡片下方、同一列）⇒ 用来读位阶/数值 ✓
            for c in cards:
                eff = []
                for t in it:
                    s2 = (t.get('text') or '')
                    cy2 = t.get('cy') or 0
                    cx2 = t.get('cx') or 0
                    if cy2 <= 705 or cy2 > 1140:        # PC 470~760 ×1.5
                        continue
                    if abs(cx2 - (c['x'] or 0)) > 90:   # PC ±60 ×1.5
                        continue
                    eff.append(s2)
                c['eff'] = ' '.join(eff)
                c['tier'] = _foretell_tier(c['name'], c['eff'])
            if log is not None:
                log.append({'foretell': 'cards_ok', 'round': rd, 'n': len(cards),
                            'names': [c['name'] for c in cards]})
            return cards, rd
    return [], FORETELL_WAIT_ROUNDS


def foretell_flow(bot, log, flags=None):
    """预言石碑「预言石板」：选卡 → 点确定 → 拿预言；命中要停的卡 ⇒ **不选卡直接停**

    -> {'acts': [...], 'stop': None|'幸运'|'和平·金属宝箱怪'|'元素·紫色'|'元素·橙色',
        'picked': [卡名...]}

    ⭐⭐ 判停**提到点卡之前**（PC 原话：「判停提到点卡之前 => 面板保持原样 ✓」）
      ⇒ 抽到幸运/和平/元素 并且用户开关开着 ⇒ **一张卡都不点**、面板原样留着给人工处理 ✓
      （点了就等于替用户做了选择，还把面板关掉 ⇒ 现场没了 ✗）
    ⚠ 三个停开关**都由 GUI 传进来**（flags），默认 **开**（用户点名的就是要停下来）✓
    """
    out = {'acts': [], 'stop': None, 'picked': []}
    flags = flags or {}
    b = _proxy(bot)
    it = _items(b)
    if not _has(it, FORETELL['title']):
        log.append({'foretell': 'panel_missing',
                    'texts': [(t.get('text') or '')[:12] for t in (it or [])][:12]})
        return out

    # ① 本次可选几个（面板上写着「可选择N个」）
    import re as _re
    maxpick = 1
    for t in it:
        s = (t.get('text') or '').replace(' ', '')
        m = _re.search(r'可选择(\d+)个', s)
        if m:
            maxpick = max(1, int(m.group(1)))
            break
    log.append({'foretell': 'maxpick', 'n': maxpick})
    say('      · 预言石碑：本次可选 %d 个' % maxpick)

    # ② 读卡（等动画）
    cards, _rounds = _foretell_read_cards(b, log)
    if not cards:
        log.append({'foretell': 'cards_timeout', 'rounds': _rounds})
        say('      · ⚠ 等了 %d 轮仍没读到卡片 ⇒ 不盲点，关面板（下轮再来）' % _rounds)
        close_panel(b, log, 'foretell_nocards', title=FORETELL['title'])
        return out
    say('      · 读到 %d 张卡（第 %d 轮）' % (len(cards), _rounds))
    log.append({'foretell': 'cards', 'n': len(cards), 'round': _rounds,
                'cards': [{'n': c['name'], 'tier': c['tier'],
                           'eff': (c.get('eff') or '')[:28]} for c in cards]})

    # ③ 排序：掉宝 → 要停的（幸运/和平/元素）→ 按品阶
    def _key(c):
        blob = c['name'] + c['eff']
        if FORETELL['PRIO_DROP'] in blob:
            return (0, 0)
        if any(k in blob for k in FORETELL['PRIO_STOP']):
            return (1, 0)
        return (2, -c['tier'])
    cards.sort(key=_key)
    pick = cards[:maxpick]
    say('      · 选卡：%s' % '、'.join(c['name'] for c in pick))

    # ④ 判停（**在点卡之前**）
    _stop_why = None
    for _c in pick:
        _blob = _c['name'] + _c['eff']
        if '幸运' in _blob:
            _stop_why = '幸运'
            break
        if '和平' in _blob and '金属宝箱怪' in _blob:
            if bool(flags.get('stop_peace_metal', True)):
                _stop_why = '和平·金属宝箱怪'
            break
        if '元素' in _c['name']:
            _pf = bool(flags.get('stop_elem_purple', True))
            _of = bool(flags.get('stop_elem_orange', True))
            _tier11 = ('橙色' if '橙色' in _blob else
                       ('紫色' if '紫色' in _blob else
                        ('蓝色' if '蓝色' in _blob else '**未读到位阶词**')))
            log.append({'foretell': 'elem_tier', 'name': _c['name'],
                        'tier_word': _tier11, 'stop_purple': _pf,
                        'stop_orange': _of, 'eff': (_c.get('eff') or '')[:40]})
            if '橙色' in _blob and _of:
                _stop_why = '元素·橙色'
                break
            if '紫色' in _blob and _pf:
                _stop_why = '元素·紫色'
                break
    if _stop_why:
        out['stop'] = _stop_why
        out['picked'] = []              # ⭐ **一张都没点**（面板原样留着 ✓）
        out['acts'] = ['stop_before_pick']
        log.append({'foretell': 'stop_before_pick', 'why': _stop_why,
                    'cards': [c['name'] for c in cards],
                    'note': '判停提到点卡之前 => 面板保持原样 ✓'})
        say('      · ⚠ 抽到【%s】⇒ **立即停止**（**不选卡、不点确定**，面板原样留着）'
            % _stop_why)
        return out

    # ⑤ 点卡
    for c in pick:
        # ⚠ 卡片是**图形**，但卡片**标题**（丰收/掉宝/元素…）OCR 读得到，
        #   x 就取它的 cx；y 用 FORETELL['cards_y']（卡面中心）—— 已是最接近自适应的做法 ✓
        b.tap_dlg(c['x'], c['y'], wait=1.4)
        log.append({'foretell': 'pick', 'name': c['name'],
                    'at': [c['x'], c['y']], 'tier': c['tier']})
        out['picked'].append(c['name'])

    # ⑥ 点「确定」（优先 OCR；搜索带只框面板那个确定 ✓）
    p = _find_text_btn(b, ('确定',), 1230, 1440)
    at = (p[0], p[1]) if p else FORETELL['ok']
    b.tap_dlg(at[0], at[1], wait=2.2)
    log.append({'foretell': 'ok', 'at': list(at), 'src': 'ocr' if p else 'fallback'})
    out['acts'] = ['pick%d' % len(pick), 'ok']

    close_panel(b, log, 'foretell_tail', title=FORETELL['title'])
    log.append({'foretell': 'done', 'picked': out['picked'], 'stop': out['stop']})
    return out


# ──────────────────────────────────────────────────────────────────────────────
# ④ 金属宝箱怪 / 机巧宝箱怪（SpecialSpot=2）
#    用户口径（PC 原文，**权威**）：
#      「**一般只买 8 草的，宝箱怪默认不勾选，勾选就自动买 8 草的**」
#    ⚠ 价格表（游戏源码 GetCloverPrice(step) = 1 << (Step-1)）：C=1/B=2/A=4/**S=8**
#      （SS=16 但宝箱怪不出 SS ⇒ **8 就是最高档** ✓）
#    ⚠⚠ 购买是**两步**（PC 真机实测，第一版猜错过）：
#        点商品卡 ⇒ **弹详情页**（不是买）✗ ⇒ 点详情页**右下角价格按钮** ⇒ 才真买 ✓
#    ⚠ 「取消追踪」(PC 160,1053) 是**追踪功能**，不是取消购买 ✗ 别点错
# ──────────────────────────────────────────────────────────────────────────────
MIMIC_CARD_X = (191, 407, 623, 839)     # 四列商品卡中心（PC 720 系 ×1.5）
MIMIC_PRICE_X = (218, 435, 650, 867)    # 四列价格数字中心（放大 OCR 实测 ✓）
MIMIC_CARD_Y = 1013                     # 商品卡点击 y（PC 675 ×1.5）
MIMIC_PRICE_Y = 1095                    # 价格行 y（PC 730 ×1.5）
MIMIC_BUY_BTN = (879, 1580)             # 详情页右下角价格按钮（PC (586,1053) ×1.5）
MIMIC_BUY_Y_RANGE = (1245, 1665)        # 购买键 y 范围（PC 830~1110 ×1.5）
MIMIC_REFRESH = (897, 1230)             # 「刷新 1 草」—— **不点**（用户口径）✓
MIMIC_TARGET_PRICE = 8                  # ⭐ **只买 8 草的**
MIMIC_EQUIP_COL = 0                     # ⭐ **从左数第一个必定是装备**（用户口径）✓
MIMIC_OCR_SCALE = 3                     # 价格行放大倍数（放大才读得到左边两列 ✓）


def _mimic_read_prices(bot, log=None, rounds=5, sec=0.8):
    """读四列价格 -> ([(cx, 草数)...], rounds)

    ⚠ 两级（PC 同款）：① **放大 3 倍**再 OCR（整屏只读到 2/4 个 ⇒ 必须放大）
                     ② 放大失败 ⇒ 退回整帧 OCR 的纯数字条目
    """
    import re as _re
    for rd in range(1, rounds + 1):
        if rd > 1:
            _sleep(bot, sec)
        try:
            _invalidate(bot)
        except Exception:           # noqa: BLE001
            pass
        try:
            bot.snap('bp')
        except Exception:           # noqa: BLE001
            pass

        out = []
        # ① 放大 OCR（走 _ocr() 直吃临时 PNG —— 端侧 bot.ocr(img=) 会把带当整帧 ✗）
        try:
            _zoom = _ocr_zoom_file(bot, MIMIC_PRICE_Y - 50, MIMIC_PRICE_Y + 53,
                                   MIMIC_OCR_SCALE, 'mimic')
        except Exception as _e:     # noqa: BLE001
            _zoom = []
            if log is not None:
                log.append({'mimic': 'price_zoom_err', 'round': rd,
                            'e': repr(_e)[:70]})
        for (cx, txt, _cy, conf) in (_zoom or []):
            m = _re.fullmatch(r'#?(\d{1,2})', str(txt).strip())   # 放大后常读成 #8
            if not m:
                continue
            out.append((cx, int(m.group(1))))
        # ② 整帧兜底
        if not out:
            try:
                it = _items(bot)
            except Exception:       # noqa: BLE001
                it = []
            for t in it:
                s = (t.get('text') or '').strip()
                cy = t.get('cy') or 0
                if not _re.fullmatch(r'\d{1,2}', s):
                    continue
                if not (MIMIC_PRICE_Y - 39 <= cy <= MIMIC_PRICE_Y + 39):
                    continue
                out.append((t.get('cx') or 0, int(s)))
        if out:
            out.sort()
            if log is not None:
                log.append({'mimic': 'prices_ok', 'round': rd, 'prices': out,
                            'zoomed': bool(_zoom)})
            return out, rd
    return [], rounds


def _nearest_price_x(bot, card_x):
    """从**价格行 OCR** 反推这一列的中心 x（读不到返回 None）

    ⚠ 为什么不干脆点 MIMIC_CARD_X：那四个是 **PC 720 系 ×1.5** 的推算值，
      而价格数字是**每帧现读**的 ⇒ 用它反推列心，天然自适应 ✓
      （价格行与商品卡同列，实测 y 差 55 参考像素，x 基本一致 ✓）
    """
    try:
        prices, _r = _mimic_read_prices(bot, None, rounds=1, sec=0.0)
    except Exception:       # noqa: BLE001
        return None
    if not prices:
        return None
    try:
        _x, _v = min(prices, key=lambda t: abs(t[0] - card_x))
    except Exception:       # noqa: BLE001
        return None
    return int(_x) if abs(int(_x) - int(card_x)) <= 60 else None

def _mimic_buy_one(bot, log, card_x):
    """买**一件**：点卡 → 详情页 → 点右下角价格按钮 → 关结果框 -> bool

    ⚠ 两道不盲点闸门（PC 口径，都是踩过的）：
      · 详情页**没认出来** 且 **也没找到购买键** ⇒ **不点**（放弃这一件）
        —— 面板还没打开时点 (879,1580) 会落在棋盘上 = 乱点 ✗
      · 确定/返回 是**结果框**的按钮，**绝不当成购买键**（会白关一次结果框 ✗）
    """
    # ⚠ 商品卡是**美术格子**，但**价格数字 OCR 读得到**（`_mimic_read_prices` 已读）
    #   ⇒ 价格行的 cx 就是那一列的中心 ⇒ **优先点认到的那一列**，读不到才用 MIMIC_CARD_X ✓
    _px = _nearest_price_x(bot, card_x)
    _tx = _px if _px is not None else card_x
    bot.tap_dlg(_tx, MIMIC_CARD_Y, wait=2.0)
    log.append({'mimic': 'tap_card', 'x': _tx, 'y': MIMIC_CARD_Y,
                'src': 'price_ocr' if _px is not None else 'anchor_fallback'})

    det = _find_text_btn(bot, ('尚未拥有', '已拥有', '未拥有'), 300, 750)

    btn = None
    for rd in range(1, 4):
        if rd > 1:
            try:
                _sleep(bot, 0.7)
            except Exception:       # noqa: BLE001
                pass
            try:
                _invalidate(bot)
            except Exception:       # noqa: BLE001
                pass
        it = _items(bot)
        best = None
        for t in it:
            s = (t.get('text') or '').strip()
            cy = t.get('cy') or 0
            if s in ('确定', '返回'):
                continue                    # ⚠ 别把结果框按钮当购买键 ✗
            if s not in ('1', '2', '4', '8', '16', '免费'):
                continue
            if not (MIMIC_BUY_Y_RANGE[0] <= cy <= MIMIC_BUY_Y_RANGE[1]):
                continue
            if (t.get('cx') or 0) < 570:    # ⚠ 左边是「取消追踪」⇒ 排除 ✓（PC 380 ×1.5）
                continue
            best = (t.get('cx'), t.get('cy'), s)
            break
        if best:
            btn = best
            break
    if btn:
        at = (btn[0], btn[1])
        src = 'ocr'
    else:
        at = MIMIC_BUY_BTN
        src = 'fallback'
    log.append({'mimic': 'detail', 'has_detail': bool(det),
                'buy_at': list(at), 'src': src})
    if det is None and not btn:
        say('      · ⚠ 详情页没认出来、也没找到购买键 ⇒ **不盲点**（放弃这一件）')
        return False

    bot.tap_dlg(at[0], at[1], wait=2.4)
    log.append({'mimic': 'tap_buy', 'at': list(at)})

    # 关结果框（4 轮；关不掉**如实记**，但买是买到了 ✓）
    for rd in range(1, 5):
        if rd > 1:
            try:
                _sleep(bot, 0.8)
            except Exception:       # noqa: BLE001
                pass
            try:
                _invalidate(bot)
            except Exception:       # noqa: BLE001
                pass
        p = _find_text_btn(bot, ('返回', '确定'), 840, 1350)
        if p:
            bot.tap_dlg(p[0], p[1], wait=2.0)
            log.append({'mimic': 'close_reward', 'at': [p[0], p[1]],
                        'text': p[2], 'round': rd})
            return True
    log.append({'mimic': 'close_reward_fail'})
    return True         # 买是买到了；结果框没关掉**如实记**（不假装 ✓）


def mimic_flow(bot, log, flags=None):
    """金属/机巧宝箱怪：**只买第 1 列（装备）且只买 8 草**

    -> {'acts': [...], 'bought': [...], 'skip': None|'no_prices'|...}

    ⚠ 三条不买的出口（每条都关面板、都**算正常结束**，不是失败 ✓）：
        · 读不到价格 ⇒ 不盲点
        · 装备列价格 ≠ 8 ⇒ 不买（用户口径「只买 8 草的装备」）
        · 幸运草 < 8 ⇒ 不买（钱不够游戏会弹充值面板 ✗）
    ⚠ 幸运草读法走 explore_loop.clover_count（与摇色子闸门**同一份判据** ⇒ 不会两边漂移 ✓）
    """
    out = {'acts': [], 'bought': [], 'skip': None}
    b = _proxy(bot)

    prices, rounds = _mimic_read_prices(b, log)
    if not prices:
        log.append({'mimic': 'panel_missing_or_timeout', 'rounds': rounds})
        say('      · ⚠ 宝箱怪面板读不到商品/价格 ⇒ 不盲点、关面板（下轮再来）')
        close_panel(b, log, 'mimic_nopanel')
        out['skip'] = 'no_prices'
        return out
    say('      · 宝箱怪面板：%d 件商品，价格（x,草）= %s' % (len(prices), prices))

    eq_col = MIMIC_EQUIP_COL
    eq_x = MIMIC_CARD_X[eq_col]
    eq_price = None
    if prices:
        _px, _pv = min(prices, key=lambda t: abs(t[0] - eq_x))
        eq_price = _pv
    log.append({'mimic': 'equip_col', 'col': eq_col, 'card_x': eq_x,
                'price': eq_price, 'prices': prices, 'need': MIMIC_TARGET_PRICE})

    if eq_price != MIMIC_TARGET_PRICE:
        say('      · 装备列（第 %d 列）价格是 %s，不是 %d 草 ⇒ **不买**'
            % (eq_col + 1, eq_price, MIMIC_TARGET_PRICE))
        out['skip'] = 'equip_not_target_price'
        close_panel(b, log, 'mimic_price')
        return out
    say('      · 装备列（第 1 列 x=%d）= %d 草 ⇒ **买它**（只买装备 ✓）'
        % (eq_x, eq_price))

    # ⭐ 幸运草闸门（**与摇色子同一份判据**）
    try:
        import explore_loop as _EL
        clv = _EL.clover_count(_items(b))
    except Exception:       # noqa: BLE001
        clv = None
    log.append({'mimic': 'clover', 'now': clv, 'need': MIMIC_TARGET_PRICE})
    if clv is not None and clv < MIMIC_TARGET_PRICE:
        say('      · ⚠ 幸运草 %d < %d ⇒ **不买**（只关面板 ✓）'
            % (clv, MIMIC_TARGET_PRICE))
        out['skip'] = 'low_clover'
        close_panel(b, log, 'mimic_lowclover')
        return out

    if _mimic_buy_one(b, log, eq_x):
        out['bought'].append(eq_x)
        out['acts'].append('buy@%d' % eq_x)
        say('      · 买到一件（x=%d，%d 草）✓' % (eq_x, MIMIC_TARGET_PRICE))
    else:
        say('      · x=%d 这件没买成（见日志）' % eq_x)

    # 收尾：面板还在 ⇒ 万能点位 ✓
    close_panel(b, log, 'mimic_tail')
    log.append({'mimic': 'done', 'bought': out['bought'], 'acts': out['acts']})
    return out


# ──────────────────────────────────────────────────────────────────────────────
# ⑤ 传承祭坛（SpecialSpot=4）→ 面板标题「**传承祭坛**」
#    用户口径（PC 原文，2026-10-11）：
#      「**直接点右下角的三万买了就行**」
#      「**识别一下，是30000就买，不然不买**」
#    ⇒ 判据**只看右下角价格**：== 30000 就买（用默认选中的第 1 件），否则不买 ✓
#    ⚠ 与勇者之墓的区别：那边是**三选一奖励**；这边是**选自己的装备 + 花金币激活传承**
#    ⚠ 面板结构（PC 实采）：装备网格 3 行 × 6 列 = 18 件（**你已有的装备**，不是新商品 ✓）
# ──────────────────────────────────────────────────────────────────────────────
SHRINE_GX0 = 167            # 第 1 列中心（PC 111 ×1.5）
SHRINE_GY0 = 933            # 第 1 行中心（PC 622 ×1.5）
SHRINE_PITCH_X = 149        # 列距（PC 99 ×1.5）
SHRINE_PITCH_Y = 150        # 行距（PC 100 ×1.5）
SHRINE_ROWS = 3
SHRINE_COLS = 6
SHRINE_PRICE = 30000        # ⭐ **只买 30000 这档**（用户口径 ✓）
SHRINE_PRICE_XY = (902, 1362)    # 「30000」文字中心（PC (601,908) ×1.5 ✓）
SHRINE_BUY_XY = (891, 1364)      # 价格按钮**点击点**（PC (594,909) ×1.5）
SHRINE_X_XY = (942, 503)         # ✗ 关闭（PC (628,335) ×1.5）
SHRINE_FILTER_XY = (236, 1362)   # 「筛选」（**不点** —— 用户没说筛 ✓）
SHRINE_REFRESH_XY = (375, 1362)  # ↻ 刷新（**不点** ✓）
SHRINE_TITLE = '传承祭坛'


def shrine_cells():
    """18 个装备格的中心（3 行 × 6 列）—— 只用于诊断/门禁，流程用默认选中 ✓"""
    return [(SHRINE_GX0 + c * SHRINE_PITCH_X, SHRINE_GY0 + r * SHRINE_PITCH_Y)
            for r in range(SHRINE_ROWS) for c in range(SHRINE_COLS)]


def _shrine_price_xy(bot):
    """右下角那个价格数字的 (cx, cy)；读不到返回 (None, None)

    ⚠ 复用 `_shrine_price` 的同一条窗口判据（x >= 840、按 |cx-902| 取最近），
      只是这里要**坐标**而不是数值 ⇒ 不另立一套判据，避免两边漂移 ✗
    """
    try:
        # v2.60: same fix as _shrine_price -- compute the band, do not hardcode
        #   (SHRINE_PRICE_XY is DIALOG-frame; bot.ocr wants REFERENCE-frame).
        _c2 = 0
        try:
            _c2 = int(dlg_shift() or 0)
        except Exception:       # noqa: BLE001
            _c2 = 0
        _py2 = int(SHRINE_PRICE_XY[1]) - _c2
        its = bot.ocr(band=(max(0, _py2 - 130), min(1920, _py2 + 130)),
                      tag='shrine_price_xy')
    except Exception:       # noqa: BLE001
        return (None, None)
    cands = []
    for t in (its or []):
        s = str(t.get('text') or '').strip()
        cx = int(t.get('cx') or 0)
        cy = int(t.get('cy') or 0)
        if cx < 700:
            continue
        d = ''.join(ch for ch in s if ch.isdigit())
        if not d:
            continue
        if int(d) != SHRINE_PRICE:
            continue
        cands.append((abs(cx - SHRINE_PRICE_XY[0]), cx, cy))
    if not cands:
        return (None, None)
    cands.sort()
    return (int(cands[0][1]), int(cands[0][2]))

def _shrine_price(bot, log=None):
    """读右下角价格（OCR）-> int 或 None

    ⚠ 只认 x ≥ 840 的数字（PC 560 ×1.5）—— 左边「筛选/刷新」那片数字会干扰 ✓
    ⚠ 多个候选按 |cx − 902| 排序取最近的（价格就写在那个位置 ✓）
    """
    # v2.58: band was a hardcoded 120px strip (1305,1425) -> any layout drift
    #   made price unreadable -> price=None -> "not buying this round".
    #   Widen to the whole lower half and pick the number nearest the anchor.
    try:
        # v2.60: the band MUST be computed, not guessed.
        #   SHRINE_PRICE_XY is in the DIALOG frame (dlg y=1362).
        #   bot.ocr(band=...) expects REFERENCE-frame y => 1362 - C = 1153.
        #   The old band (1305,1425) was the dlg y used as ref y => missed it
        #   by ~150px => price=None => "not buying this round".
        _c = 0
        try:
            _c = int(dlg_shift() or 0)
        except Exception:       # noqa: BLE001
            _c = 0
        _py = int(SHRINE_PRICE_XY[1]) - _c
        _y0, _y1 = max(0, _py - 130), min(1920, _py + 130)
        its = bot.ocr(band=(_y0, _y1), tag='shrine_price')
    except Exception as e:      # noqa: BLE001
        if log is not None:
            log.append({'shrine': 'price_ocr_fail', 'e': repr(e)[:90]})
        return None
    cands = []
    for t in (its or []):
        s = str(t.get('text') or '').strip()
        cx = int(t.get('cx') or 0)
        if cx < 840:
            continue
        d = ''.join(ch for ch in s if ch.isdigit())
        if d:
            cands.append((abs(cx - SHRINE_PRICE_XY[0]), int(d), s, cx))
    out = None
    if cands:
        cands.sort()
        out = cands[0][1]
    if log is not None:
        log.append({'shrine': 'price_read', 'value': out, 'band': (_y0, _y1),
                    'cands': [(c[1], c[3]) for c in cands][:4]})
    return out


def _shrine_close(bot, log, wait=1.6):
    """关祭坛面板；**先确认它还在**（游戏买成功会自己 PopAllPopPanel ✓）"""
    try:
        _it = _items(bot)
    except Exception as e:      # noqa: BLE001
        log.append({'shrine': 'close_check_fail', 'e': repr(e)[:80]})
        return
    if not (_has(_it, SHRINE_TITLE) or _has(_it, '选择装备')):
        log.append({'shrine': 'already_closed', 'note': '面板已自己关（源码 PopAllPopPanel ✓）'})
        return
    try:
        # ⭐ 关闭符**文字优先**（× / X / 关闭），读不到才用 SHRINE_X_XY 兜底 ✓
        _hit = None
        for _t in (_it or []):
            if str(_t.get('text') or '').strip().replace(' ', '') in (
                    '×', 'X', 'x', '✕', '✖', '关闭'):
                _hit = _t
                break
        if _hit is not None:
            _ax, _ay = int(_hit['cx']), int(_hit['cy'])
            _asrc = 'ocr'
        else:
            _ax, _ay = SHRINE_X_XY
            _asrc = 'anchor_fallback'
        bot.tap_dlg(_ax, _ay, wait=wait)
        log.append({'shrine': 'close_x', 'at': [_ax, _ay], 'src': _asrc})
    except Exception as e:      # noqa: BLE001
        log.append({'shrine': 'close_x_fail', 'e': repr(e)[:80]})
    try:
        _it2 = _items(bot)
        # v2.53：关面板**不靠标题可见**（弹窗帧判）⇒ 面板真能关掉
        _closed = close_panel(bot, log, 'shrine_tail', title=SHRINE_TITLE)
        if not _closed:
            log.append({'shrine': 'close_ok', 'note': '面板已不在（无需关）'})
    except Exception as e:      # noqa: BLE001
        log.append({'shrine': 'close_verify_fail', 'e': repr(e)[:80]})
        try:
            close_panel(bot, log, 'shrine_tail2', title=SHRINE_TITLE)
        except Exception:       # noqa: BLE001
            pass


def shrine_flow(bot, log, flags=None):
    """传承祭坛：右下角是 **30000** 就买（默认选中的第 1 件），否则只关面板

    ⚠ 「点价格 ⇒ 弹**确认框** ⇒ 点确定才真买」（游戏源码）⇒ **没等到确认框 = 没买到**
      ⇒ 那种情况 bought=False 并记 no_confirm_dialog（**如实记账**，不冒充 ✓）
      最常见的原因是**金币不够**（源码：钱不够会弹充值面板 ✗）
    """
    out = {'acts': [], 'bought': False, 'skip': None}
    b = _proxy(bot)
    it = _items(b)
    _pl = [t.get('text') for t in (it or [])][:14]
    if not _has(it, SHRINE_TITLE):
        log.append({'shrine': 'panel_missing', 'texts': _pl})
        say('      · ⚠ 读不到「传承祭坛」标题 ⇒ 不盲点、关面板（下轮再来）')
        close_panel(b, log, 'shrine_nopanel', title=SHRINE_TITLE)
        out['skip'] = 'no_panel'
        return out

    price = _shrine_price(b, log)
    say('      · 传承祭坛面板：右下角价格 = %s（要 %d 才买）' % (price, SHRINE_PRICE))
    if price != SHRINE_PRICE:
        say('      · 价格不是 %d ⇒ **不买**（用户口径：是 %d 就买，不然不买 ✓）'
            % (SHRINE_PRICE, SHRINE_PRICE))
        out['skip'] = 'price_not_target'
        log.append({'shrine': 'skip', 'why': 'price_not_target', 'price': price})
        _shrine_close(b, log)
        return out

    log.append({'shrine': 'will_buy', 'at': list(SHRINE_BUY_XY), 'price': price})
    say('      · 价格 = %d ⇒ **买**（点右下角 %s）' % (price, str(SHRINE_BUY_XY)))
    try:
        # ⭐ **价格文字优先**：`_shrine_price` 已经把「30000」那颗 OCR 出来了，
        #   它的 cx/cy 就是按钮上的数字 ⇒ 点它比点 SHRINE_BUY_XY（PC ×1.5 推算）更准 ✓
        #   读不到才退回 SHRINE_BUY_XY（1080 参考系、过 RefMapper）✓
        # v2.61 FIX: _shrine_price_xy() returns REFERENCE-frame coords
        #   (from bot.ocr), but tap_dlg() expects DIALOG-frame.
        #   Measured: ref(903,1209) via tap() -> device y1929 OK;
        #   via tap_dlg() -> y1681, off by 248px => tap lands nowhere
        #   => no confirm dialog => bought=False.
        _sx, _sy = _shrine_price_xy(b)
        if _sx is None:
            b.tap_dlg(SHRINE_BUY_XY[0], SHRINE_BUY_XY[1], wait=2.0)
            _at, _src = tuple(SHRINE_BUY_XY), 'anchor_fallback'
        else:
            b.tap(_sx, _sy, wait=2.0)
            _at, _src = (_sx, _sy), 'price_ocr'
        log.append({'shrine': 'buy_at', 'at': _at, 'src': _src})
        out['acts'].append('buy@%s' % (_at,))
        out['bought'] = True
        say('      · 已点购买 ⇒ 等结果')
    except Exception as e:      # noqa: BLE001
        log.append({'shrine': 'buy_tap_fail', 'e': repr(e)[:90]})
        out['skip'] = 'tap_fail'
        return out

    _had_confirm = False
    try:
        _had_confirm = bool(_confirm(b, log, 'shrine_buy'))
    except Exception as _ce:    # noqa: BLE001
        log.append({'shrine': 'confirm_fail', 'e': repr(_ce)[:90]})
    log.append({'shrine': 'confirm_step', 'got': _had_confirm,
                'note': '源码：点价格 ⇒ 弹确认框 ⇒ 点「确定」才真买 ✓'})
    if out['bought'] and not _had_confirm:
        out['bought'] = False
        out['skip'] = 'no_confirm_dialog'
        say('      · ⚠ 点完价格**没等到确认框** ⇒ 多半金币不够（源码：钱不够弹充值）'
            '⇒ **不算买到**（如实记账 ✓）')

    _shrine_close(b, log)
    log.append({'shrine': 'done', 'bought': out['bought'], 'acts': out['acts']})
    return out


# ──────────────────────────────────────────────────────────────────────────────
# ⑥ 面板标题别名 → 规范方块名（PC SPECIAL_ALIAS 的等价物）
#   ⚠ 为什么单独一张表：同一个面板在**图上**和**面板标题**上叫不同名字，
#     而 popups() 里所有判据都是按名字比 ⇒ 不归一就必然漏 ✗
#     PC 踩的连环坑（原文）：
#       ① t not in act_on ⇒ 走无视支（盲点 X 关掉）✗
#       ② 只把「石碑」加进 act_on ⇒ 还是不算（t 是「石板」）✗
#       ③ elif '预言石碑' in t ⇒ 仍不匹配（**碑 ≠ 板**）⇒ 掉进 else
#          ⇒ **拿旅行商人流程去点预言面板** ⇒ 真机日志显示**买了 4 次** ✗✗✗
#   ⇒ 口径：alias → 规范名；规范名 = 数据表 Area_Spot.Name（= 图上那个名字 ✓）
#   ⚠ 新增别名时**只改这张表**（act_on / elif / special 都不用动）✓
# ──────────────────────────────────────────────────────────────────────────────
SPECIAL_ALIAS = {
    '预言石板': '预言石碑',      # 面板标题（真机 OCR conf=0.99）→ 方块名（数据表）
    '英灵使者': '勇者之墓',      # 面板标题（relic_panel 实测）→ 方块名
    '限时超值礼包': '限时礼包',   # 面板标题（gift_free1 实测）→ 方块名
}


def canon_name(t):
    """面板/地块名 → **规范方块名**（见 SPECIAL_ALIAS；不在表里 ⇒ 原样返回 ✓）"""
    s = str(t or '')
    for _al, _ca in SPECIAL_ALIAS.items():
        if _al in s:
            return _ca
    return s