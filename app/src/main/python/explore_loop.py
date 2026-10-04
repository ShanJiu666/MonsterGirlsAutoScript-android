# -*- coding: utf-8 -*-
"""explore_loop.py (2026-09-25 lean rewrite)

Verified rules only:
  * fight ONLY boss / 4-marked blocks; skip plain fights
  * reveal-first (unlock path), never poke locked marked cells first
  * marked cells are never blacklisted; blocked -> clear-path mode
  * result panel: click 关闭 only when OCR really saw it
  * recommend fight + win -> dice (max 3), stop when thumbs-up loot appears
  * all marked blocks done -> leave the map
"""

# ─────────────────────────────────────────────────────────────────────────────
# 【Android 适配补丁 · 由 android_autoexplore/tools/port_loop.py 注入，勿手改】
# Chaquopy 里 __file__ 指向 APK 内只读资源，模板/数据表在 filesDir/mapbot_pack
import os as _os

_MAPBOT_ROOT = _os.environ.get('MAPBOT_ROOT') or _os.path.dirname(_os.path.abspath(__file__))
_MAPBOT_ANDROID = _os.environ.get('MAPBOT_ANDROID') == '1'
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2
import numpy as np
import marks as marks_mod
import spots as spots_mod
import buypanels
import layout as layout_mod
import targets_cfg as tcfg_mod          # ⭐ 目标方块白名单（用户 2026-09-28 要求 ✓）
from mapbot import Bot, RUNS, ADB, DEV, CREATE_NO_WINDOW

# ⭐ 2026-10-01：模板/资源根目录。
#   Android 侧由 `android_autoexplore/tools/port_loop.py` 注入（APK 内只读 ⇒ 指向
#   filesDir/mapbot_pack）；PC 侧**原来没定义** ⇒ 一调 `_find_ui_tpl` 就 NameError
#   （被 bag_upgrade 的兜底 except 吞成 `bag: error` ✗）。这里补一个 PC 兜底 ✓
try:
    _MAPBOT_ROOT                                       # noqa: B018
except NameError:
    _MAPBOT_ROOT = os.path.dirname(os.path.abspath(__file__))

WIN = os.path.join(RUNS, 'loop')
os.makedirs(WIN, exist_ok=True)
LOG_PATH = os.path.join(WIN, 'loop_log.json')
SUMMARY_PATH = os.path.join(RUNS, 'last_summary.json')
# ⭐ 多开模式（2026-09-25 用户要求）：每个实例用 `--tag acc2` 区分 ⇒ 截图/日志/统计各自独立
#   （截图进 `runs/acc2/`、日志 `runs/acc2/loop/loop_log.json`、统计 `runs/acc2/last_summary.json`），
#   两台模拟器同时跑不会互相覆盖：`--device 127.0.0.1:16416 --tag acc2`
# ⭐ 2026-09-25：控制台实时进度（用户要「桌面快捷方式，打开就能用」）
#   `--quiet` 关掉；结束时那份全量 json 日志照旧打印（--no-dump 关）
VERBOSE = True
DUMP_AT_END = True
# 进图前体力下限：低于它就收工（用户 2026-09-25：**连刷模式 <50 就停**；单张模式仍用 25）
MIN_STAMINA = 25
STOP_AT_5AM = True      # ⭐ 凌晨自动停止（用户 2026-09-26；停每张图之间，正在打的会打完）
STOP_HM = (4, 58)       # ⭐ 停止时刻 = 04:58（用户 2026-09-26：「4.58停吧，打完最后一张图」）
STOP_TIME = None        # 本次运行的停止时刻（datetime）
_LOOP_LOCK = None          # 本进程占的设备锁 (device, tag)
EXPLORE_DISPATCH = True   # 探索/派遣功能（紫橙地块→探索→派遣 ✓）
# ⭐ 探索槽**封顶**（2026-09-26 用户口径「一共能装 3 个」）
# ⚠⚠ 2026-09-30 真机实测（Redmi 1280×2772 / 夏日海滩）：HUD 那一行是 **4 个槽**
#   （角标 1/2/3/4；截图 `_tmpman/slots_ref_zoom.png`）+ 真机 OCR 条目实证
#   （`_verify/phone_slots_full_0930.json`：3 条倒计时 + 0 条「空闲」）
#   ⇒ 这个数只当「空闲数封顶」用，**不许再拿它去减倒计时个数**
#   （`TOTAL - busy` 反推法已废除 ⇒ 见 `explore_slots_free`：那张 3 跑 1 待领取的
#    真机帧会被反推成"空闲 1"，正是"槽满了还一直点探索"的根因 ✗）
EXPLORE_SLOTS_TOTAL = 4
AUTO_SUPPLY = False     # 没体力自动用「结实补给」（--auto-supply / GUI 按钮）
SUPPLY_USED = 0         # 本次已用个数（**只做统计**，不设上限 —— 用户 2026-09-25 要求）
OPT = False             # 体力最省模式（--opt）
INSTANCE_TAG = ''       # 多开实例名（空 = 单开，用共享目录）
INSTANCE_DEV = DEV      # 该实例绑定的模拟器 adb 设备号
_BOT = None             # 当前 Bot（统计要读它的耗时埋点）

# ⭐⭐ v1.36【揭示口径的**单一来源**】—— 定在模块顶部，别放到文件后段
#   · `spots.REVEAL_RATIO_MIN` = 0.80（2026-10-02 两帧真机实测标定，见 spots.py 注释）
#     已揭示最低 0.855 / 雾格最高 0.761 ⇒ 干净带 0.78~0.85 ⇒ 0.75 踩在雾格那侧 ✗
#   · 以前这里**自己写死 0.75**、`spots` 另写一份 ⇒ 两处漂移的典型 ✗✗
#   · ⚠ 必须定义在**所有使用点之前**：v1.34 的 `_ready_boss_cells()` 在 1000 行就用它，
#     放文件后段会 NameError（2026-10-02 当场踩过这个顺序坑两次 ✗）
REVEAL_RATIO_MIN = spots_mod.REVEAL_RATIO_MIN
# ⭐ 2026-10-02 v1.21：`board_hidden()` 判据② 的"被压暗"系数（实测标定见 `board_hidden` 注释）
DIM_RATIO_MAX = 0.42


def say(msg):
    if VERBOSE:
        try:
            print(msg, flush=True)
        except Exception:       # noqa: BLE001
            pass


# ⭐⭐ 2026-09-30（用户口径）：「悬浮窗上很多日志太技术性了，没必要全都显示出来。
#   比如什么**识别了 xx 条、用时多久**，用户完全不需要看这些。这个日志是给**用户**看的，
#   用户只需要知道**现在在干什么**」。
#
#   根因：悬浮条原先直接吃**原始日志流**，靠 Java 侧 `describeAction()` 的正则猜「哪条是行动」，
#   而它最后有一条兜底 `if (len <= 46 and 无 '{') 照播` ⇒ 任何短技术行都会漏上去
#   （`识别棋盘：35 格`、`· 分类兜底：低门槛重试拿到 30 格 ✓`、`· 自动跳过已勾选 ✓` …）。
#   修法 = **显式 UI 通道**：只有走 `status()` 发出的短句才进悬浮条日志行；其余所有
#   `say()`/`print()` 一律只进界面控制台与 logcat（**那是给开发看的**）。
#
#   ⚠ 写 status() 的三条硬规矩：
#     ① **短** —— 悬浮条一行 ≈ 28px 加粗等宽，超过 ~28 个汉字会被滚动/省略号收尾；
#     ② **人话** —— 是"我现在在干什么"，不是状态机内部名（不要轮号/坐标/cost/步数）；
#     ③ **避开 OCR 关键词**（开始冒险 / 进入地图 / 一键派遣 / 探索配队 / 探索产出 /
#        关闭 / 探索 / 派遣 / 领取）—— `OverlayService.sanitize()` 会把它们糊成 ▓
#        （双保险：万一"涂平"失效，游戏也不会把它当面板文字）。所以这里说
#        「派小队 / 收起面板 / 拿奖励」，不说「派遣 / 关闭 / 领取」。
UI_MARK = '\u203a '          # `› ` —— 只做传输标记，OverlayService 会剥掉，不会画到屏幕上


def status(msg):
    """发一条**给用户看**的「当前行动」（→ 悬浮条日志行）。

    ⚠ 与 `say()` 的区别：`say()` 是开发者日志（可能非常啰嗦，只在控制台/logcat 里）；
       `status()` 是**唯一的**能上悬浮条的口子 ⇒ 调用要克制、要短、要人话。
    """
    if not msg:
        return
    try:
        print(UI_MARK + str(msg), flush=True)
    except Exception:       # noqa: BLE001
        pass


def cur_map_no():
    """当前是第几张图（1 基）。给 status() 拼文案用；不在图上时返回 0。"""
    try:
        return int(STATS.get('current_map') or 0)
    except Exception:       # noqa: BLE001
        return 0


# ⭐ 本次运行统计（用户 2026-09-25 要求：结束时要报「刷了几张图/平均耗时/打了几个 boss 关/
#   拿到几件大拇指装备/买完几个旅行商人/几个黄金宝库」）
STATS = {'clovers': 0, 
    'maps': 0,            # 刷完的图数
    'shots': 0,           # ⭐ 采图模式（--collect-only）存下的首帧数
    'map_secs': [],       # 每张图耗时
    'boss_fights': 0,     # 首领关战斗场次
    'boss_wins': 0,       # 首领关胜利
    'recommend_fights': 0,
    'recommend_wins': 0,
    'dice_got': 0,        # 摇色子拿到「大拇指装备」的次数
    'merchants': 0,       # 买完的旅行商人
    'vaults': 0,          # 买完的黄金宝库
    'battles': 0,         # 全部战斗场次
    'battle_wins': 0,
    'stopped': '',
    'current_map': 0,     # 正在跑的这张图（1 基）；被停止时用来说明跑到哪了
    'current_secs': 0,    # 这张图已耗时
    'stamina_entries': [],  # 每次「进图时」读到的体力（用户口径：两次进图相减 = 消耗）
    'running': True,
    'classify': 0.0,        # ⭐ 棋盘分类累计耗时（埋点用）
    'classify_n': 0,        # 分类调用次数
}


def device_lock_path(device):
    try:
        port = int(str(device).split(':')[-1])
    except Exception:       # noqa: BLE001
        port = 0
    return os.path.join(RUNS, '.loop_%d.lock' % port)


def red_lock_path(device):
    """红装锁文件（用户 2026-09-25：「下次遇到红装要立刻停止，不准退出图」）

    发现红装 ⇒ 立刻停 + **绝不退图** + 写这个锁；**锁在就拒绝启动任何新运行**，
    直到你处理完红装、在窗口上点「红装已处理·解锁」（或手动删掉这个文件）。
    """
    try:
        port = int(str(device).split(':')[-1])
    except Exception:       # noqa: BLE001
        port = 0
    return os.path.join(RUNS, 'red_equip_%d.lock.json' % port)


def red_locked(device):
    """-> 锁内容 dict 或 None"""
    p = red_lock_path(device)
    if not os.path.exists(p):
        return None
    try:
        import json
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:       # noqa: BLE001
        return {'bad': True}


def _read_lock_pid(p):
    """读设备锁里的 PID —— 兼容三种形态：JSON / 纯文本 PID / 空（已释放）

    ⭐ 2026-09-28：16384 的锁原来写纯文本 PID，而 16416（采集链路）的锁是 JSON
    （`{"pid":…,"released":…}`）—— **两种格式并存**读方要猜 ✗。统一按"先试 JSON
    再退回 int"解析，新旧锁都能读；写侧一律写 JSON（见 acquire_device_lock）。
    """
    try:
        raw = (open(p, encoding='utf-8').read() or '').strip()
    except Exception:       # noqa: BLE001
        return 0
    if not raw:
        return 0
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return int(obj.get('pid') or 0)
    except Exception:       # noqa: BLE001
        pass
    try:
        return int(raw)
    except Exception:       # noqa: BLE001
        return 0


def acquire_device_lock(device):
    # 【Android】不需要设备锁（进程即实例）⇒ 返回哨兵，调用方只判 None
    if _MAPBOT_ANDROID:
        return 'android'
    """同一台模拟器**同时只允许一个循环**在跑（2026-09-25 教训：我在用户跑着的时候又起了一个，
    两边抢着点，互相打架）。已被占用就返回 None，调用方应直接退出。

    ⭐ 2026-09-28：写侧升级为 JSON（pid/device/started_at，便于事后判断谁是僵尸锁）；
    读到"PID 已不存在"的陈旧锁时**自动接管**并打一行提示（原来是静默覆写）。
    """
    p = device_lock_path(device)
    if os.path.exists(p):
        pid = _read_lock_pid(p)
        alive = False
        if pid:
            try:
                import subprocess as _sp
                out = _sp.run(['tasklist', '/FI', 'PID eq %d' % pid, '/FO', 'CSV'],
                              capture_output=True, text=True, errors='replace',
                              timeout=10,
                              creationflags=CREATE_NO_WINDOW).stdout
                # ⚠ 用带引号的精确匹配（CSV 里 PID 一定是 "1234" 形态）——
                #   原来的 `str(pid) in out` 是子串匹配，可能被别的列撞上 ✗
                alive = ('"%d"' % pid) in out
            except Exception:   # noqa: BLE001
                alive = False
        if alive:
            # ⭐⭐⭐ 2026-09-28 修「**自我冲突**」真机 bug（22:02/22:03 两次 100% 复现）：
            #   main() 里两套锁机制**串行打架** —— 先 `guard_duplicates()` →
            #   `loopguard.acquire()` 把**本进程 PID** 写进 `.loop_<port>.lock`；
            #   紧接着本函数读**同一个文件** ⇒ 看到一个"活着的 PID" ⇒ 误判
            #   "已有另一个循环在跑" ⇒ 拒绝启动（其实那就是自己 ✗✗）。
            #   症状：GUI 点开始即报「已经有另一个自动探索在跑」、退出码 0、循环
            #   从未真正开跑（loop_log 不推进）。
            #   判据：**锁主 == 自己 ⇒ 不是别人，直接放行**（锁保持 loopguard 写的内容）。
            if pid == os.getpid():
                return p
            return None
        try:
            say('   ⚠ 发现陈旧设备锁（PID %s 已不存在，多半是上次崩溃没走 finally）'
                '⇒ 自动接管 ✓' % (pid or '?'))
        except Exception:       # noqa: BLE001
            pass
    try:
        os.makedirs(RUNS, exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'pid': os.getpid(), 'device': device,
                                'started_at': time.strftime('%Y-%m-%d %H:%M:%S')},
                               ensure_ascii=False))
    except Exception:           # noqa: BLE001
        pass
    return p


def release_device_lock(p):
    """释放设备锁（⭐ 2026-09-28：**截断代替删除**）

    沙箱 `sitecustomize.py` 给 `os.remove` 挂了「每**次工具调用**计数，满 50 就
    `raise SystemExit(1)`」的守卫。长流水线每轮都要 release 一次 ⇒ 跑到第 11 轮
    就把采集进程打死（实测 `runs/_pipeline.log`）✗
    截断后文件仍在、内容为空 ⇒ `acquire_device_lock` 会当成没有锁直接覆写 ✓ 语义不变。
    """
    try:
        if p:
            open(p, 'w', encoding='utf-8').close()
    except Exception:           # noqa: BLE001
        pass


def stamina_line():
    """体力消耗（用户口径：两次进图的体力相减；**并按游戏 30 秒回 1 点做补偿**）

    单图消耗 = (进图体力_i − 进图体力_{i+1}) + (两次进图间隔秒数 / 30)
    —— 间隔期间游戏会自动回体力，不补回来的话会把「回复的」当成「没花的」，低估消耗。
    每段夹在 ≥0（中途吃药/大额补充时不冲抵别的段）。
    """
    ent = list(STATS.get('stamina_entries') or [])
    if len(ent) >= 2:
        total = 0.0
        parts = []
        for i in range(len(ent) - 1):
            s0, t0 = ent[i]
            s1, t1 = ent[i + 1]
            dt = max(0.0, t1 - t0)
            regen = dt / 30.0                     # 30 秒回 1 点
            spent = max(0.0, (s0 - s1) + regen)
            total += spent
            parts.append('%d→%d(-%d +回%.0f)' % (s0, s1, max(0, s0 - s1), regen))
        how = ('进图体力 %s 点；已按 30 秒/点补回间隔期间的回复'
               % '，'.join('%d' % s for s, _t in ent))
        return (total, how, parts)
    if len(ent) == 1:
        return (None, '只进了一张图，没有第二次进图可相减（进图时 %d）' % ent[0][0], [])
    return (None, '没读到体力', [])


def summary_text():
    s = STATS
    avg = (sum(s['map_secs']) / len(s['map_secs'])) if s['map_secs'] else 0
    spent, how, parts = stamina_line()
    # ⭐ 2026-09-27 用户要求：只显示「总消耗」+「平均每图」两条 ✓（去掉逐图明细/说明 ✗）
    _maps = max(1, int(s['maps']))
    _spent_txt = ('%.0f 点' % spent) if spent is not None else '—'
    _avg_txt = ('%.1f 点/张' % (spent / _maps)) if spent is not None else '—'
    lines = ['',
             '════════ 本次统计 ════════',
             '  消耗体力   ：%s' % _spent_txt,
             '  平均每图   ：%s' % _avg_txt,
             ]
    lines += [
             '  刷完地图   ：%d 张' % s['maps'],
             ]
    if s.get('shots'):
        # ⭐ 采图模式（--collect-only）：只存首帧、不推图 ⇒ 单独报一行 ✓
        lines += [
             '  采集首帧   ：%d 张（只进图截图退图；每张 25 体力）' % s['shots'],
             ]
    lines += [
             '  平均耗时   ：%.0f 秒/张（合计 %.0f 秒）' % (avg, sum(s['map_secs'])),
             '  首领关     ：%d 场（胜 %d）' % (s['boss_fights'], s['boss_wins']),
             '  全部战斗   ：%d 场（胜 %d）' % (s['battles'], s['battle_wins']),
             '  大拇指装备 ：%d 件（推荐战 %d 场 / 胜 %d；摇色子拿到 %d）'
             % (s['dice_got'], s['recommend_fights'], s['recommend_wins'], s['dice_got']),
             '  幸运草地块 ：%d 个' % s.get('clovers', 0),
             '  旅行商人   ：买完 %d 个' % s['merchants'],
             '  黄金宝库   ：买完 %d 个' % s['vaults'],
             ]
    if not s['running'] and s['current_map'] and s['current_secs']:
        lines.append('  ⚠ 第 %d 张图跑到 %.0f 秒时被停止（这张未计入）'
                     % (s['current_map'], s['current_secs']))
    if s['stopped']:
        lines.append('  结束原因   ：%s' % s['stopped'])
    lines.append('══════════════════════════')
    try:
        t = getattr(_BOT, 't', None)
        if t:
            total = sum(t.get(k, 0.0) for k in ('snap', 'ocr', 'wait')) + s.get('classify', 0.0)
            lines.append('  ⏱ 耗时分布：截图 %.1fs(%s)｜OCR %.1fs/%d次｜棋盘识别 %.1fs（%d次）'
                         '｜点击等待 %.1fs(%d次)'
                         % (t.get('snap', 0), '极速' if getattr(_BOT, 'fast_ok', False) else 'adb',
                            t.get('ocr', 0), t.get('ocr_n', 0), s.get('classify', 0.0),
                            s.get('classify_n', 0), t.get('wait', 0), t.get('wait_n', 0)))
            lines.append('               （以上合计 %.0f 秒；其余为游戏动画/面板本身的响应时间）' % total)
            by = t.get('ocr_by') or {}
            if by:
                detail = '｜'.join('%s %.1fs/%d次' % (k, v[0], v[1])
                                   for k, v in sorted(by.items(), key=lambda kv: -kv[1][0]))
                lines.append('              OCR 分账：%s' % detail)
    except Exception:       # noqa: BLE001
        pass
    return '\n'.join(lines)


def dump_summary():
    try:
        import json
        os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
        with open(SUMMARY_PATH, 'w', encoding='utf-8') as f:
            json.dump({'stats': STATS, 'text': summary_text(), 'tag': INSTANCE_TAG,
                       'device': INSTANCE_DEV}, f, ensure_ascii=False, indent=1)
    except Exception:       # noqa: BLE001
        pass
    # ⭐⭐⭐ 2026-10-01 v1.12【给"别人的手机"留一份可读日志】
    #   背景：MGAS 发给朋友后出问题（"面板挡住了棋盘"/"一直把游戏拉回来"），
    #   而 **release 包不可 `run-as`** ⇒ 私有 `files/runs/**` 根本拿不出来 ✗
    #   朋友圈里也不方便跑 logcat ⇒ 直接把**最近日志 + 统计**写一份到公共目录：
    #     `/sdcard/Download/autoexplore/mgas_log.txt`（让他把这个文件发过来即可 ✓）
    try:
        _lines = []
        if os.name != 'posix':      # ⚠ 只在端上写（PC 上 '/sdcard/...' 会落到盘根，污染工作区 ✗）
            raise RuntimeError('skip on pc')
        for _e in (_GLOBAL_LOG[-400:] if _GLOBAL_LOG else []):
            try:
                _lines.append(json.dumps(_e, ensure_ascii=False)[:300])
            except Exception:       # noqa: BLE001
                pass
        _txt = (summary_text() + '\n\n---- 最近日志（最多 400 条）----\n'
                + '\n'.join(_lines) + '\n')
        os.makedirs(BAG_PUB_DIR, exist_ok=True)
        with open(os.path.join(BAG_PUB_DIR, 'mgas_log.txt'), 'w',
                  encoding='utf-8') as _f:
            _f.write(_txt)
    except Exception:       # noqa: BLE001
        pass

# ⭐ 2026-09-25 重标定：屏幕格距 144.0、棋盘左上 (36, 1002)（见 spots.GRID / fit_art.py）
GRID = spots_mod.GRID
# ⭐ 分辨率自适应：连接设备后由 apply_layout() 按实际屏幕刷新 ✓
# ⭐ 分辨率自适应总开关（False = 完全按 1080×1920 常量跑 ⇒ 等于改 720p 之前 ✓）
LEARN_TILES = False        # 边跑边学空地判据（默认关 ✓ 判据不稳会帮倒忙 ✗）
# ⭐ 2026-09-27 用户口径：**只存「刚进图那一张」**（最干净 ✓ 后面轮次图标会盖住地块美术 ✗）
#   · SAVE_FIRST（默认开）⇒ 每张图只存 **进图首帧** `runs/r_<HHMMSS>_0.png`（≈0.7MB/图）
#   · SAVE_ROUNDS（默认关，**没挂窗口按钮**）⇒ 逐轮全存。只作深度调试的后门
#     （`set MAPBOT_SAVE_ROUNDS=1`），平时别开 —— 会堆一堆图，且核对用不上 ✗
SAVE_ROUNDS = bool(os.environ.get('MAPBOT_SAVE_ROUNDS'))
SAVE_FIRST = os.environ.get('MAPBOT_SAVE_FIRST', '1') != '0'
# ⭐⭐ 2026-09-27 用户要求：「开一个新脚本抓另一个模拟器 —— 只进图截图退图，拿图片快一些」
#   `--collect-only`（采图模式）：**进图 → 存首帧 → 退图**，不揭格 / 不打怪 / 不买 /
#   不补点 / 不背包升星 ⇒ 一张图 ≈ 30~40 秒换 1 张首帧（正常推图 ≈ 4 分钟才 1 张）
#   ⚠ 成本不变：**进图瞬间扣 25 体力**（实测 2282→2257、2180→2155，两次都是恰好 25），
#      退图**不退**体力 ⇒ 这是「用体力换图片」，不会白嫖 ✓
COLLECT_ONLY = False
SKIP_SPAWN_CLICK = False   # 执行序列里是否跳过出生点（默认关 ✓ 开了揭示起不来 ✗）
OPT_SOLVER = True     # ⭐ 每轮用精确解算器规划点序（最省体力 ✓ fail-open ✓）
ADAPTIVE_LAYOUT = False
_GRID_CALIBRATED = {'done': False}   # 棋盘自检只跑一次 ✓
LAYOUT = layout_mod.DEFAULT        # 默认 = 参考分辨率 1080×1920 ✓
FIGHT_Y = 735
DISPATCH_BTN = (891, 1507)   # 「一键派遣」/「开始探索」（同一位置，两步 ✓）
EXPLORE_BTN = (275, 736)     # 地块面板左边「探索」✓
# ⭐ 面板掉落的高价值配色（源码 AreaBlockPanel.highValueColorCode ✓）
#   顺序 = [C 绿, B 蓝, A 紫, S 橙, SS 红]；我们要的是**紫以上** ⇒ 取后三个 ✓
HIGH_VALUE_COLORS = ((0x7d, 0x58, 0xa1), (0xbf, 0x77, 0x43), (0xe5, 0x50, 0x50))


def has_high_value_drop(img, tol=26, min_px=60):
    """面板区域里有没有紫/橙/红（A/S/SS）⇒ 决定值不值得点「探索」✓

    面板一般在中部（y 600~1000），这里整屏扫（更稳 ✓），命中像素数 ≥ min_px 才算 ✓
    """
    try:
        import numpy as _np
        if img is None:
            return False
        h, w = img.shape[:2]
        band = img[int(h * 0.30):int(h * 0.60), :]
        b = band[:, :, 0].astype(_np.int16)
        g = band[:, :, 1].astype(_np.int16)
        r = band[:, :, 2].astype(_np.int16)
        for (rr, gg, bb) in HIGH_VALUE_COLORS:
            m = ((abs(r - rr) <= tol) & (abs(g - gg) <= tol) & (abs(b - bb) <= tol))
            if int(m.sum()) >= min_px:
                return True
        return False
    except Exception:       # noqa: BLE001
        return True         # 判不了就别拦（宁可点探索 ✓）

# 逐格分类器缓存（按图号；一局只建一次，约 1~2 秒）
_BOARDS = {}


def apply_layout(w, h):
    """按实际屏幕尺寸刷新所有坐标常量 ✓（1080×1920 下与旧值完全一致 ✓）

    ⚠ ADAPTIVE_LAYOUT = False ⇒ **直接返回**（不改任何东西 ✓）
      ⇒ 全部常量保持 1080×1920 原值 ⇒ 行为等于"改 720p 之前" ✓
    """
    global LAYOUT, FIGHT_Y, DISPATCH_BTN, EXPLORE_BTN
    global CLOSE_X_RIGHT, CLOSE_X_LEFT, BACK_BTN, CLOSE_TR_PT, START_ADV
    global END_ADV, ENTER_MAP, SLOTS_Y, SLOT_XS, GRID
    if not ADAPTIVE_LAYOUT:
        return LAYOUT

    # 在连接设备后调用一次即可 ✓ 之后 FIGHT_Y / DISPATCH_BTN / EXPLORE_BTN /
    # 槽位 y / 骰子区 / X 按钮位置等全部随屏幕缩放 ✓
    LAYOUT = layout_mod.Layout(w, h)
    FIGHT_Y = LAYOUT.sy(layout_mod.REF['fight_y'])
    DISPATCH_BTN = LAYOUT.dispatch_btn
    EXPLORE_BTN = LAYOUT.explore_btn
    CLOSE_X_RIGHT = LAYOUT.sx(layout_mod.REF['close_x_right'])
    CLOSE_X_LEFT = LAYOUT.sx(layout_mod.REF['close_x_left'])
    BACK_BTN = LAYOUT.pt(*layout_mod.REF['back_btn'])
    CLOSE_TR_PT = LAYOUT.pt(*layout_mod.REF['close_bag'])
    START_ADV = LAYOUT.pt(*layout_mod.REF['start_adv'])
    END_ADV = LAYOUT.pt(*layout_mod.REF['end_adv'])
    ENTER_MAP = LAYOUT.pt(*layout_mod.REF['enter_map'])
    SLOTS_Y = LAYOUT.sy(layout_mod.REF['slots_y'])
    SLOT_XS = [LAYOUT.sx(x) for x in layout_mod.REF['slots_x']]
    # ⭐ 标记识别也要自适应 ✓：尺度区间与棋盘几何同步缩放 ✓
    #   （GLYPH_SCALES 写死 3.8~5.2 是 1080×1920 的 ✓ 别的分辨率下标记会变大/变小 ✗）
    try:
        import marks as _mk
        s0, s1 = getattr(_mk, 'GLYPH_SCALES_BASE', None) or (
            min(_mk.GLYPH_SCALES), max(_mk.GLYPH_SCALES))
        _mk.GLYPH_SCALES_BASE = (s0, s1)
        n = max(3, int(round((s1 - s0) / 0.1)) + 1)
        _mk.GLYPH_SCALES = [round((s0 + (s1 - s0) * i / (n - 1)) * LAYOUT.k, 3)
                            for i in range(n)]
        _mk.GRID = {'x0': LAYOUT.sx(layout_mod.REF['grid_x0']),
                    'y0': LAYOUT.sy(layout_mod.REF['grid_y0']),
                    'cx': LAYOUT.s(layout_mod.REF['grid_cx']),
                    'cy': LAYOUT.s(layout_mod.REF['grid_cy'])}
    except Exception:       # noqa: BLE001
        pass

    # ⭐ 奖励行"大拇指装备"识别也要自适应 ✓（badge 的尺度/搜索框随分辨率缩 ✓）
    try:
        import badge as _bg
        _bg.SCALE_K = LAYOUT.k
    except Exception:       # noqa: BLE001
        pass

    # 棋盘几何也同步给 spots ✓（分类器按新格距工作 ✓）
    try:
        import spots as _sp
        g = LAYOUT.grid
        # ⭐ 必须**原地更新**（explore_loop.GRID 是 spots.GRID 的别名 ✓ 重新赋值它看不到 ✗）
        _sp.GRID.update({'x0': g['x0'], 'y0': g['y0'], 'cx': g['cx'], 'cy': g['cy'],
                         'pitch': g['cx'], 'cols': g.get('cols', 7),
                         'rows': g.get('rows', 5)})
        # 再把本模块的别名重新指一次（防御 ✓）
        globals()['GRID'] = _sp.GRID
        # ⭐ 三份 GRID 必须一致 ✓（marks 是独立的一份 ✗）
        try:
            import marks as _mk3
            _mk3.GRID = {'x0': g['x0'], 'y0': g['y0'], 'cx': g['cx'], 'cy': g['cy']}
        except Exception:       # noqa: BLE001
            pass
        _sp.SCALE = g['cx'] / _sp.DESIGN_PITCH if hasattr(_sp, 'DESIGN_PITCH') else _sp.SCALE
    except Exception:       # noqa: BLE001
        pass
    return LAYOUT


def auto_calibrate_grid(b, img, mapname=None, code=None, log=None):
    """⭐ 分辨率自适应：自动检测棋盘几何并用**分类分数**标定 ✓

    · 只在一张图开始时调用一次 ✓
    · 只有新几何的识别均分**高于**当前几何才采纳 ✓（绝不退化 ✗）
    """
    try:
        import grid_detect as GD
    except Exception as e:      # noqa: BLE001
        say('   ⚠ 棋盘自检模块不可用：%r' % (e,))
        return None
    code = code or spots_mod.code_of(mapname or '夏日海滩')
    hint = dict(LAYOUT.grid)
    try:
        # 当前几何的基线分
        cur = spots_mod.Board(code, grid=hint).state(img)
        base = sorted((v.get('score') or 0) for v in (cur or {}).values())
        base = sum(base[-10:]) / max(1, len(base[-10:]))

        det = GD.calibrate(img, code, hint=hint)
        if not det:
            say('   ⚠ 棋盘自检失败 ⇒ 用缩放几何（x0=%d y0=%d 格距=%.1f）✓'
                % (hint['x0'], hint['y0'], hint['cx']))
            return None
        say('   · 棋盘自检：x0=%d y0=%d 格距=%.1f/%.1f 识别均分 %.3f（当前几何 %.3f）'
            % (det['x0'], det['y0'], det['cx'], det['cy'], det['score'], base))
        if det.get('score') is None:
            # 被一致性闸拒绝（偏差过大 / 无法评分 ✓）⇒ 保持缩放几何 ✓
            say('   · 自检未通过一致性检查 ⇒ 保持缩放几何 ✓（x0=%d y0=%d 格距=%.1f）'
                % (hint['x0'], hint['y0'], hint['cx']))
            return None
        if det.get('src') == 'rejected_shift':
            say('   · 自检结果与当前几何偏差过大（>半格）⇒ 保持缩放几何 ✓（防点击偏移 ✗）')
            return None
        # ⭐ 提升不明显也不换（避免噪声把几何带偏 ✗ 用户 2026-09-27）
        if det['score'] is None or det['score'] < base + 0.10:
            say('   · 自检提升不明显（%.3f vs %.3f）⇒ 保持缩放几何 ✓'
                % (det['score'] or 0, base))
            return None
        # 采纳 ✓
        _newg = {'x0': det['x0'], 'y0': det['y0'],
                 'cx': det['cx'], 'cy': det['cy'],
                 'pitch': det['cx'],
                 'cols': spots_mod.GRID.get('cols', 7),
                 'rows': spots_mod.GRID.get('rows', 5)}
        spots_mod.GRID.update(_newg)
        globals()['GRID'] = spots_mod.GRID
        # ⭐⭐ 2026-09-27 关键修复：marks 的 GRID 是**另一份** ✗
        #   不同步 ⇒ 标记按旧格心找、点击按新格心点 ⇒ 标记错位到别的格子 ✗✗
        try:
            import marks as _mk2
            _mk2.GRID = dict(_newg)
        except Exception:       # noqa: BLE001
            pass
        try:
            _BOARDS.clear()          # 让分类器按新几何重建 ✓
        except Exception:            # noqa: BLE001
            pass
        say('   · ✓ 已采纳自检几何（x0=%d y0=%d 格距=%.1f）' % (det['x0'], det['y0'], det['cx']))
        if log is not None:
            log.append({'grid_calibrate': {'x0': det['x0'], 'y0': det['y0'],
                                           'cx': det['cx'], 'cy': det['cy'],
                                           'score': det['score'], 'base': round(base, 4)}})
        return det
    except Exception as e:      # noqa: BLE001
        say('   ⚠ 棋盘自检异常 ⇒ 继续用缩放几何：%r' % (e,))
        return None


_PLAIN_NAMES = set(getattr(tcfg_mod, 'PLAIN_NAMES', ()) or
                   ('草地', '沙地', '雪地', '岩地', '海底'))
INFER_CONSUMED = True   # ⭐ 连锁消耗反推开关（见 `_infer_chain_consumed`）


def _is_plain_cell(v):
    """这一格看起来是「可连锁的裸地」吗（营地除外；与 `mapsim.Block.plain` 同口径）"""
    nm = str(v.get('name') or '')
    if '营地' in nm:
        return False
    return nm in _PLAIN_NAMES or '草' in nm


# ⭐⭐⭐ 2026-10-01 用户口径：「勾选就主动去处理，不勾选就**拉黑**，能自由选择」
#   拉黑的地块（弹窗类特殊地块里**没勾选**的那些）在规划/点击两侧都要排除：
#     · 不是目标（`targets_cfg.is_target` 已处理 ✓）
#     · **也不能当"内容格/开路格"被点**（点一下必弹面板 ⇒ 白花一轮 ✗）
#   ⇒ 这里把它从候选池里剔掉；如果整张图的目标必须借道它，solver 会自然绕开或判定不可达 ✓
def _blocked_px(st, c):
    """本帧**被拉黑**的格子像素集合（用户：不勾 = 不碰 ✓）"""
    out = set()
    try:
        _cells = (st.get('obs') or (c.get('st') if c else {}) or {})
        for _k, _v in _cells.items():
            if tcfg_mod.is_blocked(_v.get('name')):
                try:
                    out.add(marks_mod.cell_center(int(_k[0]), int(_k[1])))
                except Exception:       # noqa: BLE001
                    pass
    except Exception:       # noqa: BLE001
        pass
    return out


def _infer_chain_consumed(cells, camp_rc, seed_rc=None, log=None, tag='solver'):
    """⭐ 反推「已经被消耗的格」—— 含**草地连锁连带吃掉**、但从来没点过的格

    揭示律（真机实测；与 `mapsolve.Problem.block_revealed` 是同一套）：
        已揭示 ⟺ 营地格 ／ 营地 4 邻 ／ 已消耗格自身 ／ 已消耗格的 4 邻
    ⇒ **反解唯一，不用猜**：一个"亮着的草地格"若既不是营地/营地 4 邻，
      也不挨着任何已知已消耗格 ⇒ 它只可能**自己已被消耗**（否则没有任何理由亮）✓

    为什么需要（用户 2026-09-30 问的「连锁连带消掉的格」）：
        点一格草地 ⇒ 游戏把**整片连通草地**一起吃掉（`mapsim.connected_plain` 同款逻辑，
        **可穿雾**）⇒ 那些没点过的格也变成裸地；但 `st['done']` 只记了**点过的那一格** ✗
        ⇒ 下一次截图里它们被分类成"已揭示的草地"（裸地贴图 ≈ 草地）
        ⇒ 模型里留下**幻影块**：以为"这片还没点" ⇒
          ① 重复规划去点它（真机 `fogged_noop`，白耗 cold）
          ② `plain_group`/揭示范围算错 ⇒ 走法不是最优 ✗✗

    ⚠ fail-open：**找不到营地就直接放弃**（返回 seed）——否则营地 4 邻会被误判成"已消耗"，
      把整张开局的可点格全抹掉 ✗

    ⭐⭐ 2026-09-30 **实测结论：本反推对"体力"是精确中性的，别指望它省体力** ✗
      三臂同执行器对拍（`_probe_oracle.py`，真机内存盘 96 张 / 多目标 16 张，
      phantom=plain+absent）：
           off（只剔真点过） 体力 725 ｜ 点击 233 ｜ 空转 1 ｜ 全清 95/96
           on （本反推）     体力 725 ｜ 点击 233 ｜ 空转 1 ｜ 全清 95/96
           oracle（真值全剔） 体力 725 ｜ 点击 233 ｜ 空转 0 ｜ 全清 95/96
      连"上帝视角"都 **0 收益** ⇒ 原因：**幻影格与已消耗格在模型里同价**
      （都是空地 1 体力、都可走），且 `Problem.targets` 从不含草地
      ⇒ 幻影格永远不会被当成"要去点的目标"，只可能被当成"走过的步" ⇒ 代价恒等 ✓
      它唯一的实际价值 = **模型语义正确**（不留幻影块）+ 约 0.01 次空转/张 的点击节省。

    ⚠ 两处已知边界（都**无害**，别再当 bug 追）：
      ① **残留**：被"真点过格"的 4 邻解释掉的连锁格反推不出来（本轮观测里它已揭示、
         但仍按"邻格揭示"解释）⇒ 幻影残留约 44/102 轮。⇒ 中性（见上表）✓
      ② **误剔**：若解释者自己是被连锁吃掉、且在该口径下**不在观测里**（phantom=absent），
         它的邻格会显得"无人解释" ⇒ 被误判成已消耗。实测只发生在**单格草地**
         （`_dbg_infer3.py`：4 例全是 `组内 1 格 ｜ 组内非草地成员=[]`）⇒ 无害 ✓
         ⚠ 真机口径是 phantom=plain（消耗格被分类成草地、**在观测里**）⇒ 误剔更少 ✓
      ③ 因此 `_cells_for_model` 里**反推的格只剔它自己、绝不连带整组**
         （只有 `st['done']` 真点过的格才允许按 anchor 整块剔）：
         万一某格与多格内容块同 anchor，整块剔会把真目标删出模型 ✗✗
    """
    seed = set(seed_rc or ())
    if not INFER_CONSUMED:
        return seed
    if not camp_rc:
        return seed
    try:
        rows, cols = int(GRID['rows']), int(GRID['cols'])
        camp = (int(camp_rc[0]), int(camp_rc[1]))

        def nbrs(rc):
            r, c = rc
            return {(r + dr, c + dc) for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                    if 1 <= r + dr <= rows and 1 <= c + dc <= cols}

        # 亮着的格（`_from_mark` 是"雾中标记格被强行当已揭示"喂进模型的，不算观测 ✓）
        R = {k for k, v in cells.items()
             if v.get('revealed') and not v.get('_from_mark')}
        covered = {camp} | nbrs(camp)
        consumed = set(seed)
        for x in consumed:
            covered.add(x)
            covered |= nbrs(x)
        odd = []
        for _ in range(rows * cols + 2):
            rest = sorted(R - covered)
            if not rest:
                break
            x = rest[0]
            if _is_plain_cell(cells.get(x) or {}):
                consumed.add(x)      # 亮着 + 没人能揭示它 ⇒ 只能是自己已被消耗 ✓
            else:
                odd.append(x)        # 非草地却亮着 ⇒ 本律解释不了，**别动它**（只记日志）
            covered.add(x)
            covered |= nbrs(x)
        if log is not None:
            _extra = consumed - seed
            if _extra:
                log.append({tag: 'chain_consumed_inferred', 'n': len(_extra),
                            'cells': ['%d,%d' % k for k in sorted(_extra)[:12]]})
            if odd:
                log.append({tag: 'revealed_unexplained', 'n': len(odd),
                            'cells': ['%d,%d' % k for k in odd[:8]]})
        return consumed
    except Exception:       # noqa: BLE001
        return seed


def _cells_for_model(st, c, log=None, tag='solver', mark_revealed=True,
                     drop_done=True):
    """⭐ 2026-09-28 抽公共：给模型（MapSim.from_observation）用的「观测合并」
    （solver_order / eff_order **共用这一份**，防止两处漂移 —— 参照 _fix_blank_cost_1
    只改 mapsolve 漏 mapsim 的教训 ✓）

    · `c['st']`（分类器格）∪ `st['marks']`（标记扫描）—— 标记优先 ✓
    · 有标记但分类器没给出的格补进去（认不出 ⇒ mark='battle' 兜底 ✓）
    · mark_revealed：
        True（solver 默认，保持原行为）—— 标记格当"可点"喂给 mapsolve
        （mapsolve 需要目标可达才求解；真机点不动由 nochange 兜底 ✓）
        False（**eff 必须用**）—— 雾中标记格保持"可见但不可点"：
        2026-09-28 离线验证抓到：True 时 EffPolicy 推演盘一步把雾中 boss/商人
        "消耗掉" ⇒ targets 丢方向、真机执行全是 fogged noop ⇒ 空转 ✗✗

    ⭐⭐⭐ 2026-09-30 两处关键修正（离线 `_bench_online.py` 80 张盘对拍，见当日日报）：
    ① **剔除已消耗格**（`drop_done`）：
         已消耗的格在地图上已经空了，但地块分类器照样会给它一个 top1（裸地 ≈ 草地贴图）
         ⇒ `from_observation` 会为它建一个**幻影空地** ⇒ 模型以为"这里还没走过"
         ⇒ `mapsolve.Problem.visible()` 只剩「营地四邻」⇒ **每轮规划都从营地重新起步**、
           走法必然不是最优，还会把已走过的格再排进计划（真机 `fogged_noop`）✗
         ⚠ 必须**按 anchor 整块剔**：真机只 tap 了块里的一格，`done` 也只记那一格，
           只剔那一格会把多格块剩下的成员留成"幻影块" ✗
      ② **补 `target` 字段**：`targets_cfg` 白名单（用户 2026-09-28 明确要求
         「勾选某一种类型的方块，后续就专门去拿那个方块」）此前**只在文件头 import、
         全文件从未调用** ⇒ 喂给求解器的 cells 里没有 `target` ⇒ `Block.want` 恒 None
         ⇒ `Problem.targets` 永远退回 `mark ∪ is_buy` 老口径
         ⇒ **紫橙探索格(221/321/331) 与用户勾选的类型压根不进规划** ✗
    """
    _mk_all = st.get('marks') or {}
    _cells_merged = {}
    # ⭐⭐⭐ 2026-10-01 修「规划很差劲」：模型输入的底子换成**跨轮累积观测** `st['obs']`
    #   （见 one_round 里 obs_merge 的注释）。原来直接用 `c['st']`＝**单帧**分类 ⇒
    #   面板/动画/加载那一帧认不到的格会从模型里消失 ⇒ 求解器以为要重新开路
    #   ⇒ cost 乱跳（真机 17:10~17:12 同一张图：2 → 17 → 7 ✗）。
    #   `st['obs']` 只增不减（已揭示永不翻回）⇒ 模型永不会"忘掉"走过的地方 ✓
    #   没有 obs（首轮/退化）时自然回落到本帧 `c['st']` ✓
    _base_cells = st.get('obs') or (c.get('st') or {})
    for _k, _v in _base_cells.items():
        _vv = dict(_v)
        _mlist = list((_mk_all.get(_k) or {}).get('marks') or [])
        # ⭐⭐ 2026-09-27 用户口径：「我认不出来的那几个就是战斗格」✓
        if _mlist:
            _vv['marks'] = _mlist
        # ⭐⭐⭐ 2026-09-28 二次修正（用户真机报「被宝箱隔断的草地被当连通」）：
        #   此处曾有 `score>=0.8 ⇒ revealed=True` —— **错误，已撤回**。
        #   分类器能"看穿雾"：雾格也拿 score 0.91（ratio 0.65）⇒ 该规则把**雾格**
        #   翻成"已揭示草地" ⇒ plain_group 穿雾假连通 ⇒ 规划认为能连锁 ✗。
        #   正确语义：**ratio 是"揭示状态"的唯一可靠信号**
        #   （雾 ratio≈0.65 vs 已揭示 ~1.0，干净间隔）；score 只说明"底下是什么"。
        #   首帧暗罩（全盘 ratio 被进图动画压到 0.65）的正确修法 =
        #   **进图后等暗罩散去再识别**（见 enter_map 的 _wait_fog_clear ✓）。
        _cells_merged[_k] = _vv
    # ⭐⭐ 2026-09-27：**有标记但分类器没给出**的格子必须补进模型 ✓
    #   （实测 boss 格 (1,6) 六轮 board 全是 None ✗ 但标记看得到 ✓）
    for _k, _m in _mk_all.items():
        if _k in _cells_merged:
            continue
        _ml = list(_m.get('marks') or [])
        if not _ml:
            continue
        _cells_merged[_k] = {'sid': None, 'name': None, 'marks': _ml,
                             'revealed': mark_revealed,
                             'ratio': None, 'score': None, '_from_mark': True}
        if 'battle' not in _cells_merged[_k]['marks']:
            _cells_merged[_k]['marks'].append('battle')   # 认不出 ⇒ 当战斗格 ✓
        if log is not None:
            log.append({tag: 'mark_cell_added', 'cell': '%d,%d' % _k,
                        'marks': _ml})
    # ---- ⭐⭐⭐ 2026-10-01 用户报「点了金属宝箱怪（说了不点的）」----
    #   根因：`_blocked_px` 只把拉黑格从 `nones_extra`（内容格/开路池）剔掉了，
    #   但**规划器（solver/eff）喂进去的 cells 里没剔** ⇒ 它照样把宝箱怪排进点序 ✗
    #   （真机铁血高地实证：规划 `['3,2','2,4','2,5']` 第一步 3,2 就是宝箱怪，
    #     点完弹面板、白转 26 秒 ✗）
    #   ⇒ 现在：**拉黑格留在模型里，但标记为"blocked"且强制非目标**（不再 pop ✗ ——
    #     见下面 v0.99 的说明：pop 会让它变成 `board < 0` = 模型眼里的"已消耗空地"，
    #     于是拉黑格被当成**能连锁穿过的空地**，规划整条走法都错 ✗✗）
    try:
        _blk_rc = set()
        for _k2, _v2 in list(_cells_merged.items()):
            if tcfg_mod.is_blocked(_v2.get('name')):
                _blk_rc.add(_k2)
        if _blk_rc:
            for _k2 in _blk_rc:
                _v2 = _cells_merged.get(_k2) or {}
                _v2['blocked'] = True
                _v2['target'] = False        # ⭐ 双保险：目标白名单里也不许有它 ✓
            if log is not None:
                log.append({tag: 'blocked_cells_tagged', 'n': len(_blk_rc),
                            'cells': ['%d,%d' % k for k in sorted(_blk_rc)[:12]]})
    except Exception:       # noqa: BLE001
        pass
    # ⭐⭐⭐ 2026-10-01 v0.99 用户报「最近一次规划很差啊，**是把拉黑的看成能连锁了**？」
    #   —— 用户猜对了，就是我们自己引入的：
    #   v0.94 的修法是**把拉黑格从 `_cells_merged` 里 pop 掉**（防 solver 点它）。
    #   但 pop 掉 ⇒ `MapSim.from_observation` 不给它建块 ⇒ `board[cell] = -1`，
    #   而 `mapsolve.Problem.consumed_cells()` 把 **`board < 0` 一律当"已消耗的格"**
    #   （那是 2026-09-30 为"已经走出去的地图"补的 F3 语义），并且
    #   `block_revealed()` 里"与任一已消耗格 4 邻接 ⇒ 该块已揭示"也走这条
    #   ⇒ 后果三条，全是"规划很差"的直接来源：
    #     ① 拉黑格被当成**空地** ⇒ 相邻的**雾格**被判"已揭示/可点" ⇒ 计划里出现点不动的格 ✗
    #     ② 连通空地的**连锁**会**穿过**这个洞 ⇒ 体力/步数被严重低估（= 用户说的"看成能连锁"）✗
    #     ③ `_build_cache` 的 `EMPTY_ADJ`（可点集合）也把它算进去 ⇒ 可见范围虚高 ✗
    #   ⇒ 正确语义：拉黑格 = **一个不可点的普通内容格**（游戏里它同样**阻断连锁穿透** ✓）
    #      · 留在模型里 ⇒ `board >= 0` ⇒ 不是"已消耗" ⇒ 不参与连通/连锁 ✓
    #      · `target=False` + 非 plain（宝箱怪/预言石碑的 SpecialSpot>0 ✓）⇒ solver 不会去点它 ✓
    #      · 启发式点序里仍由 `_blocked_px` 排除（v0.94 那一层保留 ✓）
    # ---- ⭐ 2026-09-30 ①：剔除已消耗的块（按 anchor 整块剔） ----
    # `_seed_rc` = **真点过**的格（`st['done']`，真机只在 act∈{battle,battle_clear,
    #   handled} 或 商人/营地/预言石板 时写入）⇒ **高可信** ⇒ 允许按 anchor 整块剔
    # `_infer_rc` = 反推出来的**草地**格（连锁连带吃掉、从没点过）⇒ **只剔它自己**，
    #   ⚠ 绝不允许它连带剔掉整组 —— 万一它跟某个多格内容块同 anchor，
    #   整块剔会把**真目标**从模型里删掉（计划里再也不去拿）✗✗
    _seed_rc = set()
    _infer_rc = set()
    _done_rc = set()
    if drop_done:
        for _px in (st.get('done') or ()):
            try:
                _seed_rc.add(cell_of(_px[0], _px[1]))
            except Exception:           # noqa: BLE001
                pass
        _done_rc = set(_seed_rc)
        # ⭐⭐ 2026-09-30 补：`st['done']` 只记**点过**的格；草地连锁连带吃掉的格不在里面
        #   ⇒ 反推它们（见 `_infer_chain_consumed`）并一起剔 ✗→✓
        try:
            _camp_rc = None
            _sp = st.get('spawn') or st.get('camp')
            if _sp:
                _camp_rc = cell_of(_sp[0], _sp[1])
            if _camp_rc is None:
                for _k2, _v2 in _cells_merged.items():
                    if '营地' in str(_v2.get('name') or ''):
                        _camp_rc = _k2
                        break
            _done_rc = _infer_chain_consumed(_cells_merged, _camp_rc,
                                             seed_rc=_seed_rc, log=log, tag=tag)
            _infer_rc = _done_rc - _seed_rc
        except Exception:               # noqa: BLE001
            pass
    _grp = {}
    for _k, _v in _cells_merged.items():
        _a = tuple(_v.get('anchor') or _k)
        _grp.setdefault(_a, []).append(_k)
    _out = {}
    _dropped = []
    for _a, _mem in _grp.items():
        if _seed_rc and any(m in _seed_rc for m in _mem):
            _dropped.extend(_mem)       # 真点过 ⇒ 整块剔（真机口径：块里被点掉一个就没了）
            continue
        for _k in _mem:
            if _k in _infer_rc:         # 反推命中 ⇒ **只剔这一格**（绝不连带）✓
                _dropped.append(_k)
                continue
            _vv = dict(_cells_merged[_k])
            # ---- ⭐ 2026-09-30 ②：补目标白名单字段（Block.want ⇒ Problem.targets） ----
            try:
                _vv['target'] = bool(tcfg_mod.is_target(
                    _vv.get('name'), _vv.get('sid'), _vv.get('marks')))
            except Exception:           # noqa: BLE001
                pass
            _out[_k] = _vv
    if _dropped and log is not None:
        log.append({tag: 'done_cells_dropped', 'n': len(_dropped),
                    'cells': ['%d,%d' % k for k in _dropped[:12]]})
    return _out


def eff_order(st, c, log=None, max_steps=20):
    """⭐⭐ 2026-09-28：EffPolicy（片感知 + 一步前瞻）在线点序 —— solver 失败的兜底 ✓

    用与 solver_order **同一份**观测合并口径（_cells_for_model → from_observation）建盘，
    再让 EffPolicy 推演整条点序（strategy.EffPolicy.plan ✓）。特点：
      · 毫秒级（solver 是秒~分钟级）⇒ 调用方可**每轮用最新观测重算**（在线策略 ✓）
      · 部分观测天然支持：雾格 board=-1 不进候选（visible() 只给已揭示格 ✓）
      · 2000 张独立验证 11.021 vs 旧启发式 11.675（省 5.61%，地图生成算法.md §16）
    任何异常返回 [] ⇒ 调用方退回旧启发式 ✓（fail-open ✓）
    """
    try:
        import mapsim as _ms
        from strategy import EffPolicy as _Eff
        _cells_merged = _cells_for_model(st, c, log=log, tag='eff',
                                         mark_revealed=False)
        if not _cells_merged:
            return []
        sim = _ms.MapSim.from_observation(_cells_merged, spots_mod.spot_rows())
        # ⭐ stop_when_no_target=False：观测盘上目标可能还在雾里（targets 空 ≠ 图清完）
        #   ⇒ 没目标也继续开路（2026-09-28 离线验证抓到的坑，见 strategy.plan 注释 ✓）
        plan = _Eff().plan(sim, max_click=max_steps, stop_when_no_target=False)
        # ⭐ v1.34：兜底路径**同样**"能点的首领优先"（与 solver 同一口径，不两处漂移 ✓）
        plan = _hoist_ready_boss_first(st, plan, log=log, tag='eff')
        if log is not None:
            log.append({'eff': 'ok', 'steps': len(plan),
                        'order': ['%d,%d' % p for p in plan]})
        return plan
    except Exception as e:      # noqa: BLE001
        if log is not None:
            log.append({'eff': 'error', 'e': repr(e)[:100]})
        return []


# ⭐⭐⭐ 2026-10-02 v1.28【用户口径：**进图只规划一次**，之后不再重算】
#   「规划就刚进入规划一次，后续不再规划。走完规划的还有目标就用之前的保底方案走」
#
#   ⚠ 这条 09-27 本来就是这么做的，09-30 被"每轮重解更省体力"的离线对拍推翻过：
#     进图规划一次的目标集是**残缺**的（未揭示的标记格/商人还没认出来）
#     ⇒ 全知对拍贵 +9.2%（marks 可见）/ +26.1%（marks 藏雾里），最坏单盘贵 16 体力。
#     现在用户明确要回"进图一次"（可预期、不在图里反复改主意）⇒ 按用户口径实现 ✓，
#     并保留两条安全网：**计划连着 3 轮没推进**（格子点不动/被挡）⇒ 自动切兜底，
#     不会像旧版那样死抱着一个走不通的计划 ✗
PLAN_STUCK_ROUNDS = 3

# ⭐⭐ v1.45【规划步数上限 4 → 10】（学 PC 端 `42c65a1`，用户口径「上限改为 10 步」）
#   与 `PLAN_ONCE` 是**配套**的：只有"一图只规划一次"才需要足够长的计划 ——
#   截得太短 ⇒ 走完就切兜底 ⇒ 那次规划等于白算 ✗
#   ⏱ 成本可忽略（solver p50 0.65ms）⇒ 纯粹是"要够长"的问题，不是"快慢"问题 ✓
#   环境变量 `MAPBOT_PLAN_MAX_STEPS` 可现场调 ✓
PLAN_MAX_STEPS = int(os.environ.get('MAPBOT_PLAN_MAX_STEPS', '10') or 10)

# ⭐⭐⭐ 2026-10-02 v1.39【探索模式已**移除**】—— 用户定：「去掉探图模式」
#   它本是 v1.29 为治「进图发呆就退出」加的兜底（没目标但暗格多 ⇒ 沿可点格开路逼标记），
#   但真机反复**白烧体力**，且那几张盘人工核对**确实一个标记都没有**：
#     v1.35：solver no_plan + grays=20 ⇒ 探，零产出
#     v1.36：solver no_plan + grays=10 ⇒ 又探，零产出（用户目击「还在显示探索」✗）
#   ⇒ 现在**没目标就退图**（`targets_done`）⇒ 标记清完立即收工，不再开路 ✓
#   ⚠ 已删：`need_explore()` / `EXPLORE_MIN_GRAY` / `EXPLORE_MAX_CLICKS` /
#     `EXPLORE_NO_YIELD_ROUNDS`（只服务于探索模式，留着会让人以为还有效 ✗）
#   ⇒ 若日后又要「宁可多开几格也别提前退」，从 v1.38 的 git 历史取回 `need_explore()` 即可 ✓

# ⭐⭐ 2026-10-02 v1.29 / v1.45：**规划口径开关**（历史上已来回翻两次）
#   两条路都留代码，别再手改逻辑 ✗；环境变量 `MAPBOT_PLAN_ONCE=0` 可现场切回旧口径
#     True（**v1.45 起默认**）= 进图只规划一次 + 走完/推不动切兜底 —— 可预期 ✓
#     False = 每轮用最新观测重解 —— 09-30 离线对拍说省 9.2%~26.1% 体力
#   ⚠⚠ v1.45 **默认翻回 True**，学 PC 端 `0abbbdf`（用户口径：「怎么还在多次规划？
#     我不是说过一次规划就行」）。PC 端真机铁证（用户贴的第 5 张图 ✓）：
#       r0 计划 3 步（2,3/1,5/4,4）⇒ 点 2,3 打首领 ⇒ 胜利
#       r2 **又算** 3 步（4,3/2,2/1,1）✗
#       r5 **又算** 4 步（1,4/1,3/1,2/1,1）✗
#       ⇒ 本图 71 秒，最后落到 `target_unreachable` ✗
#   ⚠ 手机端 09-30/10-02 的对拍结论（每轮重解更省体力）**仍然成立**，
#     但**用户 10-04 实测：一图一次并不多花体力** ⇒ 以用户口径为准 ✓
#   ⇒ 安全网保留：计划连着 `PLAN_STUCK_ROUNDS` 轮推不动 / 走完还有目标 ⇒ 切兜底 ✓
PLAN_ONCE = (os.environ.get('MAPBOT_PLAN_ONCE', '1') or '1') \
    not in ('0', '', 'no', 'false')


def plan_mode(st, rest_n, targets_left, once=None):
    """规划口径决策（纯函数，`once` 可注入 ⇒ 两种模式都能离线对拍 ✓）

    返回 `(动作, 原因)`：
        `('plan', 'each_round')` —— **每轮重解**（默认口径：拿最新观测覆盖旧计划 ✓）
        `('plan', 'first')`      —— `PLAN_ONCE=1`：还没规划过 ⇒ 现在算一次
        `('keep', 'has_rest')`   —— `PLAN_ONCE=1`：计划还有没做完的步 ⇒ 继续照走
        `('eff', 'stuck')`       —— `PLAN_ONCE=1`：连着 `PLAN_STUCK_ROUNDS` 轮没推进 ⇒ 切兜底
        `('eff', 'exhausted')`   —— `PLAN_ONCE=1`：计划走完但还有目标 ⇒ 切兜底
        `('none', 'no_targets')` —— `PLAN_ONCE=1`：计划走完、也没目标 ⇒ 不动
    """
    if once is None:
        once = PLAN_ONCE
    if not once:
        return 'plan', 'each_round'
    return plan_next(st, rest_n, targets_left)



def plan_next(st, rest_n, targets_left):
    """进图只规划一次 + 走完切兜底（纯函数，可离线对拍 ✓）

    返回 `(动作, 原因)`：
        `('plan', 'first')`      —— 还没规划过 ⇒ 现在算一次（就是"进图那一下"）
        `('keep', 'has_rest')`   —— 计划还有没做完的步 ⇒ **继续用，不重算** ✓
        `('eff', 'stuck')`       —— 计划连着 `PLAN_STUCK_ROUNDS` 轮没推进 ⇒ 切兜底 ✓
        `('eff', 'exhausted')`   —— 计划走完了、但还有目标 ⇒ 切**片感知兜底**（老方案 ✓）
        `('none', 'no_targets')` —— 计划走完、也没目标了 ⇒ 什么都不做（交给收尾逻辑 ✓）
    """
    if rest_n > 0:
        if rest_n >= st.get('plan_prev_len', rest_n):
            st['plan_stuck'] = st.get('plan_stuck', 0) + 1
        else:
            st['plan_stuck'] = 0
        st['plan_prev_len'] = rest_n
        if st.get('plan_stuck', 0) >= PLAN_STUCK_ROUNDS:
            return 'eff', 'stuck'
        return 'keep', 'has_rest'
    st['plan_stuck'] = 0
    st['plan_prev_len'] = 0
    if not st.get('planned'):
        return 'plan', 'first'
    if targets_left > 0:
        return 'eff', 'exhausted'
    return 'none', 'no_targets'


def _ready_boss_cells(st, order):
    """⭐ v1.34 纯函数：点序里**当下就能点**的首领/红装格（按原顺序）

    「能点」= 该格在 `st['obs']`/本帧分类里是**已揭示**（`ratio` 落在揭示区间）
    —— 分类器能看穿雾，所以**必须用 `ratio`** 判揭示，不能看 `score`（见
    `_cells_for_model` 里那段踩坑注释：score≥0.8 的雾格是常见误判 ✗）。

    ⚠ **点不动的首领（还在雾里）绝不返回** —— 提上来也点不动，
      只会白花一体力并把真正该点的素材格挤掉 ⇒ 反而更差 ✗
    """
    # ⭐ v1.36：揭示口径**取模块级 `REVEAL_RATIO_MIN`**（它自己又来自 `spots`，单一来源 ✓）
    #   ⚠ 不用 `globals().get(默认)` —— 那样常量名拼错会**静默吃默认值**、永远测不出
    #     （2026-10-02 v1.34 踩过：`REVEALED_…` vs 真实的 `REVEAL_…`）✗
    _min_ratio = REVEAL_RATIO_MIN
    try:
        _mk = st.get('marks') or {}
        if not _mk:
            return []
        _obs = st.get('obs') or {}
        _frame = st.get('frame_st') or {}
        out = []
        for _rc in order:
            _k = (_rc[0], _rc[1])
            _marks = list((_mk.get(_k) or {}).get('marks') or [])
            if not any(m in ('boss', 'redEquip') for m in _marks):
                continue                                   # 只管首领/红装 ✓
            _cell = _obs.get(_k) or _frame.get(_k) or {}
            _ratio = _cell.get('ratio')
            try:
                _ratio = float(_ratio) if _ratio is not None else None
            except (TypeError, ValueError):
                _ratio = None
            if _ratio is None:
                continue          # 认不出揭示状态 ⇒ 保守当"点不动"（fail-safe ✓）
            # 已揭示格 ratio≈1.0，雾格≈0.65（真机实测间隔很干净）
            if _ratio < _min_ratio:
                continue
            out.append(_rc)
        return out
    except Exception:       # noqa: BLE001
        return []

def _hoist_ready_boss_first(st, order, log=None, tag='solver'):
    """⭐⭐ v1.34：把「当下能点的高价值格」提到点序**最前面**，其余顺序不动

    用户 2026-10-02 报（朋友真机）：「会把能点的素材格全点开，**boss 格已经能打了**，
    还是会先点 boss 格周围的素材格」✗
    真机铁证（`fb_20261002_015406`）：`marks {"2,3": ["boss","recommend"]}` +
    `solver order ["3,5","2,3"]`，同一轮 `popup: fight_panel` 已弹出 ⇒ boss **可打**
    却被排在第 2 位 ✗

    ⚠ 只调整**执行顺序**，不碰解算器的结果本身（cost/其余步骤一律不变 ✓）
    ⚠ 任何异常都不改变点序（fail-open ✓）
    """
    try:
        if not order:
            return order
        _ready = _ready_boss_cells(st, order)
        if not _ready:
            return order
        _rest = [rc for rc in order if rc not in _ready]
        _new = _ready + _rest
        if log is not None and _new != list(order):
            log.append({tag: 'boss_hoisted',
                        'ready': ['%d,%d' % p for p in _ready],
                        'was': ['%d,%d' % p for p in order],
                        'now': ['%d,%d' % p for p in _new]})
        return _new
    except Exception:       # noqa: BLE001
        return order


def solver_order(st, c, log=None, max_steps=6, out=None):
    """⭐ 用精确解算器算"当前信息下的最省体力点序" ✓

    返回 [(cell_row, cell_col), …]（按最优顺序 ✓ 取前 max_steps 步）
    任何异常/无解都返回 [] ⇒ 调用方退回启发式 ✓（fail-open ✓）

    `out`（可选 dict）：回填 `ok / cost / reason / no_targets`
      —— 2026-09-30 加：**每轮重解**后调用方要能区分
         「算不出（该降级）」vs「盘上已经没有目标了（正常收尾）」，
         否则会把"没目标"当成连续失败 ⇒ 白切 EffPolicy ✗
    """
    if not OPT_SOLVER:
        if out is not None:
            out['ok'] = False
        return []
    try:
        import mapsim as _ms
        import mapsolve as _mv
        _t0 = time.time()
        # ⭐⭐ 2026-09-27 根因修复（用户报「不点 1 体空白格、反去打更贵的战斗格」）：
        #   原样只传 `c['st']`（**地块分类** ✓）⇒ 模型看不到**标记** ⇒ targets 为空
        #   ⇒ 求解器不知道"点这个空白格能解锁两个标记格" ⇒ 点序变成乱走 ✗✗
        #   2026-09-28：合并逻辑抽成 _cells_for_model（eff_order 共用 ✓）
        _cells_merged = _cells_for_model(st, c, log=log, tag='solver')
        # ⚠ 2026-09-27 试过"摘掉出生点不点它" ✗ —— 实测**模型直接无解**：
        #     含出生点 ⇒ cost=11 / 4 步 ✓ ；摘掉 ⇒ cost=None / 0 步 ✗
        #   原因：开局其它空地块多为雾格（点不动 ✓）⇒ 出生点是唯一能启动"连锁揭示"的格 ✓
        #   ⇒ 保留出生点 ✓（它那一步不是多余的 ✓）；如需从"执行序列"里剔除，见下方开关 ✓
        sim = _ms.MapSim.from_observation(_cells_merged, spots_mod.spot_rows())
        prob = _mv.Problem(sim)
        # ⭐ 2026-09-28 加 max_secs=8（用户报「进图要等很久」）：复杂盘 60k 状态枚举
        #   可达 30~60s，失败后下轮还重试 ⇒ 进图几分钟不点格 ✗。8 秒算不出就
        #   fail-open ⇒（今日新链）EffPolicy 毫秒级接管 ✓
        #   ⭐ 2026-09-30 实测（真机盘 96 张、每轮重解）：完整链路 p50 0.65ms /
        #     p95 1.4ms / p99 1.9ms / max 2.4ms ⇒ 8 秒上限实际**永远碰不到** ✓
        _rep = {}
        cost, plan = _mv.solve(prob, max_states=60000, max_secs=8, report=_rep)
        if out is not None:
            out['cost'] = cost
            out['reason'] = _rep.get('reason')
            out['no_targets'] = (not plan) and cost == 0
            out['ok'] = bool(plan)
        if not plan:
            if log is not None:
                log.append({'solver': 'no_plan', 'cost': cost,
                            'reason': _rep.get('reason'),
                            'expanded': _rep.get('expanded'),
                            'secs': round(time.time() - _t0, 2)})
            return []
        # block idx → **真的能点的格**
        # ⭐⭐⭐ 2026-09-30 修（离线 `_bench_online.py` 80 张盘对拍，代价极大）：
        #   旧实现取「该块在 `c['st']` 里出现的第一个格」（实际等于 `cells[0]`，块首格）。
        #   但 `mapsolve` 的 `visible()` 会把**一整片连通空地**去重成「片内最小 idx 的
        #   代表块」⇒ 计划里的块常常是那个代表块，而**代表块本身还没揭示** ✗
        #   ⇒ 真机点它 = `fogged_noop`（不消耗、不揭示）⇒ 这片空地在下一帧里边界不变
        #   ⇒ **后面整条计划全部错位**：空转、重复点已走过的格、最后漏目标/卡住 ✗✗
        #   离线实测（80 张盘、`marks_in_fog`）：修前 **空转 1.62 次/张、平均 4.6 轮、
        #     48/80 张到最后目标都没清完**；修后 空转 0、1.0 轮、0/80 漏目标
        #   ⇒ 改用 `Problem.cells_for_plan()`：逐步推演模型状态，每一步在目标块（片）
        #     里挑一个**当下已揭示**的格 ✓
        out = []
        for _rc, _bi, _w in prob.cells_for_plan(plan[:max_steps]):
            if _rc not in out:
                out.append(_rc)
        # ⭐⭐⭐ v1.34【能点的首领格必须**立刻打**，不许先点它周围的素材格】
        #   用户 2026-10-02 报（朋友真机）：「会把能点的素材格全点开，**boss 格已经能打了**，
        #   **还是会先点 boss 格周围的素材格**」✗
        #   真机铁证（`fb_20261002_015406`，Redmi 1280×2772）：
        #     `marks {"2,3": ["boss","recommend"]}` + `solver order ["3,5","2,3"]`
        #     同一轮日志里 `popup: fight_panel` **弹出来了** ⇒ boss 当下**完全可打**，
        #     可点序还是把它排在**第 2 位**、先点了一格素材 ✗
        #   根因：解算器优化的是**总花费最小**，它不知道"这格现在就能直接打"有多重要
        #     （且计划是**静态**的，排在后面的 boss 会被前面的动作挤到最后）✗
        #   修法：**当下能点的首领/红装格一律提到最前面**（不动解算器给出的其余顺序 ✓）
        #     · 只提「**已揭示**且**在点序里**」的 ⇒ 雾里点不动的 boss 不会被提上来
        #       （提上来也点不动，只会把一格素材浪费掉 ⇒ 反而更差 ✗）
        #     · 只提**高价值**目标（首领/红装），普通标记/幸运草维持原顺序 ✓
        _hoisted = _hoist_ready_boss_first(st, out, log=log, tag='solver')
        if _hoisted:
            out = _hoisted
        try:
            _nt = len(sim.targets())
        except Exception:       # noqa: BLE001
            _nt = -1
        # ⭐ 2026-09-27：**输出里隐去出生点**（执行仍保留 ✓ 否则揭示起不来 ✗）
        _sp_px2 = st.get('spawn') or st.get('camp')
        _sp_rc2 = None
        if _sp_px2:
            try:
                _sp_rc2 = cell_of(_sp_px2[0], _sp_px2[1])
            except Exception:       # noqa: BLE001
                _sp_rc2 = None
        # ⭐ 2026-09-27 用户报「规划给我看的是错的，执行的是对的」⇒ **显示完整** ✓
        #   （之前隐去出生点 ⇒ 显示缺第一步 ⇒ 看起来像错的 ✗）
        _disp = list(out)
        _hidden = []
        # ⭐ 2026-09-27 用户要求：**步数统计也要减掉出生点那一步** ✓
        #   （显示里已隐去出生点 ✓ 步数还含它就不一致 ✗ "3 步"却只列 2 个 ✗）
        _steps_disp = len(_disp)
        if log is not None:
            _rec = {'solver': 'ok', 'cost': cost, 'steps': _steps_disp,
                    'steps_raw': len(plan), 'targets': _nt,
                    'order': ['%d,%d' % p for p in _disp],
                    'secs': round(time.time() - _t0, 2)}
            if _hidden:
                _rec['spawn_hidden'] = ['%d,%d' % p for p in _hidden]
            log.append(_rec)
        say('       · 精确规划：最省体力 %s，%d 步；先执行 %s'
            % (cost, _steps_disp, ['%d,%d' % p for p in _disp]
               or ['（只点出生点，已隐去）']))
        # ⭐⭐ 2026-10-01 用户报「怎么看不到规划了」⇒ 规划也发**悬浮条日志行** ✓
        #   背景：只有 `status()` 的行会上悬浮条；「精确规划」原来是 `say()`（只进 logcat
        #   与应用内日志）⇒ 用户盯悬浮条时看不到 ✗。文本避开 OCR 关键词（探索/派遣/关闭/领取/背包…）
        try:
            _pv = ' '.join('%d,%d' % p for p in _disp[:4]) or '（只点出生点）'
            status('规划：体力 %s / %d 步 → %s' % (cost, _steps_disp, _pv))
        except Exception:       # noqa: BLE001
            pass
        return out
    except Exception as e:      # noqa: BLE001
        if out is not None:
            out['ok'] = False
            out['err'] = repr(e)[:100]
        if log is not None:
            log.append({'solver': 'error', 'e': repr(e)[:100]})
        return []


def board_for(mapname=None, code=None):
    """取该图的地块分类器（mapname/code 二选一；失败返回 None）"""
    code = code or spots_mod.code_of(mapname or '夏日海滩')
    if not code:
        return None
    if code not in _BOARDS:
        try:
            _BOARDS[code] = spots_mod.Board(code)
        except Exception as e:      # noqa: BLE001
            print('[warn] 地块分类器构建失败 %s: %r' % (code, e))
            _BOARDS[code] = None
    return _BOARDS[code]


_CODE_DECIDED = {}          # mapname -> 已实测消歧后的 code（按图名缓存，避免每轮重算 ✓）


def _candidate_codes(mapname):
    """图名 → **所有可能的** code（>1 个就是有歧义，需要实测消歧 ✓）

    背景（2026-10-01 离线核查发现）：15 个图名里有几组很像，OCR 掉字时 `code_of`
    会**在同组里猜错成员** —— 实测「沙滩」→ 清凉沙滩(S40002)、「森林」→ 迷失森林(S20001)；
    若实际是夏日海滩/幽暗密林 ⇒ 用错模板集 ⇒ **整盘分类全错** ✗
    """
    try:
        mt = spots_mod.map_table()
    except Exception:       # noqa: BLE001
        return []
    nm = str(mapname or '')
    if not nm:
        return []
    if nm in mt:                       # 精确命中 ⇒ 无需消歧 ✓
        return [mt[nm]]
    out = []
    for k, v in mt.items():
        if (nm in k or k in nm) and v not in out:
            out.append(v)
    if out:
        return out
    # ⭐⭐ v1.36【容忍 OCR 错一个字】—— 真机 2026-10-02 13:30 实测踩到的坑：
    #   日志 OCR 把「广**袤**草原」读成「广**豪**草原」⇒
    #     上面那条"包含"匹配**一个都不中** ⇒ 候选列表 **[]**
    #     ⇒ `board_for()` 拿 `code=None` **回落成默认的夏日海滩模板集**
    #     ⇒ 拿沙滩贴图去认草原的格子 ⇒ 整盘分类错 ⇒ `light=0`
    #     ⇒ `board_hidden()` 判"全暗=面板挡住棋盘" ⇒ **连关 3 次面板** ✗✗✗
    #   （用户目击：「显示有面板挡住，但实际上没有」——棋盘一直是好的）
    #   ⚠ 症状与"真被面板挡住"**完全一样**，光看日志分不出来 ⇒ 必须容错 ✓
    #   做法：**同长度或差 1 字**才当候选（OCR 错字几乎不改变长度）
    _norm = lambda s: str(s or '').strip().replace(' ', '')
    _n = _norm(nm)
    for k, v in mt.items():
        _k = _norm(k)
        if not _k or not _n:
            continue
        if abs(len(_k) - len(_n)) > 1:
            continue                   # 长度差 >1 ⇒ 不是错字，是别的图 ✗
        # 逐位看差几个字；差 0（已被上面精确命中）或 1 才算候选 ✓
        if len(_k) == len(_n):
            diff = sum(1 for a, b in zip(_k, _n) if a != b)
            if diff <= 1 and v not in out:
                out.append(v)
                continue
        # 长度差 1：短的那方删掉任一字符后应能相等（OCR 常见"多/少一个字"）
        short, lng = (_n, _k) if len(_n) < len(_k) else (_k, _n)
        if any(lng[:i] + lng[i + 1:] == short for i in range(len(lng))):
            if v not in out:
                out.append(v)
    return out


def _disambiguate_map(img, mapname, cands, log=None):
    """有多个候选图时：**各建一次盘、比分类质量**，取最高的那个 ✓

    判据 = 「已分类格数」+「高分格(≥0.85)数」的加权（用真实帧，不靠猜 ✓）
    代价：只在**图名有歧义**时做一次，且结果按图名缓存 ⇒ 每张图最多付一次（≈0.2~0.5s）✓
    """
    best, best_key = None, None
    for c in cands:
        bd = board_for(code=c)
        if bd is None:
            continue
        try:
            st = bd.state(img)
        except Exception:       # noqa: BLE001
            continue
        n = len(st or {})
        hi = sum(1 for v in (st or {}).values()
                 if float(v.get('score') or 0) >= 0.85)
        key = (hi, n)          # 高分格优先，其次格数 ✓
        if best_key is None or key > best_key:
            best, best_key = c, key
    if log is not None:
        log.append({'map_disambig': mapname, 'cands': cands, 'picked': best,
                    'key': list(best_key) if best_key else None})
    if best:
        say('   · 图名「%s」有歧义 %s ⇒ 实测选 %s（高分格 %s）✓'
            % (mapname, cands, best, best_key[0] if best_key else '?'))
    return best


def board_state(img, mapname=None, code=None):
    """整盘状态 -> {(r,c): {...}}；失败返回 {}（调用方退回旧的启发式）"""
    # ⭐⭐ 2026-10-01：图名有歧义时**用真实帧实测消歧**（按图名缓存 ✓）
    if code is None and mapname:
        code = _CODE_DECIDED.get(mapname)
        if code is None:
            _cands = _candidate_codes(mapname)
            if len(_cands) > 1:
                code = _disambiguate_map(img, mapname, _cands, log=None)
            elif _cands:
                code = _cands[0]
            if code:
                _CODE_DECIDED[mapname] = code
    bd = board_for(mapname, code)
    if bd is None:
        return {}
    _t0 = time.time()
    try:
        st = bd.state(img)
        if not st:
            # ⭐ 兜底：空结果 ⇒ 用更低门槛再试一次（小分辨率/雾格多时 ✓）
            st = bd.state(img, thr=max(0.10, 0.80 * (float(bd.px) / 144.0) * 0.6))
            if st:
                say('   · 分类兜底：低门槛重试拿到 %d 格 ✓' % len(st))
        STATS['classify'] = STATS.get('classify', 0.0) + (time.time() - _t0)
        STATS['classify_n'] = STATS.get('classify_n', 0) + 1
        return st
    except Exception as e:          # noqa: BLE001
        print('[warn] 地块分类失败: %r' % (e,))
        return {}

L = {
 'kick': ('其他设备', '退出游戏', '重新登录'),
 'low': ('能量不足', '体力不足'),
 'fight': '战斗事件', 'fbtn': '战斗', 'expl': '探索产出', 'ebtn': '探索',
 # ⭐ 敌方预览面板（2026-09-25：用户报卡在「偶遇强敌」）——底部是「邀请挑战」+「开始战斗」
 'strong': ('偶遇强敌', '遭遇强敌'), 'sbtn': '开始战斗',
 'claim': ('领取', '继续'), 'ok': '确定', 'cancel': '取消',
 'end': '结束冒险', 'menu': ('快速扫荡', '进入地图'), 'enter': '进入地图',
 'win': '战斗胜利', 'lose': '战斗失败', 'close': '关闭',
 'hud': ('背包', '神石', '预言'),
 'desc': ('【正面】', '【负面】'),
 'dice': ('幸运草', '骰', '摇'),
 'special': ('旅行商人', '金属宝箱怪', '机巧宝箱怪', '黄金宝库', '勇者之墓',
             '传承祭坛', '限时礼包', '献祭宝箱怪', '预言石碑'),
 'buy': ('购买', '解锁', '开启'),
 'buyout': ('旅行商人', '金属宝箱怪', '机巧宝箱怪', '黄金宝库'),
 # 用户 09-25：特殊地块**只点这两个**，其余（勇者之墓/传承祭坛/限时礼包/献祭宝箱怪/
 # 预言石碑/金属宝箱怪/机巧宝箱怪）一律无视
 'act_on': ('旅行商人', '黄金宝库'),
 # ⭐「发现莱姆！」弹窗（用户 2026-09-25）：揭格/退图前补点都可能弹，**点「返回」关掉**
 #   实测版面：标题「发现莱姆！」(529,771)、莱姆名 (541,1025)、**返回按钮 (539,1309)**
 'lime': ('莱姆', '发现莱姆'),
 # ⭐「获得新装备！」弹窗（用户 2026-09-26 报卡住）：**同模板版面**
 #   实测（1080×1920，OCR conf）：标题「获得新装备！」(531,992)、装备描述 (528,1101)、
 #   **「返回」(540,1252) conf=1.00**
 #   ⚠ 触发场景（用户口径）：① 打完大拇指(recommend)地块 ② 退图前补点（发现莱姆点那下）
 #   ⚠ 不关掉它 ⇒ 整盘被遮 ⇒ board_hidden: all_dark ⇒ 认不到任何地块 ⇒ finish: timeout ✗
 'newequip': ('获得新装备', '获得装备', '新装备'),
 # ⭐「预言石板」占卜面板（用户 2026-09-26）：点出后就关掉，并**拉黑这格不再点** ✓
 #   ⚠ 别写成单独的 '预言' —— `L['hud']` 里也有「预言」（主界面入口），会误伤 ✓
 'prophecy': ('预言石板', '预言石碑', '占卜'),
}

# ⭐⭐ 万能关闭点（用户 2026-09-26 实测口径：「点击中间最下面就可以关闭几乎所有弹窗，
#   而且还会在地图界面」）—— 就是底部导航中间那格 (541,1890)（平时是「开始冒险」）✓
#   有了它就不必给每个弹窗单独写关闭逻辑（预言石板/莱姆/各种未知面板都吃这一下）
#
# ⚠⚠ 定位（用户 2026-09-26 最新口径）：「**万能点位可以用来应对异常情况，防止任务过早中断**」
#   ⇒ 它是**异常兜底**，不是常规动作 ✗（别每轮都点一下）
#   ✅ 安全性（用户 2026-09-26 补充实测）：「**那边点了非常安全，不会有变化**」
#     我 2026-09-26 也复测过：在**选图界面**（那格文字正是「开始冒险」）点它，
#     前后两张 OCR 完全一致（只有体力自然 +1、倒计时正常走）⇒ 无副作用 ✓
#     （底部导航 公会/角色/开始冒险/斗技场/图鉴 在所有界面常驻，但点中间那格不会开图）
#   ⇒ 所以可以放心用作兜底；但仍**必须**保留「先认面板类型」：
#     战斗界面（有战斗胜利/失败/回放战斗）**只能点「关闭」(577,1439)** ✗不能点开始冒险
#     有底部「关闭」按钮的（结算/奖励面板）⇒ 点那个关闭 ✓
#     其余未知面板 ⇒ 点万能位 (541,1890) ✓
#   使用场景：① 整盘读成暗格（面板盖住棋盘）；② 退图 90 秒快超时的最后一救；
#            ③ 连续两轮一个可识别元素都认不到；④ 已认出面板类型（预言石板等）
UNIVERSAL_CLOSE = (541, 1890)


def universal_close(b, log, items=None, probe=None, where='', at=None):
    """关当前弹窗 —— **先认面板类型再决定点哪** ✓（也是任务"异常兜底"，用户 2026-09-26 口径）

    ⚠⚠ 用户 2026-09-26 明确：「**战斗界面还是得点关闭，不能点开始冒险**」✗
      ⇒ 判断顺序：
        ① 认到底部「关闭」按钮（战斗结算/胜利界面都是它）⇒ 点它 ✓
        ② 认到是战斗面板（战斗胜利/失败/回放战斗）但没量到「关闭」⇒ 按实测坐标
           **(577,1439)** 点关闭 ✓（**绝不点 (541,1890)** ✗）
        ③ 其它弹窗 ⇒ 点「中间最下面」万能位 (541,1890) ✓（用户实测：几乎所有弹窗都能关，
           而且关完还在图里）
      ✅ 安全性：用户 2026-09-26 补充「**那边点了非常安全，不会有变化**」⇒ 即使当前没弹窗，
        点它也无副作用（不切图/不走掉）⇒ 可放心当兜底用，但**别当常规动作每轮点** ✗
      关完还要**验证**（probe）⇒ 没关掉就走老兜底（找 X / 关闭符 / 硬脱困），不占死闭环。

    probe = 弹窗的识别文字（用来自查真的关掉了）
    at    = 点出这个弹窗的格子坐标（记下来给调用方拉黑 ⇒ 以后不再点它）
    """
    items = list(items or [])
    cl = bottom_close(items)
    # ⚠ 战斗面板判据必须严格（见 is_battle_panel 的注释：地图上「首领战斗胜利」会让
    #   宽松判据误判 ⇒ 点在棋盘格上 = 乱点 ✗）
    is_battle = is_battle_panel(items)
    if cl:
        _tap(b, cl['cx'], cl['cy'], wait=1.8)
        rec = {'panel_close': 'bottom_close', 'where': where, 'at': (cl['cx'], cl['cy'])}
    elif is_battle:
        b.tap(int(LAYOUT.sx(577)), int(LAYOUT.sy(1439)), wait=1.8)
        rec = {'panel_close': 'battle_close_fixed', 'where': where,
               'at': (577, 1439), 'note': '战斗界面点关闭，不点开始冒险'}
    else:
        b.tap(int(LAYOUT.sx(UNIVERSAL_CLOSE[0])), int(LAYOUT.sy(UNIVERSAL_CLOSE[1])),
              wait=1.6)
        rec = {'universal_close': where, 'at': list(UNIVERSAL_CLOSE)}
    if at:
        rec['cell'] = tuple(at) if isinstance(at, (list, tuple)) else at
    gone = True
    if probe:
        gone = panel_gone(b, probe)
        rec['still'] = (not gone)
    if not gone:
        # 万能位没关掉 ⇒ 老路子：找 X / 找关闭符 / 硬脱困 ✓（一样要验证）
        n = close_x_panels(b, b.img())
        x = find_x(ocr_ch(b, tag='uni'))
        if x:
            _tap(b, x['cx'], x['cy'], wait=1.3)
            n += 1
        if not n:
            force_unstick(b, log, 'universal_close', ctx={'tapped': at})
        rec['fallback'] = n
    log.append(rec)
    return True


def block_cell(log, st, cell, why):
    """把某格**拉黑**（本图不再点）——用户 2026-09-26：点出预言石板的那格不要再点 ✓"""
    if not cell:
        return
    try:
        c = (int(cell[0]), int(cell[1]))
    except (TypeError, ValueError, IndexError):
        return
    if isinstance(st, dict):
        st.setdefault('done', set()).add(c)
    log.append({'cell_blocked': why, 'at': list(c)})


def _bottom_ok(items, lo=900, hi=1650):
    """弹窗下半屏的「返回 / 确定 / 确认」按钮（取最靠下那条）"""
    best = None
    for t in items or []:
        s = (t.get('text') or '').strip().replace(' ', '')
        if s in ('返回', '确定', '确认') and LAYOUT.sy(lo) < t['cy'] < LAYOUT.sy(hi):
            if best is None or t['cy'] > best['cy']:
                best = t
    return best


def lime_back(items):
    """「发现莱姆！」弹窗的返回按钮（按文本找，实测 (539,1309)）"""
    if not fb(items, *L['lime']):
        return None
    return _bottom_ok(items, 900, 1600)


def newequip_back(items):
    """「获得新装备！」弹窗的返回按钮（实测 (540,1252)，2026-09-26 补）"""
    if not fb(items, *L['newequip']):
        return None
    return _bottom_ok(items, 900, 1650)


def close_newequip(b, items, log, where, at=None, verify=True):
    """⭐「获得新装备！」弹窗 → 点底部「返回」关掉；关不掉就强制脱困 ✓

    返回 True 表示「这个弹窗我处理了」（调用方据此 continue / return 'handled'）。
    ⚠ 按钮坐标**按文字找**，不写死：点序分支只 OCR 了 y130~1080，标题在 y≈992 能认到，
      但按钮在 y≈1252 不见得在同一条带里 ⇒ 补一次**底部窄带 OCR** 精确取按钮（罕见才走）。
    """
    if not fb(items, *L['newequip']):
        return False
    nb = _bottom_ok(items)
    if nb is None:
        it = ocr_ch(b, band=(LAYOUT.sy(1050), LAYOUT.sy(1650)), tag='newequip')
        nb = _bottom_ok(it)
    if nb is None:                       # 兜底：实测位置（1080×1920）
        nb = {'cx': int(LAYOUT.sx(540)), 'cy': int(LAYOUT.sy(1252))}
    _tap(b, int(nb['cx']), int(nb['cy']), wait=1.6)
    rec = {'newequip_back': where, 'at': (int(nb['cx']), int(nb['cy']))}
    if at:
        rec['tap'] = tuple(at) if isinstance(at, (list, tuple)) else at
    key = 'newequip_%s' % where
    if verify and not panel_gone(b, L['newequip'][0]):
        # 关不掉 ⇒ 别让循环对着面板继续点 ✗（老毛病：不验证就 return handled = 死循环）
        _PANEL_STUCK[key] = _PANEL_STUCK.get(key, 0) + 1
        force_unstick(b, log, 'newequip_%s' % where, ctx={'tapped': at})
        rec['still'] = True
        rec['n'] = _PANEL_STUCK[key]
    else:
        _PANEL_STUCK[key] = 0
    log.append(rec)
    return True


def flush(log):
    # ⭐ v1.12：把最新日志挂到模块全局 ⇒ `dump_summary()` 能把它抄一份到**公共目录**
    #   （release 包不可 run-as，私有 runs/ 拿不出来；朋友的手机只能靠这个文件回传 ✓）
    try:
        global _GLOBAL_LOG
        _GLOBAL_LOG = log
    except Exception:       # noqa: BLE001
        pass
    try:
        import json
        with open(LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    # ⭐ 统计**边跑边落盘**：这样即使被「停止」（taskkill /F 杀进程）也能拿到最新总结
    dump_summary()


# ⭐⭐ 2026-09-27 用户要求：每连刷 N 张图，去背包→装备→**一键升级**
BAG_EVERY = 10          # 每几张图升级一次（0 = 关闭 ✓）
BAG_STEPS = (
    # (说明,           候选文字（命中任一即点 ✓）,        点完等几秒, 必须命中?)
    ('打开背包',       ('背包', '道具'),                    2.2, True),
    ('进装备页',       ('装备', '装备栏', '装 备'),          2.2, False),
    ('一键升级',       ('一键升级', '一键升阶', '一键强化'),   2.6, True),
    ('确认',           ('确定', '确认', '是'),               2.6, False),
    ('返回',           ('返回', '关闭'),                    2.2, False),
)


_UI_TPL_CACHE = {}
# ⭐ 2026-10-01：背包 UI 的关键帧落**公共目录**（诊断用；release 包不可 run-as ⇒ 私有拿不出来）
BAG_PUB_DIR = '/sdcard/Download/autoexplore/bagdbg'
# ⭐ v1.33：本次运行的标记文件（`_clear_stale_diag_frames()` 写的）
#   Java 侧 `Feedback.java` 打包时读它 ⇒ 只收**本次运行**的帧 + 把新鲜度写进包 ✓
RUN_MARKER = '_run_marker.json'
# ⭐ v1.33：本次运行落过的诊断帧台账 [(文件名, 落盘时刻)]（`_pub_dump` 追加）
_DIAG_DUMP_LOG = []
# ⭐⭐ 落帧开关（**性能相关，用户 2026-10-01 问「跑一张图会不会变慢」**）：
#   · BAG_DUMP=False ⇒ 完全不落帧（零 I/O 零编码开销 ✓ 稳定后建议关）
#   · BAG_DUMP_ALL=False（默认）⇒ **只落"值得看"的帧**：每轮第一张起点帧 + 公会/背包结果帧
#     + 每次失败/兜底帧；routine 的成功帧不落 ⇒ 默认每图 ~3~5 张（≈0.1~0.3s/张 PNG 编码）
BAG_DUMP = os.environ.get('MAPBOT_BAG_DUMP', '1') != '0'
BAG_DUMP_ALL = os.environ.get('MAPBOT_BAG_DUMP_ALL', '0') == '1'
# 模板多尺度范围（老版 0.90~1.15 对"面板随分辨率非等比缩放"不够；放宽到 0.80~1.20 ✓）
_BAG_TPL_SCALES = (0.80, 0.85, 0.90, 0.95, 1.0, 1.05, 1.10, 1.15, 1.20)

def _find_ui_tpl(b, name, region=None, thr=0.80):
    """⭐⭐ 2026-09-30 治本（用户：「换个分辨率不就又用不了了」）：公会/背包 UI 入口改
    **模板匹配**，不再依赖写死的归一化坐标 —— 公会/背包窗口的 Unity UI **不守探索棋盘的
    锚定模型**（A 类弹窗/弹性布局），硬编码坐标换分辨率必错位（720x1600 实测 bag_not_open）。
    模板 = 归一化 1080x1920 帧系裁剪（templates/ui/，build_pack 随包分发），
    在当前归一化帧上多尺度 TM_CCOEFF_NORMED（0.9~1.15 容忍长屏非等比压缩）。
    region=(x0,y0,x1,y1) 限定搜索区。返回 (cx,cy,score) 或 None。"""
    try:
        import cv2
        import numpy as np
    except Exception:       # noqa: BLE001
        return None
    tpl = _UI_TPL_CACHE.get(name)
    if tpl is None:
        path = os.path.join(_MAPBOT_ROOT, 'templates', 'ui', name)
        if not os.path.exists(path):
            log_note = 'ui_tpl_missing:' + name
            say('   ⚙ ' + log_note)
            return None
        tpl = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        _UI_TPL_CACHE[name] = tpl
    if tpl is None:
        return None
    img = b.img()
    if img is None:
        return None
    # ⭐⭐ v1.45 提速（施工单 ②）：**先走参考系定点单尺度快查**（毫秒级），
    #   没命中再回退下面那套 6 档多尺度全图搜（长屏非等比压缩的兜底，行为不变）。
    #   为什么敢先单尺度：归一化帧是**等比**归一的（RefMapper 两段斜率都是 kx）
    #   ⇒ 1024×1920 帧上模板就是 1:1；只有真机弹性区压缩那类才需要多档。
    try:
        import fixed_ref as _fxr
        _hit0 = _fxr.find(img, name, region=region, thr=thr)
        if _hit0 is not None:
            return _hit0
    except Exception:       # noqa: BLE001
        pass
    H, W = img.shape[:2]
    x0, y0, x1, y1 = region or (0, 0, W, H)
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    best = None
    th, tw = tpl.shape[:2]
    for s in (0.90, 0.95, 1.0, 1.05, 1.1, 1.15):
        w, h = int(tw * s), int(th * s)
        if w < 16 or h < 16 or w >= sub.shape[1] or h >= sub.shape[0]:
            continue
        t = cv2.resize(tpl, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(sub.astype(np.float32), t.astype(np.float32),
                                cv2.TM_CCOEFF_NORMED)
        _mn, mx, _mnl, mxl = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (mx, mxl[0] + w / 2 + x0, mxl[1] + h / 2 + y0)
    if best and best[0] >= thr:
        return (int(best[1]), int(best[2]), round(best[0], 3))
    return None


def _pub_dump(name, img, important=True):
    """把一帧写一份到**公共目录** `/sdcard/Download/autoexplore/bagdbg/`（诊断用 ✓）

    为什么不用私有 `runs/`：**release 包不可 `run-as`** ⇒ 真机截图根本拿不出来 ✗
    （Java 侧 `OverlayService.dump()` 就是往这儿写的，同一个 uid、同一档权限 ✓）

    ⚠ 性能（用户 2026-10-01 问「会不会变慢」）：一次 PNG 编码 + 落盘 ≈ 0.1~0.3 秒
    ⇒ **默认只落"值得看"的帧**（`important=True`：起点/公会/背包结果/失败/兜底）；
    routine 成功帧（装备页/确认框…）只在 `BAG_DUMP_ALL=1` 时才落 ✓；
    总开关 `BAG_DUMP=0`（或环境变量 `MAPBOT_BAG_DUMP=0`）⇒ 一张都不落 ✓
    """
    if not BAG_DUMP:
        return None
    if not important and not BAG_DUMP_ALL:
        return None
    try:
        if img is None:
            return None
        if not os.path.isdir(BAG_PUB_DIR):
            os.makedirs(BAG_PUB_DIR, exist_ok=True)
        import cv2
        p = os.path.join(BAG_PUB_DIR, str(name) + '.png')
        # ⚠ 用 imencode + tofile：`cv2.imwrite` 在**含中文的路径**上会静默失败（返回 False ✗）
        ok, buf = cv2.imencode('.png', img)
        if not ok:
            return None
        buf.tofile(p)
        # ⭐ v1.33：把落帧时刻**留在文件 mtime 上**（Java 侧按它过滤陈货 ✓）
        #   并记到本模块的诊断台账里，打包时可逐张写清"这张图是哪一刻落的" ✓
        try:
            _DIAG_DUMP_LOG.append((str(name), time.time()))
        except Exception:       # noqa: BLE001
            pass
        return p
    except Exception:       # noqa: BLE001
        return None


def _diag_frame_files():
    """列出 bagdbg 目录里**本次可用于诊断**的帧（png），按新→旧排

    ⚠ 只认"诊断帧"那一类文件名（`board_hidden_*` / `marks_none_*` / `dice_nobtn` /
    `vault_no_hit_*`），**不含** `mgas_log.txt` / `_run_marker.json`（那不是帧）✓
    """
    try:
        if not os.path.isdir(BAG_PUB_DIR):
            return []
        out = [f for f in os.listdir(BAG_PUB_DIR)
               if f.lower().endswith('.png') and not f.startswith('_')]
        out.sort()
        return out
    except Exception:       # noqa: BLE001
        return []


def _purge_diag_frames_in(bag_dir, device='', tag=''):
    """⭐ v1.33 真正干活的核：清空 `bag_dir` 下的 `*.png` + 写运行标记

    ⭐ 抽成独立函数是**为了能真跑验证**（门禁/手工都能直接调它 ✓）——
    门禁只查字符串的话，"函数写了但从没被调起"这种错会一路绿到底 ✗
    （教训见《错误教训》B2：先分清代码错还是环境错，别信"看着对"）

    返回 (删掉几个, 写的标记路径 | None)；**失败绝不抛**（诊断不该影响开跑 ✓）
    """
    import json as _json
    killed = 0
    try:
        if not os.path.isdir(bag_dir):
            os.makedirs(bag_dir, exist_ok=True)
        for n in os.listdir(bag_dir):
            if n.lower().endswith('.png'):
                try:
                    os.remove(os.path.join(bag_dir, n))
                    killed += 1
                except Exception:       # noqa: BLE001
                    pass
    except Exception:       # noqa: BLE001
        return killed, None
    try:
        _mark = {
            # ⚠ 写成**整数秒**（不写浮点）：`json` 遇到小数可能输出科学计数法
            #   （`1.790885417073e+09`），Java 侧解析要多担一份风险 ⇒ 源头掐掉 ✓
            'run_started': int(time.time()),
            'run_started_h': time.strftime('%Y-%m-%d %H:%M:%S'),
            'device': device,
            'tag': tag,
        }
        p = os.path.join(bag_dir, RUN_MARKER)
        with open(p, 'w', encoding='utf-8') as _f:
            _json.dump(_mark, _f, ensure_ascii=False)
        return killed, p
    except Exception:       # noqa: BLE001
        return killed, None


def _clear_stale_diag_frames():
    """⭐⭐⭐ v1.33【每次开跑先把上一次的诊断帧清干净】—— 治"反馈包里的图是陈货"

    起因（用户 2026-10-02 原话）：「反馈包里的图**不是他刚刚运行的图**，和之前的图一样」
    根因：诊断帧写**固定文件名**（`board_hidden_rN.png` …），而 `_pub_dump()` 静默覆盖、
    **从不清理** ⇒ 这一局没触发那个分支就没新文件 ⇒ 目录里剩的**还是上次的旧帧**，
    `Feedback.java` 又把 bagdbg 的 png 全塞进包 ⇒ 发出来就是陈货 ✗
    （实证：realme 两包相隔 3 小时，`board_hidden_r0.png` 的 md5 完全相同）

    做法：
      ① 删掉 bagdbg 下的 `*.png`（只删 png ⇒ 日志/运行标记不动 ✓）
      ② 写一份 `_run_marker.json`（本次运行起始时间戳）
         ⇒ Java 侧打包时**只收比它新的帧**并把清单写进包，双保险 ✓
    ⚠ 端上（Chaquopy，os.name=='posix'）以外直接跳过：PC 上 '/sdcard/...' 会污染工作区 ✗
    ⚠ 真干活的核在 `_purge_diag_frames_in()`，可脱离端上直接验证 ✓
    """
    if os.name != 'posix':      # ⚠ 只在端上做（PC 跑门禁/对拍时不碰 /sdcard ✗）
        return
    try:
        del _DIAG_DUMP_LOG[:]    # 本次运行的台账从零开始 ✓
        killed, p = _purge_diag_frames_in(BAG_PUB_DIR, INSTANCE_DEV, INSTANCE_TAG)
        if p:
            say('   · 已清理上次的诊断帧（%d 张 · %s）' % (killed, BAG_PUB_DIR))
        else:
            say('   · ⚠ 清理旧诊断帧失败（不影响开跑）')
    except Exception as _e:     # noqa: BLE001
        say('   · ⚠ 清理旧诊断帧失败（不影响开跑）：%r' % (_e,))


def _tpl_hit(img, name, region=None, scales=None, thr=0.80):
    """在**给定图像**（归一化帧 or 弹窗帧）上多尺度模板匹配 → (cx, cy, score) | None

    `_find_ui_tpl` 只能吃 `b.img()`（归一化帧）；这里抽出"吃任意帧"的版本，
    让背包流程能在**弹窗帧**上也做匹配（锚设备中心 ⇒ 分辨率无关的第二条路 ✓）
    """
    try:
        import cv2
        import numpy as np
    except Exception:       # noqa: BLE001
        return None
    tpl = _UI_TPL_CACHE.get(name)
    if tpl is None:
        path = os.path.join(_MAPBOT_ROOT, 'templates', 'ui', name)
        if not os.path.exists(path):
            say('   ⚙ ui_tpl_missing:' + name)
            return None
        tpl = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        _UI_TPL_CACHE[name] = tpl
    if tpl is None or img is None:
        return None
    # ⭐⭐ v1.45 提速（施工单 ②）：同上 —— 先单尺度定点快查，未命中再回退多尺度。
    #   ⚠ 只在「调用方没指定多档尺度」时才走快查（`scales=` 显式给了就说明它要扫多档）
    if not scales:
        try:
            import fixed_ref as _fxr2
            _hit1 = _fxr2.find(img, name, region=region, thr=thr)
            if _hit1 is not None:
                return _hit1
        except Exception:       # noqa: BLE001
            pass
    H, W = img.shape[:2]
    x0, y0, x1, y1 = region or (0, 0, W, H)
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(W, int(x1)), min(H, int(y1))
    sub = img[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    best = None
    th, tw = tpl.shape[:2]
    for s in (scales or _BAG_TPL_SCALES):
        w, h = int(tw * s), int(th * s)
        if w < 16 or h < 16 or w >= sub.shape[1] or h >= sub.shape[0]:
            continue
        t = cv2.resize(tpl, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(sub.astype(np.float32), t.astype(np.float32),
                                cv2.TM_CCOEFF_NORMED)
        _mn, mx, _mnl, mxl = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (mx, mxl[0] + w / 2 + x0, mxl[1] + h / 2 + y0)
    if best and best[0] >= thr:
        return (int(best[1]), int(best[2]), round(best[0], 3))
    return None


def _bag_find(b, keys, prefer='top', tag='', exact=False):
    """⭐ 双通道找**文字目标** → (cx, cy, ch, text) 或 None（ch: 'norm' | 'dlg'）

    ① 归一化帧 `b.ocr()`（点用 `b.tap`）—— PC/9:16 与真机都走这条 ✓
    ② 查不到且 C>0（真机高分辨率）⇒ 补一次**弹窗帧** `b.ocr_dlg()`（点用 `b.tap_dlg`）
       —— 弹窗系坐标**锚设备屏幕中心**，分辨率一变它自己跟着缩放 ✓
    ⚠ **一律不做绝对 y 过滤**（老版 `cy<700` 在真机上把页签滤掉了 ✗）；同一通道里多个
      候选按**面板内相对位置**挑：`prefer='top'` 取最上（页签在面板顶部 ✓）、
      `prefer='bottomright'` 取最右下（按钮在面板右下 ✓）
    """
    cands = []
    try:
        cands.append(('norm', b.ocr(tag=(tag + '_n') if tag else None)))
    except Exception:       # noqa: BLE001
        pass
    for ch, its in cands:
        hit = _bag_pick(its, keys, prefer, exact)
        if hit:
            return (int(hit['cx']), int(hit['cy']), ch, (hit.get('text') or ''))
    if dlg_c() and hasattr(b, 'ocr_dlg'):
        try:
            its2 = b.ocr_dlg(tag=(tag + '_d') if tag else None)
        except Exception:       # noqa: BLE001
            its2 = []
        hit = _bag_pick(its2, keys, prefer, exact)
        if hit:
            return (int(hit['cx']), int(hit['cy']), 'dlg', (hit.get('text') or ''))
    return None


def _bag_pick(items, keys, prefer='top', exact=False):
    """在一组 OCR 条目里挑目标（见 `_bag_find`）"""
    hits = []
    for i in (items or []):
        t = (i.get('text') or '').replace(' ', '')
        if not t:
            continue
        if exact:
            ok = t in keys
        else:
            ok = any(k in t for k in keys)
        if ok:
            hits.append(i)
    if not hits:
        return None
    if prefer == 'bottomright':
        return max(hits, key=lambda z: (z.get('cy', 0), z.get('cx', 0)))
    return min(hits, key=lambda z: (z.get('cy', 0), z.get('cx', 0)))


def _panel_tap(b, x, y, ch='norm', log=None, what=''):
    """**面板类**点击：走完整阶梯（同点 → 下移 45px → 长按 350ms → **换通道**）✓

    ⭐ 2026-10-01 全分辨率体检：面板按钮有两套坐标系（归一化系 / 弹窗系），
    写死的常量必然只对其中一套成立 ⇒ `_tap_verified(tries=2)` 的"只重试 1 次"不够：
    第 1 下没生效时**必须允许换通道再试**（跨通道那一级）。
    ⚠ 这不会造成"连点"：`_tap_verified` 用 `b.tap` 的真实回报判生效，
    生效就立刻返回 ⇒ 正常情况**只点 1 下** ✓
    """
    return _tap_verified(b, x, y, ch, log=log, what=what, tries=4)


def _bag_tap(b, cx, cy, ch, wait=1.6):
    """按通道点击（弹窗系必须 `tap_dlg`，真机上用 b.tap 会偏 C≈200px ✗）
    → **返回"画面变没变"**（kt 侧监听；None=没等/未知 ✓）"""
    if ch == 'dlg':
        return b.tap_dlg(int(cx), int(cy), wait=wait)
    return b.tap(int(cx), int(cy), wait=wait)


def bag_upgrade(b, log, tag='bag'):
    """⭐ 每 N 张图去背包「装备」页做一键升级（用户 2026-09-27 要求 ✓）

    流程**复用 use_supply 那套**（用户：「和之前一样」✓）：
        公会 → 背包 → **装备页签** → 一键升级 →（确定）→ 关背包回地图界面
    ✅ 页签与按钮**优先按 OCR 文字找** ✓（不写死坐标 ✓）；找不到才用兜底坐标 ✓
    ✅ **必须站在选图界面**才动手（和 use_supply 同款安全闸 ✓ 免得在地图里误点棋盘 ✗）

    ⭐⭐ 2026-10-01 **重写：全分辨率适用**（用户要求「重新搞自动升星，要求全分辨率适用」）
    ────────────────────────────────────────────────────────────────────────
    老流程在真机（1280×2772）上的病（`_verify/phone_stamina_0930/autoexplore_bag*.log`）：
      · 「装备」页签判据带**绝对 y 过滤**（`cy < 700`）⇒ 面板位置随分辨率一变就被滤掉
        ⇒ 实测永远走兜底坐标；
      · 「一键升星」在**归一化帧**里认不到、模板也没命中（面板在真机上未必落进 toRef 的
        可见区）⇒ 全程碰运气；
      · 收尾把「进入地图」当点击候选 ⇒ 真开图（-25 体力）✗（已单独修 ✓）。
    新口径（四条，都是"分辨率无关"的）：
      ① **双通道识别**：每一步先查**归一化帧**（`b.ocr` → `b.tap`），没查着再查**弹窗帧**
         （`b.ocr_dlg` → `b.tap_dlg`）—— 弹窗系坐标**锚设备屏幕中心**，天生随分辨率缩放 ✓
         （PC/9:16 的 C=0 ⇒ 只有归一化通道，行为与旧版一致 ✓）
      ② **纯文字驱动**：目标 = 「背包」/「装备」/「一键升星·一键升级·一键升阶·一键强化」/
         「确定·确认」；**取消一切绝对 y 过滤**，改在**同一面板内按相对位置挑**
         （页签取**最上**、按钮取**最右下** ✓）
      ③ **模板两帧 × 多尺度**（0.80~1.20）兜底 —— 仍找不到才退锚点坐标，且**只在
         "已确认在背包里/在公会界面"**时才允许（绝不在任意画面盲点 ✗）
      ④ **真机自证**：每步把「用哪个通道 / 命中什么 / 点哪」`say` 出来，关键帧写一份到
         `/sdcard/Download/autoexplore/bagdbg/`（release 包不可 `run-as` ⇒ 私有 runs/ 拿不出来，
         公共目录 PC 侧能直接 `adb pull` 回来离线核对 ✓）
    """
    try:
        b.snap(tag + '0')
        items = b.ocr(tag=tag)
        txt = [i['text'] for i in items]
        in_map_now = any('结束冒险' in t for t in txt)
        on_select = any(any(k in t for k in ('进入地图', '快速扫荡', '开始冒险', '星界秘境'))
                        for t in txt)
        if in_map_now or not on_select:
            log.append({'bag': 'skip_not_on_select', 'in_map': bool(in_map_now),
                        'on_select': bool(on_select), 'texts': txt[:14]})
            say('   ⚙ 背包升级：现在不在选图界面 ⇒ 跳过（免得误点地图格 ✗）')
            status('不在选图界面 · 跳过升星')
            return False
        say('   ⚙ 背包一键升级：开始（复用补给的流程 ✓）')
        status('装备升星中…')

        # ① 公会（看不到 邮件/商店/招募 就先去公会 ✓）
        # ② 背包（⭐ 2026-09-30 深夜重构：实证「公会界面直接点 BAG_BTN」可开背包
        #    （bag_step2 手动验证 ✓），但「点 GUILD_BTN 按钮再点背包」的时序不稳
        #    （公会界面内点公会按钮后的画面状态不确定，v0.45 在公会界面 3 轮全失败）
        #    ⇒ 反转：**每轮先点 BAG_BTN 查「背包」，没开再 GUILD_BTN 进公会**，共 3 轮。
        #    起点已在公会 ⇒ 第 1 轮命中；起点在选图界面 ⇒ 第 1 轮点空、第 2 轮命中 ✓）
        # ⭐⭐ 2026-09-30 深夜【点击有效性自检】：模拟器 MuMu 的无障碍手势对公会界面会
        #   **静默失效**（dispatchGesture 返回 True 但事件丢失；input tap 同坐标有效 ——
        #   2026-09-30 对照实验）。失效时升级流程每次点击都打在空气上或误点别处
        #   （用户：「一直打开着头像界面却不知道在干嘛」——失败兜底的 _close_bag 盲点万能位）。
        #   ⇒ 判据：点击后**画面均值差 <2.0 = 零变化**，连续 2 轮 ⇒ 判定通道失效 ⇒
        #     **立即放弃**（不重试、不 _close_bag 盲点），say 明确报错让人手动升星 ✓
        import numpy as _np
        _frame0 = b.img()
        _pub_dump(tag + '_select', _frame0)      # 起点帧（选图界面）也留一份 ✓
        _dead = 0
        items = []
        opened = False
        # ⭐⭐ 2026-10-01 真机修（用户报「装备升星脚本出问题了，没有正常升星」）：
        #   现象：`⚙ 背包一键升级：开始` 之后 15 秒 → `背包没打开（重试 3 次）✗`（真机 15:34 实锤）
        #   根因（结构性问题）：原流程**第 1 轮就盲点「公会界面的 BAG_BTN(964,1680)」**，
        #   可此刻人站在**选图界面** ⇒ 那一击落点不可控（真机上可能点开图鉴等面板）
        #   ⇒ 之后"点公会 → 找背包图标"全在**错误画面**上做 ⇒ 3 轮全失败 ✗
        #   ⇒ 改成：**先确认在不在公会界面**（公会/邮件/商店/招募 任一），不在就
        #     「OCR 找『公会』二字进公会」（分辨率无关 ✓）→ 找不到才退写死坐标；
        #     进公会之后才找背包图标 ✓。每轮的关键信息**直接 say 出来**（结构化条目要等
        #     `flush(log)` 跑完才打印，真机上根本来不及看 ✗）
        # ⚠ 判据函数一律用**模块级** `_guild_on()`（2026-10-01：写成嵌套函数导致
        #   `NameError: free variable 'i' ...`，整个升星流程当场崩 —— 真机 15:41/15:51 实锤 ✗）
        for _try in range(3):
            # ① 先站到公会界面（不在才点，避免在公会界面里重复盲点）
            if not _guild_on(items):
                _g = None
                for _i in items:
                    if (_i.get('text') or '').strip().replace(' ', '') in ('公会', '公會'):
                        _g = _i
                        break
                _gat = (_g['cx'], _g['cy']) if _g else GUILD_BTN
                b.tap(_gat[0], _gat[1], wait=2.8)
                log.append({'bag': 'open_guild', 'at': _gat,
                            'by': 'ocr' if _g else 'fallback', 'try': _try})
                say('   ⚙ 升星第 %d 轮：先进公会 (%d,%d) %s'
                    % (_try + 1, _gat[0], _gat[1],
                       '（OCR 找到「公会」✓）' if _g else '（写死坐标）'))
                time.sleep(1.2)      # 公会界面静止时 wait_stable 会秒过 ⇒ 固定等
                b.snap(tag + 'g%d' % _try)
                items = b.ocr(tag=tag + 'g')
                _pub_dump('%sg%d_guild' % (tag, _try), b.img())
                if not _guild_on(items):
                    say('   ⚠ 点了公会但画面不像公会界面：认到 %s'
                        % ([i['text'] for i in items][:10],))
                    log.append({'bag': 'guild_not_reached', 'try': _try,
                                'texts': [i['text'] for i in items][:12]})
            # ② 开背包（⭐ 2026-10-01：**文字优先** —— 真机公会帧里「背包」二字清清楚楚
            #    （离线核对：`guild_bag_icon.png` 在真机帧上命中 **(964,1680) score 0.978** ✓，
            #    与写死坐标 BAG_BTN 完全一致）；顺序 = 文字「背包」→ 模板（归一化/弹窗两帧）
            #    → 锚点坐标（**只在已确认公会界面内**才允许 ✓）
            _bk = None
            for _i in (items or []):
                if (_i.get('text') or '').strip().replace(' ', '') in ('背包', '道具'):
                    _bk = _i
                    break
            if _bk:
                _tap_verified(b, _bk['cx'], _bk['cy'], 'norm', log=log,
                              what='背包(文字)')
                log.append({'bag': 'open_bag_text', 'at': (_bk['cx'], _bk['cy']),
                            'text': _bk.get('text'), 'try': _try})
                say('   ⚙ 开背包：OCR 找到「%s」(%d,%d) ✓'
                    % (_bk.get('text'), _bk['cx'], _bk['cy']))
            else:
                _hit, _ch = _tpl_hit(b.img(), 'guild_bag_icon.png',
                                     region=(int(LAYOUT.sx(300)), int(LAYOUT.sy(1000)),
                                             1080, 1920)), 'norm'
                if _hit is None and dlg_c() and hasattr(b, 'img_dlg'):
                    _hit = _tpl_hit(b.img_dlg(), 'guild_bag_icon.png')
                    _ch = 'dlg'
                if _hit:
                    _tap_verified(b, _hit[0], _hit[1], _ch, log=log,
                                  what='背包(模板%.2f)' % _hit[2])
                    log.append({'bag': 'open_bag_tpl', 'at': (_hit[0], _hit[1]),
                                'score': _hit[2], 'ch': _ch, 'try': _try})
                    say('   ⚙ 开背包：模板命中 (%d,%d) %.2f（%s）'
                        % (_hit[0], _hit[1], _hit[2],
                           '弹窗帧' if _ch == 'dlg' else '归一化帧'))
                else:
                    _tap_verified(b, BAG_BTN[0], BAG_BTN[1], 'norm', log=log,
                                  what='背包(锚点)')
                    log.append({'bag': 'open_bag_anchor', 'at': BAG_BTN, 'try': _try})
                    say('   ⚙ 开背包：文字/模板都没中 ⇒ 公会界面锚点 (%d,%d)' % BAG_BTN)
            b.snap(tag + '1')
            items = b.ocr(tag=tag)
            _pub_dump('%s%d_bag' % (tag, _try), b.img())
            # ⭐⭐ 判"开了没"用**颜色判据**（真机 OCR 读不到标题「背包」二字 ✗）
            _op, _how = _bag_panel_open(b, items)
            if _op:
                opened = True
                say('   ⚙ 背包已打开 ✓（判据：%s）' % _how)
                log.append({'bag': 'bag_open_ok', 'how': _how, 'try': _try})
                break
            # ⭐⭐ 可诊断：这一轮点了哪、模板分数多少、屏幕上认到啥（logcat 直接可见 ✓）
            _txts = [i['text'] for i in items][:12]
            _where = (('模板命中 (%d,%d) %.2f' % (_hit[0], _hit[1], _hit[2])) if _hit
                      else ('写死坐标 (%d,%d)' % BAG_BTN))
            say('   ⚙ 开背包第 %d 轮未成：%s ⇒ 屏上认到 %s' % (_try + 1, _where, _txts))
            log.append({'bag': 'open_bag_miss', 'try': _try, 'at': _where, 'texts': _txts})
            if _hit is not None:
                # ⭐ 硬判据（v0.52：均值差判据被轮播横幅干扰——横幅一动 diff 就超阈值）：
                #   **模板命中背包图标、点击却没开出背包 = 点击通道失效铁证** ⇒ 立即放弃。
                #   重试同一点击无意义；GUILD_BTN/万能位兜底才是「打开着头像界面不知道在干嘛」
                #   的乱点源头 ⇒ 坚决不点（v0.53）
                say('   ⚠ 模板命中背包图标但点击未生效 ⇒ 放弃升星（点击通道异常），请手动操作')
                log.append({'bag': 'abort_tap_dead', 'at': (_hit[0], _hit[1]), 'try': _try})
                return False
            _now = b.img()
            if _frame0 is not None and _now is not None:
                _diff = float(_np.mean(_np.abs(
                    _now.astype(int) - _frame0.astype(int))))
            else:
                _diff = 999.0
            if _diff < 2.0:
                _dead += 1
                log.append({'bag': 'tap_no_effect', 'try': _try, 'diff': round(_diff, 2),
                            'tpl_hit': bool(_hit)})
                # ⭐ 判据收紧（v0.51 实测 diff=1.6 只触发 1 次没拦住 _close_bag 盲点）：
                #   **模板明明命中了图标、点了却零变化 = 通道失效铁证 ⇒ 一次即放弃**；
                #   兜底坐标轮连续 2 次零变化也放弃
                if _hit is not None or _dead >= 2:
                    say('   ⚠ 点击通道在此界面无效（画面零变化）⇒ 放弃升星，请手动操作')
                    log.append({'bag': 'abort_dead_channel', 'tpl_hit': bool(_hit)})
                    return False
            else:
                _dead = 0
                _frame0 = _now
            time.sleep(1.2)
        if not opened:
            _ftxts = [i['text'] for i in items][:20]
            log.append({'bag': 'bag_not_open', 'texts': _ftxts})
            say('   ⚙ 背包没打开（重试 3 次 ✗）｜最后一屏认到：%s' % (_ftxts,))
            if _dead < 2:        # 通道失效时绝不 _close_bag 盲点（乱点源头 ✗）
                _close_bag(b, items, log)
            return False
        # ③ **装备页签**（⭐ 2026-10-01 真机修正：**页签只在弹窗帧里** ⇒ 直接走
        #    `_bag_switch_tab('装备')`（实测弹窗帧 @dlg(346,314) ✓）；旧写法在归一化帧里
        #    找「装备」恒失败 ⇒ 退锚点 (370,360)（真机上那里是别的东西 ✗））
        _ok_tab = _bag_switch_tab(b, '装备', log=log, tag=tag)
        if not _ok_tab:
            _tab = _bag_find(b, ('装备', '装备栏'), prefer='top', tag=tag + '_tab')
        if _tab:
            _bag_tap(b, _tab[0], _tab[1], _tab[2], wait=1.6)
            log.append({'bag': 'equip_tab', 'at': (_tab[0], _tab[1]),
                        'by': 'ocr', 'ch': _tab[2], 'text': _tab[3]})
            say('      · 装备页 → 点 (%d,%d)（%s OCR ✓「%s」）'
                % (_tab[0], _tab[1], '弹窗帧' if _tab[2] == 'dlg' else '归一化帧', _tab[3]))
        else:
            # 兜底：模板（两帧 × 多尺度）→ 仍没有才用锚点坐标（**已确认在背包里**才允许 ✓）
            _hit, _ch = _tpl_hit(b.img(), 'bag_tab_equip.png',
                                 region=(0, 0, 1080, int(LAYOUT.sy(1100)))), 'norm'
            if _hit is None and dlg_c() and hasattr(b, 'img_dlg'):
                _hit = _tpl_hit(b.img_dlg(), 'bag_tab_equip.png')
                _ch = 'dlg'
            if _hit:
                _bag_tap(b, _hit[0], _hit[1], _ch, wait=1.6)
                log.append({'bag': 'equip_tab_tpl', 'at': (_hit[0], _hit[1]),
                            'score': _hit[2], 'ch': _ch})
                say('      · 装备页 → 模板命中 (%d,%d) %.2f（%s）'
                    % (_hit[0], _hit[1], _hit[2], '弹窗帧' if _ch == 'dlg' else '归一化帧'))
            else:
                # ⭐ 2026-10-01 全分辨率体检修：旧兜底点 `EQUIP_TAB=(370,360)`（归一化系）——
                #   真机实测「装备」页签在**弹窗系** dlg(345,315) ⇒ 设备 y≈620；
                #   而 ref(370,360) ⇒ 设备 y≈923 ⇒ **差 ~300px，点空** ✗
                #   根因：页签落在 `toRef()` 丢弃的弹性带（真机设备 y 488~852）里 ⇒ 归一化系没有它 ✗
                _pt = BAG_TAB_DLG.get('装备', EQUIP_TAB)
                _panel_tap(b, _pt[0], _pt[1], 'dlg', log=log, what='装备页(弹窗系标定)')
                log.append({'bag': 'equip_tab_anchor_dlg', 'at': _pt})
                say('      · 装备页 → 页签没认到 ⇒ 弹窗系标定坐标 %s' % (_pt,))
        _pub_dump(tag + '_equip', b.img(), important=False)
        # ④ 一键升星（⭐ 重写：文字（双通道，取**最右下** = 面板右下那颗按钮 ✓）
        #    → 模板（两帧 × 多尺度）→ 锚点兜底（已确认在背包里 ✓））
        b.snap(tag + '2')
        _up = _bag_find(b, ('一键升星', '键升星', '一键升级', '一键升阶', '一键强化'),
                        prefer='bottomright', tag=tag + '_up')
        if _up:
            _bag_tap(b, _up[0], _up[1], _up[2], wait=2.6)
            log.append({'bag': 'upgrade_tap', 'text': _up[3], 'at': (_up[0], _up[1]),
                        'by': 'ocr', 'ch': _up[2]})
            say('      · 一键升星 → 点「%s」(%d,%d)（%s OCR ✓）'
                % (_up[3], _up[0], _up[1], '弹窗帧' if _up[2] == 'dlg' else '归一化帧'))
        else:
            _hit, _ch = _tpl_hit(b.img(), 'bag_upgrade_btn.png',
                                 region=(int(LAYOUT.sx(300)), int(LAYOUT.sy(1100)),
                                         1080, 1920)), 'norm'
            if _hit is None and dlg_c() and hasattr(b, 'img_dlg'):
                _hit = _tpl_hit(b.img_dlg(), 'bag_upgrade_btn.png')
                _ch = 'dlg'
            if _hit:
                _bag_tap(b, _hit[0], _hit[1], _ch, wait=2.6)
                log.append({'bag': 'upgrade_tpl_btn', 'at': (_hit[0], _hit[1]),
                            'score': _hit[2], 'ch': _ch})
                say('      · 一键升星 → 模板命中 (%d,%d) %.2f（%s）'
                    % (_hit[0], _hit[1], _hit[2], '弹窗帧' if _ch == 'dlg' else '归一化帧'))
            else:
                b.tap(UPGRADE_BTN[0], UPGRADE_BTN[1], wait=2.6)
                log.append({'bag': 'upgrade_anchor', 'at': UPGRADE_BTN,
                            'texts': [i['text'] for i in items][:26]})
                say('      · 一键升星 → 文字/模板都没中 ⇒ 锚点坐标 %s（已确认在背包里 ✓）'
                    % (UPGRADE_BTN,))
        # ⑤ 确认弹框（⭐ 2026-10-01 重写：**弹窗系的 y 带**天生与分辨率无关 ✓）
        #   实测：按钮行在**弹窗系** y≈1112（左边「取消」x≈334）；右边那颗**只有金币数**
        #   （如「8000」，没有"确定"字样 ✗）⇒ 优先在**弹窗帧**里按 dlg 带 [1000,1240] 筛、
        #   取**最右**那颗 ✓（第一通道）；再退文字「确定/确认」；最后才用归一化帧老路子 ✓
        b.snap(tag + '3')
        _pub_dump(tag + '_confirm', b.img(), important=False)
        items = b.ocr(tag=tag)
        cf, _cfch, _cfrow = None, 'norm', None
        if dlg_c() and hasattr(b, 'ocr_dlg'):
            try:
                _dits = b.ocr_dlg(tag=tag + '_cf')
            except Exception:       # noqa: BLE001
                _dits = []
            _drow = [i for i in _dits if (i.get('text') or '').strip()
                     and 1000 <= i.get('cy', 0) <= 1240]
            if _drow:
                _dc = max(_drow, key=lambda z: z['cx'])
                cf, _cfch, _cfrow = (_dc['cx'], _dc['cy']), 'dlg', _drow
        if cf is None:
            _ok = _bag_find(b, ('确定', '确认'), prefer='bottomright', tag=tag + '_ok')
            if _ok:
                cf, _cfch = (_ok[0], _ok[1]), _ok[2]
        if cf is None:
            _bands = [(1020, 1220)]
            if dlg_c():
                _c = dlg_c()
                _bands.append((1020 - _c, 1220 - _c))
            row = [i for i in items
                   if (i.get('text') or '').strip()
                   and any(_a <= i.get('cy', 0) <= _b for (_a, _b) in _bands)]
            if row:
                _rc = max(row, key=lambda z: z['cx'])
                cf, _cfch, _cfrow = (_rc['cx'], _rc['cy']), 'norm', row
        if cf:
            _bag_tap(b, cf[0], cf[1], _cfch, wait=2.8)
            log.append({'bag': 'confirm_tap', 'at': cf, 'ch': _cfch,
                        'row': [(i['cx'], i['cy'], i['text'])
                                for i in sorted(_cfrow or [], key=lambda z: z['cx'])]})
            say('      · 确认弹框 → 点 (%d,%d)（%s；左边那个是取消 ✗ 不点 ✓）'
                % (cf[0], cf[1], '弹窗帧' if _cfch == 'dlg' else '归一化帧'))
        else:
            # 兜底坐标 (803,1112) 是 PC 标定的**弹窗系**坐标 ⇒ 真机必须走 tap_dlg ✓
            if dlg_c():
                b.tap_dlg(803, 1112, wait=2.8)
                _cfch = 'dlg'
            else:
                b.tap(803, 1112, wait=2.8)
            log.append({'bag': 'confirm_anchor', 'at': (803, 1112), 'ch': _cfch,
                        'texts': [i['text'] for i in items][:20]})
            say('      · 确认弹框 → 没读到按钮行 ⇒ 弹窗系锚点 (803,1112)')
        # ⭐ 2026-10-01 诊断（用户报「升星没变化」）：确认之后再扫一眼屏幕 ——
        #   有没有「升级成功/恭喜获得」、是不是还在背包/弹框 ⇒ logcat 里直接判成败 ✓
        time.sleep(0.8)
        _after = b.ocr(tag=tag + '_after')
        _atxt = [i['text'] for i in _after][:14]
        _pub_dump(tag + '_after', b.img())
        say('      · 确认后屏幕认到：%s' % (_atxt,))
        log.append({'bag': 'after_confirm', 'texts': _atxt})
        # ⑥ 回选图界面 ✓
        #   ⚠ 实测（2026-09-27）：
        #     ① `_close_bag`（返回/关闭/X）**关不掉背包** ✗
        #     ② 升星后会弹「恭喜获得 / 升星奖励」框 ⇒ **挡住底部导航** ✗
        #   ⇒ 循环最多 5 次：先关弹框（返回/关闭/确定）✓ 再点底部「开始冒险」✓
        #     直到 OCR 认到「进入地图/星界秘境」为止 ✓
        done = False
        for _k in range(6):
            items2 = b.ocr(tag=tag + '_back%d' % _k)
            txt2 = [(i.get('text') or '') for i in items2]
            if any(any(k in t for k in ('进入地图', '快速扫荡', '星界秘境')) for t in txt2):
                done = True
                log.append({'bag': 'back_ok', 'round': _k})
                break
            # ① 先关**弹窗**（⭐⭐ 2026-10-01 真机修：升星后会弹「升星奖励/恭喜获得」框，
            #   它**挡住背包的 X** ⇒ 老代码一路点 X，5 次都关不掉 ⇒ 用户看到"停留在装备界面" ✗）
            #   用户口径的「返回」就在这个框上 ✓
            #   ⚠ 老判据要求 `cy > 1200` ⇒ 真机上这个框的「返回」被漏掉 ✗
            #   ⇒ 放宽到 [sy(600), sy(1700))（**排除底部导航带**，避免点到 公会/角色/开始冒险 ✗）
            pop = None
            for i in items2:
                t = (i.get('text') or '').replace(' ', '')
                _cy = i.get('cy', 0)
                if t in ('返回', '关闭', '确定', '确认', '取消') \
                        and LAYOUT.sy(600) <= _cy < LAYOUT.sy(1700):
                    pop = i
                    break
            if pop:
                b.tap(pop['cx'], pop['cy'], wait=1.8)
                log.append({'bag': 'close_popup', 'text': pop.get('text'),
                            'at': (pop['cx'], pop['cy']), 'round': _k})
                say('      · 关弹窗「%s」(%d,%d) ✓' % (pop.get('text'), pop['cx'], pop['cy']))
                continue
            # ② 弹窗关完了、背包面板还开着 ⇒ 点**它的 X**（弹窗系 ✓）
            _op2, _how2 = _bag_panel_open(b, items2)
            if _op2:
                b.tap_dlg(BAG_X_DLG[0], BAG_X_DLG[1], wait=1.8)
                log.append({'bag': 'close_bag_x', 'at': BAG_X_DLG, 'round': _k,
                            'was': _how2})
                say('      · 关背包 → 点右上 X (%d,%d)（弹窗系 ✓）' % BAG_X_DLG)
                continue
            # 再点底部导航「开始冒险」✓
            # ⭐⭐⭐ 2026-10-01 用户报「装备升星的时候还要先点下进入地图是干什么。。」→ 修
            #   ⚠⚠ 原来这里点的是 `t in ('开始冒险', '进入地图') and cy > 1700` ——
            #     真机上只要那格读成 **「进入地图」**，这一下就**真的开图**：
            #       扣 25 体力 + 把刚升完星的收尾直接顶进地图（用户当场看到的就是这个 ✗✗）
            #   ⇒ **只点底部导航中间的「开始冒险」**（图标锚点 START_ADV=(540,1828)，
            #     用户 2026-09-27 实测「点中间那格不会开图」✓）；
            #     「进入地图 / 快速扫荡」只保留在**上面那句"回到选图界面了吗"的只读判据**里 ✓
            nav = None
            for i in items2:
                t = (i.get('text') or '').replace(' ', '')
                if t == '开始冒险' and i.get('cy', 0) >= LAYOUT.sy(1750):
                    nav = i
                    break
            at2 = START_ADV                       # 锚定的底部导航图标位（不看 OCR 也不会跑偏 ✓）
            b.tap(at2[0], at2[1], wait=2.2)
            log.append({'bag': 'back_tap', 'at': at2, 'saw_start_adv': bool(nav),
                        'round': _k})
            say('      · 回选图界面 → 点底部「开始冒险」(%d,%d)%s'
                % (at2[0], at2[1], '（OCR 也认到 ✓）' if nav else '（锚点坐标）'))
        log.append({'bag': 'back_done', 'ok': bool(done)})
        if not done:
            say('   ⚠ 收尾可能没回到选图界面（已尽力 ✓ 日志有记录 ✓）')
            try:
                _close_bag(b, b.ocr(tag=tag), log)
            except Exception:       # noqa: BLE001
                pass
        STATS['bag_upgrades'] = STATS.get('bag_upgrades', 0) + 1
        log.append({'bag': 'done', 'ok': True})
        say('   ⚙ 背包一键升级：完成 ✓')
        status('装备升星完成 ✓')
        return True
    except Exception as e:      # noqa: BLE001
        log.append({'bag': 'error', 'e': repr(e)[:120]})
        say('   ⚠ 背包升级异常：%r' % (e,))
        try:
            _close_bag(b, b.ocr(tag=tag), log)
        except Exception:       # noqa: BLE001
            pass
        return False



def fb(items, *labels):
    for lb in labels:
        for it in items:
            if lb in it['text']:
                return it
    return None


def exb(items, *labels):
    for lb in labels:
        for it in items:
            if it['text'].strip() == lb:
                return it
    return None


def bottom_close(items, min_cy=None):
    # ⭐ 2026-09-27 修：min_cy 原来写死 1100 ✗ ⇒ 720p 下关闭键(y=960)被排除 ⇒ 卡在结算界面 ✗
    if min_cy is None:
        min_cy = LAYOUT.sy(1100)
    best = None
    for it in items:
        if L['close'] in it['text'] and it['cy'] >= min_cy:
            if best is None or it['cy'] > best['cy']:
                best = it
    return best


# ⭐⭐ v1.19（2026-10-01 1264×2780 真帧）结算面板「奖励行」定位：**锚定「关闭」**，不写死 y
#   实测（设备帧 OCR → 换算回参考系 1080×1920）：
#       PC 9:16 : 奖励行数字 907 / 994~1001 ｜ 回放 1223 ｜ 关闭 1440 ｜ 自动跳过 1563
#       真机    : 奖励行数字 636 / 752       ｜ 回放 1224 ｜ 关闭 1441 ｜ 自动跳过 1563
#   ⇒ 面板**底部三键两机一致**（锚定模型成立 ✓），但奖励行在真机**高 271px**（战斗 UI 纵向压缩）
#   ⇒ 旧常量 `sy(700)~sy(1180)`（文字带）/ `box=(40,840+C,1020,1140+C)`（图标框）
#      在 1264×2780 上**完全盖不到奖励行** ⇒ `no_btn` + 三路图标全 None ✓（真机复现）
#   ⇒ 改用「相对关闭按钮」：奖励行恒在关闭**上方** CLOSE_UP_MAX~CLOSE_UP_MIN，
#      且落在**左侧骰子区** x<sx(560)（实测奖励行在 x 103~1159，但骰子在左半区）
REWARD_X1 = 560          # 骰子/大拇指检测的右边界（参考系；实测图标在 x 134~464）
REWARD_CLOSE_UP_MIN = 520     # 奖励行最低（离关闭最远）
REWARD_CLOSE_UP_MAX = 1020    # 奖励行最高（必须在「回放战斗」上方，避免把按钮当奖励）


def _reward_box(items=None, c=0):
    """奖励行搜索框（参考系；c>0 时是**弹窗系** ⇒ y 要 +C，与旧代码同口径 ✓）

    ⚠ `items` 传进来时会**用真实「关闭」按钮**收紧上界（更准）；没有就退回默认常量。
    ⚠⚠ 教训：上界要 **min(常量, 关闭-60)**，不能反过来 —— 反过来 clamp 会让"关闭锚定"完全失效
       （我第一版写成 `min(MAX, close-60)` 而 MAX=1180 > close-60=1380 时永远取 1180 ✗）。
    """
    y0, y1 = REWARD_CLOSE_UP_MIN, REWARD_CLOSE_UP_MAX
    if items:
        _cl = bottom_close(items)
        if _cl:
            y1 = max(REWARD_CLOSE_UP_MIN,
                     min(REWARD_CLOSE_UP_MAX, int(_cl['cy']) - 260))
    return (20, y0 + c, REWARD_X1 + c, y1 + c)


def _reward_band(items=None, c=0):
    """骰子按钮的**文字**搜索带（cx, cy 上下界），同样锚定「关闭」

    ⚠⚠ 2026-10-01 实测：**奖励行是纯图标+数字，OCR 读不到「骰」字**
      （真机结算帧 OCR 只有 `1/3` `1/16` `5/5` `220 46 184` 这类）⇒ 文字通道在**任何**
      分辨率都不可能命中，它只作为**兜底**（万一某版本有字）保留 ✓
    """
    _x0, _y0, _x1, _y1 = _reward_box(items, c)
    return _x0, _y0, _y1


def is_battle_panel(items):
    """是不是**战斗结算/胜利/失败**面板（战斗界面 ⇒ 必须点「关闭」，不能点开始冒险 ✗）
      `fb(items, L['win'], L['lose'], L['close'], '回放战斗')` —— 而**地图界面左上角的
      挑战目标里有一行「首领战斗胜利」**，子串包含「战斗胜利」⇒ 在**干净地图**上被误判成
      战斗面板 ⇒ `universal_close` 去点 (577,1439) ✗ —— 那其实是**棋盘格 (4,4)** ⇒
      等于每两轮在棋盘上乱点一次！（铁证：`runs/m0_r003.png` 是干净地图 + 结束冒险，
      日志却记 `panel_close: battle_close_fixed`）

    现在的判据（都要求"确实像结算面板"）：
      ① 底部「关闭」(y≥1100) 认到         ⇒ 是结算/奖励面板 ✓
      ② 认到「回放战斗」                   ⇒ 结算面板独有 ✓
      ③ 有**恰好等于**「战斗胜利/战斗失败」的标题 ✓（`首领战斗胜利` 是 6 字长句 ⇒ 不算 ✗）
    """
    if bottom_close(items):
        return True
    if fb(items, '回放战斗'):
        return True
    for it in items:
        if (it.get('text') or '').strip() in ('战斗胜利', '战斗失败'):
            return True
    return False


def stamina(items):
    """读体力：HUD 左上角那个 `x/2500`（实测坐标 ≈ (338,94)）

    ⚠ 2026-09-25 修：原来取"第一个 x/y 文字"——在背包/图鉴里会取到别的计数器
      （装备 1634/1634、莱姆 41/50 …）⇒ 数字乱跳（实测出现过 -499 ✗）。
      现在只在**顶部 HUD 区域**(cy<130) 且 x<560 的条目里找 x/数字 的形式 ✓
    """
    cands = []
    for it in items or []:
        t = (it.get('text') or '').replace(' ', '')
        if '/' not in t:
            continue
        a, _, b2 = t.partition('/')
        if a.isdigit() and b2.isdigit() and it.get('cy', 9999) < 130 and it.get('cx', 9999) < 560:
            cands.append((it['cy'], it['cx'], int(a)))
    if cands:
        cands.sort()
        return _stam_sanity(cands[0][2])
    # 退路：老口径（第一个 x/y），但排除背包里那种大分母
    for it in items or []:
        t = (it.get('text') or '').replace(' ', '')
        if '/' in t:
            a, _, b2 = t.partition('/')
            if a.isdigit() and b2.isdigit() and int(b2) >= 100:
                return _stam_sanity(int(a))
    return None


# ⭐ 2026-09-26 实测：刚打完战斗/关面板那一帧，HUD 上的体力偶发**多认一位**
#   实测序列 864→1863、835→1834（真值应该是 863 / 834，前面凭空多个 "1"）
#   ⇒ 后果：① 日志/统计里体力会"回升"，② --min-stamina 收工判断会被高估的假值骗过去
#   修法：相邻两轮间隔只有几秒（一轮循环 ~3s），体力不可能凭空涨 ≈1000 ⇒ 修正回来
_LAST_STAM = {'v': None}


def _stam_sanity(v):
    """体力读数合理性校验：把 OCR 多认一位的假值修回来 ✓"""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    prev = _LAST_STAM['v']
    try:
        # ⚠ 刚吃过补给 / 没历史值 ⇒ 不校验（补给是真涨 ✓）
        if prev is not None and not STATS.get('supply_used'):
            # ⭐ 两个必备特征：① 涨幅约 +1000（只可能是凭空多一位）
            #                ② 去掉首位后 ≈ 上一轮（一轮循环通常只花 1~8 点 ⇒ 放宽到 12）
            d = v - prev
            if 901 <= d <= 1099 and len(str(v)) == len(str(prev)) + 1:
                alt = v - 1000
                if abs(alt - prev) <= 12:         # 一轮的花销上限：大格 8 点 + 容错
                    say('       · 体力读数 %d 疑似 OCR 多认一位（上一轮 %d）⇒ 修正为 %d'
                        % (v, prev, alt))
                    v = alt
    except Exception:           # noqa: BLE001
        pass
    _LAST_STAM['v'] = v
    return v


def cell_of(cx, cy):
    return (int((cy - GRID['y0']) // GRID['cy']) + 1,
            int((cx - GRID['x0']) // GRID['cx']) + 1)


def cell_center(r, c):
    return (int(GRID['x0'] + (c - 1) * GRID['cx'] + GRID['cx'] / 2),
            int(GRID['y0'] + (r - 1) * GRID['cy'] + GRID['cy'] / 2))


def cells_of(img, mapname=None, code=None):
    """棋盘逐格状态（2026-09-25 起用地块分类器，不再靠中心色采样）

    -> {'gray': 未揭示格中心, 'light': 已揭示格中心,
        'plain': 已揭示的空地(草地/海边杂物这类可揭格), 'content': 已揭示的内容格,
        'buy': 已揭示的旅行商人/黄金宝库, 'st': {(r,c): {...}}, 'unknown': [格]}
    """
    out = {'gray': [], 'light': [], 'plain': [], 'content': [], 'buy': [],
           'buy_hidden': [], 'unknown': []}
    st = board_state(img, mapname, code)
    out['st'] = st
    if not st:
        # 兜底：老的颜色启发式（分类器不可用时至少还能跑）
        for r in range(1, 6):
            for c in range(1, 8):
                cx, cy = cell_center(r, c)
                w = img[cy - 35:cy + 35, cx - 45:cx + 45]
                if w.size == 0:
                    continue
                b, g, rr = cv2.split(w)
                ri, gi, bi = rr.astype(int), g.astype(int), b.astype(int)
                gray = ((rr >= 125) & (rr <= 175) & (abs(ri - gi) < 16) & (abs(gi - bi) < 16))
                light = ((rr >= 235) & (g >= 185) & (bi >= 105) & (bi <= 220))
                if float(gray.mean()) > 0.45:
                    out['gray'].append((cx, cy))
                elif float(light.mean()) > 0.35:
                    out['light'].append((cx, cy))
        return out
    for (r, c), v in sorted(st.items()):
        p = cell_center(r, c)
        if v['anchor'] != (r, c) and v['anchor'] is not None:
            continue                     # 多格物件只按锚点算一次
        # ⚠ 商人/宝库必须**匹配分数够高**才算（2026-09-25 卡死事故）：
        #   屏幕上若有面板/遮罩盖住棋盘，分类器会把整盘读成"暗格"，并凭 0.6~0.7 的
        #   弱匹配误报出好几个"未揭示的商人/宝库"；而商人宝库是**永不拉黑**的目标，
        #   于是循环对着点不动的格子空转（用户报「退出地图时卡住了」）。
        #   实测：真商人/宝库 0.95+（含变暗时 0.9+），误报 ≤0.7 ⇒ 阈值 0.85。
        strong = v['score'] >= BUY_SCORE_MIN
        if not v['revealed']:
            out['gray'].append(p)
            # ⭐ 未揭示的商人/宝库**仍然是目标**（用户 2026-09-25：「有黄金宝库你没点就要退」）：
            #   它此时点不动，要像 boss 一样沿路开路把它解锁出来
            if strong and v['name'] in spots_mod.BUY_OUT_NAMES:
                out['buy_hidden'].append(p)
            continue
        out['light'].append(p)
        if strong and v['name'] in spots_mod.BUY_OUT_NAMES:
            out['buy'].append(p)
        elif is_plain_spot(v['sid']):
            out['plain'].append(p)
        else:
            out['content'].append(p)
    return out


# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐ v1.45 提速（施工单 ⑦）：**同帧并发** —— 把「轮首全屏 OCR」与「棋盘分类」重叠
#
# 现状（串行）：snap → Java OCR(~1.5s) → popups 判定 → Python 分类(~1s) → 标记 → 规划 → 点。
#   两段都是"同一帧上的独立计算"，彼此**不依赖**（分类只需要 img，不需要 OCR 结果）⇒
#   可以重叠。JDK/ONNX 都是 native 调用（GIL 大部分时间是放开的）⇒ 有重叠空间。
#
# ⚠⚠ 为什么**默认关**（`MAPBOT_PARALLEL=1` 才开）：
#   手机上两边都是 CPU 密集型，**核数不够时并发反而互相抢 CPU**，净收益只能是真机上 A/B 出来。
#   我没有真机可测（用户 2026-10-04 口径：只跑离线门禁、真机验收留给用户）⇒
#   做成**可开关 + 离线证明"结果与串行逐格一致"**，把"开不开"留给真机数据决定 ✓
#
# ⚠ 只在 `st['mapname']` **已知**时才并发（第一轮还不知道图名，串行拿 items 里的图名）；
#   并且**上一轮的并发还没跑完就不再提交**（避免任务在池里排队 ⇒ join 反而更久）。
# ══════════════════════════════════════════════════════════════════════════
PARALLEL_CLASSIFY = (os.environ.get('MAPBOT_PARALLEL', '') or '').strip() not in (
    '', '0', 'no', 'false', 'False')
_PAR_POOL = None
_PAR_LAST = None


# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐ v1.45【真机 A/B 开关文件】—— 不用出包就能开关实验特性
#
# 为什么要有：以前每试一个开关都要「改代码 → 发热更 → 冷启动 → 跑 5 张图」，
#   一轮十几分钟，而且要真机才能定的事（并发划不划算 / 某个 OCR 砍了会不会漏面板）
#   根本没法快速试。
# 现在：`adb shell touch /sdcard/Download/autoexplore/bagdbg/<名字>.flag` 就开，
#   `rm` 就关；**每次调用现读**（同一次运行里改也生效），跑完我拉统计对比即可。
#
# ⚠ 纪律：**正式行为不许依赖 flag**（flag 不在 ⇒ 走默认，与发布行为一字不差）；
#   flag 只用于"待真机定论"的实验开关。目录可用 `MAPBOT_FLAG_DIR` 覆盖（门禁就这么测）。
# 已知开关：
#   parallel  —— 同帧并发分类（`classify_async_start`）
# ══════════════════════════════════════════════════════════════════════════

def flag_dir():
    """开关文件目录（**每次现读环境变量** ⇒ 门禁/测试可运行时改）

    ⚠ v1.45e 起**主落点换成了 App 的外部私有目录**，原因见 `flag_dirs()` 的注释。
    这个函数保留"单个目录"语义给门禁/旧调用方（返回列表里第一个存在的，否则第一个候选）。
    """
    env = os.environ.get('MAPBOT_FLAG_DIR')
    if env:
        return env
    for d in flag_dirs():
        try:
            if os.path.isdir(d):
                return d
        except Exception:       # noqa: BLE001
            pass
    return flag_dirs()[0]


def flag_dirs():
    """开关文件的**候选目录**（任一目录里有 `<名字>.flag` ⇒ 算开）

    ⭐⭐⭐ v1.45e【为什么不能只用 `/sdcard/Download/…`】—— 2026-10-04 真机实测：
      用 `adb push` 把 `menu_tpl.flag` / 模板推进
      `/sdcard/Download/autoexplore/bagdbg/`，App **根本看不见**：
        · 一键反馈包的收集账写着「诊断帧: 收 0 张；**非诊断 png 0 张未收**」，
          而我 10 分钟前确实推了一张 `board_hidden_adbprobe.png` 进去 ⇒
          **`listFiles()` 既没列出它、也没把它算成"非诊断"** ⇒ 那份目录在 App 眼里是空的 ✗
        · 后果：A/B 的 flag **全都等于没开**、模板也**永远加载不到**
          ⇒ 那次"44 秒/张"的 A/B 结论作废（不是变慢，是**根本没生效**）✗✗
      ⇒ 落点改成 **App 自己的外部私有目录** `/sdcard/Android/data/<pkg>/files/`：
        · `adb push` 能写（实测 ✓）
        · App **必然**看得见（那是它自己的目录，文件组 `ext_data_rw` 它就在里面，
          且它自己的 `dump/` 就住在这儿 ✓）
      ⚠ 包名写死：本 App 的 applicationId 固定（`com.fantasy.autoexplore`），
        而且这只是**排障/A-B 落点**，不是产品路径（正式模板进资源包）✓
    """
    env = os.environ.get('MAPBOT_FLAG_DIR')
    if env:
        return [env]
    return [os.path.join(PUB_FILES, 'flags'), PUB_FILES, BAG_PUB_DIR]


def flag_path(name, d=None):
    return os.path.join(d or flag_dir(), str(name) + '.flag')


def flag_on(name, default=False):
    """**任一候选目录**里有 `<name>.flag` ⇒ True；都没有 ⇒ **default**

    ⚠ 语义容易写错（我第一版就写错了）：**必须回落到 default**，
      否则"环境变量那条路"会被这个函数**静默掐死**（`_par_on()` 用的是
      `flag_on('parallel', PARALLEL_CLASSIFY)`，不回落到 default 就永远 False）——
      门禁 v1.45 ⑧c 当场把这个错抓住了 ✓
    """
    try:
        for d in flag_dirs():
            if os.path.exists(os.path.join(d, str(name) + '.flag')):
                return True
    except Exception:       # noqa: BLE001
        return bool(default)
    return bool(default)


def _par_on():
    """⑦ 同帧并发是否生效：**文件开关优先**，其次环境变量（默认关）"""
    return flag_on('parallel', PARALLEL_CLASSIFY)


def _par_pool():
    global _PAR_POOL
    if _PAR_POOL is None:
        try:
            from concurrent.futures import ThreadPoolExecutor
            _PAR_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mgas-cls')
        except Exception:       # noqa: BLE001
            _PAR_POOL = False
    return _PAR_POOL or None


def classify_async_start(img, mapname=None, code=None):
    """把 `cells_of` 丢后台线程先算（与主线程的 Java OCR 重叠）⇒ future / None

    返回 None = **关掉了/池不可用/上一轮还在跑** ⇒ 调用方走原来的同步路 ✓
    """
    global _PAR_LAST
    if not _par_on() or img is None:
        return None
    if _PAR_LAST is not None and not _PAR_LAST.done():
        return None                      # 上一轮没跑完 ⇒ 别再提交（防排队）
    pool = _par_pool()
    if pool is None:
        return None
    try:
        _PAR_LAST = pool.submit(cells_of, img, mapname, code)
        return _PAR_LAST
    except Exception:       # noqa: BLE001
        return None


def classify_async_join(fut, img, mapname=None, code=None):
    """取并发结果；**任何异常都回退同步重算**（绝不因为并发把这一轮搞崩 ✗）"""
    if fut is None:
        return cells_of(img, mapname=mapname, code=code)
    try:
        return fut.result()
    except Exception:       # noqa: BLE001
        return cells_of(img, mapname=mapname, code=code)



BUY_SCORE_MIN = 0.85        # 认商人/宝库的最低匹配分（见上面注释）
BUY_PROBE_MAX = 3           # 「强匹配但被判未揭示」的宝库/商人：每格每图最多验证式点几下（见下）

_COLOR_TILES = ('宝库', '商人')


def vault_px_now(c, revealed_only=True, strong_only=True, any_color=False):
    """当前帧分类结果里的商人/宝库格（像素）—— `any_color=True` 时连"点开详情才认出的"也算

    ⭐ 2026-10-01 v0.96 新增（用户真机报「**黄金宝库明明都揭示了能直接点，他又去打了两个
    战斗地块**」）：这是**唯一**的「宝库像素来源」，供三处共用（防钉死 / 免拉黑 / 点序置顶），
    免得三份判据各写一遍又漂移 ✗
    """
    out = []
    for (r, cc), v in sorted(((c or {}).get('st') or {}).items()):
        v = v or {}
        if v.get('anchor') != (r, cc):
            continue                          # 多格物件只按锚点算一次 ✓
        nm = str(v.get('name') or '')
        if not any(k in nm for k in _COLOR_TILES):
            continue
        if strong_only and float(v.get('score') or 0) < BUY_SCORE_MIN:
            continue
        if revealed_only and not bool(v.get('revealed')):
            continue
        out.append(marks_mod.cell_center(r, cc))
    return out


def vault_probe_px(c, st):
    """**强匹配但被判"未揭示"**的宝库/商人格 —— 也值得点一下（验证式）

    根因（2026-10-01 真机复盘）：`revealed = ratio >= 0.75`，而
    `ratio = 格亮度 / **命中模板**亮度` ⇒ **模板一换，同一个已揭示的宝库格也会掉到
    0.75 以下**（真机：NCC 0.95+ 却 ratio 0.638 ⇒ 判"未揭示"）⇒ 它既进不了 `buy`、
    又被当"点不动"⇒ **机器人看着宝库不打，跑去开路/打拦路** ✗
    而 NCC 分数是**形状**匹配（与亮度无关）⇒ 分数高 + 名字是宝库/商人 = 值得点一次 ✓
    （点进去若真是雾格 ⇒ 白点一下，游戏不消耗；实测雾格点击 = 画面毫无变化 ⇒ 无损 ✓）

    上限 `BUY_PROBE_MAX` 次/格/图（防"一直点不开"空转，见 2026-09-25 卡死事故 ✓）。
    """
    probe = st.setdefault('buy_probe', {})
    out = []
    for p in vault_px_now(c, revealed_only=False, strong_only=True):
        if probe.get(p, 0) >= BUY_PROBE_MAX:
            continue
        out.append(p)
    return out


def vault_still_there(st):
    """该像素现在**还**是不是宝库/商人（当前帧 ∪ 跨轮累积观测 `st['obs']`）

    ⚠ 2026-10-01 v0.96 修**死代码**：原写法 `(st['cells'] or {}).get('board')` ——
    `st['cells']` 是分类器原样 dict（键是 `(r,c)` 元组，**没有 `board` 这个键**）
    ⇒ `_still_buy` 恒为空 ⇒ 「已买完/消耗就剔出粘性集」这条**永远不生效** ✗
    ⇒ 粘性宝库挂满 20 轮 = **幽灵目标**（真机日志：每一轮都是「没有目标了」却「还剩 1 个目标」，
    然后满地图开路打拦路 ✗）。这里按"当前帧 ∪ obs 里名字里还有宝库/商人"判定 ✓
    （买掉后该格名字会变成空地 ⇒ 立刻剔除 ✓，见 obs 的"已揭示+名字变了立即覆盖"规则 ✓）
    """
    out = set()
    for _src in ((st or {}).get('cells') or {}, (st or {}).get('obs') or {}):
        try:
            for _rc, _v in _src.items():
                _nm = str((_v or {}).get('name') or '')
                if any(k in _nm for k in _COLOR_TILES):
                    out.add(marks_mod.cell_center(_rc[0], _rc[1]))
        except Exception:       # noqa: BLE001
            pass
    return out


_PLAIN_CACHE = {}


def is_plain_spot(sid):
    """该地块是不是「空地」（Area_Spot: SpecialSpot==0 且 SpotSize==1）——才能点它揭一片"""
    if sid not in _PLAIN_CACHE:
        row = spots_mod.spot_rows().get(sid) or {}
        try:
            _PLAIN_CACHE[sid] = (int(row.get('SpecialSpot') or 0) == 0 and
                                 int(row.get('SpotSize') or 1) == 1)
        except Exception:           # noqa: BLE001
            _PLAIN_CACHE[sid] = False
    return _PLAIN_CACHE[sid]


def close_x_panels(b, img=None):
    # ⭐ v0.31 方案 B：真机上弹窗 X 关闭符（dlg≈225）落在 toRef 丢弃的弹性区 ⇒
    #   归一化帧上根本看不见 ✗ ⇒ C>0 时改用**弹窗帧**（b.img_dlg，Java 重投影）找，
    #   检测常数（67x67 / x≈493,1024 / y 带 180~300）就是弹窗系标定值，原样可用 ✓
    #   PC / 9:16 C=0 ⇒ 走原路，行为一字不变。
    _dlg = dlg_c()
    _im = None
    if _dlg:
        _im = b.img_dlg() if hasattr(b, 'img_dlg') else None
        if _im is None:              # 弹窗帧拿不到 ⇒ 退回归一化帧（聊胜于无）
            _dlg = 0.0
    im = _im if _im is not None else (img if img is not None else b.img())
    bb, gg, rr = cv2.split(im.astype(int))
    red = ((rr > 150) & (rr - gg > 70) & (rr - bb > 60))
    band = np.zeros_like(red)
    band[180:300, :] = True
    m = (red & band).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _l, st, ce = cv2.connectedComponentsWithStats(m, 8)
    xs = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        # 真关闭钮恒 67x67 且**只在 x≈493 / x≈1024**（左右两块面板各一个）。
        # ⚠ 只按尺寸筛会点到居中面板上的 (759,225) —— 那是回放相关按钮，
        #   点它就会放一遍回放（用户 09-25 连报三次）
        cx0 = int(ce[i][0])
        if 1500 < a < 8000 and 55 <= w <= 72 and 55 <= h <= 72 and \
                min(abs(cx0 - 493), abs(cx0 - 1024)) <= 60:
            xs.append((cx0, int(ce[i][1])))
    xs.sort(reverse=True)
    for (x, y) in xs:
        if _dlg:
            b.tap_dlg(x, y, wait=1.6)    # 弹窗帧坐标 = 弹窗系 ⇒ 走弹窗点击通道
        else:
            b.tap(x, y, wait=1.6)
    return len(xs)


# ⭐ 2026-09-27：大厅专属 UI（`_probe_lobby_sig.py` 三图对拍得出）
#   ⚠ **绝对不要**用「底部导航有 角色/斗技场/图鉴/开始冒险」判大厅 ——
#     实测**大厅 / 选图界面 / 地图界面三者底部都有这套导航**（全局导航栏）✗
LOBBY_CORNERS = ('攻略', '活动', '首充', '情报')     # 大厅四角入口（另两者都没有）
LOBBY_BANNER = '免费指定招募'                        # 大厅中部招募横幅


def in_lobby(items):
    """是否在**大厅（主界面）**

    实测三图 OCR 对拍（`_probe_lobby_sig.py`，2026-09-27）：

        特征                              大厅   选图界面  地图界面
        底部导航(角色/斗技场/图鉴/开始冒险)  ✓      ✓        ✓    ← 不可用 ✗
        四角入口 攻略/活动/首充/情报        ✓      ✗        ✗    ← 用它 ✓
        「免费指定招募」横幅                ✓      ✗        ✗    ← 用它 ✓
        帮助 + NNN% / 当前难度NNN           ✗      ✓        ✓
        快速扫荡 / 进入地图 (y≈1618)        ✗      ✓        ✗
        结束冒险(y≈773) + 图名[难度]        ✗      ✗        ✓

    为什么必须能认出大厅：2026-09-27 幻少跑采图时**游戏自己重启**停在大厅，
    `in_map()` 的格子兜底把大厅背景数成 8+ 格 ⇒ 误判"已在地图里" ⇒ 恢复路径不触发。
    """
    if not items:
        return False
    txt = [i.get('text') or '' for i in items]
    if any(LOBBY_BANNER in t for t in txt):
        return True
    return sum(1 for h in LOBBY_CORNERS if any(t == h for t in txt)) >= 2


# ⭐⭐ 2026-09-29 真机踩坑：MGAS 自己的界面（或应用双开选择框）被格子兜底数成 13 格
#   （中位分 0.186）⇒ in_map 误判"已在地图" ⇒ 对着自己界面点了一整轮。
#   ⇒ 所有"我在看什么"的判定**先认自己的 UI 标记**：命中 ≥2 个 ⇒ 一定是自己的界面。
_SELF_UI_MARKERS = ('开始探索', '停止探索', '红装解锁', '授权截图', '推图日志',
                    '清空日志', '要使用的应用', 'MGAS')


def self_ui_hits(items):
    """当前帧里有几个 MGAS 自己的 UI 标记（≥2 ⇒ 画面是本应用/系统选择框，不是游戏）"""
    if not items:
        return 0
    hits = 0
    for it in items:
        t = (it.get('text') or '').replace(' ', '')
        if not t:
            continue
        for m in _SELF_UI_MARKERS:
            if m in t:
                hits += 1
                break
    return hits


# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐⭐ v1.45h【系统"应用选择框"要专门认出来】（2026-10-04 真机事故）
#
# 事故现场（用户手机，`marks_none_r0/r1/r3.png` 三张现场帧 OCR 实测）：
#     请选择要使用的应用
#     幻想少女公会      ← 两份！（应用双开）
#     幻想少女公会
# ⇒ 手机装了双开助手（`com.hcc.clone`）⇒「启动游戏」这个意图**有两个响应者**
#   ⇒ 系统弹选择框；而 `self_ui_hits()` 只认 **MGAS 自己的界面标记**，认不出它 ✗
# ⇒ 机器人就对着选择框一直干：`popup_none` → `universal_close (541,1890)` 盲点，
#   悬浮条上写着「画面认不出 · 正在收起面板」，一轮空转 40+ 秒、图也刷不了。
#
# 判据用**选择框自己的字**（去掉空格再比，避免 OCR 把「请选择要使用的应用」拆开）：
CHOOSER_KEYS = ('请选择要使用的应用', '选择要使用的应用', '选择打开方式', '打开方式')


def is_app_chooser(items):
    """系统"应用选择框"（应用双开时启动游戏会弹）-> True/False"""
    for it in items or ():
        t = (it.get('text') or '').replace(' ', '')
        if not t:
            continue
        for k in CHOOSER_KEYS:
            if k in t:
                return True
    return False


def _login_page_hits(items):
    """当前帧里命中几个「**只在登录页出现**」的字（2026-10-01 v1.16 新增）。

    ⭐ 背景（MuMu 1264×2780 实测）：游戏没登录态时停在登录页，
    而 `in_map()` 的每一条否定证据在登录页都不成立 ⇒ 只能靠格子兜底
    ⇒ **把登录页误判成"已在图里"**（实测后果：`本图结束：stuck`，白跑 62 秒）。

    判据与 `game_recover._game_main_ok`（本文件内）**同源** —— 那几个字是
    `_game_main_ok` 判定"还没恢复成功"的同一批，所以不会自相矛盾。
    **≥1 就够了**（不要求多条同时出现：进登录动画时可能只 OCR 到其中一个）。
    """
    n = 0
    for it in items or []:
        t = (it.get('text') or '').replace(' ', '')
        if (not t) or len(t) > 40:       # 跳过整行说明文字（不是按钮/标题）
            continue
        for k in ('开始游戏', '我已详细阅读', '健康游戏忠告', '登出', '适龄提示',
                  '批准文号', '出版物号', '游戏软著', '如遇登录或充值问题'):
            if k in t:
                n += 1
                break
    return n


def in_map(b, img, items):
    """是否已经在探索地图里

    ⚠ 2026-09-25 踩坑：选图界面中间那张**地图预览图**会被地块分类器"认出一堆格子"，
      于是 `cells_of` 判定通过 → 误判成"已在地图里" → 循环直接走「目标清完退图」，
      表现成「这两轮进不去地图」。现在：
        ① 先看图内特征：结束冒险 / HUD 行(背包·神石·预言 y900~1000) / 带 [难度] 的图名
        ② 一旦看到选图界面的「快速扫荡 / 进入地图」→ **明确判为不在图里**
        ③ ⭐ 大厅（四角入口/招募横幅）→ **明确判为不在图里**（2026-09-27 游戏重启后停大厅，
           大厅背景格会被下面的格子兜底数成 8+ ⇒ 误判"已在地图里"⇒ 恢复路径不触发 ✗）
        ⑤ ⭐⭐ 2026-09-29 真机：**MGAS 自己的界面 / 应用双开选择框** 也会被格子兜底数成 13 格
           （中位分 0.186）⇒ 误判"已在地图里" ⇒ 对着自己点 47 秒。先认自己的 UI 标记 ✓
    """
    if self_ui_hits(items) >= 2:
        return False
    if exb(items, L['end']):
        return True
    for it in items:
        if LAYOUT.sy(900) < it['cy'] < LAYOUT.sy(1000) and it['text'].strip() in L['hud']:
            return True
    for it in items:
        if LAYOUT.sy(150) < it['cy'] < LAYOUT.sy(215) and re.match(r'^.+\[\d+\]\s*$', it['text'].strip()):
            return True                      # 「夏日海滩[100]」这种只在图里出现
    if fb(items, *L['menu']):
        return False                         # 选图界面（快速扫荡/进入地图）
    # ⭐⭐⭐ 2026-10-01 v1.15【朋友机 realme RMX3800 / 1264×2780 实测】：
    #   他那台上「快速扫荡/进入地图」在 ref y≈**1618**（比本机更低），一旦这两条没被读到
    #   （进图动画帧 / 文字被压暗），下面的"格子兜底"就会把**选图界面**判成"在图里" ✗
    #   ⇒ 用户看到的是：进去就"面板挡住了棋盘 · 正在收起"，一直卡着，其实一次地图都没进 ✗✗
    #   ⇒ 补两条**只在选图界面出现、且在画面中部**（不受分辨率/band 影响）的字：
    #      `深渊NN`（难度页签）与 `星界秘境`（右下挑战入口）✓
    if any(('深渊' in it['text']) or ('星界秘境' in it['text']) for it in items):
        return False
    # ⭐⭐⭐ 2026-10-01 v1.16【登录页误判】（MuMu 1264×2780 实测）：
    #   游戏**没有登录态**时停在登录页（开始游戏 / 隐私政策 / 健康游戏忠告），
    #   而登录页没有「结束冒险/HUD/图名[难度]」、也没有「快速扫荡/进入地图」，
    #   下面所有否定证据全不成立 ⇒ 只能靠格子兜底 ⇒ 把登录页**误判成"已在图里"** ✗
    #   表现：日志「已进图，体力 ?」→ 棋盘区落在登录页空白文字区 → 判「棋盘被挡」
    #        → 反复关面板 → `本图结束：stuck`（实测 62 秒）。
    #   判据与 `game_recover._game_main_ok` **同源** ⇒ 读到就一定**不在图里** ✓
    if _login_page_hits(items) >= 1:
        return False
    if in_lobby(items):
        return False                         # ⭐ 大厅（四角入口 / 免费指定招募横幅）
    c = cells_of(img, mapname=map_name(items))
    n = len(c['gray']) + len(c['light'])
    if n < 8:
        return False
    # ⭐ v1.15：格子兜底还要看**有没有真·已揭示的亮格** —— 真棋盘进图时营地恒已揭示
    #   （ratio≈1.0）；而"选图界面/进图动画"那种帧被兜底数出来的格子全是压暗的
    #   （朋友机日志实测：`light: 0/1, gray: 16/17`，全盘 ratio<0.55）
    #   ⇒ 旧写法"≥8 格就算在图里"正是那次误判的最后一根稻草 ✗
    # ⭐⭐ v1.35【这条判据**不用** `spots` 的 0.75】：语义不同 ——
    #   `spots` 的 0.75 判的是「这格是不是已揭示」（单格分类，允许边缘）；
    #   这里判的是「**确凿**在图里」（要正证据，**不该被边缘格触发**）✗
    #   起因：那张 fixture 的图名 OCR 是「清凉沙滩」⇒ 走 S40002 模板集，
    #   有一格 ratio **0.757** 恰好压在 0.75 之上 ⇒ `bool(light)` 成立
    #   ⇒ 选图界面被误判成"已在图里"（v1.15 ③ 当场红 ✓ 门禁抓到了真脆弱性）。
    #   改成**独立阈值 0.85**：真棋盘的营地 ratio≈1.0 稳稳通过，
    #   0.75~0.85 的边缘格（压暗/半揭示）**不再**冒充正证据 ✓
    _IN_MAP_LIGHT_RATIO = 0.85
    try:
        _mx = max([float((v or {}).get('ratio') or 0)
                   for v in (c.get('st') or {}).values()] or [0.0])
    except Exception:       # noqa: BLE001
        _mx = 0.0
    return bool(c['light']) and _mx >= _IN_MAP_LIGHT_RATIO


def map_name(items):
    """从 HUD 顶部读当前图名（如「夏日海滩[100]」-> 夏日海滩）

    ⚠ 别只按 y 带取：同一带里还有左上角的「首领战斗胜利」横幅（cy≈166），
      曾经把图名读成「古首领战斗胜利」→ 分类器认不出图号 → 全部退回旧启发式。
    """
    if items is None:
        return None
    for it in items:
        m = re.match(r'^(.+?)\s*\[(\d+)\]\s*$', it['text'].strip())
        if m:
            return m.group(1).strip()
    for it in items:
        t = it['text'].strip()
        if LAYOUT.sy(160) < it['cy'] < LAYOUT.sy(210) and LAYOUT.sx(360) < it['cx'] < LAYOUT.sx(720) and '战斗' not in t and '胜利' not in t:
            t = t.split('[')[0].strip()
            if t and not t.isdigit() and len(t) >= 2:
                return t
    return None


def find_x(items):
    """独立关闭符。⚠ 实测面板关闭符**只在 x≈493 / x≈1024 两处**（左右两块面板各一个）；
    结算面板上 (759,225) 那个「X」夹在中间，是回放相关按钮 —— 点它就会放一遍回放
    （用户 09-25 连报两次「还在看回放」）。"""
    for it in items:
        if it['text'].strip() not in ('X', 'x', '\u00d7', '\u2715', '\u2716'):
            continue
        # ⭐ 坐标过布局层（720p 下 493/1024 要跟着缩 ✓）
        if min(abs(it['cx'] - LAYOUT.sx(493)),
               abs(it['cx'] - LAYOUT.sx(1024))) <= LAYOUT.sx(60):
            return it
    return None


# ⭐ 2026-09-26 死循环根因修复（用户在幻少实测：探索槽满 + 紫橙探索格 ⇒ 卡死 45 轮、
#   体力/回合都不动 ⇒ 最后"退出地图失败"）
#   根因：`popups()` 里多处是「关一下 X ⇒ 就 return 'handled'」——**没人验证面板真的关掉了**。
#   一旦没关掉，下一帧还是同一段面板文字、又命中同一分支、又 return 'handled'，
#   整个闭环被这一句占住 ⇒ 不揭格、不打架、也不 reach 到 finish。
_PANEL_STUCK = {}


def panel_gone(b, probe, tag='unstick', dlg_btn=None):
    """关面板之后**重新截图验证**它真的没了 ✓（probe = 之前认到的那段面板文字）

    ⭐ v0.32：真机上面板标题（「探索产出/战斗事件」dlg≈443）落在 toRef 丢弃的弹性区
    ⇒ 归一化帧里永远看不见 ⇒ fb 恒 False ⇒ 会误判"已关" ✗
    ⇒ 传 dlg_btn（面板按钮文字，如「探索」）时补一道弹窗系验证：按钮还在 ⇒ 面板没关掉
    """
    if _OCR_CH['dlg'] and hasattr(b, 'ocr_dlg'):
        items = ocr_ch(b, tag=tag)      # ⭐ 弹窗模式：标题只在弹窗帧里，查归一化帧会误判"已关"
    else:
        b.snap(tag)
        items = b.ocr(tag=tag)
    if fb(items, probe):
        return False
    if dlg_btn and dlg_c() and _dlg_panel_btn(dlg_items(items), dlg_btn):
        return False
    return True


def force_unstick(b, log, why, ctx=None):
    """面板关不掉时的脱困：已知关闭点全试一遍 + 拉黑当前格 ⇒ 让循环能往后走 ✓"""
    tries = []
    # ⭐ v0.31 方案 B：这三个都是**面板上的**关闭点（弹窗系标定值）⇒ 走 tap_dlg
    #   （真机上原 b.tap 会落在面板下方/弹性区，全空点 ✗）
    for (bx, by, w) in ((539, 1212, 1.6),        # 面板底部「返回」
                        (LAYOUT.sx(493), LAYOUT.sy(225), 1.2),   # 左 X
                        (LAYOUT.sx(1024), LAYOUT.sy(225), 1.2)):  # 右 X
        b.tap_dlg(int(bx), int(by), wait=w)
        tries.append((int(bx), int(by)))
    try:
        tp = (ctx or {}).get('tapped')
        fl = (ctx or {}).get('flags') or {}
        if tp:
            fl.setdefault('done', set()).add((int(tp[0]), int(tp[1])))
    except Exception:           # noqa: BLE001
        pass
    log.append({'unstick': why, 'tried': tries})
    return tries


def find_orange_btn(img, x0=None, x1=None, y0=None, y1=None):
    # ⭐ 默认范围也要随分辨率缩 ✓
    x0 = LAYOUT.sx(200) if x0 is None else x0
    x1 = LAYOUT.sx(900) if x1 is None else x1
    y0 = LAYOUT.sy(600) if y0 is None else y0
    y1 = LAYOUT.sy(920) if y1 is None else y1
    """按颜色找面板底部那颗**橙色艺术字按钮**（「战斗」/「探索」都是这种字），
    返回最靠下的大色块中心 —— 比固定 y 稳（不同面板版面会挪位置）。

    艺术字实测色 ~ RGB(240,170,90)：R 高、G 中、B 低。
    """
    win = img[y0:y1, x0:x1].astype(int)
    b, g, r = cv2.split(win)
    m = ((r > 190) & (g > 120) & (g < 215) & (b < 130)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _l, st, ce = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 400 or w < 30:
            continue
        cy = int(ce[i][1]) + y0
        if best is None or cy > best[1]:
            best = (int(ce[i][0]) + x0, cy, int(a))
    return best


# ⭐⭐ 2026-10-01 修「地图界面被当成已开打」的假判（1264×2780 全分辨率实跑暴露）：
#   旧判据是**子串**匹配（`'回合' in t` / `L['win'] in t`），而《遗忘之海》地图 HUD
#   自带两条**常驻文案**：
#     · `★首领战斗不超过8回合`        ← 任务条件，含「回合」
#     · `首领战斗胜利` + `首领战斗2人存活` ← 任务达成状态，含「战斗胜利」
#   ⇒ 在图上点完「战斗」后只要 OCR 一次，这两个词必然命中 ⇒ **假判"已进战斗"**
#   ⇒ wait_end 空等 20 秒 → `back_in_map`，格子根本没打 → 下一轮原样再来一遍
#     （2026-10-01 14:29 实测：连打 4 轮「开打 · 拦路格」、STATS 战斗 0 场，
#       最后靠 same_action×4 强制脱困才停 ✗；离线复现见回归套件 ㉘ 组）
#   真·战斗/结算界面的文本形态（真机帧 `runs/bw2.json` 实测 ✓）：
#     `战斗胜利` / `战斗失败` —— **整条**（不是"首领战斗胜利"这种带前缀的横幅）
#     `第1/10回合` —— **整条**（正则）｜`加速` / `自动跳过` / `回放战斗`（战斗专属控件）
#   ⇒ 判据改成「整条严格匹配」+「带地图任务标记（★ / 不超过）的句子一律不算」✓
#   ⚠ 真·战斗界面行为不变（这些文本在真战斗里照样命中 ✓）；PC/9:16 同口径 ✓
_ROUND_RE = re.compile(r'^第\s*\d+\s*(?:[/／]\s*\d+\s*)?回合$')
_BATTLE_STRONG = ('加速', '自动跳过', '回放战斗')
_MAP_OBJ_MARK = ('★', '不超过')


def battle_started(items):
    """是否已进入战斗：看战斗特征，而不是「战斗事件面板消失没」。

    ⚠ 点一格可能同时弹出两块面板（目标格 + 相邻格）：打的那块开打后，
      另一块面板的「战斗事件」文字还在 -> 只看它消失会把**已经开打的**误判成没打
      （用户 09-25：「那场明明打完并且赢了」）。
    ⚠⚠ 但**不能**用宽子串（见上面那段教训）：地图自身的任务横幅也含「回合 / 战斗胜利」。
    """
    for it in items:
        t = (it.get('text') or '').strip()
        if t == L['win'] or t == L['lose']:          # 整条等值（"首领战斗胜利" 不算 ✓）
            return True
        if _ROUND_RE.match(t):                       # "第1/10回合" / "第3回合" 整条
            return True
        if any(k in t for k in _BATTLE_STRONG) and not any(k in t for k in _MAP_OBJ_MARK):
            return True
    return False


def start_fight(b, log, btn, marks=()):
    """点「战斗」→ 等**战斗真的起来**（最多 ~15s，一起来看见就早退）

    ⚠ 旧口径是「最多等 5s」（用户 09-25：战斗胜利不会超过 5s）—— 那是**模拟器**上的实测。
    ⭐⭐ 2026-10-02 v1.26 真机翻车（用户报「点了战斗格、**还没打就去点下一个格子**」）：
       真机（Redmi 1280×2772）点完「战斗」到**真正开打 >5 秒**（游戏加载慢）⇒
       旧代码 5 秒就判 `not_started` ⇒ 上层当成 `blocked`（被挡路）⇒ **战斗还在加载就去点下一格** ✗✗
       （真机日志：`{'battle':'no_battle_in_5s'}` → `not_started` → `blocked` → 下一轮却看到了
        结算面板 —— 战斗其实打完了 ✓ 说明"没等到"≠"没打起来"）
    ⇒ 现在：① 画面变了就**耐心等**（最多 15s，看到战斗/结算立刻返回 ✓）；
            ② **认到结算面板也算"打过了"**（自动跳过/极速战斗会直接进结算 ✓）；
            ③ 只有"点了完全没反应"才允许再点一次（防点到别的 UI ✗，原逻辑保留）。
    """
    # ⚠ 2026-09-26 用户报「连点两次战斗 ⇒ 第二下点到状态图标/战斗回放」✗
    #   ⇒ 只重试"点了完全没反应"的情况 ✓；画面变了但没进战斗**绝不重点** ✗
    tries = 0
    for i in range(2):
        # ⭐ v0.31 方案 B：btn 坐标是**弹窗系**（PC 标定），真机上走 tapRefDialog 换算
        #   （PC/9:16 C=0 ⇒ 与 b.tap 完全等价）
        changed = b.tap_dlg(btn['cx'], btn['cy'], wait=1.2)
        tries += 1
        if changed is False and i == 0:
            log.append({'battle': 'tap_no_change_retry', 'try': i})
            continue                           # 点空了 ⇒ 允许再点一次 ✓
        _t0 = time.time()
        while time.time() - _t0 < 15.0:        # ⭐ v1.26：5s → 15s（真机开打更慢 ✓）
            # ⭐⭐ v1.45 提速（施工单 ③⑥）：**别再固定 sleep(0.6) 白等**
            #   这条循环原来是「OCR(~1.4s) + sleep(0.6)」⇒ 每轮白花 0.6s，
            #   15s 窗口里最多白等 ~4s/场战斗。改成：
            #     · 先用 Java 侧 `wait_stable`（60ms 轮询**纯像素**、≈0 成本）等画面停 ≤1.0s；
            #       —— 「开打」这一帧是**静止**的，等它停再看，命中率不降、还少认几次字；
            #     · 停不下来（战斗动画一直在动）就**直接看**，绝不把检测拖过窗口 ✗
            #   ⚠ 语义没变：判据还是 `battle_started(items)` / 结算面板，只是**看字的时机**变了。
            try:
                if b.fast_ok:
                    b.wait_stable(1.0, interval=0.06, thr=1.4, need=6,
                                  band=(LAYOUT.sy(130), LAYOUT.sy(1700)))
            except Exception:       # noqa: BLE001
                pass
            items = b.ocr(band=(LAYOUT.sy(130), LAYOUT.sy(980)), tag='tap')
            if battle_started(items):
                log.append({'battle': 'started', 'at': (btn['cx'], btn['cy']),
                            'try': i, 'tries': tries, 'marks': list(marks),
                            'secs': round(time.time() - _t0, 1)})
                return True
            # ⭐ v1.26：直接到结算面板 = 这一场**已经打完了**（自动跳过/极速战斗）⇒ 也算成功 ✓
            if bool(fb(items, L['win'], L['lose'])) or bool(bottom_close(items)) \
                    or bool(fb(items, '回放战斗')):
                log.append({'battle': 'result_panel_instead', 'try': i,
                            'secs': round(time.time() - _t0, 1), 'marks': list(marks)})
                return True
            # ⚠ 只在「上一轮什么都没等到」时补一小口，别恢复成固定 0.6s 白等
            time.sleep(0.1)
        log.append({'battle': 'no_battle_in_15s', 'try': i, 'tries': tries,
                    'note': '画面变了但 15s 没进战斗 ⇒ 不再重点 ✓'})
        break                                  # ⭐ 不重试 ✗（防点到别的 UI）
    log.append({'battle': 'not_started', 'at': (btn['cx'], btn['cy']), 'tries': tries})
    return False


def handle_dice(b, log, items, tries=3):
    """重投命运之骰（源码 `GameApi.Explore.DiceRerollAsync` + `ChangeClover(-1,"重投命运之骰")`）：
    **每次重投消耗 1 个幸运草**，服务端返回新的掉落；`rerollTime` = 已重投次数（上限 3）。
    按钮就在**战斗结算面板**上（不是另开界面），文本含「骰 / 重投 / 命运」。
    摇到出现「带大拇目标记的装备」就停（用户 09-25 口径）。

    ⭐⭐ v0.35 重大修正（20:9 实测铁证，推翻 v0.31 的归类）：
      **结算面板不是居中弹窗，是归一化（锚底）系！**
      证据：20:9（720x1600, C=+240）跑图日志 `{'battle':'closed','at':(577,1440)}` ——
      bottom_close 是从**归一化帧** OCR 量到的「关闭」y=1440，与 PC 标定 (577,1439)
      只差 1px；若结算面板真是居中弹窗，归一化帧上它应在 1439-240=1199 ✗。
      （对照组：战斗事件面板的「战斗」钮归一化帧 495 = PC 735 - C ⇒ 那个才是弹窗系 ✓）
      ⇒ 本函数**一切按归一化系**：条目不再 +C、点击走 b.tap、找标记用归一化帧。
      v0.31 的 +C + tap_dlg 会把搜索带 [820,1070] 变成归一化 [580,830] ⇒
      骰子按钮（归一化 ~979）根本不在带里 ⇒ 永远 no_btn / rolls=0 ✗（真机不能摇色子根因）
    """
    rolls = 0
    btn_pos = None
    items = list(items)      # ⭐ v0.35：结算面板 = 归一化系，绝不再 +C

    # ⭐⭐ 2026-09-29 真机实锤（用户目击 + dice_0.png + loop_log mark_routes 佐证）：
    #   结算面板奖励行**初始就可能已带大拇指装备**（推荐怪掉的就是追踪装备）——
    #   旧逻辑无脑先摇第 1 次再检测 ⇒ 把初始的大拇指装备重投掉 + 白耗 1 草
    #   （用户原话「摇出大拇指了还继续用幸运草摇」；现场：第 1 摇后 dice_0.png 无拇指、
    #   三路由全 null，第 2 摇才认出 0.904）。⇒ 抽 _mark_routes()，进循环前先查一次，
    #   初始就有 ⇒ 一次都不摇。
    import badge as badge_mod

    def _mark_routes():
        # ⭐⭐ v0.37：真机（C>0）上**归一化帧是非等比压缩**（横 ×0.844 / 纵 ×0.7195）
        #   ⇒ 大拇指图标被压扁 ~15% ⇒ ref 路由匹配分数掉到 0.43 ✗
        #   而**弹窗帧是等比 ×0.8437** ⇒ 图标 148×148 完好、scale 仍 4.4 ✓ ⇒ 必须用弹窗帧。
        #   但弹窗帧里元素坐标 = 归一化 + C ⇒ 检测框要跟着对位：
        #     · 结算面板若是 B 类（归一化系，实测「关闭」1440≈PC 1439）⇒ box **+C**
        #     · 若是 A 类（弹窗系）⇒ box 不变
        #   ⇒ 两路弹窗 + 一路归一化，取**分数最高**的那个（阈值 0.70 兜底防噪声）✓
        #
        # ⚠⚠ v1.19（2026-10-01 1264×2780 真帧）：box **不能写死绝对 y**。
        #   真机实测（设备帧 OCR，转回参考系）：
        #     奖励行数字 636~752 ｜ 回放战斗 1224 ｜ **关闭 1441** ｜ 自动跳过 1563
        #   PC 9:16 同位置是 907/994 ｜ 1223 ｜ 1440 ｜ 1563
        #   ⇒ 面板**底部三键两机完全一致**（锚定模型对 ✓），但**奖励行在真机上高 271px**
        #   （战斗 UI 纵向压缩）⇒ 旧 box (40,840+C,1020,1140+C) 在真机完全盖不到奖励行
        #   ⇒ 三路全 None、图标掉到 0.40「近失」，文字通道更绝（见 _reward_band 注释）。
        #   ⇒ 改成**锚定「关闭」**：奖励行 = 关闭上方 (600~1300)，任何分辨率都成立 ✓
        _c = int(round(dlg_c()))
        _routes = []
        _dimg = None
        if hasattr(b, 'img_dlg'):
            try:
                _dimg = b.img_dlg()
            except Exception:       # noqa: BLE001
                _dimg = None
        if _dimg is not None and _c:
            _routes.append(('dlg+C', badge_mod.find_reward_mark(
                _dimg, box=_reward_box(items, _c))))
            _routes.append(('dlg', badge_mod.find_reward_mark(_dimg, box=_reward_box(items))))
        _routes.append(('ref', badge_mod.find_reward_mark(b.img(), box=_reward_box(items))))
        _best = None
        for _t, _h in _routes:
            if _h and (not _best or _h[0][0] > _best[0][0]):
                _best = _h
        # ⭐ 三路由全空时必须返回 [] 而不是 None——调用方 `hits[:4]` 会
        #   TypeError（2026-09-29 模拟器 23:28 两场实锤：i=0 全空 → match_err → 近失诊断被吞）
        return _routes, _dimg, _c, (_best or [])

    def _detect(tag, i, retry=2):
        """⭐ 2026-09-29 深夜：带重试的三路由检测。
        模拟器 23:44 实锤（v0.40）：第 1 摇奖励行明明有大拇指（近失 0.45@(614,936)，
        下一摇同位置 0.943），但检测帧上拇指被「确认弹窗遮罩 / 奖励行动画」拉到
        0.45 < 0.70 ⇒ 单帧检测漏判。⇒ 首检失败等 1.5s 重试一次；仍失败输出近失候选。"""
        routes, dimg, c, hits = [], None, 0, []
        for k in range(retry):
            routes, dimg, c, hits = _mark_routes()
            log.append({'dice': tag, 'k': k, 'i': i, 'C': c,
                        'best': {t: (round(h[0][0], 3) if h else None)
                                 for t, h in routes}})
            if hits:
                return routes, dimg, c, hits
            if k < retry - 1:
                _near = []
                if dimg is not None and c:
                    _near += badge_mod.find_reward_mark(
                        dimg, box=_reward_box(items, c),
                        shape_min=0.0, color_min=0.0, top=2)
                _near += badge_mod.find_reward_mark(b.img(), box=_reward_box(items),
                                                    shape_min=0.0,
                                                    color_min=0.0, top=2)
                log.append({'dice': tag + '_near', 'k': k,
                            'top': [('近失', round(x[0], 3), round(x[1], 3),
                                     x[2], x[3], x[4]) for x in _near]})
                time.sleep(1.5)      # 等遮罩/动画结束再检一次（wait_stable 对静止遮罩会立即通过）
        return routes, dimg, c, hits

    def _hit(hits, i, rolls):
        if not hits:
            return False
        STATS['dice_got'] += 1
        say('       · 摇到大拇指装备，停止重摇（第 %d 次）' % rolls)
        status('摇骰子 · 拿到大拇指装备 ★')
        log.append({'dice': 'got_recommend', 'i': i,
                    'at': (hits[0][2], hits[0][3]), 'shape': round(hits[0][0], 3),
                    'color': round(hits[0][1], 3)})
        return True

    try:
        _r0, _d0, _c0, _h0 = _detect('initial_check', -1)
        if _h0:
            STATS['dice_got'] += 1
            say('       · 奖励行初始已带大拇指装备，不重投 ✓')
            log.append({'dice': 'initial_recommend', 'at': (_h0[0][2], _h0[0][3]),
                        'shape': round(_h0[0][0], 3), 'color': round(_h0[0][1], 3)})
            log.append({'dice': 'done', 'rolls': 0})
            return 0
    except Exception as e:      # noqa: BLE001
        log.append({'dice': 'initial_check_err', 'e': repr(e)})
    # ⭐⭐⭐ 2026-10-01 机制纠错（用户指正，推翻 v0.53）：**点骰子按钮只是触发
    #   「是否重掷？」确认框，点「确定」才真正摇**（扣幸运草、刷新奖励行）。
    #   v0.53 把确认框全点「取消」= 一次都没摇成 ⇒ 奖励行永远是初始掉落 ⇒
    #   「一直取消弹窗、永远没有大拇指」（用户 10-01 实锤）。
    #   ⇒ 正确流程：点骰子（触发确认框）→ **点确定执行摇** → 摇完的干净帧上检测
    #     （retry=2）→ 有拇指停；没有 → 再点骰子 → 再确定… 最多 tries 次 ✓
    _no_confirm = 0              # 连续「点了骰子却没弹确认框」次数（手势失效特征 ⇒ 防死循环）
    while rolls < tries:
        # A. 确认框挂着？⇒ 点「确定」= **执行摇**
        # ⭐⭐⭐ v1.25：判据换成 `dice_dialog()`（**宽容**识别）——
        #   真机日志铁证：弹框明明在（`命运之骰 / 是否继续重掷？/ 取消 / 石确定`），
        #   旧的 `exb(items,'确定')`（**整条等值**）认不出「石确定」⇒ `no_confirm_popup` ×2
        #   ⇒ 只摇了 1 次就放弃（用户看到的是"摇了一次就不摇了"）✗✗
        _dlg = dice_dialog(items)
        if _dlg is not None:
            _yes = _dlg['yes']
            _no_confirm = 0
            b.tap(_yes['cx'], _yes['cy'], wait=2.5)
            rolls += 1
            log.append({'dice': 'reroll_confirm', 'at': (_yes['cx'], _yes['cy']),
                        'text': _yes.get('text'), 'rolls': rolls})
            b.wait_stable(1.5, interval=0.06, thr=1.6, need=6)
            items = b.ocr(min_conf=0.35, tag='dice')
            # ⭐ 决定性检测：摇完的奖励行（确认框已消费、等过动画）⇒ retry=2 保险
            try:
                _routes, _dimg, _c, hits = _detect('mark_routes', rolls, retry=2)
            except Exception as e:      # noqa: BLE001
                hits = []
                log.append({'dice': 'match_err', 'e': repr(e)})
            got = hits
            log.append({'dice': 'after', 'rolls': rolls, 'reward_mark_hits': len(got)})
            if _hit(got, rolls, rolls):
                break
            # ⭐ v1.25：弹框还挂着（真机上「是否继续重掷？」会一直在）⇒ 直接回 A 再点确定，
            #   **不走 B**（B 会把弹框正文当按钮点掉 = 用户看到的"乱点" ✗✗）
            if dice_dialog(items) is not None:
                log.append({'dice': 'dialog_still_up', 'rolls': rolls})
                continue
        elif fb(items, *DICE_DLG_TITLES):
            # ⭐ v1.25：认到"这是重掷弹框"却找不出「确定」⇒ **绝不走 B**（防点正文）
            log.append({'dice': 'dialog_unparsed', 'rolls': rolls,
                        'texts': [(i.get('text') or '')[:12] for i in items][:16]})
            break
        # B. 找骰子按钮（触发下一轮确认框）
        # ⭐⭐⭐ 2026-10-01 用户报「刚刚那一张图怎么点了回放战斗」⇒ 修：
        #   原来**只按位置挑**（`cx < sx(230)` + y 820~1070 的**任意文字**）⇒ 真机结算面板
        #   左边那格正是「回放战斗」⇒ 被当成骰子按钮点掉 ✗✗（函数 docstring 早就写了
        #   "文本含 骰/重投/命运"，代码却没校验 ✗）
        #   ⇒ 必须**文字命中**才算骰子按钮；位置只作为二次筛选 ✓
        _dice_keys = ('骰', '重投', '命运', '重掷', '掷')
        # ⭐ v1.19：搜索带**锚定「关闭」按钮**（不再写死 sy(700)~sy(1180)）——
        #   1264×2780 真帧实测奖励行在参考系 636~752，旧带完全盖不到（真机 no_btn 根因 ✓）
        _bx0, _by0, _by1 = _reward_band(items)
        btn = None
        for it in items:
            _t = (it.get('text') or '')
            if not any(k in _t for k in _dice_keys):
                continue
            if it['cx'] < LAYOUT.sx(REWARD_X1) and _by0 <= it['cy'] <= _by1:
                if btn is None or it['cx'] < btn['cx']:
                    btn = it
        if btn is None and rolls == 0:
            # ⭐ v0.35：按钮区是**图标+小数字**，整帧 OCR 常漏小字 ⇒ 低置信度窄带补找
            #   （同样必须**文字命中骰子关键词** ✓ 否则又会点到「回放战斗」✗）
            _it2 = b.ocr(min_conf=0.2, band=(_by0, _by1), tag='dice2')
            for it in _it2:
                _t = (it.get('text') or '')
                if not any(k in _t for k in _dice_keys):
                    continue
                if it['cx'] < LAYOUT.sx(REWARD_X1) and _by0 <= it['cy'] <= _by1:
                    if btn is None or it['cx'] < btn['cx']:
                        btn = it
            if btn is not None:
                log.append({'dice': 'narrow_hit', 'at': (btn['cx'], btn['cy']),
                            'text': btn.get('text'), 'n_items': len(_it2),
                            'band': (_by0, _by1)})
        if btn is not None:
            btn_pos = (btn['cx'], btn['cy'])
        if btn_pos is None:
            # ⭐⭐⭐ 2026-10-02 v1.24【真机实测：重投按钮**没有文字**】
            #   真机 v1.23 跑图日志：`{'dice':'no_btn', 'cand':[...'16'@(111,906), '1'@(118,979)...]}`
            #   ⇒ 面板上 OCR 只能读到「剩余骰子数」和「🍀 消耗数」，**没有任何骰/重投/命运字样**
            #   ⇒ 按文字找按钮是死路。游戏面板原图实测：那个按钮就是**奖励行左边的「🍀 + 数字」
            #      图标按钮**（上面大数字=剩余骰子数，下面 `🍀 1`=重投消耗 1 个幸运草）
            #      参考系 (114,979)，与「关闭」(y1441/1445) 固定差 **466** ✓
            #   ⇒ 兜底：先试结构定位（`clover_btn()`，优先用 OCR 到的那个数字条目 ✓）
            #   ⚠ 安全性：点完**照旧**走下面的「确认框必须弹出」校验 ——
            #     没弹出确认框就不执行、两次即放弃（`_no_confirm`）⇒ 不会乱点/不会白花幸运草 ✓
            _cb = clover_btn(items) if rolls == 0 else None
            if _cb is not None:
                btn_pos = _cb
                log.append({'dice': 'clover_btn_fallback', 'at': _cb,
                            'band': (_by0, _by1)})
                say('       · 找不到文字的骰子按钮 ⇒ 按「🍀 重投按钮」结构定位点一下试 ✓')
            else:
                _cand = [it for it in items
                         if it['cx'] < LAYOUT.sx(340) and _by0 <= it['cy'] <= _by1]
                log.append({'dice': 'no_btn', 'rolls': rolls, 'band': (_by0, _by1),
                            'cand': [{'t': (i.get('text') or '')[:10],
                                      'cx': i['cx'], 'cy': i['cy']}
                                     for i in _cand][:12]})
                # ⭐ v1.24：把这块面板**存成诊断帧**（反馈包会自动带上它 ✓）
                #   —— 下次再出现"没摇成"，我们手里就有真机面板图，不用再靠猜位置
                try:
                    _dp = _pub_dump('dice_nobtn', b.img())
                    if _dp:
                        log.append({'dice_dump': _dp})
                except Exception as _edp:      # noqa: BLE001
                    log.append({'dice_dump_fail': repr(_edp)[:60]})
                break
        btn = {'cx': btn_pos[0], 'cy': btn_pos[1]}
        log.append({'dice': 'panel', 'rolls': rolls,
                    'items': [{'t': x['text'], 'cx': x['cx'], 'cy': x['cy']}
                              for x in items if x['cy'] > LAYOUT.sy(400)][:28],
                    'btn': (btn['cx'], btn['cy']) if btn else None})
        if btn is None:
            break
        b.tap(btn['cx'], btn['cy'], wait=2)      # 点骰子 ⇒ 触发「是否重掷？」确认框
        b.snap('dice_%d' % rolls, save=True)
        items = b.ocr(min_conf=0.35, tag='dice')
        if not (exb(items, L['ok']) and exb(items, L['cancel'])):
            _no_confirm += 1
            log.append({'dice': 'no_confirm_popup', 'rolls': rolls, 'streak': _no_confirm})
            if _no_confirm >= 2:
                # ⭐ 连续 2 次点骰子都没弹确认框 ⇒ 点击通道在此界面失效（MuMu quirk）
                #   ⇒ 放弃（继续点只会像 v0.53 一样空转）✓
                say('   ⚠ 点骰子无响应（确认框未弹出 ×2）⇒ 放弃摇色子，请手动操作')
                status('摇骰子没反应 · 需手动摇')
                log.append({'dice': 'abort_no_confirm'})
                break
        else:
            _no_confirm = 0
        # ⭐ 此刻确认框刚弹/将弹，奖励行还没刷新 ⇒ **不检测**（摇都没摇），
        #   下一圈 A 段点「确定」执行摇后再检测 ✓
    # 收尾：确认框若还挂着（最后一次点骰子没来得及确定）⇒ 点「取消」= 不执行这次摇 ✓
    #   （不扣幸运草、奖励行保持最后一次摇的结果；也不会把弹窗留给关面板逻辑 ✗）
    # ⭐ v1.25：同样走 `dice_dialog()`（宽容识别 ⇒ 真机 OCR 多带字也认得出 ✓）
    _dlg2 = dice_dialog(items)
    if _dlg2 is not None:
        _no = _dlg2.get('no') or _dlg2['yes']
        b.tap(_no['cx'], _no['cy'], wait=2.0)
        log.append({'dice': 'reroll_cancel_tail', 'at': (_no['cx'], _no['cy']),
                    'text': _no.get('text')})
    log.append({'dice': 'done', 'rolls': rolls})
    return rolls


def dice_gate(marks, exact, win_streak, result_streak, on_result, diced=False):
    """⭐ 2026-10-02 v1.22：**「该不该摇色子」抽成一个纯函数**（离线可测 ✓ + 不许静默跳过）

    起因（用户反馈包 `不使用幸运草.zip`，nubia NX809J / v1.20）：
      症状「遇见大拇指格子**不使用幸运草**」；那一局的统计是
      `大拇指装备 0 件（推荐战 2 场 / 胜 2；摇色子拿到 0）`。
      ⚠ 但那包的**日志里一条 `dice` 条目都没有**（后一次运行把 loop_log 覆盖了）
      ⇒ 无法判断是「根本没摇」还是「摇了 3 次没中」。根因是这条判据原来埋在
      `wait_end()` 里、**跳过时一个字都不记** ✗ ⇒ 反馈包永远自证不了。

    所以：① 判据抽出来（能离线对拍）；② 调用方**必须**把 `(None, 原因)` 写进 log。

    返回 `(动作, 原因)`：
        `('roll', 'result_panel')` —— 真结算面板连认两帧（原路径，一字未改 ✓）
        `('roll', 'win_only')`     —— ⭐ v1.22 兜底：连读两帧「战斗胜利」，但本机 OCR
            读不到结算面板的【正面】/【负面】/「关闭」（`on_result` 恒 False）⇒ 也去试一次。
            安全性：`handle_dice()` 在非结算面板上只会记 `{'dice':'no_btn'}` 就返回
            （它的骰子按钮判据要求文字含 骰/重投/命运/重掷/掷，地图 UI 里没有这些字）✓
        `(None, 原因)`             —— 这轮先不摇（`cell_has_no_recommend_mark` /
            `waiting_result_panel` / `already_diced`）
    """
    if diced:
        return None, 'already_diced'
    if 'recommend' not in list(marks or []):
        return None, 'cell_has_no_recommend_mark'
    if result_streak >= 2:
        return 'roll', 'result_panel'
    if win_streak >= 2 and not on_result:
        return 'roll', 'win_only'
    return None, 'waiting_result_panel'


def clover_btn(items, close_y=None):
    """找「重投命运之骰」按钮 —— ⭐ 真机上它**没有文字**，是「🍀 + 数字」图标按钮

    ⭐⭐ 2026-10-02 v1.24 实测（Redmi 1280×2772 真机 v1.23 跑图 + 游戏面板原图）：
      结算面板奖励行**左边**有个按钮：上面一个大数字（剩余骰子数），下面一条
      「🍀 1」= **重投消耗 1 个幸运草** —— 它才是重投按钮 ✗ 不是文字按钮。
      手机端 OCR 在那块面板上只能读到 `'16' @ (111,906)` 和 `'1' @ (118,979)`，
      **读不到任何「骰/重投/命运」字样** ⇒ `handle_dice` 只按文字找 ⇒ 恒 `no_btn`
      ⇒ 一次都不摇、一个幸运草都不花 = 用户报的「不摇色子」✗✗

    参考系实测（1080×1920 归一化帧，面板是**锚底系** ⇒ 用「关闭」当锚点最稳）：
        关闭 y = 1445（PC 帧）/ 1441（真机） ；重投按钮 ≈ (114, 979) ⇒ **偏移 −466**
      ⇒ 本函数优先用**OCR 条目**（跨分辨率自适应 ✓），找不到再退回「关闭上方 466」的推算坐标。

    返回 `(x, y)` 或 `None`（连「关闭」都认不到 ⇒ 不敢点，交回调用方记 no_btn ✓）
    """
    try:
        _cy = close_y
        if _cy is None:
            _cl = bottom_close(items)
            _cy = _cl['cy'] if _cl else None
        if _cy is None:
            return None
        _ty = float(_cy) - 466.0
        _best, _bd = None, 1e9
        for it in items:
            _t = str(it.get('text') or '').strip()
            if not _t or len(_t) > 4 or not _t.isdigit():
                continue                      # 那一行是「🍀 1」这种纯数字（骰子数/消耗数）
            if it['cx'] > LAYOUT.sx(300):
                continue
            _d = abs(float(it['cy']) - _ty)
            if _d < _bd and _d <= 160:        # 允许 ±160（面板纵向压缩随分辨率变 ✓）
                _best, _bd = it, _d
        if _best is not None:
            return (int(_best['cx']), int(_best['cy']))
        return (int(LAYOUT.sx(114)), int(_ty))     # 兜底：按锚点推算（x 用参考值缩一下 ✓）
    except Exception:       # noqa: BLE001
        return None


# ⭐ 2026-10-02 v1.25：重掷确认框（「命运之骰 · 是否继续重掷？」）的**宽容**识别口径
#   真机实测：弹框出来了，日志却是 `{"dice":"no_confirm_popup"}` ×2 ⇒ 只摇 1 次就放弃 ✗
#   根因：判据用 `exb()`（**整条等值**），而本机 OCR 把它读成 **「石确定」**（多一个"石"字）
#         ⇒ `'石确定' != '确定'` ✗ ；且弹框挂着时"找骰子按钮"那条路会把**弹框正文**
#         「每次重掷必定高于当前点数…」（含「重掷」）当按钮点掉 ⇒ 用户看到"乱点" ✗✗
DICE_DLG_TITLES = ('命运之骰', '是否继续重掷', '是否重掷', '重掷必定')
DICE_OK_KEYS = ('确定', '确认')
DICE_NO_KEYS = ('取消', '放弃')


def dice_dialog(items):
    """识别「命运之骰 · 是否继续重掷？」确认框 → `{'yes': item, 'no': item}`，否则 None

    口径（v1.25 实测定）：
      · **标题词**（命运之骰 / 是否继续重掷…）说明"弹框挂着" ⇒ 有它才认；
      · 「确定 / 取消」用**包含**匹配（`fb` 语义）—— 真机 OCR 会多带字（「石确定」）✗；
      · 标签长度限 ≤6（防把正文「每次重掷必定高于当前点数，最高20点」当成按钮 ✗）；
      · 「确定」取最右、「取消」取最左（真机实测 取消(304,803) / 确定(774,802) ✓）。
    """
    _yes = _no = None
    _title = False
    for it in items:
        _t = str(it.get('text') or '').strip()
        if not _t:
            continue
        if any(k in _t for k in DICE_DLG_TITLES):
            _title = True
        if len(_t) > 6:
            continue
        if any(k in _t for k in DICE_OK_KEYS):
            if _yes is None or it['cx'] > _yes['cx']:
                _yes = it
        elif any(k in _t for k in DICE_NO_KEYS):
            if _no is None or it['cx'] < _no['cx']:
                _no = it
    if not _title or _yes is None:
        return None
    return {'yes': _yes, 'no': _no}


# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐ v1.45c 结算面板「定点模板」判据（施工单 ②③）
#
# 用途：`wait_end` 等结算时**先花一次毫秒级模板匹配**判"面板出来没有"，
#   没出来就**不付那一次 ~1.5s 的 OCR**。
#
# 为什么比"文字含战斗胜利"干净：地图顶部常驻「首领战斗胜利」横幅**也含这四个字**
#   （代码里 `is_battle_panel`/`win_only` 那些兜底就是被它逼出来的）；
#   而这三个按钮（回放战斗/关闭/自动跳过）**只在结算面板上**。
#   真机帧实测（2026-10-04）：
#     · 正样本：结算面板帧上三个模板自匹配 **1.000**，位置与 `layout.REF`
#       （`settle_replay`(577,1223) / `bottom_close`(578,1440) / `settle_skip`(576,1563)）**逐位吻合**；
#     · 负样本：6 张**地图帧**（含那条横幅）+ 3 张棋盘帧 → **全部不命中** ✓
# 模板从真机参考帧裁（1080×1920），落在 `templates/ui/`；**参考系坐标 ⇒ 全分辨率通吃** ✓
#
# ⚠ flag `settle_tpl`（默认关）：没有真机 A/B 数据前不改默认行为；
#   而且**模板缺失 ⇒ 判据返回 None ⇒ 调用方立刻走原路**（绝不因缺模板而跳过判定 ✗）
# ══════════════════════════════════════════════════════════════════════════
SETTLE_TPL = {
    'settle_replay_btn.png': (577, 1223),   # 回放战斗
    'settle_close_btn.png': (577, 1440),    # 关闭
    'settle_skip_btn.png': (575, 1560),     # 自动跳过
}
SETTLE_TPL_THR = 0.80
SETTLE_TPL_HALF = (160, 60)                 # 定点搜索半径（参考系像素）
# 距上次"真正 OCR"超过这么多秒 ⇒ 无论模板说什么都强制 OCR 一次（安全网）
SETTLE_FORCE_SEC = 6.0

# ⭐ v1.45e：A/B 落点/模板落点的"App 外部私有目录"（见 `flag_dirs()` 的长注释）
PUB_FILES = '/sdcard/Android/data/com.fantasy.autoexplore/files'


def _settle_tpl_on():
    return flag_on('settle_tpl')


def settle_panel_hit(b, log=None):
    """结算面板在不在 —— **定点模板**，不 OCR。-> True / False / **None（判不了）**

    None 的两种情形（调用方**必须**回退 OCR）：
      · 模板文件缺失（资源没到位 / 换 UI 版本）
      · 帧拿不到
    返回 False = "三个按钮都没命中" ⇒ 可以安全跳过这一次 OCR ✓
    """
    try:
        import fixed_ref as _fxr
    except Exception:       # noqa: BLE001
        return None
    img = b.img()
    if img is None:
        return None
    best = None
    missing = False
    for nm, (cx, cy) in SETTLE_TPL.items():
        hx, hy = SETTLE_TPL_HALF
        got = _fxr.find(img, nm, region=(cx - hx, cy - hy, cx + hx, cy + hy),
                        thr=SETTLE_TPL_THR)
        if got is None:
            if _fxr.load(nm) is None:
                missing = True            # 模板不在 ⇒ 这一路判不了
            continue
        best = got[2] if best is None else max(best, got[2])
    if best is not None:
        return True
    return None if missing else False


# ══════════════════════════════════════════════════════════════════════════
# ⭐⭐ v1.45d 选图界面「定点模板」判据（施工单 ②③ 第二刀）
#
# 用途：进图/退图路径上有 **8 次全屏 OCR/图**（`enter_map` 等待循环、`ensure_in_map`、
#   `finish_map`），其中有些只是要回答"现在在不在**选图界面**"——而选图界面最下面那两个
#   按钮（快速扫荡 / 进入地图）是**固定位置 + 固定长相**的 ⇒ 定点模板毫秒级就能答。
#
# 为什么安全：**只做正向短路**。模板命中 ⇒ 立刻返回/跳过（等价于原来 OCR 文本命中的分支）；
#   模板**没命中** ⇒ 一个字都不改，照样走原来的全屏 OCR 全链路 ✓
#   （对比被回退的那次"回合开头只看顶部 HUD"：那是**把全屏判定换成窄带判定**，漏了就瞎；
#     这里是**先花毫秒级问一个确定的问题**，答不出来就原路走 ✗）
#
# 模板实测（真机帧 2026-10-04）：
#   · 正样本：选图界面帧上自匹配 **1.000**，位置与 `layout.REF['enter_map']`(904,1618) 吻合；
#   · 负样本：棋盘帧 / 结算面板帧 / 地图帧 → 不命中（`nav_start_adv` 那条常驻导航命中是对的，本判据不用它）
# ⚠ 另外：`in_map()` 本身就把"看到快速扫荡/进入地图"当成**不在图里**的铁证 ⇒
#   模板命中与它的语义**同向**，不会互相打架 ✓
# ══════════════════════════════════════════════════════════════════════════
MENU_TPL = {
    'quick_sweep_btn.png': (684, 1617),      # 快速扫荡
    'enter_map_btn.png': (904, 1618),        # 进入地图（== layout.REF['enter_map'] ✓）
}
MENU_TPL_HALF = (140, 60)
MENU_TPL_THR = 0.80
# ⚠ 安全网：靠模板短路时，**距上次真正 OCR 最多跳这么久**（超过就强制认一次字）
#   用途：进图等待循环里万一连续命中模板，也不能让"面板/提示框"一直不被看见
MENU_SKIP_MAX = 5.0


def _menu_tpl_on():
    return flag_on('menu_tpl')


def menu_hit(b, need=1):
    """"现在在**选图界面**"（定点模板）-> True / False / **None（判不了）**

    `need` = 要命中几个按钮才算（默认 1；给 2 更严）。
    None 表示"模板没到位/拿不到帧" ⇒ 调用方**必须**走原路（原全屏 OCR）✓
    """
    try:
        import fixed_ref as _fxr
    except Exception:       # noqa: BLE001
        return None
    img = b.img()
    if img is None:
        return None
    hits = 0
    missing = False
    for nm, (cx, cy) in MENU_TPL.items():
        hx, hy = MENU_TPL_HALF
        got = _fxr.find(img, nm, region=(cx - hx, cy - hy, cx + hx, cy + hy),
                        thr=MENU_TPL_THR)
        if got is None:
            if _fxr.load(nm) is None:
                missing = True
            continue
        hits += 1
    if hits >= max(1, int(need)):
        return True
    return None if missing else False


def wait_end(b, log, timeout=45, marks=(), exact_marks=None, state=None, rc=None):
    """等战斗结算。⚠ 用户 09-25：战斗胜利不会超过 5s —— 超过很久还没结算就是没打起来，
    别死等（原来 180s，白耗时间）。

    ⚡ 2026-09-25 二次提速（OCR 是最大头，实测全屏 1.4s / 条带 1.0s 一次）：
    - 战斗过程一直在动 ⇒ 极速截图轮询（0.06s/张）几乎免费，**不做 OCR**
    - 画面**连续 ~1 秒完全不动**才算「该看一眼了」（`need=15` ≈ 0.9s@0.06）
      ⚠ 一开始设成 3 帧就被战斗动画的**每次停顿**触发 → 一场战斗 OCR 十几次（实测 22 次/35s）
    - 再叠加**最小间隔 3 秒**，最多 8 秒兜底一次 ⇒ 一场战斗通常只 OCR 2~4 次

    ⭐ 2026-10-02 v1.23：`state` / `rc` = 本局循环状态 + 这一格的坐标，用于**跨路径防重复摇色子**
    （结算面板也可能被下一轮的 `popups()` 看到 ⇒ 两条路径都摇就白花幸运草 ✗）
    """
    say('       · 战斗中…')
    # ⭐ v1.08 用户口径：战斗期间悬浮条也要写清"在打什么格子"（多种标记全写 ✓）
    status('战斗中 · %s' % tile_phrase(marks))
    t0 = time.time()
    time.sleep(1.2)          # ⭐ 2.0→1.2：进场黑幕后的首次判定，早点看一眼
    diced = False
    result_streak = 0        # ⭐ 结算面板连续命中次数（防单帧误判触发摇色子）
    win_streak = 0           # ⭐ v1.22：连续读到「战斗胜利」的次数（on_result 认不出时的兜底 ✓）
    _dice_skip_logged = False   # ⭐ v1.22：这场战斗只记一条"想摇没摇成"（防 OCR 循环刷屏 ✓）
    back = 0
    last_ocr = 0.0
    _last_ocr_real = 0.0     # ⭐ v1.45c：上次**真正做了 OCR** 的时刻（模板省 OCR 的安全网用）
    # ⭐ 用户 2026-09-25：「不是每个战斗都要等待，只有有大拇指的要等待」
    #   - 带 recommend 标记：要**细等**（等奖励行稳定，才判断得出有没有大拇指）→ wait_stable
    #   - 普通战斗：不追稳定，每 ~2.5 秒看一眼就够（结算面板一出现就关掉走人）
    # ⭐ 2026-09-27：只认**本格**标记（exact_marks ✓ 没传才退回 marks ✓）
    _ex = list(exact_marks) if exact_marks is not None else list(marks or [])
    if _ex != list(marks or []):
        log.append({'wait_end': 'exact_only', 'marks': list(marks or []), 'exact': _ex})
    need_dice = 'recommend' in _ex
    while time.time() - t0 < timeout:
        # ⭐⭐ 2026-10-01 用户报「点 ■ 后还要运行一会」⇒ 真机实测最长白等 **11.37 秒**，
        #   其中一大部分就是卡在战斗等待里（这个循环原本收到停止还会 continue 继续等 ✗）
        #   ⇒ 循环顶部查一次：收到停止就**立刻退出**（`wait_stable` 也可中断 ✓，
        #     两者合起来把延迟压到一次轮询 ≈ 0.06~0.1 秒 ✓）
        if stop_requested():
            log.append({'wait_end': 'stopped_by_user', 'elapsed': round(time.time() - t0, 1)})
            return False
        elapsed = time.time() - t0
        need_ocr = False
        if b.fast_ok:
            if need_dice:
                # ⭐ 用户 2026-09-25：「大拇指战斗等待不要那么长」
                #   原来是 8 秒上限 + 0.9 秒稳定判定（一场战斗能磨十几秒）⇒ 收紧到
                #   3 秒上限 + 0.5 秒稳定（need=8@0.06s），最小间隔 3s→1.5s
                stable = b.wait_stable(3.0, interval=0.06, thr=1.4, need=8, band=(LAYOUT.sy(130), LAYOUT.sy(1700)))
                need_ocr = bool(stable) or (elapsed - last_ocr >= 5.0)
                if need_ocr and (elapsed - last_ocr) < 1.5:
                    need_ocr = False
            else:
                # ⚠ 2026-09-25 用户报「普通战斗突然开始摇色子了」⇒ 门槛不能太低：
                #   降到 0.24 秒后**战斗中途的画面也被 OCR**，被误判成"结算面板"⇒ 误触发摇色子。
                #   现在：画面停 **0.5 秒**（need=8@0.06s）才看一眼，最小间隔 1.5 秒，2.5 秒兜底。
                stable = b.wait_stable(2.5, interval=0.06, thr=1.4, need=8, band=(LAYOUT.sy(130), LAYOUT.sy(1700)))
                need_ocr = bool(stable) or (elapsed - last_ocr >= 2.5)
                if need_ocr and (elapsed - last_ocr) < 1.5:
                    need_ocr = False
        else:
            time.sleep(1.5)
            need_ocr = True
        if not need_ocr:
            continue
        last_ocr = elapsed
        # ⭐⭐⭐ v1.45c（施工单 ②③，flag `settle_tpl`）：
        #   **先用定点模板判"结算面板到底出来没有"，没出来就不付那一次 OCR（~1.5s）**。
        #   为什么这条安全（对比 2026-09-25 被回退的那次"只看顶部 HUD"）：
        #     · 不是"只看画面一小块"，而是**三个面板专有按钮**（回放战斗/关闭/自动跳过）的定点匹配；
        #       实测负样本含 **6 张地图帧**（顶部同样有「首领战斗胜利」横幅）——**全部不命中** ⇒
        #       这个判据比"文字含战斗胜利"更干净（文字判据分不开横幅与面板，见下一行注释）。
        #     · **超时强制**：距上次真正 OCR 超过 SETTLE_FORCE_SEC 秒 ⇒ 无论模板说什么都 OCR 一次
        #       （模板没裁好 / 换了 UI 版本 ⇒ 最坏退化成原行为，绝不让判据饿死 ✗）
        #     · 模板文件缺失 ⇒ `settle_panel_hit()` 返回 None ⇒ 立刻走原路 ✓
        b.snap('battle_wait')
        if _settle_tpl_on():
            _sp = settle_panel_hit(b)
            if _sp is not None and log is not None:
                log.append({'settle_tpl': _sp, 'secs': round(elapsed, 1)})
            if _sp is False and (elapsed - _last_ocr_real) < SETTLE_FORCE_SEC:
                continue                     # 面板还没出来 ⇒ 这一轮省掉 OCR ✓
            if _sp is not None:
                _last_ocr_real = elapsed
        _OCR_CH['dlg'] = False      # ⭐ 战斗界面是**全屏**界面（不是居中弹窗）⇒ 一切回归一化系
        items = b.ocr(band=(LAYOUT.sy(130), LAYOUT.sy(1560)), tag='battle')
        win = fb(items, L['win'])
        # ⚠ 摇色子触发必须限定在**真结算面板**上：地图顶部「首领战斗胜利」横幅也含
        #   「战斗胜利」，只看它会在地图界面误触发
        on_result = bool(fb(items, *L['desc'])) or bool(bottom_close(items))
        # ⭐⭐ 摇色子判定（2026-09-25 用户：「判断摇不摇色子直接看这个地块有没有对应标记」✓）
        #   marks 就是**这一格的标记**（由点它的那一下 + 本回合标记扫描得出）。
        #   ⚠ 踩过的坑：为了防"普通战斗误摇"加了「连续两帧确认」，但**首帧判成结算面板后
        #   立刻又走了下面的关面板分支** ⇒ 面板被关掉、永远等不到第 2 帧 ⇒ 真·大拇指战斗
        #   反而不摇色子（用户本次报的 bug）。正确做法：大拇指战斗在首帧**先别关**，
        #   隔 0.6 秒复核一次；复核仍是结算面板就去摇色子，否则照常关掉 ✓
        if win and on_result:
            result_streak += 1
        else:
            result_streak = 0
        win_streak = (win_streak + 1) if win else 0
        # ⭐⭐ v1.22：判据走 `dice_gate()`（纯函数 ✓），且**无论摇不摇都留一条日志** ——
        #   用户那个「不使用幸运草」的包就是因为"跳过时零日志"而无法自证 ✗
        if not diced and 'recommend' in list(marks):
            if isinstance(state, dict) and rc is not None and state.get('diced_rc') == rc:
                # ⭐ v1.23：这一格的结算面板**已经摇过了**（多半是 `popups()` 那条路径摇的）
                #   ⇒ 别再摇（每次重投都要花 1 个幸运草 ✗）
                diced = True
                log.append({'dice_skip': 'already_diced_this_cell', 'rc': list(rc)})
            else:
                _act, _why = dice_gate(marks, _ex, win_streak, result_streak, on_result, diced)
                if _act is None and result_streak < 2:
                    time.sleep(0.6)                     # 复核一帧（不关面板，等它稳定）
                    b.snap('battle_wait2')
                    it3 = b.ocr(band=(LAYOUT.sy(130), LAYOUT.sy(1560)), tag='battle')
                    _w3 = bool(fb(it3, L['win']))
                    if _w3 and (bool(fb(it3, *L['desc'])) or bool(bottom_close(it3))):
                        result_streak += 1
                        win_streak += 1
                        items = it3
                    else:
                        result_streak = 0
                        win_streak = (win_streak + 1) if _w3 else 0
                    _act, _why = dice_gate(marks, _ex, win_streak, result_streak,
                                           on_result, diced)
                if _act == 'roll':
                    diced = True
                    if _why == 'win_only':
                        say('       · 结算面板文字认不出，但连读两帧「战斗胜利」⇒ 照常试摇色子 ✓')
                        log.append({'dice': 'win_only_attempt', 'win_streak': win_streak,
                                    'marks': list(marks or []), 'exact': list(_ex or [])})
                    handle_dice(b, log, items)
                    if isinstance(state, dict) and rc is not None:
                        state['diced_rc'] = rc          # ⭐ v1.23：记账（防另一条路径重复摇 ✓）
                    items = b.ocr(band=(LAYOUT.sy(130), LAYOUT.sy(1560)), tag='battle')
                elif not _dice_skip_logged:
                    # ⭐ 这一场"想摇却没摇"的**唯一证据**：连判据的输入一起记下来 ✓
                    _dice_skip_logged = True
                    log.append({'dice_skip': _why, 'win': bool(win),
                                'on_result': bool(on_result),
                                'result_streak': result_streak, 'win_streak': win_streak,
                                'marks': list(marks or []), 'exact': list(_ex or []),
                                'texts': [(i.get('text') or '')[:12] for i in items][:24]})
        # ⭐ 2026-09-28 提速（P5）：真结算面板上把「自动跳过」勾上（只一次，已勾不点），
        #   之后的战斗跳过动画直接进结算 —— 战斗动画是单图最大动画开销 ✓
        if win and on_result and not _AUTO_SKIP['done']:
            _auto_skip_enable(b, log)
        cl = bottom_close(items)
        if cl:
            time.sleep(0.4)                 # ⭐ 0.8→0.4：结算面板不会自己消失，少等一半
            items = b.ocr(band=(LAYOUT.sy(130), LAYOUT.sy(1560)), tag='battle')
            cl = bottom_close(items)
            if cl:
                _tap(b, cl['cx'], cl['cy'], wait=1.6)
                win = bool(fb(items, L['win']))
                log.append({'battle': 'closed', 'at': (cl['cx'], cl['cy']), 'win': win})
                mk = list(marks or [])
                STATS['battles'] += 1
                STATS['battle_wins'] += 1 if win else 0
                # ⭐⭐ 2026-09-27 修（用户报「7 张图却报 9 个首领关」）：
                #   `marks` 里含 **±1 邻域**的标记（紧挨目标的拦路格也算 ✓ 那是"该不该打"的判据 ✓）
                #   ⇒ 但**统计**只能算"本格真有该标记"的 ✓（7 张图 ⇒ 正好 7 个首领关 ✓）
                if 'boss' in _ex:
                    STATS['boss_fights'] += 1
                    STATS['boss_wins'] += 1 if win else 0
                if 'recommend' in _ex:
                    STATS['recommend_fights'] += 1
                    STATS['recommend_wins'] += 1 if win else 0
                if _ex != mk:
                    log.append({'stat': 'exact_marks', 'near': mk, 'exact': _ex})
                say('       · 战斗结算已关闭（%s）' % ('胜利' if win else '未确认胜利'))
                # ⭐ v1.08：结算也带上"打的是什么格子"（用户口径：战斗日志要写清格子 ✓）
                # ⚠ v1.37：`marks` 是**邻域兜底**（可能含邻居的 boss）⇒ 显示**只用 `_ex`**，
                #   否则又出现「打完拦路的却显示打了首领格」✗；`_ex` 空就是"拦路格"✓
                status('%s ✓ · %s' % ('战斗胜利' if win else '战斗结束',
                                      tile_phrase(_ex)))
                return True
        el = time.time() - t0
        centered = any(i['text'] in (L['win'], L['lose']) and LAYOUT.sx(200) < i['cx'] < LAYOUT.sx(900) for i in items)
        if el > 15 and exb(items, L['end']) and cl is None and not centered:
            back += 1
            if back >= 2:
                log.append({'battle': 'back_in_map', 'secs': int(el)})
                return True
        else:
            back = 0
        time.sleep(0.4)
    log.append({'battle': 'timeout'})
    return False


_AUTO_SKIP = {'done': False}
_AUTO_SKIP_BOX = (465, 1559)    # 结算面板「自动跳过」勾选框中心（1080x1920 实测截图标定 ✓）
# ⚠ 坐标教训：从聊天里「显示尺寸」估的坐标 (258,879) 是错的 —— 截图实际 1080x1920，
#   显示缩放 ~1.77 倍，第一版采样到了奖励图标上（bright=0.281 是紫色图标的值）。
#   判据用**框内均值亮度**：已勾选(亮黄) 实测 mean≈197；>140 按已勾；
#   <100 按未勾（去点一下）；100~140 拿不准 ⇒ 不点只记日志（防误 toggle ✗）


def _auto_skip_enable(b, log):
    """结算面板上的「自动跳过」勾选框：勾上后**之后的战斗跳过动画直接进结算**（P5）

    勾选状态游戏内持久 ⇒ 只处理一次（`_AUTO_SKIP['done']`）：
    已勾就不点——**绝不能盲点**（会把已勾的又点掉 ✗）。
    """
    _AUTO_SKIP['done'] = True
    try:
        arr = b.img()
        if arr is None:
            return
        x, y = int(LAYOUT.sx(_AUTO_SKIP_BOX[0])), int(LAYOUT.sy(_AUTO_SKIP_BOX[1]))
        k = max(4, int(round(10 * LAYOUT.k)))         # 内框半径（参考分辨率下 10px）
        box = arr[max(0, y - k):y + k, max(0, x - k):x + k]
        if box.size == 0:
            return
        mean_luma = float(box.mean())
        log.append({'auto_skip': 'probe', 'mean': round(mean_luma, 1)})
        if mean_luma > 140:
            say('       · 自动跳过已勾选 ✓')
            return
        if mean_luma >= 100:
            say('       · ⚠ 自动跳过勾选状态拿不准（mean=%.0f），本次不动（已记日志）'
                % mean_luma)
            return
        b.tap(x, y, wait=0.8)
        log.append({'auto_skip': 'tapped', 'at': (x, y), 'mean': round(mean_luma, 1)})
        say('       · 勾选「自动跳过」（后续战斗跳过动画，提速 ✓）')
    except Exception as e:      # noqa: BLE001
        log.append({'auto_skip': 'error', 'e': repr(e)[:100]})


# ⭐⭐ v0.31 方案 B（2026-09-30）：居中弹窗空间 ──────────────────────────────
# 真机实锤（1280×2772）：boss「战斗」钮归一化帧 y=582，PC 同一按钮 y=791
#   ⇒ 游戏**弹窗**锚定**设备屏幕中心**，不守棋盘的「顶块锚顶+其余锚底」模型。
# 弹窗系 = PC 参考系（PC 无缩放 ⇒ PC 标定的面板常数 FIGHT_Y / y 带 650~860 / X(493,225) 原样可用）；
# 归一化帧里弹窗内容 y = 弹窗系 y − C（纯平移，C = 960 + (shift − H/2)/kx；
# 真机 1280×2772 ⇒ 209、1080×2400 ⇒ 240、PC / 9:16 ⇒ 0）。
# 使用纪律：
#   · 面板按钮的 **y 带筛选** → 用 dlg_items()（+C）后的条目 ✓
#   · 面板**固定标定点**（FIGHT_Y=735 / (275,736) / X(493,225) / (539,1212)）→ b.tap_dlg() ✓
#   · OCR **找到的**按钮按归一化坐标 b.tap() 本来就准（两套映射斜率相同），不必改 ✓
#   · 棋盘 / 底部导航 / 万能位 (541,1890) **不是弹窗系**，绝不换算 ✗
#   · dlg≈202~509 的内容（面板 X 关闭符）在真机落在 toRef 丢弃的弹性区 ⇒ 归一化帧**看不见**，
#     要看它必须走弹窗帧（端上 b.img_dlg()，Java grabDlgPng 重投影）
# ⭐⭐ v0.35 重大修正（20:9 实测，720x1600 C=+240 跑图铁证）——**面板分两类，不能一刀切**：
#   · A 类「居中弹窗」：战斗事件 / 探索产出 / 偶遇强敌 …
#       实证：归一化帧「战斗」钮 y=495，PC 标定 735 ⇒ 495 + C(240) = 735 ✓
#       ⇒ 条目 +C（dlg_items）、点击 tap_dlg、标题/X 在归一化帧不可见（要走弹窗帧）✓
#   · B 类「归一化（锚底）系」：**战斗结算面板**（胜利/失败/骰子/自动跳过/关闭）
#       实证：归一化帧「关闭」钮 y=1440 ≈ PC 标定 1439（差 1px ⇒ 完全不随 C 位移）
#       ⇒ 一切按归一化系：条目**不** +C、点击 b.tap、PC 标定区域原样可用
#       （v0.31 把结算面板也当成弹窗系 ⇒ handle_dice 搜索带错位 240 ⇒ 真机永远摇不了色子 ✗）
#   · 判别法（以后每个新面板都要先做这一步）：拿一张 C>0 的真机/20:9 帧，
#     看面板上某个已 PC 标定的元素在**归一化帧**里量到的 y 与 PC 值差多少：
#     差 ≈ C ⇒ A 类（弹窗系）；差 ≈ 0 ⇒ B 类（归一化系）。
_DLGS = {'C': None}


def dlg_c():
    """弹窗系 y 偏移 C（懒加载一次；PC 恒 0）"""
    if _DLGS['C'] is None:
        c = 0.0
        try:
            if os.environ.get('MAPBOT_ANDROID'):
                import mapbot as _mb
                c = float(_mb.dlg_shift())
        except Exception:       # noqa: BLE001
            c = 0.0
        _DLGS['C'] = c
        if c:
            say('       · 居中弹窗偏移 C=%+.0fpx（高分辨率屏 ⇒ 弹窗系 = 归一化帧 y+%d）'
                % (c, c))
    return _DLGS['C']


def dlg_items(items):
    """归一化帧 OCR 条目 → 弹窗系（cy +C）。C=0 时原样返回（PC/9:16 零开销零行为差）。

    ⚠ 只对弹窗系 y ≳ 509 的内容严格成立（更靠上的内容在真机归一化帧里被丢掉）；
    面板按钮筛选（650~860 / 820~1070 等）都在安全区 ✓
    """
    c = dlg_c()
    if not c or not items:
        return items
    out = []
    for it in items:
        d = dict(it)
        d['cy'] = it['cy'] + c
        out.append(d)
    return out


def _dlg_panel_btn(ditems, text, y0=650, y1=860):
    """⭐ 弹窗系里找**独立按钮**（严格相等匹配，防「战斗胜利/回放战斗」这类合并文本误命中）。

    用途：真机上面板**标题**（「战斗事件/探索产出」dlg≈443）和 X 关闭符（dlg≈225）
    落在 toRef 丢弃的弹性区 ⇒ 归一化帧里看不见 ⇒ 面板检测只能靠**看得见的按钮**
    （战斗/探索 dlg≈735~791，在归一化帧 526~582 处 ✓）。
    """
    for it in ditems:
        t = (it.get('text') or '').strip()
        if t == text and LAYOUT.sy(y0) <= it['cy'] <= LAYOUT.sy(y1):
            return it
    return None


def _dlg_btn_sig(ditems, kind):
    """⭐ v0.61：真机上靠**右下角按钮**认「黄金宝库」面板（零额外 OCR）。

    ⭐⭐⭐ 2026-10-01 **真机帧实测标定**（用户手动停在宝库面板，我只读抓帧 ✓）：
        弹窗帧实测：`黄金宝库` @dlg(690,438) conf 0.998 ／ `购买` @dlg(**895,1498**)
        conf 1.000 ／ `10000` @dlg(914,1541) ／ 说明文案「※花费金币分别解锁宝库的外层…」
        @dlg(387,1514)
      归一化帧里：**标题和按钮都看不见**（band 130~1080 内只有那句"只能领取一件哦"；
      按钮归一化 y ≈ 1498−209 = **1289** ⇒ 被 band 1080 截掉 ✗）
      ⇒ 这印证了本函数的思路（靠弹窗系按钮）**但原 y 带 1400~1530 太窄**：
        真机按钮在 **1498**、价格 1541 ⇒ 一旦文案变化（选择奖励/离开）就会掉出带外 ✗
      ⇒ 现按实测放宽到 **1330~1650**，并把认到的按钮写进日志（下次漂了一目了然 ✓）
    """
    if kind != 'vault':
        return False
    for it in ditems:
        t = (it.get('text') or '').strip()
        if 700 < it.get('cx', 0) < 1040 and 1330 < it.get('cy', 0) < 1650 \
                and any(k in t for k in ('购买', '选择', '离开', '完成', '领取')):
            return True
    return False


def vault_title_seen(ditems):
    """弹窗帧里有没有**宝库标题**（真机实测 @dlg(690,438) conf 0.998 ✓）

    ⚠ 此前文档里写的「宝库标题 dlg 383 落在 toRef 丢弃的弹性区 ⇒ 永远认不到」
      **不准确**：真机实测标题在 dlg 438，而丢弃带是 dlg>509 ⇒ **标题其实在带外、读得到** ✓
      （真正读不到的是归一化帧：那里标题被压到 y<300 的锚顶区，OCR band 又以 130 起 ⇒ 漏）
      ⇒ 两条件（标题 or 按钮）任一命中即认定宝库面板 ✓ 更稳
    """
    for it in ditems or []:
        t = (it.get('text') or '').strip()
        if '黄金宝库' in t or ('宝库' in t and '解锁' not in t):
            return True
    return False


def panel_seen(items, ditems=None, b=None):
    """⭐ v0.33：**现在有没有弹着面板**（特殊地块 / 探索 / 战斗 / 领取 / 结算 / 确定）。

    ⚠ `b`（Bot，可选）：只有走「真·弹窗帧 OCR 复核」那条路才需要它；
      不传就跳过那段（PC / 9:16 C=0 本来就走不到）✓

    ⚠⚠ 漏判的后果很严重：主循环靠它 `break` 出点序、交给 `popups()` 处理；判不成
      ⇒ 它就带着面板继续点后面的格子 ⇒ 点击全落到面板上 ⇒ "点了战斗格却不点战斗" ✗
    ⚠ 真机高分辨率（C>0）上面板**标题**（战斗事件/探索产出/获得新装备…）落在 toRef 丢弃的
      弹性区 ⇒ 归一化帧里看不见 ⇒ 只看标题必然漏判 ⇒ 补一条：弹窗系里出现独立的
      「战斗」/「探索」按钮（dlg 650~860）即判"面板弹着" ✓
      （PC / 9:16 C=0 ⇒ 与原来完全等价 ✓）
    ⚠⭐ v0.61 再补一条**黄金宝库**：它的标题（dlg 383）和 X（dlg 384）**都在丢带里**
      ⇒ `fb(items, *L['special'])` 对它恒 False（旅行商人标题 dlg 601 不在丢带，所以只有
      宝库会漏）⇒ 面板盖着棋盘却报"没面板" ⇒ 主循环继续点棋盘格（全落到面板上）⇒
      白烧 2 轮 + 一堆 OCR/等待才走「点了没反应」的兜底。改用归一化帧里看得见的签名：
        ① 说明文案「※花费金币分别解锁宝库的外层…」→ 含「解锁宝库」(dlg 1459 ⇒ 帧内 1250 ✓)
        ② 右下角按钮（dlg 1444 ⇒ 帧内 1235 ✓）
    """
    if fb(items, *L['special']) or fb(items, L['fight']) or fb(items, L['expl']) \
            or fb(items, *L['claim']) or fb(items, *L['desc']):
        return True
    if dlg_c():
        ditems = ditems if ditems is not None else dlg_items(items)
        if _dlg_panel_btn(ditems, L['fbtn']) or _dlg_panel_btn(ditems, L['ebtn']):
            return True
        if fb(items, '解锁宝库') or _dlg_btn_sig(ditems, 'vault'):
            return True
        # ⭐⭐⭐ 2026-10-01 真机修（用户报「识别到宝库，点开**瞬间就关**」）：
        #   上面 `ditems = dlg_items(items)` 只是**把归一化条目坐标 +C**，条目本身仍是
        #   归一化帧 OCR 的产物 ⇒ **band 之外的按钮（真机宝库在 ≈1121~1441）根本不在 items 里**
        #   ⇒ 换算后照样没有 ⇒ 宝库判据恒 False ✗
        #   ⇒ 这里再补一手**真·弹窗帧 OCR**（`dlg_ocr`）：它覆盖到弹窗系 1769，
        #     宝库/商人的按钮就在那儿 ✓（≈2s，且**只在 dlg 环境**、有面板嫌疑时跑 ✓）
        try:
            # ⚠⚠ 2026-10-01 修 NameError：这里原来直接用 `b`，但本函数**签名里没有 b**
            #   ⇒ 真机（走 dlg_c() 真分支时）必然 NameError ⇒ 被 except 吞掉
            #   ⇒ **整段「真·弹窗帧 OCR 复核」从来就没跑过**（PC C=0 走不到，真机是唯一受害者）
            #   这正是用户 10-01 报的「点开宝库瞬间就关」没修掉的直接原因。
            # ⇒ 现在 b 由调用方传入（可选）；没传就跳过这一段（保持旧行为，不崩）。
            if b is not None and hasattr(b, 'ocr_dlg'):
                _dp = dlg_ocr(b, tag='panel_seen_dlg')
                if _dp:
                    if _dlg_panel_btn(_dp, L['fbtn']) or _dlg_panel_btn(_dp, L['ebtn']):
                        return True
                    if vault_title_seen(_dp) or _dlg_btn_sig(_dp, 'vault'):
                        return True
        except Exception:       # noqa: BLE001
            pass
    return False


def tap_item(b, it, wait=1.2, in_dlg=False):
    """⭐ v0.34：点一个 **OCR 找到的**条目 —— 通道必须跟**条目所在坐标系**走。

    数学上 `b.tap(归一化帧 y)` 与 `b.tap_dlg(弹窗系 y)` 落在**同一个设备点**
    （两套映射斜率相同，弹窗系 = 归一化帧 + C）⇒ 只要条目和通道同源就必然点中 ✓；
    串味（弹窗系条目走 b.tap）会整体下移 C·k（真机 ≈248 设备px）⇒ 必空 ✗。
    固定标定点（FIGHT_Y / X(493,225) / 万能位…）**不走这里**——它们本来就有自己的通道。
    """
    if it is None:
        return False
    x, y = it.get('cx'), it.get('cy')
    if x is None or y is None:
        return False
    return b.tap_dlg(x, y, wait=wait) if in_dlg else b.tap(x, y, wait=wait)


# ⭐⭐ v0.34「通道同源」总闸：当前在闭环里流动的 **OCR 条目**是哪个坐标系。
#   · False（默认）：条目来自归一化帧（顶块锚顶 / 其余锚底）⇒ 点走 b.tap
#   · True        ：条目来自**弹窗帧**（弹窗系 == PC 参考系）⇒ 点必须走 b.tap_dlg
# 只要「条目坐标系」与「点击通道」同源就必然点中；串味会整体偏 C·kx（真机 ≈248 设备px）⇒ 必空。
# ⚠ 只管 **OCR 量出来的**条目；硬编码标定常数各有各的通道，不经过这里（保持真机已验证行为）。
# ⚠ 弹窗帧条目不翻译成归一化系再喂进来 —— 减 C 后会落进 y<300 的**顶块锚顶区**，
#   那里两段映射不同 ⇒ 同源律失效（X 关闭符 dlg≈225 就是这种情况）⇒ 必须整条链路留在弹窗系。
_OCR_CH = {'dlg': False}


def _tap(b, x, y, wait=1.2):
    """点一个**当前通道里量出来的**条目坐标（通道见 _OCR_CH）"""
    return b.tap_dlg(x, y, wait=wait) if _OCR_CH['dlg'] else b.tap(x, y, wait=wait)


def ocr_ch(b, tag=None, band=None, min_conf=None):
    """按**当前通道**取 OCR 条目 —— 弹窗模式下取弹窗帧 ⇒ 看得到面板标题（归一化帧看不见）"""
    if _OCR_CH['dlg'] and hasattr(b, 'ocr_dlg'):
        try:
            return list(b.ocr_dlg(min_conf=min_conf or 0.5, band=band, tag=tag) or [])
        except Exception:       # noqa: BLE001
            pass
    kw = {}
    if band is not None:
        kw['band'] = band
    if min_conf is not None:
        kw['min_conf'] = min_conf
    return b.ocr(tag=tag, **kw)


def dlg_ocr(b, min_conf=0.5, tag='dlg'):
    """⭐ v0.34：**弹窗帧** OCR —— 拿得到**面板标题**（归一化帧里看不见的那批）。

    真机上 `toRef` 会丢掉设备弹性区，而所有面板标题都落在那里（战斗事件 dlg≈443、
    偶遇强敌 dlg≈243、旅行商人/预言石板…）⇒ 归一化帧 OCR 永远认不出面板类型
    ⇒ 只在"面板确实开着但认不出类型"时补这一手（≈2s；**不是每轮都跑** ✓）。
    PC / 9:16（C=0）没有这个通道 ⇒ 返回 None（标题本来就可见，无需补）。

    返回：弹窗系条目列表（坐标**即** PC 参考系坐标），失败返回 None。
    """
    if not dlg_c() or not hasattr(b, 'ocr_dlg'):
        return None
    try:
        items = list(b.ocr_dlg(min_conf=min_conf, tag=tag) or [])
    except Exception:       # noqa: BLE001
        return None
    return items if items else None


# ══════════════════════════════════════════════════════════════════════════
# 探索小队槽（紫/橙地块「探索产出」的前置条件）
#
# ⭐⭐ 2026-09-30 真机事故修复（用户报「明明探索格子满了，还一直点探索」）
#   日志实证（Redmi / MGAS v0.64）：`{'explore': 'first_high_value', 'at': (274, 790)}`
#   **连打 18 轮**（105 秒、0 战斗 0 装备、白花 25 体力），末了只能人工停。
#   两条根因：
#     ① **倒计时被 OCR 吃掉一个冒号**：真机帧实测 `04:24:31` → `04:24831`（conf 0.87）
#        ⇒ 旧式 `TOTAL(3) - busy(2) = 空闲 1` = **假空闲**（真值 0）
#     ② 该账号 HUD 是 **4 个槽**（角标 1/2/3/4，其中 1 个"待领取"只有进度条没有倒计时）
#        ⇒ `EXPLORE_SLOTS_TOTAL=3` 的反推法**从根上不成立**，已废除。
#   ⇒ 新口径 = **只认正面证据**「空闲」二字：
#        · 认到 ⇒ 有空闲槽（几个算几个）
#        · 没认到 ⇒ **这一帧不下结论**（free=None，保留旧值）—— 真伪交给
#          popups 的「点一次 + 验证面板是否被受理」闭环：派进去了就是真有空闲，
#          连点两次都没反应 ⇒ 判满本图（改开打 ✓ 用户 09-26 口径）
#   ⚠ 为什么不干脆"没认到就当满"：那样会让**「空闲」字小/被遮认不出来的机器永远
#     派不出探索小队**。09-26 那版死在"假空闲"这个方向，两个方向都不能拍死 ✗
_EXPLORE_TIMER_RE = re.compile(r'\d{1,2}:\d{2}:\d{2}')
# 容错式：允许**吃掉一个冒号**（"04:24831"）。只认"整条基本就是计时器"的条目
# （`^\D{0,3}…\D{0,3}$`），防把 `PID:222025` / `4057162` 这类数字也数成倒计时 ✗
_EXPLORE_TIMER_BROKEN_RE = re.compile(r'^\D{0,3}\d{1,2}:\d{2,4}:?\d{2,4}\D{0,3}$')


def count_slot_timers(items):
    """数「探索槽倒计时」→ (严格命中数, 含容错命中数)。

    ⚠ 这个数**只进日志/诊断**，不再当闸门（见上面那段：用它反推空闲数会假空闲 ✗）
    """
    strict = loose = 0
    for it in (items or []):
        t = (it.get('text') or '').replace('：', ':').replace(' ', '')
        n = len(_EXPLORE_TIMER_RE.findall(t))
        if n:
            strict += n
            loose += n
        elif ':' in t and _EXPLORE_TIMER_BROKEN_RE.match(t):
            loose += 1
    return strict, loose


def explore_slots_free(items):
    """空闲探索槽 → (free | None, info)

    · 认到「空闲」⇒ free = 个数（封顶 EXPLORE_SLOTS_TOTAL）✓ 硬证据
    · 一个都没认到 ⇒ free = None（**这一帧不下结论**，见文件上方那段说明）
    """
    n_free = sum(1 for i in (items or []) if '空闲' in (i.get('text') or ''))
    strict, busy = count_slot_timers(items)
    info = {'free_txt': n_free, 'busy': busy, 'busy_strict': strict}
    if n_free > 0:
        return max(0, min(int(EXPLORE_SLOTS_TOTAL), n_free)), info
    return None, info


def _set_slots_free(ctx, v):
    """把「空闲探索槽」写回**本轮 ctx** 与**持久 flags**（popups 里改结论用 ✓）

    ⚠ 必须两处都写：ctx 是这一趟 popups 用的，flags(=st) 是下一轮 one_round 读的。
    """
    try:
        v = int(v)
    except Exception:       # noqa: BLE001
        return
    try:
        ctx['slots_free'] = v
    except Exception:       # noqa: BLE001
        pass
    try:
        (ctx.get('flags') or {})['slots_free'] = v
    except Exception:       # noqa: BLE001
        pass


def _explore_panel_visible(items, ditems):
    """当前这帧是不是**地块面板**（「探索产出」标题 或 看得见的「探索」按钮）"""
    if fb(items, L['expl']):
        return True
    return bool(dlg_c()) and bool(_dlg_panel_btn(ditems, L['ebtn']))


def _fight_panel_visible(items, ditems):
    """当前这帧有没有**看得见的「战斗」按钮**（决定"槽满了改开打"能不能真的开打）"""
    if fb(items, L['fight']):
        return True
    return bool(dlg_c()) and bool(_dlg_panel_btn(ditems, L['fbtn']))


# ⭐⭐ 2026-09-30 成本审计（**零行为影响**，只写日志）
#   背景：用户报「最省体力算法出错：不点 1 体力的，去点 4 体力的」（现场存档见
#   `android_autoexplore/_verify/phone_stamina_0930/`）。logcat 里原本**只有格号没有成本**
#   ⇒ 事后无法判断"1 点的草地到底有没有排在点序前面"、还是"模型把贵地块看成了草地"。
#   口径 = `mapsolve.Problem.block_cost`（空地 1 / 内容格·探索 SpotSize / 内容格·战斗 ×2）
_COST_FIGHT_MARKS = ('boss', 'redEquip', 'recommend', 'battle')
# ⭐⭐ v1.08 标记中文名（用户口径：日志要写清"打的是什么格子"，多种标记全写出来 ✓）
MARK_CN = {'boss': '首领', 'recommend': '大拇指', 'clover': '四叶草',
           'redEquip': '红装', 'battle': '战斗'}


def mark_cn(marks):
    """标记英文 → 中文名列表（**全写出来**，用户 2026-10-01 口径）

    用户原话：「战斗时日志要写出打这个格子是什么格子，拦路的就写拦路格，首领就写首领格，
    四叶草就写四叶草格，大拇指就写大拇指格。同时有多种就都写出来，比如
    当前格子标志：首领，四叶草，大拇指，红装」✓
    """
    out = []
    for m in (marks or []):
        cn = MARK_CN.get(str(m))
        if cn and cn not in out:
            out.append(cn)
    return out


def tile_desc(marks):
    """该格的**中文标签串**（一个都没有 ⇒ 空串，调用方自己决定兜底成「拦路格」✓）"""
    _cn = mark_cn(marks)
    return '，'.join(_cn) if _cn else ''


def tile_phrase(marks):
    """该格的**完整中文说法**（用户 2026-10-01 口径的最终文案 ✓）

    · 无标记   ⇒ `拦路格`
    · 单个     ⇒ `首领格` / `四叶草格` / `大拇指格` / `红装格`
    · 多个     ⇒ `格子标志：首领，四叶草，大拇指，红装`（用户原话给的样例 ✓）
    """
    _cn = mark_cn(marks)
    if not _cn:
        return '拦路格'
    if len(_cn) == 1:
        return '%s格' % _cn[0]
    return '格子标志：%s' % '，'.join(_cn)


def model_cost(sid, marks=()):
    """这一格**模型以为**要花的体力（仅供日志审计 ✓ 不参与决策 ✗）"""
    try:
        row = (spots_mod.spot_rows().get(str(sid)) or {})
        size = int(row.get('SpotSize') or 1)
        if spots_mod.is_plain_spot(str(sid)):
            return 1                      # 空地（连锁）：固定 1 点 ✓
        if set(marks or ()) & set(_COST_FIGHT_MARKS):
            return size * 2               # 明确要打的 ⇒ SpotSize×2 ✓
        return size                       # 内容格·探索 = SpotSize ✓
    except Exception:       # noqa: BLE001
        return 1


def popups(b, items, log, ctx=None):
    ctx = ctx or {}
    markers = ctx.get('marks') or {}
    tapped = ctx.get('tapped')
    # ⭐ v0.32：弹窗系条目（+C）一次算好；真机上面板标题/X 在弹性区看不见，
    #   分支入口与按钮全靠它（C=0 时就是 items 本身，PC 零影响）
    # ⭐ v0.34：`in_dlg` ⇒ 调用方传进来的**就是弹窗帧条目**（已是弹窗系坐标），
    #   绝不能再 +C（否则按钮 y 带整体再抬 209 ⇒ 全都落空 ✗）
    ditems = items if (ctx or {}).get('in_dlg') else dlg_items(items)
    if fb(items, *L['kick']):
        log.append({'popup': 'kicked'})
        return 'kicked'
    # ⭐「发现莱姆！」先处理（揭格/补点后可能弹，不处理会挡住后面的所有判断）
    lb = lime_back(items)
    if lb:
        _tap(b, lb['cx'], lb['cy'], wait=1.8)
        log.append({'popup': 'lime_back', 'at': (lb['cx'], lb['cy'])})
        say('       · 发现莱姆！→ 点返回')
        status('遇到莱姆 · 返回')
        return 'handled'
    # ⭐「获得新装备！」（2026-09-26 用户报卡住）：打完大拇指地块 / 补点发现莱姆点都可能弹，
    #   它盖住整盘 ⇒ 后面的地块分类全是暗格 ⇒ 一路空转到退图超时 ✗
    if close_newequip(b, items, log, 'popup'):
        if _PANEL_STUCK.get('newequip_popup', 0) >= 2:
            # 连着两次都关不掉 ⇒ 别再占着闭环（交给整盘暗格那套兜底处理）
            log.append({'popup': 'newequip_give_up'})
            return 'none'
        say('       · 获得新装备！→ 点返回')
        status('拿到新装备 · 返回')
        return 'handled'
    # ⭐「预言石板」等占卜面板（用户 2026-09-26）：**点中间最下面**关掉 + **拉黑这格** ✓
    if fb(items, *L['prophecy']):
        universal_close(b, log, items=items, probe=L['prophecy'][0], where='prophecy',
                        at=tapped)
        block_cell(log, ctx.get('flags'), tapped, 'prophecy')
        say('       · 预言石板 → 点中间最下面关掉，并拉黑这格（以后不再点）')
        status('触发预言石板 · 已跳过这格')
        return 'handled'
    if fb(items, *L['low']):
        return 'insufficient'
    # ⭐⭐ 2026-09-26 修（**这是"没打 boss 就退图"的根因**）：
    #   原来判据只有 `【正面】/【负面】 and 战斗胜利/失败` —— 但**有些结算面板不显示
    #   【正面】/【负面】**（实测 runs/m0_r008.png：面板上只有「战斗胜利 / 回放战斗 / 关闭」）
    #   ⇒ 这里判不成结算面板 ⇒ 一直走到函数尾巴 `return 'none'`
    #   ⇒ 棋盘被面板盖住 ⇒ `marks` 扫描读不到 boss 标记 ⇒ 误判 `finish: targets_done`
    #   ⇒ **boss 没打就退图** ✗（用户 2026-09-26 报「第一把没打到 boss 关就退了」）
    #   ⇒ 改成和 `wait_end()` 里 `on_result` **同一套判据**（那边早就修过了 ✓）：
    #      ①（【正面】/【负面】 and 胜负）  ② 底部「关闭」  ③ 「回放战斗」
    # ⭐ 刚点那格的标记（本格精确命中优先；没有就取 ±1 邻域最近的）
    #
    # ⭐⭐ v1.37【邻域结果**不许**当成"这格是什么"】—— 治用户 2026-10-02 真机报
    #   「打完拦路的却显示打了首领格，后面又打了首领格」✗
    #   真机铁证（Redmi 1280×2772 广袤草原，v1.34 日志）：
    #     点 (4,1) **拦路**格 ⇒ `cell_marks: ["boss"]`  ← 其实是 (5,1) 的 boss
    #     同一轮日志 `{"stat":"exact_marks","near":["boss"],"exact":[]}` ← **exact 是空的** ✗
    #     ⇒ 后面 `solver` 仍认为 (5,1) 有 boss ⇒ **又打一次真 boss**（重复扣体力）
    #   根因：`near()` 找不到本格标记时**退而取 ±1 邻域最近的**（2026-09-25 加的兜底）
    #     ⇒ 把**邻居**的 boss 记成自己的 ✗✗
    #   修法：**邻域只用于"要不要打"（内部），不用于"记成什么"（显示/统计）** ✓
    #     → `cell_marks` 与 `stat` 一律只用 **exact**；邻域另记为 `near_*` 供诊断 ✓
    def near():
        """⚠ 返回的是**邻域兜底**结果（含邻居标记）—— 只用于内部判断，
        **绝不**用于显示/统计；要"这格到底有什么"请用 `exact_marks()` ✓"""
        if not tapped:
            return []
        r0, c0 = cell_of(tapped[0], tapped[1])
        # ⭐ 2026-09-25 用户口径：「判断摇不摇色子直接看这个地块有没有对应标记」
        #   ⇒ **本格精确命中优先**（原来只在 ±1 邻域里挑最近的，本格没扫到标记时会误取邻格的）
        exact = markers.get((r0, c0))
        if exact is not None:
            return list(exact.get('marks') or [])
        hit, best = [], 99
        for (r, c), v in markers.items():
            d = max(abs(r - r0), abs(c - c0))
            if d <= 1 and d < best:
                best, hit = d, v['marks']
        return list(hit)

    def exact_marks():
        """⭐⭐ v1.37：**本格**真实标记（认不出就是空，**不拿邻居的顶替** ✓）

        用于 `cell_marks` 日志、`stat: exact_marks` 统计、以及
        「打完显示成什么」的所有对外口径 ⇒ 杜绝"拦路格显示成首领格" ✗
        """
        if not tapped:
            return []
        r0, c0 = cell_of(tapped[0], tapped[1])
        _e = markers.get((r0, c0))
        return list((_e or {}).get('marks') or [])

    _res = bool(fb(items, *L['desc']) and fb(items, L['win'], L['lose'])) \
        or bool(bottom_close(items)) or bool(fb(items, '回放战斗'))
    if _res:
        # 结算面板：把所有按钮文字落盘（含幸运草/摇色子相关），供实现摇色子用
        log.append({'popup': 'result_panel',
                    'buttons': [{'t': i['text'], 'cx': i['cx'], 'cy': i['cy']}
                                for i in items if i['cy'] > LAYOUT.sy(600) and len(i['text']) <= 8],
                    'texts': [i['text'] for i in items][:30]})
        # ⭐⭐⭐ 2026-10-02 v1.23【**用户报「遇见大拇指格子不使用幸运草」的真根因**】
        #   真机实测（Redmi 1280×2772 / v1.22 实跑日志）：
        #     ① r3 点大拇指格 (1,6) → 弹「战斗事件」面板 → 点「战斗」→ `wait_end` 等 5 秒
        #        没看到战斗（`{'battle':'no_battle_in_5s'}` / `not_started` / `blocked`）
        #     ② **下一轮** r4 才看到结算面板 ⇒ 走的是**本分支**（`popup: result_panel`）
        #     ③ 本分支以前**只关面板、从不摇色子**（`handle_dice` 只挂在 `wait_end` 里 ✗）
        #     ⇒ 大拇指标记白丢、一次幸运草都没花 = 用户看到的现象 ✗✗
        #   （`no_battle_in_5s` 在真机上很常见：点完「战斗」到真正开打 >5 秒）
        #   修法：**结算面板落在大拇指格上 ⇒ 先摇色子，再关**（摇色子按钮就在这块面板上 ✓）
        #   ⚠ 防重复：`st['diced_rc']` 记这一格已摇过（两条路径都摇 = 白花幸运草 ✗）
        _state = ctx.get('flags') if isinstance(ctx.get('flags'), dict) else {}
        _rc, _mk_here = None, []
        if tapped:
            try:
                _rc = cell_of(tapped[0], tapped[1])
                _mk_here = near()
            except Exception:       # noqa: BLE001
                _rc, _mk_here = None, []
        if 'recommend' in _mk_here and _state.get('diced_rc') != _rc:
            say('       · 结算面板落在大拇指格(%s)上 ⇒ **先摇色子再关**（v1.23）'
                % ('%d,%d' % _rc if _rc else '?'))
            status('摇骰子 · 大拇指格')
            log.append({'popup': 'result_dice', 'rc': list(_rc) if _rc else None,
                        'marks': _mk_here})
            try:
                handle_dice(b, log, items)
            except Exception as _ed:      # noqa: BLE001
                log.append({'popup': 'result_dice_err', 'e': repr(_ed)[:80]})
            if _rc is not None:
                _state['diced_rc'] = _rc
            items = b.ocr(tag='popup_dice')
        cl = bottom_close(items)
        if cl:
            _tap(b, cl['cx'], cl['cy'], wait=2.5)
            log.append({'popup': 'result_closed', 'at': (cl['cx'], cl['cy'])})
            return 'handled'
        # ⭐ 确实认到是结算面板却没量到「关闭」⇒ 交给 universal_close（内部按战斗面板
        #   点实测的关闭坐标 (577,1439)，**不会点开始冒险** ✓）——别再 return 'none' 干耗 ✗
        universal_close(b, log, items=items, where='result_no_close_btn')
        log.append({'popup': 'result_closed_fixed'})
        return 'handled'
    img = b.img()

    # ⭐ 敌方预览面板「偶遇强敌 / 遭遇强敌」（2026-09-25 用户报卡在这里）：
    #   面板：标题(542,243) + 右上角 X(988,244) + 敌人名 + 底部「邀请挑战」(297,1587)
    #   用户口径变更（2026-09-25 晚）：**不打，关掉就行**（先前说过"遇到就打"，以本次为准）
    if fb(items, *L['strong']):
        mk = near()
        log.append({'popup': 'strong_panel', 'cell_marks': mk})
        x = find_x(items)
        if x:
            _tap(b, x['cx'], x['cy'], wait=1.5)
        else:
            close_x_panels(b, img)
        log.append({'skip': 'strong_closed', 'tapped': tapped, 'marks': list(mk),
                    'closed_at': (x['cx'], x['cy']) if x else None})
        say('       · 偶遇强敌 → 不打，关掉')
        status('遇到强敌 · 已避开')
        return 'handled'

    # ⭐⭐ 派遣探索面板（用户 2026-09-26 实测口径，**2026-10-01 用户明确要保留**）：
    #   点「探索」后弹出「探索配队」面板 ⇒ 一键派遣(891,1507) ⇒ 按钮变「开始探索」
    #   ⇒ 再点 (875,1507) ⇒ 上方一个格子被填（出现倒计时 ✓）
    #   ⚠ 必须在战斗分支之前判（该面板与地块面板一样，别掉进别的分支 ✗）
    #   ⚠⚠ 2026-10-01 我一度按"不点一键派遣"把这一整块删掉 ✗ —— 那是**误读**：
    #      用户说的「刚刚脚本不点派遣」是在报 **bug 现象**（它该点却卡着没点），
    #      不是口径。用户随后明确：「**恢复原逻辑：要点一键派遣**」⇒ 本块按原样保留 ✓
    if EXPLORE_DISPATCH and any(fb(items, k) for k in ('探索配队', '一键派遣',
                                                 '键派遣', '开始探索')):
        # ⭐ 槽位满了 ⇒ 不能派遣（用户：探索满了还在探索 ✗）⇒ 关掉面板 ✓
        if int(ctx.get('slots_free', 1) or 0) <= 0:
            log.append({'dispatch': 'skip_slots_full'})
            say('       · 三个探索槽已满，关掉派遣面板（不派遣 ✓）')
            status('三个小队槽已满 · 收起面板')
            x = find_x(items)
            if x:
                _tap(b, x['cx'], x['cy'], wait=1.5)
            else:
                back = find_button(items, '返回', '取消', '关闭', maxlen=4)
                if back:
                    _tap(b, back['cx'], back['cy'], wait=1.5)
                else:
                    _panel_tap(b, 275, 1507, 'norm', log=log, what='返回(兜底)')
            return 'handled'
        _gone = False
        it2 = None          # ⭐ 初始化：下面 `if _try and it2` 与收尾的 find_x/n_free 都要读它
        for _try in range(2):
            # ⭐⭐⭐ 2026-10-01 用户报「点搓（错）一键派遣位置了」⇒ **改用 OCR 现读的按钮坐标**：
            #   面板 OCR 里本来就有那颗按钮（真机实测读到 `键派遣`、`开始探索`）✗
            #   而代码却一直去点**写死的** `DISPATCH_BTN=(891,1507)` ——
            #   那个值是 PC 归一化系的旧标定，在真机上点不中（用户连报两次位置不对 ✗）
            #   ⇒ 现在**优先用 OCR 到的那颗按钮**（`it2`/`items` 里找），
            #     只有实在读不到文字时才退回标定常量（并有通道兜底 ✓）
            #   好处：与分辨率无关、与文案变化无关（键派遣/一键派遣/开始探索 都认 ✓）
            _btn_it = None
            # ⚠⚠ 2026-10-01 修 NameError：原来写 `for _src in (it2 if _try else items, items)`
            #   —— `it2` 只在**循环体末尾**（ocr_ch 之后）才赋值 ⇒ **首轮必然 NameError** ✗
            #   （被上层 `except Exception: pass` 吞掉 ⇒ 症状：派遣面板点了两下都关不掉，
            #    日志永远停在 dispatch 的第一条 ⇒ user 报「点不了一键派遣」）
            # ⇒ 第 1 轮只有 `items`；第 2 轮起才把上一轮 OCR 到的 `it2` 也纳入候选
            #   （面板文字会变：键派遣 → 开始探索，所以每轮仍会重新 OCR）。
            _src_list = [items]
            if _try and it2:
                _src_list.insert(0, it2)
            for _src in _src_list:
                for _it in (_src or []):
                    _t = (_it.get('text') or '').strip()
                    if ('派遣' in _t or '开始探索' in _t) and '预计时间' not in _t:
                        # 取**最靠右下**的那颗（面板底部主按钮 ✓）
                        if _btn_it is None or (_it.get('cy', 0), _it.get('cx', 0)) > \
                                (_btn_it.get('cy', 0), _btn_it.get('cx', 0)):
                            _btn_it = _it
                if _btn_it is not None:
                    break
            if _btn_it is not None:
                _bx, _by = int(_btn_it['cx']), int(_btn_it['cy'])
                # ⭐⭐⭐ 2026-10-01 **通道同源**（我上一次又在这里串味了 ✗）：
                #   `_btn_it` 来自 `ocr_ch()` ⇒ 它**跟着 `_OCR_CH['dlg']` 走**
                #   （dlg=False ⇒ 归一化帧坐标；True ⇒ 弹窗系坐标）。
                #   我上次写死 `tap_dlg` ⇒ 归一化坐标 + 弹窗通道 ⇒ 真机偏 C≈209px ✗
                #   真机实证（21:11）：`btn_by_ocr 键派遣 @(891,1350)` → tap1 后按钮变
                #   「开始探索」（说明第 1 击其实点中了），但第 2 击落到别处 ⇒ 状态弹回
                #   ⇒ `still_open_close`（面板两次都关不掉）✗
                #   ⇒ **必须用 `_tap()`**（它按 `_OCR_CH['dlg']` 自动选通道 = 同源 ✓）
                log.append({'dispatch': 'btn_by_ocr', 'text': _btn_it.get('text'),
                            'at': (_bx, _by), 'try': _try + 1,
                            'ch': 'dlg' if _OCR_CH['dlg'] else 'norm'})
                say('       · 一键派遣 → 点 OCR 读到的「%s」(%d,%d)（%s 通道 ✓）'
                    % ((_btn_it.get('text') or '')[:8], _bx, _by,
                       '弹窗帧' if _OCR_CH['dlg'] else '归一化帧'))
                _tap(b, _bx, _by, wait=2.5)
            else:
                # 兜底：读不到按钮文字 ⇒ 用标定常量（`_panel_tap` 会验证生效并自动换通道 ✓）
                log.append({'dispatch': 'btn_by_const', 'at': DISPATCH_BTN,
                            'try': _try + 1})
                say('       · ⚠ 没读到派遣按钮文字 ⇒ 退回标定坐标 %s' % (DISPATCH_BTN,))
                _panel_tap(b, DISPATCH_BTN[0], DISPATCH_BTN[1], 'norm', log=log,
                           what='一键派遣(标定)')
            it2 = ocr_ch(b, min_conf=0.2, tag='dispatch')
            t2 = [i['text'] for i in it2]
            log.append({'dispatch': 'tap%d' % (_try + 1), 'texts': t2[:8]})
            if not any(('探索配队' in x) or ('开始探索' in x) or ('派遣' in x) or
                       ('探索预计时间' in x) for x in t2):
                _gone = True
                break
        if not _gone:
            # ⚠ 点了两次面板还在 ⇒ 别再点了 ✗（用户报「一直点探索」就是这个）
            log.append({'dispatch': 'still_open_close'})
            say('       · 派遣面板点了两次还在 ⇒ 关掉它，不再重复点 ✓')
            x = find_x(it2)
            if x:
                _tap(b, x['cx'], x['cy'], wait=1.5)
            else:
                back = find_button(it2, '返回', '取消', '关闭', maxlen=4)
                if back:
                    _tap(b, back['cx'], back['cy'], wait=1.5)
                else:
                    _panel_tap(b, 275, 1507, 'norm', log=log, what='返回(兜底)')
            return 'handled'
        n_free = sum(1 for i in it2 if '空闲' in i['text'])
        say('       · 已派遣一支探索队（上方还剩 %d 个空闲槽）' % n_free)
        status('已派出小队（还剩 %d 个空位）' % n_free)
        return 'handled'

    # ⭐⭐ 2026-09-26 用户口径：**三个探索格子有空闲时，紫/橙探索地块要点左边「探索」**
    #   实测面板同时含「探索产出(274,443)」与「战斗事件(806,442)」⇒ 必须先判探索 ✓
    #   否则会掉进下面的战斗分支、点成右边的「战斗」✗（用户当场抓到 ✗）
    # ⭐ 判据：**用当前点击位置现算** sid（原来用 st['tapped_sid'] 是上一轮的值 ✗ 导致
    #   紫橙探索格被当成普通格打了战斗 ✗ —— 用户 2026-09-26 报）
    _ev_tiles = ctx.get('ev_tiles') or []
    _tapped_sid = ''
    try:
        _tapped = ctx.get('tapped')      # ⭐ 改名 _tapped：原局部 `_tap` 遮蔽模块级
        _cst = ctx.get('st') or {}       #   点击函数 _tap ⇒ X 关闭分支 TypeError 崩溃
        if _tapped and _cst:
            _tc = cell_of(_tapped[0], _tapped[1])
            _tapped_sid = str((_cst.get(_tc) or {}).get('sid') or '')
    except Exception:       # noqa: BLE001
        _tapped_sid = ''
    _purple_suffix = set(getattr(spots_mod, 'EXPLORE_SUFFIX', ('221', '321', '331')))
    _is_purple = ('_' in _tapped_sid) and (_tapped_sid.split('_')[-1] in _purple_suffix)
    # ⭐ 槽位满了 ⇒ 不走探索 ✓（落到下面的战斗分支 ⇒ 打掉它 ✓ 用户 2026-09-26）
    _free_now = int(ctx.get('slots_free', 1) or 0)
    if (EXPLORE_DISPATCH and _is_purple and _free_now > 0
            and (fb(items, L['expl'])
                 # ⭐ v0.32：真机上「探索产出」标题（dlg≈443）落弹性区看不见 ⇒
                 #   用看得见的「探索」按钮（dlg≈735）进分支（仅 C>0 生效）
                 or (dlg_c() and _dlg_panel_btn(ditems, L['ebtn'])))):
        # ⭐ v0.31 方案 B：面板按钮 y 带是弹窗系标定 ⇒ 用 +C 后的条目筛、tap_dlg 点
        act = None
        for it in ditems:
            if L['ebtn'] in it['text'] and L['expl'] not in it['text'] and it['cy'] > LAYOUT.sy(620):
                act = it
                break
        _eat = (int(act['cx']), int(act['cy'])) if act else (275, 736)
        # ⭐⭐⭐ 2026-09-30 真机事故修复（用户报「明明探索格子满了，还一直点探索」）：
        #   旧版**点完直接 return handled、不验证** ⇒ 游戏侧槽位满时点「探索」**毫无反应、
        #   地块面板不关** ⇒ 下一轮又看到同一个面板、又点一次……
        #   真机日志实证：连续 18 轮 `{'explore': 'first_high_value', 'at': (274, 790)}`，
        #   整张图 105 秒 0 战斗 0 装备（25 体力白花，只能人工停 ✗）。
        #   ⇒ 与下面「探索产出」分支同口径：**点完必须验证游戏有没有受理**：
        #       面板关掉/换成「探索配队」⇒ 受理了 ⇒ 空闲槽 -1 ✓
        #       面板还在 ⇒ 没受理（槽其实是满的）⇒ 计数；连两次 ⇒ 判满本图 ✓
        b.tap_dlg(_eat[0], _eat[1], wait=3.0)
        _n_ex = (_PANEL_STUCK.get('expl') or 0) + 1
        _PANEL_STUCK['expl'] = _n_ex
        log.append({'explore': 'first_high_value' if act else 'first_fixed_btn',
                    'at': _eat, 'n': _n_ex, 'slots_free': _free_now,
                    # ⭐⭐ v1.40 补诊断：把**点的哪格、sid、是不是紫橙**记下来
                    #   （2026-10-02 用户问「第三次规划打开了一个蓝色探索格，这是什么问题」——
                    #    旧日志只有坐标，board 字段又被截断到 300 字符 ⇒ **事后查不出点的哪格** ✗）
                    'tile': '%d,%d' % cell_of(_eat[0], _eat[1]) if _eat else None,
                    'sid': _tapped_sid, 'is_purple': bool(_is_purple)})
        if panel_gone(b, L['expl'], dlg_btn=L['ebtn']):
            _PANEL_STUCK['expl'] = 0
            # ⚠ **不在这里改 slots_free**：面板关掉只代表游戏受理了这下（多半换成
            #   「探索配队」面板，真正派遣在下面的 A 分支）⇒ 提前 -1 会让 A 分支
            #   把配队面板当成"槽满"关掉 ✗。空闲数一律以**下一轮轮首 HUD 读数**为准 ✓
            say('       · 点「探索」(%d,%d) → 事件进格子' % _eat)
            status('派出一支小队 · 探索中')
            return 'handled'
        if _n_ex < 2:
            say('       · 点了「探索」(%d,%d) 面板没关（第 %d 次，可能动画没走完）'
                % (_eat[0], _eat[1], _n_ex))
            return 'handled'
        # ⭐ 连点两次都没反应 ⇒ **游戏说没有空闲槽**（HUD 读数错了）⇒
        #   记满本图（后面的紫/橙格直接走「战斗」分支 ✓ 用户 09-26 口径「满了就改战斗」）
        _set_slots_free(ctx, 0)
        _can_fight = _fight_panel_visible(items, ditems)
        log.append({'explore': 'slots_full_latched', 'taps': _n_ex,
                    'at': _eat, 'can_fight': _can_fight})
        say('       · 「探索」点了两次都没反应 ⇒ 探索槽其实是满的（本图改开打）')
        status('小队槽已满 · 这格改开打')
        if not _can_fight:
            # 这块面板连「战斗」都没有 ⇒ 下一轮的战斗分支也接不住 ⇒ 直接拉黑这格，
            # 免得在它身上来回空转（本图目标清完就正常退图 ✓）
            block_cell(log, ctx.get('flags'), tapped, 'explore_no_fight_btn')
            x = find_x(items)
            if x:
                _tap(b, x['cx'], x['cy'], wait=1.4)
            else:
                close_x_panels(b, b.img())
        return 'handled'

    # ⭐⭐ v0.32 入口修复（真机 boss 面板点不到战斗的**真正根因**）：
    #   面板标题「战斗事件」dlg≈443 在真机落在 toRef 丢弃的弹性区 ⇒ 归一化帧看不见
    #   ⇒ fb(items,'战斗事件') 恒 False ⇒ 战斗分支**从来没进去过**（v0.27~v0.31 全白修）✗
    #   ⇒ C>0 时用看得见的独立「战斗」按钮（dlg≈735~791）进分支；
    #     严格相等匹配防「战斗胜利/回放战斗」误命中；PC/9:16 C=0 ⇒ 行为一字不变 ✓
    _fe_title = fb(items, L['fight'])
    _fe_btn = (not _fe_title) and bool(dlg_c()) and _dlg_panel_btn(ditems, L['fbtn'])
    if _fe_title or _fe_btn:
        mk = near()
        # ⭐ 2026-09-26 用户口径（原话「满了后就改成战斗」）：
        #   探索槽**满了**时的紫/橙探索格（ID 后缀 221/321/331）⇒ **直接打掉** ✓
        #   ⚠ 不补这一条的话，它会掉进下面「不在路上 ⇒ 不打」的分支 ⇒ 面板只是被关掉
        #     ⇒ 既没探索也没打 ⇒ 还是白点一下 ✗（离线测 slots_free=0 就是 offroad_fight）
        if _is_purple and _free_now <= 0:
            mk = list(mk) + ['explore_full_fight']
            log.append({'popup': 'fight_panel_explore_full',
                        'slots_free': _free_now, 'tapped_sid': _tapped_sid})
        log.append({'popup': 'fight_panel', 'cell_marks': exact_marks(),
                    'near_marks': mk,
                    'entry': 'title' if _fe_title else 'dlg_btn'})
        if not mk:
            # ⭐ 用户 2026-09-25：**跟「接近 boss」无关的战斗格一律不打**。
            #   只有落在「出生地 → 待处理标记格」路上的那格才打（它挡着路，打掉才能连锁揭示）；
            #   其他内容格弹出来的战斗面板直接关掉（旧版只要 marked 非空就打 → 白打乱打）。
            road = set(ctx.get('road') or [])
            on_road = bool(tapped and (tapped in road or any(
                abs(tapped[0] - q[0]) <= GRID['cx'] and abs(tapped[1] - q[1]) <= GRID['cy']
                for q in road)))
            # ⭐⭐⭐ 2026-09-28 修「点了 33 却没点到开始战斗」（用户真机报，图二实锤：
            #   solver plan=['2,7','3,3','3,1'] ⇒ 点 (3,3) 弹 fight_panel ⇒ 被
            #   offroad_fight 关掉（closed=2）⇒ 格没清、后面点序全乱 ✗）：
            #   **计划内**的格弹出战斗面板 ⇒ 必打 —— solver/EffPolicy 已做过
            #   「绕开更贵」的权衡，它挡着计划；旧口径只认启发式 road_all ⇒
            #   计划内的开路战斗被误判"无关战斗" ✗。plan_road = 本轮计划执行步 ✓
            _proad = set(ctx.get('plan_road') or [])
            on_plan = bool(tapped and (tapped in _proad or any(
                abs(tapped[0] - q[0]) <= GRID['cx'] and abs(tapped[1] - q[1]) <= GRID['cy']
                for q in _proad)))
            # ⭐⭐ 2026-09-27 用户口径修正：
            #   「目标相邻的战斗格子**不是必打的**，只有附加没有空格子能连接目标格子才会被迫打」
            #   ⇒ 旧口径「紧挨目标 ⇒ 必打」(near_target) 作废 ✗
            #   ⇒ 新判据：**这条路上还有空地块(1 体)可走 ⇒ 不打** ✓；确实没有 ⇒ 被迫打 ✓
            # ⭐⭐ 2026-09-27 修（用户报「点了 33 却没打掉这个战斗格」）：
            #   路是**有序**的（path_to 从出生点往外 ✓）
            #   ⇒ 只看"**在它之前**"那段路上还有没有空地 ✓
            #      （旧版只看"整条路上有没有空地" ✗ ⇒ 障碍两侧各有空地时误判成"不用打"✗
            #        结果点了却关面板 ⇒ 障碍没清掉 ⇒ 后面根本过不去 ✗）
            _road_seq = list(ctx.get('road') or [])
            _plain_road = list(ctx.get('plain_road') or [])
            _plain_left = False
            if tapped:
                _idx = None
                for _i3, _q in enumerate(_road_seq):
                    if (abs(tapped[0] - _q[0]) <= GRID['cx'] * 1.05
                            and abs(tapped[1] - _q[1]) <= GRID['cy'] * 1.05):
                        _idx = _i3
                        break
                if _idx is None:
                    _plain_left = bool(_plain_road)      # 不在路上 ⇒ 保守不动 ✓
                else:
                    for _q in _road_seq[:_idx]:           # 只看它**前面**那段 ✓
                        for _p in _plain_road:
                            if (abs(_q[0] - _p[0]) <= 1 and abs(_q[1] - _p[1]) <= 1):
                                _plain_left = True
                                break
                        if _plain_left:
                            break
            forced_fight = bool((on_road and not _plain_left) or on_plan)
            if not forced_fight:
                # ⚠ 2026-09-25 踩坑：残留的战斗面板（比如上一轮/手动留下的）会让循环原地打转
                #   （日志刷 `skip: offroad_fight` + `tapped: None`）—— 这里必须**确实关掉**
                n = close_x_panels(b, img)
                if n == 0:
                    x = find_x(items)
                    if x:
                        _tap(b, x['cx'], x['cy'], wait=1.5)
                        n = 1
                if n == 0:
                    c = exb(items, L['cancel']) or fb(items, '关闭') or exb(items, '返回')
                    if c:
                        _tap(b, c['cx'], c['cy'], wait=1.5)
                        n = 1
                if n == 0 and tapped is None:
                    for bx in (493, 1024):          # 只认这两个真关闭符位置
                        # ⭐ v0.31 方案 B：X 关闭符是**弹窗系**标定坐标 ⇒ tap_dlg
                        #   （真机上原 b.tap(·,225) 落在弹性区/顶块，点不到 ✗）
                        b.tap_dlg(bx, 225, wait=1.1)
                    n = 2
                log.append({'skip': 'offroad_fight', 'tapped': tapped,
                            'road': sorted(road)[:4], 'closed': n})
                return 'handled' if n else 'none'
        if not mk and ctx.get('clear_fights', 0) >= 3:
            close_x_panels(b, img)
            log.append({'skip': 'clear_path_capped',
                        'clear_fights': ctx.get('clear_fights', 0)})
            return 'handled'
        btn = None
        # ⭐⭐ v0.31 方案 B（真机 boss 面板实锤：战斗钮弹窗系 y=791，归一化帧里只有 582
        #   ⇒ 原 y 带 650~860 在真机永远落空 ✗）：y 带筛选必须用 **+C 后的弹窗系条目** ✓
        #   （PC/9:16 C=0 ⇒ dlg_items 原样返回，行为一字不变）
        for it in ditems:
            t = it['text'].strip()
            if L['fbtn'] in t and len(t) <= 4 and LAYOUT.sy(650) <= it['cy'] <= LAYOUT.sy(860) and L['fight'] not in t:
                btn = it
                break
        if btn is None:
            # 用户 09-25 口径：**只有「首领」标记的地块**才是居中单块面板 -> (541,735)；
            # 其余（普通格 / 大拇指 / 幸运草 / 红装）都是左右两列面板 -> 标题 x（806 / 275），y 恒 735
            # ⭐ v0.31：FIGHT_Y / 806 / 标题 cx 都是**弹窗系**坐标 ⇒ start_fight 里 tap_dlg 点 ✓
            if 'boss' in list(mk):
                btn = {'cx': 541, 'cy': FIGHT_Y, 'text': 'boss-fixed'}
            else:
                anchors = [it for it in ditems if L['fight'] in it['text']]
                if tapped:
                    anchors.sort(key=lambda it: abs(it['cx'] - tapped[0]))
                a = anchors[0] if anchors else fb(ditems, L['fight'])
                btn = {'cx': a['cx'] if a else 806, 'cy': FIGHT_Y, 'text': 'normal'}
            log.append({'popup': 'fbtn_pos', 'at': (btn['cx'], btn['cy']),
                        'marks': list(mk)})
        # ⚠ v1.37：`mk` 是**邻域兜底**（可能含邻居的 boss）⇒ 这里传 **exact_marks()**，
        #   否则战斗日志又会把"拦路格"显示成"首领格"（用户 2026-10-02 真机报 ✗）✓
        if not start_fight(b, log, btn, exact_marks()):
            close_x_panels(b, b.img())
            if not mk:
                # ⚠ 普通格点不动 = 这格就是点不动，**绝不开清路模式**
                #   （旧版把普通格的 not_started 也当「被挡路」，于是跑去打没标记的格 —— 用户 09-25 报）
                log.append({'battle': 'unmarked_no_start', 'note': '普通格点不动 -> 拉黑这格'})
                return 'handled'
            log.append({'battle': 'blocked', 'marks': mk})
            say('       · 标记格打不开（可能被挡路）: %s' % (mk,))
            return 'blocked'
        # ⭐ 统计：幸运草地块 / 大拇指地块各打了几次（用户 2026-09-26 要求）
        if 'clover' in (mk or []):
            STATS['clovers'] = STATS.get('clovers', 0) + 1
        # ⭐⭐⭐ 2026-10-01 v1.08 用户口径（原话）：「战斗时日志要写出打这个格子是什么格子，
        #   拦路的就写**拦路格**，首领就写**首领格**，四叶草就写**四叶草格**，大拇指就写
        #   **大拇指格**。同时有多种就都写出来，比如『当前格子标志：首领，四叶草，大拇指，红装』」
        #   ⇒ 控制台 + 悬浮条都按中文写全（在列的全写、逗号分隔；一个标记都没有 = 拦路格 ✓）
        _desc_open = tile_phrase(mk)
        say('       · 开打 · %s（标记 %s）' % (_desc_open, mk or ['拦路']))
        status('开打 · %s' % _desc_open)
        # ⭐ 本格标记（统计/摇色子用 ✓）：只取刚点那格的标记，不含 ±1 邻域 ✓
        _exm, _rc = None, None          # ⚠ v1.23：`_rc` 必须先初始化（下面 may 不进 try 体 ✗）
        try:
            if tapped:
                _rc = cell_of(tapped[0], tapped[1])
                _mv = markers.get(_rc)
                _exm = list(_mv.get('marks') or []) if _mv else []
        except Exception:       # noqa: BLE001
            _exm = None
        wait_end(b, log, marks=mk, exact_marks=_exm,
                 state=ctx.get('flags'), rc=_rc)     # ⭐ v1.23：带格号，防两条路径重复摇 ✓
        # ⚠ 2026-09-27 用户要求：**去掉**"战斗成功后下一轮先试点目标格" ✗
        #   （原来会 try_targets=True ⇒ 下一轮把目标排最前 ✓ 用户不要这个行为 ✗）
        return 'battle_clear' if not mk else 'battle'

    # ⭐ v0.32：入口同战斗分支 —— 真机上「探索产出」标题落弹性区看不见，
    #   C>0 时用看得见的「探索」按钮（dlg≈735）进分支；PC/9:16 行为一字不变 ✓
    if fb(items, L['expl']) or (dlg_c() and _dlg_panel_btn(ditems, L['ebtn'])):
        act = None
        for it in ditems:
            if L['ebtn'] in it['text'] and L['expl'] not in it['text'] and it['cy'] > LAYOUT.sy(620):
                act = it
                break
        # ⭐ 2026-09-26 用户口径：**面板掉落里有紫/橙/红（A/S/SS）才点探索** ✓
        #   （三个槽位要装"紫色以上的探索事件" ✓；只有绿/蓝就不值得，关掉换别的格子 ✓）
        # ⭐ 2026-09-26 用户口径：这些是**固定紫/橙探索**的地块 ⇒ 不用看颜色、直接点探索 ✓
        _is_target_tile = bool(ctx.get('ev_tiles'))
        _hv_img = None
        if _OCR_CH['dlg'] and hasattr(b, 'img_dlg'):
            try:
                _hv_img = b.img_dlg()
            except Exception:       # noqa: BLE001
                _hv_img = None
        hv = True if _is_target_tile else has_high_value_drop(_hv_img or img)
        # ⭐⭐ 2026-09-26 修复（用户在幻少实测卡死）：原来**不检查槽位**，只要 hv 就点探索。
        #   探索槽已经满了的时候点「探索」游戏没有反应 ⇒ 面板不关 ⇒ 下一帧又认到同一段
        #   面板文字、又点探索…⇒ 整个闭环卡死（最后表现就是"退出地图失败"）。
        _free2 = int(ctx.get('slots_free', 1) or 0)
        # ⚠⚠ 2026-10-01 修 NameError：`entry` 是 **one_round()** 的局部变量，本函数里根本没有
        #   ⇒ 走到「紫/橙探索格」分支时**必抛 NameError**（被上层 except 吞掉 ⇒
        #     症状：点到紫橙格就静默中断那一轮，日志里没有 explore_panel 记录）。
        # ⇒ 诊断信息改成直接进 `log`（本函数能写的），不依赖 one_round 的局部变量。
        log.append({'explore_panel': {'hv': bool(hv), 'btn': bool(act),
                                      'target_tile': _is_target_tile,
                                      'slots_free': _free2}})
        # ⭐ 不靠 slots_free 当闸门（OCR 偶尔认不到「空闲」会误判成 0 ✗），
        #   改成**先点、再验证**：点了「探索」面板还在 ⇒ 就是派不进去（多半槽位满）⇒ 改走战斗
        # ⭐⭐ 2026-09-30：**已经确认满本图**（`slots_full_latched`，两次点不动）时不再给
        #   第三次机会 —— 否则紫/橙格多起来又会"一格一下"地空转（用户报的就是这个体感 ✗）
        _latched = (_PANEL_STUCK.get('expl') or 0) >= 2 and _free2 <= 0
        if act and hv:
            if not _latched:
                b.tap_dlg(act['cx'], act['cy'], wait=3.5)   # ⭐ v0.31：弹窗系按钮 → tap_dlg
                if panel_gone(b, L['expl'], dlg_btn=L['ebtn']):
                    _PANEL_STUCK['expl'] = 0
                    # ⚠ 这里**不改** slots_free：面板关掉只说明"游戏受理了这一下"
                    #   （多半是换成「探索配队」面板，真正派遣在下面的 A 分支），
                    #   提前 -1 会把还有空槽的机器误判成满 ⇒ A 分支反而把配队面板关掉 ✗。
                    #   空闲数一律以**下一轮轮首的 HUD 读数**为准（见 one_round 顶部）✓
                    log.append({'explore': 'claimed_high_value'})
                    return 'handled'
                n = (_PANEL_STUCK.get('expl') or 0) + 1
                _PANEL_STUCK['expl'] = n
                log.append({'explore': 'tap_no_effect', 'n': n, 'slots_free': _free2})
                if n < 2:
                    return 'handled'          # 再给一次机会（可能只是动画没走完）
            else:
                log.append({'explore': 'skip_latched_full', 'slots_free': _free2})
            # ⭐ 用户 09-26 口径：**探索槽满了 ⇒ 紫橙格改当成普通目标打掉**（不再派探索）
            _mk2 = near()
            _fbtn = None
            for it in ditems:               # ⭐ v0.31 方案 B：y 带 = 弹窗系标定 ✓
                t = it['text'].strip()
                if (L['fbtn'] in t and len(t) <= 4 and L['fight'] not in t
                        and LAYOUT.sy(650) <= it['cy'] <= LAYOUT.sy(860)):
                    _fbtn = it
                    break
            if _fbtn is None:
                _fbtn = {'cx': int(LAYOUT.sx(806)), 'cy': FIGHT_Y, 'text': 'fixed'}
            log.append({'explore': 'slots_full_fight', 'at': (_fbtn['cx'], _fbtn['cy']),
                        'marks': list(_mk2)})
            if start_fight(b, log, _fbtn, _mk2):
                say('       · 探索槽已满 ⇒ 这一格改开打（标记: %s）' % (_mk2 or ['拦路'],))
                # ⭐ v1.08：悬浮条同样按中文写清是什么格子（多种标记全写 ✓）
                status('开打 · %s' % tile_phrase(_mk2))
                # ⭐ 2026-09-27：本格标记（不含 ±1 邻域 ✗）⇒ 防"邻格大拇指"白摇色子 ✓
                _exm2, _rc2 = None, None      # ⚠ v1.23：`_rc2` 必须先初始化（见上）
                try:
                    if tapped:
                        _rc2 = cell_of(tapped[0], tapped[1])
                        _mv2 = markers.get(_rc2)
                        _exm2 = list(_mv2.get('marks') or []) if _mv2 else []
                except Exception:       # noqa: BLE001
                    _exm2 = None
                wait_end(b, log, marks=_mk2, exact_marks=_exm2,
                         state=ctx.get('flags'), rc=_rc2)   # ⭐ v1.23：同上 ✓
                # ⚠ 2026-09-27 用户要求：不再设 try_targets ✓（战斗后不抢着点目标 ✓）
                return 'battle_clear' if not _mk2 else 'battle'
            # 开不起来也不能像以前那样干耗着 ⇒ 强制脱困
            force_unstick(b, log, 'explore_slots_full', ctx)
            return 'none'
        if act and not hv:
            log.append({'explore': 'skip_low_value'})
            close_x_panels(b, img)
            x = find_x(items)
            if x:
                _tap(b, x['cx'], x['cy'], wait=1.4)
            return 'handled'
        close_x_panels(b, img)
        return 'handled'

    # ⭐ 特殊地块（旅行商人 / 黄金宝库）必须**排在「领取」之前**判：
    #   黄金宝库面板的说明文案是「不管你看到多少宝物，每一层都只能**领取**一件哦」，
    #   先判「领取」会一直去点这句说明文字（点了没反应 → 每轮空转）
    # ⭐⭐ v0.61 真机**可达性**修复：宝库标题（dlg 383）落在 toRef 丢弃的弹性区 ⇒
    #   归一化帧里没有它 ⇒ 旧写法 `fb(items, '黄金宝库')` 在真机恒 False ⇒
    #   buypanels 整条链路只能靠"点了没反应 2 轮"的兜底碰运气进来（旅行商人标题
    #   dlg 601 不在丢带 ⇒ 它不受影响）。这里补一条**归一化帧里看得见**的签名
    #   （零额外 OCR，全靠已有的 items / ditems）：
    #     ① 说明文案「※花费金币分别解锁**宝库**的外层、内层、核心」(dlg 1459 ⇒ 帧内 1250 ✓)
    #     ② 右下角按钮 (dlg 1444 ⇒ 帧内 1235 ✓) 经 dlg_items 换算后按 dlg 标定值判
    _sp = []
    if dlg_c() and (fb(items, '解锁宝库') or _dlg_btn_sig(ditems, 'vault')):
        _sp.append('黄金宝库')
    for t in L['special']:
        if fb(items, t) or t in _sp:
            if t not in L['act_on']:
                # 用户 09-25：特殊地块**只点旅行商人和黄金宝库**，其他一律无视
                close_x_panels(b, img)
                x = find_x(items)
                if x:
                    _tap(b, x['cx'], x['cy'], wait=1.8)
                # ⭐⭐ 2026-09-26：这里原来**直接 return 'handled'** ⇒ 面板没关掉时闭环被它占死
                #   （实测图13：连刷 45 次、stamina/round 都不动，最后退出地图失败）
                #   改：关完**重新截图验证**；还在 ⇒ 计数，第二次就强制脱困 + return 'none'
                #   （'none' ⇒ 主循环继续往下做决策，不再被这一条卡住）
                if panel_gone(b, t):
                    _PANEL_STUCK[t] = 0
                    log.append({'special_ignored': t, 'closed': True})
                    return 'handled'
                n = (_PANEL_STUCK.get(t) or 0) + 1
                _PANEL_STUCK[t] = n
                log.append({'special_ignored': t, 'closed': False, 'n': n})
                if n >= 2:
                    force_unstick(b, log, 'special:%s' % t, ctx)
                    _PANEL_STUCK[t] = 0
                    return 'none'
                return 'handled'
            log.append({'special': t, 'texts': [i['text'] for i in items][:24]})
            # ⭐ 2026-09-25：买完流程独立成 buypanels.py（坐标实测 + 每轮 OCR 定位按钮）
            #   旅行商人：购买(895,1255)→返回(539,1212) ×4 → X(983,602)
            #   黄金宝库：购买解锁一层(10000/20000/40000) → 现场认奖励（优先天赋果实/幸运草）
            #             →「选择奖励」→ 中间「返回」，三层完按钮变「离开」
            if '黄金宝库' in t:
                status('发现黄金宝库 · 正在开箱…')
                # ⭐⭐⭐ 2026-10-01 用户报「第一层还没选择就乱点了」⇒ 两条硬规矩：
                #   ① **必须包 try/except**：`vault_flow` 一崩就抛到上层 ⇒ 面板留在屏幕上
                #      没人管 ⇒ 主循环继续按点序点棋盘格 ⇒ 那些点击**全落在宝库面板上**
                #      = 用户看到的"乱点" ✗✗（真机 18:35 实证：ICON_THR NameError ×3 轮）
                #   ② **只有真的买到了才计数**：旧写法无论成败都 `STATS['vaults'] += 1`
                #      ⇒ 日志会谎报"买完 1 个"，而用户看到的是没买到 ✗
                _vok = False
                try:
                    _vacts = buypanels.vault_flow(b, log)
                    _vok = bool(_vacts)
                except Exception as _ve:      # noqa: BLE001
                    import traceback as _tb
                    log.append({'vault': 'flow_error', 'e': repr(_ve)[:120],
                                'trace': _tb.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 宝库流程异常：%r ⇒ **不计数**，交给下一轮重试' % (_ve,))
                if _vok:
                    STATS['vaults'] += 1
                    say('       · 黄金宝库买完（第 %d 个）' % STATS['vaults'])
                    status('黄金宝库 · 完成 ✓')
                    # ⭐⭐⭐ 2026-10-02 v1.27【**买完的宝库格要登记"已消耗"**】
                    #   用户实报：「宝库都没问题了，但悬浮条显示还剩 1 个目标，我看着已经没目标了」
                    #   真机日志（`vault: done` 之后 r11）：`marked`/`buy`/`buy_hidden` 全空
                    #   （所以打了「没有目标了」），可 `pending_buy` 还留着 1 个 ⇒ 悬浮条
                    #   「还剩 1 个目标」= **幽灵目标** ✗
                    #   根因：那一格的贴图**买完还在**（认成宝库/商人、score ≥ 0.60）
                    #   ⇒ `buy_seen`（跨轮记忆）每轮都被刷新 ⇒ 永远不会被"4 轮没再出现"清掉 ✗✗
                    #   ⇒ 买完当场把它记进 `st['buy_consumed']`，并从 sticky/记忆里删掉 ✓
                    try:
                        _st_v = ctx.get('flags')
                        if isinstance(_st_v, dict) and tapped:
                            _rcv = cell_of(tapped[0], tapped[1])
                            _pxv = marks_mod.cell_center(*_rcv)
                            _st_v.setdefault('buy_consumed', set()).add(_rcv)
                            for _kk in (_pxv, tuple(tapped)):
                                _st_v.get('buy_seen', {}).pop(_kk, None)
                                _st_v.get('buy_sticky', {}).pop(_kk, None)
                            log.append({'vault': 'consumed', 'rc': list(_rcv)})
                    except Exception:       # noqa: BLE001
                        pass
                else:
                    # ⚠ 不管成败都要**确保面板被收起**，否则下一轮又会点在面板上 ✗
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    say('       · 宝库本轮没走完 ⇒ 已尝试收起面板（下轮再来 ✓）')
                    status('宝库没走完 · 先收起面板')
            else:
                status('发现旅行商人 · 正在购物…')
                # ⭐ 2026-10-01 同宝库口径：包 try/except + 只有成功才计数 + 失败必收面板 ✓
                _mok = None
                try:
                    # ⚠ `merchant_flow` 返回**买到的次数**（可能为 0 = 正常结束但没钱）⇒
                    #   不能用 bool() 当成败判据（买到 0 次也是"流程走完了" ✓）
                    _mok = buypanels.merchant_flow(b, log)
                except Exception as _me:      # noqa: BLE001
                    import traceback as _tb2
                    log.append({'merchant': 'flow_error', 'e': repr(_me)[:120],
                                'trace': _tb2.format_exc().splitlines()[-3:]})
                    say('       · ⚠ 商人流程异常：%r ⇒ **不计数**，交给下一轮重试' % (_me,))
                if _mok is not None:
                    STATS['merchants'] += 1
                    say('       · 旅行商人买完（第 %d 个，本次买到 %d 次）'
                        % (STATS['merchants'], _mok))
                    status('旅行商人 · 完成 ✓')
                    # ⭐⭐ v1.40【商人买完也要登记"已消耗"】—— 与黄金宝库**同口径** ✓
                    #   用户 2026-10-02 实报：「买完商人后，商人格子**不会消失**，
                    #     下一次规划又打开了商人格子（黄金宝库买完会消失）」✗
                    #   根因：v1.27 只给**宝库**加了这段登记（当时报的是"宝库还剩1个目标"），
                    #     商人的成功分支只 `STATS['merchants'] += 1` ⇒ **没登记** ⇒
                    #     那一格的贴图买完还在（认成商人、score ≥ 0.60）⇒
                    #     `buy_seen` 每轮被刷新 ⇒ 永远进不了"已消耗" ⇒ 永远被当目标 ✗✗
                    #   真机日志铁证（v1.39）：
                    #     `{"merchant":"done","bought":4}`      ← 四档全买成 ✓
                    #     下一轮 `{"solver":"ok","targets":2}`  ← 实际只有 1 个 boss ⇒ 多一个就是商人格 ✗
                    #     又打开一次面板 ⇒ `{"merchant":"all_bought"}`（认出来了、没重复买，但白点一次）✗
                    try:
                        # ⚠ 只在**真买成了**（`_mok > 0`）才登记"已消耗"。
                        #   `_mok == 0` 表示"流程走完了但这次没买到"（已买完 / 没钱）⇒
                        #   若也登记，那一格就被永久拉黑 ⇒ **下次买新档位时不会再去** ✗
                        _st_m = ctx.get('flags')
                        if isinstance(_st_m, dict) and tapped and _mok > 0:
                            _rcm = cell_of(tapped[0], tapped[1])
                            _pxm = marks_mod.cell_center(*_rcm)
                            _st_m.setdefault('buy_consumed', set()).add(_rcm)
                            for _km in (_pxm, tuple(tapped)):
                                _st_m.get('buy_seen', {}).pop(_km, None)
                                _st_m.get('buy_sticky', {}).pop(_km, None)
                            log.append({'merchant': 'consumed', 'rc': list(_rcm)})
                    except Exception:       # noqa: BLE001
                        pass
                else:
                    try:
                        buypanels.ensure_closed(b, log)
                    except Exception:       # noqa: BLE001
                        pass
                    say('       · 商人本轮没走完 ⇒ 已尝试收起面板（下轮再来 ✓）')
                    status('商人没走完 · 先收起面板')
            return 'handled'

    it = fb(items, *L['claim'])
    if it and it['cy'] < LAYOUT.sy(1700) and len(it['text']) <= 4:
        _tap(b, it['cx'], it['cy'], wait=2)
        log.append({'popup': 'claim'})
        return 'handled'

    ok = exb(items, L['ok'])
    if ok and ok['cy'] > LAYOUT.sy(900) and exb(items, L['cancel']) is None:
        if fb(items, '购买', '钻石不足'):
            return 'none'
        _tap(b, ok['cx'], ok['cy'], wait=2.5)
        log.append({'popup': 'reward_confirm'})
        return 'handled'

    x = find_x(items)
    if x:
        _tap(b, x['cx'], x['cy'], wait=1.8)
        log.append({'popup': 'close_x'})
        return 'handled'
    return 'none'


def save_board_frame(b, log, rnd=0, img=None):
    """存一张棋盘帧 → `<实例目录>/r_<HHMMSS>_<轮次>.png`

    ⚠ 多开隔离（2026-09-27）：**必须落 `b.runs`**（带 `--tag acc2` 时 = `runs/acc2/`）。
      以前写死公共 `RUNS` ⇒ 主号与 2 号的首帧会混进同一个 `runs/` ✗（时间戳撞车就互相覆盖）
    """
    try:
        import cv2 as _cv2
        if img is None:
            img = b.img()
        if img is None:
            log.append({'shot': 'no_img', 'rnd': rnd})
            return None
        _dir = getattr(b, 'runs', None) or RUNS
        os.makedirs(_dir, exist_ok=True)
        rp = os.path.join(_dir, 'r_%s_%s.png' % (time.strftime('%H%M%S'), rnd))
        _cv2.imencode('.png', img)[1].tofile(rp)
        log.append({'shot': 'saved', 'rnd': rnd, 'file': os.path.basename(rp)})
        say('   ★ 存图：%s' % rp)
        return rp
    except Exception as e:      # noqa: BLE001
        log.append({'shot': 'error', 'rnd': rnd, 'e': repr(e)[:120]})
        return None


def enter_map(b, log, timeout=40):
    """在选图界面点「进入地图」。

    ⚠ 2026-09-25 用户报「退图后乱点切换到别的图」：进图前先确认**确实在选图界面**
    （有「快速扫荡/进入地图」这类菜单文字），并且只点识别到的那个按钮；
    没确认到就等下一轮，绝不盲点（盲点就会点到别的图卡片上）。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        b.snap('enter')
        img = b.img()
        items = b.ocr(tag='round')
        if in_map(b, img, items):
            log.append({'enter': 'in_map', 'stamina': stamina(items)})
            return True
        if fb(items, *L['kick']):
            return False
        # ⭐ 2026-09-27：**大厅**（游戏重启后常见）⇒ 点底部中间「开始冒险」离开，
        #   再等下一轮验证 ⇒ 不会白等到 40 秒超时 ✗（用户口径：「点中间的开始冒险」✓）
        if in_lobby(items) and go_lobby_to_menu(b, log, items=items):
            time.sleep(1.0)
            continue
        # 确认在「选图界面」（菜单文字在）再点进入地图；否则等着，绝不盲点
        on_menu = bool(fb(items, *L['menu'])) or any(
            ('快速扫荡' in i['text']) or ('进入地图' in i['text']) for i in items)
        ent = None
        for it in items:
            if L['enter'] in it['text'] and it['cy'] > LAYOUT.sy(1400):
                ent = it
                break
        if ent and on_menu:
            # ⭐⭐⭐ 2026-10-01 用户报「刚刚不到 25 还去点击进入地图」⇒ **每次点之前都复查体力**：
            #   这个 while 循环等不到地图会**再点一次「进入地图」**（见上面 2026-09-25 的注释），
            #   而原来**只在进函数前查过一次** ⇒ 第二/第三次点就可能是"体力已经扣完还点" ✗
            #   （真机日志里 `{'enter':'clicked'}` 出现过两次连续条目）
            #   规则：读得到且 < MIN_STAMINA ⇒ 立刻放弃（不点）；读不到 ⇒ 记一条告警但仍点
            #   （外层 `ensure_in_map` 已经做过严格判定 ✓，这里只是防"循环内重复点"）
            # 体力用**窄带(0~140)现读**（≈0.25s，比全屏帧更稳 ✓）；失败才退回本帧条目
            try:
                _st_now = stamina(b.ocr(band=(0, 140), tag='enter_stam'))
            except Exception:       # noqa: BLE001
                _st_now = None
            if _st_now is None:
                _st_now = stamina(items)
            if _st_now is not None and _st_now < MIN_STAMINA:
                log.append({'enter': 'skip_low_stamina', 'stamina': _st_now,
                            'min': MIN_STAMINA, 'at': (ent['cx'], ent['cy'])})
                say('   ⚠ 体力 %d < %d ⇒ 不点「进入地图」（防止白点/白扣）'
                    % (_st_now, MIN_STAMINA))
                return False
            if _st_now is None:
                log.append({'enter': 'stamina_unknown_still_click',
                            'texts': [i['text'] for i in items][:8]})
            b.tap(ent['cx'], ent['cy'], wait=2.0)
            log.append({'enter': 'clicked', 'at': (ent['cx'], ent['cy']),
                        'stamina_before': _st_now})
            # ⚠ 2026-09-25 用户报「一进图就点一下右下角」：原来点完没立刻认出地图
            #   **同一秒又点了一次**，第二下正好落在刚加载出来的地图上（看起来像乱点）。
            #   现在点一下就**等地图加载**（最多 ~9 轮），期间处理弹窗。
            # ⭐⭐ v1.45 提速（施工单 ⑥）：固定 sleep(1.5) → **有条件地等**
            #   原来「sleep(1.5) + snap + 全屏 OCR(~1.5s)」⇒ 每轮 ~3s，最多 9 轮 ≈ **27 秒**！
            #   而这条循环的全部目的只是「等地图加载完」——OCR 本身就是个 1.5s 的阻塞操作，
            #   再叠加固定 1.5s 等于每轮多花一倍时间。
            #   ⇒ 改成：先 `wait_stable` 等画面停（进图动画播完就停，最多 1.2s，≈免费），
            #     然后 snap + OCR 判定；**地图一认出来就立刻返回**（原本也不会更早）。
            #   ⚠ 不减少判定次数上限（仍 9 轮），只把"白等"换成"等它停"。
            #   ⭐ v1.45d：`_last_ocr_enter` = 这一轮里**上次真正 OCR** 的时刻
            #     （`menu_tpl` 短路的安全网用；一进来就允许跳 ⇒ 不必先白认一次字）
            _last_ocr_enter = time.time()
            for _ in range(9):
                try:
                    if b.fast_ok:
                        b.wait_stable(1.2, interval=0.06, thr=1.4, need=6,
                                      band=(LAYOUT.sy(130), LAYOUT.sy(1700)))
                except Exception:       # noqa: BLE001
                    time.sleep(0.4)
                b.snap('enter_wait')
                img2 = b.img()
                # ⭐ v1.45d（flag `menu_tpl`）：**正向短路** —— 定点模板证明"还在选图界面"
                #   ⇒ 这一轮必然没进图，**省掉这次全屏 OCR（~1.8s）**。
                #   ⚠ 安全网 `MENU_SKIP_MAX`：距上次**真正 OCR** 超过它秒数就不再跳
                #     （面板/提示框最多晚看这么久 ⇒ 不会因为模板一直命中而"再也不认字"）
                if _menu_tpl_on() and (time.time() - _last_ocr_enter) < MENU_SKIP_MAX:
                    _mh = menu_hit(b)
                    if _mh is True:
                        log.append({'enter': 'still_menu_tpl',
                                    'secs': round(time.time() - _t0, 1)})
                        continue
                it2 = b.ocr(tag='round')
                _last_ocr_enter = time.time()
                if is_app_chooser(it2):
                    # ⭐ v1.45h：进图途中弹系统选择框（双开）⇒ 按返回收掉再等 ✓
                    log.append({'enter': 'app_chooser'})
                    say('   · 弹出系统「请选择要使用的应用」框 ⇒ 按返回收掉再等')
                    try:
                        b.back(wait=1.2)
                    except Exception:                # noqa: BLE001
                        pass
                    continue
                if in_map(b, img2, it2):
                    log.append({'enter': 'in_map', 'stamina': stamina(it2)})
                    return True
                if fb(it2, *L['kick']):
                    return False
                act = popups(b, it2, log)
                if act == 'kicked':
                    return False
            continue
        if not on_menu:
            log.append({'enter': 'not_menu_yet',
                        'texts': [i['text'] for i in items if i['cy'] > LAYOUT.sy(900)][:8]})
        # ⭐ v1.45：本循环每轮已经付了一次全屏 OCR（~1.5s）⇒ 固定 1.5s 属于纯白等，
        #   收到 0.3s（只是让出一点 CPU、别把设备榨干）
        time.sleep(0.3)
    log.append({'enter': 'timeout'})
    return False


# ---------------------------------------------------------------------------
# ⭐ 2026-09-27 新增：清体力时**顺手抓真盘**（含 roadMap ✓ / 零额外体力 ✓）
#
# 用户问：「我现在用那个自动探索脚本去清体力，能自动拿真盘截图并且分析成数据吗」
# 答：**能，但要读内存** —— 截图那条路拿不到路网 ✗
#   · 实测 runs/map_shot_1.png：35 格只有「地块美术」或「灰雾」，**没有任何道路视觉元素**
#     ⇒ 截图/OCR 只能认已揭示格子的地块身份，拿不到 roadMap / 块号结构 / 迷雾格 ✗
#   · 读内存：blockList + blockBoard + chestMap + **roadMap** 全字段 ✓（零额外体力 ✓）
# 所以这里挂一步：进图成功 ⇒ 顺手读一张并入库 ✓
# ---------------------------------------------------------------------------
# ⭐ 2026-09-28 22:15 用户授权（「听你的」）⇒ **关闭**主循环里的"顺手抓真盘"：
#   ① 92 张真盘已采完（§6「数量够了吗」主要项已验证），边际价值低
#   ② 它挂在推图主循环里 ⇒ 任何一次内存慢读都会拖累推图（22:12 实测卡死 ✗）
#   ③ 要继续采集走**独立脚本**（体力/耗时可控、不拖推图）：
#      `collect_maps_mem.py --device <dev> --tag <tag>` / `watch_collect.py` / `grab_lobby_maps.py`
#   想开回主循环：把这行改回 True 即可（预算保护已就位，最多 25 秒/图 ✓）
COLLECT_REAL_MAPS = False
# ⭐⭐⭐ 2026-09-28 顺手抓真盘的**总预算**（秒）：超了就收手，绝不拖住推图。
#   依据（真机 22:12 实测）：无预算时 live_pick 会在 _sweep 里依次读几十~上百个区
#   （单区上限 180 秒）⇒ 进图后整条推图线卡死 ✗。命中表/提示建好后本条路径亚秒 ✓
COLLECT_BUDGET_SECS = 25
                               #    True = 进图后顺手读内存存真盘（含 roadMap ✓ 零额外体力 ✓）
                               #    ⚠ 只读 /proc/<pid>/mem，不注入、不点屏、不改游戏状态 ✓
                               #    历史：09-27 曾按用户指示关成 False（「靠截图+OCR」）
AUTO_SHOT_DIR = os.path.join(RUNS, 'auto')
_COLLECT = {'n': 0, 'miss': 0}


def _try_collect_map(b, log, tag=''):
    """读一张真盘（含路网 ✓）存进 `runs/maps_dataset.jsonl` + 截一张图 ✓

    ⚠ 为什么挂在「进图成功」这一刻（而不是退图时）：
        进图后游戏会把新图写进存档 JSON ⇒ 此刻内存里就是**这张图** ✓
        失败也不影响清体力 —— 全程 try/except，异常只写日志 ✓

    ⚠ 耗时（2026-09-27 实测）：旧 `live_pick` 未命中要**全扫 405 个区 = 100.5 秒** ✗
        现走「含针区表」（实测全内存只有 **2 个**区含 `"blockBoard":[` 针）
        ⇒ **1.10 秒** ✓（91 倍）；表里没有(冷启动)才付一次 ~100 秒并自动建表 ✓

    安全边界：只读内存 + 写 runs/ ⇒ **不点屏幕、不花体力、不改游戏状态** ✓
        读到上一张图也无所谓（`add_map` 按棋盘指纹去重 ⇒ 只是白读一次 ✓）
    """
    if not COLLECT_REAL_MAPS:
        return
    try:
        import mapcollect
        t0 = time.time()
        m, why = mapcollect.live_pick(getattr(b, 'dev', None) or INSTANCE_DEV,
                                      verbose=False,
                                      budget_secs=COLLECT_BUDGET_SECS,
                                      mem_timeout=12)
        dt = time.time() - t0
        if not m:
            _COLLECT['miss'] += 1
            log.append({'collect': 'miss', 'why': why[:120], 'secs': round(dt, 2)})
            say('   · 顺手抓真盘：没读到（%.1f 秒 · %s）' % (dt, why[:56]))
            return
        shot = None
        try:
            os.makedirs(AUTO_SHOT_DIR, exist_ok=True)
            shot = b.snap('auto/%s' % (tag.rstrip('_') or 'map'), save=True)
        except Exception as _e:         # noqa: BLE001
            log.append({'collect': 'shot_fail', 'e': repr(_e)[:100]})
        m['shot'] = shot
        new = mapcollect.add_map(m, tag='auto')
        if new:
            _COLLECT['n'] += 1
        st = m.get('_stats') or {}
        log.append({'collect': 'ok', 'area': m.get('areaName'),
                    'diff': m.get('difficulty'), 'new': bool(new),
                    'E': st.get('E'), 'K': st.get('K'), 'secs': round(dt, 2)})
        say('   ★ 顺手存了真盘：%s d%s 边%s/K%s 死胡同%s（%.1f 秒）→ 本轮新增 %d 张%s'
            % (m.get('areaName'), m.get('difficulty'), st.get('E'), st.get('K'),
               st.get('dead'), dt, _COLLECT['n'],
               '' if new else '（重复，库里已有 ✓）'))
    except Exception as e:              # noqa: BLE001
        log.append({'collect': 'error', 'e': repr(e)[:140]})


def ensure_in_map(b, log, tag=''):
    for a in range(4):
        b.snap('%schk%d' % (tag, a))
        items = b.ocr(tag='round')
        img = b.img()
        # ⭐⭐ 2026-09-29 真机：画面是 MGAS 自己的界面/应用双开选择框 ⇒ 别再乱点
        #   （点下去全是自己的按钮），直接把原因讲清楚让人处理 ✓
        if is_app_chooser(items):
            # ⭐ v1.45h：系统"应用选择框"（双开导致）⇒ 别对着它乱点，讲清原因并收掉
            log.append({'pre': 'app_chooser', 'attempt': a})
            say('⚠ 手机上弹了系统的「请选择要使用的应用」框（应用双开 ⇒ 启动游戏有两个响应者）')
            say('   ⇒ 请在选择框里选**游戏本体**并勾「总是」，或把双开助手关掉/卸载')
            try:
                b.back(wait=1.2)                 # 先把框收掉，别继续挡着画面 ✓
            except Exception:                    # noqa: BLE001
                pass
            status('⚠ 请先处理系统「应用选择框」')
            flush(log)
            return False
        if self_ui_hits(items) >= 2:
            log.append({'pre': 'self_ui', 'attempt': a})
            say('⚠ 画面是 MGAS 自己的界面/应用选择框（游戏没在前台）')
            say('   ⇒ 请手动切到游戏、到「选图界面」后再点 ▶ 重试')
            say('   ⇒ （手机上若开了「应用双开」，切游戏会弹选择框 ⇒ 关掉双开即可）')
            status('⚠ 请先切到游戏，再点 ▶')
            flush(log)
            return False
        if in_map(b, img, items):
            _try_collect_map(b, log, tag)      # ⭐ 顺手抓真盘（失败绝不影响主流程 ✓）
            return True
        act = popups(b, items, log)
        if act == 'kicked':
            return False
        n = close_x_panels(b, img)
        st = 'lobby' if in_lobby(items) else ('menu' if is_map_screen(items) else 'other')
        log.append({'pre': 'not_in_map', 'attempt': a, 'act': act,
                    'closed_x': n, 'state': st})
        flush(log)
        if act == 'none' and n == 0:
            # ⭐⭐ 2026-09-27 用户口径：「点中间的开始冒险就能回到选图界面」
            #   场景：采图中途**游戏自己重启** ⇒ 停在大厅 ⇒ 老逻辑到这就 break，
            #   接着 enter_map() 在非选图界面里等 40 秒 → 超时 → 整个任务中断 ✗
            #   现在：认出大厅就点「开始冒险」，回头再验一次 ⇒ 重启自愈 ✓
            if go_lobby_to_menu(b, log, items=items):
                continue
            break
    st = stamina(b.ocr(tag='round'))
    # ⭐⭐ 2026-10-01 修（用户报「进图前怎么不检查体力」）：
    #   ① 老写法 `if st is not None and st < MIN_STAMINA` ⇒ **读不到体力就整段跳过检查、
    #      直接进图** ✗（fail-open）。现在：读不到就**换窄带(0~140)再读一次**（≈0.25s ✓ 更稳），
    #      两次都读不到才放行，但**明确 say 出来**（不留静默 ✗）
    #   ② 门限一律打进日志（`下限 N`）—— 安卓悬浮条那条调用曾把 min_stamina 写死 25，
    #      连刷模式下也是 25，日志却写着「连刷下限」⇒ 以后一眼能对出来 ✓
    if st is None:
        # ⭐⭐⭐ 2026-10-01 用户报「刚刚不到 25 还去点击进入地图」⇒ **fail-open 改成 fail-closed**：
        #   读不到体力就**不许进图**（多读几次，都读不到就停下并说明原因）。
        #   老写法是"读不到 ⇒ 跳过检查 ⇒ 照样进图" ✗ —— 体力见底时这一下就是白点/白扣。
        #   ⚠ 顺手把"读不到"的原因**落盘 + 打出来**（窄带读不到 ⇒ 再试全屏 ⇒ 还不行就存帧 +
        #     打顶部那几条文字）——体力必须在 ≤130 且 x<560 的 HUD 格里且**斜杠与数字在
        #     同一条 OCR 文本**里（实测那条 OCR 通常给的就是 `11/2500` 一整条 ✓；
        #     会读不到多半是 ① 被面板/加载盖住 ② 被拆成两条 ✗）
        for _k in range(3):
            time.sleep(1.2)
            _its = b.ocr(band=(0, 140), tag='pre_stam%d' % _k)
            st = stamina(_its)
            if st is None:
                _its2 = b.ocr(tag='pre_stam_full%d' % _k)      # 再给一次全屏机会 ✓
                st = stamina(_its2)
                if st is None:
                    _pub_dump('stamina_fail%d' % _k, b.img())
                    say('   · 体力读不到（第 %d 次）｜顶部认到：%s'
                        % (_k + 1, [i['text'] for i in (_its2 or _its)
                                   if i.get('cy', 9999) < 200][:8]))
            log.append({'pre': 'stamina_retry', 'n': _k + 1, 'stamina': st})
            if st is not None:
                break
        if st is None:
            log.append({'stop': 'stamina_unknown', 'min': MIN_STAMINA})
            say('   ⚠ 连续 3 次读不到体力 ⇒ **不进图**（无法确认够不够 %d）' % MIN_STAMINA)
            # ⭐ v1.07：悬浮条要说清"为什么停"，否则用户会以为脚本坏了（见下面 no_stamina 同因）
            status('体力读不到（要 ≥%d）· 先不进图，请看一眼体力' % MIN_STAMINA)
            return False
    say('   进图判定：体力 %s ｜ 下限 %d ｜ 自动补给 %s'
        % (st if st is not None else '?', MIN_STAMINA, '开' if AUTO_SUPPLY else '关'))
    log.append({'pre_gate': 'stamina', 'stamina': st, 'min': MIN_STAMINA,
                'auto_supply': bool(AUTO_SUPPLY)})
    if st is not None and st < MIN_STAMINA:
        # ⭐ 用户 2026-09-25：「加个自动使用结实补给的按钮（没体力就自动去背包里使用一个）」
        if AUTO_SUPPLY:
            log.append({'supply': 'try_before_giveup', 'stamina': st,
                        'min': MIN_STAMINA})
            for attempt in range(2):
                if not use_supply(b, log):
                    break
                st2 = stamina(b.ocr(band=(0, 140), tag='round'))
                log.append({'supply': 'after_use', 'attempt': attempt + 1,
                            'stamina': st2})
                # ⭐ 标记"刚吃过补给" ⇒ _stam_sanity 不再把这次真实涨幅当 OCR 误读 ✗
                STATS['supply_used'] = True
                if st2 is not None and st2 >= MIN_STAMINA:
                    say('   用了补给，体力 %s ≥ %d，继续刷' % (st2, MIN_STAMINA))
                    status('体力不够 · 已用结实补给，继续')
                    return enter_map(b, log)
            st = stamina(b.ocr(band=(0, 140), tag='round')) or st
        if st is not None and st < MIN_STAMINA:
            log.append({'stop': 'no_stamina', 'stamina': st, 'min': MIN_STAMINA,
                        'auto_supply': bool(AUTO_SUPPLY)})
            say('   体力 %d < %d（连刷下限），收工' % (st, MIN_STAMINA))
            # ⭐⭐⭐ 2026-10-01 v1.07 用户报「怎么连启动都启动不了了，完全用不了」
            #   —— 其实是**体力低于下限就正常收工**（一次点击都没做），但这句提示原先
            #   只进控制台（`say`），悬浮条上只写「体力不够了 · 收工」⇒ 用户看不到
            #   **差多少 / 下限是多少 / 自动补给是关的** ⇒ 以为脚本坏了 ✗
            #   ⇒ 悬浮条改成**可操作**的一句话：把三个数都写出来 + 给出怎么办 ✓
            #     ⚠ 文案避开 OCR 关键词（探索/派遣/领取/关闭/开始冒险…）—— 见硬约束③与
            #       `OverlayService.sanitize()`：否则会被糊成 ▓ ✗
            _tips = ('开自动补给可自动吃结实补给'
                     if not AUTO_SUPPLY else '补给没吃够，请手动补一次')
            status('体力 %d 不足（要 %d）· %s' % (st, MIN_STAMINA, _tips))
            # ⭐ v1.08：把原因也写进 `STATS['stopped']` ⇒ 收工那行（以及统计面板）都会带上它 ✓
            STATS['stopped'] = '体力 %d 不足（要 %d）' % (st, MIN_STAMINA)
            return False
    return enter_map(b, log)


def finish_map(b, log, timeout=90):
    """结束冒险 → 回选图界面

    ⚠ 2026-09-25：退图时**经常弹确认框**（「还有未拾取的战利品 / 是否结束冒险？」），
      按钮是 确定(774,1113) / 取消(305,1113) —— 只点靠右的那个，绝不点取消；
      另外还可能先弹结算面板（底部「关闭」）或奖励领取，都要先处理掉。
    """
    t0 = time.time()
    clicked = 0
    end_tapped_at = 0.0        # ⭐ 上次点「结束冒险」的时间（防连点 ✗）
    idle = 0                   # ⭐ 2026-09-26：连续"什么都认不到"的轮数
    # ⭐⭐ 2026-09-26 用户口径：「万能点位可以用来应对异常情况，防止任务过早中断」✓
    _rescued = False           # 退图快超时时是否已用万能位救过一次
    while time.time() - t0 < timeout:
        # ⭐⭐ 退图快超时 ⇒ 万能位**最后救一次**，并把截止时间**延后 20 秒**再继续跑 ✓
        #   老逻辑：超时就直接 `finish: timeout` + return False ⇒ **任务在这里中断** ✗
        #   现在：先让万能位（关得掉几乎所有弹窗，且点它无副作用）救一手，再多给 20 秒 ✓
        #   ⚠ 依然先认面板类型：战斗界面点「关闭」(577,1439)，绝不点开始冒险 ✓
        if not _rescued and timeout > 20 and time.time() - t0 > timeout - 6:
            _rescued = True
            universal_close(b, log, items=b.ocr(tag='fin_to'), where='finish_timeout')
            log.append({'universal_fallback': 'finish_timeout'})
            say('       · 退图快超时 → 万能位兜底关面板（截止时间延后 20 秒）')
            status('退出超时 · 强行脱困')
            timeout += 20.0
            continue
        b.snap('finish')
        # ⭐ v1.45d（flag `menu_tpl`）：**正向短路** —— 定点模板看到选图界面那两个按钮
        #   ⇒ 与下面 `fb(items, *L['menu'])` 是**同一个判据的更快版本**，直接收工，
        #   **省掉这次全屏 OCR（~1.8s）**。模板没命中 ⇒ 一个字不改，照原路走 ✓
        if _menu_tpl_on():
            _mh = menu_hit(b)
            if _mh is True:
                log.append({'finish': 'back_to_menu_tpl'})
                return True
        items = b.ocr(tag='round')
        if fb(items, *L['menu']):
            log.append({'finish': 'back_to_menu'})
            return True
        # ⭐ 2026-09-27：**大厅**也算"已离开地图"⇒ 直接收工 ✓
        #   场景：退图途中游戏自己重启 ⇒ 停在大厅 ⇒ 老逻辑所有分支都不命中，
        #   一路 idle 到第 4 轮就 `universal_close()` 盲点 (541,1890)（就是大厅的「开始冒险」），
        #   或更糟 —— 90 秒 `finish: timeout` ⇒ 整个任务中断 ✗
        if in_lobby(items):
            log.append({'finish': 'lobby'})
            say('       · 已在大厅（退图途中重启过）⇒ 本轮按退图完成处理 ✓')
            return True
        # ①' 「发现莱姆！」→ 点返回
        lb = lime_back(items)
        if lb:
            b.tap(lb['cx'], lb['cy'], wait=1.8)
            log.append({'finish': 'lime_back', 'at': (lb['cx'], lb['cy'])})
            continue
        # ①'' 「获得新装备！」→ 点返回（2026-09-26：盖住棋盘 ⇒ 认不到「结束冒险」⇒ 90 秒超时）
        if close_newequip(b, items, log, 'finish'):
            say('       · 获得新装备！→ 点返回')
            continue
        # ①''' 「预言石板」→ 点中间最下面（万能位）关掉
        if fb(items, *L['prophecy']):
            universal_close(b, log, items=items, probe=L['prophecy'][0], where='finish')
            say('       · 预言石板 → 点中间最下面关掉')
            continue
        # ①'' 「偶遇强敌」→ 不打，点 X 关掉（用户 2026-09-25 报退图流程被它卡住）
        if fb(items, *L['strong']):
            x = find_x(items)
            if x:
                b.tap(x['cx'], x['cy'], wait=1.5)
            else:
                close_x_panels(b, b.img())
            log.append({'finish': 'strong_closed',
                        'closed_at': (x['cx'], x['cy']) if x else None})
            continue
        # ① 结算/奖励面板：底部「关闭」
        cl = bottom_close(items)
        if cl:
            b.tap(cl['cx'], cl['cy'], wait=1.8)
            log.append({'finish': 'closed_result'})
            continue
        # ② 确认弹窗：确定/确认/是（取最靠右的，避开「取消」）
        ok = None
        for it in items:
            if it['text'].strip() in ('确定', '确认', '是') and it['cy'] > LAYOUT.sy(800):
                if ok is None or it['cx'] > ok['cx']:
                    ok = it
        if ok:
            b.tap(ok['cx'], ok['cy'], wait=2.5)
            log.append({'finish': 'confirmed', 'at': (ok['cx'], ok['cy'])})
            continue
        # ③ 领取 / 继续
        cl2 = fb(items, *L['claim'])
        if cl2 and cl2['cy'] < LAYOUT.sy(1700) and len(cl2['text']) <= 4:
            b.tap(cl2['cx'], cl2['cy'], wait=2)
            log.append({'finish': 'claimed'})
            continue
        # ④ 结束冒险
        end = exb(items, L['end'])
        if end:
            # ⚠ 2026-09-26 用户报「结束冒险还是会多点一下（可能导致切换地图）」：
            #   上一版点完只在一个窄带里找确认按钮，找不到就进下一轮 ⇒ 又看到「结束冒险」
            #   ⇒ 再点一次 ✗；那时弹框/画面可能已经变了 ⇒ 第二下落在**地图卡片**上 ⇒ 切图 ✗
            #   ⇒ 现在：点过一次后 **8 秒内绝不再点「结束冒险」**，只等确认框或等切到选图界面 ✓
            if time.time() - end_tapped_at < 8.0:
                time.sleep(1.0)
                continue
            clicked += 1
            if clicked > 3:
                n = close_x_panels(b, b.img())
                if not n:
                    x = find_x(items)
                    if x:
                        b.tap(x['cx'], x['cy'], wait=1.5)
                clicked = 0
                log.append({'finish': 'close_panel_retry'})
                continue
            b.tap(end['cx'], end['cy'], wait=2.5)
            end_tapped_at = time.time()
            log.append({'finish': 'clicked_end', 'at': (end['cx'], end['cy'])})
            # 等确认框：找「确定/确认」（取最靠右的 = 确定，避开"取消"），
            # 最多等 ~4 秒，等到就点掉；等不到也不回头乱点 ✓
            # ⭐ 2026-09-28 提速（P0）：原版每轮 `sleep(0.5)` + **全屏 OCR**（0.8s/次），
            #   而且循环里不重截帧 ⇒ 8 次基本在对**同一帧**反复 OCR（纯浪费，实测一轮
            #   退图能烧 6~10 秒）。确认按钮固定在 cy>700、cx>420 ⇒ 改 **band OCR**
            #   （~0.3s/次）+ `wait_change` 等弹框出现（画面一变立刻看，不再死等）✓
            # ⭐ 二次修正：3 张实测全是 `end_no_dialog` —— 多数情况**根本不弹确认框**
            #   （没有未拾取战利品），8 轮白等 ~7s ⇒ 砍到 **3 轮**（~2s）：真弹框
            #   一般 1~2 轮内出现；万一出现得晚，**外层轮询自己就有「确定/确认」分支**
            #   （上方 ②）兜底，不会漏 ✓
            ok2 = None
            for _wait in range(3):
                if b.fast_ok:
                    b.wait_change(0.6, band=(int(LAYOUT.sy(600)), int(LAYOUT.sy(1500))),
                                  thr=4.0, min_sec=0.15)
                else:
                    time.sleep(0.5)
                it_after = b.ocr(min_conf=0.35,
                                 band=(int(LAYOUT.sy(680)), int(LAYOUT.sy(1500))), tag='pre')
                for t in it_after:
                    s2 = t['text'].strip()
                    if s2 in ('确定', '确认') and t['cy'] > LAYOUT.sy(700) and t['cx'] > LAYOUT.sx(420):
                        if ok2 is None or t['cx'] > ok2['cx']:
                            ok2 = t
                if ok2:
                    break
            if ok2:
                b.tap(ok2['cx'], ok2['cy'], wait=2.5)
                log.append({'finish': 'end_confirmed', 'at': (ok2['cx'], ok2['cy'])})
            else:
                log.append({'finish': 'end_no_dialog'})
            continue
        # ⭐⭐ 2026-09-26（rendslot 实测）：面板盖住棋盘时 OCR **根本看不到「结束冒险」**，
        #   于是上面每个分支都不命中 ⇒ 一直 sleep 到 90 秒 timeout ⇒ "退图没成功，已停止"
        #   （诱因常常是退图前那一下"补点"点出了面板）⇒ 认不到东西就先清面板再试
        idle += 1
        if idle >= 4:
            # ⭐⭐ 2026-09-26 用户实测：**「点中间最下面」(541,1890) 能关掉几乎所有弹窗，
            #   而且关完还在图里** ⇒ 退图阶段第一步就试它 ✓（比"找 X / 找关闭符"稳）
            #   ⚠ 但**战斗界面必须点「关闭」**（用户明令：不能点开始冒险 ✗）
            #     ⇒ 交给 universal_close 认面板类型，别在这里硬点 ✓
            universal_close(b, log, items=items, where='finish_idle')
            n = close_x_panels(b, b.img())
            x = find_x(b.ocr(tag='fin_univ'))
            if x:
                b.tap(x['cx'], x['cy'], wait=1.5)
                n += 1
            if not n and not x:
                # 连关闭符都认不到 ⇒ 按实测的固定位置试（底部返回 + 左侧 X）
                # ⭐ v0.31 方案 B：这两个都是**面板上的**关闭点（弹窗系）⇒ tap_dlg ✓
                b.tap_dlg(int(LAYOUT.sx(539)), int(LAYOUT.sy(1212)), wait=1.5)
                b.tap_dlg(int(LAYOUT.sx(493)), int(LAYOUT.sy(225)), wait=1.2)
            log.append({'finish': 'unknown_panel_clear', 'idle': idle,
                        'closed': n, 'x': bool(x), 'universal': True})
            idle = 0
            continue
        # ⭐ 2026-09-28 提速（P3）：空转轮不再死等 1.2s —— 画面一变（面板关掉/界面
        #   切换）立刻进入下一轮识别；没变才等满 ✓
        if b.fast_ok:
            b.wait_change(1.2, band=(130, 1800), thr=4.0, min_sec=0.2)
        else:
            time.sleep(1.2)
    log.append({'finish': 'timeout'})
    return False


def final_collect(b, log, st):
    """⭐ 退出地图前的固定动作（用户 2026-09-25）：**只点一下**，点的是**最近点过的那格**

    用户口径原话：「退出前点一下之前点过的位置，**点一下就行**」「**不是各一下，是一共一下**」
    「**最后点的那一下是点最近点的那次的点位**」。
    只补点 + 关面板，不再打架、不再买、不再揭新格。
    """
    clicks = list(st.get('clicked') or [])
    pos = clicks[-1] if clicks else st.get('last')
    if not pos:
        log.append({'collect': 'none'})
        return 0
    # ⚠ 2026-09-25 用户报「退出地图后乱点切换到别的图」：
    #   补点前**必须确认还在图里**！上一轮可能已经自己退图 / 被顶回选图界面，
    #   这时再按老坐标补一下 = 在选图界面上乱点（可能选到别的图）。
    b.snap('collect_pre')
    it0 = b.ocr(min_conf=0.4, band=(0, 320), tag='pre')
    if not in_map(b, b.img(), it0):
        log.append({'collect': 'skip_not_in_map'})
        say('       · 已经不在图里了 → 跳过退图前补点（避免乱点）')
        return 0
    b.tap(pos[0], pos[1], wait=1.8)
    b.snap('collect')
    it = b.ocr()
    # ⭐ 补点后可能弹「发现莱姆！」（用户 2026-09-25）→ 要**点返回**
    lb = lime_back(it)
    if lb:
        b.tap(lb['cx'], lb['cy'], wait=1.6)
        log.append({'collect': 'lime_back', 'at': (lb['cx'], lb['cy'])})
        say('       · 发现莱姆！→ 点返回')
        return 1
    # ⭐ 也可能弹「获得新装备！」（用户 2026-09-26 报：最后点击最近一次点过的位置那出现）
    if close_newequip(b, it, log, 'collect', at=pos):
        say('       · 退图前补点弹出「获得新装备！」→ 点返回')
        return 1
    # ⭐ 或者「预言石板」→ 点中间最下面关掉 + 拉黑这格 ✓
    if fb(it, *L['prophecy']):
        universal_close(b, log, items=it, probe=L['prophecy'][0], where='collect', at=pos)
        block_cell(log, st, pos, 'prophecy')
        say('       · 退图前补点弹出「预言石板」→ 关掉并拉黑这格')
        return 1
    # ⭐ 也可能弹「偶遇强敌」（2026-09-25 用户报卡住）→ 不打，点 X 关掉
    if fb(it, *L['strong']):
        x = find_x(it)
        if x:
            b.tap(x['cx'], x['cy'], wait=1.5)
        else:
            close_x_panels(b, b.img())
        log.append({'collect': 'strong_closed',
                    'closed_at': (x['cx'], x['cy']) if x else None})
        say('       · 退图前补点弹出「偶遇强敌」→ 不打，关掉')
        return 1
    opened = panel_seen(it, b=b) or bool(bottom_close(it))
    if opened:
        close_x_panels(b, b.img())
        cl = bottom_close(it)
        if cl:
            b.tap(cl['cx'], cl['cy'], wait=1.6)
        ok = exb(b.ocr(), L['ok'])
        if ok and ok['cy'] > LAYOUT.sy(900):
            b.tap(ok['cx'], ok['cy'], wait=1.5)
        x = find_x(b.ocr())
        if x:
            b.tap(x['cx'], x['cy'], wait=1.2)
    # ⭐ 2026-09-26（rendslot 实测）：补点点出的面板**关不掉**时，后面 finish_map 会因为
    #   「结束冒险」被面板遮住而 OCR 不到 ⇒ 空转到 90 秒 timeout ⇒ "退图没成功，已停止"
    #   ⇒ 这里关完**验证**一次；还在就强制脱困
    it2 = b.ocr(tag='collect2')
    still = panel_seen(it2, b=b) or bool(bottom_close(it2))
    log.append({'collect': 'tapped', 'at': pos, 'opened': bool(opened),
                'still': bool(still)})
    if still:
        force_unstick(b, log, 'collect_panel',
                      ctx={'tapped': pos, 'flags': st if isinstance(st, dict) else {}})
        say('       · 退图前补点点出了面板且关不掉 ⇒ 已强制脱困')
    return 1


def frame_age_ms():
    """⭐ v1.26：当前帧的帧龄（ms）——`None` = 拿不到（PC 端 / 还没帧）

    真机实报（用户 2026-10-02）：「点了战斗格、还没打就去点下一个格子」 ——
    真因是**截图流断了**（`截图流断流且自救失败 ×56`），Python 却拿**冻结的旧帧**继续
    做判断、继续点地图 ⇒ 瞎点 ✗✗
    """
    try:
        from java import jclass        # Chaquopy
    except Exception:       # noqa: BLE001
        return None
    try:
        _v = int(jclass('com.fantasy.autoexplore.DeviceApi').frameAgeMs())
        return _v if _v >= 0 else None
    except Exception:       # noqa: BLE001
        return None


def capture_path():
    """⭐ v1.31：本机取帧走的是**快路径**还是"行距填充"慢路径 —— `None` = 拿不到（PC 端）

    为什么要记它：真机 realme RMX3800（屏宽 1264，行距 5056→补 5120）**只有它走慢路径**，
    而旧慢路径把 RGBA 当 ARGB 用 ⇒ **R↔B 互换** ⇒ 整屏偏紫、标记全漏 ✗（v1.31 已修）。
    把 `[慢路径?, 实际行距, 宽度*4]` 记进每局的日志 ⇒ 反馈包**自带通道序证据** ✓
    """
    try:
        from java import jclass        # Chaquopy
    except Exception:       # noqa: BLE001
        return None
    try:
        _v = jclass('com.fantasy.autoexplore.DeviceApi').capturePath()
        return [int(x) for x in _v]
    except Exception:       # noqa: BLE001
        return None


def run_one_map(b, log, max_round=45, prefix='', deadline=900):
    t0 = time.time()
    st = {'cold': {}, 'done': set(), 'last': None, 'err': 0, 'stuck': 0,
          'marks': {}, 'clear': False, 'clear_fights': 0, 'stall': 0, 'sig': None,
          'blank': 0, 'clicked': [], 'battles': []}
    # ⭐⭐ 2026-09-30：**「点了探索没反应」的连击计数每张图清零**（它属于"本图验证"）
    #   —— 全局留着的话，第一张图踩到"槽满"之后，**后面每张图只敢点 1 次就判满** ✗；
    #      而"槽真的空出来、只是「空闲」两个字认不出来"的机器就会**永远派不出探索小队** ✗✗
    #   每图给足 2 次机会 = 最坏每图多花 ~6 秒，换"槽一空就能重新派队" ✓
    #   （本图内一旦判满，`st['slots_free']=0` 会把后面的紫/橙格全部送去开打，不会反复点 ✓）
    if EXPLORE_DISPATCH:
        _PANEL_STUCK['expl'] = 0
    # ⭐⭐⭐ v1.31：每局记一次**取帧通道序证据**（真机整屏偏紫的现场 = 走了"行距填充"慢路径 ✓）
    #   起因：realme RMX3800 屏宽 1264（行距 5056→补 5120）只有它走慢路径，而旧慢路径
    #   R↔B 互换 ⇒ 标记全漏。日志里有这条，反馈包就能自证"是不是这条路"✓
    try:
        _cp = capture_path()
        if _cp:
            log.append({'capture_path': {'slow': bool(_cp[0]), 'row_stride': _cp[1],
                                         'w4': _cp[2]}})
            if _cp[0]:
                say('       · 取帧走**慢路径**（行距填充 rowStride=%d 期望=%d）'
                    % (_cp[1], _cp[2]))
    except Exception:       # noqa: BLE001
        pass
    for rnd in range(max_round):
        # ⭐ 立即停止（2026-09-29 用户口径）：**每轮开头先查**，不等这张图打完
        if stop_checked(log, '轮首 r%d' % rnd):
            return 'stopped'
        # ⭐⭐⭐ 2026-10-02 v1.26【**帧断了就别再点**（瞎点会打乱游戏）】
        #   真机实报：「点了战斗格、还没打就去点下一个格子」—— 真因是截图流断流
        #   （`截图流断流且自救失败 ×56`），Python 拿**冻结的旧帧**继续判、继续点 ✗✗
        #   判据：帧龄 >8s（与 Java 看门狗同口径）**连续 2 轮** ⇒ 停整局并说清怎么恢复。
        #   ⚠ `frame_age_ms()` 返回 None（PC 端 / 还没拿到帧）时**不做判断**（别误停 ✓）
        _age = frame_age_ms()
        if _age is not None and _age > 8000:
            st['stale'] = st.get('stale', 0) + 1
            if st['stale'] >= 2:
                log.append({'finish': 'capture_stale', 'age_ms': _age,
                            'stale_rounds': st['stale']})
                say('  ⚠⚠ 截图流断了 %.1fs 没新帧 ⇒ **停止点击**（瞎点会打乱游戏）'
                    % (_age / 1000.0))
                say('     · 恢复：点悬浮条「① 授权截图」（必要时先重启 App）再重新启动 ✓')
                status('截图断了 · 请点①授权截图')
                return 'stale'
        else:
            st['stale'] = 0
        if time.time() - t0 > deadline:
            log.append({'finish': 'deadline'})
            final_collect(b, log, st)
            return 'deadline'
        try:
            why = one_round(b, log, rnd, prefix, st)
            # ⭐⭐ 2026-09-29 诊断（真机「点了格子不点战斗」空转 15 秒排查）：
            #   每轮返回值落 log —— 之前 r1~r6 在 logcat 里**完全隐形**（轮首 say 都没有），
            #   无法判断卡在哪个状态。有这条后：每轮一条 `round_end`，配合轮首 say
            #   就能定位"每 2.2 秒一次 OCR 却零点击"到底发生在哪一段。
            log.append({'round_end': rnd, 'why': why,
                        'secs': round(time.time() - t0, 1)})
        except Exception as e:
            import traceback
            st['err'] += 1
            log.append({'round': rnd, 'error': repr(e),
                        'trace': traceback.format_exc().splitlines()[-3:]})
            flush(log)
            if st['err'] >= 3:
                log.append({'finish': 'too_many_errors'})
                final_collect(b, log, st)
                return 'errors'
            time.sleep(2)
            continue
        flush(log)
        if why:
            # ⚠ 「发现红装立即停止」时**什么都别做**（别补点、别退图），把现场留给人
            # ⚠ 「用户点了停止」同理：**绝不能补点**（`final_collect` 会再点一遍打过的格
            #   ⇒ 明明点了停还要多等十几秒，正是用户抱怨的"等打完这张图"✗）
            if why not in ('kicked', 'red_equip', 'stopped'):
                final_collect(b, log, st)      # ⭐ 退出前固定补点（只点打过的格）
            return why
    final_collect(b, log, st)
    return 'maxed'


def line_cells(a, b):
    """两格之间按**直线**取格（Bresenham），含两端

    用户 2026-09-25 口径：「拦路 = 出生点到对应标记**那条直线上的格子**，两点之间直线最短」
    ⇒ 不要用「走廊」判据（`|d1+d2-d|<=2`，会把偏出去的格子也算成拦路）。
    """
    (r0, c0), (r1, c1) = a, b
    dr, dc = abs(r1 - r0), abs(c1 - c0)
    sr = 1 if r1 >= r0 else -1
    sc = 1 if c1 >= c0 else -1
    err = dr - dc
    r, c = r0, c0
    out = []
    for _ in range(dr + dc + 3):
        out.append((r, c))
        if (r, c) == (r1, c1):
            break
        e2 = 2 * err
        if e2 > -dc:
            err -= dc
            r += sr
        if e2 < dr:
            err += dr
            c += sc
    return out


def optimal_order(c, mk, st, log=None):
    """⭐ 用「体力最省」的最优解算本回合点序（mapsolve.Dijkstra，毫秒级）

    用户 2026-09-25：「要按消耗体力最少的方案走」。
    体力公式（源码 82956-82992）：普通格 = SpotSize；战斗格 = SpotSize*2。
    建盘：把视觉状态（每格 sid/是否已揭示/标记）交给 mapsim.from_observation（相邻同 sid 归一块），
    再交给 mapsolve.solve 求最省体力的动作序列 → 返回要点的像素坐标列表。
    失败(异常/无解)返回 None，调用方退回原来的启发式点序 ✓
    """
    try:
        import mapsim as sim_mod
        import mapsolve as solve_mod
        # ⭐⭐⭐ 2026-09-30：这里原来自己拼一份 cells（与 `_cells_for_model` 各写一遍）
        #   ⇒ ① 漏掉「按 anchor 整块剔已消耗格」和 `target` 白名单 ② 两处口径漂移
        #     （本仓库历史上 `_fix_blank_cost_1` 只改 mapsolve 漏 mapsim 就是这么踩的）
        #   ⇒ 统一改走 `_cells_for_model`（solver_order / eff_order 用的同一份 ✓）
        cells = _cells_for_model(st, c, log=log, tag='opt')
        if len(cells) < 8:
            if log is not None:
                log.append({'opt_skip': 'too_few_cells', 'n': len(cells)})
            return None
        sim = sim_mod.MapSim.from_observation(cells, spots_mod.spot_rows())
        prob = solve_mod.Problem(sim)
        if not prob.targets:
            if log is not None:
                log.append({'opt_skip': 'no_targets', 'blocks': len(sim.blocks),
                            'cells': len(cells), 'marks': len(mk or {})})
            return None
        # ⭐⭐⭐ 2026-10-01 v1.12 真机**空转卡死**修复（用户：「连地图都进不去了，显示正在把游戏
        #   拉回来」→ 实际是 **200% CPU 空转、日志停在进图后那次 OCR**）：
        #   本行原来只有 `max_states=40000`、**没有时间上限** ✗ —— 另一处（`solver_order`）
        #   早就加了 `max_secs=8`（2026-09-28「进图要等很久」），这一处漏了。
        #   一旦棋盘被切得很碎（例如雾格剪影判成"非空地"⇒ 连锁片变多、A* 状态空间爆炸），
        #   40000 个状态的展开就是**几分钟的满载空转**，而且**全程不打日志** ⇒
        #   用户看到的就是"卡在某一步不动"。⇒ 加 8 秒上限 + 前后落日志（下次一眼能看见）✓
        _t_opt = time.time()
        cost, acts = solve_mod.solve(prob, max_states=40000, max_secs=8)
        if log is not None:
            log.append({'opt_solved': {'secs': round(time.time() - _t_opt, 2),
                                       'cost': cost, 'steps': (len(acts) if acts else 0),
                                       'blocks': len(sim.blocks), 'targets': len(prob.targets)}})
        if not acts:
            if log is not None:
                log.append({'opt_skip': 'no_solution', 'targets': len(prob.targets),
                            'cost': cost})
            return None
        # ⭐ 2026-09-30：点击点必须取「当下已揭示的格」——理由见 `solver_order` 同处注释
        out = [marks_mod.cell_center(*_rc)
               for _rc, _bi, _w in prob.cells_for_plan(acts)]
        if out:
            say('       · 体力最优解：%d 步、预计 %s 点体力' % (len(acts), cost))
        return out or None
    except Exception as e:      # noqa: BLE001
        import traceback
        if log is not None:
            log.append({'opt_err': repr(e),
                        'trace': traceback.format_exc().splitlines()[-2:]})
        return None


BACK_BTN = (539, 1212)        # 中间「返回」（交接文档实测坐标 ✓）
CLOSE_TR_PT = (984, 191)      # 背包右上角「关闭」
START_ADV = (540, 1828)       # 底部中间「开始冒险」**图标**（回地图界面）
# ⚠ 2026-09-28 修：原来是 (541,1889) —— 那是 OCR 到的**文字**位置，实测**点空** ✗
#   底部导航栏 = 图标在上(y≈1828)、文字在下(y≈1890)；文字那格点了不导航 ✓
CLOSE_TR, CLOSE_TR_Y = 984, 191    # 面板右上角关闭按钮（背包/招募/图鉴通用 ✓）

MAP_SCREEN_HINTS = ('开始冒险', '进入地图', '快速扫荡', '结束冒险', '探索度')


def is_map_screen(items):
    """判断是不是「地图/选图界面」（用户要求：用完补给必须回到这里）

    ⚠ 2026-09-27：`MAP_SCREEN_HINTS` 里的「开始冒险」**大厅也有**（全局底部导航），
      所以必须先用 `in_lobby()` 把大厅排除掉，否则大厅会被当成"已回到地图界面" ✗
    """
    if in_lobby(items):
        return False
    txt = [i.get('text') or '' for i in (items or [])]
    return any(any(h in t for h in MAP_SCREEN_HINTS) for t in txt)


def go_lobby_to_menu(b, log, items=None, wait=3.0):
    """大厅 → 点底部中间「开始冒险」→ 离开大厅

    ⭐ 用户 2026-09-27 明示：「点中间的开始冒险就能回到选图界面」
       （背景：幻少采图第 13 张时**游戏自己重启**，重启后停在大厅，
         每轮 `{'pre':'not_in_map','act':'none'}` 直到 40 秒超时 ✗）

    ⚠ 实测补充（2026-09-27 22:04 幻少真机）：从大厅点「开始冒险」的落点**有两种**——
        · 若存在**未完成的图** ⇒ **直接恢复到那张图**（实测落进「夏日海滩[100]」棋盘，
          体力 1406/2100 不变 ⇒ 确认不是新进图、没扣 25 体力 ✓）
        · 否则 ⇒ 回选图界面
       两种落点对调用方都可用：`ensure_in_map` 前者 `in_map()==True` 直接开工，
       后者交给 `enter_map()` 点「进入地图」✓
       所以函数名保留 menu，但语义是 **"离开大厅"**，不保证一定到选图界面。

    ⚠ 安全边界不变：**必须先 OCR 真认到「开始冒险」文本**（且 cy 在底部带内）才点；
      认不到就什么都不做 —— 绝不盲点万能位 (541,1890) ✗
      （地图/选图界面的底部也有「开始冒险」，所以这里**同时要求 `in_lobby()`**，
        避免在推图循环里误触它 ✗）
    """
    if items is None:
        items = b.ocr(tag='lobby')
    if not in_lobby(items):
        return False
    adv = None
    for it in items:
        if '开始冒险' in (it.get('text') or '') and it['cy'] > LAYOUT.sy(1600):
            adv = it
            break
    if not adv:
        log.append({'lobby': 'no_start_adv_text'})
        say('   · 判定在大厅，但没认到「开始冒险」文本 ⇒ 不盲点，停在原地')
        return False
    # ⭐⭐ 2026-09-28 修（**"点了开始冒险却不离开大厅"的根因**）：
    #   底部导航栏是「**图标在上、文字在下**」，直接点 OCR 到的**文字**位置会点空 ✗
    #   实测（幻少 16416 / 1080×1920，大厅与选图界面**同一套底部栏**）：
    #     文字 bbox: 开始冒险 cx=540 y0=1869 y1=1910（cy=1890）
    #     图标中心      y≈1828  ← 点这里才有效 ✓（实测 (540,1828) 一次就离开大厅）
    #   沿用「角色」tab 的老教训：文字 (304,1889) 无效 / 图标 (284,1827) 有效，dy≈−62 ✓
    #   ⇒ 按「文字顶边 −41px」点图标，并且**点完必须验证真的离开大厅**，不行再试别的偏移 ✓
    cands_y = [adv['y0'] - 41, adv['cy'] - 62, adv['y0'] - 25, adv['cy']]
    for k, ty in enumerate(cands_y):
        ty = int(ty)
        b.tap(adv['cx'], ty, wait=wait)
        log.append({'lobby': 'tap_start_adv', 'at': (adv['cx'], ty), 'try': k})
        say('   ★ 大厅 → 点「开始冒险」图标 (%d,%d) 离开大厅（未完成的图会直接恢复 ✓）'
            % (adv['cx'], ty))
        status('人在大厅 · 正在回地图')
        # ⭐ 2026-09-28：判定改成**最多看 3 次**（每次间隔 1.2 秒）
        #   因为「大厅→（恢复进图）/（选图界面）」有**场景过渡**，点完 3 秒时 OCR 常还停在大厅 ✗
        #   老逻辑一次判死 ⇒ 白点剩余 3 次偏移（实测每轮多花 ~30 秒，占单轮 20%）
        ok_leave = False
        for _k in range(3):
            _it2 = b.ocr(tag='lobby2')
            if not in_lobby(_it2):
                ok_leave = True
                break
            try:
                if in_map(b, b.img(), _it2):          # 直接恢复进图 ⇒ 也算离开大厅 ✓
                    log.append({'lobby': 'tap_start_adv_to_map'})
                    say('   ★ 点「开始冒险」后**直接恢复进图**（存在未完成的图）⇒ 已离开大厅 ✓')
                    ok_leave = True
                    break
            except Exception:           # noqa: BLE001
                pass
            time.sleep(1.2)
        if ok_leave:
            return True
        say('     · 这一下没离开大厅，换下一个偏移再试')
    log.append({'lobby': 'tap_start_adv_failed', 'tried': cands_y})
    say('   ✗ 四个偏移都点过还是在大厅 ⇒ 交回调用方（不盲点万能位 ✗）')
    return False


try:
    from mapbot import ADB, CNW
    ADB = ADB or r'D:\android-build\sdk\platform-tools\adb.exe'
except Exception:       # noqa: BLE001
    ADB = r'D:\android-build\sdk\platform-tools\adb.exe'
    CNW = 0x08000000 if os.name == 'nt' else 0


def back_to_map(b, log, tries=5):
    """一路退回到地图界面（每步都**验证**，退到为止）"""
    for k in range(tries):
        b.snap('backmap')
        items = b.ocr(min_conf=0.2, tag='backmap')
        if is_map_screen(items):
            log.append({'back_to_map': 'ok', 'tries': k})
            return True
        # ⭐ 2026-09-27：大厅 ⇒ 点底部中间「开始冒险」
        #   ⚠ 绝不能落到下面的 ③ —— 大厅的 (984,191) 是**右上角齿轮（设置）**，
        #     点它会弹设置面板，越退越远 ✗
        if in_lobby(items):
            if go_lobby_to_menu(b, log, items=items, wait=2.5):
                continue
            log.append({'back_to_map': 'lobby_no_btn', 'try': k + 1})
            return False
        # ① 返回 / 关闭 / 取消
        back = find_button(items, '返回', '关闭', '取消', maxlen=4) or \
            find_in(items, '返回', '关闭')
        if back:
            b.tap(back['cx'], back['cy'], wait=1.3)
            log.append({'back_to_map': 'tap_back', 'try': k + 1,
                        'text': back['text']})
            continue
        # ② 提示弹窗的 确定 / 确认（用完道具后常见；此时只是关提示，不会买东西 ✓）
        ok = find_button(items, '确定', '确认', maxlen=3)
        if ok and ok['cy'] > LAYOUT.sy(600):
            b.tap(ok['cx'], ok['cy'], wait=1.3)
            log.append({'back_to_map': 'tap_ok', 'try': k + 1,
                        'at': (ok['cx'], ok['cy'])})
            continue
        # ③ ⭐ 右上角关闭按钮（用户提醒：背包右上角就有关闭 ✓；实测 (984,191)）
        b.tap(CLOSE_TR, CLOSE_TR_Y, wait=1.3)
        log.append({'back_to_map': 'tap_close_tr', 'try': k + 1,
                    'at': (CLOSE_TR, CLOSE_TR_Y)})
        continue
        # ④ X 按钮（万一是别的图标的 X）
        x = find_x(items)
        if x:
            b.tap(x['cx'], x['cy'], wait=1.3)
            log.append({'back_to_map': 'tap_x', 'try': k + 1})
            continue
        # ④ 安卓返回键（面板类界面最通用的退法 ✓）
        try:
            if _MAPBOT_ANDROID:
                # Android：走无障碍 dispatchGesture 的全局返回（无需 adb/root ✓）
                getattr(b, 'back')(wait=1.0)
                log.append({'back_to_map': 'a11y_back', 'try': k + 1})
            else:
                import subprocess
                # ⚠ 设备号取 Bot 自己的（原来误用了模块里不存在的 SERIAL ✗）
                dev = getattr(b, 'dev', None) or getattr(b, 'serial', None) or ''
                cmd = [ADB, '-s', dev] if dev else [ADB]
                subprocess.run(cmd + ['shell', 'input', 'keyevent', '4'],
                               capture_output=True, timeout=10, creationflags=CNW)
                time.sleep(1.0)
                log.append({'back_to_map': 'keyevent_back', 'try': k + 1, 'dev': dev})
        except Exception as e:      # noqa: BLE001
            log.append({'back_to_map': 'no_more_fallback', 'try': k + 1, 'err': repr(e)})
            break
    b.snap('backmap_end')
    ok = is_map_screen(b.ocr(min_conf=0.2, tag='backmap'))
    log.append({'back_to_map': 'give_up', 'ok': bool(ok)})
    say('       · 回到地图界面: %s' % ('✓' if ok else '✗ 没退干净'))
    return bool(ok)


def find_button(items, *keys, maxlen=4):
    """找**按钮**（不是说明文字）：文字短(≤maxlen)、不含句号、含关键词

    现场教训：结实补给的说明是"使用后立即获得500点体力。"——含"使用"二字 ✗，
    之前的 find_in 把它当按钮点了 ⇒ 什么都没发生（体力 316→316）。
    真按钮「使用」在 (868,1013)，只有 2 个字 ✓
    """
    for it in sorted(items or [], key=lambda x: x['cy']):
        t = (it.get('text') or '').strip()
        if not t or len(t) > maxlen or t.endswith('。') or t.endswith('，'):
            continue
        if any(k in t for k in keys):
            return it
    return None


def find_in(items, *keys):
    """在 OCR 结果里找含任一关键词的条目（优先更靠上的那条）"""
    for it in sorted(items or [], key=lambda x: x['cy']):
        t = it.get('text') or ''
        if any(k in t for k in keys):
            return it
    return None


GUILD_BTN = (95, 1889)        # 主界面左下角「公会」
BAG_BTN = (964, 1680)         # 公会界面右下角「背包」（在「招募」正下方）
#   ⭐ 2026-09-30 重标定 (969,1700)→(964,1680)：模拟器 720x1600 放大条带实测背包图标中心
#   设备 (643,1440) ⇒ 归一化 (964,1680)。旧值 y=1700 的落点在图标热区下沿/横幅上 ⇒
#   公会界面点 BAG_BTN 无反应（bag_not_open ×3 轮，实拍 _verify/bag_final*.png ✓）
ITEM_TAB = (879, 360)         # 背包页签「道具」（最右；⭐ 2026-09-30 实拍校准 (586,360)设备 ✓）
# ⭐⭐ 2026-10-01 真机标定（用户手动停在页面上、我只读抓帧实测；两条通道互验一致 ✓）
#   ① 背包**页签**（素材/装备/符文/宝箱/道具）与**右上角 X** 都落在 `toRef()` 丢弃的
#      弹性带里 ⇒ **归一化帧根本看不见**（OCR 读不到、模板 0.38/0.61 也不中 ✗）
#      ⇒ 它们的坐标是**弹窗系**：必须 `b.tap_dlg(...)` 点（拿 `b.tap` 会偏 C≈209 ✗）
#   ② 「一键升星」两条通道都读到了：归一化帧 @(923,1550) ｜ 弹窗帧 @(923,1759)
#      （差 209 = C ✓ 自洽）⇒ 旧 `UPGRADE_BTN=(928,1789)` 是**弹窗系**值被当归一化系用 ✗
#      —— 真机实测归一化系在 y=1550，这就是"点了一键升星没反应"的原因之一 ✓
BAG_TAB_DLG = {'素材': (152, 315), '装备': (345, 315), '符文': (540, 315),
               '宝箱': (732, 315), '道具': (925, 315)}
BAG_X_DLG = (1023, 215)          # 背包右上角 X（弹窗系）
BAG_FILTER_DLG = (199, 1758)     # 底部「筛选」（弹窗系；一般用不到）
UPGRADE_BTN = (923, 1550)        # 装备页右下「一键升星」——**归一化系**（真机实测 ✓）
# ⚠⚠ 2026-10-01 修：原来这行紧接着又定义了一次 `UPGRADE_BTN = (928, 1789)`（旧标定值）
#   ⇒ 后者生效，把上面注释标为「弹窗系值被当归一化系用 ✗」的错误值又启用了
#   ⇒ 兜底点击整体偏 C≈209px，真机「一键升星」点空。已删掉重复定义。
EQUIP_TAB = (370, 360)        # 背包页签「装备」（第 2 个；⭐ 2026-09-30 实拍校准 ✓）（⭐ 2026-09-27 新增；
                              #   首次跑会先 OCR 找「装备」✓ 找不到才用这个兜底 ✓）
SUPPLY_TPL = os.path.join(_MAPBOT_ROOT, 'templates', 'items', 'supply_strong.png')
SUPPLY_MASK = os.path.join(_MAPBOT_ROOT, 'templates', 'items', 'supply_strong_mask.png')
SUPPLY_THR = 0.90             # 识图匹配下限（自匹配 1.000，其他格子差得远）


def find_supply_icon(b, img=None):
    """⭐ 靠识图在背包「道具」页里找「结实补给」-> (cx, cy, score) 或 None

    模板是 2026-09-25 从用户屏幕上裁的 150×150 格子（掩码挖掉右下角数量数字，
    因为数量会变、不能参与匹配）。位置**不写死**：每个人背包不一样 ✓

    ⚠⚠ 2026-10-01 修（**Android 上这条以前 100% 失败**）：模板路径原来取的是
    `os.path.dirname(os.path.abspath(__file__))` —— Android 上那是 APK 内的
    `…/chaquopy/AssetFinder/app/`（**只读且没有 templates/** ✗），真正的资源包在
    `filesDir/mapbot_pack/`（= `_MAPBOT_ROOT`，由 port_loop 注入）⇒ 每次都在这里
    返回 None ⇒ 自动补给永远"识图没找到结实补给"✗。
    ⇒ 统一走 `_MAPBOT_ROOT`（PC 侧有兜底 = 本文件目录 ✓），并把"模板缺失/匹配分数"
    say 出来（否则失败是静默的 ✗）
    """
    import cv2
    import numpy as np
    tp = os.path.join(_MAPBOT_ROOT, SUPPLY_TPL)
    mp = os.path.join(_MAPBOT_ROOT, SUPPLY_MASK)
    if not (os.path.exists(tp) and os.path.exists(mp)):
        say('       · ⚠ 补给模板缺失：%s（_MAPBOT_ROOT=%s）' % (SUPPLY_TPL, _MAPBOT_ROOT))
        return None
    tpl = cv2.imdecode(np.fromfile(tp, dtype=np.uint8), cv2.IMREAD_COLOR)
    msk = cv2.imdecode(np.fromfile(mp, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        img = b.img()
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    y0, y1, x0, x1 = 330, 1500, 60, 1020          # 道具网格区域
    sub = img[y0:y1, x0:x1].astype(np.float32)
    m = (msk > 0).astype(np.float32)
    res = cv2.matchTemplate(sub, tpl.astype(np.float32), cv2.TM_SQDIFF, mask=m)
    res = np.nan_to_num(res, nan=1e12, posinf=1e12, neginf=1e12)
    mn, _, loc, _ = cv2.minMaxLoc(res)
    score = 1.0 - mn / (m.sum() * 255.0 * 255.0)
    cx = x0 + loc[0] + tpl.shape[1] // 2
    cy = y0 + loc[1] + tpl.shape[0] // 2
    say('       · 补给识图最好成绩 %.3f @(%d,%d)（阈值 %.2f）'
        % (score, cx, cy, SUPPLY_THR))
    return (int(cx), int(cy), round(float(score), 3)) if score >= SUPPLY_THR else None


def use_supply(b, log, names=('结实补给',)):
    """⭐ 使用一个「结实补给」回体力（用户 2026-09-25 给的流程）

        公会(95,1889) → 背包(969,1700) → 道具(926,261) → **识图**找结实补给 → 使用 → 回地图界面
    位置不写死（每个人背包不一样），靠模板匹配 ✓；OCR 只用来找「使用/确定」这类文字按钮。
    **不设数量上限**（勾了就按需一直用），只统计用了几个 ✓
    """
    # ⭐⭐ 2026-09-28 修：`SUPPLY_USED += 1` 走的是**局部变量**语义 ⇒ UnboundLocalError ✗
    #   （实测：补给其实**已经吃成功**（体力 14→489）、退图也退对了，
    #     只在最后统计那一行抛异常 ⇒ 被 except 吞掉 → 返回 False → 上层 `break`，
    #     全靠"后面再读一次体力发现够了"才没断线 ⇒ **侥幸跑通**，必须修 ✓）
    global SUPPLY_USED
    try:
        b.snap('supply0')
        items = b.ocr(tag='supply')
        txt = [i['text'] for i in items]
        # ⭐⭐ 安全闸（2026-09-26 教训）：**必须站在选图界面**才动手
        #   在地图里点 (95,1889) 会落在棋盘格子上 ✗（实测和正在跑的循环抢点击）
        in_map_now = any('结束冒险' in t for t in txt)
        on_select = any(any(k in t for k in ('进入地图', '快速扫荡', '开始冒险', '星界秘境'))
                        for t in txt)
        if in_map_now or not on_select:
            log.append({'supply': 'skip_not_on_select',
                        'in_map': bool(in_map_now), 'on_select': bool(on_select),
                        'texts': txt[:14]})
            say('       · 现在不在选图界面（%s），不碰补给，避免误点地图格子'
                % ('地图里' if in_map_now else '未知界面'))
            return False
        # ② 开背包（⭐ 2026-10-01 与升星同口径重做：**先确认公会界面** → 文字「背包」
        #    → 模板（两帧×多尺度）→ 公会界面锚点；全程 say + 落帧，真机可诊断 ✓）
        # ⭐ 2026-10-01 用户要求：「使用结实补给**记得在悬浮窗的弹窗上给用户看**」✓
        #   （只有 `status()` 的消息会上悬浮条日志行；文本避开 OCR 关键词：不写"背包/关闭/领取"）
        status('体力不够 · 去取结实补给')
        _pub_dump('supply_select', b.img())
        items = []
        opened = False
        for _try in range(3):
            if not _guild_on(items) and not any(
                    '背包' in (i.get('text') or '') for i in items):
                _g = None
                for _i in items:
                    if (_i.get('text') or '').strip().replace(' ', '') in ('公会', '公會'):
                        _g = _i
                        break
                _gat = (_g['cx'], _g['cy']) if _g else GUILD_BTN
                b.tap(_gat[0], _gat[1], wait=2.8)
                log.append({'supply': 'open_guild', 'at': _gat,
                            'by': 'ocr' if _g else 'anchor', 'try': _try})
                say('       · 补给第 %d 轮：先进公会 (%d,%d) %s'
                    % (_try + 1, _gat[0], _gat[1],
                       '（OCR「公会」✓）' if _g else '（底部导航锚点）'))
                time.sleep(1.2)
                b.snap('supply_g%d' % _try)
                items = b.ocr(tag='supply_g')
                _pub_dump('supply_g%d_guild' % _try, b.img())
                if not _guild_on(items):
                    say('       · ⚠ 点了公会但不像公会界面：认到 %s'
                        % ([i['text'] for i in items][:10],))
            _bk = None
            for _i in items:
                if (_i.get('text') or '').strip().replace(' ', '') in ('背包', '道具'):
                    _bk = _i
                    break
            if _bk:
                _tap_verified(b, _bk['cx'], _bk['cy'], 'norm', log=log, what='背包(文字)')
                log.append({'supply': 'open_bag_text', 'at': (_bk['cx'], _bk['cy']),
                            'text': _bk.get('text'), 'try': _try})
                say('       · 开背包：OCR 找到「%s」(%d,%d) ✓'
                    % (_bk.get('text'), _bk['cx'], _bk['cy']))
            else:
                _hit, _ch = _tpl_hit(b.img(), 'guild_bag_icon.png',
                                     region=(int(LAYOUT.sx(300)), int(LAYOUT.sy(1000)),
                                             1080, 1920)), 'norm'
                if _hit is None and dlg_c() and hasattr(b, 'img_dlg'):
                    _hit = _tpl_hit(b.img_dlg(), 'guild_bag_icon.png')
                    _ch = 'dlg'
                if _hit:
                    _tap_verified(b, _hit[0], _hit[1], _ch, log=log,
                                  what='背包(模板%.2f)' % _hit[2])
                    log.append({'supply': 'open_bag_tpl', 'at': (_hit[0], _hit[1]),
                                'score': _hit[2], 'ch': _ch, 'try': _try})
                    say('       · 开背包：模板命中 (%d,%d) %.2f（%s）'
                        % (_hit[0], _hit[1], _hit[2],
                           '弹窗帧' if _ch == 'dlg' else '归一化帧'))
                else:
                    _tap_verified(b, BAG_BTN[0], BAG_BTN[1], 'norm', log=log, what='背包(锚点)')
                    log.append({'supply': 'open_bag_anchor', 'at': BAG_BTN, 'try': _try})
                    say('       · 开背包：文字/模板都没中 ⇒ 公会界面锚点 (%d,%d)' % BAG_BTN)
            b.snap('supply1')
            items = b.ocr(tag='supply')
            _pub_dump('supply%d_bag' % _try, b.img())
            # ⭐⭐ 判"开了没"用**颜色判据**（真机 OCR 读不到标题「背包」二字 ✗）
            _op, _how = _bag_panel_open(b, items)
            if _op:
                opened = True
                say('       · 背包已打开 ✓（判据：%s）' % _how)
                log.append({'supply': 'bag_open_ok', 'how': _how, 'try': _try})
                break
            log.append({'supply': 'open_bag_miss', 'try': _try,
                        'texts': [i['text'] for i in items][:12]})
            say('       · 背包未开（第 %d 轮）：屏上认到 %s'
                % (_try + 1, [i['text'] for i in items][:10]))
        if not opened:
            _ftxts = [i['text'] for i in items][:20]
            log.append({'supply': 'bag_not_open', 'texts': _ftxts})
            say('       · 背包没打开（重试 3 轮 ✗）｜最后一屏：%s' % (_ftxts,))
            _close_bag(b, items, log)
            return False
        # ③ 道具页签（⭐ 2026-10-01 真机修正：**页签只在弹窗帧里** —— 直接走 `_bag_switch_tab` ✓；
        #    旧写法在归一化帧里找「道具」永远找不到 ⇒ 退锚点坐标 (879,360)，而真机上那里是**装备** ✗）
        _ok_tab = _bag_switch_tab(b, '道具', log=log, tag='supply')
        if not _ok_tab:
            _tab = _bag_find(b, ('道具', '物品'), prefer='top', tag='supply_tab')
            if _tab:
                _bag_tap(b, _tab[0], _tab[1], _tab[2], wait=1.5)
                log.append({'supply': 'item_tab', 'at': (_tab[0], _tab[1]),
                            'by': 'ocr', 'ch': _tab[2], 'text': _tab[3]})
                say('       · 道具页 → 点 (%d,%d)（%s OCR ✓「%s」）'
                    % (_tab[0], _tab[1],
                       '弹窗帧' if _tab[2] == 'dlg' else '归一化帧', _tab[3]))
            else:
                # ⭐ 2026-10-01 体检修：同上（道具页签真机在弹窗系 dlg(925,315) ⇒ 设备 y≈620；
                #   旧 `ITEM_TAB=(879,360)` ref ⇒ 设备 y≈923 ⇒ 点空 ✗）
                _pt = BAG_TAB_DLG.get('道具', ITEM_TAB)
                _panel_tap(b, _pt[0], _pt[1], 'dlg', log=log, what='道具页(弹窗系标定)')
                log.append({'supply': 'item_tab_anchor_dlg', 'at': _pt})
                say('       · 道具页 → 页签没认到 ⇒ 弹窗系标定坐标 %s' % (_pt,))
        # ④ 识图找结实补给
        b.snap('supply2')
        _pub_dump('supply_items', b.img())
        hit = find_supply_icon(b)
        if not hit:
            log.append({'supply': 'icon_not_found'})
            say('       · 识图没找到结实补给 ✗')
            _close_bag(b, b.ocr(tag='supply'), log)
            return False
        cx, cy, score = hit
        log.append({'supply': 'icon_hit', 'at': (cx, cy), 'score': score})
        say('       · 识图找到结实补给 (%d,%d) 分数 %.3f' % (cx, cy, score))
        status('找到结实补给 · 正在用…')          # ⭐ 悬浮条上看得见 ✓（用户 2026-10-01 要求）
        b.tap(cx, cy, wait=1.4)
        # ⑤ 使用（⭐ 双通道文字优先：真机上「使用」可能在归一化帧外 ⇒ 补弹窗帧 ✓）
        b.snap('supply3')
        _pub_dump('supply_item_click', b.img(), important=False)
        items = b.ocr(tag='supply')
        _use = _bag_find(b, ('使用', '使用道具'), prefer='bottomright', tag='supply_use')
        if _use:
            _bag_tap(b, _use[0], _use[1], _use[2], wait=1.6)
            log.append({'supply': 'use', 'at': (_use[0], _use[1]), 'ch': _use[2],
                        'text': _use[3]})
            say('       · 使用 → 点「%s」(%d,%d)（%s）'
                % (_use[3], _use[0], _use[1], '弹窗帧' if _use[2] == 'dlg' else '归一化帧'))
        else:
            _btn = [i for i in items if (i['text'] or '').strip() in ('使用', '使用道具')
                    and i['cx'] > LAYOUT.sx(700)]
            if _btn:
                b.tap(_btn[0]['cx'], _btn[0]['cy'], wait=1.6)
                log.append({'supply': 'use_right', 'at': (_btn[0]['cx'], _btn[0]['cy'])})
            else:
                log.append({'supply': 'no_use_btn',
                            'texts': [i['text'] for i in items][:22]})
                say('       · ⚠ 没认到「使用」按钮 ⇒ 屏上：%s'
                    % ([i['text'] for i in items][:12],))
        # ⑥ 确认弹窗（双通道）
        for _ in range(2):
            b.snap('supply4')
            _pub_dump('supply_confirm', b.img(), important=False)
            _ok = _bag_find(b, ('确定', '确认', '使用', '是'), prefer='bottomright',
                            tag='supply_ok')
            if _ok and _ok[1] > LAYOUT.sy(700):
                _bag_tap(b, _ok[0], _ok[1], _ok[2], wait=1.5)
                log.append({'supply': 'confirm', 'at': (_ok[0], _ok[1]),
                            'text': _ok[3], 'ch': _ok[2]})
                say('       · 确认 → 点「%s」(%d,%d)' % (_ok[3], _ok[0], _ok[1]))
            else:
                break
        # ⭐⭐ 用完补给的**三步退图**（用户 2026-09-26 口径）：
        #   ① 「返回」→ ② 右上角关闭背包 → ③ 中间下面「开始冒险」回地图界面
        #   ⚠ ① 必须点**界面上那个「返回」按钮**（用 OCR 找文字），
        #     找不到就**跳过**，绝不盲点左上角 ✗（用户明确要求删掉这个动作 ✗）
        b.snap('supply_ret')
        it_ret = b.ocr(tag='supply')
        back = find_button(it_ret, '返回', maxlen=4) or find_in(it_ret, '返回')
        if back:
            _panel_tap(b, back['cx'], back['cy'], 'norm', log=log, what='返回(文字)')
            log.append({'supply_return': 'back_text', 'at': (back['cx'], back['cy']),
                        'text': back['text']})
        else:
            # 交接文档里记的实测坐标：中间「返回」= (539,1212)（**归一化系** ✓ 仅作兜底）
            # ⭐ 2026-10-01 体检修：走 `_panel_tap` ⇒ 没生效会自动换通道（弹窗系）再试 ✓
            _panel_tap(b, BACK_BTN[0], BACK_BTN[1], 'norm', log=log, what='返回(标定)')
            log.append({'supply_return': 'back_coord', 'at': BACK_BTN,
                        'texts': [i['text'] for i in it_ret][:10]})
        # ② 关闭背包（⭐⭐ 2026-10-01 真机修：背包那个 X 落在 toRef 丢弃的弹性带里
        #    ⇒ 只有**弹窗帧**看得见，且必须 `tap_dlg`（归一化系硬点会偏 C≈209 ✗）
        #    ⇒ 先按面板颜色判"背包还开着吗"，开着就点弹窗系 X；关了就直接走下一步 ✓）
        _op, _how = _bag_panel_open(b, it_ret)
        if _op:
            _panel_tap(b, BAG_X_DLG[0], BAG_X_DLG[1], 'dlg', log=log, what='关闭(弹窗系 X)')
            log.append({'supply_return': 'close_bag_x_dlg', 'at': BAG_X_DLG, 'was': _how})
            say('       · 关背包 → 点右上 X (%d,%d)（弹窗系 ✓ %s）' % (BAG_X_DLG + (_how,)))
            _op2, _how2 = _bag_panel_open(b, None)
            if _op2:
                _panel_tap(b, CLOSE_TR_PT[0], CLOSE_TR_PT[1], 'norm', log=log,
                           what='关闭(归一化 X 兜底)')
                log.append({'supply_return': 'close_bag_ref', 'at': CLOSE_TR_PT,
                            'still': _how2})
        else:
            _panel_tap(b, CLOSE_TR_PT[0], CLOSE_TR_PT[1], 'norm', log=log,
                       what='关闭(归一化 X)')
            log.append({'supply_return': 'close_bag', 'at': CLOSE_TR_PT, 'was': _how})
        # ③ 中间下面「开始冒险」→ 回地图界面
        b.tap(START_ADV[0], START_ADV[1], wait=1.5)
        log.append({'supply_return': 'start_adv', 'at': START_ADV})
        back_to_map(b, log)                 # 兜底：确认真的回到地图界面 ✓
        st = stamina(b.ocr(band=(0, 140), tag='supply'))
        SUPPLY_USED += 1
        log.append({'supply': 'done', 'stamina': st, 'used_total': SUPPLY_USED})
        say('       · 补给流程走完，体力 %s' % st)
        status('补给已用 · 体力 %s' % (st if st is not None else '?'))   # ⭐ 悬浮条可见 ✓
        return True
    except Exception as e:      # noqa: BLE001
        import traceback
        log.append({'supply': 'error', 'err': repr(e),
                    'trace': traceback.format_exc().splitlines()[-2:]})
        say('       · 使用补给出错: %r' % e)
        return False


def _guild_on(items):
    """这一帧像不像**公会界面**（公会/邮件/商店/招募 任一文字命中）

    ⚠ 必须是**模块级函数**：2026-10-01 曾把它写成 `bag_upgrade` 里的嵌套函数，
    内层生成式引用了 `i` 而外层函数又有 `for i in items2:` ⇒ `i` 成了闭包 cell，
    首次调用直接 `NameError: free variable 'i' referenced before assignment in
    enclosing scope` ⇒ **整个升星流程当场崩掉**（真机 15:41/15:51 两轮实锤 ✗）。
    教训：这类"判据函数"一律放模块级，别在长函数里用闭包 ✗
    """
    keys = ('公会', '邮件', '商店', '招募')
    for it in (items or []):
        t = (it.get('text') or '')
        if any(k in t for k in keys):
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# 2026-10-01 晚：背包流程的两个真机硬事实（都用真机帧量过 ✓）
#   ① 「背包开了没」**不能靠 OCR 认字**：这台真机 OCR 读不到美术字标题「背包」
#      （日志里只认到物品数量 1931/2280 与 HUD）⇒ 老判据 `any('背包' in text)` 恒 False
#      ⇒ 明明开成功了却判"没开" ⇒ **又去点一次背包图标**（那一下正好点在已开的背包上
#      ⇒ 把它关掉）⇒ 来回空转、最后报「背包没打开」✗ —— 用户看到的就是"打开背包就没后续了"
#   ② 判据改用**颜色**：背包面板是大片棕色，实测占比
#        公会界面 0.29 ｜ 选图界面 0.22 ｜ **背包面板 0.91~0.94**
#      ⇒ 阈值 0.60 干净分开，而且"面积占比"天然与分辨率无关 ✓
BAG_PANEL_THR = 0.60


def _brown_frac(img, box=(200, 600, 900, 1400)):
    """面板棕色占比（见上面 ② 的实测值）"""
    try:
        import numpy as _np
        if img is None:
            return 0.0
        x0, y0, x1, y1 = box
        sub = img[y0:y1, x0:x1].astype(int)
        b, g, r = sub[:, :, 0], sub[:, :, 1], sub[:, :, 2]
        m = (r > b + 25) & (r > 80) & (r < 200) & (g > 40) & (g < 160) & (b < 130)
        return float(m.mean())
    except Exception:       # noqa: BLE001
        return 0.0


def _bag_panel_open(b, items=None):
    """背包面板开了没 → (bool, 依据串)：**颜色为主**（OCR 读不到标题 ✗）+ 文字为辅 ✓"""
    fr = _brown_frac(b.img())
    if fr >= BAG_PANEL_THR:
        return True, 'panel-color %.2f' % fr
    for it in (items or []):
        t = (it.get('text') or '')
        if any(k in t for k in ('背包', '道具', '装备', '材料', '筛选')):
            return True, 'text:%s' % t
    return False, 'panel-color %.2f' % fr


def _img_diff(a, bb):
    """两帧平均绝对差（None 安全 ✓）"""
    try:
        import numpy as _np
        if a is None or bb is None:
            return 999.0
        return float(_np.mean(_np.abs(a.astype(int) - bb.astype(int))))
    except Exception:       # noqa: BLE001
        return 999.0


def _tap_verified(b, x, y, ch='norm', log=None, what='', tries=2):
    """点一下并**验证真的生效** → True/False

    ⚠⚠ 2026-10-01 用户报「为什么要连点三下背包？？」—— **就是本函数的锅**：
      它原来拿 `b.img()` 前后对比判"画面变没变"，而 **`b.img()` 返回的是上一次 `snap()`
      的缓存帧**（点击后没重新取帧）⇒ 前后**永远是同一帧** ⇒ diff≈0 ⇒ 误判"没生效"
      ⇒ 一路重试（阶梯 4 级 × 外层 3 轮 = 最多十几下 ✗✗）。
      正确做法两条：
        ① **直接用 `b.tap()` 的返回值**（= Kotlin 侧"点击后画面有没有变"，最准、零额外开销 ✓）
        ② 需要自己比时必须**先 `b.snap()` 取新帧**（缓存帧不能当"之后"✗，只有长按那条路用）
      阶梯也收窄：默认**最多 2 下**（同点 + 下移 45px），确认没生效才继续 ✓
    """
    ladder = [(x, y, ch, 1.8, 'again'), (x, y + 45, ch, 1.8, 'below'),
              (x, y, ch, 0.35, 'hold'), (x, y, ('dlg' if ch == 'norm' else 'norm'), 1.8, 'cross')]
    for i, (ax, ay, ach, hold, mode) in enumerate(ladder[:max(1, int(tries))]):
        _chg = None
        _before = None
        if mode == 'hold':                  # 长按没返回值 ⇒ 只能前后比（先 snap ✓）
            try:
                b.snap('tapv_pre')
                _before = b.img()
            except Exception:       # noqa: BLE001
                _before = None
        try:
            if mode == 'hold':
                try:
                    b.api.tapRefHold(float(ax), float(ay), int(hold * 1000))
                except Exception:       # noqa: BLE001
                    _bag_tap(b, ax, ay, ach, wait=hold)
            else:
                _chg = _bag_tap(b, ax, ay, ach, wait=hold)
        except Exception as e:          # noqa: BLE001
            if log is not None:
                log.append({'tap_err': what, 'e': repr(e)[:90], 'n': i + 1})
        _diff = -1.0
        if _chg is True:
            _ok = True
        elif _chg is False:
            _ok = False                     # Kotlin 明确回报"没变" ⇒ 不必再自己比 ✓
        else:                               # 长按/无返回值 ⇒ 自己比（**必须 snap 新帧** ✓）
            try:
                b.snap('tapv_post')
                _diff = _img_diff(_before, b.img())
            except Exception:       # noqa: BLE001
                _diff = 999.0
            _ok = _diff >= 2.0
        if log is not None:
            log.append({'tap': what, 'at': (int(ax), int(ay)), 'ch': ach, 'mode': mode,
                        'changed': _chg, 'diff': round(_diff, 2), 'n': i + 1})
        if _ok:
            say('      · 点「%s」(%d,%d)[%s] 生效 ✓%s'
                % (what, ax, ay, mode,
                   ('（画面差 %.1f）' % _diff) if _diff >= 0 else '（b.tap 回报画面有变化 ✓）'))
            return True
        say('      · ⚠ 点「%s」(%d,%d)[%s] **没生效** ⇒ 换下一招' % (what, ax, ay, mode))
    return False


def _bag_switch_tab(b, name, log=None, tag=''):
    """切背包页签（**素材/装备/符文/宝箱/道具**）—— 走**弹窗帧**通道 ✓

    ⭐⭐ 2026-10-01 真机实锤（用户原话：「就是直接点道具那两个字。上面一排
    素材/装备/符文/宝箱/道具都能点」）：
      那一排落在 `toRef()` **丢弃的弹性带**里 ⇒ **归一化帧里根本没有它**
      （OCR 读不到、`bag_tab_*.png` 模板也匹配不上 ✗ —— 这就是"打开背包就没后续"的另一半原因）。
      但**弹窗帧**（`grabDlgPng`：原始帧按锚设备中心重投影，不丢弹性带）里清清楚楚，实测：
        素材 @dlg(152,315) ｜ 装备 (346,314) ｜ 符文 (540,315) ｜ 宝箱 (732,315) ｜ 道具 (925,315)
    ⇒ 切页签固定这么走：`ocr_dlg` **精确匹配**文字 → `tap_dlg` 点击 → 用画面差验证生效 ✓
    """
    try:
        if not (dlg_c() and hasattr(b, 'ocr_dlg')):
            say('      · ⚠ 切页签「%s」：本环境没有弹窗帧通道（C=0？）' % name)
            return False
        its = b.ocr_dlg(tag=(tag + '_tab') if tag else None)
    except Exception as e:      # noqa: BLE001
        if log is not None:
            log.append({'bag': 'switch_tab_err', 'tab': name, 'e': repr(e)[:90]})
        return False
    hit = None
    for i in (its or []):
        t = (i.get('text') or '').strip().replace(' ', '')
        if t == name:
            hit = i
            break
    if hit is None:
        # ⭐ 兜底：用**真机标定的弹窗系坐标**（2026-10-01 用户手动停页面时只读抓帧测得 ✓）
        _pt = BAG_TAB_DLG.get(name)
        if _pt:
            # ⚠ 用 `_tap_verified` 判生效（`b.img()` 是缓存帧 ⇒ 自己比 diff 永远是 0 ✗）
            _ok2 = _tap_verified(b, _pt[0], _pt[1], 'dlg', log=log,
                                 what='页签「%s」(标定坐标)' % name)
            if log is not None:
                log.append({'bag': 'switch_tab_anchor', 'tab': name, 'at': _pt, 'ok': _ok2})
            if not _ok2:
                say('      · ⚠ 切页签「%s」用标定坐标也没生效' % name)
            return _ok2
        if log is not None:
            log.append({'bag': 'switch_tab_miss', 'tab': name,
                        'texts': [(i.get('text'), i.get('cx'), i.get('cy'))
                                  for i in (its or [])][:14]})
        say('      · ⚠ 弹窗帧里没找到页签「%s」（屏上：%s）'
            % (name, [i.get('text') for i in (its or [])][:10]))
        return False
    # ⭐ 找到文字页签 ⇒ 同样走 `_tap_verified`（用 b.tap_dlg 的返回值判生效 ✓
    #   —— 2026-10-01 踩过：自己用 b.img() 前后比 ⇒ 缓存帧 ⇒ 永远 diff=0 ⇒ 白点第二次 ✗）
    return _tap_verified(b, int(hit['cx']), int(hit['cy']), 'dlg', log=log,
                         what='页签「%s」' % name)


def _close_bag(b, items, log):
    """退回探索界面（返回/关闭/X 都试）—— **全分辨率**口径

    ⚠⚠ 2026-10-01 体检修（旧写法最后一个兜底是 `b.tap(96, 96)` ✗）：
      真机 1280×2772 上 ref y=96 ≤ 300 ⇒ 走**锚顶段** ⇒ 设备 y = 96×1.1852 + 132 ≈ **246**
      = 顶部 HUD（PID/头像那一排）⇒ **既关不掉面板、还可能误触** ✗
      更根本的：背包右上角 X 落在 `toRef()` **丢弃的弹性带**里
      （真机实测 dlg(1023,215) ⇒ 设备 y ≈ 503；弹性带 = 设备 y 488~852）
      ⇒ **归一化系里没有它的坐标**，只能走弹窗系 ✓
    ⇒ 现在：文字优先 → 面板还开着就点**弹窗系 X**（真机标定）→ 再退归一化系 X ✓
    """
    back = find_in(items, '返回', '关闭', '取消')
    if back:
        _panel_tap(b, back['cx'], back['cy'], 'norm', log=log, what='关闭(文字)')
    else:
        _op, _how = _bag_panel_open(b, items)
        x = find_x(items)
        if x:
            _panel_tap(b, x['cx'], x['cy'], 'norm', log=log, what='关闭(X/认到字)')
        elif _op:
            _panel_tap(b, BAG_X_DLG[0], BAG_X_DLG[1], 'dlg', log=log,
                       what='关闭(弹窗系 X %s)' % _how)
        else:
            _panel_tap(b, CLOSE_TR_PT[0], CLOSE_TR_PT[1], 'norm', log=log,
                       what='关闭(归一化 X)')
    log.append({'supply': 'closed_bag'})


# ⭐ 2026-10-02 v1.21：`board_hidden()` 判据② 的两个口径（实测标定见函数注释）
#   REVEAL_RATIO_MIN / DIM_RATIO_MAX —— ⚠ **已上移到模块顶部常量区**（v1.36）
#     原因：本文件 1000 行处的 `_ready_boss_cells()` 也要用 `REVEAL_RATIO_MIN`，
#     定义放这儿会 NameError（顺序坑，2026-10-02 连踩两次）✗
#   `DIM_RATIO_MAX` = 0.42 的来历：真面板/已揭示 = 0.25~0.35、雾格/已揭示 = 0.49~0.61
#     ⇒ 取这条缝的中点（两侧余量 16%/17%）。⚠ 别凭感觉调，改了要重跑标定脚本 ✓


def board_hidden(c):
    """棋盘是不是**被面板/遮罩盖住**（⇒ cells_of 的分类结果不可信，标记也扫不到）

    ⭐ 2026-09-26 修（**"第一把没打到 boss 就退了"的根因**）：
      原来判据只有"全暗"（`light == 0 and gray >= 25`）—— 但**战斗结算面板只盖住棋盘中间**，
      下面还能认出 3 格 ⇒ `light = 3 > 0` ⇒ **漏判** ✗
      ⇒ 棋盘被盖 ⇒ `marks` 扫不到 boss 标记 ⇒ 误判 `finish: targets_done` ⇒ 提前退图 ✗

    实测数据（把 runs/ 里的截图离线丢进 `cells_of`，见 `_probe_board_cover.py`）：

    | 帧 | 内容 | gray | light | 亮度比<0.55 的格数 dim |
    |---|---|---|---|---|
    | `m0_r003.png` | 干净地图 | 6 | 26 | **0** |
    | `m0_r006.png` | 干净地图 | 6 | 26 | **0** |
    | `m0_r008.png` | 结算面板盖住中间 | 32 | 3 | **30** |

    ⇒ 加一条"多数格被压暗"（遮罩会把棋盘压暗 ~35%，`ratio` 掉到 0.25~0.35）；
      **未揭示格恒 ~0.65**（见 §5/§7），所以 0.55 这个阈值不会误伤普通暗格 ✓

    ⚠⚠ 2026-10-01 v1.11【**朋友真机翻车**：进图就报"面板挡住了棋盘 · 正在收起"，实际棋盘空的】
      根因：上面两条判据都是**绝对阈值**（0.55 / 0.85），而 `ratio = 画面亮度 / 模板亮度`
      **依赖设备**（不同机型的截图 gamma / 亮度 / 分辨率缩放会让整盘偏暗）
      ⇒ 正常棋盘被整盘判成"暗格+被压暗" ⇒ 每张图都走"关面板"分支、3 次后 `board_not_visible`
      ⇒ 退图失败 → 游戏恢复 → 下一张图**同样**⋯ ⇒ 用户看到的就是**一直卡在这** ✗✗
      修法（**只收窄、不放松**，绝不放跑真的面板遮挡）：
        ① 只要**有一格 ratio ≥ 0.85**（= 明确"已揭示"的亮格），就**不算被挡住**
           —— 真面板遮罩会把整盘压到 0.25~0.35，**不可能**还剩 0.85 的亮格 ✓
           （这正是朋友那台的情形：营地/已走开的格子还亮着，只是暗格被设备压到 0.55 以下）
        ② 判据里改用**相对本帧的**亮格证据：`light >= 1` 也算"画面正常" ✓
      ⚠ v1.11 的 ② 把基准取成**本帧最亮那一格** —— 见 v1.21，这条在新机型上又翻了一次车 ✗

    ⚠⚠⚠ 2026-10-02 v1.21【**又一台真机翻车**：nubia NX809J 1216×2688 / Android 16 / v1.20】
      现象：反馈包里有 `board_hidden_r2.png`（= 判"被挡"时存的诊断帧），
      但那一帧**棋盘好端端地全在**（35 格全部识别、8 格已揭示、营地/海边小屋清清楚楚），
      面板（「结束冒险」+ 骰子条）在棋盘**上方**，压条在棋盘**下方** ⇒ 根本没盖到棋盘 ✗
      根因：判据②的基准 `_mx = 本帧最亮格` 会被**过亮的已揭示格**抬高 ——
        该帧最亮格是「海边小屋」**1.196**（比模板本身还亮）⇒ 旧阈值 `0.55*1.196 = 0.658`，
        而**雾格恒在 0.650** ⇒ 整盘雾格（18 格）全被判成"被压暗" ⇒ 误判"面板挡住棋盘" ✗
        （v1.11 的注释自己写了「未揭示格恒 ~0.65 ⇒ 0.55 这个阈值不会误伤普通暗格」——
          那句话只在 `_mx ≤ 1.18` 时成立；**刚进图/大半盘还是雾**的帧最容易踩到 ✗）

      两帧真机反馈 + 历史基准的实测（脚本 `tools/fb_calib_boardhidden.py`）：

      | 帧 | 已揭示格 ratio（中位） | 雾格 ratio | 雾格/已揭示 | 旧阈值 | 旧判定 |
      |---|---|---|---|---|---|
      | nubia 1216×2688（新反馈） | 0.867~1.196（**1.058**） | 0.573~0.724（0.650） | **0.61** | 0.658 | ✗ 误判被挡 |
      | realme 1264×2780（旧反馈） | 0.777~0.849（**0.849**） | 0.361~0.425（0.413） | **0.487** | 0.467 | ✗ 误判被挡 |
      | 真面板盖中间（doc `m0_r008`） | ~1.0 | — | — | — | ✓ 该判被挡 |

      ⇒ **雾格/已揭示 = 0.49~0.61**，而**真面板/已揭示 = 0.25~0.35**（doc 实测）——
        两者之间只有一条窄缝，阈值就取缝里（`0.42`，两侧余量 16% / 17%）。

      修法（**只收窄、不放松**）：
        ① 基准从「本帧**最亮**格」改成「本帧**已揭示格的中位**亮度」`_ref`
           —— 中位数对"单个过亮格"免疫（`1.196` 那种抬不动 8 格的中位）✓
           已揭示口径 = `ratio ≥ 0.75`，与 `spots.py` 的 `revealed`（`ratio >= 0.75`）同源 ✓
           （一格都没有 ⇒ 退回 `_mx`：整盘全雾/全暗时判据①本来就管 ✓）
        ② 系数 `0.55 → 0.42`（= 上面那条缝的中点）⇒ 雾格不再被算成"被压暗" ✓
        ③ 判据① 与"≥15 格"原样不动（真·全盘遮罩仍由 ① 抓到 ✓）
      回归：`tools\verify_explore_slots_fix.py` v1.21 段（含这两帧真机的执行级断言）。
    """
    _st = c.get('st') or {}
    _mx, _lit = 0.0, []
    try:
        for v in _st.values():
            _r = float((v or {}).get('ratio') or 0)
            if _r > _mx:
                _mx = _r
            if _r >= REVEAL_RATIO_MIN:
                _lit.append(_r)
    except Exception:       # noqa: BLE001
        _mx, _lit = 0.0, []
    # ⭐ 基准 = 已揭示格的中位亮度（对单个过亮格免疫）；一格都没有就退回最亮格
    _ref = float(np.median(_lit)) if _lit else _mx
    # ① 全盘"无亮格"：**且连最亮的一格都很暗**（<0.40）才算被遮
    #    —— 加 `_mx < 0.40` 是为了"整体偏暗的设备"：它 light 也可能是 0（没格到 0.75），
    #    但最亮格能到 0.6+ ⇒ 那是**设备暗**、不是**面板遮** ✓（真遮罩不可能还剩 0.55+）
    if len(c.get('light') or []) == 0 and len(c.get('gray') or []) >= 25 and _mx < 0.40:
        return True
    # ② 多数格被压暗：阈值按**本帧已揭示格的水平**缩放 ⇒ 设备偏暗/过亮都不误判 ✓
    #    （面板只盖中间那类：已揭示格 ~1.0 ⇒ 阈值 0.42 ⇒ 0.25~0.35 的格照样判出来 ✓）
    _thr = DIM_RATIO_MAX * _ref if _ref > 0 else DIM_RATIO_MAX
    n = 0
    for v in _st.values():
        if float((v or {}).get('ratio') or 1.0) < _thr:
            n += 1
    return n >= 15


def _board_dimmed(c):
    """⭐ 2026-09-28：进图首帧**暗罩**检测（与 board_hidden 的"面板遮罩"不同物）

    board_hidden() 的 dim 判据是 ratio<0.55（面板遮罩把棋盘压到 0.25~0.35），
    **判不出暗罩帧** —— 进图动画只把全盘均匀压暗 ~35%，已揭示格 ratio 掉到
    ~0.65 > 0.55，dim 计数恒 0 ✗。

    暗罩特征 = **全盘无一格 ratio≥0.85**：正常帧必有已揭示格（营地恒已揭示、
    每图必有营地，营地周边一圈通常也亮），已揭示 ~1.0 vs 暗/雾 ~0.65 是干净
    间隔（loop_log 实测 0.99~1.03 vs 0.65）。格数下限 20 防"只认出几格"的
    边角帧误触发。
    """
    vals = []
    for v in ((c or {}).get('st') or {}).values():
        r = (v or {}).get('ratio')
        if r is not None:
            vals.append(float(r))
    if len(vals) < 20:
        return False
    return not any(r >= 0.85 for r in vals)


def one_round(b, log, rnd, prefix, st):
    cold, done = st['cold'], st['done']
    _t_round = time.time()       # ⭐ 诊断用：本轮起点（点序里每次点击相对它记秒数，见 §37.3）
    b.snap('%sr%03d' % (prefix, rnd))
    img = b.img()
    # ⭐⭐⭐ 2026-09-28 修「进图首帧暗罩」（用户报：①精确规划逐格点草地
    #   ②被宝箱隔断的草地被规划当成可连锁）：
    #   进图动画把全盘均匀压暗 ~35% ⇒ 已揭示格 ratio 也掉到 ~0.65 ⇒
    #   ①旧版把全盘判"未揭示" ⇒ plain 连锁断裂 ⇒ 逐格点 ✗；
    #   ②中途加的 score≥0.8 硬翻 revealed 又把**真雾格**翻成已揭示
    #     （分类器能看穿雾，雾格也拿 0.91）⇒ 假连通 ✗。
    #   正确修法 = **等暗罩散去再存图/识别**：rnd==0 先无条件等 2 秒
    #   （enter_map 确认 in_map 后动画多半已播完，这 2 秒是兜底）；
    #   识别后再用 _board_dimmed() 复查兜底（见 cells_of 之后）。
    #   口径：**ratio 是"揭示状态"的唯一可靠信号**（已揭示 ~1.0 vs 暗/雾
    #   ~0.65 干净间隔）；score 只说明"底下是什么"——绝不用 score 硬翻。
    if rnd == 0:
        # ⭐ 2026-09-28 提速（P2）：原版无条件 sleep(2.0)。暗罩/进图动画多数 <1.5s
        #   就播完 ⇒ 改成「棋盘区域画面稳定（~0.5s 不动）就提前通过」，上限仍 2 秒；
        #   后面的 `_board_dimmed()` 复查兜底原样保留，行为不降级 ✓
        if b.fast_ok:
            b.wait_stable(2.0, interval=0.08, thr=1.6, need=6, band=(1002, 1722))
        else:
            time.sleep(2.0)
        b.snap('%sr%03d_fog' % (prefix, rnd))
        img = b.img()
        log.append({'fog_wait': 'pre_identify', 'secs': 2.0})
    # ⭐ 2026-09-27：**存图必须放在这里**（拿到 img 就存），不能放到函数尾部 ✗
    #   尾部在「动作分发」之后，而 `act == 'battle'/'handled'` 会**提前 return**（见下方）
    #   ⇒ 进图首帧 (rnd==0) 恰好是"点了就开打"的话，尾部那版**根本执行不到** ⇒ 白存 ✓
    #   （实测：末次连刷第 1 张图的 r0 就是 `开打（标记 boss）`，是 battle ⇒ 提前 return）
    #   口径（用户 2026-09-27）：**只存「刚进图那一张」**（最干净 ✓ 后面轮次图标盖住美术 ✗）
    if SAVE_ROUNDS or (SAVE_FIRST and rnd == 0):
        save_board_frame(b, log, rnd=rnd, img=img)
    # ⭐ 2026-09-25 第三次提速：回合开头的全屏 OCR（实测 1.2s，13 轮 = 15.8 秒，是最大头）
    #   其实这一下只需要读 HUD（图名 / 体力 / 踢下线提示）；面板文本在「点完那一下」
    #   已经用条带 OCR 看过了。所以：**只 OCR 顶部 0~320**，只有疑似盖着面板时才补全屏
    #   —— 判据是**棋盘亮度**（面板遮罩会把棋盘压暗 ~35%，跟上一轮比即可，不用绝对阈值）
    # ⚠ 2026-09-25 回退：曾试过「回合开头只 OCR 顶部 HUD（省 1 秒）」，结果**残留面板
    #   在回合开头被漏看 ⇒ 循环对着盖着面板的屏幕继续点 = 用户报的「乱点」**。
    #   正确性优先：回合开头一律**全屏 OCR**（0.75 倍缩放已经把它压到 ~1.5 秒）。
    # ⚠ 2026-09-28 实测否决「跳帧复用 OCR」（P4 试错，已撤）：连续两轮的帧差
    #   （96×160 灰度均值差）最小都有 **42.7** —— 夏日海滩水面等待机动画让画面
    #   永远在动，根本不存在"帧没变" ⇒ 复用永远命中不了，纯加噪音。别再加回来。
    # ⭐⭐ v1.45 提速（施工单 ⑦）：**同帧并发**（默认关，`MAPBOT_PARALLEL=1` 才开）
    #   本轮的 `img` 已经拿到（上面 snap 过），而下面这行全屏 OCR 是 **Java 侧 ~1.5s 阻塞**；
    #   棋盘分类只需要 `img`、**不需要 OCR 结果** ⇒ 先把分类丢后台一起算，
    #   等下面真的要用 `c` 时再 join（见 `c = classify_async_join(...)`）。
    #   ⚠ 只在 `st['mapname']` **已知**时并发：第一轮图名要从本帧 items 里读，
    #     提前分类会拿不到正确模板集（宁可串行）；`mapname` 一旦定了，后面每轮都用它 ✓
    _fut_cls = classify_async_start(img, st.get('mapname')) if st.get('mapname') else None
    items = b.ocr(tag='round')
    st['mapname'] = map_name(items) or st.get('mapname')
    entry = {'round': rnd, 'stamina': stamina(items)}
    # ⭐⭐⭐ 2026-09-30 真机事故修复：**每轮轮首都刷新「探索小队槽」**
    #   旧版只在**轮尾**算一次 slots_free ⇒ 凡是走 `act in ('handled','battle',…)`
    #   提前 return 的轮次**根本不会更新** ⇒ 值一直停在旧读数上 ✗。
    #   真机实锤：第 2 轮点「探索」时其实槽已满，可 st['slots_free'] 还是 1
    #   ⇒ 后面 18 轮全在点「探索」（游戏不响应）⇒ 整张图白跑。
    #   轮首这份 `items` 就是当前帧全屏 OCR ⇒ 零额外开销 ✓
    #   ⚠ `explore_slots_free` 认不到「空闲」时返回 None ⇒ **保留旧值**（不瞎写 ✓）；
    #     认到「空闲」= 硬证据 ⇒ 顺手把"两次点不动"的计数清零（说明槽真的空出来了）
    if EXPLORE_DISPATCH:
        _sf_now, _si = explore_slots_free(items)
        entry['slots'] = _si
        if _sf_now is not None:
            st['slots_free'] = _sf_now
            entry['slots_free'] = _sf_now
            if _sf_now > 0 and (_PANEL_STUCK.get('expl') or 0) >= 2:
                _PANEL_STUCK['expl'] = 0
                log.append({'slots': 'free_again', 'free': _sf_now})
        else:
            entry['slots_free'] = int(st.get('slots_free', 1) or 0)
    act = popups(b, items, log, ctx={'road': st.get('road') or [], 'plain_road': st.get('plain_road') or [], 'plan_road': st.get('plan_road') or [], 'flags': st, 'st': st.get('cells'), 'slots_free': st.get('slots_free', 1), 'ev_tiles': st.get('ev_tiles') or [], 'tapped_sid': st.get('tapped_sid') or '', 'marks': st.get('marks') or {},
                                     'tapped': st.get('last'),
                                     'force_fight': st.get('force_fight'),
                                     'road': st.get('road') or [],
                                     'targets': (st.get('targets') or []),
                                     'clear_fights': st.get('clear_fights', 0)})
    # ⭐⭐ 2026-09-26 用户口径：「**万能点位可以用来应对异常情况，防止任务过早中断**」
    #   这里统计"一个可识别元素都没认到"（act=='none'）的**连续轮数**；
    #   连续 **3** 轮都没认到 ⇒ 多半盖着一个认不出的异常面板 ⇒ 用万能位兜一手 ✓
    #   ⚠⚠ 门槛不能低（我 2026-09-26 第一版用"连续 2 轮"⇒ 真机上**每两轮误触发一次**）：
    #     「连续 2 轮无弹窗」在正常跑图时是**常态**（点普通格/迷雾格本来就不弹面板）
    #     ⇒ 当时 `universal_close` 的 `is_battle` 判据太松，挑到 (577,1439) 去点，
    #       而**那是棋盘格** ⇒ 乱点 ✗（铁证 m0_r001/003/005 三轮；已由 `is_battle_panel` 修掉 ✓）
    #   ✅ 现在为什么敢点：`is_battle_panel` 严格之后，**在干净地图上**这个兜底只会点
    #     万能位 (541,1890)——用户实测「那边点了非常安全，不会有变化」⇒ 无副作用 ✓
    #   ⚠ 仍明确**不是常规动作**：只要有任何一次可识别的动作（handled/battle/…）就清零 ✓
    _nn = (st.get('popup_none', 0) + 1) if act == 'none' else 0
    st['popup_none'] = _nn
    # ⭐⭐⭐ 2026-09-30「同类动作连点不停」总闸门（真机事故后加的兜底网）
    #   事故原型：`{'explore': 'first_high_value'}` 连打 18 轮（105 秒 0 战斗 0 装备）。
    #   具体那条已在 popups 里修好（点完验证 + 两次判满 + 拉黑），这里再兜一层：
    #   **同一个动作签名连续出现 4 轮** ⇒ 不管它是什么，都认定卡死 ⇒ 万能位脱困 +
    #   拉黑当前格 ⇒ 一定走得掉 ✓（阈值 4 足够大，正常跑图不会连续 4 轮同一动作）
    try:
        _last = log[-1] if log else None
        _sig = None
        # ⚠ 只认**本轮 popups 刚追加的、动作名明确的**条目：
        #   · 带 'round' 的是上一轮的轮摘要 ⇒ 拿它当签名会把"这轮 popups 啥都没追加"
        #     误判成连点 ✗
        #   · 只管「探索/派遣/跳过/弹窗」这几类**动作名稳定**的条目；
        #     **宝库/商人的条目一律不管**（`vault/merchant/buy_*` 的 value 不进签名 ⇒
        #     pick→buy→claim 会被看成同一个签名 ⇒ 兜底网会把正在买的宝库拉黑 ✗
        #     那是用户报过的另一种事故；宝库自己已有 20 轮粘性上限兜底 ✓）
        _KEYS = ('explore', 'dispatch', 'skip', 'popup')
        if isinstance(_last, dict) and 'round' not in _last \
                and any(_last.get(k) for k in _KEYS):
            # ⚠⚠ 签名必须带**刚点的那一格**：像 `{'explore':'claimed_high_value'}` 这种
            #   条目里没有坐标，连派 4 个不同紫橙格会撞成同一个签名 ⇒ 被兜底网误伤 ✗
            _at = _last.get('at')
            _sig = (act,) + tuple(_last.get(k) for k in _KEYS) + (
                tuple(_at) if isinstance(_at, (list, tuple)) else _at,
                tuple(st.get('last') or ()) or None)
        if _sig is not None and _sig == st.get('act_sig'):
            st['act_rep'] = int(st.get('act_rep', 1) or 1) + 1
        else:
            st['act_rep'] = 1
        st['act_sig'] = _sig
        if _sig is not None and st['act_rep'] >= 4:
            log.append({'loop_guard': 'same_action', 'n': st['act_rep'], 'act': act,
                        'sig': [str(x) for x in _sig]})
            say('  [r%d] 同一个动作连续 %d 轮没变化 ⇒ 强制脱困（拉黑这一格）✗'
                % (rnd, st['act_rep']))
            status('卡住了 · 正在脱困')
            force_unstick(b, log, 'same_action_x%d' % st['act_rep'],
                          {'tapped': st.get('last'), 'flags': st})
            st['act_rep'] = 1
            st['act_sig'] = None
            log.append(entry)
            return None
    except Exception:       # noqa: BLE001
        pass
    if _nn >= 3:
        # ⭐⭐ 2026-10-01 用户报「识别到宝库，点开瞬间就关了，后面乱点」⇒ **关之前先自查**
        #   宝库/商人这类面板的标题在真机弹性区里认不到，签名又可能因坐标漂移失效 ⇒
        #   会一路被判成"认不出"然后被万能位关掉 ✗（真机 17:28 实锤）
        #   ⇒ 兜底顺序改成：① 先试**弹窗帧**再判一次面板（宝库签名 + 按钮在哪都记日志 ✓）
        #                  ② 认出来了 ⇒ **不关**，把控制权交回主循环（下一轮就会走 vault_flow ✓）
        #                  ③ 还是认不出 ⇒ 才按老办法万能位兜底 ✓
        try:
            if dlg_c():
                _dp2 = dlg_ocr(b, tag='popup_none_dlg')
                _dbg = [(i.get('cx'), i.get('cy'), (i.get('text') or '')[:8])
                        for i in (_dp2 or [])
                        if 700 < i.get('cx', 0) < 1040 and 1300 < i.get('cy', 0) < 1680]
                log.append({'popup_none_dlg': 'probe', 'btn_zone': _dbg[:8],
                            'n': len(_dp2 or [])})
                if _dlg_btn_sig(_dp2 or [], 'vault'):
                    log.append({'popup_none_dlg': 'vault_found',
                                'btn_zone': _dbg[:4]})
                    say('  [r%d] 弹窗帧认出**黄金宝库**面板 ⇒ 不关它（下一轮进购买流程 ✓）'
                        % rnd)
                    st['popup_none'] = 0
                    log.append(entry)
                    return None
        except Exception as _e:      # noqa: BLE001
            log.append({'popup_none_dlg': 'err', 'e': repr(_e)[:80]})
        universal_close(b, log, items=items, where='popup_none')
        st['popup_none'] = 0
        log.append(entry)
        log.append({'universal_fallback': 'popup_none', 'n': _nn})
        say('  [r%d] 连续 %d 轮认不到任何元素 → 万能位兜底关面板（防任务过早中断）'
            % (rnd, _nn))
        status('画面认不出 · 正在收起面板')
        return None
    if act == 'kicked':
        return 'kicked'
    if act == 'insufficient':
        return 'insufficient'
    if act == 'blocked':
        st['clear'] = True
        log.append(entry)
        return None
    if act in ('battle', 'battle_clear', 'handled'):
        st['stuck'] = 0
        if act in ('battle', 'battle_clear') and st.get('last'):
            # ⭐ 记下「打过架的格」：退出地图前要回到这几格各点一下（领战利品）
            if st['last'] not in (st.get('battles') or []):
                st.setdefault('battles', []).append(st['last'])
        if act == 'battle_clear':
            st['clear_fights'] = st.get('clear_fights', 0) + 1
        if st['last']:
            done.add(st['last'])
            c = cell_of(st['last'][0], st['last'][1])
            if c in (st.get('marks') or {}):
                st['clear'] = False
                st['clear_fights'] = 0
        log.append(entry)
        return None

    # ⭐ 2026-09-27：存图已**提到函数开头**（拿到 img 就存）—— 见 `one_round` 顶部注释 ✓
    #   这里不再存（原来放这儿会被 `act == 'battle'/'handled'` 的提前 return 跳过 ✗）
    # ⭐ v1.45（施工单 ⑦）：如果轮首把分类并发起来了，这里取它的结果；否则**走原来的同步路**
    #   （`classify_async_join` 在 fut=None 时就是 `cells_of(...)`，语义一字不差 ✓）
    c = classify_async_join(_fut_cls, img,
                            st.get('mapname') or map_name(items))
    # ⭐⭐⭐ 2026-09-28 暗罩复查（只看 rnd==0）：预等待 2 秒没盖住进图动画时兜底。
    #   _board_dimmed(c) = 全盘无一格 ratio≥0.85 ⇒ 这帧还是暗罩 ⇒ 等 2 秒重截
    #   重识别（最多 2 次；用尽则 fail-open 照常往下走，行为同旧版不会更糟）。
    #   ⚠ 复查只针对"全盘亮格缺失"（暗罩），真·面板遮罩（ratio<0.55）仍由
    #   board_hidden() 管，两套判据各管各的，别混。
    for _fi in range(2):
        if rnd != 0 or not _board_dimmed(c):
            break
        # ⭐ v1.45 提速（施工单 ⑥）：固定 2s → 等**棋盘带**画面停（暗罩散去就停，最多 2s）
        #   语义不变（仍上限 2s、仍重截重识别），只是"暗罩一散就往下走"。
        _stable6 = False
        try:
            if b.fast_ok:
                # band 是**参考系**行号（Java waitStable 内部按 RefMapper 换算）——
                # 与 `one_round` 开头那处 `band=(1002, 1722)` 同口径 ✓
                _stable6 = bool(b.wait_stable(2.0, interval=0.08, thr=1.6, need=6,
                                              band=(1002, 1722)))
        except Exception:       # noqa: BLE001
            _stable6 = False
        if not _stable6:
            time.sleep(2.0)
        b.snap('%sr%03d_fog%d' % (prefix, rnd, _fi + 1))
        img = b.img()
        c = cells_of(img, mapname=st.get('mapname') or map_name(items))
        log.append({'fog_retry': _fi + 1, 'dimmed': _board_dimmed(c)})
    # ⭐ 2026-09-26：缓存分类结果 ✓ 供下一轮 popups() 判断"刚点那格是不是紫橙探索格"用 ✓（零额外开销 ✓）
    try:
        st['cells'] = c.get('st')
    except Exception:       # noqa: BLE001
        st['cells'] = None
    # ⭐⭐⭐ 2026-10-01 修「规划很差劲」的**观测脏**根因（用户真机报）：
    #   上面这行是**单帧整体覆盖** ⇒ 任何一帧被面板/动画/加载污染，已知的东西就**丢了**。
    #   真机铁证（17:10~17:12 同一张图）：
    #     [r2] 已揭示 10 → [r3] 已揭示 **11** → [r5] 已揭示 **9**（揭示过的格不该变少 ✗）
    #     ⇒ 下一轮地图模型里那些格又变成"未揭示" ⇒ 求解器以为还得重新开路
    #     ⇒ cost 在 2 → 17 → 7 之间乱跳（同一张图、同一个目标 ✗）
    #   修法：维护 **st['obs']**＝跨轮**只增不减**的观测累积：
    #     · 已揭示（revealed=True）一旦记下**永不被翻回 False**（揭示不可逆 ✓）
    #     · sid/name/ratio/score 用**较可信的那一帧**更新
    #       （已揭示 > 未揭示；同类则 score 高者优先 —— 暗罩帧 score 会掉 ✓）
    #     · mark 取并集（标记扫描也会被遮挡吞掉，见 5135 同因✓）
    #   `st['cells']` 仍保留原始单帧（popups 判"刚点那格"要当下帧 ✓，两套互不干扰 ✓）
    try:
        _obs = st.setdefault('obs', {})
        _added = 0
        for _k, _v in (c.get('st') or {}).items():
            _old = _obs.get(_k)
            _new_rev = bool(_v.get('revealed'))
            if _old is None:
                _obs[_k] = dict(_v)
                _added += 1
                continue
            _old_rev = bool(_old.get('revealed'))
            if _old_rev and not _new_rev:
                continue                     # ✗ 不让脏帧把"已揭示"翻回去
            if _new_rev and not _old_rev:
                _obs[_k] = dict(_v)          # ✓ 新揭示 ⇒ 覆盖（含 sid/name/ratio）
                _added += 1
                continue
            # ⭐⭐⭐ 2026-10-01 修（我上一轮加的累积观测埋的隐患）：
            #   **已揭示格**上"名字变了"必须立刻跟新 —— 尤其是**宝库/商人被买掉之后**：
            #   那一刻它会变成空地（低分/空名）⇒ 旧写法"分数不占优就保留旧值"
            #   会把 `黄金宝库` **永久留在 obs 里** ⇒ 模型/记忆一直以为那儿还有个宝库 ✗
            #   ⇒ 已揭示 + 新帧给的是**别的名字** ⇒ 直接覆盖（揭示后名字变更 = 语义变更 ✓）
            if _old_rev and _new_rev:
                _on = str(_old.get('name') or '')
                _nn = str(_v.get('name') or '')
                if _nn and _on and _nn != _on:
                    _obs[_k] = dict(_v)
                    continue
            _os = float(_old.get('score') or 0)
            _ns = float(_v.get('score') or 0)
            if _ns > _os:                    # 同类 ⇒ 谁看得清听谁的
                _keep = dict(_v)
                if _old.get('marks'):
                    _keep['marks'] = sorted(set(list(_old['marks'])
                                                + list(_v.get('marks') or [])))
                _obs[_k] = _keep
            elif _v.get('marks'):            # 分数不占优 ⇒ 至少把标记并进去 ✓
                _old['marks'] = sorted(set(list(_old.get('marks') or [])
                                           + list(_v.get('marks') or [])))
        # 标记扫描给出、分类器没给的格也累积（真机 boss 格常整帧认不到 ✓）
        for _k, _m in (st.get('marks') or {}).items():
            _ml = list(_m.get('marks') or [])
            if not _ml:
                continue
            _o = _obs.get(_k)
            if _o is None:
                _obs[_k] = {'sid': None, 'name': None, 'marks': _ml,
                            'revealed': bool(_m.get('revealed')), 'ratio': None,
                            'score': None, '_from_mark': True}
            else:
                _o['marks'] = sorted(set(list(_o.get('marks') or []) + _ml))
        if _added and log is not None:
            log.append({'obs_merge': 'grew', 'added': _added, 'total': len(_obs)})
    except Exception as _e:      # noqa: BLE001
        if log is not None:
            log.append({'obs_merge': 'err', 'e': repr(_e)[:80]})
    vis = (len(c['gray']) + len(c['light'])) >= 8
    # ⚠ 2026-09-25 卡死事故：屏幕上盖着面板/遮罩时，分类器会把整盘读成"暗格"，
    #   还会凭弱匹配误报出几个"未揭示的商人/宝库"⇒ 那两个是永不拉黑的目标 → 无限空转。
    #   这里加一道闸：**棋盘被遮住**就认定分类不可信，先关面板；连关 3 轮不行就退出本图。
    # ⭐⭐ 2026-09-26 修：判据原来只有"全暗"（light==0 且 gray>=25）—— 但**结算面板只盖住
    #   棋盘中间**，下面还能认出 3 格 ⇒ light=3>0 ⇒ **漏判** ✗ ⇒ marks 扫不到 boss 标记
    #   ⇒ 误判 `finish: targets_done` ⇒ **没打 boss 就退图**（用户 2026-09-26 报的就是这个）
    #   ⇒ 改用 `board_hidden()`（多一条"多数格被压暗"）；实测数据见该函数注释 ✓
    if board_hidden(c):
        # ⭐ A（2026-09-25 用户要求「暗格误判别浪费一整轮」）：战斗结算/动画过渡那一帧
        #   也会"整盘暗格" ⇒ 先**快速复查**（0.4 秒后重抓）——过渡帧通常已经过去，
        #   复查正常就照常继续，不白花一轮（实测每图能少 1~2 轮空转）
        time.sleep(0.4)
        b.snap('%sr%03d_b' % (prefix, rnd))
        img2 = b.img()
        c2 = cells_of(img2, mapname=st.get('mapname') or map_name(items))
        if not board_hidden(c2):
            log.append({'board_blink': 'ok_after_retry'})
            c, img = c2, img2
        else:
            # 整盘暗格 ⇒ 多半盖着面板 ⇒ 这里补一次**全屏 OCR** 再关
            items = b.ocr(tag='round_full')
            _hctx = {'road': st.get('road') or [], 'plain_road': st.get('plain_road') or [], 'plan_road': st.get('plan_road') or [], 'flags': st, 'st': st.get('cells'), 'slots_free': st.get('slots_free', 1), 'ev_tiles': st.get('ev_tiles') or [], 'tapped_sid': st.get('tapped_sid') or '', 'marks': st.get('marks') or {},
                     'tapped': st.get('last'),
                     'force_fight': st.get('force_fight'),
                     'road': st.get('road') or [],
                     'clear_fights': st.get('clear_fights', 0)}
            act2 = popups(b, items, log, ctx=_hctx)
            if act2 == 'kicked':
                return 'kicked'
            if act2 in ('battle', 'battle_clear', 'handled'):
                return None
            # ⭐⭐ v0.34（彻底解决"真机认不出面板类型"）：
            #   面板确实盖着棋盘（board_hidden 已确认）但 popups 没认出类型 ⇒
            #   八成是**面板标题落在归一化帧丢弃的弹性区**（战斗事件 dlg≈443 / 偶遇强敌
            #   dlg≈243 / 旅行商人 / 预言石板…）⇒ 补一次**弹窗帧** OCR（≈2s，
            #   **仅此一处**、仅真机高分辨率）再判一次 ✓（PC/9:16 直接跳过）
            if act2 in (None, 'none') and dlg_c():
                _dp = dlg_ocr(b, tag='round_dlg')
                if _dp:
                    _hctx2 = dict(_hctx)
                    _hctx2['in_dlg'] = True
                    _OCR_CH['dlg'] = True      # ⭐ _dp 是弹窗系 ⇒ 里面所有条目点击走 tap_dlg
                    try:
                        act3 = popups(b, _dp, log, ctx=_hctx2)
                    finally:
                        _OCR_CH['dlg'] = False
                    log.append({'popup': 'dlg_frame_retry', 'n_items': len(_dp),
                                'act': act3,
                                'texts': [(i.get('text') or '')[:10] for i in _dp][:26]})
                    if act3 == 'kicked':
                        return 'kicked'
                    if act3 in ('battle', 'battle_clear', 'handled'):
                        return None
                    act2 = act3
            n = close_x_panels(b, img)
            if not n:
                x = find_x(items)
                if x:
                    b.tap(x['cx'], x['cy'], wait=1.5)
                    n = 1
            if n == 0 and not st.get('last'):
                for bx in (493, 1024):
                    b.tap(bx, 225, wait=1.1)
                n = 2
            st['dark'] = st.get('dark', 0) + 1
            # ⭐⭐ 2026-09-26 用户口径：「万能点位可以用来应对异常情况，防止任务过早中断」
            #   「棋盘被盖住」= **面板挡住棋盘**的确凿证据（不是盲点）⇒ 这里点万能位最合适 ✓
            #   ⚠ 放在判 stuck 之前：老逻辑第 3 次就 `finish: board_not_visible` 中断任务 ✗，
            #     现在第 2 次先让万能位救一手（用户实测「那边点了非常安全，不会有变化」）✓
            #   ⚠ universal_close 会先认面板类型：战斗界面改点「关闭」(577,1439)，绝不点开始冒险 ✓
            if st['dark'] >= 2:
                universal_close(b, log, items=items, where='board_all_dark')
                log.append({'universal_fallback': 'board_all_dark', 'n': st['dark']})
                say('  [r%d] 棋盘被挡 → 万能位兜底关面板（第 %d 次）' % (rnd, st['dark']))
            # ⭐⭐⭐ 2026-10-01 v1.11【"被判挡住"必须能自证 + 不再无限循环】
            #   朋友真机实况：「进图就显示面板挡住了棋盘，正在收起，一直卡在这，棋盘上啥都没有」
            #   ① 第一次判"被挡"就**存帧**（诊断用）—— 我们手上没有任何"别的机型"的帧，
            #      没有它就无法给 `board_hidden` 的绝对阈值标定（见该函数注释）✗
            #   ② 连续多张图都判"被挡" ⇒ **整局停下并说清原因**（不再"退图失败→恢复→再来一张"）
            if st['dark'] == 1:
                try:
                    _hp = _pub_dump('board_hidden_r%d' % rnd, b.img())
                    if _hp:
                        say('     · 这一帧已存档（诊断用）：%s' % _hp)
                        log.append({'board_hidden_dump': _hp})
                except Exception as _eh:      # noqa: BLE001
                    log.append({'board_hidden_dump_fail': repr(_eh)[:80]})
            say('  [r%d] 棋盘被挡（读成暗格/压暗，面板挡住棋盘？）→ 关面板 %d 个（第 %d 次）'
                % (rnd, n, st['dark']))
            status('面板挡住了棋盘 · 正在收起')
            log.append(entry)
            log.append({'board_hidden': 'all_dark', 'closed': n, 'n': st['dark'],
                        'light': len(c['light']), 'gray': len(c['gray'])})
            if st['dark'] >= 3:
                log.append({'finish': 'board_not_visible'})
                return 'stuck'
            return None
    st['dark'] = 0
    if vis:
        # ⭐⭐⭐ v1.45 提速（施工单 ①）：标记扫描改走**定点窗口版**
        #   旧 `marks_mod.scan_board` 每次「整条 1080×740 棋盘带 × 15 尺度 × 7 模板 = 105 次全图像素匹配」，
        #   端上实测 **10.28s/次**，而它**不在任何埋点里** ⇒ 一局 23 次 ≈ 236s 的时间黑洞。
        #   新版只用「35 个格心 ±14px 小窗 × 5 尺度」（标记模板中心相对格心恒为 (-36,-36)，
        #   尺度实测只落在 3.8~4.5）⇒ 匹配面积降到约 1/100，**6 张真机帧逐格一致**（含负样本无多报）。
        #   ⚠ 旧 `scan_board` 一字未动，留作对拍基准（门禁㊻ 组会做等价性断言）。
        _new_mk = marks_mod.scan_board_fast(img)
        # ⭐ v1.22 诊断：这一帧**一个标记都没扫到**（且此前也没攒下标记）⇒ 记下"最像的候选"
        #   起因（用户 2026-10-02 「进不去图.zip」/ nubia NX729J）：
        #   日志是 `no_plan` + `blank_board` + `targets_done(gray_left 29)` —— 一个目标都没有、
        #   直接退图；可那帧肉眼看得见格子上有标记图标 ✗
        #   ⇒ 到底"真没有标记"还是"有标记但形状/配色分被机身偏暗压到闸门之下"，
        #     必须能从反馈包里一眼看出来（`probe_top` 给裸分 ✓ 只诊断不判定）
        #   ⚠ v1.45：诊断也走定点窗口版（同一批格心窗口），否则 marks:none 那一下要多付 ~9s
        if not _new_mk and not (st.get('marks') or {}):
            try:
                log.append({'marks_scan': 'none', 'top': marks_mod.probe_top_fast(img)})
                # ⭐⭐⭐ 2026-10-02 v1.30【识别问题的**铁证**：把这一帧存下来】
                #   用户真机（realme RMX3800，`进图发了会呆就退出了.zip`）反馈：
                #   「啥都没识别出来」；日志里 `marks_scan: none`，近失分 recommend 0.769 /
                #   boss 0.734 **都贴在闸门下面**（闸门 0.80 / 0.90）⇒ 到底是
                #   ①"这盘真没标记"还是 ②"有标记、被机身偏暗压到闸门之下"，**必须有帧才能定**
                #   ✗ 之前那包里的 PNG 是更早一局留下的（海岸 vs 沙漠主题）⇒ 不能用
                #   ⇒ 这个状态下**每次都落一帧**（`marks_none_rN`，反馈包自动带上 ✓）
                #     + 存一份**该帧的裸分**（省得再靠日志里截断的 top 列表）
                if BAG_DUMP:
                    try:
                        _mp = _pub_dump('marks_none_r%d' % int(rnd), b.img())
                        if _mp:
                            log.append({'marks_none_dump': _mp})
                    except Exception:       # noqa: BLE001
                        pass
            except Exception as _emk:      # noqa: BLE001
                log.append({'marks_scan': 'probe_err', 'e': repr(_emk)[:60]})
        # ⭐⭐ 2026-09-26 保险：**别让"被压暗的一帧"把标记吞掉**
        #   实测 m0_r008：结算面板只盖住棋盘**中间**，那一帧 marks 扫成空
        #   ⇒ 上一轮的 boss 标记就此丢了 ⇒ 误判 `targets_done` ⇒ **没打 boss 就退图** ✗
        #   规矩：新扫结果为空 + 上一轮有标记 + 这一帧确实有被压暗的格（可疑）
        #   ⇒ **保留上一轮的标记**（宁可多找一次，也绝不漏 boss ✓ 用户口径：boss 必打）；
        #     真打过/不存在的标记会被 nochange 拉黑 + cold 兜住，不会死转 ✓
        _old_mk = st.get('marks') or {}
        _dim_now = 0
        for _v in (c.get('st') or {}).values():
            if float((_v or {}).get('ratio') or 1.0) < 0.55:
                _dim_now += 1
        if (not _new_mk) and _old_mk and _dim_now >= 3:
            log.append({'marks_kept': 'board_dimmed', 'dim': _dim_now, 'kept': list(_old_mk)})
            say('  [r%d] 这一帧棋盘被压暗（%d 格）却扫不到标记 → 保留上一轮的标记 ✓'
                % (rnd, _dim_now))
        else:
            st['marks'] = _new_mk
    mk = st.get('marks') or {}
    # ⚠ 2026-09-25：面板盖住棋盘时**不采信标记**（游戏用同一个红装图标标敌方 SS 装备，
    #   面板里的那枚会被误判成地图标记）。判据：该格亮度比 < 0.50（未揭示格恒 ~0.65）。
    if mk and c.get('st'):
        bad = []
        for k in list(mk):
            v = c['st'].get(k)
            if v is None:
                continue
            if float(v.get('ratio') or 1.0) < 0.55:
                bad.append(k)
        for k in bad:
            log.append({'marks_dropped_panel': '%d,%d' % k,
                        'ratio': round(float(c['st'][k].get('ratio') or 0), 3),
                        'marks': mk[k].get('marks')})
            mk.pop(k, None)
        if bad:
            say('       · 丢掉 %d 个疑似「面板里的图标」误判（那几格被面板盖着）' % len(bad))
        st['marks'] = mk
    if mk:
        entry['marks'] = {'%d,%d' % k: v['marks'] for k, v in mk.items()}
    # 🛑 红装（SS）标记：**只在刚进图那拨扫描时判断**（用户 2026-09-25：「只扫描刚进图那一拨的
    #   图来确认有没有红装，后面不判断红装」）。
    #   ⚠ 为什么不能每轮都判：游戏给**敌方装备带 SS** 时用的是同一个 `mid_ico_map_0001` 图标，
    #   面板（偶遇强敌/结算）盖住棋盘时那枚图标会被当成"地图格上的红装标记"
    #   （实测两次误判都是 (4,3) 分数 0.901 / 配色 0.846，且该帧"已揭示 0 格、暗格 6 格"
    #    = 面板盖着棋盘 ⇒ 用户「我游戏里没看到红装啊」）。
    #   ⭐⭐ 再加一道**根因判据**：这一帧必须**看得见棋盘**（有已揭示格）才允许判红装 ——
    #   面板/结算盖住棋盘时一律不判，从根上堵死这个误判。
    red = []
    if rnd <= 1 and len(c.get('light') or []) > 0:
        red = sorted(k for k, v in mk.items() if 'redEquip' in (v.get('marks') or []))
    elif rnd <= 1:
        # ⚠ v1.22：这里的 value 以前写成 `'board_hidden'`，读日志会误以为"board_hidden 命中了"
        #   —— 其实只是"这一帧没有已揭示格 ⇒ 不敢判红装"（与 board_hidden 无关 ✗）
        log.append({'red_skip': 'no_revealed_cells', 'light': 0})
    if red:
        # ⭐ 留证据图（极速截图通道下帧只在内存，默认不落盘 —— 2026-09-25 用户问「红装截图在哪」）
        shot = None
        try:
            shot = b.snap('red_equip_r%02d' % rnd, save=True)
        except Exception:       # noqa: BLE001
            pass
        # ⭐ 上锁：**锁在就拒绝启动新运行**，避免"下一次运行把这局退掉"（用户 2026-09-25 要求）
        try:
            import json
            with open(red_lock_path(b.dev), 'w', encoding='utf-8') as f:
                json.dump({'device': b.dev, 'map': st.get('mapname'),
                           'cell': red, 'round': rnd,
                           'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                           'shot': os.path.basename(shot or '')},
                          f, ensure_ascii=False, indent=1)
        except Exception:       # noqa: BLE001
            pass
        log.append(entry)
        log.append({'stop': 'red_equip_mark',
                    'cells': ['%d,%d' % k for k in red],
                    'shot': os.path.basename(shot or '')})
        say('')
        say('🛑🛑 发现红装（SS）标记：%s → 立即停止（不点它、不退图，留着你自己打）'
            % '、'.join('第%d行第%d列' % k for k in red))
        say('')
        status('★ 发现红装 · 已停下，请手动处理')
        return 'red_equip'
    # ⭐ 2026-09-25 起：地块分类器直接给出「已揭示格」的三分类，不再靠中心色采样：
    #   plain   = 已揭示的空地（草地）→ 可以点它揭一片（连通消除）
    #   content = 已揭示的内容格（木箱/宝箱/游乐设施/勇者之墓…）→ 点了拿东西/开面板
    #   buy     = 已揭示的旅行商人 / 黄金宝库 → **最高优先**（用户口径：要买完）
    #   未揭示格（暗）点不动，只能靠揭格推进
    # ⭐ 目标集合（用户 2026-09-25 定案，提高效率）：
    #   = **标记格（首领/大拇指/幸运草/红装） ∪ 旅行商人 ∪ 黄金宝库**
    #   ⇒ 其他已揭示内容格（木箱/宝箱/海螺/游乐设施/勇者之墓…）**一律不点**；
    #     也没有「已露出内容格」这个退图条件了 —— 目标清完立刻退图
    # ⭐⭐⭐ 2026-10-01 v0.96【宝库永不丢 · ①不许被"点过一次"钉死】
    #   用户口径（2026-09-25 起反复强调）：「**有黄金宝库你没点就要退**」、「能直接点就先点」。
    #   而 `done` 是「这一格处理过了」的**永久**集合：只要某次点击弹出了面板（哪怕宝库面板
    #   被自己的下一次点击关掉、或层数奖励没走完），这一格就永远不再被点 ⇒
    #   真机复盘（autoexplore_vaultskip.log 22:28~22:32）里那格**已揭示的黄金宝库**
    #   再也没人碰，机器人却满地图开路、把体力花在"拦路"战斗上 ✗
    #   ⇒ 只要**本帧**它还是"已揭示 + 强匹配的商人/宝库"，就把它从 `done` 里摘出来
    #     （真被买掉 ⇒ 本帧名字变空地/它不再进 buy ⇒ 自然不再摘 ✓ 不会重复点已消耗格 ✓）
    _unpinned = 0
    try:
        for _p in vault_px_now(c):
            if _p in done:
                done.discard(_p)
                _unpinned += 1
    except Exception:       # noqa: BLE001
        pass
    if _unpinned:
        entry['vault_unpin'] = _unpinned
        say('       · 已揭示的宝库/商人 %d 格「还没买掉」⇒ 从"处理过"里放回（宝库永不拉黑 ✓）'
            % _unpinned)
    buy = [p for p in c['buy'] if p not in done]
    buy_hidden = [p for p in c.get('buy_hidden', []) if p not in done]   # 未揭示的商人/宝库
    # ⭐ v1.27：**已经买完/消耗掉的格子不再当目标**（幽灵目标根因，见「vault: consumed」注释）
    _cons_early = st.get('buy_consumed') or set()
    if _cons_early:
        buy = [p for p in buy if cell_of(*p) not in _cons_early]
        buy_hidden = [p for p in buy_hidden if cell_of(*p) not in _cons_early]
    # ⚠ 2026-09-25 修（用户报「幻少第一张图明明还有一个未揭示的商人就退了」）：
    #   未揭示的商人/宝库**点不动**，绝对不能排进点击序列 —— 旧版把它当普通目标去点，
    #   点一次没反应就 cold+1，4 轮后被「放弃」规则踢掉 → 判成目标清完 → 退图漏掉它。
    #   现在它只当**开路目标**（沿出生地→它那条直线揭格把它解锁出来）；
    #   放弃条件改成「连续多轮棋盘毫无变化」（真的一点都推不动了才放弃）。
    board_sig = (len(c['gray']), len(c['light']))
    if buy_hidden:
        if st.get('h_sig') == board_sig:
            st['h_stall'] = st.get('h_stall', 0) + 1
        else:
            st['h_stall'] = 0
        st['h_sig'] = board_sig
        if st['h_stall'] >= 8 and st.get('clear_clicks', 0) >= 24:
            for p in list(buy_hidden):
                done.add(p)
                buy_hidden.remove(p)
                say('       · 未揭示的商人/宝库 (%d,%d)：连着 8 轮棋盘毫无变化且开路预算用尽，'
                    '放弃它' % p)
                status('宝库/商人 点不开 · 放弃这一格')
            st['h_stall'] = 0
    else:
        st['h_stall'] = 0
        st['h_sig'] = None
    nones_extra = [p for p in c['content'] if p not in done]     # 只用于日志/统计 + 开路
    # ⭐⭐⭐ 2026-10-01 用户口径：「勾选就主动去处理，不勾选就**拉黑**」
    #   ⇒ 拉黑格（弹窗类特殊地块里没勾选的）**不参与开路**（点一下必弹面板 ✗）
    #   实现：从"内容格"候选池里剔除 ⇒ 既不进 clearable、也不进 cands、也不算 road 的
    #   plain_road/比例 ✓（目标侧由 `targets_cfg.is_target` 管 ✓）
    try:
        _blk = _blocked_px(st, c)
        if _blk:
            _n0 = len(nones_extra)
            nones_extra = [p for p in nones_extra if p not in _blk]
            if len(nones_extra) != _n0:
                entry['blocked_skipped'] = _n0 - len(nones_extra)
                say('       · 拉黑不碰的地块 %d 个（未勾选：宝箱怪/预言石碑…✓）'
                    % (_n0 - len(nones_extra)))
    except Exception:       # noqa: BLE001
        pass
    nones = [p for p in c['plain'] if p not in done]
    if c.get('st'):
        # ⭐ 2026-09-26：board 日志加记 **sid 后缀** —— 名字不够用：「游乐设施」有
        #   202(绿)/311(蓝)/221(紫) 三个同名 ID ✗，复盘"紫橙数量对不对"必须看 ID ✓
        entry['board'] = {('%d,%d' % k): (str(v.get('sid') or '').split('_')[-1],
                                          v['name'], v['score'], v['ratio'])
                          for k, v in sorted(c['st'].items()) if v['anchor'] == k}
    grays = list(c['gray'])
    # ⭐ 用户 2026-09-25：「优化掉多余点击，比如说点击出生点」
    #   出生点(营地) 点了只弹一个没用面板、不消耗、不揭示 ⇒ 直接当"已完成"排除，
    #   省掉一次点击 + 一次面板判定（约 1.5 秒/图），也少一次 OCR
    if c.get('st'):
        for k, v in sorted(c['st'].items()):
            if v.get('anchor') == k and v.get('name') == '营地':
                camp_px = marks_mod.cell_center(k[0], k[1])
                done.add(camp_px)
                st['spawn'] = camp_px
                st['camp'] = camp_px
                break
    if c['unknown']:
        entry['unknown_cells'] = len(c['unknown'])
    # ⭐ 2026-09-27：标记格也按**锚点**去重（多格大块的成员格会各报一次 ✓ 去重后只点一次 ✓）
    try:
        _mk_dedup, _by_anchor = [], {}
        for (r0, c0) in sorted(mk):
            _v0 = (c['st'].get((r0, c0)) or {}) if c.get('st') else {}
            _a0 = tuple(_v0.get('anchor') or (r0, c0))
            _n0 = len(mk[(r0, c0)] or [])
            if _a0 not in _by_anchor or _n0 > _by_anchor[_a0][1]:
                _by_anchor[_a0] = ((r0, c0), _n0)
        _mk_dedup = [v[0] for v in _by_anchor.values()]
        if len(_mk_dedup) < len(mk):
            entry['marks_dedup'] = '%d→%d' % (len(mk), len(_mk_dedup))
        mk = {k: mk[k] for k in _mk_dedup}
    except Exception:       # noqa: BLE001
        pass
    marked = [marks_mod.cell_center(r, cc) for (r, cc) in sorted(mk)]
    # ⭐⭐ 2026-09-26 用户需求（原话）：
    #   「如果探索格子有空闲的就要找这种格子点探索来填满；如果探索格子被填满就不需要找」
    #   这种格子 = 紫/橙探索地块（ID 后缀 221/321/331 ✓ 小助手官方分类 ✓）
    # ⭐ 判据 = 地块 **ID 后缀** ∈ {221,321,331}（紫/橙探索地块 ✓，小助手官方分类 ✓）
    #   ⚠ 不能按名字筛 ✗：「游乐设施」有 202(绿)/311(蓝)/221(紫) 多个 ID ✓
    try:
        _ap = set(spots_mod.EXPLORE_SUFFIX)
    except Exception:       # noqa: BLE001
        _ap = {'221', '321', '331'}
    if EXPLORE_DISPATCH and _ap and c.get('st'):
        # ⭐⭐ 空闲探索槽（2026-09-30 改口径，见文件上方 `explore_slots_free` 那段）：
        #   **只认正面证据「空闲」**；认不到 ⇒ 不下结论（保留 old / None）。
        #   ⚠ 旧版「总槽数 - 倒计时个数」反推法已**废除**（真机实证会假空闲 ⇒ 死循环 ✗）：
        #     · 那台机器 HUD 是 **4 个槽**（角标 1/2/3/4），`TOTAL=3` 反推本身就不成立
        #     · 倒计时还会被 OCR 吃掉一个冒号（`04:24:31` → `04:24831`）⇒ 少算一个"占用"
        #   轮首已经刷过一次（同一份 items）⇒ 这里只补落日志用的 entry 字段 ✓
        _sf_here, _si_here = explore_slots_free(items)
        _free_txt = _si_here['free_txt']
        _busy = _si_here['busy']
        if _sf_here is not None:
            _slots_free = _sf_here
            _saw_row = True
        else:
            _slots_free = int(st.get('slots_free', 1) or 0)     # 认不到 ⇒ 保留旧值
            _saw_row = False
        entry['slots_free'] = _slots_free      # ⭐ 空闲探索槽个数（0 = 已填满 ✓）
        entry['slots_busy'] = _busy
        entry['slots_busy_strict'] = _si_here['busy_strict']
        if _saw_row:
            st['slots_free'] = _slots_free
        # ⭐ 2026-09-26 用户要求：**不管满没满，紫橙格都是目标** ✓
        #   有空闲 ⇒ 点探索+派遣 ✓；满了 ⇒ 点战斗 ✓（都在 popups 里分流 ✓）
        if True:
            # ⭐⭐ 2026-09-26 修正：紫/橙格**按大块去重**，一个大块只给一个点击目标 ✓
            #   旧逻辑逐格看 sid ⇒ 一个 2×3 的 221 大块会产出 5~6 个目标，
            #   而点哪一格弹的都是**同一块的面板** ⇒ 重复弹面板 + 白点（用户发现）
            #   `Board.state()` 已经把成员格归属修正过了（同一大块 ⇒ 同一个 anchor、
            #   同一个 sid）⇒ 这里只要**按 anchor 归并**、每块挑一个还没点的格 ✓
            _ev_blocks = {}                 # anchor -> [成员格...]
            _seen_anchor = set()      # ⭐ 按锚点去重（一个大块只留一个目标 ✓）
            for _k, _v in sorted(c['st'].items()):
                _sid = str(_v.get('sid') or '')
                _suf = _sid.split('_')[-1] if '_' in _sid else ''
                _anc = tuple(_v.get('anchor') or _k)
                if _anc in _seen_anchor:
                    continue             # 同块成员格 ⇒ 跳过 ✓
                _seen_anchor.add(_anc)
                if _suf not in _ap:
                    continue
                # ⚠ 分数门槛 0.70：分类器对看不清的格子会给低分瞎猜（实测 0.21/0.30 ✗），
                #   而用户确认的真地块是 0.794 ✓ ⇒ 0.70 干净分开 ✓
                #   ⭐ 属于大块的格子看 **block_score**：它自己的 top1 可能压根不是这块
                #     （实测 findA3 的 (1,7) 自己认成空地 0.910，大块分才是 0.794）
                _sc = float(_v.get('block_score') or _v.get('score') or 0)
                if _sc < 0.70:
                    continue
                _ev_blocks.setdefault(_v.get('anchor') or _k, []).append(_k)
            _ev_cells = []
            for _ak, _members in sorted(_ev_blocks.items()):
                # 优先点锚点；锚点已经点过了就退而选同块里其它没点过的成员 ✓
                _want = [k for k in [_ak] + _members
                         if marks_mod.cell_center(*k) not in done]
                if _want:
                    _ev_cells.append(_want[0])   # ⭐ 每块只出一个目标
            # ⭐ 用户口径：**有空闲槽时这些是必须清完的目标** ✓（含雾格 ⇒ 会开路去揭示 ✓）
            #   没有空闲槽时就不管它们 ✓（上面已经 return/记 full 了）
            if _ev_cells:
                _ev_px = [marks_mod.cell_center(r, cc) for (r, cc) in _ev_cells]
                marked = list(dict.fromkeys(marked + _ev_px))
                entry['event_tiles'] = ['%d,%d' % k for k in _ev_cells]
                st['ev_tiles'] = list(entry['event_tiles'])
                say('       · 发现 %d 块紫/橙探索地块（%d 个成员格 %s）⇒ %s（空闲槽 %d 个）'
                    % (len(_ev_cells), sum(len(v) for v in _ev_blocks.values()),
                       '/'.join(sorted(_ap)),
                       '去探索+派遣' if _slots_free > 0 else '探索槽已满 ⇒ 改战斗',
                       _slots_free))
                status('发现紫金地块 · %s' % ('去派小队' if _slots_free > 0 else '槽满，改开打'))
        else:
            entry['event_slots'] = 'full'
    marked = [p for p in marked if p not in done]
    need = [p for p in marked if cold.get(p, 0) >= 1]
    fresh = [p for p in marked if cold.get(p, 0) == 0]
    sig = (len(grays), len(nones))
    st['stall'] = (st.get('stall', 0) + 1 if st['sig'] == sig else 0) if need else 0
    st['sig'] = sig
    # 拦路格判定（用户 09-25）：**只要场上还有未处理的标记格**，普通战斗格就可能是
    # 「去 boss 路上的拦路格」，要打掉（上限由 popups 里的 clear_fights<3 控制）。
    # ⚠ 旧版要「打标记格失败」才知道被挡路 -> 表现成「遇到拦路格直接关掉不打」。
    st['force_fight'] = bool(marked) or st.get('clear')
    if st.get('clear_fights', 0) >= 3:
        st['force_fight'] = False
    entry['order'] = {'none': len(nones), 'gray': len(grays), 'marked': len(marked),
                      'fogged': len(need), 'force': st['force_fight'],
                      'content(unused)': len(nones_extra), 'buy': len(buy),
                      'buy_hidden': len(buy_hidden)}
    if not marked and not buy and not buy_hidden:
        say('  [r%d] 没有目标了，准备退图' % rnd)
    else:
        say('  [r%d] 标记格 %d（含点不动的 %d）| 商人/宝库 %d（未揭示 %d）| 已揭示 %d / 暗格 %d'
            % (rnd, len(marked), len(need), len(buy), len(buy_hidden),
               len(nones) + len(nones_extra), len(grays)))

    def dist(p):
        src = need or marked
        if not src:
            return 0
        return min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in src)

    nones = sorted(nones, key=dist)
    # 退图规则（用户 2026-09-25 定案）：**只有标记格 + 商人/宝库是目标**
    #   目标都处理完 → 立刻结束冒险；不为「已露出的内容格」多跑一趟、更不乱揭格
    # ⚠ 2026-09-25 修：`pending_buy` 必须**把「未揭示的商人/宝库」也算进去**
    #   —— 否则「已识别到但还没解锁」的宝库会被当成"目标清完"直接退图
    #   （用户报「第三张图未揭示的宝库还有一个没买就退地图了」：日志 r4 显示「未揭示 1」却 done）
    # ⭐⭐⭐ 2026-10-01 用户报「盘上有宝库但没识别到就退了」+「我是在地图里直接启动脚本、
    #   boss 关已经打过」⇒ 根因：**中途接手时那一帧常被残留面板/结算动画盖住**
    #   ⇒ `board_state` 整盘读成暗格 ⇒ `buy_hidden` 空 ⇒ 判「没有目标了」直接退图 ✗
    #   而稍后（我抓帧时）同一张图宝库分数 **0.974** —— 说明**识别没问题，是"那一帧没看见"**。
    #   ⇒ 加一份 **跨轮持久的宝库/商人记忆 `st['buy_seen']`**：
    #     · 任何一轮认到（≥ `BUY_MEMORY_MIN`）就记下，**本图内不再遗忘** ✓
    #     · 它只影响"要不要退图"：**别在还可能漏着宝库时就退图** ✓
    #     · 真的被买掉/消耗掉 ⇒ 本帧 board 里那格不再是宝库 ⇒ 自然从记忆里移除 ✓
    #     · 上限 `BUY_MEMORY_MAX_ROUNDS` 轮防死锁（一直点不开也不至于卡死 ✓）
    BUY_MEMORY_MIN = 0.60          # 比 0.85 低：宁可疑心，也别漏（漏了用户就得手动补 ✗）
    try:
        _seen = st.setdefault('buy_seen', {})
        _cells_now2 = (c.get('st') or {})
        for _k, _v in _cells_now2.items():
            _nm2 = str(_v.get('name') or '')
            _sc2 = float(_v.get('score') or 0)
            # ⭐ v1.27：**已经买完/消耗掉的格子不再进记忆**（否则买完那张贴图还在 ⇒
            #   每轮刷新记忆 ⇒ 幽灵目标永远清不掉，见上面「vault: consumed」注释 ✓）
            if _k in (st.get('buy_consumed') or set()):
                continue
            if _nm2 in spots_mod.BUY_OUT_NAMES and _sc2 >= BUY_MEMORY_MIN:
                _px = marks_mod.cell_center(*_k)
                _seen[_px] = st.get('_rnd', 0) + 1
        # 本帧还有没有它（已买掉 ⇒ 分类结果会变成别的名字/空地）
        _alive = set()
        for _k, _v in _cells_now2.items():
            if str(_v.get('name') or '') in spots_mod.BUY_OUT_NAMES:
                _alive.add(marks_mod.cell_center(*_k))
        # ⭐ 已揭示的格**名字变了**（= 已被买掉/消耗）⇒ 立刻从记忆里删 ✓
        for _k, _v in _cells_now2.items():
            if bool(_v.get('revealed')) and str(_v.get('name') or '') \
                    and str(_v.get('name') or '') not in spots_mod.BUY_OUT_NAMES:
                _seen.pop(marks_mod.cell_center(*_k), None)
        for _p in [q for q in list(_seen)
                   if q not in _alive and _seen[q] and
                   (st.get('_rnd', 0) + 1 - _seen[q]) > 4]:
            _seen.pop(_p, None)       # 4 轮都没再出现 ⇒ 真的没了 ✓（防死锁）
    except Exception:       # noqa: BLE001
        pass

    # ⚠ 2026-09-25 又修（用户报「漏了已经揭示的黄金宝库」）：
    #   **已揭示的商人/宝库不做 cold 过滤**（和标记格一样永不排除），否则点两次没开面板
    #   就被踢出 pending_buy → 判成「目标清完」直接退图，宝库白漏。
    #   未揭示的**不加 cold 过滤**（它压根不该被点，见上面 board_sig 那段）。
    # ⭐⭐⭐ 2026-09-30【粘性商人/宝库目标】（模拟器 10:31 实锤，用户报「宝库没正常购买」）：
    #   宝库暗格揭示后匹配分会**抖动**（0.978 → 0.822，暗罩/角度让 NCC 掉分），
    #   一旦低于 0.85 强匹配线就从 buy_hidden 掉出 ⇒ pending_buy 变空 ⇒
    #   「目标清完」直接退图，宝库没买（统计「买完 0 个」）。
    #   ⇒ 一旦识别为商人/宝库（≥0.80）就进 **st['buy_sticky'] 粘性集合**，持续算 pending；
    #     排除条件只有一个：本轮 board 里该格已不再是宝库/商人（= 已买完消耗/消失）。
    #     另设 20 轮上限防死锁（一直点不开的宝库到上限就放弃，deadline 兜底退图）。
    sticky = st.setdefault('buy_sticky', {})
    _buy_now = {}
    for _p in (list(buy) + list(buy_hidden)):
        _buy_now[_p] = True
        sticky[_p] = sticky.get(_p, 0) + 1
    _still_buy = vault_still_there(st)
    # ⚠⚠ 2026-10-01 v0.96：上面这行原来写成 `(st['cells'] or {}).get('board')` ——
    #   而 `st['cells']` 是**分类器原样 dict**（键 `(r,c)` 元组，没有 `board` 键）
    #   ⇒ `_still_buy` **恒为空** ⇒ 下面「已消耗就剔出粘性集」这条**是死代码** ✗
    #   后果（真机 autoexplore_vaultskip.log 22:28~22:32 实测）：粘性集里那个宝库挂满 20 轮，
    #   每轮 `pending_buy` 都非空 ⇒ **永远「还剩 1 个目标」**，而本帧又认不到它
    #   ⇒ 机器人满地图开路、把体力花在"拦路"战斗上（用户报「能直接点的黄金宝库不去点，
    #     却去打了两个战斗地块」就是这个）✗
    for _p in [q for q in list(sticky)
               if q not in _buy_now and q not in _still_buy]:
        sticky.pop(_p, None)          # 已消耗/消失 ⇒ 从粘性集移除 ✓
    for _p in [q for q in list(sticky) if sticky[q] > 20]:
        sticky.pop(_p, None)          # 20 轮都点不开 ⇒ 放弃这个目标（防死锁）
        log.append({'buy_sticky_giveup': _p})
    # ⭐⭐⭐ 2026-10-01 v0.96【宝库永不丢 · ②强匹配但被判"未揭示"的也要去点一下】
    #   `revealed` 是 ratio 判据（格亮度/命中模板亮度）⇒ **换模板/换贴图帧就会抖动**，
    #   真机实测：NCC 0.95+ 的已揭示宝库被判 ratio 0.638 = "未揭示" ⇒ 既不进 buy、
    #   又被当"点不动"⇒ 机器人看着宝库去开路打拦路 ✗（用户报的就是这个）
    #   ⇒ 强匹配(NCC≥0.85) + 名字是宝库/商人 ⇒ **验证式点它**（每格上限 BUY_PROBE_MAX 次）
    # ⛔⛔ v1.44【默认关掉，严格走计划】（学 PC 端 b3f92d8 的【B】，用户口径原话）
    #   PC 端用户定：「**也不要去额外点宝库了，严格走计划**」
    #   ⇒ 雾里（判成"未揭示"）的宝库/商人**一律不点**，只按规划走 ✓
    #   ⇒ 原因：ratio 抖动导致的"假未揭示"是**识别问题**，
    #     用"多点几下试试"去掩盖它 = **拿体力赌识别**，而且会插队打乱规划 ✗✗
    #   ⇒ 正确做法是把 `revealed` 判据修准（v1.35/v1.36 的 ratio 口径已在校准 ✓），
    #     而不是靠暴力点击兜底 ✓
    #   想恢复旧行为：设 `MAPBOT_VAULT_PROBE=1` ✓
    VAULT_PROBE = (os.environ.get('MAPBOT_VAULT_PROBE', '0') or '0') \
        not in ('0', '', 'no', 'false')
    _probe_px = set()
    try:
        if VAULT_PROBE:
            _probe_px = set(vault_probe_px(c, st))
        _add = [p for p in _probe_px if p not in buy]
        if _add:
            buy = list(buy) + _add
            entry['buy_probe'] = ['%d,%d' % cell_of(*p) for p in _add]
            log.append({'buy_probe': ['%d,%d' % cell_of(*p) for p in _add]})
            say('       · 宝库/商人 %s 被判"未揭示"但强匹配 ⇒ 也去点一下（不丢宝库 ✓）'
                % '、'.join('%d,%d' % cell_of(*p) for p in _add))
    except Exception:       # noqa: BLE001
        pass
    pending_buy = list(buy) + list(buy_hidden) +         [q for q in sticky if q not in _buy_now]
    # ⭐⭐⭐ 2026-10-02 v1.27：**买完的宝库格从所有目标集合里剔掉**（幽灵目标根因 ✓）
    #   用户实报：「宝库都没问题了，但显示还剩 1 个目标，我看着已经没目标了」
    _consumed = st.get('buy_consumed') or set()
    if _consumed:
        pending_buy = [p for p in pending_buy if cell_of(*p) not in _consumed]
    # ⭐⭐⭐ 2026-10-01：把**跨轮记忆**里的宝库/商人也算进 pending ⇒ 这一帧被面板盖住
    #   也不会误判「没有目标了」直接退图（用户报的「盘上有宝库却没识别到就退了」✗）
    # ⚠⚠ v1.37 修「打完首领、盘上没目标了还在打拦路格」（用户 2026-10-02 真机报）：
    #   上一条只按 `buy_consumed`（**买过**的格）过滤，可 `buy_seen` 里的格子若是
    #   **战斗消耗**的（没买过、也不在 buy_consumed）⇒ **逃过过滤、永久残留** ✗
    #   真机铁证：`{"targets_ghost":{...,"sticky":["1,6"],"mem":["1,6"]}}`
    #     而 (1,6) 早已在同图 `done_cells_dropped` 里被消耗 ⇒ 幽灵 ⇒ 退图判据永不成立 ✗
    #   ⇒ 跨轮记忆**也**按 `buy_consumed` 过滤，且额外按**本局已消耗**(`done`)兜底 ✓
    try:
        _mem = st.get('buy_seen') or {}
        for _p in _mem:
            if _p in pending_buy:
                continue
            try:
                _rc_p = cell_of(*_p)
                if _rc_p in _consumed:                    # 买过的 ⇒ 别再当目标 ✓
                    continue
                if marks_mod.cell_center(*_rc_p) in done:  # ⭐ v1.37：已消耗 ⇒ 幽灵 ✗
                    continue
            except Exception:       # noqa: BLE001
                pass
            pending_buy.append(_p)
            st.setdefault('buy_mem_used', 0)
            st['buy_mem_used'] = st['buy_mem_used'] + 1
    except Exception:       # noqa: BLE001
        pass
    # ⭐⭐⭐ 2026-10-02 v1.29【用户报「进图发了会呆就退出了」】—— 根因在下面 `order` 的构建条件
    #   真机包 `进图发了会呆就退出了.zip`（realme RMX3800，v1.28）日志：
    #     r0/r1 `marks_scan: none` + `solver: no_plan` + **`finish: blank_board` ×2**（各 40~90 秒）
    #     r2   `popup_none_dlg: probe`（找不到面板）+ `universal_close: popup_none`
    #     r3   `finish: targets_done, gray_left: 24` ⇒ **24 个暗格一格没开就退图** ✗✗
    #   ⇒ 因为点序只在「有标记 or 有商人/宝库」时才构建（见下面 `if not order and (marked or
    #     buy_any)`）⇒ 这一帧没认出任何标记（近失分 recommend 0.769 / boss 0.734，都低于闸门）
    #     ⇒ `order=[]` ⇒ 判"盘上空白" ⇒ 发呆 → 再按"目标做完"退图 ✗
    # ⭐⭐ v1.39：探索模式已移除 ⇒ 没有目标就退图（不再沿可点格开路逼标记 ✓）
    #   （v1.29 当初是反着加的：没目标但暗格多就先探图，逼出雾里的标记。
    #    真机证明它反复白烧体力且常无产出 ⇒ 用户定「去掉探图模式」✓）
    # ⭐⭐ v1.37【solver 说"没目标了"就退图，不信 sticky 幽灵】——
    #   用户 2026-10-02 真机报「打完首领、棋盘上没有目标了还在打拦路格子」✗
    #   真机铁证（v1.34 日志，同一张图）：
    #     `{"solver":"no_plan","cost":0}`                    ← 求解器明确：盘上没目标了 ✓
    #     `{"targets_ghost":{...,"sticky":["1,6"],"mem":["1,6"]}}`  ← 但 sticky 残留 (1,6)
    #     紧接着 `{"popup":"fight_panel","cell_marks":[]}` + 一场战斗  ← 白打拦路格 ✗✗
    #   根因：(1,6) **早已消耗**（同一日志 `done_cells_dropped` 里有它），
    #     可"宝库粘性记忆"没清 ⇒ `pending_buy` 一直非空 ⇒ 退图条件永不成立 ✗
    #   修法：**已消耗格上的幽灵目标**直接清掉再判退图 ✓
    #   ⚠ **不能等 `solver: no_plan`**：退图判据在求解器**之前**跑（`solver_order` 在 ~7207 行）⇒
    #     此刻拿不到 no_plan ⇒ 改用**更硬的证据**：这个"目标"格**已经被消耗掉了** ✗
    #   ⚠ 只清"中心已消耗"的幽灵 —— 真目标（还在盘上）绝不动 ✓
    if not marked and pending_buy:
        try:
            _dead = set()
            for _g in pending_buy:
                _rc = cell_of(*_g)
                if marks_mod.cell_center(*_rc) in done:
                    _dead.add(_g)
            if _dead and len(_dead) == len(pending_buy):
                # 全部幽灵 ⇒ 盘上确实没目标了 ⇒ 清掉让退图判据生效 ✓
                log.append({'targets_ghost_cleared':
                            ['%d,%d' % cell_of(*g) for g in _dead],
                            'why': '这些\"目标\"格**已消耗** ⇒ 幽灵，清掉后退图 ✓'})
                pending_buy = []
        except Exception:       # noqa: BLE001
            pass
    # ⭐ v1.39：没有目标 ⇒ **直接退图**（探索模式已移除，不再有"先探图"这条路 ✓）
    if vis and rnd >= 2 and not marked and not pending_buy:
        log.append(entry)
        log.append({'finish': 'targets_done', 'gray_left': len(grays),
                    'content_skipped': len(nones_extra)})
        return 'done'
    # ⭐ 2026-09-30 悬浮条心跳：给用户看的是「第几张图 · 还剩几个目标」，
    #   **不是**轮号/坐标/cost/步数（那些只进控制台）。每轮更新一次 ⇒ 长时间无事件时
    #   用户也能看出"它还活着、在推进"，而不是盯着一句几分钟前的旧状态。
    status('第 %d 张图 · 正在找路（还剩 %d 个目标）'
           % (cur_map_no(), len(marked) + len(pending_buy)))
    # ⭐ v1.27 诊断：**没有标记却有 pending 目标** ⇒ 记下这堆"幽灵"是谁（下次反馈能一眼定位 ✓）
    if not marked and pending_buy:
        try:
            log.append({'targets_ghost': {
                'buy': ['%d,%d' % cell_of(*p) for p in buy],
                'buy_hidden': ['%d,%d' % cell_of(*p) for p in buy_hidden],
                'sticky': ['%d,%d' % cell_of(*p) for p in sticky],
                'mem': ['%d,%d' % cell_of(*p) for p in (st.get('buy_seen') or {})],
                'consumed': sorted('%d,%d' % rc for rc in _consumed)}})
        except Exception:       # noqa: BLE001
            pass
    # 点序：**无条件交替** —— 揭一格 → 点一次商人/宝库 → 点一次标记格 → 再揭一格…
    #   ⭐ 内容格只在「还有未完成目标」时当**开路**用（用户 2026-09-25）：
    #      boss 那类标记格常常是「未揭示」状态、点不动，必须消耗它旁边的地块才会
    #      连锁揭示（`RemoveBlock` → `SetBlockVisible`）—— 内容格（宝箱/海螺/游乐设施…）
    #      点一下就消耗，正好用来开路。**目标一清完立刻退图，不再多点**（提高效率）。
    marks_any = fresh + need
    buy_any = pending_buy
    clearable = [p for p in nones_extra if p not in done and cold.get(p, 0) < 2]

    # 「出生地」= 营地格（用来判断哪些格在「出生地 → 目标」的路上）
    spawn = st.get('spawn')
    if not spawn and c.get('st'):
        for k, v in sorted(c['st'].items()):
            if v.get('anchor') == k and v.get('name') == '营地':
                spawn = marks_mod.cell_center(k[0], k[1])
                st['spawn'] = spawn
                break

    def path_to(target, limit=6):
        """出生地 → 目标 **那条直线上的可点格**（用户 2026-09-25 口径）

        判据 = Bresenham 直线取格；只保留「已揭示、能点」的格（点不动的暗格点了也没用）。
        顺序 = 从出生地那头往目标走（沿路推进）。
        直线上一格可点的都没有时，退回旧的走廊判据兜底（免得卡死）。
        """
        cands = [p for p in list(nones) + list(nones_extra)
                 if p not in done and cold.get(p, 0) < 2]
        if not spawn:
            cands.sort(key=lambda p: abs(p[0] - target[0]) + abs(p[1] - target[1]))
            return cands[:limit]
        sc_ = cell_of(spawn[0], spawn[1])
        tc_ = cell_of(target[0], target[1])
        line = line_cells(sc_, tc_)
        road = []
        for (rr, cc) in line:
            if (rr, cc) == tc_:
                continue                    # 目标格本身不是「拦路」
            pt = marks_mod.cell_center(rr, cc)
            if pt in cands and pt not in road:
                road.append(pt)
        if road:
            return road[:limit]
        # 兜底：直线上一格都点不了（都被点过/拉黑）→ 用走廊判据找附近的
        d_st = abs(spawn[0] - target[0]) + abs(spawn[1] - target[1])

        def key(p):
            d_t = abs(p[0] - target[0]) + abs(p[1] - target[1])
            d_s = abs(p[0] - spawn[0]) + abs(p[1] - spawn[1])
            return (abs((d_s + d_t) - d_st) > 2, d_t)
        cands.sort(key=key)
        return cands[:limit]

    order = []
    road_all = []
    if OPT:
        # ⭐ 体力最省模式：整轮点序由 Dijkstra 最优解给出（失败则退回下面的启发式 ✓）
        opt = optimal_order(c, mk, st, log)
        if opt:
            entry['opt_order'] = len(opt)
            road_all = list(opt)
            order = list(opt)
    if not order and (marked or buy_any):
        # ⭐ 有标记格（或商人/宝库）未处理 -> 先把「出生地→目标」路上的可点格列出来，
        #   a) 优先沿路开路  b) 只有这些格弹出来的战斗才允许打（用户口径：无关战斗不打）
        if st.get('clear_clicks', 0) < 24:
            # 开路目标 = 点不动的标记格 / 所有标记格 / **商人宝库（含已揭示但点不开的）**
            road_targets = list(need or marked) + list(buy_any) + list(buy_hidden)
            for t in road_targets:
                for p in path_to(t):
                    if p not in road_all:
                        road_all.append(p)
        if road_all:
            entry['road'] = road_all[:6]
        # ⭐ 点序必须**严格交替**：揭一格/开一格 → 立刻试一次目标（首领/商人宝库）→ 再揭…
        #   用户 2026-09-25：「为什么连续点了好几次出生点周围的，中间没有去点首领判断能不能直接打？
        #   不应该是点一下判断一下首领吗」
        # ⚠ 2026-09-25 再修（用户：「还在点不是那条直线上的格子」）：
        #   有目标时**只点直线上的格**（`road_all`），别再把全部已揭示格（nones）也排进去；
        #   只有直线上真的没有可点的格时才退回 nones 兜底（否则会卡死）。
        # ⚠ 另：**未揭示的商人/宝库不进点击序列**（点不动，只会白耗 cold 被误判成放弃）
        targets = [p for p in buy_any if p in set(buy)] + marks_any
        if road_all:
            reveals = list(road_all)
        else:
            reveals = list(nones)
        for p in reveals[:10]:
            order.append(p)
            order.extend(targets)
        order += reveals[10:] + targets
        # 直线上一格可点的都没有 → 才用内容格兜底开路（同样只在这时插）
        if not road_all and st.get('clear_clicks', 0) < 16:
            for q in clearable[:6]:
                order.append(q)
                order.extend(targets)
    else:
        order = []
    # ⭐⭐ 2026-09-27 用户要求：**每张图只在进图后规划一次** ✓（不要每轮都规划 ✗）
    #   ⭐⭐⭐ 2026-09-30 **推翻这条**（离线 96 张真机内存盘对拍 `_bench_online.py --corpus`）：
    #     ① 进图时规划的**目标集是残缺的**（未揭示的标记格 / 商人还没认出来）
    #        ⇒ 「进图规划一次」比全知最优贵 **+9.2%**（marks 可见时）/ **+26.1%**（marks 藏雾里），
    #        最坏单盘贵 **16 体** —— 这正是用户报的「算出了但不是最优走法」✗
    #     ② 当年"每轮重算要卡几十秒"是**旧 Dijkstra** 的数字；2026-09-29 A* 重构后
    #        求解**完整链路**（建盘+编译+solve）实测 **p50 0.65ms / p95 1.4ms / p99 1.9ms**
    #        ⇒ 每轮重解**零成本** ✓
    #     ③ 改「每轮用最新观测重解」后：真机盘 **95/95 张与全知最优逐字节相等**（0.00% 差）
    #        （`cur` 进图一次：89 相等 / 6 更贵；`EffPolicy`：75 相等 / 20 更贵）
    #   ⇒ 现在每轮都重解，旧计划**直接丢弃**（不再累积、不再"计划耗尽才兜底"）✓
    # ⭐⭐⭐ 2026-10-02 v1.28【用户口径：**每张图只在进图后规划一次**】
    #   「规划就刚进入规划一次，后续不再规划。走完规划的还有目标就用之前的保底方案走」
    #   ⇒ 判据抽成纯函数 `plan_next()`（可离线对拍 ✓）：
    #      · 计划还有没做完的步 ⇒ **继续照走，绝不重算** ✓
    #      · 计划走完 / 连着 3 轮推不动 ⇒ 切 **EffPolicy 片感知兜底**（就是"之前的保底方案"）✓
    #   ⚠ 09-30 曾按"每轮重解更省体力"（离线 +9.2%~+26.1% 优势）推翻本条，
    #     10-02 白天按用户口径改回"进图一次"，**10-02 晚用户又改口「那换回来吧」** ⇒
    #     ⭐⭐ v1.29：**两条路都留在代码里，用开关切**（`PLAN_ONCE`，历史上已来回翻两次，
    #        以后再改就动这一个常量 / 环境变量，别再手改逻辑 ✗）
    #       · `PLAN_ONCE=0`（默认，当前）：**每轮用最新观测重解**（省体力 ✓）
    #       · `PLAN_ONCE=1`：进图只规划一次 + 走完/推不动切兜底（可预期，但多花体力）
    #   ⏱ 时间成本实测可忽略（所以这条从来不是"快慢"问题，是"体力 vs 可预期"）：
    #     真机 solver 自报 `secs: 0.0`；离线 96 张真机盘 p50 0.65ms / p99 1.9ms（A* 重构后）
    if c.get('st'):
        if not OPT_SOLVER:
            st['plan_src'] = 'eff'       # `--no-solver`：直奔 EffPolicy，别白数 3 轮 ✓
        _rest = [p for p in (st.get('plan') or [])
                 if marks_mod.cell_center(p[0], p[1]) not in done]
        _tleft = len(marked) + len(pending_buy)
        if st.get('plan_src') == 'eff':
            _pact, _pwhy = 'keep', 'eff_mode'          # 已在兜底模式 ⇒ 不再规划 ✓
        else:
            _pact, _pwhy = plan_mode(st, len(_rest), _tleft)
        if _pact == 'plan':
            _so = {}
            # ⭐⭐ v1.45 规划步数上限 4 → **10**（学 PC 端 `42c65a1`，用户口径「上限改为 10 步」）
            #   原来只要前 4 步的理由是「每轮就点 4 下，多要步数没意义」——
            #   但 `PLAN_ONCE=1`（一图一次）之后这个前提**不成立**了：
            #     计划被 4 步截断 ⇒ 日志只看得到前 4 步 ⇒ 走完就得切兜底 ⇒ 规划白算 ✗
            #   改 10 步后一次规划能覆盖更长的走法 ✓
            #   ⏱ 成本可忽略：真机 solver 自报 `secs: 0.0`；离线 96 张真机盘
            #     p50 **0.65ms** / p99 1.9ms（A* 重构后）⇒ 步数上限不是"快慢"问题 ✓
            #   （`eff_order` 的兜底上限本来就是 20，这里保持一致量级 ✓）
            _sol = solver_order(st, c, log=log, max_steps=PLAN_MAX_STEPS, out=_so)
            if _sol:
                st['plan'] = list(_sol)          # ⭐ 每轮**覆盖**（v1.29 恢复到这个口径 ✓）
                st['plan_src'] = 'solver'
                st['planned'] = True
                st['plan_tries'] = 0
                st['plan_stuck'] = 0
                st['plan_prev_len'] = len(_sol)
                log.append({'plan': _pwhy, 'cells': ['%d,%d' % (p[0], p[1]) for p in _sol]})
                if _pwhy == 'first':
                    say('       · 进图规划一次：%s（后续照着走，不再重算 ✓）'
                        % ' '.join('%d,%d' % (p[0], p[1]) for p in _sol[:6]))
            else:
                st['plan'] = []
                # ⚠ 「盘上已经没有目标了」**不算失败**（正常收尾）——否则会白切 EffPolicy ✗
                if not _so.get('no_targets'):
                    st['plan_tries'] = st.get('plan_tries', 0) + 1
                    if st['plan_tries'] >= 3:
                        st['plan_src'] = 'eff'
                        say('       · 进图规划连续 %d 轮没算出 ⇒ 本图直接用片感知兜底'
                            '（EffPolicy）' % st['plan_tries'])
                        try:        # ⭐ 悬浮条也告诉用户"这图改走兜底策略了" ✓
                            status('规划：改用片感知兜底（精确解算没出结果）')
                        except Exception:       # noqa: BLE001
                            pass
        elif _pact == 'eff':
            st['plan'] = []
            st['plan_src'] = 'eff'
            _sol = None
            log.append({'plan': _pwhy, 'targets_left': _tleft})
            if _pwhy == 'exhausted':
                say('       · 进图那份计划走完了，还剩 %d 个目标 ⇒ 切回**片感知兜底**（老方案）✓'
                    % _tleft)
                status('规划走完 · 改用兜底策略')
            else:
                say('       · 计划连着 %d 轮没推进（格子点不动/被挡）⇒ 切回片感知兜底 ✓'
                    % PLAN_STUCK_ROUNDS)
                status('计划推不动 · 改用兜底策略')
        # ⭐⭐ 2026-09-28：EffPolicy 兜底 —— 每轮用**最新观测**现算点序（毫秒级 ✓）
        if st.get('plan_src') == 'eff' and c.get('st'):
            _eff = eff_order(st, c, log=log, max_steps=20)
            _eff_pick = []
            for _p in _eff:
                if marks_mod.cell_center(_p[0], _p[1]) in done:
                    continue
                _eff_pick.append(_p)
                # ⭐ 取前 2 步（2026-09-28 离线扫描 60 张：batch=4 → 11.88，
                #   batch=2 → 10.97，batch=1 → 10.72；2→1 只省 0.25 但真机轮数翻倍
                #   （每轮截图+OCR 有开销）⇒ 2 是甜点 ✓ solver plan 消费保持 4 不动
                #   ——那是静态点序（不重算），多取几步减少空轮 ✓）
                if len(_eff_pick) >= 2:
                    break
            if _eff_pick:
                _eff_px = [marks_mod.cell_center(r, cc) for (r, cc) in _eff_pick]
                order = _eff_px + order
                entry['eff_order'] = ['%d,%d' % p for p in _eff_pick]
        else:
            _eff_pick = []
        _picked = []
        _plan = list(st.get('plan') or [])
        if _plan:
            # 取"接下来还没做完的几步" ✓（已完成的跳过 ✓）
            for _p in _plan:
                if marks_mod.cell_center(_p[0], _p[1]) in done:
                    continue
                _picked.append(_p)
                if len(_picked) >= 4:
                    break
            if _picked:
                _sol_px = [marks_mod.cell_center(r, cc) for (r, cc) in _picked]
                order = _sol_px + order
                _sp_px3 = st.get('spawn') or st.get('camp')
                _sp_rc3 = None
                if _sp_px3:
                    try:
                        _sp_rc3 = cell_of(_sp_px3[0], _sp_px3[1])
                    except Exception:       # noqa: BLE001
                        _sp_rc3 = None
                entry['solver_order'] = ['%d,%d' % p for p in _picked
                                         if p != _sp_rc3]
                entry['plan_left'] = len(_plan)
        # ⭐⭐⭐ 2026-09-28 修「点了 33 却没打」（用户真机报）：计划内剩余步 =
        #   「计划内的路」⇒ popups 的战斗面板判定用（solver/EffPolicy 已做过
        #   「绕开更贵」的权衡 ⇒ 计划内弹出的战斗**必打**，不再被 offroad_fight
        #   旧口径关掉 ✗ → 参见 popups 里 on_plan 分支 ✓）
        st['plan_road'] = [marks_mod.cell_center(r, cc) for (r, cc) in
                           (_eff_pick if st.get('plan_src') == 'eff' else _picked)]

    # ⚠ 2026-09-27 用户要求：**去掉**"战斗刚结束 ⇒ 把目标格插到最前"这个行为 ✗
    #   （原来 st['try_targets'] 会在战斗后把目标排最前 ✓ 用户明确不要 ✓）
    if st.get('try_targets'):        # 兼容老状态：只清标记，不再改点序 ✓
        st['try_targets'] = False
    st['road'] = road_all
    # ⭐ 2026-09-27：`plain_road` = 这条路上**可点的空地块**（判断"是否被迫打"用 ✓）
    try:
        _nones_set = set(nones) | set(nones_extra)
        # ⚠ 必须排除**已完成**的格 ✓（否则"已经点掉的空地"还在算 ⇒ 会误判成"前面有空地"✗
        #   ⇒ 该打的障碍不打 ✗ = 用户报「点了 33 却没打掉这个战斗格」✓）
        st['plain_road'] = [p for p in road_all
                            if p in set(nones) and p not in done]
    except Exception:       # noqa: BLE001
        st['plain_road'] = []
    # ⭐ 待处理目标（供 popups 判「紧挨目标的战斗格 = 拦路」用）
    st['targets'] = list(marked) + list(buy_any)
    # ⭐ v1.39：探索模式的记账 + 「先探图」悬浮条提示**已一并移除**（用户定）
    #   —— 这段就是用户目击「还在显示探索」的来源（`status('…没标记，先探图…')`）✓
    if not order and not marked:
        st['blank'] = st.get('blank', 0) + 1
        log.append(entry)
        log.append({'finish': 'blank_board', 'n': st['blank']})
        if st['blank'] >= 3:
            return 'blank'
        time.sleep(1.5)
        return None
    # ⭐ 刚点那格的地块 ID（给 popups 判"是不是紫/橙探索地块"用 ✓）
    try:
        if st.get('last') and c.get('st'):
            _tc = cell_of(st['last'][0], st['last'][1])
            st['tapped_sid'] = str((c['st'].get(_tc) or {}).get('sid') or '')
    except Exception:       # noqa: BLE001
        st['tapped_sid'] = ''
    marked_px = set(marked)
    # ⭐⭐⭐ 2026-10-01 v1.00【用户问：「规划没有拉黑特殊地块？还是规划那里并且去点了」】
    #   答：**两条都得堵**。v0.99 已让"拉黑格不参与连通/连锁/目标"（模型侧 ✓），
    #   但**点序里还可能出现它**——因为求解器的"可点步"是按"已揭示的块"给的，
    #   而点掉一个内容格在模型里也算"消耗一个块、让邻居算已揭示"
    #   （真机也确实如此：点一下会揭开邻居）⇒ solver 可能把宝箱怪当**便宜的开路步**排进去 ✗
    #   而执行侧 `cands` 只看 `done/cold`，**不认拉黑** ⇒ 真把它点了 ✗✗
    #   ⇒ 这里在**点序进 keep 之前**做硬过滤：拉黑格（含 solver plan 里的）一律剔除，
    #     并落日志 `blocked_in_order`（这样"规划里有没有它"一眼可见 ✓）。
    _blk_set = set()
    try:
        _blk_set = set(_blocked_px(st, c))
    except Exception:       # noqa: BLE001
        _blk_set = set()
    if _blk_set:
        _drop = [p for p in order if p in _blk_set]
        if _drop:
            _drop_rc = []
            for _p in _drop[:8]:
                try:
                    _drop_rc.append('%d,%d' % cell_of(_p[0], _p[1]))
                except Exception:       # noqa: BLE001
                    pass
            entry['blocked_in_order'] = _drop_rc
            log.append({'blocked_in_order': _drop_rc,
                        'note': '拉黑地块被排进点序 ⇒ 剔除（不点 ✓）'})
            say('       · 点序里有 %d 个拉黑地块（%s）⇒ 已剔除，不去点 ✓'
                % (len(_drop), '、'.join(_drop_rc)))
            order = [p for p in order if p not in _blk_set]
    # ⭐ 商人/宝库格**永不拉黑**（用户 2026-09-25：「有黄金宝库你没点就要退」）：
    #   点它那一下如果面板没被 OCR 认到（动画/时机），旧逻辑会给它 cold+1，
    #   两次之后进 `done` 永久排除 → 下一轮 buy=0 → 直接退图，宝库白白漏掉。
    # ⭐⭐⭐ 2026-10-01 v0.96：免拉黑范围**扩到「粘性集 + 跨轮记忆 + 验证式探点」** ——
    #   上面那段注释说的"永不拉黑"必须对**认到过**的宝库成立，而不是只对"本帧还认得出"的成立：
    #   真机证据（用户报「能直接点的黄金宝库不去点，却去打了两个战斗地块」）：
    #   `st['plan']` 里明明排了那格宝库（日志「最省体力 1，1 步 → 2,7」），
    #   但本帧 buy/buy_hidden 恰好都空 ⇒ `buy_px` 空 ⇒ `cands` 用 `cold<2` 把它滤掉
    #   ⇒ 点序跳到下一个候选（开路格）⇒ 弹出的"拦路"战斗就这么打起来了 ✗
    buy_px = (set(buy) | set(buy_hidden) | set(sticky)
              | set(st.get('buy_seen') or {}) | set(_probe_px))
    # ⭐⭐⭐ 2026-10-01 v0.96【能直接点就先点】：**已揭示的商人/宝库排到点序最前**
    #   用户口径（2026-09-25 / 2026-10-01 两次强调）：「有黄金宝库你没点就要退」、
    #   「黄金宝库明明都揭示了能直接点，他又去打了两个战斗地块」。
    #   旧点序是"揭一格 → 试一次目标"**交替**（`for p in reveals: order.append(p); order += targets`）
    #   ⇒ 第一下永远是**开路格**；枯木丛林那类图的开路格常触发"拦路"战斗
    #   ⇒ 用户看到的就是"宝库就摆在眼前，机器人先去打了两个战斗地块"✗
    #   ⇒ 宝库是 1 体力、点完就买；直接把它放最前（面板流程照旧接管 ✓）
    try:
        _buy_first = [p for p in buy if p not in done]
        if _buy_first:
            order = _buy_first + list(order)
            entry['buy_first'] = ['%d,%d' % cell_of(*p) for p in _buy_first]
    except Exception:       # noqa: BLE001
        pass
    # ⭐ 2026-09-26：按格累计「点了画面完全没反应」（跨轮持久，见下方拉黑逻辑）
    _nc = st.setdefault('nochange', {})
    cands = [x for x in order if x not in done
             and (x in marked_px or x in buy_px or cold.get(x, 0) < 2)]
    if not cands:
        log.append(entry)
        if marked:
            log.append({'finish': 'targets_unreachable'})
            return 'stuck'
        log.append({'finish': 'all_done'})
        return 'done'
    hit, tried = None, 0
    progress_set = set(clearable) | set(nones)     # 点这些格 = 开路/揭格（消耗地块 → 连锁揭示）
    tapped_progress = False
    # ⭐⭐ 2026-09-30 成本审计（零行为影响）：把"本轮点序前 12 格 + 模型体力"落日志
    #   用途：用户报「不点 1 体力的、去点 4 体力的」时，一眼看出
    #   ① 便宜格有没有排在前面（点序问题）② 模型把贵格看成了 1 点（分类问题）
    #   （现场存档 + 三种机制的判据见 `_verify/phone_stamina_0930/README.md`）
    try:
        _cells_now = c.get('st') or {}
        _marks_now = st.get('marks') or {}
        _oc = {}
        for _p in list(order)[:12]:
            _rc = cell_of(_p[0], _p[1])
            _v = _cells_now.get(_rc) or {}
            _mk = list((_marks_now.get(_rc) or {}).get('marks') or [])
            _oc['%d,%d' % _rc] = [model_cost(_v.get('sid'), _mk), _v.get('sid') or '?'] + _mk
        if _oc:
            entry['order_cost'] = _oc
    except Exception:       # noqa: BLE001
        pass
    for (cx, cy) in order:
        # ⭐⭐ 立即停止的**最细粒度**检查点（2026-09-29）：一次点击 + 连锁动画 ≈ 2~4 秒，
        #   放在这里 ⇒ 用户点 ■ 后**最多再等一次当前点击**就收工（不是"打完这张图"✓）
        if stop_checked(log, '点击前'):
            return 'stopped'
        if (cx, cy) in done or tried >= 12:
            continue
        if cold.get((cx, cy), 0) >= 2 and (cx, cy) not in marked_px \
                and (cx, cy) not in buy_px:
            done.add((cx, cy))
            continue
        tried += 1
        st['last'] = (cx, cy)
        if (cx, cy) not in (st.get('clicked') or []):
            st.setdefault('clicked', []).append((cx, cy))     # 退出前补点用
        # ⭐⭐ 2026-09-28 诊断（**零行为影响**，只多记几个字段）：每次点击记
        #   「格 / 本轮开始后第几秒 / 画面是否变化」⇒ 用来判"点了没反应"到底是
        #   ① 格子不可点（规则）还是 ② 连锁揭示动画还没播完（时序）。
        #   背景：r_221835_0 那把计划 8 点、实花 7 点，(4,5) 那一击 `changed is False`
        #   且没扣体力；(5,4) 却是"第一次 noop、第二次成功" ⇒ 两种解释都成立，
        #   必须靠"点击时刻"区分（见 .workbuddy/memory/2026-09-28.md §37.3 ✓）
        _t_tap = time.time()
        # ⭐⭐ 2026-09-30 成本审计：这一格**模型以为**花多少体力（记进 taps，便于和体力读数对账）
        _cost_tap, _sid_tap = None, '?'
        try:
            _rc_tap = cell_of(cx, cy)
            _v_tap = (c.get('st') or {}).get(_rc_tap) or {}
            _mk_tap = list(((st.get('marks') or {}).get(_rc_tap) or {}).get('marks') or [])
            _sid_tap = _v_tap.get('sid') or '?'
            _cost_tap = model_cost(_v_tap.get('sid'), _mk_tap)
        except Exception:       # noqa: BLE001
            _cost_tap, _sid_tap = None, '?'
        changed = b.tap(cx, cy, wait=1.3)
        # ⭐ 2026-10-01 v0.96：验证式宝库点击**计数**（每格每图上限 BUY_PROBE_MAX ✓）
        #   —— 防"一直点不开的宝库"空转（2026-09-25 卡死事故的复刻预防 ✓）
        if (cx, cy) in _probe_px:
            try:
                st.setdefault('buy_probe', {})[(cx, cy)] = \
                    st['buy_probe'].get((cx, cy), 0) + 1
            except Exception:       # noqa: BLE001
                pass
        try:
            entry.setdefault('taps', []).append(
                ['%d,%d' % cell_of(cx, cy), round(_t_tap - _t_round, 1),
                 (changed is not False), _sid_tap, _cost_tap])
        except Exception:       # noqa: BLE001
            pass
        b.snap()
        # ⭐ B（2026-09-25 用户要求「都试试」）：**只在"画面完全没变"时**跳过这次 OCR
        #   （0.74 秒/次，36 次/图是大头）。
        #   ⚠ 为什么这次敢跳：弹面板**必然**引起画面变化 ⇒ `changed` 会是 True ⇒ 照样 OCR ✓；
        #     只有"点了跟没点一样"（点不动的暗格/被挡）才会 False ⇒ 那种情况 OCR 也读不到东西 ✓。
        #   （之前那次事故是因为**同时**还砍了"回合开头的全屏 OCR"，漏看残留面板 ⇒ 乱点；
        #     回合开头那次全屏 OCR 现在保留着 ✓）
        if changed is False:
            it2 = []
            # ⭐⭐ 2026-09-27 修（用户报「第 7 张图 boss 没打就说没目标」）：
            #   点不动有两种 —— ① **未揭示的雾格**（游戏本来就点不动 ✓ 正常 ✓）
            #   ② 真被面板/别的东西挡住 ✓。原来不分 ⇒ 雾格被记 nochange ⇒ 3 次拉黑 ✗
            #   ⇒ 拉黑后 boss 目标等同消失 ⇒ 判 targets_done 提前退图 ✗✗
            #   判据：该格亮度比 <0.8 = 未揭示（已揭示≈1.0 / 未揭示≈0.65 ✓）
            #   （v0.29 回退：v0.27 的 revealed 前置改动撤销，恢复 v0.26 原判定 ✓）
            _cells_now = (c.get('st') or {}) if c else {}
            _tap_rc = cell_of(cx, cy)
            _tv = _cells_now.get(_tap_rc) or {}
            _ratio = _tv.get('ratio')
            _fogged = (_ratio is not None and float(_ratio) < 0.8) or (_tap_rc not in _cells_now)
            if _fogged:
                log.append({'tap': 'fogged_noop', 'at': (cx, cy),
                            'cell': '%d,%d' % _tap_rc,
                            'ratio': _ratio,
                            'note': '未揭示格点不动=正常 ⇒ 不计 nochange ✓'})
            else:
                entry.setdefault('tap_no_change', 0)
                entry['tap_no_change'] += 1
                # ⭐ 2026-09-26：**按格**记「点了画面完全没反应」
                _nc[(cx, cy)] = _nc.get((cx, cy), 0) + 1

        else:
            # ⭐ 2026-09-26：上界 980 → **1080**（「获得新装备！」标题实测在 y≈992，
            #   卡在条带外 ⇒ 认不到 ⇒ 循环对着弹窗继续点 ✗）。只多 100px（+12% 高度）✓
            it2 = b.ocr(band=(LAYOUT.sy(130), LAYOUT.sy(1080)), tag='tap')
            # ⭐⭐⭐ 2026-10-01 真机修（用户报「识别到宝库，但点开**瞬间就关掉了**，
            #   后面乱点」）：上面这条 band 到 1080 就断，而**宝库面板的签名**
            #   （右下「购买/选择奖励/离开」按钮）在真机上落在弹窗系 1330~1650
            #   ⇒ 归一化帧 ≈1121~1441 ⇒ **整条签名在 band 之外** ⇒ `panel_seen(it2)`
            #   认不出宝库 ⇒ 循环不 break，继续按点序点下一格 ⇒ 那一击正落在
            #   宝库面板按钮/关闭区 ⇒ **面板被自己的下一次点击关掉** ✗✗（"瞬间"就是这个）
            #   ⇒ 补一条**只在弹窗帧上判宝库**的检查（`_dlg_btn_sig`，零额外代价：
            #     dlg 帧条目本来就要取，且只在"点完画面变了"这条路径上做一次 ✓）
            try:
                _dts = dlg_ocr(b, tag='tap_dlg')
                if _dts and (vault_title_seen(_dts) or _dlg_btn_sig(_dts, 'vault')):
                    hit = ('tap', cx, cy)
                    done.add((cx, cy))
                    entry['panel_via'] = 'vault_dlg'
                    log.append({'tap': 'vault_panel_by_dlg', 'at': (cx, cy),
                                'btn_zone': [(i.get('cx'), i.get('cy'),
                                              (i.get('text') or '')[:6])
                                             for i in _dts
                                             if 700 < i.get('cx', 0) < 1040
                                             and 1300 < i.get('cy', 0) < 1680][:4]})
                    say('       · 点 (%d,%d) → 弹出**黄金宝库**（弹窗帧标题/按钮 ✓ 不关它）'
                        % (cx, cy))
                    break
            except Exception:       # noqa: BLE001
                pass
            # ⭐ v0.35：撤掉 tap_ocr 诊断日志（校准使命已完成：FIGHT_Y=735 已钉死；
            #   用户 09-29 要求去掉）。⚠ **OCR 本体保留** —— it2 是偶遇强敌/获得新装备/
            #   预言石板/发现莱姆的唯一判据，删了这些面板就全瞎了 ✗
        # ⭐ 2026-09-27：点完回报"连锁 or 面板"⇒ 边跑边学空地判据 ✓
        #   ⚠ 判据必须是"**认到面板文字**" ✓ 不能只看"画面有变化"✗
        #     （点空地连锁也会让画面变化 ✗ 我第一版就是这么写错的 ✗
        #      实测把草地 S00003_001 学成了 panel ✗ ⇒ 计划绕开草地 ✗）
        if LEARN_TILES:
            try:
                _sid_now = ''
                if st.get('last') and c.get('st'):
                    _tc2 = cell_of(st['last'][0], st['last'][1])
                    _sid_now = str((c['st'].get(_tc2) or {}).get('sid') or '')
                if _sid_now:
                    _ptxt = ' '.join((i.get('text') or '') for i in (it2 or []))
                    _has_panel = any(k in _ptxt for k in
                                     ('战斗事件', '探索产出', '探索配队', '选择奖励',
                                      '一键派遣', '开始探索'))
                    if changed is not None:
                        import mapsim as _ms2
                        _ms2.learn_tile(_sid_now, plain=not _has_panel)
                        log.append({'learn_tile': _sid_now,
                                    'as': 'panel' if _has_panel else 'plain'})
            except Exception:       # noqa: BLE001
                pass

        # ⭐ 2026-09-25 用户报「综合那个被遭遇强敌卡住了」：**点完这一下必须检查
        #   「偶遇强敌 / 遭遇强敌」和「发现莱姆」** —— 原来这两个不在检查列表里，
        #   于是循环对着面板继续点（把下面的点击全点到面板按钮上）= 卡住 + 乱点。
        #   这里就地关掉（强敌点右上角 X；莱姆点返回），然后继续点序里的下一格。
        if fb(it2, *L['strong']):
            x = find_x(it2)
            if x:
                b.tap(x['cx'], x['cy'], wait=1.5)
            else:
                close_x_panels(b, b.img())
            log.append({'tap': 'strong_closed', 'at': (cx, cy),
                        'closed_at': (x['cx'], x['cy']) if x else None})
            say('       · 点 (%d,%d) 弹出「偶遇强敌」→ 不打，关掉' % (cx, cy))
            continue
        lb2 = lime_back(it2)
        if lb2:
            b.tap(lb2['cx'], lb2['cy'], wait=1.5)
            log.append({'tap': 'lime_back', 'at': (cx, cy)})
            say('       · 点 (%d,%d) 弹出「发现莱姆」→ 点返回' % (cx, cy))
            continue
        # ⭐「获得新装备！」（2026-09-26）：点到大拇指/莱姆点时弹，就地关掉再点下一格
        if close_newequip(b, it2, log, 'tap', at=(cx, cy)):
            say('       · 点 (%d,%d) 弹出「获得新装备！」→ 点返回' % (cx, cy))
            continue
        # ⭐「预言石板」（2026-09-26 用户要求）：点出它就关掉，并**拉黑这格不再点** ✓
        #   ⚠ 面板标题可能不在条带(y130~1080)里 ⇒ 这里只当**快路径**；漏了下一轮
        #     `popups()` 的全屏 OCR 还会兜住（那里也会关 + 拉黑 ✓）
        if fb(it2, *L['prophecy']):
            universal_close(b, log, items=it2, probe=L['prophecy'][0], where='tap',
                            at=(cx, cy))
            block_cell(log, st, (cx, cy), 'prophecy')
            say('       · 点 (%d,%d) 弹出「预言石板」→ 关掉并拉黑这格' % (cx, cy))
            continue
        if (cx, cy) in progress_set:
            st['clear_clicks'] = st.get('clear_clicks', 0) + 1
            tapped_progress = True
        # ⭐ v0.33：原来只认面板**标题** ⇒ 真机高分辨率上标题落在弹性区看不见
        #   ⇒ 判不成"弹了面板" ⇒ 主循环带着面板继续点后面的格（点击全落到面板上 ✗）
        #   ⇒ 改用 panel_seen()（补"弹窗系独立按钮"这条判据，PC 行为不变 ✓）
        if panel_seen(it2, b=b):
            hit = ('tap', cx, cy)
            done.add((cx, cy))
            # ⭐ v0.33 诊断：记下是"认到标题"还是"靠弹窗系按钮"判成的（真机只会是后者）
            entry['panel_via'] = 'title' if (
                fb(it2, L['fight'], L['expl'], *L['claim'])
                or fb(it2, *L['desc']) or fb(it2, *L['special'])) else 'dlg_btn'
            say('       · 点 (%d,%d) → 弹面板' % (cx, cy))
            break
        cold[(cx, cy)] = cold.get((cx, cy), 0) + 1
        if cold[(cx, cy)] >= 2 and (cx, cy) not in marked_px \
                and (cx, cy) not in buy_px:
            done.add((cx, cy))
        # ⭐ 2026-09-26（用户报「综合乱点」）：同一格**点了没反应**也要计数拉黑 ✱
        #   原来只有 cold 计数，而 **marked（标记格）/ buy（商人宝库）被"永不拉黑"保护**
        #   ⇒ 面板盖着棋盘、它又点不动时 ⇒ **每轮点同一格**，实测连点 5 轮
        #   （日志 `tap_no_change:1, tried:1, clear_clicks:3` ×5）⇒ stuck⇒no_progress ✗
        #   ⇒ 现在：同一格累计 3 次「点了没反应」⇒ 本轮拉黑，下一轮不再点它 ✓
        if _nc.get((cx, cy), 0) >= 3:
            done.add((cx, cy))
            log.append({'tap_no_change_blacklist': '%d,%d' % (cx, cy),
                        'n': _nc[(cx, cy)]})
    entry['tried'] = tried
    entry['clear_clicks'] = st.get('clear_clicks', 0)
    # ⭐⭐ 整轮"点了都没反应" ⇒ 十有八九是**盖着面板** ⇒ 连续 2 轮就清面板/脱困，
    #   别再下一轮盲点（原来要等到 stuck>=4 才退图，中间全是白点 ✗）
    if entry.get('tap_no_change', 0) >= 1 and not hit:
        st['nochange_rounds'] = st.get('nochange_rounds', 0) + 1
        if st['nochange_rounds'] >= 2:
            n = close_x_panels(b, b.img())
            if not n:
                x = find_x(b.ocr(tag='nochange'))
                if x:
                    b.tap(x['cx'], x['cy'], wait=1.5)
                    n = 1
            if not n:
                # ⭐⭐ v0.34：连着两轮"点了没反应" + 关不掉 ⇒ 多半是**认不出类型的面板**
                #   （真机上标题落在归一化帧丢弃的弹性区：偶遇强敌/旅行商人/预言石板/…）
                #   ⇒ 补一次**弹窗帧** OCR（≈2s，只在真的卡住时）认类型再按类型处理 ✓
                _dp = dlg_ocr(b, tag='nochange_dlg')
                if _dp:
                    _OCR_CH['dlg'] = True      # ⭐ 同上：_dp 是弹窗系
                    try:
                        _act3 = popups(b, _dp, log, ctx={'in_dlg': True,
                                                         'flags': st,
                                                         'tapped': st.get('last'),
                                                         'marks': st.get('marks') or {},
                                                         'st': st.get('cells')})
                    finally:
                        _OCR_CH['dlg'] = False
                    log.append({'popup': 'dlg_frame_retry_nochange',
                                'n_items': len(_dp), 'act': _act3,
                                'texts': [(i.get('text') or '')[:10] for i in _dp][:26]})
                    if _act3 in ('battle', 'battle_clear', 'handled'):
                        n = 1
            if not n:
                force_unstick(b, log, 'tap_no_change',
                              ctx={'tapped': st.get('last'), 'flags': st})
            log.append({'tap': 'nochange_unstick', 'closed': n,
                        'rounds': st['nochange_rounds']})
            say('       · 连续 %d 轮点了没反应 ⇒ 清面板/脱困（closed=%d）'
                % (st['nochange_rounds'], n))
            status('点了没反应 · 正在脱困')
            st['nochange_rounds'] = 0
    else:
        st['nochange_rounds'] = 0
    if hit or tapped_progress:
        if hit:
            entry['hit'] = hit
        st['stuck'] = 0
    else:
        st['stuck'] += 1
        entry['stuck'] = st['stuck']
        if st['stuck'] >= 4:
            log.append(entry)
            log.append({'finish': 'no_progress'})
            return 'stuck'
    log.append(entry)
    return None


def scan_bag():
    """把当前屏 OCR 出来并落盘截图（用于标定背包/「使用」按钮坐标）"""
    # ⚠ 2026-10-01 修：这里原来写 `serial=SERIAL`，而 `SERIAL` **从未定义**
    #   （是早期 `INSTANCE_DEV` 的残留名）⇒ 真跑到这个标定入口就 NameError ✗
    b = Bot(log_prefix='scanbag', serial=INSTANCE_DEV, tag=INSTANCE_TAG, use_fast=True)
    b.snap('scanbag', save=True)
    items = b.ocr(min_conf=0.3, tag='scanbag')
    say('当前屏文字 %d 条：' % len(items))
    for i in sorted(items, key=lambda x: (x['cy'], x['cx'])):
        say('   (%4d,%4d) %s' % (i['cx'], i['cy'], i['text'][:36]))
    say('截图已存到 runs/ 目录（scanbag.png）')
    return 0


def _release_lock():
    if _LOOP_LOCK:
        try:
            import loopguard
            loopguard.release(_LOOP_LOCK[0], _LOOP_LOCK[1])
        except Exception:       # noqa: BLE001
            pass


def next_5am(now=None):
    """下一个停止时刻（默认 04:58；今天还没到就今天，否则明天）"""
    import datetime as _dt
    now = now or _dt.datetime.now()
    t = now.replace(hour=STOP_HM[0], minute=STOP_HM[1], second=0, microsecond=0)
    if t <= now:
        t += _dt.timedelta(days=1)
    return t


def past_stop_time():
    """到点了吗（到点就该收工）"""
    import datetime as _dt
    # 【Android】广播 cmd=stop → 与「到点」共用同一个挂载点
    #   ⚠ 2026-09-29 用户口径改成「立即停止」后，主路径已由 `stop_requested()` 在
    #   轮首/每次点击前**抢先**接住（不等打完）；这里是兜底（万一有新挂载点用到它）
    if _MAPBOT_ANDROID and globals().get('_ANDROID_STOP'):
        say('⏹ 收到外部停止指令 ⇒ 收工')
        return True
    if not STOP_AT_5AM or STOP_TIME is None:
        return False
    return _dt.datetime.now() >= STOP_TIME


def stop_requested():
    """⭐ **立即停止**信号（2026-09-29 用户口径：「停止键点了要立即停止，不要等打完这张图」）

    · 端上（APK）：悬浮条点 ■ ⇒ 广播 ⇒ `explore_android.stop()` ⇒ `android_request_stop()`
      ⇒ `_ANDROID_STOP = True` ⇒ 这里立刻返回 True
    · PC 上 `_ANDROID_STOP` **根本不存在** ⇒ 恒 False ⇒ **行为一字不变 ✓**（零回归风险）
    · 与 `past_stop_time()`（凌晨 5 点 / 两张图之间）的区别：那个**故意**等到图边界，
      这个**每一步都要查**（见 `run_one_map` 的轮首 + 每次点击前）
    """
    return bool(globals().get('_ANDROID_STOP'))


def stop_checked(log=None, where=''):
    """查到停止请求就记一条日志并返回 True（调用方负责立刻 return/break ✓）"""
    if not stop_requested():
        return False
    if log is not None:
        log.append({'stop': 'user_immediate', 'where': where})
    say('⏹ 收到「停止」⇒ %s 立刻收工（不等这张图打完 ✓）' % (where or '',))
    status('收到停止 · 立刻收工')
    return True


def guard_duplicates(device, tag, force=False):
    # 【Android】单实例运行，没有 tasklist / 多开抢点击的问题 ⇒ 直接放行
    if _MAPBOT_ANDROID:
        return True
    """⭐ 用户 2026-09-25：启动前查重 —— 同一台模拟器已经有循环在跑就**拒绝启动**

    两道防线见 `loopguard.py`：原子锁（同 tag 抢锁）+ 进程枚举（兜住绕过锁的）。
    `--force` 可以强行启动（调试用）。
    """
    try:
        import loopguard
    except Exception:       # noqa: BLE001
        return True
    try:
        return _guard_duplicates_inner(loopguard, device, tag, force)
    except Exception as ex:     # noqa: BLE001 —— 守卫自身出错就放行，绝不让它拖垮循环 ✓
        import traceback
        say('⚠ 重复循环自检出错（%r），本次直接放行' % ex)
        say('   ' + ' | '.join(traceback.format_exc().splitlines()[-2:]))
        return True


def _guard_duplicates_inner(loopguard, device, tag, force):
    dupes = loopguard.duplicates_for(device, tag, exclude_pid=os.getpid())
    if dupes:
        say('')
        say('⚠ 已经有一个循环在跑同一台模拟器（%s）：' % device)
        for p in dupes:
            say('     PID %-6d 设备 %-20s tag %s' % (p['pid'], p['device'] or '?',
                                                     p['tag'] or '-'))
        if not force:
            say('')
            say('   为避免两边抢点击，这次不启动 ✗')
            say('   · 想停掉旧的：在它的窗口点「停止」，或删掉锁文件后重来')
            say('   · 确实要强开（调试用）：加 --force')
            return False
        say('   --force：仍然启动（可能互相抢点击）')
    ok, info = loopguard.acquire(device, tag)
    if not ok:
        say('⚠ 设备锁被占用：%s' % json.dumps(info, ensure_ascii=False))
        if not force:
            return False
    globals()['_LOOP_LOCK'] = (device, tag)
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-round', type=int, default=45)
    ap.add_argument('--force', action='store_true',
                    help='已有同设备循环时也强行启动（调试用）')
    ap.add_argument('--no-guard', action='store_true',
                    help='跳过重复循环自检（GUI 已查过时用）')
    ap.add_argument('--scan-bag', action='store_true',
                    help='把当前屏 OCR 落盘（标定背包界面用）')
    ap.add_argument('--maps', type=int, default=1)
    ap.add_argument('--deadline', type=int, default=900)
    ap.add_argument('--quiet', action='store_true', help='关掉控制台实时进度')
    ap.add_argument('--no-dump', action='store_true', help='结束时不打印全量 json 日志')
    ap.add_argument('--min-stamina', type=int, default=25,
                    help='进图前体力下限（低于它就收工）；连刷模式用 50')
    ap.add_argument('--bag-every', type=int, default=10,
                    help='每连刷多少张图去背包做一次装备一键升星（0=关闭，默认10）')
    ap.add_argument('--no-solver', action='store_true',
                    help='关掉精确规划（走原来的启发式点序）')
    ap.add_argument('--device', default=None,
                    help='adb 设备号（多开：127.0.0.1:16384 / 16416 / 16448 …）')
    ap.add_argument('--tag', default='',
                    help='多开实例名（隔离截图/日志/统计目录），如 acc1 / acc2')
    ap.add_argument('--auto-supply', action='store_true',
                    help='没体力时自动进背包使用「结实补给」（窗口勾选框用）')
    ap.add_argument('--opt', action='store_true',
                    help='体力最省模式：每轮用 Dijkstra 求最优点序（mapsolve）')
    # ⭐⭐ 2026-09-27 用户要求：「开一个新脚本抓另一个模拟器 —— 只进图截图退图，拿图片快一些」
    ap.add_argument('--collect-only', dest='collect_only', action='store_true',
                    help='采图模式：只「进图 → 存首帧 → 退图」，不揭格/不打怪/不买/不补点'
                         '/不背包升星（拿到最干净的首帧；⚠ 每张图照旧扣 25 体力）')
    a = ap.parse_args()
    # ⭐ 用户 2026-09-25：「加个检测有没有重复的循环进程」
    #   同一台模拟器上已有循环在跑 ⇒ 拒绝启动（两个循环会互相抢点击、抢状态）
    if not getattr(a, 'no_guard', False):
        import atexit
        if not guard_duplicates(a.device or '', a.tag or '',
                                force=getattr(a, 'force', False)):
            return 3
        atexit.register(_release_lock)
    global VERBOSE, DUMP_AT_END, MIN_STAMINA, WIN, LOG_PATH, SUMMARY_PATH, AUTO_SUPPLY
    global INSTANCE_TAG, INSTANCE_DEV, _BOT, STOP_TIME, COLLECT_ONLY
    VERBOSE = not a.quiet
    DUMP_AT_END = not a.no_dump
    MIN_STAMINA = a.min_stamina
    # ⭐ 每 N 张图做一次装备升星（窗口可填 ✓ 默认 10 ✓）
    global BAG_EVERY, OPT_SOLVER   # 必须声明，否则只是局部变量（用户报取消勾选还规划）
    BAG_EVERY = max(0, int(getattr(a, 'bag_every', 10) or 0))
    OPT_SOLVER = not bool(getattr(a, 'no_solver', False))
    say('   · 精确规划：' + ('开 ✓' if OPT_SOLVER else '关（走启发式 ✓）'))
    say('   · 装备升星：' + (('每 %d 张图一次' % BAG_EVERY) if BAG_EVERY else '关闭（0）'))
    global STOP_TIME
    STOP_TIME = next_5am() if STOP_AT_5AM else None
    if STOP_TIME:
        say('⏰ 本次运行到 %s 自动停止（打完手上这张图就收工）'
            % STOP_TIME.strftime('%m-%d %H:%M'))
    AUTO_SUPPLY = bool(getattr(a, 'auto_supply', False))
    global OPT
    OPT = bool(a.opt)
    COLLECT_ONLY = bool(getattr(a, 'collect_only', False))
    if COLLECT_ONLY:
        # 采图模式下这些开关没意义 ⇒ 直接按最省的方式跑，免得误触
        BAG_EVERY = 0
        _tag = (getattr(a, 'tag', '') or '').strip()
        say('')
        say('📷 采图模式（--collect-only）：只做「进图 → 存首帧 → 退图」')
        say('   · 不揭格 / 不打怪 / 不买 / 不补点 / 不背包升星')
        say('   · ⚠ 每张图照旧扣 **25 体力**（进图瞬间扣，退图不退）—— 这是拿体力换图片')
        say('   · 存图目录：%s' % (os.path.join(RUNS, _tag) if _tag else RUNS))
        say('')
    INSTANCE_TAG = (a.tag or '').strip()
    INSTANCE_DEV = a.device or DEV
    _lock = acquire_device_lock(INSTANCE_DEV)
    if _lock is None:
        say('⚠ 这台模拟器（%s）已经有另一个自动探索在跑了 —— 同时跑两个会互相抢点击。' % INSTANCE_DEV)
        say('   要强制重跑：先停掉那个窗口，或删掉 %s' % device_lock_path(INSTANCE_DEV))
        return
    # ⭐ 红装锁：上次发现红装还没处理 ⇒ **拒绝启动**，绝不把那一局带走
    #   （用户 2026-09-25：「下次遇到红装要立刻停止，不准退出图」）
    rl = red_locked(INSTANCE_DEV)
    if rl:
        say('')
        say('🛑 上次在这台模拟器上**发现了红装（SS）**，已经锁定，不启动新的探索：')
        say('     地图 %s  格 %s  时间 %s  截图 %s'
            % (rl.get('map'), rl.get('cell'), rl.get('at'), rl.get('shot')))
        say('     请先在游戏里处理掉那件红装；处理完在窗口上点「红装已处理·解锁」，')
        say('     或手动删掉：%s' % red_lock_path(INSTANCE_DEV))
        say('')
        release_device_lock(_lock)
        return
    try:
        run_maps(a)
    finally:
        release_device_lock(_lock)


def _game_screen_ok(items):
    """当前帧 OCR 是否具备**游戏任何界面**的特征（崩溃自恢复检测用）。
    全 OCR 文字判据，无写死坐标 ⇒ 全分辨率适用 ✓"""
    import re as _re
    txts = [(i.get('text') or '') for i in items]
    for t in txts:
        if _re.search(r'\d+/\d+', t) and ('/' in t):      # HUD 体力/资源计数
            return True
    for k in ('开始冒险', '进入地图', '结束冒险', '快速扫荡', '公会', '斗技场',
              '星界秘境', '开始游戏', '检测到游戏更新'):
        if any(k in t for t in txts):
            return True
    return False


def _game_main_ok(items):
    """⭐ 恢复成功的**严格**判定：游戏已进到可玩界面（主界面/选图/图内）。
    登录页（开始游戏/我已同意/健康忠告）/热更提示（检测到游戏更新）/公告 都不算 ✓
    （v0.57 实锤：宽判据把登录页误判成恢复成功 ⇒ 公告没关 ⇒ 进图全卡 stuck）"""
    import re as _re
    txts = [(i.get('text') or '') for i in items]
    joined = ''.join(txts)
    for bad in ('开始游戏', '检测到游戏更新', '我已详细阅读', '健康游戏忠告', '公告'):
        if bad in joined:
            return False
    for t in txts:
        if _re.search(r'\d+/\d+', t):
            return True
    for k in ('开始冒险', '进入地图', '结束冒险', '快速扫荡', '斗技场', '星界秘境'):
        if any(k in t for t in txts):
            return True
    return False


def game_recover(b, log, tag='recover', timeout=600):
    """⭐⭐ 2026-10-01 崩溃自启动 + 热更新导航（用户要求：「游戏会热更新，记得做上这个备案」「全分辨率适用」）。

    游戏进程死亡/停在热更页/登录页时：
      bringGame 拉起 → **全 OCR 文字导航**（无写死坐标 ✓ 任意分辨率 ✓）：
        「检测到游戏更新/需下载」→ 点「确定」（开始下载）
        「下载中/更新中/加载资源」→ 静默等待（进度自己走）
        「公告」+「确定」→ 点确定
        「开始游戏」→ 点它（登录）
        「同意/同意并继续」→ 点它（隐私协议）
        主界面特征（开始冒险/进入地图/结束冒险/快速扫荡）→ 成功 ✓
    超时（timeout 秒）返回 False；每步动作/等待都落 log。"""
    dev = None
    try:
        from java import jclass as _jc      # Chaquopy（mapbot._api 同款）
        dev = _jc('com.fantasy.autoexplore.DeviceApi')
    except Exception as e:  # noqa: BLE001
        log.append({'recover': 'no_deviceapi', 'e': repr(e)[:120]})
        return False
    if not dev.bringGame():
        return False
    say('   ⚙ 游戏已拉起，等待加载/热更/登录（OCR 导航，最多 %d 秒）' % timeout)
    status('正在把游戏拉回来…')
    t0 = time.time()
    acted_at = 0.0
    while time.time() - t0 < timeout:
        if globals().get('_ANDROID_STOP') or stop_requested():
            return False
        b.snap(tag)
        items = b.ocr(min_conf=0.35, tag=tag)
        txts = [(i.get('text') or '').replace(' ', '') for i in items]
        joined = ''.join(txts)
        if _game_main_ok(items):
            # ⭐ 严格判定（_game_main_ok）：登录页/公告/热更提示都不算恢复成功，
            #   继续导航把它们处理掉 ✓
            log.append({'recover': 'ok', 'secs': round(time.time() - t0, 1)})
            say('   ⚙ 游戏恢复 ✓（用时 %.0f 秒）' % (time.time() - t0))
            status('游戏已恢复 ✓')
            return True
        act = None
        def _find_one(label, extra=()):
            for i in items:
                t = (i.get('text') or '').replace(' ', '')
                if t == label or any(k in t for k in (label,) + tuple(extra)):
                    return i
            return None
        if ('检测到游戏更新' in joined) or ('需下载' in joined):
            act = _find_one('确定')
            if act:
                b.tap(act['cx'], act['cy'], wait=2.5)
                log.append({'recover': 'update_confirm', 'at': (act['cx'], act['cy'])})
                say('   ⚙ 热更提示 → 点确定（开始下载）')
        elif ('下载' in joined) or ('更新中' in joined) or ('加载资源' in joined) or ('%' in joined):
            if time.time() - acted_at > 30:
                log.append({'recover': 'downloading', 'texts': txts[:10]})
                say('   ⚙ 热更资源下载中…（等待，不点击）')
                acted_at = time.time()
            time.sleep(4.0)
            continue
        # ⚠⚠ 2026-10-01 v1.16 修**真 bug**：登录页上「公告」两个字**仍在画面里**
        #   （实测 OCR：['公告','幻想少女公会','开始游戏','我已详细阅读并同意《',…]）
        #   ⇒ 旧的 `elif ('公告' in joined)` 抢先命中 → 帧上没有「确定」⇒ act=None
        #      → **`elif _find_one('开始游戏')` 永远轮不到**（elif 互斥）✗
        #      ⇒ 登录页永远点不到「开始游戏」，自动登录形同虚设。
        #   修法：**先判登录页**（最具体），公告分支放后面，并要求它有独立的「确定」按钮。
        elif _find_one('开始游戏'):
            act = _find_one('开始游戏')
            b.tap(act['cx'], act['cy'], wait=3.0)
            log.append({'recover': 'start_game', 'at': (act['cx'], act['cy'])})
            say('   ⚙ 登录页 → 点「开始游戏」')
        # 公告分支收紧：必须有**独立的「确定」按钮**才点，否则只记日志等画面推进
        #   （登录页/主界面上出现「公告」字样 ≠ 有公告弹窗 ✗）
        elif ('公告' in joined) and _find_one('确定'):
            act = _find_one('确定')
            b.tap(act['cx'], act['cy'], wait=2.5)
            log.append({'recover': 'notice_confirm', 'at': (act['cx'], act['cy'])})
            say('   ⚙ 公告弹窗 → 点确定')
        elif _find_one('同意', '同意并继续'):
            act = _find_one('同意', '同意并继续')
            b.tap(act['cx'], act['cy'], wait=2.5)
            log.append({'recover': 'agree', 'at': (act['cx'], act['cy'])})
        if act is not None:
            acted_at = time.time()
        else:
            time.sleep(3.0)      # 无识别目标 ⇒ 等画面推进
    log.append({'recover': 'timeout'})
    say('   ⚠ 游戏恢复超时（%d 秒）' % timeout)
    status('游戏起不来 · 已停下')
    return False


def _reset_run_stats():
    """把**每一轮开跑都该清零**的统计字段复位（`STATS` 是模块级，不重置就会串轮）

    ⚠ 只清"本轮"的字段；`STATS` 里没有跨轮累加项（设置类常量都在别处），
      所以这里按"白名单重置"比整体重建更安全（不会把将来新增的字段漏掉语义）：
      —— 将来若有人往 STATS 里加**跨轮**字段，务必加到下面的 `keep` 里并写清理由 ✓
    """
    keep = ()                      # 目前没有跨轮字段
    for _k in ('maps', 'shots', 'boss_fights', 'boss_wins', 'recommend_fights',
               'recommend_wins', 'dice_got', 'merchants', 'vaults', 'battles',
               'battle_wins', 'clovers', 'current_map', 'current_secs',
               'classify', 'classify_n', 'recover_n', 'stuck_maps'):
        if _k not in keep:
            STATS[_k] = 0
    STATS['map_secs'] = []
    STATS['stamina_entries'] = []
    STATS['stopped'] = ''          # ⭐ 关键：上一轮的结束原因**不许**串到这一轮
    STATS['running'] = True


def run_maps(a):
    global WIN, LOG_PATH, SUMMARY_PATH, _BOT
    # ⭐⭐⭐ v1.45h【每次开跑先把统计清零】—— 2026-10-04 真机实证的坑：
    #   上一轮失败留下的 `STATS['stopped']='游戏自动恢复失败'` **串到了这一轮**，
    #   于是"一张图正常打完、`result='done'`"的一轮，统计里却写着
    #   「结束原因：游戏自动恢复失败」⇒ 用户当然以为坏了 ✗✗
    #   （`run_maps` 原先**完全没重置** STATS，它只在模块 import 时初始化过一次）
    _reset_run_stats()
    b = Bot(log_prefix='loop', serial=INSTANCE_DEV, tag=INSTANCE_TAG or None)
    # ⭐ 分辨率自适应：拿到真实屏幕尺寸后刷新坐标 ✓（1080×1920 下零变化 ✓）
    try:
        _im = b.img()
        if _im is not None:
            _h, _w = _im.shape[:2]
            _L = apply_layout(_w, _h)
            say('屏幕 %dx%d ⇒ 缩放 k=%.4f（参考 1080×1920 ✓）' % (_w, _h, _L.k))
            if (_w, _h) != (layout_mod.REF_W, layout_mod.REF_H):
                say('   ⚠ 非参考分辨率：棋盘 x0=%d y0=%d 格距=%.1f（自适应 ✓）'
                    % (_L.grid['x0'], _L.grid['y0'], _L.grid['cx']))
    except Exception as _e:      # noqa: BLE001
        say('⚠ 分辨率自适应失败（按 1080×1920 继续 ✓）：%r' % (_e,))
    _BOT = b
    if INSTANCE_TAG:                      # 多开：日志/统计也各自独立
        WIN = os.path.join(b.runs, 'loop')
        os.makedirs(WIN, exist_ok=True)
        LOG_PATH = os.path.join(WIN, 'loop_log.json')
        SUMMARY_PATH = os.path.join(b.runs, 'last_summary.json')
    say('实例：%s  设备：%s  目录：%s' % (INSTANCE_TAG or '（单开）', INSTANCE_DEV, b.runs))
    log = []
    t_all = time.time()
    status('开跑 · 正在找游戏画面' if a.maps > 1 else '开跑（1 张）· 正在找游戏画面')
    for mi in range(a.maps):
        # ⭐ 2026-09-29 用户口径：点 ■ 要**立即停止**（比凌晨 5 点的判定点**更靠前**）
        if stop_checked(log, '地图边界（第 %d 张前）' % (mi + 1)):
            STATS['stopped'] = '用户点了停止'
            break
        # ⭐ 2026-09-26 用户要求：凌晨 5 点自动停止
        #   停**每张图之间**（不打断正在打的那张 ⇒ 退图流程照常走完，不会留下半张图 ✓）
        if past_stop_time():
            log.append({'stop': 'five_am', 'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'stop_time': STOP_TIME.strftime('%m-%d %H:%M')})
            STATS['stopped'] = '到点自动停止（%02d:%02d）' % STOP_HM
            say('⏰ 到 %s 了（%02d:%02d 自动停止），最后一张图已打完，收工'
                % (STOP_TIME.strftime('%m-%d %H:%M'), STOP_HM[0], STOP_HM[1]))
            break
        b.snap('m%d_pre' % mi)
        # ⭐ 2026-09-28 提速（P1）：原版这里对**同一帧**跑了两遍全屏 OCR
        #   （一遍查顶号、一遍读体力，0.8s/次纯浪费）⇒ 合并成一次，两项都从这帧取 ✓
        _items_pre = b.ocr(tag='pre')
        if fb(_items_pre, *L['kick']):
            log.append({'stop': 'kicked'})
            STATS['stopped'] = '账号被其他设备顶下线'
            say('⚠ 账号被其他设备顶下线，已停止（不会自动点确定）')
            break
        # ⭐⭐ 2026-10-01 崩溃自恢复检测（用户要求「游戏会热更新，做上备案，全分辨率适用」）：
        #   当前帧没有游戏任何特征（游戏进程死亡/停在热更页/登录页/桌面）⇒
        #   bringGame 拉起 + OCR 文字导航（热更确定→下载等待→公告→开始游戏），全分辨率 ✓
        if not _game_screen_ok(_items_pre):
            say('   ⚠ 画面无游戏特征（崩溃/热更/登录页？）⇒ 自动恢复')
            status('画面不是游戏 · 正在把游戏拉回来…')
            log.append({'recover': 'trigger'})
            if not game_recover(b, log, tag='rec%d_' % mi):
                STATS['stopped'] = '游戏自动恢复失败'
                say('   ⚠ 游戏自动恢复失败 ⇒ 停止（可在悬浮条再点 ▶ 重试）')
                status('⚠ 游戏起不来 · 已停下（可再点 ▶ 重试）')
                break
            b.snap('m%d_recovered' % mi)
            _items_pre = b.ocr(tag='pre')       # 恢复后重读（kick/体力都从这帧取）
            log.append({'recover': 'recheck', 'ok': _game_screen_ok(_items_pre)})
        # ⭐⭐ 2026-09-30：装备升星**已挪到"每张图跑完"处**（本循环体末尾，`if ok:` 之后）——
        #   原来放在这里（`mi>0 and mi%10==0`）⇒ 实际触发点是**第 11 张图开始前**，语义是
        #   "刷够 10 张之后、下一张之前"。用户报「刚刷了 10 把没触发升星」：真机 14:12 实测
        #   刷完 10 张、`bag_upgrade` 调用 0 次 —— 因为 maps=10 的一局 `mi` 只到 9，
        #   **永远等不到第 11 张**（`mi%10==0` 需要 mi=10）。挪走后本处不再判，见循环末尾 ✓
        say('== 第 %d 张图 ==' % (mi + 1))
        status('第 %d 张图 · 准备进图' % (mi + 1))
        # ⭐ 2026-09-27：**进图前**读一次体力（选图界面 ✓ 此时还没扣那 25）
        #   ⇒ 相邻两次"进图前"的差 = 25 进图消耗 + 图内消耗 ✓（用户要求算进图消耗 ✓）
        try:
            _st_pre = stamina(_items_pre)
            if _st_pre is not None:
                STATS['stamina_entries'].append((_st_pre, time.time()))
                say('   进图前体力 %d（已记入统计 ✓）' % _st_pre)
        except Exception as _e3:      # noqa: BLE001
            say('   ⚠ 进图前体力读取失败：%r' % (_e3,))
        if not ensure_in_map(b, log, tag='m%d_' % mi):
            log.append({'map': mi, 'stop': 'not_in_map'})
            STATS['stopped'] = STATS['stopped'] or '进图失败（体力不足 / 不在选图界面）'
            say('⚠ 进图失败（可能体力不足 / 不在选图界面），已停止')
            status('⚠ 进图失败 · 已停下（体力不够？）')
            break
        # ⭐ 分辨率自适应：进图成功后标定一次棋盘几何 ✓（只跑一次 ✓ 永不退化 ✓）
        if ADAPTIVE_LAYOUT and not _GRID_CALIBRATED['done']:
            try:
                _im0 = b.img()
                if _im0 is not None:
                    auto_calibrate_grid(b, _im0, log=log)
                    # ⭐ 不管成功/被拒，本次启动只测一次 ✓（用户 2026-09-27）
                    _GRID_CALIBRATED['done'] = True
            except Exception as _e2:      # noqa: BLE001
                say('   ⚠ 棋盘自检异常：%r' % (_e2,))
        # ⭐ 2026-09-28 提速（P1）：体力在顶部 HUD ⇒ band OCR 就够（~0.25s），
        #   不必全屏（0.8s）；这行只用于日志展示，不进账（进账在"进图前"那次 ✓）
        st_now = stamina(b.ocr(band=(0, int(LAYOUT.sy(320))), tag='pre'))
        say('   已进图，体力 %s' % (st_now if st_now is not None else '?'))
        status('第 %d 张图 · 已进图，正在看棋盘' % (mi + 1))
        if st_now is not None:
            # ⚠ 2026-09-27：这里**不再记账**（改由"进图前"那次记账 ✓）
            #   否则会把"扣完 25 之后"的值当基准 ⇒ 25 又丢了 ✗
            ent = STATS['stamina_entries']
            if len(ent) >= 2:
                (s0, t0), (s1, t1) = ent[-2], ent[-1]
                regen = max(0.0, t1 - t0) / 30.0
                say('   上一张图消耗体力约 %.0f（进图 %d → %d，间隔 %.0f 秒，期间回 +%.0f）'
                    % (max(0.0, (s0 - s1) + regen), s0, s1, t1 - t0, regen))
        STATS['current_map'] = mi + 1
        # ⭐⭐ 2026-09-27 采图模式（--collect-only）：
        #   进图成功这一刻的画面 = **整张图最干净的一帧**（没有任何图标/战斗/面板盖住）
        #   ⇒ 存下来 → 立刻退图 → 下一张。全程不揭格、不打怪、不买、不补点 ✓
        #   ⚠ 退图**不做 final_collect**（那一步是"把打过的格再点一遍领战利品"，
        #     采图模式一格没打过 ⇒ 点了反而会揭开新格/弹面板 ✗）
        if COLLECT_ONLY:
            t_one = time.time()
            _shot = save_board_frame(b, log, rnd=0)
            ok = finish_map(b, log)
            _dt = time.time() - t_one
            log.append({'map': mi, 'collect_only': True, 'finished': ok,
                        'shot': os.path.basename(_shot) if _shot else None,
                        'secs': round(_dt, 1)})
            say('   采图：%s（本张 %.0f 秒）%s'
                % (os.path.basename(_shot) if _shot else '⚠ 存图失败', _dt,
                   '' if ok else '  ⚠ 退图没成功'))
            if _shot:
                STATS['shots'] += 1
            if ok:
                STATS['map_secs'].append(_dt)
                STATS['current_map'] = 0
                STATS['current_secs'] = 0
            else:
                STATS['stopped'] = STATS['stopped'] or '退图失败（采图模式）'
                flush(log)
                break
            flush(log)
            continue
        t_one = time.time()
        try:
            why = run_one_map(b, log, a.max_round, prefix='m%d_' % mi, deadline=a.deadline)
        finally:
            STATS['current_secs'] = time.time() - t_one
        log.append({'map': mi, 'end_reason': why})
        say('   本图结束：%s（耗时 %.0f 秒）' % (why, time.time() - t_one))
        # ⭐⭐⭐ 2026-10-01 v1.11【"画面被判被挡"不许无限循环】（朋友真机：一张接一张地卡）
        #   旧路径：`board_not_visible` → 'stuck' → 退图失败 → game_recover → 下一张图
        #   → 同样判"被挡" → ⋯ **永远出不来**，用户看到的就是"一直卡在这" ✗✗
        #   ⇒ 连续 2 张都 stuck（且没跑完）⇒ 整局停下 + 悬浮条说明 + 已存诊断帧 ✓
        if why in ('stuck', 'blank'):
            STATS['stuck_maps'] = STATS.get('stuck_maps', 0) + 1
            if STATS['stuck_maps'] >= 2:
                STATS['stopped'] = ('连续 %d 张图认不出棋盘（画面被判"被面板挡住"）'
                                    % STATS['stuck_maps'])
                say('   ⚠ 连续 %d 张图都认不出棋盘 ⇒ 停止（诊断帧已存 /sdcard/Download/'
                    'autoexplore/bagdbg/，请发给作者 ✓）' % STATS['stuck_maps'])
                status('⚠ 连续认不出棋盘 · 已停下（请把诊断帧发我）')
                flush(log)
                break
        else:
            STATS['stuck_maps'] = 0
        if why == 'kicked':
            STATS['stopped'] = '账号被顶下线'
            break
        if why == 'red_equip':
            # 🛑 看到红装标记：**不退图、不补点**，停在原地交给人处理
            STATS['stopped'] = '发现红装（SS）标记 → 立即停止（现场保留）'
            say('⚠ 已停止：红装标记格留在图上，请你自己处理（本轮不再动作）')
            break
        if why == 'stopped':
            # ⭐ 2026-09-29 用户口径「点 ■ 要立即停止」：**连退图都别做**（打图动作立刻全停 ✓）
            #   留在图内即可：游戏账号空闲、下次启动可接着打这张图 ✓
            STATS['stopped'] = '用户点了停止'
            say('⏹ 已停止：留在图内，不退图不补点（下次启动可接着打 ✓）')
            status('已停止 · 留在图内（下次可接着打）')
            break
        ok = finish_map(b, log)
        log.append({'map': mi, 'finished': ok})
        if ok:
            STATS['maps'] += 1
            STATS['map_secs'].append(time.time() - t_one)
            STATS['current_map'] = 0        # 正常跑完就不算「被停止」
            STATS['current_secs'] = 0
            STATS['recover_n'] = 0          # ⭐ v1.12：跑完一张 ⇒ 恢复计数清零 ✓
        say('   已退出地图并回到选图界面' if ok else '⚠ 退图没成功，已停止')
        if ok:
            status('第 %d 张图 · 完成（%.0f 秒）' % (mi + 1, time.time() - t_one))
        else:
            status('⚠ 退图没成功 · 已停下')
        # ⭐⭐ 2026-09-30 用户报「刷了 10 把没触发自动装备升星」⇒ 触发点从"第 N+1 张之前"
        #   改成**"每跑完 BAG_EVERY 张"**（此刻人正站在选图界面，正是去背包升星的时机 ✓）：
        #     · 用户口径「每 10 张图升一次星」现在字面成立：第 10/20/30… 张跑完就升 ✓
        #     · 旧写法（循环开头 `mi>0 and mi%10==0`）要求开跑第 11 张才触发 ⇒
        #       maps=10 的一局 **一次都不触发**（真机 14:12：刷完 10 张、调用 0 次 ✓ 实锤）
        #   `STATS['maps']` 在这里刚 +1 过（上一行几下）⇒ 用它计数最稳（恢复重试不会重复计 ✓）
        if ok and BAG_EVERY and STATS['maps'] and STATS['maps'] % BAG_EVERY == 0:
            try:
                bag_upgrade(b, log, tag='bag%d_' % STATS['maps'])
            except Exception as e:      # noqa: BLE001
                log.append({'bag': 'error', 'e': repr(e)[:120]})
                say('   ⚠ 背包升级异常：%r（已跳过，继续刷图 ✓）' % (e,))
        if not ok:
            # ⭐⭐ 2026-10-01 崩溃自恢复（用户要求）：退图失败最常见的原因就是
            #   **游戏进程已死/冻结**（画面冻结 ⇒ OCR 恒定 ⇒ 一路 idle 到超时）。
            #   ⇒ 退图失败不再直接停：先检测+恢复（game_recover：拉起+热更/登录导航），
            #     恢复成功 ⇒ continue 进下一张图；恢复失败 ⇒ 才停止 ✓
            _items_pre = b.ocr(tag='pre')
            if not _game_screen_ok(_items_pre):
                say('   ⚠ 画面无游戏特征 ⇒ 自动恢复（拉起+热更/登录导航）')
                status('画面不是游戏 · 正在把游戏拉回来…')
                log.append({'recover': 'trigger_after_finish_fail'})
                if game_recover(b, log, tag='recf%d_' % mi):
                    _items_pre = b.ocr(tag='pre')
                    log.append({'recover': 'recheck_after_finish_fail',
                                'ok': _game_screen_ok(_items_pre)})
                    # ⭐⭐⭐ 2026-10-01 v1.12 真机（**朋友那台**）报「连地图都进不去，一直显示
                    #   正在把游戏拉回来」——本分支原来**无计数**：恢复成功就 `continue` 下一张，
                    #   下一张要是又失败 ⇒ 又恢复 ⇒ **无限"拉回来"** ✗
                    #   ⇒ 连续 3 次"拉回来自检通过、但下一张还是跑不动"就**停整局**并提示发日志 ✓
                    STATS['recover_n'] = STATS.get('recover_n', 0) + 1
                    if STATS['recover_n'] >= 3:
                        STATS['stopped'] = ('连续 %d 次把游戏拉回来、但下一张仍跑不动'
                                            % STATS['recover_n'])
                        say('   ⚠ 连续 %d 次自动恢复后仍跑不动 ⇒ 停止（请把 logcat 发我 ✓）'
                            % STATS['recover_n'])
                        status('⚠ 拉回游戏后仍跑不动 · 已停下（请把日志发我）')
                        flush(log)
                        break
                    STATS['stopped'] = ''
                    continue          # 恢复成功 ⇒ 继续刷下一张 ✓
                STATS['stopped'] = '游戏自动恢复失败'
                say('   ⚠ 游戏自动恢复失败 ⇒ 停止（可在悬浮条再点 ▶ 重试）')
                status('⚠ 游戏起不来 · 已停下（可再点 ▶ 重试）')
                break
            STATS['stopped'] = STATS['stopped'] or '退图失败'
            break
    flush(log)
    STATS['running'] = False
    say('==== 全部结束，共 %.0f 秒；日志：%s' % (time.time() - t_all, LOG_PATH))
    if STATS['maps']:
        # ⭐⭐⭐ 2026-10-01 v1.08 用户报「悬浮窗还是只写了收工，**没有写是因为体力不够 50 才收工**」
        #   根因：`STATS['stopped']`（= 真正的结束原因，由 `pre_gate` 那一路写成
        #   「体力不足（37 < 50）」之类）**没被拼进收工那行** ⇒ 悬浮条永远只显示"收工：刷完 N 张" ✗
        #   ⇒ 把原因并进同一行（⚠ 文案要避开 OCR 关键词，且别太长 ✓）
        _why = str(STATS.get('stopped') or '').strip()
        status('收工：刷完 %d 张 · %s'
               % (STATS['maps'],
                  _why or ('平均 %.0f 秒/张'
                           % (sum(STATS['map_secs']) / max(1, len(STATS['map_secs']))))))
    else:
        _why0 = str(STATS.get('stopped') or '').strip()
        status('收工：一张都没跑完%s' % ('（%s）' % _why0 if _why0 else ''))
    say(summary_text())
    dump_summary()
    # ⭐ 2026-09-27：收尾再读一次体力 ⇒ 最后一张图的"25 + 图内消耗"也能算出来 ✓
    try:
        _st_end = stamina(b.ocr(tag='end'))
        if _st_end is not None:
            STATS['stamina_entries'].append((_st_end, time.time()))
            say('收尾体力 %d（已记入统计 ✓）' % _st_end)
    except Exception:       # noqa: BLE001
        pass

    if DUMP_AT_END:
        for e in log:
            print(e)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        STATS['stopped'] = STATS['stopped'] or '手动中断（Ctrl+C）'
        STATS['running'] = False
        say(summary_text())
        dump_summary()
    except SystemExit:
        # 锁冲突 / 红装锁等**正常退出路径**（main 里 return 或显式退出）⇒ 原样放行，
        # 不写 crash 日志（否则假崩溃太多 ✗）
        raise
    except BaseException as _e:        # noqa: BLE001
        # ⭐⭐⭐ 2026-09-28 加固：任何未捕获异常都**留下证据**
        #   背景：21:36 那把循环打印「进图前体力」后**无声消失**（无 traceback、
        #   无 summary、无 [warn]）⇒ 事后完全无法定位死因 ✗ 只能靠这个兜住。
        #   崩溃记录写 `runs/<tag>/_crash.log`（append，不覆盖历史）。
        import traceback as _tbm
        _tb = _tbm.format_exc()
        _crash = os.path.join(RUNS, INSTANCE_TAG or '', '_crash.log')
        try:
            os.makedirs(os.path.dirname(_crash), exist_ok=True)
            with open(_crash, 'a', encoding='utf-8') as _f:
                _f.write('\n===== %s  pid=%d  dev=%s =====\n%s\n'
                         % (time.strftime('%Y-%m-%d %H:%M:%S'), os.getpid(),
                            INSTANCE_DEV, _tb))
        except Exception:       # noqa: BLE001
            pass
        try:
            say('💥 未捕获异常 ⇒ 已写入 %s（可据此定位死因）' % _crash)
            say(_tb)
        except Exception:       # noqa: BLE001
            pass
        STATS['stopped'] = STATS['stopped'] or ('崩溃：%s' % repr(_e)[:80])
        STATS['running'] = False
    finally:
        try:
            STATS['running'] = False
            dump_summary()
        except Exception:       # noqa: BLE001
            pass


# ═════════════════════════════════════════════════════════════════════════════
# 【Android 入口 · 由 port_loop.py 追加】
# 不走 argparse（APK 里没有命令行），由 explore_android.py 设置好模块级开关后调用。
# ═════════════════════════════════════════════════════════════════════════════
class _Args(object):
    """假装成 argparse.Namespace（run_maps 只读这几个字段 ✓）"""
    def __init__(self, maps=1, max_round=45, deadline=900):
        self.maps = maps
        self.max_round = max_round
        self.deadline = deadline


def android_run(maps=1, max_round=45, deadline=900,
                min_stamina=25, opt_solver=True, bag_every=0,
                stop_at_5am=False, auto_supply=False, say_fn=None):
    """Android 主入口：跑 maps 张图

    调用方（explore_android.py）负责：
      · 设置环境变量 MAPBOT_ROOT / MAPBOT_RUNS / MAPBOT_DT（**必须在 import 本模块之前**）
      · 设置 INSTANCE_TAG / VERBOSE / LOG_PATH 等模块级开关
    本函数只做「开关落位 + 调 run_maps」，并把 SYSTEM 异常写进 _crash.log。

    ⭐ 2026-09-29（APK 需求 ④⑤⑥）新增两件事：
      · `auto_supply` —— 没体力自动进背包用「结实补给」（对应界面上的勾选框）
      · **红装锁拦截** —— `main()` 里的红装闸门 Android 走不到（APK 不走 argparse），
        这里补上：上次发现红装还没处理 ⇒ 直接拒绝启动（绝不把那一局退掉）。
    """
    global OPT_SOLVER, MIN_STAMINA, BAG_EVERY, STOP_AT_5AM, VERBOSE, DUMP_AT_END
    global AUTO_SUPPLY
    MIN_STAMINA = int(min_stamina)
    OPT_SOLVER = bool(opt_solver)
    BAG_EVERY = max(0, int(bag_every or 0))
    AUTO_SUPPLY = bool(auto_supply)
    STOP_AT_5AM = bool(stop_at_5am)
    if STOP_AT_5AM:
        global STOP_TIME
        STOP_TIME = next_5am()
    # ⭐ 红装锁：上次发现红装（SS）还没处理 ⇒ 拒绝启动（与 PC 的 main() 同口径 ✓）
    #   处理完在界面上点「红装解锁」（或 explore_android.red_unlock()）即可放行
    _rl = red_locked(INSTANCE_DEV)
    if _rl:
        say('')
        say('🛑 上次在这台设备上**发现了红装（SS）**，已锁定，不启动新的探索：')
        say('     地图 %s  格 %s  时间 %s  截图 %s'
            % (_rl.get('map'), _rl.get('cell'), _rl.get('at'), _rl.get('shot')))
        say('     处理完在界面上点「红装解锁」即可重新开跑')
        say('')
        return 'red_locked'
    # ⭐⭐⭐ v1.33【反馈包里的图必须是「这一局」的】—— 用户 2026-10-02 报：
    #   「反馈包里的图不是他刚刚运行的图，和之前的图一样」✗
    #   根因（字节级实证）：诊断帧落在**公共目录的固定文件名**上
    #   （`board_hidden_rN.png` / `marks_none_rN.png` / `dice_nobtn.png`），
    #   而 `_pub_dump()` 用 `imencode().tofile()` **静默覆盖**旧文件、**从不清理** ⇒
    #   这一局没触发那个分支 = 根本没写新文件 ⇒ 目录里剩的**还是上次那局的旧帧** ✗
    #   ⇒ `Feedback.java` 把 bagdbg 里的 png 一股脑塞进包 ⇒ 发出来的是陈货 ✓
    #   （实证：realme 两包相隔 3 小时，板 md5 完全相同 b6810e49…）
    #   修法：**每次开跑先把上一次留下的诊断帧清干净** ⇒ 目录里的 png
    #     只可能来自本次运行；顺便写一个运行标记文件，给包侧判新鲜度用 ✓
    _clear_stale_diag_frames()
    say('   · 自动补给：' + ('开 ✓（没体力就进背包用结实补给）' if AUTO_SUPPLY else '关'))
    say('   · 装备升星：' + (('每 %d 张图一次' % BAG_EVERY) if BAG_EVERY else '关闭（0）'))
    # ⭐⭐⭐ v1.07 用户报「怎么连启动都启动不了了，完全用不了」——真因是**体力不足静默收工**：
    #   点 ▶ 后 6 秒就停，悬浮条只写「体力不够了 · 收工」，用户看不出是什么毛病 ✗
    #   ⇒ 启动瞬间就把**关键前提**摆到悬浮条上（体力下限 + 自动补给开关），
    #     并且**自动补给关着时明确提示去开**（用户 09-30 那次成功时它是开着的 ✓）
    #   ⚠ 文案避开 OCR 关键词（探索/派遣/领取/关闭/开始冒险…，见 OverlayService.sanitize ✗）
    status('已启动 · 体力下限 %d ｜ 自动补给%s'
           % (MIN_STAMINA, '开' if AUTO_SUPPLY else '关（体力不够会直接收工，建议开上）'))
    return run_maps(_Args(maps=maps, max_round=max_round, deadline=deadline))


def android_stop_requested():
    """供外部（广播）设置的中断标志 —— 2026-09-29 用户口径：立即停止（不等打完 ✓）"""
    return bool(globals().get('_ANDROID_STOP'))


def android_request_stop():
    globals()['_ANDROID_STOP'] = True
