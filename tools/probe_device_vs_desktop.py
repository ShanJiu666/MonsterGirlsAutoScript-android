# -*- coding: utf-8 -*-
"""端 ↔ 桌面 **逐格等价性核对**（零体力）—— 证明"手机上跑的就是这份代码"

## 为什么需要这条
改完 `spots.py` / `explore_loop.py` / `mapsolve.py` 之后，"门禁全绿 + 桌面探针通过"
**仍然不能证明手机上跑的是新代码**：
  · 可能 APK 是旧的（改了仓、没重打包）
  · 可能包里的 `.pyc` 没跟着更新
  · 可能热更补丁把旧模块又盖上去了
本项目已经栽过同族问题（v1.20「APK 是 120、git 里还是 119」）。
⇒ 唯一可信的办法：**让手机自己跑一遍，再把逐格结果跟桌面逐格对拍**。

## 怎么跑（三步，全程不消耗体力）
```powershell
$adb = 'E:\\MuMu Player 12\\shell\\adb.exe'
$s   = '<设备号>'                       # adb devices 里那台真机

# ① 装 **arm64 debug** 包（`classify` 广播在 release 里被 DEBUG_ONLY 拒掉 ✗）
& gradle.bat assembleArm64Debug
& $adb -s $s install -r app\\build\\outputs\\apk\\arm64\\debug\\app-arm64-debug.apk

# ② 把 fixture 帧推进 App 私有目录（`/sdcard/Download` 读不到 —— 分区存储 ✗）
& $adb -s $s shell mkdir -p /sdcard/Android/data/com.fantasy.autoexplore/files/v160chk
& $adb -s $s push _verify\\phone_redmi_grassland\\board_grassland_r0.png `
        /sdcard/Android/data/com.fantasy.autoexplore/files/v160chk/r0.png
& $adb -s $s shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver `
        -a com.fantasy.autoexplore.CMD --es cmd classify `
        --es img /sdcard/Android/data/com.fantasy.autoexplore/files/v160chk/r0.png `
        --es map S10002

# ③ 取回端侧 JSON（App 私有目录 ⇒ 走 `exec-out run-as`）
& $adb -s $s exec-out run-as com.fantasy.autoexplore `
        cat files/runs/board_dev_S10002.json > _dev_S10002.json

# ④ 对拍（本脚本；`_dev_*.json` 若是 UTF-16 会先转 UTF-8）
python tools\\probe_device_vs_desktop.py

# ⑤ **装回 release 包**（别把 debug 包留给用户 ✗）
& $adb -s $s install -r MGAS-v<版本>-release.apk
```

## 判据
35 格 × 6 字段（`sid/name/score/ratio/revealed/anchor`）逐格一致。
⚠ `score`/`ratio` 是浮点：端（Chaquopy numpy 1.x / OpenCV 4.x）与本机在**末位**会差
最多 **0.001**（实测 0.9495 → 端 round 成 0.95、本机 0.949）⇒ 只对这两个字段留 2e-3 容差；
**`sid`/`name`/`revealed`/`anchor` 必须严格相等** ✓
"""
import io
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
_TMP = os.path.abspath(os.path.join(HERE, '..', '..', '_tmpman'))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:                           # noqa: BLE001
    pass
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


for _m, _at in (('rapidocr_onnxruntime', {'RapidOCR': type('RapidOCR', (), {'__init__': _noop})}),
                ('airtest', {'core': None}), ('airtest.core', {}),
                ('airtest.core.api', {'connect_device': _noop, 'snapshot': _noop,
                                      'touch': _noop, 'swipe': _noop, 'keyevent': _noop,
                                      'exists': _noop, 'Template': object}),
                ('airtest.core.cv', {'Template': object}),
                ('java', {}), ('java.android', {}), ('java.lang', {}),
                ('java.util', {}), ('java.util.concurrent', {})):
    try:
        __import__(_m)
    except Exception:                       # noqa: BLE001
        _stub(_m, **_at)

import cv2                                  # noqa: E402
import spots as SP                          # noqa: E402

# (code, 桌面 fixture, 端侧 JSON)
CASES = (
    ('S10002', os.path.join(PROJ, '_verify', 'phone_redmi_grassland',
                            'board_grassland_r0.png'),
     os.path.join(_TMP, '_dev_S10002.json'), '草原帧A'),
    ('S00003', os.path.join(PROJ, '_verify', 'phone_friend_rmx3800',
                            'board_hidden_r0.png'),
     os.path.join(_TMP, '_dev_S00003.json'), 'realme RMX3800'),
)
FIELDS = ('sid', 'name', 'score', 'ratio', 'revealed', 'anchor')
_TOL = 2e-3


def _load_json(p):
    """端侧 JSON 可能是 UTF-16（adb `exec-out` 在某些 shell 下会带 BOM）⇒ 自动判编码 ✓"""
    b = open(p, 'rb').read()
    enc = 'utf-16' if b[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
    return json.loads(b.decode(enc))


def main():
    allok = True
    ncase = 0
    for code, imgp, devp, tag in CASES:
        print('=' * 96)
        print('%s  code=%s' % (tag, code))
        if not (os.path.exists(imgp) and os.path.exists(devp)):
            print('  ⚠ 缺件 ⇒ **跳过**（不是通过 ✗）：')
            print('     桌面 fixture %s：%s' % (os.path.exists(imgp), imgp))
            print('     端侧 JSON    %s：%s' % (os.path.exists(devp), devp))
            print('      ⇒ 按文件头的"怎么跑"①~④ 先生成端侧 JSON')
            allok = False
            continue
        ncase += 1
        dev = _load_json(devp)
        img = cv2.imread(imgp)
        st = SP.Board(code).state(img)
        # ⚠ 端侧 `classify_image()` 会把图 resize 到 1080×1920 ⇒ 只有本机 fixture
        #   也是 1080×1920 时才能逐格对拍（尺寸不同则先比尺寸，别静默错位）
        print('  端 n=%d（%.2fs）｜桌面 n=%d｜图 %dx%d'
              % (dev['n'], dev.get('secs', -1), len(st), img.shape[1], img.shape[0]))
        if (img.shape[1], img.shape[0]) != (1080, 1920):
            print('  ⚠ 本机 fixture 不是 1080×1920 ⇒ **不可比**（端侧会 resize）✗')
            allok = False
            continue
        dv = {(c['r'], c['c']): c for c in dev['cells']}
        diff, miss = [], []
        for k, v in sorted(st.items()):
            d = dv.get(k)
            if d is None:
                miss.append(k)
                continue
            got = {'sid': v.get('sid'), 'name': v.get('name'),
                   'score': round(float(v.get('score') or 0), 3),
                   'ratio': round(float(v.get('ratio') or 0), 3),
                   'revealed': bool(v.get('revealed')),
                   'anchor': list(v['anchor']) if v.get('anchor') else None}
            for f in FIELDS:
                a, b = got[f], d.get(f)
                if isinstance(b, float):
                    b = round(b, 3)
                if f in ('score', 'ratio') and isinstance(a, float) \
                        and isinstance(b, float) and abs(a - b) <= _TOL:
                    continue
                if a != b:
                    diff.append(('%d,%d' % k, f, a, b))
        print('  桌面独有的格：%s' % (['%d,%d' % k for k in miss] or '无'))
        if not diff and not miss:
            print('  ✅ **%d 格 × %d 字段逐格一致** ⇒ 端上跑的就是本仓这份代码 ✓'
                  % (len(st), len(FIELDS)))
        else:
            allok = False
            print('  ❌ 不一致 %d 处（格, 字段, 桌面, 端）：' % len(diff))
            for d in diff[:20]:
                print('     %-6s %-9s 桌面=%-22s 端=%s' % d)
        _ev = sorted({v.get('rev_evidence') for v in st.values()})
        print('  揭示：桌面已揭示 %d 格 rev_evidence=%s；端 %d 格'
              % (sum(1 for v in st.values() if v.get('revealed')), _ev,
                 sum(1 for c in dev['cells'] if c.get('revealed'))))
    print()
    print('=' * 96)
    if ncase == 0:
        print('⚠ 一例都没跑到 ⇒ **不算通过**（按文件头的①~④ 先生成端侧 JSON）✗')
        return 2
    print('结论：%s' % ('✅ 端 ↔ 桌面逐格等价 ⇒ 手机上跑的就是这份代码 ✓'
                       if allok else '❌ 有差异/缺件 ⇒ 先查是不是"端上跑的不是这份代码"'))
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
