# -*- coding: utf-8 -*-
"""v1.62 第三步标定：`Block.plain` 的"空地"判据 —— 手机端数据表实测

## 背景（PC `9129a78`，用户口径）
    「**空地有好多种，其实本质都一样**」
    「**只有类似那种宝箱海螺的非空地才会拦截连锁**」
    「**这张图没认出宝箱吗，中间有宝箱拦住连锁了**」

PC 诊断出**旧写法两处都不对**（只是碰巧在 `_001` 那类地图上行得通）：
  · `suffix in PLAIN_SUFFIX and suffix != '000'` —— 号段会变（`地穴` 就是 `_005`）✗
  · `'草' in name` —— **只认「草地」** ⇒ 岩地/沙地/雪地/海底 全被判"非空地" ✗
    （与本仓 `targets_cfg.PLAIN_NAMES` **自相矛盾** ✗）

## 本脚本问：**手机端**同不同型？
  ① 全部地块按 `Weight` 排序 —— 看"地面填充块"是不是明显一簇（PC 说 = 40000）
  ② `targets_cfg.PLAIN_NAMES` 里到底有哪几种地面
  ③ 按旧判据（`'草' in name`）跑一遍：**有几种地面会被误判成"非空地"** ✗
  ④ 内容地块的 `score` 分布（真机帧）—— 定 `CONTENT_SCORE_MIN` 该取多少

用法：python android_autoexplore\\tools\\probe_plain_calib.py
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, '..'))
_PY = os.path.join(PROJ, 'app', 'src', 'main', 'python')
_ASSETS = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack')
CAL = os.environ.get('MGAS_CAL_DIR') or os.path.abspath(
    os.path.join(PROJ, '..', '_tmpman', 'cal'))
try:
    sys.stdout.reconfigure(encoding='utf-8')
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

import spots as SP                          # noqa: E402
import targets_cfg as TC                    # noqa: E402
import mapsim as MS                         # noqa: E402


def main():
    rows = SP.spot_rows() or {}
    plain_names = set(getattr(TC, 'PLAIN_NAMES', ()) or ())
    print('=' * 96)
    print('① `targets_cfg.PLAIN_NAMES`（手机端"空地"清单，共 %d 个）：' % len(plain_names))
    print('   %s' % sorted(plain_names))
    print()
    # 全部地块按 Weight 分组
    byw = {}
    for sid, r in rows.items():
        try:
            w = int(r.get('Weight') or 0)
        except Exception:                   # noqa: BLE001
            w = 0
        byw.setdefault(w, []).append((sid, str(r.get('Name') or '')))
    print('=' * 96)
    print('② 数据表 `Weight` 分布（PC 说"地面填充块"= 40000）：')
    for w in sorted(byw, reverse=True)[:8]:
        items = byw[w]
        names = sorted({n for _s, n in items})
        print('   Weight %-6d × %-3d 种：%s' % (w, len(items), names[:12]))
    print()
    print('=' * 96)
    print('③ ⚠ 按**旧判据**跑一遍：哪些"地面"会被判成**非空地**（= 连锁被截断 ✗）')
    print('   旧判据①：`suffix in PLAIN_SUFFIX and suffix != "000"`')
    print('   旧判据②：`"草" in name`')
    bad = []
    for sid, r in sorted(rows.items()):
        nm = str(r.get('Name') or '')
        try:
            w = int(r.get('Weight') or 0)
        except Exception:                   # noqa: BLE001
            w = 0
        # 只关心"其实是地面"的那些（Weight 最大那一簇 + PLAIN_NAMES 里有的）
        is_ground = (w >= 40000) or (nm in plain_names)
        if not is_ground:
            continue
        suf = str(sid).split('_')[-1]
        old_plain = (suf in set(getattr(MS, 'PLAIN_SUFFIX', ())) and suf != '000') \
            or ('草' in nm)
        if not old_plain:
            bad.append((sid, nm, w, suf))
    if bad:
        print('   ✗ **%d 个地面地块**会被旧判据判成"非空地"⇒ 连锁穿过不去 ✗✗：' % len(bad))
        for sid, nm, w, suf in bad:
            print('      %-14s %-8s Weight=%-6d suffix=%s' % (sid, nm, w, suf))
    else:
        print('   ✅ 没有（旧判据在手机端数据表上够用）')
    print()
    print('=' * 96)
    print('④ 真机帧上"内容地块"的 `score` 分布（定 `CONTENT_SCORE_MIN`）')
    if not os.path.isdir(CAL):
        print('   ⚠ 没有标定帧目录 ⇒ 跳过')
        return 0
    import cv2                              # noqa: E402
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    for fn in files[:4]:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        st = SP.Board('S30001').state(img)
        hi, lo = [], []
        for k, v in sorted(st.items()):
            if not isinstance(v, dict):
                continue
            sc = float(v.get('score') or 0)
            nm = str(v.get('name') or '')
            try:
                w = int((rows.get(v.get('sid')) or {}).get('Weight') or 0)
            except Exception:               # noqa: BLE001
                w = 0
            is_ground = (w >= 40000) or (nm in plain_names)
            if is_ground:
                continue
            (hi if sc >= 0.85 else lo).append((k, nm, sc))
        print('   %-18s 非地面格：高分(≥0.85) %d ｜ 低分 %d'
              % (fn, len(hi), len(lo)))
        for k, nm, sc in hi[:6]:
            print('        HIGH %-6s %-10s %.3f' % ('%d,%d' % k, nm, sc))
        for k, nm, sc in lo[:6]:
            print('        low  %-6s %-10s %.3f' % ('%d,%d' % k, nm, sc))
    return 0


if __name__ == '__main__':
    sys.exit(main())
