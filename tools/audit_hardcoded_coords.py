# -*- coding: utf-8 -*-
"""audit_hardcoded_coords.py · MGAS 全分辨率体检：清点**写死的像素坐标/常量**

分类口径（决定它在别的分辨率下会不会失准）：
  · ref   = 归一化参考系（1080x1920）常量，经 `b.tap()` / `LAYOUT.sx/sy` 使用
            ⇒ 只要 RefMapper 的「上块锚顶 + 下块锚底」模型成立就自适应 ✓
            ⚠ 但落在**弹性带**（toRef 丢弃的那条带）里的东西**归一化帧根本看不见** ⇒ 必须走弹窗通道
  · dlg   = 弹窗系常量，经 `b.tap_dlg()` 使用（面板锚设备中心）⇒ 与分辨率无关 ✓
  · devpx = **设备像素**写死（不经任何映射）⇒ ✗ 换分辨率必错
  · dp    = Android dp / 屏幕比例 ⇒ 一般自适应 ✓

退出码（2026-11 加：旧版**永远 0** ⇒ 结论表过期、常量被改名、甚至源文件全缺，
都只会安静地少打几行再 exit 0 ⇒ 整脚本失效而没有任何信号）
  0 = 扫完、且与 ⑤ 结论表一致
  1 = 漂移（⑤ 结论表与实测对不上）
  2 = 脚本自身无法工作（列出的源文件缺失）
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ⚠ 扫描根**由本文件位置推导**，不写死盘符（2026-11 修）：
#   旧版 ROOT = r'D:\幻想少女公会' 指的是**另一个仓**（本仓从那里分出来后没跟着改）
#   ⇒ 在本仓跑时列出的 PC 侧条目**全部静默跳过**，只扫到零散文件还照样打印报告 ⇒ 已失效。
#   本文件在 <仓根>/tools/ 下 ⇒ 仓根 = tools/ 的父目录。
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PY_FILES = [
    os.path.join('app', 'src', 'main', 'python', 'explore_loop.py'),
    os.path.join('app', 'src', 'main', 'python', 'mapbot.py'),
    os.path.join('app', 'src', 'main', 'python', 'mapsolve.py'),
    os.path.join('app', 'src', 'main', 'python', 'badge.py'),
    os.path.join('app', 'src', 'main', 'python', 'spots.py'),
    os.path.join('app', 'src', 'main', 'python', 'explore_android.py'),
]
JAVA_DIR = os.path.join('app', 'src', 'main', 'java', 'com', 'fantasy', 'autoexplore')

# ⑤ 结论表自述：写死坐标点击「仅剩 2 处」= b.tap_dlg(803,1112) + b.tap(803,1112)
EXPECTED_RAW_TAP_HITS = 2

_SRC_CACHE = {}


def _read(rel):
    """按相对路径读一次并缓存（①②③ 与末尾自检复用同一份文本）。"""
    if rel not in _SRC_CACHE:
        _SRC_CACHE[rel] = open(os.path.join(ROOT, rel), encoding='utf-8').read()
    return _SRC_CACHE[rel]


MISSING = [rel for rel in PY_FILES if not os.path.isfile(os.path.join(ROOT, rel))]
if MISSING:
    print('✗ 扫描根：%s' % ROOT)
    print('✗ 下列源文件不存在 ⇒ 脚本自身无法工作（缺文件就没法体检）：')
    for rel in MISSING:
        print('    %s' % os.path.join(ROOT, rel))
    print('  ⇒ 退出码 2（不打印残缺报告，免得被当成「没有漂移」）')
    sys.exit(2)

CONST_RE = re.compile(r'^([A-Z][A-Z0-9_]{2,})\s*=\s*(\[?\(?\s*-?\d+\s*,\s*-?\d+\s*\)?\]?)\s*(#.*)?$')
TUPLERE = re.compile(r'-?\d+')

print('=' * 96)
print('① Python 层：模块级「坐标常量」清单（名字 = (x, y)）')
print('=' * 96)
rows = []
for rel in PY_FILES:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    used = {}
    src = _read(rel)
    for m in re.finditer(r'(\w+)\s*\(\s*([A-Z][A-Z0-9_]{2,})\s*[,\)]', src):
        used.setdefault(m.group(2), set()).add(m.group(1))
    for i, line in enumerate(src.splitlines(), 1):
        m = CONST_RE.match(line.strip())
        if not m:
            continue
        name, val = m.group(1), m.group(2)
        nums = TUPLERE.findall(val)
        if len(nums) != 2:
            continue
        x, y = int(nums[0]), int(nums[1])
        callers = sorted(used.get(name, []))
        rows.append((rel, i, name, x, y, callers))

print('%-46s %-22s %-10s %s' % ('文件', '常量', '(x,y)', '被谁用（决定坐标系）'))
print('-' * 96)
for rel, i, name, x, y, callers in rows:
    print('%-46s %-22s (%4d,%4d)  %s'
          % (os.path.basename(rel) + ':' + str(i), name, x, y, ','.join(callers)[:44]))
print('共 %d 个' % len(rows))

print()
print('=' * 96)
print('② Python 层：**函数体内直接写数字**的点击/滑动（最容易在别的分辨率上失准）')
print('=' * 96)
TAP_RE = re.compile(r'(b\.tap|b\.tap_dlg|_bag_tap|_tap|b\.swipe|b\.tapRef|b\.tapRefHold)'
                    r'\(\s*(-?\d+)\s*,\s*(-?\d+)')
# ⚠ 必须**跳过注释与文档字符串里的示例文本**（否则会误报：如 `_close_bag` 的注释里
#   写着"旧写法是 b.tap(96,96)" ⇒ 审计会把注释当代码 ✗）
def _strip_py(src):
    out, in_doc = [], None
    for line in src.splitlines():
        s = line.strip()
        if in_doc:
            if in_doc in s:
                in_doc = None
            out.append('')
            continue
        if s.startswith('#'):
            out.append('')
            continue
        for q in ('"""', "'''"):
            if s.startswith(q) and s.count(q) == 1:
                in_doc = q
                break
        if in_doc:
            out.append('')
            continue
        out.append(line.split('#')[0] if '#' in line else line)
    return out


hits = 0
for rel in PY_FILES:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    src = _read(rel)
    for i, line in enumerate(_strip_py(src), 1):
        for m in TAP_RE.finditer(line):
            hits += 1
            print('%-44s %s(%s, %s)' % (os.path.basename(rel) + ':' + str(i),
                                        m.group(1), m.group(2), m.group(3)))
print('共 %d 处写死坐标的点击（已排除注释/文档字符串 ✓）' % hits)

print()
print('=' * 96)
print('③ 自适应用法统计（作为对照：这些是与分辨率无关的）')
print('=' * 96)
for rel in PY_FILES:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    src = _read(rel)
    n_sx = len(re.findall(r'LAYOUT\.sx\(', src))
    n_sy = len(re.findall(r'LAYOUT\.sy\(', src))
    n_tpl = len(re.findall(r'_tpl_hit\(', src))
    n_ocr = len(re.findall(r'b\.ocr\(', src))
    if n_sx or n_sy or n_tpl:
        print('%-34s LAYOUT.sx %3d ｜ LAYOUT.sy %3d ｜ 模板命中 %3d ｜ OCR %3d'
              % (os.path.basename(rel), n_sx, n_sy, n_tpl, n_ocr))

print()
print('=' * 96)
print('⑤ 结论表：每个写死坐标的"坐标系 + 自适应依据"（全分辨率体检 ✓）')
print('=' * 96)
# ⚠ 这里的事实来自真机实测（1280×2772，kx=1.1852 / shift=496.4 / topInset=132）：
#   弹性带（toRef 丢弃）= 设备 y ∈ (topInset+300·kx, 300·kx+shift) = (487.6, 852.0)
KX, SHIFT, INSET = 1280 / 1080.0, 2772 - 1920 * (1280 / 1080.0), 132
BAND = (INSET + 300 * KX, 300 * KX + SHIFT)
print('真机 1280×2772：kx=%.4f  shift=%.1f  topInset=%d  ⇒ **弹性带（归一化帧丢弃）= 设备 y %.0f~%.0f**'
      % (KX, SHIFT, INSET, BAND[0], BAND[1]))
print()
VERDICT = [
    ('STOP_HM (4,58)', 'ref', '顶部锚顶段（y≤300 ⇒ 设备 y=4·kx+132≈137）', '✓ 安全'),
    ('DISPATCH_BTN (891,1507)', 'ref', '底部锚底段；真机实测已生效（日志「已派出小队」✓）', '✓ 已实证'),
    ('EXPLORE_BTN (275,736)', 'ref', '地块面板「探索」；实际主要走 OCR 找字 ✓', '✓ 安全'),
    ('UNIVERSAL_CLOSE (541,1890)', 'ref（经 LAYOUT.sx/sy）', '底部导航带，锚底 ✓', '✓ 安全'),
    ('BACK_BTN (539,1212)', 'ref', '居中面板的「返回」——归一化系会被弹性带挤掉 ~C ⇒ 已改 `_panel_tap`（没生效自动换弹窗系）',
     '✓ 已加固'),
    ('CLOSE_TR_PT (984,191)', 'ref', '背包 X —— 真机实测在 **弹性带内**（dlg(1023,215) ⇒ 设备 y≈503）',
     '⚠ 必须走弹窗系（已加 BAG_X_DLG ✓）'),
    ('START_ADV (540,1828)', 'ref（经 LAYOUT）', '底部导航「开始冒险」图标，锚底 ✓', '✓ 安全'),
    ('GUILD_BTN (95,1889)', 'ref', '底部导航「公会」，锚底；真机已实证 ✓', '✓ 已实证'),
    ('BAG_BTN (964,1680)', 'ref', '公会「背包」图标；模板 `guild_bag_icon.png` 真机 0.978 ✓ 优先于它',
     '✓ 已实证（模板兜底）'),
    ('UPGRADE_BTN (923,1550)', 'ref', '装备页「一键升星」；真机 OCR 直接读到 ✓', '✓ 已实证'),
    ('ITEM_TAB (879,360)', 'ref', '道具页签 —— 真机实测在**弹性带内** ⇒ ref 点空 ~300px',
     '⚠ 已改走弹窗系 BAG_TAB_DLG'),
    ('EQUIP_TAB (370,360)', 'ref', '装备页签 —— 同上', '⚠ 已改走弹窗系 BAG_TAB_DLG'),
    ('BAG_TAB_DLG 5 项 (…,315)', 'dlg', '真机抓帧实测（面板锚设备中心 ⇒ 与分辨率无关 ✓）', '✓ 正确'),
    ('BAG_X_DLG (1023,215)', 'dlg', '真机抓帧实测 ✓', '✓ 正确'),
    ('UPGRADE confirm (803,1112)', 'dlg+ref 双通道', 'PC 标定弹窗系；C=0（9:16）时两系同值 ✓', '✓ 正确'),
]
print('%-30s %-22s %-62s %s' % ('写死坐标', '坐标系', '自适应依据/真机实测', '结论'))
print('-' * 96)
for name, ch, why, ok in VERDICT:
    print('%-30s %-22s %-62s %s' % (name, ch, why[:60], ok))
print()
print('Java 层：`RefMapper` 统一做 ref→设备映射（devX/devY/devYDialog + detectTopInset 自动测安全区）✓；')
print('         `OverlayService` 几何用 dp + *_REF 常量经映射换算 ✓；**没有任何写死设备像素的点击** ✓')
print('Python 层：写死坐标点击仅剩 2 处（`b.tap_dlg(803,1112)` + `b.tap(803,1112)`），')
print('         即"升星确认按钮"的**有意双通道兜底**（C=0 时两系同值 ✓）—— 已白名单 ✓')

# ── 退出口：⑤ 结论表 vs 本次实测（2026-11 加）───────────────────────────────────
#   只把**脚本自己 ⑤ 里已经写下的断言**拿去和实测对拍，不改任何判据口径。
print()
print('=' * 96)
print('⑥ 自检：⑤ 结论表 vs 本次实测（漂移 ⇒ 退出码 1）')
print('=' * 96)
drift = []
if hits != EXPECTED_RAW_TAP_HITS:
    drift.append('写死坐标点击实测 %d 处，而 ⑤ 自述「仅剩 %d 处」⇒ 结论表过期'
                 % (hits, EXPECTED_RAW_TAP_HITS))
for _name, _ch, _why, _ok in VERDICT:
    _m = re.match(r'^[A-Z][A-Z0-9_]{2,}', _name)
    if not _m:
        continue
    _key = _m.group(0)
    if not any(_key in _read(rel) for rel in PY_FILES):
        drift.append('⑤ 点名了 %s，但扫描源里查不到 %s（常量被删/改名 ⇒ 结论表过期）'
                     % (_name, _key))
if drift:
    for _d in drift:
        print('✗ ' + _d)
    print('⇒ 漂移 %d 项，退出码 1' % len(drift))
    sys.exit(1)
print('✓ 无漂移：%d 个源文件全在；写死坐标点击 %d 处；⑤ 点名的常量均在源里'
      % (len(PY_FILES), hits))
sys.exit(0)
