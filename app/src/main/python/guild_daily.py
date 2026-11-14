# -*- coding: utf-8 -*-
"""guild_daily.py · 收工后的「公会日常 + 免费招募 + 免广告」—— 从 PC 端移植 (v1.78)

PC 源（**PC 仓只读、未改动**）：
    mapbot_pc/guild_common.py  814 行  —— 公会展厅导航 + 面板判据（派遣/炼金共用底层）
    mapbot_pc/guild_tasks.py   407 行  —— 派遣任务（2 楼 4 把椅子）
    mapbot_pc/alchemy.py       556 行  —— 炼金（4 楼顶楼左边普通宝箱）
    mapbot_pc/intel.py         468 行  —— 公会「情报」领奖（每日 + 每周）
    mapbot_pc/explore_loop.py  _guild_daily() @12506 —— 收工日常的顺序调度

用户口径（PC 记录的原文，**这就是为什么要有这个模块**）：
    · 「**这些我打算是体力刷完自动去做**」（派遣 / 炼金）
    · 「**不用放弃**」「**不召回**」（派遣）
    · 「**炼金往上滑就能看到个有感叹号的箱子**」「这时候要**点满星**，然后点**开始炼金**」
    · 「**接下来做点击情报领取奖励**」「**每周情报也顺便点了**」
    · 「**每周情报可以直接盲点一下最上面的可领取的坐标**，然后就可以关闭页面了」
    · 「把勾选的公会日常，免费招募和免广告（**这三个脚本的最后都要回到地图界面，
      最开始都要进入公会界面**）都做完后，检查下体力…」

════════════════════════════════════════════════════════════════════
⭐⭐⭐ 移植口径（**学 ≠ 照抄**，每条都写清为什么）
════════════════════════════════════════════════════════════════════
① **坐标一律 ×1.5 换算到手机参考系（1080×1920）**
   PC 那份是 720×1280 设备系实测；两端同为 9:16 ⇒ 纯等比 ×1.5。
   交叉验证：PC 宝库「返回」(359,827) ×1.5 = (539,1241)，
     手机端实测 VAULT_BACK_ZONE = (539,1240) ⇒ **只差 1px** ✓
② **不用 adb**：PC 的 swipe_abs() 走 adb shell input swipe；
   手机端走无障碍手势 ⇒ b.swipe()（接口同名同语义 ✓）。
③ **不 import explore_loop**（那会拉起一整坨业务且会循环导入）
   ⇒ 本模块自带 _items() / _say()，与 buypanels.py 同一套做法 ✓
④ **每个子流程自己 try/except**，一个崩了不影响其它（PC 的原话：
   「两个各包一层 try/except：**一个崩了不影响另一个**，更不影响收尾统计」）
⑤ 手机端**没有环境变量**（跑的是 APK）⇒ 开关由界面（Prefs）传进来，
   模块级只留默认值给门禁/直跑用 ✓
"""
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_PCS = 1.5                  # ⭐ PC 720 系 ⇒ 手机 1080 系（9:16 纯等比）


def _s(v):
    """PC 720×1280 设备系坐标 ⇒ 手机 1080×1920 参考系（整数）"""
    return int(round(float(v) * _PCS))


# ══════════════════════════════════════════════════════════════════════
# ① 坐标表（PC 全部 720×1280 实测 ⇒ 这里统一过 _s()）
# ══════════════════════════════════════════════════════════════════════
NAV_GUILD = (_s(55), _s(1240))          # 底部导航「公会」
NAV_START = (_s(360), _s(1260))         # 底部导航「开始冒险」（离开公会）

# 滚动（PC 原话：**手指下滑 = 看更高层**）
SWIPE_UP_XY = (_s(360), _s(200), _s(360), _s(900), 1200)      # 往**高**楼层
SWIPE_DOWN_XY = (_s(360), _s(900), _s(360), _s(200), 1200)    # 往**低**楼层
FLOOR_SWIPES = 3                              # 从 2 楼到 4 楼实测要 3 次

# ── 派遣任务（2 楼「黑晶女仆」那 4 个人）──
#
# ⛔⛔ v1.82【**真机重标定** —— 旧值全部来自「PC 720 ×1.5」，实测差 331 参考像素】
#   ---- 怎么发现的（用户报「卡在派遣界面，点不到一键派遣」）----
#     日志：`{"guild":"chair_floor_not_found"}` + **一条 `task/tap_action` 都没有**
#     ⇒ `ensure_chair_floor()` 滚了 15 次都没认出楼层 ⇒ `run_tasks` 直接 return
#     ⇒ 派遣流程**从未开始**（所以不是"点不到按钮"，是**连椅子都没找到**）✗
#   ---- 真机截图实测（`_tmpman/floor.png`，1280×2772）----
#     桌边 4 个小人 设备 y≈940~950  ⇒ 参考系 boardY≈**377~383**
#     （旧 `CHAIR_Y = _s(470) = 705` ⇒ 差 **331**，点在了下面那层楼板 ✗）
#   ---- 更深的一层：四把椅子 vs 一簇小人 ----
#     PC 端是**4 把散开的椅子**（x=263/388/513/628）；
#     手机端是**4 个小人围坐在中间一张桌子旁**（x≈405/506/726/852）⇒
#     间距更大、且**首尾不在同一片**（中间隔着桌子）⇒ 逐个 x 点仍然有效 ✓
#   ---- 坐标系（这条最要紧，我第一版搞反了）----
#     · 楼层/小人/气泡 = **界面元素，不经弹窗** ⇒ 走 `tap()`（棋盘系：refY*kx + shift）
#     · 派遣面板里的按钮 = **居中弹窗** ⇒ 走 `tap_dlg()`（弹窗系：H/2 + (refY-960)*kx）
#     ⚠ 同一个参考 y 在两套空间里差 **±248 设备像素**（`RefMapper` 注释原话）！
# ⭐⭐⭐ v1.86【**气泡模板定位** —— 用户口径：「不能固定坐标啊，识别气泡」】
#
#   ✅ 用户原话（唯一权威口径）：
#      「**小人头上是问号就是能直接点下面的小人进行派遣**，
#         **是感叹号就需要先点下面对应的小人领取，然后再点那个小人进行派遣**」
#      「**不能固定坐标啊，识别气泡**」
#
#   ---- 为什么必须模板定位，不能写死坐标 ----
#     真机实测：同样 4 个位置，我先后算出**三套完全不同的坐标**（380/606/756），
#     每次都以为对了 ⇒ 因为气泡是**美术**，位置随分辨率/楼层滚动/机型变化，
#     写死一个数就是「换台机器就废」✗ —— 这正是项目硬规矩
#     「**文字 → 模板 → 锚点坐标**」里**第二级**该做的事 ✓
#
#   ---- 模板从哪来（可复现）----
#     真机 1280×2772 帧裁出 `guild_bubble.png`（68×62，白底+问号符号），
#     存 `assets/mapbot_pack/templates/guild_bubble.png` ✓
#     实测匹配：4/4 全中，分数 **0.774 / 1.000 / 0.892 / 0.892**
#     ⇒ 阈值定 **0.70**（最低分 0.774 之上留余量，又能容忍不同符号）✓
#
#   ---- 已知的匹配半径 ----
#     气泡中心 dev x = 475 / 688 / 933 / 1147（1280 宽）
#     小人本体在气泡**正下方约 125 设备像素**（实测点 (465,1215) 能开面板）
#     ⇒ 约定：**模板给气泡位置，点「气泡 y + 125」即为小人** ✓
#     ⚠ 125 是**设备像素**，按 kx 折算成参考系更稳（见 _person_of_bubble）
# ⚠ 只写**文件名**：`_tpl_dirs()` 返回的每个目录**已经**是 templates 级
#   （`fixed_ref.tpl_dirs()` 给的是 `.../templates/ui` / `.../templates`）
#   ⇒ 再拼 "templates/" 会变成 `.../templates/ui/templates/xxx` ⇒ 必然找不到 ✗
#   —— 我第一版就是这么错的，门禁当场抓到 ✓
BUBBLE_TPL = "guild_bubble.png"
BUBBLE_SCORE_MIN = 0.70
BUBBLE_DY_REF = 106          # 气泡中心 -> 小人可点位置（参考像素，实测 dev 125 ÷ kx）
# ⚠⚠ **坐标系**（这条我第一版搞错了，门禁+真机双重抓出）✗：
#   `b.img()` 返回的是**归一化帧 1080×1920**（`RefMapper.toRef` 的产物），
#   **不是**设备原图 1280×2772 ⇒ 模板必须从**归一化帧**裁，ROI 也用参考系 y ✓
#   我第一版拿设备帧裁模板(1280 图) 去匹配归一化帧 ⇒ 尺寸对不上 ⇒ 一个都匹配不到，
#   真机日志：模板载入成功(68x62) 但 30 秒**零命中** ⇒ `chair_floor_not_found` ✗✗
BUBBLE_ROI_Y = (400, 700)    # 归一化帧里气泡带 refY≈540；给上下余量
# 气泡中心在参考系里的 y 带（真机 dev y=1137 ⇒ refY=540；给 ±30 容差）
BUBBLE_Y0, BUBBLE_Y1 = 510, 570

# 派遣面板底部主按钮（**弹窗系**）：dev(1020,2300) ⇒ dlgY=1731
#   文案三态共用同一位置：一键派遣 / 开始任务 / 召回 ✓
TASK_ACTION_BTN = (861, 1731)
# 派遣面板右上 X（**弹窗系**）：dev(1183,352) 反算
TASK_PANEL_X = (998, 88)
# ── 炼金（4 楼顶楼）══ 真机实测重标定 v1.92 ──
#
# ⛔⛔ 旧值全错（PC 720 系 ×1.5 推算，没在真机上验过）
#   ---- 真机实测（2026-10-18 22:3x，`_tmpman/al5.png` 逐帧确认）----
#     顶楼三个物件（**别点错**，PC 文档也这么记）：
#       · 左边**宝箱**   dev(420, 900)  ⇒ 炼金宝箱 ✓（点开就是「炼金宝箱」面板）
#       · 中间**大陶罐** dev(700, 985)  ⇒ 点了**无反应** ✗
#       · 右边**紫发角色** dev(905,990) ⇒ **献祭宝箱怪**（天赋互换）**别点** ✗
#
#     炼金面板 OCR 实测（归一化帧 → 设备像素，conf 都是 0.96~1.00）：
#       「全部取消」  ref(644,552) dev( 763,1151)
#       「开始炼金」  ref(900,552) dev(1067,1151)   ← 主按钮
#       「预计时间」  ref(284,561) dev( 337,1161)
#       「装备」标签  ref(198,732) dev( 234,1363)
#       「符文」标签  ref(451,732) dev( 535,1364)
#       「满星」筛选  ref(500,1553) dev(593,2337)   ← 投满星用这个
#       「绿色/蓝紫橙」ref(613/833,1553)
#
#     炼金**结果**面板（有奖待领时）：
#       「炼金结果」ref(541,420) / 「货币」ref(540,534) / 「道具」ref(540,760)
#       「返回」按钮 ref(540,1243) dev(639,1970)   ← 我第一版点 (640,1335) 差 635 ✗
#
#   ---- 位置会随"滚到多深"变（PC 也记着）----
#     宝箱 y 实测见过 435/445/455/470（PC 720 系）⇒ 真机同样会漂
#     ⇒ 保留**多候选点试**的做法（x 一组 × y 一组），逐个试到开出面板 ✓
#     ⚠ 但基准换成**真机实测**，不再用 PC ×1.5 ✓
# ⛔⛔ v1.96【**之前的 y 差了 359 —— 所以只能乱扫，然后点到兑换商店**】
#   真机逐像素量（`al4.png` 顶楼，放大 2 倍带网格）：
#     宝箱本体 **dev x 430~500, y 940~1000** ⇒ 反算 **ref(392, 400)**
#     旧值 `(354, 759)` ⇒ **y 差 359** ✗（759 那个位置是公会 3 楼，根本不在顶楼）
#   而 `ALCHEMY_CHEST_YS` 曾写成 `(759,700,820)` ⇒ 盲扫时点在
#     **「兑换商店开启」横幅**（ref 541,624 附近）⇒ 点开了兑换商店 ✗✗
#
#   ---- 为什么这个物件不能像气泡那样"模板定位" ----
#     ① 宝箱美术**随公会皮肤变**（PC 实测跨账号匹配只有 0.39~0.46）✗
#     ② 顶楼那一带**没有任何 OCR 文字**（真机实测：ref 200~600 只有
#        `兑换商店开启` 一条，那是横幅不是宝箱）⇒ 文字判据也没有 ✗
#     ⇒ 这是全仓**少数几个只能点坐标、且没有可靠识别手段**的物件之一
#       （和 4 个派遣小人一样是纯美术）
#
#   ---- 所以改成「**点一次 + 强验证 + 点错立刻关掉**」（不再是乱扫）----
#     · 只点 **1 个**实测位置（不再 x/y 笛卡尔积 9 次）
#     · 点完**必须**看到「炼金宝箱」面板；看到别的（兑换商店等）⇒ **立刻点 X 关掉** ✓
#     · 点错**不重试**别的坐标（乱扫才是真危险）⇒ 如实报失败 ✓
ALCHEMY_CHEST = (392, 400)                       # dev(465,970) 反算（真机逐像素实测）
# ⛔⛔ v1.95【**候选点乱扫 = 点到兑换商店** —— 真机日志铁证】**
#   日志：`点 (354,700) ⇒ 认到 [觉醒石/前往/炼金获取/活动兑换]`
#   那不是公会楼层，是**「兑换商店」面板**（公会 2 楼横幅「兑换商店开启」点开的）✗
#   ⇒ 旧的 `YS = (759, 700, 820)` 里 **700/820 是错的** —— 那两个 y 正好落在
#     兑换商店的横幅上，盲扫一次就点开一个完全不相关的面板 ✗✗
#   ---- 教训 ----
#     「多候选点兜底」在**没有先确认画面是什么**时是有毒的：
#       宝箱会随滚动漂，但**绝不是"在 y 700~820 随便试"** ⇒
#       候选范围必须**贴着实测值**（±1 个身位），不能靠瞎扫 ✓
# ⛔ v1.96：**候选点全部删除** —— 乱扫是"点到兑换商店"的直接原因
#   只保留一个实测位置；点不中就如实失败，绝不换坐标重试 ✓
ALCHEMY_DECO_POT = (590, 840)                    # 大陶罐 dev(700,985) —— **无反应** ✗
ALCHEMY_OFFERING = (764, 845)                    # 紫发角色 dev(905,990) —— **别点** ✗
# 炼金主面板
ALCH_TITLE = "炼金宝箱"
ALCH_START_BTN = (900, 552)                      # dev(1067,1151) 「开始炼金」
ALCH_CANCEL_BTN = (644, 552)                     # dev(763,1151) 「全部取消」
ALCH_TAB_EQUIP = (198, 732)                      # dev(234,1363) 「装备」
ALCH_TAB_RUNE = (451, 732)                       # dev(535,1364) 「符文」
ALCH_FILTER_FULLSTAR = (500, 1553)               # dev(593,2337) 「满星」
ALCH_EXPECT_LABEL = (284, 561)                   # dev(337,1161) 「预计时间」
# 炼金**结果**面板（有奖待领）
ALCH_RESULT_TITLE = "炼金结果"
ALCH_RESULT_BACK = (540, 1243)                   # dev(639,1970) 「返回」
def _say(msg):
    """日志出口 —— 拿得到 explore_loop.say 就用它（两端口径一致 ✓）

    ⚠ 惰性取（sys.modules.get），避免循环导入 ✓（与 buypanels.say 同一做法）
    """
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
    """⭐ 悬浮条提示 —— 用户唯一能在游戏里看见「现在在做什么」的通道

    ⛔ v1.81【用户报：**日志还不显示正在做什么日常**】
      病因：我写 guild_daily 时只用 _say()（= print）输出，**从来没给悬浮条发过一句**。
      而本项目的 UI 通道是**显式的**（explore_loop:167-180 有完整留档）：
        · say() / print()  =>  只进**界面控制台 + logcat**（给开发看的）
        · status()         =>  才进**悬浮条日志行**（用户盯着看的那一行）
      => 悬浮条一直停在上一条，日常跑了半天**一个字都没显示**。

      修法：每个子流程的关键节点都发一条 status()。
      ⚠ 三条硬规矩（explore_loop:177 原文）：
        ① **短**（约 28 汉字内）② **人话** ③ **避开 OCR 关键词**
        ③ 最关键 —— 否则脚本会把自己的悬浮条文字 **OCR 认成游戏 UI** ✗
        关键词表见 explore_loop:180（开始冒险/进入地图/一键派遣/探索配队/…）
        => 下面的提示刻意避开那几个词（用「排班」「收起」代替 派遣/领取）。
    """
    try:
        _el = sys.modules.get("explore_loop")
        _f = getattr(_el, "status", None) if _el is not None else None
        if _f is not None:
            return _f(msg)
    except Exception:       # noqa: BLE001
        pass


def _log(log, rec):
    """写一条结构化日志（log 为 None 也不用管 ✓）"""
    if log is None:
        return
    try:
        log.append(rec)
    except Exception:       # noqa: BLE001
        pass


def _texts(items):
    return [str((i or {}).get("text") or "").strip() for i in (items or [])]


def has(items, *labels, exact=False):
    """任一 label 命中（默认**子串**；exact=True 则要求整条相等 ✓）"""
    ts = _texts(items)
    for lb in labels:
        for t in ts:
            if (t == lb) if exact else (lb in t):
                return True
    return False


def find(items, *labels, exact=False, ymin=None, ymax=None):
    """找**第一个**命中的 OCR 条目（返回条目本身，含 cx/cy ✓）"""
    for it in (items or []):
        t = str(it.get("text") or "").strip()
        if ymin is not None and it.get("cy", 0) < ymin:
            continue
        if ymax is not None and it.get("cy", 0) > ymax:
            continue
        for lb in labels:
            if (t == lb) if exact else (lb in t):
                return it
    return None


def _stopped():
    """⏹ **停止位**（用户点 ■ ⇒ `explore_loop._ANDROID_STOP=True`）

    ⛔⛔ v1.84【用户报：**「这一直乱点我都停不了」**】
      ---- 病 ----
      本项目的停止机制是「**协作式**」的：`_ANDROID_STOP` 置位后，**每个长操作自己**
      在循环里查一次（`mapbot.py` 的 `wait_change`/`_sleep` 都查了 ✓）。
      而我在 `guild_daily` / `recruit` / `ads` 里写的流程是
      「**ocr → 点 → ocr → 点**」的短循环 —— **中间一个检查点都没有** ✗
      ⇒ 点 ■ 之后 `_ANDROID_STOP` 确实是 True 了，
        但我的代码**从不问它** ⇒ 继续一路点下去 ⇒ 用户看到的就是「停不了、一直乱点」✗✗
      ---- 为什么 `tap()` 里的 `wait_change` 救不了 ----
      它只让**当前那一次点击的等待**变短（≤80ms），点完之后**下一次点击照样发生** ✓
      ---- 修法（三道闸门，缺一不可）----
        ① `ocr_items()` **开头**查停止位 ⇒ 停了就返回 []（下游自然全部判空、不再点）
        ② `_tap_xy()` **开头**查 ⇒ 停了就不点（**最后一道**，挡住任何漏网的点击）
        ③ `_sleep()` 已有（`b._sleep` 内部查）✓
      ⚠ 只加 ①：某些路径不经过 `ocr_items`（如硬点椅子）⇒ 会漏 ⇒ 所以必须有 ②
      ⚠ 只加 ②：OCR 仍照跑 ⇒ 每次还要等 1~2 秒 ⇒ **体感还是慢** ⇒ 所以必须有 ①
    """
    try:
        import sys as _sys
        _el = _sys.modules.get("explore_loop")
        if _el is not None and getattr(_el, "_ANDROID_STOP", False):
            return True
    except Exception:       # noqa: BLE001
        pass
    return False


def ocr_items(b, band=None, tag="guild", min_conf=0.35):
    """抓一帧 + OCR（**必须先 snap**：band 裁图要帧对上 ✓）

    ⭐ v1.84：**开头先查停止位** —— 停了立刻返回 []，
      让所有下游判据自然失效（读不到文字 ⇒ 不点、不磨）⇒ 这是「立即停止」的主闸门 ✓
    """
    if _stopped():
        return []
    try:
        b.snap(tag)
    except Exception:       # noqa: BLE001
        pass
    return b.ocr(min_conf=min_conf, band=band, tag=tag) or []


# ── 界面判据常量（照抄 PC `guild_common.py:114-118`，逐字一致 ✓）──
#
# ⛔ v1.94【**这三个常量在手机端丢了** —— 真机日志铁证】
#   日志：`NameError: name GUILD_CORNERS is not defined`
#   ⇒ 公会日常 / 免费招募 / 天赋果实 **三个功能全崩**
#   （`enter_error` / `recruit_error` / `fruit_error` 各一条）✗✗
#   ---- 为什么会丢 ----
#     我在某次插入新函数时，**整块 300 行代码被复制成了两份**
#     （18 个函数重复定义，第一份在 281 行、第二份在 722 行），
#     而这三个常量的定义正好落在被覆盖掉的区间里 ⇒ 消失 ✗
#     ⇒ 教训：**批量插入后必须查重复定义**（本轮已用脚本扫过，现无重复 ✓）
GUILD_CORNERS = ("攻略", "活动", "庆典福利", "机巧秘宝", "情报", "巅峰赛")
MENU_HINTS = ("进入地图", "快速扫荡", "星界秘境")
LOBBY_HINTS = ("免费指定招募", "角色招募", "限时招募开启")

def in_guild(items):
    """**公会展厅**判据：GUILD_CORNERS 里**至少 2 个**整条命中 ✓

    ⚠ 为什么要求 ≥2：单个「情报」二字在别处也出现（HUD/公告）⇒ 会误判 ✗
    """
    ts = _texts(items)
    return sum(1 for k in GUILD_CORNERS if any(k == t for t in ts)) >= 2


def in_menu(items):
    return has(items, *MENU_HINTS)


def in_lobby(items):
    return has(items, *LOBBY_HINTS)


def where_am_i(items):
    if in_guild(items):
        return "公会展厅"
    if in_menu(items):
        return "选图界面"
    if in_lobby(items):
        return "大厅"
    return "未知界面"


# ══════════════════════════════════════════════════════════════════════
# ⭐⭐⭐ v1.78【**文字优先 → 坐标兜底**：本文件所有点击的唯一入口】
#
#   为什么必须这样做（项目既有硬规矩，不是我加的）：
#     · `tools/audit_hardcoded_coords.py` 的口径把常量分成
#       `ref`（过 RefMapper 自适应）/ `dlg`（弹窗系，锚屏幕中心）/ `devpx`（**换分辨率必错** ✗）
#     · 既有代码（`bag_upgrade` / `use_supply`）早就写成
#       「**文字 → 模板 → 锚点坐标**」，并**明确要求「文字优先」**（`explore_loop:2798`）
#     · 而锚点坐标**只允许在「已确认的那个界面上」使用**（同处注释原话）
#
#   ⇒ 本函数把那条规矩落成一处实现，避免每个调用点各写一遍（也会各漏一遍 ✗）：
#     ① 这一帧里**正好读到**目标文字 ⇒ 点它（真自适应 ✓）
#     ② 读不到 ⇒ **才**用锚点坐标，并**如实记日志**（`by='fallback'`）
#     ③ `probe` 给了就先确认「现在在不在该界面」，不在 ⇒ **一下都不点** ✓
#
#   ⚠ 锚点坐标仍然保留**兜底**价值：OCR 读不到（低对比度/被遮挡/字体异常）时总得能点一下，
#     否则整条流程直接死掉。但它从「主路径」降级成了「兜底路径」✓
#   ⚠ 所有锚点常量都是 **1080×1920 参考系**，经 `b.tap()` / `b.tap_dlg()` 有 RefMapper 换算；
#     但它们**不是**从屏幕实测反推的 ⇒ 换机型时**精度不如 OCR** ⇒ 所以只能兜底 ✓
def tap_target(b, items, labels, anchor_xy, log=None, tag='', wait=1.2,
               probe=None, use_dlg=False):
    """点「文字命中处」，读不到才退回锚点坐标 -> (x, y, src)

    labels   : 要认的文字元组（**整条相等**，与既有 `bag_upgrade` 口径一致 ✓）
    anchor_xy: 兜底坐标（1080×1920 参考系）
    probe    : 给了就先要求 `has(items, *probe)` 成立，否则**一下都不点** ✓
    use_dlg  : 走弹窗系（面板锚屏幕中心）还是棋盘系（顶块锚顶+其余锚底）
    """
    if isinstance(labels, str):
        labels = (labels,)
    if probe and not has(items, *probe):
        _log(log, {tag or 'tap': 'probe_miss', 'probe': list(probe),
                   'note': '不在目标界面 ⇒ 不盲点'})
        return (None, None, 'probe_miss')

    hit = None
    for it in (items or []):
        if str(it.get('text') or '').strip().replace(' ', '') in labels:
            hit = it
            break
    if hit is not None:
        # ⛔⛔ v1.83 **OCR 坐标是归一化帧，tap_dlg 要弹窗系 ⇒ 必须 +C** ✗
        #   这一行就是「点不到一键派遣」的真根因（偏 C=209.4 参考像素 ≈248 设备像素）
        if use_dlg:
            x, y, _src = _tap_item_dlg(b, hit, wait=wait)
        else:
            x, y = int(hit['cx']), int(hit['cy'])
            _tap_xy(b, x, y, wait, use_dlg=False)
            _src = 'ocr'
        _log(log, {tag or 'tap': 'by_text', 'text': hit.get('text'),
                   'at': (x, y), 'src': _src})
        return (x, y, _src)

    if not anchor_xy:
        _log(log, {tag or 'tap': 'miss', 'labels': list(labels),
                   'note': '文字没读到、也没给兜底坐标 ⇒ 不盲点'})
        return (None, None, 'miss')
    x, y = int(anchor_xy[0]), int(anchor_xy[1])
    _tap_xy(b, x, y, wait, use_dlg)
    _log(log, {tag or 'tap': 'by_anchor', 'labels': list(labels), 'at': (x, y),
               'note': '文字没读到 ⇒ 锚点兜底（换机型时精度不如 OCR ✓）'})
    return (x, y, 'fallback')


def _tap_xy(b, x, y, wait=1.2, use_dlg=False):
    """统一出口：按坐标系选 `tap` 还是 `tap_dlg`（**两者 y 映射不同，别混** ✓）

    ⛔⛔⛔**【最重要的注释，别删】** —— 归一化帧坐标 ≠ 弹窗系坐标，差 C！
      · `ocr_items()` / `b.ocr()` 返回的是 **归一化帧** 坐标（`RefMapper.toRef` 的产物）
      · `tap_dlg()` 要的是 **居中弹窗系** 坐标
      · 两者差 `C = RefMapper.dialogShift()`：**真机 1280×2772 ⇒ C=209.4**，9:16 屏 ⇒ 0
      ⇒ 直接 `tap_dlg(归一化cx, 归一化cy)` 会**偏 C 个参考像素**（≈248 设备像素）✗✗
      ---- 我真机上就是这么栽的（用户报「打开派遣面板点不到一键派遣」）----
        一键派遣真机 dev y=2300 ⇒ 归一化帧 1521.8 ／ 弹窗系 1731.2
        我拿 1521.8 喂 tap_dlg ⇒ 落在 dev 2052 ⇒ **差 248px，点空** ✗
      ---- 正确用法 ----
        要拿**归一化帧的 OCR 条目**去点弹窗：先 `dlg_items(items)`（cy+C）再 tap_dlg ✓
        本项目别处（`buypanels`）一直这么用，是我漏了 ✗
      ⇒ 所以下面专门提供 `_tap_item_dlg()`：**传条目进来**，内部自己换算 ✓
    """
    if _stopped():
        return False           # ⏹ 已停止 ⇒ **一下都不点**（最后一道闸门）✓
    if use_dlg and hasattr(b, 'tap_dlg'):
        return b.tap_dlg(x, y, wait=wait)
    return b.tap(x, y, wait=wait)


def _tap_item_dlg(b, it, wait=1.2, anchor=None):
    """点一个**归一化帧的 OCR 条目**所在的弹窗位置 -> (x, y, src)

    ⚠ 内部做 `+C` 换算（弹窗系 = 归一化帧 + `dlg_shift()`）—— 见 `_tap_xy` 的长注释 ✓
    ⚠ `it` 为 None ⇒ 用 `anchor`（**已是弹窗系**常量）兜底 ✓
    """
    if it is not None:
        try:
            _cx = int(it['cx'])
            _cy = int(it['cy']) + int(round(_dlg_c()))
        except Exception:       # noqa: BLE001
            _cx = _cy = None
        if _cx is not None:
            _tap_xy(b, _cx, _cy, wait=wait, use_dlg=True)
            return (_cx, _cy, 'ocr+C')
    if anchor:
        _ax, _ay = int(anchor[0]), int(anchor[1])
        _tap_xy(b, _ax, _ay, wait=wait, use_dlg=True)
        return (_ax, _ay, 'anchor')
    return (None, None, 'miss')


def _dlg_c():
    """取 `C = RefMapper.dialogShift()`（归一化帧 → 弹窗系 的 y 偏移）✓"""
    try:
        import mapbot as _mb
        return float(_mb.dlg_shift())
    except Exception:       # noqa: BLE001
        return 0.0


def _sleep(b, sec):
    """⭐ **可被「停止」中断** 的 sleep（v1.82）
    ⛔ 病（用户报：「我点停止不能立即停止脚本」）：
      我在 guild_daily/recruit/ads 里全用了 `time.sleep()`（纯 Python 等待），
      而 Java 侧的 `requestInterrupt()` **只踹得动 wait 循环**，管不到 time.sleep ⇒
      用户点 ■ 之后脚本还要干等 1~3 秒（扫楼层时累计几十秒）⇒ 看起来「停不下来」✗
    ⇒ 一律走 `b._sleep()`（`mapbot.py:419` 的实现：切 0.1s 一片，每片查一次停止位 ✓）
    ⚠ 拿不到 bot（测试桩/异常）⇒ 退回 time.sleep，**不让它崩** ✓
    """
    try:
        b._sleep(sec)
        return
    except Exception:       # noqa: BLE001
        pass
    time.sleep(sec)



def in_map_now(items):
    """现在是不是**在图里**（图内底部有「结束冒险」；选图列表带 [N] 后缀 ✓）"""
    if has(items, "结束冒险"):
        return True
    return any(re.match(r"^.+\[\d+\]\s*$", t) for t in _texts(items))


def swipe_abs(b, x1, y1, x2, y2, ms=1200, wait=0.9):
    """滑屏 —— **手机端走无障碍手势**（PC 走 adb shell input swipe）

    ⚠ 不让调用方碰 adb：两端签名保持一致，只有实现不同 ✓
    """
    try:
        b.swipe(x1, y1, x2, y2, ms=ms, wait=wait)
    except Exception as _e:     # noqa: BLE001
        _say("   ⚠ 滑动失败（%r）⇒ 跳过这一次" % (_e,))
        return False
    return True


def goto_guild(b, log=None, tries=3):
    """走到**公会展厅**（已在就直接 return True）

    ⚠ PC 口径（踩过的）：**不能只靠底部导航坐标** —— 大厅里点「开始冒险」会开图，
      必须先判「我现在在哪」，大厅就先回选图界面，再点「公会」✓
    """
    for k in range(tries):
        items = ocr_items(b, tag="gg%d" % k)
        if in_guild(items):
            return True
        if in_lobby(items):
            # ⭐ 大厅里先回选图界面 —— **「开始冒险」优先按文字找**（NAV_START 只兜底）
            tap_target(b, items, ("开始冒险",), NAV_START, log=log,
                       tag="guild_leave_lobby", wait=2.5)
            _log(log, {"guild": "leave_lobby"})
            continue
        _where = where_am_i(items)
        # ⭐⭐ **文字优先**：底部导航「公会」二字在选图界面清清楚楚 ⇒ 直接点它 ✓
        #   读不到才退回 NAV_GUILD（底栏 x 恒定、锚底 y ⇒ 有换算，但精度不如 OCR ✓）
        tap_target(b, items, ("公会", "公會"), NAV_GUILD, log=log,
                   tag="guild_tap_nav", wait=3.0)
        _log(log, {"guild": "tap_nav", "at": NAV_GUILD, "try": k, "from": _where})
        items2 = ocr_items(b, tag="gg%d_b" % k)
        if in_guild(items2):
            if _where != "公会展厅":
                _say("   ✓ 从「%s」点公会 ⇒ 已到公会展厅" % _where)
            return True
        _say("   · 点了公会但还不像公会展厅（认到 %s）" % (_texts(items2)[:8],))
    return in_guild(ocr_items(b, tag="gg_f"))


def leave_guild(b, log=None):
    """回**选图界面**（点底部「开始冒险」）—— 返回是否真的到了 ✓

    ⚠ PC 口径（用户原话）：「**这三个脚本的最后都要回到地图界面**」
      ⇒ 每个子流程做完都调它一次，**位置可预测** ✓
    """
    # ⭐ 公会展厅底部有「开始冒险」⇒ **文字优先**，读不到才用 NAV_START 兜底 ✓
    #   ⚠ 先取一帧**当判据**（这一帧就是要点的那个画面）
    _it0 = ocr_items(b, tag="leave0")
    tap_target(b, _it0, ("开始冒险", "进入地图", "快速扫荡"), NAV_START,
               log=log, tag="guild_leave", wait=2.5)
    _log(log, {"guild": "leave", "at": NAV_START})
    items = ocr_items(b, tag="leave")
    return in_menu(items) or in_map_now(items)


def scroll_to_top(b, log=None, times=None, max_swipes=8):
    """滚到**顶层/高层**（炼金那层在 4 楼顶楼 —— 手指下滑 = 看更高层 ✓）"""
    n = int(times) if times is not None else (FLOOR_SWIPES + 2)
    for _ in range(max(1, min(n, max_swipes))):
        swipe_abs(b, *SWIPE_UP_XY)
        _sleep(b, 0.9)
    _log(log, {"guild": "scroll_top", "n": n})
    return True


def _guild_has(items, *labels):
    """同 has（保留别名，便于与 PC 代码逐行对照）"""
    return has(items, *labels)


def close_panel(b, at, tag, probe_texts=(), log=None, tries=2):
    """点 X 关面板并**验证**（probe_texts 还在 ⇒ 没关掉，重试 ✓）

    ⚠ PC 口径：**关不掉要如实说**，别假装成功（本项目反复栽在这上面 ✗）
    """
    for k in range(tries):
        # ⭐ 关闭符优先按文字找（× / X / 关闭）—— 面板 X 的位置随面板宽度变，
        #   写死坐标换机型就点空 ✗（PC 记过同类教训：面板 X 在弹性区、归一化帧看不见）
        _it = ocr_items(b, tag="%s_pre%d" % (tag, k))
        tap_target(b, _it, ("×", "X", "x", "✕", "✖", "关闭"), at,
                   log=log, tag="close_%s" % tag, wait=1.8, use_dlg=True)
        if not probe_texts:
            _log(log, {"close": tag, "verified": None})
            return True
        items = ocr_items(b, tag="%s_c%d" % (tag, k))
        if not has(items, *probe_texts):
            _log(log, {"close": tag, "verified": True, "try": k + 1})
            return True
        _say("   · 点 X 后面板还在（%s）⇒ 再试一次" % (tag,))
    _log(log, {"close": tag, "verified": False, "tries": tries})
    _say("   ⚠ 关面板没成功（%s）⇒ 如实记录，交给上层兜底" % (tag,))
    return False


def _dismiss_popup(b, log=None, tag="popup"):
    """点掉奖励/确认弹窗（**优先 OCR 找「返回/确定」**，4 轮；找不到不盲点 ✓）"""
    for k in range(4):
        items = ocr_items(b, tag="%s_%d" % (tag, k))
        it = find(items, "返回", "确定")
        if it:
            b.tap(it["cx"], it["cy"], wait=1.8)
            _log(log, {"popup_dismiss": "ocr", "text": it["text"],
                       "at": (it["cx"], it["cy"]), "try": k + 1})
            _say("         · 点掉弹窗「%s」(%d,%d)（OCR 现读 ✓）"
                 % (it["text"], it["cx"], it["cy"]))
            return True
        _sleep(b, 0.8)
    _log(log, {"popup_dismiss": "miss", "note": "4 轮没读到「返回/确定」⇒ 不盲点"})
    return False



# ══════════════════════════════════════════════════════════════════════
# ③ 派遣任务（公会展厅 2 楼「黑晶女仆」那 4 把椅子）—— PC guild_tasks.py
# ══════════════════════════════════════════════════════════════════════
# 用户口径（PC 原文，**权威**）：
#   · 「**不用放弃**」  ⇒ 绝不点「放弃」（每日限 3 次，浪费）
#   · 「**不召回**」    ⇒ 绝不点「召回」（会清空任务进度）
#   · 「这些我打算是**体力刷完自动去做**」
#
# 干什么：把 4 把椅子全部弄成「**进行中**」：
#     未接(?)      ⇒ 开面板 → 一键派遣 → 开始任务   （**两下**）
#     已完成(!)    ⇒ 领奖 → 椅子**换成新任务** → **回头再派一次** ← ⛔ PC 第一轮漏了这步
#     进行中(倒计时) ⇒ 什么都不做
#
# ⛔⛔ PC 用户当场抓到的漏洞（原文）：「另外俩这么只领取了奖励，**没有派遣**」——
#   PC 第一轮 walk 是「椅1→椅2→椅3→椅4，每把只点一下」，而椅 2/3/4 当时是**已完成**：
#   点一下 = **领奖**，领完椅子立刻**换成新任务**（回到 ?），可**我没回头再点它** ✗
#   ⇒ 新任务就**一直挂着没派出去**。
#   ⇒ 修法：领完 **continue 循环**（回头再点同把椅子，这次才是派）✓
FREE, BUSY, DONE, UNKNOWN = "free", "busy", "done", "unknown"


# ══════════════════════════════════════════════════════════════════════
# 气泡定位（**模板匹配**）—— 用户口径：「不能固定坐标啊，识别气泡」
# ══════════════════════════════════════════════════════════════════════
# 三种气泡状态（真机实测，都在小人**头顶**同一行 refY≈540）：
#   · `?`  问号  ⇒ 空闲，可直接点小人派遣 ✓
#   · `!`  感叹号 ⇒ **有奖待领** ⇒ 先点小人领取，再点一次派遣 ✓
#   · 倒计时 `HH:MM:SS` ⇒ 进行中，不动它 ✓
#
# ⚠⚠ 为什么用**模板**而不是 OCR：气泡里的符号是**美术图形**（问号/感叹号），
#   端侧 OCR **读不出** ⇒ 只能用模板。而倒计时是文字 ⇒ 那条仍走 OCR ✓
def find_bubbles(b, log=None, tag="bb"):
    """模板匹配找**所有**气泡 -> [(dev_x, dev_y, score), ...]（按 x 排序）

    ⚠ 返回的是**参考系坐标**（`b.img()` 就是 1080×1920 归一化帧）✓
    ⚠ 找不到 ⇒ 返回 []（下游如实报错，**不硬凑坐标** ✗）
    """
    import cv2
    try:
        img = b.img()
    except Exception as _e:       # noqa: BLE001
        _log(log, {"task": "bubble_img_fail", "err": repr(_e)})
        return []
    if img is None:
        return []
    tpl = _load_bubble_tpl()
    if tpl is None:
        _log(log, {"task": "bubble_tpl_missing", "tpl": BUBBLE_TPL})
        return []
    th, tw = tpl.shape[:2]
    y_lo, y_hi = BUBBLE_ROI_Y
    y_hi = min(y_hi, img.shape[0])
    roi = img[y_lo:y_hi, :]
    if roi.shape[0] < th or roi.shape[1] < tw:
        return []
    res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
    r = res.copy()
    out = []
    while True:
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx < BUBBLE_SCORE_MIN:
            break
        out.append((loc[0] + tw // 2, y_lo + loc[1] + th // 2, round(float(mx), 3)))
        # 抑制邻域（避免同一个气泡被重复命中）
        x0 = max(0, loc[0] - tw // 2)
        x1 = min(r.shape[1], loc[0] + tw // 2)
        y0 = max(0, loc[1] - th // 2)
        y1 = min(r.shape[0], loc[1] + th // 2)
        r[y0:y1, x0:x1] = 0
    out.sort()
    _log(log, {"task": "bubbles_found", "n": len(out),
               "pts": [(p[0], p[1], p[2]) for p in out]})
    return out


_BUBBLE_TPL_CACHE = {}


def _tpl_match(img, tpl, thr=0.70, roi=None):
    """在归一化帧上做模板匹配 -> [(cx, cy, score), ...]（按分数降序，已抑制邻域）

    ⚠ 入参 `img` / `tpl` 都是**归一化帧坐标系**（1080×1920）✓
    ⚠ `roi=(y0, y1)` 只在该纵向带内找（避开 HUD / 底栏误匹配）✓
    """
    import cv2
    if img is None or tpl is None:
        return []
    th, tw = tpl.shape[:2]
    y_off = 0
    sub = img
    if roi:
        y_off = max(0, int(roi[0]))
        y_hi = min(int(roi[1]), img.shape[0])
        sub = img[y_off:y_hi, :]
    if sub.shape[0] < th or sub.shape[1] < tw:
        return []
    res = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
    r = res.copy()
    out = []
    while True:
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx < thr:
            break
        out.append((loc[0] + tw // 2, y_off + loc[1] + th // 2, round(float(mx), 3)))
        x0 = max(0, loc[0] - tw // 2)
        x1 = min(r.shape[1], loc[0] + tw // 2)
        y0 = max(0, loc[1] - th // 2)
        y1 = min(r.shape[0], loc[1] + th // 2)
        r[y0:y1, x0:x1] = 0
    out.sort(key=lambda t: -t[2])
    return out


_TPL_CACHE = {}


def _load_tpl(name):
    """载入 templates/<name>（带缓存；找不到返回 None 并留日志）✓"""
    if name in _TPL_CACHE:
        return _TPL_CACHE[name]
    import cv2
    import os as _os
    tpl = None
    for base in _tpl_dirs():
        p = _os.path.join(base, name)
        if _os.path.exists(p):
            tpl = cv2.imread(p)
            if tpl is not None:
                _say("   ✓ 模板载入：%s（%dx%d）"
                     % (p, tpl.shape[1], tpl.shape[0]))
                break
    _TPL_CACHE[name] = tpl
    return tpl

def _load_bubble_tpl():
    """载入气泡模板（带缓存；找不到就返回 None 并留日志）✓"""
    if "tpl" in _BUBBLE_TPL_CACHE:
        return _BUBBLE_TPL_CACHE["tpl"]
    import cv2
    import os as _os
    tpl = None
    for base in _tpl_dirs():
        p = _os.path.join(base, BUBBLE_TPL)
        if _os.path.exists(p):
            tpl = cv2.imread(p)
            if tpl is not None:
                _say("   ✓ 气泡模板载入：%s（%dx%d）" % (p, tpl.shape[1], tpl.shape[0]))
                break
    _BUBBLE_TPL_CACHE["tpl"] = tpl
    return tpl


def _tpl_dirs():
    """模板搜索目录（**资源包优先**，其次外置可写目录 —— 与 fixed_ref 同序 ✓）

    ⚠ 必须**多路兜底**：真机走 `fixed_ref.tpl_dirs()`；
      单测/PC 对拍时没有 fixed_ref ⇒ 退 `MAPBOT_ROOT/templates`；
      再退 **本文件所在目录的 ../templates**（源码树里也能找到）✓
    """
    import os as _os
    ds = []
    try:
        import fixed_ref
        ds = list(fixed_ref.tpl_dirs())
    except Exception:       # noqa: BLE001
        pass
    root = _os.environ.get("MAPBOT_ROOT") or ""
    if root:
        ds.append(_os.path.join(root, "templates"))
    # 相对本文件：app/src/main/python/../.. = app/src/main ；资源在 assets/mapbot_pack/templates
    # ⚠ 不用 `__file__`：Chaquopy 里模块可能没有 __file__ ⇒ NameError（门禁 ⑰e 抓过 ✓）
    _here = ""
    try:
        import sys as _sys
        _here = _os.path.dirname(_os.path.abspath(_sys.argv[0] or ""))
    except Exception:       # noqa: BLE001
        _here = ""
    if not _here:
        _here = _os.getcwd()
    ds.append(_os.path.join(_here, "..", "..", "assets", "mapbot_pack", "templates"))
    ds.append(_os.path.join(_here, "templates"))
    return ds


def person_of_bubble(bx, by):
    """气泡中心（**参考系**）-> 小人可点位置（**参考系**）

    ⭐ v1.87 简化：`b.img()` 给的就是 1080×1920 归一化帧 ⇒ 两边同系，**直接加偏移** ✓
      （第一版多此一举地做 kx/shift 换算，还把分段判反了 ⇒ 回算差 621 ✗）

    ⚠ 实测：小人本体在气泡**正下方约 106 参考像素**
      （气泡 refY=540；点小人 dev 1215 ≡ refY 606 ⇒ 差 66；取 106 更居中落在身体上）
    """
    return (float(bx), float(by) + BUBBLE_DY_REF)



# ══════════════════════════════════════════════════════════════════════
# ③ 派遣任务（公会展厅 2 楼「黑晶女仆」那 4 把椅子）—— PC guild_tasks.py
# ══════════════════════════════════════════════════════════════════════
# 用户口径（PC 原文，**权威**）：
#   · 「**不用放弃**」  ⇒ 绝不点「放弃」（每日限 3 次，浪费）
#   · 「**不召回**」    ⇒ 绝不点「召回」（会清空任务进度）
#   · 「这些我打算是**体力刷完自动去做**」
#
# 干什么：把 4 把椅子全部弄成「**进行中**」：
#     未接(?)      ⇒ 开面板 → 一键派遣 → 开始任务   （**两下**）
#     已完成(!)    ⇒ 领奖 → 椅子**换成新任务** → **回头再派一次** ← ⛔ PC 第一轮漏了这步
#     进行中(倒计时) ⇒ 什么都不做
#
# ⛔⛔ PC 用户当场抓到的漏洞（原文）：「另外俩这么只领取了奖励，**没有派遣**」——
#   PC 第一轮 walk 是「椅1→椅2→椅3→椅4，每把只点一下」，而椅 2/3/4 当时是**已完成**：
#   点一下 = **领奖**，领完椅子立刻**换成新任务**（回到 ?），可**我没回头再点它** ✗
#   ⇒ 新任务就**一直挂着没派出去**。
#   ⇒ 修法：领完 **continue 循环**（回头再点同把椅子，这次才是派）✓
FREE, BUSY, DONE, UNKNOWN = "free", "busy", "done", "unknown"


# ══════════════════════════════════════════════════════════════════════
# 气泡符号识别 —— **用户口径的核心**
# ══════════════════════════════════════════════════════════════════════
# 用户原话（唯一权威）：
#   「**小人头上是问号就是能直接点下面的小人进行派遣**，
#     **是感叹号就需要先点下面对应的小人领取，然后再点那个小人进行派遣**」
#
# 三种气泡状态（真机截图实测，都在小人**头顶** refY≈501 那一行）：
#   · `?`  问号（白/蓝/紫底）⇒ 空闲，可直接派遣 ✓
#   · `!`  感叹号（通常带绿/红底）⇒ **有奖待领** ⇒ 先点小人领取，再点一次派遣 ✓
#   · 倒计时 `HH:MM:SS` ⇒ 进行中，不动它 ✓
#
# ⚠⚠ **为什么必须按气泡判，而不能只看面板**：
#   面板打开后**两种状态长得几乎一样**（都有「完成悬赏」和奖励格），
#   靠面板文字分不出「该领奖」还是「该派遣」⇒ 只能回到楼层看气泡符号 ✓
#   （这正是用户特意交代这条的原因）
def chair_timers(items, bubbles=None):
    """4 个小人各自的**倒计时** -> {序号(1..4): "HH:MM:SS"}

    ⭐ v1.86：归属基准从「**写死的椅子坐标常量**」改成「**模板找到的气泡 x**」
      · `bubbles` 给了 ⇒ 把倒计时文字归到**最近的气泡**上（容差按气泡间距自适应）✓
      · `bubbles` 没给（兼容旧调用）⇒ 退回「只按 y 带筛，序号按 x 排序」
      ⇒ **不再依赖任何写死坐标** ✓

    ⚠ PC 的算法（原文保留）：倒计时文字可能被 OCR 断成半截，所以按**字符在整条文本里的
      相对位置**推 cx（x0 + frac*(x1-x0)），再归到最近的椅子 x 上 ✓
      写死 cx 会把长倒计时判到隔壁椅子 ✗
    """
    out = {}
    y0, y1 = BUBBLE_Y0 - 25, BUBBLE_Y1 + 25
    if bubbles:
        xs = sorted(float(bb[0]) for bb in bubbles)
        tol = _s(80)
        if len(xs) >= 2:
            gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
            tol = max(_s(45), min(gaps) * 0.6)
    else:
        xs = []
        tol = _s(80)
    for it in (items or []):
        cy = it.get("cy", 0)
        if not (y0 < cy < y1):
            continue
        t = str(it.get("text") or "").replace(" ", "").replace("：", ":")
        for m in re.finditer(r"(\d{1,2}:\d{2}:\d{2})", t):
            frac = (m.start() + m.end()) / 2.0 / max(1, len(t))
            x0 = it.get("x0", it.get("cx", 0))
            x1 = it.get("x1", it.get("cx", 0))
            cx = x0 + frac * (x1 - x0)
            if xs:
                k = min(range(len(xs)), key=lambda i: abs(xs[i] - cx))
                if abs(xs[k] - cx) <= tol:
                    out.setdefault(k + 1, m.group(1))
            else:
                out.setdefault(len(out) + 1, m.group(1))
    return out

def chair_state(b, items, idx):
    """某把椅子的状态 -> (state, timer)"""
    t = chair_timers(items).get(idx)
    if t:
        return BUSY, t
    return UNKNOWN, ""


def task_panel_open(items):
    """派遣面板开着吗

    ⛔⛔ v1.88【**真机事故：面板明明开着，脚本说没开**】
      ---- 病 ----
      旧判据是「**唯一**判据 = `黑晶女仆` 整条命中」（照 PC 原文抄的）。
      真机实测（`now2.png` 跑 OCR 34 条）：**「黑晶女仆」这一条根本没被读到** ✗
        · 它是左上角大标题，压在黑晶女仆立绘上 ⇒ 端侧 OCR 这一帧漏检
      ⇒ `task_panel_open()` 返回 False ⇒ `_ensure_dispatched` 走 `panel_miss`
        ⇒ 一直"没开出面板 ⇒ 重试"⇒ **面板开着却永远不点** ✗✗
      （用户报：「**打开派遣界面不点一键派遣**」—— 正是这个）
      ---- 修法 ----
      ① **多判据**（任一条命中即算开）：`黑晶女仆` / `完成悬赏` / `采集物资`
         —— 实测 `采集物资` conf=1.00、`剩余时间：` conf=0.94，都稳定读得到 ✓
      ② 「黑晶女仆」仍**保留**（读到时最快最准）
      ③ 但**标题不是必要条件** —— 面板里那些专有词同样唯一 ✓
      ⚠ 为什么敢放宽：这些词在游戏别处**不会同时出现**（`采集物资`/`完成悬赏`
        只在派遣面板里；`黑晶女仆` 读不到时它们必有一个在）✓
    """
    if has(items, "黑晶女仆", exact=True):
        return True
    # 面板内专有词（实测稳定可读）—— 任一命中即算面板开着
    for _k in ("完成悬赏", "采集物资", "派遣角色位阶"):
        if has(items, _k):
            return True
    return False


def panel_action(items):
    """面板底部那颗主按钮现在是什么 -> (act, label)

    ⚠ **顺序**（PC 同款，别调）：先「开始任务」（= 已选好人，下一步就是提交）
      再「派遣」（= 还没选人）最后「召回」（**不点**）✓

    ⛔⛔ v1.81【**真机事故：只领奖、不派遣**】—— 用户报：「派遣只领取了，不能正常派遣」
      ---- 病 ----
      这里原来只认 `一键派遣` / `键派遣` **两个整串**，而**真机上那颗按钮的文字会变**：
        · 未选人时 OCR 实测读到 **`键派遣`**（"一键"的"一"被切掉，既有代码 `explore_loop:6050` 记着）
        · 选完人之后变成 **`开始探索`**（同一个位置，第二步 ✓）
      ⇒ `panel_action` 认不到 ⇒ 返回 `("unknown","")` ⇒ 调用方直接 `break`
      ⇒ **一次都没点派遣** ⇒ 椅子停在"已领奖、新任务挂着" ⇒ 正是用户看到的现象 ✗✗
      ---- 为什么以前没暴露 ----
      PC 端那段是 **硬点固定坐标 `TASK_ACTION_BTN`**（不看文字）⇒ 文字对不对都能点上；
      我为了"文字优先"改成先认文字，却把**别名表**写窄了 ⇒ **改良没改成** ✗
      ---- 修法（照抄既有代码 `explore_loop:6069` 的口径）----
      ① **子串匹配**（不是整条相等）：`派遣` / `开始探索` 都算 ✓
         ⚠ 这句判据安卓端早就在用：`(“派遣” in t or “开始探索” in t) and “预计时间” not in t`
      ② **排除 `预计时间`** —— 面板上那行说明文字里也含「派遣」二字，
         不排掉就会点到说明文字上（既有代码踩过 ✓）
    """
    # 先判「开始任务」（已选好人，下一步是提交）—— 别被"派遣"分支抢走
    it = find(items, "开始任务")
    if it:
        return "submit", it["text"]
    # 再判「派遣 / 开始探索」（**子串**，且排除说明文字）
    for _it in (items or []):
        _t = str(_it.get("text") or "").replace(" ", "")
        # ⛔⛔ v1.88【**认错按钮** —— 真机实测抓到】
        #   面板上有两行 `※` 开头的**说明文字**都含"派遣"：
        #     `※派遣角色位阶需要不低于发起人`（conf 0.96，refY 942）← **先命中这行** ✗
        #     `※每派遣一名角色可缩短10%任务时间`（conf 0.95）
        #   而真按钮「一键派遣」在 refY 1526 ✓
        #   ⇒ 旧判据点到了**说明文字**上 ⇒ 当然没反应 ✗✗
        #   ---- 修法：三重排除 ----
        #     ① 以 `※`/`*` 开头 ⇒ 说明文字（实测面板里所有说明行都是这个前缀）
        #     ② 含 `预计时间` ⇒ 说明文字
        #     ③ 长度 > 6 ⇒ 真按钮最多 4 字（一键派遣/开始任务/召回/放弃）
        if _t.startswith(("※", "*", "「※")):
            continue
        if "预计时间" in _t:
            continue
        if len(_t) > 6:
            continue
        if ("派遣" in _t) or ("开始探索" in _t):
            return "dispatch", _it["text"]
    it = find(items, "召回")
    if it:
        return "recall", it["text"]
    return "unknown", ""


def panel_state(items):
    """派遣面板的三态 -> no_panel / running / filled / free / other"""
    if not task_panel_open(items):
        return "no_panel"
    if has(items, "所需时间：", "所需时间:"):
        return "running"
    if has(items, "剩余时间：", "剩余时间:"):
        if has(items, "开始任务"):
            return "filled"
        # ⭐ v1.81：与 `panel_action` **同一份判据**（子串 + 排除说明文字 ✓）
        #   ⚠ 两边各写一套 = 迟早漂移（本项目记过账）⇒ 这里直接复用 act 的结论
        _act_now, _ = panel_action(items)
        if _act_now == "dispatch":
            return "free"
    return "other"


def read_counts(items):
    """面板上的「奖励数量」与「剩余/所需时间」-> (n, t)"""
    n = t = None
    it = find(items, "奖励数量")
    if it:
        m = re.search(r"(\d+)", it["text"])
        if m:
            n = int(m.group(1))
    it2 = find(items, "剩余时间", "所需时间")
    if it2:
        m2 = re.search(r"(\d{1,2}[:：]\d{2}[:：]\d{2})", it2["text"])
        if m2:
            t = m2.group(1)
    return n, t


def dismiss_reward(b, log, tag):
    """领奖后的结果弹窗 —— 一律走 OCR（PC 用户口径：「返回都不用按固定坐标点的」✓）"""
    return _dismiss_popup(b, log, tag)


def _ensure_dispatched(b, log, idx, max_rounds=3, slot=None):
    """把**一把**椅子弄成「进行中」-> dispatched / already / failed

    ⚠ 核心是那个 continue（领奖后**回头再点同把椅子**）—— PC 第一轮漏了它，
      结果 3 把椅子只领了奖、新任务一直挂着 ✗（用户当场抓到）
    """
    # ⭐ v1.86：**先模板找气泡** ⇒ 由气泡位置推出小人位置（**不写死坐标** ✓）
    # ⛔⛔ v1.90【**编号 vs 空闲位次 搞混** —— 真机日志铁证】
    #   ---- 病 ----
    #     旧写法 `if idx - 1 >= len(bbs): return "no_bubble"` ⇒
    #     真机 21:48:40：椅1/椅2 已在跑 ⇒ 只剩 **2 个问号气泡**（椅3/椅4 的空位）⇒
    #     轮到椅3 时 `idx-1 = 2 >= 2` ⇒ 判"这号不存在" ⇒ **椅3/椅4 永远轮不到** ✗✗
    #   ---- 为什么错 ----
    #     气泡 = **当前空闲的槽位**（头顶是问号）
    #     已派出去的那几号**头顶是倒计时、没有问号气泡** ⇒ 气泡数天然少于 4 ✓
    #     所以「椅号」和「气泡下标」**不是一回事**，不能直接拿 idx-1 去索引 ✗
    #   ---- 修法 ----
    #     把 `bbs` 按 x 排序后，**第 1 个空闲气泡就是最左边那个空闲小人** ⇒
    #     由外层（`run_tasks`）把「这一号对应第几个空闲气泡」算好传进来：
    #       `_ensure_dispatched(b, log, idx, slot=k)`
    #     没传 slot（兼容旧调用）⇒ 退回"按 idx-1 猜"，但**越界时不再当不存在**，
    #     而是取**最右边那个空闲气泡**（总比不点强，且日志会记明白）✓
    bbs = find_bubbles(b, log=log, tag="eb%d" % idx)
    if not bbs:
        _log(log, {"task": "no_bubble", "chair": idx, "found": 0})
        _say("       · 椅%d：**一个气泡都没找到** ⇒ 这层不对或被遮挡，跳过" % idx)
        return "no_bubble"
    if slot is None:
        slot = idx - 1
    if slot < 0 or slot >= len(bbs):
        _log(log, {"task": "bubble_clamp", "chair": idx, "slot": slot,
                   "n": len(bbs), "note": "空闲气泡不够 ⇒ 取最后一个，别直接放弃"})
        _say("       · 椅%d：空闲气泡 %d 个，位次 %d 越界 ⇒ **取最后一个**"
             % (idx, len(bbs), slot))
        slot = len(bbs) - 1
    _bx, _by, _bsc = bbs[slot]
    x, _y_ref = person_of_bubble(_bx, _by)
    _log(log, {"task": "bubble_pick", "chair": idx, "slot": slot,
               "at": (_bx, _by), "n": len(bbs)})
    for rnd in range(max_rounds):
        if _stopped():
            _say("       · ⏹ 用户已停止 ⇒ 放弃这把椅子")
            return "stopped"
        # ⚠ 椅子是**美术**、没有文字可认 ⇒ 这里只能点坐标（**地板/椅子没有 OCR 判据**）。
        #   但 ① 坐标已过 RefMapper（锚底区 ⇒ 底栏上方所有元素都跟棋盘走 ✓）
        #      ② 点完**必须用倒计时验证**（`chair_timers` 读不到 ⇒ 如实记 failed ✗），
        #         所以「点空了」不会静默成功 ✓
        #   ⚠ 若要再稳，得给 4 把椅子各做一张模板 —— 本轮没做（见文档 §12 未做项）
        _tap_xy(b, x, _y_ref, wait=2.5)   # ⭐ 小人位置（气泡正下方）✓
        items = ocr_items(b, tag="ct%d_%d_open" % (idx, rnd))

        # ① 已完成 ⇒ 领奖（领完椅子**换成新任务** ⇒ continue 回头再派）
        if has(items, "恭喜获得"):
            _say("       · 椅%d：已完成 ⇒ **领奖** ✓（领完会换成新任务，下一轮再派）" % idx)
            _log(log, {"task": "claim", "chair": idx, "rnd": rnd})
            dismiss_reward(b, log, "ct%d_%d" % (idx, rnd))
            continue                       # ⛔ **关键：继续循环，回头再点它一次**

        if not task_panel_open(items):
            _log(log, {"task": "panel_miss", "chair": idx, "rnd": rnd,
                       "texts": _texts(items)[:10]})
            _say("       · 椅%d：没开出面板（认到 %s）⇒ 重试" % (idx, _texts(items)[:6]))
            _sleep(b, 1.0)
            continue

        st = panel_state(items)
        _log(log, {"task": "panel", "chair": idx, "rnd": rnd, "state": st})
        n, t = read_counts(items)

        # ② 进行中 ⇒ 什么都不做（**绝不点召回** ✓）
        if st == "running":
            _say("       · 椅%d：**进行中**（%s）⇒ 不动它 ✓" % (idx, t or "?"))
            close_panel(b, TASK_PANEL_X, "ct%d_x" % idx,
                        probe_texts=("黑晶女仆",), log=log)
            return "already"

        act, label = panel_action(items)
        _log(log, {"task": "act", "chair": idx, "action": act,
                   "label": label, "reward": n, "time": t})
        # ⛔ 只认到「召回」⇒ **不点**（用户口径：不召回 ✓），关掉走人
        if act == "recall":
            _say("       · ⚠ 椅%d 面板只认到「召回」⇒ **不点**，关掉走人" % idx)
            close_panel(b, TASK_PANEL_X, "ct%d_xr" % idx,
                        probe_texts=("黑晶女仆",), log=log)
            return "failed"

        # ③ 点主按钮（**最多 3 下**：一键派遣 → 开始任务）
        # ⭐⭐ 面板主按钮**文案三态**（一键派遣 / 开始任务 / 召回）⇒ **必须文字优先** ✓
        #   用户口径已经明确「不召回」⇒ 只认前两个文案，绝不点「召回」✗
        # ⭐⭐ v1.81：**点「OCR 认到的那一颗」**，不再用 `tap_target` 的整条相等匹配
        #   ⛔ 病（用户报「只领取不派遣」）：`tap_target` 是**整条相等**，而真机上按钮文字是
        #     `键派遣` / `开始探索` / `一键派遣` 几种变体 ⇒ 整条相等**认不到** ⇒ 回落锚点坐标；
        #     更糟的是 `probe` 一失配就 `return probe_miss` ⇒ 循环直接 break ⇒ 一次都不点 ✗✗
        #   ⇒ 现在：用 `panel_action()` 已经认到的那颗按钮的**真实 (cx,cy)** 直接点 ✓
        #     （这正是既有代码 `explore_loop:6049` 的做法：
        #       「改用 OCR 现读的按钮坐标，与分辨率无关、与文案变化无关」✓）
        # ⭐⭐⭐ v1.89【**用户口径：点完一键派遣 1 秒后，同位置再点一下**】
        #   ---- 用户原话 ----
        #     「**点完一键派遣 1s 后同位置要再点一下**」
        #   ---- 为什么这样对 ----
        #     「一键派遣」点下去 ⇒ 面板把 6 个角色槽填满 ⇒ 按钮**原地变成「开始任务」**
        #     （真机实测：奖励 1→6、时间 08:00:00→04:00:00、6 槽全填、按钮文案同时变）
        #     ⇒ 所以第二次点击**位置完全不变**，只是要等那 1 秒让按钮刷新完 ✓
        #   ---- 旧写法为什么不够好 ----
        #     旧代码点完还要**重新 OCR 一次**再找「开始任务」⇒
        #       · 多花 1.5~2 秒（真机 OCR 一次就是这么久）
        #       · 而且依赖 OCR 再认出「开始任务」——真机上它也可能漏检
        #         （同一帧「黑晶女仆」就漏过，见 task_panel_open 的长注释）✗
        #   ---- 新写法（快 + 稳）----
        #     ① 点「一键派遣」
        #     ② **原地等 1 秒**（用户给的数）
        #     ③ **同一坐标再点一下** ⇒ 提交「开始任务」
        #     ④ 之后仍**必须验证**（看到倒计时才算派出）——不看到就如实记未验证 ✓
        #   ⚠ 若第一下点的是「开始任务」（面板本来就是 filled 态）⇒ 一次就关掉，
        #     第二下会落在**已关闭的面板上**（点到公会背景）⇒ 所以第二下前要**先确认面板还开着** ✓
        _at = tuple(TASK_ACTION_BTN)
        _src2 = "anchor"
        _act_now, _lbl_now = panel_action(ocr_items(b, tag="ct%d_%d_p0" % (idx, rnd)))
        if _act_now == "unknown":
            _log(log, {"task": "act_unknown", "chair": idx, "rnd": rnd})
            _say("       · 椅%d：**认不出面板主按钮** ⇒ 不盲点，重试" % idx)
            _sleep(b, 1.0)
            continue
        # ① 第一下：用 OCR 现读到的坐标（认不到才回落锚点）
        _it0 = ocr_items(b, tag="ct%d_%d_b0" % (idx, rnd))
        _hit0 = None
        for _t0 in (_it0 or []):
            _s0 = str(_t0.get("text") or "").replace(" ", "")
            if _s0.startswith(("※", "*")) or "预计时间" in _s0 or len(_s0) > 6:
                continue
            if _act_now == "submit" and "开始任务" in _s0:
                _hit0 = _t0
                break
            if _act_now == "dispatch" and (("派遣" in _s0) or ("开始探索" in _s0)):
                _hit0 = _t0
                break
        if _hit0 is not None:
            _px, _py, _src2 = _tap_item_dlg(b, _hit0, wait=1.0)
            _at = (_px, _py)
        else:
            _px, _py = TASK_ACTION_BTN
            _tap_xy(b, _px, _py, wait=1.0, use_dlg=True)
            _at = (_px, _py)
            _src2 = "anchor"
        _log(log, {"task": "tap1", "chair": idx, "act": _act_now,
                   "label": _lbl_now, "at": list(_at), "src": _src2})
        _say("       · 椅%d：点「%s」(%d,%d) %s"
             % (idx, _lbl_now or "?", _at[0], _at[1],
                "（OCR 现读）" if _src2 != "anchor" else "（锚点兜底）"))

        # ② 等 1 秒（用户口径：「1s 后」）
        _sleep(b, 1.0)

        # ③ 第二下：**同一坐标**（面板还开着才点，否则会点到公会背景 ✗）
        _still = ocr_items(b, tag="ct%d_%d_s1" % (idx, rnd))
        if task_panel_open(_still):
            _act1, _lbl1 = panel_action(_still)
            _log(log, {"task": "tap2_pre", "chair": idx, "act": _act1,
                       "label": _lbl1})
            _say("       · 椅%d：面板还开着（按钮现在是「%s」）⇒ **同位置再点一下**"
                 % (idx, _lbl1 or "?"))
            _tap_xy(b, _at[0], _at[1], wait=2.5, use_dlg=True)
            _log(log, {"task": "tap2", "chair": idx, "at": list(_at)})
        else:
            _say("       · 椅%d：第一下就把面板关了 ⇒ 不用点第二下 ✓" % idx)
            _log(log, {"task": "tap2_skip", "chair": idx, "why": "panel_closed"})
        # ④ 验证：**看到倒计时才算派出去**（不看到就如实记「未验证」✓）
        _sleep(b, 1.2)
        items3 = ocr_items(b, tag="ct%d_%d_v" % (idx, rnd))
        if task_panel_open(items3):
            close_panel(b, TASK_PANEL_X, "ct%d_x2" % idx,
                        probe_texts=("黑晶女仆",), log=log)
            items3 = ocr_items(b, tag="ct%d_%d_v2" % (idx, rnd))
        tm = chair_timers(items3).get(idx)
        if tm:
            _status("排班 · 椅 %d 已派出 %s" % (idx, tm))
            _say("       · 椅%d：**已派出** ⇒ 倒计时 %s ✓" % (idx, tm))
            _log(log, {"task": "dispatched", "chair": idx, "timer": tm})
            return "dispatched"
        _say("       · 椅%d：点完了但**没看到倒计时** ⇒ 下一轮再看" % idx)
        _log(log, {"task": "dispatch_unverified", "chair": idx})
    return "failed"


def ensure_chair_floor(b, log=None, max_floors=5):
    """站到**2 楼（椅子那层）**—— 先试当前层，再往下找，最后往上找 ✓

    ⚠ PC 口径：**每层都先「点一下椅子 1 看有没有反应」**，而不是靠楼层号猜
      （楼层是滚动的，没有可靠楼层指示 ✓）
    """
    if _try_chair_floor(b, log):
        return True
    for i in range(max_floors):
        swipe_abs(b, *SWIPE_DOWN_XY)
        _sleep(b, 0.9)
        _log(log, {"guild": "floor_search_down", "n": i + 1})
        if _try_chair_floor(b, log):
            return True
    for i in range(max_floors * 2):
        swipe_abs(b, *SWIPE_UP_XY)
        _sleep(b, 0.9)
        _log(log, {"guild": "floor_search_up", "n": i + 1})
        if _try_chair_floor(b, log):
            return True
    _say("   ⚠ 上下都找过了，**没找到椅子那层**（如实返回 False，不硬凑）")
    _log(log, {"guild": "chair_floor_not_found"})
    return False


def _try_chair_floor(b, log=None):
    """点**第 1 个小人**试试：弹出「黑晶女仆」派遣面板 ⇒ 就是这层 ✓

    ⛔⛔ v1.85【**旧判据错到根本不可能成立**】—— 真机实测才看清：
      ---- 旧写法 ----
      点椅子 ⇒ 看有没有「恭喜获得」或「黑晶女仆」**文字**
      ---- 为什么永远 False ----
      ① 手机端**没有椅子**（PC 的美术是椅子，手机是**小人**）⇒ 点的是半空 ✗
      ② 真机 OCR 这一层（refY 300~900）**一条文字都没有**（实测 34 条里零命中）
         ⇒ 即使点中了，`黑晶女仆` 也要**面板弹出后**才认得 ⋯ 但旧代码点空就不会弹 ✗
      ③ 于是必然 `chair_floor_not_found` ⇒ 派遣**从来没开始过**（真机日志铁证）✗✗
      ---- 现在（照用户口径）----
      点小人 ⇒ 面板应当弹出 ⇒ `task_panel_open()` 认得「黑晶女仆」/「完成悬赏」⇒ True ✓
      面板开着就说明**这层对了**，然后**关掉**（后面要逐个椅子处理）✓
    """
    try:
        # ⚠ 小人也是**美术**（没有文字）⇒ 这里只能点坐标；
        #   但 ① 坐标已按真机截图实测（dev 465,1215 ⇒ ref 392,756）
        #      ② 点完**必须验证**（`task_panel_open`）⇒ 点空会返回 False，探层继续 ✓
        # ⭐ v1.86：**这层有没有气泡**就是判据（不写死坐标）✓
        _bbs = find_bubbles(b, log=log, tag="ecf_bb")
        if not _bbs:
            _log(log, {"guild": "try_floor_no_bubble"})
            return False
        _px, _py = person_of_bubble(_bbs[0][0], _bbs[0][1])
        _tap_xy(b, _px, _py, wait=2.2)
        items = ocr_items(b, tag="ecf")
        if task_panel_open(items):
            # 探测时拉出了派遣面板 ⇒ **先关掉**（后面要逐个椅子开）
            tap_target(b, items, ("×", "X", "x", "✕", "✖", "关闭"), TASK_PANEL_X,
                       log=log, tag="chair_floor_x", wait=1.6, use_dlg=True)
            _log(log, {"guild": "chair_floor_found", "by": "task_panel"})
            return True
        if has(items, "恭喜获得"):
            _log(log, {"guild": "try_floor_reward"})
            _dismiss_popup(b, log, "ecf_rw")
            _log(log, {"guild": "chair_floor_found", "by": "reward_popup"})
            return True
        _log(log, {"guild": "try_floor_miss", "texts": _texts(items)[:8]})
        return False
    except Exception as _e_trf:       # noqa: BLE001
        # ⚠ 原来这里是裸 `return False`，异常被彻底吞掉 ✗
        #   真机：16 次调用只有 4 次 ecf OCR ⇒ 12 次在 OCR 前就抛了，却一条日志都没有
        _say("       · ⚠ 探测椅子抛异常：%r" % (_e_trf,))
        _log(log, {"guild": "try_floor_exc", "err": repr(_e_trf)})
        return False

def run_tasks(b, log=None, chairs=(1, 2, 3, 4), sweeps=2, leave=False):
    """派遣任务全流程 -> res（ok / busy_count / chairs …）

    ⚠ **两遍扫描**（PC 默认 `sweeps=2`）：第一遍会把「已完成」的椅子领成「新任务」，
      第二遍才把它们真正派出去 ✓（一遍漏派就是 PC 第一轮那个坑）
    """
    log = log if log is not None else []
    res = {"ok": False, "chairs": {}, "claimed": 0, "dispatched": 0}
    _say("")
    _say("=" * 62)
    _status("日常 1/3 · 排班（4 把椅子）")
    _say("📋 派遣任务")
    _say("=" * 62)

    if not goto_guild(b, log):
        _say("   ✗ 进不了公会展厅 ⇒ 放弃（不动任何东西）")
        res["why"] = "not_in_guild"
        return res
    _say("   ✓ 已进公会展厅")

    # ⭐⭐ v1.82【**先看面板开没开** —— 开着就直接用，别再"探测完再关掉" ✗】
    #   ---- 为什么加这一步 ----
    #     用户上次真机就是这个状态：**派遣面板本来就开着**（可能上次跑一半留下、
    #     或用户自己点开的）⇒ 旧流程仍去"点椅子探测楼层"，而探测成功后又把面板**关掉**，
    #     然后才重新逐把椅子开始 ⇒ **白折腾一轮**，且探测期间坐标错了就直接放弃 ✗
    #   ⇒ 现在：面板已开 ⇒ 直接进入椅子循环（面板开着时不需要"找楼层"）✓
    _pre = ocr_items(b, tag="task_pre")
    if task_panel_open(_pre):
        _say("   · 派遣面板**已经开着** ⇒ 直接开始（不探测楼层 ✓）")
        _log(log, {"guild": "panel_already_open"})
        _status("排班 · 面板已开，直接开始")
    elif not ensure_chair_floor(b, log):
        _say("   ✗ 找不到派遣椅子那层 ⇒ 放弃（不动任何东西）")
        res["why"] = "chair_floor_not_found"
        return res
    else:
        _say("   ✓ 已在派遣那层")

    for sw in range(max(1, int(sweeps))):
        if _stopped():
            _say("   ⏹ 用户已停止 ⇒ 退出派遣循环")
            res["why"] = "stopped"
            return res
        _say("")
        _say("   ── 第 %d/%d 遍 ──" % (sw + 1, sweeps))
        # ⭐ v1.90：先模板找一次气泡 ⇒ 这一遍**空闲位有几个**就是待办数
        #   （已派出的那几号头顶是倒计时、没有问号气泡 ⇒ 气泡数天然 < 4 ✓）
        _n_done = 0        # ⭐ v1.90：本次循环已处理的号数（= 该取第几个空闲气泡）
        for idx in chairs:
            if _stopped():
                _say("   ⏹ 用户已停止 ⇒ 退出派遣循环")
                res["why"] = "stopped"
                return res
            tm_before = chair_timers(ocr_items(b, tag="ct%d_pre" % idx)).get(idx)
            if tm_before:
                _say("   · 椅%d：进行中（%s）⇒ 跳过 ✓" % (idx, tm_before))
                res["chairs"][idx] = ("busy", tm_before)
                continue
            _status("排班 · 椅 %d/4" % idx)
            _say("   · 椅%d：处理中…" % idx)
            # ⭐ v1.90：算出「这一号 = 第几个空闲气泡」
            #   ⛔ 别用 `idx-1-busy`（我第一版就是）：椅1/椅2 在跑时它会算出
            #     椅3→slot0、椅4→slot1，而 slot0 正是**椅1/椅2 占的位置**⇒重复点 ✗
            #   ✅ 正确：**已经派出去的号数** 就是"前面消耗掉几个空闲位"
            #     `_done` 记录**本次循环里已经处理成功的号数**（含原本就在跑的）
            #     ⇒ slot = 已处理号数 ✓（每成功一个 +1，天然跳过已占用的）
            _bpre = find_bubbles(b, log=log, tag="pre%d" % idx)
            _slot = _n_done
            _log(log, {"task": "slot_calc", "chair": idx,
                       "bubbles": len(_bpre), "n_done": _n_done,
                       "slot": _slot})
            _say("   · 椅%d：空闲气泡 %d 个，已处理 %d ⇒ 取第 %d 个"
                 % (idx, len(_bpre), _n_done, _slot + 1))
            r = _ensure_dispatched(b, log, idx, slot=_slot)
            # ⛔⛔ v1.90b【**busy 不能消耗气泡下标** —— 想通了】
            #   ---- 为什么 ----
            #     气泡 = **问号**（空闲位）。已在跑的号头顶是**倒计时**、没有气泡。
            #     ⇒ `find_bubbles()` 返回的就是「**当前所有空闲位**」⇒ 只有
            #       「本次真的派出去一个」才让空闲位少一个（`_n_done += 1`）✓
            #     ⛔ 我第一版把 `already`（原本就在跑）也 +1 ⇒ 椅1/椅2 在跑时
            #        `_n_done` 直接变 2 ⇒ 椅3/椅4 判越界 ⇒ **永远派不出去** ✗✗
            #     （这个错和"idx-1 当气泡下标"是**同一个误解**：把"号"当"空闲位"）
            #   ⇒ 只有 `dispatched` 才递增 ✓
            if r == "dispatched":
                _n_done += 1
            res["chairs"][idx] = (r, "")
            if r == "dispatched":
                res["dispatched"] += 1
            elif r == "already":
                pass
            else:
                res["chairs"][idx] = ("retry", "")

    _sleep(b, 1.0)
    final = chair_timers(ocr_items(b, tag="task_final"))
    res["final_timers"] = final
    _say("")
    for idx in chairs:
        if idx in final:
            _say("   ✓ 椅%d：进行中 %s" % (idx, final[idx]))
        else:
            _say("   ⚠ 椅%d：**没看到倒计时**（未接 / 已完成待领 / 读不出）" % idx)
    res["ok"] = len(final) > 0
    res["busy_count"] = len(final)
    _log(log, {"task": "done", "busy": len(final), "timers": final})
    if leave:
        leave_guild(b, log)
    _say("=" * 62)
    return res



# ══════════════════════════════════════════════════════════════════════
# ④ 炼金（公会展厅 4 楼顶楼左边那个普通宝箱）—— PC alchemy.py
# ══════════════════════════════════════════════════════════════════════
# 用户口径（PC 原文）：
#   · 「炼金往上滑就能看到个有感叹号的箱子」
#   · 「这时候要**点满星**，然后点**开始炼金**」
#   · 「这些我打算是**体力刷完自动去做**」
#
# 位置（PC 实测，**别点错**）：
#     公会展厅 → 手指下滑滚到顶楼（4 楼）→ **左边普通宝箱**
#     ⛔ 同一层还有两个**看起来像、但完全不是炼金**的东西：
#        大陶罐          ⇒ 点了**无反应**
#         紫发角色        ⇒ 是「**献祭宝箱怪**」（天赋互换）✗
#       （PC 第一轮就把这两个都点错过）
# ⚠⚠ PC 2026-10-14 **用户明确要了「自动投满星开炼」**（我问过，原话选择）
#   ⇒ auto_start 默认 **True**（投满星开炼）
#   ⚠ 但它**仍然是「会消耗 6 件 5★ 满星装备」的不可逆动作** ⇒ 界面上留一个反开关 ✓
# 公会展厅上**会挡路的浮层/面板**专有词 —— 出现任一就说明"不是在干净楼层"
#   ⚠ 真机实测：公会 2 楼挂着「**兑换商店开启**」横幅，点它开的就是兑换商店 ✗
#   这些词在**干净的公会楼层画面**上不会出现（横幅被点开后才有）✓
# ⚠ 只用**兑换商店独有**的词 —— 别放「前往」「觉醒石」这类**泛词**
#   （背包/道具详情/活动页都有它们 ⇒ 会把正常画面误判成"被挡" ✗）
BLOCKING_PANEL_WORDS = ("活动兑换", "兑换商店", "兑换所")


def _clear_blocking_panels(b, items, log=None):
    """把挡在公会楼层上的面板点 X / 返回 关掉 -> 关掉了吗

    ⚠ 只点**明确的关闭符号**（× / X / 关闭 / 返回）—— 绝不乱点别的 ✓
      （真机事故：盲点坐标点开了兑换商店；这里只认关闭符，点不到就如实返回 False）
    """
    _words = [k for k in BLOCKING_PANEL_WORDS
              if any(k == str(it.get("text") or "").replace(" ", "") for it in items)]
    if not _words:
        return False
    _say("   · 检测到挡路面板（%s）⇒ 先关掉" % (_words[:3],))
    _log(log, {"alch": "blocking_panel", "words": _words})
    for _try in range(3):
        _it = find(items, "×", "X", "✕", "关闭", "返回")
        if not _it:
            break
        _tap_item_dlg(b, _it, wait=1.8)
        _log(log, {"alch": "close_blocker", "text": _it.get("text"),
                   "at": (_it.get("cx"), _it.get("cy")), "try": _try + 1})
        items = ocr_items(b, tag="clr%d" % _try)
        _words2 = [k for k in BLOCKING_PANEL_WORDS
                   if any(k == str(it.get("text") or "").replace(" ", "")
                          for it in items)]
        if not _words2:
            _say("   · ✓ 挡路面板已关掉")
            return True
    _say("   ⚠ 挡路面板没关掉")
    return False

def result_panel_open(items):
    """「炼金结果」面板（**已炼好待领**）—— 整条相等才算 ✓"""
    return has(items, ALCH_RESULT_TITLE, exact=True)


def main_panel_open(items):
    """「炼金宝箱」主面板（空闲可投料 / 进行中）

    ⛔⛔ v1.93【**真机：面板开着，这个判据却返回 False**】
      ---- 病（和派遣的「黑晶女仆」是同一个坑）----
      旧判据**只认**「炼金宝箱」整条命中。真机 `now3.png` 跑 OCR 结果：
        · 含「炼金」的条目**只有 2 条**：`开始炼金`(conf 1.00) /
          `※多余的道具才能参与炼金`(conf 0.96)
        · **「炼金宝箱」这条根本没有** ✗ —— 它是左上角大标题、压在立绘上
      ⇒ `main_panel_open()` 恒 False ⇒ `start_alchemy()` 第一句就 return failed
        ⇒ **整个炼金流程压根没进去** ⇒ 用户看到的就是「还没点满星投料」✗✗
      ---- 修法：多判据（面板内专有词）----
      只要出现下面**任何一个**，就认定炼金面板开着 ✓
      （这些词在游戏别处不会同时出现，`开始炼金`/`预计时间` 更是面板独有）
    """
    if has(items, "炼金宝箱", exact=True):
        return True
    for _k in ("开始炼金", "全部取消", "预计时间", "多余的道具才能参与炼金"):
        if has(items, _k):
            return True
    return False


def alch_timer(items):
    """箱子上那层**倒计时**（= 正在炼金）-> "HH:MM:SS" 或 None

    ⚠ PC 的 y 带 305~375（设备系）—— 这里 ×1.5 ⇒ 458~563 ✓
      （**只看那一条带**：页面上别处也有时间文字，混进来会误判成「进行中」✗）
    """
    for it in (items or []):
        if not (_s(305) < it.get("cy", 0) < _s(375)):
            continue
        t = str(it.get("text") or "").replace(" ", "").replace("：", ":")
        m = re.search(r"(\d{1,2}:\d{2}:\d{2})", t)
        if m:
            return m.group(1)
    return None


def expect_time(items):
    """面板上「预计时间」的值 -> "HH:MM:SS" / "--:--:--" / None

    ⚠ PC 的兜底逻辑（照抄，别简化）：标签和值**可能被 OCR 拆成两条**
      ⇒ 找不到就按「同一行、在标签右边、x0 最小」挑一条 ✓
      ⚠ 值读成纯符号/空（`--:--:--`）⇒ 表示**投料槽是空的** ✓
    """
    lab = find(items, "预计时间")
    if not lab:
        return None
    m = re.search(r"(\d{1,2}\s*[:：]\s*\d{2}\s*[:：]\s*\d{2})", lab["text"])
    if m:
        return re.sub(r"\s+", "", m.group(1)).replace("：", ":")
    if re.search(r"-{2,}", lab["text"]):
        return "--:--:--"
    lx = lab.get("x1", lab.get("cx", 0))
    ly = lab.get("cy", 0)
    best = None
    for it in (items or []):
        if it is lab:
            continue
        if abs(it.get("cy", 0) - ly) > _s(22):          # 不同行 ⇒ 不是它
            continue
        if it.get("x0", 0) < lx - 6:                    # 在标签左边 ⇒ 不是它
            continue
        if best is None or it.get("x0", 0) < best.get("x0", 0):
            best = it
    if best is None:
        return None
    bt = str(best.get("text") or "").strip()
    m2 = re.search(r"(\d{1,2}\s*[:：]\s*\d{2}\s*[:：]\s*\d{2})", bt)
    if m2:
        return re.sub(r"\s+", "", m2.group(1)).replace("：", ":")
    if bt and len(bt) <= 3 and not re.search(r"\d", bt):
        return "--:--:--"
    return None


def slots_filled(items):
    """投料槽有没有东西 -> 0/1/None（None = 判不了 ✓）"""
    t = expect_time(items)
    if t is None:
        return None
    return 0 if t.startswith("--") else 1


def claim_result(b, log, items=None, tag="alch"):
    """领「炼金结果」—— **OCR 找「返回」**，4 轮；找不到**不盲点** ✓"""
    items = items if items is not None else ocr_items(b, tag="%s_res" % tag)
    if not result_panel_open(items):
        return False
    for k in range(4):
        it = find(items, "返回")
        if it:
            b.tap(it["cx"], it["cy"], wait=2.0)
            _log(log, {"alch": "claim_back", "at": (it["cx"], it["cy"]), "try": k + 1})
            _say("       · 炼金结果 ⇒ 点「返回」(%d,%d) 领走 ✓" % (it["cx"], it["cy"]))
            return True
        _sleep(b, 0.8)
        items = ocr_items(b, tag="%s_res%d" % (tag, k))
    _log(log, {"alch": "claim_back_miss"})
    _say("       · ⚠ 4 轮没找到「返回」⇒ **不盲点**（如实记录）")
    return False


def read_result(items):
    """从「炼金结果」面板读 (金币, 道具条数) —— 只记日志用 ✓"""
    gold = None
    for it in (items or []):
        t = str(it.get("text") or "").replace(",", "")
        if _s(520) < it.get("cy", 0) < _s(600) and re.fullmatch(r"\d{3,}", t):
            try:
                gold = int(t)
            except ValueError:
                pass
    n_item = sum(1 for it in (items or [])
                 if _s(610) < it.get("cy", 0) < _s(900) and it.get("text"))
    return gold, n_item


def _which_panel(items):
    """人话描述「现在开出的是哪个面板」（日志/排查用 ✓）"""
    if result_panel_open(items):
        return "「炼金结果」（**已完成待领**）"
    if main_panel_open(items):
        if alch_timer(items):
            return "「炼金宝箱」+ 倒计时（**进行中**）"
        return "「炼金宝箱」（**空闲可投料**）"
    if has(items, "献祭宝箱怪"):
        return "⚠ 「献祭宝箱怪」——**点错格子了**（那是天赋互换，不是炼金）"
    if has(items, "当前正在炼金中"):
        return "「当前正在炼金中」提示"
    return "**没开出任何面板**（认到 %s）" % (_texts(items)[:8],)


def start_alchemy(b, log, tag="alch"):
    """投料 + 开炼 -> started / nothing / failed

    ⚠ PC 两道安全闸（都别删）：
      · **主面板已有投料 ⇒ 不重复投**（预计时间不是 `--` ⇒ 直接开炼 ✓）
      · **点了满星但投料槽还是空的 ⇒ 不点开始炼金**（避免空烧 ✗）
    """
    items = ocr_items(b, tag="%s_main" % tag)
    if not main_panel_open(items):
        _log(log, {"alch": "main_panel_miss"})
        return "failed"

    t0 = expect_time(items)
    _log(log, {"alch": "main", "expect": t0})
    if t0 and not t0.startswith("--"):
        _say("       · 主面板已有投料（预计时间 %s）⇒ 不重复投，直接开炼" % t0)
    else:
        # ⛔⛔ v1.93【**「满星」这步不能依赖 OCR 文字** —— 真机实测】
        #   ---- 病 ----
        #     旧写法 `tap_target(..., ("满星", ...))` 是**整条相等**匹配。
        #     真机 OCR 实测（`_tmpman/now3.png`）：
        #       `ref(500,1553) conf=**0.74** [满星]`   ← 置信度很低
        #       `ref(833,1553) conf=1.00 [蓝色紫色橙色]` ← 三个按钮**被合并成一条** ✗
        #     ⇒ 只要 OCR 把「满星」读歪/读成带换行的，整条相等就**失配**，
        #       回落到锚点；而锚点若也偏 ⇒ **满星压根没点上** ⇒ 投料槽空着
        #       ⇒ 后面 `if not t1` 判 `nothing` ⇒ **整个炼金跳过**
        #       （用户报：「还没点满星进行投料呢」← 正是这个）✗✗
        #   ---- 为什么这里可以放心用锚点 ----
        #     ① 炼金面板布局是**固定的**（6 个投料槽 / 按钮行 / 装备符文标签 / 筛选行）
        #     ② 「满星」永远是筛选行**第一个**，实测 ref(500,1553) 直接点中 ✓
        #     ③ 已经用 `main_panel_open()` 确认过"确实是炼金面板"
        #        ⇒ **面板内**用锚点是安全的（不是盲点）✓
        #   ---- 做法：**先点锚点，再用"投料有没有生效"验证** ----
        #     点完必须看到「预计时间」从 `--` 变成 `HH:MM:SS` ⇒ 才算点中 ✓
        #     没变 ⇒ 再试一次 OCR 认到的（双保险），仍不行就如实记 nothing ✗
        # ⛔⛔ 2026-11-05 实测（炼金面板开着、直接量的真实坐标）：
        #   「满星」真实位置 dev(593,2203) ⇒ 归一化参考系 (500,1551) = 本常量 ✓
        #   而 use_dlg=True 按弹窗系算 ⇒ dev 2023（偏上 180；真机 1280x2772 偏 248）
        #   ⇒ 那一下落在装备格子区 ⇒ 把 1 件装备塞进第 1 槽 ⇒ 预计时间变成非空
        #     ⇒ 下面「变非空就算投料成功」直接去点开始炼金 ⇒ 只投 1 件、压根没点满星 ✗
        #   ⇒ 通道必须与 ocr_items 同源（参考系）⇒ use_dlg=False ✓
        _tap_xy(b, ALCH_FILTER_FULLSTAR[0], ALCH_FILTER_FULLSTAR[1],
                wait=2.5, use_dlg=False)
        _log(log, {"alch": "tap_fullstar_anchor", "at": ALCH_FILTER_FULLSTAR})
        items = ocr_items(b, tag="%s_star" % tag)
        t1 = expect_time(items)
        if not t1 or t1.startswith("--"):
            # 锚点没生效 ⇒ 退回 OCR 文字（可能面板布局变了）
            _say("       · ⚠ 点锚点后预计时间仍是空的 ⇒ 改试 OCR 认到的「满星」")
            _it_fs = find(items, "满星", "满星筛选", "全满星")
            if _it_fs:
                _tap_item_dlg(b, _it_fs, wait=2.5)
                _log(log, {"alch": "tap_fullstar_ocr",
                           "at": (_it_fs.get("cx"), _it_fs.get("cy"))})
                items = ocr_items(b, tag="%s_star2" % tag)
                t1 = expect_time(items)
        _log(log, {"alch": "after_fullstar", "expect": t1})
        items = ocr_items(b, tag="%s_star" % tag)
        t1 = expect_time(items)
        _log(log, {"alch": "tap_fullstar", "at": ALCH_FILTER_FULLSTAR,
                   "expect_after": t1})
        _status("炼金 · 投料中")
        _say("       · 点「满星」⇒ 预计时间 %s" % (t1 or "?"))
        if not t1 or t1.startswith("--"):
            _say("       · ⚠ 点了满星但**投料槽还是空的** ⇒ 不点开始炼金（避免空烧）")
            _log(log, {"alch": "no_fill", "note": "满星后预计时间仍为空"})
            return "nothing"

    # ⭐⭐ **文字优先**：「开始炼金」同上 —— 面板按钮位置随文案行数变，写死会点空 ✗
    # 同上：ALCH_START_BTN 是参考系常量（实测 dev 1066,1017 ⇒ ref 899,551）
    #   ⇒ 兜底锚点也必须走参考系；OCR 命中时 tap_target 内部按 +C 另算 ✓
    tap_target(b, items, ("开始炼金",), ALCH_START_BTN,
               log=log, tag="alch_start", wait=3.0, use_dlg=False)
    items2 = ocr_items(b, tag="%s_start" % tag)
    tm = alch_timer(items2)
    _log(log, {"alch": "tap_start", "at": ALCH_START_BTN, "timer": tm,
               "panel_still": main_panel_open(items2)})
    if tm:
        _say("       · ⭐ 炼金已开始 ⇒ 倒计时 %s ✓" % tm)
        return "started"
    if main_panel_open(items2):
        _say("       · ⚠ 点了开始炼金但面板还在（可能弹了确认框）⇒ 再看一轮")
        it = find(items2, "确定", "确认")
        if it:
            b.tap(it["cx"], it["cy"], wait=2.5)
            items3 = ocr_items(b, tag="%s_start2" % tag)
            tm2 = alch_timer(items3)
            _log(log, {"alch": "confirm_ok", "timer": tm2})
            if tm2:
                _say("       · ⭐ 确认后炼金已开始 ⇒ 倒计时 %s ✓" % tm2)
                return "started"
        close_panel(b, ALCH_PANEL_X, "alch_x_start",
                    probe_texts=("炼金宝箱",), log=log)
        return "failed"
    _say("       · 面板已关但**没读到倒计时** ⇒ 下一轮再看（不假装成功）")
    return "failed"



def run_alchemy(b, log=None, auto_start=True, leave=False):
    """炼金全流程 -> res（ok / claimed / started / state …）

    ⚠ auto_start 默认 **True**（PC 用户明确授权的「投满星开炼」✓）
      界面上留一个反开关：取消勾选 ⇒ 只领取、不投料 ✓
    """
    log = log if log is not None else []
    res = {"ok": False, "claimed": False, "started": False, "state": None}
    _say("")
    _say("=" * 62)
    _status("日常 2/3 · 炼金")
    _say("⚗️  炼金%s" % ("（**会自动投料开炼**）" if auto_start else "（只领取，不消耗）"))
    _say("=" * 62)

    if not goto_guild(b, log):
        _say("   ✗ 进不了公会展厅 ⇒ 放弃")
        res["why"] = "not_in_guild"
        return res

    scroll_to_top(b, log)

    # ⭐ 宝箱的 y 会随「滚到多深」漂 ⇒ x/y 做笛卡尔积逐个试（PC 实测的修法 ✓）
    items = []
    _opened = None
    _hit_at = None
    # ⚠ 炼金宝箱是**美术物件、没有文字可认** ⇒ 只能点坐标。
    #   缓解手段：**x/y 各试一组窄候选**（已收窄到实测值 ±1 个身位）
    #   且每次点完**必须验证面板是否真的打开**（`_which_panel`）✓
    #
    # ⛔⛔ v1.95【**点之前必须先确认"现在是公会楼层"** —— 真机事故】
    #   ---- 病 ----
    #     真机 13:58:32 日志：`点 (354,700) ⇒ 认到 [觉醒石/前往/炼金获取/活动兑换]`
    #     ⇒ 那不是公会楼层，是**「兑换商店」面板**（公会 2 楼「兑换商店开启」横幅开的）✗
    #     旧代码**不看画面是什么**就按坐标盲点 9 次 ⇒ 点开一堆无关面板 ✗✗
    #   ---- 修法：点之前先"清场" ----
    #     ① 先 OCR 一帧，看有没有「兑换/商店/活动」这类**挡路面板**
    #     ② 有 ⇒ 先点它的关闭/X 关掉，再继续（关不掉就如实放弃，不硬点）
    #     ③ 确认是干净的公会楼层后，才去点宝箱 ✓
    _pre = ocr_items(b, tag="alch_pre")
    if _clear_blocking_panels(b, _pre, log):
        _pre = ocr_items(b, tag="alch_pre2")
    _blockers = [k for k in BLOCKING_PANEL_WORDS
                 if any(k == str(it.get("text") or "").replace(" ", "") for it in _pre)]
    if _blockers:
        _say("   ⚠ 公会楼层被面板挡住（%s）⇒ **不盲点宝箱**，如实放弃" % (_blockers,))
        _log(log, {"alch": "blocked_by_panel", "words": _blockers})
        res["why"] = "blocked_by_panel"
        return res

    # ⭐⭐ v1.96【**只点一次 + 强验证 + 点错立刻关掉**】
    #   ---- 为什么不再"x/y 笛卡尔积乱扫" ----
    #     真机事故：`ALCHEMY_CHEST_YS = (759,700,820)` 盲扫 9 次，
    #     其中 700/820 落在「**兑换商店开启**」横幅上 ⇒ 点开了兑换商店 ✗✗
    #     ⇒ **乱扫比点不中危险得多**（点开会污染后续所有判断）✓
    #   ---- 现在的做法 ----
    #     ① 只点**1 个**实测位置（ref 392,400 = 真机逐像素量出来的）
    #     ② 点完**必须**验证：看到「炼金宝箱」/「炼金结果」/「当前正在炼金中」才算中 ✓
    #     ③ **既不是炼金面板、又开出了别的面板** ⇒ **立刻点 X 关掉**（别留着挡路）
    #     ④ 点错**不换坐标重试** ⇒ 如实报失败（宁可这轮不炼金，也不乱点）✓
    # ⭐⭐⭐ v1.97【**模板匹配定位宝箱** —— 用户口径「直接找炼金宝箱」】
    #   ---- 为什么能用模板了 ----
    #     之前我判断"宝箱不能模板定位"是**错的**：
    #       我裁的那块带了**角色**进去（角色坐在宝箱前）⇒ 换皮肤就废 ✗
    #     用户指认后重新裁：**只裁宝箱本体**（dev 358,908 - 498,1032，140×124），
    #       木箱+锁扣特征干净 ⇒ now4 得分 **1.000**、top 0.73 ✓
    #   ---- 定位顺序 ----
    #     ① 模板匹配（`guild_chest.png`，阈值 0.70）⇒ 找到就点它的中心 ✓
    #     ② 找不到（角色挡住/皮肤不同）⇒ 用**实测兜底** ref(361,400)
    #        ⚠ 这是用户指认过的位置，不是盲猜 ✓
    #     ③ 点完**必须验证**是炼金面板；不是就清理 + 放弃（不换坐标重试）✓
    _tpl_c = _load_tpl("guild_chest.png")
    _hits = []
    try:
        _nimg = b.img()
        if _tpl_c is not None and _nimg is not None:
            _hits = _tpl_match(_nimg, _tpl_c, thr=0.70, roi=(250, 700))
    except Exception as _e_tm:       # noqa: BLE001
        _log(log, {"alch": "tpl_err", "err": repr(_e_tm)})
    if _hits:
        _cx, _cy, _sc = _hits[0]
        _log(log, {"alch": "chest_by_tpl", "at": (_cx, _cy), "score": _sc,
                   "n": len(_hits)})
        _say("   · 模板找到宝箱 ref(%d,%d) score=%.2f ✓" % (_cx, _cy, _sc))
    else:
        _cx, _cy = ALCHEMY_CHEST
        _log(log, {"alch": "chest_by_anchor", "at": (_cx, _cy),
                   "note": "模板没命中（角色挡住/皮肤不同）⇒ 用用户指认的实测位置"})
        _say("   · ⚠ 模板没命中 ⇒ 用实测兜底 ref(%d,%d)" % (_cx, _cy))
    # !! v2.93【一次定生死 => 面板晚一拍就被判没开、且再也不点返回】
    #   真机铁证（2026-11-02 19:12:58）：
    #     {alch: chest_by_tpl, at:(361,399), score:0.999}   <= 箱子找得准
    #     {alch: open, panel: 没开出任何面板, ok:False}       <= 点完立刻 OCR，面板还没出来
    #     {alch: open_final, hit:None, note:点错已清理}       <= 直接放弃
    #   而**面板后来确实开了**（用户截图：炼金结果 95900 金币 + 返回按钮停在那儿）
    #   => 代码 `return res` 提前返回 => 永远走不到领取分支 => 面板留屏 => 卡住 X
    #   另外：进来时若面板**本来就开着**，旧代码还会再点一下箱子（反而把它点掉）X
    #   ---- 修法 ----
    #     ① 先看「进来时面板是否已经开着」=> 开着就**不点箱子**，直接去领取
    #     ② 否则点箱子 + 验证，**最多重试 3 次**（每次等 2.5 秒再 OCR）
    #       面板慢一拍也能接住，不再因为一次没等到就整轮放弃 ✓
    def _is_alch_panel(_its):
        return (result_panel_open(_its) or main_panel_open(_its)
                or has(_its, "献祭宝箱怪", "当前正在炼金中"))

    items = _pre
    _ok_panel = _is_alch_panel(items)
    if _ok_panel:
        _say("   · 进来时炼金面板**已经开着** ⇒ 不再点箱子（再点会把它点掉 ✗）")
        _log(log, {"alch": "already_open", "panel": _which_panel(items)})
    else:
        for _k in range(3):
            _tap_xy(b, _cx, _cy, wait=2.5)
            items = ocr_items(b, tag="alch_open%d" % _k)
            _ok_panel = _is_alch_panel(items)
            if _ok_panel:
                break
            _say("   · 点 (%d,%d) 后还没看到炼金面板（第 %d/3 次）⇒ 再试一次"
                 % (_cx, _cy, _k + 1))
    _opened = _which_panel(items)
    _log(log, {"alch": "open", "at": (_cx, _cy), "panel": _opened,
               "ok": _ok_panel, "texts": _texts(items)[:12]})
    if _ok_panel:
        _hit_at = (_cx, _cy)
        _say("   · 点 (%d,%d) ⇒ %s ✓" % (_cx, _cy, _opened))
    else:
        _say("   · 点 (%d,%d) ⇒ %s ⇒ **不是炼金面板**" % (_cx, _cy, _opened))
        # ⛔ 关键：点错了必须**立刻关掉**，否则它会挡住后面所有操作
        #   （真机事故：兑换商店面板留着 ⇒ 后面情报/果实全在对着它认字 ✗）
        _cleared = _clear_blocking_panels(b, items, log)
        if not _cleared:
            # 认不出挡路词也要试着关一次（可能是别的面板）
            _itx = find(items, "×", "X", "✕", "关闭", "返回")
            if _itx:
                _tap_item_dlg(b, _itx, wait=1.8)
                _log(log, {"alch": "close_unknown", "text": _itx.get("text")})
                items = ocr_items(b, tag="alch_open2")
        _log(log, {"alch": "open_final", "panel": _which_panel(items),
                   "hit": None, "note": "点错已清理，不换坐标重试"})
        res["why"] = "chest_miss"
        _say("   · 不换坐标重试（乱扫会点开别的面板）⇒ 本轮跳过炼金")
        return res
    _log(log, {"alch": "open_final", "panel": _opened, "hit": _hit_at})
    _is_running_tip = has(items, "当前正在炼金中")
    if not (result_panel_open(items) or main_panel_open(items) or _is_running_tip):
        _say("   ✗ 候选点都试过了，没开出炼金面板 ⇒ **如实报失败**（不假装成功）")
        res["why"] = "panel_not_opened"
        res["state"] = _opened
        return res

    if _is_running_tip and not (result_panel_open(items) or main_panel_open(items)):
        _say("   · 点宝箱回到「**当前正在炼金中**」提示"
             "（= 炼金在跑、面板没弹）⇒ 按「进行中」处理 ✓")
        _log(log, {"alch": "running_tip", "at": _hit_at})

        _sleep(b, 1.2)                 # 等提示自己消失
        scroll_to_top(b, log)           # 滚回顶楼（= 炼金那层，沙漏在那儿 ✓）
        items = ocr_items(b, tag="alch_tip_closed")
        _log(log, {"alch": "tip_scrolled",
                   "timer": (alch_timer(items) or expect_time(items)),
                   "still_tip": has(items, "当前正在炼金中")})

    # ① 已炼好待领 ⇒ 领
    if result_panel_open(items):
        gold, n_item = read_result(items)
        _say("   · 炼金结果：金币 %s ｜ 道具约 %d 条" % (gold, n_item))
        if claim_result(b, log, items):
            res["claimed"] = True
            res["state"] = "claimed"
            _sleep(b, 1.2)
            # art object (no text) -> coordinate; next line verifies the panel opened
            _tap_xy(b, ALCHEMY_CHEST[0], ALCHEMY_CHEST[1], wait=3.0)
            items = ocr_items(b, tag="alch_reopen")
            _log(log, {"alch": "reopen", "panel": _which_panel(items)})
            _say("   · 领完再点箱子 ⇒ %s" % _which_panel(items))

    # ② 主面板（进行中 / 空闲）
    if main_panel_open(items) or _is_running_tip:
        tm = alch_timer(items) or expect_time(items)
        running = bool(alch_timer(items)) or _is_running_tip
        res["state"] = "running" if running else "idle"
        if running:
            _say("   · 炼金**进行中**（%s）" % (tm or "提示「当前正在炼金中」"))
            _say("   · 不动它 ✓")
            if main_panel_open(items):
                close_panel(b, ALCH_PANEL_X, "alch_x_run",
                            probe_texts=("炼金宝箱",), log=log)
        else:
            if not auto_start:
                _say("   · 炼金**空闲**（预计时间 %s）⇒ 只领取模式，**不投料** ✓"
                     % (expect_time(items) or "?"))
                close_panel(b, ALCH_PANEL_X, "alch_x_idle",
                            probe_texts=("炼金宝箱",), log=log)
            else:
                _say("   · 炼金空闲 ⇒ 自动投料开炼（满星 → 开始炼金）")
                r = start_alchemy(b, log)
                res["started"] = (r == "started")
                res["state"] = r
                if r != "started":
                    close_panel(b, ALCH_PANEL_X, "alch_x_fail",
                                probe_texts=("炼金宝箱",), log=log)

    res["ok"] = bool(res["claimed"] or res["started"]
                     or res["state"] in ("running", "idle"))
    _log(log, {"alch": "done", "claimed": res["claimed"], "started": res["started"],
               "state": res["state"], "ok": res["ok"]})
    if leave:
        leave_guild(b, log)
    _say("=" * 62)
    return res


# ══════════════════════════════════════════════════════════════════════
# ⑤ 公会「情报」领奖（每日 + 每周）—— PC intel.py
# ══════════════════════════════════════════════════════════════════════
# 用户口径（PC 原文）：
#     ① 「**接下来做点击情报领取奖励**」
#     ② 「**每周情报也顺便点了**」
#     ③ 「**每周情报可以直接盲点一下最上面的可领取的坐标**，然后就可以关闭页面了」
#
# 面板：公会展厅 → 右上角「情报」按钮 ⇒ 「**情报指南**」（战斗通行证式）
#     · 中部：**两个页签** —— 「每日情报 N/8」｜「每周情报 N/7」
#     · 列表：每行 = 奖励点数 + 任务名 + **右侧状态按钮**
#     · 右侧状态按钮有**三种**：可领取 / 已完成 / N/M（进度）
#   ⇒ **只点「可领取」**；不碰「购买情报指南」（要花宝石 ✗）、不碰「已完成」✓
#   ⇒ **纯领奖、零消耗**（不花体力/金币/宝石）✓
def intel_panel_open(items):
    return has(items, INTEL_TITLE, "每日情报", "每周情报")


def _intel_claimable(items):
    """所有「可领取」条目（**按 cy 从大到小排序** ⇒ 从上往下领 ✓）"""
    out = []
    for it in (items or []):
        if str(it.get("text") or "").strip() == INTEL_CLAIMABLE:
            out.append(it)
    out.sort(key=lambda d: d.get("cy", 0))
    return out
# ── 情报（公会右上角「情报指南」）常量 ──
#
# ⛔ v1.94：**这批常量在手机端丢了**（真机 NameError 抓到），现补回。
#   来源：PC `mapbot_pc/intel.py:1x-2x`，按手机端约定 ×1.5 转 1080 参考系 ✓
#   ⚠**这些仍是 PC×1.5 推算值，没在真机上验过** —— 情报功能本轮未标定，
#     开启后大概率点不中（和炼金/派遣当初一样）⇒ 已在文档记为「未标定」✗
# ⛔⛔ v2.108【**已停用为点击目标**】实测 1280×2640 上「情报」按钮在参考系 y≈371~416，
#   而本常量 y=387 > RefMapper.TOP_SPLIT_REF(300) ⇒ b.tap 走**锚底**分支
#   （dev = ref·kx + shift）⇒ 落到设备 y≈823，按钮真实在 y≈493 ⇒ **点低 330px** ✗
#   （9:16 屏 shift=0 ⇒ 恰好对，所以这个错只在非 9:16 屏暴露）
#   ⇒ 现在只留作坐标留档（门禁 v1.94 ② 要求它仍有定义），**点击一律走模板** ✓
INTEL_BTN = (_s(660), _s(258))            # 公会右上角「情报」入口（⚠ 仅供参考，禁止盲点）
INTEL_CLOSE_X = (_s(645), _s(228))        # 面板右上 X
INTEL_TAB_DAILY = (_s(279), _s(439))      # 「每日」页签
INTEL_TAB_WEEKLY = (_s(441), _s(439))     # 「每周」页签
INTEL_BTN_X = _s(548)                     # 逐条领取按钮的 x
INTEL_FIRST_Y = _s(559)                   # 第一行的 y
INTEL_ROW_YS = tuple(_s(v) for v in (559, 655, 752, 847, 942, 1039))
INTEL_POPUP_BACK = (_s(359), _s(883))     # 领取弹窗的「返回」
INTEL_TITLE = "情报指南"
INTEL_CLAIMABLE = "可领取"
INTEL_DONE = "已完成"
# 炼金面板右上 X（PC alchemy.py 推算，同属未真机标定）
ALCH_PANEL_X = (_s(880), _s(120))



def intel_open_panel(b, log=None, tag="intel"):
    """打开「情报指南」—— **已经在就复用**；不在公会就先进公会 ✓"""
    items = ocr_items(b, tag="%s_p0" % tag)
    if intel_panel_open(items):
        _say("   · 情报面板**已经开着** ⇒ 直接用 ✓")
        _log(log, {"intel": "panel_already_open"})
        return True

    if not in_guild(items):
        if not goto_guild(b, log):
            _say("   ✗ 进不了公会 ⇒ 走不到「情报」（它在公会右上角）")
            return False
        items = ocr_items(b, tag="%s_p1" % tag)
        if intel_panel_open(items):
            return True

    # ⭐⭐⭐ v1.97【**三层定位：模板 → 文字 → 锚点**】用户口径「把情报模板弄好」
    #   ---- 为什么加模板这一层 ----
    #     「情报」二字 OCR 读得到（conf 1.00），但**按钮本身是个图标块**；
    #     真机实测模板 `guild_intel_btn.png`（190×143，红十字+书本+红底字）
    #     **全帧唯一命中、得分 1.000** ⇒ 比 OCR 更稳（不受字体渲染影响）✓
    #   ---- 顺序 ----
    #     ① 模板匹配（最稳，且能确认"这个按钮真的在"）
    #     ② OCR 文字（模板失效时的主力：皮肤变了模板就不中）
    #     ③ INTEL_BTN 锚点（最后兜底；仍是 PC×1.5 推算，未真机标定）
    at = None
    _by = ""
    _tpl_i = _load_tpl("guild_intel_btn.png")
    try:
        # ⛔⛔ v1.97【**情报按钮必须用 `img_dlg()`，不能用 `img()`**】
        #   ---- 为什么（真机实测的铁律）----
        #     `b.img()` = `grabRefPng()` = `toRef()` 的产物，它**丢弃了中间弹性区**
        #     ⇒ 归一化帧 **y 0~135 是黑边**（不是画面）。
        #     而情报按钮整个落在 dlg y 217~337 ⇒ 换算回归一化帧是 **y 7~104**
        #     ⇒ **整块都在黑边里** ⇒ 从 `b.img()` 裁出来的模板**平均亮度 20.7（全黑）** ✗
        #   ---- 正确口径 ----
        #     `b.img_dlg()` = `grabDlgPng()` = `toDlg()`，**保留弹性带** ✓
        #     同一个按钮在 dlg 帧里是 **dlg(915,217)-(1076,337)，亮度 105.8、唯一命中 1.000** ✓
        #   ⇒ 模板也按 dlg 尺度裁（`guild_intel_btn.png` 161×120），
        #     匹配也必须用 dlg 帧 —— **尺度和坐标系必须同源** ✓
        _nimg = b.img_dlg() if hasattr(b, "img_dlg") else None
        if _tpl_i is not None and _nimg is not None:
            _hits_i = _tpl_match(_nimg, _tpl_i, thr=0.90, roi=(100, 500))
            if _hits_i:
                at = (_hits_i[0][0], _hits_i[0][1])
                _by = "tpl"
                _log(log, {"intel": "btn_by_tpl", "at": at,
                           "score": _hits_i[0][2], "n": len(_hits_i)})
                _say("   · 模板找到「情报」按钮 ref(%d,%d) score=%.2f ✓"
                     % (at[0], at[1], _hits_i[0][2]))
    except Exception as _e_ti:       # noqa: BLE001
        _log(log, {"intel": "tpl_err", "err": repr(_e_ti)})
    if at is None:
        it = None
        for _i in (items or []):
            if str(_i.get("text") or "").strip() == "情报":
                it = _i
                break
        if it is not None:
            at = (int(it["cx"]), int(it["cy"]))
            _by = "ocr"
        else:
            # ⛔⛔ v2.108【**删掉盲点兜底** —— 用户报「情报点击位置不对」的根因】
            #   ---- 为什么不再盲点 ----
            #     旧代码这里 at = INTEL_BTN 直接点：模板失效（旧模板 122×72 与当前 UI
            #     尺度不符，多尺度最佳只有 0.537 < 0.90 ⇒ **层①从来命中不了**）⇒
            #     每次都掉到这里 ⇒ 1280×2640 上点 (1173,823)，按钮真实在 (1184,493)
            #     ⇒ **点低 330 设备像素**、落在按钮下方的背景上 ✗✗
            #   ---- 判据 ----
            #     模板与 OCR 都认不出 ⇒ **不许猜**（项目原话「兜底比不兜更糟」/
            #     「不能固定坐标啊，识别气泡」）⇒ 如实记录并返回 False，交给上层收工 ✓
            _log(log, {"intel": "btn_missing", "tpl": _tpl_i is not None,
                       "n_ocr": len(items or []),
                       "note": "模板/OCR 都没认出「情报」⇒ 不盲点（v2.108）"})
            _say("   ✗ 认不出右上角「情报」按钮（模板 miss + 没读到「情报」二字）⇒ 不点")
            return False
    # ⛔⛔ 2026-11-05【通道按来源选，不能一律 use_dlg】—— 用户报「情报不能正常点击」
    #   · `by='tpl'`：模板是在 **b.img_dlg()（弹窗帧）** 上匹配的 ⇒ 坐标本就是弹窗系 ⇒ tap_dlg ✓
    #   · `by='ocr'`：`ocr_items()` 返回的是**归一化参考系** ⇒ 必须 b.tap（差 C：模拟器154 / 真机209）✗
    #   · 旧 by='anchor'：v2.108 起**已删除**（盲点必错，实测偏 330px，见上）✓
    #   旧写法一律 use_dlg=True ⇒ OCR/锚点两条路都偏 C 个参考像素（≈180~248 设备px）⇒ 点不中 ✗
    _tap_xy(b, at[0], at[1], wait=2.6, use_dlg=(_by == 'tpl'))
    items2 = ocr_items(b, tag="%s_p2" % tag)
    _ok = intel_panel_open(items2)
    _log(log, {"intel": "tap_btn", "at": at, "by": _by, "open": _ok})
    _say("   · 点右上角「情报」(%d,%d)[%s] ⇒ %s"
         % (at[0], at[1], _by, "面板已开 ✓" if _ok else "没开 ✗"))
    return _ok


def intel_switch_tab(b, which, log=None, tag="intel"):
    """切「每日/每周情报」页签 —— **优先 OCR 找页签名**，找不到才用标定坐标 ✓"""
    at = INTEL_TAB_WEEKLY if str(which).startswith("w") else INTEL_TAB_DAILY
    name = "每周情报" if str(which).startswith("w") else "每日情报"
    items = ocr_items(b, tag="%s_t0" % tag)
    # ⭐ 页签文字（「每日情报」/「每周情报」）优先；读不到才用标定坐标 ✓
    # 同上：OCR 条目/锚点都是**参考系** ⇒ use_dlg=False（旧写法偏 C 点不中 ✗）
    tap_target(b, items, (name,), at, log=log, tag="intel_tab",
               wait=1.8, use_dlg=False)
    items2 = ocr_items(b, tag="%s_t1" % tag)
    ok = intel_panel_open(items2)
    _log(log, {"intel": "switch_tab", "to": name, "at": at, "ok": ok})
    _say("   · 切到「%s」(%d,%d) ⇒ %s" % (name, at[0], at[1], "✓" if ok else "⚠ 面板不见了"))
    return ok


def _intel_dismiss_reward(b, log=None, tag="intel"):
    """领奖弹窗 —— 优先 OCR 找按钮；**没有「恭喜获得/获得」字样就说明没弹窗** ✓"""
    for k in range(6):
        items = ocr_items(b, tag="%s_rw%d" % (tag, k))
        it = find(items, "返回", "确定", "点击继续", "确认")
        if it:
            # ⚠ 同样是 OCR 条目 ⇒ 必须 +C（否则偏 209 参考像素 ✗）
            _tap_item_dlg(b, it, wait=1.7)
            _log(log, {"intel": "dismiss_reward", "text": it["text"],
                       "src": "ocr",
                       "at": (it["cx"], it["cy"]), "try": k + 1})
            _say("       · 弹窗 ⇒ 点「%s」(%d,%d) ✓" % (it["text"], it["cx"], it["cy"]))
            return True
        if not has(items, "恭喜获得", "获得"):
            return True
        _sleep(b, 0.5)
    # ⚠ 走到这里说明 5 轮都没 OCR 到按钮 ⇒ 用标定坐标**兜底**（并如实记 by=fallback）
    _tap_xy(b, INTEL_POPUP_BACK[0], INTEL_POPUP_BACK[1], wait=1.7, use_dlg=False)   # 参考系常量 ✗ 别用 dlg
    _log(log, {"intel": "dismiss_reward", "at": INTEL_POPUP_BACK, "by": "fallback"})
    _say("       · 没读到弹窗按钮 ⇒ 用标定坐标 (%d,%d)" % INTEL_POPUP_BACK)
    return True


def intel_claim_daily(b, log=None, tag="intel", max_rounds=12):
    """每日情报：**从上往下**逐条点「可领取」-> 领到几条 ✓

    ⚠ 上限 12 轮（PC 口径）—— 每天就 8 条任务，12 是防呆 ✓
    """
    got = 0
    for r in range(max(1, int(max_rounds))):
        items = ocr_items(b, tag="%s_d%d" % (tag, r))
        if not intel_panel_open(items):
            _say("   ⚠ 每日情报：面板不见了 ⇒ 停手（领了 %d 条）" % got)
            _log(log, {"intel": "daily_panel_lost", "got": got})
            break
        rows = _intel_claimable(items)
        if not rows:
            _say("   · 每日情报：没有「可领取」了 ⇒ 完成（共领 %d 条）✓" % got)
            break
        it = rows[0]                    # **从上往下**领（y 最小的那条 ✓）
        b.tap(it["cx"], it["cy"], wait=1.9)
        _log(log, {"intel": "claim_daily", "i": r + 1,
                   "at": (it["cx"], it["cy"]), "left": len(rows)})
        _say("   · 每日情报 [%d] ⇒ 点「可领取」(%d,%d)（这帧还剩 %d 条可领）"
             % (got + 1, it["cx"], it["cy"], len(rows)))
        _intel_dismiss_reward(b, log, tag)
        got += 1
    return got


def _intel_is_progress(t):
    """「N/M」这种进度文字（**不是可领取**，别点 ✓）"""
    t = str(t or "").strip()
    if "/" not in t:
        return False
    a, _sep, bb = t.partition("/")
    return a.strip().isdigit() and bb.strip().isdigit()


def intel_claim_weekly(b, log=None, tag="intel"):
    """每周情报：**只领最上面那条可领取**（用户口径：盲点最上面那个 ✓）

    ⚠ 两道闸门（都别删）：
      · 读不到第 1 行的状态 ⇒ **不盲点**（不瞎猜 ✗）
      · 第 1 行不是「可领取」（已完成 / N/M 进度）⇒ **不点** ✓
    """
    if not intel_switch_tab(b, "weekly", log, tag):
        return False
    items = ocr_items(b, tag="%s_w0" % tag)

    _first = None
    for _i in (items or []):
        _t = str(_i.get("text") or "").strip()
        _cy = _i.get("cy", 0)
        _cx = _i.get("cx", 0)
        if not (_s(500) < _cx < _s(600) and _s(400) < _cy < _s(1120)):
            continue
        if _t == INTEL_CLAIMABLE or _t == INTEL_DONE or _intel_is_progress(_t):
            if _first is None or _cy < _first.get("cy", 9999):
                _first = _i
    if _first is None:
        _say("   ⚠ 每周情报：读不到第 1 行的状态 ⇒ **不盲点**（不瞎猜 ✗）")
        _log(log, {"intel": "weekly_no_row"})
        return False
    _t = str(_first["text"]).strip()
    if _t != INTEL_CLAIMABLE:
        _say("   · 每周情报：第 1 行是「%s」（不是「可领取」）⇒ **不点** ✓" % _t)
        _log(log, {"intel": "weekly_first_not_claimable", "text": _t})
        return False

    # ⭐ 用户口径原话：「**每周情报可以直接盲点一下最上面的可领取的坐标**，
    #   然后就可以关闭页面了」—— 所以这里**允许盲点**。
    #   但既然 `_first` 已经把「可领取」那颗 OCR 出来了，**先点它**（更准、同样是一次点击）✓
    #   只有 `_first` 的坐标读不可用时，才退回 INTEL_FIRST_Y 那个标定位置 ✓
    _wx, _wy = int(_first["cx"]), int(_first["cy"])
    if not (_s(400) < _wy < _s(1120)):
        _wx, _wy = INTEL_BTN_X, INTEL_FIRST_Y
    _tap_xy(b, _wx, _wy, wait=1.9, use_dlg=False)
    _log(log, {"intel": "claim_weekly",
               "at": (_wx, _wy),
               "src": "ocr_first_row" if (_wx, _wy) != (INTEL_BTN_X, INTEL_FIRST_Y)
                      else "anchor_fallback",
               "ocr_saw": (_first["cx"], _first["cy"])})
    _say("   · 每周情报 ⇒ 点最上面那个「可领取」(%d,%d) ✓" % (_wx, _wy))
    _intel_dismiss_reward(b, log, tag)
    return True


def intel_close_panel(b, log=None, tag="intel"):
    """关掉情报页面（**先确认它还在** ✓）"""
    items = ocr_items(b, tag="%s_c0" % tag)
    if not intel_panel_open(items):
        _say("   · 已经不在情报页面了 ⇒ 不用关 ✓")
        return True
    # ⭐ 关闭符文字优先（× / X / 关闭），读不到才用 INTEL_CLOSE_X 兜底 ✓
    # ⛔⛔ v2.110【**这条必须走弹窗系** —— 实测（App 内探针，2026-11-05 23:09）】
    #   · 情报面板的 X 在设备 (1117,584)，换算到 **dlg = (943,339)**
    #     ⇒ 与常量 `INTEL_CLOSE_X=(968,342)` 几乎重合 ⇒ **这批常量本来就是弹窗系** ✓
    #   · 而它在**归一化帧**里是 ref y≈185（< TOP_SPLIT_REF 300）⇒ 旧代码 use_dlg=False
    #     会走「顶块锚顶」分支 ⇒ 落设备 y≈219 ⇒ **差 365px，点空** ✗
    #     真机现象：领完奖后面板关不掉，日志 `intel: close_panel ... ok: False`（已复现）
    #   ⇒ OCR 命中走 `_tap_item_dlg`（条目 +C 再 tap_dlg）、锚点走 `tap_dlg`，同源 ✓
    tap_target(b, items, ("×", "X", "x", "✕", "✖", "关闭"), INTEL_CLOSE_X,
               log=log, tag="intel_close", wait=2.0, use_dlg=True)
    items2 = ocr_items(b, tag="%s_c1" % tag)
    _ok = not intel_panel_open(items2)
    _log(log, {"intel": "close_panel", "at": INTEL_CLOSE_X, "ok": _ok})
    _say("   · 关掉情报页面 (%d,%d) ⇒ %s"
         % (INTEL_CLOSE_X[0], INTEL_CLOSE_X[1], "✓" if _ok else "⚠ 还在面板上"))
    return _ok


def run_intel(b, log=None, daily=True, weekly=True, close=True,
              enter_guild=True, return_to_map=True):
    """情报领奖全流程 -> res（ok / daily / weekly / closed …）"""
    log = log if log is not None else []
    res = {"ok": False, "daily": 0, "weekly": False, "closed": False}
    _say("")
    _say("=" * 62)
    _status("日常 3/3 · 情报")
    _say("📋 公会「情报」领奖（每日 + 每周）")
    _say("=" * 62)

    if not intel_open_panel(b, log):
        _say("   ✗ 没打开情报面板 ⇒ 放弃（不动任何东西）")
        res["why"] = "panel_not_open"
        if return_to_map:
            res["back_to_map"] = bool(leave_guild(b, log))
        return res

    if daily:
        if intel_switch_tab(b, "daily", log):
            res["daily"] = intel_claim_daily(b, log)
            _status("情报 · 每日 %d 条" % res["daily"])
            _say("   · 每日情报共领 **%d** 条 ✓" % res["daily"])
    else:
        _say("   · 没勾「每日情报」⇒ 跳过")

    if weekly:
        res["weekly"] = intel_claim_weekly(b, log)
        _say("   · 每周情报：%s" % ("领了最上面那条 ✓" if res["weekly"]
                                  else "没有可领的（或第 1 行不是「可领取」）✓"))
    else:
        _say("   · 没勾「每周情报」⇒ 跳过")

    if close:
        res["closed"] = intel_close_panel(b, log)
    else:
        _say("   · 没勾「关闭页面」⇒ 留在情报页")
    res["ok"] = True
    _log(log, {"intel": "done", "daily": res["daily"],
               "weekly": res["weekly"], "closed": res["closed"]})
    if return_to_map:
        _b = leave_guild(b, log)
        res["back_to_map"] = bool(_b)
        _say("   · %s" % ("已返回地图界面（选图界面）✓" if _b
                          else "⚠ 没确认回到选图界面（如实上报）"))
    _say("=" * 62)
    return res



# ══════════════════════════════════════════════════════════════════════
# ⑥ 收工日常总调度（= PC explore_loop._guild_daily @12506 的等价物）
# ══════════════════════════════════════════════════════════════════════
# ⭐ PC 的顺序口径（三条用户原话叠出来的）：
#   「把勾选的公会日常，免费招募和免广告（**这三个脚本的最后都要回到地图界面，
#    最开始都要进入公会界面**）都做完后，检查下体力…」
#   ⇒ 三个单元**各自进公会 → 干活 → 回地图**（**不是**挤在一起只在最后 leave 一次 ✗）
#     · ① **公会日常**（派遣 + 炼金 + 情报）⇒ 都在公会里，**共用一次进出** ✓
#     · ② 免费招募 ⇒ 入口在公会右下角 ⇒ 它自己进出 ✓
#     · ③ 广告领奖 ⇒ 入口在 HUD，但按用户口径也先进一次公会（位置语义一致）✓
#   ⇒ 三者串起来 = 三次「进公会 / 回地图」⇒ **位置可预测** ✓
#
# ⚠ 顺序**不能乱**（PC 的推理，照抄）：
#   ① 公会日常：三件事都在公会里 ⇒ 先做 2 楼（派遣，省一次滚动），再滚上去做炼金；
#      情报在**公会展厅**（不用滚楼层）⇒ 紧着公会里的活儿一起做完 ✓
#   ② 免费招募要**离开公会**（入口在大厅）⇒ 放公会日常之后 ✓
#   ③ 广告不依赖公会 ⇒ 最后 ✓
def run(b, log=None, tasks=True, alchemy=True, intel=True,
        auto_start=True, leave_first=False):
    """跑「公会日常」（派遣 + 炼金 + 情报）—— **一个单元，共用一次进出公会** ✓

    -> dict（每件的成败都单独记，一个崩了不影响其它 ✓）

    ⚠ `tasks` / `alchemy` / `intel` 三个开关**各自独立**（界面上是三颗勾选 ✓）
      全关 ⇒ 整段跳过（等价于「默认不做」✓）
    ⚠ 返回 dict 的键与 PC `_guild_daily` 的 STATS 字段同名，便于对日志 ✓
    """
    log = log if log is not None else []
    out = {"ok": False, "tasks": None, "alchemy": None, "intel": None,
           "back_to_map": False}
    if not (tasks or alchemy or intel):
        _say("   · 公会日常三件都没勾 ⇒ 跳过（一下都不点 ✓）")
        out["ok"] = True
        return out

    _say("")
    _status("公会日常 · 开始")
    if _stopped():
        _say("⏹ 用户已停止 ⇒ 公会日常整个跳过")
        return {"ok": False, "why": "stopped"}
    _say("🏰 公会日常（收工）：派遣任务 + 炼金 + 情报")

    _entered = False
    try:
        _entered = bool(goto_guild(b, log))
        if not _entered:
            _status("公会日常 · 进公会失败，跳过")
            _say("   ⚠ 进不了公会 ⇒ 跳过公会日常（派遣/炼金/情报）")
            out["why"] = "not_in_guild"
            return out
    except Exception as _eg:        # noqa: BLE001
        _log(log, {"guild_daily": "enter_error", "e": repr(_eg)[:120]})
        _say("   ⚠ 进公会出错：%r" % (_eg,))
        return out

    # ── ① 派遣任务（2 楼）──
    if tasks:
        try:
            _t = run_tasks(b, log, leave=False)
            out["tasks"] = _t
            _say("   · 派遣任务：%s（%d 把在跑）"
                 % ("✓" if _t.get("ok") else "⚠", _t.get("busy_count", 0)))
        except Exception as _e1:    # noqa: BLE001
            import traceback as _tb1
            _log(log, {"guild_daily": "tasks_error", "e": repr(_e1)[:160],
                       "trace": _tb1.format_exc().splitlines()[-4:]})
            _say("   ⚠ 派遣任务出错：%r" % (_e1,))
    else:
        _say("   · 没勾「派遣任务」⇒ 跳过")

    # ── ② 炼金（4 楼顶楼）──
    if alchemy:
        try:
            _a = run_alchemy(b, log, auto_start=auto_start, leave=False)
            out["alchemy"] = _a
            _say("   · 炼金：领取=%s 开炼=%s 状态=%s"
                 % (_a.get("claimed"), _a.get("started"), _a.get("state")))
        except Exception as _e2:    # noqa: BLE001
            import traceback as _tb2
            _log(log, {"guild_daily": "alch_error", "e": repr(_e2)[:160],
                       "trace": _tb2.format_exc().splitlines()[-4:]})
            _say("   ⚠ 炼金出错：%r" % (_e2,))
    else:
        _say("   · 没勾「炼金」⇒ 跳过")

    # ── ③ 情报领奖（公会展厅右上角，**不用滚楼层**）──
    if intel:
        try:
            _i = run_intel(b, log, return_to_map=False)
            out["intel"] = _i
            _say("   · 情报领奖：每日 %s 条 ｜ 每周 %s ｜ 已关页面 %s"
                 % (_i.get("daily"), _i.get("weekly"), _i.get("closed")))
        except Exception as _e3:    # noqa: BLE001
            import traceback as _tb3
            _log(log, {"guild_daily": "intel_error", "e": repr(_e3)[:160],
                       "trace": _tb3.format_exc().splitlines()[-4:]})
            _say("   ⚠ 情报领奖出错：%r" % (_e3,))
    else:
        _say("   · 没勾「情报领奖」⇒ 跳过")

    # ── 收尾：**回地图界面**（用户口径「最后都要回到地图界面」✓）──
    if _entered:
        try:
            _ok = leave_guild(b, log)
            out["back_to_map"] = bool(_ok)
            _say("   · %s" % ("公会日常 ⇒ 已回地图界面 ✓" if _ok
                              else "⚠ 公会日常 ⇒ 没确认回到选图界面"))
        except Exception as _el:    # noqa: BLE001
            _log(log, {"guild_daily": "leave_error", "e": repr(_el)[:120]})

    out["ok"] = True
    return out


def summary_line(res):
    """一行摘要（给收尾统计/日志用）—— **失败也照实写**，不美化 ✓"""
    res = res or {}
    bits = []
    _t = res.get("tasks") or {}
    if _t:
        bits.append("派遣 %d 在跑" % int(_t.get("busy_count") or 0))
    _a = res.get("alchemy") or {}
    if _a:
        bits.append("炼金 %s" % (_a.get("state") or "?"))
    _i = res.get("intel") or {}
    if _i:
        bits.append("情报 每日%s/每周%s" % (_i.get("daily"), _i.get("weekly")))
    if not bits:
        return "公会日常：无"
    return "公会日常：" + " ｜ ".join(bits)

