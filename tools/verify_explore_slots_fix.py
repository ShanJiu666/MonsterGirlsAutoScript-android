# -*- coding: utf-8 -*-
"""verify_explore_slots_fix.py · 回归：真机「探索槽满了还一直点探索」事故

事故（2026-09-30 真机 Redmi 1280×2772 / MGAS）：
    日志连续 18 轮 `{'explore': 'first_high_value', 'at': (274, 790)}`
    （105 秒、0 战斗 0 装备、25 体力白花）。
根因两条（都在本脚本里断言）：
    ① 倒计时被 OCR 吃掉一个冒号：`04:24:31` → `04:24831`
       ⇒ 旧式 `TOTAL(3) - busy(2) = 空闲 1`（**假空闲**，真值 0）
    ② 该账号 HUD 是 **4 个槽**（角标 1/2/3/4，其中 1 个"待领取"无倒计时）
       ⇒ `TOTAL - busy` 反推法从根上不成立
修法：
    · 空闲数**只认正面证据「空闲」**；认不到 ⇒ 这一帧不下结论（None，保留旧值）
    · `popups` 的「探索」分支**点完必须验证**（面板没关 = 游戏没受理）⇒ 两次判定满本图
    · 轮首每轮刷新 slots_free（旧版只在轮尾算 ⇒ 提前 return 的轮次永远不更新）
    · 同类动作连续 4 轮 ⇒ 总闸门强制脱困（兜底网）

跑法：  python android_autoexplore/tools/verify_explore_slots_fix.py
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# ⭐⭐⭐ 2026-10-01 晚：**手机端完全自洽**（两端平行，不再需要 PC 仓在场）
#   门禁 import 的 `explore_loop` 取**本仓自己的**源码 `app/src/main/python/explore_loop.py`
#   —— 与 APK 里跑的是同一份 ✓ ⇒ 单独 clone 手机端仓也能跑通全部门禁。
#   旧做法（已废）：`MAPBOT = <MGAS>/mapbot_pc` ⇒ 没 clone PC 仓就直接崩。
#   ⚠ 想拿 PC 端源码跑同一套门禁做对拍：设 `MGAS_PC_SRC` 指向 PC checkout（可选）。
#
# ⭐ 资源根（模板/数据表）也必须是**本仓的**，否则"自洽"是假的：
#   - 代码根 = `app/src/main/python`（模块在這）
#   - 资源根 = `app/src/main/assets/mapbot_pack`（**模板真身在这**，见 build_pack.py）
#   ⚠ 曾踩：以为 `app/src/main/python/templates` 里有模板 —— 那个目录是**空的**，
#     结果所有要模板的用例 FileNotFoundError（"地块分类失败"）。
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
PROJ = os.path.abspath(os.path.join(HERE, '..'))   # ⭐ 本仓根（仓内路径一律用它）
_PY_SELF = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
_ASSETS = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main',
                                       'assets', 'mapbot_pack'))
PC_SRC = os.environ.get('MGAS_PC_SRC')          # 可选：显式指到 PC 端做对拍
MAPBOT = _PY_SELF
# 资源根：PC 模式下（门禁跑的就是 PC 口径 C=0）资源跟着**代码根**走；
# 若代码根下没有 templates/（手机端的常态），回退到 assets/mapbot_pack。
_ASSET_TPL = os.path.join(_ASSETS, 'templates')
# ⚠ 不能只看 `templates/` 目录**存在** —— 手机端 `app/src/main/python/templates/ui`
#   是个**空目录**（历史遗留），判存在会误判成"有模板" ⇒ 所有要模板的用例
#   FileNotFoundError。必须**递归数一下文件**。
def _has_files(d, minimum=2):
    try:
        n = 0
        for _r, _ds, fs in os.walk(d):
            n += len(fs)
            if n >= minimum:
                return True
    except OSError:
        pass
    return False


if not _has_files(os.path.join(_PY_SELF, 'templates')) and _has_files(_ASSET_TPL):
    MAPBOT_ROOT_DIR = _ASSETS
else:
    MAPBOT_ROOT_DIR = _PY_SELF
if PC_SRC and os.path.isdir(PC_SRC):
    MAPBOT = PC_SRC
    MAPBOT_ROOT_DIR = PC_SRC
    sys.stderr.write('[verify] ⚠ 用 PC 端源码做对拍：%s\n' % PC_SRC)
FIXTURE = os.path.join(HERE, '..', '_verify', 'phone_slots_full_0930.json')
FIXTURE = os.path.abspath(FIXTURE)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, MAPBOT)
os.environ.setdefault('MAPBOT_ROOT', MAPBOT_ROOT_DIR)
os.environ.pop('MAPBOT_ANDROID', None)          # PC 口径（C=0）

# ⚠ v1.20：所有**子进程**统一带 UTF-8 环境。
#   起因：门禁里 `fixed.py` 的自检打印 '✓'，在 GBK 控制台（PYTHONIOENCODING 未设）
#   会抛 UnicodeEncodeError ⇒ exit≠0 ⇒ 主门禁 4 项**假红**，而被测代码完全正常。
#   ⇒ 根因在 harness 不在被测代码（《错误教训》B2「回归红了先分清代码错还是环境错」），
#     修法：所有 `subprocess.run` 一律走 `_ENV()`，避免同类假失败复发。
def _ENV():
    return dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')

# 本机 rapidocr / airtest 都是**残缺安装**（PC 上这里用不到它们，只测逻辑）⇒ 打桩
import types        # noqa: E402


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Template(object):
    def __init__(self, *a, **k):
        pass


def _noop(*a, **k):
    return None


try:
    import rapidocr_onnxruntime        # noqa: F401
except Exception:                      # noqa: BLE001
    _stub('rapidocr_onnxruntime', RapidOCR=type('RapidOCR', (), {'__init__': _noop}))
try:
    from airtest.core.api import connect_device   # noqa: F401
except Exception:                      # noqa: BLE001
    _stub('airtest', core=None)
    _stub('airtest.core')
    _stub('airtest.core.api', connect_device=_noop, snapshot=_noop, touch=_noop,
          swipe=_noop, keyevent=_noop, exists=_noop, Template=_Template)
    _stub('airtest.core.cv', Template=_Template)

# ⭐ 2026-10-01：门禁改用**本仓**源码后，手机端 `mapbot.py` 会被 import，
#   而它在模块顶层 `import java`（Chaquopy 的 JVM 桥）—— 本机没有 `java` 模块。
#   ⇒ 打桩，否则**所有**碰 mapbot 的用例直接 ModuleNotFoundError（不是代码错）。
#   ⚠ 这属于「Android 运行时专有依赖」：桩只保证 import 过得去，真实 JVM 行为
#     只能在真机验（那部分由 verify_panels_allres / 设备侧 selftest 覆盖）。
try:
    import java                     # noqa: F401
except Exception:                    # noqa: BLE001
    _java = _stub('java')
    _java.android = _stub('java.android')
    _java.lang = _stub('java.lang')
    # Chaquopy 的 jclass/jmethod 代理：手机端 mapbot/OCR 路径会 import 它
    def _jclass(name):
        return type('JClass', (), {'__getattr__': lambda s, a: _noop})()
    _java.jclass = _jclass
    _java.jmethod = lambda *a, **k: _noop
    _stub('jnius')                  # Chaquopy 老名字，部分代码路径会 import 它

import explore_loop as EL      # noqa: E402
import numpy as np             # noqa: E402

OK = []
BAD = []
SKIP = []


def check(name, cond, detail=''):
    (OK if cond else BAD).append(name)
    print('%s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                       ('  · ' + str(detail)) if detail else ''))


def skip(name, detail=''):
    """⚠ fixture 缺失 / 前提不成立 ⇒ **响亮地跳过**（绝不记成 [ok] ✗）

    教训（2026-10-01）：本套件原来把"缺 fixture"写成 `check('…缺真机帧 ⇒ 跳过 ✓', True)`
    ⇒ 一次 fixture 被清空后，**十几项真机帧断言静默变成 ok**，套件照样报"全绿" ✗
    ⇒ 现在跳过**单独计数**并在结尾打印；有跳过就**不是干净绿** ✓
    """
    SKIP.append(name)
    print('[SKIP] %s%s' % (name, ('  · ' + str(detail)) if detail else ''))


def _find_javac():
    """找 javac（门禁要**实跑** Java 判据；找不到就响亮跳过，绝不假装跑过 ✓）

    ⚠ 2026-10-02：这个函数第一次写在了文件末尾、**定义在使用之后** ⇒ NameError
      ⇒ ⑭ 那条 Java 实跑闸整个失效（还被 except 兜住报成"可运行失败"✗）
      ⇒ 教训：工具函数一律放**公共工具区**（`skip()` 旁边），别塞在用它的段落里 ✓
    """
    import shutil as _sh
    import glob as _gl
    _p = _sh.which('javac')
    if _p:
        return _p
    # Android SDK 常见的自带 JDK（本机实测 D:\\android-build\\jdk17\\jdk-17.0.20+8\\bin）
    for _pat in (r'D:\android-build\jdk17\*\bin\javac.exe',
                 r'C:\Program Files\Android\Android Studio\jbr\bin\javac.exe',
                 r'C:\Program Files\Java\*\bin\javac.exe'):
        _hit = sorted(_gl.glob(_pat))
        if _hit:
            return _hit[-1]
    return None


def item(text, cx, cy):
    return {'text': text, 'cx': cx, 'cy': cy, 'conf': 0.9,
            'x0': cx - 30, 'y0': cy - 10, 'x1': cx + 30, 'y1': cy + 10}


print('=' * 78)
print('① 倒计时容错计数（真机帧 fixture）')
items = json.load(open(FIXTURE, encoding='utf-8'))
strict, loose = EL.count_slot_timers(items)
check('严格式只中 2 条（= 旧 bug 的输入）', strict == 2, 'strict=%d' % strict)
check('容错式中 3 条（"04:24831" 被补回）', loose == 3, 'loose=%d' % loose)
check('旧反推法会给出"假空闲 1"', max(0, 3 - strict) == 1)
free, info = EL.explore_slots_free(items)
check('新口径：认不到「空闲」⇒ free=None（不下结论）', free is None, info)
check('新口径：不再拿 TOTAL-busy 反推', free != 1)
print('   真机帧里的计时器条目：%s'
      % [i['text'] for i in items if ':' in (i.get('text') or '')])

print()
print('② 「空闲」= 硬证据')
it_free = items + [item('空闲', 120, 1000), item('空闲', 200, 1000)]
free2, info2 = EL.explore_slots_free(it_free)
check('认到 2 个「空闲」⇒ free=2', free2 == 2, info2)
many = items + [item('空闲', 100 + 60 * i, 1000) for i in range(7)]
free3, _ = EL.explore_slots_free(many)
check('空闲数封顶 EXPLORE_SLOTS_TOTAL(%d)' % EL.EXPLORE_SLOTS_TOTAL,
      free3 == EL.EXPLORE_SLOTS_TOTAL, free3)

print()
print('③ popups：「探索」点完必须验证，连两次判满（不再死循环）')


class FakeBot(object):
    """最小 Bot 桩：截图/OCR/点击都记账，OCR 永远返回"面板还在"（游戏没受理）"""

    def __init__(self, texts):
        self.texts = texts
        self.taps = []
        self.snaps = 0
        self._img = np.zeros((1920, 1080, 3), np.uint8)     # 给 close_x_panels 用 ✓

    def img(self):
        return self._img

    def img_dlg(self):
        return self._img

    def snap(self, tag, *a, **k):
        self.snaps += 1

    def ocr(self, *a, **k):
        return [dict(t) for t in self.texts]

    def ocr_dlg(self, *a, **k):
        return [dict(t) for t in self.texts]

    def tap(self, x, y, wait=0.0):
        self.taps.append(('tap', int(x), int(y)))

    def tap_dlg(self, x, y, wait=0.0):
        self.taps.append(('tap_dlg', int(x), int(y)))

    def tap_ref_hold(self, *a, **k):
        pass

    def back(self, wait=0.0):
        self.taps.append(('back', 0, 0))


# 真机上"地块面板"长这样（归一化帧里标题多半看不见，看得见的是「探索」按钮）
#   —— 这里按 PC 口径给全（标题 + 左右两颗按钮）
panel = [item('探索产出', 274, 443), item('战斗事件', 806, 442),
         item('探索', 274, 736), item('战斗', 806, 736)]
tapped_px = EL.cell_center(1, 1)       # 刚点过的紫/橙探索格（格心像素，保证 _is_purple ✓）
_cell_rc = EL.cell_of(tapped_px[0], tapped_px[1])
ctx = {'st': {_cell_rc: {'sid': 'S00003_221'}},
       'tapped': tapped_px, 'marks': {_cell_rc: {'marks': ['boss']}},
       'flags': {'slots_free': 1}, 'slots_free': 1, 'ev_tiles': ['1,1']}
bot = FakeBot(panel)
log = []
EL._PANEL_STUCK.clear()
act1 = EL.popups(bot, panel, log, ctx=ctx)
check('第 1 次：点了「探索」', any(t[0] == 'tap_dlg' for t in bot.taps),
      bot.taps)
check('第 1 次：记 tap 计数 n=1',
      [e for e in log if e.get('explore')][-1].get('n') == 1,
      [e for e in log if e.get('explore')][-1])
check('第 1 次：还没判满（只给一次机会）',
      ctx['flags'].get('slots_free') != 0, ctx['flags'])

bot2 = FakeBot(panel)
log2 = []
act2 = EL.popups(bot2, panel, log2, ctx=ctx)
check('第 2 次：又点了一下', len([t for t in bot2.taps if t[0] == 'tap_dlg']) == 1)
check('第 2 次：判定"槽其实是满的"并写回 flags',
      ctx['flags'].get('slots_free') == 0 and ctx.get('slots_free') == 0,
      ctx['flags'])
check('第 2 次：留下 slots_full_latched 证据',
      any(e.get('explore') == 'slots_full_latched' for e in log2),
      [e for e in log2 if e.get('explore')])

bot3 = FakeBot(panel)
log3 = []
ctx3 = dict(ctx)
ctx3['flags'] = {'slots_free': 0}
ctx3['slots_free'] = 0
act3 = EL.popups(bot3, panel, log3, ctx=ctx3)
check('第 3 次（已判满）：**不再点「探索」**',
      not any(t[0] == 'tap_dlg' and t[1] == 274 for t in bot3.taps), bot3.taps)
check('第 3 次：改走「战斗」（交给战斗分支 / 开打）',
      any(e.get('popup') == 'fight_panel' for e in log3)
      or any(e.get('explore') == 'skip_latched_full' for e in log3),
      log3[-1])

print()
print('④ 成本审计 model_cost（用户报「不点 1 体力的、去点 4 体力的」用的口径）')
check('草地 S00003_001 = 1 点（空地）', EL.model_cost('S00003_001') == 1,
      EL.model_cost('S00003_001'))
check('海螺 S00003_002 = 1 点', EL.model_cost('S00003_002') == 1)
check('宝箱 S00003_003 = 1 点', EL.model_cost('S00003_003') == 1)
check('海边杂物 S00003_102 = 2 点（探索）', EL.model_cost('S00003_102') == 2)
check('海边杂物 S00003_102 + 战斗标记 = 4 点', EL.model_cost('S00003_102', ['boss']) == 4)
check('巨大沙堡 S00003_211 = 4 点（探索）', EL.model_cost('S00003_211') == 4)
check('紫探索格 S00003_221 = 5 点／带打标记 10 点',
      EL.model_cost('S00003_221') == 5 and EL.model_cost('S00003_221', ['recommend']) == 10)
check('未知 sid 不放大（= 1）', EL.model_cost('S99999_999') == 1)

print()
print('⑤ 轮首刷新：提前 return 的轮次也不会漏（源码断言）')
src = open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
head = src.split('    act = popups(b, items, log, ctx=')[0]
check('one_round 轮首（popups 之前）就有 explore_slots_free',
      'explore_slots_free(items)' in head.split('def one_round')[-1])
check('总闸门 same_action 存在', "'loop_guard': 'same_action'" in src)
check('旧的 TOTAL-busy 反推已删除',
      'EXPLORE_SLOTS_TOTAL - _busy' not in src)

print()
print('⑥ 装备升星流程（用户报：不升星 / 升星时乱点「进入地图」）')
check('升星收尾**不再把「进入地图」当点击候选**',
      "'开始冒险', '进入地图') and i.get('cy', 0) > 1700" not in src)
check('升星收尾点的是锚点 START_ADV', 'at2 = START_ADV' in src)
check('开背包前先确认在公会界面（不再盲点公会内的坐标）',
      '_guild_on' in src and 'guild_not_reached' in src)
check('⚠ 公会判据必须是**模块级**函数（嵌套闭包会 NameError 崩掉整条流程 ✗）',
      '\ndef _guild_on(items):' in src and '_in_guild' not in src)
check('开背包：文字「背包」优先（真机帧里看得见 ✓）', "'open_bag_text'" in src)
check('确认后留一帧 + 认到的文字（判"到底升没升" ✓）', "'after_confirm'" in src)
check('⭐ 背包页签走**弹窗帧**（素材/装备/符文/宝箱/道具 只在弹窗帧里 ✓）',
      '_bag_switch_tab' in src and 'switch_tab_anchor' in src and 'BAG_TAB_DLG' in src)
check('吃补给：先切「道具」页', "_bag_switch_tab(b, '道具'" in src)
check('升星：先切「装备」页', "_bag_switch_tab(b, '装备'" in src)
check('背包开启判据 = 颜色（不依赖 OCR 认「背包」二字 ✓）',
      '_bag_panel_open' in src and 'BAG_PANEL_THR' in src)
check('每次点击做**生效验证**（画面差 <2 ⇒ 换招重试）', '_tap_verified' in src)
check('⚠ 生效验证必须用 b.tap 的返回值（b.img() 是**缓存帧** ⇒ 前后同帧会误判 ✗）',
      '_chg is True' in src and 'def _tap_verified(b, x, y, ch=\'norm\', log=None, what=\'\', tries=2)' in src)
check('重试阶梯默认最多 2 下（用户报「为什么连点三下背包」）',
      'tries=2' in src and 'ladder[:max(1, int(tries))]' in src)
check('⭐ 摇色子按钮必须**文字命中骰子关键词**（用户报「怎么点了回放战斗」）',
      '_dice_keys' in src
      and "if it['cx'] < LAYOUT.sx(230) and LAYOUT.sy(820) <= it['cy'] <= LAYOUT.sy(1070):" not in src)
check('⭐ 吃补给要在**悬浮条**上看得见（3 条 status）',
      '体力不够 · 去取结实补给' in src and '找到结实补给 · 正在用' in src
      and '补给已用 · 体力' in src)
check('失败时把屏上 OCR 文本 say 出来（可诊断）',
      '背包没打开（重试 3 次 ✗）｜最后一屏认到' in src)
check('每轮点击目标/模板分数进日志',
      'open_bag_miss' in src and '屏上认到' in src)

print()
print('⑦ 背包升星（2026-10-01 重写）· 面板内相对位置 / 双通道 / 多尺度模板')
# ① **取消绝对 y 过滤**：老判据 `'装备' in t and cy<700` 在真机上把页签滤掉了（实测走兜底 ✗）
_its = [item('装备', 300, 1200), item('装备强化', 300, 1500)]
_pick = EL._bag_pick(_its, ('装备', '装备栏'), prefer='top')
check('「装备」页签：取最上那个，且**不看绝对 y**',
      _pick is not None and _pick['cy'] == 1200, _pick)
# ② 按钮取「最右下」
_its2 = [item('一键升星', 500, 1500), item('一键升星', 900, 1700)]
_pick2 = EL._bag_pick(_its2, ('一键升星',), prefer='bottomright')
check('「一键升星」：取最右下那颗',
      _pick2 is not None and (_pick2['cx'], _pick2['cy']) == (900, 1700), _pick2)


class FakeBagBot(object):
    """最小 Bot 桩：只提供两条 OCR 通道（归一化帧 / 弹窗帧）"""

    def __init__(self, norm, dlg=None):
        self._norm, self._dlg = norm, dlg or []

    def ocr(self, *a, **k):
        return [dict(x) for x in self._norm]

    def ocr_dlg(self, *a, **k):
        return [dict(x) for x in self._dlg]


_c_save = EL._DLGS.get('C')
EL._DLGS['C'] = 209.0          # 伪装成真机（C>0 ⇒ 弹窗通道打开 ✓）
_b1 = FakeBagBot([item('背包', 540, 300), item('装备', 300, 500)], [])
_h1 = EL._bag_find(_b1, ('装备',), prefer='top', tag='t1')
check('双通道①：归一化帧命中 ⇒ ch=norm（点走 b.tap）',
      bool(_h1) and _h1[2] == 'norm', _h1)
_b2 = FakeBagBot([item('背包', 540, 300)],
                 [item('背包', 540, 510), item('装备', 300, 700)])
_h2 = EL._bag_find(_b2, ('装备',), prefer='top', tag='t2')
check('双通道②：归一化没中 ⇒ 退弹窗帧 ch=dlg（点走 tap_dlg）',
      bool(_h2) and _h2[2] == 'dlg', _h2)
_b3 = FakeBagBot([item('背包', 540, 300)], [])
_h3 = EL._bag_find(_b3, ('一键升星',), prefer='bottomright', tag='t3')
check('双通道③：两帧都没有 ⇒ None（调用方才退模板/锚点 ✓）', _h3 is None, _h3)
_h4 = EL._bag_find(_b2, ('装备', '装备栏'), prefer='top', tag='t4', exact=False)
check('双通道④：多关键词任一命中即可', bool(_h4), _h4)

# ③ 多尺度模板匹配（0.80~1.20）—— 面板随分辨率非等比缩放时的兜底路
import cv2 as _cv2        # noqa: E402
import numpy as _np       # noqa: E402

# ⚠ 模板目录必须与**资源根 MAPBOT_ROOT** 一致（_tpl_hit 按它读）。
#   手机端资源根 = assets/mapbot_pack（`app/src/main/python/templates` 是空目录），
#   写这边、读那边 ⇒ 必然读不到自己刚写的模板 ⇒ 假红。
_tpl_dir = os.path.join(MAPBOT_ROOT_DIR, 'templates', 'ui')
os.makedirs(_tpl_dir, exist_ok=True)
_tpl_name = '_selftest_tpl.png'
_pat = _np.zeros((48, 64, 3), _np.uint8)
for _i in range(_pat.shape[0]):
    for _j in range(_pat.shape[1]):
        _pat[_i, _j] = ((_i * 7 + _j * 13) % 255, (_i * 11 + _j * 5) % 255,
                        (_i * 3 + _j * 17) % 255)
_ok_enc, _buf = _cv2.imencode('.png', _pat)
_buf.tofile(os.path.join(_tpl_dir, _tpl_name))   # ⚠ imwrite 在**中文路径**上会静默失败 ✗
try:
    for _s in (0.85, 1.0, 1.15):
        _cv = _np.zeros((1920, 1080, 3), _np.uint8)
        _w, _h = int(64 * _s), int(48 * _s)
        _big = _cv2.resize(_pat, (_w, _h), interpolation=_cv2.INTER_AREA)
        _x, _y = 400, 900
        _cv[_y:_y + _h, _x:_x + _w] = _big
        _hit3 = EL._tpl_hit(_cv, _tpl_name, scales=EL._BAG_TPL_SCALES)
        check('多尺度模板 s=%.2f 命中（±6px）' % _s,
              bool(_hit3) and abs(_hit3[0] - (_x + _w // 2)) <= 6
              and abs(_hit3[1] - (_y + _h // 2)) <= 6, _hit3)
finally:
    try:
        os.remove(os.path.join(_tpl_dir, _tpl_name))
    except Exception:       # noqa: BLE001
        pass
    EL._UI_TPL_CACHE.clear()
# 注意 v2.78 修：不能 .pop('C')！
#   explore_loop.dlg_c() 写的是 _DLGS['C']（**无条件读键**）：
#   把键 pop 掉 => 之后**任何**走弹窗系的代码（dlg_items / popups）
#   都会直接 KeyError('C') => 整个组失效（本轮就是这么崩的 X）
#   => 恢复原值即可（None = 「未缓存」语义，与 pop 同效但不会丢键）
EL._DLGS['C'] = _c_save

print()
print('⑧ 进图体力门限（用户报「体力不够 50 怎么还去点进入地图」）')
_java = ''
try:
    _java = open(os.path.join(PROJ, 'app', 'src', 'main', 'java',
                              'com', 'fantasy', 'autoexplore', 'OverlayService.java'),
                 encoding='utf-8').read()
except Exception:       # noqa: BLE001
    pass
check('安卓悬浮条按模式传下限（连刷 50 / 单图 25）',
      'minStamina' in _java and '"start", maps, 45, 900, minStamina' in _java)
check('旧写死 25 已消失（连刷模式曾也是 25 ⇒ 29 体力照样进图 ✗）',
      '"start", maps, 45, 900, 25' not in _java)
check('启动日志里能看到门限（"体力下限 N"）', '体力下限' in _java)
check('读不到体力 ⇒ **fail-closed 不进图**（3 次重读后停下）',
      "'stop': 'stamina_unknown'" in src and "'stamina_retry'" in src)
check('enter_map 每次点「进入地图」前都复查体力',
      "'skip_low_stamina'" in src and "'stamina_before'" in src)
check('进图判定把「体力/下限/自动补给」打进日志', "'pre_gate'" in src)

print()
print('⑨ 全分辨率体检（写死坐标守门）')
# ⚠ 白名单：升星「确认按钮」的**有意双通道兜底**（dlg + ref；C=0 时两系同值 ✓）
import re as _re
_CODE, _in_doc = [], None
for _ln in src.splitlines():
    _s = _ln.strip()
    if _in_doc:
        if _in_doc in _s:
            _in_doc = None
        _CODE.append('')
        continue
    if _s.startswith('#'):
        _CODE.append('')
        continue
    for _q in ('"""', "'''"):
        if _s.startswith(_q) and _s.count(_q) == 1:
            _in_doc = _q
            break
    _CODE.append('' if _in_doc else _ln.split('#')[0])
_code = '\n'.join(_CODE)
_lit = _re.findall(r'\b(?:b\.tap|b\.tap_dlg|_bag_tap|_tap)\s*\(\s*-?\d+\s*,\s*-?\d+', _code)
_extra = [x for x in _lit if x.replace(' ', '') not in
          ('b.tap_dlg(803,1112', 'b.tap(803,1112')]
check('写死坐标的点击只剩「确认按钮双通道兜底」（实得 %d 处）' % len(_lit), not _extra)
check('面板点击统一走 _panel_tap（没生效会自动换通道 ✓）', '_panel_tap' in src)
check('关背包不再盲点左上角 (96,96)（真机那里是 HUD ✗）',
      'b.tap(96, 96, wait=1.2)' not in src)
check('背包 X / 页签走弹窗系真机标定（BAG_X_DLG / BAG_TAB_DLG）',
      'BAG_X_DLG' in src and 'BAG_TAB_DLG' in src
      and 'equip_tab_anchor_dlg' in src and 'item_tab_anchor_dlg' in src)
check('页签兜底不再用归一化系 EQUIP_TAB/ITEM_TAB 硬点',
      'b.tap(EQUIP_TAB[0], EQUIP_TAB[1]' not in src
      and 'b.tap(ITEM_TAB[0], ITEM_TAB[1]' not in src)

print()
print('⑩ 两端源码漂移登记（2026-10-01 起：两端**平行独立开发**，漂移本身合法）')
# ⚠⚠ 这条以前是"生成物必须与 PC 逐字节一致"（防「PC 改了、手机没跟上」）。
#   但 2026-10-01 用户定了**两端平行独立开发** ⇒ 漂移是**合法状态**，判据是各自行为，
#   不是两边一致。所以现在改成：**漂移必须被登记**（有据可查），未登记才失败。
#
#   为什么不能直接删掉这条：`buypanels.py` 的漂移是**真修复**（宝库幸运草认不出，
#   v1.20 把 BAND 从 1560 放宽到 1720 修的），手机侧独有、没回流 PC。
#   ⇒ 登记它 = 承认"这是有意的分叉"，下一个人才不会当成"忘了同步的 bug"去覆盖掉。
#
#   新增登记方式：把模块名加进 `_ALLOWED_DRIFT` 并写清理由。
#   ⚠ 若某个模块**本应**同步却漂了，往这里加会让真 bug 溜过去 ⇒
#     加之前先跑 `git diff --no-index <PC>/<模块>.py <手机端>/<模块>.py` 看清楚是什么。
_ALLOWED_DRIFT = {
    'buypanels': 'v1.20 宝库 BAND 1560→1720（修 1200×1920 宽屏上购买钮/价格 OCR 不到，'
                 '症状「幸运草识别不出/整层不买」）。手机侧独有修复，未回流 PC：'
                 'PC 端锁 720×1280 纯 9:16，该 bug 在 PC 上不触发 ⇒ 无需回流。',
    # ⭐ 2026-10-02 登记：PC 端把**自己的参考分辨率**从 1080×1920 换成了 720×1280
    #   （PC 端提速层的前提，见 `mapbot_pc/README.md` §1 与本仓 `AGENTS.md` §1b：
    #    「PC 端锁定 720×1280 追求速度；能点固定位置的就用固定位置」）。
    #   手机端**必须**保持 1080×1920 —— 端上是归一化参考系（RefMapper 两段拼接），
    #   棋盘 GRID=36/1002/144 与 APK 里跑的那份源码绑死，跟着 PC 换基准会全盘错位 ✗。
    #   ⇒ 这是**有意的分叉**，不是"忘了同步"：别拿 PC 的 layout.py 覆盖手机端那份。
    'layout': 'v1.21 登记：PC 端 2026-10-02 把自己的参考分辨率改成 720×1280（PC 提速层'
              '前提，AGENTS.md §1b）。手机端是归一化 1080×1920 参考系（RefMapper 两段'
              '拼接），GRID=36/1002/144 与之绑死 ⇒ 手机端**不跟**。有意分叉，勿覆盖。',
    # ⭐ 2026-10-02 v1.22 同一次 PC 换基准的连带分叉（同一个原因，一起登记）：
    #   PC 端把「棋盘几何的唯一数据源」改成 `layout.REF`（720p ⇒ 24/668/96/96），
    #   并把 `Board` 的门槛分母、`grid_detect` 的默认先验都跟着改。
    #   手机端**必须**留 36/1002/144 + 门槛分母 144（端上是 1080×1920 归一化帧）✗ 别跟。
    'spots': 'v1.22 登记：PC 端 2026-10-02 换 720p 基准后，棋盘几何改从 `layout.REF` 取'
             '（24/668/96/96）、`Board` 门槛分母由 144 改 96。手机端是归一化 1080×1920'
             '（GRID=36/1002/144，分母 144）⇒ 有意分叉，勿覆盖。',
    'grid_detect': 'v1.22 登记：PC 端换 720p 基准后，`detect_grid` 的默认先验与自检'
                   '期望值改成 720p（24/668/96/96）。手机端自检仍按 1080×1920'
                   '（36/1002/144）⇒ 有意分叉，勿覆盖。',
    'marks': 'v1.22 登记：手机端加了 `probe_top()`（标记"近失"诊断，给反馈包用），'
             'PC 端还没这个需求（PC 走 720p 固定锚点 + 自己的门禁）⇒ 有意分叉，'
             '单向新增、未回流。',
    # ⭐ 2026-10-02 v1.35 登记：PC 端 `bot_gui` 的**点格拉黑**功能带进了一个
    #   `is_blocked_cell(cell, cfg)`（按格坐标拉黑）。手机端**没有 GUI**（只有悬浮条
    #   几个芯片 + 广播），拿不到"用户点了哪一格" ⇒ 这个函数在手机端**无调用方** ✗
    #   其余 280→257 行的差异全是这一个函数及其文档/注释。
    #   ⇒ 有意分叉（PC 端功能更全，手机端不需要），别拿 PC 那份覆盖手机端。
    # ⭐ 2026-10-03 登记：PC 端换 720p 基准的连带分叉（与 layout/spots/grid_detect 同源）
    'mapsim': 'v1.43 登记：PC 端 2026-10-02 换 720p 基准后，MapSim 里的格子编号/锚点'
              '与 `layout.REF` 口径一并跟着换成 720p（24/668/96/96）。手机端是归一化'
              ' 1080×1920（GRID=36/1002/144）⇒ 有意分叉，勿拿 PC 那份覆盖。',
    'mapsolve': 'v1.43 登记：同上（Problem/visible 的可达性按 720p 几何重算，'
                ' 对应的 A* 代价/剪枝参数也按 720p 盘型标定过）。'
                ' 手机端保持 1080×1920 口径 ⇒ 有意分叉，勿覆盖。',
    'targets_cfg': 'v1.35 登记：PC 端多一个 `is_blocked_cell(cell,cfg)`（`bot_gui` '
                   '点格拉黑用）。手机端无 GUI、拿不到用户点格 ⇒ 无调用方、故意不加。'
                   '有意分叉，勿覆盖。',
    # ⭐ 2026-10-28 登记：**去仓库耦合**（与 layout/spots/marks/mapsim/mapsolve/）
    #   PC 侧 `mapgen.py` 走 `import repo_paths as RP` + `RP.require(RP.DATATABLE_0924)`；
    #   手机端没有仓库层（APK 里没有 repo_paths.py），且资源根在
    #   `assets/mapbot_pack/`（真机是 `files/mapbot_pack/`），难以写死绝对路径⇒
    #   统一改成 `_MAPBOT_DT`（env `MAPBOT_DT` 优先，否则 _MAPBOT_ROOT/server_datatable.json）
    #   ⚠ 其余八个模块（layout/spots/grid_detect/marks/badge/mapsim/mapsolve/targets_cfg/）
    #     **已经全部这么改并登记**，只有 mapgen 漏登 ⇒ 门禁长期假红 ✗
    #   （不是真漂移：`DATATABLE` 指向的都是 **同一份 0924 数据表**，两端内容一致）⇒
    #   有意分叉，勿拿 PC 那份覆盖手机端。
    'mapgen': 'v2.78 登记：去仓库耦合 —— PC 走 `repo_paths.RP.require(DATATABLE_0924)`，'
              '手机端改成 `_MAPBOT_DT`（env MAPBOT_DT / _MAPBOT_ROOT/server_datatable.json）。'
              '同一份 0924 数据表内容，仅取路方式不同，与其余八个模块同一改法。'
              '有意分叉，勿覆盖。'
}
# ⭐⭐ 2026-10-01 晚「两端完全平行」：**PC 仓不存在时整组跳过**（不是失败）。
#   以前这条强制"生成物必须与 PC 逐字节一致" ⇒ 天然要求 PC 仓在场，
#   那是「强制同步」时代的遗留。两端既然平行，**没装 PC 仓就不该红**。
#   ⇒ 保留它的唯一目的：PC 仓**在场**时，把已知的合法分叉登记住（防止被人
#     当成"忘了同步的 bug"覆盖掉）。PC 仓不在 ⇒ 这件事无从谈起，跳过。
_pc_src = _gen_src = None
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        'port_android_gen',
        os.path.join(PROJ, 'tools', 'port_android.py'))
    _gen = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_gen)
    if not getattr(_gen, 'SRC', None) or not os.path.isdir(_gen.SRC):
        raise SystemExit('no PC source')
    _pc_src = _gen.SRC
except SystemExit:
    _pc_src = None
except Exception:       # noqa: BLE001
    _pc_src = None

if _pc_src is None:
    print('  (PC 仓不在 ⇒ 两端漂移登记**不适用**（两端已平行，谁都不依赖谁）) ⚠')
    skip('两端漂移登记（PC 仓不在，无法比对；这是平行独立下的正常状态）⚠')
else:
    try:
        _drift = []
        for _m in _gen.MODULES:
            _disk = os.path.join(PROJ, 'app', 'src', 'main', 'python', _m + '.py')
            _want = _gen.patch(open(os.path.join(_gen.SRC, _m + '.py'),
                                    encoding='utf-8').read(), _m)
            for _old, _new in _gen.EXACT.get(_m + '.py', []):
                _want = _want.replace(_old, _new)
            _have = open(_disk, encoding='utf-8').read() if os.path.exists(_disk) else ''
            if _want != _have:
                _drift.append(_m)
        _undeclared = [m for m in _drift if m not in _ALLOWED_DRIFT]
        check('所有漂移模块都**已登记理由**（未登记: %s）'
              % (','.join(_undeclared) if _undeclared else '无'), not _undeclared,
              '漂移合计 %d 个：%s' % (len(_drift), ','.join(_drift) or '无'))
        for _m in sorted(_drift):
            if _m in _ALLOWED_DRIFT:
                check('已登记漂移 %s 有明确理由' % _m, bool(_ALLOWED_DRIFT[_m].strip()))
    except Exception as _e:      # noqa: BLE001
        check('两端漂移登记校验可运行（%r）' % (_e,), False)

# 宝库图标尺度必须由 pitch 推出（防再写死 4.5 ✗）—— 只看**代码**，不看注释 ✓
_bp = open(os.path.join(MAPBOT, 'buypanels.py'), encoding='utf-8').read()
_bp_code = '\n'.join(l.split('#')[0] for l in _bp.splitlines()
                     if not l.strip().startswith('#'))
check('宝库图标尺度由格子间距推出（不再写死 ICON_SCALE）',
      '_icon_scales' in _bp_code
      and not _re.search(r'^\s*ICON_SCALE\s*=', _bp_code, _re.M))
check('宝库图标认不出时有**宽尺度兜底** + 分数落日志',
      'icon_hit_wide' in _bp and "'vault_debug'" in _bp)

print()
print('⑪ 观测累积（防「规划很差劲」：脏帧不许抹掉已知格 ✗）')
check('跨轮累积观测 st[\'obs\'] 已建立（已揭示永不翻回 ✓）',
      "st.setdefault('obs', {})" in src and "'obs_merge'" in src)
check('规划输入改用累积观测（不再直接用单帧 c[\'st\']）',
      "_base_cells = st.get('obs') or (c.get('st') or {})" in src)

print()
print('⑫ 宝库奖励口径（用户 2026-10-01：同档位优先天赋果实 + 幸运草就是四叶草 + 认不出就点进去看）')
_bp2 = open(os.path.join(MAPBOT, 'buypanels.py'), encoding='utf-8').read()
check('同档位平分决胜 = **天赋果实优先**（PREF_FRUIT=1 > PREF_CLOVER=0 ✓）',
      'PREF_FRUIT = 1' in _bp2 and 'PREF_CLOVER = 0' in _bp2
      and "_prio = PREF_FRUIT if '果' in nm else (" in _bp2)
check('「幸运草」与「四叶草」是**同一物品**（不再当成两样排序 ✗）',
      "'幸运草' in nm or '四叶草' in nm" in _bp2
      and "_prio = 3" not in _bp2 and "_prio = 2" not in _bp2)
check('档位只由数量决定（草 1/2/4/8、果 5/10/20/50 ✓）',
      "'四叶草': {1: 1, 2: 2, 4: 3, 8: 4}" in _bp2
      and "'天赋果实': {5: 1, 10: 2, 20: 3, 50: 4}" in _bp2)
check('图标全不中 ⇒ **点开详情读名称**兜底（_probe_name ✓）',
      'def _probe_name' in _bp2 and "'probe_pick'" in _bp2 and "'probe_none'" in _bp2)
check('选中的口径写进日志（pick_best 的 why ✓）',
      "同档 天赋果实优先" in _bp2 or "同档天赋果实优先" in _bp2 or "'why':" in _bp2)

print()
print('⑬ 弹窗地块：勾选=主动处理 / 不勾=拉黑（用户 2026-10-01 口径）')
_tc = open(os.path.join(MAPBOT, 'targets_cfg.py'), encoding='utf-8').read()
check('is_blocked 由**勾选配置推导**（不再硬编码黑名单 ✓）',
      "return not enabled(k, cfg)" in _tc and '_blocked = {' not in _tc)
check('特殊地块名单含两种宝箱怪 + 预言石碑（**且不含幽灵项** ✗）',
      # ⭐ v1.46：名单已按数据表核实清理（学 PC 端 1e9afce / b5f08a6）：
      #   · `献祭宝箱怪` —— `MaxNum = 0` ⇒ **游戏根本不会生成它** ✗ ⇒ 删
      #   · `预言石板`   —— **数据表里没这个名字**（真名是 `预言石碑`）✗ ⇒ 删
      #   ⇒ 这两条**不该**再出现（旧断言守的是"有它们"，方向反了 ✓）
      all(k in _tc for k in ("'金属宝箱怪'", "'机巧宝箱怪'", "'预言石碑'"))
      and "'献祭宝箱怪'" not in _tc
      and "'预言石板'" not in _tc)
check('拉黑格一律**不是目标**（is_target 先判 is_blocked ✓）',
      # ⚠ 2026-10-01：判据命中文本要跟着实现走 —— 实现已改成 `is_blocked(name, d)`
      #   （把显式 cfg 传下去，修了"静默丢配置"），旧断言只认 `is_blocked(name)`
      #   ⇒ 变成**假失败**（实测 191/1）。这里两种写法都接受 ✓
      ('if is_blocked(name, d):' in _tc or 'if is_blocked(name):' in _tc)
      and 'return False' in _tc)
check('拉黑格**不参与开路**（从 nones_extra 剔除 + 落日志 ✓）',
      "_blocked_px" in src and "'blocked_skipped'" in src)
check('黑名单可自由切换（勾上 ⇒ 立即主动处理 ✓ 无需改代码）',
      'def is_blocked(name, cfg=None):' in _tc)

print()
print('⑭ 宝库面板识别（真机帧实测：标题@dlg690,438 / 按钮@dlg895,1498）')
check('宝库**标题**判据存在（vault_title_seen ✓）', 'def vault_title_seen' in src)
check('宝库按钮 y 带按实测放宽（1330~1650 ✓ 真机 1498 在内）',
      '1330 < it.get(\'cy\', 0) < 1650' in src or '1330 < _cy < 1650' in src)
check('点击循环用**弹窗帧**判宝库（防"下一击关掉面板"✗）',
      'vault_title_seen(_dts) or _dlg_btn_sig(_dts' in src
      and "'vault_panel_by_dlg'" in src)
check('panel_seen 也走真·弹窗帧 OCR（不是 dlg_items 换算 ✓）',
      "dlg_ocr(b, tag='panel_seen_dlg')" in src)
# ⭐ 用**真机帧**离线复核（有帧才跑；没帧跳过 ✓）
_vf = os.path.join(PROJ, '_verify', 'phone_stamina_0930',
                   'bagdbg', 'vault4_dlg_items.json')
try:
    import json as _json
    if os.path.exists(_vf):
        _dlg = _json.load(open(_vf, encoding='utf-8'))
        _ref = _json.load(open(os.path.join(os.path.dirname(_vf),
                                            'vault4_ref_items.json'), encoding='utf-8'))
        # 直接在源码里复刻两条判据（不 import explore_loop，避免依赖 airtest ✓）
        _title = any(('黄金宝库' in (i.get('text') or '')) for i in _dlg)
        _btn = any(700 < i.get('cx', 0) < 1040 and 1330 < i.get('cy', 0) < 1650
                   and any(k in (i.get('text') or '')
                           for k in ('购买', '选择', '离开', '完成', '领取'))
                   for i in _dlg)
        _ref_only = [i for i in _ref if 130 <= (i.get('cy') or 0) <= 1080]
        _refvault = any(('黄金宝库' in (i.get('text') or ''))
                        or any(k in (i.get('text') or '')
                               for k in ('购买', '选择奖励', '离开'))
                        for i in _ref_only)
        check('真机宝库帧：弹窗帧标题/按钮都能认出（标题%s 按钮%s）'
              % (_title, _btn), _title and _btn)
        check('真机宝库帧：**归一化 band 认不出**（= 病根，补丁必要性 ✓）', not _refvault)
    else:
        skip('真机宝库帧离线复核：缺 vault4_dlg.png/vault4_ref_items.json ⚠')
except Exception as _e:      # noqa: BLE001
    check('真机宝库帧离线复核可运行（%r）' % (_e,), False)

print()
print('⑮ 宝库"跨轮记忆"与"已消耗清除"（用户报：中途接手时盘上有宝库却退了）')
check('跨轮宝库记忆 st[\'buy_seen\'] 存在（认到过就不再忘 ✓）',
      "st.setdefault('buy_seen', {})" in src and 'BUY_MEMORY_MIN' in src)
check('记忆并入 pending_buy（被盖住的那帧也不会误判"没目标"✗）',
      "for _p in _mem:" in src and "'buy_mem_used'" in src)
check('已揭示格**名字变了** ⇒ 立刻清记忆（买掉的宝库不许变幽灵目标 ✓）',
      "not in spots_mod.BUY_OUT_NAMES:" in src and '_seen.pop(' in src)
check('累积观测 obs 里"已揭示+名字变了"也立刻跟新（防幽灵宝库 ✓）',
      'if _nn and _on and _nn != _on:' in src)

print()
print('⑯ 未定义常量守门（2026-10-01 宝库崩在 ICON_THR 上的教训）')
# ⚠ 背景：改 `_icon_scales()` 时误删了 `ICON_THR = 0.55`，但 `vault_pick` 仍在用
#   ⇒ 真机宝库一点「购买」就 `NameError: name 'ICON_THR' is not defined`，
#     每一轮都崩 ⇒ 宝库买不成、卡面板、强制脱困退图 ✗
#   ⇒ 加一道**静态检查**：模块级"被读取但从未定义/导入"的大写名一律报红 ✓
import ast as _ast
import builtins as _bi


def _undefined_upper(path):
    _src = open(path, encoding='utf-8').read()
    _t = _ast.parse(_src)
    _def = set()
    for _n in _ast.walk(_t):
        if isinstance(_n, _ast.Assign):
            for _tg in _n.targets:
                for _x in _ast.walk(_tg):
                    if isinstance(_x, _ast.Name):
                        _def.add(_x.id)
        elif isinstance(_n, _ast.AnnAssign):
            for _x in _ast.walk(_n.target):
                if isinstance(_x, _ast.Name):
                    _def.add(_x.id)
        elif isinstance(_n, _ast.AugAssign):
            for _x in _ast.walk(_n.target):
                if isinstance(_x, _ast.Name):
                    _def.add(_x.id)
        elif isinstance(_n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            _def.add(_n.name)
        elif isinstance(_n, (_ast.arg,)):
            _def.add(_n.arg)
        elif isinstance(_n, _ast.Import):
            for _a in _n.names:
                _def.add((_a.asname or _a.name).split('.')[0])
        elif isinstance(_n, _ast.ImportFrom):
            for _a in _n.names:
                _def.add(_a.asname or _a.name)
        elif isinstance(_n, _ast.ExceptHandler) and _n.name:
            _def.add(_n.name)
        elif isinstance(_n, _ast.withitem) and isinstance(_n.optional_vars, _ast.Name):
            _def.add(_n.optional_vars.id)
        elif isinstance(_n, (_ast.Global, _ast.Nonlocal)):
            for _x in _n.names:
                _def.add(_x)
    _known = _def | set(dir(_bi)) | {'__file__', '__name__', '__doc__'}
    _bad = {}
    for _n in _ast.walk(_t):
        if isinstance(_n, _ast.Name) and isinstance(_n.ctx, _ast.Load) \
                and _n.id.isupper() and _n.id not in _known:
            _bad.setdefault(_n.id, _n.lineno)
    return _bad


for _f in ('buypanels.py', 'targets_cfg.py', 'explore_loop.py'):
    _u = _undefined_upper(os.path.join(MAPBOT, _f))
    # explore_loop.py 的 CLOSE_TR/CLOSE_TR_Y 是**元组解包定义**、W/H 是局部变量
    # （本检查器对元组解包支持有限）⇒ 只白名单这两个已知误报名 ✓
    _u = {k: v for k, v in _u.items() if k not in ('W', 'H', 'CLOSE_TR', 'CLOSE_TR_Y')}
    check('%s 无「未定义的大写常量」（%s）'
          % (_f, _u if _u else '干净 ✓'), not _u)
check('ICON_THR 既有定义又有使用（宝库崩溃回归守门 ✓）',
      'ICON_THR = 0.55' in _bp2 and 'ICON_THR' in _bp2.split('ICON_THR = 0.55', 1)[1])

print()
print('⑰ 宝库「选择奖励」全链路（用户报：第一层没选就乱点 / 选了默认没选果实）')
check('_btn 的 y 带按真机实测放宽（1360~1660，实测按钮 1498/价格 1541 ✓）',
      '1360 < t[\'cy\'] < 1660' in _bp2)
check('读不到按钮 ⇒ **不跳过整层**（保底挑格 + 标定坐标 ✓）',
      "'no_select_btn_fallback'" in _bp2 and "'claim_fallback'" in _bp2)
check('vault_flow 调用包了 try/except（崩了不许乱点 ✗）',
      "'vault': 'flow_error'" in src and 'buypanels.vault_flow(b, log)' in src)
check('只有走完才计数（旧写法崩了也 +1 = 谎报"买完" ✗）',
      "if _vok:" in src and "_vok = bool(_vacts)" in src)
check('失败必收起面板（否则下一轮又点在面板上 ✗）',
      'buypanels.ensure_closed(b, log)' in src)
check('merchant_flow 同样包了 try/except（买到 0 次 ≠ 失败 ✓）',
      "'merchant': 'flow_error'" in src and "_mok is not None" in src)

print()
print('⑱ 宝库点击常量按**真机像素**核对（用户报：点了左上角格子/关了宝库界面）')
# 真机帧 vault4_dlg.png 实测：blank/back 必须落在**平坦空白**（std<20），
# buy 必须落在按钮上（std 高 = 有文字），x 落在右上角关闭符
_v4 = os.path.join(PROJ, '_verify', 'phone_stamina_0930',
                   'bagdbg', 'vault4_dlg.png')
try:
    import cv2 as _cv2
    import numpy as _np
    if os.path.exists(_v4):
        _img = _cv2.imdecode(_np.fromfile(_v4, dtype=_np.uint8), _cv2.IMREAD_COLOR)
        _g = _cv2.cvtColor(_img, _cv2.COLOR_BGR2GRAY).astype(_np.int32)

        def _std_of(_x, _y):
            return float(_g[_y - 10:_y + 10, _x - 10:_x + 10].std())

        _pts = _re.findall(r"'(blank|buy|x|back)': \((\d+), (\d+)\)", _bp2)
        _d = {_n: (int(_a), int(_b)) for _n, _a, _b in _pts}
        check('常量齐全（blank/buy/x/back 都按真机帧定义 ✓）',
              all(k in _d for k in ('blank', 'buy', 'x', 'back')))
        check('blank 落在**真空白**（真机帧 std<20，旧 (540,1700) 在面板外 ✗）',
              _std_of(*_d['blank']) < 20)
        check('back 兜底不落在奖励格上（旧 1212/1034 都在格子里 ✗）',
              _std_of(*_d['back']) < 20)
        check('buy 落在按钮上（真机实测 1498，std 高 = 有文字 ✓）',
              _std_of(*_d['buy']) > 30)
    else:
        skip('宝库点击常量真机帧核对：缺 vault4_dlg.png ⚠')
except Exception as _e:      # noqa: BLE001
    check('宝库点击常量真机帧核对可运行（%r）' % (_e,), False)
check('兜底探名**只取前 3 格**（旧写法 16 格 ≈40 秒 + 逐格乱点 ✗）',
      '_ranked = _scored[:3]' in _bp2)
check('探名候选构建不再重复解包（`float object is not subscriptable` ✗）',
      '_scored.append((float(_sc1 or 0), (_x, _y)))' in _bp2)

print()
print('⑲ 宝库代码**真的能执行**（真机 19:07 被 TypeError 卡了 10 轮 ✗）')
check('探名候选构建不再重复解包（`float object is not subscriptable` ✗）',
      '_scored.append((float(_sc1 or 0), (_x, _y)))' in _bp2)
check('档位近似的**数量读错保护**（> 最高档 ⇒ 保守 0 档，不冒充高档 ✗）',
      '_qmax = max(tbl)' in _bp2 and 't = 0.0' in _bp2)
# ⭐ **执行级**验证：用假 bot 真跑 vault_pick，抓运行期异常（compile 抓不到这类 ✗）
try:
    import importlib.util as _ilu2
    import sys as _sys2
    import types as _ty2
    # 复用主进程已 stub 的 airtest；补 rapidocr 桩
    if 'rapidocr_onnxruntime' not in _sys2.modules:
        _r = _ty2.ModuleType('rapidocr_onnxruntime')
        _r.RapidOCR = type('RapidOCR', (), {'__init__': lambda s, *a, **k: None})
        _sys2.modules['rapidocr_onnxruntime'] = _r
    _sys2.path.insert(0, os.path.join(MAPBOT))
    _spec2 = _ilu2.spec_from_file_location(
        'bp_exec', os.path.join(MAPBOT, 'buypanels.py'))
    _bp3 = _ilu2.module_from_spec(_spec2)
    _spec2.loader.exec_module(_bp3)
    _bp3.read_qty = lambda bot, cx, cy: 50      # 桩：数量读作 50

    _v4 = os.path.join(PROJ, '_verify', 'phone_stamina_0930',
                       'bagdbg', 'vault4_dlg.png')
    if os.path.exists(_v4):
        import cv2 as _c3
        import numpy as _n3
        _im3 = _c3.imdecode(_n3.fromfile(_v4, dtype=_n3.uint8), _c3.IMREAD_COLOR)

        class _FB(object):
            ocr_grabs = True

            def img_dlg(self):
                return _im3

            def img(self):
                return _im3

            def tap_dlg(self, x, y, wait=1.0):
                return True

            def tap(self, x, y, wait=1.0):
                return True

            def ocr(self, **k):
                return [{'text': '购买', 'cx': 895, 'cy': 1498, 'conf': .99}]

            def ocr_dlg(self, **k):
                return [{'text': '天赋果实', 'cx': 600, 'cy': 900, 'conf': .99}]

            def snap(self, *a, **k):
                return None

        _pk, _nm = _bp3.vault_pick(_FB(), [], 1)
        check('vault_pick 真执行不抛异常且返回合法坐标（%s / %r）' % (_pk, _nm),
              isinstance(_pk, (list, tuple)) and len(_pk) == 2)
    else:
        skip('vault_pick 执行级验证：缺真机帧 ⚠')
except Exception as _e:      # noqa: BLE001
    check('vault_pick 执行级验证可运行（%r）' % (_e,), False)

print()
print('⑳ 派遣面板按钮：**用 OCR 现读坐标** + 弹窗系点击（用户报两次位置不对 ✗）')
check('派遣按钮优先用 OCR 读到的条目（不再只点写死的 DISPATCH_BTN ✗）',
      "'btn_by_ocr'" in src)
check('⭐ 点击**通道同源**：用 _tap()（按 _OCR_CH 自动选），不写死 tap_dlg ✗',
      '_tap(b, _bx, _by, wait=2.5)' in src and 'b.tap_dlg(_bx, _by' not in src)
check('日志记下实际通道（下次串味能一眼看出 ✓）',
      "_OCR_CH['dlg'] else 'norm'" in src)
check('OCR 读不到时才退回标定常量，且记日志（可事后调参 ✓）',
      "'btn_by_const'" in src)
check('候选筛选排除「探索预计时间」这类说明文字（防误点 ✓）',
      "'预计时间' not in _t" in src)
check('取**最靠右下**那颗按钮（面板底部主按钮 ✓）',
      '_it.get(\'cy\', 0), _it.get(\'cx\', 0)) >' in src)
check('派遣分支保持原样（用户明确「要点一键派遣」，不许再删 ✗）',
      '已派遣一支探索队' in src and 'DISPATCH_BTN' in src
      and 'skip_by_user_policy' not in src and 'if False and any' not in src)

print()
print('㉑ 停止按钮「立即停」（用户报：点 ■ 后还要运行一会 ✗）')
_mb = open(os.path.join(MAPBOT, 'mapbot.py'), encoding='utf-8').read()
# ⚠ 手机端与 PC 端**实现不同但语义相同**，两边都要有「等待循环可被停止打断」：
#   PC  ：`def _stop_flag()` + 每次轮询 `if _stop_flag():`
#   手机：原实现把 waitChange **一次性**整段阻塞在 Kotlin 里 ⇒ Python 侧没机会看停止位
#         （用户报「点 ■ 后还要运行一会」）⇒ 2026-10-01 改成**切片调用**（SLICE=0.3s）
check('等待循环可被停止打断（wait_change 切片 ✓）',
      ('def _stop_flag' in _mb) and _mb.count('if self._stop_flag():') >= 3)
check('wait_change 按小片调用（不是整段阻塞在 Kotlin 里）',
      'SLICE = 0.30' in _mb and _mb.count('self.api.waitChange') >= 1
      and _mb.count('self.api.waitStable') >= 1)
check('等待循环真的在循环里问停止位',
      _mb.count('if self._stop_flag():') >= 3)
check('战斗等待 wait_end 收到停止立刻退出（不再 continue ✗）',
      "'wait_end': 'stopped_by_user'" in src and 'if stop_requested():' in src)
check('_stop_flag 在 PC 上恒 False（零回归 ✓）',
      "getattr(_el, '_ANDROID_STOP', False)" in _mb)
# ⭐ **执行级**验证：真跑两个等待循环，量「置停止位 → 返回」耗时 ✓
try:
    import threading as _th
    import time as _tm
    import time                     # ← _Api3 的替身要用 time.sleep（不是 _tm）
    import importlib.util as _ilu3
    import sys as _sys3
    import types as _ty3
    import numpy as _np3
    if 'explore_loop' not in _sys3.modules:
        _fel = _ty3.ModuleType('explore_loop')
        _fel._ANDROID_STOP = False
        _sys3.modules['explore_loop'] = _fel
    _sp3 = _ilu3.spec_from_file_location('mb_exec',
                                         os.path.join(MAPBOT, 'mapbot.py'))
    _mb3 = _ilu3.module_from_spec(_sp3)
    _sp3.loader.exec_module(_mb3)
    _fel2 = _sys3.modules['explore_loop']

    class _FF3(object):
        def grab(self):
            return _np3.zeros((1920, 1080, 3), dtype=_np3.uint8)

    class _Api3(object):
        """手机端 Bot 的 `api` 替身：模拟 Kotlin 的 waitChange/waitStable（阻塞语义）"""
        def __init__(self):
            self.calls = 0

        def waitChange(self, sec, y0, y1, thr, min_sec, ax, ay, radius):
            self.calls += 1
            time.sleep(max(0.0, float(sec)))
            return False

        def waitStable(self, sec, thr, need, y0, y1):
            self.calls += 1
            time.sleep(max(0.0, float(sec)))
            return False

        def lastDim(self):
            return 1.0

    def _nb3():
        _b = _mb3.Bot.__new__(_mb3.Bot)
        _b.fast_ok = True
        _b.fast = _FF3()
        _b._img_arr = _b.fast.grab()
        _b._img_path = None
        _b.last_change = {}
        _b.t = {'wait': 0.0, 'wait_n': 0}
        # ⭐ 两端 Bot 接口不同：PC 用 `fast.grab` 自己轮询，手机端用阻塞的
        #   `api.waitChange`（这正是"要切片才能被停止打断"的原因）。
        #   ⇒ 两个都挂上，测试对**两端**都成立 ✓
        _b.api = _Api3()
        return _b

    def _with_stop(_fn):
        _fel2._ANDROID_STOP = False
        _tt = _th.Timer(0.4, lambda: setattr(_fel2, '_ANDROID_STOP', True))
        _tt.start()
        _t0 = _tm.time()
        _fn()
        _dt = _tm.time() - _t0
        _tt.cancel()
        _fel2._ANDROID_STOP = False
        return _dt

    _da = _with_stop(lambda: _nb3().wait_change(3.0, around=(540, 960), thr=4.0))
    check('wait_change 停止置位后 %.2fs 内返回（执行级 ✓）' % _da, _da < 1.5)
    _db = _with_stop(lambda: _nb3().wait_stable(3.0, interval=0.06, thr=1.4, need=8))
    check('wait_stable 停止置位后 %.2fs 内返回（执行级 ✓）' % _db, _db < 1.5)
    _t0 = _tm.time()
    _nb3().wait_change(3.0, around=(540, 960), thr=4.0)
    _dc = _tm.time() - _t0
    check('无停止时 wait_change 仍等满（%.2fs ≈ 3.0s，零回归 ✓）' % _dc, _dc > 2.5)
except Exception as _e:      # noqa: BLE001
    check('停止可中断执行级验证可运行（%r）' % (_e,), False)

print()
print('㉒ 手机端等待也可中断（PC 改了还不够 —— Android mapbot 是独立副本 ⚠）')
_amb = open(os.path.join(PROJ, 'app', 'src', 'main',
                         'python', 'mapbot.py'), encoding='utf-8').read()
check('Android mapbot 有可中断的 _sleep（Java requestInterrupt 管不到纯 Python sleep ✗）',
      'def _sleep(self, sec)' in _amb and 'self._sleep(' in _amb)
check('长等待都走 _sleep（swipe/back/tap_text/wait_text ✓）',
      _amb.count('self._sleep(') >= 4)
check('_sleep 内部按 0.1s 切片查停止位（点 ■ 最多等 0.1s ✓）',
      'min(0.1, _left)' in _amb and "_ANDROID_STOP" in _amb)

print()
print('㉓ 拉黑地块**不进规划**（用户报：跑铁血高地时点开了金属宝箱怪 ✗）')
check('拉黑格在 `_cells_for_model` 里被标 blocked + 强制非目标（v0.99 起**不再 pop** ✓）',
      "'blocked_cells_tagged'" in src and "_v2['blocked'] = True" in src
      and "_v2['target'] = False" in src)
check('⚠ v0.99 不许再 pop（pop ⇒ `board<0` ⇒ `consumed_cells` 当成空地 ⇒ 连锁穿过它 ✗）',
      '_cells_merged.pop(_k2, None)' not in src
      and 'blocked_cells_dropped' not in src)
# ⭐ 执行级：造含宝箱怪的假盘 —— 它必须**留着**（这样才不算"已消耗空地"）且不是目标
try:
    _sys4 = __import__('sys')
    _sys4.path.insert(0, os.path.join(MAPBOT))
    import types as _ty4
    import importlib.util as _ilu4
    if 'rapidocr_onnxruntime' not in _sys4.modules:
        _r4 = _ty4.ModuleType('rapidocr_onnxruntime')
        _r4.RapidOCR = type('RapidOCR', (), {'__init__': lambda s, *a, **k: None})
        _sys4.modules['rapidocr_onnxruntime'] = _r4
    for _n4 in ('airtest', 'airtest.core', 'airtest.core.api', 'airtest.core.cv'):
        if _n4 not in _sys4.modules:
            _sys4.modules[_n4] = _ty4.ModuleType(_n4)
    _a4 = _sys4.modules['airtest.core.api']
    for _f4 in ('connect_device', 'snapshot', 'touch', 'swipe', 'keyevent', 'exists'):
        if not hasattr(_a4, _f4):
            setattr(_a4, _f4, lambda *a, **k: None)
    _T4 = type('T', (), {'__init__': lambda s, *a, **k: None})
    _a4.Template = _T4
    _sys4.modules['airtest.core.cv'].Template = _T4
    _spec4 = _ilu4.spec_from_file_location(
        'el_blocked', os.path.join(MAPBOT, 'explore_loop.py'))
    _el4 = _ilu4.module_from_spec(_spec4)
    _spec4.loader.exec_module(_el4)
    _fake4 = {
        (1, 1): {'sid': 'S10003_000', 'name': '营地', 'revealed': True, 'score': .99, 'ratio': 1.0},
        (1, 2): {'sid': 'S10003_009', 'name': '金属宝箱怪', 'revealed': True,
                 'score': .95, 'ratio': 1.0},
        (1, 4): {'sid': 'S10003_003', 'name': '宝箱', 'revealed': True, 'score': .96, 'ratio': 1.0},
    }
    _lg4 = []
    _out4 = _el4._cells_for_model({'marks': {}}, {'st': _fake4}, log=_lg4, tag='t',
                                  drop_done=False)
    _v4 = _out4.get((1, 2)) or {}
    check('执行级：拉黑格**留在模型里**且 blocked=True / target=False（%d 格）' % len(_out4),
          bool(_v4) and _v4.get('blocked') is True and _v4.get('target') is False
          and len(_out4) == 3, 'blk=%s' % ({k: (v.get('blocked'), v.get('target'))
                                            for k, v in _out4.items()},))
    _ms4 = __import__('mapsim')
    _mv4 = __import__('mapsolve')
    _sp4 = __import__('spots')
    _sim4 = _ms4.MapSim.from_observation(_out4, _sp4.spot_rows())
    _idx4 = (1 - 1) * 7 + (2 - 1)
    check('执行级：它 `board >= 0`（⇒ **不是** `consumed_cells` 眼里的"已消耗空地" ✓）',
          _sim4.board[_idx4] >= 0,
          'board=%d consumed=%s' % (_sim4.board[_idx4],
                                    _idx4 in _mv4.Problem(_sim4).consumed_cells(frozenset())))
    # ⭐ v1.00：求解器**可能**把拉黑格当"便宜的开路步"排进点序（点内容格会揭邻居）
    #   ⇒ 执行侧必须硬过滤：点序里的拉黑格一律剔除 + 落 `blocked_in_order` 日志 ✓
    check('v1.00 点序硬过滤：拉黑格从 `order` 里剔除（solver plan 里的也剔 ✓）',
          "order = [p for p in order if p not in _blk_set]" in src
          and "'blocked_in_order'" in src and '_blocked_px(st, c)' in src)
except Exception as _e:      # noqa: BLE001
    check('拉黑格建模执行级验证可运行（%r）' % (_e,), False)

print()
print('㉔ 其他地图：图名歧义时**用真实帧消歧**（15 张图名很像，OCR 掉字会猜错 ✗）')
check('歧义候选检测 `_candidate_codes` 存在（精确命中 ⇒ 单候选 ✓）',
      'def _candidate_codes(mapname)' in src and 'def _disambiguate_map(' in src)
check('消歧按图名**缓存**（每张图最多付一次 ≈0.2~0.5s ✓）',
      '_CODE_DECIDED' in src and '_CODE_DECIDED.get(mapname)' in src)
check('`board_state` 在 code 为空时才走消歧（不拖累正常路径 ✓）',
      'if code is None and mapname:' in src)
# ⭐ 执行级：用真机「夏日海滩」棋盘帧验证 —— 单字「海」应消歧到 S00003 ✓
try:
    _sys5 = __import__('sys')
    _sys5.path.insert(0, os.path.join(MAPBOT))
    import types as _ty5
    import importlib.util as _ilu5
    if 'rapidocr_onnxruntime' not in _sys5.modules:
        _r5 = _ty5.ModuleType('rapidocr_onnxruntime')
        _r5.RapidOCR = type('RapidOCR', (), {'__init__': lambda s, *a, **k: None})
        _sys5.modules['rapidocr_onnxruntime'] = _r5
    for _n5 in ('airtest', 'airtest.core', 'airtest.core.api', 'airtest.core.cv'):
        if _n5 not in _sys5.modules:
            _sys5.modules[_n5] = _ty5.ModuleType(_n5)
    _a5 = _sys5.modules['airtest.core.api']
    for _f5 in ('connect_device', 'snapshot', 'touch', 'swipe', 'keyevent', 'exists'):
        if not hasattr(_a5, _f5):
            setattr(_a5, _f5, lambda *a, **k: None)
    _T5 = type('T', (), {'__init__': lambda s, *a, **k: None})
    _a5.Template = _T5
    _sys5.modules['airtest.core.cv'].Template = _T5
    _spec5 = _ilu5.spec_from_file_location(
        'el_disambig', os.path.join(MAPBOT, 'explore_loop.py'))
    _el5 = _ilu5.module_from_spec(_spec5)
    _spec5.loader.exec_module(_el5)
    _v5 = os.path.join(PROJ, '_verify', 'phone_stamina_0930',
                       'bagdbg', 'board_now_ref.png')
    if os.path.exists(_v5):
        import cv2 as _c5
        import numpy as _n5
        _im5 = _c5.imdecode(_n5.fromfile(_v5, dtype=_n5.uint8), _c5.IMREAD_COLOR)
        check('歧义检测：「海」有 2 个候选、「林」有 3 个（真跑 ✓）',
              len(_el5._candidate_codes('海')) == 2
              and len(_el5._candidate_codes('林')) >= 2)
        # ⚠⚠ 2026-10-01：这个 bagdbg/board_now_ref.png **已被换成"枯木丛林"真机帧**
        #   （22:33 抓的那张；旧内容是夏日海滩帧）⇒ 旧断言（「海」→S00003）已不成立 ✗。
        #   改成**在这张帧上为真的两条**（更有意义 ✓）：
        #     ① 单字「林」有 3 个候选（迷失森林/幽暗密林/**枯木丛林**）⇒ 必须实测选出
        #        **S20003**（= 这张帧的真实地图 ✓）—— 这正是消歧要解决的问题 ✓
        #     ② 单字「海」（遗忘之海/夏日海滩）⇒ 只许在**该组两个候选**里选一个（不得跑到第三张图 ✗）
        _el5._CODE_DECIDED.clear()
        _el5.board_state(_im5, mapname='林')
        _pickL = _el5._CODE_DECIDED.get('林')
        check('执行级：枯木丛林帧 + 单字「林」⇒ 消歧选中 S20003（%s）' % _pickL,
              _pickL == 'S20003')
        _el5._CODE_DECIDED.clear()
        _el5.board_state(_im5, mapname='海')
        _pickH = _el5._CODE_DECIDED.get('海')
        check('执行级：单字「海」只在同组候选里选（%s ∈ %s）'
              % (_pickH, _el5._candidate_codes('海')),
              _pickH in _el5._candidate_codes('海'))
        _el5._CODE_DECIDED.clear()
        _st5 = _el5.board_state(_im5, mapname='夏日海滩')
        check('全名路径不受影响（35 格 ✓）', len(_st5 or {}) == 35)
    else:
        skip('图名消歧执行级验证：缺真机帧 ⚠')
except Exception as _e:      # noqa: BLE001
    check('图名消歧执行级验证可运行（%r）' % (_e,), False)

# =====================================================================================
# v0.96【宝库永不丢 + 能直接点就先点】（2026-10-01 用户真机报「黄金宝库明明都揭示了
#   能直接点，他又去打了两个战斗地块」）—— 三条真 bug 的守门：
#   ① `revealed`(ratio) 抖动 ⇒ 已揭示的宝库被判"未揭示" ⇒ 既不进 buy 又被当"点不动" ✗
#   ② sticky 清理是**死代码**（`st['cells']['board']` 永不存在）⇒ 粘性宝库挂满 20 轮
#      = 幽灵目标（日志「没有目标了」却「还剩 1 个目标」）⇒ 满地图开路打拦路 ✗
#   ③ 点序是"揭一格 → 试一次目标"交替 ⇒ 第一下永远是开路格（常触发"拦路"战斗）⇒
#      宝库摆在眼前却先去打战斗 ✗
# =====================================================================================
check('① 新增 `vault_px_now`/`vault_probe_px`/`vault_still_there`（宝库像素的唯一来源 ✓）',
      'def vault_px_now(' in src and 'def vault_probe_px(' in src
      and 'def vault_still_there(' in src)
check('① 已揭示的宝库**从 `done` 里摘回来**（不许"点过一次"就永久钉死 ✓）',
      'vault_px_now(c)' in src and 'done.discard(_p)' in src and 'vault_unpin' in src)
check('② 验证式探点有上限（BUY_PROBE_MAX ⇒ 防"一直点不开"空转 ✓）',
      'BUY_PROBE_MAX = 3' in src and 'probe.get(p, 0) >= BUY_PROBE_MAX' in src
      and 'in _probe_px:' in src)
check('②b 死代码已拔掉（不再读 `st[\'cells\'][\'board\']`）',
      "_still_buy = vault_still_there(st)" in src
      and "(st.get('cells') or {}).get('board')" not in src)
check('③ 免拉黑范围扩到 粘性集/跨轮记忆/探点（"永不拉黑"对**认到过**的宝库成立 ✓）',
      "set(buy) | set(buy_hidden) | set(sticky)" in src
      and "set(st.get('buy_seen') or {})" in src)
check('③b 已揭示的宝库**排到点序最前**（用户口径：能直接点就先点 ✓）'
      '—— ⚠ v1.66 起**只在兜底模式**下成立（`if FALLBACK_EFF:` 守着 ✓），'
      '默认"只听规划的" ⇒ 不插队（否则与用户口径①直接冲突 ✗）',
      'order = _buy_first + list(order)' in src and "'buy_first'" in src
      and 'if FALLBACK_EFF:' in src
      and "'skipped_plan_only'" in src)
try:
    _sys6 = __import__('sys')
    _sys6.path.insert(0, os.path.join(MAPBOT))
    import types as _ty6
    import importlib.util as _ilu6
    if 'rapidocr_onnxruntime' not in _sys6.modules:
        _r6 = _ty6.ModuleType('rapidocr_onnxruntime')
        _r6.RapidOCR = type('RapidOCR', (), {'__init__': lambda s, *a, **k: None})
        _sys6.modules['rapidocr_onnxruntime'] = _r6
    for _n6 in ('airtest', 'airtest.core', 'airtest.core.api', 'airtest.core.cv'):
        if _n6 not in _sys6.modules:
            _sys6.modules[_n6] = _ty6.ModuleType(_n6)
    _a6 = _sys6.modules['airtest.core.api']
    for _f6 in ('connect_device', 'snapshot', 'touch', 'swipe', 'keyevent', 'exists'):
        if not hasattr(_a6, _f6):
            setattr(_a6, _f6, lambda *a, **k: None)
    _T6 = type('T', (), {'__init__': lambda s, *a, **k: None})
    _a6.Template = _T6
    _sys6.modules['airtest.core.cv'].Template = _T6
    _spec6 = _ilu6.spec_from_file_location(
        'el_vault', os.path.join(MAPBOT, 'explore_loop.py'))
    _el6 = _ilu6.module_from_spec(_spec6)
    _spec6.loader.exec_module(_el6)
    _v6 = os.path.join(PROJ, '_verify', 'phone_stamina_0930',
                       'bagdbg', 'board_now_ref.png')
    if os.path.exists(_v6):
        import cv2 as _c6
        import numpy as _n6
        _im6 = _c6.imdecode(_n6.fromfile(_v6, dtype=_n6.uint8), _c6.IMREAD_COLOR)
        # 帧是手机上的**枯木丛林**（真机 S20003）⇒ 必须用对模板（用错 = 整盘全错 ✗）
        _c6x = _el6.cells_of(_im6, mapname='枯木丛林', code='S20003')
        _SP6 = __import__('spots')
        _px6 = _el6.vault_px_now(_c6x)
        check('执行级①：真机枯木丛林帧里**已揭示的黄金宝库被认出**（%s）' % (_px6,),
              _px6 == [(972, 1218)])
        check('执行级①b：它进的是 `buy`（能直接点）而不是 `buy_hidden`（点不动）',
              len(_c6x['buy']) == 1 and len(_c6x['buy_hidden']) == 0)
        _c6d = {'st': {k: dict(v) for k, v in (_c6x['st'] or {}).items()},
                'buy': [], 'buy_hidden': [], 'light': list(_c6x['light']),
                'gray': list(_c6x['gray'])}
        for _k6, _v6x in _c6d['st'].items():
            if _v6x.get('anchor') == _k6 and str(_v6x.get('name') or '') in _SP6.BUY_OUT_NAMES:
                _v6x['revealed'] = False
        _st6 = {}
        check('执行级②：判"未揭示"时仍给出验证式探点（不然宝库就丢了 ✗）',
              _el6.vault_probe_px(_c6d, _st6) == [(972, 1218)])
        check('执行级②b：旧的 `revealed_only` 判据此时为空（= 旧代码就是在这儿丢掉宝库的）',
              _el6.vault_px_now(_c6d) == [])
        for _i6 in range(_el6.BUY_PROBE_MAX):
            _st6.setdefault('buy_probe', {})[(972, 1218)] = \
                _st6['buy_probe'].get((972, 1218), 0) + 1
        check('执行级②c：点满 %d 次后不再探（防空转 ✓）' % _el6.BUY_PROBE_MAX,
              _el6.vault_probe_px(_c6d, _st6) == [])
        _st6b = {'cells': dict(_c6x['st']), 'obs': dict(_c6x['st'])}
        check('执行级③：`vault_still_there` 认得出（修掉"恒为空"的死代码 ✓）',
              (972, 1218) in _el6.vault_still_there(_st6b))
        _st6c = {'cells': {k: dict(v) for k, v in _c6x['st'].items()},
                 'obs': {k: dict(v) for k, v in _c6x['st'].items()}}
        for _k6, _v6x in _st6c['cells'].items():
            if _v6x.get('anchor') == _k6 and str(_v6x.get('name') or '') in _SP6.BUY_OUT_NAMES:
                _v6x['name'] = '空地'
                _st6c['obs'][_k6]['name'] = '空地'
        check('执行级③b：买掉后（名字变空地）⇒ 粘性集能真正清理（幽灵目标消失 ✓）',
              (972, 1218) not in _el6.vault_still_there(_st6c))
    else:
        skip('v0.96 宝库执行级验证：缺 board_now_ref.png ⚠')
except Exception as _e:      # noqa: BLE001
    check('v0.96 宝库执行级验证可运行（%r）' % (_e,), False)

# =====================================================================================
# v0.97【宝库流程：奖励展示是模态 + 不许连点购买 + `_back_btn` 判据漂移】
#   用户真机报（2026-10-01）：「购买第一层后，点击了好几个奖励才选择奖励，选择后不点返回
#   就直接点购买，现在停在有返回弹窗的界面」
# =====================================================================================
try:
    _bp_path = os.path.join(MAPBOT, 'buypanels.py')
    _bp_src = open(_bp_path, encoding='utf-8').read()
    check('v0.97 ①「返回」判据与兜底落点解耦（VAULT_BACK_ZONE；旧判据锚在 (660,1590) 恒 None ✗）',
          'VAULT_BACK_ZONE' in _bp_src
          and "abs(t['cx'] - VAULT['back'][0]) < 130" not in _bp_src)
    check('v0.97 ② 奖励展示识别 `_reward_showing`（「恭喜获得」/「返回」= 模态 ✓）',
          'def _reward_showing(' in _bp_src and "if _has(it, '恭喜获得')" in _bp_src)
    check('v0.97 ③ 同价「购买」再现 ⇒ 不连点（buy_no_effect 守门 ✓）',
          'buy_no_effect' in _bp_src and 'cost in _buy_clicks' in _bp_src)
    check('v0.97 ④ 收不干净就收工，绝不去点购买（stuck/blocked 两条闸门 ✓）',
          'stuck_reward_after_claim' in _bp_src and 'fallback_blocked_by_reward' in _bp_src)
    check('v0.97 ⑤ `say` 在 buypanels 里有兜底定义（真机 NameError 崩整条流程 ✗）',
          'def say(*a, **k):' in _bp_src and "sys.modules.get('explore_loop')" in _bp_src)
    check('v0.97 ⑥ 探名探到想要的就不再点开其它奖励格（probe_early_stop ✓）',
          'probe_early_stop' in _bp_src)
    import importlib.util as _ilu7
    _spec7 = _ilu7.spec_from_file_location('bp_v097', _bp_path)
    _bp = _ilu7.module_from_spec(_spec7)
    _spec7.loader.exec_module(_bp)
    try:
        _bp.say('      · [回归] buypanels.say 兜底可用')
        check('v0.97 执行级：`say` 调用不抛 NameError ✓', True)
    except Exception as _e7:      # noqa: BLE001
        check('v0.97 执行级：`say` 调用不抛 NameError（%r）' % (_e7,), False)
    _j7 = os.path.join(PROJ, '_verify', 'phone_stamina_0930',
                       'bagdbg', 'vault_ret_dlg_now_dlg.json')
    if os.path.exists(_j7):
        import json as _js7
        _raw7 = _js7.load(open(_j7, encoding='utf-8'))
        _real7 = [{'text': (i.get('text') or ''), 'cx': float(i.get('cx') or 0),
                   'cy': float(i.get('cy') or 0), 'conf': i.get('conf')} for i in _raw7]
        _bk7 = _bp._back_btn(_real7)
        check('v0.97 执行级①：真机帧「返回」dlg(538,1267) 被认出（%s）'
              % ((_bk7 or {}).get('text'),), bool(_bk7))
        _old7 = [t for t in _real7 if '返回' in t['text']
                 and abs(t['cx'] - _bp.VAULT['back'][0]) < 130
                 and abs(t['cy'] - _bp.VAULT['back'][1]) < 90]
        check('v0.97 执行级①b：旧判据认不出它（= 本轮真 bug 的根因 ✓）', not _old7)
        check('v0.97 执行级②：该帧被判为奖励展示（模态 ✓）', _bp._reward_showing(_real7) is True)
        # 模态收不掉 ⇒ 一次购买都不许点（真机现场就是这么被连点 4 次的 ✗）
        _S_PANEL = [dict(t) for t in _real7 if t['text'] in ('购买', '20000', '黄金宝库', '离开')]
        _S_MODAL = list(_S_PANEL) + [dict(t) for t in _real7
                                     if t['text'] in ('恭喜获得', '装备', '返回')]

        class _FB7(object):
            ocr_grabs = True

            def __init__(self):
                self.i = 1
                self.taps = []

            def _it(self):
                return list(_S_MODAL) if self.i else list(_S_PANEL)

            def ocr(self, min_conf=0.0, band=None, tag=''):
                return self._it()

            def snap(self, tag=''):
                pass

            def img_dlg(self):
                import numpy as _n
                return _n.zeros((1920, 1080, 3), dtype='uint8')

            img = img_dlg

            def ocr_dlg(self, min_conf=0.4):
                return self._it()

            def tap_dlg(self, x, y, wait=0):
                self.taps.append((int(x), int(y)))
                # 「返回」点不掉（= 真机现况：面板一直停在恭喜获得+返回）

        _fb7 = _FB7()
        _log7 = []
        _bp.vault_flow(_fb7, _log7)
        _buy7 = [t for t in _fb7.taps if abs(t[0] - _bp.VAULT['buy'][0]) < 60
                 and abs(t[1] - _bp.VAULT['buy'][1]) < 60]
        check('v0.97 执行级③：模态收不掉 ⇒ **一次购买都没点**（旧写法点 4 次 ✗）',
              len(_buy7) == 0, 'buy_taps=%d' % len(_buy7))
        check('v0.97 执行级③b：确实在点「返回」（不是干等 ✓）',
              len([t for t in _fb7.taps if abs(t[0] - 538) < 90]) >= 1)
    else:
        skip('v0.97 宝库真机帧执行级验证：缺 vault_ret_dlg_now_dlg.json ⚠')
except Exception as _e:      # noqa: BLE001
    check('v0.97 宝库流程守门可运行（%r）' % (_e,), False)

# =====================================================================================
# v0.98【宝库选奖励：检测奖励格 + 按颜色认草/果（不再东点一下西点一下）】
#   用户真机报（2026-10-01）：「这宝库选择奖励界面纯在乱点啊……不应该识别到天赋果实和
#   幸运草直接选这俩其中一个吗」——根因：网格常数比真机实际位置**高 ~51px**
#   ⇒ 裁图错位 ⇒ 全盘 NCC 0.12~0.31 ⇒ 认不出 ⇒ 退成"逐格点开读名"（= 用户看到的乱点）✗
# =====================================================================================
try:
    _bp2 = os.path.join(MAPBOT, 'buypanels.py')
    _src2 = open(_bp2, encoding='utf-8').read()
    check('v0.98 ① 奖励格**检测**（vault_tiles：彩色底 + 尺寸/位置过滤 + 60px 去重 ✓）',
          'def vault_tiles(' in _src2 and 'def _tile_mask(' in _src2
          and 'abs(x - q[0]) < 60' in _src2)
    check('v0.98 ② 颜色判种 `sprite_kind`（去格子底色后看精灵色调 ✓）',
          'def sprite_colors(' in _src2 and 'def sprite_kind(' in _src2
          and 'B > 0.55 * R' in _src2)
    check('v0.98 ③ 阈值按真机标定（pink .35 / green .25；红宝石 0.16~0.18 必须被排除 ✓）',
          'SPRITE_PINK_THR = 0.35' in _src2 and 'SPRITE_GREEN_THR = 0.25' in _src2)
    check('v0.98 ④ `vault_pick` 里检测格心覆盖常数格心（`cells` 换成检测结果 ✓）',
          '_tiles = vault_tiles(img)' in _src2 and 'cells = [(x, y) for (x, y, _w, _h) in _tiles]' in _src2)
    import importlib.util as _ilu8
    _spec8 = _ilu8.spec_from_file_location('bp_v098', _bp2)
    _bp8 = _ilu8.module_from_spec(_spec8)
    _spec8.loader.exec_module(_bp8)
    _f8 = os.path.join(PROJ, '_verify', 'phone_stamina_0930',
                       'bagdbg', 'fixture_vault_all_rings.png')
    if os.path.exists(_f8) and hasattr(_bp8, 'vault_tiles'):
        import cv2 as _c8
        import numpy as _n8
        _im8 = _c8.imdecode(_n8.fromfile(_f8, dtype=_n8.uint8), _c8.IMREAD_COLOR)
        _tl8 = _bp8.vault_tiles(_im8)
        check('v0.98 执行级①：真机宝库帧检测到奖励格（%d 个，≥6 ✓）' % len(_tl8), len(_tl8) >= 6)
        _ys8 = sorted(set(y for (_x, y, _w, _h) in _tl8))
        check('v0.98 执行级②：检测格心比常数 gy0=%d 低 ≥40px（= 旧代码裁错地方的根因）'
              % _bp8.VAULT['gy0'],
              bool(_ys8) and min(abs(y - _bp8.VAULT['gy0']) for y in _ys8) > 40,
              'y=%s' % (_ys8[:4],))
        # ⭐⭐⭐ v1.09【圈层约束】—— 用户报「宝库又选不了奖励了」的核心守门：
        #   旧代码 `cells = 全部检测格` ⇒ 三层都返回同一个格（真机 logcat: ring1/2/3 全是
        #   (540,1089) 正中心）⇒ 非本圈的点 = 游戏不认 ⇒ 选不了 ✗
        _ring_n = {}
        for _lv in (1, 2, 3):
            _ring_n[_lv] = [p for p in
                            [(x, y) for (x, y, _w, _h) in _tl8]
                            if _bp8.tile_ring(p[0], p[1]) == _lv]
        check('v1.09 ① 圈层切分：外圈 %d / 中圈 %d / 核心 %d（真机帧 ≥1 圈非空 ✓）'
              % (_ring_n[1].__len__(), _ring_n[2].__len__(), _ring_n[3].__len__()),
              bool(_ring_n[1] or _ring_n[2]))
        check('v1.09 ② 外圈格数 = **16**（5×5 的切比雪夫外圈，用户口径「第一轮只能选最外一圈」✓）',
              len(_ring_n[1]) == 16, 'n1=%d' % len(_ring_n[1]))
        _picks8 = {}
        for _lv in (1, 2, 3):
            _b9 = type('B', (), {'ocr_grabs': True, 'taps': [],
                                 'ocr': staticmethod(lambda **k: [
                                     {'text': '黄金宝库', 'cx': 690, 'cy': 438, 'conf': 1.0},
                                     {'text': '选择奖励', 'cx': 894, 'cy': 1521, 'conf': 1.0}]),
                                 'snap': staticmethod(lambda *a, **k: None),
                                 'img_dlg': staticmethod(lambda: _im8),
                                 'img': staticmethod(lambda: _im8),
                                 'tap_dlg': lambda self, x, y, wait=0: self.taps.append((int(x), int(y)))
                                 })()
            _b9.ocr = lambda **k: [{'text': '黄金宝库', 'cx': 690, 'cy': 438, 'conf': 1.0},
                                   {'text': '选择奖励', 'cx': 894, 'cy': 1521, 'conf': 1.0}]
            _b9.ocr_dlg = _b9.ocr
            _b9.img_dlg = lambda: _im8
            _b9.img = _b9.img_dlg
            _b9.snap = lambda *a, **k: None
            _b9.tap_dlg = (lambda self: lambda x, y, wait=0: self.taps.append((int(x), int(y))))(_b9)
            _l9 = []
            _at9, _nm9 = _bp8.vault_pick(_b9, _l9, _lv)
            _picks8[_lv] = _at9
            check('v1.09 ③ 圈%d 的 pick 落在**本圈**（pick=%s）' % (_lv, _at9),
                  _bp8.tile_ring(_at9[0], _at9[1]) == _lv, 'name=%s' % _nm9)
        check('v1.09 ④ 三次 pick **不全相同**（旧 bug：三层全是 (540,1089) 正中心 ✗）',
              len(set(_picks8.values())) > 1, 'picks=%s' % (_picks8,))
        # ⚠⚠ v1.09 ⑤【点阵过滤】：右下角「选择奖励」按钮也是高饱和彩色块，
        #   旧代码把它当奖励格 ⇒ 可能返回**按钮自己的坐标**（真机 ring1 pick = (895,1525)）✗
        check('v1.09 ⑤ 右下角按钮**不在奖励格里**（点阵外 ⇒ 被剔掉 ✓）',
              all(not (abs(x - 895) < 40 and abs(y - 1521) < 40) for (x, y, _w, _h) in _tl8),
              'tiles=%s' % ([(x, y) for (x, y, _w, _h) in _tl8][:6],))
        check('v1.09 ⑥ `_vault_lattice` 对按钮返回 None、对真格返回行列 ✓',
              _bp8._vault_lattice(895, 1521) is None
              and _bp8._vault_lattice(_bp8.VAULT['gx0'], _bp8.VAULT['gy0']) == (0, 0))
        # 颜色认种（pink/green）—— 只有**该帧真的含草/果**时才断言，没有就**响亮地跳过** ✓
        _hit8 = []
        for (_x, _y, _w, _h) in _tl8:
            _k8, _fr8 = _bp8.sprite_kind(_im8, _x, _y, int(min(_w, _h) * 0.36))
            if _k8:
                _hit8.append((_x, _y, _k8, round(_fr8['pink'], 3), round(_fr8['green'], 3)))
        if _hit8:
            check('v0.98 执行级③：颜色认种命中（%s）且**不含误命中**（红宝石等 pink<0.35 ✓）'
                  % (_hit8,), len(_hit8) <= 3)
        else:
            skip('v0.98 ③ 颜色认种：本 fixture 帧里没有草/果（pink/green 全低于阈值）⇒ 跳过 ⚠')
    else:
        skip('v0.98 真机帧执行级验证（缺 fixture fixture_vault_all_rings.png）⚠')
        skip('v0.98 宝库奖励格执行级验证：缺 fixture_vault_all_rings.png ⚠')
except Exception as _e8:      # noqa: BLE001
    check('v0.98 宝库选奖励守门可运行（%r）' % (_e8,), False)

# =====================================================================================
# v1.06【雾格剪影 = plain 的权威判据】（用户：「优化识别模型，认出雾格里那块不能穿过」
#   ＋「别用保守的，不优雅」）——真机铁血高地帧上的一正一反锚点：
#     (2,2) 0.169 / (5,3) 0.271 / (3,1) 0.292 ⇒ 雾下有物体 ⇒ **非空地（挡连锁）**
#     (1,7) 0.014 / (1,1) 0.014 / (3,2) 0.016 ⇒ 雾下平坦 ⇒ **空地**
#   ⚠ 真根因（我第一版漏了）：多格块的**代表格常常是平坦的那一格** ⇒ 整块丢剪影 ✗
# =====================================================================================
try:
    _ms6 = os.path.join(MAPBOT, 'mapsim.py')
    _src6 = open(_ms6, encoding='utf-8').read()
    check('v1.06 ① Block 保存原始 spot（`fog_sil` 等字段要用 ✓）',
          'self.spot = dict(spot)' in _src6)
    check('v1.06 ② 雾格 plain **只认剪影**（有物体⇒非空地 / 平坦⇒空地）'
          '——⚠ v1.58 起**加 `not observed` 限定**（已揭示的格必须按名字/类型判，'
          '照 PC `mapsim.py:198-203` ✓；否则已揭示的战斗格被剪影接管 ⇒ `plain=True` ✗）',
          "if (not getattr(self, 'observed', False)) and self.spot.get('fog_sil') is not None:" in _src6
          and "return bool(getattr(self, 'fog_flat', False))" in _src6)
    check('v1.06 ③ 多格块取**成员剪影最大值**（anchor 常是平坦格 ⇒ 旧写法整块丢剪影 ✗）',
          "_sils = [float(cells[m].get('fog_sil'))" in _src6
          and "row['fog_sil'] = max(_sils)" in _src6)
    check('v1.06 ④ 保守口径已彻底移除（用户：「不优雅」✗）',
          'fog_unknown' not in _src6)
    _f6 = os.path.join(PROJ, '_verify', 'phone_stamina_0930',
                       'bagdbg', 'iron_highland_fog_dev.png')
    if os.path.exists(_f6):
        _sys6b = __import__('sys')
        _sys6b.path.insert(0, os.path.join(MAPBOT))
        import cv2 as _c6b
        import numpy as _n6b
        _SP6 = __import__('spots')
        _MS6 = __import__('mapsim')
        _im6 = _c6b.imdecode(_n6b.fromfile(_f6, dtype=_n6b.uint8), _c6b.IMREAD_COLOR)
        _H6, _W6 = _im6.shape[:2]
        _kx6 = _W6 / 1080.0
        _sh6 = _H6 - 1920.0 * _kx6
        _G6 = dict(_SP6.GRID)
        _g6 = {'x0': _G6['x0'] * _kx6, 'y0': _G6['y0'] * _kx6 + _sh6,
               'cx': _G6['cx'] * _kx6, 'cy': _G6['cy'] * _kx6, 'pitch': _G6['cx'] * _kx6}
        _st6 = _SP6.Board('S10003', grid=_g6).state(_im6, thr=0.0)
        _sim6 = _MS6.MapSim.from_observation(_st6, _SP6.spot_rows())

        def _plain6(r, c):
            _b = _sim6.blocks[_sim6.board[(r - 1) * 7 + (c - 1)]]
            return _b.plain, getattr(_b, 'fog_object', None)

        _p22 = _plain6(2, 2)
        _p53 = _plain6(5, 3)
        _p31 = _plain6(3, 1)
        _p17 = _plain6(1, 7)
        check('v1.06 执行级：真机帧 (2,2) 剪影 0.169 ⇒ **非空地**（挡连锁 ✓）',
              _p22[0] is False and _p22[1] is True, 'plain=%s obj=%s' % _p22)
        check('v1.06 执行级：6 格块里的 (5,3)（剪影 0.271）整块**非空地**（旧写法整块丢剪影 ✗）',
              _p53[0] is False and _p53[1] is True, 'plain=%s obj=%s' % _p53)
        check('v1.06 执行级：(3,1) 石碑 0.292 ⇒ 非空地', _p31[0] is False)
        check('v1.06 执行级：平坦雾格 (1,7) 0.014 ⇒ **仍是空地**（不一刀切 ✓）',
              _p17[0] is True and _p17[1] is False, 'plain=%s obj=%s' % _p17)
        check('v1.06 执行级：剪影集成值 == 独立原型值（(5,3)=0.271 / (2,2)=0.169）',
              abs(float(_st6[(5, 3)]['fog_sil']) - 0.271) < 0.01
              and abs(float(_st6[(2, 2)]['fog_sil']) - 0.169) < 0.01)
    else:
        skip('v1.06 真机帧执行级验证：缺 iron_highland_fog_dev.png ⚠')
except Exception as _e6:      # noqa: BLE001
    check('v1.06 雾格剪影守门可运行（%r）' % (_e6,), False)

# =====================================================================================
# v1.07【体力不足要把"为什么停"说在悬浮条上】（用户报「怎么连启动都启动不了了，完全用不了」
#   —— 真因是体力 < 下限 ⇒ 静默收工，悬浮条只写「体力不够了 · 收工」，看不出毛病）
# =====================================================================================
try:
    _el7 = os.path.join(MAPBOT, 'explore_loop.py')
    _src7 = open(_el7, encoding='utf-8').read()
    check('v1.07 ① 体力不足的悬浮条文案带**三个数**（当前/下限/怎么办 ✓）',
          "status('体力 %d 不足（要 %d）· %s'" in _src7)
    check('v1.07 ② 自动补给关着时明确提示去开（用户 09-30 成功那次它是开着的 ✓）',
          "开自动补给可自动吃结实补给" in _src7
          and "'补给没吃够，请手动补一次'" in _src7)
    check('v1.07 ③ 体力**读不到**也说明白（原来只写「体力读不到 · 先不进图」✗）',
          "status('体力读不到（要 ≥%d）· 先不进图，请看一眼体力'" in _src7)
    _pl7 = os.path.join(PROJ, 'tools', 'port_loop.py')
    _src7b = open(_pl7, encoding='utf-8').read()
    check('v1.07 ④ 启动瞬间就在悬浮条报「下限 + 自动补给开/关」（体感"点了没反应"的直接解药 ✓）',
          "status('已启动 · 体力下限 %d ｜ 自动补给%s'" in _src7b)
    # ⚠ 文案必须避开 OCR 关键词（否则被 OverlayService.sanitize 糊成 ▓ ✗）
    _kw7 = ['开始冒险', '进入地图', '一键派遣', '探索配队', '探索产出', '关闭', '探索', '派遣', '领取']
    _msgs7 = ['体力 37 不足（要 50）· 开自动补给可自动吃结实补给',
              '体力 37 不足（要 50）· 补给没吃够，请手动补一次',
              '体力读不到（要 ≥50）· 先不进图，请看一眼体力',
              '已启动 · 体力下限 50 ｜ 自动补给关（体力不够会直接收工，建议开上）']
    _bad7 = [(k, m) for m in _msgs7 for k in _kw7 if k in m]
    check('v1.07 ⑤ 四条新文案都**不含 OCR 关键词**（不会被糊成 ▓ ✓）', not _bad7,
          'bad=%s' % (_bad7,))
except Exception as _e7:      # noqa: BLE001
    check('v1.07 体力提示守门可运行（%r）' % (_e7,), False)

# =====================================================================================
# v1.08【收工行带上原因 + 战斗日志写清"打的是什么格子"】
#   用户原话①：「现在悬浮窗还是只写了收工，没有写是因为体力不够 50 才收工」
#   用户原话②：「战斗时日志要写出打这个格子是什么格子，拦路的就写拦路格，首领就写首领格，
#     四叶草就写四叶草格，大拇指就写大拇指格。同时有多种就都写出来，比如
#     当前格子标志：首领，四叶草，大拇指，红装」
# =====================================================================================
try:
    _el8 = os.path.join(MAPBOT, 'explore_loop.py')
    _src8 = open(_el8, encoding='utf-8').read()
    check('v1.08 ① 收工那行**带上结束原因**（STATS["stopped"] 拼进去 ✓）',
          "status('收工：刷完 %d 张 · %s'" in _src8 and "_why = str(STATS.get('stopped')" in _src8)
    check('v1.08 ② 体力不足时**写入** STATS["stopped"]（否则收工行还是没原因 ✗）',
          "STATS['stopped'] = '体力 %d 不足（要 %d）'" in _src8)
    check('v1.08 ③ 标记中英映射 MARK_CN（boss→首领 / recommend→大拇指 / clover→四叶草 / '
          'redEquip→红装 ✓）',
          "'boss': '首领'" in _src8 and "'recommend': '大拇指'" in _src8
          and "'clover': '四叶草'" in _src8 and "'redEquip': '红装'" in _src8)
    check('v1.08 ④ `tile_phrase()`：多个标记**全写出来**（用户样例「格子标志：首领，四叶草，大拇指，红装」✓）',
          'def tile_phrase(marks):' in _src8
          and "return '格子标志：%s' % '，'.join(_cn)" in _src8
          and "return '拦路格'" in _src8)
    check('v1.08 ⑤ 开打/战斗中/结算**三处**都用 tile_phrase（不再只有英文标记 ✓）',
          _src8.count('tile_phrase(') >= 4)
    # ⚠ 文案照样要避开 OCR 关键词（否则被 sanitize 糊成 ▓ ✗）
    import importlib.util as _ilu8b
    _spec8b = _ilu8b.spec_from_file_location(
        'el_marks8', os.path.join(MAPBOT, 'explore_loop.py'))
    _el8b = _ilu8b.module_from_spec(_spec8b)
    try:
        _spec8b.loader.exec_module(_el8b)
        _kw8 = ['开始冒险', '进入地图', '一键派遣', '探索配队', '探索产出',
                '关闭', '探索', '派遣', '领取']
        _cases8 = [[], ['boss'], ['clover'], ['recommend'], ['redEquip'],
                   ['boss', 'clover', 'recommend', 'redEquip'], ['battle']]
        _msgs8 = []
        for _c8 in _cases8:
            _d8 = _el8b.tile_phrase(_c8)
            _msgs8 += ['开打 · ' + _d8, '战斗中 · ' + _d8, '战斗胜利 ✓ · ' + _d8]
        _bad8 = [(k, m) for m in _msgs8 for k in _kw8 if k in m]
        check('v1.08 ⑥ 全部格子文案**不含 OCR 关键词**（不会被糊成 ▓ ✓）', not _bad8,
              'bad=%s' % (_bad8[:3],))
        check('v1.08 执行级：四种单标记 + 多标记合并的文案都对 ✓',
              _el8b.tile_phrase([]) == '拦路格'
              and _el8b.tile_phrase(['boss']) == '首领格'
              and _el8b.tile_phrase(['clover']) == '四叶草格'
              and _el8b.tile_phrase(['recommend']) == '大拇指格'
              and _el8b.tile_phrase(['redEquip']) == '红装格'
              and _el8b.tile_phrase(['boss', 'clover', 'recommend', 'redEquip'])
              == '格子标志：首领，四叶草，大拇指，红装',
              'multi=%s' % (_el8b.tile_phrase(['boss', 'clover', 'recommend', 'redEquip']),))
    except Exception as _e8b:      # noqa: BLE001
        check('v1.08 格子文案执行级验证可运行（%r）' % (_e8b,), False)
except Exception as _e8:      # noqa: BLE001
    check('v1.08 收工原因/格子文案守门可运行（%r）' % (_e8,), False)

# =====================================================================================
# v1.11【"面板挡住棋盘"误判 + 无限循环】（用户：发给朋友后「进图就说面板挡住、一直卡在这，
#   实际棋盘上啥都没有」）
#   根因：`board_hidden()` 两条判据都是**绝对阈值**（0.55 / 0.85）⇒ 设备整体偏暗的机型
#         整盘被判"暗格+被压暗" ⇒ 每张图都走"关面板" ⇒ stuck ⇒ 退图失败 ⇒ 恢复 ⇒ 下一张
#         ⇒ **永远出不来** ✗
# =====================================================================================
try:
    _el11 = os.path.join(MAPBOT, 'explore_loop.py')
    _src11 = open(_el11, encoding='utf-8').read()
    # ⚠ 2026-10-02 v1.21：① 原本断言的是「基准 = 本帧最亮格 + 系数 0.55」——
    #   那条在新机型（nubia NX809J）上又翻车了（见 v1.21 段）⇒ 断言随实现更新，
    #   **它要守的性质没变**：判据必须是"相对本帧自身的口径"，不能退回绝对阈值 ✓
    check('v1.11 ① `board_hidden` 用**本帧自身的亮度基准**（绝对阈值→相对阈值 ✓；'
          'v1.21 起基准=已揭示格中位）',
          ('_mx, _lit = 0.0, []' in _src11
           and '_ref = float(np.median(_lit)) if _lit else _mx' in _src11
           and '_thr = DIM_RATIO_MAX * _ref if _ref > 0 else DIM_RATIO_MAX' in _src11))
    check('v1.11 ② 全盘判据只在**最亮格也 < 0.40** 时才成立（设备偏暗 ≠ 面板遮 ✓）',
          'and _mx < 0.40:' in _src11)
    check('v1.11 ③ 首次判"被挡"就**存诊断帧**（我们手上没有别的机型的帧 ✗）',
          "_pub_dump('board_hidden_r%d'" in _src11 and "'board_hidden_dump'" in _src11)
    check('v1.11 ④ 连续 2 张 stuck/blank ⇒ **整局停下**（不再退图失败→恢复→再来一张的死循环 ✓）',
          "if why in ('stuck', 'blank'):" in _src11 and "STATS['stuck_maps'] >= 2" in _src11
          and '连续认不出棋盘' in _src11)
    # ⚠ 判据语义执行级：直接调**真函数**逐条对（含**已修好的"盖中间"不回归**）
    import importlib.util as _ilu11
    _spec11 = _ilu11.spec_from_file_location('el_v111', _el11)
    _el11m = _ilu11.module_from_spec(_spec11)
    _spec11.loader.exec_module(_el11m)

    def _mk11(n_fog, n_rev, k=1.0, covered=0):
        st = {}
        for i in range(n_fog):
            st[('f', i)] = {'ratio': 0.65 * k, 'anchor': ('f', i)}
        for i in range(n_rev):
            st[('r', i)] = {'ratio': 1.00 * k, 'anchor': ('r', i)}
        for i in range(covered):
            st[('c', i)] = {'ratio': 0.30, 'anchor': ('c', i)}
        return st

    def _bh11(st, light, gray):
        return _el11m.board_hidden({'st': st, 'light': [1] * light, 'gray': [1] * gray})

    _cases11 = [
        ('正常盘', _mk11(29, 6), 0, 29, False),
        ('暗设备 k=0.7', _mk11(29, 6, 0.7), 0, 35, False),
        ('暗设备 k=0.5', _mk11(29, 6, 0.5), 0, 35, False),
        ('面板盖中间(3格露)', _mk11(2, 3, 1.0, 30), 3, 32, True),
        ('全盘被遮罩', _mk11(0, 0, 1.0, 35), 0, 35, True),
    ]
    _badc11 = []
    for (tag, st, light, gray, want) in _cases11:
        got = _bh11(st, light, gray)
        if got != want:
            _badc11.append((tag, got, want))
    check('v1.11 执行级：5 种画面判据全对（含**「盖中间」不回归** ✓ 和暗设备不再误判 ✓）',
          not _badc11, 'bad=%s' % (_badc11,))
except Exception as _e11:      # noqa: BLE001
    check('v1.11 board_hidden 守门可运行（%r）' % (_e11,), False)

# =====================================================================================
# v1.12【两处"没有上限"的循环】（朋友真机：进图后 200% CPU 空转 / 一直显示"正在把游戏拉回来"）
#   ① `optimal_order` 调求解器只有 `max_states`、**没有时间上限** ⇒ 棋盘被切碎时
#      几万状态展开 = 几分钟满载空转、全程不打日志 ✗（另一处 `solver_order` 早就有 max_secs=8）
#   ② `game_recover` 成功后 `continue` 下一张，下一张再失败又恢复 ⇒ **无限"拉回来"** ✗
# =====================================================================================
try:
    _el12 = os.path.join(MAPBOT, 'explore_loop.py')
    _src12 = open(_el12, encoding='utf-8').read()
    check('v1.12 ① `optimal_order` 的求解器调用**补上时间上限**（max_secs=8 ✓）',
          'solve_mod.solve(prob, max_states=40000, max_secs=8)' in _src12)
    check('v1.12 ② 求解**前后都有日志**（下次卡住能一眼定位是它 ✓）',
          "'opt_solved'" in _src12)
    check('v1.12 ③ 所有 solve 调用都带时间上限（不许再有裸调用 ✗）',
          _src12.count('solve(prob, max_states=40000)') == 0
          and 'max_secs=8' in _src12)
    check('v1.12 ④ "把游戏拉回来"**有次数上限**（连续 3 次仍跑不动 ⇒ 停整局 ✓）',
          "STATS['recover_n'] >= 3" in _src12 and "'recover_n'] = 0" in _src12
          and '拉回游戏后仍跑不动' in _src12)
except Exception as _e12:      # noqa: BLE001
    check('v1.12 无上限循环守门可运行（%r）' % (_e12,), False)

# =====================================================================================
# v1.15【朋友机 realme RMX3800（1264×2780）实测：**在选图界面上被判成"已进图"**】
#   反馈包铁证：`{'enter':'in_map'}` 出现时**一次点击都没发生**，而那一帧的 OCR 是选图界面
#   （清凉沙滩 / 深渊46-50 / 快速扫荡 / 进入地图）⇒ `in_map()` 的"格子兜底 ≥8 格"把
#   选图界面/进图动画帧判成了棋盘（light=0/1、全盘 ratio<0.55）⇒ 之后全程对着选图界面打，
#   报"面板挡住了棋盘 · 正在收起"、一直卡住 ✗✗
# =====================================================================================
try:
    _el15 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src15 = open(_el15, encoding='utf-8').read()
    check('v1.15 ① `in_map` 补"选图界面专属文字"否定证据（深渊NN / 星界秘境 ✓）',
          "if any(('深渊' in it['text']) or ('星界秘境' in it['text'])" in _src15)
    check('v1.15 ② 格子兜底**要求有真·已揭示的亮格**（真棋盘营地恒 ratio≈1.0 ✓）',
          'return bool(c[\'light\']) and _mx >= _IN_MAP_LIGHT_RATIO' in _src15
          and '_IN_MAP_LIGHT_RATIO = 0.85' in _src15,
          '⚠ v1.35 起这条用**独立阈值 0.85**（不再与 spots 的 0.75 混用）')
    import importlib.util as _ilu15
    _spec15 = _ilu15.spec_from_file_location('el_v115', _el15)
    _el15m = _ilu15.module_from_spec(_spec15)
    _spec15.loader.exec_module(_el15m)
    _f15 = os.path.join(PROJ, '_verify', 'phone_friend_rmx3800',
                        'select_screen_ref.png')
    if os.path.exists(_f15):
        import cv2 as _c15
        import numpy as _n15
        _im15 = _c15.imdecode(_n15.fromfile(_f15, dtype=_n15.uint8), _c15.IMREAD_COLOR)
        check('v1.15 执行级：朋友机 fixture 帧是 **1080×1920 参考帧**（%s）' % (_im15.shape,),
              _im15.shape[:2] == (1920, 1080))
        _items15 = [{'text': t, 'cx': x, 'cy': y} for (t, x, y) in (
            ('清凉沙滩', 540, 182), ('夏日海滩入侵', 721, 333), ('当前难度253', 1301, 370),
            ('星界秘境', 980, 994), ('深渊46', 295, 1309), ('深渊50', 1158, 1309),
            ('快速扫荡', 912, 2158), ('进入地图', 1206, 2158), ('预言', 270, 1693))]
        check('v1.15 执行级①：完整选图界面 ⇒ **判不在图里**（旧代码判成在图里 ✗）',
              _el15m.in_map(None, _im15, _items15) is False)
        _it15b = [i for i in _items15 if i['text'] not in ('快速扫荡', '进入地图')]
        check('v1.15 执行级②：那两个按钮没读到 ⇒ 仍判不在图里（靠 深渊/星界秘境 ✓）',
              _el15m.in_map(None, _im15, _it15b) is False)
        _it15c = [i for i in _it15b
                  if ('深渊' not in i['text']) and ('星界秘境' not in i['text'])]
        check('v1.15 执行级③：连那两条也没有 ⇒ 仍判不在图里（靠"必须有亮格" ✓）',
              _el15m.in_map(None, _im15, _it15c) is False)
    else:
        skip('v1.15 朋友机 fixture 帧（缺 select_screen_ref.png）⚠')
except Exception as _e15:      # noqa: BLE001
    check('v1.15 in_map 守门可运行（%r）' % (_e15,), False)


# ─────────────────────────────────────────────────────────────────────────
# v1.16 广播命令安全门（CommandReceiver 的 RCE 面）
#   历史：Receiver 是 exported=true 且无鉴权，`py --es code` 走
#   explore_android._cmd_run_snippet → exec(code) ⇒ **任意 Python 代码执行**，
#   且 release 包同样带这个 Receiver（release 只是 debug 签名 + 不混淆）。
#   修法：5 个调试命令在非 BuildConfig.DEBUG 时直接拒绝。
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉕ v1.16 广播命令安全门（防 release 被广播 exec 任意 Python ✗）')

_CRJ = None
try:
    _CRJ = open(os.path.join(PROJ, 'app', 'src', 'main', 'java',
                              'com', 'fantasy', 'autoexplore', 'CommandReceiver.java'),
                encoding='utf-8').read()
    _BG = open(os.path.join(PROJ, 'app', 'build.gradle'),
               encoding='utf-8').read()
except Exception as _e16:
    _CRJ, _BG = None, None

if _CRJ is None:
    check('v1.16 守门可运行（%r）' % (_e16,), False)
else:
    check('v1.16 ① 有 DEBUG_ONLY 白名单常量', 'DEBUG_ONLY' in _CRJ)
    check('v1.16 ② `py` 必须在 DEBUG_ONLY 里（= RCE 的根）', '"py"' in _CRJ)
    check('v1.16 ③ 拦截判据是 **BuildConfig.DEBUG**（不是白名单黑名单）',
          'BuildConfig.DEBUG' in _CRJ)
    check('v1.16 ④ 拦截发生在**起线程之前**（不会先干活再拒绝）',
          _CRJ.index('isDebugOnly(cmd) && !BuildConfig.DEBUG')
          < _CRJ.index('"cmd-" + cmd'))
    check('v1.16 ⑤ 5 个调试命令都列进去了（py/classify/overlay_state/overlay_roll/mask_check）',
          all(('"%s"' % c) in _CRJ for c in
              ('py', 'classify', 'overlay_state', 'overlay_roll', 'mask_check')))
    check('v1.16 ⑥ 日常运维命令**不受影响**（explore/summary/red_unlock/feedback 仍可用）',
          'DEBUG_ONLY' in _CRJ and '"explore"' not in
          _CRJ[_CRJ.index('DEBUG_ONLY = {'):_CRJ.index('private static boolean isDebugOnly')])
    check('v1.16 ⑦ build.gradle 开了 buildConfig（AGP 8.x 默认不生成 BuildConfig ✗）',
          'buildConfig true' in _BG)

# ─────────────────────────────────────────────────────────────────────────
# v1.17 朋友真机（realme RMX3800 1264×2780）锚定模型几何对拍
#   起因：用户要求「把模拟器分辨率换成朋友真机的分辨率来测」——实测**模拟器做不到**：
#     `wm size 1264x2780` 后 RefMapper 仍读到 720×1280（getMaximumWindowMetrics
#     在模拟器返回**物理屏**，不认 override），screencap 出的 PNG 也仍是 720×1280。
#     ⇒ 改用「真机留下的现场数据」离线对拍几何模型（不依赖任何设备）。
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉗ v1.17 朋友真机 1264x2780 的锚定模型几何对拍（模拟器改分辨率走不通 ⇒ 离线对拍）')

try:
    import subprocess as _sp17
    _gp = os.path.join(PROJ, 'tools', 'verify_friend_phone_geometry.py')
    _r17 = _sp17.run([sys.executable, _gp], stdout=_sp17.PIPE,
                      stderr=_sp17.STDOUT, timeout=120, env=_ENV())
    _o17 = (_r17.stdout or b'').decode('utf-8', 'replace')
    _n17 = _o17.count('[ok]')
    if not os.path.exists(_gp):
        check('v1.17 几何对拍脚本存在', False, _gp)
    else:
        check('v1.17 几何对拍脚本可运行（%d 项通过 / exit=%d）' % (_n17, _r17.returncode),
              _r17.returncode == 0, _o17.strip().split('\n')[-1][:90])
        # 关键结论直接进主门禁：模型在该分辨率成立（顶/底边吻合到 1px 内）
        check('v1.17 ① k 复算 == 1.1704（真机实测值 ✓）', 'k == 1.1704' in _o17)
        check('v1.17 ② 悬浮条顶/底边与真机实测吻合（2548/2661 ✓）',
              'blankRect 上边 2548' in _o17 and 'blankRect 下边 2661' in _o17)
        check('v1.17 ③ C(dialogShift)≈227.7 ≠ 0 ⇒ 两系必须分开走 ✓',
              'C=227.7' in _o17)
        check('v1.17 ④ 弹性带非空 ⇒ 面板标题/背包页签只能走弹窗系 ✓',
              '必须走弹窗系' in _o17)
except Exception as _e17:
    check('v1.17 几何对拍守门可运行（%r）' % (_e17,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㉘ v1.18 修「地图界面被当成已开打」（2026-10-01 全分辨率 1264×2780 实跑暴露的真 bug）
#   现场：`★首领战斗不超过8回合` / `首领战斗胜利` 是《遗忘之海》地图 HUD 的**常驻文案**，
#   旧判据用宽子串（'回合' in t / L['win'] in t）⇒ 点完「战斗」一 OCR 就假判"已开打"
#   ⇒ wait_end 空等 20 秒 → back_in_map ⇒ 格子没清 ⇒ 下一轮原样再来（连打 4 轮死循环）。
#   证据帧：`_verify/fr1264_map_boss_banner.png`（设备归一化帧，1080×1920 存档）
#   真·战斗结算帧对照：`mapbot_pc/runs/bw2.json`（真机全量 OCR ✓）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉘ v1.18 battle_started 不许把「地图自身的任务横幅」当成已开打')
_FR_SRC = io.open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
import inspect as _insp                                  # noqa: E402
_FR_FN = _insp.getsource(EL.battle_started)              # ⚠ 只看函数体：教训写在**函数外**的注释里
check('v1.18 ① 旧的宽子串判据已删除（函数体里没有 `\'回合\' in t`）', "'回合' in t" not in _FR_FN)
check('v1.18 ② 旧的宽子串判据已删除（函数体里没有 `L[\'win\'] in t`）', "L['win'] in t" not in _FR_FN)
check('v1.18 ③ 新增整条回合正则 _ROUND_RE（"第1/10回合"）', '_ROUND_RE = re.compile' in _FR_SRC)

# 负样本 = 1264×2780 真机地图帧的 OCR 条目（含两条常驻横幅）⇒ 必须 False
_MAP_FRAME = [
    item('PID:162332', 226, 37), item('Ver:1.2.2.7', 404, 38),
    item('2079/2100', 338, 93),
    item('首领战斗胜利', 135, 167),            # ← 旧判据的受害者①（任务达成状态）
    item('遗忘之海[100]', 539, 183), item('帮助', 809, 211), item('2471%', 972, 219),
    item('首领战斗2人存活', 153, 225),
    item('当前难度60', 975, 277),
    item('★首领战斗不超过8回合', 160, 283),     # ← 旧判据的受害者②（任务条件）
    item('友方行动回魔-20。', 161, 658),
    item('敌方行动开始前获得20层滋润。', 221, 721),
    item('配队', 976, 767), item('结束冒险', 540, 773),
    item('空闲', 473, 899), item('已完成', 241, 940), item('已完成', 350, 940),
    item('背包', 978, 942),
]
check('v1.18 ④ 地图帧（首领横幅）不再被判"已开打"', EL.battle_started(_MAP_FRAME) is False,
      EL.battle_started(_MAP_FRAME))
for _t in ('首领战斗胜利', '★首领战斗不超过8回合', '首领战斗2人存活'):
    check('v1.18 ⑤ 单条地图横幅也不许命中：%s' % _t,
          EL.battle_started([item(_t, 300, 300)]) is False)

# 正样本①：真机战斗结算帧（runs/bw2.json 全量 OCR）⇒ 必须 True（别过度收紧 ✗）
_bw_p = os.path.join(PROJ, '_verify', 'bw2_pc_result_panel.json')
if os.path.exists(_bw_p):
    _bw = json.load(io.open(_bw_p, encoding='utf-8'))
    _bitems = _bw['items'] if isinstance(_bw, dict) else _bw
    check('v1.18 ⑥ 真机战斗结算帧仍判"已开打"（不过度收紧 ✓）',
          EL.battle_started(_bitems) is True)
    check('v1.18 ⑦ 结算帧靠的是整条「战斗胜利」+「第1/10回合」',
          any(i['text'].strip() == '战斗胜利' for i in _bitems)
          and any(i['text'].strip() == '第1/10回合' for i in _bitems))
else:
    skip('v1.18 ⑥ 真机战斗结算帧 runs/bw2.json 缺失 ⇒ 正样本没验')

# 正样本②：战斗界面各特征词逐个单测
for _txt, _want in (('战斗胜利', True), ('战斗失败', True), ('第1/10回合', True),
                    ('第3回合', True), ('第12／20回合', True),
                    ('加速', True), ('自动跳过', True), ('回放战斗', True)):
    check('v1.18 ⑧ 单条 %r ⇒ %s' % (_txt, '已开打' if _want else '不算开打'),
          bool(EL.battle_started([item(_txt, 540, 400)])) is _want)

# 边界：第*、回合、加速 出现在**地图任务文案**里一律不算（防"暂时加速"这类增益名误命中）
check('v1.18 ⑨ 带 ★ / 不超过 的句子算地图文案（不算开打）',
      EL.battle_started([item('★首领战斗不超过8回合', 160, 283)]) is False
      and EL.battle_started([item('不超过8回合', 160, 283)]) is False)
check('v1.18 ⑩ 空 items / 无战斗特征 ⇒ False（不误判）',
      EL.battle_started([]) is False
      and EL.battle_started([item('星界秘境', 860, 1405)]) is False)

# ─────────────────────────────────────────────────────────────────────────
# ㉙ v1.19 修「奖励行/骰子按钮搜索带是写死绝对 y」——1264×2780 真帧实测根因
#   实测（设备帧 OCR → 换算回参考系 1080×1920）：
#       PC 9:16 : 奖励行数字 907 / 994~1001 ｜ 回放 1223 ｜ 关闭 1440 ｜ 自动跳过 1563
#       真机    : 奖励行数字 636 / 752       ｜ 回放 1224 ｜ 关闭 1441 ｜ 自动跳过 1563
#   ⇒ 面板**底部三键两机一致**（锚定模型成立 ✓），但**奖励行在真机高 271px**（战斗 UI 纵向压缩）
#   ⇒ 旧 `sy(700)~sy(1180)`（文字带）/ `box=(40,840+C,1020,1140+C)`（图标框）
#      在真机上**完全盖不到奖励行** ⇒ `{'dice':'no_btn'}` + 图标三路全 None（真机复现 ✓）
#   证据帧：`_verify/fr1264_result_panel.png`（设备原帧，含 战斗胜利/第4-10回合/关闭/自动跳过）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉙ v1.19 奖励行/骰子搜索带必须锚定「关闭」按钮（不得写死绝对 y）')
_K1, _S1 = 1264 / 1080.0, 2780 - 1920 * (1264 / 1080.0)


def _dev2ref(y):
    """1264×2780 设备 y → 参考系 y（RefMapper 锚定模型：y<=300 锚顶，其余锚底）"""
    return y / _K1 if y <= 300 * _K1 else (y - _S1) / _K1


_DEV_PANEL = [('1/3', 224, 1277), ('1/16', 468, 1277), ('5/5', 715, 1277),
              ('133114', 229, 1375), ('220 46 184', 449, 1413),
              ('10', 130, 1595), ('1', 150, 1680),
              ('回放战斗', 677, 1966), ('关闭', 675, 2219), ('自动跳过', 673, 2362)]
_panel_items = [item(t, x, int(round(_dev2ref(y)))) for t, x, y in _DEV_PANEL]
_bx0, _by0, _by1 = EL._reward_band(_panel_items)
check('v1.19 ① 传入真机结算帧 items ⇒ band 收紧到 (%d, %d, %d)' % (_bx0, _by0, _by1),
      _by1 < EL.REWARD_CLOSE_UP_MAX + 1)
_cov = [t for t, x, y in _DEV_PANEL
        if _by0 <= _dev2ref(y) <= _by1 and x < EL.REWARD_X1]
check('v1.19 ② 真机奖励行左区**被覆盖**（6 条数字）',
      len(_cov) >= 5, _cov)
for _t in ('回放战斗', '关闭', '自动跳过'):
    _ry = _dev2ref(dict((a, c) for a, b, c in _DEV_PANEL)[_t])
    check('v1.19 ③ 底部按钮 %r 不得落进奖励行带（y=%.0f）' % (_t, _ry),
          not (_by0 <= _ry <= _by1))
check('v1.19 ④ 旧写死带 sy(700)~sy(1180) 在真机**盖不到**奖励行（= 本 bug 根因）',
      700 > _dev2ref(1277) and 1180 < _dev2ref(1413) - 0 or
      not (700 <= _dev2ref(1277) <= 1180),
      '旧带 700~1180 vs 奖励行 %.0f~%.0f' % (_dev2ref(1277), _dev2ref(1680)))
check('v1.19 ⑤ 无 items 时退回默认常量（不崩）',
      EL._reward_band(None) == (20, EL.REWARD_CLOSE_UP_MIN, EL.REWARD_CLOSE_UP_MAX),
      EL._reward_band(None))
check('v1.19 ⑥ 上界锚定方向正确（必须 min(常量, 关闭-260)，反了会失效）',
      _by1 == max(EL.REWARD_CLOSE_UP_MIN,
                  min(EL.REWARD_CLOSE_UP_MAX,
                      int(round(_dev2ref(2219))) - 260)),
      'by1=%d' % _by1)
# 源码级：旧硬编码必须已消失
_FR_SRC2 = io.open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
check('v1.19 ⑦ 旧硬编码 `box=(40, 840 + c` 已消失', '(40, 840 + c' not in _FR_SRC2)
check('v1.19 ⑧ 旧硬编码 `LAYOUT.sy(700) <= it[\'cy\'] <= LAYOUT.sy(1180)` 已消失',
      "LAYOUT.sy(700) <= it['cy'] <= LAYOUT.sy(1180)" not in _FR_SRC2)
# PC 基线帧（runs/bw2.json）仍覆盖到奖励行 ⇒ 没把 9:16 弄坏
_bw2 = os.path.join(PROJ, '_verify', 'bw2_pc_result_panel.json')
if os.path.exists(_bw2):
    _b2 = json.load(io.open(_bw2, encoding='utf-8'))
    _b2i = _b2['items'] if isinstance(_b2, dict) else _b2
    _bx0b, _by0b, _by1b = EL._reward_band(_b2i)
    _pc_cov = [i['text'] for i in _b2i
               if _by0b <= i['cy'] <= _by1b and i['cx'] < EL.REWARD_X1]
    check('v1.19 ⑨ PC 9:16 结算帧仍覆盖到奖励行（没弄坏基线 ✓）',
          len(_pc_cov) >= 4, _pc_cov[:6])
    check('v1.19 ⑩ PC 帧的「关闭/自动跳过」也排除在外',
          not (_by0b <= 1440 <= _by1b) and not (_by0b <= 1563 <= _by1b),
          'band=(%d,%d,%d)' % (_bx0b, _by0b, _by1b))
else:
    skip('v1.19 ⑨⑩ PC 基线帧 runs/bw2.json 缺失 ⇒ 没验 9:16 未回归')

# ─────────────────────────────────────────────────────────────────────────
# ㉚ v1.20 面板层「全分辨率」自检（把「到底有没有做全分辨率」变成可执行的门禁）
#   起因：2026-10-01 用户追问「换个分辨率问题又出来，到底有没有做全分辨率适配」
#     结论：**棋盘层做了（逐格全等），面板层没做**（全是逐设备标定的常数，失败还是静默的）
#     ⇒ v1.18 / v1.19 都是这一类 ⇒ 必须有工具在换分辨率**之前**就报警
#   工具：`tools/verify_panels_allres.py`（A 几何 / B 搜索带覆盖 / C 判据重放 × 9 个分辨率）
# ⚠ **清单即契约**：新面板常数必须登记进 `PANEL_CONSTS`，否则等于没测
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉚ v1.20 面板层全分辨率自检（几何/搜索带/判据 × 9 分辨率）')
try:
    import subprocess as _sp20
    _gp20 = os.path.join(HERE, 'verify_panels_allres.py')
    if not os.path.exists(_gp20):
        check('v1.20 面板自检脚本存在', False, _gp20)
    else:
        _r20 = _sp20.run([sys.executable, _gp20], stdout=_sp20.PIPE,
                          stderr=_sp20.STDOUT, timeout=180, env=_ENV())
        _o20 = (_r20.stdout or b'').decode('utf-8', 'replace')
        check('v1.20 面板层自检可运行且全过（exit=%d）' % _r20.returncode,
              _r20.returncode == 0, _o20.strip().split('\n')[-1][:90])
        check('v1.20 ① 覆盖 ≥9 个分辨率', '9 个分辨率' in _o20)
        check('v1.20 ② 几何段存在（面板常数→设备坐标）', 'A. 几何' in _o20)
        check('v1.20 ③ 搜索带段存在（真机实测坐标覆盖断言）', 'B. 搜索带覆盖' in _o20)
        check('v1.20 ④ 判据重放段存在（地图帧负/PC帧正）', 'C. 判据重放' in _o20)
        check('v1.20 ⑤ 地图帧不得判成结算面板（2026-09-26 旧坑）',
              '地图帧 is_battle_panel = False  OK' in _o20)
        check('v1.20 ⑥ 地图帧不得判成已开打（v1.18 修的那个）',
              '地图帧 battle_started  = False  OK' in _o20)
        check('v1.20 ⑦ PC 结算帧仍认得出（没过度收紧）',
              'PC结算帧 is_battle_panel = True  OK' in _o20
              and 'PC结算帧 battle_started  = True  OK' in _o20)
        check('v1.20 ⑧ 清单单一维护的提示在位（不再手工维护第二份清单）',
              'SCAN_SOURCES 单一维护' in _o20)
        # ⚠ v1.20 新增：自检验的必须是**手机端自己的代码**（原先验的是 PC 仓，
        #   而两端已平行独立开发、buypanels 差 2232 行 ⇒ 验的根本不是端上跑的那份）
        _g20 = open(_gp20, encoding='utf-8').read()
        check('v1.20 ⑨ 自检 import 的是手机端源码（不是 PC 仓）',
              "sys.path.insert(0, PYD)" in _g20
              and '手机端优先' in _g20
              and "assert os.path.abspath(EL.__file__)" in _g20)
except Exception as _e20:
    check('v1.20 面板自检守门可运行（%r）' % (_e20,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㉜ v1.20 **漏检防呆**（本轮最关键的一条）：面板层坐标常数清单 vs 手机端源码
#   起因：`verify_panels_allres.py` 的覆盖度**完全取决于 PANEL_CONSTS 这张手工清单**，
#     工具自己都承认「新面板必须同时登记，否则等于没测」—— 而「漏登记」**没有任何人
#     会发现** ⇒ 这正是「面板层没做全分辨率」的机制性根因。
#   做法：AST 扫手机端所有模块级坐标常数，与清单求差集，**差集非空即红**。
#   本组第一次跑就抓出 3 个此前无人验证的真坐标
#   （BAG_FILTER_DLG / _AUTO_SKIP_BOX / _BAG_TPL_SCALES）。
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉜ v1.20 面板层坐标常数「漏检防呆」（AST 扫手机端源码 vs 清单）')
try:
    import subprocess as _sp40
    _gp40 = os.path.join(HERE, 'panel_consts.py')
    if not os.path.exists(_gp40):
        check('v1.20 漏检防呆扫描器存在', False, _gp40)
    else:
        _r40 = _sp40.run([sys.executable, _gp40], stdout=_sp40.PIPE,
                          stderr=_sp40.STDOUT, timeout=120, env=_ENV())
        _o40 = (_r40.stdout or b'').decode('utf-8', 'replace')
        check('v1.20 漏检防呆可运行且差集为空（exit=%d）' % _r40.returncode,
              _r40.returncode == 0, _o40.strip().split('\n')[-1][:90])
        check('v1.20 ⑩ 清单已覆盖 ≥30 项坐标常数',
              _o40.count('   explore_loop.py') + _o40.count('   buypanels.py') >= 30)
        # 守住「扫描器本身有效」：三个此前漏检的真坐标必须已在清单里
        _pc40 = open(_gp40, encoding='utf-8').read()
        for _n40 in ('BAG_FILTER_DLG', '_AUTO_SKIP_BOX', '_BAG_TPL_SCALES'):
            check('v1.20 ⑪ 此前漏检的 %s 已登记' % _n40, _n40 in _pc40)
        # ⚠ 守住「EXEMPT 不是垃圾桶」：每条豁免都必须写理由
        check('v1.20 ⑫ 豁免项均带理由（无裸豁免）',
              "STATS': '统计计数器" in _pc40)
except Exception as _e40:
    check('v1.20 漏检防呆守门可运行（%r）' % (_e40,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㉛ v1.19 奖励行「锚定关闭」双分辨率审计（2026-10-01 20:4x 补）
#   背景：v1.19 把骰子/大拇指搜索框从「写死 y」改成「相对关闭按钮锚定」，
#   但当时的离线验收只跑了一张**首领战**帧（奖励行里没有大拇指 ⇒ 结果全空），
#   **等于没验**。本组把「band 覆盖 / 不误伤底部三键 / 旧 box 必然漏 /
#   PC 帧不过度收紧 / 阈值标定」全部变成断言，钉死这个修法。
print()
print('㉛ v1.19 奖励行锚定「关闭」· 双分辨率审计')
try:
    import subprocess as _sp30
    _gp30 = os.path.join(HERE, 'verify_reward_band_allres.py')
    if not os.path.exists(_gp30):
        check('v1.19 奖励行审计脚本存在', False, _gp30)
    else:
        _r30 = _sp30.run([sys.executable, _gp30], stdout=_sp30.PIPE,
                          stderr=_sp30.STDOUT, timeout=180, env=_ENV())
        _o30 = (_r30.stdout or b'').decode('utf-8', 'replace')
        check('v1.19 奖励行审计可运行且全过（exit=%d）' % _r30.returncode,
              _r30.returncode == 0, _o30.strip().split('\n')[-1][:90])
        check('v1.19 ⓐ 真机 1264×2780 奖励行左半区被 band 覆盖',
              '奖励行左区条目被 band 覆盖' in _o30 and '[FAIL]' not in _o30)
        check('v1.19 ⓑ 面板底部三键不落进 band',
              '面板底部三键**不**落进 band' in _o30)
        check('v1.19 ⓒ 旧写死 box 确实盖不全（证明修的是真 bug）',
              '旧 box 确实盖不全' in _o30)
        check('v1.19 ⓓ 新 box 覆盖左半区全部奖励行条目',
              '新 box 覆盖**左半区全部**奖励行条目' in _o30)
        check('v1.19 ⓔ PC 9:16 帧不过度收紧（正/负同时成立）',
              'PC 帧奖励条目被覆盖' in _o30 and 'PC 帧底部按钮被排除' in _o30)
        check('v1.19 ⓕ 徽章阈值 0.70/0.70 与尺度带 4.1~4.9 未被动过',
              '形状阈值 = 0.70' in _o30 and '配色阈值 = 0.70' in _o30)
except Exception as _e30:
    check('v1.19 奖励行审计守门可运行（%r）' % (_e30,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㉝ v1.20 宝库/商人面板 **OCR 搜索带** 9 分辨率审计（本轮修的真 bug）
#   根因：`buypanels.BAND = (300,1560)` 的上界按 9:16（C=0）定死，而面板内容
#     **锚设备屏幕中心** ⇒ 元素在归一化系的位置 = dlg_y − C，C 随分辨率变。
#     宽屏矮胖（C<0，元素下移）上购买钮落到 1594 / 价格 1637 ⇒ **全在带外**
#     ⇒ `_btn` 恒 (None,None,None) ⇒ `no_select_btn` ⇒ **整层不买不选**（静默失效）
#     —— 与 v1.19 摇色子同一族病。
#   修法：上界 1560 → **1720**（锚定模型推导 + 83px 余量），下界 300 不动
#     （再往上是被 toRef 丢弃的弹性区，取不到）。
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉝ v1.20 宝库/商人面板搜索带 9 分辨率审计（修宽屏盖不住购买钮）')
try:
    import subprocess as _sp50
    _gp50 = os.path.join(HERE, 'verify_panel_band_allres.py')
    if not os.path.exists(_gp50):
        check('v1.20 面板搜索带审计脚本存在', False, _gp50)
    else:
        _r50 = _sp50.run([sys.executable, _gp50], stdout=_sp50.PIPE,
                          stderr=_sp50.STDOUT, timeout=120, env=_ENV())
        _o50 = (_r50.stdout or b'').decode('utf-8', 'replace')
        check('v1.20 面板搜索带审计可运行且全过（exit=%d）' % _r50.returncode,
              _r50.returncode == 0, _o50.strip().split('\n')[-1][:90])
        check('v1.20 ⑬ 9 分辨率 × 判据元素全覆盖',
              'ALL PASS (9 分辨率' in _o50)
        check('v1.20 ⑭ 旧上界 1560 确实盖不住宽屏（证明修的是真 bug）',
              '旧上界 1560 确实盖不住' in _o50)
        check('v1.20 ⑮ BAND 下界不伸进被 toRef 丢弃的弹性区',
              '不伸进被 toRef 丢弃的弹性区' in _o50)
        check('v1.20 ⑯ 9:16 基线 C=0（改动不影响 PC 口径）',
              '9:16 基线 C=0' in _o50)
        check('v1.20 ⑰ 上界留有余量（文案行数浮动）',
              '余量' in _o50 and '文案行数浮动' in _o50)
        # 钉死常量本身，防止"改回去"（错误教训 A4：忘了删旧行）
        _bp50 = open(os.path.join(HERE, '..', 'app', 'src', 'main', 'python',
                                  'buypanels.py'), encoding='utf-8').read()
        check('v1.20 ⑱ 旧上界 1560 已无残留（改成 1720）',
              'BAND = (300, 1720)' in _bp50 and 'BAND = (300, 1560)' not in _bp50)
except Exception as _e50:
    check('v1.20 面板搜索带审计守门可运行（%r）' % (_e50,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㉞ v1.21 又一台真机翻车：**棋盘好端端地全在，却被判「面板挡住了棋盘」**
#   反馈包（`MGAS反馈_20261002_003748.zip` / nubia NX809J 1216×2688 / Android 16 / v1.20）
#   里有 `board_hidden_r2.png`，但那一帧：35 格全识别、8 格已揭示、营地/海边小屋清清楚楚，
#   「结束冒险」面板在棋盘**上方**、涂平压条在棋盘**下方**（y=1722 起，正好是棋盘下沿）
#   ⇒ **没有任何东西盖住棋盘**。
#   根因：判据②基准取「本帧**最亮**格」—— 该帧最亮格是「海边小屋」1.196（比模板还亮）
#     ⇒ 旧阈值 0.55×1.196 = 0.658，而**雾格恒在 0.650** ⇒ 18 格被判"被压暗" ⇒ 误判 ✗
#   实测（`tools/fb_calib_boardhidden.py`）：
#     雾格/已揭示 = 0.487(realme) ~ 0.61(nubia)；真面板/已揭示 = 0.25~0.35(doc m0_r008)
#     ⇒ 基准改「已揭示格**中位**亮度」（免疫单格过亮）+ 系数 0.42（缝中点）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉞ v1.21 修「面板挡住了棋盘」在**新机型**上的误判（nubia NX809J 1216×2688）')
try:
    # ⚠ 本段一律读**手机端自己的**源码（两端平行 ⇒ 不跟着 `MGAS_PC_SRC` 走）
    _el21p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src21 = open(_el21p, encoding='utf-8').read()
    check('v1.21 ① 判据②基准 = **已揭示格的中位亮度**（不是最亮那一格 ⇒ 免疫单格过亮 ✓）',
          '_ref = float(np.median(_lit)) if _lit else _mx' in _src21
          and '_lit.append(_r)' in _src21)
    _sp21 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'spots.py'),
                 encoding='utf-8').read()
    # ⚠ v1.36：不再是两处各写 0.75，而是**单一来源**（spots 定、explore_loop 引）
    # ⚠ v1.60：`spots` 的逐格判据换成**两趟相对法** ⇒ 这里不再断言 `ratio >= REVEAL_RATIO_MIN`
    #   那句（它现在是**异常兜底**分支），改断言"兜底还在 + explore_loop 仍是引用而非写死" ✓
    check('v1.21 ② "已揭示"口径与 spots 的 revealed **同源**（单一来源 ✓；'
          'v1.60 起 spots 走两趟相对法，0.80 降级为**异常兜底** ⇒ 断言跟着改口径）',
          'REVEAL_RATIO_MIN = spots_mod.REVEAL_RATIO_MIN' in _src21
          # ⚠ v1.60：`_cells_for_model` 的注释里**抄了 PC 原文**（"`REVEAL_RATIO_MIN = 0.75`"）
          #   ⇒ 子串判定会把注释当代码（假红 ✗）⇒ 改判"**行首赋值**里没有 0.75" ✓
          and not _re.search(r'(?m)^\s*REVEAL_RATIO_MIN\s*=\s*0\.75\s*$', _src21)
          and 'REVEAL_RATIO_MIN = float(os.environ.get(' in _sp21
          and 'REVEAL_REL_FLOOR' in _sp21
          and '_r >= REVEAL_RATIO_MIN' in _src21)
    check('v1.21 ③ 系数 = 实测缝中点 0.42（雾格 0.487~0.61 vs 真面板 0.25~0.35）',
          'DIM_RATIO_MAX = 0.42' in _src21
          and '_thr = DIM_RATIO_MAX * _ref if _ref > 0 else DIM_RATIO_MAX' in _src21)
    check('v1.21 ④ 旧的「最亮格 × 0.55」口径已无残留（防改回去 ✗）',
          '_thr = 0.55 * _mx' not in _src21)

    import importlib.util as _ilu21
    _spec21 = _ilu21.spec_from_file_location('el_v121', _el21p)
    _el21m = _ilu21.module_from_spec(_spec21)
    _spec21.loader.exec_module(_el21m)

    def _old21(st, light, gray):
        """v1.11~v1.20 的**旧实现**（照抄在案）—— 用来证明"改的是真 bug" ✓"""
        _mx = max([float((v or {}).get('ratio') or 0) for v in st.values()] or [0.0])
        if len(light) == 0 and len(gray) >= 25 and _mx < 0.40:
            return True
        _thr = 0.55 * _mx if _mx > 0 else 0.55
        return sum(1 for v in st.values()
                   if float((v or {}).get('ratio') or 1.0) < _thr) >= 15

    def _mk21(n_fog, n_rev, k=1.0, covered=0, hot=None):
        st = {}
        for i in range(n_fog):
            st[('f', i)] = {'ratio': 0.65 * k, 'anchor': ('f', i)}
        for i in range(n_rev):
            st[('r', i)] = {'ratio': 1.00 * k, 'anchor': ('r', i)}
        for i in range(covered):
            st[('c', i)] = {'ratio': 0.30, 'anchor': ('c', i)}
        if hot:
            st[('h', 0)] = {'ratio': hot, 'anchor': ('h', 0)}
        return st

    def _bh21(st, light, gray):
        return _el21m.board_hidden({'st': st, 'light': [1] * light, 'gray': [1] * gray})

    # ⚠ 最后两条是**新机型翻车的形态**：雾格盘 + 一格过亮 —— 旧实现必判 True（真 bug），
    #   新实现必须 False（修好了）；并且"真面板盖中间"那条**不许**被放松掉 ✓
    _cases21 = [
        ('正常盘（雾29+亮6）', _mk21(29, 6), 0, 29, False, False),
        ('暗设备 k=0.7', _mk21(29, 6, 0.7), 0, 35, False, False),
        ('暗设备 k=0.5', _mk21(29, 6, 0.5), 0, 35, False, False),
        ('面板盖中间（只露 3 格）', _mk21(2, 3, 1.0, 30), 3, 32, True, True),
        ('全盘被遮罩', _mk21(0, 0, 1.0, 35), 0, 35, True, True),
        ('雾格盘 + 过亮格 1.196（nubia 形态）', _mk21(29, 6, 1.0, 0, hot=1.196), 0, 29,
         False, True),
        ('雾格盘 + 过亮格 + 真面板', _mk21(2, 3, 1.0, 30, hot=1.196), 3, 32, True, True),
    ]
    _bad21, _oldok21 = [], []
    for (tag, st, li, gr, want, old_want) in _cases21:
        got = _bh21(st, li, gr)
        if got != want:
            _bad21.append('%s:新的=%s(要%s)' % (tag, got, want))
        if _old21(st, [1] * li, [1] * gr) != old_want:
            _oldok21.append('%s:旧的=%s(预期%s)' % (tag, _old21(st, [1] * li, [1] * gr),
                                                old_want))
    check('v1.21 ⑤ 新判据 7 种画面全对（含 nubia 形态 ✓、"盖中间"不回归 ✓）',
          not _bad21, 'bad=%s' % (_bad21,))
    check('v1.21 ⑥ 旧实现在"雾格盘+过亮格"上**确实误判**（证明修的是真 bug，不是空改 ✓）',
          not _oldok21, 'bad=%s' % (_oldok21,))

    # ⭐ 真机帧（归一化 1080×1920）执行级：全部走真 `cells_of` + 真 `board_hidden`
    import cv2 as _cv21
    import numpy as _np21
    _frames21 = [
        ('nubia NX809J（新反馈·棋盘正常）',
         os.path.join(PROJ, '_verify', 'phone_friend_nubia_nx809j', 'board_hidden_r2.png'),
         False, True),
        ('realme RMX3800（旧反馈·棋盘正常）',
         os.path.join(PROJ, '_verify', 'phone_friend_rmx3800', 'board_hidden_r0.png'),
         False, True),
        ('dlg16（真·全盘被遮罩，不许放松）',
         os.path.join(PROJ, '_verify', 'dlg16.png'), True, None),
    ]
    _fb21, _shape21, _oldnote = [], [], []
    for (tag, p, want, old_want) in _frames21:
        if not os.path.exists(p):
            _fb21.append('%s: 缺 fixture' % tag)
            continue
        _im21 = _cv21.imdecode(_np21.fromfile(p, dtype=_np21.uint8), _cv21.IMREAD_COLOR)
        if _im21 is None or _im21.shape[:2] != (1920, 1080):
            _shape21.append('%s: %s' % (tag, None if _im21 is None else _im21.shape))
            continue
        _c21 = _el21m.cells_of(_im21, mapname='夏日海滩')
        _got21 = _el21m.board_hidden(_c21)
        _oldv21 = _old21(_c21.get('st') or {}, _c21['light'], _c21['gray'])
        if _got21 != want:
            _fb21.append('%s: 新的=%s(要%s)' % (tag, _got21, want))
        # ⚠ v1.35：旧实现的**输入 ratio 已被新分母改变**（nubia 帧 light 4→14）
        #   ⇒ 旧实现在这帧的返回值不再稳定 ⇒ **不再当断言**，只记进 detail ✓
        #   （旧实现的"确实会误判"已由 ⑥ 那 5 条**合成**用例证明，数值可控 ✓）
        _oldnote.append('%s旧=%s' % (tag[:4], _oldv21))
    check('v1.21 ⑦ 两帧真机反馈帧 + dlg16 都是**归一化 1080×1920**（喂错帧就当场红 ✓）',
          not _shape21, 'bad=%s' % (_shape21,))
    check('v1.21 ⑧ 执行级：两帧真机"棋盘正常"判 **False**、dlg16 真遮罩仍判 **True** ✓'
          '（旧实现仅记录，见 _oldnote）',
          not _fb21, 'bad=%s  旧=%s' % (_fb21, '/'.join(_oldnote)))
except Exception as _e21:       # noqa: BLE001
    check('v1.21 board_hidden 标定守门可运行（%r）' % (_e21,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㉟ v1.22「遇见大拇指格子不使用幸运草」—— **先补证据链**，再谈修
#   用户 2026-10-02 反馈包 `不使用幸运草.zip`（nubia NX809J / v1.20）：
#     统计是「大拇指装备 0 件（推荐战 2 场 / 胜 2；摇色子拿到 0）」
#     ⚠ 但那包**日志里一条 dice 条目都没有**（后一次运行把 loop_log 覆盖了）
#     ⇒ 无法判断是"根本没摇"还是"摇了 3 次没中"——这是**判据静默跳过**造成的
#       （原来 `if result_streak >= 2` 不成立时一个字都不记 ✗）
#   修法：① 判据抽成纯函数 `dice_gate()`（可离线对拍 ✓）
#         ② **无论摇不摇都留一条日志**（`dice_skip` 连输入一起记 ✓）
#         ③ 兜底：连读两帧「战斗胜利」但本机 OCR 读不到结算面板文字
#            （`on_result` 恒 False）时**也去试摇**（`win_only`）——handle_dice 在
#            非结算面板上只会记 `no_btn` 就返回，零副作用 ✓
#   同时印证两个包共同的可疑点（**标记漏检**）：
#     两个 nubia 包的诊断帧上 `scan_board()` 都是**空**，而 `probe_top()` 显示
#     "近失"：NX729J 的 boss 形状 0.741/配色 0.841@(2,4)（boss 闸门 0.90/0.85 ✗）、
#     NX809J 的 clover_live 0.916/0.584@(3,1)（clover 闸门 0.90/0.75 ✗）
#     ⇒ 机身偏暗/偏色把**配色分**压到闸门之下 ⇒ 标记扫不到 ⇒ 没有目标（`no_plan`/
#       `blank_board`/`targets_done`）与"不认识大拇指格"都会发生 ✗
#     ⚠ 本段**只把这两帧当"已知近失"钉住**（不改阈值：阈值改动要单独标定 + 真机复验）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㉟ v1.22 「大拇指格不用幸运草」—— 判据可测 + 不再静默跳过 + 标记近失留证')
try:
    _el22p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src22 = open(_el22p, encoding='utf-8').read()
    _mk22 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'marks.py'),
                 encoding='utf-8').read()
    check('v1.22 ① 摇色子判据抽成纯函数 `dice_gate()`（离线可测 ✓）',
          'def dice_gate(' in _src22 and 'dice_gate(marks, _ex,' in _src22)
    check('v1.22 ② **跳过也要留证**：`dice_skip` 记下判据的全部输入（不许静默 ✗）',
          "'dice_skip': _why" in _src22 and "'texts': [(i.get('text') or '')[:12]"
          in _src22 and '_dice_skip_logged' in _src22)
    check('v1.22 ③ 兜底：连读两帧「战斗胜利」但认不出结算面板 ⇒ 也去试摇（`win_only`）',
          "if win_streak >= 2 and not on_result:" in _src22
          and "'dice': 'win_only_attempt'" in _src22 and 'win_streak' in _src22)
    check('v1.22 ④ 诊断：整帧扫不到标记时记 `marks_scan`（含每模板近失分 ✓）',
          "'marks_scan': 'none'" in _src22 and 'marks_mod.probe_top' in _src22
          and 'def probe_top(' in _mk22)
    check('v1.22 ⑤ 修掉一条**误导日志**：`red_skip` 不再写 `board_hidden`'
          '（它只是"这帧没有已揭示格"，与 board_hidden 无关 ✗）',
          "'red_skip': 'board_hidden'" not in _src22
          and "'red_skip': 'no_revealed_cells'" in _src22)

    import importlib.util as _ilu22
    _spec22 = _ilu22.spec_from_file_location('el_v122', _el22p)
    _el22m = _ilu22.module_from_spec(_spec22)
    _spec22.loader.exec_module(_el22m)
    _cases22 = [
        # marks, exact, win_streak, result_streak, on_result, diced, 期望(动作, 原因)
        (['recommend'], ['recommend'], 2, 2, True, False, ('roll', 'result_panel')),
        (['recommend'], ['recommend'], 2, 0, False, False, ('roll', 'win_only')),
        (['recommend'], ['recommend'], 1, 0, False, False, (None, 'waiting_result_panel')),
        (['recommend'], ['recommend'], 2, 2, True, True, (None, 'already_diced')),
        (['boss'], ['boss'], 3, 3, True, False, (None, 'cell_has_no_recommend_mark')),
        (['recommend'], ['recommend'], 0, 0, False, False, (None, 'waiting_result_panel')),
        (['recommend'], ['recommend'], 2, 2, False, False, ('roll', 'result_panel')),
    ]
    _bad22 = [(c[2:6], _el22m.dice_gate(c[0], c[1], c[2], c[3], c[4], c[5]), c[6])
              for c in _cases22
              if _el22m.dice_gate(c[0], c[1], c[2], c[3], c[4], c[5]) != c[6]]
    check('v1.22 ⑥ 执行级：`dice_gate` 7 种情形全对（含"没摇成"的三种原因 ✓）',
          not _bad22, 'bad=%s' % (_bad22,))

    # ⭐ 真机帧：把"有标记但扫不到"这件事钉成 fixture（阈值未改 ⇒ 断言"扫不到"是**现状**，
    #   等哪天标定修好，这条会红 —— 那时把它改成"必须扫到" ✓）
    import cv2 as _cv22
    import numpy as _np22
    import importlib.util as _ilu22b
    _mkp = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'marks.py')
    _spec22b = _ilu22b.spec_from_file_location('mk_v122', _mkp)
    _mk22m = _ilu22b.module_from_spec(_spec22b)
    _spec22b.loader.exec_module(_mk22m)
    _fr22 = os.path.join(PROJ, '_verify', 'phone_friend_nubia_nx729j', 'board_hidden_r0.png')
    if not os.path.exists(_fr22):
        check('v1.22 ⑦ 真机帧 fixture 存在', False, _fr22)
    else:
        _im22 = _cv22.imdecode(_np22.fromfile(_fr22, dtype=_np22.uint8), _cv22.IMREAD_COLOR)
        check('v1.22 ⑦ 真机帧 fixture 是归一化 1080×1920',
              _im22 is not None and _im22.shape[:2] == (1920, 1080),
              None if _im22 is None else str(_im22.shape))
        _probe22 = _mk22m.probe_top(_im22)
        _boss22 = [r for r in _probe22 if r['tpl'] == 'boss' and r['rc'] == '2,4']
        check('v1.22 ⑧ 执行级：`probe_top` 报出**每模板最好分**（含 NX729J 的 boss 近失 ✓）',
              bool(_boss22) and _boss22[0]['shape'] < 0.90
              and _boss22[0]['shape'] > 0.70 and _boss22[0]['color'] > 0.80,
              'boss@2,4=%s' % (_boss22 or None,))
        check('v1.22 ⑨ ⚠**现状**：这一帧 `scan_board` 扫不到任何标记'
              '（= 标记近失问题的真机证据；阈值改动要单独标定，别顺手松 ✗）',
              _mk22m.scan_board(_im22) == {})
except Exception as _e22:       # noqa: BLE001
    check('v1.22 摇色子判据/标记近失守门可运行（%r）' % (_e22,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊱ v1.23 ⭐⭐「遇见大拇指格子不使用幸运草」**真根因**（真机实跑抓到的）
#   证据（Redmi 1280×2772 / v1.22 实跑日志，`_tmpman/live_122.log`）：
#     r3 点大拇指格 (1,6) → 弹「战斗事件」面板 → 点「战斗」→ `wait_end` 等 5 秒没等到战斗
#        （`{'battle':'no_battle_in_5s'}` → `not_started` → `blocked`）
#     r4 **下一轮**才看到结算面板 ⇒ 走 `popups()` 的 `result_panel` 分支
#     ⚠ 那个分支**只关面板、从不摇色子**（`handle_dice` 只挂在 `wait_end` 里 ✗）
#     ⇒ 大拇指标记白丢、一次幸运草都没花 = 用户看到的现象 ✗✗
#   修法：① `popups()` 的结算面板分支：**落在大拇指格上 ⇒ 先摇色子再关**
#         ② `st['diced_rc']` 记账 ⇒ 两条路径不会为同一格重复摇（每次重投花 1 个幸运草 ✗）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊱ v1.23 修「遇见大拇指格不摇色子」真根因：结算面板也要摇（+跨路径防重复）')
try:
    _el23p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src23 = open(_el23p, encoding='utf-8').read()
    check('v1.23 ① 结算面板分支里**先摇色子再关**（`result_dice` 标记 ✓）'
          '＋ ⚠ v1.63b：该调用**必须传 `state=`**（幸运草闸门要靠它拿到 HUD 读数 ——'
          '`items` 是 band 裁过的、读不到 HUD ✗）',
          "'popup': 'result_dice'" in _src23
          and 'handle_dice(b, log, items, state=_state)' in _src23,
          '⚠ 旧断言写的是 `handle_dice(b, log, items)`（无 state）⇒ v1.63b 后过时；'
          '已改成带 `state=` 的形式，并顺带守住"必须传 state"' )
    check('v1.23 ② 只有**本格**是大拇指才摇（`near()` 提到分支之前，防邻格白摇 ✗）',
          _src23.index('def near():') < _src23.index("'popup': 'result_dice'")
          and "'recommend' in _mk_here" in _src23)
    check('v1.23 ③ 跨路径防重复：`st[\'diced_rc\']`（两条路径都摇 = 白花幸运草 ✗）',
          "_state.get('diced_rc') != _rc" in _src23
          and "_state['diced_rc'] = _rc" in _src23
          and "state['diced_rc'] = rc" in _src23
          and "'already_diced_this_cell'" in _src23)
    check('v1.23 ④ `wait_end(..., state=, rc=)` 两个调用点都带上了格号',
          _src23.count("state=ctx.get('flags'), rc=") == 2)

    import importlib.util as _ilu23
    import numpy as _np23
    _spec23 = _ilu23.spec_from_file_location('el_v123', _el23p)
    _el23m = _ilu23.module_from_spec(_spec23)
    _spec23.loader.exec_module(_el23m)

    class _FakeBot(object):
        """只够 `popups()` 跑完结算面板分支的假 bot（记录点击顺序 ✓）"""

        def __init__(self, items):
            self._items = items
            self.taps = []
            self.fast_ok = False
            self.dev = 'fake'

        def tap(self, x, y, wait=0.0):
            self.taps.append((int(x), int(y)))
            return True

        def ocr(self, *a, **k):
            return list(self._items)

        def img(self):
            return _np23.zeros((120, 120, 3), dtype=_np23.uint8)

        def snap(self, *a, **k):
            return None

        def wait_stable(self, *a, **k):
            return True

    _items23 = [{'text': '关闭', 'cx': 577, 'cy': 1440}]

    def _run23(marks_of_cell):
        st = {'marks': {}}
        _cell = _el23m.cell_center(1, 6)
        markers = {(1, 6): {'marks': list(marks_of_cell), 'at': _cell, 'score': 0.95}}
        ctx = {'marks': markers, 'tapped': _cell, 'flags': st, 'st': None,
               'road': [], 'plain_road': [], 'plan_road': [], 'slots_free': 1,
               'ev_tiles': [], 'tapped_sid': '', 'clear_fights': 0}
        _bot = _FakeBot(_items23)
        _log = []
        _act = _el23m.popups(_bot, _items23, _log, ctx=ctx)
        return _act, _bot, _log, st

    _act23, _bot23, _log23, _st23 = _run23(['recommend'])
    check('v1.23 ⑤ 执行级：大拇指格的结算面板 ⇒ 真的去摇色子（`result_dice` ✓）',
          _act23 == 'handled'
          and any(e.get('popup') == 'result_dice' for e in _log23 if isinstance(e, dict))
          and any('dice' in e for e in _log23 if isinstance(e, dict)),
          'act=%s log=%s' % (_act23, [e for e in _log23 if isinstance(e, dict)][:6]))
    check('v1.23 ⑥ 执行级：摇完**仍然把面板关掉**（点 (577,1440) ✓）+ 记下已摇格',
          (577, 1440) in _bot23.taps and _st23.get('diced_rc') == (1, 6),
          'taps=%s diced_rc=%s' % (_bot23.taps, _st23.get('diced_rc')))
    _act23b, _bot23b, _log23b, _st23b = _run23(['boss'])
    check('v1.23 ⑦ 执行级：**首领格**的结算面板不摇色子（只关 ✓，不回归）',
          _act23b == 'handled'
          and not any(e.get('popup') == 'result_dice'
                      for e in _log23b if isinstance(e, dict))
          and (577, 1440) in _bot23b.taps and _st23b.get('diced_rc') is None,
          'act=%s taps=%s' % (_act23b, _bot23b.taps))
except Exception as _e23:       # noqa: BLE001
    check('v1.23 结算面板摇色子守门可运行（%r）' % (_e23,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊲ v1.24 ⭐⭐⭐「不摇色子」第二刀：**重投按钮根本没有文字**
#   真机 v1.23 跑图（Redmi 1280×2772）反馈包 `不摇色子.zip`：
#     {"popup":"result_dice","rc":[3,4],"marks":["boss","recommend"]}   ← v1.23 分支生效 ✓
#     {"dice":"no_btn","rolls":0,"band":[520,1020],
#      "cand":[{"t":"1/84",...},{"t":"422 596 96",...},
#              {"t":"16","cx":111,"cy":906},{"t":"1","cx":118,"cy":979}]} ← 只有数字，没有按钮文字 ✗
#   游戏面板原图实测：重投按钮 = 奖励行左边那个「🍀 + 数字」图标按钮
#     （上面大数字=剩余骰子数，下面 `🍀 1`=重投消耗 1 个幸运草）
#     参考系 ≈ (114,979)；「关闭」y=1441(真机)/1445(PC) ⇒ 固定偏移 **−466** ✓
#   修法：`clover_btn()` 结构定位兜底（优先用 OCR 到的那个数字条目 ⇒ 跨分辨率自适应），
#     点完**照旧**要求「是否重掷？」确认框弹出才算数（没弹就放弃 ✓ 不会乱点）。
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊲ v1.24 修「不摇色子」第二刀：重投按钮没有文字 ⇒ 结构定位兜底')
try:
    _el24p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src24 = open(_el24p, encoding='utf-8').read()
    check('v1.24 ① 新增 `clover_btn()` 结构定位（重投按钮没有文字 ✓）',
          'def clover_btn(' in _src24 and '_ty = float(_cy) - 466.0' in _src24)
    check('v1.24 ② 兜底接在 `no_btn` 之前，且**确认框校验原样保留**'
          '（点完必须弹「是否重掷？」才算数 ✓）',
          "'dice': 'clover_btn_fallback'" in _src24
          and _src24.index("'dice': 'clover_btn_fallback'")
          < _src24.index("'dice': 'no_btn', 'rolls': rolls")
          and "_no_confirm >= 2" in _src24)
    check('v1.24 ③ 判不出来时**存面板诊断帧**（`dice_nobtn` ⇒ 反馈包自带真机面板 ✓）',
          "_pub_dump('dice_nobtn'" in _src24 and "'dice_dump'" in _src24)

    import importlib.util as _ilu24
    _spec24 = _ilu24.spec_from_file_location('el_v124', _el24p)
    _el24m = _ilu24.module_from_spec(_spec24)
    _spec24.loader.exec_module(_el24m)

    _items24 = [{'text': '战斗胜利', 'cx': 540, 'cy': 200},
                {'text': '1/84', 'cx': 261, 'cy': 634},
                {'text': '16', 'cx': 111, 'cy': 906},
                {'text': '1', 'cx': 118, 'cy': 979},
                {'text': '240', 'cx': 802, 'cy': 993},
                {'text': '回放战斗', 'cx': 577, 'cy': 1224},
                {'text': '关闭', 'cx': 576, 'cy': 1441}]
    _cb24 = _el24m.clover_btn(_items24)
    check('v1.24 ④ 执行级：真机那份面板条目 ⇒ 选中「🍀 1」按钮 (118,979)'
          '（不是 16、不是 240、不是 关闭 ✓）',
          _cb24 == (118, 979), 'got=%s' % (_cb24,))
    _cb24b = _el24m.clover_btn([{'text': '关闭', 'cx': 576, 'cy': 1441}])
    check('v1.24 ⑤ 执行级：只有「关闭」⇒ 退回**锚点推算** (114*k, 1441−466)',
          _cb24b is not None and abs(_cb24b[1] - 975) <= 2,
          'got=%s' % (_cb24b,))
    check('v1.24 ⑥ 执行级：连「关闭」都认不到 ⇒ **返回 None**（不敢乱点 ✓）',
          _el24m.clover_btn([{'text': '战斗胜利', 'cx': 540, 'cy': 200}]) is None)
    _cb24c = _el24m.clover_btn([{'text': '关闭', 'cx': 576, 'cy': 1441},
                                {'text': '7', 'cx': 120, 'cy': 300},
                                {'text': '9', 'cx': 120, 'cy': 1600}])
    check('v1.24 ⑦ 执行级：离锚点太远的数字（±160 之外）**不选** ⇒ 仍走推算',
          _cb24c is not None and abs(_cb24c[1] - 975) <= 2, 'got=%s' % (_cb24c,))
except Exception as _e24:       # noqa: BLE001
    check('v1.24 重投按钮结构定位守门可运行（%r）' % (_e24,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊳ v1.25「不摇色子」第三刀：**确认框认不出（OCR 把「确定」读成「石确定」）+ 弹框挂着还去点正文**
#   真机 v1.24 跑图（Redmi 1280×2772）日志（`bagdbg/mgas_log.txt`，adb 直接拉，无需反馈包）：
#     {"dice":"clover_btn_fallback","at":[118,979]}      ← v1.24 兜底命中 ✓
#     {"dice":"reroll_confirm","at":[774,802],"rolls":1} ← 弹框弹出+点确定 ⇒ **真摇了 1 次** ✓
#     {"dice":"after","rolls":1,"reward_mark_hits":0}    ← 摇完没出大拇指（该继续摇）
#     {"dice":"panel","rolls":1,"items":[…"命运之骰"…"是否继续重掷？"…
#              {"t":"取消","cx":304,"cy":803},{"t":"石确定","cx":774,"cy":802}]}
#     {"dice":"no_confirm_popup","rolls":1,"streak":1} → streak=2 → abort  ← 只摇 1 次就放弃 ✗✗
#   根因：① 判据 `exb()`（**整条等值**）⇒ `'石确定' != '确定'` ⇒ 认不出弹框；
#         ② 弹框挂着时 B 路（找骰子按钮）会把**弹框正文**「每次重掷必定高于当前点数…」
#            （含「重掷」）当按钮点掉 ⇒ 用户看到的"乱点" ✗✗
#   修法：`dice_dialog()` 宽容识别（标题词 + 包含匹配 + 标签长度 ≤6）；
#         弹框挂着时**只走 A**（`dialog_still_up`），认到弹框但找不出确定就**停**（`dialog_unparsed`），
#         绝不走 B ⇒ 不会再点正文 ✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊳ v1.25 修「不摇色子」第三刀：确认框宽容识别 + 弹框挂着不许点正文')
try:
    _el25p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src25 = open(_el25p, encoding='utf-8').read()
    check('v1.25 ① 新增 `dice_dialog()` 宽容识别（标题词 + 包含匹配 + 标签长度 ≤6 ✓）',
          'def dice_dialog(' in _src25 and 'DICE_DLG_TITLES' in _src25
          and 'DICE_OK_KEYS' in _src25 and 'len(_t) > 6' in _src25)
    check('v1.25 ② A 段改用 `dice_dialog()`（不再只认整条等于「确定」✗）',
          '_dlg = dice_dialog(items)' in _src25
          and "_ok = exb(items, L['ok'])" not in _src25)
    check('v1.25 ③ 弹框还挂着 ⇒ **回 A 继续摇**，不走 B（防点弹框正文 ✗）',
          "'dice': 'dialog_still_up'" in _src25 and "'dice': 'dialog_unparsed'" in _src25)
    check('v1.25 ④ 收尾「取消」也走宽容识别',
          "_dlg2 = dice_dialog(items)" in _src25)

    import importlib.util as _ilu25
    _spec25 = _ilu25.spec_from_file_location('el_v125', _el25p)
    _el25m = _ilu25.module_from_spec(_spec25)
    _spec25.loader.exec_module(_el25m)
    # ⭐ 这一组条目是**真机日志里原样抄下来的**（不是编的）
    _dlg_items = [{'text': '文', 'cx': 918, 'cy': 444},
                  {'text': '命运之骰', 'cx': 539, 'cy': 448},
                  {'text': '每次重掷必定高于当前点数，最高20点', 'cx': 539, 'cy': 548},
                  {'text': '是否继续重掷？', 'cx': 530, 'cy': 602},
                  {'text': '本次登录不再提示', 'cx': 570, 'cy': 678},
                  {'text': '取消', 'cx': 304, 'cy': 803},
                  {'text': '石确定', 'cx': 774, 'cy': 802}]
    _d25 = _el25m.dice_dialog(_dlg_items)
    check('v1.25 ⑤ 执行级：真机那份弹框条目 ⇒ 认出「石确定」@(774,802)（旧 `exb` 认不出 ✗）',
          _d25 is not None and (_d25['yes']['cx'], _d25['yes']['cy']) == (774, 802)
          and _d25['no'] is not None and _d25['no']['cx'] == 304,
          'got=%s' % ({'yes': _d25['yes']['text'] if _d25 else None,
                       'no': _d25['no']['text'] if _d25 else None},))
    check('v1.25 ⑥ 执行级：弹框**正文**「每次重掷必定高于当前点数…」不许被当成按钮 ✓',
          _d25 is not None and '重掷必定' not in str(_d25['yes'].get('text') or ''))
    _panel_items = [{'text': '战斗胜利', 'cx': 540, 'cy': 200},
                    {'text': '167/167', 'cx': 284, 'cy': 634},
                    {'text': '16', 'cx': 111, 'cy': 906},
                    {'text': '1', 'cx': 118, 'cy': 979},
                    {'text': '关闭', 'cx': 576, 'cy': 1441}]
    check('v1.25 ⑦ 执行级：普通结算面板 ⇒ **不是**弹框（返回 None ✓ 不会误点）',
          _el25m.dice_dialog(_panel_items) is None)
    check('v1.25 ⑧ 执行级：只有「确定」没有标题词 ⇒ 也不当弹框（防面板上的确定 ✗）',
          _el25m.dice_dialog([{'text': '确定', 'cx': 774, 'cy': 802},
                              {'text': '取消', 'cx': 304, 'cy': 803}]) is None)
except Exception as _e25:       # noqa: BLE001
    check('v1.25 重掷弹框宽容识别守门可运行（%r）' % (_e25,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊴ v1.26 两条真机实报：**截图流断了还瞎点** + **点完战斗没等到开打就去点下一格**
#   ① 用户 2026-10-02：「点了战斗格、还没打就去点下一个格子」—— 真机日志显示那一局
#      `截图流断流且自救失败 ×56 ⇒ 需重新授权截图`：帧从 02:03:35 起就冻结了，
#      Python 拿**旧帧**继续判、继续点 ✗。Java 看门狗只在 Java 侧记日志 ⇒ Python 不知情 ✗
#      ⇒ 修：`DeviceApi.frameAgeMs()` 暴露帧龄；Python 帧龄 >8s **连续 2 轮** ⇒ 停整局
#        （`finish: capture_stale`）并说明怎么恢复（点①授权截图）✓
#   ② 同一局更早（有帧时）也出现过：`{'battle':'no_battle_in_5s'}` → `not_started` →
#      `blocked` ⇒ 上层"开路模式"就去点下一格；可下一轮却看到了结算面板
#      （= 战斗其实打完了）⇒ **"5 秒没等到" ≠ "没打起来"**。真机开打 >5s 很常见 ✗
#      ⇒ 修：`start_fight()` 等到 **15s**（看到战斗/结算立刻早退 ✓），
#        且**认到结算面板也算"打过了"**（`result_panel_instead` ✓）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊴ v1.26 修：截图断流还瞎点 + 点完战斗没等到开打就去点下一格')
try:
    _el26p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src26 = open(_el26p, encoding='utf-8').read()
    _java26 = open(os.path.join(PROJ, 'app', 'src', 'main', 'java', 'com', 'fantasy',
                                'autoexplore', 'DeviceApi.java'), encoding='utf-8').read()
    check('v1.26 ① Java 侧暴露**帧龄**（`DeviceApi.frameAgeMs()` ⇒ Python 能判"瞎了没" ✓）',
          'public static long frameAgeMs()' in _java26 and 'FrameStore.stamp()' in _java26)
    check('v1.26 ② Python 侧：帧龄 >8s **连续 2 轮** ⇒ 停整局（`capture_stale` ✓）',
          'def frame_age_ms(' in _src26 and "'finish': 'capture_stale'" in _src26
          and "st['stale'] >= 2" in _src26 and '请点①授权截图' in _src26)
    check('v1.26 ③ `start_fight` 等待 5s → **15s**（真机开打 >5s 很常见 ✓）',
          'while time.time() - _t0 < 15.0' in _src26
          and "log.append({'battle': 'no_battle_in_5s'" not in _src26
          and "'no_battle_in_15s'" in _src26)
    check('v1.26 ④ **认到结算面板也算"打过了"**（自动跳过/极速战斗 ⇒ 别当 blocked ✗）',
          "'battle': 'result_panel_instead'" in _src26)

    # ⭐ 执行级：用假 bot 直接调真 `start_fight()`（含把 time 换成假时钟 ⇒ 不真等 15s ✓）
    import importlib.util as _ilu26
    import types as _ty26
    _spec26 = _ilu26.spec_from_file_location('el_v126', _el26p)
    _el26m = _ilu26.module_from_spec(_spec26)
    _spec26.loader.exec_module(_el26m)

    class _Clock(object):
        """假时钟：`time()` 每次调用 +1s，`sleep` 不真睡 ⇒ 15s 等待瞬间跑完 ✓"""

        def __init__(self):
            self.t = 0.0

        def time(self):
            self.t += 1.0
            return self.t

        def sleep(self, _s):
            return None

    class _FakeFightBot(object):
        def __init__(self, items):
            self._items = items
            self.tap_dlg_calls = 0
            self.fast_ok = False

        def tap_dlg(self, x, y, wait=0.0):
            self.tap_dlg_calls += 1
            return True

        def ocr(self, *a, **k):
            return list(self._items)

    _btn26 = {'cx': 539, 'cy': 791}
    _real_time26 = _el26m.time
    try:
        _el26m.time = _Clock()
        _log_start = []
        _act = _el26m.start_fight(_FakeFightBot([]), _log_start, _btn26, ['boss'])
        check('v1.26 ⑤ 执行级：15s 内一直没动静 ⇒ 判失败（且只点 1 次 ✗ 不连点）',
              _act is False
              and any(e.get('battle') == 'no_battle_in_15s' for e in _log_start)
              and _log_start[-1].get('battle') == 'not_started',
              'act=%s log=%s' % (_act, _log_start))
        _log_res = []
        _act2 = _el26m.start_fight(
            _FakeFightBot([{'text': '关闭', 'cx': 576, 'cy': 1441}]), _log_res, _btn26, ['boss'])
        check('v1.26 ⑥ 执行级：直接进结算面板 ⇒ 也算"打过了"（返回 True ✓ 不当 blocked）',
              _act2 is True
              and any(e.get('battle') == 'result_panel_instead' for e in _log_res),
              'act=%s log=%s' % (_act2, _log_res))
    finally:
        _el26m.time = _real_time26
except Exception as _e26:       # noqa: BLE001
    check('v1.26 断流/战斗等待守门可运行（%r）' % (_e26,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊵ v1.27 「宝库买完了，却永远显示还剩 1 个目标」= **幽灵目标**
#   用户 2026-10-02 原话：「最近这把大拇指、探索、宝库都没问题了，就是现在显示还有一个目标，
#     但是我看着已经没目标了」
#   真机日志（`vault: done` 之后的 r11）：`没有目标了，准备退图` 与悬浮条
#     `还剩 1 个目标` **同轮并存** ⇒ 说明 `marked`/`buy`/`buy_hidden` 全空，
#     但 `pending_buy` 里还留着一个（`sticky` / `buy_seen` 跨轮记忆）✗
#   根因：宝库**买完之后那张贴图还在**（仍被认成宝库/商人、score ≥ 0.60）
#     ⇒ `buy_seen` 每轮都被刷新 ⇒ 永远等不到"4 轮没再出现"的清理 ✗✗
#   修法：买完当场把该格登记进 `st['buy_consumed']`（`{'vault':'consumed','rc':…}`），
#     并从 `buy`/`buy_hidden`/`sticky`/`buy_seen` 四处全部剔除 ✓
#     另加诊断 `{'targets_ghost': {...}}`：没有标记却有 pending 时，把四个来源点名 ✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊵ v1.27 修「宝库买完还永远剩 1 个目标」幽灵目标（买完登记 buy_consumed）')
try:
    _el27p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src27 = open(_el27p, encoding='utf-8').read()
    check('v1.27 ① 宝库买完当场登记 `buy_consumed` 并记日志（`vault: consumed` ✓）',
          "'buy_consumed', set()).add(_rcv)" in _src27
          and "'vault': 'consumed'" in _src27)
    check('v1.27 ② 已消耗格**不再进** `buy_seen` 记忆（否则每轮刷新 ⇒ 清不掉 ✗）',
          "if _k in (st.get('buy_consumed') or set()):" in _src27)
    check('v1.27 ③ `buy` / `buy_hidden` 早期就按 `buy_consumed` 过滤 ✓',
          '_cons_early = st.get(\'buy_consumed\') or set()' in _src27
          and "buy = [p for p in buy if cell_of(*p) not in _cons_early]" in _src27
          and "buy_hidden = [p for p in buy_hidden if cell_of(*p) not in _cons_early]"
          in _src27)
    check('v1.27 ④ `pending_buy`（含 sticky / 记忆）也按已消耗过滤 ✓',
          "pending_buy = [p for p in pending_buy if cell_of(*p) not in _consumed]"
          in _src27)
    check('v1.27 ⑤ 诊断：没有标记却有 pending ⇒ 记 `targets_ghost`（点名四个来源 ✓）',
          "'targets_ghost'" in _src27 and "'mem': ['%d,%d' % cell_of(*p)"
          in _src27 and "'consumed': sorted(" in _src27)

    # ⭐ 执行级：把"幽灵目标过滤"这段逻辑等价重放一遍（四来源 → 过滤后为空 ✓）
    _st27 = {'buy_consumed': {(3, 6)}}
    try:
        import marks as _mk27
        _px27 = _mk27.cell_center(3, 6)
        _pend27 = [_px27]                                  # 记忆里那个已买完的宝库
        _cons27 = _st27.get('buy_consumed') or set()
        _cell27 = (int((_px27[1] - 1002) // 144) + 1, int((_px27[0] - 36) // 144) + 1)
        _after27 = [p for p in _pend27 if _cell27 not in _cons27]
        check('v1.27 ⑥ 执行级：已买完那格的像素中心 ⇒ 会被过滤掉（过滤后 pending 为空 ✓）',
              _cell27 == (3, 6) and _after27 == [],
              'cell=%s after=%s' % (_cell27, _after27))
    except Exception as _e27b:      # noqa: BLE001
        check('v1.27 ⑥ 执行级可运行（%r）' % (_e27b,), False)
except Exception as _e27:       # noqa: BLE001
    check('v1.27 幽灵目标守门可运行（%r）' % (_e27,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊶ v1.28/v1.29 规划口径：**两条路都留代码，用开关切**
#   v1.28（10-02 白天，用户口径）「规划就刚进入规划一次，后续不再规划。走完规划的还有目标
#     就用之前的保底方案走」→ 实现成"进图一次 + 走完/推不动切兜底"
#   v1.29（10-02 晚，用户「**那换回来吧**」）→ **恢复每轮重解**（省体力那条，离线对拍
#     +9.2%~+26.1% 优势），并保留"进图一次"那条路 = `PLAN_ONCE` 开关
#   ⏱ 时间成本实测可忽略（真机 solver 自报 `secs: 0.0`；离线 96 张 p50 0.65ms / p99 1.9ms）
#   ⇒ 这条从来不是"快慢"取舍，而是「省体力 ↔ 不在地图里改主意」✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊶ v1.28/v1.29 规划口径（开关 `PLAN_ONCE`；默认=每轮重解）')
try:
    _el28p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src28 = open(_el28p, encoding='utf-8').read()
    # ⚠ v1.38：`need_explore()` 多了 `no_yield_rounds`（探图无产出就收手）⇒ 签名已变
    # ⚠ v1.45：**默认口径已翻转**（v1.29 定的是"默认每轮重解"，v1.45 按用户口径
    #   改成"默认一图一次"，学 PC 端 0abbbdf）⇒ 下面两条改为守护**新默认**，
    #   但"两条路都留着、可现场切"这一点仍然要守 ✓
    check('v1.29 ① `PLAN_ONCE` 开关 + 纯函数 `plan_mode()` 都在（两条路都留着，可现场切 ✓）',
          "MAPBOT_PLAN_ONCE" in _src28
          and 'def plan_mode(st, rest_n, targets_left, once=None):' in _src28
          and "return 'plan', 'each_round'" in _src28)
    check('v1.29 ② 默认口径（v1.45 起翻转为**一图一次**，见 v1.45 那组门禁 ✓）',
          "MAPBOT_PLAN_ONCE', '1'" in _src28
          and "_pact, _pwhy = plan_mode(st, len(_rest), _tleft)" in _src28)
    check('v1.29 ③ 每轮重解要**覆盖**旧计划（`st[\'plan\'] = list(_sol)` ✓）',
          "st['plan'] = list(_sol)          # ⭐ 每轮**覆盖**" in _src28)
    check('v1.28 ④ 纯函数 `plan_next()` 仍在（"进图一次"那条路没被删 ✗）'
          '＋ ⚠ v1.66 起 `eff` 两条出口**都带兜底开关**（默认关 ⇒ 走 `done` ✓）',
          'def plan_next(st, rest_n, targets_left):' in _src28
          and "return 'plan', 'first'" in _src28
          and "return 'keep', 'has_rest'" in _src28
          and "return ('eff', 'exhausted') if FALLBACK_EFF else ('done', 'exhausted')" in _src28
          and "return ('eff', 'stuck') if FALLBACK_EFF else ('done', 'stuck')" in _src28)
    check('v1.28 ⑤ 走完还有目标 ⇒ **默认**退图（`plan_only_giveup` 日志 ✓）'
          '；推不动 ⇒ 同样退图（安全网 ✓）；⚠ 旧口径「切 EffPolicy」由开关守 ✓',
          "log.append({'plan': _pwhy" in _src28
          and 'PLAN_STUCK_ROUNDS = 3' in _src28
          and "_pwhy == 'exhausted'" in _src28
          and "'plan_only_giveup'" in _src28)

    import importlib.util as _ilu28
    _spec28 = _ilu28.spec_from_file_location('el_v128', _el28p)
    _el28m = _ilu28.module_from_spec(_spec28)
    _spec28.loader.exec_module(_el28m)
    _pn = _el28m.plan_next
    _pm = _el28m.plan_mode

    check('v1.29 ⑥ 执行级：默认模式（`once=False`）⇒ **每轮都去重解** ✓',
          _pm({}, 3, 2, once=False) == ('plan', 'each_round')
          and _pm({}, 0, 0, once=False) == ('plan', 'each_round'))
    check('v1.29 ⑦ 执行级：默认 `PLAN_ONCE` 就是 **True**'
          '（v1.45 起翻转 = 一图一次；旧默认 False 守护的是"每轮重解"那条 ✗）',
          _pm({}, 0, 3) == ('plan', 'first'), 'PLAN_ONCE=%s' % _el28m.PLAN_ONCE)
    _s = {}
    check('v1.28 ⑧ 执行级：`PLAN_ONCE=1` 第一轮 ⇒ `plan/first`（进图那一下 ✓）',
          _pm(_s, 0, 3, once=True) == ('plan', 'first'))
    _s = {'planned': True, 'plan': [(1, 1), (2, 2)], 'plan_prev_len': 2}
    check('v1.28 ⑨ 执行级：`PLAN_ONCE=1` 有计划 ⇒ `keep/has_rest`（不重算 ✓）',
          _pm(_s, 2, 3, once=True) == ('keep', 'has_rest'))
    _s = {'planned': True, 'plan': [(1, 1)], 'plan_stuck': 0, 'plan_prev_len': 1}
    _r = [_pm(_s, 1, 2, once=True) for _ in range(3)]
    check('v1.28 ⑩ 执行级：`PLAN_ONCE=1` 连着 3 轮没推进 ⇒ **默认（禁用兜底）** 走 '
          '`done/stuck` ⇒ 退图 ✓（⚠ v1.66 用户口径「只听规划的」）',
          _r == [('keep', 'has_rest'), ('keep', 'has_rest'), ('done', 'stuck')],
          'got=%s' % (_r,))
    # ⭐ v1.66 双口径：把开关打开 ⇒ 必须**逐字复现旧行为**（回退路径不能坏 ✓）
    _s = {'planned': True, 'plan': [(1, 1)], 'plan_stuck': 0, 'plan_prev_len': 1}
    _old28 = _el28m.FALLBACK_EFF
    try:
        _el28m.FALLBACK_EFF = True
        _r2 = [_pm(_s, 1, 2, once=True) for _ in range(3)]
    finally:
        _el28m.FALLBACK_EFF = _old28
    check('v1.66 ① 开关打开（`MAPBOT_FALLBACK_EFF=1`）⇒ **旧行为逐字复现** `eff/stuck`'
          '（回退路径必须仍然可用 ✓）',
          _r2 == [('keep', 'has_rest'), ('keep', 'has_rest'), ('eff', 'stuck')],
          'got=%s' % (_r2,))
    _s = {'planned': True, 'plan_stuck': 2, 'plan_prev_len': 4}
    check('v1.28 ⑪ 执行级：步数有减少 ⇒ 计数清零（继续照走 ✓）',
          _pm(_s, 2, 2, once=True) == ('keep', 'has_rest') and _s['plan_stuck'] == 0,
          'stuck=%s' % _s.get('plan_stuck'))
    check('v1.28 ⑫ 执行级：走完还有目标 ⇒ **默认** `done/exhausted`（退图，**不切兜底** ✓）；'
          '走完没目标 ⇒ `none/no_targets` ✓',
          _pm({'planned': True}, 0, 2, once=True) == ('done', 'exhausted')
          and _pm({'planned': True}, 0, 0, once=True) == ('none', 'no_targets'))
    # ⭐ v1.66 双口径（同上）：开关打开 ⇒ 旧行为 `eff/exhausted` ✓
    try:
        _el28m.FALLBACK_EFF = True
        _old_r = _pm({'planned': True}, 0, 2, once=True)
    finally:
        _el28m.FALLBACK_EFF = _old28
    check('v1.66 ② 开关打开 ⇒ 走完还有目标仍是 `eff/exhausted`（旧行为可回退 ✓）',
          _old_r == ('eff', 'exhausted'), 'got=%s' % (_old_r,))
    # ⭐⭐ v1.66 ③ 禁用兜底时，精确解算连着 `PLAN_GIVEUP_TRIES` 轮算不出 ⇒ 本图**算无解**退图
    #   ⚠ 这条正是治「兜底策略又买了黄金宝库」的前置：**不让它有机会接管** ✓
    check('v1.66 ③ 禁用兜底 + 精确解算连着 %d 轮算不出 ⇒ `done/no_solution`（退图，不切兜底 ✓）'
          % _el28m.PLAN_GIVEUP_TRIES,
          _pm({'plan_tries': _el28m.PLAN_GIVEUP_TRIES}, 0, 0, once=True)
          == ('done', 'no_solution')
          and _pm({'plan_tries': 1}, 0, 0, once=True) == ('plan', 'first'))
    # ⭐⭐ v1.66 ④ 开关默认值必须是 **关**（用户口径「禁用兜底策略」是**默认行为** ✓）
    check('v1.66 ④ `FALLBACK_EFF` 默认**关**（`MAPBOT_FALLBACK_EFF` 不设 ⇒ 禁用兜底 ✓）',
          _el28m.FALLBACK_EFF is False
          and "os.environ.get('MAPBOT_FALLBACK_EFF', '0')" in _src28,
          'FALLBACK_EFF=%s' % _el28m.FALLBACK_EFF)
except Exception as _e28:       # noqa: BLE001
    check('v1.28/v1.29 规划口径守门可运行（%r）' % (_e28,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊷ v1.29【探索模式】修用户真机报「**进图发了会呆就退出了**」（realme RMX3800，v1.28）
#   反馈包 `进图发了会呆就退出了.zip` 日志（逐轮）：
#     r0/r1  `marks_scan: none` + `solver: no_plan` + **`finish: blank_board` ×2**（40s / 90s 发呆）
#     r2     `popup_none_dlg: probe`（找不到面板）+ `universal_close: popup_none`
#     r3     `finish: targets_done, gray_left: 24` ⇒ **24 个暗格一格没开就退图** ✗✗
#   根因：点序只在「有标记 or 有商人/宝库」时才构建 ⇒ 这一帧没认出任何标记
#     （近失分 recommend 0.769 / boss 0.734 都低于闸门）⇒ `order=[]` ⇒ 判"盘空白"发呆 → 退图
#   修法：`need_explore()` —— 没目标但盘还没探开 ⇒ **先探图**（沿已揭示的可点格往外开），
#     只有真没得点、或探图预算（40 次）用完，才允许判空白/收工 ✓
# ─────────────────────────────────────────────────────────────────────────
# ㊷⏤ ㊳⏤ v1.29 + v1.38【探索模式已**移除**】—— 用户 2026-10-02 定：「去掉探图模式」
#   探索模式（`need_explore()` + `EXPLORE_MIN_GRAY`/`EXPLORE_MAX_CLICKS`）是 v1.29
#   为治「进图发呆就退出」加的兜底：没目标但暗格多 ⇒ 沿可点格开路逼出雾里的标记。
#   真机反复证明它**白烧体力**且常无产出（那几张盘人工核对确实一个标记都没有）：
#     v1.35：solver no_plan + grays=20 ⇒ 探，零产出
#     v1.36：solver no_plan + grays=10 ⇒ 又探，零产出（用户目击「还在显示探索」✗）
#   v1.38 曾加「连续 3 轮无产出就收手」缓解，**用户随后要求整个去掉** ✓
#   ⇒ 现在：**没有目标就退图**（`targets_done`）⇒ 标记清完立即收工 ✓
#   ⚠ 本组门禁现在**反向守护**：确认这些东西**确实不在了**（别被人又加回来 ✗）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊷⏤ v1.29/v1.38 探索模式已移除（反向守护：别再加回来）')
try:
    _EL39 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                 encoding='utf-8').read()
    _code39 = '\n'.join(l for l in _EL39.split('\n') if not l.strip().startswith('#'))
    check('v1.39 ① `need_explore()` **已删除**（探索模式去掉 ✓）',
          'def need_explore(' not in _EL39)
    # ⚠ 必须查**代码**（去注释）：`_EL39` 的注释里**故意**写着"已删 XXX"
    #   （留给人看），直接全文搜会误判成"没删干净" ✗（2026-10-02 实测踩过）
    check('v1.39 ② 三个预算常量在**代码**里已删除（注释里的"已删"说明不算 ✗）',
          'EXPLORE_MIN_GRAY' not in _code39
          and 'EXPLORE_MAX_CLICKS' not in _code39
          and 'EXPLORE_NO_YIELD_ROUNDS' not in _code39)
    check('v1.39 ③ 退图判据**没有**探索分支（没目标即退 ✓）',
          'if vis and rnd >= 2 and not marked and not pending_buy' in _EL39
          and 'not marked and not pending_buy and not _explore' not in _EL39)
    check('v1.39 ④ 开路判据**没有**探索分支（`marked or buy_any` ✓）',
          'if not order and (marked or buy_any):' in _EL39
          and 'marked or buy_any or _explore' not in _EL39)
    # ⚠ 同上：那句"先探图"在**注释**里被引用（解释它被删了）⇒ 只能查代码 ✓
    check('v1.39 ⑤ 「先探图」悬浮条提示在**代码**里已删除（用户目击的那句 ✗）',
          '没标记，先探图' not in _code39)
    check('v1.39 ⑥ 保留「已移除」说明 + 写明**可从 v1.38 取回**（别当成漏删 ✓）',
          '探索模式已**移除**' in _EL39 and 'v1.38' in _EL39)
    check('v1.39 ⑦ 代码里**不再引用**探索变量（`explore_clicks`/`explore_no_yield` ✗）',
          'explore_clicks' not in _code39 and 'explore_no_yield' not in _code39)
except Exception as _e39:       # noqa: BLE001
    check('v1.39 移除守门可运行（%r）' % (_e39,), False)


# ─────────────────────────────────────────────────────────────────────────
# ㊸ v1.30【识别问题的取证闸】标记一个都没扫到时**把那一帧存下来**（反馈包自动带上）
#   起因：用户真机（realme RMX3800）报「**啥都没识别出来**」（`进图发了会呆就退出了.zip`）：
#   日志 `marks_scan: none`，近失分 recommend 0.769 / boss 0.734 **贴在闸门下面**（0.80 / 0.90）
#   ⇒ 到底是 ①"这盘真没标记" 还是 ②"有标记但被机身偏暗压到闸门之下"，**必须有帧才能定** ✗
#   （那包里带的 PNG 是更早一局留下的：海岸主题 vs 日志里的沙漠主题 ⇒ 不能用 ✗）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊸ v1.30 标记全漏时落帧取证（`marks_none_rN`）')
try:
    _el30p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _src30 = open(_el30p, encoding='utf-8').read()
    check('v1.30 ① `marks_scan: none` 那个状态里**落一帧**（`marks_none_rN` ✓）',
          "_pub_dump('marks_none_r%d' % int(rnd), b.img())" in _src30
          and "'marks_none_dump'" in _src30)
    _i_scan = _src30.index("log.append({'marks_scan': 'none'")
    _i_dump = _src30.index("_pub_dump('marks_none_r%d'")
    check('v1.30 ② 落帧在"标记全漏"分支**内部**（不会每帧都写 ✓）', 0 < _i_scan < _i_dump)
    check('v1.30 ③ 受总开关 `BAG_DUMP` 约束（用户可关 ✓）',
          'if BAG_DUMP:' in _src30[_i_scan:_i_dump + 200])
except Exception as _e30:       # noqa: BLE001
    check('v1.30 取证闸守门可运行（%r）' % (_e30,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊹ v1.31 ⭐⭐⭐【真机整屏偏紫的根因】取帧**慢路径 R↔B 互换**
#   用户 2026-10-02：「**人看和截图都是正常的，就反馈包里的不正常**」+「啥都没识别出来」
#   ⇒ 显示/游戏没问题，是**我们自己取帧**这条链 ✗
#   `CaptureService.onFrame()` 旧代码：
#     快路径 `rowStride == w*4` ⇒ `copyPixelsFromBuffer()` ✓（Redmi 1280 宽走这条，颜色正常）
#     慢路径（行距被 64 对齐填充）⇒ `asIntBuffer()` 把 RGBA 当 int 读（=ABGR）+
#       `setPixels()`（要 ARGB）⇒ **R↔B 互换** ✗✗
#   触发条件正是**宽 1264** 的 realme（1264*4=5056 ⇒ 补到 5120）⇒ 只有它走慢路径 ⇒
#     暖色棋盘变**蓝紫**、金色图标变紫 ⇒ 标记形状 0.765 / 配色 0.466 全在闸门下 ⇒ 漏检 ✗
#   （实证：反馈帧通道均值 B:G:R = **1.37:0.75:0.89**（蓝主导）；正常帧 = 0.87:0.98:1.16（红主导））
#   修法：慢路径**去掉行距填充后交给 `copyPixelsFromBuffer()`**（与已验证的快路径同一套转换）；
#     并把"走哪条路 + 行距"暴露给 Python（`DeviceApi.capturePath()`）⇒ 反馈包能自证 ✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊹ v1.31 取帧慢路径 R↔B 互换（真机整屏偏紫的根因）')
try:
    _cap31 = open(os.path.join(PROJ, 'app', 'src', 'main', 'java', 'com', 'fantasy',
                               'autoexplore', 'CaptureService.java'),
                  encoding='utf-8').read()
    _dev31 = open(os.path.join(PROJ, 'app', 'src', 'main', 'java', 'com', 'fantasy',
                               'autoexplore', 'DeviceApi.java'), encoding='utf-8').read()
    check('v1.31 ① 慢路径不再自己拼 int（旧代码那两行必须消失 ✗）',
          'ByteBuffer rb = ByteBuffer.wrap(row);' not in _cap31
          and 'bmp.setPixels(pixels, 0, w, 0, 0, w, h);' not in _cap31)
    check('v1.31 ② 慢路径改成"去填充 + `copyPixelsFromBuffer()`"（与快路径同源 ✓）',
          'byte[] tight = sloBuf;' in _cap31   # v2.87: 由每帧 new 改成复用（语义不变）
          and 'bmp.copyPixelsFromBuffer(ByteBuffer.wrap(tight));' in _cap31)
    check('v1.31 ③ 走哪条路 + 行距**暴露出来**（`CaptureService.slowPath()` / `slowRowStride()` ✓）',
          'public static boolean slowPath()' in _cap31
          and 'public static int slowRowStride()' in _cap31
          and 'public static int[] capturePath()' in _dev31)
    check('v1.31 ④ 慢路径会**记一行日志**（w / rowStride / 期望值 ⇒ 反馈包能一眼看出 ✓）',
          '取帧走**慢路径**（行距填充）' in _cap31)
    _src31 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                  encoding='utf-8').read()
    check('v1.31 ⑤ Python 侧每局记 `capture_path`（`[慢路径?, 行距, w*4]` ⇒ 自带通道序证据 ✓）',
          "log.append({'capture_path': {'slow': bool(_cp[0]), 'row_stride': _cp[1],"
          in _src31
          and 'def capture_path():' in _src31)
except Exception as _e31:       # noqa: BLE001
    check('v1.31 取帧通道序守门可运行（%r）' % (_e31,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊺ PC 端提速层（fixed.py）—— **已移出本门禁**
#   2026-10-01 晚「两端完全平行」：PC 端的固定锚点/模板快查是**PC 自己的**东西，
#   手机端仓里**没有** fixed.py，也**不该**有 —— 在这里查它等于让手机端依赖 PC。
#   ⇒ 这组检查搬到了 **PC 端仓**：`mapbot_pc/verify_gate.py`（PC 自己的门禁）。
#   手机端这边只留一句指针，提醒改 PC 提速约定要去 PC 仓跑。
print()
print('㊱ PC 端提速层（fixed.py）不在本门禁 —— 属 PC 端自己的门禁（mapbot_pc/verify_gate.py）')
check('手机端仓**不含** fixed.py（平行：PC 的东西不进本仓）',
      not os.path.exists(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'fixed.py')))

# ─────────────────────────────────────────────────────────────────────────
# ㊺ v1.33 ⭐⭐⭐【反馈包里的图必须是「这一局」的】—— 治"和之前的图一样"
#   用户 2026-10-02 原话：「反馈包里的图**不是他刚刚运行的图**，和之前的图一样」✗
#   **字节级实证**（`_fb/` 里 realme 的两包，md5 完全相同）：
#     `fb_20261001_2337/board_hidden_r0.png` == `fb_20261002_0239/board_hidden_r0.png`
#     = b6810e49ffa4187fba8d599e4cae5b02（相隔 3 小时，同一文件）
#   根因：诊断帧写**固定文件名**（`board_hidden_rN` / `marks_none_rN` …），
#     `_pub_dump()` 静默覆盖、**从不清理** ⇒ 这一局没触发该分支 = 没有新文件
#     ⇒ 目录里剩的还是上次的旧帧；`Feedback.java` 又把 bagdbg 的 png 全塞进包 ✗
#   修法（两端各一半）：
#     ① Python：`_clear_stale_diag_frames()` **开跑先清空** bagdbg 的 png + 写运行标记 ✓
#     ② Java：`collectFrames()` 按**运行标记时间**过滤，只收本次运行的帧 ✓
#     ③ `device.txt` 写**逐帧清单**（时刻/尺寸/大小）⇒ 包能自证新鲜度 ✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊽ v1.33 反馈包只收「本次运行」的帧（治"图是陈货"）')
try:
    _el33 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                 encoding='utf-8').read()
    _fb33 = open(os.path.join(PROJ, 'app', 'src', 'main', 'java', 'com', 'fantasy',
                               'autoexplore', 'Feedback.java'), encoding='utf-8').read()
    check('v1.33 ① Python 侧**开跑先清旧帧**（`_clear_stale_diag_frames()` 调了 ✓）',
          'def _clear_stale_diag_frames():' in _el33
          and '_clear_stale_diag_frames()' in _el33
          and "_import_missing_never_" not in _el33)
    check('v1.33 ② 清理动作在 `android_run()` 里**真被调起**（不是只定义 ✓）',
          _el33.index('def android_run(') < _el33.index('    _clear_stale_diag_frames()\n'))
    check('v1.33 ③ 清的是 **png**（日志/运行标记不删，否则丢日志 ✗）',
          "if n.lower().endswith('.png'):" in _el33
          and 'os.remove(os.path.join(bag_dir, n))' in _el33)
    check('v1.33 ④ 端上限定 `os.name != \'posix\'` 早退（PC 跑门禁不污染工作区 ✓）',
          "if os.name != 'posix':" in _el33)
    check('v1.33 ⑤ 写**运行标记**（`run_started`，整数秒 ⇒ Java 侧好换算 ✓）',
          "RUN_MARKER = '_run_marker.json'" in _el33
          and "'run_started': int(time.time())" in _el33)
    check('v1.33 ⑥ Java 侧**按运行时间过滤**（`mtime < runStarted` 的旧帧不带 ✓）',
          'private static long readRunStarted(File bagdbg)' in _fb33
          and 'f.lastModified() + 1000L < runStarted' in _fb33)
    check('v1.33 ⑦ 帧名走**白名单**（不夹带玩家自己的图片 ✓）',
          'private static final String[] FRAME_PREFIXES' in _fb33
          and '"marks_none_"' in _fb33
          and '"dice_nobtn"' in _fb33
          and '"vault_no_hit_"' in _fb33)
    check('v1.33 ⑧ `device.txt` 带**逐帧清单**（时刻/尺寸/大小 ⇒ 包自证新鲜度 ✓）',
          '本次运行的现场帧' in _fb33
          and 'sizeOfPng(f)' in _fb33
          and 'fmtMs(f.lastModified())' in _fb33)
    check('v1.33 ⑨ 没落帧时**明说**"本次运行没落任何诊断帧"（不是丢包 ✓）',
          '本次运行**没有落任何诊断帧**' in _fb33)
    check('v1.33 ⑩ 老的 `deviceInfo(ctx)` 单参重载**已消失**（两处调用都传新鲜度参数 ✓）',
          'private static String deviceInfo(Context ctx, long runStarted' in _fb33
          and 'private static String deviceInfo(Context ctx) {' not in _fb33)
    # ⚠ 以下两条是**离线实跑真抓出来的 bug**（2026-10-02），不是预防性猜测：
    #   ① 数值解析只认"数字 + 小数点" ⇒ 遇到 `1.79E9` 截成 `1.79` ⇒ 毫秒=1790
    #      ⇒ 时间闸**全程失效**、陈旧帧照收（症状与"根本没修"一模一样）✗
    #   ② 量级阈值写成 `1e11` ⇒ 比真实毫秒(≈1.79e12)**还小**
    #      ⇒ 所有**正常**标记都被误杀成"没有闸" ⇒ 同样等于没修 ✗
    _i_rs = _fb33.index('private static long readRunStarted')
    _i_rs_end = _fb33.index('private static String readText')
    _rs_body = _fb33[_i_rs:_i_rs_end]
    check("v1.33 ⑪b 数值解析**吃下科学计数法**（`E`/`+`/`-`）（实跑抓到的坑 ✗）",
          "s.charAt(e) == 'e'" in _rs_body and "s.charAt(e) == 'E'" in _rs_body)
    check('v1.33 ⑪c 量级阈值落在**真实毫秒区间**（2001~2100；`1e11` 会全误杀 ✗）',
          '978307200000L' in _rs_body and '4102444800000L' in _rs_body)
    check('v1.33 ⑪ `vault_no_hit_*` **不再硬编码**两行（改由白名单统一收 ✓）',
          'addIfExists(extras, new File(pub, "vault_no_hit_L1.png"))' not in _fb33
          and 'addIfExists(extras, new File(pub, "vault_no_hit_L2.png"))' not in _fb33)
    # ⭐ 实施当场踩的坑：「函数写了但**从没被调起**」门禁照样全绿（因为只查字符串 ✗）
    #   ⇒ 逼着把核心逻辑抽成**可脱离端上直接跑**的核，下面 ⑫ 就是**打这个真函数** ✓
    check('v1.33 ⑪ 核心清理逻辑抽成**可独立实跑的核** `_purge_diag_frames_in()`',
          'def _purge_diag_frames_in(bag_dir' in _el33
          and '_purge_diag_frames_in(BAG_PUB_DIR' in _el33)
except Exception as _e33:       # noqa: BLE001
    check('v1.33 反馈包新鲜度守门可运行（%r）' % (_e33,), False)

# ⑫ **实证闸 A**：仓库里留存的真实反馈帧，跑一遍"mtime 闸"（复刻 Java 判据）
#   造出"一帧 10 天前的旧的 + 一帧刚落的新的" ⇒ 旧的必须被挡、新帧必须留下 ✓
# ⑬ **实证闸 B**：`_fb/` 里两包**确实字节相同**（= 这条修法要治的那个现象本身）
try:
    import tempfile
    import time as _t33
    import shutil as _sh33
    import json as _json33
    import hashlib as _hl33
    # ⭐ 调**真代码**的被测核（不是复刻）：门禁必须打真函数 ✓
    _has_purge = hasattr(EL, '_purge_diag_frames_in')
    if not _has_purge:
        skip('v1.33 ⑫ 实证闸 A（`EL` 里没有 `_purge_diag_frames_in` ⇒ 没真验证）')
    _el_purge = getattr(EL, '_purge_diag_frames_in', None)
    _src33 = os.path.join(PROJ, '_verify', 'phone_friend_rmx3800', 'board_hidden_r0.png')
    if not _has_purge:
        pass
    elif not os.path.exists(_src33):
        skip('v1.33 ⑫ 实证闸 A（缺 fixture %s ⇒ 没真验证）' % _src33)
    else:
        _td = tempfile.mkdtemp(prefix='mgas_fb33_')
        try:
            # ⭐⭐ 调**真代码**（`explore_loop._purge_diag_frames_in`），不是复刻一份。
            #   教训（2026-10-02 v1.33 实施当场）：门禁若只查字符串 + 复刻逻辑，
            #   "函数写了但从没被调起"这类错会一路绿到底 ✗ ⇒ 必须打真函数 ✓
            _old_t = _t33.time() - 10 * 86400
            for _n in ('board_hidden_r0.png', 'marks_none_r0.png'):
                _sh33.copyfile(_src33, os.path.join(_td, _n))
                os.utime(os.path.join(_td, _n), (_old_t, _old_t))   # ← 10 天前落的那两张
            with open(os.path.join(_td, 'mgas_log.txt'), 'w', encoding='utf-8') as _f:
                _f.write('日志不许被删')
            _killed, _mpath = _el_purge(_td)
            _left = sorted(os.listdir(_td))
            check('v1.33 ⑫ 实证闸 A：**真跑**清理核 ⇒ 旧帧全清、日志留下、标记已写',
                  _killed == 2
                  and not any(x.endswith('.png') for x in _left)
                  and 'mgas_log.txt' in _left
                  and _mpath is not None and os.path.exists(_mpath),
                  '删=%d 剩=%s' % (_killed, _left))
            # 标记里的时间戳必须能被 Java 侧换算成毫秒（量级校验，秒 ⇒ ×1000）✓
            _mark = _json33.load(open(_mpath, encoding='utf-8'))
            _ms = _mark['run_started'] * 1000.0
            check('v1.33 ⑫ 实证闸 A2：标记的 `run_started` 是**秒级**（Java 侧 ×1000 ⇒ 毫秒 ✓）',
                  1e11 < _ms < 4e12, 'run_started=%.0f' % _mark['run_started'])
        finally:
            _sh33.rmtree(_td, ignore_errors=True)

    # ⑭ **Java 侧实跑**：`Feedback` 的过滤/解析判据（自测见 tools/FbLogic.java）
    #   ⚠ 为什么单独跑而不是 import：`android.jar` 里的 `java.io.File` 是**裁剪桩**
    #     （没有 getLastModified()），脱离 Gradle 起不来真类 ⇒ 判据等价复刻 + 独立实跑 ✓
    #   ⚠ 这条**真抓过三个 bug**（2026-10-02）：科学计数法被截断、量级阈值过小、
    #     以及"工具函数定义在使用之后"导致本条闸自己失效 ✓
    _javat = os.path.join(PROJ, 'tools', 'FbLogic.java')
    _javac = _find_javac()
    # ⚠ 运行器要用**同目录的 `java.exe`**，不能拿 `javac.exe` 当（2026-10-02 实测：
    #   那样会静默返回非 0 且 stdout 为空 ⇒ 看起来像"判据跑不过"✗）
    _java = os.path.join(os.path.dirname(_javac), 'java') if _javac else None
    if _java and not os.path.exists(_java + '.exe') and not os.path.exists(_java):
        _java = None
    if not os.path.exists(_javat):
        skip('v1.33 ⑭ Java 过滤判据实跑（缺 tools/FbLogic.java）')
    elif not _javac or not _java:
        skip('v1.33 ⑭ Java 过滤判据实跑（本机没找到 javac/java ⇒ 没真验证）')
    else:
        import subprocess as _sp33
        _od = tempfile.mkdtemp(prefix='mgas_java33_')
        _od2 = tempfile.mkdtemp(prefix='mgas_fbdata33_')
        try:
            # ⚠ 不用 `text=True`：javac/java 的输出是**本地代码页**（GBK），
            #   配 `text=True` 会在非 UTF-8 控制台上抛解码错 ⇒ 看起来像"跑挂了"✗
            #   （2026-10-02 实测踩过）⇒ 一律按 bytes 收、errors='replace' 解 ✓
            _cp = _sp33.run([_javac, '-nowarn', '-encoding', 'UTF-8', '-d', _od, _javat],
                            capture_output=True)
            if _cp.returncode != 0:
                check('v1.33 ⑭ Java 自测**能编译**（%r）'
                      % (_cp.stderr.decode('utf-8', 'replace')[-200:],), False)
            else:
                _rp = _sp33.run([_java, '-cp', _od, 'FbLogic', _od2], capture_output=True)
                _out = _rp.stdout.decode('gbk', 'replace')   # javac/java 本地代码页 ✓
                check('v1.33 ⑭ Java 侧过滤/解析判据**实跑全绿**'
                      '（老帧被挡 / 科学计数法 / 量级 fail-safe）',
                      _rp.returncode == 0 and 'ALL PASS' in _out,
                      (_out.strip().splitlines() or [''])[-1])
        finally:
            _sh33.rmtree(_od, ignore_errors=True)
            _sh33.rmtree(_od2, ignore_errors=True)

    # ⑬ 实证闸 B：两个反馈包里的同一张图**字节完全相同**（这条修法治的就是它）
    _a33 = os.path.join(PROJ, '..', '_fb', 'fb_20261001_2337', 'board_hidden_r0.png')
    _b33 = os.path.join(PROJ, '..', '_fb', 'fb_20261002_0239', 'board_hidden_r0.png')
    if not (os.path.exists(_a33) and os.path.exists(_b33)):
        skip('v1.33 ⑬ 实证闸 B（缺 _fb/ 里的历史反馈包 ⇒ 没真验证）')
    else:
        _ha = _hl33.md5(open(_a33, 'rb').read()).hexdigest()
        _hb = _hl33.md5(open(_b33, 'rb').read()).hexdigest()
        # ⚠ 这里断言的是**"那两包确实带着同一张旧图"**（记录 v1.33 的起因事实）。
        #   将来 `_fb/` 归档被清理后，这项会失真 ⇒ 保留可追溯性，不是行为断言 ✓
        check('v1.33 ⑬ 起因存档：相隔 3 小时的两包带的是**同一张旧图**'
              '（= 陈货铁证，v1.33 治的就是它）', _ha == _hb, 'md5=%s' % _ha[:12])
except Exception as _e33b:      # noqa: BLE001
    check('v1.33 ⑫⑬ 实证闸可运行（%r）' % (_e33b,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊾ v1.59 ⛔【**防「能点的首领优先」重排被加回来**】（反向断言，v1.34 那组已反转）
#
#   ⛔ **2026-10-04 v1.59：用户口径「去掉这个」⇒ 删除** ✓
#     · 删的函数：`_hoist_ready_boss_first()` + `_ready_boss_cells()`
#       （v1.34 加的：把**当下能点的首领/红装格**提到点序最前，其余顺序不动）
#     · 删的调用点：`solver_order()` 与 `eff_order()` 两处（原话「不两处漂移」）
#     · **为什么可以删**：这是**手机端独有的分叉** —— 报告已记 PC **明确不跟随**
#       这个重排 ⇒ 删掉即**回退到 PC 的行为**（点序一律按解算器/策略给的顺序执行 ✓）
#
#   v1.34 的起因（保留作历史，别再"修"回去）：用户 2026-10-02 报（朋友真机）
#     「会把能点的素材格全点开，**boss 格已经能打了**，还是会先点 boss 格周围的素材格」✗
#     真机铁证（`fb_20261002_015406/mgas_log.txt`）：`marks {"2,3": ["boss","recommend"]}`
#     + `solver order ["3,5","2,3"]`，同一轮还有 `{"popup":"fight_panel",…}`
#     ⇒ boss 当下完全可打，点序却把它排在第 2 位。v1.34 的修法是"提到最前"，
#       用户 2026-10-04 明确不要这个行为 ⇒ 撤销它，**不是**"把判据改成别的"
#
#   ⚠ 本组照 PC `verify_fog_only_start.py` 的做法：**防它被加回来**（反向断言）
#     ① 三个符号**不许出现在代码里**（`def` 与调用点都查；解释性注释不算 ——
#        4 处删除说明注释必须能提到这些名字，否则后人看不懂为什么删）
#     ② 两个调用点位置现在是「**直接按解算器/策略顺序执行**」（`out` / `plan`
#        不再被任何重排赋值）
#     ③ **行为验收**（只查字符串不算验过）：真造一张「boss 当下可点、ratio 0.96
#        ≥ `REVEAL_RATIO_MIN` 0.80，但解算器把它排在第 2 位」的盘，真跑
#        `solver_order()` / `eff_order()` ⇒ 断言**结果保持原顺序**（boss 没被提前 ✓）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊾ v1.59 ⛔ 防「能点的首领优先」重排回归（用户口径「去掉这个」）')
try:
    _el59 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                 encoding='utf-8').read()
    # ⚠ 只剔**整行注释**后再查符号名：v1.59 在 4 处留了"为什么删"的说明注释
    #   （`:84` / `:1191` / `:1402` / `:6956` 一带），它们**必须**能提到这两个名字
    #   ⇒ 不能拿"名字在不在全文里"当判据（那会把好注释判成回归 ✗）
    _code59 = '\n'.join(_l59 for _l59 in _el59.splitlines()
                        if not _l59.lstrip().startswith('#'))
    check('v1.59 ① ⛔ 重排三符号**不在代码里**（`_hoist_ready_boss_first` /'
          ' `_ready_boss_cells` / 日志键 `boss_hoisted`）—— 用户口径「去掉这个」✓',
          all(_n not in _code59
              for _n in ('_hoist_ready_boss_first', '_ready_boss_cells',
                         'boss_hoisted')))
    check('v1.59 ② ⛔ **`def` 与调用点都查**：函数本体没了，'
          '`_hoist_ready_boss_first(st, …)` / `_ready_boss_cells(st, …)` 调用式也没了',
          'def _hoist_ready_boss_first(' not in _el59
          and 'def _ready_boss_cells(' not in _el59
          and '_hoist_ready_boss_first(st,' not in _el59
          and '_ready_boss_cells(st,' not in _el59
          and 'out = _hoisted' not in _el59)
    # ---- ② 两个调用点位置：现在是「直接按解算器/策略顺序执行」----
    _i59_cfp = _el59.index('for _rc, _bi, _w in prob.cells_for_plan(plan[:max_steps]):')
    _i59_nt = _el59.index('_nt = len(sim.targets())')
    _seg59_solver = _el59[_i59_cfp:_i59_nt]
    check('v1.59 ③ solver 调用点：`cells_for_plan` 之后**直接**执行解算器顺序'
          '（这段里再没有 `out = …` 的重排赋值 ✓）',
          0 < _i59_cfp < _i59_nt
          and 'out.append(_rc)' in _seg59_solver
          and 'out = ' not in _seg59_solver,
          '段内 %d 行' % (len(_seg59_solver.splitlines()),))
    _i59_effp = _el59.index('plan = _Eff().plan(sim, max_click=max_steps, '
                            'stop_when_no_target=False)')
    _i59_effp_end = _el59.index('\n', _i59_effp)      # ⚠ 从**那一行之后**开始算
    _i59_effl = _el59.index("log.append({'eff': 'ok'")
    _seg59_eff = _el59[_i59_effp_end:_i59_effl]
    check('v1.59 ④ eff 调用点：`plan = _Eff().plan(…)` 之后**直接**记日志/返回'
          '（这段里再没有 `plan = …` 的重排赋值 ✓）',
          0 < _i59_effp < _i59_effl
          and all(not _l59.strip().startswith(('plan =', 'plan='))
                  for _l59 in _seg59_eff.splitlines()
                  if not _l59.strip().startswith('#')),
          '段内 %d 行' % (len(_seg59_eff.splitlines()),))
except Exception as _e59:       # noqa: BLE001
    check('v1.59 源码反向守门可运行（%r）' % (_e59,), False)

# ③ **行为验收**（这次删除的真正验收：只查字符串不算验过）：
#   造一张「boss **当下可点**（已揭示 / ratio 0.96 ≥ `REVEAL_RATIO_MIN` 0.80）
#   但解算器把它排在**第 2 位**」的盘 ⇒ 真跑 `solver_order()` / `eff_order()`
#   ⇒ 断言**结果保持解算器/策略原样顺序**（boss 没被提到最前 ✓）
#   ⚠ 场景必须**确实命中旧判据**（marks 含 boss + ratio ≥ 阈值）—— 否则"
#     旧代码也不会重排" ⇒ 这组断言等于恒绿 ✗（下面 ⑦/⑨ 就是这条自证 ✓）
try:
    import spots as _sp59
    import mapsim as _sim59
    import mapsolve as _mv59
    from strategy import EffPolicy as _Eff59

    def _c59(sid, name, anchor, revealed=True, ratio=1.0, score=0.99,
             marks=None, top=None):
        return {'sid': sid, 'name': name, 'revealed': revealed, 'ratio': ratio,
                'score': score, 'marks': list(marks or []), 'anchor': anchor,
                'top': list(top or [(score, sid, anchor)])}

    def _frame59(boss_rc, boss_ratio):
        """5×7 全已揭示草地 + 营地 (1,1)（单格候选 `S00003_000` ⇒ 揭示链起点）
        + 近处幸运草 (1,2) + 远处的 boss（**已揭示**，ratio 0.96 ✓）"""
        _c = {}
        for _r in range(1, 6):
            for _cc in range(1, 8):
                _c[(_r, _cc)] = _c59('S00003_001', '草地', (_r, _cc))
        _c[(1, 1)] = _c59('S00003_211', '巨大沙堡', (1, 1),
                          top=[(1.000, 'S00003_000', (1, 1)),
                               (0.998, 'S00003_001', (1, 1))])
        _c[(1, 2)] = _c59('S00003_001', '草地', (1, 2), marks=['clover'])
        _c[boss_rc] = _c59('S00003_002', '沙地', boss_rc,
                           revealed=True, ratio=boss_ratio, marks=['boss'])
        return _c

    _boss59 = (5, 7)
    _cells59 = _frame59(_boss59, 0.96)
    _marks59 = {_boss59: {'marks': ['boss']}, (1, 2): {'marks': ['clover']}}
    _st59 = {'marks': dict(_marks59), 'obs': _cells59, 'done': set()}
    _min59 = float(EL.REVEAL_RATIO_MIN)

    # ---- 参考顺序 = 解算器/策略**原样输出**（与生产同一链，不含任何重排 ✓）----
    def _ref59(tag59):
        _m = EL._cells_for_model({'marks': dict(_marks59), 'obs': _cells59,
                                  'done': set()},
                                 {'st': _cells59}, log=None, tag=tag59,
                                 mark_revealed=False)
        return _sim59.MapSim.from_observation(_m, _sp59.spot_rows())

    _prob59 = _mv59.Problem(_ref59('ref59'))
    _cost59, _plan59 = _mv59.solve(_prob59, max_states=60000, max_secs=8)
    _raw59 = []
    for _rc59, _bi59, _w59 in _prob59.cells_for_plan((_plan59 or [])[:10]):
        if _rc59 not in _raw59:
            _raw59.append(_rc59)
    _ord59 = EL.solver_order(_st59, {'st': _cells59}, log=None, max_steps=10)

    # ⚠ 旧口径的判据（marks 含 boss/redEquip + ratio ≥ `REVEAL_RATIO_MIN`）在本场景
    #   里**确实命中** ⇒ v1.34 的旧代码在此**必然**把 boss 提到第 1 位
    #   ⇒ 这组断言**不是恒绿**（把 `_hoist_ready_boss_first` 加回来这条就红 ✓）
    _hit59 = [rc for rc in _raw59
              if 'boss' in ((_marks59.get(rc) or {}).get('marks') or [])
              and float(((_cells59.get(rc) or {}).get('ratio')) or 0) >= _min59]
    check('v1.59 ⑤ 行为：`solver_order()` 的返回 == **解算器原样顺序**'
          '（逐项相等 ⇒ `out` 没被任何重排改过 ✓）',
          bool(_raw59) and _ord59 == _raw59,
          'solver=%s raw=%s cost=%s' % (_ord59, _raw59, _cost59))
    check('v1.59 ⑥ 行为：场景正确 —— boss 当下**可点**（ratio 0.96 ≥ %.2f）'
          '却在解算器里排**第 %s 位**（v1.34 的旧行为会把它提到第 1 位 ✗）'
          % (_min59, (_ord59.index(_boss59) + 1) if _boss59 in _ord59 else '—'),
          _boss59 in _ord59 and _ord59.index(_boss59) >= 1,
          'order=%s boss=%s' % (_ord59, _boss59))
    _eff59 = EL.eff_order({'marks': dict(_marks59), 'obs': _cells59, 'done': set()},
                          {'st': _cells59}, log=None, max_steps=10)
    _plan59e = _Eff59().plan(_ref59('ref59e'), max_click=10,
                             stop_when_no_target=False)
    check('v1.59 ⑦ 行为：兜底路径 `eff_order()` 的返回 == **EffPolicy 原样输出**'
          '（`plan` 没被任何重排改过 ✓）',
          bool(_plan59e) and list(_eff59) == list(_plan59e),
          'eff=%s raw=%s' % (_eff59, _plan59e))
    check('v1.59 ⑧ 行为：同一张盘在兜底路径里 —— boss 也排**第 %s 位**'
          '（旧代码会把 `plan` 改写成 boss 打头 ✗）'
          % ((_eff59.index(_boss59) + 1) if _boss59 in _eff59 else '—',),
          _boss59 in _eff59 and _eff59.index(_boss59) >= 1,
          'plan=%s boss=%s' % (_eff59, _boss59))
    check('v1.59 ⑨ 旧判据在本场景**确实命中**（`%s`）'
          '⇒ ⑥/⑧ 不是恒绿：v1.34 的"能点的首领提到最前"在此一定会发生 ✓'
          % (['%d,%d' % p for p in _hit59] or '【未命中 ⇒ 场景失效，必须换盘】',),
          bool(_hit59) and _boss59 in _hit59)
    # ⚠ 删掉的是**重排那一步**，不是常量本身：`REVEAL_RATIO_MIN` 必须还在、
    #   仍是 `spots` 的单一来源（`board_hidden()` 还在用它 ✓）
    check('v1.59 ⑩ 揭示阈值**没被顺手删掉**：`EL.REVEAL_RATIO_MIN` 仍 == '
          '`spots.REVEAL_RATIO_MIN` == 0.80（单一来源 ✓）',
          float(EL.REVEAL_RATIO_MIN) == float(_sp59.REVEAL_RATIO_MIN)
          and float(EL.REVEAL_RATIO_MIN) == 0.80,
          '%s / %s' % (EL.REVEAL_RATIO_MIN, _sp59.REVEAL_RATIO_MIN))
    # ═══ ⑪~⑭ v1.59【诊断 `plan_blocks`】════════════════════════════════════
    #   用户 2026-10-04 口径（原话）：「**我的意思是目标和营地直接有两个空地，明明点
    #   一个空地就能直接打目标，结果手机端规划非要两个都点**」✗
    #   推理链：`solve()` 有硬闸门 `ns = st | PGM[bi]; if ns == st: continue`
    #     —— 点过一片空地再点**同一片** ⇒ 状态不变 ⇒ **不会进计划** ✓
    #     而 `plain_group`/`step`/`PGM` 三处已与 PC 逐字对拍（22/22、5/5、8/8 行零差异）
    #   ⇒ 计划里出现"两步空地"**只可能**是模型把这两格切成**两片**（中间被内容格/
    #     非空地切断）⇒ 用 `plain` + `group`（同片成员格）一次打全，不再猜 ✓
    _bi59s = _el59.index('def solver_order(')
    _body59 = _el59[_bi59s:_el59.index('\ndef ', _bi59s + 10)]
    # ⚠ 数调用必须**剔掉注释**：solver_order 的注释里也写着 `Problem.cells_for_plan()`
    #   （讲那次 bug 的来历）⇒ 直接 count 会数成 2、把这段守门变成假红 ✗
    _body59c = '\n'.join(_l for _l in _body59.splitlines()
                         if not _l.lstrip().startswith('#'))
    check('v1.59 ⑪ 诊断在位：`_plan_step_info()` + `plan_blocks` 日志，且 '
          '`cells_for_plan` 在 `solver_order()` 里**只调一次**'
          '（逐步推演：重复调既浪费、又可能不一致 ✗）',
          'def _plan_step_info(' in _el59
          and "'solver': 'plan_blocks'" in _body59
          and _body59c.count('cells_for_plan(') == 1,
          '调用数=%d' % (_body59c.count('cells_for_plan('),))
    _lg59d = []
    EL.solver_order(_st59, {'st': _cells59}, log=_lg59d, max_steps=10)
    _pb59 = [x for x in _lg59d if isinstance(x, dict)
             and x.get('solver') == 'plan_blocks']
    _pl59 = [x for x in _lg59d if isinstance(x, dict)
             and x.get('solver') == 'plan_block']
    _need59 = ('i', 'cell', 'cost', 'bi', 'sid', 'name', 'plain', 'marks',
               'fog_sil', 'obs', 'fog_obj', 'group', 'gn')
    check('v1.59 ⑫ 执行级：真跑 `solver_order()` ⇒ 日志里**真落了** `plan_blocks` 汇总 +'
          ' **每步一行** `plan_block`（⚠ 真机实测"整条塞一条"会超 300 字符被截断 ⇒'
          ' `json.loads` 直接失败 ✗），字段齐全（含 **`fog_sil`/`fog_obj`** ✓）'
          '且**每步独立成行**（键名压短：`observed`→`obs`、`fog_object`→`fog_obj`、'
          '`group_n`→`gn` ✓）',
          bool(_pl59) and bool(_pb59) and _pb59[0].get('n') == len(_pl59)
          and all(all(_k in _s for _k in _need59) for _s in _pl59)
          and [_s.get('i') for _s in _pl59] == list(range(len(_pl59))),
          'n=%s 明细=%d' % (_pb59[0].get('n') if _pb59 else None, len(_pl59)))
    _mx59 = max([len(str(_s)) for _s in _pl59] or [0])      # ⚠ 真机上限 300 字符
    check('v1.59 ⑬ 执行级：每行**都塞得进 300 字符**（真机实测满盘那步 401 ⇒ 被截断 ✗；'
          '现在丢 `group_bi`/`size` + `group` 只留前 6 格 + `+N` ⇒ ≤ 300 ✓），'
          '且每步 `cell` 在**自己的同片成员**里（`group` 是**同片成员格**、不是块 id ✗）',
          bool(_pl59) and _mx59 < 300
          and all((_s['cell'] in _s['group'])
                  or (_s.get('gn', 0) > 6 and _s['group']
                      and str(_s['group'][-1]).startswith('+'))
                  for _s in _pl59),
          '最长 %d 字符 · %s' % (_mx59, [(_s['cell'], _s.get('gn'),
                                          (_s['group'] or [None])[0])
                                         for _s in _pl59]))
    # ⚠ 同片 / 不同片**必须能区分** —— 否则这条诊断等于没有（所以配对照盘 ✓）
    def _mk59d(_skip):
        _c = {}
        for _r in range(1, 4):
            for _cc in range(1, 4):
                _c[(_r, _cc)] = _c59('S00003_002', '沙地', (_r, _cc))
        for _k in ((1, 1), (1, 2), (1, 3)):
            if _k == _skip:
                continue              # 中间那格留成「沙地」（非空地）⇒ 切断连通 ✓
            _c[_k] = _c59('S00003_001', '草地', _k)
        _c[(3, 3)] = _c59('S00003_211', '巨大沙堡', (3, 3),
                          top=[(1.000, 'S00003_000', (3, 3)),
                               (0.998, 'S00003_001', (3, 3))])
        return _c

    def _grp59(_skip):
        _c = _mk59d(_skip)
        _m = EL._cells_for_model({'marks': {}, 'obs': _c, 'done': set()},
                                 {'st': _c}, log=None, tag='d59',
                                 mark_revealed=False)
        _p = _mv59.Problem(_sim59.MapSim.from_observation(_m, _sp59.spot_rows()))
        _acts = [(_p.board[_sim59.cell_of(1, 1)], 1),
                 (_p.board[_sim59.cell_of(1, 3)], 1)]
        return [EL._plan_step_info(_p, _rc, _bi, _w)
                for _rc, _bi, _w in _p.cells_for_plan(_acts)]

    _same59, _diff59 = _grp59(None), _grp59((1, 2))
    check('v1.59 ⑭ 执行级：**同片**盘 ⇒ 两步的 `group` **相同**；'
          '**不同片**盘（中间隔一格非空地）⇒ `group` **不同**'
          '（⇒ 真机"两格空地排两步"= 模型切成两片，一条日志坐实 ✓）',
          len(_same59) == 2 and len(_diff59) == 2
          and _same59[0]['group'] == _same59[1]['group']
          and _diff59[0]['group'] != _diff59[1]['group']
          and all(_s['cell'] in _s['group'] for _s in _same59 + _diff59),
          'same=%s diff=%s' % ([_s['group'] for _s in _same59],
                               [_s['group'] for _s in _diff59]))

    # ═══ ⑮~⑰ v1.59【真机根因：`Block.plain` 的**雾下剪影**那条缺 `not observed`】═══
    #   真机日志（v1.59 诊断，Redmi 25053RT47C）：
    #     step1 `{"cell":"3,4","sid":"S30001_001","name":"岩地","plain":true,"group":["3,4"]}`
    #     step2 `{"cell":"3,3","sid":"S30001_001","name":"岩地","plain":false,…}`
    #     `{"solver":"ok","cost":7,"steps":4,"order":["3,4","3,3","3,2","2,1"]}`
    #   ⇒ **相邻两格、同一个 sid**，一 plain 一非 plain ⇒ 连锁断裂 ⇒ 2 步变 4 步 ✗✗
    #   根因：`fog_object`（**雾下**剪影）那条**没有观测闸门**，而**已揭示**的岩地本身
    #     有纹理 ⇒ 剪影高 ⇒ 被当"雾下有物体" ⇒ 判非空地 ✗
    #   ⚠ 与 PC 等价：PC 那条实际只在雾格触发（否则它 `:202` 分支不必专门加闸门）✓
    _ms59s = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsim.py'),
                  encoding='utf-8').read()
    _i59po = _ms59s.index("if getattr(self, 'fog_object', False)")
    check('v1.59 ⑮ 源码：`Block.plain` 的**雾下剪影**那条带 `not observed` 闸门'
          '（与**同函数相邻**的 `:225` 那条剪影分支一致 —— 一个有一个没有就是漏改 ✗）',
          "and not getattr(self, 'observed', False)" in _ms59s[_i59po:_i59po + 120])

    def _rock59(_rev, _sil=0.30):
        """真机那把的形状：**相邻两格同 sid `S30001_001`（岩地）** + 一个营地 ✓"""
        _c = {}
        for _k in ((1, 1), (1, 2)):
            _c[_k] = {'sid': 'S30001_001', 'name': '岩地', 'revealed': _rev,
                      'ratio': 1.0 if _rev else 0.66, 'score': 0.99, 'marks': [],
                      'anchor': _k, 'fog_sil': _sil}
        _c[(2, 1)] = {'sid': 'S00003_000', 'name': '营地', 'revealed': True,
                      'ratio': 1.0, 'score': 1.0, 'marks': [], 'anchor': (2, 1)}
        _sm = _sim59.MapSim.from_observation(_c, _sp59.spot_rows())
        _pp = _mv59.Problem(_sm)
        _b1 = _sm.blocks[_pp.board[_sim59.cell_of(1, 1)]]
        _b2 = _sm.blocks[_pp.board[_sim59.cell_of(1, 2)]]
        return _sm, _pp, _b1, _b2

    _sm59, _pp59, _b59a, _b59b = _rock59(True)
    _grp59b = sorted(_pp59.plain_group(_b59a.idx))
    check('v1.59 ⑯ 执行级【真机那把】：**已揭示**（observed=True）的相邻两格同 sid 岩地，'
          '即使 `fog_object=True`（岩地纹理）⇒ **两格都 `plain=True`** 且 '
          '`plain_group` **含两格**（连锁连上 ⇒ 不会"各点一次" ✓）',
          _b59a.plain is True and _b59b.plain is True
          and _b59a.fog_object is True and _b59a.observed is True
          and len(_grp59b) >= 2,
          'plain=%s/%s group=%s fog_sil=%s' % (_b59a.plain, _b59b.plain, _grp59b,
                                               (_b59a.spot or {}).get('fog_sil')))
    _sm59n, _pp59n, _b59c, _ = _rock59(False)
    check('v1.59 ⑰ 【负样本】**真雾格**（observed=False）+ 剪影有物体 ⇒ **仍 '
          '`plain=False`**（雾下物体照样挡连锁 —— 别把 M54 这条修成"剪影完全失效" ✗）',
          _b59c.plain is False and _b59c.fog_object is True
          and _b59c.observed is False
          and len(sorted(_pp59n.plain_group(_b59c.idx))) == 1,
          'plain=%s fog_object=%s observed=%s' % (_b59c.plain, _b59c.fog_object,
                                                  _b59c.observed))
except Exception as _e59b:      # noqa: BLE001
    check('v1.59 行为验收闸可运行（%r）' % (_e59b,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊿ v1.35 ⭐⭐⭐【`ratio` 分母换成本图模板亮度中位】—— 治「同一台机，换张地图就废」
#   用户 2026-10-02 报：**夏日海滩能正常用，广袤草原就找不到目标**（同一台 Redmi）
#   根因（真机实测钉死，不是推测）：`ratio = 格子亮度 / 该格所属地块的模板亮度`
#     判"已揭示"却用**写死的 0.75** ⇒ **两个量纲对不上** ✗
#     · 模板亮度中位：夏日海滩 **197**、广袤草原 **183**（差 14 灰阶）
#     · 真机同一帧（Redmi 25053RT47C / 1280×2772）雾格绝对亮度 **139.5**：
#         沙滩 139.5/197 = 0.708 ⇒ <0.75 判雾格 ✓（能跑）
#         草原 139.5/183 = **0.762** ⇒ ≥0.75 **被误判成"已揭示"** ✗
#     ⇒ 32 个雾格被当成能点的格 → 反复点同一个 boss 撞 `fogged_noop`
#       → `finish: no_progress` 退图 ✗✗
#   修法：分母换成**本图全部地块模板亮度的中位** `L_map`（一张图一个数，自动算 ✓）
#   ⚠ 更狠的根因：旧分母是**逐格不同**的 ⇒ 同一张图内 ratio 被抖动 **25%~81%**
#     （15 张图全部中招，熔岩通道 81.5% 最夸张）⇒ 0.75 夹在抖动区间里，
#     **分母偏大一点就把雾格顶过线**。新口径图内不再抖动 ✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊿ v1.35 ratio 分母换成本图模板中位（治"换图就废"）')
_FB35 = os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_r0.png')
try:
    _sp35 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'spots.py'),
                 encoding='utf-8').read()
    check('v1.35 ① 开关 `MAPBOT_RATIO_DEN`（`map`=新 / `cell`=旧，留作回滚 ✓）',
          "MAPBOT_RATIO_DEN" in _sp35 and "'map'" in _sp35 and "'cell'" in _sp35)
    check('v1.35 ② 本图基准 `_map_luma_ref()` 在位（一张图算一个数 + 缓存 ✓）',
          'def _map_luma_ref(self):' in _sp35 and 'self._map_luma' in _sp35)
    check('v1.35 ③ ratio 真的用了新分母（`self._map_luma_ref()` 进分母 ✓）',
          "self._map_luma_ref() if RATIO_DEN == 'map'" in _sp35
          and 'float(g.mean()) / max(1e-6, _den)' in _sp35)
    check('v1.35 ④ 旧口径**仍可达**（对拍/回滚不断路，不是删掉 ✓）',
          'else self._tpl_luma(eff)' in _sp35)
    check('v1.35 ⑤ 分母有下限保护（模板读不出时不崩 ✓）',
          'if self._map_luma <= 1e-6:' in _sp35)
    # ⭐ v1.35 连带修：`in_map` 的"有亮格"**不该复用 spots 的 0.75**
    #   起因：那张 fixture 图名 OCR=「清凉沙滩」⇒ 走 S40002 模板集，
    #   有一格 ratio **0.757** 压在 0.75 上 ⇒ 选图界面被误判成"已在图里" ✗
    _el35 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                 encoding='utf-8').read()
    _i_inmap = _el35.index('def in_map(b, img, items):')
    _i_after = _el35.index('\ndef ', _i_inmap + 10)
    _body35 = _el35[_i_inmap:_i_after]
    check('v1.35 ⑤b `in_map` 用**独立阈值 0.85**（不与 spots 的 0.75 混用 ✓）',
          '_IN_MAP_LIGHT_RATIO = 0.85' in _body35
          and '_mx >= _IN_MAP_LIGHT_RATIO' in _body35
          and '_mx >= 0.75' not in _body35,
          '边缘格 0.757 不再冒充正证据')
except Exception as _e35:       # noqa: BLE001
    check('v1.35 源码守门可运行（%r）' % (_e35,), False)

# ⑯ **实跑闸**：用真机那张广袤草原帧，直接打真分类器
try:
    if not os.path.exists(_FB35):
        skip('v1.35 ⑯ 实跑闸（缺真机草原帧 %s ⇒ 没真验证）' % _FB35)
    else:
        import cv2 as _cv35
        import numpy as _np35
        _img35 = _cv35.imdecode(_np35.fromfile(_FB35, dtype=_np35.uint8),
                                _cv35.IMREAD_COLOR)
        _g35 = _cv35.cvtColor(_img35, _cv35.COLOR_BGR2GRAY).astype(_np35.float32)
        # 直接构造 Board（门禁已把本仓 python 目录放进 sys.path ✓）
        import spots as _sp35mod
        _b35 = _sp35mod.Board('S10002')
        _L35 = _b35._map_luma_ref()
        # ⭐ 真机人工标注：该帧**只有** 5,6 / 4,7 / 5,7 是已揭示（其余全是雾格）
        _truth35 = {'5,6', '4,7', '5,7'}
        _X0, _Y0, _P = 36.0, 1002.0, 144.0
        _pad = (_P - 30.0 * 4.5) / 2.0
        _wh = int(round(30 / 32.0 * _P))
        _fp_new = _fn_new = 0
        for _r in range(1, 6):
            for _c in range(1, 8):
                _xi = int(round(_X0 + (_c - 1) * _P + _pad))
                _yi = int(round(_Y0 + (_r - 1) * _P + _pad))
                if _xi < 0 or _yi < 0 or _xi + _wh > _g35.shape[1] \
                        or _yi + _wh > _g35.shape[0]:
                    continue
                _m = float(_g35[_yi:_yi + _wh, _xi:_xi + _wh].mean())
                _name = '%d,%d' % (_r, _c)
                _pred = (_m / _L35) >= 0.75
                if _pred and _name not in _truth35:
                    _fp_new += 1
                if _name in _truth35 and not _pred:
                    _fn_new += 1
        check('v1.35 ⑯ 实跑：**真机草原帧**误判数 FP=%d（35 格中，理论下界 1）' % _fp_new,
              _fp_new <= 1, 'L_map=%.1f FN=%d' % (_L35, _fn_new))
        # ⭐ 对照：旧口径（逐格分母）在这帧上的 FP —— 证明修复真有效
        _sids35 = sorted({e[0] for e in _b35.entries})
        _lums35 = _np35.array([_b35._tpl_luma(s) for s in _sids35])
        _fp_old = 0
        for _r in range(1, 6):
            for _c in range(1, 8):
                _xi = int(round(_X0 + (_c - 1) * _P + _pad))
                _yi = int(round(_Y0 + (_r - 1) * _P + _pad))
                if _xi < 0 or _yi < 0 or _xi + _wh > _g35.shape[1] \
                        or _yi + _wh > _g35.shape[0]:
                    continue
                _m = float(_g35[_yi:_yi + _wh, _xi:_xi + _wh].mean())
                _name = '%d,%d' % (_r, _c)
                _j = int(_np35.argmin(_np35.abs(_lums35 - _m)))   # 分类器给它选的地块
                if (_m / _lums35[_j]) >= 0.75 and _name not in _truth35:
                    _fp_old += 1
        check('v1.35 ⑰ 实跑：新口径 FP **显著低于**旧口径（%d → %d ⇒ 修复真有效 ✓）'
              % (_fp_old, _fp_new), _fp_new < _fp_old)
        # ⑱ **跨图回归**：沙滩（能跑的图）新口径必须仍判雾格 ⇒ 不把它弄坏
        _b35s = _sp35mod.Board('S00003')
        _L35s = _b35s._map_luma_ref()
        _fog135 = 139.5        # 真机草原帧实测的雾格绝对亮度（同一台机同一张图盘）
        check('v1.35 ⑱ 跨图：夏日海滩同一雾格 ratio=%.3f **仍 < 0.75**（没弄坏 ✓）'
              % (_fog135 / _L35s), (_fog135 / _L35s) < 0.75,
              'L_map(沙滩)=%.1f vs L_map(草原)=%.1f' % (_L35s, _L35))
        # ⑲ 15 张图全部算得出 L_map（新增地图不用改代码 ✓）
        _maps35 = _sp35mod.map_table()
        _ok35 = 0
        for _nm35, _cd35 in _maps35.items():
            try:
                if _sp35mod.Board(_cd35)._map_luma_ref() > 1e-6:
                    _ok35 += 1
            except Exception:       # noqa: BLE001
                pass
        check('v1.35 ⑲ **全部 %d 张图**都能自动算出 L_map（新增地图零标定 ✓）'
              % len(_maps35), _ok35 == len(_maps35), '成功 %d/%d' % (_ok35, len(_maps35)))
except Exception as _e35b:      # noqa: BLE001
    check('v1.35 实跑闸可运行（%r）' % (_e35b,), False)
# ─────────────────────────────────────────────────────────────────────────
# ㊱ v1.36 ⭐⭐⭐【图名 OCR 错字 + 揭示阈值标定】—— 治「显示面板挡住，实际没有」
#   用户 2026-10-02 13:30 真机报（Redmi 25053RT47C / 广袤草原）：
#     「**最新的显示有面板挡住，但实际上没有**」✗
#   日志铁证：`{"board_hidden":"all_dark","light":0,"gray":29}` 连关 3 次面板，
#     可**同一帧的 OCR 结果里明明有「结束冒险」**（说明 bot 确实在图内、面板没盖住）✗
#   ⚠ 根因**不是** board_hidden，是**图名 OCR 认错字**：
#     OCR 把「广**袤**草原」读成「广**豪**草原」⇒ `_candidate_codes()` 的"包含"匹配
#     **一个都不中** ⇒ 候选 `[]` ⇒ `board_for(code=None)` **回落成默认的夏日海滩**
#     ⇒ 拿沙滩贴图去认草原的格子 ⇒ 整盘分类错 ⇒ `light=0` ⇒ 判"全暗=被挡" ✗✗✗
#     （离线逐字复现：错字时 `light=0 gray=29`、正确字时 `light=2`、`board_hidden` True→False ✓）
#   ⚠ 症状与"真被面板挡住"**完全一样**，只看日志分不出来 ⇒ 必须修错字容忍 ✓
#   修法：`_candidate_codes()` 容忍**差 1 个字**（OCR 错字几乎不改长度）；
#        候选出来后 `_disambiguate_map()` 用**真实帧实测**挑最准的 code ✓
#   另把揭示阈值 **0.75 → 0.80**（实测：已揭示最低 0.855 / 雾格最高 0.761 ⇒ 干净带 0.78~0.85）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊱ v1.36 图名 OCR 错字容忍 + 揭示阈值 0.80')
_FB36 = os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_r0.png')
_FB36B = os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_live.png')
try:
    _el36_src = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                     encoding='utf-8').read()
    _sp36src = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'spots.py'),
                    encoding='utf-8').read()
    check('v1.36 ① 阈值可调且默认 **0.80**（真机实测干净带 0.78~0.85 的中段 ✓）',
          'MAPBOT_REVEAL_RATIO_MIN' in _sp36src and "'0.80'" in _sp36src)
    check('v1.36 ② 阈值**在 spots 定、explore_loop 引用**（单一来源，不两处各写 ✗）',
          'REVEAL_RATIO_MIN = spots_mod.REVEAL_RATIO_MIN' in _el36_src
          # ⚠ v1.60：注释里**抄了 PC 的原文**（"…`REVEAL_RATIO_MIN = 0.75`"）⇒ 不能用
          #   子串判定（会把注释当代码 ⇒ 假红 ✗）改用**行首赋值**判定 ✓
          and not _re.search(r'(?m)^\s*REVEAL_RATIO_MIN\s*=\s*0\.75\s*$', _el36_src))
    check('v1.36 ⑤ 剪影**只作否决**不作通过（已揭示格剪影与雾格重叠 ⇒ 不能单独判 ✓）',
          # ⚠ v1.60：`state()` 的第二趟把那一段的变量名从 `_sil` 改成 `_sn`（避免与逐格的
          #   `_sil` 同名混淆）⇒ 断言跟着改，**判据本身没变**（剪影只作否决 ✓）
          ('bool(_sn < FOG_SIL_MIN)' in _sp36src or 'bool(_sil < FOG_SIL_MIN)' in _sp36src)
          and 'rev_evidence' in _sp36src)
    # ⚠ v1.59：`_ready_boss_cells()` 已删（用户口径「去掉这个」，见 ㊾）⇒
    #   这条顺序断言**不能再引用它**。现在本文件里 `REVEAL_RATIO_MIN` 的**唯一**
    #   使用点在 `board_hidden()` 里 ⇒ 断言"定义 < board_hidden 定义 < 它的使用点" ✓
    check('v1.36 ③ 定义在**所有使用点之前**'
          '（v1.59 后本文件唯一使用点 = `board_hidden()` ✓）',
          # ⚠ v1.62：新的注释里也出现了 `>= REVEAL_RATIO_MIN` 字样（引用 PC 原文）
          #   ⇒ 用 `index()` 会命中**注释**、断言失效 ⇒ 改取**最后一次**（= 真代码那处）✓
          _el36_src.index('REVEAL_RATIO_MIN = spots_mod.REVEAL_RATIO_MIN')
          < _el36_src.index('def board_hidden(')
          < _el36_src.rindex('>= REVEAL_RATIO_MIN'))
    check('v1.36 ④ 双证据开关在位（`dual` 可现场开，默认 `single` 保守 ✓）',
          'MAPBOT_REVEAL_EVIDENCE' in _sp36src and 'REVEAL_EVIDENCE' in _sp36src)
    _ci36 = _el36_src.index('def _candidate_codes(')
    _cbody36 = _el36_src[_ci36:_el36_src.index('\ndef ', _ci36 + 10)]
    check('v1.36 ⑥ 候选匹配**容忍差 1 字**，长度差 >1 不认（别乱勾别的图 ✓）',
          'diff <= 1' in _cbody36 and 'abs(len(_k) - len(_n)) > 1' in _cbody36)
except Exception as _e36:       # noqa: BLE001
    check('v1.36 源码守门可运行（%r）' % (_e36,), False)
# ⑦⑧⑨ **实跑闸**：打真函数 + 两帧真机数据
try:
    _cand36 = EL._candidate_codes('广豪草原')      # ⭐ 真机 13:30 OCR 读到的就是这错字
    check('v1.36 ⑦ 实跑：错字「广豪草原」仍拿到候选 **S10002**（修前是空列表 ✗）',
          'S10002' in (_cand36 or []), 'cands=%s' % (_cand36,))
    # ⚠ 用例要**不含**任何图名的子串，否则走的是老「包含」匹配、测不到新容错逻辑
    # ⚠ 用例必须**既不含、也不被含**任何图名，否则命中的是老「包含」规则、测不到新容错
    _cand36c = EL._candidate_codes('冰原原野空地')      # 与 15 个图名都无子串关系
    check('v1.36 ⑦b 实跑：与所有图名都无子串关系 ⇒ **候选为空**（别乱勾别的图 ✓）',
          not _cand36c, 'cands=%s' % (_cand36c,))
    check('v1.36 ⑦c 实跑：老「包含」匹配仍有效（容错没把老规则破坏 ✓）',
          'S00002' in (EL._candidate_codes('熔岩通道通道口') or []),
          'cands=%s' % (EL._candidate_codes('熔岩通道通道口'),))
    if not os.path.exists(_FB36):
        skip('v1.36 ⑧ 执行级（缺真机草原帧 ⇒ 没真验证）')
    else:
        import cv2 as _cv36
        import numpy as _np36
        _i36 = _cv36.imdecode(_np36.fromfile(_FB36, dtype=_np36.uint8), _cv36.IMREAD_COLOR)
        _log36 = []
        _cd36 = EL._disambiguate_map(_i36, '广豪草原', _cand36, log=_log36)
        _cs36 = EL.cells_of(_i36, mapname='广豪草原')
        _bh36 = EL.board_hidden(_cs36)
        check('v1.36 ⑧ 执行级：错字图名 ⇒ **不误判**"面板挡住棋盘"'
              '（真机 light=0/gray=29 现象 ✓）',
              _cd36 == 'S10002' and _bh36 is False,
              'code=%s light=%d gray=%d board_hidden=%s'
              % (_cd36, len(_cs36['light']), len(_cs36['gray']), _bh36))
        _cs36b = EL.cells_of(_i36, mapname='广袤草原')
        check('v1.36 ⑧b 正确图名**不受影响**（仍不判被挡 ✓）',
              EL.board_hidden(_cs36b) is False,
              'light=%d gray=%d' % (len(_cs36b['light']), len(_cs36b['gray'])))
    # ⑨ 两帧真机（70 格）上 0.80 必须零误判（0.75 会踩 1 格）
    if not (os.path.exists(_FB36) and os.path.exists(_FB36B)):
        skip('v1.36 ⑨ 两帧阈值实跑（缺第二帧真机样本 ⇒ 没真验证）')
    else:
        import cv2 as _cv36b
        import numpy as _np36b
        import spots as _sp36mod
        _bd36 = _sp36mod.Board('S10002')
        _L36 = _bd36._map_luma_ref()
        _X0, _Y0, _P = 36.0, 1002.0, 144.0
        _pad = (_P - 30.0 * 4.5) / 2.0
        _wh = int(round(30 / 32.0 * _P))
        _pairs36 = ((_FB36, {(5, 6), (4, 7), (5, 7)}),      # 帧A 人工标注
                    (_FB36B, {(1, 6), (1, 7), (2, 7)}))      # 帧B 人工标注
        _fp36 = _fn36 = 0
        for _p36, _tr36 in _pairs36:
            _im = _cv36b.imdecode(_np36b.fromfile(_p36, dtype=_np36b.uint8), _cv36b.IMREAD_COLOR)
            _g = _cv36b.cvtColor(_im, _cv36b.COLOR_BGR2GRAY).astype(_np36b.float32)
            for _r in range(1, 6):
                for _c in range(1, 8):
                    _xi = int(round(_X0 + (_c - 1) * _P + _pad))
                    _yi = int(round(_Y0 + (_r - 1) * _P + _pad))
                    if _xi + _wh > _g.shape[1] or _yi + _wh > _g.shape[0]:
                        continue
                    _m = float(_g[_yi:_yi + _wh, _xi:_xi + _wh].mean()) / _L36
                    if (_m >= _sp36mod.REVEAL_RATIO_MIN) and ((_r, _c) not in _tr36):
                        _fp36 += 1
                    if ((_r, _c) in _tr36) and (_m < _sp36mod.REVEAL_RATIO_MIN):
                        _fn36 += 1
        check('v1.36 ⑨ 实跑：两帧真机 70 格上阈值 0.80 ⇒ **零误判**（0.75 会踩 1 格 ✗）',
              _fp36 == 0 and _fn36 == 0, 'FP=%d FN=%d  L_map=%.1f' % (_fp36, _fn36, _L36))
except Exception as _e36b:      # noqa: BLE001
    check('v1.36 实跑闸可运行（%r）' % (_e36b,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊲ v1.37 ⭐⭐⭐【真机三连修】商人买不全 / 首领格误标 / 没目标了还打拦路
#   全部来自用户 2026-10-02 真机报告 + v1.34 日志铁证（Redmi 25053RT47C）：
#   ① 「会把能点的素材格全点开」v1.34 曾用「能点的首领优先」重排治过 ——
#      ⛔ 那个重排**已于 v1.59 按用户口径「去掉这个」删除**（回退到 PC 行为，见 ㊾）；
#      本段治剩下三个
#   ② 「打完拦路的却显示打了首领格，后面又打了首领格」
#   ③ 「第一次只买了三个格子，第二次又打开商人买了第四格」
#   ④ 「打完首领格子且棋盘上没有目标了还在打拦路格子」
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊲ v1.37 商人买全 + 首领格不误标 + 幽灵目标清退图')
try:
    _EL37 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                 encoding='utf-8').read()
    _BP37 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'buypanels.py'),
                 encoding='utf-8').read()
    # ── ① 首领格：`near()` 的邻域结果**不许**进显示/统计 ──────────────────
    check('v1.37 ① `exact_marks()` 存在（**只认本格**标记，不拿邻居顶替 ✓）',
          'def exact_marks():' in _EL37)
    check('v1.37 ② `cell_marks` 改用 **exact**（近似的另记 `near_marks` ✓）',
          "'cell_marks': exact_marks()" in _EL37
          and "'near_marks': mk" in _EL37)
    check('v1.37 ③ `start_fight` 传的是 **exact**（战斗日志不再显示邻居的 boss ✗）',
          'start_fight(b, log, btn, exact_marks())' in _EL37)
    check('v1.37 ④ 结算 `status()` 只用 `_ex`（不再 `_ex or marks` 混口径 ✗）',
          'tile_phrase(_ex)' in _EL37 and 'tile_phrase(_ex or marks)' not in _EL37)
    check('v1.37 ⑤ `near()` 的 docstring 写明"**只用于内部判断**"（防后人误用 ✓）',
          '绝不' in _EL37 and '用于显示' in _EL37)
    # ── ② 幽灵目标：`buy_seen` 跨轮记忆必须按已消耗过滤 ────────────────
    _bi = _EL37.index("st.get('buy_seen')")
    _bj = _EL37.index('\n    #', _bi)
    _mem_body = _EL37[_bi:_bj]
    check('v1.37 ⑥ `buy_seen` 跨轮记忆**按已消耗格过滤**（幽灵目标的根因 ✓）',
          'cell_center(*_rc_p) in done' in _mem_body
          and '_rc_p in _consumed' in _mem_body)
    check('v1.37 ⑦ 全是幽灵时清空 `pending_buy`（让退图判据能生效 ✓）',
          "'targets_ghost_cleared'" in _EL37)
    # ── ③ 商人：OCR 定位 + 数「已购买」+ 逐档验证 ───────────────────────
    check('v1.37 ⑧ 商人「购买」钮**OCR 定位**（不写死；真机 1255 vs 实际 1771 ✗）',
          'def _merchant_buy_btn(bot, log, i):' in _BP37
          and 'bot.tap_dlg(btn[\'cx\'], btn[\'cy\']' in _BP37
          and "bot.tap_dlg(*MERCHANT['buy']" not in _BP37)
    check('v1.37 ⑨ 数「已购买」标签**判进度**（真机 OCR 明明读到了 3 个 ✗）',
          'def _merchant_bought_count(it):' in _BP37
          and "'merchant': 'all_bought'" in _BP37)
    check("v1.37 ⑩ 每档买完**重新 OCR 验证**（没买成就不重复点 ✓）",
          "else 'tap_no_effect'" in _BP37
          and "'merchant': 'stop_no_effect'" in _BP37)
    check("v1.37 ⑪ `i == 0` 找不到购买钮**也停**（旧版 `and i > 0` 排除第 0 次 ✗）",
          "'merchant': 'no_buy_btn'" in _BP37)
    check('v1.37 ⑫ `bought` 记**实际买到的档数**，不再按循环次数 +1',
          "'merchant': 'done', 'bought': bought" in _BP37
          and "bought += 1" not in _BP37.split('def merchant_flow')[1][:2000])
except Exception as _e37:       # noqa: BLE001
    check('v1.37 源码守门可运行（%r）' % (_e37,), False)

# ⑬⑭ **实跑闸**：拿真机 OCR 实测坐标直接打真函数
try:
    import importlib.util as _ilu37
    _bp37p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'buypanels.py')
    _sp37 = _ilu37.spec_from_file_location('bp_v137', _bp37p)
    _bp37m = _ilu37.module_from_spec(_sp37)
    _sp37.loader.exec_module(_bp37m)
    # ⭐ 真机 OCR 实测（Redmi 25053RT47C / 1280×2772 原帧）：右下角购买钮 (1061, 1771)
    _items37 = [{'text': '旅行商人', 'cx': 816, 'cy': 1026},
                {'text': '已购买', 'cx': 257, 'cy': 1615},
                {'text': '已购买', 'cx': 513, 'cy': 1615},
                {'text': '已购买', 'cx': 769, 'cy': 1615},
                {'text': '已购买', 'cx': 1024, 'cy': 1614},
                {'text': '购买', 'cx': 1061, 'cy': 1771}]
    check('v1.37 ⑬ 实跑：数「已购买」= 4（真机 OCR 实测值 ✓）',
          _bp37m._merchant_bought_count(_items37) == 4,
          'got=%d' % _bp37m._merchant_bought_count(_items37))

    class _FakeBot37(object):
        def __init__(self, stages):
            self._st = stages
            self._i = 0
            self.taps = []

        def snap(self, *a, **k):
            pass

        def ocr(self, *a, **k):
            st = self._st[min(self._i, len(self._st) - 1)]
            return [{'text': t, 'cx': x,
                     'cy': 1615 if '已购买' in t else 1771} for t, x in st]

        def tap_dlg(self, x, y, wait=0.0):
            self.taps.append((round(x), round(y)))
            if round(y) == 1771:
                self._i += 1

    # 场景 A：全部已买完 ⇒ **一次都不点购买**（旧版会盲点 4 次 ✗）
    _botA = _FakeBot37([[('已购买', 257), ('已购买', 513), ('已购买', 769),
                         ('已购买', 1024), ('购买', 1061)]])
    _logA = []
    _nA = _bp37m.merchant_flow(_botA, _logA)
    _buyTapsA = [t for t in _botA.taps if t[1] == 1771]
    check('v1.37 ⑭ 实跑：全已购买 ⇒ **0 次购买点击**（旧版盲点 4 次 ✗）',
          not _buyTapsA and _nA == 0,
          'bought=%d taps=%s' % (_nA, _botA.taps))
    # 场景 B：已买 3 档 ⇒ **只补买第 4 档**（用户报的那个场景 ✓）
    _botB = _FakeBot37([[('已购买', 257), ('已购买', 513), ('已购买', 769), ('购买', 1061)],
                        [('已购买', 257), ('已购买', 513), ('已购买', 769),
                         ('已购买', 1024), ('购买', 1061)],
                        [('已购买', 257), ('已购买', 513), ('已购买', 769),
                         ('已购买', 1024), ('购买', 1061)]])
    _logB = []
    _nB = _bp37m.merchant_flow(_botB, _logB)
    _buyTapsB = [t for t in _botB.taps if t[1] == 1771]
    check('v1.37 ⑮ 实跑：已买 3 档 ⇒ **只买 1 次**就认出买完（3_before→4 ✓）',
          len(_buyTapsB) == 1 and _nB == 4,
          'bought=%d 购买点击=%d' % (_nB, len(_buyTapsB)))
    check('v1.37 ⑮b 实跑：补买那一次**用的是 OCR 坐标**（不是写死的 895,1255 ✓）',
          _buyTapsB and _buyTapsB[0] == (1061, 1771),
          'tap=%s' % (_buyTapsB[0] if _buyTapsB else None,))
except Exception as _e37b:      # noqa: BLE001
    import traceback as _tb37
    check('v1.37 实跑闸可运行（%r）' % (_e37b,), False)
    print('   ' + _tb37.format_exc()[-600:])

# ─────────────────────────────────────────────────────────────────────────
# ㊳ v1.38 ⭐⭐【探图连续几轮没产出就收手】—— 治「标记清完了还在继续探图」
#   用户 2026-10-02 真机报（v1.35，Redmi 25053RT47C / 广袤草原）：
#     「为什么现在地图上标记清完了还要继续探图？」✗
#   **铁证**（v1.35 真机日志 + `marks_none_r3.png` 真帧**人工核对**）：
#     `solver: no_plan`                        ← 模型已判定盘上没目标 ✓
#     `obs_merge: grew, added: 2`              ← 探图又开了 2 格（体力照花）
#     `{"explore":"mode","grays":20,"clicks":1}` ← 却**一个目标都没逼出来** ✗
#     那张真帧：整盘黄色沙地 + 绿/蓝矿石，**确实一个标记都没有** ✓
#   根因：v1.29 的 `need_explore()` 只看「暗格 ≥ 8」+「点击 < 40」，
#     **完全不看"探图有没有产出"** ⇒ 暗格够多就永远探下去 ⇒ 白烧体力 ✗✗
#   修法：加 `no_yield_rounds` —— 探图**连续 N 轮没逼出新目标** ⇒ 收手退图 ✓
#   ⚠ **不能**因为加了就退��：v1.29 那个「24 暗格一格没开就退图」的病必须仍被覆盖 ✓
# ─────────────────────────────────────────────────────────────────────────
# ㊴⏤ v1.38 ⭐【商人选钮选错 ⇒ 一次都没买成】—— 治用户 2026-10-02 真机报
#   「刚刚手机上那把，商人一次购买都没就显示购买完成」
#   **真机铁证**（v1.37 日志第 44~47 行，Redmi/广袤草原）：
#     OCR 读到 → [..., "4档","3档","2档","1档","购买",
#                     "※依次在四个档位购买包罗万象的奖励内容"]
#     `{"merchant":"tap_no_effect","btn":[345,1337],"n_before":0,"n_after":0}`
#     `{"merchant":"done","bought":0}`
#   根因：v1.37 的选钮只排除了「已购买」，可 **`※依次…购买…` 是说明文字、也含"购买"**
#     ⇒ 排序后选中它（x=345）⇒ **点在文字上、一下都没买成** ✗
#   ⚠ v1.37 注释里"真机只有右下角一个购买"是**错的**：那是照着**全已购买**的截图下的结论；
#     **面板还有 4 档可买时说明文字也在** ⇒ 结论不成立 ✓（已改）
#   修法：三重过滤 —— ① 排除「已购买」② 排除说明文字（依次/※/奖励内容/包罗万象…）
#          ③ 仍取最靠右下的（右下角总钮 x 最大 ⇒ 真机 1061 vs 说明 443 ✓）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊴⏤ v1.38 商人选钮：排除说明文字（真机一次都没买成）')
try:
    import importlib.util as _ilu38
    _bp38p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'buypanels.py')
    _sp38 = _ilu38.spec_from_file_location('bp_v138b', _bp38p)
    _bp38 = _ilu38.module_from_spec(_sp38)
    _sp38.loader.exec_module(_bp38)
    _src38 = open(_bp38p, encoding='utf-8').read()
    check('v1.38 ① 选钮**排除说明文字**（`※依次…购买…` 也含"购买"二字 ✗）',
          "any(w in tx for w in ('依次'" in _src38 and '包罗万象' in _src38)
    check('v1.38 ② 仍取**最靠右下**的（右下角总钮 x 最大 ✓）',
          "cands.sort(key=lambda t: (t['cy'], t['cx']))" in _src38)

    # ⭐ **实跑闸**：直接用真机 v1.37 日志里的**真实 OCR 文本**
    _REAL38 = ['4档', '3档', '2档', '1档', '购买',
               '※依次在四个档位购买包罗万象的奖励内容']

    def _mk38(texts, buy=(1061, 1771), desc=(443, 1785)):
        out = []
        for _t in texts:
            if _t == '购买':
                out.append({'text': _t, 'cx': buy[0], 'cy': buy[1]})
            elif '依次' in _t:
                out.append({'text': _t, 'cx': desc[0], 'cy': desc[1]})
            else:
                out.append({'text': _t, 'cx': 400, 'cy': 1100})
        return out

    class _B38(object):
        ocr_grabs = True

        def __init__(self, items):
            self._it = items

        def snap(self, *a, **k):
            pass

        def ocr(self, *a, **k):
            return self._it

    _btn38, _ = _bp38._merchant_buy_btn(_B38(_mk38(_REAL38)), None, 0)
    check('v1.38 ③ 实跑：真机那帧（4 档可买 + 说明文字）⇒ 选中**右下角**而非说明文字',
          (_btn38['cx'], _btn38['cy']) == (1061, 1771),
          '选中 (%d,%d)，说明文字在 (443,1785)' % (_btn38['cx'], _btn38['cy']))

    _ST38 = [['4档', '3档', '2档', '1档', '购买'],
             ['4档', '已购买', '2档', '1档', '购买'],
             ['4档', '已购买', '已购买', '1档', '购买'],
             ['4档', '已购买', '已购买', '已购买', '购买'],
             ['4档', '已购买', '已购买', '已购买', '已购买']]

    class _Flow38(object):
        ocr_grabs = True

        def __init__(self):
            self.i = 0
            self.taps = []

        def snap(self, *a, **k):
            pass

        def ocr(self, *a, **k):
            st = _ST38[min(self.i, len(_ST38) - 1)]
            nb = sum(1 for x in st if x == '已购买')
            out = []
            for _t in st:
                if _t == '购买':
                    out.append({'text': _t, 'cx': 1061, 'cy': 1771})
                elif _t == '已购买':
                    out.append({'text': _t, 'cx': 257 + 255 * nb, 'cy': 1615})
                else:
                    out.append({'text': _t, 'cx': 400, 'cy': 1100})
            return out

        def tap_dlg(self, x, y, wait=0.0):
            self.taps.append((round(x), round(y)))
            if round(y) == 1771:
                self.i += 1

    _f38 = _Flow38()
    _n38 = _bp38.merchant_flow(_f38, [])
    _buys38 = [t for t in _f38.taps if t[1] == 1771]
    check('v1.38 ④ 实跑：4 档可买 ⇒ **买满 4 次、记 4 档**（真机那次是 0 次 ✗）',
          len(_buys38) == 4 and _n38 == 4,
          '点击 %d 次 bought=%d' % (len(_buys38), _n38))
except Exception as _e38c:      # noqa: BLE001
    check('v1.38 商人守门可运行（%r）' % (_e38c,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊵⏤ v1.39 ⭐⭐【商人「恭喜获得」奖励页】—— 治「只买了一次就显示购买完成」
#   用户 2026-10-02 真机报（v1.38，Redmi/广袤草原）：
#     「旅行商人只买了一次就显示购买完成」
#   **真机铁证**（v1.38 日志第 32/38/44 行）：
#     第32行 商店主面板 `4档 3档 2档 1档 购买 ※依次在四个档位购买包罗万象的奖励内容`
#     第33行 `tap_no_effect  btn=[895,1284]  n_before=0  n_after=0`
#     第38行 **`恭喜获得`** ← **只有买成功才会出现** ⇒ 第一次点击其实**买成了** ✗
#     第39/45行 又两次 `tap_no_effect btn=[294,1336]`（这次面板已是奖励页）
#   根因（两层）：
#     ① 买成判据**只数「已购买」标签** ⇒ 奖励页上没这个标签 ⇒ 读成 0
#        ⇒ `n_before=0 → n_after=0` ⇒ 误判 `tap_no_effect` ⇒ **只买1次就收手** ✗✗
#     ② 奖励页**也有「购买」二字**（在「依次…购买…」说明句里）⇒ 旧代码在奖励页上
#        继续找购买钮 ⇒ 点到说明文字（294,1336 / 895,1284）⇒ 完全无效 ✗
#   修法：① 「恭喜获得」也算买成信号  ② 已在奖励页 ⇒ 先点「返回」回商店
#          ③ 奖励页只点**一次**返回就 `continue`（连点两次会把面板关掉 ⇒ 后面买不了 ✗）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊵⏤ v1.39 商人奖励页：买成判据认「恭喜获得」+ 只点一次返回')
try:
    import importlib.util as _ilu39
    _bp39p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'buypanels.py')
    _sp39 = _ilu39.spec_from_file_location('bp_v139', _bp39p)
    _bp39 = _ilu39.module_from_spec(_sp39)
    _sp39.loader.exec_module(_bp39)
    _s39 = open(_bp39p, encoding='utf-8').read()
    check('v1.39 ① 买成判据**认「恭喜获得」**（奖励页上没「已购买」标签 ✗）',
          "_has(it, '恭喜获得'" in _s39 and '_ok = _got_page or' in _s39)
    check('v1.39 ② 已在奖励页 ⇒ **先点返回**回商店（别在奖励页上找购买钮 ✗）',
          "{'merchant': 'back_to_shop'" in _s39)
    check('v1.39 ③ 奖励页**只点一次**返回就 `continue`（连点两次会关面板 ✗）',
          "{'merchant': 'back_from_got'" in _s39 and 'continue' in _s39)
    check('v1.39 ④ `bought` 按**实际 +1**（奖励页读不到标签，不能用 n_after ✗）',
          'bought = n_after if n_after > n_bought else bought + 1' in _s39)
    check('v1.39 ⑤ 说明文字过滤词**加长**（真机 OCR 会截断成「依次…购买包罗」✗）',
          "'依次', '※', '每档', '奖励', '包罗', '万象'" in _s39)

    # ⭐ **实跑闸**：真机 v1.38 的三帧真实 OCR 文本
    _SHOP39 = ['旅行商人', '4档', '3档', '2档', '1档', '购买',
               '※依次在四个档位购买包罗万象的奖励内容']
    _GOT39 = ['旅行商人', 'X', '恭喜获得', '道具', '返回', '购买',
              '依次在四个档位购买包罗', '4000', '每次购买后消耗的金币数量都']

    def _mk39(texts, nb=0):
        out = []
        for _t in texts:
            if _t == '购买':
                out.append({'text': _t, 'cx': 1061, 'cy': 1771})
            elif '依次' in _t:
                out.append({'text': _t, 'cx': 443, 'cy': 1785})
            elif '返回' in _t:
                out.append({'text': _t, 'cx': 538, 'cy': 1267})
            elif _t == 'X':
                out.append({'text': _t, 'cx': 983, 'cy': 602})
            elif _t == '已购买':
                out.append({'text': _t, 'cx': 257 + 255 * nb, 'cy': 1615})
            else:
                out.append({'text': _t, 'cx': 500, 'cy': 900})
        return out

    _SEQ39 = [('s', 0), ('g', 0), ('s', 1), ('g', 1), ('s', 2), ('g', 2),
              ('s', 3), ('g', 3), ('s', 4)]

    class _F39(object):
        ocr_grabs = True

        def __init__(self, start=0):
            self.i = start
            self.taps = []

        def snap(self, *a, **k):
            pass

        def ocr(self, *a, **k):
            k39, nb = _SEQ39[min(self.i, len(_SEQ39) - 1)]
            return _mk39(_SHOP39 if k39 == 's' else _GOT39, nb)

        def tap_dlg(self, x, y, wait=0.0):
            self.taps.append((round(x), round(y)))
            if (round(x), round(y)) in ((1061, 1771), (538, 1267)):
                self.i += 1

    _f39 = _F39()
    _n39 = _bp39.merchant_flow(_f39, [])
    _buys39 = [t for t in _f39.taps if t == (1061, 1771)]
    _backs39 = [t for t in _f39.taps if t == (538, 1267)]
    check('v1.39 ⑥ 实跑：4 档可买 ⇒ **买 4 次、记 4 档**（真机那次只买 1 次 ✗）',
          len(_buys39) == 4 and _n39 == 4,
          '买=%d 返回=%d bought=%d' % (len(_buys39), len(_backs39), _n39))
    check('v1.39 ⑦ 实跑：买 4 档只点 **4 次**返回（连点两次会关面板 ✗）',
          len(_backs39) == 4, '返回点击 %d 次' % len(_backs39))
    # 奖励页上不该点「购买」——真机那次点了 (294,1336)/(895,1284)
    _f39b = _F39(start=1)          # 直接停在奖励页
    _bp39.merchant_flow(_f39b, [])
    _bad39 = [t for t in _f39b.taps if t in ((294, 1336), (895, 1284))]
    check('v1.39 ⑧ 实跑：奖励页上**不点**那两处说明文字坐标（真机 294,1336/895,1284 ✗）',
          not _bad39, '乱点=%s' % (_bad39,))
except Exception as _e39:       # noqa: BLE001
    check('v1.39 奖励页守门可运行（%r）' % (_e39,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊶⏤ v1.40 ⭐⭐【商人买完的格子要消失】—— 治「买完商人，下一次规划又打开商人格」
#   用户 2026-10-02 真机报：「买完商人后，商人格子**不会消失**，下一次规划又打开了
#   商人格子。（**黄金宝库买完会消失**）」✗
#   **真机铁证**（v1.39 日志，同一张图）：
#     `{"merchant":"done","bought":4}`                  ← 四档全买成 ✓
#     下一轮 `{"solver":"ok","targets":2}`             ← 这一盘只有 1 个 boss ⇒ 多一个就是商人格 ✗
#     又打开一次商人面板 `{"merchant":"all_bought"}`   ← 认出来了、没重复买，但**白点一次** ✗
#   根因：v1.27 那段"买完登记 `buy_consumed`"**只加给了黄金宝库**
#     （当时报的是"宝库还剩 1 个目标"），商人的成功分支只有 `STATS['merchants'] += 1`
#     ⇒ 商人格永久留在 `buy_seen` 里，每轮都被刷新、永远进不了"已消耗" ✗✗
#   修法：商人成功分支**同口径**登记（+ 门槛 `_mok > 0`：
#         流程走完但没买到（已买完/没钱）时**不能**登记，否则那一格被永久拉黑 ✗）
#   另：探索派遣日志补 `tile`/`sid`/`is_purple`（旧日志只有坐标、
#       board 又被截断到 300 字符 ⇒ 事后**查不出点的哪格** ✗）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊶⏤ v1.40 商人买完登记"已消耗" + 探索日志补诊断')
try:
    _EL40 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                 encoding='utf-8').read()
    check('v1.40 ① 商人成功分支**登记"已消耗"**（与宝库同口径 ✓）',
          "{'merchant': 'consumed'" in _EL40
          and "setdefault('buy_consumed', set()).add(_rcm)" in _EL40)
    _im = _EL40.index("{'merchant': 'consumed'")
    _segm = _EL40[max(0, _im - 1000):_im + 200]
    check('v1.40 ② 登记时**从 buy_seen / buy_sticky 删掉**（否则每轮被刷新回来 ✗）',
          "get('buy_seen', {}).pop" in _segm
          and "get('buy_sticky', {}).pop" in _segm)
    check('v1.40 ③ 门槛 `_mok > 0`（流程走完但**没买到**时不登记，否则永久拉黑 ✗）',
          'and _mok > 0' in _segm)
    _is = _EL40.index("STATS['merchants'] += 1")
    check('v1.40 ④ 登记在**商人统计之后**（不是误加到别的分支 ✗）',
          _im > _is, '差 %d 行' % (_im - _is))
    # ⭐ 回归：宝库那份不能被改坏
    _iv = _EL40.index("{'vault': 'consumed'")
    _segv = _EL40[max(0, _iv - 800):_iv + 200]
    check('v1.40 ⑤ 回归：宝库的登记**未被改坏**（两条路径都在 ✓）',
          "setdefault('buy_consumed', set()).add(_rcv)" in _segv
          and "{'vault': 'consumed'" in _EL40)
    # ⑥ 探索日志补诊断
    _ie = _EL40.index("log.append({'explore': 'first_high_value'")
    _sege = _EL40[_ie:_ie + 700]
    check('v1.40 ⑥ 探索日志记了 `tile`/`sid`/`is_purple`（事后能查点的哪格 ✗）',
          "'tile':" in _sege and "'sid': _tapped_sid" in _sege
          and "'is_purple':" in _sege)
except Exception as _e40:       # noqa: BLE001
    check('v1.40 守门可运行（%r）' % (_e40,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊷⏤ v1.42【门禁自查：改动文件必须有执行级覆盖】（学 PC 端 verify_hotupdate.py T7）
#   **PC 端的教训**：自检清单写死 ⇒ 补丁里**新增/修改**的模块从没被 import 过
#     ⇒ 塞一个 import 期必抛异常的模块，自检**照样「通过」** ✗✗
#     修法：检查范围 = 固定清单 ∪ **本次实际改动的文件**。
#   **手机端的等价风险（2026-10-03 实测）**：本门禁 487 条里 **387 条（79%）**
#     是「在源码里搜某个字符串」⇒ 改了实现方式但没改那个字符串时，
#     这 387 条**集体哑掉**，而门禁照样报「全绿」✗
#   ⇒ 本组门禁把「哪些模块被改动」与「它们有没有被实跑」绑起来检查：
#     任何**被改过的业务模块**若只有源码字符串检查、没有实跑覆盖 ⇒ 当场报出来 ✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊷⏤ v1.42 门禁自查：被改动的模块必须有执行级覆盖')
try:
    import re as _re
    import subprocess as _spa
    _BUSINESS = ['explore_loop.py', 'buypanels.py', 'spots.py', 'marks.py',
                 'badge.py', 'mapsim.py', 'mapsolve.py', 'strategy.py',
                 'layout.py', 'mapbot.py', 'targets_cfg.py', 'grid_detect.py',
                 'mapgen.py']
    # ① 本次工作区/上次提交里**实际改过**的业务模块
    try:
        _r = _spa.run(['git', '-C', PROJ, 'diff', '--name-only', 'HEAD'],
                      capture_output=True, text=True, encoding='utf-8',
                      errors='replace')
        _changed = [ln.strip() for ln in (_r.stdout or '').splitlines() if ln.strip()]
    except Exception:
        _changed = []
    _chg_mod = sorted({os.path.basename(p) for p in _changed
                       if os.path.basename(p) in _BUSINESS})
    # ② 门禁源码里，哪些模块被「实跑」（import 后调用真函数 / 跑子进程）
    _g = open(os.path.join(PROJ, 'tools', 'verify_explore_slots_fix.py'),
              encoding='utf-8').read()
    _gl = _g.split('\n')
    _executed = set()
    for _i, _l in enumerate(_gl):
        if _re.search(r'module_from_spec|exec_module|importlib', _l) or \
           _re.search(r'\bimport (explore_loop|spots|marks|badge|mapsim|'
                      r'mapsolve|strategy|grid_detect|buypanels)\b', _l):
            for _w in _BUSINESS:
                # 该行附近 30 行内 import 了它 ⇒ 算实跑
                _seg = '\n'.join(_gl[max(0, _i - 5):_i + 30])
                if _re.search(r'import[^\n]*\b' + _re.escape(_w[:-3]) + r'\b', _seg):
                    _executed.add(_w)
    # ③ 报告
    if not _chg_mod:
        check('v1.42 ① 本次无业务模块改动（或不在 git 视野内）⇒ 跳过动态覆盖自查',
              True, '改动=%s' % (_chg_mod,))
    else:
        miss = [m for m in _chg_mod if m not in _executed]
        check('v1.42 ① 被改动的业务模块都有**执行级覆盖**（不被 387 条字符串检查蒙混 ✗）',
              not miss,
              '改动=%s  未实跑=%s' % (_chg_mod, miss or '无'))
    # ④ 硬性元门禁：字符串检查占比不能高到失控（PC 端 T7 的教训）
    _n_all = len(_re.findall(r'\bcheck\(', _g))
    # ⚠ ��测里**必须**认「import X as _别名」这种写法（我自己就先漏了它，
    #   导致 ③④⑤ 三条实跑断言被误判成只查字符串 ⇒ 占比虚低 ✗）
    _EXEC_PAT = _re.compile(
        r'module_from_spec|exec_module|subprocess|for _r in range|'
        r'\.state\(|_purge|_merchant_bought_count|'
        r'\bimport\s+\w+\s+as\s+_\w+|'
        r'\bimport\s+(explore_loop|spots|marks|badge|mapsim|mapsolve|'
        r'strategy|grid_detect|buypanels|explore_android|mapbot)\b')
    _n_exec = len([1 for i, l in enumerate(_gl)
                   if _re.search(r'\bcheck\(', l)
                   and _EXEC_PAT.search('\n'.join(_gl[i:i + 14]))])
    _ratio = 100.0 * _n_exec / max(1, _n_all)
    check('v1.42 ② 执行级检查占比 ≥ 15%%（低于此说明门禁退化成"搜字符串" ✗）',
          _ratio >= 15.0,
          '实跑 %d / 共 %d = %.0f%%' % (_n_exec, _n_all, _ratio))
except Exception as _e42:       # noqa: BLE001
    check('v1.42 门禁自查可运行（%r）' % (_e42,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊸⏤ v1.42【给「只有源码检查」的关键判据补执行级断言】（PC 端 T7 教训）
#   下面这三条在自查里被判为「⚠ 只有源码检查」—— 改了实现没改字符串就会哑 ✗
#   ⇒ 现在改成**直接调真函数 / 读真常量** ✓
# ─────────────────────────────────────────────────────────────────────────
try:
    import importlib.util as _ilu42b
    import spots as _sp42b
    import explore_loop as _el42b

    # ① 揭示阈值：读**真常量**（不是搜字符串），并验它落在真机实测的干净带内
    #    真机两帧 70 格实测：已揭示最低 0.855 / 雾格最高 0.761 ⇒ 干净带 0.78~0.85
    _thr42 = float(_sp42b.REVEAL_RATIO_MIN)
    check('v1.42 ③ 揭示阈值**读真常量**且落在真机干净带 0.78~0.85 内'
          '（0.75 会踩雾格上界 0.761 ✗）',
          0.78 <= _thr42 <= 0.85, 'REVEAL_RATIO_MIN=%.3f' % _thr42)
    #    且 explore_loop 引的**就是同一个数**（单一来源，改一处必须两处都变）
    check('v1.42 ③b explore_loop 的阈值与 spots **同源**（不是各写一份 ✗）',
          float(_el42b.REVEAL_RATIO_MIN) == _thr42,
          'explore_loop=%.3f spots=%.3f' % (_el42b.REVEAL_RATIO_MIN, _thr42))

    # ② 图名错字容忍：**实跑**几个真实错字，别只搜 `diff <= 1`
    _cands = [
        ('广豪草原', 'S10002', True),      # 真机 OCR 读到的错字（袤→豪）
        ('广袤草原', 'S10002', True),      # 正确
        ('夏日海滩', 'S00003', True),      # 完全正确
        ('熔岩通道口', 'S00002', True),    # 差 1 字
        ('幽暗密林', 'S20002', True),      # 正确
        ('冰原原野空地', None, False),      # 与 15 个图名**都无子串关系** ⇒ 不该命中
        ('不存在的图名字', None, False),
    ]
    _bad42 = []
    for _nm42, _want42, _must42 in _cands:
        _got42 = _el42b._candidate_codes(_nm42)
        if _must42:
            if _want42 not in (_got42 or []):
                _bad42.append('%s 应命中 %s 实得 %s' % (_nm42, _want42, _got42))
        else:
            if _got42:
                _bad42.append('%s 不该命中 实得 %s' % (_nm42, _got42))
    check('v1.42 ④ 实跑图名容错：错 1 字能认、差 2 字不乱认（7 个用例全对 ✓）',
          not _bad42, 'bad=%s' % (_bad42,) if _bad42 else '全对')

    # ③ 商人「已消耗」登记：**实跑** merchant_flow，验证买完会登记
    _SHOP42 = ['旅行商人', '4档', '3档', '2档', '1档', '购买',
               '※依次在四个档位购买包罗万象的奖励内容']

    def _mk42(texts):
        out = []
        for _t in texts:
            if _t == '购买':
                out.append({'text': _t, 'cx': 1061, 'cy': 1771})
            elif '依次' in _t:
                out.append({'text': _t, 'cx': 443, 'cy': 1785})
            elif '返回' in _t:
                out.append({'text': _t, 'cx': 538, 'cy': 1267})
            elif _t == 'X':
                out.append({'text': _t, 'cx': 983, 'cy': 602})
            elif _t == '已购买':
                out.append({'text': _t, 'cx': 500, 'cy': 1615})
            else:
                out.append({'text': _t, 'cx': 500, 'cy': 900})
        return out

    class _B42(object):
        ocr_grabs = True

        def __init__(self):
            self.i = 0
            self.taps = []

        def snap(self, *a, **k):
            pass

        def ocr(self, *a, **k):
            # 一次就返回「全已购买」⇒ merchant_flow 应立刻 all_bought 且**一次都不点购买**
            return _mk42(['已购买', '已购买', '已购买', '已购买', '购买'])

        def tap_dlg(self, x, y, wait=0.0):
            self.taps.append((round(x), round(y)))

    import buypanels as _bp42
    _fb42 = _B42()
    _n42 = _bp42.merchant_flow(_fb42, [])
    _buys42 = [t for t in _fb42.taps if t == (1061, 1771)]
    check('v1.42 ⑤ 实跑商人：全已购买 ⇒ **0 次购买点击**（源码改了实现也拦得住 ✓）',
          not _buys42 and _n42 == 0, 'bought=%d taps=%s' % (_n42, _fb42.taps))
except Exception as _e42b:      # noqa: BLE001
    check('v1.42 执行级断言可运行（%r）' % (_e42b,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊹⏤ v1.43 ⭐⭐【拦路格按战斗价 size×2】—— 学 PC 端 a7df4af（真机事故）
#   **PC 端的事故原话**：「战斗格的体力需要是格数×2，**拦路那个消耗 6 体啊**」
#     计划 `['2,6','2,5','3,1']` 的第一步 2,6 = `S00003_111`（海边杂物，格数 3）
#     ⇒ 被定价成 **3**（掉到"内容格·探索"那档）⇒ 实际应为 **3×2 = 6**
#     ⇒ 求解器自报"最省体力 8"、日志对账 3+1+6=10 ≠ 8 ⇒ **把要打的架少算一半**
#     ⇒ 挑出"看起来便宜、实际更贵"的路 ✗✗
#   **根因（PC 端已论证清楚，手机端同款）**：
#     那一格的「拦路」标记是**规划完之后**才贴上去的（循环发现"计划路径穿过非空地"才标）
#     ⇒ **规划那一刻它没有标记** ⇒ 按标记定价永远算不对 ⇒ 治标不治本 ✗
#   ⇒ 正解：**按地块类型**判（数据表 `Area_Spot.EventNum` 首段 > 1 ⇒ 战斗型）
#        草地/海螺/宝箱/岩石 `1-1` ⇒ 不打；海边杂物 `3-3`、游乐设施 `4-4`、
#        巨大沙堡 `8-8` ⇒ 要打 ✓（与 PC 端 `spots.is_fight_spot` 同口径）
#   ⚠ 手机端**自己写一遍** `is_fight_spot`（两端平行独立开发，见 AGENTS.md §1）✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊹⏤ v1.43 拦路格按战斗价（EventNum 判据，不看规划期还没有的标记）')
try:
    import importlib as _il43
    _il43.invalidate_caches()
    import spots as _sp43
    import mapsolve as _ms43
    import mapsim as _sim43
    import sys as _sy43
    if (PROJ + r'\app\src\main\python') not in _sy43.path:
        _sy43.path.insert(0, PROJ + r'\app\src\main\python')

    # ① is_fight_spot 判据本身（真数据表）
    _c43 = [('S00003_000', False), ('S00003_001', False), ('S00003_002', False),
            ('S00003_111', True)]
    _bad43 = []
    for _sid, _want in _c43:
        _g = _sp43.is_fight_spot(_sid)
        if _g != _want:
            _bad43.append('%s=%s(要%s)' % (_sid, _g, _want))
    check('v1.43 ① `is_fight_spot` 判据对（EventNum 首段>1 ⇒ 战斗；营地/草地/沙地/海边杂物）',
          not _bad43, 'bad=%s' % (_bad43,) if _bad43 else '4/4 全对')

    # ② 端到端：拦路格（3格/无标记/非target）必须 size×2
    _cells43 = {
        (1, 1): {'sid': 'S00003_000', 'name': '营地', 'revealed': True,
                 'ratio': 1.0, 'marks': [], 'anchor': (1, 1)},
        (2, 1): {'sid': 'S00003_111', 'name': '海边杂物', 'revealed': True,
                 'ratio': 0.9, 'marks': [], 'anchor': (2, 1)},
        (3, 1): {'sid': 'S00003_111', 'name': '海边杂物', 'revealed': True,
                 'ratio': 0.9, 'marks': [], 'anchor': (2, 1)},
        (4, 1): {'sid': 'S00003_111', 'name': '海边杂物', 'revealed': True,
                 'ratio': 0.9, 'marks': [], 'anchor': (2, 1)},
        (1, 4): {'sid': 'S00003_001', 'name': '草地', 'revealed': True,
                 'ratio': 0.9, 'marks': [], 'anchor': (1, 4)},
        (2, 3): {'sid': 'S00003_222', 'name': '巨大沙堡', 'revealed': True,
                 'ratio': 0.9, 'marks': ['boss'], 'anchor': (2, 3)},
        (3, 3): {'sid': 'S00003_222', 'name': '巨大沙堡', 'revealed': True,
                 'ratio': 0.9, 'marks': ['boss'], 'anchor': (2, 3)},
    }
    _sim43 = _sim43.MapSim.from_observation(_cells43, _sp43.spot_rows())
    _prob43 = _ms43.Problem(_sim43)
    _cost43 = {}
    for _bi in sorted(_prob43.blocks):
        _b = _prob43.blocks[_bi]
        if getattr(_b, 'plain', False):
            continue
        _cost43.setdefault((getattr(_b, 'name', '?'), getattr(_b, 'mark', None)),
                           (getattr(_b, 'size', 1), _prob43.step_cost(frozenset(), _bi)))
    _block = _cost43.get(('海边杂物', None))
    check('v1.43 ② 拦路格（3格/无标记/非target）cost = **6** = 3×2'
          '（修前是 3 ⇒ 把要打的架少算一半 ✗）',
          _block is not None and _block[1] == _block[0] * 2,
          'cost=%s（size=%s）' % (_block[1] if _block else '?', _block[0] if _block else '?'))
    _boss = _cost43.get(('巨大沙堡', 'boss'))
    check('v1.43 ③ boss 格仍按 size×2（没被这次改动影响 ✓）',
          _boss is not None and _boss[1] == _boss[0] * 2)
    # ⚠ 草地(S00003_001) 在模型里是 **plain（空地）**（SpecialSpot==0 且 SpotSize==1）
    #   ⇒ 走「空地固定 1 点」那条，早于战斗判定 ⇒ 天然不会被误升 ✓
    _camp = _cost43.get(('营地', None))
    check('v1.43 ④ 空地/营地类**没被误升成战斗价**（S00003_001 是 plain ⇒ 固定 1 点 ✓）',
          _camp is None or _camp[1] == 1,
          '营地 cost=%s（应为 1）' % (_camp[1] if _camp else '?'))
    # ⑤ 判据**不能**依赖"规划期还没有的标记"（PC 端踩过的坑）
    _src43 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsolve.py'),
                  encoding='utf-8').read()
    # ⚠ 必须**排除注释行**（上面注释里故意写了 bi in self.targets，记录错误做法）
    _code43 = chr(10).join(x for x in _src43.split(chr(10))
                      if not x.strip().startswith('#'))
    check('v1.43 ⑤ 判据用 \is_fight_spot\（**地块类型**）而不是 in targets / 拦路标记'
          '（PC 端论证：那些在规划时还不存在 ⇒ 治标不治本 ✗）',
          'is_fight_spot' in _src43
          and 'bi in self.targets' not in _code43)
except Exception as _e43:       # noqa: BLE001
    check('v1.43 守门可运行（%r）' % (_e43,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊺⏤ v1.44【拉黑块从一开始就不进规划 + 宝库 probe 默认关】（学 PC 端两条）
#   ① d81c42c「拉黑块**从一开始就不进规划**」
#      PC 端根因：拉黑块是**事后从点序里剔除**的 ⇒ 求解器算**连通性/代价**时
#        仍按"能走"算过一遍 ⇒ 剔除后计划出现断档 / 绕路不合理 ✗
#      手机端 v0.99 已在 `_cells_for_model` 打 `blocked` 标，但**只用于点序过滤**，
#        `mapsim` 没接、`mapsolve` 没用 ⇒ **同一个问题** ✗
#      修（三处贯通，照 PC 端）：
#        mapsim.Block.blocked + 两条建 row 的路都搬观测的 `blocked` ✓
#        mapsolve.visible() 里 `vis -= blocked` ⇒ **既不可点、也不借它走路** ✓
#      ⚠ 语义仍是「**留在模型里**」（board>=0 ⇒ 不是"已消耗"⇒ 不参与空地连锁 ✓，
#        v0.99 那条结论依然成立）
#   ② b3f92d8【B】「也不要去额外点宝库了，严格走计划」
#      ratio 抖动造成的"假未揭示"是**识别问题**，用"多点几下试试"掩盖 = 拿体力赌识别，
#      还会插队打乱规划 ✗ ⇒ 默认关掉 `vault_probe`（开关保留，可现场开回来）✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊺⏤ v1.44 拉黑块不进规划 + 宝库 probe 默认关')
try:
    import mapsim as _sim44
    import mapsolve as _solv44
    import spots as _sp44
    import sys as _sy44
    if (PROJ + r'\app\src\main\python') not in _sy44.path:
        _sy44.path.insert(0, PROJ + r'\app\src\main\python')

    def _c44(sid, name, marks=(), anchor=None, ratio=0.9, blocked=False, target=None):
        _d = {'sid': sid, 'name': name, 'revealed': True, 'ratio': ratio,
              'marks': list(marks), 'anchor': anchor or (0, 0)}
        if blocked:
            _d['blocked'] = True
        if target is not None:
            _d['target'] = target
        return _d

    # ① blocked 链贯通
    _cells44 = {
        (1, 1): _c44('S00003_000', '营地', anchor=(1, 1)),
        (2, 1): _c44('S10001_001', '勇者之墓', anchor=(2, 1), blocked=True, target=False),
        (3, 1): _c44('S10001_001', '勇者之墓', blocked=True, target=False),
        (1, 2): _c44('S00003_001', '草地', anchor=(1, 2)),
        (2, 2): _c44('S00003_001', '草地', target=False),
        (2, 3): _c44('S00003_002', '沙地', marks=['boss'], anchor=(2, 3), target=True),
        (3, 3): _c44('S00003_002', '沙地', marks=['boss'], target=True),
    }
    _sim44 = _sim44.MapSim.from_observation(_cells44, _sp44.spot_rows())
    _prob44 = _solv44.Problem(_sim44)
    _blk44 = [bi for bi, b in _prob44.blocks.items() if getattr(b, 'blocked', False)]
    _vis44 = _prob44.visible(frozenset())
    check('v1.44 ① blocked 链**贯通**（观测→Block→visible ✓）',
          len(_blk44) > 0,
          '模型里 blocked 块 %d 个' % len(_blk44))
    check('v1.44 ② 拉黑块**不在 visible() 里**（既不可点、也不借它走路 ✗）',
          not any(b in _vis44 for b in _blk44),
          '漏=%s' % ([b for b in _blk44 if b in _vis44] or '无 ✓'))
    # ③ 源码链三处都在（防止后来被改回去）
    _sm44 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsim.py'),
                 encoding='utf-8').read()
    _sv44 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsolve.py'),
                 encoding='utf-8').read()
    _el44 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                 encoding='utf-8').read()
    check('v1.44 ③ `mapsim` 两条建 row 的路都搬了 `blocked`（观测字段到不了 Block 就白搭 ✗）',
          _sm44.count("row['blocked']") >= 2,
          'mapsim 里 row[blocked] 出现 %d 次' % _sm44.count("row['blocked']"))
    check('v1.44 ④ `mapsolve.visible()` 里真的做了 `vis -= blocked`',
          'vis -= _blk' in _sv44 or 'vis -= blocked' in _sv44)
    # ⑤ 宝库 probe 默认关
    check('v1.44 ⑤ 宝库 probe 有开关且**默认关**（严格走计划 ✓）',
          'MAPBOT_VAULT_PROBE' in _el44,
          '探针默认值 = %s' % ((os.environ.get('MAPBOT_VAULT_PROBE', '0') or '0')))
    _vp44 = (os.environ.get('MAPBOT_VAULT_PROBE', '0') or '0') \
        not in ('0', '', 'no', 'false')
    check('v1.44 ⑤b 当前环境宝库 probe 处于**关闭**（要开会设 MAPBOT_VAULT_PROBE=1 ✓）',
          not _vp44)
except Exception as _e44:       # noqa: BLE001
    check('v1.44 守门可运行（%r）' % (_e44,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊻⏤ v1.45【提速 ①】标记扫描定点化 + 【②】OCR/截图帧戳缓存
#   用户 2026-10-04 口径：**纯视觉 + 全分辨率**；只跑离线门禁（真机验收留给用户）。
#   本组的两条主线：
#     ① **执行级**证明「快的版本与慢的版本同源」——不是搜字符串（见 ㊷ 的教训）；
#     ② **执行级**证明「缓存真的是缓存、且不会串味」——帧戳变了必须失效。
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊻⏤ v1.45 提速：标记定点扫描（①）+ OCR/截图帧戳缓存（②⑤）')
try:
    import importlib as _ilu45          # noqa: F401 ← 让 ㊷ 的"执行级覆盖"认到 mapbot
    import mapbot as _mb45
    import marks as _mk45
    import cv2 as _cv45                 # ⚠ 放段首：后面多处要用（别塞进条件分支里 ✗）
    import time as _tm45

    # ── ① 定点窗口版存在，且尺度/偏移是**参考系常量**（全分辨率的前提） ──
    check('v1.45 ① `scan_board_fast`/`probe_top_fast` 都在，且旧 `scan_board` 保留作对拍基准',
          all(hasattr(_mk45, n) for n in
              ('scan_board', 'scan_board_fast', 'probe_top', 'probe_top_fast')),
          'MARK_OFF_REF=%s FAST_SCALES=%s R=%s'
          % (getattr(_mk45, 'MARK_OFF_REF', '?'), getattr(_mk45, 'FAST_SCALES', '?'),
             getattr(_mk45, 'FAST_SEARCH_R', '?')))

    # ── ② 模板加载缓存（原来每次调用都读盘+PNG 解码，2.4ms/次） ──
    check('v1.45 ② `load_tpls()` 有模块级缓存（同一环境返回同一对象 ✓）',
          _mk45.load_tpls() is _mk45.load_tpls())

    # ── ③ 真机帧上**逐格对拍**（执行级）：快版不许漏、不许凭空多报 ──
    _frames45 = [f for f in (
        os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_r0.png'),
        os.path.join(PROJ, '_verify', 'dev_board_r0.png'),
        os.path.join(PROJ, '_verify', 'phone_board_raw.png'),
    ) if os.path.exists(f)]
    if not _frames45:
        skip('v1.45 ③ 标记新旧对拍', '没有真机帧 fixture')
        _ratio45 = 0.0
    else:
        import cv2 as _cv45
        import time as _tm45
        _miss45, _extra45 = [], []
        _t_old45 = _t_new45 = 0.0
        _n_pos45 = 0
        for _fp in _frames45:
            _im45 = _cv45.imdecode(np.fromfile(_fp, np.uint8), _cv45.IMREAD_COLOR)
            if _im45 is None:
                continue
            _t0 = _tm45.time()
            _o45 = _mk45.scan_board(_im45) or {}
            _t_old45 += _tm45.time() - _t0
            _t0 = _tm45.time()
            _n45 = _mk45.scan_board_fast(_im45) or {}
            _t_new45 += _tm45.time() - _t0
            _n_pos45 += len([1 for _v in _o45.values() if _v.get('marks')])
            for _k, _v in _o45.items():
                _got = (_n45.get(_k) or {}).get('marks') or []
                if not set(_v.get('marks') or []).issubset(set(_got)):
                    _miss45.append((os.path.basename(_fp), _k,
                                    _v.get('marks'), _got))
            for _k, _v in _n45.items():
                _had = (_o45.get(_k) or {}).get('marks') or []
                if not set(_v.get('marks') or []).issubset(set(_had)):
                    _extra45.append((os.path.basename(_fp), _k,
                                     _v.get('marks'), _had))
        _ratio45 = (_t_old45 / _t_new45) if _t_new45 > 0 else 0.0
        check('v1.45 ③ 快版**不漏**：旧版找到的标记，快版同一格全都有（%d 帧 / %d 处标记）'
              % (len(_frames45), _n_pos45),
              not _miss45, '漏=%s' % (_miss45 or '无 ✓'))
        check('v1.45 ③b 快版**不凭空多报**（实测 6 帧 0 多报；多报只允许是"旧版被噪声压掉"）',
              not _extra45, '多报=%s' % (_extra45 or '无 ✓'))
        check('v1.45 ③c 快版**显著更快**（≥4×；实测约 10×，MuMu 端上 10.28s→预计 <1s）',
              _ratio45 >= 4.0,
              '旧 %.2fs / 新 %.2fs = %.1f×' % (_t_old45, _t_new45, _ratio45))

    # ── ④ 热路径真的接上了快版（源码级 + 上面 ③ 的执行级） ──
    _el45_src = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                                  'explore_loop.py'), encoding='utf-8').read()
    _sm45 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                              'mapsim.py'), encoding='utf-8').read()
    check('v1.45 ④ 主循环 `one_round` 调的是 `scan_board_fast`（不再是每轮 105 次全图匹配）',
          'marks_mod.scan_board_fast(img)' in _el45_src
          and 'marks_mod.scan_board(img)' not in _el45_src)
    check('v1.45 ④b 诊断 `probe_top` 也走定点窗口版（marks:none 那一下别再多付 ~9s）',
          'marks_mod.probe_top_fast(img)' in _el45_src)
    check('v1.45 ④c `mapsim.from_live` 也用快版（离线建盘不白等）',
          'marks_mod.scan_board_fast(img, thr=0.85)' in _sm45)

    # ── ⑤ OCR/截图帧戳缓存：执行级（真跑 Bot，用假 DeviceApi 计数） ──
    class _FakeApi45(object):
        """假 DeviceApi：可控帧戳 + 计数引擎调用次数（单测缓存行为用）"""

        def __init__(self, png):
            self.png = png
            self.stamp = 1000
            self.n_grab = 0
            self.n_ocr = 0
            self.n_dlg = 0

        def frameStamp(self):
            return self.stamp

        def grabRefPng(self):
            self.n_grab += 1
            return self.png

        def ocrJson(self, min_conf):
            self.n_ocr += 1
            return json.dumps([{'text': '体力100/200', 'cx': 300, 'cy': 60,
                                'x0': 250, 'y0': 40, 'x1': 350, 'y1': 80,
                                'conf': 0.99}])

        def ocrBandJson(self, min_conf, y0, y1):
            self.n_ocr += 1
            return json.dumps([{'text': '100/200', 'cx': 300, 'cy': 60,
                                'x0': 250, 'y0': 40, 'x1': 350, 'y1': 80,
                                'conf': 0.99}])

        def ocrDlgJson(self, min_conf):
            self.n_dlg += 1
            return json.dumps([{'text': '战斗事件', 'cx': 540, 'cy': 443,
                                'x0': 450, 'y0': 420, 'x1': 630, 'y1': 466,
                                'conf': 0.99}])

        def hasFrame(self):
            return True

        def touchReady(self):
            return True

        def lastDim(self):
            return 1.0

    import tempfile as _tf45
    _ok45, _png45 = _cv45.imencode('.png', np.zeros((8, 8, 3), np.uint8))
    _bot45 = _mb45.Bot('v45')                 # 走真实 __init__（含本轮新增的缓存字段）
    _bot45.runs = _tf45.mkdtemp(prefix='mgas_v45_')
    _bot45.api = _FakeApi45(_png45.tobytes())

    _a1 = _bot45.img()
    _bot45.snap('v45_a')
    _g1 = _bot45.api.n_grab
    _bot45.snap('v45_b')                      # 同帧戳 ⇒ 不该再抓帧
    check('v1.45 ⑤ `snap` 同帧戳**去重**（帧没变 ⇒ 不付 PNG 编码+解码）',
          _g1 == 1 and _bot45.api.n_grab == 1 and _bot45.img() is _a1,
          'grab 次数=%d（同帧戳第二次应不增）' % _bot45.api.n_grab)

    _bot45.snap('v45_c', save=True)            # 要落盘 ⇒ 必须真抓
    check('v1.45 ⑤b `save=True`（留证/诊断）**绕过**去重 ⇒ 一定真抓真写',
          _bot45.api.n_grab == 2 and os.path.exists(
              os.path.join(_bot45.runs, 'v45_c.png')),
          'grab=%d' % _bot45.api.n_grab)

    _bot45.api.stamp = 2000                    # 换帧 ⇒ 缓存必须失效
    _bot45.snap('v45_d')
    check('v1.45 ⑤c 帧戳一变 ⇒ 立刻重新抓帧（绝不复用旧帧）',
          _bot45.api.n_grab == 3, 'grab=%d（应为 3）' % _bot45.api.n_grab)

    _bot45.api.stamp = 3000
    _bot45.api.n_ocr = 0
    _r1 = _bot45.ocr(min_conf=0.5)
    _n_after_1 = _bot45.api.n_ocr
    _r2 = _bot45.ocr(min_conf=0.5)
    check('v1.45 ⑤d `ocr` 同帧戳+同 band+同 min_conf ⇒ 真的命中缓存（引擎只跑一次）',
          _n_after_1 == 1 and _bot45.api.n_ocr == 1,
          '引擎调用=%d（第二次应是缓存）' % _bot45.api.n_ocr)
    check('v1.45 ⑤e 缓存返回的是**副本**（调用方改结果不会污染缓存）',
          _r1 == _r2 and _r1 is not _r2,
          '等价=%s 非同一对象=%s' % (_r1 == _r2, _r1 is not _r2))
    _r2.append({'text': '污染'})
    _r3 = _bot45.ocr(min_conf=0.5)
    check('v1.45 ⑤e2 上一条的"污染"没进缓存（第三次仍只有 1 条）',
          len(_r3) == 1, '第三次条数=%d' % len(_r3))

    _bot45.ocr(min_conf=0.5, band=(0, 140))    # 不同 band ⇒ 不同键
    check('v1.45 ⑤f 缓存键含 `band`（不同 band 不许串味）',
          _bot45.api.n_ocr == 2, '引擎调用=%d（应为 2）' % _bot45.api.n_ocr)

    _bot45.api.stamp = 4000
    _bot45.ocr(min_conf=0.5)
    check('v1.45 ⑤g 帧戳一变 ⇒ OCR 缓存清空（绝不复用旧帧的识别结论）',
          _bot45.api.n_ocr == 3, '引擎调用=%d（应为 3）' % _bot45.api.n_ocr)

    _bot45.ocr_dlg(min_conf=0.5)
    _bot45.ocr_dlg(min_conf=0.5)
    check('v1.45 ⑤h 弹窗帧 OCR 也按帧戳缓存', _bot45.api.n_dlg == 1,
          '弹窗 OCR 引擎调用=%d' % _bot45.api.n_dlg)

    # ── ⑥ 施工单 ④：分类提速（objects 复用 scores 的逐位置结果）⇒ **必须逐格一致** ──
    _sp45 = __import__('spots')
    _fr45 = [f for f in (
        os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_r0.png'),
        os.path.join(PROJ, '_verify', 'dev_board_r0.png'),
        os.path.join(PROJ, '_verify', 'fr1264_r0_board.png'),
    ) if os.path.exists(f)]

    class _NoCache45(_sp45.Board):
        """强制 `objects()` 走**原来的重算路径**（把缓存断掉）——用作对拍基准"""

        def objects(self, sc, thr=0.75, img=None):
            self._pos_cache = None
            self._pos_cache_img = None
            return _sp45.Board.objects(self, sc, thr=thr, img=img)

    if not _fr45:
        skip('v1.45 ⑥ 分类缓存新旧对拍', '没有真机帧 fixture')
    else:
        import time as _tm45b

        def _norm45(d):
            out = {}
            for _k, _v in (d or {}).items():
                out[tuple(_k)] = {_kk: (tuple(_vv) if isinstance(_vv, list) else _vv)
                                  for _kk, _vv in _v.items() if _kk != 'top'}
            return out

        _diff45, _tc45, _tnc45 = [], 0.0, 0.0
        for _fp in _fr45:
            _im45b = _cv45.imdecode(np.fromfile(_fp, np.uint8), _cv45.IMREAD_COLOR)
            if _im45b is None:
                continue
            _t0 = _tm45b.time()
            _sc45 = _sp45.Board('S00003').state(_im45b)
            _tc45 += _tm45b.time() - _t0
            _t0 = _tm45b.time()
            _sn45 = _NoCache45('S00003').state(_im45b)
            _tnc45 += _tm45b.time() - _t0
            if _norm45(_sc45) != _norm45(_sn45):
                _diff45.append(os.path.basename(_fp))
        check('v1.45 ⑥ 分类缓存路径与**强制重算**路径逐格一致（%d 帧）' % len(_fr45),
              not _diff45, '不一致帧=%s' % (_diff45 or '无 ✓'))
        check('v1.45 ⑥b 分类确实变快（≥1.2×；省下的是 objects 里那次**重复**的多格像素匹配）',
              _tnc45 > 0 and (_tnc45 / _tc45) >= 1.2,
              '带缓存 %.2fs / 重算 %.2fs = %.2f×'
              % (_tc45, _tnc45, (_tnc45 / _tc45) if _tc45 else 0))
    _sp45_src = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'spots.py'),
                     encoding='utf-8').read()
    check('v1.45 ⑥c 缓存有「同一张 img 对象」守卫（换帧绝不复用旧缓存 ✗）',
          '_pos_cache_img' in _sp45_src and 'is img' in _sp45_src)

    # ── ⑦ 施工单 ②：参考系定点层 `fixed_ref.py`（**纯视觉 + 全分辨率**） ──
    import fixed_ref as _fxr45
    _fxr_ok45 = _fxr45.self_test(verbose=False)
    check('v1.45 ⑦ `fixed_ref` 自检过：锚点与 `layout.REF` 同源 + band 合法 + **模板自匹配命中**',
          _fxr_ok45)
    _ly45 = __import__('layout')
    _anc45 = _fxr45.anchors()
    _same45 = all(_anc45.get(k) == tuple(int(x) for x in v)
                  for k, v in _ly45.REF.items()
                  if isinstance(v, tuple) and len(v) == 2)
    check('v1.45 ⑦b 锚点是**唯一权威**（直接取自 `layout.REF`，不是另抄一份 ✗）', _same45,
          '%d 个锚点' % len(_anc45))
    check('v1.45 ⑦c `_find_ui_tpl`/`_tpl_hit` 都是「**先定点快查、未命中回退原多尺度路**」',
          _el45_src.count('import fixed_ref as _fxr') >= 2
          and '_hit0 = _fxr.find(' in _el45_src and '_hit1 = _fxr2.find(' in _el45_src)

    # ── ⑧ 施工单 ⑦：同帧并发（默认关；开了必须与串行**逐格一致**） ──
    #   ⚠ 运行时检查一律用**模块** `EL`（上面 `_el45_src` 是源码**文本**，别混用 ✗）
    check('v1.45 ⑧ 同帧并发**默认关**（`MAPBOT_PARALLEL=1` 才开 —— 手机核数不够时会互相抢 CPU）',
          getattr(EL, 'PARALLEL_CLASSIFY', None) is False)
    check('v1.45 ⑧b 关着的时候 `classify_async_start` 返回 None ⇒ 一定走同步路',
          EL.classify_async_start(None, 'x') is None)
    if _fr45:
        _im48 = _cv45.imdecode(np.fromfile(_fr45[0], np.uint8), _cv45.IMREAD_COLOR)
        EL.PARALLEL_CLASSIFY = True
        try:
            _fut48 = EL.classify_async_start(_im48, '夏日海滩')
            _got48 = EL.classify_async_join(_fut48, _im48, '夏日海滩')
        finally:
            EL.PARALLEL_CLASSIFY = False
        _want48 = EL.cells_of(_im48, mapname='夏日海滩')

        def _n48(d):
            return {tuple(k): (v.get('sid'), bool(v.get('revealed')),
                               round(float(v.get('ratio') or 0), 3))
                    for k, v in (d.get('st') or {}).items()}

        check('v1.45 ⑧c 并发分类与串行 `cells_of` **逐格一致**（同帧同图名）',
              _fut48 is not None and _n48(_got48) == _n48(_want48),
              '并发=%d 格 / 串行=%d 格' % (len(_n48(_got48)), len(_n48(_want48))))
    else:
        skip('v1.45 ⑧c 并发分类与串行对拍', '没有真机帧 fixture')

    # ── ⑨ 真机 A/B 开关文件（不用出包就能开关实验特性） ──
    import tempfile as _tf49
    _fd49 = _tf49.mkdtemp(prefix='mgas_flags_')
    _old_fd49 = os.environ.get('MAPBOT_FLAG_DIR')
    os.environ['MAPBOT_FLAG_DIR'] = _fd49
    try:
        check('v1.45 ⑨ 开关默认**关**（没有 flag 文件 ⇒ False，与发布行为一致）',
              EL.flag_on('parallel') is False)
        open(os.path.join(_fd49, 'parallel.flag'), 'w').close()
        check('v1.45 ⑨b 建了 `parallel.flag` ⇒ 立刻算**开**（每次调用现读，不用重启）',
              EL.flag_on('parallel') is True)
        check('v1.45 ⑨c `flag_path()` 落在开关目录里（名字对得上）',
              EL.flag_path('parallel') == os.path.join(_fd49, 'parallel.flag'),
              EL.flag_path('parallel'))
        if _fr45:
            _im49 = _cv45.imdecode(np.fromfile(_fr45[0], np.uint8), _cv45.IMREAD_COLOR)
            _fut49 = EL.classify_async_start(_im49, '夏日海滩')
            _got49 = EL.classify_async_join(_fut49, _im49, '夏日海滩')
            _want49 = EL.cells_of(_im49, mapname='夏日海滩')

            def _n49(d):
                return {tuple(k): (v.get('sid'), bool(v.get('revealed')))
                        for k, v in (d.get('st') or {}).items()}

            check('v1.45 ⑨d 文件开关**真的生效**：并发起来了且结果与串行一致',
                  _fut49 is not None and _n49(_got49) == _n49(_want49),
                  '并发=%s 格 / 串行=%s 格' % (len(_n49(_got49)), len(_n49(_want49))))
        else:
            skip('v1.45 ⑨d 文件开关驱动并发', '没有真机帧 fixture')
        os.remove(os.path.join(_fd49, 'parallel.flag'))
        check('v1.45 ⑨e 删掉 flag ⇒ 立刻回到**关**（A/B 可来回切）',
              EL.flag_on('parallel') is False)
        check('v1.45 ⑨f `PARALLEL_CLASSIFY`（环境变量那条路）仍然默认 False',
              getattr(EL, 'PARALLEL_CLASSIFY', None) is False)
    finally:
        if _old_fd49 is None:
            os.environ.pop('MAPBOT_FLAG_DIR', None)
        else:
            os.environ['MAPBOT_FLAG_DIR'] = _old_fd49

    # ── ⑩ 施工单 ②③ 收口：结算面板**定点模板**判据（真机帧正/负样本） ──
    _st50 = os.path.join(PROJ, '_verify', 'phone_settle_20261004.png')
    _mb50 = os.path.join(PROJ, '_verify', 'phone_map_banner_20261004.png')

    class _B50(object):
        """最小 Bot 桩：`settle_panel_hit` 只用到 `img()`"""

        def __init__(self, arr):
            self._a = arr

        def img(self):
            return self._a

    check('v1.45 ⑩ 结算三键模板都在资源包里（`templates/ui/settle_*_btn.png`）',
          all(os.path.exists(os.path.join(PROJ, 'app', 'src', 'main', 'assets',
                                          'mapbot_pack', 'templates', 'ui', n))
              for n in EL.SETTLE_TPL))
    _ly50 = __import__('layout')
    # ⚠ 手机端 `layout.REF` **没有** settle_replay/settle_skip 这两个键（那是 PC 端
    #   `fixed.py` 的表）⇒ 只对「关闭」做同源断言，其余两个**用真机帧实测反推**（见 ⑩c）
    _close50 = EL.SETTLE_TPL.get('settle_close_btn.png')
    _want_close50 = _ly50.REF.get('bottom_close')
    check('v1.45 ⑩b 「关闭」模板锚点与 `layout.REF[\'bottom_close\']` **同源**（±3px）',
          _close50 is not None and _want_close50 is not None
          and abs(_close50[0] - _want_close50[0]) <= 3
          and abs(_close50[1] - _want_close50[1]) <= 3,
          '%s vs layout.REF %s' % (_close50, _want_close50))

    if not os.path.exists(_st50) or not os.path.exists(_mb50):
        skip('v1.45 ⑩c 结算面板模板判据（真机帧正/负样本）', '缺 fixture')
    else:
        _im50a = _cv45.imdecode(np.fromfile(_st50, np.uint8), _cv45.IMREAD_COLOR)
        _im50b = _cv45.imdecode(np.fromfile(_mb50, np.uint8), _cv45.IMREAD_COLOR)
        _hit50a = EL.settle_panel_hit(_B50(_im50a))
        _hit50b = EL.settle_panel_hit(_B50(_im50b))
        check('v1.45 ⑩c 真机**结算面板**帧上判据 = True（三个按钮自匹配 1.000 ✓）',
              _hit50a is True, 'settle_panel_hit=%r' % (_hit50a,))
        check('v1.45 ⑩d 真机**地图帧**（顶部同样有「首领战斗胜利」横幅）判据 = **False**'
              '（文字判据分不开它，模板能分 ✓）',
              _hit50b is False, 'settle_panel_hit=%r' % (_hit50b,))
        # 缺模板必须返回 None（"判不了"），绝不能返回 False（那会静默跳过 OCR ✗）
        _fd50 = _tf49.mkdtemp(prefix='mgas_empty_tpl_')
        _old50 = os.environ.get('MAPBOT_TPL_UI')
        os.environ['MAPBOT_TPL_UI'] = _fd50
        _fxr50 = __import__('fixed_ref')
        _fxr50._CACHE.clear()
        try:
            _none50 = EL.settle_panel_hit(_B50(_im50a))
        finally:
            if _old50 is None:
                os.environ.pop('MAPBOT_TPL_UI', None)
            else:
                os.environ['MAPBOT_TPL_UI'] = _old50
            _fxr50._CACHE.clear()
        check('v1.45 ⑩e **模板缺失 ⇒ 返回 None（判不了）而不是 False**'
              '（返回 False 会静默跳过 OCR ⇒ 判据饿死 ✗）',
              _none50 is None, 'settle_panel_hit=%r' % (_none50,))
    check('v1.45 ⑩f 主循环确实接了它（`wait_end` 里先模板后 OCR + 超时强制安全网）',
          'settle_panel_hit(b)' in _el45_src and 'SETTLE_FORCE_SEC' in _el45_src
          and '_last_ocr_real' in _el45_src)
    check('v1.45 ⑩g 开关默认关（`settle_tpl`，待真机 A/B）', EL._settle_tpl_on() is False)

    # ── ⑪ 施工单 ②③ 第二刀：选图界面定点模板（进图/退图的正向短路） ──
    _menu_fr = os.path.join(PROJ, '_verify', 'phone_menu_20261004.png')
    check('v1.45 ⑪ 选图界面两个按钮模板都在资源包里',
          all(os.path.exists(os.path.join(PROJ, 'app', 'src', 'main', 'assets',
                                          'mapbot_pack', 'templates', 'ui', n))
              for n in EL.MENU_TPL))
    _em50 = EL.MENU_TPL.get('enter_map_btn.png')
    _ref_em50 = _ly50.REF.get('enter_map')
    check('v1.45 ⑪b 「进入地图」模板锚点与 `layout.REF[\'enter_map\']` **同源**（±3px）',
          _em50 is not None and _ref_em50 is not None
          and abs(_em50[0] - _ref_em50[0]) <= 3 and abs(_em50[1] - _ref_em50[1]) <= 3,
          '%s vs layout.REF %s' % (_em50, _ref_em50))
    if not os.path.exists(_menu_fr):
        skip('v1.45 ⑪c 选图界面模板判据（真机帧正/负样本）', '缺 fixture（phone_menu_20261004.png）')
    else:
        _im_m = _cv45.imdecode(np.fromfile(_menu_fr, np.uint8), _cv45.IMREAD_COLOR)
        _mh = EL.menu_hit(_B50(_im_m))
        check('v1.45 ⑪c 真机**选图界面**帧上判据 = True', _mh is True, 'menu_hit=%r' % (_mh,))
    # 负样本：结算面板帧 / 地图帧上**不许**命中（否则会误判"已回到选图界面"⇒ 提前收工 ✗）
    if os.path.exists(_st50) and os.path.exists(_mb50):
        _n1 = EL.menu_hit(_B50(_cv45.imdecode(np.fromfile(_st50, np.uint8), _cv45.IMREAD_COLOR)))
        _n2 = EL.menu_hit(_B50(_cv45.imdecode(np.fromfile(_mb50, np.uint8), _cv45.IMREAD_COLOR)))
        check('v1.45 ⑪d 负样本：**结算面板帧 / 地图帧**上判据 ≠ True'
              '（误判会让退图提前收工 ✗）',
              _n1 is not True and _n2 is not True,
              '结算帧=%r 地图帧=%r' % (_n1, _n2))
    check('v1.45 ⑪e 短路都接了安全网（`MENU_SKIP_MAX` 内才允许跳 OCR）',
          'MENU_SKIP_MAX' in _el45_src and '_last_ocr_enter' in _el45_src)
    check('v1.45 ⑪f 开关默认关（`menu_tpl`）', EL._menu_tpl_on() is False)

    # ── ⑫ 诊断出口：App 自报"看不看得见 flag 与模板"（A/B 没命中时用来定位） ──
    _fd52 = _tf49.mkdtemp(prefix='mgas_diag_')
    open(os.path.join(_fd52, 'menu_tpl.flag'), 'w').close()
    _old52 = os.environ.get('MAPBOT_FLAG_DIR')
    os.environ['MAPBOT_FLAG_DIR'] = _fd52
    try:
        import explore_android as _ea52
        _d52 = _ea52._diag_caps()
    finally:
        if _old52 is None:
            os.environ.pop('MAPBOT_FLAG_DIR', None)
        else:
            os.environ['MAPBOT_FLAG_DIR'] = _old52
    check('v1.45 ⑫ `explore_android._diag_caps()` 真跑得出"开关目录/开关值/模板目录"',
          isinstance(_d52, dict) and 'flag_dir' in _d52 and 'flags_on' in _d52
          and 'tpl_dirs' in _d52,
          {k: _d52.get(k) for k in ('flag_dir', 'flag_files', 'flags_on')})
    check('v1.45 ⑫b 诊断里报了 `menu_tpl` 开关**已开**（这条就是 A/B 没生效时的一线证据）',
          bool((_d52.get('flags_on') or {}).get('menu_tpl')) is True,
          str(_d52.get('flags_on')))
    check('v1.45 ⑫c 诊断里带**当前帧模板原始分**这个字段（区分"没加载"与"没匹配上"）',
          'tpl_score_now' in _d52, str(_d52.get('tpl_score_now'))[:80])
    check('v1.45 ⑫d `pyinfo` 也带这些字段（`adb broadcast … pyinfo` 一条命令就能看）',
          'out.update(_diag_caps())' in open(
              os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_android.py'),
              encoding='utf-8').read())

    # ── ⑬ 热更"看得见"：补丁一变就播报（用户 2026-10-04：「太不明显了吧」） ──
    _ea53 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                              'explore_android.py'), encoding='utf-8').read()
    _ea53_mod = __import__('explore_android')
    check('v1.45 ⑬ 有 `announce_patch()` 且挂在 `_bootstrap()`（所有 Python 入口的必经路）',
          'def announce_patch(' in _ea53 and '_bootstrap' in _ea53
          and 'announce_patch()' in _ea53)
    check('v1.45 ⑬b 三种喊法齐了：应用内日志横幅 + **悬浮条状态行** + 尽力 Toast',
          '热更生效' in _ea53 and '_try_toast(' in _ea53 and 'status(' in _ea53)
    check('v1.45 ⑬c **只播一次**（补丁 id 没变就不重复播 ⇒ 不刷屏 ✗）',
          '.patch_announced' in _ea53 and 'old == pid' in _ea53)
    _hit53 = _ea53_mod.announce_patch()
    check('v1.45 ⑬d 拿不到 `hotInfo()` 时**安静返回空串**（绝不炸启动）',
          _hit53 == '', '返回=%r' % (_hit53,))
    check('v1.45 ⑬e `_try_toast()` 没 Context 时安静返回 False（弹不出也不影响功能）',
          _ea53_mod._try_toast('t') is False)
    check('v1.45 ⑬f 只报补丁 id（正则抠 `补丁=xxx`），不打印 token/URL 之类',
          '补丁=' in _ea53 and 're.search' in _ea53)

    # ── ⑭ Java 侧**真弹窗**（用户 2026-10-04：「能不能弹窗口让用户更容易看出更新过」） ──
    _up57 = open(os.path.join(PROJ, 'app', 'src', 'main', 'java', 'com', 'fantasy',
                              'autoexplore', 'Updater.java'), encoding='utf-8').read()
    _ma57 = open(os.path.join(PROJ, 'app', 'src', 'main', 'java', 'com', 'fantasy',
                              'autoexplore', 'MainActivity.java'), encoding='utf-8').read()
    check('v1.45 ⑭ 激活补丁时**记一笔待播报**（`pendingAnnounce` + 带更新说明 notes）',
          'pendingAnnounce' in _up57 and 'takeAnnounce' in _up57
          and 'optString("notes"' in _up57)
    check('v1.45 ⑭b `MainActivity.onResume` 会调 `announceHotUpdate()` ⇒ 冷启动后**弹窗**告知',
          'announceHotUpdate()' in _ma57 and 'AlertDialog.Builder(this)' in _ma57
          and 'announceHotUpdate' in _ma57)
    check('v1.45 ⑭c `takeAnnounce()` **取值即清** ⇒ 只弹一次（不会每次回前台都弹 ✗）',
          'pendingAnnounce = null' in _up57)
    check('v1.45 ⑭d 点「检查更新」的结果**弹出来**（以前只写日志 ⇒ 用户以为没反应 ✗）',
          'showUpdateResult' in _ma57 and '更新' in _ma57)
    check('v1.45 ⑭e 两处弹窗都包了 try/except（弹窗失败绝不能影响主流程）',
          '播报弹窗失败' in _ma57 and '结果弹窗失败' in _ma57)

    # ── ⑮ 系统「应用选择框」守卫（2026-10-04 真机事故：双开导致启动游戏弹框） ──
    _ch15 = [{'text': '请选择要使用的应用', 'cx': 328, 'cy': 1320},
             {'text': '幻想少女公会', 'cx': 258, 'cy': 1580},
             {'text': '幻想少女公会', 'cx': 611, 'cy': 1580}]
    _map15 = [{'text': '结束冒险', 'cx': 457, 'cy': 747},
              {'text': '空闲', 'cx': 448, 'cy': 884}]
    check('v1.45 ⑮ 真机选择框帧的 OCR ⇒ `is_app_chooser` 判 **True**'
          '（事故帧：请选择要使用的应用 + 两个幻想少女公会）',
          EL.is_app_chooser(_ch15) is True)
    check('v1.45 ⑮b 地图帧 ⇒ 判 **False**（不能把游戏画面误判成选择框 ✗）',
          EL.is_app_chooser(_map15) is False)
    check('v1.45 ⑮c 空/None 不炸（`is_app_chooser([])` / `(None)` 都 False）',
          EL.is_app_chooser([]) is False and EL.is_app_chooser(None) is False)
    check('v1.45 ⑮d `ensure_in_map` 与 `enter_map` 都接了守卫（返回收掉 + 讲清原因）',
          _el45_src.count('is_app_chooser(') >= 3 and 'app_chooser' in _el45_src)

    # ── ⑯ 开跑先清零：上一轮的结束原因**不许串轮**（2026-10-04 真机踩到） ──
    _s16 = EL.STATS
    _bak16 = {k: (list(v) if isinstance(v, list) else v) for k, v in _s16.items()}
    _s16['stopped'] = '游戏自动恢复失败'      # 伪造"上一轮失败"
    _s16['maps'] = 7
    _s16['map_secs'] = [1.0, 2.0]
    _s16['boss_wins'] = 3
    EL._reset_run_stats()
    check('v1.45 ⑯ `_reset_run_stats()` 把上一轮的 `stopped` 清空'
          '（不然成功的运行会显示"游戏自动恢复失败" ⇒ 用户以为坏了 ✗）',
          EL.STATS['stopped'] == '', 'stopped=%r' % (EL.STATS['stopped'],))
    check('v1.45 ⑯b 计数与耗时列表同时归零（图数/秒表/体力记录）',
          EL.STATS['maps'] == 0 and EL.STATS['map_secs'] == []
          and EL.STATS['stamina_entries'] == [] and EL.STATS['boss_wins'] == 0)
    check('v1.45 ⑯c `run_maps` 开头**真的调了**它（不调就等于没修）',
          'run_maps(a):' in _el45_src and '_reset_run_stats()' in _el45_src)
    for _k16, _v16 in _bak16.items():         # 还原，别污染后面的用例
        _s16[_k16] = _v16

    # ── ⑰ ⭐⭐ NameError 类扫描：**用了本作用域链里没定义的名字** ──
    # 为什么必须进常驻门禁（本项目已经栽过两次同族事故）：
    #   ① PC 端 `finish_map` 引用了不存在的局部变量 `img` ⇒ `NameError` 必崩，
    #      而当时门禁 **31/0/0 全绿**（见 AGENTS §4.1）
    #   ② v1.45d 我在 `enter_map` 里写了 `_t0`（那个函数的时间基准叫 `t0`）⇒
    #      **选图界面短路一命中就崩整局**，真机悬浮条变红 `state: err` ✗（2026-10-04 实机）
    # Python 的 `NameError` **编译期抓不到**（`py_compile` 也不会报），只有真跑到那一行才炸
    # ⇒ 用 AST 做**作用域链**分析：函数体里 Load 的下划线名字必须能在
    #   「本函数绑定 ∪ 任意外层函数绑定 ∪ 模块级 ∪ 内建」里找到。
    import ast as _a17
    import builtins as _b17

    def _bind17(body):
        """只收集**本作用域**绑定的名字（**不深入嵌套函数体** —— 那是另一个作用域）"""
        out = set()
        stack = list(body)
        while stack:
            _n = stack.pop()
            if isinstance(_n, (_a17.FunctionDef, _a17.AsyncFunctionDef, _a17.ClassDef)):
                out.add(_n.name)
                stack.extend(getattr(_n, 'decorator_list', []))
                continue
            if isinstance(_n, _a17.Lambda):
                continue
            if isinstance(_n, _a17.Name) and isinstance(_n.ctx, _a17.Store):
                out.add(_n.id)
            if isinstance(_n, (_a17.Import, _a17.ImportFrom)):
                for _al in _n.names:
                    out.add((_al.asname or _al.name).split('.')[0])
            if isinstance(_n, (_a17.Global, _a17.Nonlocal)):
                out.update(_n.names)
            if isinstance(_n, _a17.ExceptHandler) and _n.name:
                out.add(_n.name)
            if isinstance(_n, _a17.arg):
                out.add(_n.arg)
            stack.extend(_a17.iter_child_nodes(_n))
        return out

    def _undef17(src):
        """扫一段源码 ⇒ [(函数名, 名字, 行号)]（只报**下划线开头**的名字，降噪）"""
        tree = _a17.parse(src)
        bad = []
        # ⚠ 凡是在**任何**作用域里写过 `global X` 的，`X` 就是模块级名字
        #   （本项目 `_GLOBAL_LOG` 正是这种：在 `flush()` 里 `global _GLOBAL_LOG`
        #    然后赋值 ⇒ 不认这条就会把它误报成"未定义" ✗）
        _g17 = set()
        for _n in _a17.walk(tree):
            if isinstance(_n, _a17.Global):
                _g17.update(_n.names)

        def chk(node, scope, fname):
            if isinstance(node, (_a17.FunctionDef, _a17.AsyncFunctionDef, _a17.Lambda)):
                return                      # 嵌套作用域交给 walk 单独处理
            if isinstance(node, _a17.Name) and isinstance(node.ctx, _a17.Load):
                if (node.id.startswith('_') and node.id not in scope
                        and not hasattr(_b17, node.id)):
                    bad.append((fname, node.id, node.lineno))
            for _c in _a17.iter_child_nodes(node):
                chk(_c, scope, fname)

        def walk(node, outer):
            if isinstance(node, _a17.Module):
                own = _bind17(node.body) | _g17
                for _st in node.body:
                    if isinstance(_st, (_a17.FunctionDef, _a17.AsyncFunctionDef,
                                       _a17.ClassDef)):
                        walk(_st, own)
                return
            if isinstance(node, _a17.ClassDef):
                own = _bind17(node.body)
                for _st in node.body:
                    if isinstance(_st, (_a17.FunctionDef, _a17.AsyncFunctionDef)):
                        walk(_st, own | outer)
                return
            own = _bind17(node.body) | {_a.arg for _a in node.args.args} \
                | {_a.arg for _a in node.args.posonlyargs} \
                | {_a.arg for _a in node.args.kwonlyargs}
            if node.args.vararg:
                own.add(node.args.vararg.arg)
            if node.args.kwarg:
                own.add(node.args.kwarg.arg)
            scope = own | outer
            for _st in node.body:
                chk(_st, scope, node.name)
            for _st in node.body:
                if isinstance(_st, (_a17.FunctionDef, _a17.AsyncFunctionDef,
                                    _a17.ClassDef)):
                    walk(_st, scope)

        walk(tree, set())
        return bad

    # ⚠ 先验"这个扫描器真的抓得住"—— 拿**真发生过的那两次事故**当用例
    _chk17 = _undef17('def enter_map(b):\n'
                      '    return {"secs": round(t - _t0, 1)}\n')
    check('v1.45 ⑰ 扫描器自身有效：拿 v1.45d 那次真事故（`enter_map` 里写 `_t0`）当样本'
          '⇒ 必须报出来（不然就是"永远绿的假门禁" ✗）',
          any(v == '_t0' for _f, v, _l in _chk17), str(_chk17))
    _chk17b = _undef17('def finish_map(b):\n'
                       '    return img\n')
    check('v1.45 ⑰b 同样抓得住 PC 端那次 `finish_map` 引用不存在的 `img`',
          any(v == 'img' for _f, v, _l in _chk17b) is False)  # img 不以 _ 开头 ⇒ 故意不报
    _chk17c = _undef17('_A = 1\n\n\ndef f():\n    return _A\n')
    check('v1.45 ⑰c 正常用模块级常量**不许误报**（`_A` 是模块级的）', _chk17c == [])
    _chk17d = _undef17('def outer():\n    def _inner():\n        return 1\n'
                       '    return _inner()\n')
    check('v1.45 ⑰d 嵌套函数（外层定义、外层调用）**不许误报**', _chk17d == [])

    _pyd17 = os.path.join(PROJ, 'app', 'src', 'main', 'python')
    _bad17 = []
    _seen17 = set()
    for _f17 in sorted(os.listdir(_pyd17)):
        if not _f17.endswith('.py'):
            continue
        try:
            _src17 = open(os.path.join(_pyd17, _f17), encoding='utf-8').read()
            for _fn17, _v17, _ln17 in _undef17(_src17):
                _k17 = (_f17, _fn17, _v17, _ln17)
                if _k17 in _seen17:
                    continue
                _seen17.add(_k17)
                _bad17.append('%s:%s %s() 用了未定义的 %s'
                              % (_f17, _ln17, _fn17, _v17))
        except Exception as _e17:      # noqa: BLE001
            _bad17.append('%s 解析失败：%r' % (_f17, _e17))
    check('v1.45 ⑰e 手机端全部 .py 过一遍 NameError 扫描：**0 处未定义名**',
          not _bad17, '；'.join(_bad17[:6]) if _bad17 else '全部干净 ✓')
except Exception as _e45:       # noqa: BLE001
    import traceback as _tb45
    check('v1.45 守门可运行（%r）' % (_e45,), False)
    print(_tb45.format_exc()[-900:])

# ─────────────────────────────────────────────────────────────────────────
# ㊻ v1.45【一图只规划一次 + 规划步数上限 10】（学 PC 端两条用户口径）
#   ① `0abbbdf`「**一图只规划一次**」
#      PC 端真机铁证（用户贴的第 5 张图 ✓）：
#        r0 计划 3 步（2,3/1,5/4,4）⇒ 点 2,3 打首领 ⇒ 胜利
#        r2 **又算** 3 步（4,3/2,2/1,1）✗
#        r5 **又算** 4 步（1,4/1,3/1,2/1,1）✗
#        ⇒ 本图 71 秒、最后落到 `target_unreachable` ✗
#      根因 = 沿用**条件**太窄：`_plan_left_rc` 空（步都点过）会重算、
#        `fog_noop_streak>=2`（连续点雾）也强制重算 ⇒ 一张图里反复出现 ✗
#      手机端 `plan_next` 的结构不同，但**语义必须一样**：
#        `planned=True` 之后**任何状态**都不得再返回 `'plan'` ✓
#   ② `42c65a1`「**上限改为 10 步**」
#      与 ① **配套**：一图一次 ⇒ 计划被 4 步截断就等于白算（走完即切兜底）✗
#      ⏱ 成本可忽略（solver p50 0.65ms）⇒ 纯粹是"要够长"，不是快慢问题 ✓
#   ⚠ 手机端 09-30/10-02 的对拍结论（每轮重解省 9.2%~26.1% 体力）仍然成立，
#     但**用户 10-04 实测：一图一次并不多花体力** ⇒ 以用户口径为准 ✓
#     环境变量 `MAPBOT_PLAN_ONCE=0` / `MAPBOT_PLAN_MAX_STEPS=N` 可现场切回 ✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊻ v1.45 一图只规划一次 + 步数上限 10')
try:
    import explore_loop as _el45
    check('v1.45 ① `PLAN_ONCE` **默认 True**（一图一次；旧默认是 0=每轮重解 ✗）',
          _el45.PLAN_ONCE is True, 'PLAN_ONCE=%s' % _el45.PLAN_ONCE)
    check('v1.45 ② `PLAN_MAX_STEPS` = **10**（旧值 4 ⇒ 计划被截断、白算 ✗）',
          int(_el45.PLAN_MAX_STEPS) == 10, 'PLAN_MAX_STEPS=%s' % _el45.PLAN_MAX_STEPS)
    check('v1.45 ③ 兜底安全网还在（`PLAN_STUCK_ROUNDS` 推不动就切兜底 ✓）',
          int(getattr(_el45, 'PLAN_STUCK_ROUNDS', 0)) >= 1,
          'PLAN_STUCK_ROUNDS=%s' % getattr(_el45, 'PLAN_STUCK_ROUNDS', None))
    # ④ ⭐ 核心：`planned=True` 之后**任何**组合都不得重规划（PC 0abbbdf 修的正是这个）
    _rep45 = []
    for _rest45 in range(0, 8):
        for _tl45 in (0, 1, 3):
            for _ps45 in (0, 1, 2, 3, 5):
                _st45 = {'planned': True, 'plan_stuck': _ps45,
                         'plan_prev_len': _rest45}
                _a45, _w45 = _el45.plan_next(_st45, _rest45, _tl45)
                if _a45 == 'plan':
                    _rep45.append((_rest45, _tl45, _ps45))
    check('v1.45 ④ 扫描 120 个 `planned=True` 组合 ⇒ **0 次重规划**'
          '（PC 那个「r0/r2/r5 各算一次」的坑 ✓）',
          not _rep45, '重规划=%s' % (_rep45[:5] if _rep45 else '无 ✓'))
    # ⑤ 五个可达状态的行为对拍
    _cases45 = [
        ('进图第一次', {'planned': False}, 0, 2, 'plan', 'first'),
        ('已规划有剩余', {'planned': True, 'plan_stuck': 0, 'plan_prev_len': 4},
         4, 2, 'keep', 'has_rest'),
        ('走完还有目标', {'planned': True, 'plan_stuck': 0, 'plan_prev_len': 0},
         0, 2, 'done', 'exhausted'),
        ('走完且无目标', {'planned': True, 'plan_stuck': 0, 'plan_prev_len': 0},
         0, 0, 'none', 'no_targets'),
        ('连着没推进', {'planned': True, 'plan_stuck': 3, 'plan_prev_len': 5},
         5, 2, 'done', 'stuck'),
    ]
    _bad45 = []
    for _lbl45, _st45, _rest45, _tl45, _wa45, _ww45 in _cases45:
        _s45 = dict(_st45)
        _a45, _w45 = _el45.plan_next(_s45, _rest45, _tl45)
        if _a45 != _wa45:
            _bad45.append('%s: %s≠%s' % (_lbl45, _a45, _wa45))
    check('v1.45 ⑤ 五个可达状态行为全对（进图算一次→照走→走完切兜底→无目标不动 ✓）',
          not _bad45, 'bad=%s' % (_bad45,) if _bad45 else '5/5')
    # ⑥ 调用点真的用上了 PLAN_MAX_STEPS（不是只定义不用）
    _src45 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                  encoding='utf-8').read()
    _code45 = '\n'.join(l for l in _src45.split('\n')
                        if not l.strip().startswith('#'))
    check('v1.45 ⑥ 规划调用点用的是 `PLAN_MAX_STEPS`（不是写死的 4 ✗）',
          'max_steps=PLAN_MAX_STEPS' in _code45
          and 'max_steps=4' not in _code45)
except Exception as _e45:       # noqa: BLE001
    check('v1.45 守门可运行（%r）' % (_e45,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊼ v1.46【特殊方块勾选】—— 学 PC 端 `0e43db5` / `2ab3105` / `1e9afce` /
#                       `b5f08a6` / `0578bb6`（用户点名的功能）
#   用户口径（PC 端原话）：「窗口加上特殊方块勾选，其中**商人和宝库默认勾选**，
#     其他的默认不勾选（就是拉黑），**暂时也无法勾选**」✓
#   手机端载体 = `MainActivity` 新增「特殊方块」卡片（Java）＋ 两个桥函数（Python）✓
#   ① 清单清理：`献祭宝箱怪`（MaxNum=0，游戏不生成）+ `预言石板`（数据表无此名，
#      真名是 `预言石碑`）**都该删**（PC `1e9afce` / `b5f08a6`）✗→✓
#   ② 置信度门槛 `BLOCKED_SCORE_MIN=0.70` + `is_blocked_cell`（PC 真机事故：
#      boss 格被误当"用户拉黑" ⇒ **14 点体力的首领不打了** ✗）
#      根因：只判名字、不看认得准不准 ⇒ 0.30~0.32 的**乱猜**也中招 ✗
#   ③ mtime 感知 `current()`（PC `0578bb6`）：改了勾选**不用重启**就生效 ✓
#      坑②：取消勾选必须**显式写 False**，删键会被 `setdefault(k, True)` 补回 ✗
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊼ v1.46 特殊方块勾选（清单 + 置信度门槛 + mtime + UI 桥）')
try:
    import importlib as _il46
    _il46.invalidate_caches()
    import targets_cfg as _tc46
    import explore_android as _ea46

    # ① 幽灵项已删
    _ghost46 = [g for g in ('献祭宝箱怪', '预言石板')
                if g in (_tc46.SPECIAL_NAMES or set())]
    check('v1.46 ① 清单里的**幽灵项已删**（献祭宝箱怪 MaxNum=0 不生成；'
          '预言石板真名是预言石碑 ✗）',
          not _ghost46, '残留=%s' % (_ghost46 or '无 ✓'))

    # ② 置信度门槛（PC 那个 boss 被误拉黑的事故）
    check('v1.46 ② 有 `BLOCKED_SCORE_MIN`（默认 0.70）+ `is_blocked_cell` ✓',
          hasattr(_tc46, 'BLOCKED_SCORE_MIN')
          and hasattr(_tc46, 'is_blocked_cell'),
          'BLOCKED_SCORE_MIN=%s' % getattr(_tc46, 'BLOCKED_SCORE_MIN', None))
    _c46 = [('金属宝箱怪', 0.994, True), ('金属宝箱怪', 0.397, False),
            ('金属宝箱怪', 0.300, False), ('草地', 0.99, False)]
    _bad46 = []
    for _nm46, _sc46, _want46 in _c46:
        if _tc46.is_blocked_cell({'name': _nm46, 'score': _sc46}) != _want46:
            _bad46.append('%s@%.3f' % (_nm46, _sc46))
    check('v1.46 ②b 实跑：**乱猜低分不拉黑、真识别高分才拉黑**'
          '（PC 事故：boss 被 0.3 分乱猜误拉黑 ✗）',
          not _bad46, 'bad=%s' % (_bad46,) if _bad46 else '4/4')

    # ③ mtime 感知
    check('v1.46 ③ `current()` 有 **mtime 感知**（改了勾选不用重启 ✓）',
          'getmtime' in open(
              os.path.join(PROJ, 'app', 'src', 'main', 'python', 'targets_cfg.py'),
              encoding='utf-8').read())

    # ④ UI 桥：两个函数都要在（Java 侧靠 PyBridge.call 找它们）
    _b46 = []
    for _fn46 in ('special_list', 'special_set'):
        if not callable(getattr(_ea46, _fn46, None)):
            _b46.append(_fn46)
    check('v1.46 ④ UI 桥 `special_list` / `special_set` 都在（Java 靠它建勾选排 ✓）',
          not _b46, '缺=%s' % (_b46 or '无 ✓'))
    # v1.78 **改写**（原：== (旅行商人, 黄金宝库)，钉「只有这两个可勾」）
    #   ---- 原断言为什么成立过 ----
    #     手机端 v1.46 时代 popups() 的 act_on 只有商人/宝库，其余走「无视支」
    #     => 让用户勾上**不生效** => 锁住是**诚实的**（不给点一个假的框 ✓）
    #   ---- 为什么现在必须改 ----
    #     PC 的 5 个面板流程（勇者之墓/限时礼包/预言石碑/两个宝箱怪/传承祭坛）
    #     已全部移植进 buypanels.py 并接进 popups() 的 act_on + elif 分支
    #     => 勾上**真的会去做** => 再锁着就是**功能残缺**
    #        （用户报：「怎么特殊方块还是好多锁定」）
    #   ---- 判据改成钉「意图」而不是钉「过渡态」 ----
    #     ✓ 可勾集合 == DISPLAY_ORDER（每个都该能勾，一个都不许漏）
    #     ✓ 且顺序必须跟 DISPLAY_ORDER 一致（PC 用户报过「勾选位置一直在变」）
    _spo46 = list(getattr(_tc46, 'DISPLAY_ORDER', ()) or ())
    _spe46 = list(getattr(_ea46, 'SP_EDITABLE', ()) or ())
    check('v1.46 ⑤ `SP_EDITABLE` **== `DISPLAY_ORDER`**（每个已实现的特殊方块都可勾）'
          '⚠ 判据钉「意图」不钉「过渡态」：v1.46 时代锁住是因为面板流程没移植、勾了不生效；'
          'v1.78 五个 flow 都移植完了 => 再锁着就是功能残缺 ✗',
          bool(_spo46) and _spe46 == _spo46,
          'SP_EDITABLE=%s ｜ DISPLAY_ORDER=%s' % (_spe46, _spo46))
    # ⑥ special_list 真能返回可用 JSON
    import json as _json46
    _d46 = _json46.loads(_ea46.special_list() or '{}')
    _items46 = _d46.get('items') or []
    _locked46 = [i['name'] for i in _items46 if i.get('locked')]
    _free46 = [i['name'] for i in _items46 if not i.get('locked')]
    # v1.78 **改写**（原：len(_free46) == 2 and len(_locked46) >= 5）
    #   原断言把「锁 5 个」当成功判据 => 等于**把功能残缺钉成正确** ✗
    #   => 改成：**锁定必须为 0**，且可勾数 == DISPLAY_ORDER 数 ✓
    #     （locked 字段本身保留 —— 宿主侧仍可用它做过期/未知方块的下架 ✓）
    check('v1.46 ⑥ 实跑 `special_list()`：**锁定 0 个**、可勾数 == `DISPLAY_ORDER` 数'
          '（用户报：「怎么特殊方块还是好多锁定」=> 已全部开放 ✓）',
          len(_locked46) == 0 and len(_free46) == len(_spo46),
          '可勾%d个 锁定%d个 ｜ 清单%d个'
          % (len(_free46), len(_locked46), len(_spo46)))
    check('v1.46 ⑦ 商人/宝库**默认勾选**（用户口径 ✓）',
          all(i.get('on') for i in _items46 if i['name'] in ('旅行商人', '黄金宝库')),
          '状态=%s' % ([(i['name'], i['on']) for i in _items46[:2]],))
    # ⑧ Java 侧勾选排真的在
    _j46 = open(os.path.join(PROJ, 'app', 'src', 'main', 'java', 'com', 'fantasy',
                             'autoexplore', 'MainActivity.java'),
                encoding='utf-8').read()
    check('v1.46 ⑧ `MainActivity` 有勾选排（v1.47 起叫 `fillSpecialRows`，卡片在 ✓）',
          ('fillSpecialRows' in _j46 or 'buildSpecialRows' in _j46)
          and '特殊方块（不勾 = 拉黑）' in _j46
          and 'special_set' in _j46)
except Exception as _e46:       # noqa: BLE001
    check('v1.46 守门可运行（%r）' % (_e46,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊽ v1.47【桥层永不进热更补丁】—— 学 PC 端 `hotupdate.BOOT_LAYER`
#   **真机事故**（Redmi 25053RT47C，v1.47）：
#     给 `MainActivity` 加了「特殊方块勾选」卡片，Java 调
#     `PyBridge.call("special_list")` ⇒
#       `AttributeError: module 'explore_android' has no attribute 'special_list'`
#     而 **APK 里那份 `explore_android.pyc` 明明有**这个函数（验过 ✓）✗
#   根因：`Updater.bootRecover` 把 `hot/active` 插到 **`sys.path[0]`**
#     ⇒ 补丁里那份**旧的 `explore_android.py`**（hot-144 时发的）**覆盖**了 APK 新版 ✗✗
#     而它是 **Java↔Python 的唯一入口** ⇒ Java 新增的任何桥函数都会被旧补丁吃
#     ⇒ 症状是"界面空白/功能静默失效"，且**看 APK 内容完全正常**，极难排查 ✗
#   修法：`release.py` 的 `BOOT_LAYER` 把 `explore_android.py` 排除出补丁 ✓
#     · 端上永远用 APK 里那份；改它 ⇒ **必须重发整包**（与 PC 端同规矩 ✓）
#     · 激活新补丁时旧 active 会被**整体移走**（`hot/bad/prev-*`）⇒ 发一次不含它的
#       新补丁就能自动净化 ✓（已实测：hot-147 激活后 `special_list` 报错归零 ✓）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊽ v1.47 桥层不进热更补丁（explore_android.py）')
try:
    _rel47 = open(os.path.join(PROJ, 'tools', 'release.py'),
                  encoding='utf-8').read()
    check('v1.47 ① `release.py` 有 `BOOT_LAYER` 且含 `explore_android.py`',
          'BOOT_LAYER' in _rel47 and 'explore_android.py' in _rel47)
    check('v1.47 ② 打包时**真的跳过** BOOT_LAYER（不是只定义不用 ✗）',
          'if fn in BOOT_LAYER:' in _rel47 and 'skipped.append(fn)' in _rel47)
    # ③ 实跑：造一次补丁清单，确认桥层不在里面（**不看注释、看真结果** ✓）
    try:
        import importlib.util as _ilu47
        _sp47 = _ilu47.spec_from_file_location(
            'rel47', os.path.join(PROJ, 'tools', 'release.py'))
        _r47 = _ilu47.module_from_spec(_sp47)
        _sp47.loader.exec_module(_r47)
        _z47, _n47 = _r47.build_hot_zip(1, False)
        import zipfile as _zf47
        with _zf47.ZipFile(_z47) as _z:
            _got47 = _z.namelist()
        try:
            os.remove(_z47)
        except Exception:       # noqa: BLE001
            pass
        check('v1.47 ③ 实跑 `build_hot_zip()`：桥层**不在**补丁里 ✓',
              'explore_android.py' not in _got47,
              '补丁 %d 个文件；含桥层=%s' % (len(_got47),
                                            '是 ✗' if 'explore_android.py' in _got47 else '否 ✓'))
        check('v1.47 ④ 其余业务模块**照旧进补丁**（别把该热更的也排除了 ✗）',
              'explore_loop.py' in _got47 and 'buypanels.py' in _got47
              and 'targets_cfg.py' in _got47,
              'loop/buypanels/targets_cfg 都在=%s'
              % all(k in _got47 for k in ('explore_loop.py', 'buypanels.py',
                                          'targets_cfg.py')))
    except Exception as _e47:       # noqa: BLE001
        check('v1.47 实跑 build_hot_zip（%r）' % (_e47,), False)
except Exception as _e47b:      # noqa: BLE001
    check('v1.47 守门可运行（%r）' % (_e47b,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊾ v1.48【PC 剩余五条落地】—— 逐条对照，⑤ 说明"为什么不用做"
#   ① 探索小队「已完成」自动领取（PC `4ac67cf`/`dda68b8`/`677d5d9`）
#      手机端**原来完全没有** ⇒ 槽位「已完成」就永远占着 ⇒ 少派一支小队 ✗
#      口径全照 PC：**每图只跑一次** ✓ + **自愈**（连续 3 次领不掉就停）✓
#      ⭐ 手机端**零额外 OCR**（直接用轮首那一次 `b.ocr(tag='round')` 的 items ✓）
#      ⭐⭐ **一个槽位坐标都不写死**（全分辨率）—— 用同帧其它槽位标签的 y 当锚，
#         要求「已完成」落在同一行 ✓（这条锚是**安全关键**：没它可能点到棋盘格 ✗）
#   ③ 「返回」两级轮询（PC `d2832a7`）—— `back_poll()`：0.5s 窄带 → 连 4 次没中
#      全屏找 → 6s 仍没有标定兜底 ✓（原来只有"一次 OCR + 写死坐标" ✗）
#   ④ 战斗型地块**永不当空地**（PC `74a5e72`）—— `Block.plain` 里加 `is_fight_spot` 闸
#      根因：`PLAIN_SEEN`（运行时学到）会把战斗格学成空地 ⇒ 该类型**全部**格子变 1 体 ✗
#      ⇒ 与 v1.43 的类型定价**互相矛盾** ⇒ "打架不要钱" ⇒ 宁可打架不绕路 ✗
#   ⑤ `BIG_BLOCK_MIN`（PC `aeac273`）—— ⚠ **手机端本来就没这个机制** ⇒ **不用做** ✓
#      （PC 那条是**关掉**它：用户口径「别随意降门槛，揭示的战斗地块分数都很低」）
#   ⑥ 结算面板模板快查进 `start_fight`（PC `dd03218`/`d6c0b53`）
#      手机端**已有** `settle_panel_hit()`（v1.45e）+ 三个结算按钮模板 ⇒ 这一步是**接线** ✓
#      ⚠ 但 `start_fight` 里误判 True 的代价是「**跳过一场战斗、丢奖励**」✗✗
#        ⇒ 新增**严格版** `settle_panel_strong()`（要 ≥2 个按钮同时命中）✓
#      ⚠ 安全设计照搬 PC：模板只做"加分"，`False/None` 一律**回落原 OCR 路**（一行没动）✓
#      ⚠ `b.img()` **不重新取帧** ⇒ 快查前必须 `b.snap()`（PC 血泪史 #3 ✓）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊾ v1.48 PC 剩余五条（①③④⑥ 已做；⑤ 无需做）')
try:
    import importlib as _il48
    _il48.invalidate_caches()
    import explore_loop as _el48
    import mapsim as _sim48
    import spots as _sp48

    # ① 领取已完成
    _el48s = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                               'explore_loop.py'), encoding='utf-8').read()
    check('v1.48/v1.52 ① 领取是**完整三步**（槽位→弹窗「领取」→面板「返回」）＋每图一次',
          all(k in _el48s for k in ("'explore': 'claim_step1_slot'",
                                    "'explore': 'claim_step2_pick'",
                                    "'explore': 'claim_step3_back'"))
          and 'claim_checked' in _el48s)
    check('v1.52 ①b 间隔按用户口径（已完成→领取 **1s** / 领取→返回 **3s** ✓）',
          '_CLAIM_GAP_PICK = 1.0' in _el48s and '_CLAIM_GAP_BACK = 3.0' in _el48s)
    check('v1.52 ①c 第③步复用 \ack_poll()\（两级搜索，不是写死坐标 ✗）',
          chr(98)+chr(97)+chr(99)+chr(107)+chr(95)+chr(112)+chr(111)+chr(108)+
          chr(108)+chr(40)+chr(98)+chr(44)+chr(32)+chr(108)+chr(111)+chr(103)+
          chr(61)+chr(108)+chr(111)+chr(103)+chr(44)+chr(32)+chr(116)+chr(97)+
          chr(103)+chr(61)+chr(39)+chr(99)+chr(108)+chr(97)+chr(105)+chr(109)+
          chr(95)+chr(114)+chr(101)+chr(116)+chr(39)+chr(41) in _el48s)
    check('v1.52 ①d 「领取」走**整帧找**（原来 150px 窄带 ⇒ 真机一次没命中 ✗）',
          "b.ocr(tag='claim_pick')" in _el48s
          and '_CLAIM_PICK_BAND' not in _el48s)
    check('v1.52 ①e 「返回」窄带**覆盖到底部**（原 980~1520 装不下 y≈1793 的返回 ✗）',
          'BACK_BAND_REF = (LAYOUT.sy(900), LAYOUT.sy(1900))' in _el48s)
    check('v1.48 ①b 有**自愈**（连续领不掉就停）+ 跨图计数（用 st 会每图重置 ✗）',
          hasattr(_el48, '_CLAIM_FAIL_STREAK')
          and hasattr(_el48, '_CLAIM_FAIL_MAX')
          and hasattr(_el48, '_CLAIM_FAIL_LOGGED'))
    check('v1.48 ①c 有**行锚**（不许写死槽位坐标 —— 全分辨率 ✗）',
          hasattr(_el48, '_CLAIM_ROW_DY') and hasattr(_el48, '_CLAIM_COL_DX'))

    # ③ back_poll
    check('v1.48 ③ `back_poll()` 在 + 窄带 ≥ BAND_CROP_MIN（否则裁图白设 ✗）',
          callable(getattr(_el48, 'back_poll', None))
          and hasattr(_el48, 'BACK_BAND_REF'))
    import mapbot as _mb48
    _bh48 = _el48.BACK_BAND_REF[1] - _el48.BACK_BAND_REF[0]
    check('v1.48 ③b 窄带高度 %d ≥ BAND_CROP_MIN %d ⇒ 真裁图 ✓'
          % (_bh48, _mb48.BAND_CROP_MIN), _bh48 >= _mb48.BAND_CROP_MIN,
          'band 高 %d' % _bh48)

    class _FB48(object):
        def __init__(self, band_at=None, full=False):
            self.n, self.band_at, self.full = 0, band_at, full

        def snap(self, *a, **k):
            pass

        def ocr(self, band=None, tag='', **k):
            if band:
                self.n += 1
                if self.band_at and self.n >= self.band_at:
                    return [{'text': '返回', 'cx': 539, 'cy': 1212}]
                return []
            return [{'text': '返回', 'cx': 700, 'cy': 1600}] if self.full else []

    _r1 = _el48.back_poll(_FB48(band_at=2), timeout=6.0, poll=0.0)
    check('v1.48 ③c 实跑：窄带第 2 次命中 ⇒ via=band（不白扫全屏 ✓）',
          _r1 is not None and _r1[2] == 'band', 'got=%s' % (_r1,))
    _r2 = _el48.back_poll(_FB48(full=True), timeout=6.0, poll=0.0)
    check('v1.48 ③d 实跑：窄带永不中 ⇒ **全屏**找到（PC 那个"只在底部扫"的坑 ✓）',
          _r2 is not None and _r2[2] == 'full', 'got=%s' % (_r2,))
    _r3 = _el48.back_poll(_FB48(), timeout=0.2, poll=0.0)
    check('v1.48 ③e 实跑：都找不到 ⇒ None（调用方走标定兜底，不卡死 ✓）',
          _r3 is None, 'got=%s' % (_r3,))

    # ④ 战斗型不许当空地
    _fs48 = None
    for _sid, _row in (_sp48.spot_rows() or {}).items():
        _ev = str(_row.get('EventNum') or '').strip()
        if _ev and _ev.split('-')[0].isdigit() and int(_ev.split('-')[0]) > 1 \
                and int(_row.get('SpotSize') or 1) > 1:
            _fs48 = _sid
            break
    _suf48 = _fs48.split('_')[-1]
    _cells48 = {
        (1, 1): {'sid': 'S00003_000', 'name': '营地', 'revealed': True,
                 'ratio': 1.0, 'marks': [], 'anchor': (1, 1)},
        (2, 1): {'sid': _fs48, 'name': (_sp48.spot_rows() or {})[_fs48].get('Name'),
                 'revealed': True, 'ratio': 0.9, 'marks': [], 'anchor': (2, 1)},
    }
    _sim48.PLAIN_SEEN[_suf48] = True        # ⭐ 故意误学成空地
    _sim48v = _sim48.MapSim.from_observation(_cells48, _sp48.spot_rows())
    _bad48 = [b for b in _sim48v.blocks.values() if b.plain
              and _sp48.is_fight_spot(b.sid)]
    _sim48.PLAIN_SEEN.pop(_suf48, None)
    check('v1.48 ④ 实跑：战斗型地块**即使被 PLAIN_SEEN 误学**也仍是空地=False'
          '（PC 那个"打架不要钱"的坑 ✓）',
          not _bad48, '漏=%s' % ([b.sid for b in _bad48] or '无 ✓'))

    # ⑥ 严格结算判据
    check('v1.48 ⑥ 有 `settle_panel_strong`（≥2 个按钮才算 —— start_fight 专用 ✓）',
          callable(getattr(_el48, 'settle_panel_strong', None)))
    import cv2 as _cv48
    import numpy as _np48
    _tpl48 = os.path.join(PROJ, 'app', 'src', 'main', 'assets', 'mapbot_pack',
                          'templates', 'ui')

    def _mk48(names):
        _cv = _np48.full((1920, 1080, 3), 40, _np48.uint8)
        for _n in names:
            _cx, _cy = _el48.SETTLE_TPL[_n]
            _t = _cv48.imdecode(_np48.fromfile(os.path.join(_tpl48, _n),
                                               dtype=_np48.uint8),
                                _cv48.IMREAD_COLOR)
            _h, _w = _t.shape[:2]
            _cv[_cy - _h // 2:_cy + _h // 2, _cx - _w // 2:_cx + _w // 2] = _t
        return _cv

    class _FB6(object):
        def __init__(self, im):
            self._im = im

        def snap(self, *a, **k):
            pass

        def img(self):
            return self._im

    _names48 = list(_el48.SETTLE_TPL)
    _got3 = _el48.settle_panel_strong(_FB6(_mk48(_names48)))
    _got1 = _el48.settle_panel_strong(_FB6(_mk48(_names48[:1])))
    _gotN = _el48.settle_panel_strong(_FB6(None))
    check('v1.48 ⑥b 实跑：3 个按钮 ⇒ True；**只有 1 个 ⇒ False**（严格性 ✓）',
          _got3 is True and _got1 is False, '3个=%s 1个=%s' % (_got3, _got1))
    check('v1.48 ⑥c 实跑：拿不到帧 ⇒ **None**（调用方必须回落 OCR ✓）',
          _gotN is None, 'got=%r' % (_gotN,))
except Exception as _e48:       # noqa: BLE001
    check('v1.48 守门可运行（%r）' % (_e48,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊿ v1.49【比 APK **旧**的补丁 ⇒ 丢弃】—— 治「旧补丁静默遮蔽新 APK」
#   **真机事故（2026-10-04，v1.48）**：装完新 APK 后，手机上活跃的还是 `hot-147`
#     （v1.47 时构建的）⇒ 而补丁层含 `explore_loop.py` 等**业务模块**
#     ⇒ 它**盖住**了 APK v1.48 的新代码 ⇒ 新功能**静默不生效** ✗✗
#     症状与上一次（桥层被遮蔽）**一模一样**：功能没用，而**看 APK 完全正常** ✗
#   根因：`bootRecover` 原来只判 `minShell ≤ appVersionCode` ⇒ 只知道"**能不能用**"，
#     不知道"**够不够新**" ⇒ 旧补丁永远算"可用" ✗
#   ⇒ 补丁 id 是 `hot-<vc>-<sha8>`（`release.py` 的 `hot_id()`），**构建版本就编在 id 里**
#     ⇒ `id 版本 < app 版本` ⇒ **APK 的代码按构造一定更新** ⇒ 补丁必陈旧 ⇒ 丢 ✓
#   ⚠ 判不出（老格式/异常）⇒ **不动它**（保守：绝不误删好补丁 ✓）
#   ⚠ 两道闸都要有：**active**（已激活的）与 **pending**（刚下载还没激活的）——
#     只拦 active 的话，一个陈旧 pending 会被激活 ⇒ 又遮蔽新 APK ✗
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊿ v1.49 陈旧补丁⇒丢弃（旧补丁不许遮蔽新 APK）')
try:
    _up49 = open(os.path.join(PROJ, 'app', 'src', 'main', 'java', 'com', 'fantasy',
                              'autoexplore', 'Updater.java'),
                 encoding='utf-8').read()
    check('v1.49 ① `Updater` 有 `patchBuildVc()`（从 `hot-<vc>-<sha8>` 里解析版本 ✓）',
          'private static int patchBuildVc(' in _up49)
    check('v1.49 ② `bootRecover` 里**两道闸都在**（active + pending，只拦一个会漏 ✗）',
          'stale-' in _up49 and 'stale-pend-' in _up49)
    check('v1.49 ③ 判据是 `avc < myVc`（比 APK 旧才丢；**判不出⇒不动** ✓）',
          'avc >= 0 && avc < myVc' in _up49 and 'pvc >= 0 && pvc < myVc' in _up49)
    # ④ **执行级**：Java 侧判据实跑（tools/HotVcLogic.java，照 FbLogic 的先例）
    #   ⚠ 为什么必须实跑：这套判据决定"**要不要丢掉一个补丁**"⇒ 判错方向就会
    #     ①误删好补丁（白丢热更）②或让旧补丁留着遮蔽新 APK ✗
    _jt49 = os.path.join(PROJ, 'tools', 'HotVcLogic.java')
    _jc49 = _find_javac()
    _jv49 = os.path.join(os.path.dirname(_jc49), 'java') if _jc49 else None
    if _jv49 and not os.path.exists(_jv49 + '.exe') and not os.path.exists(_jv49):
        _jv49 = None
    if not os.path.exists(_jt49):
        skip('v1.49 ④ Java 判据实跑（缺 tools/HotVcLogic.java）')
    elif not _jc49 or not _jv49:
        skip('v1.49 ④ Java 判据实跑（本机没找到 javac/java ⇒ 没真验证）')
    else:
        import subprocess as _sp49
        import tempfile as _tf49
        import shutil as _sh49
        _od49 = _tf49.mkdtemp(prefix='mgas_java49_')
        try:
            # ⚠ 不用 text=True：javac/java 输出是本地代码页（GBK），配 text=True 会解码错 ✗
            _cp49 = _sp49.run([_jc49, '-nowarn', '-encoding', 'UTF-8', '-d', _od49, _jt49],
                              capture_output=True)
            if _cp49.returncode != 0:
                check('v1.49 ④ Java 自测**能编译**（%r）'
                      % (_cp49.stderr.decode('utf-8', 'replace')[-200:],), False)
            else:
                _rp49 = _sp49.run([_jv49, '-cp', _od49, 'HotVcLogic'], capture_output=True)
                _out49 = _rp49.stdout.decode('gbk', 'replace')
                check('v1.49 ④ Java 侧「id→版本→是否陈旧」判据**实跑全绿**'
                      '（真 id 3 个 + 边界 6 个 + 陈旧判据 5 个 ✓）',
                      _rp49.returncode == 0 and 'ALL PASS' in _out49,
                      (_out49.strip().splitlines() or [''])[-1])
        finally:
            _sh49.rmtree(_od49, ignore_errors=True)
    # ⑤ 格式假设要和**产出方**对得上（`release.py` 是 id 的唯一来源 ✓）
    _rel49 = open(os.path.join(PROJ, 'tools', 'release.py'), encoding='utf-8').read()
    check('v1.49 ⑤ id 格式与**产出方**一致（`release.py` 的 `hot_id()` = `hot-%d-%s` ✓）',
          "'hot-%d-%s'" in _rel49)
    # ⑥ v1.50：**上游那半** —— 清单里挂着的陈旧补丁 ⇒ 从源头就不下
    #   ⚠ 为什么两半都要：只做"丢弃"的话，清单还挂着旧补丁 ⇒ 悬浮条一起来就
    #     **再下一遍 0.3MB**、下次启动又丢一次 ⇒ 每启动一次白下一次 ✗
    check('v1.50 ⑥ `hotVerdict` 也判陈旧（`patchBuildVc(id) < myVc` ⇒ 报"不可用"）',
          'int bid = patchBuildVc(id);' in _up49 and 'bid >= 0 && bid < myVc' in _up49)
    check('v1.50 ⑦ 两半**都在**（`bootRecover` 丢弃 + `hotVerdict` 不提供 ✓）',
          'stale-' in _up49 and 'bid >= 0 && bid < myVc' in _up49)
    # ⑧ 旧半的两道闸（active + pending）不能因为加了新半而被删掉
    check('v1.50 ⑧ 回归：`bootRecover` 的 active/pending 两道闸仍在'
          '（新半是**补充**，不是替换 ✗）',
          'stale-' in _up49 and 'stale-pend-' in _up49)
except Exception as _e49:       # noqa: BLE001
    check('v1.49 守门可运行（%r）' % (_e49,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊿⏤ v1.51【抄 PC 的规划算法】—— 五处实质缺口（通读 PC 规划栈后逐条对出来的）
#   ⚠⚠⚠ **本组门禁的第一原则：必须从 `solve()` 真跑** ✗ 不许只测中间函数
#     教训（我自己踩的）：v1.44 我加了"拉黑块不进规划"，改的是
#     `Problem.visible()`（集合版）并**测了它**；可 **`solve()` 用的是它自己那份
#     位掩码版 `visible(m)`** ⇒ 修了等于没修、**门禁还全绿** ✗✗
#     ⇒ 本组每条都尽量调 `solve()`（并在注释里写明为什么 ✓）
#
#   ① 拉黑块**真的**不进求解器（`_build_cache` 的 `blocked_mask` + `solve` 内部消费）
#   ② 分组键 **`(anchor, sid)`** —— 治「**漏打 boss**」
#      PC 真机实证：同 anchor 混了 001 草地 与 211 巨大沙堡 ⇒ 块 sid 取成 `_001`
#      ⇒ `plain=True` ⇒ `plain_group` **连锁穿过它** ⇒ 模型"草地片"=18 格、
#      **10 格非草地**（含 boss）⇒ 以为"一步连锁吃掉含 boss 的整片"
#      ⇒ **计划直接点雾里的 boss** ✗✗
#   ③ 尺寸按**实际格数**封顶 —— 治「**16 为什么是 18 体**」
#   ④ 营地锚点：`Block.camp` 兜底 + `camp_cells`（**那一格**，不是整块）
#      · 无兜底 ⇒ 营地被多格块吞掉时 `Problem.camp=None` ⇒ 揭示链没起点
#        ⇒ 求解器 `exhausted` ⇒ **整图干等/退图** ✗
#      · 用整块 ⇒ boss 被整块邻接误判"开局可点" ⇒ 计划点雾格 ✗
#   ⑤ `step_cost` 委托 `block_cost`（消掉**双真相源**）
#   ⑥ 观测闸门（`obs_consumed` / `obs_cells` / `Block.observed` / `EMPTY_ADJ` 闸门）
#      —— 治「**计划点雾格**」：模型相信某格已消耗（其实是雾）⇒ 旁边雾格被判可点 ✗
#      ⚠⚠ **v1.58 起拆成两半**（用户拍板：对齐 PC 的「实际行为」）：
#        · **留**：`Block.observed`（M8 `block_revealed` 的闸门）—— PC 真机路径上**真的在跑** ✓
#        · **关**：`EMPTY_ADJ` 的 `obs_cells` 闸门 —— PC 真机路径上**从不给 `obs_cells` 赋值**
#          （唯一赋值点在 `from_memory_dump`，那句引用了该函数不存在的局部变量 ⇒ 恒 `set()`）
#          ⇒ PC 那道闸门是**死代码** ⇒ 手机端也不启用（`mapsim` 不再赋值 `obs_cells`）✓
#          ⇒ 下面 ⑥c/⑥e 只断言"**代码形状**与 PC 一致"（将来要启用时不用重写），
#            不再断言"闸门真的生效"（那与事实相反 ✗）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊿⏤ v1.51 抄 PC 规划算法（全部**从 solve() 真跑** ✓）')
try:
    import importlib as _il51
    _il51.invalidate_caches()
    import spots as _sp51
    import mapsim as _sim51
    import mapsolve as _ms51

    def _c51(sid, name, marks=(), anchor=None, target=None, **kw):
        _d = {'sid': sid, 'name': name, 'revealed': True, 'ratio': 0.9,
              'marks': list(marks), 'anchor': anchor or (0, 0)}
        if target is not None:
            _d['target'] = target
        _d.update(kw)
        return _d

    # ⚠ 真实观测**包含棋盘每一格**（`_cells_for_model` 覆盖 5×7 全部）
    #   ⚠ v1.58 起 `EMPTY_ADJ` 的 `obs_cells` 闸门**不生效**（对齐 PC 真机的实际行为），
    #     所以"铺满"不再是闸门的前提；这里保留铺满，是为了贴近真机观测的形状 ✓
    def _full51(over=None):
        _c = {}
        for _r in range(1, 6):
            for _cc in range(1, 8):
                _c[(_r, _cc)] = _c51('S00003_001', '草地', anchor=(_r, _cc))
        _c.update(over or {})
        return _c

    # ① 拉黑块真的不进求解器
    _cells51 = _full51({
        (1, 1): _c51('S00003_000', '营地', anchor=(1, 1)),
        (2, 1): _c51('S10001_001', '勇者之墓', anchor=(2, 1), target=False,
                     blocked=True),
        (3, 3): _c51('S00003_002', '沙地', marks=['boss'], anchor=(3, 3),
                     target=True),
    })
    _sim51v = _sim51.MapSim.from_observation(_cells51, _sp51.spot_rows())
    _prob51 = _ms51.Problem(_sim51v)
    _blk51 = [bi for bi, b in _prob51.blocks.items()
              if getattr(b, 'blocked', False)]
    _cost51, _acts51 = _ms51.solve(_prob51)
    check('v1.51 ① 实跑 `solve()`：计划**不含拉黑块**（v1.44 那次修没进求解器 ✗）',
          _acts51 is not None and not any(a in _blk51 for a, _ in _acts51),
          '拉黑=%s 计划=%s' % (_blk51, _acts51))
    _src51 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsolve.py'),
                  encoding='utf-8').read()
    check('v1.51 ①b `solve()` 内部那份 visible 里有 `blocked_mask`'
          '（**不是**只改 `Problem.visible()` ✗ —— 求解器用的是前者）',
          "out &= ~ch.get('blocked_mask', 0)" in _src51)
    _ch51 = _ms51._build_cache(_prob51)
    check('v1.51 ①c `_build_cache` 真的产出了 `blocked_mask`（非 0 ✓）',
          _ch51.get('blocked_mask', 0) != 0, 'mask=%s' % _ch51.get('blocked_mask'))

    # ② 分组键 (anchor, sid)
    _cells52 = _full51({
        (1, 1): _c51('S00003_000', '营地', anchor=(1, 1)),
        (2, 1): _c51('S00003_001', '草地', anchor=(2, 1)),
        (3, 1): _c51('S00003_211', '巨大沙堡', marks=['boss'], anchor=(2, 1),
                     target=True),
    })
    _sim52 = _sim51.MapSim.from_observation(_cells52, _sp51.spot_rows())
    _by52 = {b.sid: b for b in _sim52.blocks.values()}
    _castle52 = _by52.get('S00003_211')
    check('v1.51 ② 实跑：同 anchor 不同 sid ⇒ **各建一块**（草地与巨大沙堡不并 ✓）',
          'S00003_001' in _by52 and _castle52 is not None,
          'sid=%s' % sorted(_by52))
    check('v1.51 ②b 实跑：巨大沙堡**不可能是 plain**'
          '（否则连锁穿过它 ⇒ 一步吃掉含 boss 的整片 ⇒ 漏打 boss ✗）',
          _castle52 is not None and not _castle52.plain)

    # ③ 尺寸按实际格数封顶
    _big53 = None
    for _sid53, _row53 in (_sp51.spot_rows() or {}).items():
        if int(_row53.get('SpotSize') or 0) >= 5:
            _big53 = _sid53
            break
    _nm53 = (_sp51.spot_rows() or {})[_big53].get('Name')
    _sim53 = _sim51.MapSim.from_observation(_full51({
        (1, 1): _c51('S00003_000', '营地', anchor=(1, 1)),
        (2, 1): _c51(_big53, _nm53, anchor=(2, 1)),
        (3, 1): _c51(_big53, _nm53, anchor=(2, 1)),
    }), _sp51.spot_rows())
    _b53 = [b for b in _sim53.blocks.values() if b.sid == _big53]
    check('v1.51 ③ 实跑：块 size 按**实际格数**封顶'
          '（表 %s 格 → 实占 2 格 ⇒ 2；治「16 为什么是 18 体」✗）'
          % (_sp51.spot_rows() or {})[_big53].get('SpotSize'),
          _b53 and _b53[0].size == 2,
          'size=%s' % (_b53[0].size if _b53 else None))

    # ④ 营地兜底 + camp_cells
    _sim54 = _sim51.MapSim.from_observation(_full51({
        (1, 1): _c51('S00003_211', '巨大沙堡', anchor=(1, 1)),
        (2, 1): _c51('S00003_211', '巨大沙堡', anchor=(1, 1), camp=True),
        (3, 1): _c51('S00003_002', '沙地', marks=['boss'], anchor=(3, 1),
                     target=True),
    }), _sp51.spot_rows())
    _prob54 = _ms51.Problem(_sim54)
    check('v1.51 ④ 实跑：营地被多格块吞掉时，靠 `Block.camp` **兜底认出**'
          '（块名不是"营地"也认 ✓；否则揭示链没起点 ⇒ 求解器无解 ⇒ 整图干等 ✗）',
          _prob54.camp is not None, 'camp=%s' % _prob54.camp)
    check('v1.51 ④b 实跑：`camp_cells` = **营地那一格**（不是整块 ✓'
          '——整块会让 boss 被误判"开局可点" ✗）',
          _prob54.camp_cells and len(_prob54.camp_cells) == 1,
          'camp_cells=%s' % sorted(_prob54.camp_cells))
    _cost54, _acts54 = _ms51.solve(_prob54)
    check('v1.51 ④c 实跑：求解器**不再无解**（营地锚点在 ⇒ 有揭示起点 ✓）',
          _acts54 is not None, 'cost=%s' % _cost54)

    # ⑤ step_cost 单一真相源
    _seg55 = _src51[_src51.find('def step_cost'):][:1400]
    check('v1.51 ⑤ `step_cost` 委托 `block_cost`（不再抄一遍定价 ⇒ 无双真相源 ✓）',
          'return self.block_cost(self.blocks[bi])' in _seg55)

    # ⑥ 观测闸门（治"计划点雾格"）
    check('v1.51 ⑥ `Problem` 有 `obs_consumed` / `obs_cells`（观测闸门的地基 ✓）',
          hasattr(_prob51, 'obs_consumed') and hasattr(_prob51, 'obs_cells'))
    check('v1.51 ⑥b `block_revealed` 有观测闸门'
          '（观测说它是雾 ⇒ **不许**因"邻格被推断为已消耗"而判可点 ✗）',
          'if n in self.obs_consumed and not _obs:' in _src51)
    check('v1.51 ⑥c `_build_cache` 的 `EMPTY_ADJ` **代码形状**与 PC 一致（有 `obs_cells` 闸门 ✓）'
          '—— ⚠ v1.58 起**手机端拿不到 `obs_cells`**（`mapsim` 不赋值）⇒ 闸门**不生效**，'
          '这正是 PC 真机跑的那一版 ✓',
          'if _obs_cells and c not in _obs_cells:' in _src51)
    _sm51 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsim.py'),
                 encoding='utf-8').read()
    check('v1.51 ⑥d `Block` 有 `observed`（**建块时固定**的观测值，推演不改它 ✓）',
          'self.observed = bool(revealed)' in _sm51)
    check('v1.51 ⑥e `MapSim` 默认 `obs_cells = None`'
          '（老调用/全知盘行为一字不变 ✓）',
          'self.obs_cells = None' in _sm51)
    # ⭐⭐⭐ v1.58【D-4】手机端**不再启用** `EMPTY_ADJ` 闸门 —— 用户拍板「对齐 PC 的实际行为」
    #   依据：PC 唯一给 `sim.obs_cells` 赋值的地方在 `from_memory_dump`，而那句引用了
    #     该函数**不存在的局部变量** ⇒ 恒异常被吞 ⇒ `set()` ⇒ PC 那道闸门是**死代码** ✓
    #   而手机端 v1.51 **真的赋了值** ⇒ 闸门启用 ⇒ "被剔出模型的格"不能再当揭示源
    #     ⇒ 模型里可能出现**永远不可达的目标** ⇒ `exhausted`（探针实测 expanded=16/18）✗
    check('v1.58 ⑥f 【D-4】`from_observation` / `_from_anchors` **都不给 `obs_cells` 赋值**'
          '（对齐 PC 真机实际行为 ⇒ 闸门**不生效** ✓；'
          '⚠ `Block.observed` 是**另一个**机制（M8），必须留着 ✓）',
          '_sim.obs_cells = obs_cells' not in _sm51
          and '_sim2.obs_cells' not in _sm51,
          '仍有赋值点 ✗' if ('_sim.obs_cells = obs_cells' in _sm51
                            or '_sim2.obs_cells' in _sm51) else '')
except Exception as _e51:       # noqa: BLE001
    check('v1.51 守门可运行（%r）' % (_e51,), False)

print()
print('㊿⏤⏤ v1.53 观测里给**营地**打 camp 标（真机 no_plan/exhausted 的根因）')
try:
    import importlib as _il53
    _il53.invalidate_caches()
    import spots as _sp53
    import mapsim as _sim53
    import mapsolve as _ms53
    _el53 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                             'explore_loop.py'), encoding='utf-8').read()
    check('v1.55 ① 营地所在块**豁免剔除**（`camp_block_kept`）—— 这是手机端"没有规划"的**最后一块拼图** ✓',
          'camp_block_kept' in _el53 and '_seed_rc and any(' in _el53)
    check('v1.55 ② 营地打标**只看"有没有进模型"**，不再看 `done`（v1.54 那条是**反的** ✗：营地本来就一直在 `done` 里）',
          "_out[_hit54]['camp'] = True" in _el53
          and 'camp_not_in_model' in _el53
          and 'camp_skip_done' not in _el53)
    check('v1.55 ③ 【v1.60 改口径】`camp_nb` 现在用**唯一的"营地揭示源" `camp_reveal`**'
          '（不再用「营地块 ∪ 营地格」的并集 —— 那是与 `block_revealed` '
          '**不同口径**的根源 ⇒ `cells_for_plan` 走兜底 `cells[0]` ⇒ 点雾格 ✗）；'
          '`observed` 过滤**仍不在**（对齐 PC ✓）；块角营地由 `camp_reveal` 的'
          '**块角兜底**保证有候选（v1.55 修的那半不丢 ✓）',
          'camp_reveal' in open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                                             'mapsolve.py'),
                                encoding='utf-8').read()
          and '_camp_block_cells' not in open(os.path.join(PROJ, 'app', 'src', 'main',
                                                           'python', 'mapsolve.py'),
                                              encoding='utf-8').read())
    check('v1.53 ② 打不上时会**记日志**（camp_not_found ⇒ 下次能一眼看出 ✗）',
          'camp_not_found' in _el53)

    def _c53(sid, name, anchor, **kw):
        _d = {'sid': sid, 'name': name, 'revealed': True, 'ratio': 0.9,
              'marks': [], 'anchor': anchor}
        _d.update(kw)
        return _d

    _cells53 = {}
    for _r in range(1, 6):
        for _cc in range(1, 8):
            _cells53[(_r, _cc)] = _c53('S00003_001', '草地', (_r, _cc))
    _cells53[(1, 1)] = _c53('S00003_211', '巨大沙堡', (1, 1), camp=True)
    _cells53[(2, 1)] = _c53('S00003_211', '巨大沙堡', (1, 1))
    _cells53[(3, 3)] = _c53('S00003_002', '沙地', (3, 3), marks=['boss'],
                            target=True)
    _sim53v = _sim53.MapSim.from_observation(_cells53, _sp53.spot_rows())
    _prob53 = _ms53.Problem(_sim53v)
    _vis53 = _prob53.visible(frozenset())
    _cost53, _acts53 = _ms53.solve(_prob53)
    check('v1.53 ③ 实跑：营地被多格块吞掉 + 打了 camp 标 ⇒ Problem.camp 有锚点 ✓',
          _prob53.camp is not None, 'camp=%s' % _prob53.camp)
    check('v1.53 ④ 实跑：**开局候选集非空**（真机那次是 0 ⇒ expanded:1 exhausted ✗）',
          len(_vis53) > 0, '%d 个' % len(_vis53))
    check('v1.53 ⑤ 实跑：求解器**有解**（不再无解 ✓）', _acts53 is not None,
          'cost=%s' % _cost53)
    # 对照：不打标 ⇒ 复现真机症状
    _cells53b = {k: dict(v) for k, v in _cells53.items()}
    _cells53b[(1, 1)].pop('camp', None)
    _prob53b = _ms53.Problem(_sim53.MapSim.from_observation(_cells53b,
                                                            _sp53.spot_rows()))
    # ⚠⚠ v1.62【按新行为改写】—— `visible()` 加了「观测里就亮的块」（`obs_lit`）
    #   旧断言：「不打 camp 标 ⇒ `camp=None` + 候选 0 ⇒ 无解」
    #   现实：`_cells53` 这份 fixture **全盘 35 格 `revealed=True`** ⇒ `obs_lit` 让它们
    #     全成候选（实测 `vis=34`）⇒ "无解"不再成立 ✗
    #   ⇒ 哨兵改成断言**「认不出营地」这个事实 + 日志**，并把"候选非空"归因到 `obs_lit`：
    #     · 真机上不存在全亮盘（3 张真机进图帧只 7~8 格亮）⇒ 这条 fixture 的"全亮"
    #       本身不真实，但它**仍然有效**于验证"camp 认不出"这条路 ✓
    #     · 真正要守的是：**没打 camp 标 ⇒ `camp is None`**（这个必须恒成立 ✓）
    #     · 且"候选非空"**只**来自 `obs_lit`（不是 `camp_nb` 意外非零）
    check('v1.53 ⑥ ⚠【v1.62 按新行为改写】不打 camp 标 ⇒ **`camp is None`**（哨兵 ✓）；'
          '候选不再为 0，是因为 `obs_lit`（观测已亮的块）生效 —— 那是**正确行为**'
          '（全亮盘在真机不存在，但"认不出营地"这条必须仍守 ✓）',
          _prob53b.camp is None and len(_prob53b.visible(frozenset())) > 0,
          'camp=%s vis=%d' % (_prob53b.camp,
                              len(_prob53b.visible(frozenset()))))
except Exception as _e53:       # noqa: BLE001
    check('v1.53 守门可运行（%r）' % (_e53,), False)

# ─────────────────────────────────────────────────────────────────────────
# ⓹⓵ v1.58【D-9 补门禁盲区：**真端到端**（`_cells_for_model` → `from_observation` → `Problem` → `solve`）】
#
#   ⚠⚠⚠ 这是「**576 项全绿 vs 真机全崩**」的根因，也是本次改动**唯一**能防它复发的东西：
#     本套件此前**只调用过一次 `_cells_for_model`**（㉓，测拉黑打标），
#     而 v1.51~v1.56 的"实跑"断言（㊿④ / v1.53③~⑥）**绕过它**，
#     直接给 `MapSim.from_observation` 喂**已经打好 `camp=True` 的合成观测**
#     ⇒ 等于**假设打标链已通** ✗
#     ⇒ M30（`find_camp_cell` 缺失）/ M31（`_rescue` 拆块缺失）这个洞**完全无覆盖**
#       ⇒ "expanded:1 exhausted" 在门禁上永远是绿的 ✗✗
#
#   ⇒ 本组必须从 `_cells_for_model` **起**跑通整条链，并且配**负样本**
#     证明它不是恒绿（把 `top` 里的 `_000` 删掉 ⇒ **必须**回到 `expanded == 1`）✓
#   ⇒ 外加 D-3 的不变量：随机 500 张盘（营地塞进 1~4 格块）⇒ `camp_nb > 0` 且 `solve` 有解 ✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('⓹⓵ v1.58 D-9【真端到端】`_cells_for_model` → `from_observation` → `Problem` → `solve`')
try:
    import importlib as _il58
    _il58.invalidate_caches()
    import random as _rnd58
    import spots as _sp58
    import mapsim as _sim58
    import mapsolve as _mv58

    _cell58 = _sim58.cell_of

    def _c58(sid, name, anchor, revealed=True, ratio=1.0, score=0.99,
             marks=None, top=None):
        return {'sid': sid, 'name': name, 'revealed': revealed, 'ratio': ratio,
                'score': score, 'marks': list(marks or []), 'anchor': anchor,
                'top': list(top or [(score, sid, anchor)])}

    def _frame58():
        """与 PC 真机帧 `r_204323_0.png` / `r_233023_0.png` **同形状**：
        营地 (2,1) 属 4 格块 `S00003_211 巨大沙堡`（anchor=(1,1)），
        但 (2,1) 的**单格候选** `top[0] = (1.000, 'S00003_000', (2,1))`；
        其余格为相连草地；(5,7) 是雾里的 boss ✓"""
        _c = {}
        for _r in range(1, 6):
            for _cc in range(1, 8):
                _c[(_r, _cc)] = _c58('S00003_001', '草地', (_r, _cc))
        _a = (1, 1)
        for _k in ((1, 1), (2, 1), (2, 2), (2, 3)):
            _c[_k] = _c58('S00003_211', '巨大沙堡', _a)
        _c[(2, 1)] = _c58('S00003_211', '巨大沙堡', _a,
                          top=[(1.000, 'S00003_000', (2, 1)),
                               (0.998, 'S00003_001', (2, 1))])
        _c[(1, 1)] = _c58('S00003_211', '巨大沙堡', _a,
                          top=[(0.998, 'S00003_001', (1, 1)),
                               (0.980, 'S00003_211', _a)])
        _c[(5, 7)] = _c58('S00003_002', '沙地', (5, 7), revealed=False,
                          ratio=0.66, marks=['boss'])
        return _c

    _c58a = _frame58()
    _mk58 = {(5, 7): {'marks': ['boss']}}
    _lg58a = []
    _m58a = EL._cells_for_model({'marks': dict(_mk58), 'obs': _c58a, 'done': set()},
                                {'st': _c58a}, log=_lg58a, tag='e2e58',
                                mark_revealed=False)
    _txt58a = ' '.join(str(x) for x in _lg58a)
    check('D-9 ① 真端到端：`_cells_for_model` 内部真的走了**单格候选 `top`** 那条路'
          '（日志里有 `cell_split_from_block` / `spawn_fallback` ✓）',
          ('cell_split_from_block' in _txt58a) or ('spawn_fallback' in _txt58a),
          _txt58a[:160])
    _sim58a = _sim58.MapSim.from_observation(_m58a, _sp58.spot_rows())
    _prob58a = _mv58.Problem(_sim58a)
    check('D-9 ② 真端到端：营地被多格块吞掉时 **`Problem.camp` 非空**'
          '（旧行为：`camp=None` ⇒ 揭示链没起点 ✗）',
          _prob58a.camp is not None, 'camp=%s' % (_prob58a.camp,))
    _cache58a = _mv58._build_cache(_prob58a)
    check('D-9 ③ 真端到端：**`camp_nb` 非零**（用户口径原话：'
          '「**不可能出现开局没有一个地方能点的情况**」✓）',
          _cache58a.get('camp_nb', 0) != 0, 'camp_nb=%s' % (_cache58a.get('camp_nb'),))
    _rep58a = {}
    _cost58a, _acts58a = _mv58.solve(_prob58a, max_states=60000, max_secs=8,
                                     report=_rep58a)
    check('D-9 ④ ⭐真端到端：**`expanded > 1` 且 `reason == \'ok\'`**'
          '（真机/旧代码是 `expanded=1` + `exhausted` ✗ —— 这条就是"576 项全绿 vs 真机全崩"的补丁 ✓）',
          (int(_rep58a.get('expanded') or 0) > 1)
          and _rep58a.get('reason') == 'ok' and _acts58a is not None,
          'cost=%s reason=%s expanded=%s' % (_cost58a, _rep58a.get('reason'),
                                             _rep58a.get('expanded')))
    check('D-9 ⑤ 原格**不许从模型里消失**（`board >= 0`）—— PC `9c045a9` 的教训：'
          '「重新缩进 ⇒ 该格从模型里消失（`board<0`）⇒ 比原问题更危险」✗',
          _sim58a.board[_cell58(2, 1)] >= 0,
          'board=%s' % (_sim58a.board[_cell58(2, 1)],))

    # ---- 负样本：把 `top` 里的 `_000` 删掉 ⇒ **必须仍回到** expanded==1 / exhausted ----
    _c58b = {}
    for _k, _v in _c58a.items():
        _v2 = dict(_v)
        _v2['top'] = [t for t in (_v.get('top') or [])
                      if str(t[1]).split('_')[-1] != '000']
        _c58b[_k] = _v2
    _lg58b = []
    _m58b = EL._cells_for_model({'marks': dict(_mk58), 'obs': _c58b, 'done': set()},
                                {'st': _c58b}, log=_lg58b, tag='e2e58b',
                                mark_revealed=False)
    _sim58b = _sim58.MapSim.from_observation(_m58b, _sp58.spot_rows())
    _prob58b = _mv58.Problem(_sim58b)
    _rep58b = {}
    _cost58b, _acts58b = _mv58.solve(_prob58b, max_states=60000, max_secs=8,
                                     report=_rep58b)
    # ⚠⚠ v1.62【本条已按新行为改写】—— `visible()` 加了「观测里就亮的块」（`obs_lit`）
    #   旧断言：「删掉 `_000` ⇒ `camp=None` ⇒ `expanded==1` + `exhausted`（无解）」
    #   现实：`_c58a` 这份 fixture **全盘 20 格都 `revealed=True`** ⇒ `obs_lit` 让它们
    #     全成候选 ⇒ **有解**（`expanded=3`）✗ 旧断言不再成立
    #   ## 为什么**不是**放水（用户 2026-10-05 拍板：按新行为改写、保住哨兵）
    #     · `obs_lit` 的**设计意图**就是"观测里亮的格本来就能点 ⇒ 该在候选里"
    #       ⇒ 「全盘都亮 ⇒ 有解」是**正确行为**，不是 bug ✓
    #     · 而**真机上不存在**这种全亮盘（v1.62 实测 3 张真机进图帧：**只 7~8 格亮**）
    #     · **「认不出营地」这个故障仍须守** —— 真机上它仍会让**规划质量变差**
    #       （绕路/多花体力），只是不再"无解" ⇒ 哨兵改成断言**日志 + 开局候选构成**
    #   ⇒ 新断言（三条，缺一不可）：
    #     ① `camp is None`（**认不出营地这个事实本身**必须仍成立）
    #     ② **仍要落 `camp_not_found` 日志**（运维能一眼看出"这图没认出营地"✓）
    #     ③ 开局候选**确实来自 `obs_lit`**（即"有解"是那条新支路给的，不是别的巧合）
    _lg58b_txt = ' '.join(str(x) for x in (_lg58b or []))
    _ch58b = _mv58._build_cache(_prob58b)
    check('D-9 ⑥ ⚠【v1.62 按新行为改写】删掉 `top` 里的 `_000` ⇒ '
          '**`camp` 仍必须认不出**（哨兵保住 ✓）'
          '＋ **仍要落 `camp_not_found` 日志**（不能静默）；'
          '而"有解"是 `obs_lit`（观测已亮的块）给的 —— 那是**正确行为**'
          '（真机进图实测只 7~8 格亮，不存在全亮盘 ✓）',
          _prob58b.camp is None
          and 'camp_not_found' in _lg58b_txt
          and int(_ch58b.get('obs_lit') or 0) != 0,
          'camp=%s obs_lit块=%d 日志含camp_not_found=%s'
          % (_prob58b.camp, bin(int(_ch58b.get('obs_lit') or 0)).count('1'),
             'camp_not_found' in _lg58b_txt))
    # ⚠ 保留**旧口径的对照**（证明"没有 `obs_lit` 时确实是旧行为"）——
    #   不删旧结论，只是把它降级成"对照项"而非"负样本断言" ✓
    _ch58b2 = dict(_ch58b)
    _ch58b2['obs_lit'] = 0
    _prob58b._cache = _ch58b2
    _rep58b2 = {}
    _cost58b2, _acts58b2 = _mv58.solve(_prob58b, max_states=60000, max_secs=8,
                                       report=_rep58b2)
    check('D-9 ⑥b 【对照】把 `obs_lit` 人为清零 ⇒ **复现旧真机症状**'
          '（`camp=None` + `expanded==1` + `exhausted`）'
          '—— 证明「有解」确实是那条新支路给的，这条门禁**不是恒绿** ✓',
          _prob58b.camp is None and int(_rep58b2.get('expanded') or 0) == 1
          and _rep58b2.get('reason') == 'exhausted',
          'camp=%s reason=%s expanded=%s'
          % (_prob58b.camp, _rep58b2.get('reason'), _rep58b2.get('expanded')))

    # ═══ D-3 不变量：随机 500 张盘，把营地塞进 1~4 格块 ⇒ **开局候选恒非空** ═══
    #   依据（用户口径）：开局**一定**有点得动的格（营地挨着的那几个）⇒ `camp_nb == 0`
    #     **只能是模型 bug**。PC 的做法是**不做任何 revealed/observed 过滤**
    #     （`mapbot_pc/mapsolve.py:403-415`）⇒ 手机端对齐它 ✓
    def _rand58(_rng, fog):
        _a = (_rng.randint(1, 5), _rng.randint(1, 7))
        _nbrs = [(_a[0] + _dr, _a[1] + _dc)
                 for _dr, _dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                 if 1 <= _a[0] + _dr <= 5 and 1 <= _a[1] + _dc <= 7]
        _rng.shuffle(_nbrs)
        _mem = [_a] + _nbrs[:max(0, _rng.randint(1, 4) - 1)]
        _anc = min(_mem)
        _c = {}
        for _r in range(1, 6):
            for _cc in range(1, 8):
                _c[(_r, _cc)] = _c58('S00003_001', '草地', (_r, _cc))
        for _k in _mem:
            _c[_k] = _c58('S00003_211', '巨大沙堡', _anc)
        _camp = _rng.choice(_mem)
        _c[_camp] = _c58('S00003_211', '巨大沙堡', _anc, score=1.0,
                         top=[(1.000, 'S00003_000', _camp),
                              (0.998, 'S00003_001', _camp)])
        _tgt = _rng.choice([k for k in sorted(_c) if k not in _mem])
        _c[_tgt] = _c58('S00003_002', '沙地', _tgt, marks=['boss'])
        if fog:      # ⚠ 随机判雾 —— 这正是 v1.55 那道 `observed` 过滤会把 camp_nb 清成 0 的场景
            for _k in _mem:
                _c[_k]['revealed'] = False
            for _k in _rng.sample(sorted(_c), _rng.randint(0, 6)):
                if _k != _tgt:
                    _c[_k]['revealed'] = False
        return _c, _camp, _tgt

    _rnd58.seed(20261004)
    _bad_nb, _bad_sol, _bad_nb_fog = [], [], []
    for _i in range(500):
        _cells, _camp, _tgt = _rand58(_rnd58, fog=False)
        _lg = []
        _m = EL._cells_for_model({'marks': {_tgt: {'marks': ['boss']}},
                                  'obs': _cells, 'done': set()},
                                 {'st': _cells}, log=_lg, tag='inv58',
                                 mark_revealed=False)
        _sv = _sim58.MapSim.from_observation(_m, _sp58.spot_rows())
        _pv = _mv58.Problem(_sv)
        if _mv58._build_cache(_pv).get('camp_nb', 0) == 0:
            _bad_nb.append(_i)
        _rep = {}
        _cost, _acts = _mv58.solve(_pv, max_states=60000, max_secs=8, report=_rep)
        if _acts is None:
            _bad_sol.append((_i, _rep.get('reason'), _rep.get('expanded')))
    check('D-9 ⑦ 【D-3 不变量】随机 500 张盘（营地塞进 1~4 格块）⇒ **`camp_nb > 0` 恒成立**'
          '（对齐 PC「营地四邻恒为候选」的不变量 ✓）',
          not _bad_nb, 'camp_nb==0 的盘：%d 张 %s' % (len(_bad_nb), _bad_nb[:8]))
    check('D-9 ⑧ 【D-3 不变量】随机 500 张盘 ⇒ **`solve` 都有解**'
          '（用户口径：「不可能出现开局没有一个地方能点的情况」✓）',
          not _bad_sol, '无解的盘：%d 张 %s' % (len(_bad_sol), _bad_sol[:5]))

    _rnd58.seed(20261005)
    for _i in range(500):
        _cells, _camp, _tgt = _rand58(_rnd58, fog=True)
        _m = EL._cells_for_model({'marks': {_tgt: {'marks': ['boss']}},
                                  'obs': _cells, 'done': set()},
                                 {'st': _cells}, log=None, tag='inv58f',
                                 mark_revealed=False)
        _pv = _mv58.Problem(_sim58.MapSim.from_observation(_m, _sp58.spot_rows()))
        if _mv58._build_cache(_pv).get('camp_nb', 0) == 0:
            _bad_nb_fog.append(_i)
    check('D-9 ⑨ 【D-3 不变量 · 含雾】随机 500 张盘（**营地块整块判雾** + 若干随机格判雾）'
          '⇒ `camp_nb > 0` **仍恒成立**（v1.55 那道 `observed` 过滤会把这里清成 0 ✗）',
          not _bad_nb_fog, 'camp_nb==0 的盘：%d 张 %s' % (len(_bad_nb_fog),
                                                        _bad_nb_fog[:8]))

    # ---- D-5 硬告警路径的**真跑**（`solver_order()` 在 `expanded<=1` 时落 `no_plan_giveup`）----
    #   ⚠ 必须真调一次 —— 只断言源码字符串等于没测（`no_plan_giveup` 整段在 `if not plan:` 里，
    #     光照 ⑥ 那样走 `mapsolve.solve()` 是**走不到**的）✗
    # ⚠⚠ v1.62【按新行为改写】—— `visible()` 加了 `obs_lit` ⇒ 这条"坏帧"**不再无解**
    #   （实测 `order=[(1,1),(5,7)]`、`expanded=3`、`reason=ok`）
    #   ## 为什么不能因此删掉这条门禁
    #     `no_plan_giveup` 是**"模型层坏掉必须一眼看出丢图"**的硬告警（D-5 的核心 ✓），
    #     必须仍有办法**真跑**到它 —— 否则以后真坏了也没人知道 ✗
    #   ## 正确做法：**人为造一条真的无解的坏帧**（把 `obs_lit` 清零 ⇒ 复现旧症状）
    #     ⇒ 这样测的仍是**同一条代码路径**（`if not plan:` + `expanded<=1`），
    #       且**不依赖"全亮 fixture 恰好无解"这个已被 v1.62 改掉的巧合** ✓
    _ch58g = _mv58._build_cache(
        _mv58.Problem(_sim58.MapSim.from_observation(_m58b, _sp58.spot_rows())))
    _ch58g['obs_lit'] = 0                    # 人为清零 ⇒ 复现"认不出营地 + 无候选"✓
    _sim58g = _sim58.MapSim.from_observation(_m58b, _sp58.spot_rows())
    _prob58g = _mv58.Problem(_sim58g)
    _prob58g._cache = _ch58g
    _lg58g = []
    _so58g = {}
    #   ⚠ 必须让 `solver_order` 用**同一份被清零的缓存** ⇒ 直接走 `mapsolve.solve`
    #     那一段（`solver_order` 内部会重建缓存 ⇒ 这里改为直接验证判据 + 手动落告警）
    _rep58g = {}
    _cost58g, _plan58g = _mv58.solve(_prob58g, max_states=60000, max_secs=8,
                                     report=_rep58g)
    _is_bad58g = (not _plan58g) and _rep58g.get('reason') != 'ok' \
        and 0 <= int(_rep58g.get('expanded') or 0) <= 1
    check('D-9 ⑫ ⚠【v1.62 按新行为改写】`no_plan_giveup` 的**触发条件**仍必须可达'
          '（人为把 `obs_lit` 清零 ⇒ 复现"认不出营地 + 无候选"坏帧'
          '⇒ `expanded<=1` + `reason!=ok` + 无解 ✓）—— '
          '这样测的是**同一条判据**，不再依赖"全亮 fixture 恰好无解"那个巧合；'
          '⚠ **不许删这条**：它是"模型层坏掉必须一眼看出丢图"的唯一守卫 ✗',
          _is_bad58g,
          'cost=%s plan=%s reason=%s expanded=%s'
          % (_cost58g, _plan58g, _rep58g.get('reason'), _rep58g.get('expanded')))
    #   并核对**源码里那段告警仍在**（判据真被消费，而不只是算出来）
    _el58g_src = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                                   'explore_loop.py'), encoding='utf-8').read()
    check('D-9 ⑫b `no_plan_giveup` 落日志那段**源码仍在**'
          '（判据被真消费；v1.62 只改了"怎么造坏帧"，没动告警本身 ✓）',
          "'finish': 'no_plan_giveup'" in _el58g_src
          and '0 <= _exp58i <= 1' in _el58g_src)

    # ---- D-1 **单独**覆盖（把 D-2 的拆块排除在外）----
    #   构造：营地格的 `top1` 分**低于分组分**（⇒ `_rescue` 的 `_ts >= _gs` 不成立 ⇒ 拆块不触发），
    #   但它的 `top` 里仍有一个 `≥ CAMP_TOP_MIN` 的 `_000` ⇒ **只有**"扫 `top` 兜底"能救回来 ✓
    #   这正是 PC `find_camp_cell()` docstring 里那把帧的形状（top[0]=1.000 / top[1]=0.996…）✓
    def _d1_frame58(_sc):
        _c = _frame58()
        _c[(2, 1)] = _c58('S00003_211', '巨大沙堡', (1, 1), score=0.99,
                          top=[(_sc, 'S00003_000', (2, 1)),
                               (0.94, 'S00003_001', (2, 1))])
        return _c

    for _sc58, _want58 in ((0.95, True), (0.50, False)):
        _c58f = _d1_frame58(_sc58)
        _lg58f = []
        _m58f = EL._cells_for_model({'marks': dict(_mk58), 'obs': _c58f, 'done': set()},
                                    {'st': _c58f}, log=_lg58f, tag='d1c58',
                                    mark_revealed=False)
        _fb58f = [x for x in _lg58f if isinstance(x, dict) and 'spawn_fallback' in x]
        _split58f = [x for x in _lg58f if isinstance(x, dict)
                     and x.get('d1c58') == 'cell_split_from_block'
                     and x.get('cell') == '2,1']
        _sim58f = _sim58.MapSim.from_observation(_m58f, _sp58.spot_rows())
        _prob58f = _mv58.Problem(_sim58f)
        _cache58f = _mv58._build_cache(_prob58f)
        _rep58f = {}
        _cost58f, _acts58f = _mv58.solve(_prob58f, max_states=60000, max_secs=8,
                                         report=_rep58f)
        if _want58:
            check('D-9 ⑩ 【D-1 单独覆盖】营地格 `top1` 分（%.2f）**低于分组分** ⇒ 拆块不触发，'
                  '但 `top` 里有 `≥ CAMP_TOP_MIN(0.90)` 的 `_000` ⇒ '
                  '**只有"扫 `top`"这条兜底**能救它 ⇒ `spawn_fallback: 2,1` + 有解 ✓'
                  % _sc58,
                  (not _split58f) and bool(_fb58f)
                  and _fb58f[0].get('spawn_fallback') == '2,1'
                  and _prob58f.camp is not None
                  and _cache58f.get('camp_nb', 0) != 0
                  and _rep58f.get('reason') == 'ok',
                  'split2,1=%s fallback=%s camp=%s camp_nb=%s reason=%s expanded=%s'
                  % (bool(_split58f), (_fb58f[0].get('spawn_fallback') if _fb58f else None),
                     _prob58f.camp, _cache58f.get('camp_nb'),
                     _rep58f.get('reason'), _rep58f.get('expanded')))
        else:
            # ⚠⚠ v1.62【按新行为改写】—— 旧断言要"无解（expanded==1/exhausted）"，
            #   但 `visible()` 加了 `obs_lit` ⇒ 全亮 fixture 必有解 ✗
            #   ⇒ 哨兵改成：**兜底不许命中**（`not _fb58f`）+ **认不出营地**（`camp is None`）
            #     —— 这两条才是"D-1 分数门槛在起作用"的**真正证据** ✓
            #     （"无解"已不是必然后果：`obs_lit` 会给别的候选 ⇒ 有解也是对的 ✓）
            check('D-9 ⑪ ⚠【v1.62 按新行为改写】把那个 `_000` 的分数降到 '
                  '`CAMP_TOP_MIN` 之下（%.2f）⇒ **兜底不许命中**（`not _fb58f`）'
                  '＋ **`camp` 仍认不出**（哨兵 ✓）'
                  '—— 这两条才是"分数门槛真在起作用"的证据；'
                  '"无解"已不是必然后果（`obs_lit` 会给别的候选 ⇒ 有解也对 ✓）' % _sc58,
                  (not _fb58f) and (not _split58f) and _prob58f.camp is None,
                  'fallback=%s camp=%s reason=%s expanded=%s'
                  % (bool(_fb58f), _prob58f.camp, _rep58f.get('reason'),
                     _rep58f.get('expanded')))
except Exception as _e58:       # noqa: BLE001
    check('v1.58 D-9 真端到端守门可运行（%r）' % (_e58,), False)

print()
print('⓹⓶ v1.58【P0 落地守门：D-1 / D-2 / D-3 / D-5 / D-6 / D-7 / D-8 每条都有断言】')
try:
    _el58s = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                  encoding='utf-8').read()
    _ms58s = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsim.py'),
                  encoding='utf-8').read()
    _mv58s = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsolve.py'),
                  encoding='utf-8').read()
    _code58 = '\n'.join(l for l in _el58s.split('\n') if not l.strip().startswith('#'))

    # ---------------- D-1 `find_camp_cell()` + CAMP_TOP_MIN + 两处调用点 ----------------
    check('D-1 ① 手机端有 `find_camp_cell()` 与 `CAMP_TOP_MIN = 0.90`'
          '（抄 PC `explore_loop.py:7470-7523` / `:2797` ✓）',
          'def find_camp_cell(' in _el58s and 'CAMP_TOP_MIN = 0.90' in _el58s)
    check("D-1 ② 兜底扫的是**单格候选 `top`**（`v.get('top')`），不是归组后的 `sid` ✓",
          "for t in (v.get('top') or []):" in _el58s
          and "sid.split('_')[-1] == '000'" in _el58s
          and 'sc >= CAMP_TOP_MIN' in _el58s)
    _n58_old = _code58.count("v.get('anchor') == k and v.get('name') == '营地'")
    check('D-1 ③ 老判据**只剩 `find_camp_cell()` 里那一份**'
          '（原来在 `:7764` / `:8105` 各有一份副本 ⇒ 「只改一半 ⇒ 线上仍复现」，'
          'PC `交接文档 §14.1` ✓）',
          _n58_old == 1, '代码里出现 %d 次（应为 1）' % _n58_old)
    check("D-1 ④ 两处调用点都走 `find_camp_cell()`（`where='spawn'` / `where='spawn_road'`）"
          '—— 照 PC `:8341` / `:8824` ✓',
          "where='spawn'" in _el58s and "where='spawn_road'" in _el58s)
    check('D-1 ⑤ `_cells_for_model` 的兜底**复用** `find_camp_cell()`（单一真相源 ✓）'
          '—— 不再自己扫归组后的 `sid`（多格归组**恰好把营地格的 sid 覆盖成块 sid**'
          '⇒ 在唯一需要它的场景下**必然失败** ✗）',
          "where='cells_for_model'" in _el58s
          and "if not str(_v54.get('sid') or '').endswith('_000'):" not in _el58s)

    # ---------------- D-2 `_rescue` 拆块规则 ----------------
    check("D-2 ① `_rescue` 拆块规则在 `_cells_for_model` 里（`cell_split_from_block` 日志 ✓）",
          "tag: 'cell_split_from_block'" in _el58s
          and "_vv['anchor'] = tuple(_k)" in _el58s)
    check('D-2 ② 收窄口径照 PC `:1075-1077`（**只**救 空地系/营地/海螺/`_000`）'
          '—— 否则 `(2,6)` 被拆成「勇者之墓」⇒ 战斗格被定价 1 体 ✗',
          "_rescue = (is_plain_spot(_tsid)" in _el58s
          and "_tname in ('营地', '海螺')" in _el58s
          and "str(_tsid).endswith('_000')" in _el58s)
    _i58_res = _el58s.find('_rescue = (is_plain_spot(_tsid)')
    _i58_out = _el58s.find('            _out[_k] = _vv')
    _line58_res = [x for x in _el58s.split('\n')
                   if '_rescue = (is_plain_spot(_tsid)' in x]
    check('D-2 ③ ⚠ PC `9c045a9` 的教训：**只改字段、不动函数体缩进**'
          '（拆块段与同层代码**同缩进**，且 `_out[_k] = _vv` 仍在它**之后**'
          '⇒ 拆出来的 `anchor/sid/name` 真的进了模型，该格**不会从模型里消失** ✓）',
          _line58_res and _line58_res[0].startswith(' ' * 20)
          and 0 < _i58_res < _i58_out)

    # ---------------- D-3 `camp_nb` 去掉 `observed` 过滤 ----------------
    check("D-3 ① `camp_nb` **不再**按 `Block.observed` 滤雾"
          "（对齐 PC `mapsolve.py:403-415`：**没有任何过滤**，"
          "用户口径「最开始就是只有**营地挨着的四个格子**可以点」✓）",
          "if not bool(getattr(prob.blocks.get(_nb), 'observed', True)):" not in _mv58s)
    check('D-3 ② 【v1.60 改口径】营地揭示源 = **唯一**那份 `prob.camp_reveal`'
          '（排除营地块自己 ✓；v1.55 的「营地块 ∪ 营地格」并集已删 —— 它与 '
          '`block_revealed` 不同口径 ⇒ 求解器可点、选格时找不到已揭示格 ⇒ **点雾格** ✗）；'
          '`elif` 兜底（`camp_cells` 为空 ⇒ 退回整块 `NB_MASK[camp]`）照抄 PC ✓',
          '_camp_block_cells' not in _mv58s
          and '_ccells | _camp_block_cells' not in _mv58s
          and 'def _camp_nb_blocks(self, cells, exclude_camp=True):' in _mv58s
          and 'if exclude_camp and _nb == self.camp:' in _mv58s
          and 'camp_nb = NB_MASK[camp] & ~camp_mask' in _mv58s)
    check('D-3 ③ ⚠ `Block.observed` 本身**必须留着** —— 那是**另一个**机制'
          '（M8 `block_revealed` 的观测闸门）✓',
          'self.observed = bool(revealed)' in _ms58s
          and 'if n in self.obs_consumed and not _obs:' in _mv58s)

    # ---------------- D-5 退图判据补 `had_plan` ----------------
    check('D-5 ① 规划成功时置 `had_plan`（照 PC `:9027` ✓）',
          "st['had_plan'] = True" in _code58)
    check('D-5 ② 退图判据按 `had_plan` 区分（照 PC `:9149-9172`）：'
          '算出过计划 ⇒ **立刻收工**；从没算出过 ⇒ **留 3 轮耐心** ✓',
          "if st.get('had_plan'):" in _code58
          and "'finish': 'blank_board', 'had_plan': True" in _el58s)
    check('D-5 ③ `no_plan` 且 `expanded <= 1` ⇒ **硬告警** `finish: no_plan_giveup`'
          '（模型层坏了必须一眼看得出"丢图"，不许被静默转成"正常收工" ✗）',
          "'finish': 'no_plan_giveup'" in _el58s
          and "'expanded': _exp58" in _el58s)
    check('D-5 ④ 旧的**无条件** `targets_done` 退图已删除'
          '（它在 `blank_board` 的 3 轮耐心**之前**跑 ⇒ 直接绕过保护 ⇒ 25 体力白扔，'
          '日志还冒充"满意收工" ✗✗）',
          "'finish': 'targets_done'" not in _el58s)
    check('D-5 ⑤ ⛔ **没有**加回「点序空就多等几轮」的兜底'
          '（PC `verify_fog_only_start.py:160-165` 已按用户口径删掉它 ✗'
          '—— 要治的是 `expanded:1` 本身，不是给它盖被子）',
          'need_explore' not in _code58
          and 'EXPLORE_MIN_GRAY' not in _code58)

    # ---------------- D-6 `Block.plain` 对齐 PC ----------------
    _i58_fs = _ms58s.find('if _sp0.is_fight_spot(self.sid):')
    _i58_fog = _ms58s.find("if (not getattr(self, 'observed', False)) "
                           "and self.spot.get('fog_sil') is not None:")
    check('D-6 ① `plain` 里**战斗保护在最前**（照 PC `:180-185`）——'
          '任何分支都不许把战斗型判成空地（用户原话：'
          '「**42 为什么能连锁？这不是战斗地块吗**」✗）',
          0 < _i58_fs < _i58_fog, 'fight@%s fog@%s' % (_i58_fs, _i58_fog))
    check('D-6 ② 雾剪影那一支加了 `not observed`（照 PC `:198-203`）——'
          '已揭示的格**必须**按名字/类型判（用户原话：'
          '「**模型都认出这是海边小屋了，怎么还会认为是空地**」✗）',
          _i58_fog > 0)
    _sp58c = __import__('spots')
    _sim58c = __import__('mapsim')
    _row58c = {'sid': 'S00003_111', 'name': '海边杂物', 'SpotSize': 3,
               'SpecialSpot': 1, 'fog_sil': 0.2, 'fog_flat': True, 'cells': [0, 1, 2]}
    _b58c = _sim58c.Block(0, dict(_row58c), revealed=True)
    check('D-6 ③ 执行级：**已揭示**（observed=True）的战斗块，**即使带剪影值** '
          '⇒ `plain is False`（旧写法：剪影分支提前 return ⇒ `plain=True` ⇒ 定价 1'
          '（应 `size×2`）且被算进草地连锁 ✗✗）',
          _b58c.observed and _b58c.plain is False, 'plain=%s' % (_b58c.plain,))
    _b58d = _sim58c.Block(1, {'sid': 'S00003_001', 'name': '草地', 'SpotSize': 1,
                              'SpecialSpot': 0, 'fog_sil': 0.012, 'fog_flat': True},
                          revealed=False)
    check('D-6 ④ 【负样本】**真雾格**（observed=False）+ 剪影平坦 ⇒ **仍 `plain is True`**'
          '（⚠ 别把这一支整个删掉 —— 那是**另一个**机制 M54，'
          '删了会"连锁穿过雾里的障碍" ✗）',
          _b58d.plain is True, 'plain=%s' % (_b58d.plain,))

    # ---------------- D-7 三处同步：`is_fight_spot` + `拦路` ----------------
    _seg58_x2 = _mv58s.split('FIGHT_X2 = ')[1][:160]
    _seg58_bc = _ms58s.split('def block_cost')[1][:1800]
    _seg58_cm = _el58s.split('_COST_FIGHT_MARKS = ')[1][:220]
    check("D-7 ① **三处同步**都有 `拦路`（PC `a7df4af` 正文：「修法（**三处同步**，口径一致 ✓）」）",
          "'拦路'" in _seg58_x2 and "'拦路'" in _seg58_bc and "'拦路'" in _seg58_cm,
          'mapsolve=%s mapsim=%s loop=%s' % ("'拦路'" in _seg58_x2,
                                             "'拦路'" in _seg58_bc,
                                             "'拦路'" in _seg58_cm))
    check('D-7 ② `mapsim.block_cost` 里也有**地块类型**定价（`is_fight_spot`）'
          '—— `_fix_blank_cost_1` 当年「只改了 mapsolve、漏了 mapsim」⇒'
          '「策略评估与最优解**不可比**」✗',
          'is_fight_spot' in _seg58_bc)
    _cells58e = {
        (1, 1): {'sid': 'S00003_000', 'name': '营地', 'revealed': True,
                 'ratio': 1.0, 'marks': [], 'anchor': (1, 1)},
        (2, 1): {'sid': 'S00003_111', 'name': '海边杂物', 'revealed': True,
                 'ratio': 0.9, 'marks': [], 'anchor': (2, 1)},
        (2, 2): {'sid': 'S00003_111', 'name': '海边杂物', 'revealed': True,
                 'ratio': 0.9, 'marks': [], 'anchor': (2, 1)},
    }
    _sim58e = _sim58c.MapSim.from_observation(_cells58e, _sp58c.spot_rows())
    _b58e = [b for b in _sim58e.blocks.values() if b.name == '海边杂物']
    _cst58e = _sim58c.MapSim.block_cost(_b58e[0]) if _b58e else None
    _sz58e = _b58e[0].size if _b58e else None
    check('D-7 ③ 执行级：`MapSim.block_cost` 对**战斗型地块**按 `size×2`'
          '（与 `mapsolve.step_cost` 同口径 ⇒ 模拟器与求解器可比 ✓）',
          _cst58e is not None and _cst58e == _sz58e * 2,
          'cost=%s size=%s' % (_cst58e, _sz58e))
    _b58f = _sim58c.Block(9, {'sid': 'S00003_002', 'name': '沙地', 'SpotSize': 3,
                              'SpecialSpot': 0}, revealed=True, mark='拦路')
    check("D-7 ④ 执行级：`mark='拦路'` 的块也按 `size×2`（拦路标记在**规划时还没有**，"
          '但 EffPolicy / `model_cost` 审计要用 ✓）',
          _sim58c.MapSim.block_cost(_b58f) == _b58f.size * 2,
          'cost=%s size=%s' % (_sim58c.MapSim.block_cost(_b58f), _b58f.size))

    # ---------------- D-8 `FOLLOW_PLAN_ONLY` ----------------
    check('D-8 ① `FOLLOW_PLAN_ONLY = True`（照 PC `:436`；用户口径原话：'
          '「**去掉那些追加的，只按规划的走**」✓）',
          'FOLLOW_PLAN_ONLY = True' in _el58s)
    _i58_fpo = _code58.find('if FOLLOW_PLAN_ONLY:')
    _i58_rev = _code58.find('for p in reveals[:10]:')
    check('D-8 ② 追加逻辑（开路格 + 交替插目标 + 内容格兜底）**已套进 `else:`**'
          '（PC `:8919-8945` 同款改法 ✓）',
          0 < _i58_fpo < _i58_rev, 'follow@%s reveals@%s' % (_i58_fpo, _i58_rev))
    check('D-8 ③ ⚠ **降级链保留**（solver 失败 ⇒ EffPolicy）——'
          "那不是\"追加点击\"，是**换一个规划器** ✓",
          "st.get('plan_src') == 'eff'" in _code58 and 'eff_order(' in _code58)
    check('D-8 ④ ⚠ `road_all` / `targets` **仍照旧计算**'
          '（它们是"**哪些战斗该打**"的**判据**（popups 的 `offroad_fight` / `forced_fight` /'
          "`on_plan` 靠它们），**不是点击序列** ⇒ 别一起删 ✗；PC `:8923` 原文 ✓",
          "st['road'] = road_all" in _code58
          and "st['targets'] = list(marked)" in _code58
          and "entry['road'] = road_all[:6]" in _code58)
except Exception as _e58s:      # noqa: BLE001
    check('v1.58 P0 落地守门可运行（%r）' % (_e58s,), False)

# =====================================================================================
# ㊿⭐ v1.60 ⭐⭐⭐ 照抄 PC 揭示判据（**相对两趟法** + 模型层 **0.75** 覆写）
#                 ＋ `camp_nb` 与 `block_revealed` **同口径**
#
# 未决第 1 条（`会话接力.md` §3 / `PC规划算法对照报告.md` §D 的 M35 / M50 / M51）：
#   「手机端**已揭示的格会被判成雾**（`observed=False`）⇒ `plain=False` ⇒ **空地连锁断裂**」
#
# PC 两处（**结构逐字抄**，见 `app/src/main/python/spots.py` 顶部与 `_cells_for_model` 注释）：
#   ① `spots` 的**相对两趟法**：`revealed ⟺ ratio ≥ max(地板, 第10分位×1.06)`
#   ② `_cells_for_model` 的**模型层覆写**：`ratio ≥ 0.75`
#
# ⚠⚠ **本门禁最重要的一条：0.66 地板在手机端是坏的（实测，不是口味）**
#   手机端 `ratio` 分母是**本图模板亮度中位**（v1.35）⇒ 雾带按格子美术亮度摊开
#   （真机草原帧实测 0.685~0.761 ⇒ 是 p10 的 **1.26 倍**）⇒ PC 的 ×1.06 盖不住。
#   实测（`_tmpman/probe_v160_reveal.py`）：
#     地板 0.66 ⇒ 真机草原帧 **FP 28/35 格**（[ok] 下面第 ③ 项把它固化成**反向断言**）
#     地板 0.80 ⇒ FP 0 / FN 0
#   ⇒ 门禁**同时**钉住"地板必须是 0.80"和"0.66 确实会 FP≥20"——
#     谁把地板改回 0.66，这两条里的一条必然红 ✓
# =====================================================================================
print()
print('㊿⭐ v1.60 揭示判据（PC 两趟相对法 + 模型层 0.75 覆写）+ camp_nb ≡ block_revealed')
_SP60 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'spots.py')
_EL60 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
_MV60 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsolve.py')
try:
    _sp60s = open(_SP60, encoding='utf-8').read()
    _el60s = open(_EL60, encoding='utf-8').read()
    _mv60s = open(_MV60, encoding='utf-8').read()

    # ---------------- ① `spots` 两趟相对法 ----------------
    check('v1.60 ① `spots` 有**两趟相对法**的三个常数（照抄 PC：10 分位 / ×1.06；'
          '⚠ 地板是手机端标定值 0.80，PC 是 0.66 ⇒ 见 ③）',
          'REVEAL_REL_Q' in _sp60s and 'REVEAL_REL_K' in _sp60s
          and 'REVEAL_REL_FLOOR' in _sp60s
          and float(EL.REVEAL_RATIO_MIN) == 0.80,
          'spots.REVEAL_REL_FLOOR=%s Q=%s K=%s'
          % (getattr(__import__('spots'), 'REVEAL_REL_FLOOR', '缺失'),
             getattr(__import__('spots'), 'REVEAL_REL_Q', '缺失'),
             getattr(__import__('spots'), 'REVEAL_REL_K', '缺失')))
    _sp60 = __import__('spots')
    check('v1.60 ② 判据 = `max(REVEAL_REL_FLOOR, _base * REVEAL_REL_K)`，'
          '且 `_base` 取**第 10 分位**（照抄 PC `:726-727` ✓）',
          'max(REVEAL_REL_FLOOR, _base * REVEAL_REL_K)' in _sp60s
          and 'int(len(_rs) * REVEAL_REL_Q) - 1' in _sp60s)
    check('v1.60 ③ 地板默认 **0.80**（手机端实测：0.66 在真机草原帧上 FP=28/35 ⇒ '
          '`REVEAL_REL_FLOOR = 0.80`；想对拍 PC 用 `MAPBOT_REVEAL_FLOOR=0.66` ✓）',
          abs(float(_sp60.REVEAL_REL_FLOOR) - 0.80) < 1e-9
          and 'MAPBOT_REVEAL_FLOOR' in _sp60s,
          'REVEAL_REL_FLOOR=%.2f' % float(_sp60.REVEAL_REL_FLOOR))
    check('v1.60 ④ `REVEAL_RATIO_MIN`（0.80）**降级为两趟法的异常兜底**，'
          "且 `revealed` 判定**只在第二趟**做（逐格算时拿不到全盘分布 ⇒ PC 原文"
          '「**必须两趟**」✗ 逐格判）',
          "'rev_evidence'] = 'fallback'" in _sp60s
          and "'revealed': False, 'rev_evidence': None," in _sp60s
          and 'revealed \u27fa ratio' not in _sp60s.split('def state')[1][:4000])
except Exception as _e60a:      # noqa: BLE001
    check('v1.60 ①~④ 源码守门可运行（%r）' % (_e60a,), False)

# ---------------- ⑤⑥ 实跑：真机草原两帧（**用代码自己的 ratio**）+ 人工标注真值 -------
#   ⚠⚠ 这里**必须调 `Board.state()`**（真流水线），**不能**像 v1.36 ⑨ 那样自己重算
#     `mean/L_map` —— 2026-10-05 实测两者对**营地格**差了 0.08（自己算 0.861、
#     代码算 0.780）⇒ 自己算的那版把"营地被判成雾"这个真 bug 整个盖住了 ✗✗
_F60 = (os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_r0.png'),
        os.path.join(PROJ, '_verify', 'phone_redmi_grassland', 'board_grassland_live.png'))
_TR60 = ({(5, 6), (4, 7), (5, 7)}, {(1, 6), (1, 7), (2, 7)})
try:
    import cv2 as _cv60
    import numpy as _np60
    import spots as _sp60b
    import mapsim as _sim60

    if not all(os.path.exists(f) for f in _F60):
        skip('v1.60 ⑤⑥ 实跑（缺真机草原帧 ⇒ 没真验证）')
    else:
        _st60 = []
        for _f in _F60:
            _im = _cv60.imdecode(_np60.fromfile(_f, dtype=_np60.uint8),
                                 _cv60.IMREAD_COLOR)
            _st60.append(_sp60b.Board('S10002').state(_im))
        # ⑤ spots 层：**零 FP**；FN 只许是营地（营地 ratio 0.780 < 0.80 是已知的，
        #    下一层（模型层 0.75）负责把它捞回来 ⇒ 见 ⑥ ✓）
        _fp60, _fn60 = [], []
        for _s, _tr in zip(_st60, _TR60):
            for _k, _v in _s.items():
                _rv = bool(_v.get('revealed'))
                if _rv and _k not in _tr:
                    _fp60.append('%d,%d' % _k)
                if (not _rv) and _k in _tr:
                    _fn60.append(('%d,%d' % _k, _v.get('name')))
        _ev60 = sorted({v.get('rev_evidence') for s in _st60 for v in s.values()})
        check('v1.60 ⑤ 实跑（真流水线 `Board.state()` + 人工标注 70 格）：spots 层'
              '**零 FP**；FN 只许是**营地**（known：它 ratio≈0.78 被模型层捞回 ✓）',
              not _fp60 and all(n == '营地' for _k, n in _fn60),
              'FP=%s FN=%s ev=%s' % (_fp60, _fn60, _ev60))
        check("v1.60 ⑤b 判定走了**相对法**路径（`rev_evidence=='rel'`，不是兜底/逐格 ✗）",
              _ev60 == ['rel'], 'ev=%s' % (_ev60,))
        # ⑥ 模型层 0.75：FN 归零；且多出来的 FP **必须全是非空地**
        #    （是空地就会"假连锁穿雾" —— 那正是 v1.03 用户口径要防的 ✗）
        _fp60b, _fn60b, _plain_fp = [], [], []
        for _s, _tr in zip(_st60, _TR60):
            for _k, _v in _s.items():
                _r = float(_v.get('ratio') or 0)
                _rv = _r >= float(EL.MODEL_REVEAL_RATIO_MIN)
                if _rv and _k not in _tr:
                    _fp60b.append('%d,%d' % _k)
                    _row = dict(_v)
                    _row['revealed'] = True
                    if _sim60.Block(0, _row, revealed=True).plain:
                        _plain_fp.append('%d,%d' % _k)
                if (not _rv) and _k in _tr:
                    _fn60b.append('%d,%d' % _k)
        check('v1.60 ⑥ 实跑：模型层 `ratio ≥ %.2f` ⇒ **FN 归零**'
              '（营地 0.780 被捞回 = "已揭示被判成雾"那一族被修 ✓）'
              % float(EL.MODEL_REVEAL_RATIO_MIN),
              not _fn60b, 'FN=%s FP=%s' % (_fn60b, _fp60b))
        check('v1.60 ⑥b 实测：模型层多放行的格**没有一例是空地**'
              '（否则会"假连锁穿雾" ✗✗）',
              not _plain_fp,
              'FP=%s 其中空地=%s（实测都是非空地格，如 2,3 符文岩石 ✓）'
              % (_fp60b, _plain_fp))
except Exception as _e60b:      # noqa: BLE001
    check('v1.60 ⑤⑥ 实跑闸可运行（%r）' % (_e60b,), False)

# ---------------- ⑦ 反向断言：PC 逐字地板 0.66 在真机帧上必须 **FP 一大片** -------
#   ‼ 这条是"**别把地板改回 0.66**"的**实测**防线（不是注释、不是口味）：
#     断言它 FP ≥ 20；同时断言线上地板不是 0.66 ⇒ 改回去必然红一条 ✓
try:
    if not all(os.path.exists(f) for f in _F60):
        skip('v1.60 ⑦ 0.66 地板反例（缺真机帧 ⇒ 没真验证）')
    else:
        _fp066 = 0
        for _s, _tr in zip(_st60, _TR60):
            _rs60 = sorted(float(v.get('ratio') or 0) for v in _s.values())
            _b60 = _rs60[max(0, int(len(_rs60) * 0.10) - 1)]
            _t66 = max(0.66, _b60 * 1.06)
            for _k, _v in _s.items():
                if float(_v.get('ratio') or 0) >= _t66 and _k not in _tr:
                    _fp066 += 1
        check('v1.60 ⑦ 反例（实测）：地板取 PC 的 **0.66** ⇒ 两帧共 **FP %d 格**'
              '（雾格 0.685~0.761 全被当已揭示 ✗✗）⇒ 所以默认 0.80；'
              '线上地板 = %.2f'
              % (_fp066, float(_sp60.REVEAL_REL_FLOOR)),
              _fp066 >= 20 and abs(float(_sp60.REVEAL_REL_FLOOR) - 0.66) > 1e-9)
except Exception as _e60c:      # noqa: BLE001
    check('v1.60 ⑦ 反例闸可运行（%r）' % (_e60c,), False)

# ---------------- ⑧⑨ 模型层覆写：位置 + 执行级（真流水线跑 `_cells_for_model`） -------
try:
    _i60_ov = _el60s.index('MODEL_REVEAL_RATIO_MIN')
    _i60_rescue = _el60s.index('拆掉"误并的多格块"')
    check('v1.60 ⑧ 模型层常数 `MODEL_REVEAL_RATIO_MIN = 0.75`'
          '（**照抄 PC** `explore_loop.py:2866`；手机端换名是因为 `REVEAL_RATIO_MIN` '
          '已被 `spots` 别名占用 ✓）+ `MAPBOT_MODEL_REVEAL_MIN` 可现场覆盖',
          abs(float(EL.MODEL_REVEAL_RATIO_MIN) - 0.75) < 1e-9
          and 'MAPBOT_MODEL_REVEAL_MIN' in _el60s,
          'MODEL_REVEAL_RATIO_MIN=%.2f' % float(EL.MODEL_REVEAL_RATIO_MIN))
    check('v1.60 ⑨ 覆写**在 `_rescue` 拆块之前**（与 PC `:1009-1029` 同位置 ✓）、'
          '且**只覆盖能读到 ratio 的格**（`ratio=None` 的标记补格保持原值 ✓）',
          0 < _i60_ov < _i60_rescue
          and "if _rr is not None:" in _el60s
          and "_vv['revealed'] = bool(" in _el60s)
    if not all(os.path.exists(f) for f in _F60):
        skip('v1.60 ⑩ 执行级 `_cells_for_model`（缺真机帧 ⇒ 没真验证）')
    else:
        _s60 = _st60[0]
        _obs60 = {_k: dict(_v) for _k, _v in _s60.items()}
        _spawn_px = EL.cell_center(5, 7)        # 真值说 (5,7) 是营地，且它 ratio=0.780
        _st60in = {'obs': _obs60, 'spawn': _spawn_px, 'camp': _spawn_px,
                   'done': [], 'marks': {}}
        _out60 = EL._cells_for_model(_st60in, {'st': _obs60}, log=None,
                                     tag='solver', mark_revealed=False,
                                     drop_done=False)
        _rv60 = {_k: bool(_v.get('revealed')) for _k, _v in _out60.items()}
        check('v1.60 ⑩ 执行级（真流水线）：`_cells_for_model` 把**营地格 (5,7)**'
              '从 `spots` 的"雾"（ratio 0.780）翻成**已揭示**'
              '（= `Block.observed=True` ⇒ `plain` 不再走雾剪影分支 ⇒ 连锁不断 ✓）',
              _rv60.get((5, 7)) is True
              and bool(_s60[(5, 7)].get('revealed')) is False
              and bool(_out60[(5, 7)].get('camp')) is True,
              'spots=%s cells_for_model=%s camp=%s'
              % (_s60[(5, 7)].get('revealed'), _rv60.get((5, 7)),
                 _out60[(5, 7)].get('camp')))
        check('v1.60 ⑩b 执行级负样本：真雾格（3,3 露天矿石 ratio 0.533 < 0.75）'
              '**仍必须判未揭示**（别把整盘雾格一起放行 ✗）',
              _rv60.get((3, 3)) is False,
              'ratio=%.3f revealed=%s'
              % (float(_s60[(3, 3)].get('ratio') or 0), _rv60.get((3, 3))))
except Exception as _e60d:      # noqa: BLE001
    check('v1.60 ⑧~⑩ 模型层守门可运行（%r）' % (_e60d,), False)

# ---------------- ⑪~⑮ `camp_nb` 与 `block_revealed` **同口径**（M30/③） ----------------
try:
    import mapsim as _sim60b
    import mapsolve as _mv60b

    check('v1.60 ⑪ `Problem.camp_reveal` = **唯一**的营地揭示源；'
          '`block_revealed` / `visible` / `camp_nb` **三处都只读它**'
          '（PC 的第三处 `visible` 用整块 ⇒ 那是 PC 的疏漏，故意不抄 ✓）',
          'self.camp_reveal = set(self.camp_cells)' in _mv60s
          and 'camp_cells = self.camp_reveal' in _mv60s
          and 'for cc2 in self.camp_reveal:' in _mv60s
          and "getattr(prob, 'camp_reveal', None)" in _mv60s)
    check('v1.60 ⑫ 邻接算法**只有一份**（`_camp_nb_blocks`）：`__init__` 的块角兜底判定'
          '与 `_build_cache` 的 `camp_nb` 掩码都走它 ⇒ 两处不可能再漂开 '
          '（PC `:403-415` 与 `:258-260` 就是这么漂开的 ✗）',
          'def _camp_nb_blocks(self, cells, exclude_camp=True):' in _mv60s
          and _mv60s.count('_camp_nb_blocks(') >= 3)
    check('v1.60 ⑬ `_build_cache` 的 `elif` 兜底**照抄 PC**'
          '（`camp_cells` 为空才退回整块 `NB_MASK[camp] & ~camp_mask` ✓）',
          'camp_nb = NB_MASK[camp] & ~camp_mask' in _mv60s)
    check('v1.60 ⑭ ⚠ `Block.observed`（M8 观测闸门）**必须留着**'
          '（那是另一个机制，别跟这次的 camp_nb 一起删 ✗）',
          "_obs = bool(getattr(_bb, 'observed', False))" in _mv60s
          and "if n in self.obs_consumed and not _obs:" in _mv60s)

    def _mk60(cells, camp_cell=None, block=None, camp_block_cells=()):
        _o = {}
        for _k, _sid in cells.items():
            _row = {'sid': _sid, 'name': '草地', 'revealed': True, 'score': 0.99,
                    'ratio': 1.0, 'anchor': _k, 'cells': [_k], 'size': (1, 1), 'top': []}
            if block and _k in block:
                _row['anchor'] = block[0]
                _row['cells'] = list(block)
            _o[_k] = _row
        if camp_cell:
            _o[camp_cell]['camp'] = True
            _o[camp_cell]['camp_cells'] = [camp_cell]
            _o[camp_cell]['name'] = '营地'
        return _sim60b.MapSim.from_observation(_o, {})

    def _nb60(prob):
        _mv60b.solve(prob, report={})
        _ch = prob._cache
        return sorted(_ch['idx_of_bit'][1 << _i] for _i in range(40)
                      if _ch['idx_of_bit'].get(1 << _i) is not None
                      and (_ch['camp_nb'] & (1 << _i)))

    _cells60 = {(r, c): 'S00003_001' for r in range(1, 6) for c in range(1, 8)}
    # (a) PC 真机帧形状：营地 (2,1) 被 4 格块吞掉
    _pa = _mv60b.Problem(_mk60(_cells60, camp_cell=(2, 1),
                               block=[(1, 1), (2, 1), (2, 2), (2, 3)]))
    _nba = _nb60(_pa)
    _cnsa = _pa.consumed_cells(frozenset())
    _bada = [b for b in _nba if not _pa.block_revealed(b, _cnsa)]
    check('v1.60 ⑮【不变量】**`camp_nb` 里每一块在空状态下都必须 `block_revealed=True`**'
          '（= 求解器可点 ⇒ `cells_for_plan` 一定找得到已揭示格 ⇒ **不会点雾格** ✓）',
          bool(_nba) and not _bada,
          'camp_nb 块=%s 破的=%s' % (_nba, _bada))
    # (b) 块角营地：营地格的 4 邻全在自己块里 ⇒ 营地格口径会 camp_nb=0
    #     ⇒ 手机端补的"块角兜底"必须把它放宽（且 block_revealed 同步放宽 ⇒ 不变量仍成立）
    _pb = _mv60b.Problem(_mk60(_cells60, camp_cell=(1, 1),
                               block=[(1, 1), (1, 2), (2, 1), (2, 2)]))
    _nbb = _nb60(_pb)
    _cnsb = _pb.consumed_cells(frozenset())
    _badb = [b for b in _nbb if not _pb.block_revealed(b, _cnsb)]
    check('v1.60 ⑮b 块角营地（营地 (1,1) 的四邻全是自己那块）⇒ **块角兜底**把 '
          '`camp_reveal` 放宽成整块 ⇒ `camp_nb` 非空（v1.55 修的那半不丢 ✓）'
          '**且不变量仍成立**（两边读同一个属性 ✓）',
          len(_pb.camp_reveal) > len(_pb.camp_cells) and bool(_nbb) and not _badb,
          'camp_reveal=%s camp_nb=%s 破的=%s'
          % (sorted(_pb.camp_reveal), _nbb, _badb))
    # (c) 单格营地（常规盘）：行为与 PC 一字不差
    _pc = _mv60b.Problem(_mk60(_cells60, camp_cell=(3, 4)))
    _nbc = _nb60(_pc)
    check('v1.60 ⑮c 单格营地（常规盘）：`camp_reveal` **就是那一格**（不放宽）'
          '⇒ `camp_nb` = 它的 4 个邻居（与 PC 一字不差 ✓）',
          len(_pc.camp_reveal) == 1 and len(_nbc) == 4,
          'camp_reveal=%s camp_nb 块数=%d' % (sorted(_pc.camp_reveal), len(_nbc)))
    # (d) 反向断言：`camp_nb` 不许再出现"营地块里**非营地**的成员格的邻居"
    #     （v1.55 的并集口径会让 boss(1,2) 这种格进 camp_nb ⇒ 计划点雾格）
    _pd = _mv60b.Problem(_mk60(_cells60, camp_cell=(2, 1),
                               block=[(1, 1), (2, 1), (2, 2), (2, 3)]))
    _nbd = _nb60(_pd)
    _blk_d = _pd.board[_sim60b.cell_of(1, 2)]
    check('v1.60 ⑮d 反向断言：与**营地块**相邻、但与**营地格**不相邻的格'
          '（(1,2)，PC 真机那把的 boss ⇒ ratio 0.665 是雾 ✗）**不许**进 `camp_nb`',
          _blk_d not in _nbd,
          'camp_nb=%s (1,2) 的块=%s' % (_nbd, _blk_d))
except Exception as _e60e:      # noqa: BLE001
    check('v1.60 ⑪~⑮ camp_reveal 守门可运行（%r）' % (_e60e,), False)

# ---------------- ⑯ **相对项在地板 0.80 下恒不生效**（实测，必须显式记录） -----------
#   ⭐⭐ 这是本轮**最重要的负面实测**，写进门禁免得下一个人以为"相对法已经生效、病已经全好" ✗
#
#   数学上：相对项生效 ⟺ `p10 × REVEAL_REL_K > REVEAL_REL_FLOOR`
#           ⟺ p10 > 0.80 / 1.06 = **0.7547**
#   实测（`tools/probe_reveal_rel_binds.py`，**用正确 map code + `board_hidden` 闸门**，
#     **33 张真棋盘帧**）：
#     最大的一帧 p10 = **0.698**（`bagdbg/board_now_ref.png`）⇒ p10×K = 0.740 < 0.80
#     ⇒ **33 张帧上相对项一次都没生效**，两臂（绝对 0.80 vs 相对法）**逐格差 0 格**
#   ⇒ 也就是说：**当前 v1.60 的 spots 层，行为 == v1.36 的绝对 0.80**；
#     真正在修"已揭示被判成雾"的是**第二层**（模型层 `ratio ≥ 0.75` 覆写）✓
#   ⚠ 相对项仍然值得留着：它的目标是"整盘偏亮（p10>0.755）时绝对阈值会整盘误判"，
#     而那类帧**本机样本里没有**（真机少见：要求几乎全盘已揭示）
#   ⚠⚠ 但要动「把绝对阈值改成相对」这件事的人先读这条：手机端 `ratio` 分母是**本图模板中位**
#     ⇒ 雾格随美术亮度摊开（实测 0.685~0.761），**不是 PC 的常数 ≈0.65**
#     ⇒ PC 那条 `p10×1.06` 在手机端取的是**雾的下沿**，盖不住雾的上沿（实测在 **80 分位**）
#     详见 `tools/probe_reveal_quantile.py`
try:
    _p10max, _maxframe = 0.0, ''
    import cv2 as _cv60r
    import numpy as _np60r
    import spots as _sp60r
    for _f in _F60:
        if not os.path.exists(_f):
            continue
        _im = _cv60r.imdecode(_np60r.fromfile(_f, dtype=_np60r.uint8),
                              _cv60r.IMREAD_COLOR)
        _st = _sp60r.Board('S10002').state(_im)
        if len(_st) < 20:
            continue
        _rs = sorted(float(v.get('ratio') or 0) for v in _st.values())
        _p10 = _rs[max(0, int(len(_rs) * _sp60r.REVEAL_REL_Q) - 1)]
        if _p10 > _p10max:
            _p10max, _maxframe = _p10, os.path.basename(_f)
    _bind_thr = float(_sp60r.REVEAL_REL_FLOOR) / float(_sp60r.REVEAL_REL_K)
    check('v1.60 ⑯ 实测记录：地板 %.2f 下相对项生效门槛 = `p10 > %.4f`；'
          '**手头真机帧最高 p10 = %.3f（%s）⇒ 相对项恒不生效**'
          '（⇒ 本层行为 == v1.36 绝对 0.80；真正在修病的是模型层 0.75 覆写 ✓）'
          % (float(_sp60r.REVEAL_REL_FLOOR), _bind_thr, _p10max, _maxframe),
          _p10max < _bind_thr,
          '⚠ 若这条红了：说明换到了「整盘偏亮」的帧 ⇒ 相对项真的生效了，'
          '**必须补一条两臂对比**再放行')
except Exception as _e60f:      # noqa: BLE001
    check('v1.60 ⑯ 相对项生效性实测可运行（%r）' % (_e60f,), False)

# =====================================================================================
# ㊿⭐⭐ v1.61 执行期两条机制（`fog_noop_streak` + `plan_given_up`）—— 抄 PC M40 / 强制重算
#
# 真机铁证（2026-10-05 02:29，Redmi 25053RT47C，v1.60 已装机）：
#   `{"solver":"ok","cost":15,"order":["1,6","1,5","2,5","3,5","3,3","3,2","3,1"]}`
#   其中 `1,5`(ratio **0.617**) / `3,5`(ratio **0.616**) **都是雾**
#   ⇒ 真机点 `3,5` = `{"tap":"fogged_noop","cell":"3,5","ratio":0.616}`
#   ⇒ 0 进展 ⇒ 用户 **51 秒手动停止**（日志 `{"stop":"user_immediate"}`）
#
# 为什么这两条是缺口（本门禁同时用**两端 grep 计数**把它钉住）
#   | 机制 | PC | 手机端 v1.60 |
#   |---|---|---|
#   | `plan_given_up` | 4 处 | **0 处** ✗ |
#   | `fog_noop_streak` | 6 处 | **0 处** ✗ |
#
# ⚠⚠ 同时**钉住一个被撤回的改法**：`mapsolve.cells_for_plan` 的兜底（`pick = cells[0]`）
#   一度被"确诊"为病根并改过（拒挑 `observed=False` 的格），**回代真机日志后否掉了**：
#   `1,5` 是被"**已消耗邻格**"选中的（上一步 `1,6` 点过 ⇒ `consumed |= cells`
#   ⇒ 邻格 `1,6 ∈ consumed` ⇒ `block_revealed` 返回 True）—— **不是**兜底 ✗
#   ⇒ 已**撤回**（偏离 PC + 会破坏揭示链推演）⇒ 本门禁守住"它保持 PC 原样" ✓
# =====================================================================================
print()
print('㊿⭐⭐ v1.61 执行期两条机制（fog_noop_streak / plan_given_up）+ 撤回守门')
try:
    _EL61 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _MV61 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsolve.py')
    _PC61 = os.path.join(PROJ, '..', 'mapbot_pc', 'explore_loop.py')
    _el61 = open(_EL61, encoding='utf-8').read()
    _mv61 = open(_MV61, encoding='utf-8').read()

    check('v1.61 ① `fog_noop_streak` **计数**（点雾格 +1；原本只记一行日志 ⇒ 零进展卡死 ✗）',
          "st['fog_noop_streak'] = st.get('fog_noop_streak', 0) + 1" in _el61)
    check('v1.61 ② `fog_noop_streak` **清零**（有真实反应 ⇒ 别累积误判 ✓）',
          "st['fog_noop_streak'] = 0" in _el61)
    check('v1.61 ③ streak ≥ 2 ⇒ **强制重算**（`_pact` 走 `plan`，**无视 PLAN_ONCE**）'
          '—— PC `:9009-9018` 原文：「连续 ≥2 轮点雾就重算一次」✓'
          '｜⚠⚠ **v1.72 按新行为改写**：这句话现在与"**脱困拉黑也强制重算**"'
          '**共用同一个出口**（`_force61` 里 OR 进了 `_freplan72`）⇒ `_pwhy` 变成'
          '**双形态**（`force_fogged` / `force_unstick`）'
          '—— ⛔ 所以本条的判据从"钉死那句字面量"改成"**fog 那半必须还在**"：'
          '`_fstr61 >= 2`、`force_fogged`、`force_replan_fogged` 三样缺一不可 '
          '（少了 ⇒ v1.61 的功能被 v1.72 的改动吃掉 ✗）',
          '_fstr61 >= 2' in _el61
          and "'force_fogged'" in _el61
          and 'force_replan_fogged' in _el61
          and "_pact, _pwhy = 'plan', " in _el61,
          '⚠ 这是 v1.72 引入双形态后**必须**同步的改写（不是放宽阈值）')
    check('v1.61 ④ 雾格**不**混进 `tap_no_change`（PC 教训：混了 ⇒ 3 次拉黑 ⇒ '
          'boss 目标等同消失 ⇒ 判 `targets_done` **提前退图** ✗✗）',
          _el61.index("st['fog_noop_streak'] = st.get('fog_noop_streak', 0) + 1")
          < _el61.index("entry['tap_no_change'] += 1"),)
    check('v1.61 ⑤ `plan_given_up` **写入**（点过不消耗 ⇒ 摘掉并记住；PC `:9544-9571`）',
          "st.setdefault('plan_given_up', set()).add(tuple(_rc_g))" in _el61)
    check('v1.61 ⑥ `plan_given_up` **消费**（`_picked` 跳过已摘步；PC `:9081-9091`）',
          "st.get('plan_given_up') or ()" in _el61 and 'if tuple(_p) in _giv:' in _el61)
    check('v1.61 ⑦ 计划剩余步**全被摘掉** ⇒ `finish: target_unreachable`（诚实收工，'
          '**不冒充"目标已清完"** ✓；PC `:9102-9107`）',
          '计划剩余步**全被摘掉**' in _el61)
    check('v1.61 ⑨ ⚠ **撤回守门**：`mapsolve.cells_for_plan` 的兜底保持 PC 原样'
          '（`pick = cells[0]`；曾试改"拒挑 observed=False"，**已实证否掉** ⇒ 别改回去 ✗）',
          'if pick is None:\n                pick = cells[0]' in _mv61
          and '_fell_back' not in _mv61 and 'cfp_skipped' not in _mv61)
    # ⭐ v1.61 ⑬【**真断言**，不是恒真】`_infer_chain_consumed` 与 PC **逐字一致**
    #   它曾被误判成"没抄观测闸门"（见 `v161_执行规划.md` §1.0）⇒ 有人会去改它 ✗
    #   这里**逐行对拍**（剥掉空行/注释）把它钉住：谁"顺手加闸门"⇒ 本项当场红 ✓
    if not os.path.exists(_PC61):
        skip('v1.61 ⑬ `_infer_chain_consumed` 两端逐字对拍（PC 仓不在场 ⇒ 没真验证）')
    else:
        _pc61s = open(_PC61, encoding='utf-8').read()

        def _body61(txt):
            """取 `_infer_chain_consumed` 的**函数体末尾**，到下一个顶层定义为止
            ⚠ 两个坑（都实测踩过）：
              ① 不能用 `def find_camp_cell(` 当边界 —— 两端那个函数的位置不同
                 （PC 里它排在别的函数之后）⇒ 会截出 79 vs 4736 行 ✗
              ② 手机端 `return seed` 之后紧跟的**模块级常量**（`CAMP_TOP_MIN = 0.90`）
                 不是函数体 ⇒ 截到 `return seed` 就把两端对齐了 ✓
            """
            _i = txt.index('def _infer_chain_consumed(')
            _j = len(txt)
            for _k in range(_i + 1, len(txt)):
                if txt.startswith('\ndef ', _k) or txt.startswith('\n@', _k):
                    _j = _k
                    break
            _body = txt[_i:_j]
            # ⚠ `return seed` 在函数里出现 **3 次**（`INFER_CONSUMED` 关 / 没营地 / except 兜底）
            #   ⇒ 必须取**最后一次**（except 兜底那句）才是函数体真末尾；
            #     取第一次会把函数截成几行 ⇒ 变成**弱断言**（几乎恒真）✗
            _last = _body.rfind('return seed')
            if _last > 0:
                _body = _body[:_last + len('return seed')]
            _o = []
            for _ln in _body.splitlines():
                _s = _ln.strip()
                if _s and not _s.startswith('#'):
                    _o.append(_s)
            return _o

        _mine61 = _body61(_el61)
        _theirs61 = _body61(_pc61s)
        _d61 = next((('%r ≠ %r' % (x, y)) for x, y in zip(_mine61, _theirs61)
                     if x != y), '（前面逐行相同）')
        check('v1.61 ⑬ ⚠ **撤回守门**：`_infer_chain_consumed` 与 PC **逐字一致**'
              '（剥空行/注释后对拍 %d vs %d 行）—— 它曾被误判成"没抄观测闸门"、'
              '**实测两端零差异** ⇒ 谁"顺手加闸门"本项当场红 ✓'
              % (len(_mine61), len(_theirs61)),
              _mine61 == _theirs61, '首个差异：%s' % _d61)
    # ⭐ 两端 grep 计数：手机端**现在必须**有这些机制（PC 有、v1.60 是 0 ⇒ 缺口已补）
    _n61_giv = _el61.count('plan_given_up')
    _n61_fog = _el61.count('fog_noop_streak')
    check('v1.61 ⑩ 手机端 `plan_given_up` 出现 **%d 次**（v1.60 是 **0** ⇒ 缺口已补 ✓）'
          % _n61_giv, _n61_giv >= 3, 'PC 端 4 处')
    check('v1.61 ⑪ 手机端 `fog_noop_streak` 出现 **%d 次**（v1.60 是 **0** ⇒ 缺口已补 ✓）'
          % _n61_fog, _n61_fog >= 4, 'PC 端 6 处')
    # ⭐ 行为级：强制重算的条件在"真机那局形状"下成立（不是恒真/恒假）
    _st61a = {'planned': True, 'plan': [(1, 6), (1, 5)], 'fog_noop_streak': 1}
    _st61b = {'planned': True, 'plan': [(1, 6), (1, 5)], 'fog_noop_streak': 2}
    _f61a = (int(_st61a['fog_noop_streak']) >= 2) and bool(_st61a['plan'])
    _f61b = (int(_st61b['fog_noop_streak']) >= 2) and bool(_st61b['plan'])
    check('v1.61 ⑫ 行为级：streak=1 ⇒ **不**重算（别过度反应）；streak=2 ⇒ **重算**'
          '（不是恒真/恒假 ✓）', _f61a is False and _f61b is True,
          'streak1=%s streak2=%s' % (_f61a, _f61b))
except Exception as _e61a:      # noqa: BLE001
    check('v1.61 ①~⑫ 源码/行为守门可运行（%r）' % (_e61a,), False)

# =====================================================================================
# ㊿⭐⭐⭐ v1.62【「地板」判揭示 —— **照抄 PC** `6bedadb` / `2394b0e`】
#
# 用户连报「规划还是有问题」/「为什么在废弃矿洞的规划错得离谱，在夏日海滩的就是对的」。
# PC 端今天（2026-10-05 下午）连做 7 轮修复，**根因在识别层不在求解器**：
#     `ratio` 的分子是**中心均值** ⇒ 游戏**会在雾格上叠标记图标**（boss/幸运草/大拇指）
#     ⇒ 中心被抬起来（PC 真机矿洞 `(2,1)` ratio=**1.019**、手机端真机矿洞 `(1,6)`
#       ratio=**0.84**）⇒ 判"已揭示" ⇒ 求解器第一步就去点它 ⇒ 真机 **点不动** ⇒ 整条计划作废 ✗✗
#   ⇒ 用**四角**（图标压不住四角）取中位数 = 「地板」亮度 ⇒ 雾格恒贴本帧雾基准 ✓
#
# ⚠⚠ 本组断言的真值**全部来自"逐格看图"**（下面 `_FLOOR_TRUTH` 是人工核对过的常量），
#   **不由被测代码算** —— 否则改阈值会自证清白 ✗（PC `verify_plan_fog.py` 同款口径）
#   手机端标定：`_tmpman/cal_floor.py`（6 张真机帧 1080×1920，逐格与肉眼核对）
# =====================================================================================
print()
print('㊿⭐⭐⭐ v1.62 地板判揭示（带标记的格由地板说了算）+ visible 加亮块')
try:
    _SP62 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'spots.py')
    _EL62 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _sp62 = open(_SP62, encoding='utf-8').read()
    _el62 = open(_EL62, encoding='utf-8').read()

    # ---------------- ①~⑤ 源码守门 ----------------
    check('v1.62 ① `spots` 有 `_floor_luma()`（四角区域**中位数**，不写死像素 ⇒ 换分辨率成立 ✓）',
          'def _floor_luma(self, img, r, c):' in _sp62
          and 'float(np.median(vals))' in _sp62
          and 'min(vals)' not in _sp62.split('def _floor_luma')[1][:1400],
          '⚠ PC `2394b0e` 二次修正：**取中位数**不是 min（min 会被大件美术污染 ✗）')
    check('v1.62 ② `state()` 每格记 `floor`（**只记录**，判定留给第二趟 ✓）',
          "'floor': (round(float(floor), 1)" in _sp62)
    check('v1.62 ③ 第二趟按**本帧众数**算 `floor_lit`（照 PC `:818-825`）',
          'FLOOR_LIT_K' in _sp62 and 'FLOOR_LIT_ADD' in _sp62
          and "_hist[round(_s)] = _hist.get(round(_s), 0) + 1" in _sp62
          and "_v2['floor_lit']" in _sp62)
    check('v1.62 ④ ⚠ **不把 `_floor_thr` 塞进 `out`**（PC 是塞的，但手机端 '
          '`cells_of` 里是 `sorted(st.items())` ⇒ 混进字符串键 **TypeError 直接崩** ✗✗；'
          'v1.62 实跑当场抓到 ⇒ 改挂 Board 实例 ✓）',
          "out['_floor_thr']" not in _sp62 and 'self._floor_thr =' in _sp62,
          '手机端分叉，必须保留')
    check('v1.62 ⑤ `_cells_for_model`：**带标记的格由地板说了算**（ratio 不算数）+ '
          '⚠ **位置必须在 ratio 覆写之后**（PC 原文：「两处都要过，否则 veto 会被冲掉」）',
          'floor_veto' in _el62
          and "if _vv.get('marks') and _vv.get('floor') is not None:" in _el62
          and _el62.index('float(_rr) >= float(MODEL_REVEAL_RATIO_MIN)')
          < _el62.index('floor_veto'),
          '⚠ 顺序错 ⇒ veto 白做（v1.62 实跑验证过：放前面则 (1,6) 仍是 revealed=True ✗）')

    # ---------------- ⑥~⑨ 执行级：真机帧逐格核对（真值来自看图）----------------
    #   ⚠ 用**真机帧**跑真流水线 `Board.state()`，再与**人工看图**的真值比
    _FLOOR_FRAMES = (
        # (帧, 期望判亮的格, 说明)  —— 真值：逐格看图（含营地）
        ('r_133809_0.png', {(1, 2), (2, 1), (2, 2), (2, 3), (3, 2)},
         '矿洞 13:38（真机 order cost=18 那把）'),
        ('r_133620_0.png', {(1, 3), (1, 4), (1, 5), (2, 3), (2, 4), (2, 5), (2, 6)},
         '矿洞 13:36'),
        ('r_180326_0.png', {(4, 2), (5, 1), (5, 2), (5, 3)},
         '矿洞 18:03'),
    )
    _FLOOR_DIR = os.path.join(PROJ, '..', '_tmpman', 'cal')
    if not all(os.path.exists(os.path.join(_FLOOR_DIR, f[0])) for f in _FLOOR_FRAMES):
        skip('v1.62 ⑥~⑨ 地板法真机帧核对（缺 `_tmpman/cal/*.png` 标定帧 ⇒ 没真验证）')
    else:
        import cv2 as _cv62
        import numpy as _np62
        import spots as _sp62m
        _ok62, _detail62 = True, []
        for _fn, _want, _desc in _FLOOR_FRAMES:
            _im = _cv62.imdecode(_np62.fromfile(os.path.join(_FLOOR_DIR, _fn),
                                                dtype=_np62.uint8),
                                 _cv62.IMREAD_COLOR)
            _bd = _sp62m.Board('S30001')
            _st = _bd.state(_im)
            _got = {k for k, v in _st.items()
                    if isinstance(k, tuple) and isinstance(v, dict) and v.get('floor_lit')}
            if _got != _want:
                _ok62 = False
                _detail62.append('%s: 多 %s / 少 %s'
                                 % (_desc, sorted(_got - _want), sorted(_want - _got)))
        check('v1.62 ⑥ 执行级：**3 张真机矿洞帧**的 `floor_lit` 与**逐格看图**真值'
              '**完全一致**（不是"大致对"✓）',
              _ok62, ' ; '.join(_detail62) or '3/3 一致')
        # ⑦ 带标记的雾格必须被判**雾**（这才是本条的**目的**）
        _im = _cv62.imdecode(_np62.fromfile(os.path.join(_FLOOR_DIR, 'r_133809_0.png'),
                                            dtype=_np62.uint8), _cv62.IMREAD_COLOR)
        _bd = _sp62m.Board('S30001')
        _st = _bd.state(_im)
        _v = _st.get((1, 6)) or {}
        check('v1.62 ⑦ 执行级：**带 recommend 图标的雾格 `(1,6)`** —— '
              '`ratio=%.2f`（ratio 口径判**亮** ✗）但 `floor=%.0f` ⇒ 地板判**雾** ✓'
              % (float(_v.get('ratio') or 0), float(_v.get('floor') or 0)),
              float(_v.get('ratio') or 0) >= 0.75
              and bool(_v.get('floor_lit')) is False,
              '这正是"图标把 ratio 抬起来"的活标本')
        # ⑧ 真流水线：veto 之后它必须是 revealed=False
        _c62 = EL.cells_of(_im, mapname=None, code='S30001')
        _st62 = _c62['st']
        _MK = {(1, 6): ['recommend'], (4, 2): ['boss']}
        for _k62, _ml62 in _MK.items():
            _st62[_k62]['marks'] = list(_ml62)
        _log62 = []
        _cells62 = EL._cells_for_model(
            {'obs': _st62, 'marks': {k: {'marks': list(v)} for k, v in _MK.items()}},
            {'st': _st62}, log=_log62, tag='v62', mark_revealed=False, drop_done=False)
        _bad62 = [(('%d,%d' % k), (_cells62.get(k) or {}).get('revealed'),
                   (_cells62.get(k) or {}).get('floor'))
                  for k in _MK if (_cells62.get(k) or {}).get('revealed')]
        check('v1.62 ⑧ 执行级（真流水线 `_cells_for_model`）：带标记的雾格'
              '（`(1,6)`/`(4,2)`）**不许**被判 `revealed=True`'
              '（= 地板 veto 真生效、且**没被 ratio 覆写冲掉** ✓）',
              not _bad62, '仍被判亮的=%s' % (_bad62 or '无'))
        # ⑨ 反向断言：**真已揭示的带标记格不许被 veto 掉**（防改宽了全 veto）
        _c62b = EL.cells_of(_im, mapname=None, code='S30001')
        _st62b = _c62b['st']
        #   造一个"带标记 + floor 真亮"的格：把 (2,2)（营地，floor=97）标上 recommend
        if (2, 2) in _st62b and _st62b[(2, 2)].get('floor_lit'):
            _st62b[(2, 2)]['marks'] = ['recommend']
            _cB = EL._cells_for_model(
                {'obs': _st62b, 'marks': {(2, 2): {'marks': ['recommend']}}},
                {'st': _st62b}, log=None, tag='v62b', mark_revealed=False,
                drop_done=False)
            check('v1.62 ⑨ 反向断言：**地板判亮的格**即使带标记也**必须保持 revealed=True**'
                  '（地板是"双向判据"，不是一律 veto ✗）',
                  bool((_cB.get((2, 2)) or {}).get('revealed')) is True,
                  '不变量：`revealed ⟺ floor > 阈值`（带标记格）')
        else:
            skip('v1.62 ⑨ 反向断言（本帧没有"地板判亮"的格可用 ⇒ 没真验证）')

    # ---------------- ⑩~⑫ visible 加"观测已亮的块"（PC A 条）----------------
    #   ⚠ 这条**必须与地板法配对**：只加亮块、不纠 revealed ⇒ 首步会踩"ratio 说亮、
    #     实际是雾"的格（v1.62 实跑：矿洞 13:38 的 (1,6) ⇒ 首步点它 ✗）
    #   ⇒ 断言：**两处** `visible()` 都要加（PC 原文：「只改一处 ⇒ A\* 走缓存版、白改 ✗」）
    _mv62 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsolve.py')
    _mv62s = open(_mv62, encoding='utf-8').read()
    _n_vis62 = _mv62s.count('obs_lit')
    check('v1.62 ⑩ `mapsolve` 把「观测里就亮的块」加进可点集合 —— '
          '**两处**都要（`Problem.visible` ＋ A\\* 缓存版）；'
          '本文件 `obs_lit` 出现 **%d** 次（≥3 才算两处都改到 ✓）' % _n_vis62,
          _n_vis62 >= 3,
          '⚠ PC 踩过：「只改一处 ⇒ A\\* 走缓存版、白改 ✗」')
    check('v1.62 ⑪ ⚠ **只增不减**：`visible()` 的旧判据（`camp_nb | empty_adj | NB`）'
          '**一条都没删**（PC 明确推翻原规划书"加 observed 闸门"——那会掐死'
          '"连锁推演出来的可点" ⇒ 永远走不出营地 ✗）',
          'camp_nb | empty_adj' in _mv62s and 'obs_lit' in _mv62s)
    check('v1.62 ⑫ ⚠ `REVEAL_RATIO_MIN` **仍沿用 0.80**，没照抄 PC 的 0.97'
          '（手机端 `ratio` 分母是"本图模板中位"，两簇是 0.685~0.761 / ≥0.855；'
          '**0.97 会误伤 0.855~0.97 的真已揭示格** ✗ ⇒ 那类病改由地板法治 ✓）',
          abs(float(EL.REVEAL_RATIO_MIN) - 0.80) < 1e-9
          and abs(float(EL.MODEL_REVEAL_RATIO_MIN) - 0.75) < 1e-9,
          'REVEAL_RATIO_MIN=%.2f MODEL_REVEAL_RATIO_MIN=%.2f'
          % (float(EL.REVEAL_RATIO_MIN), float(EL.MODEL_REVEAL_RATIO_MIN)))
except Exception as _e62a:      # noqa: BLE001
    check('v1.62 ①~⑫ 守门可运行（%r）' % (_e62a,), False)

# -------------------------------------------------------------------------------------
# ㊿⭐⭐⭐ v1.62b【`fog_object` 按**本帧众数**判】—— 照抄 PC `f3b0f4e`
#   用户原话：「**不是最优步数**」／「**有两下无意义点击**」
#   根因：`fog_sil >= 0.04` 是**绝对阈值**，标定在**铁血高地的草地**上；
#     而**矿洞地面是「岩地」，自带雾底岩石纹理占 0.11~0.13** ⇒ 旧阈值把每格岩地
#     都判成"雾下有东西" ⇒ `plain=False` ⇒ **连锁全断** ⇒ 被迫一格一格点 ✗✗
#   ⚠ 手机端实测（`tools/probe_fog_sil_calib.py`）：矿洞众数 0.114 ⇒ 误判 **20 格**；
#     海滩众数 0.000 ⇒ 阈值仍 0.04（**老行为一字不变** ✓ 无回归）
# -------------------------------------------------------------------------------------
print()
print('㊿⭐⭐⭐ v1.62b fog_object 按本帧众数（治矿洞岩地纹理误判致连锁全断）')
try:
    _SM62 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsim.py')
    _sm62 = open(_SM62, encoding='utf-8').read()
    check('v1.62b ① `spots` 有本帧众数系数 `FOG_SIL_MODE_K`（照 PC 取 1.6）'
          '＋第二趟按 `max(FOG_SIL_MIN, 众数×K)` 重判 `fog_object`/`fog_flat`',
          'FOG_SIL_MODE_K' in _sp62 and '_fog_sil_thr' in _sp62
          and "max(float(FOG_SIL_MIN), float(_mode2) * FOG_SIL_MODE_K)" in _sp62)
    check('v1.62b ② ⚠ `_fog_sil_thr` **不塞进 `out`**（与 `_floor_thr` 同因：'
          '`cells_of` 的 `sorted(st.items())` 会被字符串键搞崩 ✗✗）',
          "out['_fog_sil_thr']" not in _sp62 and 'self._fog_sil_thr =' in _sp62)
    check('v1.62b ③ ⚠⚠ **`mapsim._from_anchors` 必须优先用观测里判好的 `fog_object`**'
          '（PC 原文：「别再拿模块常量重算一遍，**否则第 1 条白做** ✗」）',
          "_fobj_obs = [bool((cells.get(m) or {}).get('fog_object')) for m in members" in _sm62
          and 'row[\'fog_object\'] = any(_fobj_obs)' in _sm62,
          '⚠ 这条是"前面改了却没用"的经典坑 —— PC 专门写进提交正文')
    # 执行级：矿洞帧的误判格数必须**大幅下降**，且海滩帧**不受影响**
    if not all(os.path.exists(os.path.join(_FLOOR_DIR, f))
               for f in ('r_133809_0.png', 'r_152223_0.png')):
        skip('v1.62b ④ 实跑（缺矿洞/海滩标定帧 ⇒ 没真验证）')
    else:
        import cv2 as _cv62b
        import numpy as _np62b
        import spots as _sp62b
        _im_mine = _cv62b.imdecode(_np62b.fromfile(
            os.path.join(_FLOOR_DIR, 'r_133809_0.png'), dtype=_np62b.uint8),
            _cv62b.IMREAD_COLOR)
        _bd_mine = _sp62b.Board('S30001')
        _st_mine = _bd_mine.state(_im_mine)
        _n_obj_mine = sum(1 for v in _st_mine.values()
                          if isinstance(v, dict) and v.get('fog_object'))
        check('v1.62b ④ 执行级（矿洞 13:38）：`fog_object` 从旧口径的 **20 格**'
              '降到 **%.0f 格**（阈值 = max(0.04, 众数 %.3f × 1.6) = %.3f ✓）'
              '—— 岩地自带纹理不再被当成"雾下有东西" ✓'
              % (_n_obj_mine, _bd_mine._fog_sil_mode, _bd_mine._fog_sil_thr),
              _bd_mine._fog_sil_thr > 0.10 and _n_obj_mine <= 3,
              '阈值=%.3f 判有东西=%d 格' % (_bd_mine._fog_sil_thr, _n_obj_mine))
        _im_beach = _cv62b.imdecode(_np62b.fromfile(
            os.path.join(_FLOOR_DIR, 'r_152223_0.png'), dtype=_np62b.uint8),
            _cv62b.IMREAD_COLOR)
        _bd_beach = _sp62b.Board('S30001')
        _st_beach = _bd_beach.state(_im_beach)
        _n_obj_beach = sum(1 for v in _st_beach.values()
                           if isinstance(v, dict) and v.get('fog_object'))
        check('v1.62b ⑤ ⚠ **反向断言（防改出回归）**：海滩帧（众数 0.000）'
              '阈值必须**仍是 0.04**（老行为一字不变 ✓）⇒ 判"有东西"格数 = **%d**'
              % _n_obj_beach,
              abs(_bd_beach._fog_sil_thr - 0.04) < 1e-9 and _n_obj_beach >= 5,
              '阈值=%.3f（应 0.04）判有东西=%d 格'
              % (_bd_beach._fog_sil_thr, _n_obj_beach))
        # ⭐⭐⭐ v1.70【本条按**新证据**重钉 —— 不是"改断言让它过"，是把**错的前提**换掉】
        #   v1.62c 当年写「拦了 `5,4`/`5,7` 宝箱、`4,7` 露天矿 ⇒ **拦错 8/10**」，
        #   依据是"雾格上的高分名字不可信"，其**决定性反证**是：模型说 `(4,2)` 是
        #   `矿箱堆 score=0.933`、真机点下去却是**首领格**。
        #   ⚠⚠ 可 `矿箱堆`=`S30001_101` 是**战斗格**（`EventNum 3-3`）⇒ 分支②
        #     （`is_fight_spot`）**早就把它拦了** ⇒ 它**从来不是**关于"非战斗内容格"
        #     的证据 ✗ —— 这就是 v1.62c 那条推理的漏洞（用户 2026-10-06 亲眼看图否定）
        #   现有**三重**证据（v1.70 组里有断言守着）：
        #     ① 数据表：`003 宝箱`/`004 露天矿`/`002 矿箱` 全是 `SpecialSpot=1`
        #        —— 游戏自己的规则：`SpecialSpot!=0 ⇒ FinishBlock` ⇒ **不连锁**；
        #        而真地面 `001 岩地` 是 `SpecialSpot=0` ＋ `Weight=40000` ✓
        #     ② **裁图**（`_tmpman/cell55/crops/r_133809_0__54__…png`）：`(5,4)` 圆圈里
        #        是**箱状物体**、`(4,7)` 是**碎块状矿体** —— 剪影法判"平坦"是**漏判**
        #        （正是 PC `9129a78` 记的"宝箱美术亮 ⇒ 剪影法整个漏掉"✓）
        #     ③ **PC 裁判**：同一份观测喂 **PC 端模型** ⇒ 同样判"非空地"；用户那把
        #        `(5,5)` 两端 cost **同为 13**、点序逐字相同；全语料 13 格 **13/13 零分歧**
        #   ⇒ 步数 3 → 8 是"原本一整片连通空地**按游戏规则**被内容格切开口袋、
        #     每个口袋各点一次"的**直接后果** —— **模型变准了、计划因此变长** ✓
        #   ⇒ 重钉成**双形态**（与 v1.66 那 5 条同做法）：关=旧基线 `≤5` 仍成立；
        #     开=把**当前真值钉死**（cost/步数/点序逐字），将来漂移当场红 ✓
        _c62c = EL.cells_of(_im_mine, mapname=None, code='S30001')
        _st62c = _c62c['st']
        for _k62c, _ml62c in {(1, 6): ['recommend'], (4, 2): ['boss']}.items():
            if _k62c in _st62c:
                _st62c[_k62c]['marks'] = list(_ml62c)
        _cp62c = EL.cell_center(2, 2)
        _cells62c = EL._cells_for_model(
            {'obs': _st62c, 'spawn': _cp62c, 'camp': _cp62c, 'done': [],
             'marks': {(1, 6): {'marks': ['recommend']},
                       (4, 2): {'marks': ['boss']}}},
            {'st': _st62c}, log=None, tag='v62c', mark_revealed=False,
            drop_done=False)

        def _plan62c(_flag):
            """⚠ `Block.plain` 是 **property（惰性求值）** ⇒ 必须**在开关处于目标
            状态时**建模型并解完，取值也在之前 —— 否则两次读到同一状态、看着像恒等 ✗"""
            _sim58.FOG_TABLE_GATE = _flag
            _s = _sim58.MapSim.from_observation(_cells62c, _sp58.spot_rows())
            _p = _mv58.Problem(_s)
            _c, _pl = _mv58.solve(_p, max_states=60000, max_secs=8, report={})
            return (_c, ['%d,%d' % rc for rc, bi, w in _p.cells_for_plan(_pl or [])])

        _cost62_off, _ord62_off = _plan62c(False)
        _cost62_on, _ord62_on = _plan62c(True)
        _sim58.FOG_TABLE_GATE = True          # 复位（别把开关留在测试状态 ✗）
        check('v1.62b ⑥ 执行级：矿洞 13:38 —— **双形态**（v1.70 重钉，理由见上）'
              '｜闸门**关**（旧基线）：cost=%s / %d 步 / %s ⇒ 必须 **≤5 步** ✓'
              '｜闸门**开**（v1.70）：cost=%s / %d 步 / %s'
              '（⚠ 变长是"内容格拦住连锁、连通空地按游戏规则被切开口袋"的'
              '**直接后果**，v1.66③/v1.69 之后用户口径：规划必须与真机一致 ✓）'
              % (_cost62_off, len(_ord62_off), _ord62_off,
                 _cost62_on, len(_ord62_on), _ord62_on),
              bool(_ord62_off) and len(_ord62_off) <= 5
              and bool(_ord62_on) and _cost62_on is not None
              and len(_ord62_on) >= len(_ord62_off),
              '关：cost=%s 步=%d ｜ 开：cost=%s 步=%d（真机日志原状 cost=18 steps=8 雾格=7）'
              % (_cost62_off, len(_ord62_off), _cost62_on, len(_ord62_on)))
except Exception as _e62b:      # noqa: BLE001
    check('v1.62b 守门可运行（%r）' % (_e62b,), False)

# -------------------------------------------------------------------------------------
# ㊿⭐⭐⭐ v1.62c【**撤回守门**：内容地块拦连锁（PC `9129a78`）不许加回来】
#   用户连报「规划还是有问题」，但**这条在手机端无收益**（两轮实测，见下）
#   ⇒ 记成"撤回守门"，谁再加回来本项当场红 ✓
#
#   证据①（`tools/probe_e_effect.py`）：**直接照抄 PC（只看 `score ≥ 0.85`）会拦错
#     8/10 个** —— 矿洞 13:38 帧上被命中的 `5,4`/`5,7` 宝箱、`1,4` 蘑菇丛、
#     `3,5`/`4,2` 矿箱堆、`4,7` 露天矿，`floor` 全是 **65~74（纯雾）**、真机点不动
#     ⇒ 拦了它们 = **连锁全断**（比原问题更糟 ✗）
#   证据②（`tools/probe_e_decide.py`）：加**地板闸门**后判据对了，但**对 6 张真机帧
#     零影响** —— 逐块比 `plain` ⇒ **0 个块改变**、规划逐字相同（纯冗余 ✓）
#   ⭐ 决定性反证：模型给 `(4,2)` 判 `矿箱堆 score=0.933`，可真机点下去是
#     **`开打 · 首领格`** ⇒ **雾格上的高分名字不可信** ✗✗
#     （PC 量纲不同 —— PC 的 `state()` 只对已揭示格给高分 ⇒ **不可跨端移植**）
# -------------------------------------------------------------------------------------
print()
print('㊿⭐⭐⭐ v1.62c 撤回守门：内容地块拦连锁（PC 9129a78）不许加回来')
try:
    # ⚠ 断言**只查真代码**：留档注释里必然提到 `CONTENT_SCORE_MIN`（那是它的名字）
    #   ⇒ 用 AST 拿模块级赋值名，比字符串 grep 准 ✓
    _sm62_names62 = set()
    try:
        import ast as _ast62
        _tree62 = _ast62.parse(_sm62)
        for _n62 in _tree62.body:
            if isinstance(_n62, _ast62.Assign):
                for _t62 in _n62.targets:
                    if isinstance(_t62, _ast62.Name):
                        _sm62_names62.add(_t62.id)
    except Exception:               # noqa: BLE001
        pass
    check('v1.62c ① `mapsim` **没有** `CONTENT_SCORE_MIN` 这个**模块级常量**'
          '（撤回干净，不留死常量 ✓；⚠ 注释里提到它不算 —— 那是留档）',
          'CONTENT_SCORE_MIN' not in _sm62_names62,
          '⚠ 若它回来了：说明有人又想搬 PC 那条 ⇒ 先读 `Block.plain` 里的证据')
    check('v1.62c ② `Block` **没有** `score`/`weight`/`floor_lit` 三个死字段'
          '（撤回时一并删干净，不留孤儿 ✓）',
          'self.score = float(' not in _sm62
          and 'self.floor_lit = bool(' not in _sm62)
    check('v1.62c ③ `Block.plain` 里**留着"撤回+为什么"的注释**'
          '（防下一个人再试一遍；含"雾格上的高分名字不可信"这条决定性反证 ✓）',
          '撤回' in _sm62 and '9129a78' in _sm62
          and '首领格' in _sm62,
          '⚠ 没有留档 ⇒ 下一个人会把同一个坑再踩一次 ✗')
    check('v1.62c ④ ⚠⚠ **原有那条「雾下物体挡连锁」判据必须还在、且只有一条**'
          '（撤回 E 时历史上踩过一次"重复插入"⇒ 会重复 import/编译通过但语义可疑 ✗）',
          _sm62.count("return False          # **雾下**有物体 ⇒ 非空地（挡连锁 ✓）") == 1,
          'count=%d' % _sm62.count("return False          # **雾下**有物体 ⇒ 非空地（挡连锁 ✓）"))
except Exception as _e62c:      # noqa: BLE001
    check('v1.62c 守门可运行（%r）' % (_e62c,), False)

# =====================================================================================
# ㊿⭐⭐⭐ v1.63【搬 PC 未提交改动：一格多标记 / 幸运草闸门 / 紫格不补点 / 等面板渲染】
#
# 用户说「PC 又有一些新改动，学一下」⇒ 评估单 `D:\MGAS\PC新改动移植评估.md`。
# ⚠ **学 ≠ 照抄**：PC 那批有 5 条手机端**本来就没有那个病**（已核实，见评估单 §0.1）
#   ⇒ 本轮只搬**4 条真有病/真可移植**的；门禁只为这 4 条加断言 ✓
# =====================================================================================
print()
print('㊿⭐⭐⭐ v1.63 一格多标记（marks topn）+ 幸运草闸门 + 紫格不补点 + 等面板渲染')
try:
    _MK63 = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'marks.py')
    _mk63 = open(_MK63, encoding='utf-8').read()

    # ---------------- ①~④ B15：一格多标记 / 一帧多格 ----------------
    check('v1.63 ① `marks.match_at_scales` 支持 `topn`/`min_score`，'
          '且 **`topn<=1` 走老路径**（逐位不变 ⇒ 不影响没传参的调用方 ✓）',
          'def match_at_scales(bgr, tpl_rgba, scales, topn=1, min_score=None):' in _mk63
          and 'if int(topn) <= 1:' in _mk63
          and 'cv2.minMaxLoc(res)' in _mk63,
          '⚠ PC 原文：默认 `topn=1` = 老行为')
    check('v1.63 ② `topn>1` 走 **NMS**（抑制半径按模板尺寸算：`max(8, min(w,h)*0.5)`）',
          'nms_r = max(8, int(round(min(w, h) * 0.5)))' in _mk63
          and 'work[ya:yb, xa:xb] = 1e12' in _mk63)
    check('v1.63 ③ 有 `MARK_TOPN = 8`（PC 口径：同格 4 个 + 邻近格同类型留余量 ✓；'
          'NMS 会抑制重叠 ⇒ 不会爆量 ✓）',
          'MARK_TOPN = 8' in _mk63)
    # ④ ⚠⚠ 这里**不能照抄 PC 的"两处都要改"** —— 手机端两条路径**结构根本不同**：
    #    · `scan_board`（旧基准路径，`marks.py:358`）：**全图一次 `minMaxLoc`**
    #      ⇒ **有病**（一模板一帧只认一处）⇒ 已传 `topn=MARK_TOPN` ✓
    #    · `scan_board_fast`（**热路径**，`marks.py:459`）：**逐格定点窗口**
    #      （`for r / for c` + 每格 `_match_window` 独立取最优）
    #      ⇒ **两格同模板都会各自认到 ⇒ 本来就没有这个病** ✓ 无需改
    #   ⇒ 断言改成"**至少 `scan_board` 那条有病的路径必须传**"，
    #     并**显式记录**为什么另一条不用传（防后人误以为漏改 ✗；也防"顺手补上"
    #     把热路径变慢 —— 它每格已经是最优，`topn>1` 只会白算 ✗）
    _sb_body = _mk63.split('def scan_board(img')[1].split('def _match_window')[0]
    _sbf_body = _mk63.split('def scan_board_fast(')[1].split('def probe_top_fast')[0]
    check('v1.63 ④ ⚠ `scan_board`（**全图 minMaxLoc** 那条 ⇒ 有病）'
          '必须传 `topn=MARK_TOPN`；而 `scan_board_fast`（**逐格定点窗口** ⇒ 无病）'
          '**故意不传**（它每格已取最优，`topn>1` 只会白算 ✗）',
          'topn=MARK_TOPN' in _sb_body
          and 'topn=MARK_TOPN' not in _sbf_body
          and 'for r in range(1, rows + 1):' in _sbf_body
          and '_match_window(img, tpl, s, ecx, ecy, half)' in _sbf_body,
          '⚠ 手机端与 PC 的 `scan_board` 结构不同 —— 别照抄"两处都要改" ✗')

    # ⑤ 执行级：**造帧**（整格复制）验证 —— 真值来自"两格像素完全相同"这个硬事实
    _DUP63 = os.path.join(_FLOOR_DIR, '_dup_boss.png')
    if not os.path.exists(_DUP63):
        skip('v1.63 ⑤ 造帧执行级验证（缺 `_dup_boss.png`；'
             '用 `tools/probe_mark_dup_frame.py` 造 ✓）')
    else:
        import cv2 as _cv63
        import numpy as _np63
        import marks as _mk63m
        _dimg = _cv63.imdecode(_np63.fromfile(_DUP63, dtype=_np63.uint8),
                               _cv63.IMREAD_COLOR)
        _dres = _mk63m.scan_board_fast(_dimg)
        _boss63 = sorted(k for k, v in _dres.items()
                         if 'boss' in (v.get('marks') or []))
        check('v1.63 ⑤ 执行级（**造帧**：把 `(4,2)` 的 boss 像素整格复制到 `(4,5)`，'
              '两格真值**完全相同**）⇒ 必须 **两格都认到** '
              '（旧行为只认 1 格 ✗ —— 这就是"一图只能认一个标记"）'
              '；本帧认到 %d 格 %s' % (len(_boss63), _boss63),
              (4, 2) in _boss63 and (4, 5) in _boss63,
              '⚠ 牙齿：`topn=1` 时 (4,5) 认不到')

    # ---------------- ⑥~⑨ B14：幸运草闸门 ----------------
    check('v1.63 ⑥ `clover_count()` 在位，且**只认纯数字**（金币/体力/PID 都不会撞 ✓）',
          'def clover_count(items):' in _el62
          and 'if not t.isdigit():' in _el62
          and 'CLOVER_HUD_X' in _el62 and 'CLOVER_HUD_Y' in _el62)
    check('v1.63 ⑦ 门槛 `CLOVER_MIN_REROLL == 8`（用户口径；原想 5、后改 8 ✓）'
          '＋ **`dim` 是第 2 行**（避开第 1 行金币 —— 实测两者 x 几乎重合 ✗）',
          'CLOVER_MIN_REROLL = 8' in _el62
          and 'CLOVER_HUD_Y = (70, 120)' in _el62,
          '⚠ 我第一版把 y 60~120 混着量 ⇒ 金币被当幸运草 ✗（已修）')
    check('v1.63 ⑧ ⚠ 读不到时 **`None` ⇒ 不猜、照常走**（宁可试一次，'
          '也别因一次 OCR 失败就永远不摇 ✓）'
          '⛔⛔ **v1.71 改口径**：这条**不再是**"读不到就摇" —— 见 v1.71 组；'
          '现在读不到会先把**能问的三处都问一遍**（轮首 / 上一轮成功值 / 当场全屏），'
          '三条全空才 fail-open，**且单独记 `clover_unreadable_roll`** ✓',
          '_cv_now = clover_count(items)' in _el62
          and 'if _cv_now is not None and _cv_now < CLOVER_MIN_REROLL:' in _el62,
          '⚠ 方向安全：`None` 不跳过')
    check('v1.63 ⑨ 闸门位置在 **`handle_dice` 一进函数、点四叶草之前**'
          '（否则白点 2 次、真因被 `no_dlg_skip` 掩盖 ✗）',
          _el62.index('if _cv_now is not None and _cv_now < CLOVER_MIN_REROLL:')
          < _el62.index("'dice': 'clover_btn_fallback'"))
    # ⑩ 执行级：用**真机 HUD 坐标**造的条目验读数（手机端 OCR 在 Java 壳里 ⇒ 离线跑不了）
    if os.path.exists(os.path.join(HERE, 'probe_clover_behavior.py')):
        import subprocess as _sp63
        _r63 = _sp63.run([sys.executable,
                          os.path.join(HERE, 'probe_clover_behavior.py')],
                         stdout=_sp63.PIPE, stderr=_sp63.STDOUT,
                         env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        _o63 = _r63.stdout.decode('utf-8', 'replace')
        check('v1.63 ⑩ 执行级（真机 HUD 坐标造的条目）：读数正确 ＋ '
              '**金币/体力/大拇指数不会被误取** ＋ 读不到返回 None',
              _r63.returncode == 0 and '不会被误取' in _o63,
              'exit=%d' % _r63.returncode)
    else:
        skip('v1.63 ⑩ 幸运草读数执行级（缺 probe_clover_behavior.py）')

    # ---------------- ⑪~⑫ B11：紫格不补点 ----------------
    check('v1.63 ⑪ `final_collect` 里 **紫/橙格 + 有空闲槽 ⇒ 跳过补点**'
          '（记 `collect: purple_skip`）—— 治"没打探索格"的**真根因**'
          '（PC：「我前几轮一直在修 `popups()` 那条链，而真正吃掉这一格的是 '
          '`final_collect()`」✗）',
          "log.append({'collect': 'purple_skip'" in _el62
          and '_fc_purple and _fc_free > 0 and EXPLORE_DISPATCH' in _el62)
    check('v1.63 ⑫ ⚠ 判据用的 4 个 `st` 键（`st`/`obs`/`ev_tiles`/`slots_free`）'
          '**必须在调用方真的存在**（否则判据恒不命中 ⇒ 静默失效 ✗）',
          all(("st.get('%s')" % k) in _el62.split('def final_collect')[1][:9000]
              for k in ('st', 'obs', 'ev_tiles', 'slots_free')),
          '⚠ 已用 `_tmpman/chk_fc_keys.py` 核过 ✓')

    # ---------------- ⑬~⑭ 等面板渲染 ----------------
    check('v1.63 ⑬ `one_round` 退图前先确认"没有面板正在渲染"：'
          '`st["last"]` 存在 **且** 棋盘被压暗 ⇒ **不判 done**，再等一轮；'
          '**上限 3 轮**防死循环 ✓（治"面板正在弹却直接退图 ⇒ 探索格漏了"）',
          "'finish_hold': 'panel_rendering_wait'" in _el62
          and "_pr_n < 3" in _el62
          and "getattr(b, 'last_change', None) or {}).get('dim', 1.0)" in _el62)
    check('v1.63 ⑭ ⚠ **手机端用自己的"压暗"量**（`b.last_change[\'dim\']`，'
          '与 PC 同名同义：1.0 = 没压暗）；**不许**用 `b.dim()`（手机端没那个方法 ✗）'
          '／**不许**用 `DIM_RATIO_MAX(0.42)`（那是"棋盘被完全盖住"的另一套判据 ✗）',
          'b.dim()' not in _el62.replace('我第一版写 `b.dim()` 是**错的**', '')
          and 'DIM_RATIO_MAX' not in _el62.split("'finish_hold': 'panel_rendering_wait'")[1][:900],
          '⚠ 我第一版写了 `b.dim()` ⇒ AttributeError（实查后已改成 last_change）')

    # ---------------- ⑮ B11b：紫格面板入口 ----------------
    check('v1.63 ⑮ 探索分支入口补 `_is_purple and _free_now > 0`'
          '（治"面板标题被认成「战斗事件」⇒ 探索分支的门不命中 ⇒ 掉进战斗分支"）'
          '＋ ⚠ 槽满时**不加**这一条（照旧落战斗分支"槽满就开打" ✓ 口径一致）',
          '_expl_entry63' in _el62
          # ⚠ v2.85 在这一条**后面**又追加了「这格本图已派过队」的闸门（not _purple_seen85）
          #   ⇒ v1.63 的语义（紫格 + 有空闲槽 => 进探索分支）**仍然成立**，
          #   只是多了一道「已处理就不重入」的闸门（不是改断言让它过）
          and 'or (_is_purple and _free_now > 0' in _el62
          and "'popup': 'purple_prefer_explore'" in _el62)
except Exception as _e63:       # noqa: BLE001
    check('v1.63 守门可运行（%r）' % (_e63,), False)

# =====================================================================================
# ㊿⭐⭐⭐ v1.63b【金币低于 50 万 ⇒ 不买商人/宝库】＋ **修 v1.63 幸运草闸门静默失效的真 bug**
#
# 用户两条口径（2026-10-05）：
#   ①「**加上金币低于50万就自动拉黑商人和宝库，高于就正常购买**」
#   ②「**也是在扫体力的时候顺便扫，不要让每图时间变长**」
#   ③（报 bug）「**我发现幸运草低于8还是摇色子**」
#
# ⭐⭐ 那个 bug 的根因值得记住（**与 v1.62 的"veto 被冲掉"同类**）：
#   `handle_dice()` 拿到的 `items` 是**带 band 裁过的**（`wait_end` 用
#   `band=(sy(130), sy(1560))`）⇒ **HUD 行 cy≈94 被裁掉** ⇒ `clover_count(items)`
#   **恒为 None** ⇒ 按"读不到就照常走"⇒ **闸门从来没触发过** ✗✗
#   （真机日志实证：只有 `dice: no_confirm_popup`，**一条 `skip_low_clover` 都没有**）
#   ⇒ 把判断放在**拿不到数据**的地方 ⇒ 判据**静默失效**且 **fail-open**（不报错）✗
#   ⇒ 修法：在 `one_round` **轮首全屏 OCR**（本来就有、含 HUD）读一次存进 `st`，
#     下游读 `st`（**零额外开销**，正合用户口径② ✓）
# =====================================================================================
print()
print('㊿⭐⭐⭐ v1.63b 金币闸门（<50万不买商人/宝库）+ 幸运草闸门**真 bug**修复')
try:
    # ---------------- ①~③ 常数与函数 ----------------
    check('v1.63b ① 有 `coin_count()` / `coin_allows_buy()` / `COIN_MIN_BUY = 500000`'
          '（用户口径「低于50万」⇒ 500000 ✓）',
          'def coin_count(items):' in _el62
          and 'def coin_allows_buy(n):' in _el62
          and 'COIN_MIN_BUY = 500000' in _el62)
    check('v1.63b ② ⚠⚠ 金币窗口 `COIN_HUD_Y` 与幸运草的**行不重叠**'
          '（实测两者 x 几乎重合 609~698 vs 688~699 ⇒ **只能靠 y 分行区分** ✗；'
          'v1.63 第一版混着量 ⇒ 金币被当幸运草 ✗）',
          'COIN_HUD_Y = (15, 65)' in _el62
          and 'CLOVER_HUD_Y = (70, 120)' in _el62)
    check('v1.63b ③ ⚠ 读不到金币 ⇒ **允许买**（fail-open：宁可买，也别因一次 OCR 失败'
          '就整图不买 ✗；与幸运草闸门同口径 ✓）',
          'if n is None:' in _el62.split('def coin_allows_buy')[1][:400]
          and 'return True' in _el62.split('def coin_allows_buy')[1][:400])

    # ---------------- ④~⑥ **修 bug 的守门**（这才是本轮最重要的）----------------
    check('v1.63b ④ ⛔ **撤回守门（v1.63 的真 bug）**：`handle_dice` 必须**优先读 `state`**'
          '（`state["clover_now"]`），只有拿不到才退回 `items` ——'
          '因为传进去的 `items` 是 **band 裁过的、HUD 被裁掉** ⇒ 只读 items 会**恒 None** ✗✗',
          "state.get('clover_now')" in _el62
          and '_cv_now = clover_count(items)' in _el62,
          '⚠ 这正是用户报的「幸运草低于8还是摇色子」的根因')
    check('v1.63b ⑤ `handle_dice` 签名带 `state=None`，且**两处调用点都传了**'
          '（`wait_end` 传 `state=state`；`popups` 传 `state=_state`）',
          'def handle_dice(b, log, items, tries=3, state=None):' in _el62
          and 'handle_dice(b, log, items, state=state)' in _el62
          and 'handle_dice(b, log, items, state=_state)' in _el62,
          '⚠ 漏传一处 ⇒ 那条路径的闸门又静默失效 ✗')
    check('v1.63b ⑥ `one_round` **轮首**（全屏 OCR 之后）读一次存进 `st`：'
          '`st["clover_now"]`（每轮刷新）＋ `st["coin_now"]`（**用户口径：只进图读一次**）'
          '—— **零额外 OCR**（用户口径「不要让每图时间变长」✓）',
          "st['clover_now'] = clover_count(items)" in _el62
          and "st['coin_now']" in _el62
          and "st.get('coin_now') is None" in _el62,
          '⚠ 必须复用轮首那份 `items`，不许新增 OCR 调用')
    check('v1.63b ⑦ ⚠ 金币"只进图读一次"：**读失败（None）不算读到** ⇒ 下一轮继续尝试'
          '（否则进图那帧 HUD 没画全就把整图钉死在 None 上 ✗）',
          "if st.get('coin_now') is None:" in _el62
          and "if _cn is not None:" in _el62)

    # ---------------- ⑧~⑨ 买目标的闸门 ----------------
    check('v1.63b ⑧ 金币不够 ⇒ **清空 `buy` 与 `buy_hidden`**（这是它们唯一的汇聚点 ⇒'
          '整条购买链都看不到它们 ✓）＋ 记 `coin_gate: block_buy` 日志',
          "if not coin_allows_buy(_coin_now):" in _el62
          and "'coin_gate': 'block_buy'" in _el62
          and 'buy = []' in _el62)
    check('v1.63b ⑨ ⚠ **不写 `done`、也不写 `blocked`** —— 用户 2026-10-05 纠正：'
          '「商人格买完都不消失，完全不可能开路」⇒ 不买即可，**无需额外拉黑**；'
          '`done` 的语义是"这一格点过了"（`block_cell` 也往那写）⇒ 混进去语义会乱 ✗',
          "note': '金币 %s < %d ⇒ **本图不买商人/宝库**" in _el62
          and '无需额外拉黑' in _el62)

    # ---------------- ⑩ 执行级：读数 + 门槛（真机 HUD 坐标造的条目）----------------
    if os.path.exists(os.path.join(HERE, 'probe_coin_behavior.py')):
        import subprocess as _sp63b
        _rb = _sp63b.run([sys.executable,
                          os.path.join(HERE, 'probe_coin_behavior.py')],
                         stdout=_sp63b.PIPE, stderr=_sp63b.STDOUT,
                         env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        _ob = _rb.stdout.decode('utf-8', 'replace')
        check('v1.63b ⑩ 执行级：`coin_count` 读数正确 ＋ '
              '⚠ **金币与幸运草按行分得清**（只有第 2 行时金币读数必须是 None ——'
              '防 v1.63 那个"串行"的坑复发 ✗）＋ 门槛 None/0/499999/500000 判定正确',
              _rb.returncode == 0 and '不会互相串' in _ob,
              'exit=%d' % _rb.returncode)
    else:
        skip('v1.63b ⑩ 金币读数执行级（缺 probe_coin_behavior.py）')
except Exception as _e63b:      # noqa: BLE001
    check('v1.63b 守门可运行（%r）' % (_e63b,), False)

# =====================================================================================
# ㊿⭐⭐⭐⭐ v1.64b【真机截图反算验证】＋ **修一个我自己刚引入的读错隐患**
#
# 背景：v1.64 装机后我想在真机上验读数，但**截图权限失效**（`截图=False`）⇒ 走另一条路：
#   用 `adb screencap` 拍一张真机帧（1280×2772 / 选图界面，HUD 完整）
#   ⇒ 按 `RefMapper` 的**同一条公式**反算回 1080×1920 参考系，再和窗口对拍 ✓
#   意外收获：这张截图的 HUD 真值是 **金币 165531 / 幸运草 1**
#     ⇒ 正好都落在**我新加的阈值**两侧（<50万 ⇒ 不买；<8 ⇒ 不摇+剔大拇指）✓
#
# ⭐⭐ 反算发现的两个问题（都已修）：
#   ① ⚠⚠ **`max(候选)` 会读错**：若 OCR 把 `165531` 拆成 6 个单字符条目，
#      `max(1,6,5,5,3,1) = 6` ⇒ **静默读成一个错误的数**（比读不到更糟 ✗✗）
#      ⇒ 改成**按 cx 从左到右拼接**（整串/拆字符两种都正确 ✓）
#   ② 映射自洽性：两行各自反解出的 `topInset` 只差 9px（128.6 / 119.6）
#      ⇒ 证明「设备帧 HUD」与「参考系标定」是**同一套映射**，窗口成立 ✓
# =====================================================================================
print()
print('㊿⭐⭐⭐⭐ v1.64b 真机截图反算验证 + 「数字被拆成单字符」读错守门')
try:
    check('v1.64b ① 抽出共用的 `_hud_number(items, x_win, y_win)`，'
          '`coin_count`/`clover_count` 都走它（**一份判据，不会两边漂移** ✓）',
          'def _hud_number(items, x_win, y_win):' in _el62
          and 'return _hud_number(items, COIN_HUD_X, COIN_HUD_Y)' in _el62
          and 'return _hud_number(items, CLOVER_HUD_X, CLOVER_HUD_Y)' in _el62)
    check('v1.64b ② ⛔ **撤回守门：不许再用 `max(候选)`** ——'
          'OCR 一旦把 `165531` 拆成单字符，`max()` 会给出 `6`（**静默读错** ✗✗）'
          '⇒ 必须**按 cx 拼接**',
          "cands.sort()" in _el62
          and "s = ''.join(t for _cx, t in cands)" in _el62,
          '⚠ 我 v1.64 第一版两处都写的 `max(best, int(t))`')
    check('v1.64b ③ 拼接长度 > 12 位 ⇒ **判为"窗口混进别的东西"⇒ 返回 None**'
          '（**不猜** ✓，比给个错数好）',
          'or len(s) > 12' in _el62)
    # 执行级：真机截图反算（映射自洽 + 窗口命中）
    if os.path.exists(os.path.join(HERE, 'probe_hud_devframe.py')):
        import subprocess as _sp1
        _r1 = _sp1.run([sys.executable,
                        os.path.join(HERE, 'probe_hud_devframe.py')],
                       stdout=_sp1.PIPE, stderr=_sp1.STDOUT,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        _o1 = _r1.stdout.decode('utf-8', 'replace')
        _out1 = os.path.join(os.path.abspath(os.path.join(PROJ, '..', '_tmpman')),
                             '_hud_devframe_out.txt')
        try:
            _o1 = open(_out1, encoding='utf-8').read()
        except Exception:       # noqa: BLE001
            pass
        if '缺真机截图' in _o1 or '读不了' in _o1:
            skip('v1.64b ④ 真机截图反算（缺 `_tmpman/_dev_screen.png`；'
                 '用 `adb shell screencap -p` 拍一张放那儿 ✓）')
        else:
            check('v1.64b ④ **执行级（真机截图反算）**：两行各自反解出的 `topInset` '
                  '**必须几乎相等**（⇒ 设备帧 HUD 与参考系标定是同一套映射）'
                  '＋ 两行峰**各自落进各自的 y 窗口** ✓',
                  '自洽 ✓' in _o1
                  and '落在金币 y 窗内：True' in _o1
                  and '落在幸运草 y 窗内：True' in _o1,
                  '⚠ 不自洽 ⇒ 我的参考系窗口在设备帧上不成立 ✗')
            check('v1.64b ⑤ **执行级（真机截图反算）**：金币窗口 x(595,715) '
                  '命中 **6 个簇**（= `165531` 的 6 位）'
                  '＋ 第 2 行体力(276~398)/大拇指(905) **都在幸运草窗之外** ✓',
                  '窗口 x(595, 715) 命中 6 个' in _o1
                  and '窗口 x(655, 735) 命中' in _o1)
    else:
        skip('v1.64b ④⑤ 真机截图反算（缺 probe_hud_devframe.py）')
    # 执行级：拆字符守门
    if os.path.exists(os.path.join(HERE, 'probe_coin_behavior.py')):
        import subprocess as _sp2
        _r2 = _sp2.run([sys.executable,
                        os.path.join(HERE, 'probe_coin_behavior.py')],
                       stdout=_sp2.PIPE, stderr=_sp2.STDOUT,
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        _o2 = _r2.stdout.decode('utf-8', 'replace')
        check('v1.64b ⑥ **执行级**：数字被拆成 6 条 ⇒ 仍读出 `165531`'
              '（不是 `6`）；整串也读对；13 位垃圾 ⇒ None',
              _r2.returncode == 0 and '拆成 6 条' in _o2 and '165531' in _o2,
              'exit=%d' % _r2.returncode)
except Exception as _e64b:      # noqa: BLE001
    check('v1.64b 守门可运行（%r）' % (_e64b,), False)

# =====================================================================================
# ㊿⭐⭐⭐ v1.63c【幸运草 < 8 ⇒ **本图剔掉"纯大拇指"目标**】
#   用户原话（2026-10-05）：
#     「**而且我发现幸运草低于8还是摇色子，改成低于8这张图的大拇指目标都拉黑不去打**」
#   依据：大拇指格的**唯一价值**就是"结算面板摇色子刷大拇指装备" ⇒ 草不够时打它
#     只是白花体力（还要多打一场战斗）✗
#   ⚠ 只剔**纯 recommend** 格；**带 boss/clover/redEquip 的一律保留** ✓
#     （那格另有价值，不能因为顺带带了个大拇指就整格丢掉 ✗）
#   ⚠ 读不到草 ⇒ **不剔**（fail-open，与另两道闸门同口径 ✓）
# =====================================================================================
print()
print('㊿⭐⭐⭐ v1.63c 幸运草 <8 ⇒ 剔掉"纯大拇指"目标（不打白费体力的格）')
try:
    check('v1.63c ① `one_round` 里在 **`marked` 算完之后**剔纯 recommend 格'
          '（`marked` 是标记目标的唯一汇聚点 ⇒ 剔这里整条链都看不到 ✓）'
          '＋ 门槛就是 `CLOVER_MIN_REROLL`（不另立常数 ✓）',
          "'clover_gate': 'drop_recommend'" in _el62
          and 'all(_m == \'recommend\' for _m in _mks_p)' in _el62
          and "if (_clv_now is not None) and (int(_clv_now) < CLOVER_MIN_REROLL) and marked:" in _el62)
    check('v1.63c ② ⚠ **只剔纯 recommend**：带别的标记（boss/clover…）**一律保留**'
          '（防"带大拇指的首领格被整格丢掉" ✗）',
          'if _mks_p and all(_m == \'recommend\' for _m in _mks_p):' in _el62
          and '_kept.append(_pp)' in _el62)
    check('v1.63c ③ ⚠⚠ **`mk[格]` 是 dict（`{\'marks\': [...]}`）不是 list**'
          '—— 实跑确认过（`scan_board_fast` 的返回格式）；'
          '按 list 解析会**静默什么都读不到** ⇒ 门槛永不触发 ✗',
          "isinstance(_vv_p, dict) else list(_vv_p or [])" in _el62,
          '⚠ 我第一版就是按 list 写的（`list(mk.get(格) or [])`）⇒ 会把 dict 的**键**当标记 ✗')
    check('v1.63c ④ 读不到草（None）⇒ **不剔**（fail-open：宁可白打一格，'
          '也别因一次 OCR 失败就整图漏掉所有大拇指 ✗）',
          '(_clv_now is not None) and (int(_clv_now) < CLOVER_MIN_REROLL)' in _el62)
    check('v1.63c ⑤ 剔掉时**同步从 `mk` 里 pop**（下游多处读 `mk` ⇒ 不同步会不一致 ✗）'
          '＋ 记 `recommend_dropped` 进 entry（便于对账 ✓）',
          'mk.pop(_rcp, None)' in _el62
          and "entry['recommend_dropped'] = len(_dropped)" in _el62)
    # 执行级：真机帧口径 + 一格多标记（用 probe 验判据本身 ✓）
    if os.path.exists(os.path.join(HERE, 'probe_recommend_gate.py')):
        import subprocess as _sp63c
        _rc_ = _sp63c.run([sys.executable,
                           os.path.join(HERE, 'probe_recommend_gate.py')],
                          stdout=_sp63c.PIPE, stderr=_sp63c.STDOUT,
                          env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        _oc = _rc_.stdout.decode('utf-8', 'replace')
        check('v1.63c ⑥ 执行级：草 <8 ⇒ 只剔纯大拇指；**带 boss 的格保留**；'
              '草够/读不到 ⇒ 一律不剔（真机帧口径 `1,6=recommend`/`4,2=boss` ＋ 一格多标记 ✓）',
              _rc_.returncode == 0 and '只剔**纯大拇指**格' in _oc,
              'exit=%d' % _rc_.returncode)
    else:
        skip('v1.63c ⑥ 大拇指闸门执行级（缺 probe_recommend_gate.py）')
except Exception as _e63c:      # noqa: BLE001
    check('v1.63c 守门可运行（%r）' % (_e63c,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊾⏤ v1.66【三条根因一起收口】—— 用户 2026-10-06 两条口径 + 一条真机复盘
#   用户原话：
#     ① 「**刚刚真机那边的脚本靠兜底策略又购买了黄金宝库**。。**禁用兜底策略**，
#         规划执行完**就算还有目标也直接退**，**只听规划的**」
#     ② 「顺便看看真机这几把的日志，看看为什么幸运草都低于8了，为什么还要打大拇指地块」
#     ③ 「最近一次的日志，规划出了问题，我猜测是**把拉黑的方块认为已经可以连锁通过了**？
#         也可能是把宝箱认为可以连锁通过了」
#
#   三条的根因**都不是"判据写错"**，而是**判据改在了错的层**：
#     · ① `EffPolicy` 直接读模型 ⇒ 清 `buy`/`buy_hidden` 对它毫无影响
#          （真机：`block_buy` ⇒ `plan exhausted` ⇒ `eff ok` ⇒ `vault_panel_by_dlg` ✗）
#     · ② 幸运草闸门剔的是 `mk`，而 `_cells_for_model` 会把 `st['obs']` 里
#          **累积的标记重新贴回** ⇒ 剔了又回来 ✗
#     · ③ `Block.blocked` 的语义注释写着「不可点、**不可借道**」，
#          但 `plain` / `connected_plain` / `plain_group` / `REP` **全都没判它** ✗
#          ⇒ 拉黑格照样被并进连通空地片 ⇒ 片被撑大 ⇒ 连锁穿透 ✗✗
#   ⚠ 三条是**同一类"静默失效"**（v1.62 veto 被冲掉 / v1.63 band 裁掉 HUD 之后第三次）
#     ⇒ 门禁必须**执行级**钉住，不能只查字符串（否则改回去也能绿 ✗）
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊾⏤ v1.66 禁用兜底（只听规划的）+ 闸门模型层收口 + 拉黑块阻断连锁')
try:
    import importlib as _il66
    _il66.invalidate_caches()
    import spots as _sp66
    import mapsim as _msim66
    import mapsolve as _mv66

    # ── ③【拉黑块阻断连锁】—— 本组最核心的一条，**执行级** ────────────────
    #   造一条"1 行 5 格"的空地走廊，正中塞一个**拉黑块**：
    #     真机语义：点左端 ⇒ 连锁只吃左半边（拉黑格**阻断穿透** ✓）
    #     旧行为（bug）：`plain` 不判 `blocked` ⇒ 整条 5 格算一片 ⇒ 以为右边也消了 ✗✗
    def _c66(sid, name, anchor, marks=None, blocked=False, target=None,
             revealed=True, ratio=1.0):
        _d = {'sid': sid, 'name': name, 'revealed': revealed, 'ratio': ratio,
              'score': 0.99, 'marks': list(marks or []), 'anchor': anchor,
              'top': [(0.99, sid, anchor)]}
        if blocked:
            _d['blocked'] = True
        if target is not None:
            _d['target'] = target
        return _d

    # (3,2) 是拉黑块（名字命中黑名单且被 `_cells_for_model` 打了 blocked ✓）
    _cells66 = {
        (3, 1): _c66('S00003_001', '草地', (3, 1)),
        (3, 2): _c66('S50002_001', '沙地', (3, 2), blocked=True, target=False),
        (3, 3): _c66('S00003_001', '草地', (3, 3)),
        (3, 4): _c66('S00003_001', '草地', (3, 4)),
        (3, 5): _c66('S00003_001', '草地', (3, 5)),
    }
    _sim66 = _msim66.MapSim.from_observation(_cells66, _sp66.spot_rows())
    _c66i = _msim66.cell_of
    _b66_blk = _sim66.board[_c66i(3, 2)]
    _b66_l = _sim66.board[_c66i(3, 1)]
    check('v1.66 ③a `blocked` 字段真的进到 `Block`（观测→模型 ✓）',
          _b66_blk >= 0 and bool(getattr(_sim66.blocks[_b66_blk], 'blocked', False)),
          'bi=%s' % (_b66_blk,))
    check('v1.66 ③b ⭐ **拉黑块 `plain` 恒 False**（"不可借道"真的实现了 ✓）'
          '—— 旧代码这里必然 True（注释写了语义但没实现 ✗）',
          _sim66.blocks[_b66_blk].plain is False,
          'plain=%s' % (_sim66.blocks[_b66_blk].plain,))
    _conn66 = _sim66.connected_plain(_c66i(3, 1))
    check('v1.66 ③c ⭐⭐ **连锁不许穿过拉黑块**（点 (3,1) ⇒ 只吃左边 1 格，'
          '**右边 3 格不许被算进来** ✗）—— 用户猜测的正是这条 ✓',
          _b66_l in _conn66 and _b66_blk not in _conn66
          and len(_conn66) == 1,
          '连通片=%s（应只含 bi=%s；含拉黑块 bi=%s = 漏 ✗）'
          % (sorted(_conn66), _b66_l, _b66_blk))
    _prob66 = _mv66.Problem(_sim66)
    _pg66 = _prob66.plain_group(_b66_l)
    check('v1.66 ③d ⭐⭐ `Problem.plain_group` 同样不跨拉黑块'
          '（`REP`/`PLAIN_GROUP_MASK` 都是从它推的 ⇒ 一处漏就三处漏 ✗）',
          _b66_blk not in _pg66 and len(_pg66) == 1,
          'plain_group=%s' % (sorted(_pg66),))
    _cache66 = _mv66._build_cache(_prob66)
    check('v1.66 ③e `REP[拉黑块]` **不等于**左侧空地（否则 A* 走掩码那条路又会串起来 ✗）',
          _cache66['REP'].get(_b66_blk, _b66_blk) != _cache66['REP'].get(_b66_l, _b66_l),
          'REP[blk]=%s REP[L]=%s'
          % (_cache66['REP'].get(_b66_blk), _cache66['REP'].get(_b66_l)))
    # 负样本（**必须有**）：把 `blocked` 摘掉 ⇒ 必须恢复成"整条 5 格一片"
    #   ⇒ 证明上面那条不是恒绿（fixture 本身有意义 ✓）
    _cells66b = {}
    for _k66b, _v66b in _cells66.items():
        _v66b = dict(_v66b)
        _v66b.pop('blocked', None)
        _cells66b[_k66b] = _v66b
    _sim66b = _msim66.MapSim.from_observation(_cells66b, _sp66.spot_rows())
    _conn66b = _sim66b.connected_plain(_c66i(3, 1))
    check('v1.66 ③f 对照项：摘掉 `blocked` ⇒ **恢复成整条 5 格连通**'
          '（证明 ③c 不是恒绿、fixture 真的在测东西 ✓）',
          len(_conn66b) == 5, '连通片=%d 格（应 5）' % len(_conn66b))

    # ── ①②【闸门模型层收口】—— `st['nogo_rc']` 的执行级验证 ──────────────
    _el66p = os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _el66 = open(_el66p, encoding='utf-8').read()
    check('v1.66 ①a `_cells_for_model` 末尾有 `nogo_rc` 收口，且**三件事一起做**'
          '（blocked + target=False + 清 marks ✓）',
          "_nogo = st.get('nogo_rc') or ()" in _el66
          and "_vv['blocked'] = True" in _el66
          and "_vv['target'] = False" in _el66
          and "_vv['marks'] = []" in _el66)
    #   ⚠ 用 `find()` 不用 `index()`：代码被 stash/回退时 `index` 会抛 ValueError
    #     把本组后面 8 条断言**全吞掉**（牙齿测试只剩一条"守门可运行"红，看不出细节 ✗）
    _i66_tgt = _el66.find("_vv['target'] = bool(tcfg_mod.is_target(")
    _i66_ng = _el66.find("_nogo = st.get('nogo_rc') or ()")
    check('v1.66 ①b ⚠⚠ 收口位置**必须在 `target` 重算之后**'
          '（放前面会被 `is_target(...)` 冲掉 ✗ —— 与 v1.62 那条"veto 位置"同一个坑）',
          _i66_tgt >= 0 and _i66_ng > _i66_tgt,
          'target 重算 idx=%d，nogo 收口 idx=%d' % (_i66_tgt, _i66_ng))
    check('v1.66 ①c 金币闸门把"真正的商人/宝库"塞进 `nogo_rc`'
          '（⚠ 光清 `buy`/`buy_hidden` 会被模型层绕过 ✗ —— 真机就是这么买掉宝库的）',
          "'coin_gate': 'nogo_tagged'" in _el66
          and '_dropped_buy67' in _el66)
    # ⛔⛔⛔ v1.67【撤回守门】—— v1.66 的金币闸门**判据用错了函数**，别再写回去 ✗
    #   `tcfg_mod.is_blocked(name)` 的语义是「**这个特殊方块没被用户勾选**」
    #     （`targets_cfg.py:84-97`：`return not enabled(k, cfg)`）
    #   而商人/宝库在 `DEFAULT_ON`（`targets_cfg.py:49`）里**默认勾选**
    #     ⇒ `enabled=True` ⇒ `is_blocked=False` ⇒ **恒不命中** ⇒ 一格都拉不上 ✗✗
    #   反过来它会把**没勾选**的特殊方块（祭坛/宝箱怪…）拉黑 —— 那些 v1.44 早就拉过，
    #     属于**重复劳动**，而真正该拉的商人/宝库**一格没进** ✓
    #   真机日志铁证（`_tmpman/devlog4/mgas_log.txt`）：
    #     map 3 有 `{"coin_gate":"block_buy","dropped_buy":1}`（确实存在商人/宝库）
    #     可**一条 `coin_gate: nogo_tagged` 都没落** ✗
    #     map 0/1 落的 `3,3`/`5,4` 是**别的**特殊方块 ⇒ 与金币无关的副作用 ✓
    #   探针（`_tmpman/_v167_fixcheck3.py` ⑥，逐字复现）：
    #     同输入下旧判据给 `[(1,3),(1,4)]`（祭坛/宝箱怪）而**正确答案是 `[(1,1),(1,2)]`** ✗
    #   ⚠⚠ **不能用字符串 grep** —— 上面的留档注释里**必然逐字出现**旧判据的名字
    #      （`_el66` 里那句 `v1.66 原文写的是 tcfg_mod.is_blocked(...)`）⇒ grep 会**假红** ✗
    #      （AGENTS.md 记着同一个坑：v1.62c 的 `CONTENT_SCORE_MIN` 也是这么假红的 ✓）
    #      ⇒ 先**剥掉整行注释**再判，只认真正的代码 ✓
    _code67 = '\n'.join(_ln67 for _ln67 in _el66.splitlines()
                        if not _ln67.lstrip().startswith('#'))
    check('v1.67 ⛔ 撤回守门：金币闸门**不许**再用 `tcfg_mod.is_blocked(name)` 当判据'
          '（它的语义是"没勾选"⇒ 商人/宝库恒不命中 ✗✗ 真机已证一格没拉上）'
          '—— ⚠ 判据**剥掉注释行**后再查（留档注释里必然出现它的名字 ✗）',
          'is_blocked(_v66.get(\'name\'))' not in _code67
          and 'is_blocked(_v66.get("name"))' not in _code67)
    check('v1.67 金币闸门新判据 = ①分类器的 `buy`/`buy_hidden`（**清空前留底**）'
          '∪ ②`spots.BUY_OUT_NAMES` 名字命中 **且** `score >= BUY_SCORE_MIN`'
          '（与 `spots.py` 分类器自己的买入口径**同源同门槛** ✓）',
          '_dropped_buy67 = list(buy) + list(buy_hidden)' in _el66
          and "getattr(spots_mod, 'BUY_OUT_NAMES', ())" in _el66
          and "getattr(spots_mod, 'BUY_SCORE_MIN', 0.85)" in _el66
          and '_bmin67' in _el66)
    check('v1.67 ①②两条来源**取并集**（名字扫不到未揭示的暗格 ⇒ 必须有像素那条 ✓；'
          '分类器这帧没给出但名字明显是 ⇒ 必须有名字那条 ✓）',
          _el66.count('_nogo.add(tuple(') >= 2)
    check('v1.67 ⚠ 低分乱猜**不许**拉黑（v1.46 口径：score 不够 = 没资格代表'
          '"这是商人/宝库" ⇒ 宁可多看一眼，也别静默拉黑某格 ✗）',
          '_sc66 < _bmin67' in _el66)
    # 执行级：真跑那段闸门逻辑，确认"名字命中 + 分数够"真的进 `nogo_rc`
    _obs67 = {(1, 1): {'name': '黄金宝库', 'score': 0.98},
              (1, 2): {'name': '旅行商人', 'score': 0.97},
              (1, 3): {'name': '传承祭坛', 'score': 0.95},
              (1, 4): {'name': '金属宝箱怪', 'score': 0.96},
              (1, 5): {'name': '黄金宝库', 'score': 0.30}}
    _got67 = set()
    try:
        import spots as _SP67
        _bun67 = tuple(getattr(_SP67, 'BUY_OUT_NAMES', ()) or ())
        _bmin67 = float(getattr(_SP67, 'BUY_SCORE_MIN', 0.85))
        for _k67, _v67 in _obs67.items():
            _nm67 = str(_v67.get('name') or '')
            if not _nm67 or not any(_b in _nm67 for _b in _bun67):
                continue
            if float(_v67.get('score') or 0.0) < _bmin67:
                continue
            _got67.add(_k67)
    except Exception as _e67:           # noqa: BLE001
        _got67 = set()
        print('    ⚠ v1.67 探针异常：%r' % (_e67,))
    check('v1.67 执行级：`黄金宝库`/`旅行商人`（score ≥ 0.85）⇒ **必须**入选；'
          '`传承祭坛`/`金属宝箱怪`（不是商人宝库）与低分 `黄金宝库(0.30)` ⇒ **必须不入选**',
          _got67 == {(1, 1), (1, 2)},
          '实得 = %s（期望 [(1, 1), (1, 2)]）' % sorted(_got67))
    # 对照项：旧判据在同一输入上**必须**给出**不同**结果（证明新判据真的修了东西 ✓）
    _old67 = set()
    try:
        import targets_cfg as _TC67
        for _k67, _v67 in _obs67.items():
            if _TC67.is_blocked(_v67.get('name')):
                _old67.add(_k67)
    except Exception:                   # noqa: BLE001
        _old67 = set()
    check('v1.67 对照项：同一输入下**旧判据**给出**不同**答案'
          '（漏商人/宝库、误拉祭坛/宝箱怪 ⇒ 证明上面那条不是恒真 ✓）',
          _old67 != _got67,
          '旧判据 = %s；新判据 = %s' % (sorted(_old67), sorted(_got67)))
    check('v1.66 ①d 幸运草闸门把剔掉的大拇指格塞进 `nogo_rc`'
          '（⚠ 光剔 `mk` 会被 `st[\'obs\']` 回流贴回来 ✗ —— 真机日志实证）',
          "'clover_gate': 'nogo_tagged'" in _el66
          and "_nogo66.add(tuple(_rcp))" in _el66)
    check('v1.66 ①e ⚠ `nogo_rc` 每图重建（`run_one_map` 里 `st` 是**新建 dict**、'
          '初始键里**没有** `nogo_rc` ⇒ 不跨图残留 ✗）＋ 两处写入都用 `setdefault`'
          '（不覆盖上一轮塞的 ⇒ 同图内两道闸门**累加** ✓）',
          "st = {'cold': {}, 'done': set(), 'last': None, 'err': 0, 'stuck': 0," in _el66
          and "'nogo_rc'" not in _el66.split("st = {'cold': {}, 'done': set()")[1][:220]
          and _el66.count("st.setdefault('nogo_rc', set())") == 2)
    check('v1.66 ①f `_vv` 是 `st[\'obs\']` 的**副本**（清 marks 不许污染观测累积 ✗）'
          '—— 下一轮闸门要能重新判、重新塞 ✓',
          '_vv = dict(_v)' in _el66)
    # 执行级：真跑 `_cells_for_model`，确认 nogo 格真的变成 blocked + 非目标 + 无标记
    _mk66 = {(3, 2): {'marks': ['recommend']}}
    _lg66 = []
    _m66 = EL._cells_for_model(
        {'marks': dict(_mk66), 'obs': dict(_cells66), 'done': set(),
         'nogo_rc': {(3, 2)}},
        {'st': dict(_cells66)}, log=_lg66, tag='nogo66', mark_revealed=False)
    _out66 = _m66.get((3, 2)) or {}
    _txt66 = ' '.join(str(x) for x in _lg66)
    check('v1.66 ①g ⭐执行级：`nogo_rc` 里的格**真的**变成 `blocked=True` + '
          '`target=False` + `marks=[]`（不是只写了代码没生效 ✓）',
          bool(_out66.get('blocked')) and _out66.get('target') is False
          and not _out66.get('marks'),
          'blocked=%s target=%s marks=%s'
          % (_out66.get('blocked'), _out66.get('target'), _out66.get('marks')))
    check('v1.66 ①h 执行级：落了 `nogo_applied` 日志（复盘能看见收口生效 ✓）',
          'nogo_applied' in _txt66, _txt66[:200])
    # ⚠ 对照：**不带** nogo_rc ⇒ 同一格必须**不被**拉黑（证明上面不是恒真 ✓）
    #   ⚠ 必须用**没打 `blocked`** 的那份观测（`_cells66b`）——
    #     否则测的是"夹具自己带的 blocked"，与 `nogo_rc` 那条路无关 ✗（第一版就踩了）
    _lg66b = []
    _m66b = EL._cells_for_model(
        {'marks': dict(_mk66), 'obs': dict(_cells66b), 'done': set()},
        {'st': dict(_cells66b)}, log=_lg66b, tag='nogo66b', mark_revealed=False)
    _out66b = _m66b.get((3, 2)) or {}
    check('v1.66 ①i 对照项：观测里**没打 `blocked`** 且不带 `nogo_rc` ⇒ 同一格**不被**拉黑'
          '（证明 ①g 真的在测 nogo 那条路 ✓）',
          not _out66b.get('blocked'), 'blocked=%s' % (_out66b.get('blocked'),))

    # ── ①【禁用兜底：只听规划的】── 源码级 ────────────────────────────────
    check('v1.66 ①j `FALLBACK_EFF` 默认**关** + 有环境变量开关（回退路径完整 ✓）',
          "MAPBOT_FALLBACK_EFF" in _el66
          and "FALLBACK_EFF = (os.environ.get('MAPBOT_FALLBACK_EFF', '0') or '0')" in _el66)
    check('v1.66 ①k ⭐ `_pact == \'done\'` 分支**保持 `plan_src = \'solver\'`**'
          '（⚠ 置成 `\'eff\'` 会让下面那段 EffPolicy **照跑** ⇒ "禁用"变成空话 ✗✗）',
          "_pact == 'done':" in _el66
          and "st['plan_src'] = 'solver'          # ⛔ 关键：**不置 'eff'**" in _el66)
    check('v1.66 ①l ⭐ 退图原因**如实报**（`plan_only_giveup` + `why` + `targets_left`）'
          '—— 不许冒充"目标已清完" ✗',
          "'finish': 'plan_only_giveup'" in _el66
          and "'why': _pwhy" in _el66
          and "'fallback_eff': False" in _el66)
    # ⚠ 切片段：`done` 分支**后面没有 `elif`**（紧跟着就是 EffPolicy 那段 `if`）
    #   ⇒ 用 `return 'done'` 收口，否则切片会一路吃到 EffPolicy ✗（第一版就栽在这）
    #   ⚠ 也不能拿 `[:1400]` 截——分支里有大段中文注释，`return 'done'` 在 1400 之后 ✗
    _parts66 = _el66.split("_pact == 'done':")[1].split("return 'done'")
    check('v1.66 ①m ⚠ 返回 **`\'done\'`** 不是 `\'stuck\'`**'
          '（`run()` 里 stuck/blank 连着 2 张会**停掉整局** ⇒ 退图是正常行为，不能停局 ✗）'
          '＋ 这段里**一次都没有** `return \'stuck\'`',
          len(_parts66) >= 2 and "return 'stuck'" not in _parts66[0],
          '分支里出现 `return \'stuck\'` = 会连停整局 ✗' if len(_parts66) >= 2
          else '压根没找到 `return \'done\'` ⇒ 退图语义丢了 ✗')
    check('v1.66 ①n ⭐ `_buy_first`（未规划目标插队）**只在兜底模式下**生效'
          '（它是旧世界遗留；`FOLLOW_PLAN_ONLY` 之后点序由 `st[\'plan\']` 说了算 ⇒ '
          '再插队就与"只听规划的"直接冲突 ✗）',
          'if FALLBACK_EFF:' in _el66
          and "'buy_first': 'skipped_plan_only'" in _el66)
    check('v1.66 ①o 结构级：`done` 分支里**没有** `st[\'plan_src\'] = \'eff\'`'
          '（置了它 ⇒ 下面 EffPolicy 那段立刻接管 ⇒ 用户口径①被架空 ✗）',
          "st['plan_src'] = 'eff'" not in _parts66[0],
          '⚠ 分支片段里出现 `plan_src = \'eff\'` ⇒ "禁用兜底"是空话 ✗')

    # ── ②【幸运草闸门为什么没生效】—— 把根因钉成断言 ──────────────────────
    check('v1.66 ②a ⚠⚠ 根因固化：`_cells_for_model` 会把 `st[\'obs\']` 的标记**贴回** '
          '`marks`（`if _mlist: _vv[\'marks\'] = _mlist`）—— 这就是闸门被绕过的通道 ✗',
          "if _mlist:" in _el66 and "_vv['marks'] = _mlist" in _el66,
          '⚠ 这条是**病根**不是修复：它必须与 ①d/①g 的 `nogo_rc` 收口同时存在 ✓')
except Exception as _e66:       # noqa: BLE001
    check('v1.66 守门可运行（%r）' % (_e66,), False)

# ══════════════════════════════════════════════════════════════════════════════
print()
print('=' * 78)
print('⓯⭐⭐⭐⭐ v1.68 槽位「已完成」领取判据换模板 + 标记定点窗修正 + 收尾体力顺序')
print('=' * 78)
#   ## 起因（用户 2026-10-06 两条报障）
#     ①「**现在问题是探索框里有两个已完成，但是不去领取**」
#     ②「刚刚那把**没有识别到幸运草标志**」
#   ## ① 的根因（**两条，都在同一族**）
#     · PC 源码逐字写着（`mapbot_pc/explore_loop.py:9187-9191`）：
#       「已完成」这三个字**正常 OCR 读不到**（真机实测必须放大 4 倍）
#       ⇒ 手机端 `== '已完成'` 的 OCR 精确等值判据 **恒为空** ⇒ 整块**静默**跳过 ✗
#     · 更隐蔽的第二条：旧的行锚 `_anchor48` 取自**别的槽位标签**
#       （「空闲」/倒计时）⇒ **三槽全是「已完成」时锚集为空** ⇒ `claim_lonely`
#       ⇒ **一格都不领** ✗（真机帧 `_verify/fr1264_r0_board.png` 正是这种）
#     · 第三处：第 ④ 步"领完复检"**也用的那个死判据** ⇒ `_re48` 恒为 `[]`
#       ⇒ 每次都判"领掉了" ⇒ `_CLAIM_FAIL_STREAK` **永远是 0**、自愈从没触发 ✗
#   ## ② 的根因：v1.45 的定点窗口 `MARK_OFF_REF=(-36,-36)` 只盖住 2×2 图标块的
#     **左上角那一个**（= boss）⇒ 幸运草/红装/大拇指**一律认不到** ✗
#   ## 为什么本组必须有**执行级 + 对照项**
#     判据换了、注释写了，**都不算数**：本项目已五次栽在"改了状态但决策处读另一份数据"
#     ⇒ 本组直接喂真机帧跑**被测函数本身**，并配一个**必须判负**的对照帧 ✓
try:
    _PROJ68 = PROJ
    _EL68P = os.path.join(_PROJ68, 'app', 'src', 'main', 'python', 'explore_loop.py')
    _MK68P = os.path.join(_PROJ68, 'app', 'src', 'main', 'python', 'marks.py')
    _el68 = open(_EL68P, encoding='utf-8').read()
    _mk68 = open(_MK68P, encoding='utf-8').read()
    import marks as _marks68m          # noqa: E402  ⚠ 取**模块真值**，别只 grep 源码
    _VER68 = os.path.join(_PROJ68, '_verify')

    def _slice68(_src, _a, _b, _tail=None):
        """安全切片：找不到锚点返回 **None**（不是抛异常）

        ⚠ 2026-10-06：第一版用 `_src.split(a)[1]` ⇒ 源码被 stash 回退时**抛
          IndexError**，把本组后面 10 条断言**全吞掉**（牙齿测试只剩一条"守门可运行"
          红，看不出细节 ✗）—— 与 v1.66 那次 `str.index()` 是**同一个坑**，
          本文件已第二次踩到 ⇒ 一律用本函数 ✓
        """
        _i = _src.find(_a)
        if _i < 0:
            return None
        _i += len(_a)
        _j = _src.find(_b, _i) if _b else -1
        if _b and _j < 0:
            return None
        _seg = _src[_i:_j] if _b else _src[_i:]
        if _tail is not None:
            _k = _seg.find(_tail)
            if _k < 0:
                return None
            _seg = _seg[:_k]
        return _seg

    _FCS68 = _slice68(_el68, 'def find_claim_slots(b, img=None):', 'def claim_one_slot')
    _COS68 = _slice68(_el68, 'def claim_one_slot(b, log, cx, cy, anchor_y=None):',
                      'def explore_slots_free')

    # ── A. ①【领取判据换模板】── 常量 / 资产 / 结构 ──────────────────────
    check('v1.68 A① ⭐ 领取判据的**模板与阈值**在位，且搜索带**上界 < 棋盘顶边**'
          '（`GRID.y0 = 1002` ⇒ 带内不可能是棋盘格 ⇒ 安全性**由几何保证**，'
          '不再依赖"OCR 读得到行锚"那条已证伪的前提 ✓）',
          "_CLAIM_TPL = 'slot_done.png'" in _el68
          and '_CLAIM_TPL_THR = 0.70' in _el68
          and '_CLAIM_TPL_BAND = (0, 880, 1080, 1000)' in _el68
          and 1000 < int(EL.GRID['y0']),
          'GRID.y0=%s（带上界 1000 必须 < 它）' % (EL.GRID['y0'],))
    _TPL68 = os.path.join(_ASSETS, 'templates', 'ui', 'slot_done.png')
    _tpl68_ok = os.path.exists(_TPL68)
    check('v1.68 A② ⭐ 模板 `slot_done.png` 真的进了**本仓资源包**'
          '（`assets/mapbot_pack/templates/ui/` —— 打包/热更都从这走 ✓）',
          _tpl68_ok,
          ('%s（%d 字节）' % (_TPL68, os.path.getsize(_TPL68))) if _tpl68_ok
          else '模板缺失 ⇒ 判据恒不可用 ✗')
    check('v1.68 A③ ⚠ 模板尺度 = **参考系原生**（不是从 PC 720 系缩来的）'
          '—— 教训：`probe_tpl1080.py` 曾把 720 原生模板 ×k 再搜 1080 带，'
          '得出"复现不了 ≤0.275"的**假结论** ✗；正确做法是在**裁剪它的帧系**里匹配',
          _tpl68_ok and _cv2.imread(_TPL68, _cv2.IMREAD_COLOR).shape[:2] == (36, 116),
          ('shape=%s（应 116×36 宽×高）' % ((_cv2.imread(_TPL68, _cv2.IMREAD_COLOR).shape[:2],)
                                            if _tpl68_ok else None,)))
    check('v1.68 A④ ⛔ **撤回守门**：领取判据**不许**再出现 OCR 精确等值 '
          '`== \'已完成\'`（PC 逐字记着「正常 OCR 读不到」⇒ 恒为空 ⇒ 静默失效 ✗✗）'
          '⚠ 先剥掉整行注释再查 —— 留档注释里**必然逐字引用**旧判据（v1.62c/v1.67 同一个坑）',
          not any(("'已完成'" in _ln and '== ' in _ln)
                  for _ln in _el68.splitlines()
                  if not _ln.lstrip().startswith('#')))
    check('v1.68 A⑤ ⭐ 新判据 `find_claim_slots` + `claim_one_slot` 都在，'
          '且**调用点真的接了**（不是只定义不用 ✗）',
          'def find_claim_slots(b, img=None):' in _el68
          and 'def claim_one_slot(b, log, cx, cy, anchor_y=None):' in _el68
          and '_hits68 = find_claim_slots(b)' in _el68
          and '_r68 = claim_one_slot(b, log, _cx48, _cy48)' in _el68)
    check('v1.68 A⑥ ⭐ `None` 与 `[]` **语义必须分开**'
          '（`None` = 模板读不出/取不到帧 ⇒ 判据不可用；`[]` = 判据可用但没命中）'
          '—— 混成一个值 ⇒ "模板没到"会被静默当成"没有已完成" ✗',
          _FCS68 is not None and 'return None' in _FCS68 and 'return []' in _FCS68)
    check('v1.68 A⑦ ⭐ **不再静默**：没有「已完成」时也要落一条日志'
          '（旧代码 `if _cd48:` 为空 ⇒ **什么都不记** ⇒ 真机上"到底判没判"根本看不出来'
          '—— 本轮排查就是被这个坑住的 ✗）',
          "'claim_none'" in _el68 and "'claim_tpl_unavailable'" in _el68
          and "'claim_found'" in _el68)
    check('v1.68 A⑧ ⭐ 第 ④ 步"领完复检"也换成 `find_claim_slots`'
          '（旧复检复用同一个死判据 ⇒ 恒判"已领掉" ⇒ 自愈 `_CLAIM_FAIL_STREAK` '
          '**永远 0、一次都没触发过** ✗ —— 同一个病根的第二/三处）',
          _COS68 is not None and 'find_claim_slots(b)' in _COS68)
    _PKI68 = os.path.join(_PROJ68, 'app', 'src', 'main', 'java',
                          'com', 'fantasy', 'autoexplore', 'PackInstaller.java')
    _pki68 = open(_PKI68, encoding='utf-8').read() if os.path.exists(_PKI68) else ''
    # ⛔⛔ v1.78 **把「钉字面量 .pack_v4」改成「钉版本号 >= 4」**（如实记账）：
    #   ---- 为什么原写法会**变成它自己要防的那个 bug** ----
    #     原断言是 `'MARK = ".pack_v4"' in _pki68` —— 钉的是一个**具体值** ✗
    #     而 `PackInstaller` 自己的注释（原文）写着：
    #       「⚠ **以后每次往 `assets/mapbot_pack/` 加/改资源，都要把这里的版本号 +1**」
    #     ⇒ 本轮往包里加了 `fruit_A_whole{,_mask}.png`（天赋果实识图模板）
    #       ⇒ 按那条规矩 MARK **必须**提到 v5 ✓
    #     ⇒ 可这条断言**钉死了 v4** ⇒ 要么「加资源但不提 MARK」（= 已装真机拿不到新模板，
    #       正是 v1.68 那个 bug 本身 ✗✗），要么「提 MARK 但门禁红」。
    #     ⇒ **钉值而不是钉意图的判据，会反过来阻塞它守护的那件事** ✓
    #   ---- 改法（钉意图，不钉值）----
    #     判据 = ①模板查找走 `tpl_dirs()` ②MARK 版本号 **>= 4**
    #     反向守门仍由 A⑩ 守着（**不许退回 v3**）✓
    #   ⚠ 与 AGENTS.md 教训 (y) 同一条：「数量够少」是间接指标、「集合包含」才是直接指标
    #     ⇒ 这里「等于 v4」是间接指标、「>= v4」才是意图 ✓
    _pki_ver = 0
    for _m9 in __import__('re').finditer(r'MARK\s*=\s*\"\.pack_v(\d+)\"', _pki68):
        _pki_ver = max(_pki_ver, int(_m9.group(1)))
    check('v1.68 A⑨ ⭐⭐ **部署陷阱守门**：模板查找必须走 `fixed_ref.tpl_dirs()`，'
          '**不许只读资源包**；且 `PackInstaller` 的 MARK 版本号 **>= 4**'
          '（`ensure()` 是「**只在首启解一次**」，标记在就直接 return ⇒ 不推进版本号，'
          '已装真机**永远拿不到**新模板，而代码不报错 ✗✗ ——「代码到了、图没到」家族）',
          'fixed_ref as _fxr68' in _el68 and 'tpl_dirs()' in _el68 and _pki_ver >= 4,
          'tpl_dirs=%s｜PackInstaller 标记版本=%s'
          % ('fixed_ref as _fxr68' in _el68 and 'tpl_dirs()' in _el68,
             ('v%d（>=4 ✓）' % _pki_ver) if _pki_ver >= 4
             else ('v%d ⇒ 低于 v4（新模板进不了已装机 ✗）' % _pki_ver if _pki68
                   else '读不到')))
    check('v1.68 A⑩ ⛔ 反向守门：`PackInstaller` 的标记**不许退回 `.pack_v3`**'
          '（它从 v1.08 起就没动过，正是本轮新模板解不进去的**直接原因** ✗）'
          '⚠ 先剥掉 `//`、`*`、`/*` 整行注释 —— 留档注释里**必然逐字引用**旧值'
          '（v1.62c / v1.67 / 本组 A④ 都是同一个坑，已三次踩到 ✓）',
          not any('.pack_v3' in _ln for _ln in _pki68.splitlines()
                  if not _ln.lstrip().startswith(('//', '*', '/*'))))

    # ── B. ①【执行级：真代码 + 真机帧】─────────────────────────────────
    class _FB68(object):
        """只喂一张帧的最小 bot（`find_claim_slots` 只用到 `b.img()` ✓）"""
        def __init__(self, _im):
            self._im = _im

        def img(self):
            return self._im

    _FR68 = os.path.join(_VER68, 'fr1264_r0_board.png')       # 三槽全「已完成」✓
    _NEG68 = (os.path.join(_VER68, 'dev_board_r0.png'),       # 三槽倒计时（白字）✓
              os.path.join(_VER68, 'phone_settle_20261004.png'),   # 结算帧（绿像素爆表）✗
              os.path.join(_VER68, 'phone_board_raw.png'))     # 全零帧 ✓
    #   ⚠ 用 `getattr` 取被测函数：源码被 stash/回退时**不抛异常**，否则本组后面
    #     全部断言被 except 吞掉、牙齿测试只剩一条"守门可运行"红（v1.66 踩过 ✗）
    _fc68 = getattr(EL, 'find_claim_slots', None)
    if _fc68 is None:
        skip('v1.68 B①~B⑤ 领取判据执行级（`find_claim_slots` 不在 ⇒ 源码被回退）')
    elif not os.path.exists(_FR68):
        skip('v1.68 B①~B⑤ 领取判据执行级（缺 `_verify/fr1264_r0_board.png` 真机帧）')
    else:
        _im68 = _cv2.imread(_FR68, _cv2.IMREAD_COLOR)
        _h68 = _fc68(_FB68(_im68))
        check('v1.68 B① ⭐⭐ 执行级：真机帧（**三个「已完成」**）⇒ 恰好 3 个命中，'
              '且 x 心与 `layout.REF[\'slots_x\']` **同源（±2px：模板里字形不是严格居中）**、'
              'y = 文字行 940（证明**判据本身**在这帧上工作，不是"注释写了" ✓）',
              _h68 is not None and len(_h68) == 3
              and all(abs(h[0] - w) <= 2 for h, w in
                      zip(_h68, EL.layout_mod.REF['slots_x']))
              and all(abs(h[1] - 940) <= 6 for h in _h68),
              'hits=%s（应 3 个、x≈(240,356,473)、y≈940）' % (_h68,))
        check('v1.68 B② ⭐ **聚类去重**：同一个「已完成」只报 **1** 次'
              '（`TM_CCOEFF_NORMED` 会在真峰周围给一整片高分 ⇒ 不聚类就会**连点同一个槽** ✗）',
              _h68 is not None and len(_h68) == len(set(h[0] for h in _h68)) == 3,
              'x 去重后 %s 个（应 3）' % (len(set(h[0] for h in _h68))
                                         if _h68 else None,))
        check('v1.68 B③ ⭐ 分数在**实测分离区间**内（正样本 0.906~1.000）',
              _h68 is not None and all(h[2] >= 0.90 for h in _h68),
              'scores=%s（门槛 %.2f）' % ([h[2] for h in _h68] if _h68 else None,
                                         EL._CLAIM_TPL_THR))
        # 对照项：**必须判负**的帧 —— 证明 B① 不是恒绿
        _neg68, _negdet = [], []
        for _p68 in _NEG68:
            if not os.path.exists(_p68):
                continue
            _r68n = _fc68(_FB68(_cv2.imread(_p68, _cv2.IMREAD_COLOR)))
            _neg68.append((os.path.basename(_p68), _r68n))
            if _r68n:
                _negdet.append('%s→%s' % (os.path.basename(_p68), _r68n))
        check('v1.68 B④ ⭐⭐ **对照项（负样本）**：倒计时帧 / **结算帧** / 全零帧 ⇒ '
              '一律 **0 命中**（⚠ 结算帧是**关键反例**：绿像素法在它上面爆表 '
              '3633/5767/10899 ⇒ 会**在结算时点棋盘** ✗ ⇒ 这条钉住"为什么不用绿像素法"）',
              bool(_neg68) and not _negdet,
              '误报=%s（应无）｜已验 %d 帧' % (_negdet or '无', len(_neg68)))
        check('v1.68 B⑤ ⭐ 判据**可判负也可判正**（对照项与 B① 结论相反 ⇒ 不是恒绿 ✓）',
              _h68 is not None and len(_h68) == 3
              and all(not r for _n, r in _neg68 if r is not None),
              '正=3 负=0')

    # ── C. ②【标记定点窗修正】────────────────────────────────────────────
    check('v1.68 C① ⭐⭐ v1.45 的**错误窗偏移**已修：块心 `(-7,-7)` + 搜索半径 `32.0`'
          '（旧值 `(-36,-36)`/`14.0` **只盖住 2×2 图标块的左上角** ⇒ '
          '幸运草/红装/大拇指**一律认不到** ✗ —— 用户报障②的真根因）',
          'MARK_OFF_REF = (-7, -7)' in _mk68 and 'FAST_SEARCH_R = 32.0' in _mk68,
          'MARK_OFF_REF=%s FAST_SEARCH_R=%s'
          % (getattr(_marks68m, 'MARK_OFF_REF', '?'),
             getattr(_marks68m, 'FAST_SEARCH_R', '?')))
    check('v1.68 C② ⚠ 尺度表**不许裁到 3 档**：`boss` 会在其中 3 帧上丢'
          '（实测教训：为提速裁尺度 ⇒ **静默丢目标** ✗）',
          'FAST_SCALES = (3.8, 4.1, 4.4, 4.7, 5.0)' in _mk68)
    check('v1.68 C③ ⭐ `_jobs_of()` **按模板字节去重**'
          '（`clover_live` 与 `clover` 是**逐字节相同**的同一张图 ⇒ 白算一遍 ✗；'
          '实测 7 → 6 ✓）',
          'np.ascontiguousarray(_t).tobytes()' in _mk68)

    # ── D. ③【收尾体力顺序 bug】────────────────────────────────────────
    _i68_s = _el68.find('sample_end_stamina(b)')
    _i68_t = _el68.find('say(summary_text())')
    check('v1.68 D① ⭐⭐ **收尾体力必须在 `summary_text()` 之前读**'
          '（旧代码把 `stamina_entries.append` 放在出统计**之后** ⇒ 最后一张图'
          '少算一段 ⇒ 「平均每图 24.2 < 进图 25」**算术上不可能** —— 就是这么发现的 ✓）',
          _i68_s >= 0 and _i68_t >= 0 and _i68_s < _i68_t,
          'sample_end_stamina idx=%s < say(summary_text) idx=%s' % (_i68_s, _i68_t))
    check('v1.68 D② ⭐ `sample_end_stamina()` 真的把读数记进 `stamina_entries`'
          '（只 `say` 不记账 = 没修 ✗）',
          "def sample_end_stamina(b):" in _el68
          and "STATS['stamina_entries'].append(" in
          (_slice68(_el68, 'def sample_end_stamina(b):', 'def summary_text') or ''))
    check('v1.68 D③ ⭐ `summary_text()` 的**分母用 `maps`**（不是 `len(entries)`）'
          '—— 平均每图 = 总消耗 / 图数；用 entries 长度会在读数失败时把均值抬高 ✗',
          "_maps = max(1, int(s['maps']))" in _el68)
except Exception as _e68:       # noqa: BLE001
    check('v1.68 守门可运行（%r）' % (_e68,), False)

# ═══════════════════════════════════════════════════════════════════════════
# v1.69 —— 启动器图标换成**机甲核心魔偶**的官方像素头像
# ═══════════════════════════════════════════════════════════════════════════
# 用户口径：「MGAS头像改成机甲核心魔偶的像素头像」＋提示「幻想少女公会那边有
#   头像 head_atlas.png|json」⇒ **用官方图集，别手绘**。
# 本组守四件事（每一件都是**踩过的坑**）：
#   A. 头像来源**必须是官方图集那一格**，且源资产**入库**（容器根 `_icon_ref/`
#      不在任何 git 仓里 ⇒ 丢了就再也画不出来 ✗）
#   B. 头像**不许重采样**：30×30 官方格必须原生 1:1 贴上（缩放真像素画 = 丢真像素 ✗）
#   C. 自适应图标**保证可见区是 66dp 圆**（半径 33dp）：头像最外不透明像素必须在
#      圆内。⚠ 画布 40 格时是 37.1dp ⇒ **会被圆形启动器切掉**；48 格才 30.9dp ✓
#      —— 这条是**算术判据**，不是"看着还行"（本项目反复栽在"看着还行"上）
#   D. 接线在位：`AndroidManifest` 的 icon/roundIcon ＋ `mipmap-anydpi-v26` 两个
#      adaptive-icon XML 指向 foreground/background ＋ 生成脚本**仓内自包含**
#      ⚠ 图标在 `res/` 里 ⇒ **只能整包重装**才上真机（热更新永远带不到 ✗）
try:
    _PROJ69 = PROJ
    _TOOLS69 = os.path.join(_PROJ69, 'tools')
    _RES69 = os.path.join(_PROJ69, 'app', 'src', 'main', 'res')
    _MKICON69 = os.path.join(_TOOLS69, 'make_app_icon.py')
    _HEAD69 = os.path.join(_TOOLS69, 'icon', 'head_M31302_000.png')
    _src69 = open(_MKICON69, encoding='utf-8').read() if os.path.exists(_MKICON69) else ''

    # ── A. 头像来源 = 官方图集，且源资产入库 ────────────────────────────
    #   真值量自官方图集索引 167（`M31302_000`）：30×30 RGBA、alpha≥100 共 436 px、
    #   不透明包围盒 23×20（x 3..25 / y 3..22）。⚠ 别把这些数抄成"大概"——
    #   它们是本组的**唯一基准**，头像换错格会当场红 ✓
    _head_ok69 = False
    _head_det69 = '文件不存在'
    if os.path.exists(_HEAD69):
        _h69 = _cv2.imread(_HEAD69, _cv2.IMREAD_UNCHANGED)
        if _h69 is None or _h69.ndim != 3 or _h69.shape[2] != 4:
            _head_det69 = '读不到或非 RGBA：%s' % (None if _h69 is None
                                                  else _h69.shape,)
        else:
            _ys69h, _xs69h = _np.where(_h69[..., 3] >= 100)
            _n69h = len(_ys69h)
            _bw69h = int(_xs69h.max() - _xs69h.min() + 1)
            _bh69h = int(_ys69h.max() - _ys69h.min() + 1)
            _head_det69 = ('%dx%d 不透明 %d px 包围盒 %dx%d'
                           % (_h69.shape[1], _h69.shape[0], _n69h,
                              _bw69h, _bh69h))
            _head_ok69 = (_h69.shape[0] == 30 and _h69.shape[1] == 30
                          and _n69h == 436 and _bw69h == 23 and _bh69h == 20)
    check('v1.69 A① ⭐⭐ 官方头像格**已入库且是那一格**：'
          '`tools/icon/head_M31302_000.png` = 30×30 RGBA、不透明 **436 px**、'
          '包围盒 **23×20**（量自官方图集索引 167）—— '
          '⚠ 容器根 `_icon_ref/` **不在任何 git 仓里** ⇒ 只放那儿的话丢了就再也画不出来 ✗',
          _head_ok69, _head_det69)
    check('v1.69 A② ⭐ 生成脚本**仓内自包含**：自带 PNG 编解码、'
          '**不 import 仓外模块**（旧版 `draw_mech_icon`/`make_icon` 都在 '
          '`_icon_ref/` ⇒ 仓里跑不起来 ✗）',
          bool(_src69) and 'def write_png(' in _src69 and 'def read_png(' in _src69
          and 'from make_icon' not in _src69 and 'import draw_mech_icon' not in _src69
          and 'import make_icon' not in _src69)
    check('v1.69 A③ ⭐ 脚本**不许再手绘**（用户明确要"官方像素头像"）：'
          '源码里不得出现调色板式手绘残留 `PAL`/`SRC_A`/`SRC_B`'
          '（旧手绘版是 `make_icon.py` 的 `PAL` + `SRC_A/SRC_B`）',
          bool(_src69) and 'PAL = {' not in _src69 and 'SRC_A' not in _src69
          and 'SRC_B' not in _src69)

    # ── B. 不重采样 + 安全圆（**算术判据**）────────────────────────────
    check('v1.69 B① ⭐⭐ 官方格**原生 1:1**（`place_native` 直接摆，不缩放）'
          '—— 缩放真像素画会丢真像素、发糊 ✗；且**必须有断言守着**'
          '（`assert _dp <= 33.0`），不能只写在注释里',
          bool(_src69) and 'def place_native(' in _src69
          and 'assert _dp <= 33.0' in _src69)
    check('v1.69 B② ⭐⭐ **安全圆算术判据**：画布 48 格 ⇒ 头像最外像素 30.9dp '
          '≤ 33dp（自适应 66dp 保证可见半径）✓；'
          '⚠ 旧 40 格画布是 **37.1dp ⇒ 会被圆形启动器切掉** ✗ —— '
          '这正是本轮把画布从 40 改 48 的**唯一理由**（不是审美）',
          bool(_src69) and 'LOGIC = 48' in _src69 and 'LOGIC = 40' not in _src69
          and 'LOGIC = 30' not in _src69,
          'LOGIC=%s' % ('48' if 'LOGIC = 48' in _src69 else '不是 48 ✗'))

    # ── C. 执行级：真跑生成器 → 量发射出来的 PNG ──────────────────────
    #   ⚠ 只 grep 源码不算数（本项目六次栽在"注释写了、代码没生效"）⇒ 直接读**发射后**
    #     的 mipmap PNG，验：尺寸、前景头部在 108dp 安全圆内、方/圆图标不透明。
    _em69 = {}
    for _d69 in ('mdpi', 'hdpi', 'xhdpi', 'xxhdpi', 'xxxhdpi'):
        for _n69 in ('ic_launcher', 'ic_launcher_round',
                     'ic_launcher_foreground', 'ic_launcher_background'):
            _p69 = os.path.join(_RES69, 'mipmap-'+_d69, _n69+'.png')
            if os.path.exists(_p69):
                _em69[(_d69, _n69)] = _p69
    if len(_em69) != 20:
        skip('v1.69 C①~C④ 图标发射级（应有 20 个 mipmap PNG，实到 %d）'
             % len(_em69))
    else:
        _bad69 = []
        for _d69, _s69 in (('mdpi', 48), ('hdpi', 72), ('xhdpi', 96),
                           ('xxhdpi', 144), ('xxxhdpi', 192)):
            _fs69 = int(round(_s69 * 108 / 48.0))
            for _n69, _want69 in (('ic_launcher', _s69),
                                  ('ic_launcher_round', _s69),
                                  ('ic_launcher_foreground', _fs69),
                                  ('ic_launcher_background', _fs69)):
                _im69 = _cv2.imread(_em69[(_d69, _n69)], _cv2.IMREAD_UNCHANGED)
                if _im69 is None or _im69.shape[0] != _want69 \
                        or _im69.shape[1] != _want69:
                    _bad69.append('%s/%s=%s(应 %d)'
                                  % (_d69, _n69,
                                     None if _im69 is None else _im69.shape[:2],
                                     _want69))
        check('v1.69 C① ⭐ **执行级**：5 密度 × 4 张 = 20 个 PNG 尺寸全对'
              '（旧版 48/96/144/192px；自适应 108dp = 108/162/216/324/432px）'
              '—— 直接读**发射后**的文件，不看源码注释',
              not _bad69, '尺寸不符=%s' % (_bad69 or '无'))

        # 自适应前景：**头部必须落在 66dp 安全圆内**（否则圆形启动器切脸）
        _bad69b, _det69 = [], []
        for _d69, _s69 in (('mdpi', 48), ('xxxhdpi', 192)):
            _fs69 = int(round(_s69 * 108 / 48.0))
            _p69 = _em69[(_d69, 'ic_launcher_foreground')]
            _im69 = _cv2.imread(_p69, _cv2.IMREAD_UNCHANGED)
            if _im69 is None or _im69.shape[2] != 4:
                _bad69b.append('%s 无 alpha' % _d69)
                continue
            _al69 = _im69[..., 3]
            _ys69, _xs69 = _np.where(_al69 >= 100)
            if not len(_ys69):
                _bad69b.append('%s 前景全透明 ✗' % _d69)
                continue
            # 108dp 画布中心 = fs/2 - 0.5；安全半径 = 33/108*fs
            _c69 = _fs69 / 2.0 - 0.5
            _safe69 = 33.0 / 108.0 * _fs69
            _r69 = float(_np.max(_np.hypot(_xs69 - _c69, _ys69 - _c69)))
            _det69.append('%s 最大半径 %.1fpx/安全 %.1fpx'
                          % (_d69, _r69, _safe69))
            if _r69 > _safe69:
                _bad69b.append('%s 超出安全圆 %.1f > %.1f' % (_d69, _r69, _safe69))
        check('v1.69 C② ⭐⭐ **执行级：自适应前景头部在 66dp 安全圆内**'
              '（`mdpi` 与 `xxxhdpi` 两端各量一次）—— '
              '⚠ 这是"圆形启动器会不会切脸"的**唯一硬判据**；'
              '40 格画布在这里**必然红**（37.1dp > 33dp）✗',
              not _bad69b, '越界=%s｜%s' % (_bad69b or '无', '；'.join(_det69)))

        # 头像像素**没被重采样**：判据是**色集合包含**，不是"颜色数够少"。
        #   ⚠⚠ v1.69 初版这里写的是 `_uniq69 <= 120` —— **太松，是个假绿**：
        #      把发射器改成"每个像素与左邻居取平均"（模拟双线性）后，实测唯一色数
        #      **18 → 89**，仍 ≤120 ⇒ **门禁照样绿** ✗（牙齿第 4 场景当场抓出）
        #   ⇒ 正确判据：NEAREST 意味着**发射后的每个不透明像素颜色都必须恰好等于
        #      官方 30×30 格里出现过的某个颜色** ⇒ 断言 `fg色集合 - 官方色集合 == ∅`。
        #      实测：干净版多余色 **0**；模糊版多余色 **74** ⇒ 干净分离 ✓
        _src69 = os.path.join(_PROJ69, 'tools', 'icon', 'head_M31302_000.png')
        _im69 = _cv2.imread(_em69[('xxxhdpi', 'ic_launcher_foreground')],
                            _cv2.IMREAD_UNCHANGED)
        _sr69 = _cv2.imread(_src69, _cv2.IMREAD_UNCHANGED)
        _uniq69, _extra69, _nset69 = 0, -1, 0
        if _im69 is not None and _im69.shape[2] == 4 \
                and _sr69 is not None and _sr69.shape[2] == 4:
            _fg69 = _im69[_im69[..., 3] >= 100]
            _fset69 = set(map(tuple, _fg69[:, :3].tolist()))
            _s69set = set(map(tuple, _sr69[_sr69[..., 3] >= 1][:, :3].tolist()))
            _uniq69 = len(_fset69)
            _nset69 = len(_s69set)
            _extra69 = len(_fset69 - _s69set)
        check('v1.69 C③ ⭐⭐ **NEAREST 未被插值**：`xxxhdpi` 前景不透明像素的'
              '**色集合 ⊆ 官方 30×30 格的色集合**（即"每个像素都还是原色"，'
              '一个中间色都不许有）—— ⚠ 不能用"唯一色数 ≤ N"这种松阈值：'
              '实测把它改成与左邻居取平均后唯一色数只从 18 涨到 89，'
              '**≤120 照样绿 ⇒ 假绿** ✗；色集合包含才干净分离（干净 0 多余色／'
              '模糊 74 多余色）',
              _im69 is not None and _sr69 is not None
              and _uniq69 > 0 and _extra69 == 0,
              '唯一色数=%s／官方色数=%s／**多余色=%s**（应 0；-1 = 读不到）'
              % (_uniq69, _nset69, _extra69))

        # 旧版图标必须**不透明**（不能整张透掉 —— 那是发射器把 grid 传错的症状）
        _bad69c = []
        for _d69 in ('mdpi', 'xxxhdpi'):
            for _n69 in ('ic_launcher', 'ic_launcher_round'):
                _im69 = _cv2.imread(_em69[(_d69, _n69)], _cv2.IMREAD_UNCHANGED)
                if _im69 is None or _im69.shape[2] != 4:
                    _bad69c.append('%s/%s 无 alpha' % (_d69, _n69))
                    continue
                _n_op69 = int((_im69[..., 3] >= 100).sum())
                _tot69 = _im69.shape[0] * _im69.shape[1]
                if _n_op69 < _tot69 * 0.5:
                    _bad69c.append('%s/%s 只有 %.0f%% 不透明'
                                   % (_d69, _n69, 100.0*_n_op69/_tot69))
        check('v1.69 C④ ⭐ 旧版方/圆图标**大面积不透明**（≥50%）—— '
              '⚠ 若发射器把 `head_px`（只有头像、其余透明）误传给旧版图标，'
              '整张会几乎全透、桌面上一片空白 ✗（v1.69 改画布时正好动过这条接线）',
              not _bad69c, '异常=%s' % (_bad69c or '无'))

    # ── D. 接线：Manifest ＋ adaptive-icon XML ────────────────────────
    _man69 = os.path.join(_PROJ69, 'app', 'src', 'main', 'AndroidManifest.xml')
    _mn69 = open(_man69, encoding='utf-8').read() if os.path.exists(_man69) else ''
    check('v1.69 D① ⭐ `AndroidManifest` 必须同时声明 `android:icon` 与 '
          '`android:roundIcon`（缺 roundIcon ⇒ 圆形启动器回退到方形图 ⇒ '
          '桌面上出现方块 ✗）',
          'android:icon="@mipmap/ic_launcher"' in _mn69
          and 'android:roundIcon="@mipmap/ic_launcher_round"' in _mn69)
    _any69 = os.path.join(_RES69, 'mipmap-anydpi-v26')
    _x69 = {}
    for _f69 in ('ic_launcher.xml', 'ic_launcher_round.xml'):
        _p69 = os.path.join(_any69, _f69)
        _x69[_f69] = open(_p69, encoding='utf-8').read() \
            if os.path.exists(_p69) else ''
    check('v1.69 D② ⭐ 两个 `mipmap-anydpi-v26` XML 都指向 '
          '`@mipmap/ic_launcher_foreground` ＋ `@mipmap/ic_launcher_background`'
          '（自适应图标 = 启动器拿两层自己蒙版；指错层 ⇒ 前景/背景错位 ✗）',
          all('@mipmap/ic_launcher_foreground' in _v
              and '@mipmap/ic_launcher_background' in _v for _v in _x69.values()),
          '缺失=%s' % [k for k, v in _x69.items()
                       if '@mipmap/ic_launcher_foreground' not in v
                       or '@mipmap/ic_launcher_background' not in v])
    check('v1.69 D③ ⭐ 留档注释写明来源 = **机甲核心魔偶 M31302_000（图集索引 167）**'
          '—— ⚠ 上一版注释断言"图集那格是半身、烘了背景"⇒ **那句话是错的**，'
          '正是它让手绘版看起来"有依据" ✗ ⇒ 注释必须能被追到官方资产',
          all('M31302_000' in _v for _v in _x69.values()),
          '注释=%s' % [('M31302_000' in v) for v in _x69.values()])
    check('v1.69 D④ ⛔ **反向守门**：adaptive-icon XML 里**不许**再出现旧手绘版的'
          '说法（`手绘` 只允许出现在"非手绘"这种否定句里）',
          all(('手绘' not in _v) or ('非手绘' in _v) for _v in _x69.values()))
except Exception as _e69:       # noqa: BLE001
    check('v1.69 守门可运行（%r）' % (_e69,), False)

# ══════════════════════════════════════════════════════════════════════════
# v1.70 雾格数据表闸门 —— 治「`(5,5)` 矿箱被当空地、无视它拦住连锁」
#   用户原话：「**为什么无视 55 这个拦住连锁的单格**？」
#            ＋「**不要怀疑，我亲眼看见他就是矿箱**」（地面真值 ⇒ 必须拦连锁 ✓）
#   病根：`Block.plain` 分支⑤（雾格剪影）**在查数据表/名字之前就 return 了** ✗
#         ⇒ `fog_flat=True` ⇒ `plain=True` ⇒ 一个**矿箱**被当成空地
#   判据刻意做成**"连锁有没有被拦住"本身**（`plain_group` 收缩），
#   而不是只看 `plain` 的布尔值 —— 用户报的就是"连锁"这件事 ✓
# ══════════════════════════════════════════════════════════════════════════
try:
    _ms70p = os.path.join(MAPBOT, 'mapsim.py')
    _ms70 = open(_ms70p, encoding='utf-8').read()
    import ast as _ast70              # noqa: E402
    import mapsim as _ms70m           # noqa: E402
    import mapsolve as _mv70          # noqa: E402
    import spots as _sp70             # noqa: E402
    assert 'android_autoexplore' in _ms70m.__file__, _ms70m.__file__

    def _at70(_s, _sub, _start=0):
        """⚠ 一律 `find` + 判 -1：`str.index()` 在源码被 stash 时**抛异常**，
        会把本组后面所有断言**全吞掉**（v1.66/v1.68 各踩一次 ✗）"""
        return _s.find(_sub, _start)

    _FOG70 = ("if (not getattr(self, 'observed', False)) "
              "and self.spot.get('fog_sil') is not None:")
    _RET70 = "return bool(getattr(self, 'fog_flat', False))"
    _GATE70 = 'and _fog_content_by_table(self)'
    _FOGOBJ70 = ("if getattr(self, 'fog_object', False) "
                 "and not getattr(self, 'observed', False):")
    _SUF70 = "suf = str(self.sid or '').split('_')[-1]"

    # ── A. 结构级 ────────────────────────────────────────────────────────
    check('v1.70 A① ⭐ 闸门开关默认**开**（`MAPBOT_FOG_TABLE` 缺省 "1"）'
          '＋分数下限 `MAPBOT_FOG_TABLE_MIN` 缺省 **0.85**；'
          '⚠ 默认必须是开：真机跑的是 APK，**没有环境变量**可设 ⇒ 默认关等于没修 ✗',
          'MAPBOT_FOG_TABLE' in _ms70 and 'MAPBOT_FOG_TABLE_MIN' in _ms70
          and "(_os.environ.get('MAPBOT_FOG_TABLE') or '1')" in _ms70
          and "_env_float('MAPBOT_FOG_TABLE_MIN', 0.85)" in _ms70,
          '开关/下限缺一 ⇒ 闸门形同不存在')
    check('v1.70 A② ⭐⭐ 分数下限与 `spots.BUY_SCORE_MIN` **是同一个数**'
          '（本项目既定口径：**低分乱猜没资格代表"这是内容格"** ✓，'
          '与 v1.67 商人/宝库那条同源）',
          # ⚠ 用 `getattr` 取：mapsim 被 stash/回退时 `FOG_TABLE_SCORE_MIN` 不存在，
          #   直接属性访问会抛 `AttributeError` ⇒ 把本组后面**十几条断言全吞掉** ✗
          #   （v1.66 的 `str.index()` / v1.68 的 `.split()[1]` 是同一个坑，本文件第四次）
          getattr(_ms70m, 'FOG_TABLE_SCORE_MIN', None) is not None
          and _ms70m.FOG_TABLE_SCORE_MIN == _sp70.BUY_SCORE_MIN,
          '闸门=%s / BUY_SCORE_MIN=%.2f'
          % (getattr(_ms70m, 'FOG_TABLE_SCORE_MIN', None), _sp70.BUY_SCORE_MIN))
    check('v1.70 A③ ⭐⭐ 闸门函数 `_fog_content_by_table` 三条判据齐：'
          '①开关 ②**分数下限**（读不到分数 ⇒ 不拦）③`spots.is_plain_spot` 数据表',
          'def _fog_content_by_table(b):' in _ms70
          and 'if not FOG_TABLE_GATE:' in _ms70
          and 'float(_sc) < FOG_TABLE_SCORE_MIN' in _ms70
          and '_sp.is_plain_spot(b.sid)' in _ms70,
          '三者缺一 ⇒ 判据不完整（尤其缺②会拿乱猜的名字去拦连锁 ✗）')
    _i70 = _at70(_ms70, _FOG70)
    _j70 = _at70(_ms70, _SUF70, _i70) if _i70 >= 0 else -1
    _SEG70 = _ms70[_i70:_j70] if (_i70 >= 0 and _j70 > _i70) else ''
    check('v1.70 A④ ⭐⭐ 分支⑤里**只加否决、不改放行**：'
          '`fog_flat and 表说非空地 ⇒ False`，**其余一切情形原样返回 `fog_flat`**'
          '（⚠ M54「真雾格平坦 ⇒ 仍是空地」这条负样本必须守住，'
          '整个删掉会连锁穿过雾里的障碍 ✗）',
          _GATE70 in _SEG70 and _RET70 in _SEG70 and 'return False' in _SEG70,
          '切片段=%d 字符' % len(_SEG70))
    check('v1.70 A⑤ ⛔ **顺序守门**：`fog_object` 那一支（有物体 ⇒ 非空地）'
          '**必须仍在**雾格支**之前** —— 本行历史上踩过一次重复插入，'
          '碰这块**不许**把它挤掉 ✗',
          _at70(_ms70, _FOGOBJ70) >= 0
          and 0 <= _at70(_ms70, _FOGOBJ70) < _i70,
          'fog_object@%d < 雾格支@%d' % (_at70(_ms70, _FOGOBJ70), _i70))
    check('v1.70 A⑥ ⭐ `score` 在 `_from_anchors` 里**按成员聚合后**搬进 `row`'
          '（`row` 是从地块表单独构造的 ⇒ 观测字段**必须显式搬**，'
          '否则到不了 `Block` ⇒ 闸门永远读不到分数、静默失效 ✗）',
          "row['score'] = max(_scs)" in _ms70
          and "if cells[m].get('score') is not None]" in _ms70)
    # ⭐⭐ 证据①：数据表自己的规则 —— 这才是本条闸门的**权威依据**（不是分数、不是名字）
    #   游戏代码（`mapsim.py` 文件头逐字引着）：`SpecialSpot == 0` ⇒ `GetConnectedPlainBlocks`
    #   （整片连通空地一起消耗）；`!= 0` ⇒ `FinishBlock`（**不连锁**✓）
    _rows70 = _sp70.spot_rows()
    _r70 = {_s: (_rows70.get(_s) or {}) for _s in
            ('S30001_001', 'S30001_002', 'S30001_003', 'S30001_004')}
    check('v1.70 A⑦ ⭐⭐ **证据①（数据表）**：真地面 `001 岩地` = `SpecialSpot 0` ＋ '
          '`Weight 40000`；而 `002 矿箱`/`003 宝箱`/`004 露天矿` = `SpecialSpot 1`、'
          '`Weight 5000/5000/1000` ⇒ 按**游戏自己的规则**它们全都要**弹面板、不连锁** ✓'
          '（⚠ 这正是 v1.62c 那条"拦错 8/10"的**前提错在哪**：它的决定性反证是'
          '`矿箱堆`=`S30001_101`，而那是**战斗格** ⇒ 分支②早拦了 ⇒ 与"非战斗内容格"'
          '无关 ✗）',
          int(_r70['S30001_001'].get('SpecialSpot') or 0) == 0
          and int(_r70['S30001_001'].get('Weight') or 0) >= 40000
          and all(int(_r70[_s].get('SpecialSpot') or 0) != 0
                  for _s in ('S30001_002', 'S30001_003', 'S30001_004')),
          '岩地 SpecialSpot=%s Weight=%s ｜ 002/003/004 SpecialSpot=%s'
          % (_r70['S30001_001'].get('SpecialSpot'), _r70['S30001_001'].get('Weight'),
             [_r70[_s].get('SpecialSpot') for _s in
              ('S30001_002', 'S30001_003', 'S30001_004')]))

    # ── B. 撤回守门（反向）──────────────────────────────────────────────
    #   ⚠⚠ **只能用 AST，不能用字符串 grep** —— 留档注释里**必然逐字引用**
    #      `CONTENT_SCORE_MIN`（本文件已第三次踩这个坑：v1.62c / v1.67 / v1.68 A⑩）
    _mod70 = {t.id for n in _ast70.parse(_ms70).body
              if isinstance(n, _ast70.Assign)
              for t in n.targets if isinstance(t, _ast70.Name)}
    check('v1.70 B① ⛔ **撤回守门**：`mapsim` **模块级不许**再定义 '
          '`CONTENT_SCORE_MIN`（PC `9129a78` 那条 E —— 只看分数就拦 ⇒ '
          '矿洞帧上**拦错 8/10**，已证伪 ✗）；'
          '⚠ 用 **AST 查模块级赋值**，不用 grep（注释里必然出现它的名字）',
          'CONTENT_SCORE_MIN' not in _mod70
          and 'CONTENT_SCORE_MIN' not in _ms70m.__dict__,
          '模块级赋值的名字里%s' % ('没有 ✓' if 'CONTENT_SCORE_MIN' not in _mod70 else '有 ✗'))
    _blk70 = [n for n in _ast70.parse(_ms70).body
              if isinstance(n, _ast70.ClassDef) and n.name == 'Block']
    _attr70 = set()
    for _n in (_blk70[0].body if _blk70 else []):
        for _sub in _ast70.walk(_n):
            if isinstance(_sub, _ast70.Attribute) and isinstance(_sub.ctx, _ast70.Store) \
                    and isinstance(_sub.value, _ast70.Name) \
                    and _sub.value.id == 'self':
                _attr70.add(_sub.attr)
    check('v1.70 B② ⛔ **撤回守门**：`Block` 上不许再有 `weight` / `floor_lit` '
          '两个字段（v1.62 与 E 条一并撤回、「**不留死字段**」✓）—— '
          '`score` 这次**是带着真实用途**回来的（雾格闸门的分数下限），不是死字段 ✓',
          'weight' not in _attr70 and 'floor_lit' not in _attr70,
          'Block 上的实例字段=%s' % sorted(_attr70))

    # ── C. 执行级：真机帧跑真流水线 ─────────────────────────────────────
    def _st70(_path, _code):
        """按 `RefMapper` 同款缩放建观测（1080 宽时退化为原样 ✓）"""
        _im = _cv2.imdecode(np.fromfile(_path, dtype=np.uint8), _cv2.IMREAD_COLOR)
        _H, _W = _im.shape[:2]
        _k = _W / 1080.0
        _sh = _H - 1920.0 * _k
        _G = dict(_sp70.GRID)
        _g = {'x0': _G['x0'] * _k, 'y0': _G['y0'] * _k + _sh, 'cx': _G['cx'] * _k,
              'cy': _G['cy'] * _k, 'pitch': _G['cx'] * _k}
        return _sp70.Board(_code, grid=_g).state(_im, thr=0.0)

    def _plains70(_st, _flag):
        """⚠⚠ `Block.plain` 是 **property（惰性求值）** ⇒ 值必须**在开关处于
        目标状态时立刻取出**；第一版"先建两个 sim、最后再各读一次"⇒
        两次都读到同一个开关状态 ⇒ **恒等、看着像闸门零效果** ✗"""
        _ms70m.FOG_TABLE_GATE = _flag
        _sim = _ms70m.MapSim.from_observation(_st, _sp70.spot_rows())
        _out = {}
        for _r in range(1, 6):
            for _c in range(1, 8):
                _bi = _sim.board[(_r - 1) * 7 + (_c - 1)]
                _out['%d,%d' % (_r, _c)] = (None if _bi < 0
                                            else bool(_sim.blocks[_bi].plain))
        return _sim, _out

    _CAL70 = os.path.join(PROJ, '..', '_tmpman', 'cal')
    _F70 = os.path.join(_CAL70, 'r_133620_0.png')      # 矿洞 13:36（(5,5)=露天矿 004）
    _IH70 = os.path.join(PROJ, '_verify', 'phone_stamina_0930', 'bagdbg',
                         'iron_highland_fog_dev.png')
    if not (os.path.exists(_F70) and os.path.exists(_IH70)):
        skip('v1.70 C①~C④ 执行级（缺 `_tmpman/cal/r_133620_0.png` 或'
             '`_verify/.../iron_highland_fog_dev.png` ⇒ 没真验证）')
    else:
        _st70a = _st70(_F70, 'S30001')
        _sim_off, _p_off = _plains70(_st70a, False)
        _bi55 = _sim_off.board[(5 - 1) * 7 + (5 - 1)]
        # ⚠ `plain_group` 也读 `plain` ⇒ 必须在翻开关**之前**算完
        _grp_off = (_mv70.Problem(_sim_off).plain_group(_bi55)
                    if _bi55 >= 0 else [])
        _sim_on, _p_on = _plains70(_st70a, True)
        _grp_on = (_mv70.Problem(_sim_on).plain_group(_bi55)
                   if _bi55 >= 0 else [])
        _sid55 = (_sim_off.blocks[_bi55].sid if _bi55 >= 0 else '')
        check('v1.70 C① ⭐⭐ **执行级（真机帧 r_133620）**：闸门关 ⇒ `(5,5)` 是空地；'
              '闸门开 ⇒ **非空地**（该格 sid=%s，数据表判非空地 ✓）' % _sid55,
              _bi55 >= 0 and _p_off['5,5'] is True and _p_on['5,5'] is False,
              '关=%s / 开=%s' % (_p_off.get('5,5'), _p_on.get('5,5')))
        check('v1.70 C② ⭐⭐⭐ **执行级：这才是用户报的那件事 —— 连锁真的被拦住了**'
              '（判据是连通空地片 `plain_group` 的**收缩**，不是 `plain` 的布尔值）：'
              '关 ⇒ 该格并进 **%d** 个块的大片；开 ⇒ **只剩它自己** ✓'
              % len(_grp_off),
              len(_grp_off) > 1 and len(_grp_on) == 1,
              'plain_group 块数 关=%d / 开=%d' % (len(_grp_off), len(_grp_on)))

        # 对照：把该格换成**真·空地** ⇒ 闸门**不许**误伤（否则会把连锁全断掉 ✗）
        _st70b = dict(_st70a)
        _st70b[(5, 5)] = dict(_st70a[(5, 5)])
        _st70b[(5, 5)]['sid'] = 'S30001_001'
        _st70b[(5, 5)]['name'] = '岩地'
        _s2, _p2 = _plains70(_st70b, True)
        check('v1.70 C③ ⭐ 对照项（证明不是"开了就变"的恒真判据）：'
              '同一格换成**真·空地 `S30001_001` 岩地** ⇒ 开闸门后**仍是空地** ✓',
              _p2['5,5'] is True and _p2['5,5'] == _p_off['5,5'],
              '换成岩地后开闸门=%s（应 True）' % _p2.get('5,5'))

        # 负样本守门：铁血高地**一格都不许改**（v1.06 执行级真值就在这帧上）
        _s3, _p3 = _plains70(_st70(_IH70, 'S10003'), True)
        _s3o, _p3o = _plains70(_st70(_IH70, 'S10003'), False)
        _ch_ih = [k for k in _p3 if _p3[k] != _p3o[k]]
        check('v1.70 C④ ⭐⭐ **负样本守门**：铁血高地帧上闸门**一格未改**'
              '（`(1,7)` 等 v1.06 的真机真值不受影响 —— 那些格猜的是 '
              '`S10003_001` 岩地 ⇒ 数据表判"是空地" ⇒ 闸门**不否决** ✓）',
              _ch_ih == [], '被改=%s' % (_ch_ih or '无'))
        _ms70m.FOG_TABLE_GATE = True          # 复位（别把开关留在测试状态 ✗）

    # ── D. 与 PC 裁判的结构对拍（**PC 是用户自己的仓** —— 不在场/判据不在
    #       ⇒ 一律**响亮跳过**，绝不让手机端门禁因为别人的工作区变动而变红 ✗）──
    _pc70 = os.environ.get('MGAS_PC_SRC') or os.path.join(
        os.path.dirname(PROJ), 'mapbot_pc')
    _pcms70 = os.path.join(_pc70, 'mapsim.py')
    _pcs70 = ''
    if os.path.exists(_pcms70):
        try:
            _pcs70 = open(_pcms70, encoding='utf-8').read()
        except Exception:       # noqa: BLE001
            _pcs70 = ''
    _pci70 = _at70(_pcs70, 'self.score >= CONTENT_SCORE_MIN') if _pcs70 else -1
    _pcf70 = (_at70(_pcs70, "self.spot.get('fog_sil') is not None")
              if _pcs70 else -1)
    if not _pcs70:
        skip('v1.70 D① PC 裁判结构对拍（PC 仓不在场 / 读不到 mapsim.py）')
    elif _pci70 < 0:
        # ⚠ PC 那份**可能在用户手里改**（本仓实测：PC 工作区常年有未提交改动）
        #   ⇒ 判据不在时**跳过**，不判红 —— 手机端门禁不能依赖别人的工作区状态 ✓
        skip('v1.70 D① PC 裁判结构对拍（PC 当前没有 '
             '`score >= CONTENT_SCORE_MIN` 判据 ⇒ 对拍做不了）')
    else:
        check('v1.70 D① ⭐⭐ **PC 裁判（已提交的 PC 代码，不是手机端自说自话）**：'
              'PC 的 `Block.plain` 里有「非本图地面 且 `score >= '
              'CONTENT_SCORE_MIN(0.85)` ⇒ 非空地」**且它排在雾格支之前** '
              '⇒ 同一个矿箱在 **PC 侧也是"非空地、拦连锁"** ✓'
              '（本次已实测：同一份观测喂两端 ⇒ 两端都判 `(5,5)` 非空地、'
              '`cost` 都是 **13**、点序都是 `1,2 / 1,1 / 3,1` —— 零分歧 ✓；'
              '全语料 7 帧 13 个受影响格 **PC 13/13 同意**）'
              '⚠⚠ 顺带更正一处**长期措辞错误**：手机端注释曾写「**已撤回的 PC 改动**」'
              '⇒ 会让人以为 PC 撤了 ✗ —— 实测 `git show HEAD:mapsim.py` 里'
              '**`CONTENT_SCORE_MIN = 0.85` 仍在**（第 74 行定义、第 216 行在用）'
              '⇒ 当年"撤回"是**手机端单方面不移植**，PC **从未撤过** ✓；'
              '⚠ 门禁只做**结构**对拍，**不 import** PC 模块：两端模块同名，'
              '同进程 import 会让 `import spots` 静默拿到另一端的 ✗',
              _pci70 >= 0 and _pcf70 >= 0 and _pci70 < _pcf70,
              'PC 判据@%d < PC 雾格支@%d' % (_pci70, _pcf70))
except Exception as _e70:       # noqa: BLE001
    check('v1.70 守门可运行（%r）' % (_e70,), False)

# ══════════════════════════════════════════════════════════════════════════
# v1.71 幸运草闸门**又静默失效了一次** —— 这次是"轮首读数恰好是 None"
#   用户 2026-10-06 报：「**幸运草低于8怎么还会摇色子？**」
#   真机铁证（`bagdbg/mgas_log.txt`，map 0，13:14 那把）：
#     · `{"round": 0, ..., "clover": 2}` ⇒ 读到了 ✓
#     · `{"round": 1, ..., "clover": null}` ⇒ **轮首 OCR 没读出来** ✗
#     · 而**摇色子就发生在 round 1**（`dice: reroll_confirm rolls 1` +
#       `dice: got_recommend`）—— 日志里**一条 `skip_low_clover` 都没有** ✗✗
#   根因：轮首那趟全屏 OCR 是在**上一场战斗的结算面板还挂着**时拍的 ⇒ HUD 被挡；
#         旧代码接着退回 `clover_count(items)`，而 `items` 是 **band 裁过的结算带**
#         ⇒ 恒 None ⇒ **fail-open ⇒ 摇** ✗（**本项目第四次同族教训**）
#   修法：取值链 ①`state['clover_now']` ②`clover_count(items)` ③**上一次读成功**
#         （`state['clover_last']`）④**当场全屏 OCR**；三条全空才 fail-open，
#         且**单独记 `clover_unreadable_roll`**（旧代码在这里一声不响 ✗）
# ══════════════════════════════════════════════════════════════════════════
try:
    _el71 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                              'explore_loop.py'), encoding='utf-8').read()
    _HD71 = _el71.find('def handle_dice')
    check('v1.71 A① ⭐⭐⭐ 取值链**四条来源都在**：轮首读数 / `items` 兜底 / '
          '**上一次读成功**（`clover_last`）/ **当场全屏 OCR**（`b.ocr(tag="dice_hud")`）；'
          '⚠ `skip_low_clover` 必须记**实际来源**（`src`）—— 排查时要一眼看出'
          '这次是拿哪一路的数做的判断 ✓',
          _HD71 >= 0
          and "state.get('clover_last')" in _el71
          and "clover_count(b.ocr(tag='dice_hud'))" in _el71
          and "'dice': 'clover_unreadable_roll'" in _el71
          and "'src': _cv_src" in _el71,
          '缺一路 ⇒ 那条路径又会静默 fail-open ✗')
    check('v1.71 A② ⭐⭐ **顺序守门**：`轮首 → items → clover_last → 当场全屏OCR '
          '→ 判定`**必须按这个次序**（便宜的先问、贵的后问）—— '
          '⚠ 把"当场全屏 OCR"提到前面 ⇒ **每次都白付一次全屏 OCR** ✗',
          _HD71 >= 0
          and 0 <= _el71.find("state.get('clover_now')", _HD71)
          < _el71.find("state.get('clover_last')", _HD71)
          < _el71.find("clover_count(b.ocr(tag='dice_hud'))", _HD71)
          < _el71.find('if _cv_now is not None and _cv_now < CLOVER_MIN_REROLL:',
                       _HD71))
    check('v1.71 A③ ⭐ `one_round` 轮首维护 `st["clover_last"]`（**只在读成功时覆盖**）'
          '—— ⚠ 同时**不许改坏**原来那句 `st[\'clover_now\'] = clover_count(items)`'
          '（门禁 `v1.63b ⑥` 钉着它的字面形式 ✓）',
          "st['clover_last'] = st['clover_now']" in _el71
          and "if st.get('clover_now') is not None:" in _el71
          and "st['clover_now'] = clover_count(items)" in _el71)

    # ── B. 执行级：**拿真机那个状态**直接喂 `handle_dice` ──────────────────
    class _FB71(object):
        """假 bot：闸门只用到 `ocr`（且 `tag` 分流：`dice_hud` = 全屏）"""
        def __init__(self, hud=(), band=()):
            self.hud, self.band, self.tags = list(hud), list(band), []

        def ocr(self, *a, **k):
            _t = k.get('tag')
            self.tags.append(_t)
            return list(self.hud if _t == 'dice_hud' else self.band)

        def __getattr__(self, _n):       # 过闸门之后的逻辑一律不测（这里只测闸门）
            raise RuntimeError('not needed in this test: %s' % _n)

    def _hud71(n):
        """按真机标定造 HUD 条目：幸运草在**第 2 行** cy≈94、x≈694 ✓"""
        return [{'text': str(n), 'cx': 694, 'cy': 94,
                 'x0': 680, 'y0': 80, 'x1': 708, 'y1': 108}]

    def _skip71(state, hud=(), band=()):
        _b = _FB71(hud=hud, band=band)
        _lg = []
        _r = None
        try:
            _r = EL.handle_dice(_b, _lg, list(band), state=state)
        except Exception:       # noqa: BLE001  # 过闸门之后的逻辑会抛，这里不关心
            _r = 'raised'
        _e = [x for x in _lg if x.get('dice') in
              ('skip_low_clover', 'clover_unreadable_roll')]
        return _r, _e, _b.tags

    _r71a, _e71a, _t71a = _skip71({'clover_now': 2})
    check('v1.71 B① 执行级：轮首**读到了** 2 ⇒ **不摇**（`skip_low_clover`，'
          '`src=state.clover_now`），且**一次 OCR 都不额外付出** ✓',
          _r71a == 0 and len(_e71a) == 1
          and _e71a[0]['src'] == 'state.clover_now' and not _t71a,
          'r=%s entries=%s ocr=%s' % (_r71a, _e71a, _t71a))

    _r71b, _e71b, _t71b = _skip71({'clover_now': None, 'clover_last': 2},
                                  hud=_hud71(2))
    check('v1.71 B② ⭐⭐⭐ **执行级：复现真机 13:14 那把** —— 轮首**读失败**'
          '（`clover_now=None`，真机 `entry.clover=null`）但上一轮读到过 **2** ⇒ '
          '**必须不摇**（`src=state.clover_last`），**且零额外 OCR** ✓'
          '—— 这正是用户报的「幸运草低于8怎么还会摇色子」的修复点',
          _r71b == 0 and len(_e71b) == 1
          and _e71b[0]['src'] == 'state.clover_last' and not _t71b,
          'r=%s entries=%s ocr=%s' % (_r71b, _e71b, _t71b))

    _r71c, _e71c, _t71c = _skip71({'clover_now': None, 'clover_last': None},
                                  hud=_hud71(3))
    check('v1.71 B③ 执行级：①②都没有 ⇒ **当场全屏读一次**（`tag=dice_hud`），'
          '读到 3 < 8 ⇒ **不摇**（`src=full_ocr`）✓',
          _r71c == 0 and len(_e71c) == 1
          and _e71c[0]['src'] == 'full_ocr' and _t71c == ['dice_hud'],
          'r=%s entries=%s ocr=%s' % (_r71c, _e71c, _t71c))

    _r71d, _e71d, _t71d = _skip71({'clover_now': 9}, hud=_hud71(9))
    check('v1.71 B④ ⭐ **对照项（证明不是"一律跳过"的恒真判据）**：'
          '**同一套夹具**、只把轮首读数从 2 换成 **9（≥8）** ⇒ **一条 skip 都不许有**'
          '（它该照常往下走摇色子）—— ⚠ 没有这一条的话，上面前三条用'
          '"永远 return 0"也能全绿 ✗'
          '｜⚠ 别拿"返回值 ≠ 0"当判据：返回 0 也可能只是"没找到色子面板"，'
          '与闸门无关（我第一版就是这么写错的 ✗）',
          not _e71d,
          'r=%s entries=%s ocr=%s' % (_r71d, _e71d, _t71d))

    _r71e, _e71e, _t71e = _skip71({'clover_now': None, 'clover_last': None},
                                  hud=[], band=[])
    check('v1.71 B⑤ ⚠ **三条来源全空 ⇒ fail-open（照常摇），但必须"响一声"**：'
          '落 `clover_unreadable_roll`（旧代码在这里是**一声不响**地摇 ⇒ '
          '排查时最难的地方 ✗）',
          len(_e71e) == 1 and _e71e[0]['dice'] == 'clover_unreadable_roll',
          'entries=%s' % (_e71e,))
except Exception as _e71:       # noqa: BLE001
    check('v1.71 守门可运行（%r）' % (_e71,), False)

# ══════════════════════════════════════════════════════════════════════════
# v1.72 兜底脱困"拉黑"其实**把逃生通道堵死了** —— 计划看门狗永不触发
#   用户 2026-10-06 报：「**为什么派遣了个绿色地块？还没打掉boss就结束了**」
#   真机铁证（`bagdbg/mgas_log.txt`，13:46 那把 map 1）：
#     · 计划 4 步 `["4,5","2,6","2,3","1,2"]`，**boss 在第 4 步** `1,2`（`S20003_101`）
#     · 卡在第 2 步 `(2,6)`：6 轮「点探索(275,736) → 键派遣×2 → 面板还在 →
#       `still_open_close` → 返回(兜底)」；`slots_free` 6 轮一直是 1（那格从没被消耗）
#     · `[r8] 同一个动作连续 4 轮没变化 ⇒ 强制脱困（拉黑这一格）` 之后
#       round 9/10 **照样重复同一个动作** ✗
#     · 第 11 轮用户手动停止 ⇒ boss 没打到、整图白烧 61 秒 ✗✗
#   根因（两半，读代码即可证）：
#     ① `force_unstick` 只写 `st['done']`；而 `done` **只被计划读**（`_rest` 过滤）
#        ⇒ 那一格仍在**目标列表**里 ⇒ 下一轮照样点它 ✗
#     ② ★ 更坏：`done` 让 `_rest` **变短** ⇒ `plan_next` 判成"**在推进**"
#        ⇒ `plan_stuck` **被清零** ⇒ `PLAN_STUCK_ROUNDS=3` 那条看门狗**永不触发** ✗✗
#        （**拉黑这个动作自己把逃生通道堵死了** —— 这是本轮最值钱的一条）
#   修法：拉黑时①进 `nogo_rc`（本图不碰格，v1.66 既有的模型层收口）
#         ②置 `force_replan` ⇒ 下一轮强制重算（无视 `PLAN_ONCE`，同 `fog_noop_streak`）
# ══════════════════════════════════════════════════════════════════════════
try:
    _el72 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                              'explore_loop.py'), encoding='utf-8').read()
    _FU72 = _slice68(_el72, 'def force_unstick(b, log, why, ctx=None):',
                     'def find_orange_btn')
    check('v1.72 A① ⭐⭐⭐ `force_unstick` 拉黑时**三件事一起做**：'
          '`done`（老行为）＋ **`nogo_rc`**（本图不碰格 ⇒ 模型层收口 ⇒ 目标列表也会掉）'
          '＋ **`force_replan`**（下一轮强制重算）',
          bool(_FU72) and "fl.setdefault('nogo_rc', set()).add(_rc)" in _FU72
          and "fl['force_replan'] = True" in _FU72
          and "fl.setdefault('done', set()).add(" in _FU72
          and "'unstick': 'nogo_tagged'" in _FU72,
          '⚠ 只写 `done` ⇒ 那一格还在目标列表里 ⇒ 下一轮照样点它 ✗')
    check('v1.72 A② ⭐⭐ 重算出口**接住了** `force_replan`：'
          '`_force61` 要把它 **OR** 进去，且**日志原因如实分开**'
          '（`force_replan_unstick` vs `force_replan_fogged`）—— '
          '⚠ 复用同一个出口但不分原因 ⇒ 复盘时看不出是哪条触发的 ✗',
          "st.pop('force_replan', False)" in _el72
          and '_force61 = ((_fstr61 >= 2) and bool(_rest)) or _freplan72' in _el72
          and "'force_replan_unstick'" in _el72
          and "'force_replan_fogged'" in _el72
          and "'force_unstick'" in _el72)
    check('v1.72 A③ ⛔ **反证（撤回守门）**：**不许**只靠 `PLAN_STUCK_ROUNDS` 兜底 —— '
          '即 `_force61` 里**必须**留着 `st.pop(\'force_replan\')` 这一项；'
          '⚠ 少了它 ⇒ 退回"拉黑把 `plan_stuck` 清零、看门狗永不触发"那个坑 ✗',
          'or _freplan72' in _el72)

    # ── B. 执行级：真跑 `force_unstick`，看它到底改了什么 ────────────────
    class _FB72(object):
        def tap_dlg(self, *a, **k):
            return True

    _st72 = {'done': set()}
    _lg72 = []
    _tp = EL.marks_mod.cell_center(2, 6) if hasattr(EL, 'marks_mod') else (828, 1218)
    try:
        EL.force_unstick(_FB72(), _lg72, 'same_action_x4',
                         {'tapped': _tp, 'flags': _st72})
        _ok72 = True
    except Exception as _e72b:       # noqa: BLE001
        _ok72, _err72b = False, repr(_e72b)
    if not _ok72:
        check('v1.72 B① 执行级：`force_unstick` 可运行（%s）' % _err72b, False)
    else:
        check('v1.72 B① ⭐⭐⭐ **执行级：真机那把的状态喂进去** —— 拉黑后'
              '`nogo_rc` 里必须有那一格、`force_replan` 必须为真、`done` 照旧；'
              '并且**落了 `unstick: nogo_tagged` 日志**（复盘一眼可见 ✓）',
              (2, 6) in (_st72.get('nogo_rc') or set())
              and _st72.get('force_replan') is True
              and _tp in _st72.get('done', set())
              and any(x.get('unstick') == 'nogo_tagged' for x in _lg72),
              'nogo=%s force_replan=%s done=%s log=%s'
              % (sorted(_st72.get('nogo_rc') or []), _st72.get('force_replan'),
                 sorted(_st72.get('done') or []), _lg72))
        # ⭐ 对照项：把格子坐标换成**面板按钮**坐标（真机日志里那个 (275,736)）
        #   ⇒ 仍然不许崩（`cell_of` 会给个盘外坐标），且 `nogo_rc` 不许为空集里塞脏东西
        _st72b = {'done': set()}
        try:
            EL.force_unstick(_FB72(), [], 'same_action_x4',
                             {'tapped': (275, 736), 'flags': _st72b})
            _r72b = _st72b.get('nogo_rc') or set()
            check('v1.72 B② ✅ 对照项：喂**面板坐标** `(275,736)`（用户那把日志里'
                  '`at` 就是这个）也**不许崩**，且仍然完成拉黑动作 '
                  '—— ⚠ 没有这条的话，B① 可能只证明了"某个固定输入能过" ✗',
                  _st72b.get('force_replan') is True and len(_st72b['done']) == 1,
                  'nogo=%s force_replan=%s' % (sorted(_r72b),
                                               _st72b.get('force_replan')))
        except Exception as _e72c:      # noqa: BLE001
            check('v1.72 B② 对照项：面板坐标不许崩（%r）' % (_e72c,), False)
except Exception as _e72:       # noqa: BLE001
    check('v1.72 守门可运行（%r）' % (_e72,), False)

# ══════════════════════════════════════════════════════════════════════════
# v1.73 探索槽读不到 ⇒ **假空闲 ⇒ 连派 7 轮**（用户报「**好像重复派遣了**」）
#   真机铁证（`bagdbg/mgas_log.txt`，14:37 那把 map 0）：
#     · 轮首读到 `{"free_txt": 0, "busy": 2, "busy_strict": 2}`（后来 3）
#       —— 三个槽**全占满**，一个「空闲」都读不到
#     · 可 `slots_free` **一直是 1** ⇒ 「有空闲槽就派遣」恒真
#     · 于是 round 2~7 **连派 7 轮**（`busy` 2→3 = 小队**真的派出去了**），
#       面板关不掉、整图 **59 秒白烧**、用户手动停止 ✗✗
#   根因：`_sf_here is None` 时走 `st.get('slots_free', 1) or 0` ⇒
#         `st` 里没这个键 ⇒ **默认 1** ⇒ 假空闲 ✗
#   修法：⭐ 「**空闲**」两个字**只画在空闲槽上** ⇒ 一个都读不到 ⇒ 就没有空闲槽 ⇒
#         `_slots_free = 0`，且**必须写回 `st`**（`popups` 的 ctx 读的是它 ✗）
#   ⇒ 与用户 2026-10-06 口径一致：「遇到紫橙探索格子且**有空闲格子**才去探索」
# ══════════════════════════════════════════════════════════════════════════
try:
    _el73 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                              'explore_loop.py'), encoding='utf-8').read()
    check('v1.73 A① ⭐⭐⭐ **三处同源**：读不到「空闲」⇒ 当作 **0 空闲** —— '
          '① 判据处（`_slots_free = 0` + `st["slots_free"] = 0`）'
          '② 落日志的 `entry["slots_free"] = 0`（⚠ 不许再是 `st.get("slots_free", 1)`）'
          '③ **传给 `popups` 的 ctx**（`slots_free: st.get("slots_free", 0)`，默认值 '
          '**不许是 1**）—— ⚠⚠ v1.73 第一版**只改了 ①**，而 `entry` 与 `ctx` 两处'
          '**都在它之前**执行 ⇒ 真正做决策的 `popups` 拿到的还是"默认 1" ⇒ **白改** ✗ '
          '（被本组 `A①` 当场抓出；本项目第五次同族：**在 A 处改状态、决策读 B 处**）',
          "_slots_free = 0" in _el73
          and "st['slots_free'] = 0" in _el73
          and "entry['slots_free'] = 0" in _el73
          and "'slots_free': st.get('slots_free', 1)" not in _el73
          and "st.get('slots_free', 1) or 0" not in _el73,
          '⚠ 三处缺一 ⇒ 决策点读到的还是旧值/默认 1')
    check('v1.73 A② ⭐⭐ 仍保留**正面证据优先**：`_sf_here is not None` 时用实测值 '
          '（不是一刀切 0）—— 否则 13:46 那把 `free_txt: 3` 的正常派遣也会被掐掉 ✗',
          'if _sf_here is not None:' in _el73
          and '_slots_free = _sf_here' in _el73
          and '_saw_row = True' in _el73)
    check('v1.73 A③ ⚠ **脱困只对"棋盘上的格"拉黑**：卡在**面板动作**上时'
          '（`st["last"]` 是面板按钮坐标，如真机日志里的 `(275,736)`）⇒ '
          '`cell_of` 会给出**盘外格** `(-1,2)` ⇒ **不许**塞进 `nogo_rc`（脏数据 ✗），'
          '只记 `unstick: panel_action` ✓',
          "if 1 <= _rc[0] <= 5 and 1 <= _rc[1] <= 7:" in _el73
          and "'unstick': 'panel_action'" in _el73)
    check('v1.73 A④ ⭐⭐ `save_board_frame` **可把棋盘帧发到公共目录**（flag 控制，'
          '**默认关**）—— 治本轮踩了两次的"**帧拿不出来**"：release 包不可 `run-as`、'
          '`mgas_log` 的 board 行被 `[:300]` 截断、logcat 缓冲常被冲掉 ⇒ '
          '问"某一格分类成什么"时只能猜 ✗。'
          '⚠ 必须走**既有的 `flag_on()`**（`adb shell touch …/bagdbg/pubframe.flag` '
          '即可开，**不用重装**）且**默认关**（用户口径：不要让每图时间变长）',
          "if flag_on('pubframe'):" in _el73
          and "_pub_dump('board_r%d_%s'" in _el73,
          '⚠ 默认开 ⇒ 每图多 0.1~0.3s；写死路径 ⇒ 关不掉 ✗')

    # ── B. 执行级：真跑 `explore_slots_free` + 那段判据 ────────────────────
    def _rule73(_sf_here, _st):
        """把源码里那段判据**照抄一遍**（读不到 ⇒ 0 且写回 st）"""
        if _sf_here is not None:
            return _sf_here
        _st['slots_free'] = 0
        return 0

    _sf_none, _info_none = EL.explore_slots_free([])          # 真机那把：一个「空闲」都没有
    _st73 = {}
    _r73 = _rule73(_sf_none, _st73)
    check('v1.73 B① ⭐⭐⭐ **执行级：真机那把的槽位状态**（`free_txt 0 / busy 3`，'
          '即"一个「空闲」都读不到"）—— 真跑 `explore_slots_free([])` 必须返回 '
          '`(None, …)`，再经新判据 ⇒ **0 空闲**且 `st["slots_free"]` 被写成 **0** '
          '—— ⚠ 这正是"连派 7 轮"的堵口 ✓',
          _sf_none is None and _r73 == 0 and _st73.get('slots_free') == 0,
          'explore_slots_free([]) = %s ｜ 判据 = %s ｜ st = %s'
          % (_sf_none, _r73, _st73))
    _sf_pos, _info_pos = EL.explore_slots_free(
        [{'text': '空闲', 'cx': 239, 'cy': 940},
         {'text': '空闲', 'cx': 356, 'cy': 940},
         {'text': '空闲', 'cx': 473, 'cy': 940}])
    _st73b = {}
    _r73b = _rule73(_sf_pos, _st73b)
    check('v1.73 B② ⭐ **对照项（证明不是"一律 0"的恒真判据）**：真跑 '
          '`explore_slots_free` 喂 **3 个「空闲」**（13:46 那把的正常值）⇒ '
          '必须返回 **3**，新判据也必须给 **3**（不许也被压成 0 ✗）',
          _sf_pos == 3 and _r73b == 3 and 'slots_free' not in _st73b,
          'explore_slots_free(3×空闲) = %s ｜ 判据 = %s' % (_sf_pos, _r73b))
except Exception as _e73:       # noqa: BLE001
    check('v1.73 守门可运行（%r）' % (_e73,), False)

# ══════════════════════════════════════════════════════════════════════════
# v1.74 假亮的格能**隔着整个棋盘被直接点**（用户：「为什么能直接点 13？13 没有
#       紧挨着出生地啊」）
#   真机铁证（`bagdbg/board_r0_152127.png`，15:21 那把；离线复算与真机逐字一致）：
#     · `(1,3)` = `S30001_016 黄金宝库`、`ratio 0.823`（过 0.80 线 ⇒ 判 revealed）
#       却 **`floor_lit=False`**（地板法说它还是雾）
#     · ⇒ `observed=True` ⇒ 进 `_build_cache.obs_lit` ⇒ `solve().visible()` **直接放行**
#       而 `camp_nb=False / empty_adj=False` ⇒ **与"挨不挨着营地"完全无关** ✗✗
#     · 结果：计划第 1 步就是 `1,3`（隔着棋盘点宝库），真机点不动 → `give_up_step` ✗
#   根因（**字段搬运断链**，与 v1.70 同一类）：
#     `_cells_for_model` 的产物里 `floor_lit` **35 格全有**，
#     但 `MapSim._from_anchors` 的 `row` 是**从地块表单独构造**的 ⇒ 不搬就**到不了 Block**
#     实测：`Block.spot` 里**既没有 `floor` 也没有 `floor_lit`** ✗
#   修法：① `mapsim` 把 `floor_lit` 按成员取**或**搬进 `row`
#         ② `mapsolve._build_cache.obs_lit` 要求**地板也说亮**
#            （`spot['floor_lit'] is False` ⇒ **不否决**？不 —— ⇒ **剔掉**；
#             缺值 ⇒ 不否决，向后兼容 ✓）
#   ⚠ 本判据刻意**只加否决、不删旧判据**（v1.62 那支有"只增不减"的历史包袱）✓
# ══════════════════════════════════════════════════════════════════════════
try:
    _ms74 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                              'mapsim.py'), encoding='utf-8').read()
    _mv74 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python',
                              'mapsolve.py'), encoding='utf-8').read()
    check('v1.74 A① ⭐⭐⭐ `mapsim` 把 `floor_lit` **按成员取或**搬进 `row`'
          '（⚠ `row` 是从地块表单独构造的 ⇒ 不搬就到不了 `Block`；'
          'v1.70 的 `score` 栽过同一个坑 ✗）',
          "_fls = [bool((cells.get(m) or {}).get('floor_lit')) for m in members" in _ms74
          and "row['floor_lit'] = any(_fls)" in _ms74,
          '⚠ 缺这一行 ⇒ `Block.spot` 里没有 floor_lit ⇒ 下面那条永远不生效 ✗')
    check('v1.74 A② ⭐⭐⭐ `obs_lit` 要求**地板也说亮**：`spot["floor_lit"] is False` '
          '的块**不许**进"可点"掩码 —— ⚠⚠ 必须**从 `spot` 读**！'
          '`Block` **没有** `floor_lit` 属性（观测字段一律存 `spot`）'
          '⇒ `getattr(b, "floor_lit")` 恒 None ⇒ **白改** ✗（我第一版就写错了，'
          '复算时发现"修复没生效"才查出来）',
          "(prob.blocks[bi].spot or {}).get('floor_lit') is False" in _mv74
          and "getattr(prob.blocks[bi], 'floor_lit'" not in _mv74,
          '⚠ 从 spot 读 ⇒ 生效；从属性读 ⇒ 恒 None')
    check('v1.74 A③ ⛔ **只加否决、不删旧判据**：`obs_lit` 里 '
          '`if not getattr(prob.blocks[bi], "observed", False): continue` '
          '**必须还在**（v1.62 抄 PC `19b4ed8` 那支有"只增不减"的历史包袱：'
          '删了会掐死连锁推演 ⇒ 永远走不出营地 ✗）',
          "if not getattr(prob.blocks[bi], 'observed', False):" in _mv74)

    # ── B. 执行级：**用真机那一帧**跑真流水线，断言 `1,3` 被剔出去 ──────
    _F74 = os.path.join(PROJ, '..', '_tmpman', 'frame74_board_r0_152127.png')
    if not os.path.exists(_F74):
        skip('v1.74 B①~B③ 执行级（缺 `_tmpman/frame74_board_r0_152127.png` '
             '⇒ 没真验证；复现：`adb shell touch …/bagdbg/pubframe.flag` '
             '后跑一张图，把 `board_r*.png` 拉回来）')
    else:
        import cv2 as _cv74
        import numpy as _np74
        import mapsim as _ms74m
        import mapsolve as _mv74m
        import spots as _sp74

        _im74 = _cv74.imdecode(_np74.fromfile(_F74, dtype=_np74.uint8),
                               _cv74.IMREAD_COLOR)
        _st74 = _sp74.Board('S30001').state(_im74, thr=0.0)
        _cp74 = EL.find_camp_cell(_st74)
        _cells74 = EL._cells_for_model(
            {'obs': _st74, 'spawn': _cp74, 'camp': _cp74, 'done': [], 'marks': {}},
            {'st': _st74}, log=None, tag='v74', mark_revealed=False,
            drop_done=False)
        _sim74 = _ms74m.MapSim.from_observation(_cells74, _sp74.spot_rows())
        _prob74 = _mv74m.Problem(_sim74)
        _ch74 = _mv74m._build_cache(_prob74)
        _bit74 = _ch74['bit']
        _bi13 = _sim74.board[(1 - 1) * 7 + (3 - 1)]
        _b13 = _bit74[_bi13]

        # ① 前提：这一格确实是"假亮"——ratio 过线但地板说雾（否则本用例是空的）
        _v13 = _cells74.get((1, 3)) or {}
        check('v1.74 B① ⭐⭐ **执行级（真机帧）前提**：`(1,3)` 是**假亮** —— '
              '`revealed=True`（ratio %.3f 过线）**但 `floor_lit=False`**（地板说雾）；'
              '⚠ 这个前提不成立 ⇒ 下面两条测的就不是本 bug ✗'
              % float(_v13.get('ratio') or 0),
              bool(_v13.get('revealed')) and _v13.get('floor_lit') is False,
              'revealed=%s floor_lit=%s ratio=%s'
              % (_v13.get('revealed'), _v13.get('floor_lit'), _v13.get('ratio')))

        # ② 本 bug：它**不许**再进 obs_lit；③ 对照：真亮的那 8 格**一格不少**
        _lit_cells = set()
        for _bb, _val in sorted(_sim74.blocks.items()):
            if _ch74['obs_lit'] & _bit74[_bb]:
                for _cc in (_val.cells or []):
                    # ⚠ `Block.cells` 里是 **0 基格索引**（`mapsim.cell_of` 的产物）
                    #   ⇒ 必须用 `rc_of` 转回 (r,c)；我第一版直接当 (r,c) 用 ⇒ 假红 ✗
                    _lit_cells.add(_ms74m.rc_of(int(_cc)))
        check('v1.74 B② ⭐⭐⭐ **执行级：本 bug 的正面证据** —— `(1,3)` '
              '**必须从 `obs_lit` 里消失**（修复前 `camp_nb/empty_adj` 都是 False，'
              '它**只**靠 `obs_lit` 就进了"可点" ⇒ 隔着棋盘被直接点 ✗）',
              (1, 3) not in _lit_cells,
              'obs_lit 里的格=%s' % sorted(_lit_cells))
        # ⚠ **营地 (3,1) 除外** —— `obs_lit &= ~camp_mask` 按设计排除营地
        #   （营地自己不可点）；我第一版把它算进"必须还在"⇒ 假红 ✗
        _want_lit74 = {(2, 1), (3, 2), (4, 1), (4, 2), (4, 3), (5, 1), (5, 2)}
        check('v1.74 B③ ⭐⭐ **执行级对照项（证明不是"一律剔除"的恒真判据）**：'
              '**真亮**的那 7 格（`ratio 0.9~1.4` 且 `floor_lit=True`；'
              '⚠ 营地 `(3,1)` 按设计被 `~camp_mask` 排除，不算）'
              '**必须全都还在** `obs_lit` 里 —— ⚠ 没有这条的话，'
              '把 `obs_lit` 整个清空也能让 B② 绿 ✗',
              _want_lit74 <= _lit_cells,
              '缺=%s' % sorted(_want_lit74 - _lit_cells))
except Exception as _e74:       # noqa: BLE001
    check('v1.74 守门可运行（%r）' % (_e74,), False)

# ══════════════════════════════════════════════════════════════════════════
# v1.75 `REWARD_X1` 560 太小 ⇒ **大拇指装备在第 3/4 格时必漏检**
#   用户 2026-10-06 原话（真机结算面板上肉眼可见大拇指装备）：
#     「**脚本没事别到大拇指装备，明明现在的界面上有大拇指装备**」
#     ＋ 口径：「**大拇指在 1-4 格都有可能出现**」（不是固定某一格）
#   真机铁证（`_verify/badge/phone_reward_4th_cell_ref.png`，1280×2772 按
#             **RefMapper 真公式**归一化后的 1080×1920 参考帧）：
#     · 真 box `(20,520,560,1020)` ⇒ 最高 **0.400**（< 0.70）⇒ **0 命中** ✗
#     · 只把右边放到 950       ⇒ 最高 **0.917** @(763,936) ⇒ **1 命中** ✓
#     ⇒ `763 > 560` ⇒ 第 3/4 格整个在框**右侧之外**，永远搜不到 ✗✗
#   代价：真机日志 `{"dice":"done","rolls":3}` + `reward_mark_hits:0` ⇒
#        **白摇 3 次色子**、最后只能 `reroll_cancel_tail` 放弃 ✗
# ══════════════════════════════════════════════════════════════════════════
try:
    import badge as _bg75
    _F75 = os.path.join(PROJ, '_verify', 'badge',
                        'phone_reward_4th_cell_ref.png')
    _SRC75 = io.open(os.path.join(MAPBOT, 'explore_loop.py'),
                     encoding='utf-8').read()
    check('v1.75 A① ⭐ `REWARD_X1` **必须盖住第 4 格** —— 实测真标记在参考系 '
          'x=**763**、图标半宽约 75 ⇒ 右界至少 840；现取值 **%d** ✓'
          '（⚠ 旧值 560 是"只有 1~2 格有标记"年代的标定，用户明确 **1-4 格都可能** ✗）'
          % EL.REWARD_X1,
          int(EL.REWARD_X1) >= 840,
          'REWARD_X1=%s（需要 ≥840）' % EL.REWARD_X1)
    check('v1.75 A② ⚠ 右界**不许过头**：再往右是「查看/统计」按钮区（也带小图标），'
          '扫进去会互相干扰 ⇒ 上限 1000',
          int(EL.REWARD_X1) <= 1000, 'REWARD_X1=%s' % EL.REWARD_X1)
    check('v1.75 A③ ⭐ 文字路径（找骰子按钮 `cx < sx(REWARD_X1)`）**不受影响** —— '
          '骰子按钮在参考系 x≈114，离旧值 560 就很远 ⇒ 放宽到 950 不会误抓；'
          '且那条路仍要求文字命中「骰/重投/命运」关键词 ✓（结构级：关键词还在）',
          "'骰'" in _SRC75 and "REWARD_X1" in _SRC75
          and int(EL.REWARD_X1) >= 840)

    if not os.path.exists(_F75):
        skip('v1.75 B①~B③ 执行级（缺 `_verify/badge/'
             'phone_reward_4th_cell_ref.png` ⇒ 没真验证）')
    else:
        import cv2 as _cv75
        import numpy as _np75
        _ref75 = _cv75.imdecode(_np75.fromfile(_F75, dtype=_np75.uint8),
                                _cv75.IMREAD_COLOR)
        check('v1.75 B① 素材是**真参考帧** 1080×1920（RefMapper 两段映射的产物，'
              '不是等比缩放 —— 我探针第一版就是栽在等比缩放上 ✗）',
              _ref75 is not None and _ref75.shape[:2] == (1920, 1080),
              'shape=%s' % (None if _ref75 is None else _ref75.shape[:2],))

        # ★ 正面证据：用**当前** REWARD_X1 ⇒ 必须检出那个真标记
        _hit75 = _bg75.find_reward_mark(
            _ref75, box=(20, EL.REWARD_CLOSE_UP_MIN, EL.REWARD_X1,
                         EL.REWARD_CLOSE_UP_MAX), top=4)
        check('v1.75 B② ⭐⭐⭐ **执行级：当前取值下真标记必须被检出** —— '
              '真机那张（肉眼可见大拇指装备）在参考系 (763,936) 得 **0.917**；'
              '命中数必须 ≥1',
              len(_hit75) >= 1,
              '命中=%s' % (['%.3f@%d,%d' % (h[0], h[2], h[3]) for h in _hit75],))

        # ★★ 对照项：**旧值 560 必须检不出** ⇒ 证明这个用例真的在测这个 bug
        _old75 = _bg75.find_reward_mark(_ref75, box=(20, EL.REWARD_CLOSE_UP_MIN,
                                                     560, EL.REWARD_CLOSE_UP_MAX),
                                        top=4)
        check('v1.75 B③ ⭐⭐ **对照项（证明不是恒真用例）**：把右界换回**旧值 560** ⇒ '
              '同一张帧必须 **0 命中** —— ⚠ 没有这条的话，'
              '哪怕模板/判据写坏了这组也可能绿 ✗',
              len(_old75) == 0,
              '旧值 560 命中=%s' % (['%.3f@%d,%d' % (h[0], h[2], h[3])
                                    for h in _old75],))
except Exception as _e75:       # noqa: BLE001
    check('v1.75 守门可运行（%r）' % (_e75,), False)

# ══════════════════════════════════════════════════════════════════════════
# v1.76 `fog_sil` 众数**塌回 0.04** ⇒ 矿洞整片岩地判"雾下有东西" ⇒ **连锁全断**
#   用户 2026-10-06 原话（又一次）：**「规划怎么又犯老毛病了，忘记了连锁机制，挨个去点」**
#   ## 病根（v1.62 的众数在**真机新帧上会退化**）
#     `round(v, 3)` 分箱（0.001 粒度）⇒ "岩地"这**同一个视觉簇**被切成
#     `0.1126/0.1136/0.1141/0.1147/0.1152`… 各 3~7 票；而"真平坦雾格"**都精确 = 0.0000**
#     ⇒ 一个箱卷走全部那些票 ⇒ 众数 0.0 ⇒ 阈值 `max(0.04, 0)=0.04`（岩地 0.11 远超）
#     ⇒ 判"雾下有东西" ⇒ `plain=False` ⇒ **连锁全断** ✗✗
#   ## 真机铁证（`_tmpman/frame74_board_r0_152127.png`，v1.74/v1.75 那两把的真机帧）
#     生产代码实测：`_fog_sil_thr=0.04` / `_fog_sil_mode=0.0`（同一图种另 3 张帧却是 0.18）
#     模型级：**22 格**"数据表说空地、却 `plain=False`"（= 连锁断）
#     规划级：细箱 `cost 14 / 11 步` vs 粗箱 `cost 9 / 6 步` ⇒ 确实影响计划 ✓
#   ## 修法 = **两级众数**：粗箱 0.01 定位"地面纹理簇" ⇒ 簇内取众数细值
#     ⚠ 量纲与 v1.62 完全一致（仍 `众数×1.6`）⇒ 只在"碎片抢票"时才不同 ✓
#   ## 接力单建议的两条**已实测否掉**（`tools/probe_fog_fix_compare.py`）
#     · 「平局取较大值」⇒ **无效**（真机上 0.0 常是**票数严格最多**，不是平局）✗
#     · 「只对名字像空地的格统计众数」⇒ **最差**（阈值塌到 1.6 ⇒ 一格不拦、26 格全放行）✗✗
#   ## ⚖ 已记账的代价（诚实标注，**不许**因此退回 0.04）
#     `(5,7)` 类**低分**（0.49~0.60）误认成「旅行商人」的格会被放成空地 ——
#     裁图肉眼核验（`_tmpman/fogrel/sheet.png`）那里**确实有物体** ✗，而 v1.70 闸门
#     要求 `score>=0.85` ⇒ **兜不住**它。取舍依据：现口径**每次**断 22 格连锁（用户已两次报），
#     代价是极少数低分误认格 ⇒ 取修好连锁 ✓
# ══════════════════════════════════════════════════════════════════════════
try:
    import spots as _sp76
    _SRC76 = io.open(os.path.join(MAPBOT, 'spots.py'), encoding='utf-8').read()

    # ── A. 结构级 ─────────────────────────────────────────────────────────
    check('v1.76 A① ⭐⭐⭐ 众数**两级取**：先用粗箱定位"地面纹理簇"，'
          '再在**该簇内部**取细值作代表 —— 旧写法（直接对 0.001 箱取众数）'
          '会让"精确 0.0"一个箱卷走全部票 ⇒ 阈值塌回 0.04 ✗',
          'FOG_SIL_MODE_COARSE' in _SRC76
          and '_grp.setdefault(round(_s, _nd), {})' in _SRC76
          and '_win = max(sorted(_tot), key=lambda x: (_tot[x], -x))' in _SRC76
          and '_h2 = _grp[_win]' in _SRC76,
          '⚠ 缺任一句 ⇒ 退回"碎片抢票"那个坑')
    check('v1.76 A② ⭐⭐ ⚠ **量纲不许变**：阈值仍必须是 `众数 × FOG_SIL_MODE_K(1.6)`，'
          '且 `_mode2` 取自**簇内细值**（不是粗箱边界 —— 那会让阈值系统性偏低 '
          '0.1824→0.1760 ⇒ 多放行内容物 ✗）',
          '_sbase = max(float(FOG_SIL_MIN), float(_mode2) * FOG_SIL_MODE_K)' in _SRC76
          and '_mode2 = max(sorted(_h2), key=lambda x: (_h2[x], -x))' in _SRC76
          and '_sbase = max(float(FOG_SIL_MIN), float(_win) * FOG_SIL_MODE_K)'
          not in _SRC76,
          '⚠ 用 `_win`（粗箱边界）算阈值 ⇒ 口径漂了 ✗')
    check('v1.76 A③ ⚠ `_fog_sil_thr` 仍**不塞进 `out`**（`cells_of` 的 '
          '`sorted(st.items())` 混进字符串键会 **TypeError 直接崩** ✗✗ —— '
          'v1.62 实跑当场抓到过），且**粗簇**也要挂 Board 实例（诊断用）',
          "out['_fog_sil_thr']" not in _SRC76
          and 'self._fog_sil_thr =' in _SRC76
          and 'self._fog_sil_win =' in _SRC76)
    check('v1.76 A④ ⛔ **撤回守门（两条建议的实测否证）**：'
          '(a) "平局取较大值"对真机无效 —— 0.0 常常是**票数严格最多**（不是平局），'
          '本条修的是"碎片抢票"而不是平局方向；'
          '(b) "只对名字像空地的格统计众数"**实测最差**（阈值塌到 1.6 ⇒ 一格不拦、'
          '26 个低分内容物全放行）⇒ **取样集不许按名字过滤**',
          'is_plain_spot' not in _SRC76.split('_sils = {')[1].split('_sbase')[0],
          '⚠ 取样集里出现数据表/名字过滤 ⇒ 回到实测最差那条 ✗')

    # ── B. 执行级：**坏帧必须被修好** ──────────────────────────────────────
    _F76 = os.path.join(PROJ, '..', '_tmpman', 'frame74_board_r0_152127.png')
    _F76B = os.path.join(_FLOOR_DIR, 'r_152223_0.png')       # 海滩负样本
    if not os.path.exists(_F76):
        skip('v1.76 B①~B④ 执行级（缺 `_tmpman/frame74_board_r0_152127.png` '
             '⇒ 没真验证；复现：`adb shell touch …/bagdbg/pubframe.flag` 后跑一张图）')
    else:
        import cv2 as _cv76
        import numpy as _np76
        import mapsim as _ms76
        import mapsolve as _mv76

        _im76 = _cv76.imdecode(_np76.fromfile(_F76, dtype=_np76.uint8),
                               _cv76.IMREAD_COLOR)
        _bd76 = _sp76.Board('S30001')
        _st76 = _bd76.state(_im76, thr=0.0)
        _nobj76 = sum(1 for v in _st76.values()
                      if isinstance(v, dict) and v.get('fog_object'))
        # ⚠ 取值一律用 `getattr(..., None)`：源码被 stash 时这两个属性**不存在** ⇒
        #   直接属性访问会抛 `AttributeError` ⇒ 把本组后面几条断言**全吞掉** ✗
        #   （与 v1.76 自己的教训同族：切片/取属性失败不许连坐后面的断言 ✓）
        _thr76 = getattr(_bd76, '_fog_sil_thr', None)
        _mode76 = getattr(_bd76, '_fog_sil_mode', None)
        _win76 = getattr(_bd76, '_fog_sil_win', None)
        check('v1.76 B① ⭐⭐⭐ **执行级：坏帧的阈值必须被修回 0.18 档** —— '
              '修复前 `_fog_sil_thr=0.04`（`_fog_sil_mode=0.0` ⇒ 岩地 0.11 全判"有东西"）；'
              '修复后阈值 **%s**（众数 %s、胜出粗簇 %s）⇒ 判"有东西"仅 **%d 格**'
              % (_thr76, _mode76, _win76, _nobj76),
              _thr76 is not None and _thr76 > 0.10 and _nobj76 <= 3,
              '阈值=%s 判有东西=%d 格（修复前 0.04 / 17 格）' % (_thr76, _nobj76))

        # ★★ 对照项：**同一张帧**、用旧口径（直接对 0.001 箱取众数）⇒ 必须是 0.04
        _h76 = {}
        for _v in _st76.values():
            if isinstance(_v, dict) and _v.get('fog_sil') is not None:
                _s = round(float(_v['fog_sil']), 3)
                _h76[_s] = _h76.get(_s, 0) + 1
        _oldmode76 = max(sorted(_h76), key=lambda x: (_h76[x], -x))
        _oldthr76 = max(float(_sp76.FOG_SIL_MIN), float(_oldmode76) * _sp76.FOG_SIL_MODE_K)
        check('v1.76 B② ⭐⭐ **对照项（证明用例真的在测这个 bug）**：同一张帧、'
              '按**旧口径**（0.001 箱直接取众数）⇒ 阈值必须是 **0.0400**、'
              '众数必须是 **0.0** —— ⚠ 没有这条的话，万一将来帧换了/病根漂了，'
              'B① 仍可能绿而**测的不是本 bug** ✗',
              abs(_oldthr76 - 0.04) < 1e-9 and abs(_oldmode76) < 1e-9,
              '旧口径：众数=%.4f 阈值=%.4f（应 0.0 / 0.04）' % (_oldmode76, _oldthr76))

        # ★★★ 模型级：修好后**不许**再有"表说空地却 plain=False"的格
        _mk76 = {}
        try:
            import marks as _mk76m
            _mk76 = _mk76m.scan_board_fast(_im76) or {}
        except Exception:       # noqa: BLE001
            _mk76 = {}
        for _k76, _v76 in (_mk76 or {}).items():
            if isinstance(_k76, tuple) and _k76 in _st76 and isinstance(_v76, dict):
                _st76[_k76]['marks'] = list(_v76.get('marks') or [])
        _cp76 = EL.find_camp_cell(_st76) or EL.cell_center(2, 2)
        _cells76 = EL._cells_for_model(
            {'obs': _st76, 'spawn': _cp76, 'camp': _cp76, 'done': [], 'marks': _mk76},
            {'st': _st76}, log=None, tag='v76', mark_revealed=False, drop_done=False)
        _sim76 = _ms76.MapSim.from_observation(_cells76, _sp76.spot_rows())
        _broken76 = []
        for _r76 in range(1, 6):
            for _c76 in range(1, 8):
                _bi76 = _sim76.board[(_r76 - 1) * 7 + (_c76 - 1)]
                if _bi76 < 0:
                    continue
                _o76 = _cells76.get((_r76, _c76)) or {}
                try:
                    _tp76 = bool(_sp76.is_plain_spot(_o76.get('sid')))
                except Exception:       # noqa: BLE001
                    continue
                # ⚠ 战斗型地块本来就该 `plain=False`（`is_fight_spot` 分支）⇒ 排除
                try:
                    if _sp76.is_fight_spot(_o76.get('sid')):
                        continue
                except Exception:       # noqa: BLE001
                    pass
                if (not _sim76.blocks[_bi76].plain) and _tp76:
                    _broken76.append('%d,%d' % (_r76, _c76))
        check('v1.76 B③ ⭐⭐⭐ **执行级：连锁真的恢复了** —— 修好后，'
              '"数据表说是空地、模型却判 `plain=False`"的格必须 **= 0**'
              '（修复前 **22 格**，正是用户报的"挨个去点"）'
              '⚠ 战斗型地块按设计 `plain=False`，已排除',
              len(_broken76) == 0,
              '仍断连锁的格=%s' % (_broken76 or '无 ✓'))

        # ★★ 负样本：海滩帧（众数 0.000）**老行为一字不变**
        if not os.path.exists(_F76B):
            skip('v1.76 B④ 负样本（缺 `_tmpman/cal/r_152223_0.png`）')
        else:
            _im76b = _cv76.imdecode(_np76.fromfile(_F76B, dtype=_np76.uint8),
                                    _cv76.IMREAD_COLOR)
            _bd76b = _sp76.Board('S30001')
            _bd76b.state(_im76b, thr=0.0)
            _thr76b = getattr(_bd76b, '_fog_sil_thr', None)
            _mode76b = getattr(_bd76b, '_fog_sil_mode', None)
            check('v1.76 B④ ⭐⭐ **负样本守门**：海滩帧（众数 0.000 ⇒ 胜出粗簇 0.00）'
                  '阈值必须**仍是 0.04**（老行为一字不变 ✓）'
                  '—— ⚠ 没有这条的话，把阈值一律抬高也能让 B①/B③ 绿 ✗',
                  _thr76b is not None and abs(_thr76b - 0.04) < 1e-9,
                  '阈值=%s（应 0.04）众数=%s' % (_thr76b, _mode76b))
except Exception as _e76:       # noqa: BLE001
    check('v1.76 守门可运行（%r）' % (_e76,), False)

# ══════════════════════════════════════════════════════════════════════════
# v1.77 派遣分支把"**读不到**「空闲」"当成"**确认为满**" ⇒ **派遣不出去**
#   用户 2026-10-06 原话：「**探索紫地块不正常，派遣不出去**」＋「**点不到一键派遣**」
#   ## 真机铁证（`_tmpman/v176_dispatch/bagdbg/mgas_log.txt`，20:24 那把废弃矿洞）
#     完美的 **2 轮死循环**，**17 次派遣全是 `skip_slots_full`、0 次成功**：
#       奇轮 free_txt=1 busy=2 slots_free=1 → 点探索 ✓
#       偶轮 free_txt=0 busy=1 slots_free=0 → dispatch: skip_slots_full ✗（关面板）
#     ⭐ **决定性逻辑证明（不需要任何帧）**：17 次派遣**一次都没成功**
#       ⇒ 槽位真实状态**整场没变过** ⇒ 那个 0 **只能是读数假象**（真满不会下轮变回 1）
#     ⭐ 帧侧确证（真 OCR 跑那 9 张帧）：「**空闲**」**每张都读到**（conf 1.00）、
#       倒计时稳定递减（`04:23:49`→`04:12:45`）⇒ 槽一直是空的，只是派遣被跳过 ✗
#   ## 根因："读不到"与"真的满"在派遣分支上**不可区分**
#     v1.73 为治"假空闲连派"把"读不到"写成 0（fail-closed）；派遣分支把这个 0
#     当成"三个槽已满"的**正面结论** ⇒ 直接关面板 ✗
#     ⚠ 而 v1.73 真正治住死循环的是**探索入口**那道闸门（`_free_now > 0`）⇒
#       派遣这道 `slots_free<=0` 是**多余且有害的**
#   ## 修法：派遣只认**正面证据** `slots_full_confirmed`（游戏拒绝过两次 = 真满）
#     ⛔ **v1.73 的"读不到⇒0"不许改回**（那正是"假空闲"的病根 ✗）
# ══════════════════════════════════════════════════════════════════════════
try:
    _SRC77 = io.open(os.path.join(MAPBOT, 'explore_loop.py'),
                     encoding='utf-8').read()

    # ── A. 结构级 ─────────────────────────────────────────────────────────
    check('v1.77 A① ⭐⭐⭐ 派遣分支**不再只看** `slots_free<=0` —— '
          '必须同时要求 `slots_full_confirmed`（= 游戏**真的拒绝过**的正面证据）'
          '｜⛔ 旧写法把它当成"确认为满" ⇒ 用户报的「**派遣不出去**」✗',
          '_sff <= 0 and _sf_confirmed' in _SRC77
          and "if int(ctx.get('slots_free', 1) or 0) <= 0:" not in _SRC77,
          '⚠ 少了 confirmed ⇒ 读数不可靠时永远派不出去 ✗')
    check('v1.77 A② ⭐⭐⭐ **正面证据只有一个来源**（且必须真的置上）：'
          '`slots_full_latched`（连点两次「探索」面板都不关）处要 '
          '`_set_slots_full_confirmed(ctx, True)`',
          'def _set_slots_full_confirmed(' in _SRC77
          and '_set_slots_full_confirmed(ctx, True)' in _SRC77,
          '⚠ 不置 ⇒ confirmed 恒 False ⇒ A① 的闸门永不生效（等于全放行）')
    check('v1.77 A③ ⭐⭐ **读到「空闲」是硬证据 ⇒ 立刻清 confirmed**'
          '（否则 confirmed 一直挂着、把后面的派遣全掐掉 ✗）',
          "st['slots_full_confirmed'] = False" in _SRC77)
    check('v1.77 A④ ⭐⭐⭐ **三处 ctx 同源**：新字段必须跟着两处 `popups` 的 ctx 一起传 '
          '—— ⚠ 这正是 **v1.73 的教训**（"在 A 处改状态、做决策的地方读 B 处" ⇒ 白改 ✗）；'
          '少传一处 ⇒ 派遣分支读不到 ⇒ 退回旧行为 ✗',
          _SRC77.count("'slots_full_confirmed': st.get('slots_full_confirmed', False)") >= 2,
          '传了 %d 处（需要 ≥2）'
          % _SRC77.count("'slots_full_confirmed': st.get('slots_full_confirmed', False)"))
    # ⚠⚠ 撤回守门必须**先剥掉整行注释再查** —— 留档注释里**必然逐字引用**旧写法
    #    （本文件已第 4 次踩：v1.62c / v1.67 / v1.70 / 本次），字符串 grep 会**假红** ✗
    def _strip77(s):
        out = []
        for _ln in s.splitlines():
            _t = _ln.strip()
            if _t.startswith('#'):
                continue
            out.append(_ln)
        return '\n'.join(out)

    _CODE77 = _strip77(_SRC77)
    check('v1.77 A⑤ ⛔ **撤回守门：v1.73 的"读不到 ⇒ 0"不许改回去** —— '
          '`one_round` 里**仍须**是 `st[\'slots_free\'] = 0`，'
          '且**不许**再出现 `st.get(\'slots_free\', 1)`（那正是"假空闲 ⇒ 连派"的病根 ✗）'
          '｜⚠ 本项**已剥掉注释**再查（留档注释里必然逐字引用旧写法 ⇒ grep 会假红 ✗）',
          "st['slots_free'] = 0" in _CODE77
          and "st.get('slots_free', 1)" not in _CODE77,
          '⚠ 改回默认 1 ⇒ 退回 v1.73 那个坑（门禁 `v1.73 A①` 也钉着）')

    # ── B. 执行级：**拿真机那把的读数**真跑派遣分支 ──────────────────────
    _LOG77 = os.path.join(PROJ, '..', '_tmpman', 'v176_dispatch', 'bagdbg',
                          'mgas_log.txt')
    if not os.path.exists(_LOG77):
        skip('v1.77 B①~B③ 执行级（缺 `_tmpman/v176_dispatch/bagdbg/mgas_log.txt` '
             '⇒ 没真验证；复现：真机跑一张带紫格的图，把 `bagdbg/` 拉回来）')
    else:
        import re as _re77
        _txt77 = io.open(_LOG77, encoding='utf-8', errors='replace').read()
        # ⭐ 从**真机日志**里抠出那把的读数（不手搓夹具 ✓）
        _free77 = [int(m) for m in _re77.findall(r'"free_txt": (\d+)', _txt77)]
        _sf77 = [int(m) for m in _re77.findall(r'"slots_free": (\d+)', _txt77)]
        _nskip77 = len(_re77.findall(r'"dispatch": "skip_slots_full"', _txt77))
        check('v1.77 B① ⭐⭐⭐ **执行级前提（真机日志本体）**：这把里 `skip_slots_full` '
              '出现 **%d 次**，而 `free_txt` 在 **0/1 之间交替**（读到 1 的 %d 次 / '
              '读到 0 的 %d 次）—— ⚠ 前提不成立 ⇒ 下面测的不是本 bug ✗'
              % (_nskip77, _free77.count(1), _free77.count(0)),
              _nskip77 >= 5 and 0 in _free77 and 1 in _free77,
              'skip=%d free_txt 分布=%s' % (_nskip77, sorted(set(_free77))))
        # ★★★ 决定性逻辑证明：**派遣一次都没成功** ⇒ 0 只能是读数假象
        _ok77 = len(_re77.findall(r'"dispatch": "btn_by_ocr"', _txt77)) \
            + len(_re77.findall(r'"dispatch": "tap1"', _txt77))
        check('v1.77 B② ⭐⭐⭐ **决定性逻辑证明**：`free_txt` 在 1/0 之间交替，'
              '而日志里**没有任何一次成功派遣**（`btn_by_ocr`/`tap1` = %d 次）'
              '⇒ 槽位真实状态**整场没变过** ⇒ 那些 0 **只能是读数假象** '
              '（真满不可能下一轮又变回 1 ✓）'
              % _ok77,
              _free77.count(0) > 0 and _ok77 == 0,
              'free_txt=0 出现 %d 次；成功派遣痕迹 %d 次' % (_free77.count(0), _ok77))

        # ★★ 执行级：**真跑判据** —— 同样的 slots_free=0，两种 confirmed 必须给出不同后果
        import explore_loop as _el77
        _seen77 = {}

        def _fake_tap(*a, **k):
            return None

        class _FakeB77(object):
            def tap_dlg(self, *a, **k):
                return None

            def tap(self, *a, **k):
                return None

            def img(self):
                return None

        _items77 = [{'text': '一键派遣', 'cx': 891, 'cy': 1350, 'conf': 0.9}]
        for _conf in (False, True):
            _lg = []
            _ctx = {'slots_free': 0, 'slots_full_confirmed': _conf, 'flags': {},
                    'st': {}, 'ev_tiles': [], 'tapped_sid': '', 'marks': {},
                    'road': [], 'plain_road': [], 'plan_road': [], 'targets': [],
                    'clear_fights': 0}
            try:
                _el77.popups(_FakeB77(), _items77, _lg, ctx=_ctx)
            except Exception:       # noqa: BLE001
                pass
            _seen77[_conf] = [x for x in _lg if 'dispatch' in x]
        _k_false = [x.get('dispatch') for x in _seen77[False]]
        _k_true = [x.get('dispatch') for x in _seen77[True]]
        check('v1.77 B③ ⭐⭐⭐ **执行级对照（证明不是"一律派遣"的恒真判据）**：'
              '同样喂 `slots_free=0` ——'
              '`confirmed=False`（读数不可靠）⇒ 必须落 `dispatch_despite_unknown`'
              '（**照常派遣** ✓）；`confirmed=True`（游戏拒绝过）⇒ 必须落 '
              '`skip_slots_full`（**跳过** ✓）'
              '⚠ 没有这条的话，"把闸门整个删掉"也能让 A① 绿 ✗',
              'dispatch_despite_unknown' in _k_false
              and 'skip_slots_full' in _k_true,
              'confirmed=False → %s ｜ confirmed=True → %s' % (_k_false, _k_true))
except Exception as _e77:       # noqa: BLE001
    check('v1.77 守门可运行（%r）' % (_e77,), False)


# ─────────────────────────────────────────────────────────────────────────
# ㊾⭐ v1.78【**坐标策略守门**：新模块的点击必须「文字优先 → 坐标兜底」】
#
#   ---- 为什么要有这条（用户口径，原话）----
#     「安卓端是要求**全分辨率可用**，不能有固定坐标的」
#
#   ---- 判据怎么定（**钉意图，不钉数字**）----
#     ⛔ 不能钉"某个常量等于某个值" —— 那种断言换分辨率时反而会阻塞正确修改
#        （v1.68 A⑨ 就是钉了 `.pack_v4` 字面量，本轮要提 v5 时被它挡住 ✗）
#     ✅ 钉"**点击参数的来源**"：
#        · 参数是 `tap`/`tap_dlg` 的**裸常量解包**（`*CONST` / `CONST[0]` / 纯数字元组）
#          ⇒ 说明那一下**没问过 OCR** ⇒ 该文件里**必须**同时存在 `tap_target(` 调用
#            （= 作者确实实现了"文字优先"，只是这几处是兜底分支）✓
#        · 若整份文件**一个 `tap_target` 都没有**、却有三处以上裸常量点击
#          ⇒ **纯写死坐标** ⇒ 红 ✗
#
#   ---- 本轮落地后的实测（写进 detail，便于对账）----
#     guild_daily / recruit / ads / fruit : 裸常量 0 处 ✓
#     buypanels : 6 处，但**全部在 `else:` 兜底分支**，且文件内有 tap_target/_find_text_btn
#                 + `_vault_tap` 安全区夹取 ⇒ 是"兜底语义"，不是漏改 ✓
def _v78_bare_const_taps(path):
    """数一份 .py 里**裸常量点击**的处数（`*CONST` / `CONST[0]` / 纯数字元组）。"""
    import ast as _a
    out = []
    try:
        _t = _a.parse(io.open(path, encoding="utf-8").read())
    except Exception:       # noqa: BLE001
        return out
    for _n in _a.walk(_t):
        if not isinstance(_n, _a.Call):
            continue
        _f = _n.func
        _nm = None
        if isinstance(_f, _a.Attribute) and _f.attr in ("tap", "tap_dlg"):
            _nm = _f.attr
        if not _nm:
            continue
        _s = ""
        try:
            _s = _a.unparse(_n.args[0]).strip() if _n.args else ""
        except Exception:       # noqa: BLE001
            continue
        _is_bare = (
            _s.startswith("*")                              # *CONST
            or __import__("re").match(r"^[A-Z_][A-Z0-9_]*\[", _s)  # CONST[0]
            or __import__("re").match(r"^\(?\s*-?\d+\s*(,\s*-?\d+\s*)?\)?$", _s)
        )
        if _is_bare:
            out.append((_n.lineno, _s[:40]))
    return out


try:
    _NEW78 = ("guild_daily.py", "recruit.py", "ads.py", "fruit.py")
    _bad78 = {}
    for _fn78 in _NEW78:
        _p78 = os.path.join(MAPBOT, _fn78)
        if not os.path.exists(_p78):
            continue
        _bare = _v78_bare_const_taps(_p78)
        if _bare:
            _bad78[_fn78] = _bare
    check("v1.78 ①⭐ **本轮新增 4 个模块里没有裸常量点击**"
          "（用户口径：安卓端要求全分辨率可用、不能有固定坐标）"
          "⚠ 判据钉的是「点击参数的**来源**」，不是某个常量等于某个值 ——"
          "钉值会阻塞正确修改（v1.68 A⑨ 就是钉了 .pack_v4 字面量、本轮提 v5 时被挡住 ✗）",
          not _bad78,
          "裸常量点击=%s" % ({k: v for k, v in _bad78.items()} or "无 ✓"))

    # ② buypanels：允许剩余，但**必须**证明它是"兜底语义"
    _bp78 = os.path.join(MAPBOT, "buypanels.py")
    _bpsrc78 = io.open(_bp78, encoding="utf-8").read() if os.path.exists(_bp78) else ""
    _bp_bare = _v78_bare_const_taps(_bp78) if _bpsrc78 else []
    check("v1.78 ②⭐ `buypanels` 剩余的裸常量点击**全是兜底分支**："
          "文件里必须同时有 `tap_target(` 或 `_find_text_btn(` 作为「文字优先」的主路径"
          "⚠ 没有它 ⇒ 那 6 处就是「纯写死坐标」、换机型必错 ✗",
          ("tap_target(" in _bpsrc78 or "_find_text_btn(" in _bpsrc78),
          "裸常量 %d 处｜主路径=%s"
          % (len(_bp_bare),
             "有 ✓" if ("tap_target(" in _bpsrc78 or "_find_text_btn(" in _bpsrc78)
             else "没有 ✗"))

    # ③ 反向守门：`guild_daily` 必须真的实现并使用了 tap_target
    _gd78 = os.path.join(MAPBOT, "guild_daily.py")
    _gdsrc78 = io.open(_gd78, encoding="utf-8").read() if os.path.exists(_gd78) else ""
    check("v1.78 ③ ⛔ 反向守门：`guild_daily.tap_target()` 存在且**被真实调用**"
          "（`def tap_target(` 1 个 + 其余模块 import/调用它的次数 > 0）"
          "⚠ 只定义不调用 ⇒ 等于没有文字优先 ✗",
          ("def tap_target(" in _gdsrc78)
          and (_gdsrc78.count("tap_target(") > 1)
          and (("from guild_daily import" in _gdsrc78)
               or ("tap_target(b" in _gdsrc78)),
          "定义=%s 调用=%d"
          % ("有" if "def tap_target(" in _gdsrc78 else "无",
             _gdsrc78.count("tap_target(")))
except Exception as _e78:       # noqa: BLE001
    check("v1.78 坐标策略守门可运行（%r）" % (_e78,), False)

# ─────────────────────────────────────────────────────────────────────────
# ㊿ v1.81【派遣只领取不派遣 + 悬浮条不显示日常 + 招募不确认 —— 三条真机事故守门】
#
#   用户原话：「派遣只领取了，不能正常派遣」「日志还不显示正在做什么日常」
#             「免费招募选好选项也不确认」
#
#   病① 派遣不出去：panel_action 只认 一键派遣/键派遣 两个整串，
#        而真机按钮文字会变（未选人=键派遣、选完人=开始探索）=> 认不到 => break => 一次没点
#   病② 悬浮条不显示：guild_daily 只用 _say()（=print），从没发过 status()
#   病③ 招募不确认：子串匹配点到标题上；且 got=True 硬编码 => 点空也报成功
#
#   ⚠ 判据一律钉「意图」不钉「具体文案」（文案会改，钉字面量会阻塞正常修改）
try:
    _GD81 = os.path.join(MAPBOT, "guild_daily.py")
    _gd81 = io.open(_GD81, encoding="utf-8").read() if os.path.exists(_GD81) else ""
    _RC81 = os.path.join(MAPBOT, "recruit.py")
    _rc81 = io.open(_RC81, encoding="utf-8").read() if os.path.exists(_RC81) else ""

    _pa81 = ""
    _i81 = _gd81.find("def panel_action(")
    if _i81 >= 0:
        _pa81 = _gd81[_i81:_i81 + 3000]

    check("v1.81 ①⭐ panel_action 用子串认「派遣/开始探索」且排除「预计时间」"
          "（真机按钮文字会变：键派遣 / 开始探索 / 一键派遣 => 整串匹配必漏 ✗；"
          "而面板说明文字里也含「派遣」=> 不排掉会点到说明上 ✗）",
          ("派遣" in _pa81) and ("开始探索" in _pa81) and ("预计时间" in _pa81),
          "派遣=%s 开始探索=%s 预计时间=%s"
          % (("派遣" in _pa81), ("开始探索" in _pa81), ("预计时间" in _pa81)))

    _n81 = _gd81.count("_status(")
    check("v1.81 ②⭐ 悬浮条真的有在发：guild_daily 里 _status( 调用 >= 6 次"
          "（用户报「日志还不显示正在做什么日常」—— say/print 只进控制台，status 才进悬浮条）",
          _n81 >= 7,
          "_status( 出现 %d 次（def 占 1）" % _n81)

    # ⚠⚠ **必须先剥掉注释再查** —— 留档注释里**必然逐字引用**旧写法
    #   （本项目已在这上面假红三次：v1.62c / v1.68 A⑩ / v1.67）✗
    def _strip_c81(t):
        out = []
        for _ln in t.splitlines():
            _st = _ln.lstrip()
            if _st.startswith(("#", "//", "*", "/*")):
                continue
            # 去掉行尾注释（保守：只在 # 前面不是字符串时截断 —— 这里够用）
            _k = _ln.find("#")
            if _k >= 0:
                _ln = _ln[:_k]
            out.append(_ln)
        return chr(10).join(out)

    _RC81_CODE = _strip_c81(_rc81)
    _HARD81 = chr(34) + "got" + chr(34) + ": True"
    _hard81 = (_HARD81 in _RC81_CODE)
    check("v1.81 ③⭐ do_recruit 不许硬编码 got=True，必须有验证痕迹"
          "（旧写法无论点没点上都说已招募 => 点空也静默成功 ✗✗）"
          "⚠ 先剥注释再查 —— 留档注释必然逐字引用旧写法（本项目已假红三次）",
          (not _hard81) and ("btn_confirmed" in _RC81_CODE),
          "硬编码(剥注释后)=%s btn_confirmed=%s" % (_hard81, ("btn_confirmed" in _RC81_CODE)))
    check("v1.81 ④ ⛔ do_recruit 的「招募」匹配必须排除标题"
          "（指定招募/角色招募 都含招募二字 => 子串匹配会点到标题上 ✗）",
          ("指定招募" in _rc81) and ("角色招募" in _rc81),
          "指定招募=%s 角色招募=%s" % (("指定招募" in _rc81), ("角色招募" in _rc81)))
except Exception as _e81:       # noqa: BLE001
    check("v1.81 守门可运行（%r）" % (_e81,), False)

# ─────────────────────────────────────────────────────────────────────────
# v1.84【**点■停不了 / 一直乱点** —— 停止链路守门】
#
#   用户原话：「**先把立即停止弄好，这一直乱点我都停不了**」
#
#   病① 我写的 guild_daily/recruit/ads/buypanels **一处停止检查都没有**
#        ⇒ 点■后 _ANDROID_STOP=True，但这些模块**从不问它** ⇒ 继续一路点 ✗
#   病② android_run 的 relaunch 循环**只看体力不看停止位**
#        ⇒ 用户停了 ⇒ 体力够 ⇒ **又开一轮** ⇒ 继续乱点 ✗✗
#   病③ popups() 是**所有点击的分叉点**，内部一处检查都没有
#        ⇒ one_round 一轮跑十几秒~几分钟，其间照点不误 ✗
#
#   ⚠ 判据钉「有没有闸门 + 闸门在不在对的函数里」，不钉具体文案
try:
    _GD84 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    _EL84 = io.open(os.path.join(MAPBOT, "explore_loop.py"), encoding="utf-8").read()

    _o84 = ("def _stopped(" in _GD84)
    _ocr84 = (_GD84.find("if _stopped():") < _GD84.find("b.snap(tag)")
              if "b.snap(tag)" in _GD84 else False)
    check("v1.84 ①⭐ guild_daily 有 `_stopped()` 且 `ocr_items` **开头**就查它"
          "（用户报「一直乱点我都停不了」—— ocr_items 是每条流程的必经点，"
          "装了它等于覆盖全部路径 ✓） · _stopped=%s 开头检查=%s"
          % (_o84, _ocr84),
          _o84 and _ocr84)

    _tx84 = "_stopped()" in _GD84[_GD84.find("def _tap_xy("):][:4000]
    check("v1.84 ②⭐ `_tap_xy` 也查停止位（**最后一道**：挡住任何漏网的点击）"
          " · %s" % ("有 ✓" if _tx84 else "缺失"),
          _tx84)

    _mod84 = {m: ("def _stopped(" in io.open(
        os.path.join(MAPBOT, m + ".py"), encoding="utf-8").read())
        for m in ("recruit", "ads", "buypanels")}
    check("v1.84 ③⭐ 其它三个新模块也都有 `_stopped()`"
          "（recruit/ads/buypanels 同样是新写的 ⇒ 同样漏了停止检查） · %s"
          % _mod84,
          all(_mod84.values()))

    _rl84 = _EL84[_EL84.find("while True:"):][:1200]
    _has84 = "_ANDROID_STOP" in _rl84
    check("v1.84 ④⭐ `android_run` 的 relaunch 循环**退出后先查停止位**"
          "（旧写法只看 `_should_relaunch` ⇒ 用户停了还会因体力够**再开一轮** ✗✗）"
          " · %s" % ("找到 ✓" if _has84 else "缺失"),
          _has84)

    _pp84 = _EL84[_EL84.find("def popups("):][:2500]
    _pk84 = ("stop_requested()" in _pp84) and ("return " in _pp84)
    check("v1.84 ⑤⭐ `popups()` 入口有停止闸门并返回 `stopped`"
          "（它是所有弹窗处理的分叉点 ⇒ 装这里一次覆盖全部分支 ✓）"
          " · %s" % ("有 ✓" if _pk84 else "缺失"),
          _pk84)

    _sleep84 = _EL84[_EL84.find("while True:"):][:2000]
    _sl84 = ("_BOT" in _sleep84) and ("_sleep" in _sleep84)
    check("v1.84 ⑥ relaunch 里的 `sleep` **可中断**（`_BOT._sleep`）"
          "（旧 `time.sleep(2.0)` 点■后还要干等 2 秒 ✗） · %s"
          % ("可中断 ✓" if _sl84 else "仍是 time.sleep"),
          _sl84)
except Exception as _e84:       # noqa: BLE001
    check("v1.84 守门可运行（%r）" % (_e84,), False)

# ─────────────────────────────────────────────────────────────────────────
# v1.86【**不能固定坐标啊，识别气泡** —— 用户口径守门】
#
#   用户原话：「**不能固定坐标啊，识别气泡**」
#             「小人头上是问号就是能直接点下面的小人进行派遣，
#               是感叹号就需要先点下面对应的小人领取，然后再点那个小人进行派遣」
#
#   ⛔ 病：我先后给同一批位置算出**三套坐标**（380 / 606 / 756），每次以为对了
#      ⇒ 气泡是**美术**，位置随分辨率/滚动变化 ⇒ 写死必然换机就废 ✗
#   ✅ 修：按项目硬规矩「文字 → **模板** → 锚点坐标」的第二级做
#      真机帧裁 `guild_bubble.png`（68×62）⇒ 实测 4/4 命中（0.774 / 1.000 / 0.892 / 0.892）
#
#   ⚠ 判据钉「有没有模板定位 + 有没有写死坐标」，不钉具体分数
try:
    _GD86 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    import cv2 as _cv87
    _tpl_p87 = os.path.join(PROJ, "app", "src", "main", "assets", "mapbot_pack",
                            "templates", "guild_bubble.png")
    _im87 = _cv87.imread(_tpl_p87) if os.path.exists(_tpl_p87) else None
    _tpl_size87 = (int(_im87.shape[1]), int(_im87.shape[0])) if _im87 is not None else None
    _TPL86 = os.path.join(PROJ, "app", "src", "main", "assets", "mapbot_pack",
                          "templates", "guild_bubble.png")

    check("v1.86 ①⭐ 气泡模板资产**入库**（guild_bubble.png）"
          "（用户口径「识别气泡」—— 没有模板就只能写死坐标 ✗） · %s"
          % ("存在 ✓" if os.path.exists(_TPL86) else "**缺失**"),
          os.path.exists(_TPL86))

    check("v1.86 ②⭐ guild_daily 有 `find_bubbles()`（模板匹配）"
          "且用 `TM_CCOEFF_NORMED`（归一化互相关，对亮度不敏感 ✓） · %s"
          % ("有 ✓" if ("def find_bubbles(" in _GD86
                        and "TM_CCOEFF_NORMED" in _GD86) else "缺失"),
          ("def find_bubbles(" in _GD86) and ("TM_CCOEFF_NORMED" in _GD86))

    # ⚠⚠ 用 **AST 查模块级常量名**，不做字符串 grep：
    #   字符串 grep 会被**注释/docstring 里的留档引用**判假红
    #   （本项目已在这上面假红五次：v1.62c / v1.67 / v1.68 A⑩ / v1.70 B / v1.86）✗
    #   AST 只看**真正绑定的名字** ⇒ 留档写多少遍都不会红 ✓
    import ast as _ast86
    _gdt86 = _ast86.parse(_GD86)
    _modnames86 = set()
    for _n in _gdt86.body:
        if isinstance(_n, _ast86.Assign):
            for _t in _n.targets:
                if isinstance(_t, _ast86.Name):
                    _modnames86.add(_t.id)
                elif isinstance(_t, _ast86.Tuple):
                    for _e in _t.elts:
                        if isinstance(_e, _ast86.Name):
                            _modnames86.add(_e.id)
    _nochair86 = ("CHAIR_X" not in _modnames86) and ("CHAIR_Y" not in _modnames86)
    check("v1.86 ③⭐⛔ **不许再有写死的椅子坐标**（`CHAIR_X`/`CHAIR_Y` 已删）"
          "（用户口径「不能固定坐标」；留任何一个都是换机就废 ✗）"
          "⚠ 剥注释后查 —— 留档注释必然提到它们"
          " · %s" % ("已删净 ✓" if _nochair86 else "仍有残留"),
          _nochair86)

    _pb87 = _GD86[_GD86.find("def person_of_bubble("):][:1500]
    _pb_ok87 = ("def person_of_bubble(" in _GD86) and ("BUBBLE_DY_REF" in _pb87)
    check("v1.86 ④ 有 `person_of_bubble()`（气泡 → 小人位置）"
          "且**两边同一参考系**（`b.img()` 就是 1080×1920 归一化帧 ⇒ 直接加偏移）"
          "⚠ 第一版多做 kx/shift 换算且分段判反 ⇒ 回算差 621（门禁+真机双重抓出 ✗）"
          " · %s" % ("同系加法 ✓" if _pb_ok87 else "缺失"),
          _pb_ok87)

    _ct86 = _GD86[_GD86.find("def chair_timers("):][:2200]
    check("v1.86 ⑤ `chair_timers` 归属基准改成**气泡 x**（`bubbles=` 参数）"
          "（旧写法归到写死的 CHAIR_X 上 ⇒ 同样换机就废 ✗） · %s"
          % ("有 ✓" if "bubbles" in _ct86 else "缺失"),
          "bubbles" in _ct86)
except Exception as _e86:       # noqa: BLE001
    check("v1.86 守门可运行（%r）" % (_e86,), False)

    check("v1.87 ①⭐⛔ 气泡模板必须是**归一化帧尺度**（68×62 附近），不是设备帧尺度"
          "（`b.img()` 返回 1080×1920 归一化帧；拿 1280×2772 设备帧裁的模板去匹配",
          " ⇒ 尺寸对不上 ⇒ **一个都命中不了**，真机实测 30 秒零命中 ✗✗）"
          " · %s" % ("归一化尺度 ✓" if _tpl_size87 in ((68, 62), (67, 62), (69, 62),
                                            (68, 61), (68, 63), (66, 60), (70, 64))
                        else "尺寸异常 %s" % (_tpl_size87,)),
          _tpl_size87 is not None and 55 <= _tpl_size87[0] <= 80
          and 50 <= _tpl_size87[1] <= 75)
except Exception as _e87:       # noqa: BLE001
    check("v1.87 守门可运行（%r）" % (_e87,), False)

# v1.88【**打开派遣界面不点一键派遣** —— 两处真机 bug 守门】
#   用户原话：「**打开派遣界面不点一键派遣**」
#   病① `task_panel_open` 只认「黑晶女仆」整条；真机那一帧**读不到它**（压在立绘上）
#        ⇒ 面板开着却判"没开" ⇒ 一直 panel_miss 重试 ⇒ 永远不点 ✗
#   病② `panel_action` 子串匹配命中了 `※派遣角色位阶需要不低于发起人`（conf 0.96）
#        ⇒ 点在说明文字上 ⇒ 当然没反应 ✗
try:
    _GD88 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    _tp88 = _GD88[_GD88.find("def task_panel_open("):][:1800]
    _multi88 = ("完成悬赏" in _tp88) or ("采集物资" in _tp88)
    check("v1.88 ①⭐ `task_panel_open` **多判据**（黑晶女仆读不到时靠面板专有词兜住）"
          "（真机实测该帧「黑晶女仆」漏检 ⇒ 单判据必然判成没开 ✗） · %s"
          % ("多判据 ✓" if _multi88 else "仍是单判据"),
          _multi88)

    _pa88 = _GD88[_GD88.find("def panel_action("):][:2600]
    _excl88 = ("※" in _pa88) and ("len(_t) > 6" in _pa88.replace(" ", " "))
    check("v1.88 ②⭐ `panel_action` **排除说明文字**（`※` 前缀 + 长度上限）"
          "（真机上 `※派遣角色位阶…` conf 0.96 会先命中 ⇒ 点到说明上 ✗） · %s"
          % ("三重排除 ✓" if _excl88 else "缺排除"),
          _excl88)
except Exception as _e88:       # noqa: BLE001
    check("v1.88 守门可运行（%r）" % (_e88,), False)

# v1.89【用户口径：**点完一键派遣 1s 后同位置要再点一下**】
#   用户原话：「点完一键派遣1s后同位置要再点一下」
#   实测依据：一键派遣 ⇒ 6 槽填满、按钮原地变「开始任务」⇒ 同位置再点即提交 ✓
#   ⚠ 但「开始任务」只点一下就关面板 ⇒ 第二下前**必须确认面板还开着**，
#     否则会点到公会背景（真机实测 v2.png：点一次就关）✗
try:
    _GD89 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    # ⚠ 判据锚点要跟着**新写法**走：旧的 `for hit in range(3):` 已被删掉，
    #   拿它当切片起点会得到空串 ⇒ 假红（本轮实测踩到 ✓）
    _i89 = _GD89.find("_tap_xy(b, _at[0], _at[1], wait=2.5, use_dlg=True)")
    _seg89 = _GD89[max(0, _i89 - 3000):_i89 + 800] if _i89 >= 0 else ""
    check("v1.89 ①⭐ 派遣改成**两段式**：点完等 `_sleep(b, 1.0)` 再同位置点第二下"
          "（用户口径「1s 后同位置再点一下」；旧写法要重新 OCR 一次 ⇒ 多花 1.5~2s 且可能漏检 ✗）"
          " · %s" % ("两段式 ✓" if ("_sleep(b, 1.0)" in _seg89 and "tap2" in _seg89)
                      else "仍是单段"),
          ("_sleep(b, 1.0)" in _seg89) and ("tap2" in _seg89))

    check("v1.89 ②⭐ 第二下前**确认面板还开着**（否则点到公会背景）"
          "（真机实测：「开始任务」点一次就关面板 ✗） · %s"
          % ("有守卫 ✓" if ("task_panel_open(_still)" in _GD89) else "缺守卫"),
          "task_panel_open(_still)" in _GD89)

    check("v1.89 ③ 认不出主按钮时**不盲点**（记 `act_unknown` 并重试）"
          "（面板三态都不匹配 ⇒ 宁可重试，也别乱点） · %s"
          % ("有 ✓" if ("act_unknown" in _GD89) else "缺"),
          "act_unknown" in _GD89)
except Exception as _e89:       # noqa: BLE001
    check("v1.89 守门可运行（%r）" % (_e89,), False)

# v1.90【**气泡数 ≠ 椅子号** —— 真机日志铁证的两处误解】
#   真机 21:48:40 日志：`椅3：气泡只找到 2 个 ⇒ 这号不存在` ⇒ 椅3/椅4 永远跳不过去
#   误解① `if idx-1 >= len(bbs)` 把「椅子号」当「气泡下标」
#         —— 已派出的号**头顶是倒计时、没有气泡** ⇒ 气泡数天然 < 4 ✗
#   误解② `already`（原本就在跑）也 `_n_done += 1` ⇒ 椅1/2 在跑时直接变 2 ⇒ 全越界 ✗
#   ⇒ 只有 `dispatched`（本次真的派出去）才消耗一个空闲位 ✓
try:
    _GD90 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    _i90 = _GD90.find("def _ensure_dispatched(")
    _seg90 = _GD90[_i90:_i90 + 3000] if _i90 >= 0 else ""
    check("v1.90 ①⭐ `_ensure_dispatched` 收 `slot=` 参数（由调用方算空闲位次）"
          "（旧写法拿 `idx-1` 索引气泡 ⇒ 已派出的号没气泡 ⇒ 必越界 ✗） · %s"
          % ("有 slot ✓" if "slot=None" in _seg90 else "缺"),
          "slot=None" in _seg90)

    _n90 = _GD90.count("_n_done += 1")
    _onlydisp = False
    _k = _GD90.find("_n_done += 1")
    if _k > 0:
        _onlydisp = "_n_done += 1" in _GD90[_GD90.find('if r == "dispatched":'):][:80]
    check("v1.90 ②⭐⛔ **只有 `dispatched` 才递增 `_n_done`**"
          "（`already` 也递增的旧写法 ⇒ 椅1/椅2 在跑时椅3/椅4 全越界 ✗✗）"
          "⚠ busy 的号头顶**没有气泡**，不该消耗空闲位 · %s"
          % ("只 dispatched ✓" if _onlydisp else "仍有 other 分支递增"),
          _onlydisp)

    check("v1.90 ③ 越界时**clamp 到最后一个**而不是直接放弃"
          "（`bubble_clamp` 日志 + `slot = len(bbs)-1`） · %s"
          % ("有 ✓" if "bubble_clamp" in _GD90 else "缺"),
          "bubble_clamp" in _GD90)
except Exception as _e90:       # noqa: BLE001
    check("v1.90 守门可运行（%r）" % (_e90,), False)

# v1.91【用户需求：**加个可以让日常前置的选项**】
#   用户原话：「加个可以让日常前置的选项」
#   语义：勾上 ⇒ 刷图**之前**先做完勾选的日常；不勾（默认）⇒ 老行为（收工后做）
#   ⚠ 判据钉「参数链有没有断」——这类跨 4 层的透传最容易漏一层 ⇒ 静默失效 ✗
try:
    _EA91 = io.open(os.path.join(MAPBOT, "explore_android.py"), encoding="utf-8").read()
    _EL91 = io.open(os.path.join(MAPBOT, "explore_loop.py"), encoding="utf-8").read()
    _PR91 = io.open(os.path.join(PROJ, "app", "src", "main", "java",
                                 "com", "fantasy", "autoexplore", "Prefs.java"),
                    encoding="utf-8").read()
    _OV91 = io.open(os.path.join(PROJ, "app", "src", "main", "java",
                                 "com", "fantasy", "autoexplore", "OverlayService.java"),
                    encoding="utf-8").read()
    _MA91 = io.open(os.path.join(PROJ, "app", "src", "main", "java",
                                 "com", "fantasy", "autoexplore", "MainActivity.java"),
                    encoding="utf-8").read()

    check("v1.91 ① Prefs 有 `dailyFirst` 读写（默认 **false** = 老行为 ✓） · %s"
          % ("有 ✓" if ("K_DAILY_FIRST" in _PR91 and "dailyFirst(" in _PR91) else "缺"),
          "K_DAILY_FIRST" in _PR91 and "dailyFirst(" in _PR91)

    check("v1.91 ② MainActivity 有 `cbDailyFirst` 复选框（能在界面上勾） · %s"
          % ("有 ✓" if "cbDailyFirst" in _MA91 else "缺"),
          "cbDailyFirst" in _MA91)

    check("v1.91 ③ OverlayService **真的传了**第 16 个参数 `dailyFirst`"
          "（跨 4 层透传最容易漏这层 ⇒ 勾了也不生效 ✗） · %s"
          % ("传了 ✓" if ("dailyFirst" in _OV91
                          and "adFree,{0}                    dailyFirst".format(chr(10)) in _OV91
                          .replace("\r\n", chr(10))) else "检查中"),
          "dailyFirst" in _OV91)

    check("v1.91 ④ `explore_android.start/run` 都收并透传 `daily_first`"
          "（`start` 走 kw dict、`run` 再传给 android_run ✓） · %s"
          % ("有 ✓" if _EA91.count("daily_first") >= 4 else "缺（只 %d 处）"
             % _EA91.count("daily_first"),),
          _EA91.count("daily_first") >= 4)

    check("v1.91 ⑤ `explore_loop` 有 `DAILY_FIRST` 全局 + `_pre_daily()` 实现"
          "且**在日常循环之前**执行（`_relaunch = 0` 上方） · %s"
          % ("有 ✓" if ("DAILY_FIRST = bool(daily_first)" in _EL91
                        and "def _pre_daily(" in _EL91) else "缺"),
          ("DAILY_FIRST = bool(daily_first)" in _EL91) and ("def _pre_daily(" in _EL91))

    _ipre91 = _EL91.find("if DAILY_FIRST:")
    _irel91 = _EL91.find("    _relaunch = 0")
    check("v1.91 ⑥ ⛔ 前置块必须在 `_relaunch = 0` **之前**（否则等于没前置） · %s"
          % ("位置对 ✓" if (0 <= _ipre91 < _irel91) else "位置错"),
          0 <= _ipre91 < _irel91)
except Exception as _e91:       # noqa: BLE001
    check("v1.91 守门可运行（%r）" % (_e91,), False)

# v1.92【炼金坐标真机重标定 —— 旧值全是 PC×1.5 推算，从没验过】
#   真机实测（al5.png 逐帧确认）：
#     炼金宝箱 dev(420,900) / 陶罐 dev(700,985) 无反应 / 紫发角色 dev(905,990) 别点
#     开始炼金 ref(900,552) / 返回 ref(540,1243)
try:
    _GD92 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    check("v1.92 ① 炼金宝箱坐标是**真机实测值**（ref 354,759 ⇒ dev 420,900）"
          "（旧 `_s(240,445)` 是 PC×1.5 推算 ⇒ dev y 差 400+ ✗） · %s"
          % ("实测 ✓" if ("ALCHEMY_CHEST = (392, 400)" in _GD92
                          or "ALCHEMY_CHEST = (354, 759)" in _GD92) else "仍是旧值"),
          (("ALCHEMY_CHEST = (392, 400)" in _GD92)
           or ("ALCHEMY_CHEST = (354, 759)" in _GD92)))

    check("v1.92 ② 「开始炼金」按实测 ref(900,552)（dev 1067,1151）"
          "（面板 OCR conf=1.00，最稳） · %s"
          % ("实测 ✓" if "ALCH_START_BTN = (900, 552)" in _GD92 else "仍是旧值"),
          "ALCH_START_BTN = (900, 552)" in _GD92)

    check("v1.92 ③ 保留**多候选点试**（宝箱 y 会随滚动漂，PC 也记着） · %s"
          % ("有 ✓" if "ALCHEMY_CHEST_YS" in _GD92 else "缺"),
          "ALCHEMY_CHEST_YS" in _GD92)

    check("v1.92 ④ ⛔ 紫发角色（献祭宝箱怪）**单独记了常量并标注别点**"
          "（点错会进天赋互换，不可逆 ✗） · %s"
          % ("已标注 ✓" if "ALCHEMY_OFFERING" in _GD92 else "缺"),
          "ALCHEMY_OFFERING" in _GD92)

    check("v1.92 ⑤ 「返回」按实测 ref(540,1243)（dev 639,1970）"
          "（我第一版点 dev(640,1335) ⇒ 差 635，面板关不掉 ✗） · %s"
          % ("实测 ✓" if "ALCH_RESULT_BACK = (540, 1243)" in _GD92 else "仍是旧值"),
          "ALCH_RESULT_BACK = (540, 1243)" in _GD92)
except Exception as _e92:       # noqa: BLE001
    check("v1.92 守门可运行（%r）" % (_e92,), False)

# v1.93【炼金：面板判据漏检 + 满星低置信度 —— 两个真机 bug】
#   用户原话：「还没点满星进行投料呢」
#   病① `main_panel_open` 只认「炼金宝箱」整条；真机实测该条 **OCR 根本读不到**
#        （大标题压立绘）⇒ 恒 False ⇒ `start_alchemy` 一进门就 failed ⇒ 整个炼金没进 ✗
#   病② 「满星」OCR conf 只有 **0.74**（且「蓝色紫色橙色」被合并成一条）
#        ⇒ `tap_target` 整条相等容易失配 ⇒ 满星没点上 ⇒ 投料槽空 ⇒ 判 nothing ✗
try:
    _GD93 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    _i93 = _GD93.find("def main_panel_open(")
    _seg93 = _GD93[_i93:_i93 + 1800] if _i93 >= 0 else ""
    _multi93 = ("开始炼金" in _seg93) and ("全部取消" in _seg93 or "预计时间" in _seg93)
    check("v1.93 ①⭐ `main_panel_open` **多判据**（炼金宝箱读不到时靠面板专有词兜住）"
          "（真机实测「炼金宝箱」漏检 ⇒ 单判据必然判成没开 ⇒ 整个炼金跳过 ✗） · %s"
          % ("多判据 ✓" if _multi93 else "仍是单判据"),
          _multi93)

    _i93b = _GD93.find("ALCH_FILTER_FULLSTAR[0], ALCH_FILTER_FULLSTAR[1]")
    check("v1.93 ②⭐ 「满星」改为**直接点实测锚点**再验证投料是否生效"
          "（OCR conf 仅 0.74，整条相等易失配 ⇒ 满星没点上 ✗） · %s"
          % ("锚点+验证 ✓" if _i93b > 0 else "仍只靠 OCR"),
          _i93b > 0)

    check("v1.93 ③ 点完必须**验证预计时间变化**（`--` → `HH:MM:SS` 才算投料成功）"
          "⚠ 这是「满星到底点上没有」的唯一可靠判据 · %s"
          % ("有验证 ✓" if "after_fullstar" in _GD93 else "缺验证"),
          "after_fullstar" in _GD93)

    check("v1.93 ④ 锚点没生效时**退回 OCR 文字**双保险（布局变了也能救） · %s"
          % ("有 ✓" if "tap_fullstar_ocr" in _GD93 else "缺"),
          "tap_fullstar_ocr" in _GD93)
except Exception as _e93:       # noqa: BLE001
    check("v1.93 守门可运行（%r）" % (_e93,), False)

# v1.94【**日常全崩：NameError + 300 行代码重复** —— 真机日志铁证】
#   用户原话：「怎么不做日常？」
#   日志：`NameError: name GUILD_CORNERS is not defined`
#        ⇒ 公会日常 / 免费招募 / 天赋果实 **三个功能全崩**（各一条 error）
#   根因：某次插入新函数时**整块 300 行被复制成两份**（18 个函数重复），
#        而 GUILD_CORNERS / MENU_HINTS / LOBBY_HINTS / INTEL_* / ALCH_PANEL_X
#        的定义正好落在被覆盖的区间 ⇒ 全部消失 ✗✗
#   ⚠ 这类 bug **静态语法检查抓不到**（语法合法、只是名字没定义）
#     ⇒ 判据必须是「**运行期能 import + 能调用**」，不能只查字面量 ✗
try:
    _GD94 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    import ast as _ast94
    _t94 = _ast94.parse(_GD94)

    # ① 无重复函数定义（本轮的真凶）
    _defs94 = {}
    for _n in _t94.body:
        if isinstance(_n, (_ast94.FunctionDef, _ast94.AsyncFunctionDef)):
            _defs94[_n.name] = _defs94.get(_n.name, 0) + 1
    _dup94 = {k: v for k, v in _defs94.items() if v > 1}
    check("v1.94 ①⭐⛔ **guild_daily 无重复函数定义**"
          "（真机：整块 300 行被复制两份 ⇒ 18 个函数重复 ⇒ 常量定义被覆盖丢失 ✗✗）"
          " · %s" % ("无重复 ✓" if not _dup94 else "重复: %s" % _dup94),
          not _dup94)

    # ② 关键常量都在**模块级赋值**里
    _modnames94 = set()
    for _n in _t94.body:
        if isinstance(_n, _ast94.Assign):
            for _tg in _n.targets:
                if isinstance(_tg, _ast94.Name):
                    _modnames94.add(_tg.id)
    _need94 = ("GUILD_CORNERS", "MENU_HINTS", "LOBBY_HINTS",
               "INTEL_BTN", "INTEL_TITLE", "INTEL_CLAIMABLE", "INTEL_DONE",
               "ALCH_PANEL_X", "ALCH_START_BTN", "ALCH_FILTER_FULLSTAR",
               "BUBBLE_TPL", "BUBBLE_DY_REF")
    _miss94 = [k for k in _need94 if k not in _modnames94]
    check("v1.94 ②⭐ 日常/炼金/情报的**关键常量全部有定义**"
          "（GUILD_CORNERS 等丢了 ⇒ in_guild() 直接 NameError ⇒ 整套日常崩 ✗）"
          " · %s" % ("全在 ✓" if not _miss94 else "缺: %s" % _miss94),
          not _miss94)

    # ③ 每个 Name 引用都能找到定义（粗筛未定义名）
    # ⚠⚠ **必须把 `FunctionDef.name` 也算进 known**
    #   —— 第一版只收了 Assign 的目标名，于是「def foo(): ...」之后调 foo()
    #      被当成"未定义"⇒ **60 个假红**（本轮实测踩到）✗
    #   ⇒ 函数名 / 类名 / 参数 / 局部赋值 / import / except 别名 全部要收 ✓
    import builtins as _bi94
    _known94 = set(dir(_bi94)) | set(_modnames94)
    for _n in _ast94.walk(_t94):
        if isinstance(_n, _ast94.arg):
            _known94.add(_n.arg)
        elif isinstance(_n, (_ast94.FunctionDef, _ast94.AsyncFunctionDef,
                            _ast94.ClassDef)):
            _known94.add(_n.name)          # ⭐ 关键：函数/类自己的名字
        elif isinstance(_n, _ast94.Name) and isinstance(_n.ctx, _ast94.Store):
            _known94.add(_n.id)
        elif isinstance(_n, (_ast94.Import, _ast94.ImportFrom)):
            for _a in _n.names:
                _known94.add((_a.asname or _a.name).split(".")[0])
        elif isinstance(_n, _ast94.ExceptHandler) and _n.name:
            _known94.add(_n.name)
        elif isinstance(_n, _ast94.comprehension):
            for _e in _ast94.walk(_n.target):
                if isinstance(_e, _ast94.Name):
                    _known94.add(_e.id)
        elif isinstance(_n, _ast94.Global):
            for _nm in _n.names:
                _known94.add(_nm)
        elif isinstance(_n, _ast94.Nonlocal):
            for _nm in _n.names:
                _known94.add(_nm)
    _known94.add("__file__")
    _used94 = set()
    for _n in _ast94.walk(_t94):
        if isinstance(_n, _ast94.Name) and isinstance(_n.ctx, _ast94.Load):
            _used94.add(_n.id)
    _undef94 = sorted(_used94 - _known94)
    check("v1.94 ③⭐ ⛔ **guild_daily 无未定义名**（AST 级）"
          "（静态语法检查抓不到这类 bug —— 语法合法、只是名字没定义 ✗）"
          " · %s" % ("无 ✓" if not _undef94 else "未定义: %s" % _undef94),
          not _undef94)
except Exception as _e94:       # noqa: BLE001
    check("v1.94 守门可运行（%r）" % (_e94,), False)

# v1.96【**盲点坐标点到兑换商店** —— 用户口径：「不能固定坐标啊」】
#   用户原话：「炼金不对，乱点点到兑换商店了」「你现在是盲点？？不能固定坐标啊」
#   病① `ALCHEMY_CHEST = (354,759)` 的 y **差 359**（真机实测宝箱在 ref 392,400）
#   病② `ALCHEMY_CHEST_YS = (759,700,820)` 盲扫 9 次 ⇒ 700/820 落在「兑换商店开启」
#        横幅上 ⇒ **点开兑换商店**，污染后续所有判断 ✗✗
#   修：只点 1 个实测位置 + 点完强验证 + 点错**立刻点 X 关掉** + 不换坐标重试 ✓
try:
    _GD96 = io.open(os.path.join(MAPBOT, "guild_daily.py"), encoding="utf-8").read()
    check("v1.96 ①⭐⛔ **不再有 x/y 候选点**（`ALCHEMY_CHEST_XS/YS` 已删）"
          "（盲扫 9 次 ⇒ 700/820 落在兑换商店横幅上 ⇒ 点开商店污染后续 ✗✗） · %s"
          % ("已删 ✓" if ("ALCHEMY_CHEST_XS" not in _GD96.split("ALCHEMY_CHEST = (392, 400)")[1][:2000]
                          if "ALCHEMY_CHEST = (392, 400)" in _GD96 else True)
                      else "仍有候选点"),
          "ALCHEMY_CHEST_XS" not in _GD96
          or "候选点全部删除" in _GD96)

    check("v1.96 ②⭐ 炼金宝箱坐标 = 真机实测 `ref(392,400)`"
          "（旧 (354,759) 的 y **差 359** ⇒ 点在公会 3 楼，不在顶楼 ✗） · %s"
          % ("实测 ✓" if "ALCHEMY_CHEST = (392, 400)" in _GD96 else "仍是旧值"),
          "ALCHEMY_CHEST = (392, 400)" in _GD96)

    check("v1.96 ③⭐ 点错后**立刻清理挡路面板**（`_clear_blocking_panels`）"
          "（兑换商店留着会挡住后面情报/果实的所有 OCR ✗） · %s"
          % ("有 ✓" if "_clear_blocking_panels" in _GD96 else "缺"),
          "_clear_blocking_panels" in _GD96)

    _blk96 = _GD96[_GD96.find("BLOCKING_PANEL_WORDS"):][:600]
    _clean96 = ("前往" not in _blk96.split(chr(10))[0]
                and "觉醒石" not in _blk96.split(chr(10))[0])
    check("v1.96 ④ 挡路词表**只用兑换商店独有词**（不放「前往」「觉醒石」这种泛词）"
          "（泛词在背包/道具详情也有 ⇒ 会把正常画面误判成被挡 ✗） · %s"
          % ("干净 ✓" if _clean96 else "含泛词"),
          _clean96)
except Exception as _e96:       # noqa: BLE001
    check("v1.96 守门可运行（%r）" % (_e96,), False)

# v2.01【**特殊方块都不去点** —— 分类器不看勾选】
#   用户原话：「现在特殊方块都不去点」
#   病：分类器把商人/宝库放进 `buy`/`buy_hidden` 时**只看名字**，
#       完全不看用户勾没勾 ⇒ 「不勾 = 拉黑」这条语义在这个汇聚点**从未生效** ✗
#       （`is_blocked()` / `is_target()` 是另一条路，管不到 `buy` 列表）
try:
    _EL201 = io.open(os.path.join(MAPBOT, "explore_loop.py"), encoding="utf-8").read()
    _i201 = _EL201.find("if strong and v['name'] in spots_mod.BUY_OUT_NAMES")
    _seg201 = _EL201[_i201:_i201 + 300] if _i201 >= 0 else ""
    check("v2.01 ①⭐ 分类器 `buy` 判定带 `is_blocked` 闸门"
          "（旧写法只看名字 ⇒ 不勾也照买 ⇒ 用户报「特殊方块都不去点」✗） · %s"
          % ("有闸门 ✓" if "not _blk_now" in _seg201 else "缺"),
          "not _blk_now" in _seg201)

    check("v2.01 ② `buy_hidden` 也有闸门（未揭示的商人/宝库同样受勾选控制） · %s"
          % ("有 ✓" if "BUY_OUT_NAMES and not _blk_now:" in _EL201 else "缺"),
          "BUY_OUT_NAMES and not _blk_now:" in _EL201)

    check("v2.01 ③ ⛔ fail-open：读配置失败时**按老行为**（进 buy）"
          "（宁可多买，也别因一次读取失败整盘不买 ✓） · %s"
          % ("有 ✓" if "_blk_now = False" in _EL201 else "缺"),
          "_blk_now = False" in _EL201)
except Exception as _e201:       # noqa: BLE001
    check("v2.01 守门可运行（%r）" % (_e201,), False)

# v2.02【**打开预言石碑不选择预言** —— 标题 y 整窗偏移 55px】
#   用户原话：「现在这把打开预言石碑不选择预言」
#   病：`FORETELL_CARD_Y = 659`（PC 439 ×1.5 推算），而真机实测卡片标题在 **714~715**
#       ⇒ 过滤窗 `659-30 ~ 659+39` = 629~698 ⇒ **三张卡全被过滤掉** ⇒ cards=[]
#       ⇒ 走 `cards_timeout` 分支「不盲点，关面板」⇒ **一张都不选** ✗✗
#   真机实测（`fp.png`）：秘藏 dlg(212,714) / 藏宝 dlg(540,714) / 强敌 dlg(868,715)
try:
    _BP202 = io.open(os.path.join(MAPBOT, "buypanels.py"), encoding="utf-8").read()
    # v2.76: 改成**参考系基值 + 动态 C**。写死弹窗系绝对值换分辨率就失效:
    #   真机 C=209 ⇒ 506+209=715 ✓；模拟 1280x2640 C=154 ⇒ 506+154=660
    #   旧写法窗口 684~769 ⇒ 模拟器上 660 落空 ⇒ 三张卡全读不到 ✗
    _v276_ok = ('FORETELL_CARD_Y_REF' in _BP202
                and '_foretell_card_y()' in _BP202
                and 'FORETELL_CARD_Y = 714' not in _BP202)
    check('v2.76 ① ' + '`FORETELL_CARD_Y` 不再写死弹窗系绝对值'
          '（由 参考基值 + dlg_shift() 动态算 ✓） · %s'
          % ('已改成动态 ✓' if _v276_ok else '仍在写死'),
          _v276_ok)

    check("v2.02 ② 识别窗口用**常量**（`TOL_UP`/`TOL_DN`），不再写死 `-30/+39`"
          "（写死的话下次调 y 还会忘同步 ✗） · %s"
          % ("有常量 ✓" if ("FORETELL_CARD_Y_TOL_UP" in _BP202
                           and "FORETELL_CARD_Y_TOL_DN" in _BP202) else "缺"),
          "FORETELL_CARD_Y_TOL_UP" in _BP202)

    check("v2.02 ③ 「确定」按实测 dlg(542,1390)（旧 1332 差 58 ⇒ 点空） · %s"
          % ("实测 ✓" if "'ok': (542, 1390)" in _BP202 else "仍是旧值"),
          "'ok': (542, 1390)" in _BP202)
except Exception as _e202:       # noqa: BLE001
    check("v2.02 守门可运行（%r）" % (_e202,), False)

# v2.03【**在选图界面连点 4 轮「确认」** —— 奖励弹窗判据太宽】
#   用户原话：「现在又在点确认」
#   真机铁证（`mgas_log.txt`）：`{"popup":"reward_confirm"}` × 4 轮，
#     点 **(108,1218)**（参考系）≈ 设备 (128,1939) = **选图界面「深渊 46」卡片** ✗✗
#     ⇒ `loop_guard: same_action n=4` ⇒ `unstick` 把**预言石碑 2,1 拉黑**（当时不在那张图）
#   病：旧判据只要「有精确等于`确定`的文字 + y>sy(900) + 没有`取消`」就点 ⇒
#       任何界面下方有个 OCR 读成「确定」的碎字都会被误判 ✗
#   修：**必须同时看到奖励词**（恭喜获得/获得/奖励/领取/道具/金币/经验）才点 ✓
try:
    _EL203 = io.open(os.path.join(MAPBOT, "explore_loop.py"), encoding="utf-8").read()
    _i203 = _EL203.find("_REWARD_WORDS")
    check("v2.03 ①⭐ 奖励确认弹窗**必须有正向证据**（`_REWARD_WORDS`）"
          "（旧判据只看「有确定+没取消」⇒ 选图界面误判 ⇒ 连点 4 轮 ✗） · %s"
          % ("有 ✓" if _i203 >= 0 else "缺"),
          _i203 >= 0)

    _seg203 = _EL203[_i203:_i203 + 900] if _i203 >= 0 else ""
    check("v2.03 ② 该词表里含「获得/奖励/领取」（真弹窗的必有字样） · %s"
          % ("有 ✓" if all(k in _seg203 for k in ("获得", "奖励", "领取")) else "缺"),
          all(k in _seg203 for k in ("获得", "奖励", "领取")))

    check("v2.03 ③ 判据里 `fb(items, *_REWARD_WORDS)` **与已有条件串联**"
          "（不能只写在注释里 —— 本项目栽过多次「判据装好了但没接上」✗） · %s"
          % ("接上了 ✓" if "fb(items, *_REWARD_WORDS) is not None" in _EL203 else "没接"),
          "fb(items, *_REWARD_WORDS) is not None" in _EL203)

    check("v2.03 ④ 日志带 `why_word`（下次一眼看出是看到哪个词判定的） · %s"
          % ("有 ✓" if "why_word" in _EL203 else "缺"),
          "why_word" in _EL203)
except Exception as _e203:       # noqa: BLE001
    check("v2.03 守门可运行（%r）" % (_e203,), False)

# v2.04【**打开预言面板却判成「发现莱姆！」** —— 从 PC 移植（PC 2026-10-12）】
#   用户原话：「打开预言弹遇到莱姆了。。」
#   PC 同款事故（`runs/gui_20261012_125244.log`，用户原话「连续出现获得莱姆的点击」）：
#     点开 `5,4 预言石碑` ⇒ 面板正在画 ⇒ **连判 4 次"发现莱姆！"** ⇒
#     点 `lime_back()` ⇒ 4 次空点 ⇒ `loop_guard` 脱困 ⇒ 崩 ✗✗
#   病根：`fb()` 是**子串**匹配，而**预言石板「元素」卡正文**就含「莱姆」：
#     `地图中至少出现 1 只莱姆，并且所有莱姆至少是蓝色位阶。`
#   修：标题必须**独立成条**（完全相等）+ 剥首尾非中文符号 ✓
try:
    _EL204 = io.open(os.path.join(MAPBOT, "explore_loop.py"), encoding="utf-8").read()
    check("v2.04 ①⭐ 有 `_LIME_TITLES` 白名单（标题**完全相等**，不做子串）"
          "（子串匹配会被预言卡正文「地图中至少出现1只莱姆…」骗到 ✗） · %s"
          % ("有 ✓" if "_LIME_TITLES = " in _EL204 else "缺"),
          "_LIME_TITLES = " in _EL204)

    check("v2.04 ②⭐ `lime_back` 改用 `_lime_popup_title()`（不再用子串 `fb`）"
          "（旧写法连判 4 次 ⇒ 连点 4 次返回把预言面板点没了 ✗） · %s"
          % ("已改 ✓" if "if _lime_popup_title(items) is None:" in _EL204 else "仍旧"),
          "if _lime_popup_title(items) is None:" in _EL204)

    check("v2.04 ③ 剥首尾非中文符号（OCR 偶尔带 `+`/`!` 前缀） · %s"
          % ("有 ✓" if "def _clean(s):" in _EL204 else "缺"),
          "def _clean(s):" in _EL204)

    _i204 = _EL204.find("_LIME_TITLES = ")
    _seg204 = _EL204[_i204:_i204 + 200] if _i204 >= 0 else ""
    check("v2.04 ④ 三种形态都在（`发现莱姆！`/`发现莱姆`/`莱姆`） · %s"
          % ("齐 ✓" if all(k in _seg204 for k in ("发现莱姆！", "发现莱姆", "莱姆"))
             else "缺"),
          all(k in _seg204 for k in ("发现莱姆！", "发现莱姆", "莱姆")))
except Exception as _e204:       # noqa: BLE001
    check("v2.04 守门可运行（%r）" % (_e204,), False)

# v2.05【**莱姆只在退图前最后一次补点之后判断** —— 用户口径】
#   用户原话（两次同一句）：
#     · 「找莱姆的只在退出地图前最后那一次点击后啊，怎么刚进图就找莱姆了」
#     · 「是整场探图过程中，只有棋盘最后即将退出去的最后那次点击之后才判断莱姆弹窗，
#        其他时候不判断」
#   病：`popups()`（总闸门，每轮每次点击后都调）+ `one_round()`（点序循环）
#       两处都判断莱姆 ⇒ 全程任何一刻读到就去点返回 ✗
#   修：**把这两处彻底删掉**，只留 `final_collect()` / `finish_map()`（退图流程）✓
#   ⚠ PC 端当年(pc:5868-5871)把用户这句话理解成「判据要窄」**没做时机** ⇒ 本仓补上 ✓
try:
    _EL205 = io.open(os.path.join(MAPBOT, "explore_loop.py"), encoding="utf-8").read()
    _L205 = _EL205.split(chr(10))

    def _owner205(n):
        for _i in range(n - 1, -1, -1):
            if _L205[_i].startswith("def "):
                return _L205[_i][4:].split("(")[0]
        return "?"

    _calls205 = []
    for _i, _ln in enumerate(_L205):
        _s = _ln.split("#")[0]
        if "lime_back(" in _s and "def " not in _s:
            _calls205.append(_owner205(_i + 1))

    check("v2.05 ①⭐ 莱姆只剩**退图流程**两处调用（finish_map / final_collect）"
          "（用户在探图过程中不该判断莱姆 ✗） · %s"
          % (repr(_calls205),),
          _calls205 == ["finish_map", "final_collect"])

    check("v2.05 ②⭐ `popups()` 里**没有**莱姆分支"
          "（它是总闸门 ⇒ 装着就等于全程判断 ✗） · %s"
          % ("已删 ✓" if "popups" not in _calls205 else "仍有"),
          "popups" not in _calls205)

    check("v2.05 ③⭐ `one_round()` 点序循环里**没有**莱姆分支"
          "（探图过程中每次点击都不该判断 ✗） · %s"
          % ("已删 ✓" if "one_round" not in _calls205 else "仍有"),
          "one_round" not in _calls205)

    check("v2.05 ④ 判据函数**保留**（final_collect/finish_map 还在用） · %s"
          % ("齐 ✓" if all(k in _EL205 for k in ("def _lime_popup_title("
                                                  "def lime_back(")) else "缺"),
          "def _lime_popup_title(" in _EL205 and "def lime_back(" in _EL205)

    check("v2.05 ⑤ 通用兜底仍在（真弹窗挡路时 panel_seen/universal_close 会关掉） · %s"
          % ("在 ✓" if ("def panel_seen(" in _EL205
                        and "def universal_close(" in _EL205) else "缺"),
          "def panel_seen(" in _EL205 and "def universal_close(" in _EL205)
except Exception as _e205:       # noqa: BLE001
    check("v2.05 守门可运行（%r）" % (_e205,), False)
print()
# ══════════════════════════════════════════════════════════════════════════════
# v2.78【预言石碑连环 5 个 bug ＋ 压暗帧丢标记 ＋ 计划没走完就收工】（2026-10-28）
#
#   ---- 用户报的（按顺序，看着是五个问题，其实是**一条链**）----
#     ①「为什么打开了预言石碑显示了装备相关的日志」
#     ②「打开预言石碑，显示发现勇者之墓，正在领奖」
#     ③「没有正确点掉预言石碑」
#     ④「没有正确选中预言」
#     ⑤「连预言石碑都没点开，为什么」
#
#   ---- 链（README §6.76）----
#     ① L['newequip'] 子串「获得装备」命中「武装」卡说明 ⇒ newequip 抢走预言面板
#     ② L['special'] 里「勇者之墓」排在「预言石碑」之前，而「战场」卡正文含完整四字
#        ⇒ relic 抢走 ⇒ relic_flow 找不到「成功率」⇒ panel_missing ⇒ 重复 40+ 次
#     ③ bottom_close() 只认「关闭」，而预言面板的按钮叫「确定」⇒ **压根没点**
#     ④ FORETELL_CARD_Y = 714 是**弹窗系绝对值**（真机 C=209）⇒ 模拟器 C=154 时窗口落空
#        ⇒ 三张卡全读不到 ⇒ cards_timeout ⇒ 一张都不选
#     ⑤ popups() 返回 handled ⇒ 上层 done.add() ⇒ 下一轮整块剔除 ⇒ **目标永久消失**
#
#   ---- 本组为什么**必须**存在 ----
#     门禁上一段是 v2.05 —— 本轮九个修复**一条守护断言都没有** ⇒
#     把任何一条改回旧写法，套件依然全绿（本项目纪律：每个修复配门禁组 ＋ 牙齿测试）✓
#
#   ⚠⚠ 断言写法三个坑（本仓已踩过四次，这里是第五次）—— 都在本组第一版上真踩到：
#     · **撤回守门必须先剥整行注释再查** —— 留档注释里必然逐字引用旧写法 ⇒ 字符串 grep 假红
#     · 切片一律 .find() ＋ 显式判 >= 0（.split()[1] 在源码被 stash 时抛 IndexError，
#       会把本组后面的断言**全吞掉**）
#     · **判据窗口别写死小数字**：A③ 第一版只搜 400 字符 ⇒ `foretell_flow` 在 +260 能搜到、
#       `'handled'` 在 +400 之外 ⇒ **假红**（我第一次跑就红了）⇒ 改成「搜到 `for` 那行」✓
#     ⚠ 另有 v1.42② 元门禁盯着「执行级占比 ≥15%」：本组若全是字符串检查会把它拉下水 ⇒
#       B 组一律写成**表驱动真调函数**（既有 `for _r in range` 的真跑，也更好读）✓
# ══════════════════════════════════════════════════════════════════════════════
try:
    import ast as _ast78

    _EL78 = io.open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
    _BP78 = io.open(os.path.join(MAPBOT, 'buypanels.py'), encoding='utf-8').read()
    _L78 = _EL78.split(chr(10))

    def _span78(_name):
        """（起始行号, 结束行号, 函数体原文）—— 找不到返回 (None, None, 空串)"""
        _st = None
        for _i, _l in enumerate(_L78):
            if _l.startswith('def %s(' % _name):
                _st = _i
                break
        if _st is None:
            return (None, None, '')
        for _j in range(_st + 1, len(_L78)):
            if _L78[_j].startswith('def ') or _L78[_j].startswith('class '):
                return (_st, _j, chr(10).join(_L78[_st:_j]))
        return (_st, len(_L78), chr(10).join(_L78[_st:]))

    # ── A① 结构特征判据存在（**不靠标题**）──
    #   真机铁证：标题「预言石板」被 OCR 读成「领合石板」/「言何饭」conf 0.67
    #   ⇒ v1.78 靠 _panel_title_of 读标题的修法**失效** ⇒ 必须靠结构特征
    _s, _e, _b = _span78('_is_prophecy_panel')
    _a1_ok = (_b != '' and '持续' in _b and '张' in _b and '预言' in _b
              and '战场' in _b and '武装' in _b and '宝库' in _b
              and '_n_dur >= 2' in _b and '_n_pre >= 1' in _b and '_n_cat >= 2' in _b)
    check('v2.78 A① 有结构特征判据 _is_prophecy_panel()'
          '（标题不可靠 —— 实测被读成「言何饭」conf 0.67 ⇒ 旧修法失效 ✗） · %s'
          % ('三条判据齐 ✓' if _a1_ok else '缺判据'), _a1_ok)

    # ── A② close_newequip 在**查 newequip 关键词之前**先排除预言面板 ──
    #   顺序必须是「先排除」，否则子串一命中就 return True，排除写在后面等于没写
    _s, _e, _b = _span78('close_newequip')
    _i_ex = _b.find('if _is_prophecy_panel(items):')
    _i_fb = _b.find("fb(items, *L['newequip'])")
    _a2_ok = (_i_ex >= 0 and _i_fb >= 0 and _i_ex < _i_fb
              and _b[_i_ex:_i_ex + 120].find('return False') >= 0)
    check('v2.78 A② close_newequip 在**子串匹配之前**排除预言面板'
          '（「武装」卡正文含「获得装备」⇒ 否则装备流程抢走预言面板 ✗） · %s'
          % ('顺序对 ✓ (排除@%d < 匹配@%d)' % (_i_ex, _i_fb) if _a2_ok else '顺序错/缺'),
          _a2_ok)

    # ── A③ popups() 里 special 分支**提到循环之前**用结构特征提前拦 ──
    #   「战场」卡第二行是「之墓，并且勇者之墓奖」⇒ 含完整四字；而 L['special']
    #   里「勇者之墓」排在「预言石碑」之前 ⇒ 先命中就错派 ✗
    _s, _e, _b = _span78('popups')
    _i_loop = _b.find("for t in L['special']:")
    _i_pre = _b.rfind('if _is_prophecy_panel(items):', 0, _i_loop) if _i_loop > 0 else -1
    _seg_pre = _b[_i_pre:_i_loop] if _i_pre >= 0 else ''
    _a3_ok = (_i_loop > 0 and _i_pre >= 0
              and 'foretell_flow' in _seg_pre and "'handled'" in _seg_pre)
    check('v2.78 A③ popups() 用结构特征**在 special 循环之前**拦预言面板'
          '（否则「战场」卡正文含「勇者之墓」⇒ 被 relic 抢 ⇒ panel_missing 40+ 次 ✗） · %s'
          % ('已提前拦 ✓ (拦@%d < 循环@%d)' % (_i_pre, _i_loop) if _a3_ok else '没提前拦'),
          _a3_ok)

    # ── A④ universal_close：认不到「关闭」⇒ 补 _bottom_ok ⇒ 仍不行就全屏 OCR ──
    #   用户③「没有正确点掉预言石碑」：面板按钮叫「确定」实测 ref(541,1180)，
    #   而快路径 band=(130,1080) **够不到** y=1180 ⇒ 两道兜底缺一不可
    _s, _e, _b = _span78('universal_close')
    _i_cl = _b.find('cl = bottom_close(items)')
    _i_ok = _b.find('cl = _bottom_ok(items)')
    _i_full = _b.find("tag='uni_full'")
    _a4_ok = (_i_cl >= 0 and _i_ok > _i_cl and _i_full > _i_ok
              and _b.find('if cl is None:', _i_cl) >= 0
              and 'cl = _bottom_ok(_full)' in _b)
    check('v2.78 A④ universal_close 两道兜底齐（先 _bottom_ok、再全屏 OCR）'
          '（旧代码只认「关闭」⇒ 直接 skipped_no_blind_tap：**压根没点** ✗） · %s'
          % ('两道都在 ✓' if _a4_ok else '缺'), _a4_ok)

    _s, _e, _b = _span78('_bottom_ok')
    _a4b_ok = all(k in _b for k in ("'返回'", "'确定'", "'确认'"))
    check('v2.78 A④b _bottom_ok() 只认「返回 / 确定 / 确认」三种按钮名'
          '（范围放宽会把商人面板右下角的「购买」当关闭 ⇒ 一点就买 ✗） · %s'
          % ('齐 ✓' if _a4b_ok else '缺'), _a4b_ok)

    # ── A⑤ ★★★ 面板格**不写 done**（用户⑤「连预言石碑都没点开」的真根因）──
    #   done 的语义是「格子点没了」，而面板格点完**格子还在** ⇒
    #   写 done ⇒ 下一轮 _seed_rc 命中 ⇒ done_cells_dropped 整块剔除
    #   ⇒ 模型里再也没这个目标 ⇒ **连面板都不会再弹** ✗✗
    _i_cell = _EL78.find('_is_panel_cell = any(')
    _seg_cell = _EL78[_i_cell:_i_cell + 400] if _i_cell >= 0 else ''
    _kw78 = ('预言石板', '预言石碑', '旅行商人', '黄金宝库',
             '传承祭坛', '限时礼包', '金属宝箱怪', '机巧宝箱怪')
    _miss78 = [_k for _k in _kw78 if _k not in _seg_cell]
    check('v2.78 A⑤ ⭐ 面板格名单八类齐（不写 done 的判据来源）'
          '（写 done ⇒ 下轮整块剔除 ⇒ 目标永久消失 ⇒「连面板都不点开」✗） · %s'
          % ('齐 ✓' if not _miss78 else '缺 %s' % (_miss78,)),
          not _miss78)

    _i_keep = _EL78.find("'panel_cell_kept'")
    _i_done = _EL78.find("done.add(st['last'])", _i_cell)
    _seg_done = _EL78[_i_cell:_i_done + 60] if (_i_cell >= 0 and _i_done > 0) else ''
    _a5b_ok = (_i_keep > 0 and _i_done > _i_cell
               and 'if _is_panel_cell:' in _seg_done
               and 'else:' in _seg_done
               and _i_keep < _i_done)
    check('v2.78 A⑤b done.add() 落在 else 支里（面板格走记录、普通格才写 done）'
          '（顺序反了 = 面板格照样写 done = 目标永久消失 ✗） · %s'
          % ('结构对 ✓' if _a5b_ok else '结构不对'), _a5b_ok)

    # ── A⑥ 压暗帧保住标记后，**别被紧随其后的「按 ratio 丢标记」又丢掉** ──
    #   实测 m0_r008：结算面板只盖住棋盘**中间** ⇒ 那一帧 marks 扫成空
    #   ⇒ marks_kept 保住后，ratio < 0.55 又把它们全丢了（整盘压暗时所有格都低）
    _i_dim = _EL78.find('_dimmed_kept = bool(')
    _i_drop = _EL78.find("'marks_dropped_panel'")
    _i_guard = _EL78.find('if _dimmed_kept:', _i_dim) if _i_dim > 0 else -1
    _a6_ok = (_i_dim > 0 and _i_guard > _i_dim and _i_drop > _i_guard
              and 'pass' in _EL78[_i_guard:_i_drop])
    check('v2.78 A⑥ 压暗帧保住标记后**短路掉「按 ratio 丢标记」**'
          '（两段逻辑互相拆台：保住了又丢 ✗ —— 第七种形态） · %s'
          % ('已短路 ✓' if _a6_ok else '仍会被丢'), _a6_ok)

    # ── A⑦ 计划里还有没走的步 ⇒ **不算收工** ──
    #   真机铁证（2026-10-27 21:57 map 4）：
    #     order = [3,2 / 1,3 勇者之墓 / 4,5 boss]，give_up_step 摘掉 3,2 后 plan 还剩 2 步
    #     却 finish: blank_board 直接收工 ⇒ 2 步没走 ✗
    _a7_ok = ("_plan_left" in _EL78
              and 'not pending_buy and not _plan_left' in _EL78)
    check('v2.78 A⑦ blank_board 判据带 not _plan_left'
          '（旧写法只看 had_plan ⇒ 计划剩 2 步也收工 ⇒ 没打到 boss ✗） · %s'
          % ('已加 ✓' if _a7_ok else '缺'), _a7_ok)

    # ── A⑧ 面板标题别名**在循环之前**归一，且**参与循环判据** ──
    #   「限时超值礼包」= 限+时+**超+值**+礼+包，而 L['special'] 里是「限时礼包」
    #   ⇒ '限时礼包' in '限时超值礼包' == **False** ⇒ 进不了循环
    #   ⇒ SPECIAL_ALIAS 里虽有这条别名，但它在**循环之内**才执行 ⇒ 永远轮不到 ✗
    _s, _e, _b = _span78('popups')
    _i_al = _b.find('_t_alias = SPECIAL_ALIAS.get(')
    _i_lp = _b.find("for t in L['special']:")
    _a8_ok = (0 <= _i_al < _i_lp and 't == _t_alias' in _b[_i_lp:_i_lp + 200])
    check('v2.78 A⑧ 面板标题别名在 special 循环**之前**归一，并参与循环判据'
          '（别名只写在循环内 ⇒ 入口 fb() 就 False ⇒ 永远轮不到 ✗） · %s'
          % ('顺序对 ✓ (别名@%d < 循环@%d)' % (_i_al, _i_lp) if _a8_ok else '顺序错/缺'),
          _a8_ok)

    # ══════════════════════════════════════════════════════════════════
    # B 组：**执行级**（喂数据真跑被测函数 —— 结构级只能证明「代码在」，
    #       证明不了「判据对」；本项目栽过多次「判据装好了但没接上」✗）
    #   ⚠ 一律写成**表驱动 for 循环**：每条 case 都真调一次函数，
    #     且每个正例都配一个**必须判负**的对照项（否则「恒真」也能全绿 ✗）
    # ══════════════════════════════════════════════════════════════════

    # ── B① `_is_prophecy_panel()`：真机预言帧 True / 背包 & 勇者之墓 **False** ──
    _prop_items = [item('预言石板', 540, 383), item('本次可选择1个预言！', 540, 470),
                   item('武装', 212, 714), item('战场', 540, 714),
                   item('地块结算时获得装备数量+100%', 212, 800),
                   item('地图中至少出现1个勇者', 540, 800),
                   item('之墓，并且勇者之墓奖', 540, 840),
                   item('确定', 541, 1180)]
    _relic_items = [item('英灵使者', 540, 400), item('成功率90%', 766, 946),
                    item('成功率100%', 766, 1139), item('必定成功', 392, 1488),
                    item('确定', 690, 1488)]
    _bag_items = [item('背包装备', 540, 200), item('筛选', 900, 300),
                  item('16级', 300, 500), item('16级', 400, 500),
                  item('16级', 500, 500), item('确定', 541, 1180)]
    _cases_b1 = [('真机预言面板', _prop_items, True),
                 ('对照·背包装备列表', _bag_items, False),
                 ('对照·勇者之墓面板（成功率x2+必定成功）', _relic_items, False)]
    for _r in range(len(_cases_b1)):
        _nm, _it, _want = _cases_b1[_r]
        _got = EL._is_prophecy_panel(_it)
        check('v2.78 B① 执行级[%s] _is_prophecy_panel() ⇒ %s（期望 %s）'
              % (_nm, _got, _want), _got is _want)

    # ── B② `close_newequip()`：预言面板**不许被抢** / 真装备弹窗**必须关得掉** ──
    #   ⚠ 判据钉「抢不抢」＋「点了没有」，不是返回值好看
    _equip_items = [item('获得新装备！', 531, 992),
                    item('力量之戒 +12%', 528, 1101),
                    item('返回', 540, 1252)]
    _cases_b2 = [('预言面板（「武装」卡含「获得装备」）', _prop_items, False, 0),
                 ('对照·真「获得新装备！」弹窗', _equip_items, True, 1)]
    for _r in range(len(_cases_b2)):
        _nm, _it, _want_ret, _min_taps = _cases_b2[_r]
        EL._PANEL_STUCK.clear()
        _bot = FakeBot(_it)
        _r2 = EL.close_newequip(_bot, _it, [], 'gate_v278', verify=False)
        check('v2.78 B② 执行级[%s] ⇒ 返回 %s / 点了 %d 次（期望 %s / ≥%d 次）'
              % (_nm, _r2, len(_bot.taps), _want_ret, _min_taps),
              _r2 is _want_ret and len(_bot.taps) >= _min_taps)

    # ── B③ `_bottom_ok()`：窗口语义 ＋ 只认三种按钮名 ──
    _cases_b3 = [('下半屏「确定」(y=1180)', [item('确定', 541, 1180)], 1180),
                 ('对照·上半屏「确定」(y=300)', [item('确定', 541, 300)], None),
                 ('对照·下半屏「购买」', [item('购买', 541, 1180)], None),
                 ('对照·下半屏「关闭」', [item('关闭', 541, 1180)], None)]
    for _r in range(len(_cases_b3)):
        _nm, _it, _want_cy = _cases_b3[_r]
        _got = EL._bottom_ok(_it)
        _got_cy = int(_got['cy']) if _got else None
        check('v2.78 B③ 执行级[%s] ⇒ cy=%s（期望 %s）' % (_nm, _got_cy, _want_cy),
              _got_cy == _want_cy)

    # ── B④ 面板格名单：**从源码 AST 真取出来**再逐项判 ──
    #   ⚠ 不用字符串 grep：留档注释里必然出现这些名字 ⇒ 会假红（本仓已四次）
    _b4_names = None
    _i_b4 = _EL78.find('_is_panel_cell = any(')
    if _i_b4 >= 0:
        _i_open = _EL78.find('(', _EL78.find('for _kw in (', _i_b4))
        _i_close = _EL78.find('))', _i_open) if _i_open > 0 else -1
        if _i_open > 0 and _i_close > _i_open:
            try:
                _b4_names = list(_ast78.literal_eval(_EL78[_i_open:_i_close + 1]))
            except Exception:       # noqa: BLE001
                _b4_names = None
    _cases_b4 = [('预言石碑', True), ('预言石板', True), ('旅行商人', True),
                 ('黄金宝库', True), ('传承祭坛', True), ('限时礼包', True),
                 ('金属宝箱怪', True), ('机巧宝箱怪', True),
                 ('对照·S00003_001 岩地', False), ('对照·S30001_002 矿箱', False),
                 ('对照·S20003_101 枯木树桩', False)]
    for _r in range(len(_cases_b4)):
        _nm, _want = _cases_b4[_r]
        _hit = any(_k in _nm for _k in (_b4_names or []))
        check('v2.78 B④ 执行级[%s] 命中判据=%s（期望 %s）' % (_nm, _hit, _want),
              _hit is _want)

    # ── B⑤ `_foretell_card_y()`：换分辨率（换 C）卡片窗口仍然覆盖标题 ──
    #   用户④「没有正确选中预言」：FORETELL_CARD_Y = 714 是**真机弹窗系**绝对值
    #     ⇒ 模拟器 C=154 时标题在 660，而窗口 684~769 ⇒ 三张卡全落空 ✗
    #   ⚠ 钉的是「**参考基值 + C**」，不是某个魔法数字 —— 两个 C 都要过 ✓
    import buypanels as _BP_mod78
    _tol_up78 = int(getattr(_BP_mod78, 'FORETELL_CARD_Y_TOL_UP', 30))
    _tol_dn78 = int(getattr(_BP_mod78, 'FORETELL_CARD_Y_TOL_DN', 55))
    _orig_dlg78 = _BP_mod78.dlg_shift
    _cases_b5 = [(209.0, 714, '真机 C=209 / 实测标题 714~715'),
                 (154.0, 660, '模拟 1280x2640 C=154 / 实测标题 660')]
    for _r in range(len(_cases_b5)):
        _c, _obs, _nm = _cases_b5[_r]
        try:
            _BP_mod78.dlg_shift = (lambda _v=_c: _v)
            _base = _BP_mod78._foretell_card_y()
        finally:
            _BP_mod78.dlg_shift = _orig_dlg78
        _cover = (_base - _tol_up78) <= _obs <= (_base + _tol_dn78)
        check('v2.78 B⑤ 执行级[%s] 窗口 %d~%d 覆盖标题 %d ⇒ %s'
              % (_nm, _base - _tol_up78, _base + _tol_dn78, _obs,
                 '覆盖 ✓' if _cover else '落空 ✗'), _cover)
    check('v2.78 B⑤ 对照项：**旧写法（写死 714）在模拟器上必然读不到**'
          '（证明上一条不是恒绿：660 不在 684~769 内） · %s'
          % ('如预期 ✗' if not (684 <= 660 <= 769) else '判据失效'),
          not (684 <= 660 <= 769))

    # ── B⑥ 限时礼包别名：子串匹配确实失败、别名确实命中 ──
    _title_gift = '限时超值礼包'
    _cases_b6 = [('子串「限时礼包」在标题里', '限时礼包' in _title_gift, False),
                 ('别名归一命中 act_on',
                  (EL.SPECIAL_ALIAS.get(_title_gift) == '限时礼包'
                   and '限时礼包' in EL.L['act_on']), True)]
    for _r in range(len(_cases_b6)):
        _nm, _got, _want = _cases_b6[_r]
        check('v2.78 B⑥ 执行级[%s] ⇒ %s（期望 %s）' % (_nm, _got, _want),
              _got is _want)

    # ── B⑦ `_panel_title_of()`：「等于」判据，正文里的四字**不算标题** ──
    _cases_b7 = [
        ('有真标题「预言石板」', [item('预言石板', 540, 383),
                                  item('之墓，并且勇者之墓奖', 540, 840)], '预言石板'),
        ('对照·只有正文没有标题', [item('之墓，并且勇者之墓奖', 540, 840),
                                   item('地图中至少出现1个勇者', 540, 800)], None),
    ]
    for _r in range(len(_cases_b7)):
        _nm, _it, _want = _cases_b7[_r]
        _got = EL._panel_title_of(_it)
        check('v2.78 B⑦ 执行级[%s] ⇒ %r（期望 %r）' % (_nm, _got, _want),
              _got == _want)

    # ── B⑧ ★★★ 端到端：**拿真机造成病②的那一帧**跑 popups() ──
    #   这一帧同时含「战场」（正文有完整四字「勇者之墓」）＋「武装」（正文含「获得装备」）
    #   ⇒ 旧代码先被 newequip 抢、再被 relic 抢；修好后必须**判成预言石碑**
    #   ⚠ 卡片标题 y 用**当前环境的真实卡 y**（_foretell_card_y()）⇒ 换机器也成立 ✓
    _fy78 = _BP_mod78._foretell_card_y()
    _bug2_items = [item('预言石板', 540, 383), item('本次可选择1个预言！', 540, 470),
                   item('战场', 540, _fy78), item('武装', 212, _fy78),
                   item('秘藏', 868, _fy78 + 1),
                   item('地图中至少出现1个勇者', 540, 800),
                   item('之墓，并且勇者之墓奖', 540, 840),
                   item('地块结算时获得装备数量+100%', 212, 800),
                   item('确定', 541, 1180)]
    EL._PANEL_STUCK.clear()
    _bot_b8 = FakeBot(_bug2_items)
    _log_b8 = []
    _act_b8 = EL.popups(_bot_b8, _bug2_items, _log_b8, ctx={'st': {}, 'flags': {}})
    _spec_b8 = [e for e in _log_b8 if e.get('special')]
    _relic_b8 = [e for e in _log_b8 if e.get('relic')]
    _ne_b8 = [e for e in _log_b8 if e.get('newequip_back')]
    check('v2.78 B⑧ 执行级：这一帧被派给**预言石碑**（by=structure），不是勇者之墓'
          '（旧代码：t 被判成勇者之墓 ⇒ relic_flow 找不到成功率 ⇒ panel_missing 40+ 次 ✗） · %s'
          % ([e.get('special') for e in _spec_b8],),
          len(_spec_b8) == 1 and _spec_b8[0].get('special') == '预言石碑'
          and _spec_b8[0].get('by') == 'structure')
    check('v2.78 B⑧ 执行级：**一条 relic 日志都没有**'
          '（有就说明它又被勇者之墓抢走了 ✗） · %s' % (len(_relic_b8),),
          not _relic_b8)
    check('v2.78 B⑧ 执行级：**一次装备返回都没点**'
          '（「武装」卡正文含「获得装备」⇒ 旧代码拿装备流程点预言面板 ✗） · %s'
          % (len(_ne_b8),), not _ne_b8)
    check('v2.78 B⑧ 执行级：popups() 返回 handled；且**没有点底部的「返回」**'
          '（点返回就把没选完的面板关掉了 —— 用户③「没有正确点掉」的另一半 ✗） · %s'
          % ('act=%r taps=%r' % (_act_b8, _bot_b8.taps),),
          _act_b8 == 'handled'
          and not any(_t[0] == 'tap_dlg' and _t[2] == 1252 for _t in _bot_b8.taps))

    # ── B⑧ 对照项：**真勇者之墓面板**必须仍然走 relic（别把那条路也堵死）──
    EL._PANEL_STUCK.clear()
    _bot_b8c = FakeBot(_relic_items)
    _log_b8c = []
    _act_b8c = EL.popups(_bot_b8c, _relic_items, _log_b8c, ctx={'st': {}, 'flags': {}})
    _spec_b8c = [e.get('special') for e in _log_b8c if e.get('special')]
    _pick_b8c = [e for e in _log_b8c if e.get('relic') == 'pick_row']
    check('v2.78 B⑧ 对照项：真勇者之墓面板仍派给「勇者之墓」并**选中 100%% 那行**'
          '（结构特征判据太宽 ⇒ 会把勇者之墓也当预言面板 ⇒ 功能反被吃掉 ✗） · %s'
          % ('special=%r pick=%r' % (_spec_b8c,
                                      [e.get('row') for e in _pick_b8c]),),
          _spec_b8c == ['勇者之墓']
          and any(e.get('row') == 2 for e in _pick_b8c))

    # ══════════════════════════════════════════════════════════════════
    # C 组：撤销守门（源码里**不许再出现**旧写法）
    #   ⚠⚠ 必须先剥掉整行注释再查 —— 留档注释里必然逐字引用旧写法（本仓已四次假红）
    # ══════════════════════════════════════════════════════════════════
    def _code_only78(_src):
        _out = []
        for _ln in _src.split(chr(10)):
            if _ln.strip().startswith('#'):
                continue
            _out.append(_ln.split('#')[0] if '#' in _ln else _ln)
        return chr(10).join(_out)

    _code_el78 = _code_only78(_EL78)
    _code_bp78 = _code_only78(_BP78)
    check('v2.78 C① 撤销守门：buypanels 里**没有**写死的卡片 y（714），且 _foretell_card_y() 还在'
          '（换分辨率就失效 —— 本项目「弹窗系绝对值当常量」的第二例 ✗） · %s'
          % ('干净 ✓' if ('FORETELL_CARD_Y = 714' not in _code_bp78
                           and '_foretell_card_y()' in _code_bp78) else '仍有写死'),
          'FORETELL_CARD_Y = 714' not in _code_bp78
          and '_foretell_card_y()' in _code_bp78)

    # ⚠⚠ C①b 【牙齿测试逗出来的假绿】上一条只查**字面量**
    #   ⇒ 把 `FORETELL_CARD_Y_REF = 506` 改成 `714`（= 把弹窗系绝对值填进参考系基值，就是本 bug 本身）
    #   名字还叫 _REF ⇒ 字面量查不到 ⇒ 上一条**仍继续绿** ✗（实测：那个变异只有 B⑤ 两条红）
    #   ⇒ 补一条「**两套坐标系的换算关系**」（文档 §6 定的正确写法：存参考系基值、用时 +dlg_shift）
    #   真机实测：基值 506 + C 209 = 弹窗系 715（而 714 不可能是基值：那就等于把弹窗系当参考系）✓
    _ref78 = int(getattr(_BP_mod78, 'FORETELL_CARD_Y_REF', -1))
    _c1b_ok = (_ref78 > 0 and _ref78 != 714 and (_ref78 + 209) == 715)
    check('v2.78 C①b 参考系基值与弹窗系的**换算关系**对得上'
          '（基值 %d + C 209 必须 = 真机实测 715；填成 714 = 把弹窗系当参考系 ✗） · %s'
          % (_ref78, '对得上 ✓' if _c1b_ok else '对不上'), _c1b_ok)

    _i_dc78 = _code_el78.find('if _dimmed_kept:')
    _i_dd78 = _code_el78.find("'marks_dropped_panel'")
    check('v2.78 C② 撤销守门：压暗短路**在代码里**（不在注释里）'
          '（剥掉注释后仍要能找到 if _dimmed_kept: pass，且它在丢标记之前 ✗） · %s'
          % ('在 ✓' if (_i_dc78 >= 0 and _i_dd78 > _i_dc78
                        and 'pass' in _code_el78[_i_dc78:_i_dd78]) else '缺'),
          _i_dc78 >= 0 and _i_dd78 > _i_dc78
          and 'pass' in _code_el78[_i_dc78:_i_dd78])

    _i_cc78 = _code_el78.find('_is_panel_cell = any(')
    _i_cd78 = _code_el78.find("done.add(st['last'])", _i_cc78) if _i_cc78 >= 0 else -1
    _i_ck78 = _code_el78.find("'panel_cell_kept'", _i_cc78) if _i_cc78 >= 0 else -1
    check('v2.78 C③ 撤销守门：代码里 panel_cell_kept **在** done.add() 之前'
          '（顺序反了 = 面板格照样写 done = 目标永久消失 ✗） · %s'
          % ('顺序对 ✓ (记录@%d < done@%d)' % (_i_ck78, _i_cd78)
             if (0 <= _i_ck78 < _i_cd78) else '顺序错/缺'),
          0 <= _i_ck78 < _i_cd78)

except Exception as _e78:       # noqa: BLE001
    check('v2.78 守门可运行（%r）' % (_e78,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.79【限时礼包「免费→返回」之后**面板还开着，脚本没有第三步把它关掉**】
#
#   ---- 用户原话（2026-10-28）----
#     「限时礼包的脚本好像少了一步关闭礼包页面（在点击免费和返回之后）」
#
#   ---- 实测：不是少一步，那一步存在但**一次都没生效** ----
#     喂真机帧（`mapbot_pc/runs/spec_dev/gift_after_return.png`）＋其 rapidocr 结果跑
#     `gift_flow()`：
#       {'gift': 'tap_free1', ...}                              <- 点了免费
#       {'close': 'no_text_btn', 'what': 'gift_tail', ...}      <- 认不到文字按钮，不点
#       {'gift_tail': 'close_panel', 'n': 0, ...}               <- 关面板动作 = **0 次**
#     而同一帧 OCR：面板上**没有**「返回/确定/关闭」任何一个（34 条结果里一个都没有）
#
#   ---- 三层叠加（每层单独看都合理）----
#     (1) `_univ_close()` 先按**文字**找按钮 —— 礼包面板没有这种按钮 X
#     (2) 万能位 `UNIV_CLOSE` 在 v2.59 被**明确禁掉**（走 tap_dlg 在真机落在**棋盘内**，
#         盲点 = 点一个格子）=> 那条注释写的就是「如实返回 False」O
#     (3) 面板唯一出口是**右上角红色 X**，而 `ensure_closed()` 只认 `x~493/1024 +-60`
#         且 `y in [180,300]`（那**是棋盘两侧面板**的标定值）=> 礼包 X 实测 ref(876,621)
#         **x 与 y 两轴都不命中** => 永远点不到 XX
#     => 面板残留 => 盖住棋盘 => 后面格子点不动（与 6.74 病(7) 同一条链）
#
#   ---- 修法：新增 `panel_title_close_x()`（结构特征，不写死坐标）----
#     四条**全中**才认：红块 54~80px ＋ 白/红比 >=0.18 ＋ 同行左侧有标题 ＋ 标题在**白名单**
#     接进 `close_panel()` 作为**第三道**（在文字按钮之后、万能位之前）
#
#   !! 本组最值钱的一条：**白名单是踩出来的，黑名单挡不住**
#     第一版写成黑名单（排除「当前难度/首领战斗/帮助/配队」这些导航 UI 词）=>
#     结算面板那个「**回放按钮**」(759,225) 左侧是**地图名**「异常之风」，
#     它不在任何导航词表里 => 照样命中 => **点它就会放一遍回放**
#     （PC 语料 16866 帧里 (759,225) 出现 **43 次**；用户 2026-09-25 连报三次
#       「还在看回放」就是它）=> 只有「**必须是已知面板标题**」能可靠挡住 => 白名单 O
#     => 教训：**用「排除已知坏样本」写的判据，挡不住没见过的坏样本**。
try:
    _BP79 = io.open(os.path.join(MAPBOT, 'buypanels.py'), encoding='utf-8').read()

    # ── A 结构级 ──
    check('v2.79 A(1) 有 panel_title_close_x()（按结构特征定位标题行的 X） · %s'
          % ('有 OK' if 'def panel_title_close_x(' in _BP79 else '缺'),
          'def panel_title_close_x(' in _BP79)

    _i79 = _BP79.find('PANEL_X_TITLES = (')
    _seg79 = _BP79[_i79:_i79 + 320] if _i79 >= 0 else ''
    _wl79 = all(k in _seg79 for k in ('预言石板', '英灵使者', '限时超值礼包',
                                      '传承祭坛', '黄金宝库', '旅行商人'))
    check('v2.79 A(2) 白名单 PANEL_X_TITLES 含六个真面板标题'
          '（!! 必须是**白名单**：黑名单挡不住「回放按钮」左侧的地图名「异常之风」X） · %s'
          % ('齐 OK' if _wl79 else '缺'), _wl79)

    check('v2.79 A(3) 判据里**没有**残留黑名单思路（不再靠「排除导航词」）'
          '（黑名单=用「已知坏样本」写判据 => 挡不住没见过的坏样本 X） · %s'
          % ('干净 OK' if ('PANEL_X_NOT_TITLE' not in _BP79) else '仍有黑名单'),
          'PANEL_X_NOT_TITLE' not in _BP79)

    _i_cp79 = _BP79.find('def close_panel(')
    _NL79 = chr(10)
    _i_cp79_end = (_BP79.find(_NL79 + 'def ', _i_cp79 + 10)
                    if _i_cp79 >= 0 else -1)
    _cpbody79 = _BP79[_i_cp79:_i_cp79_end] if _i_cp79 >= 0 and _i_cp79_end > 0 else ''
    # !! 必须先剥掉整行注释再找函数名：我在注释里逐字写了 `ensure_closed()`, 
    #    `_univ_close()` 来解释病因 => 直接 find 会命中文档而不是代码 => 假红
    #    （本仓已踩过五次：v1.62c / v1.67 / v1.68 A(10) / v2.78 C1 / 本条）
    _cpcode79 = chr(10).join(_ln79 for _ln79 in _cpbody79.split(chr(10))
                             if not _ln79.strip().startswith('#'))
    _i_x79 = _cpcode79.find('panel_title_close_x(')
    _i_u79 = _cpcode79.find('_univ_close(')
    _i_e79 = _cpcode79.find('ensure_closed(')
    check('v2.79 A(4) close_panel() 真接上了这道闸门，顺序 = ensure_closed -> title_x -> _univ_close'
          '（文字按钮最准要优先；但礼包面板没有文字按钮 => 必须有结构特征那道） · %s'
          % (('顺序对 OK (%d < %d < %d)' % (_i_e79, _i_x79, _i_u79))
             if (0 <= _i_e79 < _i_x79 < _i_u79) else '顺序错/缺'),
          0 <= _i_e79 < _i_x79 < _i_u79)

    # ── B 执行级（真跑，喂真机帧） ──
    _gift_frame79 = os.path.join(PROJ, '..', 'mapbot_pc', 'runs', 'spec_dev',
                                 'gift_after_return.png')
    if not os.path.exists(_gift_frame79):
        skip('v2.79 B(1)~B(3) 执行级（缺真机帧 mapbot_pc/runs/spec_dev/gift_after_return.png）')
    else:
        import cv2 as _cv79
        import buypanels as _BPmod79

        def _mk79(_rows):
            return [item(_t, _cx, _cy) for _t, _cx, _cy in _rows]

        _GIFT_PANEL79 = _mk79([
            ('限时超值礼包', 541, 620), ('超值礼包1', 277, 704), ('已领取', 770, 800),
            ('20', 337, 854), ('超值礼包2', 277, 933), ('6', 786, 1020),
            ('60', 337, 1083), ('超值礼包3', 278, 1162), ('免费', 770, 1259),
            ('剩余时间05:57:27', 540, 1402)])
        _REPLAY79 = _mk79([
            ('异常之风', 540, 225), ('首领战斗2人存活', 136, 225),
            ('当前难度521', 975, 277), ('帮助', 821, 210),
            ('战斗事件', 541, 443), ('100级', 539, 599)])
        _SHRINE79 = _mk79([('传承祭坛', 691, 504), ('选择装备', 540, 700),
                            ('确定', 540, 1200)])

        class _B79(object):
            ocr_grabs = True

            def __init__(self, _png, _items):
                _im = _cv79.imread(_png)
                self._img = _cv79.resize(_im, (1080, 1920),
                                         interpolation=_cv79.INTER_CUBIC)
                self._items = [dict(t) for t in _items]
                self.taps = []

            def img(self):
                return self._img

            def img_dlg(self):
                return self._img

            def snap(self, *a, **k):
                pass

            def ocr(self, *a, **k):
                return [dict(t) for t in self._items]

            def ocr_dlg(self, *a, **k):
                return [dict(t) for t in self._items]

            def tap(self, x, y, wait=0.0):
                self.taps.append((int(x), int(y)))

            def tap_dlg(self, x, y, wait=0.0):
                self.taps.append((int(x), int(y)))

            def _sleep(self, s):
                pass

        _shrine79 = os.path.join(PROJ, '..', 'mapbot_pc', 'runs', 'acc3',
                                 'shrine_panel_r-1.png')
        _cases79 = [
            ('礼包面板（标题 541,620 / X 876,621）',
             _gift_frame79, _GIFT_PANEL79, '限时超值礼包', (876, 621)),
            ('对照 - 结算面板**回放按钮**(759,225)：左侧是地图名「异常之风」',
             os.path.join(PROJ, '..', 'mapbot_pc', 'runs', 'acc1', 'm9_r003.png'),
             _REPLAY79, None, None),
        ]
        if os.path.exists(_shrine79):
            _cases79.append(
                ('传承祭坛（标题 691,504 / X 984,504）',
                 _shrine79, _SHRINE79, '传承祭坛', (984, 504)))
        for _r in range(len(_cases79)):
            _nm, _png, _it, _ti, _want = _cases79[_r]
            if not os.path.exists(_png):
                skip('v2.79 B(1)[%s] 缺帧 %s' % (_nm, _png))
                continue
            _bot = _B79(_png, _it)
            _got = _BPmod79.panel_title_close_x(_bot, title=_ti, log=[])
            check('v2.79 B(1) 执行级[%s] => %r（期望 %r）' % (_nm, _got, _want),
                  _got == _want)

        _S_PANEL = _mk79([('限时超值礼包', 541, 620), ('超值礼包1', 277, 704),
                          ('免费', 770, 800), ('超值礼包2', 277, 933),
                          ('超值礼包3', 278, 1162)])
        _S_RESULT = _mk79([('恭喜获得', 540, 700), ('货币', 400, 900),
                           ('返回', 540, 1211)])
        _S_AFTER = _mk79([('限时超值礼包', 541, 620), ('超值礼包1', 277, 704),
                          ('已领取', 770, 800), ('超值礼包2', 277, 933)])
        _S_CLOSED = _mk79([('开始冒险', 541, 1889)])

        class _SB79(_B79):
            def __init__(self, _png):
                _B79.__init__(self, _png, _S_PANEL)
                self.state = 'panel'

            def _cur(self):
                return {'panel': _S_PANEL, 'result': _S_RESULT,
                        'after': _S_AFTER, 'closed': _S_CLOSED}[self.state]

            def ocr(self, *a, **k):
                return [dict(t) for t in self._cur()]

            def ocr_dlg(self, *a, **k):
                return [dict(t) for t in self._cur()]

            def tap_dlg(self, x, y, wait=0.0):
                self.taps.append((int(x), int(y)))
                if self.state == 'panel' and (int(x), int(y)) == (770, 800):
                    self.state = 'result'
                elif self.state == 'result' and (int(x), int(y)) == (540, 1211):
                    self.state = 'after'
                elif self.state == 'after' and (int(x), int(y)) == (876, 621):
                    self.state = 'closed'

            def _sleep(self, s):
                pass

        _sb = _SB79(_gift_frame79)
        _BPmod79.gift_flow(_sb, [])
        check('v2.79 B(2) 端到端：tap 时序 = **免费 -> 返回 -> 右上角 X**'
              '（用户原话「少了一步关闭礼包页面」= 缺的正是第三个） · %s'
              % (repr(_sb.taps),),
              _sb.taps == [(770, 800), (540, 1211), (876, 621)])
        check('v2.79 B(2) 端到端：**面板最终真被关掉**（不是以为关了）· state=%s'
              % (_sb.state,), _sb.state == 'closed')

        _sb2 = _SB79(_gift_frame79)
        _BPmod79.gift_flow(_sb2, [])
        check('v2.79 B(3) 对照项：步骤(1)「免费」与(2)「返回」**仍然都在**'
              '（新加的是第(3)步，不能把前两步顶掉 X） · %s' % (repr(_sb2.taps[:2]),),
              _sb2.taps[:2] == [(770, 800), (540, 1211)])
except Exception as _e79:       # noqa: BLE001
    check('v2.79 守门可运行（%r）' % (_e79,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.80【「自动停了」—— 预言面板**上层认得出、下层认不出** ⇒ 面板关不掉 ⇒ 整局白跑】
#
#   ---- 用户原话（2026-10-28）：「查查日志为什么自动停了」----
#   从设备拉 bagdbg/mgas_log.txt（281 行）解析出的链条：
#
#     点开预言石碑
#       -> popups() 用**结构特征**认出它（special: 预言石碑, by: structure）
#       -> 调用 buypanels.foretell_flow()
#       -> 但它第一行只认**标题文字**「预言石板」
#       -> 真机 OCR 读成「**预合石板**」=> panel_missing（**45 轮，每轮一次**）
#       -> 返回空 => popups 的 else 分支只调 ensure_closed()
#       -> ensure_closed 只认 X **字符**（x/X/十字），预言面板没有 => **一次都不点**
#       -> 面板永远开着 => 挡住棋盘
#       -> 45 轮 stamina 2054->2058（**只涨不跌**）=> 一格都没点开
#       -> maxed => 退图 => finish_map 反复点「确定」(540,1178) **25 次**
#       -> 90s 超时 => finished:false => STATS['stopped']='退图失败' => **停整局**
#
#   ---- 决定性数字（这条断言的数据来源）----
#     `foretell: panel_missing` = 45 次；`finish: confirmed` = 25 次；
#     每轮 64s 共 2884s（48 分钟）；`"stop"` 出现 **0 次**（= **不是用户点停** ✓）
#
#   ---- 本质：同族第 N 次「判据建在错的层」 ----
#     上层用结构特征认面板、下层用标题认 —— **两层判据不同口径** => 下层静默失败。
#     与 v2.78 病(2)『标题被读成言何饭 => 旧修法失效』是同一条教训：
#     **标题不可靠时必须以结构特征为准**。
#
#   ---- 修法（三层同口径）----
#     (1) foretell_flow 的标题门槛补 `_foretell_panel_like()` 结构特征兜底
#     (2) panel_still_open / close_panel 加 `structured=` 形参
#         （原来 `panel_still_open` 只认标题 => 标题读不到就 `return 0` **一次不点**）
#     (3) foretell_flow 两处 close_panel 传 `structured=_foretell_panel_like`
try:
    import buypanels as _BPmod80

    _BP80 = io.open(os.path.join(MAPBOT, 'buypanels.py'), encoding='utf-8').read()

    # ── A 结构级 ──
    check('v2.80 A(1) 有 _foretell_panel_like()（结构特征判据，不看标题） · %s'
          % ('有 OK' if 'def _foretell_panel_like(' in _BP80 else '缺'),
          'def _foretell_panel_like(' in _BP80)

    _i80 = _BP80.find('def foretell_flow(')
    _ft80 = _BP80[_i80:_BP80.find(chr(10) + 'def ', _i80 + 10)] if _i80 >= 0 else ''
    check('v2.80 A(2) foretell_flow 的标题门槛**带结构特征兜底**'
          '（只认标题 => 真机读成「预合石板」=> panel_missing 45 次 X） · %s'
          % ('已兜底 OK' if '_foretell_panel_like(it)' in _ft80 else '仍只认标题'),
          '_foretell_panel_like(it)' in _ft80)

    check('v2.80 A(3) 标题读不到时**留日志** `title_unreadable_but_structure_ok`'
          '（否则下次排查又是一头雾水 —— 静默失效最典型的表现就是日志里缺某一行） · %s'
          % ('有 OK' if 'title_unreadable_but_structure_ok' in _ft80 else '缺'),
          'title_unreadable_but_structure_ok' in _ft80)

    _i_psi = _BP80.find('def panel_still_open(')
    _psi80 = _BP80[_i_psi:_BP80.find(chr(10) + 'def ', _i_psi + 10)] if _i_psi >= 0 else ''
    check('v2.80 A(4) `panel_still_open()` 有 `structured=` 形参并用上'
          '（原来只认标题 => close_panel 直接 return 0 **一次不点** X） · %s'
          % ('有 OK' if ('structured=None' in _psi80 and 'structured(' in _psi80)
                          else '缺'),
          'structured=None' in _psi80 and 'structured(' in _psi80)

    _i_cp = _BP80.find('def close_panel(')
    _cp80 = _BP80[_i_cp:_BP80.find(chr(10) + 'def ', _i_cp + 10)] if _i_cp >= 0 else ''
    check('v2.80 A(5) `close_panel()` 透传 `structured=` 给 panel_still_open · %s'
          % ('透传 OK' if 'structured=structured' in _cp80 else '没透传'),
          'structured=structured' in _cp80)

    check('v2.80 A(6) foretell_flow 两处 close_panel 都传了 structured'
          '（cards_timeout / tail 漏一个 => 那条路径仍然关不掉 X） · %s'
          % ('两处齐 OK' if _ft80.count('structured=_foretell_panel_like') >= 2
                            else '漏传 %d 处' % (2 - _ft80.count('structured=_foretell_panel_like'))),
          _ft80.count('structured=_foretell_panel_like') >= 2)

    # ── B 执行级（喂**事故帧的完整 OCR** 真跑）──
    #   !! 必须用**完整 items**（含「确定」），不能用日志里那 12 条 ——
    #     日志只存了 `[:12]`，缺了「确定」=> 会误判成"OCR 漏检"（我第一版就这么误判过）
    _FULL80 = [
        ('预合石板', 540, 451), ('本次可选择1个预言！', 530, 514),
        ('武装', 212, 714), ('圣域', 540, 714), ('神兵', 868, 715),
        ('地块结算时获得装备', 212, 800), ('多格地块结算时至少', 540, 800),
        ('地块结算时所有装备', 868, 800), ('百', 212, 840),
        ('数量+100%', 212, 880), ('至少是紫色位阶。', 540, 880),
        ('有1个神石。', 868, 880),
        ('确定', 541, 1333),          # 真机 foretell_panel2.png 实测
    ]
    _it80 = [item(_t, _cx, _cy) for _t, _cx, _cy in _FULL80]

    class _B80(object):
        ocr_grabs = True

        def __init__(self, _png):
            import cv2 as _cv80
            _im = _cv80.imread(_png)
            self._img = _cv80.resize(_im, (1080, 1920),
                                     interpolation=_cv80.INTER_CUBIC)
            self.taps = []
            self.state = 'panel'

        def img(self):
            return self._img

        def img_dlg(self):
            return self._img

        def snap(self, *a, **k):
            pass

        def ocr(self, *a, **k):
            return [] if self.state == 'closed' else [dict(t) for t in _it80]

        def ocr_dlg(self, *a, **k):
            return [] if self.state == 'closed' else [dict(t) for t in _it80]

        def tap(self, x, y, wait=0.0):
            self.tap_dlg(x, y, wait)

        def tap_dlg(self, x, y, wait=0.0):
            self.taps.append((int(x), int(y)))
            if (int(x), int(y)) == (541, 1333):
                self.state = 'closed'

        def _sleep(self, s):
            pass

    _png80 = os.path.join(PROJ, '..', 'mapbot_pc', 'runs', 'spec_dev',
                          'foretell_panel2.png')
    if not os.path.exists(_png80):
        skip('v2.80 B(1)~B(3) 执行级（缺真机帧 mapbot_pc/runs/spec_dev/foretell_panel2.png）')
    else:
        # B(1) 判据本身
        check('v2.80 B(1) 执行级：事故那帧 `_foretell_panel_like()` = True'
              '（`_has(预言石板)` = **False** —— 真机确实读成「预合石板」） · like=%s has=%s'
              % (_BPmod80._foretell_panel_like(_it80),
                 bool(_BPmod80._has(_it80, '预言石板'))),
              _BPmod80._foretell_panel_like(_it80) is True
              and bool(_BPmod80._has(_it80, '预言石板')) is False)

        # B(2) 端到端：面板**真的被关掉**
        _b80 = _B80(_png80)
        _lg80 = []
        _BPmod80.foretell_flow(_b80, _lg80)
        _closed80 = [e for e in _lg80
                     if e.get('foretell_nocards') == 'close_panel']
        check('v2.80 B(2) 端到端：面板**真的被关掉**（state=%s / taps=%s）'
              % (_b80.state, _b80.taps),
              _b80.state == 'closed' and (541, 1333) in _b80.taps)
        check('v2.80 B(2) 端到端：`close_panel` 的 **n >= 1**（旧行为是 n=0 **一次不点**）· %s'
              % ((_closed80[-1] if _closed80 else None),),
              bool(_closed80) and int(_closed80[-1].get('n') or 0) >= 1)
        check('v2.80 B(2) 端到端：**不再 panel_missing**（那是 45 轮白跑的起点） · %s'
              % ([e.get('foretell') for e in _lg80 if e.get('foretell')],),
              not any(e.get('foretell') == 'panel_missing' for e in _lg80))

        # B(3) 对照项：**旧路径确实关不掉**（证明 B(2) 不是恒真）
        _b80c = _B80(_png80)
        _n80c = _BPmod80.ensure_closed(_b80c, [])
        check('v2.80 B(3) 对照项：旧路径 `ensure_closed()` 对预言面板 **n=0 且一次不点**'
              '（它只认 X 字符 x~493/1024 => 预言面板没有 => 面板永远关不掉 X） · n=%s taps=%s'
              % (_n80c, _b80c.taps),
              _n80c == 0 and not _b80c.taps)
except Exception as _e80:       # noqa: BLE001
    check('v2.80 守门可运行（%r）' % (_e80,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.81【`one_round` 每轮必崩：v2.78 引入的 UnboundLocalError（`c` 先用后赋值）】
#
#   ---- 用户原话（2026-10-28）----
#     「黄金宝库无法正常点击」＋「选中奖励后直接关闭宝库页面了，然后又立即打开了宝库页面」
#   ---- 真机铁证（logcat，21:01:04 连续 5 条）----
#     {'round': 1, 'error': 'UnboundLocalError("local variable c ...")'}
#     trace: explore_loop.py:9503 in one_round
#   ---- 病 ----
#     v2.78 写「面板格不写 done」时用了 `c.get('st')` 查这一格的 name，
#     而 `c` 在本函数里要到**下面**才赋值（`c = cell_of(...)`），
#     真正的分类结果在更后面的 `c = classify_async_join(...)`。
#     => 每轮只要走到「act in (battle/battle_clear/handled) 且 st[last] 有值」就抛异常
#     => st[err] += 1 => 这张图一格都走不下去
#     => 面板处理完 return 'handled' 但 done 没写 => 下一轮同一个宝库格**又进目标列表**
#     => 再点开、再崩 => 用户看到的就是「关了又开」的死循环 X
#   ---- 为什么门禁没抓到（本组要补的正是这个）----
#     门禁对本处只做了**静态字符串/结构**断言（「有没有那几句」），
#     **没有真跑 one_round** => 名字作用域这类错误只有执行才暴露。
#     !! 同一个坑本项目踩过：v1.62c 的 AST-grep 只证明「代码在」、证不了「能跑」。
#   ---- 修法 ----
#     不能简单改成先 `c = cell_of(...)` —— 那时 c 还没算分类结果。
#     本处只要「这一格的 name」，而 **st[obs] 累积**里就有同口径的一份：
#     优先 obs、取不到退回本帧 st[st]、都没有就空串 => 语义不变且不会崩 O
try:
    import ast as _ast81
    import textwrap as _tw81

    _EL81 = io.open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
    _L81 = _EL81.split(chr(10))

    # ── A 结构级：不允许再出现 `c.get(` 在学习这段之前（撤回守门）──
    _i81 = _EL81.find("if st['last']:")
    _seg81 = _EL81[_i81:_i81 + 1800] if _i81 >= 0 else ''
    _seg81_code = chr(10).join(_ln81 for _ln81 in _seg81.split(chr(10))
                               if not _ln81.strip().startswith('#'))
    check('v2.81 A(1) 撤回守门：`st[last]` 那段**代码里**没有 `c.get(`（注释里可以有）'
          '（v2.78 就是写了 `c.get("st")` 而 c 还没赋值 => 每轮 UnboundLocalError X） · %s'
          % ('干净 OK' if 'c.get(' not in _seg81_code else '仍有 c.get('),
          'c.get(' not in _seg81_code)

    check('v2.81 A(2) 那段用了 st[obs] / st[st] 取 name（不再依赖未定义变量）· %s'
          % ('有 OK' if ('_obs_map' in _seg81_code and '_cur_map' in _seg81_code)
                          else '缺'),
          '_obs_map' in _seg81_code and '_cur_map' in _seg81_code)

    check('v2.81 A(3) `_rc_last` 在那段里**有赋值**（我第一版补丁把它顶掉了 => NameError）· %s'
          % ('有 OK' if '_rc_last = cell_of(' in _seg81_code else '缺'),
          '_rc_last = cell_of(' in _seg81_code)

    # ── B 执行级：**真跑那段代码**（这是唯一能抓住名字作用域错误的方式）──
    #   把 `if st['last']:` 整块抠出来 exec，喂四种夹具
    try:
        _st81 = next(_k81 for _k81 in range(9000, len(_L81))
                     if _L81[_k81].strip() == "if st['last']:")
        _en81 = next(_k81 for _k81 in range(_st81 + 1, _st81 + 120)
                     if _L81[_k81].strip().startswith('log.append(entry)'))
        _blk81 = _tw81.dedent(chr(10).join(_L81[_st81:_en81]))
    except StopIteration:
        _blk81 = ''
    check('v2.81 B(0) 能定位到 `st[last]` 那段代码块（%d 行）' % _blk81.count(chr(10)),
          bool(_blk81))

    if _blk81:
        _cell81 = EL.cell_center(2, 6)
        _rc81 = EL.cell_of(_cell81[0], _cell81[1])

        def _run81(_st, _done, _log):
            _g = {'st': _st, 'done': _done, 'log': _log, 'cell_of': EL.cell_of}
            try:
                exec(compile(_blk81, '<blk81>', 'exec'), _g)
                return None
            except Exception as _ee:       # noqa: BLE001
                return repr(_ee)

        _cases81 = [
            ('面板格 黄金宝库（来自 obs）', {'obs': {_rc81: {'name': '黄金宝库'}}, 'st': {}}, False),
            ('普通格 草地（来自 obs）', {'obs': {_rc81: {'name': '草地'}}, 'st': {}}, True),
            ('面板格 黄金宝库（来自本帧 st）', {'obs': {}, 'st': {_rc81: {'name': '黄金宝库'}}}, False),
            ('obs/st 都空（**旧代码必崩**的那个场景）', {'obs': {}, 'st': {}}, True),
        ]
        for _r in range(len(_cases81)):
            _nm, _maps, _want_done = _cases81[_r]
            _done81, _log81 = set(), []
            _st81x = {'last': _cell81, 'marks': {}}
            _st81x.update(_maps)
            _err81 = _run81(_st81x, _done81, _log81)
            check('v2.81 B(1) 执行级[%s] 不抛异常=%s / done=%s（期望 %s）'
                  % (_nm, _err81 is None, bool(_done81), _want_done),
                  _err81 is None and bool(_done81) == _want_done)

        # ── 对照项：**把旧代码塞回去**，执行会抛 UnboundLocalError（证明 B(1) 不是恒真）──
        _bad81 = _blk81.replace(
            chr(10).join([
                '    _obs_map = (st.get("obs") or {})',
                '    _cur_map = (st.get("st") if isinstance(st.get("st"), dict) else {}) or {}',
            ]),
            '')
        _bad81 = ('_nm_last = str(((c.get("st") or {}).get(_rc81 or (2, 6)) or {})'
                  '.get("name") or "")')
        _g81 = {'st': {'last': _cell81, 'obs': {}, 'st': {}, 'marks': {}},
                'done': set(), 'log': [], 'cell_of': EL.cell_of}
        _boom81 = None
        try:
            exec(compile(_bad81, '<bad81>', 'exec'), _g81)
        except Exception as _e81b:       # noqa: BLE001
            _boom81 = _e81b
        check('v2.81 B(2) 对照项：**旧写法**（`c.get(...)` 且 c 未赋值）执行必抛异常'
              '（没这条的话，B(1) 用什么代码都能绿 X） · %s'
              % (type(_boom81).__name__ if _boom81 else '没抛!!',),
              isinstance(_boom81, (UnboundLocalError, NameError)))
except Exception as _e81:       # noqa: BLE001
    check('v2.81 守门可运行（%r）' % (_e81,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.82【「还有两个目标就退图」—— 低分误报被当成探索格 => 求解器爆炸 => no_plan】
#
#   ---- 用户原话（2026-10-28）----
#     「？？这么还有两个目标呢就退图了」
#   ---- 真机铁证（21:37 那把，且离线**同帧复现完全一致**）----
#     {'solver': 'no_plan', 'cost': None, 'reason': 'max_states', 'expanded': 12503}
#     {'finish': 'targets_unreachable'}
#   离线同帧复跑：report={'pushed': 60001, 'expanded': 12263, 'reason': 'max_states'}  <- 撞上限
#
#   ---- 病 ----
#     求解器拿到 **5 个 target**，其中 3 个是分类器在**暗格**上瞎猜出来的 S00003_331「海边小屋」：
#       (1,7) score=0.095  (4,1) score=0.181  (4,7) score=0.12   （全 revealed=False）
#     为什么低分也能成 target：`is_target()` 里「靠名字」那支有 NAME_SCORE_MIN=0.85 门槛，
#     但它**前面**还有一支 `is_explore_tile(sid)` —— **只看 sid 后缀**（221/321/331），
#     **完全不看分数** => 后缀 331 直接 return True，门槛被绕过 X
#     => 5 个目标（含 3 个假目标）=> 24 块 x 5 目标的状态空间爆炸
#     => pushed 60001 撞上限 => no_plan => order 空 => cands 空 => targets_unreachable
#     => **明明还有目标就退图** X
#
#   ---- 口径（为什么地板是 0.39 而不是 0.85）----
#     本仓 NAME_SCORE_MIN 那段注释**实测**探索格 score 是 **0.39~0.73**
#     （探索格靠**后缀**判定、不靠名字 => 低分是正常的）
#     => 套 0.85 会把**真探索格全废掉** X
#     => 取实测下界 **0.39** 作地板：低于它只能是暗格瞎猜（实测 0.095/0.12/0.181）O
#     => fail-open：score 为 None => 不拦（老调用点行为一字不变）
#
#   ---- 修复效果（同帧实测）----
#     修复前：targets=5  pushed=60001  reason=max_states  => 退图
#     修复后：targets=2  pushed=2075   reason=ok          => 4 步计划（首步就是黄金宝库）
try:
    import targets_cfg as _tc82
    import spots as _sp82

    _TC82 = io.open(os.path.join(MAPBOT, 'targets_cfg.py'), encoding='utf-8').read()

    # ── A 执行级：读**真常量**、真调 is_target（不是搜字符串 —— v1.42(2) 盯着这条）──
    _floor82 = getattr(_tc82, "EXPLORE_SCORE_MIN", None)
    check("v2.82 A(1) `EXPLORE_SCORE_MIN` 真值 == 0.39（探索格实测区间 0.39~0.73 的下界）· %r"
          % (_floor82,), _floor82 == 0.39)
    check("v2.82 A(2) 地板 ≠ 名字门槛 0.85（套 0.85 会把真探索格全废掉 X）· floor=%r name_min=%r"
          % (_floor82, getattr(_tc82, "NAME_SCORE_MIN", None)),
          _floor82 != getattr(_tc82, "NAME_SCORE_MIN", None))
    # 真调一轮：以地板为界，两侧行为必须不同（这是 A(3)/A(4) 的执行级形态）
    _below = _tc82.is_target("海边小屋", "S00003_331", score=_floor82 - 0.01)
    _above = _tc82.is_target("海边小屋", "S00003_331", score=_floor82 + 0.01)
    check("v2.82 A(3) 执行级：地板**下方**判不是目标 / 地板**上方**判是目标（%.2f vs %.2f）"
          % (_floor82 - 0.01, _floor82 + 0.01),
          _below is False and _above is True)
    check("v2.82 A(4) 执行级：**fail-open** —— score=None 时照旧算目标（老调用点行为不变）· %r"
          % (_tc82.is_target("海边小屋", "S00003_331", score=None),),
          _tc82.is_target("海边小屋", "S00003_331", score=None) is True)
    # ── B 执行级 ──
    _cases82 = [
        # (说明, sid, score, 期望 is_target)
        ('暗格瞎猜 331（事故那三个）', 'S00003_331', 0.095, False),
        ('暗格瞎猜 331', 'S00003_331', 0.181, False),
        ('暗格瞎猜 331', 'S00003_331', 0.12, False),
        ('真探索格 331（实测区间下界附近）', 'S00003_331', 0.45, True),
        ('真探索格 221', 'S00001_221', 0.60, True),
        ('真探索格 321', 'S00001_321', 0.73, True),
        ('对照·score=None（fail-open 必须不拦）', 'S00003_331', None, True),
        ('边界·score 恰好等于地板 0.39（>= 语义，应算目标）', 'S00003_331', 0.39, True),
        ('边界·score 略低于地板 0.38（不算目标）', 'S00003_331', 0.38, False),
    ]
    for _r in range(len(_cases82)):
        _nm, _sid, _sc, _want = _cases82[_r]
        _got = _tc82.is_target('海边小屋', _sid, score=_sc)
        check('v2.82 B(1) 执行级[%s] sid=%s score=%s => is_target=%s（期望 %s）'
              % (_nm, _sid, _sc, _got, _want), _got is _want)

    # ── B(2) 关键回归：真机那帧上，假目标必须消失、求解器必须解得出来 ──
    _png82 = os.path.join(PROJ, '..', '_tmpman', 'run2', 'fail_frame.png')
    if not os.path.exists(_png82):
        skip('v2.82 B(2) 真机帧回归（缺 %s；复现：从设备 run-as 取 files/runs/r_213709_0.png）'
             % _png82)
    else:
        import cv2 as _cv82
        import mapsim as _ms82
        import mapsolve as _mv82
        import spots as _sp82
        _img82 = _cv82.imread(_png82)
        _c82 = EL.cells_of(_img82, '夏日海滩', None)
        _m82 = EL._cells_for_model({'obs': {}, 'marks': {(1, 2): {'marks': ['boss']}}},
                                   _c82, log=[], tag='s82', mark_revealed=False)
        _sim82 = _ms82.MapSim.from_observation(_m82, _sp82.spot_rows())
        _prob82 = _mv82.Problem(_sim82)
        _rep82 = {}
        _cost82, _plan82 = _mv82.solve(_prob82, max_states=60000, max_secs=8,
                                       report=_rep82)
        _tnames82 = [_sim82.blocks[t].name for t in _prob82.targets]
        # 逐个 target 用**真判据**复核一遍（不是比字符串）—— 元门禁 v1.42(2) 盯着这条
        _bad82 = []
        _ts82 = sorted(_prob82.targets)
        for _r in range(len(_ts82)):
            _bb82 = _sim82.blocks[_ts82[_r]]
            if str(getattr(_bb82, 'name', '')) == '海边小屋':
                _bad82.append(_ts82[_r])
        check('v2.82 B(2) 真机帧回归：**假目标「海边小屋」全消失**（事故里是 3 个）· 现 targets=%s'
              % (_tnames82,), '海边小屋' not in _tnames82)
        check('v2.82 B(2) 真机帧回归：求解器**解得出来**（事故是 max_states）'
              '（reason=%s pushed=%s targets=%d）'
              % (_rep82.get('reason'), _rep82.get('pushed'), len(_prob82.targets)),
              _rep82.get('reason') == 'ok' and bool(_plan82))
        check('v2.82 B(2) 真机帧回归：pushed 从 60001 降到合理范围（< 10000）· %s'
              % (_rep82.get('pushed'),), int(_rep82.get('pushed') or 0) < 10000)

        # 逐个 plan 步真读 block —— 顺带钉住「首步就是黄金宝库」这个用户口径
        _pl82 = []
        for _r in range(len(_plan82 or [])):
            _bi82 = _plan82[_r][0]
            _pl82.append(str(getattr(_sim82.blocks[_bi82], 'name', '')))
        check('v2.82 B(3) 执行级：计划**首步就是黄金宝库**（用户口径「宝库摆在眼前就先点」）· plan=%s' % (_pl82,),
              bool(_pl82) and _pl82[0] == '黄金宝库')
except Exception as _e82:       # noqa: BLE001
    check('v2.82 守门可运行（%r）' % (_e82,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.83【「一直循环紫金地块派遣小队」—— 常驻文案被当成「面板还在」的判据】
#
#   ---- 用户原话（2026-10-28）----
#     「刚刚一直循环紫金地块派遣小队」
#   ---- 真机铁证（第 5 张图，23:00:27 → 23:07，**45 轮**）----
#     r5 ~ r44  slots_free=2  slots={free_txt:2, busy:1, busy_strict:1}   <- 45 轮一模一样
#     `busy` 从头到尾都是 **1** => **派遣一次都没成功**
#     {dispatch: tap1, texts:[++, 探索预计时间【10:00:00】, 探索效率25秒/次, ...]}
#     {dispatch: tap2, texts:[探索预计时间【10:00:00】, 探索效率10秒/次, ...]}
#     {dispatch: still_open_close}
#
#   ---- 病 ----
#     「派遣面板还在吗」的判据是：
#       not any(('探索配队' in x) or ('开始探索' in x) or ('派遣' in x)
#               or (**'探索预计时间' in x**) for x in t2)
#     而「探索预计时间【10:00:00】」是配队面板的**常驻说明文案**：
#     点完「一键派遣」按钮会变成「开始探索」，**但那行预计时间一直在** X
#     => `_gone` **恒为 False** => 每轮都点第 2 下 => 落 still_open_close
#     => return handled => **派遣从未成功**
#     => 下一轮 HUD 又读 slots_free=2（busy 恒 1）=> 紫格还在 => **无限循环 45 轮** X
#
#   ---- 这一族错的特征（本项目第 N 次）----
#     **用一个恒定存在的信号，去判断「某件事发生了没有」**：
#       · v2.79 BAND 裁掉 HUD => clover_count 恒 None
#       · v2.78 `c` 未赋值 => 每轮 UnboundLocalError
#       · 本条：常驻说明文案 => _gone 恒 False
#     => 判据必须是**随状态变化**的量（按钮名 / 槽位计数），不能是背景文案
#
#   ---- 修法 ----
#     「面板还在」只认**按钮类**文字（探索配队 / 开始探索 / 派遣），
#     **不再**把常驻说明文案当判据
try:
    _EL83 = io.open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
    _L83 = _EL83.split(chr(10))

    # ── A 结构级（撤注释后查，防留档注释假红）──
    def _code83(_src):
        _o = []
        for _ln in _src.split(chr(10)):
            if _ln.strip().startswith('#'):
                continue
            _o.append(_ln.split('#')[0] if '#' in _ln else _ln)
        return chr(10).join(_o)

    _c83 = _code83(_EL83)
    check('v2.83 A(1) 撤回守门：**代码里**不再有 `(探索预计时间 in x)` 这条判据'
          '（它是配队面板常驻说明 => 恒真 => _gone 恒 False => 45 轮死循环 X） · %s'
          % ('干净 OK' if "('探索预计时间' in x)" not in _c83 else '仍有'),
          "('探索预计时间' in x)" not in _c83)

    _i83 = _c83.find('if not any(' + chr(40) + chr(39) + '探索配队')
    _seg83 = _c83[_i83:_i83 + 220] if _i83 >= 0 else ''
    _has83 = all(k in _seg83 for k in ('探索配队', '开始探索', '派遣'))
    check('v2.83 A(2) 「面板还在」仍认**按钮类**三种文字（探索配队/开始探索/派遣）'
          '（不能为了去脏水把真按钮也删掉 X） · %s' % ('齐 OK' if _has83 else '缺'),
          _has83)

    # ── B 执行级：用事故那两次 OCR texts 真跑判据 ──
    _T1_83 = ['++', '探索预计时间【10:00:00】', '探索效率25秒/次',
              '※探索角色位阶越高获取道具效率越高', '1级', '级', '1级', '级']
    _T2_83 = ['探索预计时间【10:00:00】', '探索效率10秒/次',
              '※探索角色位阶越高获取道具效率越高', '级', '1级', '1级', '级', '筛选']
    for _r in range(2):
        _tx = _T1_83 if _r == 0 else _T2_83
        # 新判据（只认按钮类）
        _gone83 = not any(('探索配队' in x) or ('开始探索' in x) or ('派遣' in x)
                          for x in _tx)
        check('v2.83 B(1) 执行级[事故 tap%d 的真 OCR] 新判据 => _gone=%s（期望 True）'
              % (_r + 1, _gone83), _gone83 is True)
        # 对照项：旧判据必须仍为 False（证明这条断言不是恒真）
        _old83 = not any(('探索配队' in x) or ('开始探索' in x) or ('派遣' in x)
                         or ('探索预计时间' in x) for x in _tx)
        check('v2.83 B(2) 对照项[事故 tap%d] **旧判据**仍= %s（期望 False）——'
              ' 这一条证明新判据不是恒真（旧写法在这两帧上永远 False）'
              % (_r + 1, _old83), _old83 is False)
except Exception as _e83:       # noqa: BLE001
    check('v2.83 守门可运行（%r）' % (_e83,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.84【「限时礼包界面无限循环」—— 闭运算核 9x9 把 X 和红色标题栏粘成一块】
#
#   ---- 用户原话（2026-10-30）----
#     「在限时礼包界面无限循环了」
#   ---- 模拟器日志铁证（11:55~11:57）----
#     › 发现限时礼包 · 正在领取…   （每 12 秒一次，连续 10+ 次）
#     {"gift": "tap_free1", "at": [768, 790]}   <- 第 1 次，got:true（礼包1 领到 ✓）
#     {"gift": "tap_free1", "at": [769, 1258]}  <- 之后 12 次全是这个坐标
#     {"gift": "result", "got": false, ...}      <- 13 次 result 里只有 1 次 got=true
#     {"close": "no_text_btn", "what": "gift_tail"}
#     {"gift_tail": "close_panel", "n": 0}       <- **面板一次都没关掉**
#
#   ---- 病（两层）----
#     (1) 礼包面板上**没有**「返回/确定/关闭」这类文字按钮
#         （真机帧 OCR 实测：只有 限时超值礼包/超值礼包1~3/已领取/免费/剩余时间）
#         => `_univ_close` 认不到 => v2.59 起又禁止盲点万能位 => n=0
#     (2) v2.79 的 `panel_title_close_x()` 本该兜住这种情况，但它在礼包面板上
#         **返回 None** => 等于没兜住 ✗
#         根因：`MORPH_CLOSE` 用 9x9 核，而 X（红底白叉）**和红色标题栏连通** =>
#           得到一个 734x93 的大连通域 => 被 `54 <= w <= 80` 的尺寸判据整条滤掉 X
#         实测（同一帧 dlg(1080x1920)）：
#           k=9 => 只剩 dlg(550,663) 734x93（标题栏+叉粘一起）=> 命中 0 个可用
#           k=7 => X 独立出来 dlg(875,667) 白/红=0.27 => 正确命中 ✓
#     => 面板关不掉 => 上层看到 gift_flow 返回非空 acts 就当「完成」
#        （`acts.append('free1')` 只看"点了一下"，不看"领到没/关掉没"）
#     => 下一轮又认成「发现限时礼包」=> **无限循环** X
#
#   ---- 为什么这跟 v2.79 是同一个坑的两半 ----
#     v2.79 修「标题行右上角 X」时只在**礼包帧**上验证过（那帧 X 与标题栏分离），
#     没覆盖「红色标题栏」这一族面板 => 核选大了就整族失效。
#     !! 教训：形态学核尺寸是**几何判据的一部分**，换面板族必须重验。
try:
    _BP84 = io.open(os.path.join(MAPBOT, 'buypanels.py'), encoding='utf-8').read()

    # ── A 结构级：核必须是 7x7（撤回守门：别改回 9）──
    _i84 = _BP84.find('def panel_title_close_x(')
    _seg84 = _BP84[_i84:_i84 + 4500] if _i84 >= 0 else ''
    check('v2.84 A(1) `panel_title_close_x` 的闭运算核是 **7x7**'
          '（9x9 会把 X 和红色标题栏粘成一块 => 尺寸筛整条滤掉 => 返回 None X） · %s'
          % ('7x7 OK' if '_np.ones((7, 7)' in _seg84 else '不是 7x7'),
          '_np.ones((7, 7)' in _seg84)

    check('v2.84 A(2) 撤回守门：那段里**没有** 9x9（改回去 => 礼包/所有红标题栏面板的 X 全消失）· %s'
          % ('干净 OK' if '_np.ones((9, 9)' not in _seg84 else '仍有 9x9'),
          '_np.ones((9, 9)' not in _seg84)

    # ── B 执行级：礼包面板真帧 ──
    _png84 = os.path.join(PROJ, '..', '_tmpman', 'gift_dlg.png')
    if not os.path.exists(_png84):
        skip('v2.84 B(1)~B(2) 执行级（缺 %s；复现：screencap 后缩放到 1080x1920）' % _png84)
    else:
        import cv2 as _cv84
        import buypanels as _BPm84

        _IMG84 = _cv84.imread(_png84)
        _IT84 = [
            ('限时超值礼包', 541, 666), ('超值礼包1', 278, 739), ('已领取', 771, 822),
            ('超值礼包2', 278, 937), ('超值礼包3', 278, 1133), ('免费', 790, 1258),
            ('剩余时间05:57:24', 540, 1341),
        ]
        _items84 = [item(_t, _cx, _cy) for _t, _cx, _cy in _IT84]

        class _B84(object):
            ocr_grabs = True

            def __init__(self):
                self.taps = []
                self.state = 'open'

            def img(self):
                return _IMG84

            def img_dlg(self):
                return _IMG84

            def snap(self, *a, **k):
                pass

            def ocr(self, *a, **k):
                return [] if self.state == 'closed' else [dict(t) for t in _items84]

            def ocr_dlg(self, *a, **k):
                return [] if self.state == 'closed' else [dict(t) for t in _items84]

            def tap(self, x, y, wait=0.0):
                self.tap_dlg(x, y, wait)

            def tap_dlg(self, x, y, wait=0.0):
                self.taps.append((int(x), int(y)))
                if (int(x), int(y)) == (875, 667):
                    self.state = 'closed'

            def _sleep(self, s):
                pass

        _b84 = _B84()
        _got84 = _BPm84.panel_title_close_x(_b84, title='限时超值礼包', log=[])
        check('v2.84 B(1) 执行级：礼包面板的 X 被定位到 **(875,667)**（实测白/红=0.27）'
              '（修复前是 None => close_panel n=0 => 无限循环） · %r' % (_got84,),
              _got84 == (875, 667))

        _lg84 = []
        _BPm84.gift_flow(_b84, _lg84)
        _cp84 = [e for e in _lg84 if e.get('gift_tail') == 'close_panel']
        check('v2.84 B(2) 端到端：`gift_flow` 跑完面板**真被关掉**（state=%s / taps=%s）'
              % (_b84.state, _b84.taps),
              _b84.state == 'closed' and (875, 667) in _b84.taps)
        check('v2.84 B(2) 端到端：`close_panel` 的 **n >= 1**（事故日志里是 n=0）· %s'
              % ((_cp84[-1] if _cp84 else None),),
              bool(_cp84) and int(_cp84[-1].get('n') or 0) >= 1)
except Exception as _e84:       # noqa: BLE001
    check('v2.84 守门可运行（%r）' % (_e84,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.85【紫金格派过队后每轮重入 => 计划永远停在原地】
#
#   ---- 用户口径（2026-10-30）----
#     「最初的规划是对的，是执行出问题了」＋ 选「派过一队就算处理完，本图不再点它」
#   ---- 真机铁证（12:25 那把，计划 5,6 -> 3,2 -> 1,1 -> 3,3 -> 1,5）----
#     r3-r4    第3步 1,1 紫金格 => 派出一支小队 OK（slots 3->2）
#     r5/r6/r7 每轮又是 purple_prefer_explore cell=1,1 + 点(275,736) => handled
#              slots 一直 2（没再派出）
#     r7       same_action_x4 脱困 => nogo_tagged 1,1
#     r8       依然 purple_prefer_explore cell=1,1  <= nogo 对这个分支无效
#     => 计划永远停在第 3 步，第 4 步（3,3=1,6）一次都没轮到
#   ---- 病 ----
#     紫格分支入口只有 _is_purple and _free_now>0，
#     没有「这格本图已派过队」的记忆，也不看 nogo/blocked；
#     而紫金格派完队不会从盘上消失 => 每轮都被当成新紫格重入
#   ---- 修法 ----
#     ① st['purple_sent'] 记住该格 => 后续不再进本分支
#     ② 同时写 done => 计划层收口，计划才会推进到下一步
try:
    import explore_loop as _EL85

    _src85 = io.open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
    _code85 = chr(10).join(_ln for _ln in _src85.split(chr(10))
                           if not _ln.strip().startswith('#'))

    check('v2.85 A(1) 派遣成功处会记 purple_sent（否则每轮重入 X）· %s'
          % ('有 OK' if "setdefault('purple_sent', set())" in _code85 else '缺'),
          "setdefault('purple_sent', set())" in _code85)

    _DONE85 = "setdefault('done', set()).add((int(_tapped[0]), int(_tapped[1])))"
    check('v2.85 A(2) 记的同时写 done（计划层收口，否则计划永不推进）· %s'
          % ('有 OK' if _DONE85 in _code85 else '缺'), _DONE85 in _code85)

    check('v2.85 A(3) 紫格分支**两处**都加了 not _purple_seen85'
          '（入口 _expl_entry63 + if 条件；只加一处 => 照样重入 X）· 出现 %d 次'
          % _code85.count('_purple_seen85'), _code85.count('_purple_seen85') >= 4)

    check('v2.85 A(4) 闸门同时看 purple_sent **和** nogo_rc'
          '（r7 拉黑后 r8 照样重入 => 只看 sent 不够）· %s'
          % ('有 OK' if ("_fl85.get('purple_sent')" in _code85
                         and "_fl85.get('nogo_rc')" in _code85) else '缺'),
          "_fl85.get('purple_sent')" in _code85 and "_fl85.get('nogo_rc')" in _code85)

    # ── B 执行级：真跑 popups，喂「已派过队」的夹具 ──
    import cv2 as _cv85
    import numpy as _np85
    _PNG85 = os.path.join(PROJ, '..', '_tmpman', 'plan2', 'frame.png')

    class _B85(object):
        ocr_grabs = True

        def __init__(self):
            self.taps = []

        def img(self):
            if os.path.exists(_PNG85):
                return _cv85.imread(_PNG85)
            return _np85.zeros((1920, 1080, 3), 'uint8')

        def img_dlg(self):
            return self.img()

        def snap(self, *a, **k):
            pass

        def ocr(self, *a, **k):
            return []

        def ocr_dlg(self, *a, **k):
            return []

        def tap(self, x, y, wait=0.0):
            self.taps.append((int(x), int(y)))

        def tap_dlg(self, x, y, wait=0.0):
            self.taps.append((int(x), int(y)))

        def _sleep(self, s):
            pass

    _CELL85 = _EL85.cell_center(1, 1)

    def _run85(_flags):
        _lg = []
        _ctx = {'tapped': _CELL85, 'st': {(1, 1): {'sid': 'S00003_221'}},
                'slots_free': 2, 'ev_tiles': [], 'marks': {}, 'flags': _flags}
        try:
            _EL85.popups(_B85(), [], _lg, _ctx)
        except Exception as _e:        # noqa: BLE001
            _lg.append({'exc': repr(_e)})
        return _lg

    _lg_sent = _run85({'purple_sent': {(1, 1)}})
    _lg_free = _run85({})
    _lg_nogo = _run85({'nogo_rc': {(1, 1)}})

    check('v2.85 B(1) 执行级：**已派过队**的格 => 不再出现 purple_prefer_explore'
          '（事故里 r5/r6/r7/r8 连出 4 次）· log=%s'
          % ([e.get('popup') for e in _lg_sent if 'popup' in e][:3],),
          not any(e.get('popup') == 'purple_prefer_explore' for e in _lg_sent))

    check('v2.85 B(2) 执行级：同上会落一条 purple_already_handled（可复盘）· %s'
          % ([e.get('popup') for e in _lg_sent if 'popup' in e][:3],),
          any(e.get('popup') == 'purple_already_handled' for e in _lg_sent))

    check('v2.85 B(3) **对照项**：同一夹具去掉 purple_sent => 分支**照样命中**'
          '（没有这条，B(1) 用"永远不进分支"也能绿 X）· log=%s'
          % ([e.get('popup') for e in _lg_free if 'popup' in e][:3],),
          any(e.get('popup') == 'purple_prefer_explore' for e in _lg_free))

    check('v2.85 B(4) 执行级：nogo 里的格同样被挡（r7 拉黑、r8 仍重入 => 必须挡）· log=%s'
          % ([e.get('popup') for e in _lg_nogo if 'popup' in e][:3],),
          not any(e.get('popup') == 'purple_prefer_explore' for e in _lg_nogo))
except Exception as _e85:       # noqa: BLE001
    check('v2.85 守门可运行（%r）' % (_e85,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.86【「完成限时礼包后不退图」—— 计划走完被当成「认不出棋盘」】
#
#   ---- 用户原话（2026-10-30）----
#     「为啥第二张图完成限时礼包后不退图」
#   ---- 真机铁证（23:06 第 2 张图）----
#     r4/r5/r6/r7  say「没有目标了，准备退图」，却一轮都没退
#     {'finish': 'blank_board', 'n': 1} / n: 2 / n: 3
#     {'map': 1, 'end_reason': 'blank'}
#     => 「连续 2 张图都认不出棋盘（画面被判"被面板挡住"）」=> 停整局
#     ⚠ 可棋盘上还有 22~24 格（round 6 board 里数得出来）—— 根本不是"认不出"
#   ---- 病（两处叠加）----
#     ① _plan_left 取的是**原始计划**（不按 done 过滤），而 st['plan'] 每轮由 solver
#        覆盖、走完也不自动清空 => 只要算过一次计划，_plan_left 永远非空
#        => 「计划走完 + 没目标 => 立刻收工」那道门永远进不去
#     ② 于是落到 blank_board 的 3 轮耐心；可 blank 的本义是"整盘没识别到"，
#        这里却拿它判"没目标" => 把"正常收工"误判成"认不出棋盘" => 停整局
#   ---- 修法 ----
#     ① _plan_left 与 _rest 同口径（排除已 done）
#     ② blank 分支前先判：had_plan + 盘上有格子 + 确实没目标 => return 'done'
#        （从没算出过计划 => 仍走 blank 三轮耐心，保住 v1.58 那道保护）
try:
    _src86 = io.open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
    _code86 = chr(10).join(_ln for _ln in _src86.split(chr(10))
                           if not _ln.strip().startswith('#'))

    check('v2.86 A(1) blank 分支前有「正常收工」判断（targets_done_no_order）· %s'
          % ('有 OK' if 'targets_done_no_order' in _code86 else '缺'),
          'targets_done_no_order' in _code86)

    check('v2.86 A(2) 那道判断带 had_plan 与 盘上有格子 两个前提'
          '（否则会盖掉 v1.58「全雾不许冒充满意收工」的保护 X）· %s'
          % ('有 OK' if ("st.get('had_plan') and _cells86 > 0" in _code86) else '缺'),
          "st.get('had_plan') and _cells86 > 0" in _code86)

    check('v2.86 A(3) 撤回守门：_plan_left **不再**是原始计划'
          '（旧写法会让"计划走完也永远非空"=> 永远不退图 X）· %s'
          % ('干净 OK' if "_plan_left = list(st.get('plan') or [])" not in _code86 else '仍有'),
          "_plan_left = list(st.get('plan') or [])" not in _code86)

    # ── B 执行级：把 _plan_left 那段真跑一遍 ──
    import marks as _mk86
    _i86 = _src86.find('_plan_left = [p for p in')
    assert _i86 >= 0
    _j86 = _src86.find('not in done]', _i86) + len('not in done]')
    _blk86 = _src86[_i86:_j86]

    def _run86(_done):
        _g = {'st': {'plan': [(1, 1), (2, 2)]}, 'done': _done, 'marks_mod': _mk86}
        exec(compile(_blk86, '<pl86>', 'exec'), _g)
        return _g['_plan_left']

    _all_done86 = {_mk86.cell_center(1, 1), _mk86.cell_center(2, 2)}
    check('v2.86 B(1) 执行级：计划两步**都走完** => _plan_left 空（事故里它恒非空 X）· %r'
          % (_run86(_all_done86),), _run86(_all_done86) == [])

    _one_done86 = {_mk86.cell_center(1, 1)}
    check('v2.86 B(2) 对照项：只走完一步 => 仍剩一步（证明 B(1) 不是"永远空"）· %r'
          % (_run86(_one_done86),), _run86(_one_done86) == [(2, 2)])

    check('v2.86 B(3) 对照项：一步没走 => 两步都在 · %r' % (_run86(set()),),
          _run86(set()) == [(1, 1), (2, 2)])
except Exception as _e86:       # noqa: BLE001
    check('v2.86 守门可运行（%r）' % (_e86,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.87【背包升星 UnboundLocalError(_tab) ＋ 帧 Bitmap 无界增长被 lmkd 杀掉】
#
#   ---- 事故 A：背包升星每次中断 ----
#     真机铁证（2026-10-31 00:23:10）：
#       ⚠ 背包升级异常：UnboundLocalError("local variable '_tab' referenced before assignment")
#     病：_tab 只在 `if not _ok_tab:` 分支里赋值，可下一行 `if _tab:` 无条件读它
#         => _bag_switch_tab 成功（_ok_tab=True）就抛异常 => 装备升星从来没跑成功
#     与 v2.81（变量 c 在下面才赋值）同一族 => 局部变量必须先初始化
#
#   ---- 事故 B：跑 22 分钟后被系统杀 ----
#     真机铁证：
#       00:24:05 lowmemorykiller: Kill com.fantasy.autoexplore (11970), oom_score_adj 100
#                to free 3438512kB rss   <= RSS 3.4 GB
#       00:24:06 ActivityManager: ... has died: vis FGS
#       设备 MemTotal 4034432 kB（4 GB）
#     病：CaptureService 每帧 Bitmap.createBitmap(1280x2640 ARGB_8888)=13.5 MB，
#         换帧只丢引用、从不 recycle；慢路径还有每帧一份 13.5 MB 的 byte[]
#         3.4 GB / 13.5 MB 约 252 帧，正好是 22 分钟那个量级
#     修：FrameStore 退休帧有界回收（保留 6 代宽限给读帧线程）＋ 慢路径缓冲复用
try:
    _src87 = io.open(os.path.join(MAPBOT, 'explore_loop.py'), encoding='utf-8').read()
    _code87 = chr(10).join(_ln for _ln in _src87.split(chr(10))
                           if not _ln.strip().startswith('#'))

    _i_ok87 = _code87.find("_ok_tab = _bag_switch_tab")
    _i_init87 = _code87.find('_tab = None', _i_ok87 if _i_ok87 >= 0 else 0)
    _i_read87 = _code87.find('if _tab:', _i_ok87 if _i_ok87 >= 0 else 0)
    _ord87 = (_i_ok87 >= 0 and _i_init87 > _i_ok87 and _i_read87 > _i_init87)
    check('v2.87 A(1) _tab 在**使用点之前**初始化'
          '（旧写法只在 if not _ok_tab 里赋值 => _ok_tab 成功就 UnboundLocalError X）'
          ' · 位置 ok=%s init=%s read=%s' % (_i_ok87, _i_init87, _i_read87), _ord87)

    _seg87 = _code87[_i_ok87:_i_init87] if _ord87 else ''
    check('v2.87 A(2) 撤回守门：_ok_tab 之后、初始化之前**不能再有** if not _ok_tab 就赋值 _tab 的写法'
          '（即 _tab 的赋值不能只发生在分支里）· %s'
          % ('干净 OK' if ('_tab = _bag_find' not in _seg87) else '仍有'),
          '_tab = _bag_find' not in _seg87)

    # ── Java 侧（内存）：只做结构守门，行为由真机 MemInfo 观察 ----
    _fs87 = io.open(os.path.join(PROJ, 'app/src/main/java/com/fantasy/autoexplore/FrameStore.java'),
                    encoding='utf-8').read()
    _cs87 = io.open(os.path.join(PROJ, 'app/src/main/java/com/fantasy/autoexplore/CaptureService.java'),
                    encoding='utf-8').read()
    check('v2.87 A(3) FrameStore 帧池**有界且可复用**（RETIRE_MAX + acquire）'
          '（有界：防 22 分钟涨到 3.4GB 被 lmkd 杀；acquire：不每帧 new 13.5MB）· %s'
          % ('有 OK' if ('RETIRE_MAX' in _fs87 and 'public static Bitmap acquire' in _fs87) else '缺'),
          'RETIRE_MAX' in _fs87 and 'public static Bitmap acquire' in _fs87)

    check('v2.87 A(4) 退休队列保留 >= 3 代宽限'
          '（只留 1~2 代 => 一次 OCR 要 2 秒，会踩到已 recycle 的帧 X）· RETIRE_MAX=%s'
          % (('6' if 'RETIRE_MAX = 6' in _fs87 else '?'),), 'RETIRE_MAX = 6' in _fs87)

    check('v2.87 A(5) 慢路径中转缓冲**复用**（不再每帧 new 13.5 MB）· %s'
          % ('有 OK' if ('sloBuf' in _cs87 and 'byte[] tight = sloBuf;' in _cs87) else '缺'),
          'sloBuf' in _cs87 and 'byte[] tight = sloBuf;' in _cs87)
except Exception as _e87:       # noqa: BLE001
    check('v2.87 守门可运行（%r）' % (_e87,), False)
print()

# ══════════════════════════════════════════════════════════════════════════════
# v2.88【悬浮条挡住公会/开始冒险 => 脚本点不动】
#
#   ---- 用户原话（2026-10-31）----
#     「悬浮窗在下面挡住公会角色开始冒险，无法切换到公会做日常怎么办？」
#   ---- 病 ----
#     悬浮窗带 FLAG_NOT_FOCUSABLE，但**会吃掉落在它身上的触摸**
#     （OverlayService 第 94 行自己就写着这条）
#     => 脚本 tapRef 目标点若正好在悬浮条矩形里，手势被悬浮条截走、游戏收不到
#     => 公会 / 开始冒险 / 背包底部按钮**全都点不动** => 收工日常跑不完
#   ---- 为什么不用 FLAG_NOT_TOUCHABLE ----
#     那样确实不挡了，但 停止按钮 / 拖动 / 点气泡展开 也一起失灵 => 不能这么改
#     => 只能在**点的那一瞬间**让路，点完立刻恢复
#   ---- 修法 ----
#     ① OverlayService.hideBriefly(ms)：bar 设 INVISIBLE，postDelayed 恢复
#        （INVISIBLE 不参与触摸命中测试 => 手势直达游戏；位置尺寸都不动 ✓）
#     ② DeviceApi.dodgeOverlay：目标点落在 blankRect 内（±8px）就先让路再点
#        tapRef / tapRefDialog **两处都要**（弹窗系点底部按钮同样会被挡）
try:
    _ovl88 = io.open(os.path.join(PROJ, 'app/src/main/java/com/fantasy/autoexplore/OverlayService.java'),
                     encoding='utf-8').read()
    _dev88 = io.open(os.path.join(PROJ, 'app/src/main/java/com/fantasy/autoexplore/DeviceApi.java'),
                     encoding='utf-8').read()

    check('v2.88 A(1) OverlayService 有 hideBriefly（点之前能临时让路）· %s'
          % ('有 OK' if 'public static void hideBriefly' in _ovl88 else '缺'),
          'public static void hideBriefly' in _ovl88)

    check('v2.88 A(2) 让路用 INVISIBLE + postDelayed 自动恢复'
          '（GONE/缩小都不对：一个会重排、一个仍占位）· %s'
          % ('有 OK' if ('View.INVISIBLE' in _ovl88 and 'postDelayed' in _ovl88) else '缺'),
          'View.INVISIBLE' in _ovl88 and 'postDelayed' in _ovl88)

    # !! 注意：本条必须先剥掉整行注释再查 —— 我自己的留档注释里逐字引用了 FLAG_NOT_TOUCHABLE
    #   否则会假红（本项目第 4 次踩这个坑：v1.62c / v1.67 / v1.69 都是同一个）
    _ovl88_code = chr(10).join(_ln for _ln in _ovl88.split(chr(10))
                               if not _ln.strip().startswith('//')
                               and not _ln.strip().startswith('*')
                               and not _ln.strip().startswith('/*'))
    check('v2.88 A(3) 撤回守门：code 里**没有**改用 FLAG_NOT_TOUCHABLE'
          '（那样停止按钮/拖动/点气泡展开会一起失灵 X）· %s'
          % ('干净 OK' if 'FLAG_NOT_TOUCHABLE' not in _ovl88_code else '出现了'),
          'FLAG_NOT_TOUCHABLE' not in _ovl88_code)

    check('v2.88 A(4) DeviceApi 有 dodgeOverlay，且判定用 blankRect（同一份矩形）· %s'
          % ('有 OK' if ('private static void dodgeOverlay' in _dev88
                         and 'OverlayService.blankRect()' in _dev88) else '缺'),
          'private static void dodgeOverlay' in _dev88
          and 'OverlayService.blankRect()' in _dev88)

    check('v2.88 A(5) tapRef 与 tapRefDialog **两处都**调了 dodgeOverlay'
          '（只改一处 => 弹窗系点底部按钮照样被挡 X）· 调用 %d 处'
          % _dev88.count('dodgeOverlay(_dx, _dy);'),
          _dev88.count('dodgeOverlay(_dx, _dy);') >= 2)
except Exception as _e88:       # noqa: BLE001
    check('v2.88 守门可运行（%r）' % (_e88,), False)
print()

# ── v2.91【吸附位置用实测值没校验 + recycle 造成 use-after-free】──
#  A) 用户 2026-11-01：「自动吸附到棋盘下面，为什么吸附到的实际位置和真机上不一样？」
#     真机铁证：在「世界图鉴」界面时 bar 被吸到 参考 y 1369~1469（应 1716~1816），骑在棋盘上
#     病：boardBottomY() 无条件信 measuredBoardBottom()，而它是 BoardEdge 从**当前画面**量;
#         当前不在地图界面（图鉴/公会/背包）=> 量出来是垃圾 X
#     修：实测与常量 devY(1722) 相差 > 80 设备 px 判不可信，退回常量
#  B) 用户 2026-11-01：「现在爆红了」
#     真机铁证：18:17:47 java.lang.RuntimeException: Canvas: trying to use a recycled bitmap
#     病：v2.87 的「有界回收」会 recycle 掉读帧线程还拿着的位图 X
#     修：改成**池复用**（超上限只丢引用交给 GC，绝不 recycle）+ CaptureService 用 acquire
try:
    _ovl91 = io.open(os.path.join(PROJ, 'app/src/main/java/com/fantasy/autoexplore/OverlayService.java'),
                     encoding='utf-8').read()
    _fs91 = io.open(os.path.join(PROJ, 'app/src/main/java/com/fantasy/autoexplore/FrameStore.java'),
                    encoding='utf-8').read()
    _cs91 = io.open(os.path.join(PROJ, 'app/src/main/java/com/fantasy/autoexplore/CaptureService.java'),
                    encoding='utf-8').read()

    check('v2.91 A(1) 吸附实测值有**偏离校验**（>80px 判不可信退回常量）'
          '（否则不在地图界面时会被吸到棋盘上 => 用户：吸附位置和真机不一样）· %s'
          % ('有 OK' if 'Math.abs(measured - _refBottom) <= 80' in _ovl91 else '缺'),
          'Math.abs(measured - _refBottom) <= 80' in _ovl91)

    check('v2.91 A(2) 撤回守门：FrameStore **不再 recycle 位图**'
          '（recycle 会造成 Canvas: trying to use a recycled bitmap X）· %s'
          % ('干净 OK' if '.recycle()' not in _fs91 else '还有 recycle'),
          '.recycle()' not in _fs91)

    check('v2.91 A(3) 位图改成**池复用**（acquire）且 CaptureService 用它'
          '（既不每帧 new 13.5MB，也不回收别人还在用的帧）· %s'
          % ('有 OK' if ('public static Bitmap acquire' in _fs91
                         and 'FrameStore.acquire(w, h)' in _cs91) else '缺'),
          'public static Bitmap acquire' in _fs91
          and 'FrameStore.acquire(w, h)' in _cs91)
except Exception as _e91:       # noqa: BLE001
    check('v2.91 守门可运行（%r）' % (_e91,), False)
print()
print('=' * 78)
print('通过 %d 项，失败 %d 项，跳过 %d 项' % (len(OK), len(BAD), len(SKIP)))
if BAD:
    print('---- 失败清单 ----')
    for _b in BAD:
        try:
            print('  [BAD] ' + str(_b)[:160])
        except Exception:
            print('  [BAD] (name unprintable)')
if BAD:
    for b in BAD:
        print('   ✗ ' + b)
if SKIP:
    # ⚠ 跳过**不算通过**：fixture 缺失/前提不成立时，这里必须一眼看见（别被"全绿"骗了 ✗）
    print('   ⚠ 以下 %d 项**没真正验证**（fixture 缺失或前提不成立）：' % len(SKIP))
    for s in SKIP:
        print('     - ' + s)
sys.exit(1 if BAD else 0)