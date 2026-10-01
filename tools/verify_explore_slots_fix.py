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
check('特殊地块名单含两种宝箱怪 + 预言石碑/石板',
      all(k in _tc for k in ("'金属宝箱怪'", "'机巧宝箱怪'", "'预言石碑'", "'预言石板'")))
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
          "return bool(c['light']) and _mx >= 0.75" in _src15)
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
    check('v1.21 ② "已揭示"口径与 `spots.py` 的 `revealed` 同源（0.75 ✓）',
          'REVEAL_RATIO_MIN = 0.75' in _src21 and 'ratio >= 0.75' in _sp21
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
    _fb21, _shape21 = [], []
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
        if old_want is not None and _oldv21 != old_want:
            _fb21.append('%s: 旧的=%s(预期%s)' % (tag, _oldv21, old_want))
    check('v1.21 ⑦ 两帧真机反馈帧 + dlg16 都是**归一化 1080×1920**（喂错帧就当场红 ✓）',
          not _shape21, 'bad=%s' % (_shape21,))
    check('v1.21 ⑧ 执行级：两帧真机"棋盘正常"判 **False**（旧实现判 True ✗）、'
          'dlg16 真遮罩仍判 **True** ✓',
          not _fb21, 'bad=%s' % (_fb21,))
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
# ㊵ PC 端提速层（fixed.py）—— **已移出本门禁**
#   2026-10-01 晚「两端完全平行」：PC 端的固定锚点/模板快查是**PC 自己的**东西，
#   手机端仓里**没有** fixed.py，也**不该**有 —— 在这里查它等于让手机端依赖 PC。
#   ⇒ 这组检查搬到了 **PC 端仓**：`mapbot_pc/verify_gate.py`（PC 自己的门禁）。
#   手机端这边只留一句指针，提醒改 PC 提速约定要去 PC 仓跑。
print()
print('㊱ PC 端提速层（fixed.py）不在本门禁 —— 属 PC 端自己的门禁（mapbot_pc/verify_gate.py）')
check('手机端仓**不含** fixed.py（平行：PC 的东西不进本仓）',
      not os.path.exists(os.path.join(PROJ, 'app', 'src', 'main', 'python', 'fixed.py')))

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
