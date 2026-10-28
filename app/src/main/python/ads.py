# -*- coding: utf-8 -*-
"""ads.py · **免广告领奖**（购买体力 / 四叶草 / 金币 ＋ 加速炼金）—— 从 PC 端移植 (v1.78)

PC 源：mapbot_pc/ads.py（687 行）

用户口径（PC 原文，一次说全）：
    「**开始做领取广告（默认有免广），只做每天1次的加速炼金，
      每天三次的购买体力，幸运草和金币，单独加个有无免广的勾选，
      有就自动做**」
补问确认（PC 主动问的，用户选项）：
    · 免广勾选语义 = 「**勾 = 有免广，未勾则不做**」✓
    · 体力次数 = 「**广告都是 3 次**」（不是花宝石那 5 次）✓

════════════════════════════════════════════════════════════════════
⭐ 整套体系（PC **从游戏源码挖出来的，不是猜的**）
════════════════════════════════════════════════════════════════════
SaveData.AdsType 枚举 **7 项**，配 MaxAdsDailyLimit = new int[7]{3,3,3,1,1,1,999999}
（**按枚举顺序一一对应**）：
    | # | AdsType        | 每日上限 | 本轮做不做 |
    |---|----------------|---------|-----------|
    | 0 | CloverSupply   |   **3** | ✅ 四叶草 |
    | 1 | GoldSupply     |   **3** | ✅ 金币   |
    | 2 | EnergySupply   |   **3** | ✅ 购买体力 |
    | 3 | AlchemyAccel   |   **1** | ✅ 加速炼金 |

⚠ 「免广告」= **月卡权益还有剩余天数** —— 源码 `SaveData.CanSkipAds()` 只有一行：
    `return GetMonthRightRemainDays().Any((int x) => x >= 0);`
  ⇒ 它**不是设置开关、是账号状态** ✓
  ⇒ 那颗勾选的语义 = **告诉脚本「这个号有免广」**，脚本据此决定做不做 ✓
⛔ **未勾 ⇒ 四个入口一下都不碰**（无免广时要**真播视频广告** ✗ 脚本做不了）

⭐⭐ 移植口径：
   · 坐标 ×1.5 换算（720×1280 ⇒ 1080×1920，9:16 纯等比 ✓）
   · 判据一律走 OCR 现读（**不写死**）——唯一例外是 HUD 入口与面板 X（它们是固定 UI）
   · ⚠ **「剩余数没变」必须如实记**（PC 原话：「如实记录（见日志）」）——
     绝不把「点了但没领到」说成领到了 ✓
"""
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_PCS = 1.5



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
def _s(v):
    return int(round(float(v) * _PCS))


# ── HUD 入口（**固定 UI**，720 系实测 ×1.5）──
ADS_HUD_GOLD = (_s(481), _s(26))        # 金币的**绿加号** ⇒ 购买金币
ADS_HUD_CLOVER = (_s(462), _s(59))      # 四叶草的**绿加号** ⇒ 购买四叶草
ADS_HUD_ENERGY = (_s(224), _s(62))      # 体力的**数字**（它没有绿加号）⇒ 购买体力

# ── 面板里的广告按钮（真机实测 ×1.5）──
ADS_BUYAD_GOLD = (_s(512), _s(645))
ADS_BUYAD_CLOVER = (_s(512), _s(645))
ADS_BUYAD_ENERGY = (_s(562), _s(645))

ADS_PANEL_X = (_s(613), _s(408))        # 面板右上 X

ADS_TITLES = {"gold": "购买金币", "clover": "购买四叶草", "energy": "购买体力"}
ADS_CONFIRM_YES = ("确定", "确认", "是")
ADS_CONFIRM_NO = ("取消", "否", "关闭")

ADS_LIMIT_TIP = "今日观看广告达到上限"
ADS_FAIL_TIP = "广告播放失败"

# 加速炼金（复用 guild_daily 的三个坐标 —— **同一份判据，不两边漂移** ✓）
ADS_ALCH_HOURGLASS = (_s(361), _s(338))   # 沙漏 = 加速入口
ADS_ALCH_AD = (_s(535), _s(745))          # 看广告 ⇒ 直接加速
ADS_ALCH_X = (_s(671), _s(486))           # 关掉、不加速


# v1.78: text-first tap helper (reuse guild_daily, do not fork a second copy)
from guild_daily import tap_target, _tap_xy  # noqa: E402


def _say(msg):
    """日志出口 —— 拿得到 explore_loop.say 就用它（两端口径一致 ✓）"""
    try:
        _el = sys.modules.get("explore_loop")
        _f = getattr(_el, "say", None) if _el is not None else None
        if _f is not None:
            return _f(msg)
    except Exception:       # noqa: BLE001
        pass
    try:
        print(msg, flush=True)
    except Exception:       # noqa: BLE001
        pass


def _status(msg):
    """⭐ 悬浮条提示 —— 见 guild_daily._status 的长注释（短/人话/避开 OCR 关键词）"""



def _log(log, rec):
    if log is None:
        return
    try:
        log.append(rec)
    except Exception:       # noqa: BLE001
        pass


def _panel_open(items, which=None):
    """广告面板开着吗 —— **按标题文字判**（gold/clover/energy 各有自己的标题 ✓）"""
    import guild_daily as GC
    if which:
        return GC.has(items, ADS_TITLES[which])
    return any(GC.has(items, t) for t in ADS_TITLES.values())


def _which_panel(items):
    import guild_daily as GC
    for k, t in ADS_TITLES.items():
        if GC.has(items, t):
            return k
    return None


_AD_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def read_ad_counter(items):
    """读广告次数「N/M」-> (剩余, 上限, 条目) 或 None

    ⚠ **只看面板中间那一行**（PC 实测 630~660，设备系）—— 面板别处也有 `N/M`
      （任务进度），混进来会读成「还剩很多次」⇒ 白点 ✗
    ⚠ 多条命中取**最靠上**的（PC 原口径 ✓）
    """
    best = None
    for it in (items or []):
        t = str(it.get("text") or "")
        m = _AD_RE.match(t)
        if not m:
            continue
        cy = it.get("cy", 0)
        if not (_s(560) < cy < _s(700)):
            continue
        remaining, lim = int(m.group(1)), int(m.group(2))
        if best is None or cy < best[2].get("cy", 9999):
            best = (remaining, lim, it)
    if best is None:
        return None
    return best


def _dismiss_reward_popup(b, log=None, tag="ads", sub=""):
    """点掉「恭喜获得」弹窗 —— **没有「恭喜获得/获得」字样就说明没弹窗** ✓"""
    import guild_daily as GC
    for k in range(5):
        items = GC.ocr_items(b, tag="%s_dp%d" % (sub or tag, k))
        if not GC.has(items, "恭喜获得", "获得"):
            return True             # 没弹窗 ⇒ 已经是干净的 ✓
        it = GC.find(items, "返回", "确定", "确认")
        if not it:
            _sleep(b, 0.5)
            continue
        b.tap(it["cx"], it["cy"], wait=1.9)
        _log(log, {"ads": "dismiss_reward", "text": it["text"],
                   "at": (it["cx"], it["cy"]), "try": k + 1})
        return True
    return False


def _maybe_confirm(b, log=None, tag="ads"):
    """处理可能的确认框（只点「确定」，**找不到确定就不瞎点** ✗）"""
    import guild_daily as GC
    for k in range(3):
        items = GC.ocr_items(b, tag="%s_cf%d" % (tag, k))
        if _panel_open(items):
            return True
        _hit = None
        for it in (items or []):
            t = str(it.get("text") or "")
            if ("不足" in t and "购买" in t) or "是否购买" in t:
                _hit = it
                break
        if not _hit:
            return False                    # 没确认框 ⇒ 没有要处理的 ✓
        _say("   · 出现确认框：「%s」⇒ 点「确定」" % _hit["text"])
        _yes = None
        for it in (items or []):
            if str(it.get("text") or "").strip() in ADS_CONFIRM_YES:
                _yes = it
                break
        if _yes:
            b.tap(_yes["cx"], _yes["cy"], wait=2.0)
            _log(log, {"ads": "confirm_yes", "text": _yes["text"],
                       "at": (_yes["cx"], _yes["cy"])})
        else:
            return False                    # 找不到确定 ⇒ **不瞎点** ✗
        _sleep(b, 0.6)
    return _panel_open(GC.ocr_items(b, tag="%s_cf_f" % tag))


def _close_panel(b, log=None, tag="ads"):
    """关广告面板（**先确认它还在** ✓）"""
    import guild_daily as GC
    items = GC.ocr_items(b, tag="%s_cx" % tag)
    if not _panel_open(items):
        return True
    # text-first: panel X by glyph; anchor only as fallback
    tap_target(b, items, ("×", "X", "x", "✕", "✖", "关闭"), ADS_PANEL_X,
               log=log, tag="ads_close", wait=1.8, use_dlg=True)
    items2 = GC.ocr_items(b, tag="%s_cx2" % tag)
    ok = not _panel_open(items2)
    _log(log, {"ads": "close_panel", "at": ADS_PANEL_X, "ok": ok})
    return ok


def _is_hud_screen(items):
    """屏幕上有没有 HUD（判据：顶部 cy<90 处有 `N/M` 体力计数 ✓）"""
    import guild_daily as GC  # noqa: F401
    has_energy = False
    for it in (items or []):
        t = str(it.get("text") or "")
        cy = it.get("cy", 999)
        if cy < _s(90) and "/" in t and re.match(r"^\s*\d+\s*/\s*\d+\s*$", t):
            has_energy = True
    return has_energy



# ⭐ v1.99【**三个资源图标模板** —— 用户口径】
#
#   用户原话：「免广告不是这个模板，应该是三个模板，分别是**体力（绿色闪电）**、
#             **金币（黄色金币）**、**幸运草（绿色幸运草）**，而不是加号」
#
#   ⛔ 我之前的错：用「HUD 绿加号」当模板，然后按方位猜哪个加号是哪个资源 ✗
#     · 加号在**多个资源上都有**（金币/红宝石/四叶草/钥匙 各一个）
#     · 方位推断也错过（把"钥匙"当成"体力"）
#   ✅ 正确做法：**直接匹配资源图标本身**，一个资源一个模板 ✓
#     真机实测（`hud2.png`，颜色检测出的精确 bbox）：
#       金币    dev(576,159) 32×37  ⇒ 归一化 ref(484,132) 31×35
#       体力闪电 dev(176,223) 64×37  ⇒ 归一化 ref(147,186) 57×35
#       幸运草   dev(651,217) 37×38  ⇒ 归一化 ref(548,181) 34×36
#     三个模板在归一化帧上**都是唯一命中、score 1.000** ✓
#
#   ⚠ 模板尺度：全是 **`img()` 归一化帧**尺度（不是设备尺度）
RES_TPL = {
    "gold":   "hud_coin.png",
    "energy": "hud_energy.png",
    "clover": "hud_clover.png",
}
RES_SCORE_MIN = 0.80


def find_res_icon(b, which, log=None):
    """模板匹配找某个**资源图标**（金币/体力/幸运草）-> (x, y) 或 None

    ⚠ 用 `b.img()` 的**归一化帧**尺度 ⇒ 模板也必须归一化尺度 ✓
    ⚠ 只在 HUD 带（ref y 100~250）找，避开别处的同色元素
    """
    import guild_daily as GC
    name = RES_TPL.get(which)
    if not name:
        return None
    tpl = GC._load_tpl(name)
    try:
        nimg = b.img()
    except Exception:       # noqa: BLE001
        return None
    if tpl is None or nimg is None:
        return None
    hits = GC._tpl_match(nimg, tpl, thr=RES_SCORE_MIN, roi=(100, 260))
    if log is not None:
        GC._log(log, {"ads": "res_icon", "which": which, "tpl": name,
                      "n": len(hits), "best": hits[0] if hits else None})
    if not hits:
        return None
    return (hits[0][0], hits[0][1])

AD_PLAY_TPL = "ad_green_play.png"


def find_ad_play_btn(b, log=None):
    """在**购买面板**里找「绿色箭头/摄像机」按钮（点它才看广告）-> (x, y) 或 None

    ⛔⛔ v2.00【**用户口径：打开后得点绿色箭头才能用免广**】
    ⛔ 原话：「金币幸运草和体力打开后得点**绿色箭头**才能使用免广」

    ---- 面板结构（真机 OCR + 模板实测，`ad4.png`）----
      dlg(540, 668)  「购买金币」标题
      dlg(540, 795)  「本次购买可获得20000金币」
      dlg(540, 888)  「当前购买价格为50宝石，每日重置」
      dlg(369,1023)  「50」        ← **宝石价格**（绝不能点，花宝石 ✗）
      dlg(768,1023)  「0/3」       ← **广告剩余次数**
      dlg(671,1015)  **绿色广告图标** ← **要点这个**（模板 `ad_green_play.png`）✓

    ⚠ 为什么用模板而不是点「0/3」：
      点文字 `0/3` 的**包围盒中心**在绿色图标**右边**，那里是按钮的文字区，
      真机上点文字不一定触发（按钮的命中区在图标那侧）⇒ 用图标模板更准 ✓

    ⚠ 必须用 **`img_dlg()`**（面板是弹窗，`img()` 会丢弹性带）✓
    """
    import guild_daily as GC
    tpl = GC._load_tpl(AD_PLAY_TPL)
    try:
        nimg = b.img_dlg() if hasattr(b, "img_dlg") else None
    except Exception:       # noqa: BLE001
        nimg = None
    if tpl is None or nimg is None:
        return None
    hits = GC._tpl_match(nimg, tpl, thr=0.85, roi=(700, 1300))
    if log is not None:
        GC._log(log, {"ads": "ad_play_btn", "n": len(hits),
                      "best": hits[0] if hits else None})
    if not hits:
        return None
    return (hits[0][0], hits[0][1])

def buy_with_ad(b, which, log=None, tag="ads", max_times=3, dry=False):
    """买一次体力/四叶草/金币（**靠看广告**，不花宝石 ✓）-> 成功次数

    ⚠ PC 的**成败判据是「剩余数有没有变小」**（不是"点了没报错"）：
      · 面板上写着 `剩余 N/M` ⇒ 点完广告再看一眼 ⇒ **没变小 = 没领到**（如实记 ✓）
      · 这条很关键：本项目反复栽在「把点了当成成了」✗
    ⚠ 三条"停手"出口（每条都**如实上报**）：
      · 读不到 `N/M` ⇒ 不瞎点
      · 剩余 <= 0 ⇒ 今天到此为止
      · 「今日观看广告达到上限」/「广告播放失败」⇒ 停手
    """
    import guild_daily as GC
    title = ADS_TITLES[which]
    got = 0
    for r in range(max(1, int(max_times))):
        if dry:
            _say("   · [dry-run] %s：跳过第 %d 次" % (title, r + 1))
            continue

        items = GC.ocr_items(b, tag="%s_%s_o%d" % (tag, which, r))
        if not _panel_open(items, which):
            # ⭐⭐⭐ v1.97【**模板定位绿加号** —— 用户口径「把免广的模板弄好」】
            #   ---- 旧写法的问题 ----
            #     `entry = {"gold": ADS_HUD_GOLD, ...}` 全是 **PC×1.5 推算**，
            #     从没在真机上验过（和炼金/派遣当初一样）✗
            #   ---- 现在 ----
            #     ① 模板匹配 `hud_greenplus.png` 找**所有**绿加号
            #        （真机实测 4 个：金币/四叶草/红宝石/体力，得分 1.00/0.96/0.96/0.92）
            #     ② 按 which 选**对应位置**（HUD 布局固定：金币在左上，体力在右下）
            #     ③ 模板没命中 ⇒ 退回旧锚点（并如实记 by=anchor）✓
            # ⭐ v1.99：**直接匹配资源图标**（金币/闪电/幸运草），不再靠加号+方位猜
            _entry = find_res_icon(b, which, log=log)
            _by_gp = "tpl" if _entry else ""
            if _entry is None:
                _entry = {"gold": ADS_HUD_GOLD, "clover": ADS_HUD_CLOVER,
                          "energy": ADS_HUD_ENERGY}[which]
                _by_gp = "anchor"
            _say("   · %s：点资源图标 (%d,%d)[%s]"
                 % (title, _entry[0], _entry[1], _by_gp))
            b.tap(_entry[0], _entry[1], wait=2.4)
            items = GC.ocr_items(b, tag="%s_%s_o%dc" % (tag, which, r))
            _log(log, {"ads": "open_panel", "which": which,
                       "at": entry, "open": _panel_open(items, which)})
            if not _panel_open(items, which):
                _maybe_confirm(b, log, tag)
                items = GC.ocr_items(b, tag="%s_%s_o%dd" % (tag, which, r))
            if not _panel_open(items, which):
                _say("   · %s：没打开面板（第 %d 次）⇒ 停手如实上报" % (title, r + 1))
                _log(log, {"ads": "panel_not_open", "which": which})
                break

        cnt = read_ad_counter(items)
        if cnt is None:
            _say("   · %s：读不到广告次数 `N/M` ⇒ **不瞎点** ✗" % title)
            _log(log, {"ads": "counter_missing", "which": which})
            _close_panel(b, log, tag)
            break
        remaining, limit, it = cnt

        if remaining <= 0:
            _say("   · %s：广告次数**已用完**（剩 %d/%d）⇒ 今天到此为止 ✓"
                 % (title, remaining, limit))
            _log(log, {"ads": "limit_reached", "which": which,
                       "remaining": remaining, "limit": limit})
            _close_panel(b, log, tag)
            break
        _say("   · %s：还能领 **%d** 次（剩 %d/%d）"
             % (title, remaining, remaining, limit))

        # ⭐ v2.00：**优先点绿色广告图标**（模板）；认不到才退回 OCR 的 `0/3` 位置
        _play = find_ad_play_btn(b, log=log)
        if _play is not None:
            _at_ad, _by_ad = _play, "tpl"
        else:
            _at_ad, _by_ad = (it["cx"], it["cy"]), "ocr"
            _say("   · ⚠ 没找到绿色广告图标 ⇒ 退回点 `0/3` 文字位置（可能不触发）")
        b.tap(_at_ad[0], _at_ad[1], wait=2.6)
        _log(log, {"ads": "tap_ad_btn", "which": which, "at": _at_ad,
                   "by": _by_ad, "was_remaining": remaining, "limit": limit})
        _say("   · %s [%d] ⇒ 点绿色广告图标 (%d,%d)[%s]（当时剩 %d/%d）"
             % (title, got + 1, _at_ad[0], _at_ad[1], _by_ad, remaining, limit))

        _dismiss_reward_popup(b, log, tag, "%s_%s" % (tag, which))
        items2 = GC.ocr_items(b, tag="%s_%s_r%d" % (tag, which, r))
        if GC.has(items2, ADS_LIMIT_TIP):
            _say("   · ⚠ 提示「%s」⇒ 今天到此为止 ✓" % ADS_LIMIT_TIP)
            _log(log, {"ads": "limit_tip", "which": which})
            _close_panel(b, log, tag)
            break
        if GC.has(items2, ADS_FAIL_TIP):
            _say("   · ⚠ 提示「%s」⇒ **如实上报、不重试死磕** ✗" % ADS_FAIL_TIP)
            _log(log, {"ads": "ad_failed", "which": which})
            _close_panel(b, log, tag)
            break

        cnt2 = read_ad_counter(items2)
        if cnt2 and cnt2[0] < remaining:
            got += 1
            _say("       · ✓ 领到（剩余 %d/%d → %d/%d）"
                 % (remaining, limit, cnt2[0], cnt2[1]))
            _log(log, {"ads": "claimed", "which": which,
                       "now_remaining": cnt2[0], "limit": cnt2[1]})
        else:
            _say("       · ⚠ 剩余数没变（仍 %s）⇒ 如实记录（见日志）"
                 % ("%d/%d" % (cnt2[0], cnt2[1]) if cnt2 else "读不到"))
            _log(log, {"ads": "counter_unchanged", "which": which,
                       "before_remaining": remaining, "limit": limit,
                       "after": ("%d/%d" % (cnt2[0], cnt2[1])) if cnt2 else None,
                       "texts": GC._texts(items2)[:12]})
            break

        it3 = GC.ocr_items(b, tag="%s_%s_e%d" % (tag, which, r))
        if not _panel_open(it3, which):
            continue
        _close_panel(b, log, tag)
    return got


def _read_accel_counter(items):
    """加速炼金弹窗的 `N/1` 计数 -> (剩余, 上限, 条目) 或 None"""
    import guild_daily as GC  # noqa: F401
    best = None
    for it in (items or []):
        t = str(it.get("text") or "")
        m = _AD_RE.match(t)
        if not m:
            continue
        remaining, lim = int(m.group(1)), int(m.group(2))
        if best is None or it.get("cy", 9999) < best[2].get("cy", 9999):
            best = (remaining, lim, it)
    return best


def alchemy_accel(b, log=None, tag="ads"):
    """用免广**立即完成**炼金 -> bool

    ⚠ 用户口径（PC 原文）：「**勾选免广的话，做公会日常的时候，
      八小时炼金可以直接用一次免广立即领取**」✓
    ⚠ 三道闸门（都别删）：
      · 点了沙漏但没出加速弹窗 ⇒ **多半是炼金没在进行中** ⇒ 跳过 ✓
      · 读不到 `N/1` 计数 ⇒ **不瞎点** ✗
      · 剩余 <= 0 ⇒ 今天到此为止 ✓
    """
    import guild_daily as GC
    items = GC.ocr_items(b, tag="%s_al0" % tag)
    _on_popup = (GC.has(items, "观看广告") or GC.has(items, "加速炼金")
                 or GC.has(items, "花费宝石"))
    if not _on_popup:
        _tap_xy(b, ADS_ALCH_HOURGLASS[0], ADS_ALCH_HOURGLASS[1], wait=2.4)
        items = GC.ocr_items(b, tag="%s_al1" % tag)
        _on_popup = (GC.has(items, "观看广告") or GC.has(items, "加速炼金")
                     or GC.has(items, "花费宝石"))
        _log(log, {"ads": "alch_hourglass", "at": ADS_ALCH_HOURGLASS,
                   "popup": _on_popup})
        if not _on_popup:
            _say("   · 加速炼金：点了沙漏但没出加速弹窗"
                 "（多半是**炼金没在进行中**）⇒ 跳过 ✓")
            return False
    _say("   · 加速弹窗已开（含「观看广告/加速炼金」✓）")

    _cnt = _read_accel_counter(items)
    if _cnt is None:
        _say("   · 加速炼金：读不到 `N/1` 计数 ⇒ **不瞎点** ✗")
        _log(log, {"ads": "alch_counter_missing", "texts": GC._texts(items)[:12]})
        tap_target(b, items, ("×", "X", "x", "✕", "✖", "关闭"), ADS_ALCH_X,
                   log=log, tag="ads_alch_x", wait=1.6, use_dlg=True)   # 关掉，不加速 ✓
        return False
    remaining, limit, it = _cnt
    if remaining <= 0:
        _say("   · 加速炼金：广告次数**已用完**（剩 %d/%d）⇒ 今天到此为止 ✓"
             % (remaining, limit))
        _log(log, {"ads": "alch_limit_reached",
                   "remaining": remaining, "limit": limit})
        tap_target(b, items, ("×", "X", "x", "✕", "✖", "关闭"), ADS_ALCH_X,
                   log=log, tag="ads_alch_x", wait=1.6, use_dlg=True)   # 关掉弹窗 ✓
        return False
    _say("   · 加速炼金：还能领 %d 次（剩 %d/%d）" % (remaining, remaining, limit))

    b.tap(it["cx"], it["cy"], wait=2.6)
    _log(log, {"ads": "alch_tap_ad", "at": (it["cx"], it["cy"]),
               "was_remaining": remaining, "limit": limit})
    _say("   · 加速炼金 ⇒ 点「看广告」(%d,%d)（当时剩 %d/%d）"
         % (it["cx"], it["cy"], remaining, limit))

    items2 = GC.ocr_items(b, tag="%s_al2" % tag)
    if GC.has(items2, ADS_FAIL_TIP):
        _say("   · ⚠ 「%s」⇒ 如实上报 ✗" % ADS_FAIL_TIP)
        _log(log, {"ads": "alch_ad_failed"})
        return False
    if GC.has(items2, ADS_LIMIT_TIP):
        _say("   · ⚠ 「%s」⇒ 今天到此为止 ✓" % ADS_LIMIT_TIP)
        _log(log, {"ads": "alch_limit"})
        tap_target(b, items, ("×", "X", "x", "✕", "✖", "关闭"), ADS_ALCH_X,
                   log=log, tag="ads_alch_x", wait=1.6, use_dlg=True)
        return False

    _gone = not (GC.has(items2, "观看广告") or GC.has(items2, "花费宝石"))
    _log(log, {"ads": "alch_result", "popup_gone": _gone,
               "texts": GC._texts(items2)[:12]})
    _say("   · %s" % ("加速弹窗已关 ⇒ 加速成功 ✓" if _gone
                      else "弹窗还在 ⇒ 没加速成（如实上报）"))
    return bool(_gone)


def run(b, log=None, skip_ads=True, alchemy=True, times=3, dry=False):
    """免广告领奖全流程 -> res（gold / clover / energy / alchemy / ok …）

    ⚠ `skip_ads`（PC 里的名字）语义是「**已经默认有免广**」⇒ 真去点广告按钮；
      手机端界面上那颗勾选 = 「这个号有免广」⇒ 勾了才调本函数 ✓
    ⚠ 顺序（PC 原样）：**金币 → 四叶草 → 体力 → 加速炼金**
      （前三个都是"领资源"，最后那个会**改炼金状态** ⇒ 放最后 ✓）
    """
    import guild_daily as GC
    log = log if log is not None else []
    res = {"ok": False, "gold": 0, "clover": 0, "energy": 0, "alchemy": False}
    _say("")
    _say("=" * 62)
    _status("免广 · 开始领奖")
    _say("📺 免广告领奖（金币 / 四叶草 / 体力 / 加速炼金）")
    _say("=" * 62)

    if not skip_ads:
        _say("   ⛔ 这个号没有「免广告」⇒ **四个入口一下都不碰** ✓")
        res["why"] = "no_adfree"
        return res

    items = GC.ocr_items(b, tag="ads_pre")
    if not _is_hud_screen(items):
        _say("   ⚠ 现在看不到 HUD（不在主界面/选图界面）⇒ 跳过（瞎点会落到棋盘上 ✗）")
        res["why"] = "no_hud"
        return res

    for _which, _key, _times in (("gold", "gold", times),
                                 ("clover", "clover", times),
                                 ("energy", "energy", times)):
        try:
            n = buy_with_ad(b, _which, log, times=_times, dry=dry)
            res[_key] = n
        except Exception as _e:     # noqa: BLE001
            import traceback as _tb
            _log(log, {"ads": "%s_error" % _key, "e": repr(_e)[:140],
                       "trace": _tb.format_exc().splitlines()[-4:]})
            _say("   ⚠ %s 出错：%r（**不影响其它两项** ⇒ 继续 ✓）"
                 % (ADS_TITLES[_which], _e))

    if alchemy:
        try:
            res["alchemy"] = bool(alchemy_accel(b, log))
        except Exception as _e2:    # noqa: BLE001
            import traceback as _tb2
            _log(log, {"ads": "alch_error", "e": repr(_e2)[:140],
                       "trace": _tb2.format_exc().splitlines()[-4:]})
            _say("   ⚠ 加速炼金出错：%r（**不影响前三项** ⇒ 继续 ✓）" % (_e2,))

    res["ok"] = bool(res["gold"] or res["clover"] or res["energy"] or res["alchemy"])
    _log(log, {"ads": "done", "gold": res["gold"], "clover": res["clover"],
               "energy": res["energy"], "alchemy": res["alchemy"],
               "ok": res["ok"]})
    _say("=" * 62)
    return res


def summary_line(res):
    """一行摘要（收尾统计用）—— **失败也照实写** ✓"""
    res = res or {}
    if res.get("why"):
        return "免广告：跳过（%s）" % res["why"]
    return "免广告：金币 %s ｜ 四叶草 %s ｜ 体力 %s ｜ 加速炼金 %s" % (
        res.get("gold"), res.get("clover"), res.get("energy"),
        "✓" if res.get("alchemy") else "—")

