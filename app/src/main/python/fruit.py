# -*- coding: utf-8 -*-
"""fruit.py · **天赋果实记录**（背包 → 道具 → 识图读数量 → 落盘）—— 从 PC 端移植 (v1.78)

PC 源：mapbot_pc/fruit.py（635 行）

用户口径（PC 原文，分三次说的）：
    ① 「最后的最后（**做完日常，招募什么的且体力小于100就是最后了**）
       去**背包道具**里扫描下天赋果实数量，并且记录」
    ② 「类似**小助手的天赋果实记录**，做好放到**工具栏**里」
    ③ 补问确认：「存 runs 里吧，要**每个窗口独立计算**」
       「**自动扫描**，工具那里能看到天赋果实获取记录」

道具（PC 从游戏数据表查实）：
    special_item_10 ⇒ IDs = D00002_001、Name = 天赋果实
    描述「**可激活角色的隐藏天赋。**」、Type = 货币
⚠ 与小助手 FruitRecordView 里的 ../Shop/D00002_001.png **同一个道具 ID** ✓

⭐⭐ 移植口径：
   · **识图模板必须一起进资源包** —— PC 的 fruit_A_whole.png / _mask.png 已复制到
     assets/mapbot_pack/templates/（本仓），并把 PackInstaller.MARK 提到 .pack_v5；
     ⚠ 这一步是本项目的**教训 (k)**：新加的打包资产可能永远到不了已装设备
       （ensure() 是「标记在就直接 return」）⇒ 代码到了、图没到 ⇒ 判据静默失效 ✗
   · 计数判据、落盘格式、统计口径**逐条照 PC**（同一份 history 才能两端对拍 ✓）
"""
import io
import json
import os
import sys
import time

# ⭐ v1.78：点击一律走 `guild_daily.tap_target`（**文字优先 → 坐标兜底**）
#   ⚠ 模块级 import（写在函数里 ⇒ NameError 扫描看不到定义 ✓）
#   ⚠ 无循环导入：`guild_daily` **不** import `fruit`（它只在 explore_loop 的收尾链里被调）✓
from guild_daily import tap_target, _tap_xy  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_ROOT = os.environ.get("MAPBOT_ROOT") or _HERE
_RUNS = os.environ.get("MAPBOT_RUNS") or os.path.join(_ROOT, "runs")

FRUIT_ID = "D00002_001"
FRUIT_NAME = "天赋果实"

# 模板（与 PC 同名同位置 —— 已在 assets/mapbot_pack/templates/ 里 ✓）
FRUIT_TPL = os.path.join("templates", "fruit_A_whole.png")
FRUIT_MASK = os.path.join("templates", "fruit_A_whole_mask.png")

FRUIT_THR = 0.90                 # PC 实测阈值
FRUIT_SCALES = (0.9, 1.0, 1.1)   # 三档缩放（背包格子大小会随分辨率微变 ✓）

# 背包「道具」页里**可能出果实的那一片**（PC 设备系 y0,y1,x0,x1）
# ⚠ 手机参考系 1080×1920 ⇒ ×1.5（9:16 纯等比；与其它面板同一口径 ✓）
BAG_ITEM_BOX_720 = (220, 1120, 40, 700)
_PCS = 1.5
BAG_ITEM_BOX = tuple(int(round(v * _PCS)) for v in BAG_ITEM_BOX_720)

# ⚠ 下面两个只是**兜底锚点**（1080 参考系，过 RefMapper 换算）——
#   主路径一律先 OCR 找文字（「道具」页签 / 面板关闭符）✓
BAG_CLOSE_X = (int(round(671 * _PCS)), int(round(126 * _PCS)))   # 面板右上 X（兜底）
BAG_TAB_Y = int(round(173 * _PCS))      # 「道具」页签的兜底坐标
BAG_TAB_ITEM_X = int(round(617 * _PCS))


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


def _log(log, rec):
    if log is None:
        return
    try:
        log.append(rec)
    except Exception:       # noqa: BLE001
        pass


def record_path(b=None, tag=None):
    """记录文件路径 —— **每个实例独立一份**（用户口径：「要每个窗口独立计算」✓）

    ⚠ PC 的优先级：Bot 的 runs 目录 > HERE/runs[/tag] ⇒ 手机端 b.runs 已经是
      filesDir/runs/<tag> ⇒ 天然满足「每个窗口独立」✓
    """
    if b is not None:
        try:
            return os.path.join(b.runs, "fruit_record.json")
        except Exception:       # noqa: BLE001
            pass
    base = os.path.join(_RUNS, tag) if tag else _RUNS
    return os.path.join(base, "fruit_record.json")


def find_fruit(b, img=None):
    """在背包「道具」页里找**天赋果实图标** -> (cx, cy, score) 或 None

    ⚠ 判据 = **带 mask 的 TM_SQDIFF**（PC 原样）：
      · 图标是**不规则形状**、周围是同色格子底 ⇒ 不带 mask 会被背景拉低分数 ✗
      · 三档缩放（0.9/1.0/1.1）取最高分 ✓
      · 归一化 `1 - mn/(mask_sum*255*255)` ⇒ 与图片大小无关，阈值 0.90 可跨分辨率用 ✓
    """
    import cv2
    import numpy as np
    tp = os.path.join(_ROOT, FRUIT_TPL)
    mp = os.path.join(_ROOT, FRUIT_MASK)
    if not (os.path.exists(tp) and os.path.exists(mp)):
        _say("   ⚠ 果实模板缺失：%s" % FRUIT_TPL)
        _say("     （⚠ 若设备是**从旧版升级上来的**：PackInstaller.MARK 没变的话")
        _say("      新模板永远解不进去 —— 见本项目教训 (k) ✓）")
        return None
    tpl = cv2.imdecode(np.fromfile(tp, dtype=np.uint8), cv2.IMREAD_COLOR)
    msk = cv2.imdecode(np.fromfile(mp, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if tpl is None or msk is None:
        _say("   ⚠ 果实模板读不出来")
        return None
    if img is None:
        img = b.img()
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    y0, y1, x0, x1 = BAG_ITEM_BOX
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    sub = sub.astype(np.float32)
    best = None
    for _us in FRUIT_SCALES:
        _w = int(round(tpl.shape[1] * _us))
        _h = int(round(tpl.shape[0] * _us))
        if _w < 8 or _h < 8 or _w >= sub.shape[1] or _h >= sub.shape[0]:
            continue
        _t = cv2.resize(tpl, (_w, _h), interpolation=cv2.INTER_AREA).astype(np.float32)
        _m = cv2.resize(msk, (_w, _h), interpolation=cv2.INTER_NEAREST)
        _mf = (_m > 0).astype(np.float32)
        if float(_mf.sum()) < 20.0:
            continue
        res = cv2.matchTemplate(sub, _t, cv2.TM_SQDIFF, mask=_mf)
        res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
        mn, _mx, loc, _ml = cv2.minMaxLoc(res)
        _sc = 1.0 - mn / (float(_mf.sum()) * 255.0 * 255.0)
        if best is None or _sc > best[0]:
            best = (_sc, _us, x0 + loc[0] + _w // 2, y0 + loc[1] + _h // 2)
    if best is None:
        return None
    score, _used, cx, cy = best
    _say("   · 果实识图最好成绩 %.3f @(%d,%d) 尺度 %.2f（阈值 %.2f）"
         % (score, cx, cy, _used, FRUIT_THR))
    return ((int(cx), int(cy), round(float(score), 3))
            if score >= FRUIT_THR else None)


def _read_count(items, cx, cy, max_d=90):
    """读图标**右下角**那个数量 -> int 或 None

    ⚠ 窗口是「**同一行（|Δy|<=40）且 x 在 [cx-10, cx+max_d]**」——
      背包里一格里还有别的数字（等级/品质），窗口开大就会读错 ✗
    ⚠ 取**距离最近**的那个（PC 原口径 ✓）
    """
    best = None
    for it in (items or []):
        t = str(it.get("text") or "").strip()
        if not t.isdigit():
            continue
        _cx, _cy = it.get("cx", -9999), it.get("cy", -9999)
        if abs(_cy - cy) > int(round(40 * _PCS)):
            continue
        if not (cx - int(round(10 * _PCS)) <= _cx <= cx + int(round(max_d * _PCS))):
            continue
        d = abs(_cx - cx) + abs(_cy - cy)
        if best is None or d < best[0]:
            best = (d, int(t), it)
    return best[1] if best else None



def scan(b, log=None, leave=True, enter_guild=True):
    """背包 → 道具 → 识图 → 读数量 -> res（ok / count / why / score / at）

    ⚠ **读不到就如实报失败**（PC 原话：「识图没找到 ⇒ 如实报失败（可能这号背包里
      没有它 ✓）」）—— 绝不用 0 或瞎猜的数字冒充 ✓
    """
    import guild_daily as GC
    log = log if log is not None else []
    res = {"ok": False, "count": None, "why": None, "score": None, "at": None}
    _say("")
    _say("=" * 62)
    _say("🍒 扫天赋果实（背包 → 道具 → 读数量）")
    _say("=" * 62)

    if enter_guild:
        if not GC.goto_guild(b, log):
            _say("   ✗ 进不了公会 ⇒ 放弃（不瞎报数字 ✓）")
            res["why"] = "not_in_guild"
            return res

    try:
        import explore_loop as _EL
        bag_btn = tuple(_EL.BAG_BTN)
    except Exception:       # noqa: BLE001
        bag_btn = (964, 1680)         # 手机参考系兜底（= explore_loop.BAG_BTN ✓）
    # ⭐ 背包入口**文字优先**（「背包」二字）；读不到才用 explore_loop.BAG_BTN 兜底 ✓
    tap_target(b, GC.ocr_items(b, tag="fruit_bagbtn"), ("背包", "道具"),
                    bag_btn, log=log, tag="fruit_bag", wait=2.6)
    items = GC.ocr_items(b, tag="fruit_bag")
    _opened = GC.has(items, "背包", "素材", "装备", "符文", "道具", "宝箱")
    _log(log, {"fruit": "open_bag", "at": bag_btn, "opened": _opened})
    _say("   · 开背包 %s ⇒ %s" % (bag_btn, "已打开 ✓" if _opened else "没打开 ✗"))
    if not _opened:
        res["why"] = "bag_not_open"
        return res

    # ⭐ **文字优先**：「道具」页签读得到就点它；读不到才用标定坐标兜底 ✓
    it = GC.find(items, "道具")
    tab = (int(it["cx"]), int(it["cy"])) if it else (BAG_TAB_ITEM_X, BAG_TAB_Y)
    tap_target(b, items, ("道具",), tab, log=log, tag="fruit_tab",
                    wait=2.4, use_dlg=True)
    items = GC.ocr_items(b, tag="fruit_items")
    _log(log, {"fruit": "tap_item_tab", "at": tab, "by": "ocr" if it else "calib"})
    _say("   · 切「道具」页 %s %s" % (tab, "（OCR 现读）" if it else "（标定）"))

    hit = find_fruit(b)
    if not hit:
        _say("   ✗ 识图没找到「天赋果实」⇒ 如实报失败（可能这号背包里没有它 ✓）")
        _log(log, {"fruit": "not_found"})
        res["why"] = "fruit_not_found"
        _close_bag(b, log)
        if leave:
            _back(b, log)
        return res
    cx, cy, score = hit
    res["score"] = score
    res["at"] = (cx, cy)
    items2 = GC.ocr_items(b, tag="fruit_cnt")
    cnt = _read_count(items2, cx, cy)
    _log(log, {"fruit": "icon_hit", "at": (cx, cy), "score": score, "count": cnt})
    _say("   · 认到果实 (%d,%d) 分数 %.3f ⇒ 数量 = **%s**"
         % (cx, cy, score, cnt if cnt is not None else "读不到 ✗"))
    _close_bag(b, log)
    if leave:
        _back(b, log)
    if cnt is None:
        res["why"] = "count_unreadable"
        return res
    res["ok"] = True
    res["count"] = cnt
    _say("   ✓ 天赋果实 = **%d** 个" % cnt)
    _say("=" * 62)
    return res


def _close_bag(b, log=None):
    """关背包 —— 优先复用 explore_loop 的 _close_bag（它认得「背包」面板）✓"""
    try:
        import explore_loop as _EL
        if hasattr(_EL, "_close_bag"):
            _EL._close_bag(b, b.ocr(tag="fruit_close"), log)
            return True
    except Exception as e:      # noqa: BLE001
        _log(log, {"fruit": "close_bag_err", "e": repr(e)[:100]})
    # ⭐ **文字优先**：背包面板的关闭符（× / X / 关闭）—— 位置随面板宽度变，
    #   写死坐标换机型就点空 ✗（PC 记过：面板 X 落在弹性区、归一化帧里根本看不见）
    #   读不到才用 BAG_CLOSE_X 兜底（1080 参考系、有 RefMapper 换算 ✓）
    try:
        _it = GC.ocr_items(b, tag="fruit_close")
        tap_target(b, _it, ("×", "X", "x", "✕", "✖", "关闭"), BAG_CLOSE_X,
                       log=log, tag="fruit_close", wait=1.8, use_dlg=True)
    except Exception as _e:      # noqa: BLE001
        # ⚠ 走到这里说明**连 OCR 都抛了异常** ⇒ 这时候**不该再盲点坐标** ✗
        #   （拿不到帧/通道坏了的情况下盲点，落点完全不可控 —— 本项目反复栽在这上面）
        #   ⇒ 如实记「没关成」，交给上层（`_back` / 下一轮）处理 ✓
        _log(log, {"fruit": "close_err", "e": repr(_e)[:100],
                   "note": "OCR 异常 ⇒ 不盲点，如实上报"})
        return False
    return True


def _back(b, log=None):
    """回选图界面（用户口径：「最后都要回到地图界面」✓）"""
    try:
        import guild_daily as GC
        ok = GC.leave_guild(b, log)
        _log(log, {"fruit": "back_to_map", "ok": bool(ok)})
        _say("   · %s" % ("已返回地图界面 ✓" if ok else "⚠ 没确认回到选图界面"))
        return ok
    except Exception as e:      # noqa: BLE001
        _log(log, {"fruit": "back_err", "e": repr(e)[:100]})
        return False


# ══════════════════════════════════════════════════════════════════════
# 记录 / 统计（**口径逐条照 PC**，同一份 history 才能两端对拍 ✓）
# ══════════════════════════════════════════════════════════════════════
def load_records(b=None, path=None):
    """读历史记录 -> list（只保留**格式正确**的条目；坏文件当空 ✓）"""
    p = path or record_path(b)
    if not os.path.exists(p):
        return []
    try:
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("records"), list):
            d = d["records"]
        if not isinstance(d, list):
            return []
        return [r for r in d if isinstance(r, dict) and r.get("date")
                and isinstance(r.get("count"), int)]
    except Exception:       # noqa: BLE001
        return []


def save_records(recs, b=None, path=None):
    """写历史记录 —— **先写 .tmp 再 os.replace**（原子替换，断电不留半个文件 ✓）"""
    p = path or record_path(b)
    try:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = p + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(recs, ensure_ascii=False, indent=1))
        os.replace(tmp, p)
        return True
    except Exception as e:      # noqa: BLE001
        _say("   ⚠ 记录写入失败：%r" % (e,))
        return False


def _today():
    return time.strftime("%Y-%m-%d")


def diff_of(prev, curr):
    """两次读数之差 —— **变负 ⇒ 当作"用掉了"**（记 0，不记负数 ✓）

    ⚠ PC 口径：差额只认**正数**（获取量）；消耗量单独记 `consumed` ✓
    """
    try:
        return max(0, int(curr) - int(prev))
    except (TypeError, ValueError):
        return 0


def record(b, count, log=None, consumed=None, remark="", path=None):
    """记一条（**同一天只留一条，后写的覆盖**）-> (ok, res, stats)

    ⚠ PC 口径（照抄，别改）：
      · 同一天重复扫描 ⇒ **覆盖**那一条（不追加）⇒ 一天一条，曲线上不会出现锯齿 ✓
      · 「昨日数量」= 上一条的 count ⇒ 获取量 = 今天 − 昨天 ✓
    """
    recs = load_records(b, path)
    today = _today()
    prev = None
    for r in reversed(recs):
        if r.get("date") != today:
            prev = r
            break
    _p = prev.get("count") if prev else None
    rec = {"date": today, "count": int(count), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if _p is not None:
        rec["prev"] = int(_p)
        rec["gain"] = diff_of(_p, count)
    if consumed is not None:
        try:
            rec["consumed"] = int(consumed)
        except (TypeError, ValueError):
            pass
    if remark:
        rec["remark"] = str(remark)[:120]
    keep = [r for r in recs if r.get("date") != today]
    keep.append(rec)
    keep.sort(key=lambda r: str(r.get("date") or ""))
    ok = save_records(keep, b, path)
    _log(log, {"fruit": "record", "ok": bool(ok), "rec": rec})
    return ok, rec, stats(keep)


def stats(recs):
    """统计 -> dict（total_get / days / avg / first / last ✓）"""
    rs = [r for r in (recs or []) if isinstance(r, dict)]
    if not rs:
        return {"total_get": 0, "days": 0, "avg": None, "first": None, "last": None}
    gains = [int(r.get("gain") or 0) for r in rs]
    total = sum(gains)
    # ⚠ 分母是「**有 gain 的天数 − 1**」：第一天没有"昨天"，算不出获取量 ⇒ 不算一天 ✓
    _n = max(1, len([g for g in gains if g is not None]) - 1) if len(rs) > 1 else 1
    return {"total_get": total,
            "days": len(rs),
            "avg": (round(total / float(_n), 1) if total else None),
            "first": rs[0].get("date"),
            "last": rs[-1].get("date")}


def scan_and_record(b, log=None, leave=True):
    """扫描 + 落盘（主循环调用这一个 ✓）-> (ok, res, stats)"""
    res = scan(b, log, leave=leave)
    if not res.get("ok"):
        return False, res, stats(load_records(b))
    ok, _rec, st = record(b, res["count"], log=log)
    return bool(ok), res, st


def report_text(b=None, path=None, limit=20):
    """记录的人话摘要（界面「工具」页用 ✓）"""
    recs = load_records(b, path)
    st = stats(recs)
    if not recs:
        return "天赋果实：还没有记录（体力 < 100 收工时会自动扫一次）"
    lines = ["天赋果实记录（共 %d 天）" % st["days"],
             "  累计获取 %s ｜ 日均 %s" % (st["total_get"], st["avg"] if st["avg"] is not None else "—"),
             "  最新：%s = %d 个" % (recs[-1].get("date"), int(recs[-1].get("count") or 0))]
    for r in recs[-max(1, int(limit)):]:
        g = r.get("gain")
        lines.append("    %s  %5s 个%s"
                     % (r.get("date"), r.get("count"),
                        ("  (+%s)" % g) if g else ""))
    return "\n".join(lines)

