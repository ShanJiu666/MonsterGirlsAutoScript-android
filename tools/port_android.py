# -*- coding: utf-8 -*-
"""port_android.py · 把 PC 端 mapbot 的**纯逻辑模块**移植到 Android（Chaquopy）

做两件事
--------
1. 复制 11 个逻辑模块到 `app/src/main/python/`（不含 airtest/rapidocr/adb 依赖：
   PC 的 mapbot.py 用 Android 版替代，fastcap/mapcollect/memmap/loopguard/roadpick 属于
   **内存通道**，无 root 手机上不可用 ⇒ 不带）。
2. 路径适配：Chaquopy 下 `__file__` 指向 APK 内资源（**只读、旁边没有 templates/**），
   所以把所有「资源根」改成**环境变量优先**：
       MAPBOT_ROOT —— 模板根（= PackInstaller 解出来的 filesDir/mapbot_pack）
       MAPBOT_RUNS —— 运行期产物目录（= filesDir/runs）
       MAPBOT_DT   —— server_datatable.json
   未设置时回退到原 PC 行为 ⇒ 同一份代码在电脑上仍可直接跑（便于对拍）。
"""
import os
import re

SRC = r'D:\幻想少女公会\tools\mapbot'
DST = r'D:\幻想少女公会\android_autoexplore\app\src\main\python'

# 需要移植的纯逻辑模块（依赖只有 cv2 / numpy / 标准库）
MODULES = [
    'layout', 'targets_cfg', 'spots', 'marks', 'badge', 'grid_detect',
    'buypanels', 'mapgen', 'mapsim', 'mapsolve', 'strategy',
]

SHIM = '''
# ─────────────────────────────────────────────────────────────────────────────
# 【Android 适配补丁 · 由 android_autoexplore/tools/port_android.py 注入，勿手改】
# Chaquopy 里 __file__ 指向 APK 内只读资源，模板/数据表在 filesDir/mapbot_pack
#  ⇒ 资源根一律走环境变量，未设置时回退 PC 原行为（便于与 PC 对拍）
import os as _os

_MAPBOT_ROOT = _os.environ.get('MAPBOT_ROOT') or _os.path.dirname(_os.path.abspath(__file__))
_MAPBOT_RUNS = _os.environ.get('MAPBOT_RUNS') or _os.path.join(_MAPBOT_ROOT, 'runs')
_MAPBOT_DT = _os.environ.get('MAPBOT_DT') or _os.path.join(_MAPBOT_ROOT, 'server_datatable.json')
# ─────────────────────────────────────────────────────────────────────────────
'''

DIRNAME_EXPR = 'os.path.dirname(os.path.abspath(__file__))'


def patch(text, name):
    if 'Android 适配补丁' in text:
        raise SystemExit(f'{name}: 已被补丁过，请从 PC 源重新复制')

    # ① 先做路径替换（必须在注入 shim **之前**，否则 shim 里的
    #    `os.path.dirname(os.path.abspath(__file__))` 会被自己替换成 `_MAPBOT_ROOT`
    #    ⇒ 变成 `_MAPBOT_ROOT = ... or _MAPBOT_ROOT` 的自引用 NameError）
    out = []
    for ln in text.split('\n'):
        if DIRNAME_EXPR in ln and 'sys.path.insert' not in ln:
            ln = ln.replace(DIRNAME_EXPR, '_MAPBOT_ROOT')
        out.append(ln)
    text = '\n'.join(out)

    # ② 注入 shim：插在 `from __future__` 之后（必须是 docstring 后的第一条）；
    #    否则插在第一个顶层 import 之前（shim 自带 `import os as _os`，顺序无副作用）
    lines = text.split('\n')
    pos = None
    for i, ln in enumerate(lines):
        if ln.startswith('from __future__'):
            pos = i + 1
            break
    if pos is None:
        for i, ln in enumerate(lines):
            if re.match(r'^(import |from )\S', ln):
                pos = i
                break
    if pos is None:
        pos = 0
    lines.insert(pos, SHIM)
    return '\n'.join(lines)


# 模块级精确替换（语义化，避免误伤）
EXACT = {
    'spots.py': [
        ("RUNS = os.path.join(ROOT, 'runs')", 'RUNS = _MAPBOT_RUNS'),
        ("DT = r'D:\\幻想少女公会\\unpack_apk\\dump\\server_datatable.json'", 'DT = _MAPBOT_DT'),
    ],
    'mapgen.py': [
        ("DATATABLE = r'D:\\幻想少女公会\\unpack_apk\\dump\\fetch_20260924\\server_datatable.json'",
         'DATATABLE = _MAPBOT_DT'),
    ],
    'targets_cfg.py': [
        ("root = base or os.path.join(HERE, 'runs')", 'root = base or _MAPBOT_RUNS'),
    ],
}


def main():
    os.makedirs(DST, exist_ok=True)
    report = []
    for m in MODULES:
        src = os.path.join(SRC, m + '.py')
        txt = open(src, encoding='utf-8').read()
        n0 = len(txt)
        txt = patch(txt, m)
        for old, new in EXACT.get(m + '.py', []):
            if old not in txt:
                report.append(f'  ⚠ {m}.py: 未命中替换 → {old[:60]}')
                continue
            txt = txt.replace(old, new)
        dst = os.path.join(DST, m + '.py')
        with open(dst, 'w', encoding='utf-8', newline='\n') as f:
            f.write(txt)
        report.append(f'  {m}.py  {n0/1024:6.1f} KB')
    print(f'移植到 {DST}')
    print('\n'.join(report))
    print(f'共 {len(MODULES)} 个模块')


if __name__ == '__main__':
    main()
