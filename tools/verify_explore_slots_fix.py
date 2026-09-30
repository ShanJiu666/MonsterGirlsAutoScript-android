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
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
MAPBOT = os.path.join(ROOT, 'tools', 'mapbot')
FIXTURE = os.path.join(ROOT, 'android_autoexplore', '_verify',
                       'phone_slots_full_0930.json')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, MAPBOT)
os.environ.setdefault('MAPBOT_ROOT', MAPBOT)
os.environ.pop('MAPBOT_ANDROID', None)          # PC 口径（C=0）

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

import explore_loop as EL      # noqa: E402
import numpy as np             # noqa: E402

OK = []
BAD = []


def check(name, cond, detail=''):
    (OK if cond else BAD).append(name)
    print('%s %s%s' % ('[ok]  ' if cond else '[FAIL]', name,
                       ('  · ' + str(detail)) if detail else ''))


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

_tpl_dir = os.path.join(MAPBOT, 'templates', 'ui')
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
    _java = open(os.path.join(ROOT, 'android_autoexplore', 'app', 'src', 'main', 'java',
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
print('⑩ Android 生成物一致性（防「PC 改了、手机没跟上」✗）')
# ⚠ 2026-10-01 实锤：`buypanels.py` 在 Android 侧是**另一份手工副本**，已与 PC 漂移
#   （宝库「幸运草识别不出」就是它带来的）⇒ 现在一律走 `port_android.py` 生成，
#   并在这里**逐字节**校验生成物与磁盘文件一致 ✓
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        'port_android_gen',
        os.path.join(ROOT, 'android_autoexplore', 'tools', 'port_android.py'))
    _gen = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_gen)
    _bad = []
    for _m in _gen.MODULES:
        _disk = os.path.join(ROOT, 'android_autoexplore', 'app', 'src', 'main',
                             'python', _m + '.py')
        # ⚠ 必须复刻 main() 的**完整**变换：patch() + 该模块的 EXACT 精确替换 ✓
        _want = _gen.patch(open(os.path.join(_gen.SRC, _m + '.py'), encoding='utf-8').read(), _m)
        for _old, _new in _gen.EXACT.get(_m + '.py', []):
            _want = _want.replace(_old, _new)
        _have = open(_disk, encoding='utf-8').read() if os.path.exists(_disk) else ''
        if _want != _have:
            _bad.append(_m)
    check('port_android.py 的 %d 个模块生成物与手机侧一致（漂移: %s）'
          % (len(_gen.MODULES), ','.join(_bad) if _bad else '无'), not _bad)
    # 宝库图标尺度必须由 pitch 推出（防再写死 4.5 ✗）—— 只看**代码**，不看注释 ✓
    _bp = open(os.path.join(ROOT, 'tools', 'mapbot', 'buypanels.py'), encoding='utf-8').read()
    _bp_code = '\n'.join(l.split('#')[0] for l in _bp.splitlines()
                         if not l.strip().startswith('#'))
    check('宝库图标尺度由格子间距推出（不再写死 ICON_SCALE）',
          '_icon_scales' in _bp_code
          and not _re.search(r'^\s*ICON_SCALE\s*=', _bp_code, _re.M))
    check('宝库图标认不出时有**宽尺度兜底** + 分数落日志',
          'icon_hit_wide' in _bp and "'vault_debug'" in _bp)
except Exception as _e:      # noqa: BLE001
    check('port_android.py 生成物校验可运行（%r）' % (_e,), False)

print()
print('⑪ 观测累积（防「规划很差劲」：脏帧不许抹掉已知格 ✗）')
check('跨轮累积观测 st[\'obs\'] 已建立（已揭示永不翻回 ✓）',
      "st.setdefault('obs', {})" in src and "'obs_merge'" in src)
check('规划输入改用累积观测（不再直接用单帧 c[\'st\']）',
      "_base_cells = st.get('obs') or (c.get('st') or {})" in src)

print()
print('⑫ 宝库奖励口径（用户 2026-10-01：同档位优先天赋果实 + 幸运草就是四叶草 + 认不出就点进去看）')
_bp2 = open(os.path.join(ROOT, 'tools', 'mapbot', 'buypanels.py'), encoding='utf-8').read()
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
_tc = open(os.path.join(ROOT, 'tools', 'mapbot', 'targets_cfg.py'), encoding='utf-8').read()
check('is_blocked 由**勾选配置推导**（不再硬编码黑名单 ✓）',
      "return not enabled(k, cfg)" in _tc and '_blocked = {' not in _tc)
check('特殊地块名单含两种宝箱怪 + 预言石碑/石板',
      all(k in _tc for k in ("'金属宝箱怪'", "'机巧宝箱怪'", "'预言石碑'", "'预言石板'")))
check('拉黑格一律**不是目标**（is_target 先判 is_blocked ✓）',
      'if is_blocked(name):' in _tc and 'return False' in _tc)
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
_vf = os.path.join(ROOT, 'android_autoexplore', '_verify', 'phone_stamina_0930',
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
        check('真机宝库帧离线复核（帧不存在 ⇒ 跳过 ✓）', True)
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
    _u = _undefined_upper(os.path.join(ROOT, 'tools', 'mapbot', _f))
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
_v4 = os.path.join(ROOT, 'android_autoexplore', '_verify', 'phone_stamina_0930',
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
        check('宝库点击常量真机帧核对（帧不存在 ⇒ 跳过 ✓）', True)
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
    _sys2.path.insert(0, os.path.join(ROOT, 'tools', 'mapbot'))
    _spec2 = _ilu2.spec_from_file_location(
        'bp_exec', os.path.join(ROOT, 'tools', 'mapbot', 'buypanels.py'))
    _bp3 = _ilu2.module_from_spec(_spec2)
    _spec2.loader.exec_module(_bp3)
    _bp3.read_qty = lambda bot, cx, cy: 50      # 桩：数量读作 50

    _v4 = os.path.join(ROOT, 'android_autoexplore', '_verify', 'phone_stamina_0930',
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
        check('vault_pick 执行级验证（缺真机帧 ⇒ 跳过 ✓）', True)
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
_mb = open(os.path.join(ROOT, 'tools', 'mapbot', 'mapbot.py'), encoding='utf-8').read()
check('等待循环可被停止打断（wait_change ✓）',
      'def _stop_flag()' in _mb and 'if _stop_flag():' in _mb)
check('wait_stable 同样可打断', _mb.count('if _stop_flag():') >= 2)
check('战斗等待 wait_end 收到停止立刻退出（不再 continue ✗）',
      "'wait_end': 'stopped_by_user'" in src and 'if stop_requested():' in src)
check('_stop_flag 在 PC 上恒 False（零回归 ✓）',
      "getattr(_el, '_ANDROID_STOP', False)" in _mb)
# ⭐ **执行级**验证：真跑两个等待循环，量「置停止位 → 返回」耗时 ✓
try:
    import threading as _th
    import time as _tm
    import importlib.util as _ilu3
    import sys as _sys3
    import types as _ty3
    import numpy as _np3
    if 'explore_loop' not in _sys3.modules:
        _fel = _ty3.ModuleType('explore_loop')
        _fel._ANDROID_STOP = False
        _sys3.modules['explore_loop'] = _fel
    _sp3 = _ilu3.spec_from_file_location('mb_exec',
                                         os.path.join(ROOT, 'tools', 'mapbot', 'mapbot.py'))
    _mb3 = _ilu3.module_from_spec(_sp3)
    _sp3.loader.exec_module(_mb3)
    _fel2 = _sys3.modules['explore_loop']

    class _FF3(object):
        def grab(self):
            return _np3.zeros((1920, 1080, 3), dtype=_np3.uint8)

    def _nb3():
        _b = _mb3.Bot.__new__(_mb3.Bot)
        _b.fast_ok = True
        _b.fast = _FF3()
        _b._img_arr = _b.fast.grab()
        _b._img_path = None
        _b.last_change = {}
        _b.t = {'wait': 0.0, 'wait_n': 0}
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
_amb = open(os.path.join(ROOT, 'android_autoexplore', 'app', 'src', 'main',
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
    _sys4.path.insert(0, os.path.join(ROOT, 'tools', 'mapbot'))
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
        'el_blocked', os.path.join(ROOT, 'tools', 'mapbot', 'explore_loop.py'))
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
    _sys5.path.insert(0, os.path.join(ROOT, 'tools', 'mapbot'))
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
        'el_disambig', os.path.join(ROOT, 'tools', 'mapbot', 'explore_loop.py'))
    _el5 = _ilu5.module_from_spec(_spec5)
    _spec5.loader.exec_module(_el5)
    _v5 = os.path.join(ROOT, 'android_autoexplore', '_verify', 'phone_stamina_0930',
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
        check('图名消歧执行级验证（缺真机帧 ⇒ 跳过 ✓）', True)
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
    _sys6.path.insert(0, os.path.join(ROOT, 'tools', 'mapbot'))
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
        'el_vault', os.path.join(ROOT, 'tools', 'mapbot', 'explore_loop.py'))
    _el6 = _ilu6.module_from_spec(_spec6)
    _spec6.loader.exec_module(_el6)
    _v6 = os.path.join(ROOT, 'android_autoexplore', '_verify', 'phone_stamina_0930',
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
        check('v0.96 宝库执行级验证（缺真机帧 ⇒ 跳过 ✓）', True)
except Exception as _e:      # noqa: BLE001
    check('v0.96 宝库执行级验证可运行（%r）' % (_e,), False)

# =====================================================================================
# v0.97【宝库流程：奖励展示是模态 + 不许连点购买 + `_back_btn` 判据漂移】
#   用户真机报（2026-10-01）：「购买第一层后，点击了好几个奖励才选择奖励，选择后不点返回
#   就直接点购买，现在停在有返回弹窗的界面」
# =====================================================================================
try:
    _bp_path = os.path.join(ROOT, 'tools', 'mapbot', 'buypanels.py')
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
    _j7 = os.path.join(ROOT, 'android_autoexplore', '_verify', 'phone_stamina_0930',
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
        check('v0.97 宝库真机帧执行级验证（缺真机帧 ⇒ 跳过 ✓）', True)
except Exception as _e:      # noqa: BLE001
    check('v0.97 宝库流程守门可运行（%r）' % (_e,), False)

# =====================================================================================
# v0.98【宝库选奖励：检测奖励格 + 按颜色认草/果（不再东点一下西点一下）】
#   用户真机报（2026-10-01）：「这宝库选择奖励界面纯在乱点啊……不应该识别到天赋果实和
#   幸运草直接选这俩其中一个吗」——根因：网格常数比真机实际位置**高 ~51px**
#   ⇒ 裁图错位 ⇒ 全盘 NCC 0.12~0.31 ⇒ 认不出 ⇒ 退成"逐格点开读名"（= 用户看到的乱点）✗
# =====================================================================================
try:
    _bp2 = os.path.join(ROOT, 'tools', 'mapbot', 'buypanels.py')
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
    _f8 = os.path.join(ROOT, 'android_autoexplore', '_verify', 'phone_stamina_0930',
                       'bagdbg', 'vault_no_hit_L2.png')
    if os.path.exists(_f8) and hasattr(_bp8, 'vault_tiles'):
        import cv2 as _c8
        import numpy as _n8
        _im8 = _c8.imdecode(_n8.fromfile(_f8, dtype=_n8.uint8), _c8.IMREAD_COLOR)
        _tl8 = _bp8.vault_tiles(_im8)
        check('v0.98 执行级①：真机圈2帧检测到奖励格（%d 个，≥6 ✓）' % len(_tl8), len(_tl8) >= 6)
        _ys8 = sorted(set(y for (_x, y, _w, _h) in _tl8))
        check('v0.98 执行级②：检测格心比常数 gy0=%d 低 ≥40px（= 旧代码裁错地方的根因）'
              % _bp8.VAULT['gy0'],
              bool(_ys8) and min(abs(y - _bp8.VAULT['gy0']) for y in _ys8) > 40,
              'y=%s' % (_ys8[:4],))
        _hit8 = []
        for (_x, _y, _w, _h) in _tl8:
            _k8, _fr8 = _bp8.sprite_kind(_im8, _x, _y, int(min(_w, _h) * 0.36))
            if _k8:
                _hit8.append((_x, _y, _k8, round(_fr8['pink'], 3), round(_fr8['green'], 3)))
        check('v0.98 执行级③：认出「天赋果实」(pink≥.35) 与「四叶草」(green≥.25)，且无误命中',
              any(h[2] == '天赋果实' for h in _hit8) and any(h[2] == '四叶草' for h in _hit8)
              and len(_hit8) == 2, 'hits=%s' % (_hit8,))

        class _FB8(object):
            ocr_grabs = True

            def __init__(self, im):
                self._im = im
                self.taps = []

            def ocr(self, min_conf=0.0, band=None, tag=''):
                return [{'text': '黄金宝库', 'cx': 690, 'cy': 438, 'conf': 1.0},
                        {'text': '选择奖励', 'cx': 894, 'cy': 1521, 'conf': 1.0}]

            ocr_dlg = ocr

            def snap(self, tag=''):
                pass

            def img_dlg(self):
                return self._im

            img = img_dlg

            def tap_dlg(self, x, y, wait=0):
                self.taps.append((int(x), int(y)))

        _fb8 = _FB8(_im8)
        _lg8 = []
        _at8, _nm8 = _bp8.vault_pick(_fb8, _lg8, 2)
        check('v0.98 执行级④：`vault_pick` 直接给出草/果（%s @%s）' % (_nm8, _at8),
              ('天赋果实' in _nm8) or ('四叶草' in _nm8))
        check('v0.98 执行级⑤：**一次点击都没有**（不再逐格点开读名 ✓）', len(_fb8.taps) == 0,
              'taps=%s' % (_fb8.taps,))
        check('v0.98 执行级⑥：日志里不再走 probe（乱点那条路）',
              not any(isinstance(e, dict) and e.get('vault') in ('probe', 'probe_none', 'no_icon_hit')
                      for e in _lg8))
    else:
        check('v0.98 宝库奖励格执行级验证（缺真机帧 ⇒ 跳过 ✓）', True)
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
    _ms6 = os.path.join(ROOT, 'tools', 'mapbot', 'mapsim.py')
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
    _f6 = os.path.join(ROOT, 'android_autoexplore', '_verify', 'phone_stamina_0930',
                       'bagdbg', 'iron_highland_fog_dev.png')
    if os.path.exists(_f6):
        _sys6b = __import__('sys')
        _sys6b.path.insert(0, os.path.join(ROOT, 'tools', 'mapbot'))
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
        check('v1.06 真机帧执行级验证（缺 fixture ⇒ 跳过 ✓）', True)
except Exception as _e6:      # noqa: BLE001
    check('v1.06 雾格剪影守门可运行（%r）' % (_e6,), False)

# =====================================================================================
# v1.07【体力不足要把"为什么停"说在悬浮条上】（用户报「怎么连启动都启动不了了，完全用不了」
#   —— 真因是体力 < 下限 ⇒ 静默收工，悬浮条只写「体力不够了 · 收工」，看不出毛病）
# =====================================================================================
try:
    _el7 = os.path.join(ROOT, 'tools', 'mapbot', 'explore_loop.py')
    _src7 = open(_el7, encoding='utf-8').read()
    check('v1.07 ① 体力不足的悬浮条文案带**三个数**（当前/下限/怎么办 ✓）',
          "status('体力 %d 不足（要 %d）· %s'" in _src7)
    check('v1.07 ② 自动补给关着时明确提示去开（用户 09-30 成功那次它是开着的 ✓）',
          "开自动补给可自动吃结实补给" in _src7
          and "'补给没吃够，请手动补一次'" in _src7)
    check('v1.07 ③ 体力**读不到**也说明白（原来只写「体力读不到 · 先不进图」✗）',
          "status('体力读不到（要 ≥%d）· 先不进图，请看一眼体力'" in _src7)
    _pl7 = os.path.join(ROOT, 'android_autoexplore', 'tools', 'port_loop.py')
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
    _el8 = os.path.join(ROOT, 'tools', 'mapbot', 'explore_loop.py')
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
        'el_marks8', os.path.join(ROOT, 'tools', 'mapbot', 'explore_loop.py'))
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

print()
print('=' * 78)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
if BAD:
    for b in BAD:
        print('   ✗ ' + b)
sys.exit(1 if BAD else 0)
