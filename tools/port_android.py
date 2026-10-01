# -*- coding: utf-8 -*-
"""port_android.py · 把 PC 端 mapbot 的**纯逻辑模块**一次性快照到 Android（Chaquopy）

⭐⭐⭐ 2026-10-01 起 **PC 端与手机端正式分开、平行独立开发**（用户决定）

    两端现在是**两个独立 git 仓**、两份独立源码：
        PC 端    D:\\MGAS\\mapbot_pc\\                （独立仓，gitee/.../mapbot_pc）
        手机端   D:\\MGAS\\android_autoexplore\\      （本仓）
    `layout/spots/marks/badge/grid_detect/buypanels/mapgen/mapsim/mapsolve/
     strategy/targets_cfg/explore_loop` **各存一份，可以分叉**。

    ⇒ 本脚本的定位从「**每次改 PC 都必须重跑**」降级为
      「**想把 PC 上的某个改动/修复带到手机时，跑一次的搬运工具**」：
        · 手机端改了就直接改手机端，不必回头动 PC
        · PC 端改完想同步过来，才跑本脚本（**会覆盖**手机端同名文件！）
        · 两端逻辑漂移**是允许的**；判据是各自的行为，不是一致性

    ⚠⚠ 跑之前**先确认手机端这几个文件有没有本地改动**（`git status`）——
       本脚本是覆盖式写入，没有合并。手机端已分叉的代码会被静默冲掉。

做两件事（搬运时）
------------------
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

# ⭐⭐⭐ 2026-10-01 晚「两端完全平行」：**PC 仓对本仓是可选的**
#   本脚本只是「想把 PC 上的某个改动/修复搬到手机时」跑一次的**搬运工具**，
#   而**不是**手机端的构建/测试前置条件 ⇒ import 本模块**绝不能**因为找不到 PC 源就崩。
#   旧做法是 `raise SystemExit(...)` ⇒ 任何 `import port_android` 的工具
#     （包括主门禁）都会**直接挂掉** ⇒ 手机端仓就变成了"必须先有 PC 仓"。
#   ⇒ 现在改成：找不到就 `SRC = None` + 打印提示，调用 `main()` 时才报错。
#   仍可用环境变量覆盖：`MGAS_MAPBOT_SRC`。
_HERE = os.path.dirname(os.path.abspath(__file__))              # …/android_autoexplore/tools
PROJ = os.path.dirname(_HERE)                                    # …/android_autoexplore
MGAS_ROOT = os.path.dirname(PROJ)                                # …（MGAS 根）
DST = os.environ.get('MGAS_PY_DST') or os.path.join(PROJ, 'app', 'src', 'main', 'python')

SRC = os.environ.get('MGAS_MAPBOT_SRC') or os.path.join(MGAS_ROOT, 'mapbot_pc')
if not os.path.isdir(SRC):
    # 兜底：分离前的老布局（脚本还在旧仓库里、PC 源在 tools/mapbot）
    _old = os.path.join(MGAS_ROOT, 'tools', 'mapbot')
    SRC = _old if os.path.isdir(_old) else None
if SRC is None:
    print('[port_android] ⚠ 找不到 PC 端源码（%s）—— **本脚本是可选搬运工具**，'
          '不影响手机端构建与测试。\n'
          '            要用它把 PC 的改动搬过来时：设 MGAS_MAPBOT_SRC 指向 PC checkout，'
          '或把 PC 仓 clone 到 <MGAS>\\mapbot_pc。'
          % os.environ.get('MGAS_MAPBOT_SRC') or os.path.join(MGAS_ROOT, 'mapbot_pc'))

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


def _guard_overwrite(names):
    """⚠ 覆盖前先查手机端这些文件有没有**本地未提交改动**（2026-10-01 拆分时加）

    两端平行独立开发后，手机端的代码**可以**与 PC 端分叉。
    而本脚本是覆盖式写入、没有合并 ⇒ 若手机端有未提交改动就冲掉，是**不可逆**的数据损失。
    ⇒ 有改动就**停下**并提示，让使用者自己决定
       （`git stash` / 先提交 / 先 diff 看一眼）。
    已提交但与 PC 端分叉的情况**不拦** —— 那是合法状态，跑完 git diff 就能看清差异。
    """
    import subprocess as sp
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # ⚠ 必须传**列表**：join 成一个字符串的话 git 会当成单个路径 → 报
    #    "could not open directory" → 永远返回空 → 守卫**静默失效**（2026-10-01 自测才发现）
    paths = ['app/src/main/python/%s' % n for n in names]
    try:
        out = sp.run(['git', '-C', proj, 'status', '--porcelain'] + paths,
                     stdout=sp.PIPE, stderr=sp.DEVNULL, timeout=30)
        dirty = [ln for ln in (out.stdout or b'').decode('utf-8', 'replace').splitlines()
                 if ln.strip()]
    except Exception:
        return          # git 不可用就不拦（不该因为环境问题卡住主流程）
    if not dirty:
        return
    print('⚠⚠ 中止：手机端这些文件有**未提交改动**，本脚本会覆盖它们且不合并：')
    for ln in dirty:
        print('    ' + ln)
    print('   处置：先 `git -C %s stash`（或提交），确认后再跑。' % proj)
    print('   若你确定要丢弃这些改动：先把改动文件移走，再重跑本脚本。')
    raise SystemExit(1)


def main():
    if not SRC:
        raise SystemExit(
            '找不到 PC 端源码，无法搬运。\n'
            '   本脚本是**可选**搬运工具（手机端不依赖它），要跑就：\n'
            '   ① 设环境变量 MGAS_MAPBOT_SRC 指向 PC checkout，或\n'
            '   ② 把 PC 仓 clone 到 <MGAS>\\mapbot_pc')
    os.makedirs(DST, exist_ok=True)
    _guard_overwrite([m + '.py' for m in MODULES])
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
    print(f'搬运到 {DST}')
    print('⚠ 覆盖式写入，无合并 ⇒ 跑完务必 `git diff` 看两端差异是否可接受。')
    print('\n'.join(report))
    print(f'共 {len(MODULES)} 个模块')


if __name__ == '__main__':
    main()
