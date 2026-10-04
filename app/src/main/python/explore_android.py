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

# ⚠ v1.20：端侧日志噪音收口（**只压这两类**，不用 blanket filterwarnings('ignore')）
#   ① ResourceWarning: unclosed file —— 根因已在 mapgen/spots 改成 `with` 修掉；
#      这里只做兜底（Chaquopy 的 C 层与第三方库仍可能触发），避免淹没真正的堆栈。
#   ② RuntimeWarning: overflow encountered in matmul / divide —— 来自 ONNX
#      数值计算（int32 归一化除法的标准警告），**不是**异常，PC 端也刷同样的。
#   ⚠ 绝不用 `filterwarnings('ignore')`：那会把真警告一起吞掉（错误教训：
#     「缺数据被当成通过」同族问题——把信号静音等于把问题静音）。
import warnings as _warnings
_warnings.filterwarnings('ignore', category=ResourceWarning)
_warnings.filterwarnings('ignore', message='.*matmul.*')
_warnings.filterwarnings('ignore', message='.*overflow encountered.*')
_warnings.filterwarnings('ignore', message='.*divide by zero.*')

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
    # ⭐ v1.41 热更：把"当前生效的补丁目录"记进环境变量（**只用于诊断/取证**）。
    #   ⚠ 真正"用补丁覆盖内置模块"不靠这里 —— 靠 Java 侧把它插到 sys.path[0]
    #     （PyBridge.injectHotPath）。等这里能读到它时，import 早就结束了。
    try:
        hot = str(dev.hotDir() or '')
    except Exception:       # noqa: BLE001
        hot = ''
    if hot:
        os.environ['MAPBOT_HOT'] = hot
    _BOOTED.update(env=True, root=root, runs=runs, hot=hot)
    _install_log_tee()
    # ⭐ v1.45f：**热更要让用户一眼看见**（用户 2026-10-04：「太不明显了吧」）
    #   挂在这里的理由：`_bootstrap()` 是所有 Python 入口的必经路（info/selftest/explore…）
    #   而且此刻 `_install_log_tee()` 已装好 ⇒ 横幅进得了 AppLog（应用内日志区）✓
    #   ⚠ 全包 try/except：播报**绝不允许**影响启动（它只是提示）
    try:
        announce_patch()
    except Exception:       # noqa: BLE001
        pass


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


def _diag_caps():
    """⭐⭐ v1.45e 诊断：**开关文件与定点模板，App 到底看不看得见**

    为什么要有这一段：真机 A/B 跑完发现「短路一次都没命中」（日志里
    `still_menu_tpl` / `back_to_menu_tpl` / `settle_tpl` 全 0 条），而**从外面完全看不出**
    是哪一环断的 —— ① flag 没被读到？② 模板没加载？③ 模板加载了但没匹配上？
    ⇒ 必须让 App 自己说。挂在 `pyinfo` 广播上，`adb broadcast … pyinfo` 一条命令就能看。

    ⚠ 全部包 try/except：诊断**绝不允许**把 pyinfo 弄崩（它是排障入口）。
    """
    out = {}
    try:
        import explore_loop as _EL
        try:
            _fd = _EL.flag_dir()
            out['flag_dir'] = _fd
            out['flag_dir_exists'] = os.path.isdir(_fd)
            try:
                out['flag_files'] = sorted(f for f in os.listdir(_fd)
                                           if f.endswith('.flag'))
            except Exception as _e:      # noqa: BLE001
                out['flag_files'] = 'ERR:%r' % (_e,)
            # ⭐ 关键：**每个候选目录，App 到底看得见什么**（决定 A/B 有没有生效）
            _lst = {}
            for _d in _EL.flag_dirs():
                try:
                    _lst[_d] = (sorted(os.listdir(_d))[:14] if os.path.isdir(_d)
                                else 'NO_DIR')
                except Exception as _e:  # noqa: BLE001
                    _lst[_d] = 'ERR:%r' % (_e,)
            out['flag_dir_listing'] = _lst
            out['flags_on'] = {n: _EL.flag_on(n)
                               for n in ('parallel', 'settle_tpl', 'menu_tpl')}
        except Exception as _e:          # noqa: BLE001
            out['flag_err'] = repr(_e)
    except Exception as _e:              # noqa: BLE001
        out['el_err'] = repr(_e)
    try:
        import fixed_ref as _FR
        _dirs = list(_FR.tpl_dirs())
        out['tpl_dirs'] = _dirs
        _cnt = {}
        for _d in _dirs:
            try:
                _cnt[_d] = len(os.listdir(_d)) if os.path.isdir(_d) else 'NO_DIR'
            except Exception as _e:      # noqa: BLE001
                _cnt[_d] = 'ERR:%r' % (_e,)
        out['tpl_dir_files'] = _cnt
        _names = ('settle_replay_btn.png', 'settle_close_btn.png', 'settle_skip_btn.png',
                  'enter_map_btn.png', 'quick_sweep_btn.png')
        out['tpl_loaded'] = {n: (_FR.load(n) is not None) for n in _names}
        # ⭐ 最关键的一条：模板在**当前这一帧**上的原始匹配分（不受阈值影响）
        try:
            _EL_mod = __import__('explore_loop')
            from java import jclass
            _png = jclass('com.fantasy.autoexplore.DeviceApi').grabRefPng()
            if _png:
                import cv2 as _cv
                import numpy as _np
                _arr = _cv.imdecode(_np.frombuffer(bytes(_png), dtype=_np.uint8),
                                    _cv.IMREAD_COLOR)
                _raw = {}
                _boxes = {}
                _boxes.update({k: (v, (140, 60)) for k, v in _EL_mod.MENU_TPL.items()})
                _boxes.update({k: (v, _EL_mod.SETTLE_TPL_HALF)
                               for k, v in _EL_mod.SETTLE_TPL.items()})
                for _n, (_c, (_hx, _hy)) in _boxes.items():
                    _g = _FR.find(_arr, _n, thr=0.0,
                                  region=(_c[0] - _hx, _c[1] - _hy,
                                          _c[0] + _hx, _c[1] + _hy))
                    _raw[_n] = (round(_g[2], 3) if _g else None)
                out['tpl_score_now'] = _raw
            else:
                out['tpl_score_now'] = '没有帧'
        except Exception as _e:          # noqa: BLE001
            out['tpl_score_now'] = 'ERR:%r' % (_e,)
    except Exception as _e:              # noqa: BLE001
        out['fxr_err'] = repr(_e)
    return out


def _try_toast(msg):
    """尽力弹一个 Android Toast（Chaquopy 直接调 Java API）-> True/False

    ⚠ 三处都可能失败，全部咽掉（**只是少一个提示，绝不允许影响主流程**）：
      ① 拿不到 Context：`DeviceApi.appCtx` 是 **private static**（Chaquopy 走 JNI
         通常能读到 private 成员，但不保证 —— 所以这一步是"尽力"）
      ② 主线程 Looper/Handler 不可用
      ③ 动态代理 Runnable 不被支持
    """
    try:
        from java import dynamic_proxy, jclass
        _dev = jclass('com.fantasy.autoexplore.DeviceApi')
        _ctx = _dev.appCtx
        if _ctx is None:
            return False
        _Handler = jclass('android.os.Handler')
        _Looper = jclass('android.os.Looper')
        _Toast = jclass('android.widget.Toast')
        _Runnable = jclass('java.lang.Runnable')

        class _Show(dynamic_proxy(_Runnable)):
            def run(self):
                _Toast.makeText(_ctx, msg, _Toast.LENGTH_LONG).show()

        _Handler(_Looper.getMainLooper()).post(_Show())
        return True
    except Exception:       # noqa: BLE001
        return False


# ⭐⭐⭐ v1.45f【热更必须让用户一眼看见】（用户 2026-10-04 原话：
#   「我点击检查更新后重启app了，这样是热更新好了吗？**太不明显了吧**，能不能弹窗口
#     让用户更容易看出更新过」）
#
# 以前的问题：补丁生效**只在 logcat/`update_status` 里能看到**，界面上毫无提示 ⇒
#   用户根本不知道自己更没更上（这次 A/B 就是因此白跑了一轮）。
# 现在：**补丁 id 一变**就在三个地方同时喊一声：
#   ① 应用内日志区（`print` 经 `_Tee` ⇒ `AppLog`）—— 打开 App 就看得见，还带边框
#   ② **悬浮条状态行**（`status()`）—— 跑图时它压在游戏上面，最显眼
#   ③ **尽力弹 Toast**（`_try_toast`）—— 真"弹出来"的效果
# ⚠ 只在 id 变了时播一次（记在 `runs/.patch_announced`），否则每次启动都刷屏 ✗
# ⚠ 纯 Python ⇒ **走热更就能发**，不用重装 71MB（Java 侧的真弹窗留给下一版整包）
def announce_patch(force=False):
    """补丁 id 变了就喊一声；返回播报文案或 ''"""
    try:
        from java import jclass
        _dev = jclass('com.fantasy.autoexplore.DeviceApi')
        _info = str(_dev.hotInfo() or '')
    except Exception:       # noqa: BLE001
        return ''
    # 从 `statusLine` 里抠 id：形如 `壳 v1.44(144) · 补丁=hot-144-b1b830a4(已确认) · dir=…`
    import re as _re
    m = _re.search(r'补丁=([A-Za-z0-9._\-]+)', _info)
    pid = m.group(1) if m else ''
    if not pid or pid in ('无', 'None'):
        return ''
    runs = _BOOTED.get('runs') or ''
    mark = os.path.join(runs, '.patch_announced') if runs else ''
    try:
        old = (open(mark, encoding='utf-8').read().strip() if mark else '')
    except Exception:       # noqa: BLE001
        old = ''
    if old == pid and not force:
        return ''
    msg = '已更新到 %s' % pid
    bar = '=' * 46
    banner = ('\n%s\n  ✅ 热更生效：%s\n     （看到这行说明补丁已经加载，不用再重启）\n%s'
              % (bar, pid, bar))
    try:
        print(banner, flush=True)          # ① 应用内日志 + logcat
    except Exception:       # noqa: BLE001
        pass
    try:
        import explore_loop as _EL
        _EL.status('✅ %s' % msg)           # ② 悬浮条状态行
        _EL.say(banner)
    except Exception:       # noqa: BLE001
        pass
    ok = _try_toast('MGAS %s' % msg)        # ③ 尽力弹 Toast
    try:
        print('[hot] 播报补丁 %s（Toast=%s）' % (pid, '成功' if ok else '不可用，已用悬浮条+日志代替'),
              flush=True)
    except Exception:       # noqa: BLE001
        pass
    try:
        if mark:
            os.makedirs(os.path.dirname(mark), exist_ok=True)
            with open(mark, 'w', encoding='utf-8') as f:
                f.write(pid)
    except Exception:       # noqa: BLE001
        pass
    return msg


def info():
    """当前环境快照（自检/诊断用）"""
    _bootstrap()
    import mapbot as _mb
    out = {
        'root': _BOOTED['root'],
        'runs': _BOOTED['runs'],
        'hot': _BOOTED.get('hot', ''),
        'dt': _mb.DT,
        'dt_exists': os.path.exists(_mb.DT),
        'tpl': _mb.TPL,
        'tpl_exists': os.path.isdir(_mb.TPL),
        'unit_codes': sorted(os.listdir(os.path.join(_mb.TPL, 'unit'))) if os.path.isdir(os.path.join(_mb.TPL, 'unit')) else [],
        'save_first': os.environ.get('MAPBOT_SAVE_FIRST', '1') != '0',
    }
    out.update(_diag_caps())
    return out


# ───────────────────────── v1.41 热更新 ─────────────────────────

def hot_selftest():
    """⭐⭐ v1.41 热更自检：**只做 import + 资源可见性**，不截图、不 OCR。

    为什么必须"真的 import 一遍"，而不是看看文件在不在：
      补丁坏掉的形态几乎全是**语法错 / 缺模块 / 版本不兼容**，这些只有 import 才暴露；
      而"文件在不在"永远为真 ⇒ 那种检查等于没有检查（本项目《错误教训》同族问题：
      把没验证过的东西当验证过）。

    跑通即证明：sys.path 上那份补丁（若有）确实能被 CPython 加载 ✓
    ⇒ Java 侧 `Updater.onPythonStarted` 据此决定「确认生效」还是「自动回滚」。

    ⚠ 约定：**绝不抛异常**（Java 侧只认返回值前缀）：
      成功 `'ok:...'` ／ 失败 `'err:<异常类型>: <信息>'`
    """
    try:
        _bootstrap()
        t0 = time.time()
        import mapbot as _mb               # noqa: F401
        import explore_loop as _el         # noqa: F401 ← 连锁 import 全部逻辑模块
        hot = os.environ.get('MAPBOT_HOT', '')
        return 'ok: %.2fs loop=%s tpl=%s dt=%s hot=%s' % (
            time.time() - t0,
            os.path.basename(str(getattr(_el, '__file__', '?'))),
            os.path.isdir(_mb.TPL), os.path.exists(_mb.DT),
            hot or '(内置)')
    except BaseException as e:             # noqa: BLE001
        return 'err:%s: %s' % (type(e).__name__, e)


def hot_reset_modules():
    """把**从热更目录加载的**模块从 sys.modules 里卸掉（回滚后必须调）。

    ⚠ 不卸的后果：补丁里 `mapbot` 加载成功、`explore_loop` 失败 ⇒ 回滚后 mapbot 仍是补丁那份，
      变成"一半补丁一半内置"的混血状态 —— 行为既不是补丁也不是内置，极难排查。

    返回：卸下的模块数
    """
    hot = os.environ.get('MAPBOT_HOT', '')
    n = 0
    if hot:
        pre = os.path.abspath(hot) + os.sep
        for name, mod in list(sys.modules.items()):
            f = getattr(mod, '__file__', None)
            if not f:
                continue
            try:
                if os.path.abspath(str(f)).startswith(pre):
                    del sys.modules[name]
                    n += 1
            except Exception:              # noqa: BLE001
                pass
    # 环境变量/缓存同清：它现在指向一个已经不存在（或已回滚）的目录，留着只会误导诊断
    os.environ.pop('MAPBOT_HOT', None)
    _BOOTED['hot'] = ''
    return n


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
        # ⭐ v1.45e 诊断：A/B 开关与定点模板（`pyinfo` 里也有，这里多行更好读）
        out.append('[1b] 开关目录 = %s（在=%s）' % (i.get('flag_dir'), i.get('flag_dir_exists')))
        out.append('         目录里的 flag = %s' % (i.get('flag_files'),))
        out.append('         各候选目录 App 看得见什么 = %s' % (i.get('flag_dir_listing'),))
        out.append('         开关值 = %s' % (i.get('flags_on'),))
        out.append('[1c] 模板目录 = %s' % (i.get('tpl_dirs'),))
        out.append('         各目录文件数 = %s' % (i.get('tpl_dir_files'),))
        out.append('         模板能加载 = %s' % (i.get('tpl_loaded'),))
        out.append('[1d] 当前帧模板**原始分** = %s' % (i.get('tpl_score_now'),))
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
