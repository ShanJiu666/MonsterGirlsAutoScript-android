# -*- coding: utf-8 -*-
"""离线复现反馈包里的 `board_hidden_r*.png`（判「面板挡住棋盘」时存的诊断帧）

起因：2026-10-01 23:37 反馈包（应用 1.14 / realme RMX3800 1264x2780）
      与 2026-10-02 00:37 反馈包（应用 1.20 / nubia NX809J 1216x2688）
      都带着这么一张帧 —— 要回答的只有一个问题：
      **「这一帧到底该不该判『棋盘被面板挡住』？」**

本脚本**只做取证**，不改任何生产代码：
  ① 把帧丢进本仓**当前**的 `cells_of()`；
  ② 打印每格 ratio / revealed / score / name；
  ③ 打印 `board_hidden()` 两条判据各自的真实数值；
  ④ 对拍：仓里已知干净的棋盘帧 + **当前实现 vs 旧实现（v1.11~v1.20 的 `0.55*_mx`）**。

用法：
    set PYTHONIOENCODING=utf-8
    <py3.11> tools\fb_probe_20261001.py <反馈包目录 或 直接给 png 路径>

⚠ 帧必须是 **归一化 1080x1920**（`_pub_dump` 落的那份）；
  原始设备帧（`_verify/phone_stamina_0930/bagdbg/*.png` 那种 1280x2772）
  **不对这个坐标系**，喂进来只会得到没意义的数字 ✗
"""
import glob
import io
import os
import sys
import types

HERE = os.path.abspath(os.path.dirname(__file__))
_PY = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
_ASSETS = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main',
                                       'assets', 'mapbot_pack'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, _PY)
os.environ.setdefault('MAPBOT_ROOT', _ASSETS)
os.environ.pop('MAPBOT_ANDROID', None)


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _noop(*a, **k):
    return None


try:
    import rapidocr_onnxruntime        # noqa: F401
except Exception:                      # noqa: BLE001
    _stub('rapidocr_onnxruntime', RapidOCR=type('RapidOCR', (), {'__init__': _noop}))
for _m, _attrs in (
        ('airtest', {'core': None}),
        ('airtest.core', {}),
        ('airtest.core.api', {'connect_device': _noop, 'snapshot': _noop,
                              'touch': _noop, 'swipe': _noop, 'keyevent': _noop,
                              'exists': _noop, 'Template': object}),
        ('airtest.core.cv', {'Template': object}),
        ('java', {}), ('java.android', {}), ('java.lang', {}),
        ('java.util', {}), ('java.util.concurrent', {}),
):
    try:
        __import__(_m)
    except Exception:                  # noqa: BLE001
        _stub(_m, **_attrs)
try:
    import java                       # noqa: F811
    java.android = getattr(java, 'android', _stub('java.android'))
    java.lang = getattr(java, 'lang', _stub('java.lang'))
    java.util = getattr(java, 'util', _stub('java.util'))
    java.util.concurrent = getattr(java, 'util.concurrent', _stub('java.util.concurrent'))
except Exception:                      # noqa: BLE001
    pass

import numpy as np                                   # noqa: E402
import cv2                                           # noqa: E402
import explore_loop as E                             # noqa: E402


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else r'D:\MGAS\_fb\fb_20261001_2337'
    if os.path.isfile(arg):
        shot = arg
    else:
        # 目录 ⇒ 取里面的 board_hidden_r0.png；没有就取任意一张 board_hidden_r*.png
        shot = os.path.join(arg, 'board_hidden_r0.png')
        if not os.path.exists(shot):
            _c = sorted(glob.glob(os.path.join(arg, 'board_hidden_r*.png')))
            shot = _c[0] if _c else shot
    img = cv2.imread(shot)
    if img is None:
        print('!! 读不到', shot)
        return 1
    print('=' * 72)
    print('反馈帧：%s  %dx%d' % (shot, img.shape[1], img.shape[0]))
    if img.shape[:2] != (1920, 1080):
        print('⚠⚠ 这不是归一化 1080x1920 帧 ⇒ 下面的 ratio/判据**没有意义**（只是照跑一遍）')
    print('=' * 72)

    # 图名「夏日海滩[100]」→ code（真机 OCR 读到的就是它）
    name = '夏日海滩'
    c = E.cells_of(img, mapname=name)
    st = c.get('st') or {}
    print('\n【cells_of 逐格结果】共 %d 格' % len(st))
    print('%-7s %6s %6s %6s  %-14s %s' % ('格', 'ratio', '分数', '揭示', '名字', '备注'))
    ratios = []
    for (r, cc), v in sorted(st.items()):
        ratio = float(v.get('ratio') or 0)
        ratios.append(ratio)
        flags = []
        if v.get('fog_object'):
            flags.append('雾下有物')
        if v.get('fog_flat'):
            flags.append('雾下平坦')
        if v.get('anchor') and tuple(v['anchor']) != (r, cc):
            flags.append('成员格->%s' % (v['anchor'],))
        print('%-7s %6.3f %6.3f %6s  %-14s %s'
              % ('(%d,%d)' % (r, cc), ratio, float(v.get('score') or 0),
                 '是' if v.get('revealed') else '否', str(v.get('name') or '-'),
                 ' '.join(flags)))
    if not ratios:
        print('!! 分类器一格都没认出来 —— 这是另一种故障（模板/资源根问题）')
        return 2
    _mx = max(ratios)
    print('\nratio: 最亮=%.3f  中位=%.3f  最暗=%.3f' %
          (_mx, float(np.median(ratios)), min(ratios)))
    print('gray(未揭示)=%d  light(已揭示)=%d' % (len(c['gray']), len(c['light'])))

    print('\n【board_hidden() 判据逐条（当前实现 = v1.21）】')
    n_light = len(c.get('light') or [])
    n_gray = len(c.get('gray') or [])
    _lit = [x for x in ratios if x >= getattr(E, 'REVEAL_RATIO_MIN', 0.75)]
    _ref = float(np.median(_lit)) if _lit else _mx
    _dim = getattr(E, 'DIM_RATIO_MAX', 0.42)
    print('  ① 全暗: light==0 → %s ; gray>=25 → %s ; _mx<0.40 → %s'
          % (n_light == 0, n_gray >= 25, _mx < 0.40))
    print('     ⇒ 判据①成立 = %s' % (n_light == 0 and n_gray >= 25 and _mx < 0.40))
    print('  ② 多数压暗（v1.21）: 基准=已揭示格中位=%.3f（%d 格）  阈值=%.2f*基准=%.3f'
          % (_ref, len(_lit), _dim, _dim * _ref))
    n_dim = sum(1 for x in ratios if x < _dim * _ref)
    print('     压暗格数=%d  需要>=15 → 成立=%s' % (n_dim, n_dim >= 15))
    print('\n  ⇒ board_hidden()（当前）= %s' % E.board_hidden(c))

    # 对比：**旧实现**（v1.11~v1.20：基准=最亮格，系数 0.55）—— 这就是误判的来源
    def _old(c, thr_mx=0.55):
        _st = c.get('st') or {}
        _mx2 = max([float((v or {}).get('ratio') or 0) for v in _st.values()] or [0.0])
        if len(c.get('light') or []) == 0 and len(c.get('gray') or []) >= 25 and _mx2 < thr_mx:
            return True
        _t = 0.55 * _mx2 if _mx2 > 0 else 0.55
        return sum(1 for v in _st.values()
                   if float((v or {}).get('ratio') or 0) < _t) >= 15
    _othr = 0.55 * _mx if _mx > 0 else 0.55
    _odim = sum(1 for x in ratios if x < _othr)
    print('\n【对比：旧实现（v1.11~v1.20 —— 基准=最亮格 %.3f，系数 0.55）】' % _mx)
    print('   阈值=%.3f  压暗格数=%d（要>=15）  ⇒ board_hidden()（旧）= %s'
          % (_othr, _odim, _old(c)))
    if _old(c) != E.board_hidden(c):
        print('   ⭐ 新旧**不一致** ⇒ 这一帧正是 v1.21 修的那种误判（旧：判被挡；新：不判）')

    # 标定：拿仓里**已知干净**的棋盘帧对拍（枯木丛林真机帧，见门禁 1031~1040 注释）
    ref = os.path.abspath(os.path.join(HERE, '..', '_verify', 'phone_stamina_0930',
                                       'bagdbg', 'board_now_ref.png'))
    print('\n【对拍：已知干净的棋盘帧 vs 反馈帧】')
    if os.path.exists(ref):
        _ri = cv2.imread(ref)
        _rc = E.cells_of(_ri, mapname=name)
        _rr = [float(v.get('ratio') or 0) for v in (_rc.get('st') or {}).values()]
        if _rr:
            _rmx = max(_rr)
            _rlit = [x for x in _rr if x >= getattr(E, 'REVEAL_RATIO_MIN', 0.75)]
            _rref = float(np.median(_rlit)) if _rlit else _rmx
            print('  干净帧 %s' % os.path.basename(ref))
            print('    格数=%d 最亮=%.3f 中位=%.3f  新阈值=%.3f 压暗数=%d'
                  % (len(_rr), _rmx, float(np.median(_rr)), _dim * _rref,
                     sum(1 for x in _rr if x < _dim * _rref)))
            print('    board_hidden() = %s  ← 必须 False' % E.board_hidden(_rc))
        else:
            print('  干净帧一格都没认出来，跳过对拍')
    else:
        print('  （找不到 %s，跳过）' % ref)
    print('  反馈帧：格数=%d 最亮=%.3f 中位=%.3f  新阈值=%.3f 压暗数=%d'
          % (len(ratios), _mx, float(np.median(ratios)), _dim * _ref, n_dim))

    print('\n【怎么读这份结果】')
    print('  · `已揭示格中位` 就是这帧的"正常亮度水平"（营地/已走开的格）')
    print('  · 雾格/已揭示 ≈ 0.49~0.61（正常） vs 真面板/已揭示 ≈ 0.25~0.35（被遮）')
    print('  · 有「结束冒险」面板在**棋盘上方**、涂平压条在**棋盘下方**（y≥1722）⇒ 都没盖到棋盘')
    print('  · 想眼见为实：直接看 png 的 y 1002~1722 那一块（`board_hidden` 只看那里）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
