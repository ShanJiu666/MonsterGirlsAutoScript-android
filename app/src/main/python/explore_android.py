# -*- coding: utf-8 -*-
"""explore_android.py · APK 内的探索入口

职责边界
--------
* **本文件只做"装配"**：环境变量 → 进程内开关 → 调 `explore_loop.android_run()`
* 真正的状态机全在移植过来的 `explore_loop.py` 里（PC 端 4400 行、踩了几十轮真机坑）

⚠ 关键次序：**必须先设环境变量，再 import 任何 mapbot 模块**
  （`spots/mapbot/explore_loop` 在**模块级**就据此算 ROOT / RUNS / DATATABLE）
  ⇒ 所以所有 import 都写在函数里（延迟导入 ✓），模块顶层只有标准库。

线程模型：广播 `cmd=explore` 会 `start()` 一个后台线程（`onReceive` 在主线程，
直接跑会 ANR）；`cmd=stop` 置 `_ANDROID_STOP`（`explore_loop.past_stop_time()` 每张图
开头查一次 ⇒ **打完手上这张图**才收工，不会留半张图 ✓）。
"""
import os
import sys
import threading
import time

_STATE = {
    'running': False,
    'stop': False,
    'thread': None,
    'started_at': 0.0,
    'last': '',
    'result': '',
    'error': '',
}
_LOCK = threading.Lock()
_BOOTED = {'env': False, 'root': '', 'runs': ''}


# ───────────────────────────── 引导 ─────────────────────────────

def _bootstrap():
    """设环境变量（幂等）。必须在 import explore_loop/mapbot 之前调用 ✓"""
    if _BOOTED['env']:
        return
    from java import jclass
    dev = jclass('com.fantasy.autoexplore.DeviceApi')
    # ⭐ packRoot() 触发首启解包（assets/mapbot_pack → filesDir/mapbot_pack，≈9MB）
    root = str(dev.packRoot() or '')
    runs = str(dev.runsRoot() or '')
    os.environ['MAPBOT_ANDROID'] = '1'
    os.environ['MAPBOT_ROOT'] = root
    os.environ['MAPBOT_RUNS'] = runs
    os.environ['MAPBOT_DT'] = os.path.join(root, 'server_datatable.json')
    os.environ.setdefault('MAPBOT_TPL_FRAMES', '3')     # 包里只有前 3 帧，保持一致
    _BOOTED.update(env=True, root=root, runs=runs)
    _install_log_tee()


def _install_log_tee():
    """把 print 同时送去 Kotlin 侧日志（`adb logcat -s AutoExplore` 可见 ✓）"""
    if getattr(sys, '_mapbot_tee', False):
        return

    from java import jclass
    dev = jclass('com.fantasy.autoexplore.DeviceApi')

    class _Tee(object):
        def __init__(self, stream):
            self._s = stream
            self._buf = ''

        def write(self, s):
            try:
                self._s.write(s)
            except Exception:       # noqa: BLE001
                pass
            self._buf += s
            while '\n' in self._buf:
                ln, self._buf = self._buf.split('\n', 1)
                if ln.strip():
                    try:
                        dev.log(ln[:1200])
                    except Exception:   # noqa: BLE001
                        pass

        def flush(self):
            try:
                self._s.flush()
            except Exception:       # noqa: BLE001
                pass

        def isatty(self):
            return False

    sys.stdout = _Tee(sys.__stdout__)
    sys.stderr = _Tee(sys.__stderr__)
    sys._mapbot_tee = True


def info():
    """当前环境快照（自检/诊断用）"""
    _bootstrap()
    import mapbot as _mb
    return {
        'root': _BOOTED['root'],
        'runs': _BOOTED['runs'],
        'dt': _mb.DT,
        'dt_exists': os.path.exists(_mb.DT),
        'tpl': _mb.TPL,
        'tpl_exists': os.path.isdir(_mb.TPL),
        'unit_codes': sorted(os.listdir(os.path.join(_mb.TPL, 'unit'))) if os.path.isdir(os.path.join(_mb.TPL, 'unit')) else [],
        'save_first': os.environ.get('MAPBOT_SAVE_FIRST', '1') != '0',
    }


# ───────────────────────────── 自检 ─────────────────────────────

def selftest(with_board=True):
    """端上全套自检（**不消耗体力**）：资源 → OCR → 截图 → 地块分类 → 规划器

    这是"能不能在手机上自己推图"的最小可信验证：只要 `board` 段能认出格子，
    说明 **模板包 + 数据表 + cv2 + 分类器**整条链在端侧是通的。
    """
    _bootstrap()
    out = []
    out.append('===== Android mapbot selftest =====')
    t0 = time.time()

    # ① 资源
    try:
        i = info()
        out.append('[1] 资源  root=%s' % i['root'])
        out.append('         datatable=%s (%s)' % (i['dt_exists'], os.path.basename(i['dt'])))
        out.append('         templates/unit 地图码 %d 个 %s' % (len(i['unit_codes']), i['unit_codes'][:6]))
        out.append('         MAPBOT_TPL_FRAMES=%s' % os.environ.get('MAPBOT_TPL_FRAMES'))
    except Exception as e:      # noqa: BLE001
        out.append('[1] 资源 ✗ %r' % (e,))
        return '\n'.join(out)

    # ② import 链（逻辑层 + 求解层）
    try:
        t = time.time()
        import layout, targets_cfg, spots, marks, badge, buypanels, grid_detect  # noqa: F401
        import mapgen, mapsim, mapsolve, strategy                                # noqa: F401
        out.append('[2] import 12 个逻辑模块 ✓ %.2fs' % (time.time() - t))
    except Exception as e:      # noqa: BLE001
        import traceback
        out.append('[2] import ✗ %r' % (e,))
        out.append(traceback.format_exc()[-800:])
        return '\n'.join(out)

    # ③ 设备通道
    from java import jclass
    dev = jclass('com.fantasy.autoexplore.DeviceApi')
    out.append('[3] 截图=%s 点击(无障碍)=%s' % (dev.hasFrame(), dev.touchReady()))
    if not dev.hasFrame():
        out.append('    ⚠ 没有帧 ⇒ 先在界面上点「① 请求截图权限」')
        return '\n'.join(out)

    # ④ 截图 → ndarray
    import cv2
    import numpy as np
    t = time.time()
    png = dev.grabRefPng()
    img = cv2.imdecode(np.frombuffer(bytes(png), dtype=np.uint8), cv2.IMREAD_COLOR)
    out.append('[4] 截图 %dx%d ✓ %.0fms' % (img.shape[1], img.shape[0], (time.time() - t) * 1000))

    # ⑤ OCR
    try:
        t = time.time()
        items = __import__('json').loads(dev.ocrJson(0.5) or '[]')
        out.append('[5] OCR %d 条 ✓ %.0fms  样例=%s' % (
            len(items), (time.time() - t) * 1000,
            [it['text'] for it in items[:6]]))
    except Exception as e:      # noqa: BLE001
        out.append('[5] OCR ✗ %r' % (e,))

    # ⑥ 地块分类（**端侧能否自己看懂棋盘**的核心验证）
    # ⚠⚠ 只报"认出 N 格"是**不诚实的**：分类器对任何画面都会硬凑出 35 格（棋盘固定 7×5），
    #    **非棋盘画面**（选图/大厅/大厅面板）也会返回满满一格，只是 score 普遍偏低。
    #    ⇒ 必须同时报 **score 分布**，并用中位分给出"像不像棋盘"的判断。
    if with_board:
        try:
            import spots as SP
            code = None
            for c in ('S00003', 'S00001', 'S00002'):
                d = os.path.join(SP.UNIT, c)
                if os.path.isdir(d) and os.listdir(d):
                    code = c
                    break
            t = time.time()
            bd = SP.Board(code)
            st = bd.state(img)
            dt = time.time() - t
            out.append('[6] 分类 %s 返回 %d 格 %.1fs' % (code, len(st), dt))
            if st:
                sc = sorted(float(v.get('score') or 0) for v in st.values())
                med = sc[len(sc) // 2]
                rev = sum(1 for v in st.values() if v.get('revealed'))
                names = {}
                for v in st.values():
                    if v.get('revealed') and v.get('name'):
                        names[v['name']] = names.get(v['name'], 0) + 1
                vr = '像棋盘 ✓' if med >= 0.80 else ('存疑 ⚠' if med >= 0.70 else '**不像棋盘 ✗**')
                out.append('        score min/中位/max = %.3f / %.3f / %.3f  ⇒ %s（已揭示 %d）'
                           % (sc[0], med, sc[-1], vr, rev))
                out.append('        识别：%s' % sorted(names.items(), key=lambda x: -x[1])[:8])
                if med < 0.70:
                    out.append('        ⚠ 中位分偏低 ⇒ 当前画面**不是探索棋盘**，'
                               '剩下的识别/规划结论都不作数（请先让游戏停在图上再测）')
        except Exception as e:      # noqa: BLE001
            import traceback
            out.append('[6] 分类 ✗ %r' % (e,))
            out.append(traceback.format_exc()[-800:])

    # ⑦ 规划器冒烟（造一张假观测盘，验证 EffPolicy 能在端上跑）
    try:
        import mapsim as _ms
        from strategy import EffPolicy
        t = time.time()
        cells = {}
        for r in range(1, 6):
            for c in range(1, 8):
                cells[(r, c)] = {'sid': 'S00003_100', 'name': '草地', 'marks': [],
                                 'revealed': r <= 2, 'ratio': 1.0 if r <= 2 else 0.65,
                                 'score': 0.9, 'anchor': (r, c)}
        sim = _ms.MapSim.from_observation(cells, __import__('spots').spot_rows())
        plan = EffPolicy().plan(sim, max_click=10, stop_when_no_target=False)
        out.append('[7] EffPolicy ✓ %d 步 %.0fms  前 3=%s' % (
            len(plan), (time.time() - t) * 1000, ['%d,%d' % p for p in plan[:3]]))
    except Exception as e:      # noqa: BLE001
        import traceback
        out.append('[7] EffPolicy ✗ %r' % (e,))
        out.append(traceback.format_exc()[-600:])

    out.append('===== 自检结束 %.1fs =====' % (time.time() - t0))
    txt = '\n'.join(out)
    print(txt, flush=True)
    return txt


# ───────────────────────────── 主流程 ─────────────────────────────

def classify_image(path, code='S00003', dump=True):
    """给**指定图片**跑棋盘分类（端侧）。

    ⭐ 用途：**零体力的端↔PC 等价性验证** —— 同一张 PNG 两端各跑一次，
       比 sid/name/score/anchor 是否逐格一致。
       比"在真实棋盘上测"强得多：输入完全相同，差异只可能来自平台（cv2 版本/字节序）。

    返回紧凑 JSON：[{r,c,sid,name,score,revealed,ratio,anchor}, …]
    """
    _bootstrap()
    import json as _json
    import cv2
    import spots as SP
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return _json.dumps({'error': 'imread failed', 'path': str(path)})
    h, w = img.shape[:2]
    if (w, h) != (1080, 1920):
        img = cv2.resize(img, (1080, 1920), interpolation=cv2.INTER_CUBIC)
    t = time.time()
    st = SP.Board(code).state(img)
    rows = []
    for (r, c), v in sorted(st.items()):
        rows.append({'r': r, 'c': c, 'sid': v.get('sid'), 'name': v.get('name'),
                     'score': round(float(v.get('score') or 0), 3),
                     'revealed': bool(v.get('revealed')),
                     'ratio': round(float(v.get('ratio') or 0), 3),
                     'anchor': list(v['anchor']) if v.get('anchor') else None})
    res = {'code': code, 'n': len(rows), 'secs': round(time.time() - t, 2), 'cells': rows}
    if dump:
        try:
            with open(os.path.join(_BOOTED['runs'], 'board_dev_%s.json' % code), 'w',
                      encoding='utf-8') as f:
                f.write(_json.dumps(res, ensure_ascii=False))
        except Exception:       # noqa: BLE001
            pass
    return _json.dumps(res, ensure_ascii=False)


def run(maps=1, max_round=45, deadline=900, min_stamina=25, tag='',
        opt_solver=True, bag_every=0, save_first=True, stop_at_5am=False,
        auto_supply=False):
    """同步跑（阻塞）。一般请用 `start()` 起后台线程 ✓

    ⚠ 参数顺序 = Java 侧 `PyBridge.call("start", …)` 的位置参数顺序，
       **只能往后追加**，不能在中间插（插了会让所有老调用点错位）。
    """
    _bootstrap()
    os.environ['MAPBOT_SAVE_FIRST'] = '1' if save_first else '0'
    import explore_loop as EL

    EL.VERBOSE = True
    EL.DUMP_AT_END = True
    EL.COLLECT_ONLY = False
    EL.SAVE_FIRST = bool(save_first)
    EL.INSTANCE_TAG = (tag or '').strip()
    EL.INSTANCE_DEV = 'android'
    EL.STOP_AT_5AM = bool(stop_at_5am)
    EL.__dict__['_ANDROID_STOP'] = False        # 清掉上一轮的停止标志
    if EL.INSTANCE_TAG:
        EL.WIN = os.path.join(EL.RUNS, EL.INSTANCE_TAG, 'loop')
        EL.LOG_PATH = os.path.join(EL.WIN, 'loop_log.json')
        EL.SUMMARY_PATH = os.path.join(EL.RUNS, EL.INSTANCE_TAG, 'last_summary.json')
        os.makedirs(EL.WIN, exist_ok=True)

    print('▶ Android 探索启动：maps=%d max_round=%d deadline=%ds tag=%r '
          'solver=%s bag_every=%d save_first=%s auto_supply=%s'
          % (maps, max_round, deadline, EL.INSTANCE_TAG, opt_solver, bag_every,
             save_first, auto_supply),
          flush=True)
    # ⭐ 2026-09-30：点 ▶ 后**立刻**给悬浮条一句反馈（后面第一句真行动要等切前台/读帧，
    #   中间可能好几秒；空着会让人以为按钮没生效）。走 status() = 唯一能上悬浮条的口子。
    EL.status('▶ 启动 · 正在连游戏')
    return EL.android_run(maps=maps, max_round=max_round, deadline=deadline,
                          min_stamina=min_stamina, opt_solver=opt_solver,
                          bag_every=bag_every, stop_at_5am=stop_at_5am,
                          auto_supply=auto_supply)


def _worker(kw):
    try:
        run(**kw)
        with _LOCK:
            _STATE['result'] = 'done'
    except BaseException as e:      # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        print('[explore] ✗ 异常：%r\n%s' % (e, tb[-1500:]), flush=True)
        with _LOCK:
            _STATE['error'] = repr(e)
            _STATE['result'] = 'error'
    finally:
        with _LOCK:
            _STATE['running'] = False
            _STATE['last'] = time.strftime('%H:%M:%S')


def start(maps=1, max_round=45, deadline=900, min_stamina=25, tag='',
          opt_solver=True, bag_every=0, save_first=True, stop_at_5am=False,
          auto_supply=False):
    """后台线程启动探索（幂等：已在跑就拒绝）

    ⚠ **签名必须与 `run()` 完全一致**（显式形参，不是 `**kw`）：
      Java 侧 `PyBridge.call("start", maps, 45, 900, …)` 走的是 **Chaquopy 的位置参数**，
      早期写成 `start(**kw)` ⇒ `TypeError: start() takes 0 positional arguments but 9 were given` ✗
      （悬浮条 / 广播 / 界面按钮三处都踩这个坑）

    形参顺序（= 位置参数顺序，只能往后追加）：
      maps, max_round, deadline, min_stamina, tag, opt_solver, bag_every,
      save_first, stop_at_5am, auto_supply
    """
    _bootstrap()
    kw = dict(maps=int(maps), max_round=int(max_round), deadline=int(deadline),
              min_stamina=int(min_stamina), tag=str(tag or ''),
              opt_solver=bool(opt_solver), bag_every=int(bag_every),
              save_first=bool(save_first), stop_at_5am=bool(stop_at_5am),
              auto_supply=bool(auto_supply))
    with _LOCK:
        if _STATE['running']:
            return 'already-running'
        _STATE.update(running=True, stop=False, started_at=time.time(),
                      result='', error='')
    t = threading.Thread(target=_worker, args=(kw,), name='mapbot-explore')
    t.daemon = True
    t.start()
    with _LOCK:
        _STATE['thread'] = t
    return 'started'


def stop():
    """请求停止（**立即停止**，不等这张图打完 —— 用户 2026-09-29 口径 ✓）

    ⭐ v0.25（2026-09-30）：**两道闸门同时拉**
      ① `_ANDROID_STOP = True`（explore_loop 三个检查点查这个 ⇒ 后续点击不再做）
      ② `DeviceApi.requestInterrupt()` ⇒ Java 端正在跑的 `waitChange` / `waitStable`
         循环下次 poll 时立刻 return false（≤80ms 之内）—— 修"点了 ■ 还在跑当前点击"的体感问题。
    """
    _bootstrap()
    try:
        import explore_loop as EL
        EL.android_request_stop()
    except Exception as e:      # noqa: BLE001
        return 'error: %r' % (e,)
    # ⭐ v0.25 同步打断 Java 端阻塞调用（让当前那一格"等连锁/等稳定"立刻退出，
    #   不再等 maxSec 才返回 —— 用户点 ■ 体感几乎瞬停）
    try:
        from java import jclass
        DeviceApi = jclass('com.fantasy.autoexplore.DeviceApi')
        DeviceApi.requestInterrupt()
    except Exception as e:      # noqa: BLE001
        # 没 Java 端 / Python 单跑（PC 端对拍）⇒ 静默忽略，不影响 _ANDROID_STOP 路径
        pass
    with _LOCK:
        _STATE['stop'] = True
    print('⏹ 已请求停止 —— 立刻停（不等这张图打完，Java wait 也立即中断）', flush=True)
    return 'stopping'


def status():
    with _LOCK:
        s = dict(_STATE)
    s.pop('thread', None)
    s['secs'] = round(time.time() - s['started_at'], 1) if s['started_at'] else 0
    # ⭐ 顺带报「红装锁」状态：悬浮条/界面据此提示"上次发现红装还没处理"
    try:
        s['red_locked'] = red_lock_info() is not None
    except Exception:       # noqa: BLE001
        s['red_locked'] = None
    return s


# ─────────────────────── 红装锁（需求 ⑥）───────────────────────
#
# PC 侧口径（explore_loop.red_lock_path / red_locked）：
#   发现红装（SS）⇒ 立刻停 + **绝不退图** + 写 `runs/red_equip_<port>.lock.json`；
#   **锁在就拒绝启动任何新运行**，直到人工处理完再解锁。
# APK 侧原来的缺口：`main()` 里有这道闸门，但 Android 走的是 `android_run()`（不经 argparse）
#   ⇒ 锁写了却没人看。已在本轮补进 `android_run`（见 tools/port_loop.py 的 ANDROID_MAIN）。

def red_lock_info():
    """-> 锁内容 dict（有锁）或 None（没锁）。DeviceApi 侧/界面用 ✓"""
    _bootstrap()
    import explore_loop as EL
    return EL.red_locked(EL.INSTANCE_DEV)


def red_lock():
    """锁详情（JSON 字符串；无锁返回 '{}'）—— 给广播/界面显示用"""
    _bootstrap()
    import json as _json
    try:
        return _json.dumps(red_lock_info() or {}, ensure_ascii=False)
    except Exception as e:      # noqa: BLE001
        return '{"error": %r}' % (e,)


def red_unlock():
    """「红装已处理·解锁」—— 删掉锁文件，之后就能重新开跑 ✓

    ⚠ 用 `os.remove`（真删文件）：**不能只把文件截断成空**，因为 `red_locked()` 读空文件时
      `json.load` 抛异常 ⇒ 返回 `{'bad': True}`（真值）⇒ 会被当成"还锁着" ✗。
      （沙箱的删除守卫只作用于 PC 侧工具调用，设备上的 Chaquopy 是干净 Python ✓）
    """
    _bootstrap()
    import explore_loop as EL
    p = EL.red_lock_path(EL.INSTANCE_DEV)
    try:
        if not os.path.exists(p):
            print('红装锁：本来就没有（无需解锁）', flush=True)
            return 'no-lock'
        os.remove(p)
        print('红装锁：已解锁 ⇒ %s' % p, flush=True)
        return 'unlocked'
    except Exception as e:      # noqa: BLE001
        print('红装锁：解锁失败 %r' % (e,), flush=True)
        return 'error: %r' % (e,)


# ─────────────────────── 运行统计（需求 ①）───────────────────────

def summary():
    """最近一次运行的「本次统计」文本（= PC 窗口下面那个统计框的内容）✓

    直接读 `runs/last_summary.json` 的 `text` 字段 —— 就是 `explore_loop.summary_text()`
    生成的那段（带 `════════ 本次统计 ════════` 分隔线），界面上原样显示即可。
    """
    _bootstrap()
    import json as _json
    import explore_loop as EL
    cands = [getattr(EL, 'SUMMARY_PATH', '') or '',
             os.path.join(_BOOTED['runs'], 'last_summary.json')]
    for p in cands:
        if not p:
            continue
        try:
            with open(p, encoding='utf-8') as f:
                t = (_json.load(f) or {}).get('text') or ''
            if t.strip():
                return t.strip()
        except Exception:       # noqa: BLE001
            continue
    return ''


def _cmd_run_snippet(code):
    """跑一段任意代码（调试用；结果打印到日志）"""
    _bootstrap()
    g = {'__name__': '__main__'}
    try:
        exec(compile(code, '<cmd>', 'exec'), g)
        return 'ok'
    except BaseException as e:      # noqa: BLE001
        import traceback
        print(traceback.format_exc()[-1500:], flush=True)
        return 'error: %r' % (e,)
