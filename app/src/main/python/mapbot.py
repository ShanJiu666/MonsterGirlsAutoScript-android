# -*- coding: utf-8 -*-
"""mapbot.py · **Android 版**（APK 内的 Bot 实现）

PC 版 `mapbot.Bot` 依赖 adb + airtest；这里换成设备本机通道：

    截图  MediaProjection（Kotlin CaptureService）  → DeviceApi.grabRefPng()
    点击  无障碍 dispatchGesture（Kotlin AutoTouchService） → DeviceApi.tapRef()
    OCR  端侧 ONNX（Kotlin OcrEngine）              → DeviceApi.ocrJson()

⭐ 对外接口与 PC 版**同名同语义**（snap/img/ocr/tap/swipe/wait_change/wait_stable/…），
   所以 mapbot 的逻辑层（explore_loop / spots / cells / marks / mapsim / mapsolve …）
   可以一行不改地跑在手机上 —— 只有跨端能力的模块（fastcap/memmap/loopguard）换成桩。

⚠ 坐标：设备侧一切坐标都是 **1080×1920 参考系**（与 PC 端一致），
   由 Kotlin 的 RefMapper 负责与真实分辨率互转，Python 侧看不到像素尺寸差异。
"""
import json
import os
import time

import cv2
import numpy as np

# ---- 与 PC 版同名的模块级常量（explore_loop 会 import） ----
ADB = None                      # Android 上不存在 adb
DEV = 'android'                 # 设备标识（占位）
CREATE_NO_WINDOW = 0            # Windows 专用（占位）
CNW = 0

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('MAPBOT_ROOT') or _HERE
TPL = os.path.join(ROOT, 'templates')
RUNS = os.environ.get('MAPBOT_RUNS') or os.path.join(_HERE, 'runs')
try:
    os.makedirs(RUNS, exist_ok=True)
except Exception:               # noqa: BLE001
    pass
DT = os.environ.get('MAPBOT_DT') or os.path.join(ROOT, 'server_datatable.json')
OCR_SCALE = 0.75                # 与 PC 同口径（端侧 OcrEngine 里也是 0.75）


def _api():
    """拿 Kotlin 侧 DeviceApi 类（Chaquopy Java 桥）"""
    from java import jclass
    return jclass('com.fantasy.autoexplore.DeviceApi')


_DLG_C = None

# ⭐ v0.61：band 真裁图的**最小高度**。低于它就别裁 —— det 的 limit_side_len=736
#   会把矮带放大（band 高 400 ⇒ 放大到 736 ⇒ det 面积 1.46M > 整帧 1.15M ⇒ 反而更慢）。
#   实测盈亏平衡点 ≈ Δy 505，取 520 留余量。见 Bot.ocr 的 docstring。
BAND_CROP_MIN = 520


def dlg_shift():
    """⭐ v0.31 方案 B：居中弹窗系 − 归一化帧 的 y 偏移 C（弹窗系 y = 帧内 y + C）。

    Java RefMapper.dialogShift() 按屏幕参数现算（真机 1280×2772 ⇒ 209、2400 屏 ⇒ 240）；
    9:16 屏 ⇒ 0（与 PC 一致）。PC 版 mapbot 里同名函数恒 0。
    """
    global _DLG_C
    if _DLG_C is None:
        try:
            from java import jclass
            _DLG_C = float(jclass('com.fantasy.autoexplore.RefMapper').dialogShift())
        except Exception:       # noqa: BLE001
            _DLG_C = 0.0
    return _DLG_C


def dlg_items(items):
    """归一化帧 OCR 条目 → 居中弹窗系（cy +C，其余原样）。C=0 时原列表直返（零开销）。

    ⚠ 只对**弹窗系 y ≥ ~509** 的内容严格成立（真机上 dlg 202~509 落在被 toRef 丢弃的
    弹性区，归一化帧里根本没有）—— 用于面板按钮 y 带筛选（650~860/820~1070 等）足够 ✓；
    要看 dlg<509 的内容（面板 X 关闭符）请用 `Bot.img_dlg()` 的弹窗帧。
    """
    c = dlg_shift()
    if not c or not items:
        return items
    out = []
    for it in items:
        d = dict(it)
        d['cy'] = it['cy'] + c
        out.append(d)
    return out


class _AndroidOcr(object):
    """端侧 OCR 引擎 —— 与 PC 的 `RapidOCR(...)` 同契约：`f(path) -> (items, secs)`

    items 元素形如 `[box, text, conf]`（PC 用 RapidOCR 的返回结构，buypanels 只读 [1]/[2]）。
    实现：图先缩到参考帧再贴黑底（端侧引擎只吃 1080×1920），然后交给同一个 ONNX 引擎
    —— 口径与全屏 OCR **完全一致**，不会出现"全屏认得、裁剪不认"的偏差 ✓
    """

    def __init__(self):
        self.api = _api()

    def __call__(self, path, *a, **kw):
        import time as _t
        t0 = _t.time()
        try:
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        except Exception:       # noqa: BLE001
            img = None
        if img is None:
            return (None, 0.0)
        h, w = img.shape[:2]
        if (w, h) != (1080, 1920):
            k = min(1080.0 / w, 1920.0 / h)
            nw, nh = max(1, int(round(w * k))), max(1, int(round(h * k)))
            interp = cv2.INTER_AREA if k < 1.0 else cv2.INTER_CUBIC
            img = cv2.resize(img, (nw, nh), interpolation=interp)
        canvas = np.zeros((1920, 1080, 3), dtype=np.uint8)
        canvas[:img.shape[0], :img.shape[1]] = img[:1920, :1080]
        ok, buf = cv2.imencode('.png', canvas)
        if not ok:
            return (None, _t.time() - t0)
        try:
            raw = self.api.ocrPng(buf.tobytes(), 0.0)
            items = json.loads(raw) if raw else []
        except Exception:       # noqa: BLE001
            items = []
        out = []
        for it in items:
            box = [[it['x0'], it['y0']], [it['x1'], it['y0']],
                   [it['x1'], it['y1']], [it['x0'], it['y1']]]
            out.append([box, it['text'], float(it['conf'])])
        return (out, _t.time() - t0)


_OCR_ENGINE = None


def _ocr():
    """OCR 引擎单例（与 PC 版同名同契约 ✓ buypanels 会 `from mapbot import _ocr`）"""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = _AndroidOcr()
    return _OCR_ENGINE


class Bot(object):
    """设备本机版 Bot：接口与 PC 版对齐"""

    # ⭐ v0.61：端侧 `ocr()` 走 `api.ocrJson`，**内部自己抓当前帧** ⇒ 调用方不必先 snap
    #   （PC 版 = False，因为它的 `ocr()` 用 `img()` 缓存的那一帧；buypanels 据此省一次 snap）
    ocr_grabs = True

    # 探索棋盘几何（1080×1920 参考系，与 PC mapbot.Bot 相同）
    GRID_X0 = 36.0
    GRID_Y0 = 1002.0
    GRID_CX = 144.0
    GRID_CY = 144.0
    COLS, ROWS = 7, 5

    BOARD_Y0, BOARD_Y1 = 1002, 1722      # 棋盘带（wait_change 的亮度参照）

    def __init__(self, log_prefix='loop', serial=None, tag=None, use_fast=True):
        self.dev = serial or DEV
        self.tag = tag or None
        self.runs = os.path.join(RUNS, self.tag) if self.tag else RUNS
        os.makedirs(self.runs, exist_ok=True)
        self.log_prefix = log_prefix
        self._seq = 0
        self._img_arr = None            # 当前帧（BGR ndarray）
        self._img_path = None
        self._last = None
        self.api = _api()
        self.fast_ok = bool(self.api.touchReady()) and bool(self.api.hasFrame())
        self.t = {'snap': 0.0, 'ocr': 0.0, 'wait': 0.0, 'wait_n': 0, 'tap': 0, 'ocr_n': 0,
                  'snap_n': 0, 'ocr_by': {}}     # ⭐ v0.61：与 PC 同口径的分账埋点
        # ⭐ v0.34：弹窗帧缓存（按帧戳），同一帧内多次 img_dlg() 只编码一次
        #   （close_x_panels / find_x / badge 常在同一轮里连着要弹窗帧 ⇒ 省几百 ms）
        self._dlg_cache = {'stamp': -1, 'arr': None}
        self.last_change = {'changed': None, 'dim': 1.0}
        self._last_items = []
        print('[bot] Android 通道：截屏=%s 点击=%s'
              % (self.api.hasFrame(), self.api.touchReady()))

    # ---------- 截图 ----------
    def snap(self, name=None, save=False):
        """取一帧（放内存，不落盘）；save=True 时才写 PNG（同 PC 的极速通道语义）"""
        self._seq += 1
        name = name or '%s_%04d' % (self.log_prefix, self._seq)
        p = os.path.join(self.runs, name + '.png')
        _t0 = time.time()
        png = self.api.grabRefPng()
        if png is None:
            self.fast_ok = False
            self.t['snap'] += time.time() - _t0
            self.t['snap_n'] += 1
            return None
        arr = cv2.imdecode(np.frombuffer(bytes(png), dtype=np.uint8), cv2.IMREAD_COLOR)
        self._img_arr = arr
        self._img_path = None
        self._last = p
        if save:
            cv2.imwrite(p, arr)
            self._img_path = p
        self.fast_ok = True
        self.t['snap'] += time.time() - _t0
        self.t['snap_n'] += 1
        return p

    def img(self):
        if self._img_arr is not None:
            return self._img_arr
        self.snap()
        return self._img_arr

    def img_dlg(self):
        """⭐ v0.31 方案 B：弹窗帧 ndarray（1080×1920，**弹窗系**坐标）。

        走 Kotlin grabDlgPng（原始帧按「锚设备中心」重投影，不丢弹性区）⇒
        面板 X 关闭符（dlg≈225）在归一化帧里被丢掉，这里能看到 ✓。
        ⭐ v0.34：按**帧戳缓存**（一次 PNG 编码 ≈ 150~300ms；同一帧内多个调用点复用）。
        PC 版没有这个方法（弹窗空间==参考系，用 img() 即可）。
        """
        try:
            stamp = int(self.api.frameStamp())
        except Exception:       # noqa: BLE001
            stamp = -1
        if stamp >= 0 and self._dlg_cache['stamp'] == stamp and self._dlg_cache['arr'] is not None:
            return self._dlg_cache['arr']
        png = self.api.grabDlgPng()
        if not png:
            return self._dlg_cache.get('arr')
        arr = cv2.imdecode(np.frombuffer(bytes(png), dtype=np.uint8), cv2.IMREAD_COLOR)
        if arr is not None and stamp >= 0:
            self._dlg_cache = {'stamp': stamp, 'arr': arr}
        return arr

    def ocr_dlg(self, min_conf=0.5, band=None, tag=None):
        """⭐ v0.34：**弹窗帧** OCR（坐标即弹窗系 == PC 参考系）。

        真机上所有面板标题（战斗事件/探索产出/偶遇强敌/旅行商人/…）都落在归一化帧
        丢弃的弹性区 ⇒ 归一化帧 OCR 看不见 ⇒ 认不出面板类型时补这一手（≈2s，只在
        "认不出"时才跑，见 explore_loop.dlg_ocr）。PC 版没有这个通道。
        """
        _t0 = time.time()
        raw = self.api.ocrDlgJson(float(min_conf))
        try:
            items = json.loads(raw) if raw else []
        except Exception:       # noqa: BLE001
            items = []
        if band:
            y0, y1 = int(band[0]), int(band[1])
            items = [it for it in items if y0 <= it['cy'] <= y1]
        self.t['ocr'] += time.time() - _t0
        self.t['ocr_n'] = self.t.get('ocr_n', 0) + 1
        if tag:                 # ⭐ v0.61：与 PC 同口径的分账（找 180s/图 到底花在哪个调用点）
            cur = self.t.setdefault('ocr_by', {}).get(tag, [0.0, 0])
            self.t['ocr_by'][tag] = [cur[0] + (time.time() - _t0), cur[1] + 1]
        return items

    def img_path(self):
        """PC 版兼容：给需要文件路径的调用方（如 spots 直接读盘）"""
        if self._img_path and os.path.exists(self._img_path):
            return self._img_path
        p = os.path.join(self.runs, '_cur.png')
        arr = self.img()
        if arr is not None:
            cv2.imwrite(p, arr)
            self._img_path = p
        return p

    # ---------- OCR ----------
    def ocr(self, min_conf=0.5, img=None, band=None, scale=None, tag=None):
        """返回 [{text,cx,cy,x0,y0,x1,y1,conf}]，坐标是 1080×1920 参考系

        ⭐ v0.61：`band` 现在是**真裁图**（走 `api.ocrBandJson`），不再"整帧识别后过滤"。
          为什么必须裁：端侧 rec 占了 OCR 总时间的 ~81%（累计 203.7s vs det 43.5s），
          而 rec 的成本 ∝ 框数 —— 裁掉上下的 HUD/导航条就少了一大批框。
          PC 实测同一份代码：整帧 0.75x 1.54s / 中段 band 0.79s（省 ~50%）。
          ⚠ 但 det 的 `limit_side_len=736 / limit_type=min` 会把**太矮**的 band 放大
            （band 高 400 ⇒ 放大到 736 ⇒ det 面积反而比整帧大）⇒ 只有
            `Δy >= BAND_CROP_MIN` 才裁，更矮的仍走整帧+过滤（口径不变）。
          ⚠ 裁图失败（返回空串）自动回退整帧路径，保证不会"整段认不出来"。
          `scale` 参数仅为接口兼容（端侧固定 0.75 倍口径）。
        """
        _t0 = time.time()
        if img is not None:
            # 调用方给了图（极少见）：落盘后走同一路（保证口径一致）
            p = os.path.join(self.runs, '_inline.png')
            cv2.imwrite(p, img)
        raw = None
        if img is None and band and (int(band[1]) - int(band[0])) >= BAND_CROP_MIN:
            try:
                raw = self.api.ocrBandJson(float(min_conf), int(band[0]), int(band[1]))
            except Exception:       # noqa: BLE001
                raw = None
            if raw:
                self.t['ocr_crop'] = self.t.get('ocr_crop', 0) + 1
        if not raw:
            raw = self.api.ocrJson(float(min_conf))
            try:
                items = json.loads(raw) if raw else []
            except Exception:       # noqa: BLE001
                items = []
            if band:
                y0, y1 = int(band[0]), int(band[1])
                items = [it for it in items if y0 <= it['cy'] <= y1]
        else:
            try:
                items = json.loads(raw) or []
            except Exception:       # noqa: BLE001
                items = []
        self.t['ocr'] += time.time() - _t0
        self.t['ocr_n'] = self.t.get('ocr_n', 0) + 1
        if tag:                 # ⭐ v0.61：按调用点分账（PC 早就有，端侧补齐 ⇒ 可逐项对账）
            cur = self.t.setdefault('ocr_by', {}).get(tag, [0.0, 0])
            self.t['ocr_by'][tag] = [cur[0] + (time.time() - _t0), cur[1] + 1]
        self._last_items = items
        return items

    def find_text(self, label, min_conf=0.5, near_y=None):
        return self._pick(self.ocr(min_conf=min_conf), label, near_y)

    @staticmethod
    def _pick(items, label, near_y=None):
        exact = [i for i in items if i['text'] == label]
        part = [i for i in items if label in i['text']]
        cands = exact or part
        if not cands:
            return None
        if near_y is not None:
            cands = sorted(cands, key=lambda i: abs(i['cy'] - near_y))
        return cands[0]

    # ---------- 操作 ----------
    def _sleep(self, sec):
        """可被「停止」中断的 sleep（真机口径：点 ■ 要**立刻**停 ✓）

        ⚠ 2026-10-01：`time.sleep(2.5)` 这类纯 Python 等待是 Java 侧 `requestInterrupt()`
          **管不到**的（那只踹 wait 循环）⇒ 用户点 ■ 后还要干等 1~3 秒 ✗
          这里把长 sleep 切成 0.1 秒一片，每片查一次停止位 ✓
        """
        try:
            import sys as _sys
            _el = _sys.modules.get('explore_loop')
        except Exception:       # noqa: BLE001
            _el = None
        _stop = bool(getattr(_el, '_ANDROID_STOP', False)) if _el is not None else False
        if not _stop and sec <= 0.15:
            time.sleep(sec)
            return
        _end = time.time() + max(0.0, sec)
        while True:
            if _el is not None and getattr(_el, '_ANDROID_STOP', False):
                return
            _left = _end - time.time()
            if _left <= 0:
                return
            time.sleep(min(0.1, _left))

    def tap(self, x, y, wait=1.2):
        """点 (x,y)（参考系坐标）；返回「画面是否变化」（同 PC 语义）"""
        ok = self.api.tapRef(float(x), float(y))
        if not ok:
            return False
        changed = None
        if wait > 0:
            changed = self.wait_change(wait, around=(x, y), thr=4.0)
        return changed

    def tap_dlg(self, x, y, wait=1.2):
        """⭐ v0.31 方案 B：点**居中弹窗系** (x,y)（boss/战斗事件/探索/结算等面板）。

        弹窗锚定设备屏幕中心（PC 上弹窗空间==参考系，PC 标定的面板常数原样可用）；
        非弹窗（棋盘/底部导航/万能位）**别用这个**，走 tap()。
        画面变化检测的取样区按 C 换算回棋盘系（waitChange 看的是归一化帧）。
        """
        ok = self.api.tapRefDialog(float(x), float(y))
        if not ok:
            return False
        changed = None
        if wait > 0:
            c = dlg_shift()
            changed = self.wait_change(wait, around=(x, y - c), thr=4.0)
        return changed

    def tap_cell(self, row, col, wait=2.5):
        x, y = self.cell_center(row, col)
        self.tap(x, y, wait=wait)
        return (x, y)

    def cell_center(self, row, col):
        x = self.GRID_X0 + (col + 0.5) * self.GRID_CX
        y = self.GRID_Y0 + (row + 0.5) * self.GRID_CY
        return (int(x), int(y))

    def swipe(self, x1, y1, x2, y2, ms=300, wait=1.2):
        self.api.swipeRef(float(x1), float(y1), float(x2), float(y2), int(ms))
        if wait > 0:
            self._sleep(wait)          # ⭐ 可中断（点 ■ 立刻停 ✓）

    def back(self, wait=1.5):
        self.api.backKey()
        if wait > 0:
            self._sleep(wait)          # ⭐ 可中断 ✓

    # ---------- 等画面变化 / 稳定（走 Kotlin，避免 PNG 编解码开销） ----------
    def wait_change(self, max_sec=1.5, band=None, thr=3.0, interval=0.06,
                    min_sec=0.22, around=None, radius=260):
        y0, y1 = (band if band else (130, 1700))
        ax = int(around[0]) if around else -1
        ay = int(around[1]) if around else -1
        _t0 = time.time()
        changed = bool(self.api.waitChange(float(max_sec), int(y0), int(y1),
                                           float(thr), float(min_sec),
                                           ax, ay, int(radius)))
        self.t['wait'] += time.time() - _t0
        self.t['wait_n'] += 1
        self.last_change = {'changed': changed, 'dim': float(self.api.lastDim())}
        return changed

    def wait_stable(self, max_sec=3.0, interval=0.08, thr=1.6, need=2, band=(130, 1800)):
        y0, y1 = band
        _t0 = time.time()
        ok = bool(self.api.waitStable(float(max_sec), float(thr), int(need),
                                      int(y0), int(y1)))
        self.t['wait'] += time.time() - _t0
        self.t['wait_n'] += 1
        return ok

    # ---------- 便捷（PC 版有、逻辑层偶尔用） ----------
    def tap_text(self, label, wait=1.5, near_y=None, required=True):
        p = self.find_text(label, near_y=near_y)
        if p is None:
            if required:
                raise RuntimeError('找不到按钮: %s' % label)
            return None
        self.api.tapRef(float(p['cx']), float(p['cy']))
        if wait:
            self._sleep(wait)          # ⭐ 可中断 ✓
        return (p['cx'], p['cy'])

    def wait_text(self, label, timeout=15, interval=1.2, required=True):
        t0 = time.time()
        while time.time() - t0 < timeout:
            p = self.find_text(label)
            if p:
                return p
            self._sleep(interval)      # ⭐ 可中断（点 ■ 不用等满 interval ✓）
        if required:
            raise RuntimeError('等待 %s 超时' % label)
        return None

    def energy(self):
        for it in self.ocr():
            t = it['text']
            if '/' in t and t.replace('/', '').isdigit():
                return int(t.split('/')[0])
        return None

    # ---------- 诊断 ----------
    def stats(self):
        return dict(self.t)
