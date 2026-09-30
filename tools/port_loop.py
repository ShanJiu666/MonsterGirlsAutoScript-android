# -*- coding: utf-8 -*-
"""port_loop.py · 把 PC 端 `explore_loop.py` 整体移植到 Android

为什么整体移植而不是重写
------------------------
`explore_loop` 是 4400 行、踩了几十轮真机坑才稳定下来的状态机（见 MEMORY-detail §B）。
它对设备的全部依赖都走 `b`（Bot）—— 而 Android 版 `mapbot.Bot` 已经**同名同语义**实现了
截图/OCR/点击/等画面，所以大部分代码可以**一行不改地跑在手机上**。

审计结果（跨端调用面极小）：
    subprocess ×3（tasklist 查锁 PID、adb 回退键）  loopguard ×10（进程查重/设备锁）
    mapcollect ×3（内存通道，已由 COLLECT_REAL_MAPS=False 关掉）  ADB ×4

本脚本只做 5 处补丁（+1 处结构补丁，共 5 项 replace + 1 段追加）：
  ① 资源根：`SUPPLY_TPL` 原来是**相对路径**（依赖 CWD）⇒ 改成 MAPBOT_ROOT 绝对路径
  ② `back_to_map` 的 adb 回退键 ⇒ Android 走无障碍 `b.back()`
  ③ `guard_duplicates` / 设备锁：Android 单实例，直接放行（不查 tasklist）
  ④ `device_lock` 相关：同上，单实例无需文件锁
  ⑤ **`stop_hook`**：`stop_requested()` 在 Android 上读 `_ANDROID_STOP`
     （2026-10-01 补：这条是"点 ■ 立即停"的 Python 侧信号源 ✓）
  + 追加 `android_main()` —— 供 `explore_android.py` 直接驱动，不走 argparse

⚠ 与 `port_android.py` 的分工（别搞混，2026-10-01 踩过）：
  · 本脚本只管 **explore_loop.py** 一个文件
  · `port_android.py` 管**另外 11 个模块**（layout/spots/marks/badge/grid_detect/
    buypanels/mapgen/mapsim/mapsolve/strategy/targets_cfg）—— 它们是**独立副本**，
    改了 PC 侧必须重跑 `port_android.py`，否则手机上是旧代码 ✗
  · `mapbot.py`（Android 版）**不在任何生成器里**，是手写独立文件 ⇒ 改 PC 的 mapbot
    对手机**没有任何影响**（2026-10-01 就因此漏过一次停止中断 ✗）
"""
import os

SRC = r'D:\幻想少女公会\tools\mapbot\explore_loop.py'
DST = r'D:\幻想少女公会\android_autoexplore\app\src\main\python\explore_loop.py'

SHIM = '''
# ─────────────────────────────────────────────────────────────────────────────
# 【Android 适配补丁 · 由 android_autoexplore/tools/port_loop.py 注入，勿手改】
# Chaquopy 里 __file__ 指向 APK 内只读资源，模板/数据表在 filesDir/mapbot_pack
import os as _os

_MAPBOT_ROOT = _os.environ.get('MAPBOT_ROOT') or _os.path.dirname(_os.path.abspath(__file__))
_MAPBOT_ANDROID = _os.environ.get('MAPBOT_ANDROID') == '1'
# ─────────────────────────────────────────────────────────────────────────────
'''

ANDROID_MAIN = '''

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
'''

# ① SUPPLY 模板相对路径 → 绝对路径
P1_OLD = """SUPPLY_TPL = 'templates/items/supply_strong.png'
SUPPLY_MASK = 'templates/items/supply_strong_mask.png'"""
P1_NEW = """SUPPLY_TPL = os.path.join(_MAPBOT_ROOT, 'templates', 'items', 'supply_strong.png')
SUPPLY_MASK = os.path.join(_MAPBOT_ROOT, 'templates', 'items', 'supply_strong_mask.png')"""

# ② back_to_map 的 adb 回退键 → Android 用无障碍返回
P2_OLD = """        try:
            import subprocess
            # ⚠ 设备号取 Bot 自己的（原来误用了模块里不存在的 SERIAL ✗）
            dev = getattr(b, 'dev', None) or getattr(b, 'serial', None) or ''
            cmd = [ADB, '-s', dev] if dev else [ADB]
            subprocess.run(cmd + ['shell', 'input', 'keyevent', '4'],
                           capture_output=True, timeout=10, creationflags=CNW)
            time.sleep(1.0)
            log.append({'back_to_map': 'keyevent_back', 'try': k + 1, 'dev': dev})"""
P2_NEW = """        try:
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
                log.append({'back_to_map': 'keyevent_back', 'try': k + 1, 'dev': dev})"""

# ③ 进程查重/设备锁：Android 单实例，直接放行
P3_OLD = "def guard_duplicates(device, tag, force=False):"
P3_NEW = """def guard_duplicates(device, tag, force=False):
    # 【Android】单实例运行，没有 tasklist / 多开抢点击的问题 ⇒ 直接放行
    if _MAPBOT_ANDROID:
        return True"""

P4_OLD = "def acquire_device_lock(device):"
P4_NEW = """def acquire_device_lock(device):
    # 【Android】不需要设备锁（进程即实例）⇒ 返回哨兵，调用方只判 None
    if _MAPBOT_ANDROID:
        return 'android'"""

# ⑤ 外部中断：广播来的「停止」⇒ 立即停止（主路径走 stop_requested()，这里兜底）
P5_OLD = '''def past_stop_time():
    """到点了吗（到点就该收工）"""
    import datetime as _dt
    if not STOP_AT_5AM or STOP_TIME is None:
        return False
    return _dt.datetime.now() >= STOP_TIME'''
P5_NEW = '''def past_stop_time():
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
    return _dt.datetime.now() >= STOP_TIME'''


def main():
    txt = open(SRC, encoding='utf-8').read()
    if 'Android 适配补丁' in txt:
        raise SystemExit('源文件已被补丁过？请从 PC 源重新读取')

    # 插入 shim：放在第一个 `import os` 之前（shim 自带 import os as _os ✓）
    idx = txt.index('\nimport os\n')
    txt = txt[:idx] + '\n' + SHIM + txt[idx:]

    report = []
    for tag, old, new in (('①SUPPLY', P1_OLD, P1_NEW), ('②back_to_map', P2_OLD, P2_NEW),
                          ('③guard_duplicates', P3_OLD, P3_NEW), ('④device_lock', P4_OLD, P4_NEW),
                          ('⑤stop_hook', P5_OLD, P5_NEW)):
        if old not in txt:
            report.append(f'  ⚠ {tag} 未命中')
            continue
        txt = txt.replace(old, new, 1)
        report.append(f'  ✓ {tag}')

    txt = txt.rstrip('\n') + '\n' + ANDROID_MAIN
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, 'w', encoding='utf-8', newline='\n') as f:
        f.write(txt)

    print(f'移植 explore_loop.py → {DST}  ({len(txt)/1024:.0f} KB, {txt.count(chr(10))+1} 行)')
    print('\n'.join(report))


if __name__ == '__main__':
    main()
