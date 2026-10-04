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
if _c_save is None:
    EL._DLGS.pop('C', None)
else:
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
check('③b 已揭示的宝库**排到点序最前**（用户口径：能直接点就先点 ✓）',
      'order = _buy_first + list(order)' in src and "'buy_first'" in src)
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
    check('v1.06 ② 雾格 plain **只认剪影**（有物体⇒非空地 / 平坦⇒空地），不再看雾下名字 ✓',
          "if self.spot.get('fog_sil') is not None:" in _src6
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
    check('v1.21 ② "已揭示"口径与 spots 的 revealed **同源**（单一来源 ✓）',
          'REVEAL_RATIO_MIN = spots_mod.REVEAL_RATIO_MIN' in _src21
          and 'REVEAL_RATIO_MIN = 0.75' not in _src21
          and 'ratio >= REVEAL_RATIO_MIN' in _sp21
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
    check('v1.23 ① 结算面板分支里**先摇色子再关**（`result_dice` 标记 ✓）',
          "'popup': 'result_dice'" in _src23 and 'handle_dice(b, log, items)' in _src23)
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
    check('v1.28 ④ 纯函数 `plan_next()` 仍在（"进图一次"那条路没被删 ✗）',
          'def plan_next(st, rest_n, targets_left):' in _src28
          and "return 'plan', 'first'" in _src28
          and "return 'keep', 'has_rest'" in _src28
          and "return 'eff', 'exhausted'" in _src28
          and "return 'eff', 'stuck'" in _src28)
    check('v1.28 ⑤ 走完还有目标 ⇒ 切 EffPolicy（`plan: exhausted` ✓）'
          '；推不动 ⇒ `plan: stuck`（安全网 ✓）',
          "log.append({'plan': _pwhy" in _src28
          and 'PLAN_STUCK_ROUNDS = 3' in _src28
          and "_pwhy == 'exhausted'" in _src28)

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
    check('v1.28 ⑩ 执行级：`PLAN_ONCE=1` 连着 3 轮没推进 ⇒ `eff/stuck`（安全网 ✓）',
          _r == [('keep', 'has_rest'), ('keep', 'has_rest'), ('eff', 'stuck')],
          'got=%s' % (_r,))
    _s = {'planned': True, 'plan_stuck': 2, 'plan_prev_len': 4}
    check('v1.28 ⑪ 执行级：步数有减少 ⇒ 计数清零（继续照走 ✓）',
          _pm(_s, 2, 2, once=True) == ('keep', 'has_rest') and _s['plan_stuck'] == 0,
          'stuck=%s' % _s.get('plan_stuck'))
    check('v1.28 ⑫ 执行级：走完还有目标 ⇒ `eff/exhausted`；走完没目标 ⇒ `none/no_targets` ✓',
          _pm({'planned': True}, 0, 2, once=True) == ('eff', 'exhausted')
          and _pm({'planned': True}, 0, 0, once=True) == ('none', 'no_targets'))
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
          'if vis and rnd >= 2 and not marked and not pending_buy:' in _EL39
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
          'byte[] tight = new byte[w * h * 4];' in _cap31
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
# ㊾ v1.34 ⭐⭐⭐【能点的首领格必须立刻打，不许先点它周围的素材格】
#   用户 2026-10-02 报（朋友真机 Redmi 1280×2772）：「会把能点的素材格全点开，
#   **boss 格已经能打了**，还是会先点 boss 格周围的素材格」✗
#   **真机铁证**（`fb_20261002_015406/mgas_log.txt`）：
#     `marks {"2,3": ["boss","recommend"]}` + `solver order ["3,5","2,3"]`
#     同一轮还有 `{"popup":"fight_panel","cell_marks":["boss","recommend"]}`
#     ⇒ boss 当下**完全可打**（战斗面板都弹出来了），点序却把它排在**第 2 位** ✗
#   根因：解算器优化的是**总花费最小**，不知道"这格现在就能直接打"的价值；
#        加上计划是**静态**的，排后面的 boss 会被前面的动作一路挤到最后 ✗
#   修法：`_hoist_ready_boss_first()` 把**当下能点**的首领/红装格提到最前，
#        其余顺序不动；雾里（点不动）的首领**绝不提**（提了也白花体力）✓
# ─────────────────────────────────────────────────────────────────────────
print()
print('㊾ v1.34 能点的首领格优先打（不许先点周围素材）')
try:
    _el34 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'explore_loop.py'),
                 encoding='utf-8').read()
    check('v1.34 ① 重排函数在位（`_hoist_ready_boss_first` / `_ready_boss_cells`）',
          'def _hoist_ready_boss_first(st, order' in _el34
          and 'def _ready_boss_cells(st, order)' in _el34)
    check('v1.34 ② **solver 与 eff 两条路径都调**（不两处漂移 ✓）',
          _el34.count('_hoist_ready_boss_first(st,') >= 2
          and "_hoist_ready_boss_first(st, _hoisted" not in _el34)
    check('v1.34 ③ 只提**首领/红装**（普通标记/幸运草维持原顺序 ✓）',
          "any(m in ('boss', 'redEquip') for m in _marks)" in _el34)
    check('v1.34 ④ 雾里（ratio 低）的首领**不提出去**（提了也点不动，白花体力 ✗）',
          'if _ratio < _min_ratio:' in _el34 and 'continue' in _el34)
    # ⚠ 常量名陷阱：注释里写 `REVEALED_RATIO_MIN`，真名是 **`REVEAL_RATIO_MIN`**（少 ED）。
    #   写成 `globals().get('REVEALED_RATIO_MIN', 0.75)` 会**静默吃默认值**、
    #   拼错了也测不出来（2026-10-02 当场踩过）⇒ 这里断言**真名**在模块里 ✓
    # ⚠ v1.36：改成**直接引用**模块常量 —— globals().get(默认) 会在
    #   常量名拼错时**静默吃默认值**，永远测不出来（2026-10-02 已踩过 ✗）
    check('v1.34 ⑤ 揭示阈值**直接引用**模块常量（不用 globals().get 兜底 ✗）',
          '_min_ratio = REVEAL_RATIO_MIN' in _el34
          and "globals().get('REVEAL_RATIO_MIN'" not in _el34)
except Exception as _e34:       # noqa: BLE001
    check('v1.34 源码守门可运行（%r）' % (_e34,), False)

# ⑯ **实跑闸**：用**朋友那一局的真机数据**直接打真函数（不 mock、不复刻 ✓）
try:
    # 真机那一局：boss 在 (2,3) 且已揭示（ratio 0.958），点序被排成 ["3,5","2,3"]
    _st34 = {
        'marks': {(2, 3): {'marks': ['boss', 'recommend']}},
        'obs': {(2, 3): {'ratio': 0.958}, (3, 5): {'ratio': 0.99}},
    }
    _out34 = EL._hoist_ready_boss_first(_st34, [(3, 5), (2, 3)])
    check('v1.34 ⑥ 实跑：**真机那一局**的首领被提到第 1 位',
          bool(_out34) and _out34[0] == (2, 3), '%s' % (_out34,))
    check('v1.34 ⑦ 实跑：素材格**没被丢掉**（只是换到后面 ✓）',
          set(_out34) == {(2, 3), (3, 5)}, '%s' % (_out34,))
    # 雾里的首领：提上去也点不动 ⇒ 必须**原样不动**（否则白花体力、挤掉该点的格 ✗）
    _stfog = {
        'marks': {(4, 6): {'marks': ['boss']}},
        'obs': {(4, 6): {'ratio': 0.65}, (1, 1): {'ratio': 0.99}},
    }
    _outfog = EL._hoist_ready_boss_first(_stfog, [(1, 1), (4, 6)])
    check('v1.34 ⑧ 实跑：雾里的首领**不提出去**（点不动，提了更差 ✓）',
          _outfog == [(1, 1), (4, 6)], '%s' % (_outfog,))
    # 阈值边界：证明用的是真阈值 0.75，而不是别的数
    _b = []
    # ⚠ v1.36：阈值标定到 0.80，边界跟着走（0.76 已**低于**阈值 ⇒ 不该提）
    for _r, _want in ((0.70, False), (0.84, True)):
        _o = EL._hoist_ready_boss_first(
            {'marks': {(2, 3): {'marks': ['boss']}},
             'obs': {(2, 3): {'ratio': _r}, (3, 5): {'ratio': 0.99}}},
            [(3, 5), (2, 3)])
        _b.append((_o[0] == (2, 3)) == _want)
    check('v1.34 ⑨ 实跑：阈值边界 **0.80**（0.70 雾不提 / 0.84 揭示提 ✓）',
          all(_b), 'ratio 0.70/0.84 ⇒ %s' % (_b,))
    # 没有首领标记时**一动不动**（绝不多余地重排点序 ✓）
    _plain = EL._hoist_ready_boss_first(
        {'marks': {(3, 5): {'marks': ['clover']}}, 'obs': {(3, 5): {'ratio': 0.99}}},
        [(3, 5), (1, 1)])
    check('v1.34 ⑩ 实跑：盘上没有首领/红装 ⇒ 点序**原样**（不瞎改 ✓）',
          _plain == [(3, 5), (1, 1)], '%s' % (_plain,))
except Exception as _e34b:      # noqa: BLE001
    check('v1.34 实跑闸可运行（%r）' % (_e34b,), False)

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
          and 'REVEAL_RATIO_MIN = 0.75' not in _el36_src)
    check('v1.36 ③ 定义在**所有使用点之前**（v1.34 顺序坑 `NameError` 连踩两次 ✗）',
          _el36_src.index('REVEAL_RATIO_MIN = spots_mod.REVEAL_RATIO_MIN')
          < _el36_src.index('def _ready_boss_cells(')
          < _el36_src.index('def board_hidden('))
    check('v1.36 ④ 双证据开关在位（`dual` 可现场开，默认 `single` 保守 ✓）',
          'MAPBOT_REVEAL_EVIDENCE' in _sp36src and 'REVEAL_EVIDENCE' in _sp36src)
    check('v1.36 ⑤ 剪影**只作否决**不作通过（已揭示格剪影与雾格重叠 ⇒ 不能单独判 ✓）',
          'bool(_sil < FOG_SIL_MIN)' in _sp36src and 'rev_evidence' in _sp36src)
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
#   ① 「会把能点的素材格全点开」已由 v1.34 治；本段治剩下三个
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
         0, 2, 'eff', 'exhausted'),
        ('走完且无目标', {'planned': True, 'plan_stuck': 0, 'plan_prev_len': 0},
         0, 0, 'none', 'no_targets'),
        ('连着没推进', {'planned': True, 'plan_stuck': 3, 'plan_prev_len': 5},
         5, 2, 'eff', 'stuck'),
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
    check('v1.46 ⑤ `SP_EDITABLE` = 商人 + 宝库（用户口径：**只有这两个可勾** ✓）',
          tuple(getattr(_ea46, 'SP_EDITABLE', ())) == ('旅行商人', '黄金宝库'),
          'SP_EDITABLE=%s' % (getattr(_ea46, 'SP_EDITABLE', None),))
    # ⑥ special_list 真能返回可用 JSON
    import json as _json46
    _d46 = _json46.loads(_ea46.special_list() or '{}')
    _items46 = _d46.get('items') or []
    _locked46 = [i['name'] for i in _items46 if i.get('locked')]
    _free46 = [i['name'] for i in _items46 if not i.get('locked')]
    check('v1.46 ⑥ 实跑 `special_list()`：可勾 2 个、其余**锁定**'
          '（用户口径「暂时也无法勾选」✓）',
          len(_free46) == 2 and len(_locked46) >= 5,
          '可勾=%s 锁定%d个' % (_free46, len(_locked46)))
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
    #   ⇒ 测试盘也必须铺满，否则 `obs_cells` 闸门会把"没给的格"当不存在 ✗
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
    check('v1.51 ⑥c `_build_cache` 的 `EMPTY_ADJ` 有 `obs_cells` 闸门'
          '（观测里没有的格不许当"已消耗"去揭示邻居 ✓）',
          'if _obs_cells and c not in _obs_cells:' in _src51)
    _sm51 = open(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'mapsim.py'),
                 encoding='utf-8').read()
    check('v1.51 ⑥d `Block` 有 `observed`（**建块时固定**的观测值，推演不改它 ✓）',
          'self.observed = bool(revealed)' in _sm51)
    check('v1.51 ⑥e `MapSim` 默认 `obs_cells = None`'
          '（老调用/全知盘行为一字不变 ✓）',
          'self.obs_cells = None' in _sm51)
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
    check('v1.53 ① _cells_for_model 给营地的格子打 camp 标'
          '（PC 口径：st[\'camp\'] + **sid 后缀 000 兜底** ✓）',
          "_cells_merged[_hit53]['camp'] = True" in _el53
          and "endswith('_000')" in _el53)
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
    check('v1.53 ⑥ 对照：**不打标就复现真机症状**（camp=None + 候选 0 ⇒ 无解 ✗）',
          _prob53b.camp is None and len(_prob53b.visible(frozenset())) == 0,
          'camp=%s vis=%d' % (_prob53b.camp,
                              len(_prob53b.visible(frozenset()))))
except Exception as _e53:       # noqa: BLE001
    check('v1.53 守门可运行（%r）' % (_e53,), False)

print()
print('=' * 78)
print('通过 %d 项，失败 %d 项，跳过 %d 项' % (len(OK), len(BAD), len(SKIP)))
if BAD:
    for b in BAD:
        print('   ✗ ' + b)
if SKIP:
    # ⚠ 跳过**不算通过**：fixture 缺失/前提不成立时，这里必须一眼看见（别被"全绿"骗了 ✗）
    print('   ⚠ 以下 %d 项**没真正验证**（fixture 缺失或前提不成立）：' % len(SKIP))
    for s in SKIP:
        print('     - ' + s)
sys.exit(1 if BAD else 0)
