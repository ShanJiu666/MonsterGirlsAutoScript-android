# -*- coding: utf-8 -*-
"""recruit.py · **免费指定招募**（公会右下角「招募」→「指定招募」）—— 从 PC 端移植 (v1.78)

PC 源：mapbot_pc/recruit.py（972 行）

用户口径（PC 原文，2026-10-14）：
    · 「现在这个界面是免费招募界面」
    · 「你了解下机制，**抄一下小助手的选项判断机制**，**尽量能拿到高等级角色**」

机制（PC 从游戏源码 PublicSummonPanel 逐字确证）：
  1. 大厅中央大门 ⇒ 弹「**指定招募**」面板（PublicSummon_GLD）
  2. 面板上有 **N 个候选标签**（PC 实测本号 7 个，菱形排布）
     —— 候选池由**服务端每日下发**（save.publicSummonTags），
       **不可重 roll**、**只能取消再选** ✓
  3. 选 **1~3 个**（源码：>=3 提示「标签选择数量已达上限」；
     <1 提示「至少需要选择一个标签」）
  4. 点「招募」⇒ POST /Summon/PublicSummon {SelectedTags} ⇒ **固定只出 1 个角色** ✓
  5. 免费旗标：主界面文字从「**免费指定招募**」变成「角色招募」（每天 1 次）✓

「选项判断机制」= 小助手那套（PC 已逐字逆向 + 对拍过）：
    Re 匹配 + **组合枚举** + **加权排序**：
      权重 w = minR*100 + has_leg*10 + len(combo)*0.1 + w_sh
        · minR    = 组合命中角色里**最低**稀有度（保底越高的组合越好 ✓）
        · has_leg = 组合里有没有**传说**（rarity==3）
        · w_sh    = 心愿角色的加分（1000 分，压倒一切）
      ⇒ 保底稀有度**优先**，其次传说，再次组合数（多一个标签范围更窄 ⇒ 更好 ✓）

⭐⭐ 移植口径：
   • 坐标 ×1.5（720×1280 ⇒ 1080×1920，9:16 纯等比 ✓）
   • **角色表从本仓 server_datatable.json 实时推**（不写死名单 ✓）
   • ⚠⚠ 免费闸门（PC 的**最重要一道**）：按钮**亮度 < 阈值 ⇒ 今天的免费机会已用掉**
     ⇒ **绝不动它**（点了会误花宝石 ✗）。用户原话：「免费机会用掉了就跳过（不花宝石）」
   • ⚠ 读不到亮度 ⇒ **保守不动**（宁可不做，也不误花宝石 ✗）
"""
import io
import itertools
import json
import os
import re
import sys
import time

# ⭐ v1.78：点击一律走 `guild_daily.tap_target`（**文字优先 → 坐标兜底**）——
#   不在这里再造第二套，否则两边迟早漂移（PC 记过「判据两份漂移」的账 ✓）
#   ⚠ 必须放**模块级 import**（写在函数里会让 NameError 扫描抓不到定义 ✓）
from guild_daily import tap_target, _tap_xy  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_ROOT = os.environ.get("MAPBOT_ROOT") or _HERE
_DT = os.environ.get("MAPBOT_DT") or os.path.join(_ROOT, "server_datatable.json")

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


# ── 坐标（PC 720×1280 实测 ×1.5）──
GUILD_RECRUIT_BTN = (_s(628), _s(1040))   # 公会右下角「招募」
HALL_DOOR = (_s(360), _s(690))            # 大厅中央大门（老路径兜底）
RETURN_TO_MAP = True                      # 做完是否回选图界面

RECRUIT_FREE_BTN = (_s(125), _s(905))     # 「指定招募(免费)」按钮
RECRUIT_FREE_TXT = (_s(125), _s(871))     # 文字「指定招募」那一行（OCR 命中点）
RECRUIT_TITLE = "指定招募"
RECRUIT_CLOSE_X = (_s(671), _s(126))      # 招募页右上角 X（**离开招募页**用 ✓）
RECRUIT_BTN = (_s(360), _s(963))          # 「招募」按钮（选中标签后才可点）
RECRUIT_TIP_XY = (_s(353), _s(806))       # 「最多选择3个标签…（N/3）」提示行

SKIP_BTN = (_s(360), _s(963))             # 招募动画的「跳过」（位置同招募按钮）
RECRUIT_END_BTN = (_s(360), _s(1214))     # 「结束招募」

TAG_BAND = (_s(400), _s(800))             # 标签只可能落在这一段 y 里（收 OCR 用）
TAG_TAP_DX = 0                            # ← **不偏移**（保留常量是为了让这个教训可见 ✓）

RARITY_CN = {3: "传说", 2: "史诗", 1: "稀有", 0: "普通"}

#: 数据表读不到时的**兜底**（只放"四大类"的取值域，用于让脚本还能跑）
#: ⚠ 兜底**不参与选最优**（那样等于瞎猜 ✗）—— 只在"读不到表"时用来**识别标签类别**，
#:   并**显式告警**让用户知道这次没算最优 ✓
FALLBACK_TAGS = {
    "职业": ("射手", "法师", "战士", "牧师"),
    "种族": ("生灵", "亡灵", "神灵", "魔灵", "器灵"),
    "属性": ("光系", "风系", "火系", "水系", "暗系", "地系"),
    "地区": ("平原", "森林", "沙滩", "海洋", "山脉", "沙漠", "星界", "雪原", "火山"),
    "星级": ("史诗", "传说"),
}

#: Step → 稀有度（游戏 Role.Step 的映射；PC 从数据表分布的实测推的）
STEP2RARITY = {"普通": 0, "稀有": 1, "史诗": 2, "传说": 3,
               "C": 0, "B": 1, "A": 2, "S": 3, "SS": 4}


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
    """⭐ 悬浮条提示（**用户唯一能看见"在做什么"的通道**）—— 见 guild_daily._status 的长注释

    ⚠ 规矩同 guild_daily：短、人话、**避开 OCR 关键词**（招募/领取/派遣…都是敏感词，
      但「排班」「收起」「抽卡」这类替身可以用 ✓）
    """


def _dlg_c():
    """C = RefMapper.dialogShift()（归一化帧 → 弹窗系 的 y 偏移）✓"""
    try:
        import mapbot as _mb
        return float(_mb.dlg_shift())
    except Exception:       # noqa: BLE001
        return 0.0

def _log(log, rec):
    if log is None:
        return
    try:
        log.append(rec)
    except Exception:       # noqa: BLE001
        pass


def _datatable_path():
    """数据表路径 —— 手机端由 MAPBOT_DT 给（explore_android._bootstrap 已设好 ✓）"""
    for c in (_DT,
              os.path.join(_ROOT, "server_datatable.json"),
              os.path.join(_HERE, "server_datatable.json"),
              os.path.join(_HERE, "..", "data", "server_datatable.json")):
        if c and os.path.exists(c):
            return c
    return None


def load_roles(path=None):
    """从游戏数据表推**招募池** -> (roles, err)

    ⚠ 两条排除（PC 从源码 `canBePublicSummon` 推的）：
      · `Source` 非空 ⇒ 不是公开招募池 ✓
      · `IDs` 里带 `_` ⇒ 是**皮肤**，不是角色 ✓
    role 元组 = (Name, Class, Type, Element, Map, rarity)
    """
    p = path or _datatable_path()
    if not p or not os.path.exists(p):
        return None, "找不到游戏数据表（%s）" % (p,)
    try:
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
        R = (d or {}).get("Role") or {}
    except Exception as e:      # noqa: BLE001
        return None, "数据表读不动（%r）" % (e,)
    out = []
    for _k, v in R.items():
        try:
            if (v.get("Source") or "").strip():
                continue                    # 非 canBePublicSummon ⇒ 不进招募池 ✓
            ids = str(v.get("IDs") or "")
            if "_" in ids:
                continue                    # 皮肤 ⇒ 排除 ✓
            out.append((str(v.get("Name") or ""),
                        str(v.get("Class") or ""), str(v.get("Type") or ""),
                        str(v.get("Element") or ""), str(v.get("Map") or ""),
                        STEP2RARITY.get(str(v.get("Step") or ""), 0)))
        except Exception:       # noqa: BLE001
            continue
    if not out:
        return None, "数据表里 Role 表是空的"
    return out, None


def tag_matches(role, tag):
    """某个标签能不能**命中**某个角色（小助手的匹配口径 ✓）"""
    _n, cls, race, elem, area, rar = role
    if tag == "传说":
        return rar == 3
    if tag == "史诗":
        return rar == 2
    return tag in (cls, race, elem, area)


def rank_combos(tags, roles, wish=None, max_k=3):
    """枚举所有 1~3 个标签的组合并**加权排序** -> [{c, f, minR, w}, ...]

    ⚠ 权重公式（PC 逐字照抄）：`w = minR*100 + has_leg*10 + len(combo)*0.1 + w_sh`
      · **保底稀有度优先**（minR 是组合命中角色里**最低**的那个 —— 保底越高越好 ✓）
      · 其次传说（has_leg）
      · 再次组合数（len*0.1 —— 多一个标签范围更窄，同分时更优 ✓）
      · 心愿角色 w_sh=1000（**压倒一切**）
    """
    wish = wish or set()
    if not tags:
        return []
    out = []
    for k in range(1, min(len(tags), int(max_k)) + 1):
        for combo in itertools.combinations(tags, k):
            hit = [r for r in roles if all(tag_matches(r, t) for t in combo)]
            if not hit:
                continue
            min_r = min(r[5] for r in hit)
            has_leg = 1 if any(r[5] == 3 for r in hit) else 0
            w_sh = 1000 if (min_r >= 2 and any(r[0] in wish for r in hit)) else 0
            w = min_r * 100 + has_leg * 10 + len(combo) * 0.1 + w_sh
            out.append({"c": list(combo), "f": sorted(hit, key=lambda r: -r[5]),
                        "minR": min_r, "w": w})
    out.sort(key=lambda d: -d["w"])
    return out


def badge(min_r):
    """保底徽章（界面显示用 ✓）"""
    if min_r >= 3:
        return "顶级招募"
    if min_r == 2:
        return "资深保底"
    return None



def panel_open(items):
    """「指定招募」标签面板开着吗 —— **两条判据任一命中** ✓

    ⚠ 为什么不是只看标题：标题「指定招募」在**别的页面**也会出现
      （大厅横幅就写着「免费指定招募」）⇒ 单看标题会误判 ✗
    """
    import guild_daily as GC
    if GC.has(items, "最多选择3个标签", "最多选择"):
        return True
    return bool(read_tags(items)) and GC.has(items, "招募")


def read_tags(items, known=None):
    """读面板上的候选标签 -> [(tag, cx, cy), ...]（**按 cy 再 cx 排序** ✓）

    ⚠ 只收 `TAG_BAND` 那一段 y 里的（面板别处也有"招募/取消"这类词）
    ⚠ 只认**已知标签名**（`_all_tag_names()`）—— 否则会把说明文字当标签 ✗
    """
    import guild_daily as GC  # noqa: F401
    known = set(known or _all_tag_names())
    out = []
    for it in (items or []):
        cy = it.get("cy", 0)
        if not (TAG_BAND[0] < cy < TAG_BAND[1]):
            continue
        t = str(it.get("text") or "").strip()
        if t in known:
            out.append((t, int(it.get("cx", 0)), int(cy)))
    out.sort(key=lambda d: (d[2], d[1]))
    return out


def _all_tag_names():
    """所有可能的标签名 —— 角色表能读就用它（**实时**），否则用兜底 ✓"""
    roles, _err = load_roles()
    names = set()
    if roles:
        for r in roles:
            names.update(x for x in (r[1], r[2], r[3], r[4]) if x)
    else:
        for v in FALLBACK_TAGS.values():
            names.update(v)
    names.update(FALLBACK_TAGS["星级"])
    return names


def tag_kind(tag):
    """标签属于哪一类（职业/种族/属性/地区/星级）—— 只用于日志可读性 ✓"""
    for k, vs in FALLBACK_TAGS.items():
        if tag in vs:
            return k
    return "?"


def read_counter(items):
    """读「（N/3）」里已经选了几个 -> int 或 None

    ⚠ 读不到 ⇒ 返回 None，调用方**必须不盲点**（toggle 点错会取消已选的 ✗）
    """
    import guild_daily as GC
    it = GC.find(items, "最多选择")
    if not it:
        return None
    m = re.search(r"[（(]\s*(\d)\s*/\s*3\s*[)）]", it["text"])
    return int(m.group(1)) if m else None


def analyze(items, roles, wish=None, verbose=True):
    """读标签 + 排序 -> (best, ranked, tags)"""
    tags = [t for t, _x, _y in read_tags(items)]
    if verbose:
        _say("   · 面板标签（%d 个）：%s"
             % (len(tags), " / ".join("%s[%s]" % (t, tag_kind(t)) for t in tags)))
    if not roles:
        return None, [], tags
    ranked = rank_combos(tags, roles, wish=wish)
    if not ranked:
        return None, [], tags
    return ranked[0], ranked, tags


def _ensure_tags(b, want, log=None, tag="rec", max_rounds=5):
    """把标签**逐个点选**到「已选 N 个」== 目标数 -> bool

    ⚠ 每点一下都**重新读计数器**（PC 原话）：
      · 计数没变 ⇒ 这一下没生效 ⇒ **下一轮重点同一颗** ✓
      · 计数**掉了** ⇒ 点到了已选的（= 取消）⇒ 下一轮重点 ✓
      · 计数 > 目标 ⇒ **如实报失败**（不硬凑，绝不靠"多点几下"凑数 ✗）
    """
    import guild_daily as GC
    want = list(want)
    target = len(want)
    for _r in range(max_rounds):
        items = GC.ocr_items(b, tag="%s_et%d" % (tag, _r))
        if not panel_open(items):
            _say("       · ⚠ 标签面板被关掉了 ⇒ 停手（不点、也不招募）")
            _log(log, {"recruit": "panel_closed_while_tapping"})
            return False
        n = read_counter(items)
        if n is None:
            _say("       · ⚠ 读不到「（N/3）」计数器 ⇒ **不盲点**（怕 toggle 点错 ✗）")
            return False
        if n == target:
            return True
        if n > target:
            _say("       · ⚠ 已选 %d 个 > 目标 %d 个 ⇒ 如实报失败（不硬凑 ✗）"
                 % (n, target))
            _log(log, {"recruit": "too_many_tags", "n": n, "want": target})
            return False

        t = want[n]
        xy = {x[0]: (x[1], x[2]) for x in read_tags(items)}
        if t not in xy:
            _say("       · ⚠ 目标标签「%s」这一帧没读到（认到 %s）"
                 % (t, [x[0] for x in read_tags(items)]))
            return False
        x, y = xy[t]
        b.tap(x + TAG_TAP_DX, y, wait=1.2)
        _log(log, {"recruit": "tap_tag", "tag": t, "at": (x, y), "was": n})
        _say("       · 点第 %d 个标签「%s」(%d,%d)（当前 %d/3）"
             % (n + 1, t, x, y, n))
        _sleep(b, 0.6)
        items2 = GC.ocr_items(b, tag="%s_et%d_c" % (tag, _r))
        n2 = read_counter(items2)
        if n2 == n:
            _say("         · 这一下没生效（仍 %s/3）⇒ 下一轮重点同一颗" % n2)
        elif n2 is not None and n2 < n:
            _say("         · ⚠ 计数掉到 %s/3（点到已选的了）⇒ 下一轮重点" % n2)
    items3 = GC.ocr_items(b, tag="%s_et_fin" % tag)
    return read_counter(items3) == target


def pick_tags(b, chosen, tags_xy, log=None, tag="rec"):
    """选标签（`tags_xy` 只为接口兼容；真正点选走 `_ensure_tags` 的每轮现读 ✓）"""
    want = list(chosen or [])
    if not want:
        return False
    ok = _ensure_tags(b, want, log=log, tag=tag)
    _log(log, {"recruit": "tags_done", "want": want, "ok": ok})
    return ok


# ══════════════════════════════════════════════════════════════════════
# ⭐⭐ 免费闸门（PC 的**最重要一道**）
# ══════════════════════════════════════════════════════════════════════
# 用户口径（PC 原文）：「免费机会用掉了就跳过（**不花宝石**）」
# 判据：那颗「指定招募」按钮的**平均亮度** ——
#   亮着（≥110）⇒ 还能免费 ✓ ／ 发灰（<110）⇒ 今天已用掉 ⇒ **绝不动它** ✗
# ⚠ 读不到亮度 ⇒ **保守不动**（宁可不做，也不误花宝石 ✗）
# ⚠ 坐标是 PC 720 设备系 ⇒ 这里 ×1.5 到手机参考系 ✓
FREE_BTN_BOX = (_s(40), _s(840), _s(220), _s(960))   # (x0, y0, x1, y1)
FREE_BTN_LIT = 110.0


def free_available(b, items=None):
    """「指定招募」那颗按钮还能不能免费 -> (bool|None, lum|None, 原因)

    ⚠ 返回 `None` = **判不了** ⇒ 调用方**必须保守不动** ✓（不是"当作可用" ✗）
    """
    try:
        img = b.img()
    except Exception as e:      # noqa: BLE001
        return None, None, "取不到帧（%r）" % (e,)
    if img is None or getattr(img, "size", 0) == 0:
        return None, None, "帧是空的"
    try:
        import cv2 as _cv2
        x0, y0, x1, y1 = FREE_BTN_BOX
        sub = img[y0:y1, x0:x1]
        if sub is None or sub.size == 0:
            return None, None, "裁剪区为空"
        lum = float(_cv2.cvtColor(sub, _cv2.COLOR_BGR2GRAY).mean())
    except Exception as e:      # noqa: BLE001
        return None, None, "亮度算不出来（%r）" % (e,)
    ok = lum >= FREE_BTN_LIT
    return ok, round(lum, 1), ("亮着 ⇒ 免费可用" if ok else "发灰 ⇒ 免费已用掉")


def _free_btn_xy(items):
    """OCR 找「指定招募」那一行，按钮在**它下面 34×1.5 px** 处（PC 实测偏移 ✓）"""
    import guild_daily as GC
    it = GC.find(items, "指定招募")
    if not it:
        return None
    try:
        return (int(it["cx"]), int(it["cy"]) + _s(34))
    except Exception:       # noqa: BLE001
        return None


def _tap_free_btn(b, items, log=None, tag="rec", note=""):
    """点「指定招募(免费)」并**验证标签面板开了** ✓"""
    import guild_daily as GC
    at = _free_btn_xy(items) or RECRUIT_FREE_BTN
    _tap_xy(b, at[0], at[1], wait=2.8)
    items2 = GC.ocr_items(b, tag="%s_free" % tag)
    _ok = panel_open(items2)
    _log(log, {"recruit": "tap_free_btn", "at": at, "open": _ok})
    _say("   · %s点「指定招募(免费)」(%d,%d) ⇒ %s"
         % (note, at[0], at[1], "标签面板已开 ✓" if _ok else "没开出面板 ✗"))
    return _ok


def _on_recruit_home(items):
    """在「招募主页」吗（有招募一次/十次/点数/心愿/预览 任一 ✓）"""
    import guild_daily as GC
    return GC.has(items, "招募一次", "招募十次", "招募点数", "改变心愿",
                  "招募预览")


def _to_recruit_home(b, items=None, log=None, tag="rec"):
    """走到「招募主页」-> items 或 None（**两条路径**：公会右下角 → 大厅大门兜底 ✓）"""
    import guild_daily as GC
    _it = items if items is not None else GC.ocr_items(b, tag="%s_h0" % tag)

    if _on_recruit_home(_it):
        _say("   · 已经在「招募主页」✓")
        return _it
    if panel_open(_it):
        return _it

    if not GC.in_guild(_it):
        if not GC.goto_guild(b, log):
            _say("   ✗ 进不了公会（招募入口在公会右下角）⇒ 走不通")
            return None
        _it = GC.ocr_items(b, tag="%s_h1" % tag)
        if _on_recruit_home(_it) or panel_open(_it):
            return _it

    it = None
    for _i in (_it or []):
        if str(_i.get("text") or "").strip() == "招募":
            it = _i
            break
    at = (int(it["cx"]), int(it["cy"])) if it else GUILD_RECRUIT_BTN
    _tap_xy(b, at[0], at[1], wait=2.8)
    items2 = GC.ocr_items(b, tag="%s_h2" % tag)
    _log(log, {"recruit": "guild_tap_recruit", "at": at,
               "by": "ocr" if it else "calib",
               "home": _on_recruit_home(items2), "panel": panel_open(items2)})
    _say("   · 公会右下角 ⇒ 点「招募」(%d,%d)%s ⇒ %s"
         % (at[0], at[1], "（OCR 现读）" if it else "（标定坐标）",
            "招募主页 ✓" if _on_recruit_home(items2) else
            ("标签面板 ✓" if panel_open(items2) else "没进招募页 ✗")))
    if _on_recruit_home(items2) or panel_open(items2):
        return items2

    _say("   · ⚠ 点了右下角「招募」没进招募页 ⇒ 试一下老路径（大厅中央大门）")
    # ⭐ **文字优先**：大厅横幅上有「指定招募」/「角色招募」/「限时招募开启」，
    #   认到就点它；读不到才用 HALL_DOOR 兜底 ✓（HALL_DOOR 是 1080 参考系、有 RefMapper 换算）
    tap_target(b, _it, ("指定招募", "角色招募", "限时招募开启"), HALL_DOOR,
               log=log, tag="recruit_door", wait=2.6)
    items3 = GC.ocr_items(b, tag="%s_h3" % tag)
    _log(log, {"recruit": "tap_door_fallback", "at": HALL_DOOR,
               "home": _on_recruit_home(items3)})
    if _on_recruit_home(items3) or panel_open(items3):
        return items3
    return None


def _click_skip_anim(b, log=None, tag="rec", rounds=6):
    """点掉招募动画的「跳过」-> bool（没看到「跳过」就返回 False ✓）"""
    import guild_daily as GC
    for k in range(max(1, int(rounds))):
        items = GC.ocr_items(b, tag="%s_skip%d" % (tag, k))
        if GC.has(items, "恭喜获得", "结束招募"):
            return False
        it = GC.find(items, "跳过")
        at = (int(it["cx"]), int(it["cy"])) if it else SKIP_BTN
        if not (it or GC.has(items, "跳过")):
            _sleep(b, 0.6)
            continue
        b.tap(at[0], at[1], wait=1.6)
        _log(log, {"recruit": "tap_skip", "at": at, "try": k + 1,
                   "by": "ocr" if it else "calib"})
        _say("   · 点「跳过」(%d,%d)%s ⇒ 看结果"
             % (at[0], at[1], "（OCR 现读）" if it else "（标定坐标）"))
        return True
    return False


def _click_text_btn(b, log=None, tag="rec", texts=(), fallback=None,
                    what="", prefer_right=False, rounds=4):
    """轮询点一个**文字按钮** -> bool（优先 OCR，找不到才用 fallback ✓）

    ⚠ `prefer_right=True` 时取**最靠右**那个（关面板的 X 在右上角，
      而页面上别处也可能有个 × ）✓；默认取**最靠上**的（结果框按钮）
    ⚠ 找不到就**如实返回 False**（不假装点了 ✗）
    """
    import guild_daily as GC
    for k in range(max(1, int(rounds))):
        items = GC.ocr_items(b, tag="%s_%s%d" % (tag, what, k))
        cands = []
        for it in (items or []):
            t = str(it.get("text") or "").strip()
            for lb in texts:
                if t == lb or (lb in t and len(lb) >= 2):
                    cands.append(it)
                    break
        if cands:
            it = (max(cands, key=lambda d: d.get("cx", 0))
                  if prefer_right else min(cands, key=lambda d: d.get("cy", 0)))
            b.tap(it["cx"], it["cy"], wait=2.0)
            _log(log, {"recruit": "tap_" + (what or "btn"),
                       "text": it["text"], "at": (it["cx"], it["cy"]),
                       "try": k + 1})
            _say("   · 点「%s」(%d,%d) ✓" % (it["text"], it["cx"], it["cy"]))
            return True
        _sleep(b, 0.6)
    if fallback:
        b.tap(fallback[0], fallback[1], wait=2.0)
        _log(log, {"recruit": "tap_" + (what or "btn"),
                   "at": fallback, "by": "fallback"})
        _say("   · 没读到「%s」⇒ 用标定坐标 (%d,%d)"
             % ("/".join(texts), fallback[0], fallback[1]))
        return True
    _log(log, {"recruit": "btn_miss", "what": what, "texts": list(texts)})
    _say("   · ⚠ 没找到「%s」⇒ 不盲点（如实上报）" % ("/".join(texts),))
    return False


def do_recruit(b, log=None, tag="rec"):
    """点「招募」→ 跳过动画 → 结束招募 → 关页 -> out（got/skipped/ended/closed）

    ⚠ 用户口径（PC 原文）：「（按用户口径**不读结果**）⇒ 直接收尾」
      ⇒ 招募出的是谁**不读**（收益已在选标签那步最大化 ✓，读它只是多花 OCR）
    """
    import guild_daily as GC
    # ⛔⛔ v1.81【**用户报：免费招募选好选项也不确认**】
    #   ---- 病（三处叠加）----
    #     ① `GC.find(items, "招募")` 是**子串**匹配 ⇒ 面板上「指定招募」标题、
    #        「角色招募」「限时招募开启」横幅**全都命中** ⇒ 取到的是**标题那一行**、
    #        而不是底部那颗真按钮 ⇒ **点空** ✗
    #     ② 认不到就 fallback 到 `RECRUIT_BTN`（PC ×1.5 推算的 1080 参考系常量）——
    #        它只在 9:16 上对，真机 1280×2588 上偏 ✗
    #     ③ `out = {"got": True, ...}` **硬编码成功** ⇒ 点空了也报"已招募"⇒ 静默失效 ✗✗
    #   ---- 修法（三条都改）----
    #     ① **精确 + 排除**：只认「招募」这种**整条短文本**，且**排除**「指定招募/角色招募/
    #        限时招募/招募一次/招募十次/招募点数/改变心愿/招募预览」这些**标题/其他按钮** ✓
    #     ② 取**最靠下**那颗（底部主按钮都在面板下方）—— 比"最靠上"稳 ✓
    #     ③ **验证**：点完必须看到「跳过」/「恭喜获得」/「结束招募」/面板消失**任一**才算真招募；
    #        否则 `got=False` 并**如实记录**（不再硬编码 True ✗）
    items = GC.ocr_items(b, tag="%s_btn" % tag)

    # 这些是**标题/其它按钮**，不是这颗「招募」
    _NOT = ("指定招募", "角色招募", "限时招募", "招募一次", "招募十次",
            "招募点数", "改变心愿", "招募预览", "招募记录", "免费指定")
    _cands = []
    for _t in (items or []):
        _s = str(_t.get("text") or "").strip().replace(" ", "")
        if "招募" not in _s:
            continue
        if any(_x in _s for _x in _NOT):
            continue
        if len(_s) > 6:                 # 主按钮就两个字，长的一定是说明/标题
            continue
        _cands.append(_t)
    if _cands:
        it = max(_cands, key=lambda d: d.get("cy", 0))    # 取最靠下 ✓
        at = (int(it["cx"]), int(it["cy"]))
        _src = "ocr"
    else:
        it = None
        at = RECRUIT_BTN
        _src = "anchor_fallback"
    _log(log, {"recruit": "tap_btn", "at": list(at), "src": _src,
               "cands": [(c.get("text"), c.get("cx"), c.get("cy")) for c in _cands][:4]})
    _say("   · 点「招募」(%d,%d)%s"
         % (at[0], at[1], "（OCR 现读）" if it else "（标定坐标）"))
    # ⛔ OCR 坐标是归一化帧，tap_dlg 要弹窗系 ⇒ 必须 +C（否则偏 209 参考像素 ✗）
    #   见 `guild_daily._tap_xy` 的长注释（真机上就是这条导致点空）
    _cx = int(at[0])
    _cy = int(at[1]) + (int(round(_dlg_c())) if it is not None else 0)
    _tap_xy(b, _cx, _cy, wait=2.5, use_dlg=True)

    # ⭐ **验证真的点上了**（不再硬编码 got=True ✗）
    out = {"got": False, "skipped": False, "ended": False, "closed": False}
    _probe = None
    for _k in range(6):
        _pi = GC.ocr_items(b, tag="%s_after%d" % (tag, _k))
        if GC.has(_pi, "跳过", "恭喜获得", "结束招募", "招募结果"):
            _probe = _k + 1
            break
        if not panel_open(_pi):
            _probe = _k + 1          # 面板没了 ⇒ 也说明点上了 ✓
            break
        _sleep(b, 0.7)
    if _probe is not None:
        out["got"] = True
        _log(log, {"recruit": "btn_confirmed", "rounds": _probe})
        _say("   · ✓ 招募已触发（第 %d 轮确认）" % _probe)
    else:
        _log(log, {"recruit": "btn_no_effect",
                   "at": list(at), "src": _src,
                   "texts": [str((x or {}).get("text") or "") for x in
                             (GC.ocr_items(b, tag="%s_noeff" % tag) or [])][:12],
                   "note": "点完 6 轮都没看到跳过/结果/面板消失 ==> 如实记未招募"})
        _say("   · ⚠ 点「招募」后**6 轮没有任何反应** ⇒ 如实记「没招募」")
        return out

    out["skipped"] = _click_skip_anim(b, log, tag)
    _say("   · （按用户口径**不读结果**）⇒ 直接收尾")

    out["ended"] = _click_text_btn(b, log, tag, ("结束招募",),
                                   fallback=RECRUIT_END_BTN, what="结束招募")

    it3 = GC.ocr_items(b, tag="%s_x" % tag)
    if _on_recruit_home(it3) or panel_open(it3):
        out["closed"] = _click_text_btn(
            b, log, tag, ("×", "X", "关闭"), fallback=RECRUIT_CLOSE_X,
            what="关闭招募页", prefer_right=True)
    else:
        out["closed"] = True        # 已经不在招募页了 ⇒ 算关掉了 ✓
    return out


def run(b, log=None, recruit=True, wish=None, leave=False, force=False,
        return_to_map=None):
    """免费指定招募全流程 -> res（ok / picked / minR / recruited …）

    ⚠ 闸门顺序（PC 原样，**不能调**）：
      ① 面板已开 ⇒ 直接用（免费机会必然还在 ✓）
      ② 否则走到招募主页 ⇒ **量「指定招募」按钮亮度**
      ③ 灰的 且 没 force ⇒ **不动它**（避免误花宝石）
      ④ 读不到亮度 ⇒ **保守不动** ✓
      ⑤ 选标签 ⇒ **选上了才允许点招募**（PC 原话：「选了才允许招募 ✗」）
    """
    import guild_daily as GC
    log = log if log is not None else []
    res = {"ok": False, "tags": [], "picked": [], "minR": None,
           "recruited": False}
    _say("")
    _say("=" * 62)
    _status("免费抽卡 · 分析标签")
    _say("🎲 免费指定招募（%s）" % ("**只分析、不招募**" if not recruit
                                  else "分析 + 招募"))
    _say("=" * 62)

    roles, err = load_roles()
    if err:
        _say("   ⚠ %s ⇒ **这次不选最优**（只按标签类别提示，不瞎猜 ✗）" % err)
    else:
        _say("   ✓ 角色表：%d 行（从游戏数据表实时推 ✓）" % len(roles))

    items0 = GC.ocr_items(b, tag="rec0")
    if panel_open(items0):
        items = items0
        _say("   · 标签面板**已经开着** ⇒ 直接用（免费机会必然还在 ✓）")
        _log(log, {"recruit": "panel_already_open"})
    else:
        home_items = _to_recruit_home(b, items0, log, "rec")
        if home_items is None:
            _say("   ✗ 没能走到「招募主页」⇒ 放弃（不动任何东西）")
            res["why"] = "home_not_reached"
            return res

        _avail, _lum, _why = free_available(b, home_items)
        _log(log, {"recruit": "flag", "where": "recruit_home",
                   "free": _avail, "lum": _lum, "why": _why})
        if _avail is None:
            _say("   ⚠ 免费判据算不出来（%s）⇒ **保守起见不动它**"
                 "（宁可不做，也不误花宝石 ✗）" % _why)
            res["why"] = "free_unknown"
            return res
        if recruit and not _avail and not force:
            _say("   ⚠ 那颗「指定招募」**是灰的**（亮度 %.1f < %.0f）⇒ "
                 "今天的免费机会已用过 ⇒ **不动它**（避免误花宝石）"
                 % (_lum, FREE_BTN_LIT))
            res["why"] = "not_free"
            return res
        _say("   · 免费判据：%s（按钮亮度 %.1f）" % (_why, _lum))

        if not _tap_free_btn(b, home_items, log, "rec", note="（招募主页）"):
            _say("   ✗ 没打开「指定招募」标签面板 ⇒ 放弃（不动任何东西）")
            res["why"] = "panel_not_open"
            return res
        items = GC.ocr_items(b, tag="rec1")
    _say("   ✓ 「指定招募」面板已开")

    best, ranked, tags = analyze(items, roles, wish=wish)
    res["tags"] = tags
    if not tags:
        _say("   ✗ 一个标签都没读到 ⇒ 放弃（不瞎点）")
        res["why"] = "no_tags"
        return res
    if best is None:
        if not roles:
            _say("   ⚠ 没有角色表 ⇒ 只读标签、**不选也不招募**（不瞎猜 ✗）")
            res["why"] = "no_roles"
            return res
        _say("   ✗ 所有组合都匹配不到角色 ⇒ 放弃")
        res["why"] = "no_combo"
        return res

    res["picked"] = best["c"]
    res["minR"] = best["minR"]
    _say("")
    _say("   ★ 最优组合（小助手权重，共 %d 组）：**%s**"
         % (len(ranked), " + ".join(best["c"])))
    _say("     保底稀有度 = %d（%s）%s"
         % (best["minR"], RARITY_CN.get(best["minR"], "?"),
            ("  ⇒ 【%s】" % badge(best["minR"])) if badge(best["minR"]) else ""))
    _say("     权重 = %.1f ｜ 可能角色 %d 个：" % (best["w"], len(best["f"])))
    for r in best["f"][:8]:
        _say("       · %-10s %-3s %s/%s/%s %s"
             % (r[0], RARITY_CN.get(r[5], "?"), r[1], r[2], r[3], r[4]))
    if len(best["f"]) > 8:
        _say("       …（还有 %d 个）" % (len(best["f"]) - 8))
    _say("")
    _say("   · 备选前 3 组：")
    for r in ranked[1:4]:
        _say("       %-22s 保底%d 权重%.1f（%d 角色）"
             % (" + ".join(r["c"]), r["minR"], r["w"], len(r["f"])))

    if not recruit:
        _say("")
        _say("   ⓘ 只分析模式 ⇒ **没有点任何标签、没有招募** ✓")
        GC.close_panel(b, RECRUIT_CLOSE_X, "rec_x", probe_texts=("最多选择",),
                       log=log)
        res["ok"] = True
        res["why"] = "analyze_only"
        return res

    tags_xy = {t: (x, y) for t, x, y in read_tags(items)}
    if not pick_tags(b, best["c"], tags_xy, log=log):
        _say("   ✗ 标签没选上 ⇒ **不点招募**（选了才允许招募 ✗）")
        res["why"] = "tags_failed"
        GC.close_panel(b, RECRUIT_CLOSE_X, "rec_x2",
                       probe_texts=("最多选择",), log=log)
        return res
    _status("免费抽卡 · 已选 " + " + ".join(best["c"]))
    _say("   ✓ 标签已选：%s" % (" + ".join(best["c"])))

    _r = do_recruit(b, log)
    res["recruited"] = bool(_r.get("got"))
    res["skipped"] = bool(_r.get("skipped"))
    res["ended"] = bool(_r.get("ended"))
    res["closed"] = bool(_r.get("closed"))
    res["ok"] = bool(res["recruited"])

    _back_wanted = (RETURN_TO_MAP if return_to_map is None
                    else bool(return_to_map)) or bool(leave)
    if _back_wanted:
        _back = GC.leave_guild(b, log)
        res["back_to_map"] = bool(_back)
        _say("   · %s" % ("已返回地图界面（选图界面）✓" if _back
                          else "⚠ 没确认回到选图界面（如实上报）"))
    _log(log, {"recruit": "done", "picked": res["picked"],
               "minR": res["minR"], "recruited": res["recruited"],
               "skipped": res["skipped"], "ended": res["ended"],
               "back_to_map": res.get("back_to_map")})
    _say("=" * 62)
    return res


def summary_line(res):
    """一行摘要（收尾统计用）✓"""
    res = res or {}
    if res.get("why"):
        return "免费招募：跳过（%s）" % res["why"]
    return "免费招募：%s ｜ 保底 %s ｜ %s" % (
        " + ".join(res.get("picked") or []) or "—",
        RARITY_CN.get(res.get("minR"), "—"),
        "已招募 ✓" if res.get("recruited") else "没招")

