# -*- coding: utf-8 -*-
"""v1.63 移植评估（B15）：手机端**有没有**「一图/一格只能认一个标记」这个病？

## PC 的诊断（`marks.py` 未提交改动 + `verify_mark_multi.py`）
  ① `match_at_scales` 用 `cv2.minMaxLoc(res)` ⇒ **每尺度每模板只回 1 个点**
     ⇒ 同模板出现在**两格**时，分数高的那格**抢走唯一名额** ⇒ 另一格**连候选都不是** ✗
     真机铁证（PC `runs/acc2/r_183432_0.png` 第 12 张图）：`(1,5)` 与 `(3,3)` **都有大拇指**
     （两格图标实测完全相同），但 `(1,5)` 的 0.925 抢走名额 ⇒ `(3,3)` 不被当目标 ✗
  ② `scan_board` 用**模块级** `GLYPH_SCALES`（720 快照 2.53~3.47）去扫 **1080 帧**（格距 144）
     ⇒ 尺度少一整档 ⇒ 四个标记只有 0.74~0.83（门槛 0.90）⇒ **全都认不出来** ✗
  ③ PC 那段"同格多标记按位置保留（≥18px / `保 4 标记格`）"的聚合代码
     **本来就是为多标记写的，却因为上游只给 1 个点而从来没派上用场** ✗

## ⚠ 手机端**不能假设同病**，但初查很像
  · `marks.py` **也有** `_dedup_candidates`（注释里写着 `保 4 标记格`、`18px`、`MARK_MARGIN`）
  · `marks.py` **也有** `minMaxLoc`（只取 1 个峰）
  · **但**手机端 `GLYPH_SCALES` 已经是 **3.8~5.2**（1080 系正确值）
    ⇒ PC 的根因②在手机端**不存在** ✓（手机端本来就是 1080 基准）

## 本脚本问：手机端真机帧上，**同一模板出现在多格**时，是不是只认到一个？
  逐帧：用真 `scan_board_fast` 扫；再看"同一 `name` 在几格出现"
  与"肉眼可见的同名标记格数"对比 ⇒ 少认了就是有病 ✓

用法：python android_autoexplore\\tools\\probe_mark_multi.py
"""
import io
import os
import sys
import types
from collections import defaultdict

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

import cv2                                  # noqa: E402
import marks as MK                          # noqa: E402


def main():
    if not os.path.isdir(CAL):
        print('⚠ 没有标定帧目录 `%s` ⇒ **跳过**（不报假绿）' % CAL)
        return 2
    files = sorted(f for f in os.listdir(CAL)
                   if f.endswith('.png') and not f.startswith('_'))
    if not files:
        print('⚠ 没有帧 ⇒ **跳过**')
        return 2
    print('=' * 96)
    print('手机端 marks：`GLYPH_SCALES` = %s' % (MK.GLYPH_SCALES[:3],))
    print('  `MARK_TOPN` 存在？ %s（PC 新增，手机端应还没有）' % hasattr(MK, 'MARK_TOPN'))
    print('  `glyph_scales()` 存在？ %s' % hasattr(MK, 'glyph_scales'))
    print('=' * 96)
    for fn in files:
        img = cv2.imread(os.path.join(CAL, fn))
        if img is None:
            continue
        try:
            res = MK.scan_board_fast(img)
        except Exception as e:              # noqa: BLE001
            print('%-20s scan 失败 %r' % (fn, e))
            continue
        # 同一 name 出现在几格
        byname = defaultdict(list)
        for k, v in sorted(res.items()):
            for nm in (v.get('marks') or []):
                byname[nm].append(k)
        multi = {nm: ks for nm, ks in byname.items() if len(ks) > 1}
        print('%-20s 识别到标记的格 %d ｜ 涉及类型 %s'
              % (fn, len(res), sorted(byname)))
        if multi:
            print('   ⭐ **同一类型出现多格**（说明 topn 不是瓶颈，或已够用）：')
            for nm, ks in sorted(multi.items()):
                print('        %-10s × %d : %s' % (nm, len(ks), ks))
        else:
            print('   ⚠ 每种类型**最多只出现在 1 格** —— 若图上肉眼见到两格同名标记，'
                  '就是 PC 那个病 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main())
