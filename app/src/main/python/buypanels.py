# -*- coding: utf-8 -*-
"""buypanels.py · 「买完」流程：旅行商人 / 黄金宝库（坐标全部实机实测 2026-09-25）

## 旅行商人（`GoldGambleBlockPanel`）
面板标题「旅行商人」(688,601)，X 关闭 (983,602)。用户口径：**买 4 次**。
实机验证过的循环：购买(895,1255) → 返回(539,1212)，重复 4 次 → 关闭 X。
（效果：依次在四个档位购买，每次消耗的金币递增）

## 黄金宝库（`GoldenVaultBlockPanel`，源码 57315 起）
5x5 的 25 件宝物，分 3 圈：外圈 16 件(1 层) / 内圈 8 件(2 层) / 正中心 1 件(3 层)，
**每层只能拿一件**；要拿下一层必须先花金币解锁：
    10000 解锁第 1 层 → 选一件领 → 20000 解锁第 2 层 → 选一件领
    → 40000 解锁第 3 层 → 选中心那件领 → 「完成」结算      合计 70000 金币
图标坐标：x = 251 + 144*c，y = 746 + 144*r（5x5，实测 135x135 一格）
按钮（购买/选择/完成都是它）：(896,1444)；标题「黄金宝库」(692,383)，X (983,384)

用法:
    from buypanels import merchant_flow, vault_flow
    merchant_flow(bot, log)
    vault_flow(bot, log)
"""

# ─────────────────────────────────────────────────────────────────────────────
# 【Android 适配补丁 · 由 android_autoexplore/tools/port_android.py 注入，勿手改】
# Chaquopy 里 __file__ 指向 APK 内只读资源，模板/数据表在 filesDir/mapbot_pack
#  ⇒ 资源根一律走环境变量，未设置时回退 PC 原行为（便于与 PC 对拍）
import os as _os

_MAPBOT_ROOT = _os.environ.get('MAPBOT_ROOT') or _os.path.dirname(_os.path.abspath(__file__))
_MAPBOT_RUNS = _os.environ.get('MAPBOT_RUNS') or _os.path.join(_MAPBOT_ROOT, 'runs')
_MAPBOT_DT = _os.environ.get('MAPBOT_DT') or _os.path.join(_MAPBOT_ROOT, 'server_datatable.json')
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MERCHANT = {'title': '旅行商人', 'x': (983, 602), 'buy': (895, 1255),
            'back': (539, 1212), 'times': 4}
VAULT = {'title': '黄金宝库', 'x': (983, 384), 'buy': (895, 1444), 'back': (539, 1212),
         'blank': (540, 1700),      # 点空白处关详情（实测有效）
         'gx0': 251, 'gy0': 746, 'pitch': 144, 'cols': 5, 'rows': 5}
VAULT_RING = {1: (0, 0), 2: (1, 1), 3: (2, 2)}      # 每层代表格（0 基 行,列）


def _items(bot):
    """⚠ 必须先 snap 再 OCR：`Bot.ocr()` 用的是**上一次截图**（缓存旧图），
    点完不重新截图会读到点击前的画面（2026-09-25 踩过：宝库面板已开却判成没开）。
    ⚡ 只 OCR 面板所在的中段（y 300~1560），比全屏快 3 倍。"""
    bot.snap('bp')
    return bot.ocr(min_conf=0.35, band=(300, 1560))


def _has(items, *labels):
    for lb in labels:
        for it in items:
            if lb in it['text']:
                return it
    return None


def _confirm(bot, log, tag=''):
    """处理可能的确认/奖励弹窗：只点「确定」，绝不点「取消」"""
    for _ in range(2):
        it = _items(bot)
        ok = None
        for t in it:
            if t['text'].strip() == '确定' and t['cy'] > 800:
                ok = t
                break
        if not ok:
            return False
        bot.tap(ok['cx'], ok['cy'], wait=2.0)
        log.append({'buy_confirm': tag, 'at': (ok['cx'], ok['cy'])})
    return True


def merchant_flow(bot, log):
    """旅行商人：购买 → 返回，重复 4 次 → 关 X（2026-09-25 实机验证过）"""
    bought = 0
    for i in range(MERCHANT['times']):
        it = _items(bot)
        if _has(it, '金币不足', '钻石不足'):
            log.append({'merchant': 'no_money', 'i': i})
            break
        buy = _has(it, '购买')
        if not buy and i > 0:
            break
        bot.tap(*MERCHANT['buy'], wait=2.0)
        _confirm(bot, log, 'merchant%d' % i)
        it = _items(bot)
        back = _has(it, '返回')
        at = (back['cx'], back['cy']) if back else MERCHANT['back']
        bot.tap(at[0], at[1], wait=1.6)
        bought += 1
        log.append({'merchant': 'bought', 'i': i, 'back': at})
    bot.tap(*MERCHANT['x'], wait=2.0)
    log.append({'merchant': 'done', 'bought': bought})
    return bought


VAULT_PRIORITY = ('天赋果实', '幸运草', '四叶草')     # 用户口径：优先这两样，没有就随便选

# 「具体奖励」图标模板（从 main_sprites.bundle 导出，见 item_icons.py）
#   天赋果实 = Special_Item D00002_001 / 四叶草(幸运草) = D00002_000
ITEM_TPL_DIR = os.path.join(_MAPBOT_ROOT, 'templates', 'items')
ITEM_TPL = {'天赋果实': ['D00002_001.png'],
            '四叶草': ['D00002_000.png', 'D00002_000_2.png']}
ICON_SCALE = 4.5          # 图标 30px × 4.5 = 135px，正好铺满一格
ICON_THR = 0.55           # 实测真命中 0.73，误命中 ≤0.35
QTY_OFF = (32, 22, 50, 50)   # 数量角标：相对格中心的 (dx, dy, w, h)

_TPL_CACHE = {}


def _load_item_tpl():
    """{名称: [(灰度模板, 掩码, w, h) ...]}（多尺度 + 模板同名多文件）"""
    key = 'tpl'
    if key in _TPL_CACHE:
        return _TPL_CACHE[key]
    import cv2
    import numpy as np
    out = {}
    for name, files in ITEM_TPL.items():
        lst = []
        for fn in files:
            p = os.path.join(ITEM_TPL_DIR, fn)
            if not os.path.exists(p):
                continue
            img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if img is None or img.ndim < 3:
                continue
            for s in (ICON_SCALE - 0.2, ICON_SCALE, ICON_SCALE + 0.2):
                w, h = int(round(img.shape[1] * s)), int(round(img.shape[0] * s))
                g = cv2.cvtColor(cv2.resize(img[:, :, :3], (w, h),
                                            interpolation=cv2.INTER_AREA),
                                 cv2.COLOR_BGR2GRAY).astype(np.float32)
                m = cv2.resize(img[:, :, 3], (w, h),
                               interpolation=cv2.INTER_NEAREST) > 128
                if int(m.sum()) < 50:
                    continue
                v = g[m]
                v = v - v.mean()
                sd = v.std()
                if sd < 1e-6:
                    continue
                lst.append(((v / sd).astype(np.float32), m, w, h))
        if lst:
            out[name] = lst
    _TPL_CACHE[key] = out
    return out


def match_item_icon(img, cx, cy):
    """该格是不是优先图标 -> (最好分数, 名称)（灰度掩码 NCC，对背景/亮度不敏感）"""
    import cv2
    import numpy as np
    tpls = _load_item_tpl()
    best, bestname = -1.0, None
    for name, lst in tpls.items():
        for (tv, m, w, h) in lst:
            for dx in (-4, 0, 4):
                for dy in (-4, 0, 4):
                    x0 = int(cx - w / 2 + dx)
                    y0 = int(cy - h / 2 + dy)
                    sub = img[y0:y0 + h, x0:x0 + w]
                    if sub.shape[0] != h or sub.shape[1] != w:
                        continue
                    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY).astype(np.float32)
                    pv = g[m]
                    pv = pv - pv.mean()
                    sd = pv.std()
                    if sd < 1e-6:
                        continue
                    sc = float((pv / sd * tv).mean())
                    if sc > best:
                        best, bestname = sc, name
    return best, bestname


def _qty_tmp_path():
    """数量角标临时 PNG 的路径 —— **必须先保证目录真的存在**。

    ⚠ 2026-09-29 安卓端踩坑（用户报「卡在黄金宝库购买界面」的真凶）：
      原来写死 `dirname(__file__)/runs`。端上这个根是**只读资源包** `files/mapbot_pack/`
      （只有 `templates/` 与数据表，**没有 `runs/`**）⇒ `cv2.imencode(...).tofile()` 抛
      `FileNotFoundError` ⇒ 黄金宝库每轮 `vault_pick` 都炸 ⇒ 3 轮后 `too_many_errors`
      ⇒ 收工离场，把游戏留在购买面板 ✗
    现在统一用 `mapbot.RUNS`（PC/安卓同一个口径，且安卓侧已 makedirs），再兜
    `MAPBOT_RUNS` 环境变量、模块旁的 runs、系统临时目录，每层都 makedirs。
    """
    cands = []
    try:
        from mapbot import RUNS as _R
        if _R:
            cands.append(_R)
    except Exception:
        pass
    if os.environ.get('MAPBOT_RUNS'):
        cands.append(os.environ['MAPBOT_RUNS'])
    cands.append(os.path.join(_MAPBOT_ROOT, 'runs'))
    for d in cands:
        try:
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, '_qty.png')
        except Exception:
            continue
    import tempfile
    return os.path.join(tempfile.gettempdir(), '_qty.png')


def read_qty(bot, cx, cy):
    """读图标右下角的数量角标（实测放大 8 倍 OCR 置信度 0.99~1.00）"""
    import cv2
    import numpy as np
    from mapbot import _ocr
    img = bot.img()
    dx, dy, w, h = QTY_OFF
    x0, y0 = int(cx + dx), int(cy + dy)
    sub = img[y0:y0 + h, x0:x0 + w]
    if sub.size == 0:
        return None
    big = cv2.resize(sub, None, fx=8, fy=8, interpolation=cv2.INTER_CUBIC)
    tmp = _qty_tmp_path()
    cv2.imencode('.png', big)[1].tofile(tmp)
    res, _ = _ocr()(tmp)
    for it in (res or []):
        t = it[1].strip().replace('x', '').replace('X', '').replace('*', '')
        if t.isdigit() and 1 <= len(t) <= 4 and float(it[2]) >= 0.5:
            return int(t)
    return None



# ⭐ 2026-09-27 用户口径：宝库奖励按**档位**比（数据来自游戏 GoldenVault 表 ✓）
#   档1 = 1 草 / 5 果 ；档2 = 2 / 10 ；档3 = 4 / 20 ；档4 = 8 / 50
VAULT_TIER = {
    '四叶草': {1: 1, 2: 2, 4: 3, 8: 4},
    '幸运草': {1: 1, 2: 2, 4: 3, 8: 4},
    '天赋果实': {5: 1, 10: 2, 20: 3, 50: 4},
}


def vault_tier_of(name, qty):
    """(名称, 数量) → 档位；同档时**天赋果实优先** ⇒ 返回 (档, 是否果实) ✓

    未知数量 ⇒ 用近似：草按数量、果按 数量/6.25（= 8:50 的比值 ✓）×1.25 换算成同尺度 ✓
    """
    nm = name or ''
    q = int(qty or 0)
    for key, tbl in VAULT_TIER.items():
        if key in nm:
            t = tbl.get(q)
            if t is None:                       # 表外数量 ⇒ 近似
                t = (q / 6.25) if '果' in nm else float(q)
            return (float(t), 1 if '果' in nm else 0)   # 同档 ⇒ 果实优先（pref 大者胜 ✓）
    return (0.0, 2)          # 其它物品（神石/装备/符文）不进这个比较 ✓


def vault_pick(bot, log, level, max_probe=25):
    """在某一层里挑一件奖励（**用户口径：不点开详情，直接认图标**）

    1. 只扫该层那一圈格子（d=2 → 16 格 / d=1 → 8 格 / d=0 → 1 格）
    2. 图标模板匹配 → 认「天赋果实 / 四叶草(幸运草)」
    3. 命中的格子再 OCR 右下角数量角标 → **取数量最多的那件**
    4. 一个都没命中就随便取该圈第一格兜底
    ⭐ 用户口径（2026-09-25）：**第一轮只能选最外一圈、第二轮中间一圈、第三轮只有中间一格**
       ⇒ 第三轮不用扫，直接点中心
    """
    cells = vault_ring(level)[:max_probe]
    it = _items(bot)
    if not (_has(it, VAULT['title']) or _has(it, '黄全宝库')):
        return (cells[0] if cells else VAULT['buy']), '?'
    if len(cells) == 1:                     # 第三轮：只有核心一格，无需扫描
        log.append({'vault': 'center_only', 'at': cells[0]})
        return cells[0], '核心'
    img = bot.img()
    cands = []
    for (x, y) in cells:
        sc, name = match_item_icon(img, x, y)
        if name and sc >= ICON_THR:
            qty = read_qty(bot, x, y)
            cands.append((qty if qty else 0, round(sc, 3), name, (x, y)))
    # ⭐ 2026-09-27：按**档位**比（同档 ⇒ 天赋果实 ✓ 用户口径）
    for c in cands:
        c_t = vault_tier_of(c[2], c[0])
        log.append({'vault': 'icon_hit', 'name': c[2], 'qty': c[0], 'score': c[1],
                    'tier': round(c_t[0], 2), 'pref': c_t[1], 'at': c[3]})
    if cands:
        # 排序键：(档位, 果实优先) ⇒ 取最大 ✓
        cands.sort(key=lambda c: vault_tier_of(c[2], c[0]), reverse=True)
        q, sc, name, at = cands[0]
        _t = vault_tier_of(name, q)
        log.append({'vault': 'pick_best', 'name': name, 'qty': q, 'at': at,
                    'tier': round(_t[0], 2), 'pref': _t[1],
                    'why': '按档位 ✓ 同档选天赋果实 ✓'})
        return at, '%s×%d(档%.2f)' % (name, q, _t[0])
    log.append({'vault': 'no_icon_hit', 'cells': len(cells)})
    return (cells[0] if cells else VAULT['buy']), '随意'



def vault_ring(k):
    """第 k 层（1 外层 16 / 2 内层 8 / 3 核心 1）的格子坐标列表

    5x5 里按到中心的切比雪夫距离分层：d=2 → 16 格，d=1 → 8 格，d=0 → 1 格
    """
    gx, gy, p = VAULT['gx0'], VAULT['gy0'], VAULT['pitch']
    d = {1: 2, 2: 1, 3: 0}[max(1, min(3, k))]
    out = []
    for r in range(5):
        for c in range(5):
            if max(abs(r - 2), abs(c - 2)) == d:
                out.append((gx + c * p, gy + r * p))
    return out


def _btn(it):
    """读面板右下角那颗按钮（y 1400~1530、x 780~1020）——**位置每次都可能不一样**
    （带价格时文字在上、价格在下；只有「选择奖励」时只有一行），所以必须每轮 OCR 定位。

    -> (label, cost, (cx,cy))；label ∈ 购买/选择奖励/离开/完成/领取
    """
    label, cost, pos = None, None, None
    KEYS = ('购买', '选择', '离开', '完成', '领取', '确定')
    for t in it:
        if not (1400 < t['cy'] < 1530 and 760 < t['cx'] < 1030):
            continue
        s = t['text'].strip()
        if any(k in s for k in KEYS):
            label = s
            pos = (t['cx'], t['cy'])
        elif s.replace(',', '').replace('+', '').isdigit() and len(s) >= 4:
            cost = int(s.replace(',', '').replace('+', ''))
            if pos is None:
                pos = (t['cx'], t['cy'])
    return label, cost, pos


def _back_btn(it):
    """中间那颗「返回」(539,1212)——**按位置认**，别用「不含离开」这种条件：
    领完奖励时「恭喜获得」+「返回」和右下角「离开」会同时出现，
    用 `not _has(it,'离开')` 会把「返回」漏掉（用户 2026-09-25 报「选择奖励后没有点返回」）"""
    for t in it:
        if '返回' in t['text'] and abs(t['cx'] - VAULT['back'][0]) < 130 \
                and abs(t['cy'] - VAULT['back'][1]) < 90:
            return t
    return None


def _dismiss(bot, log, tries=3):
    """收起奖励展示（中间「返回」）/ 确认弹窗（只点确定）"""
    for _ in range(tries):
        it = _items(bot)
        bk = _back_btn(it)
        if bk:
            bot.tap(bk['cx'], bk['cy'], wait=2.2)
            log.append({'vault': 'back', 'at': (bk['cx'], bk['cy'])})
            continue
        ok = None
        for t in it:
            if t['text'].strip() in ('确定', '确认') and t['cy'] > 700:
                ok = t
                break
        if ok:
            bot.tap(ok['cx'], ok['cy'], wait=2.2)
            log.append({'vault': 'confirm', 'at': (ok['cx'], ok['cy'])})
            continue
        return False
    return True


def vault_flow(bot, log):
    """黄金宝库买完 —— **按 1→2→3 圈依次走一遍**（用户 2026-09-25 定案）

    为什么按圈遍历而不是「数自己买了几次」：中途接手时计数从 0 开始，
    会一直去点第 1 圈 → 死循环（用户：「你刚刚是一直重复第一圈」）。
    按圈遍历时，某一圈点错了也只是**空操作**（游戏 `OnFuncButtonClicked` 会检查
    `selectingIndex` 必须属于当前层，不属于就直接 return），不会误领，下一圈继续。

    每一圈：
      ① 按钮是「购买」→ 先点它解锁（10000 外层 / 20000 内层 / 40000 核心）
      ② 按钮是「选择奖励」→ 在**这一圈**里挑（优先天赋果实/四叶草，比右下角数量）
         → 点中选那格 → 点这颗按钮
      ③ 出现「返回」→ 点掉，回到宝库面板
    三圈走完按钮变「离开」→ 点它；还开着就点右上 X 兜底。
    """
    acts = []
    for ring in (1, 2, 3):
        # ① 需要时先解锁这一圈
        for _ in range(4):
            it = _items(bot)
            if _back_btn(it):                 # 中间「返回」：先收起奖励展示
                _dismiss(bot, log)
                continue
            label, cost, pos = _btn(it)
            if label and '购买' in label:
                bot.tap(*(pos or VAULT['buy']), wait=2.6)
                _confirm(bot, log, 'vault_buy%d' % ring)
                log.append({'vault': 'buy', 'ring': ring, 'cost': cost, 'at': pos})
                acts.append('buy%d' % ring)
                continue
            break
        it = _items(bot)
        if not (_has(it, VAULT['title']) or _has(it, '黄全宝库')):
            log.append({'vault': 'panel_gone', 'ring': ring})
            break
        label, cost, pos = _btn(it)
        if label and '离开' in label:
            bot.tap(pos[0], pos[1], wait=2.4)
            log.append({'vault': 'leave'})
            break
        if not (label and ('选择' in label or '领取' in label)):
            log.append({'vault': 'no_select_btn', 'ring': ring, 'label': label})
            continue
        # ② 在**这一圈**里挑一件 + 点按钮
        pick, name = vault_pick(bot, log, ring)
        if ring < 3:
            # ⚠ 第 3 圈（中心格）**游戏会自动选中**（源码 RefreshDefaultSelectingIndex：
            #   currentLevel==3 时 selectingIndex=12），再点一次等于点已选中的格子 →
            #   会弹出该奖励的详情面板、把右下角按钮盖住（用户 2026-09-25 报「点两下中间的」）
            bot.tap(pick[0], pick[1], wait=1.7)
        it2 = _items(bot)
        l2, _c2, p2 = _btn(it2)
        if not (l2 and ('选择' in l2 or '领取' in l2)):
            # 按钮读不到 → 多半是详情面板盖住了，点空白处关掉再读一次
            bot.tap(*VAULT['blank'], wait=1.6)
            it2 = _items(bot)
            l2, _c2, p2 = _btn(it2)
        at = p2 if (l2 and ('选择' in l2 or '领取' in l2)) else pos
        bot.tap(at[0], at[1], wait=2.6)
        log.append({'vault': 'claim', 'ring': ring, 'pick': pick, 'name': name,
                    'btn': l2, 'at': at})
        acts.append('claim%d' % ring)
        # ③ 收起奖励展示
        _dismiss(bot, log)
    # 收尾：返回 → 离开 → X
    _dismiss(bot, log)
    it = _items(bot)
    label, _c, pos = _btn(it)
    if label and '离开' in label:
        bot.tap(pos[0], pos[1], wait=2.4)
        log.append({'vault': 'leave'})
    it = _items(bot)
    if _has(it, VAULT['title']) or _has(it, '黄全宝库'):
        bot.tap(*VAULT['x'], wait=2.0)
        log.append({'vault': 'x_close'})
    _confirm(bot, log, 'vault_after')
    log.append({'vault': 'done', 'acts': acts})
    return acts


def ensure_closed(bot, log):
    """兜底：把还开着的面板 X 掉（只认 x≈493 / x≈1024 的真关闭符）"""
    closed = 0
    for _ in range(3):
        it = _items(bot)
        x = None
        for t in it:
            if t['text'].strip() in ('X', 'x', '\u00d7', '\u2715', '\u2716') and \
                    min(abs(t['cx'] - 493), abs(t['cx'] - 1024)) <= 80:
                x = t
                break
        if not x:
            break
        bot.tap(x['cx'], x['cy'], wait=1.8)
        closed += 1
    if closed:
        log.append({'ensure_closed': closed})
    return closed
