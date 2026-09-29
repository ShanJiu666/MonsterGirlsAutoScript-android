# -*- coding: utf-8 -*-
"""设备端探针：证明 v0.38 里确实含 v0.34/35/36/37 的改动（APK 内是加密 .imy，只能运行时验证）"""
import traceback


def P(*a):
    print(' '.join(str(x) for x in a), flush=True)


P('=====PROBE_V038_BEGIN=====')

# ── 1. explore_loop 里 v0.34~v0.37 的痕迹（字符串常量 / 全局符号）──────────────
try:
    import explore_loop as EL
    P('[1] explore_loop imported ok')

    def _walk(o, out, d=0):
        if d > 5:
            return
        if isinstance(o, tuple) or isinstance(o, list):
            for x in o:
                _walk(x, out, d + 1)
        elif isinstance(o, str):
            out.append(o)

    consts = []
    _walk(EL.handle_dice.__code__.co_consts, consts)
    keys = ['mark_routes', 'reroll_confirm', 'reroll_confirm_tail', 'no_btn',
            'narrow_hit', 'dlg+C', 'dlg', 'ref', 'match_err', 'got_recommend']
    P('[2] handle_dice consts:', {k: (k in consts) for k in keys})
    P('[3] globals:', {n: hasattr(EL, n) for n in ('_OCR_CH', '_tap', 'ocr_ch', 'dlg_c')})
    P('[4] _OCR_CH =', getattr(EL, '_OCR_CH', None))

    # v0.35 铁证：结算面板按归一化系（源码里有这段注释文案）
    src_ok = False
    try:
        import inspect
        src_ok = 'v0.35' in inspect.getsource(EL.handle_dice)
    except Exception:
        src_ok = 'n/a'
    P('[5] inspect.getsource 可用:', src_ok)
except BaseException:
    P('[ERR-EL]', traceback.format_exc()[-1200:])

# ── 2. mapbot：img_dlg / ocr_dlg / dlg_c 是否在位 ─────────────────────────────
try:
    import mapbot as MB
    P('[6] Bot methods:', {m: hasattr(MB.Bot, m)
                           for m in ('img', 'img_dlg', 'ocr', 'ocr_dlg', 'tap', 'tap_dlg')})
    P('[7] dlg_c() =', MB.dlg_c())
except BaseException:
    P('[ERR-MB]', traceback.format_exc()[-1200:])

# ── 3. 真机几何：RefMapper 的 C 与屏幕指标 ────────────────────────────────────
try:
    from java import jclass
    RM = jclass('com.fantasy.autoexplore.RefMapper')
    P('[8] dialogShift =', RM.dialogShift())
    P('[9] topInset =', RM.detectTopInset() if hasattr(RM, 'detectTopInset') else 'n/a')
    am = jclass('android.app.ActivityThread').currentApplication()
    wm = am.getSystemService('window')
    d = wm.getDefaultDisplay()
    from android.view import Display  # noqa
except BaseException as e:
    P('[10] geom via jclass failed:', repr(e))

# ── 4. 真帧对比：归一化帧 vs 弹窗帧的形状与缩放 ───────────────────────────────
try:
    import mapbot as MB
    b = MB.Bot()
    P('[11] Bot 建好了: fast_ok=', b.fast_ok)
    im = b.img()
    P('[12] img().shape =', None if im is None else im.shape)
    try:
        di = b.img_dlg()
        P('[13] img_dlg().shape =', None if di is None else di.shape)
    except BaseException:
        P('[ERR-dlg]', traceback.format_exc()[-1200:])
except BaseException:
    P('[ERR-BOT]', traceback.format_exc()[-1200:])

P('=====PROBE_V038_END=====')
