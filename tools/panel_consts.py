# -*- coding: utf-8 -*-
"""panel_consts.py · 面板层坐标常数的**单一事实来源** + 漏检防呆扫描器（v1.20 新增）

## 为什么要有这个模块

`tools/verify_panels_allres.py` 的自检覆盖度**完全取决于 `PANEL_CONSTS` 这张清单**，
而这张清单原先是手工维护的，工具自己在结尾就承认过：

    ⚠ 但这只覆盖**已列入清单**的常数；新面板必须同时登记进 PANEL_CONSTS，
      否则等于没测（清单即契约）。

「必须手工登记」= **漏登记没有任何人会发现** ⇒ 这正是 README §6.42 判定的
「面板层没做全分辨率」的机制性根因：换分辨率后新加的面板静默失准。

⇒ 本模块做两件事：
    ① `SCAN_SOURCES`  —— 声明**哪些文件的哪些常量属于"面板层坐标"**（事实来源）
    ② `scan_unregistered()` —— 用 **AST**（不是正则）扫出手机端所有坐标类常量，
       与已登记清单求**差集**；差集非空 ⇒ ❌ 失败。

## 为什么用 AST 而不是正则

`tools/audit_hardcoded_coords.py` 用正则 + 手写「剥注释」启发式，v1.86 踩过
「改正则而误报/漏报」。AST 由 CPython 自己解析，天然：
    · 不会把 docstring / 注释里的示例坐标当代码（那类误报正是 v1.19 踩过的坑）
    · 能拿到常量的**真实结构**（tuple / list / dict 项 / 标量）而不只是文本
    · 能区分模块级常量与函数体局部量（只管模块级，前者是可维护的登记表）

## 坐标系类型（与 RefMapper 锚定模型一致）

| kind       | 含义 | 自适应性 |
|------------|------|----------|
| `ref`      | 归一化参考系（1080×1920）经 `b.tap()` / `LAYOUT.sx/sy` | 锚定模型成立即自适应 ✓ |
| `dlg_final`| 弹窗系**最终坐标**（面板锚设备屏幕中心，真机 OCR 直量） | 与分辨率无关 ✓ |
| `dlg`      | 弹窗系（需 +C，C = dialogShift） | 随面板动 ✓ |
| `abs`      | **绝对参考系 y**（换分辨率不会跟着动） | ⚠ 危险项，必须逐个盯 |
| `scale`    | 纯数值阈值/比例（不是坐标，不参与几何断言） | 与分辨率无关 ✓ |

⚠ `abs` 里的每一条都必须写明「为什么它不需要随分辨率动」——否则就是下一个 v1.19。
"""
import ast
import os
import sys

# ── 手机端 Python 源码目录 ──────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
PYD = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))

# ── 面板层坐标常数的**事实来源**：文件名 → 该文件里属于面板层的常量名 ──────────
# ⚠ 新增面板常量时**必须**在这里登记，否则 `scan_unregistered()` 会红。
#   value 形如 'x'（取 x）/'y'（取 y）/'xy'（两个都是）/''（纯数值，不参与几何）
SCAN_SOURCES = {
    'explore_loop.py': {
        # —— 结算面板（v1.19：底部三键两机一致，奖励行真机高 271px ⇒ 奖励行改锚「关闭」）——
        'REWARD_X1': ('x', 'abs'),
        'REWARD_CLOSE_UP_MIN': ('y', 'abs'),
        'REWARD_CLOSE_UP_MAX': ('y', 'abs'),
        # —— 归一化系（棋盘/导航，锚定模型保证）——
        'UNIVERSAL_CLOSE': ('xy', 'ref'),
        'START_ADV': ('xy', 'ref'),
        'GUILD_BTN': ('xy', 'ref'),
        'BAG_BTN': ('xy', 'ref'),
        'DISPATCH_BTN': ('xy', 'ref'),
        'EXPLORE_BTN': ('xy', 'ref'),
        'STOP_HM': ('xy', 'ref'),
        'BACK_BTN': ('xy', 'ref'),
        # ⚠ 这两个真机实测在**弹性带内**（归一化帧看不见）⇒ 必须走弹窗系，已加 *_DLG
        'CLOSE_TR_PT': ('xy', 'abs'),
        'ITEM_TAB': ('xy', 'abs'),
        'EQUIP_TAB': ('xy', 'abs'),
        'UPGRADE_BTN': ('xy', 'abs'),
        # —— 弹窗系（真机抓帧实测，面板锚设备中心 ⇒ 与分辨率无关）——
        'BAG_X_DLG': ('xy', 'dlg_final'),
        'BAG_TAB_DLG': ('xy', 'dlg_final'),
        'BAG_FILTER_DLG': ('xy', 'dlg_final'),
        # ⚠ v1.20 AST 扫描**新抓出来的**（原先没人验）：
        #   「自动跳过」勾选框 —— 结算面板底部三键之一，与「关闭」同属锚底系
        #   （v1.19 实测底部三键两机一致 ⇒ 真机 1264×2780 上 y 与 9:16 相同 ✓）
        '_AUTO_SKIP_BOX': ('xy', 'abs'),
        # 背包模板多尺度搜索带（相对比例，不是绝对坐标 ⇒ 与分辨率无关 ✓）
        '_BAG_TPL_SCALES': ('tuple', 'scale'),
    },
    'buypanels.py': {
        # 旅行商人：点击全走 tap_dlg ⇒ 已是 dlg_final（v1.20 核实）
        'MERCHANT': ('dict', 'dlg_final'),
        # 黄金宝库：v0.88 真机帧重标定（buy 1498 / back 660,1590 / blank 660,1590）
        'VAULT': ('dict', 'dlg_final'),
        'VAULT_BACK_ZONE': ('xy', 'dlg_final'),
        # ⚠ BAND 是 **OCR 搜索带**（归一化帧里要看的 y 段），绝对值 ⇒ 换分辨率要盯
        'BAND': ('band', 'abs'),
        'VAULT_RING': ('dict', 'scale'),
        'QTY_OFF': ('quad', 'dlg_final'),
        'ICON_FILL': ('num', 'scale'),
        'ICON_THR': ('num', 'scale'),
        'VAULT_TIER': ('dict', 'scale'),
        'VAULT_PRIORITY': ('tuple', 'scale'),
        'PREF_FRUIT': ('num', 'scale'),
        'PREF_CLOVER': ('num', 'scale'),
        'SPRITE_PINK_THR': ('num', 'scale'),
        'SPRITE_GREEN_THR': ('num', 'scale'),
    },
}

# ── 明确豁免：被扫到但**不是**面板层坐标的常量（附理由，供 review）────────────
EXEMPT = {
    'explore_loop.py': {
        'MIN_STAMINA': '体力下限，非坐标',
        'SAVE_ROUNDS': '落盘轮数，非坐标',
        'SAVE_FIRST': '落盘开关，非坐标',
        'COLLECT_ONLY': '采图开关，非坐标',
        'OPT_SOLVER': '求解器开关，非坐标',
        'ADAPTIVE_LAYOUT': '布局开关，非坐标',
        'AUTO_SUPPLY': '补给开关，非坐标',
        'SUPPLY_USED': '补给计数，非坐标',
        'BUY_SCORE_MIN': '商人购买匹配阈值（非坐标）',
        'EXPLORE_DISPATCH': '派遣开关，非坐标',
        'EXPLORE_SLOTS_TOTAL': '派遣槽封顶，非坐标',
        'BAG_EVERY': '升星间隔，非坐标',
        'BAG_STEPS': '升星步数，非坐标',
        'VERBOSE': '日志开关',
        'DUMP_AT_END': '落盘开关',
        'STOP_AT_5AM': '定时停开关',
        'STOP_TIME': '定时停时刻',
        'OPT': '优化开关',
        'LEARN_TILES': '学习开关',
        'SKIP_SPAWN_CLICK': '跳过开关',
        'MIN_STAMINA_DEFAULT': '体力默认值',
        'MAPS_CONTINUOUS': '连刷标记（UI 侧）',
        'DEADLINE_DEFAULT': '单图超时默认值',
        'MAX_ROUND_DEFAULT': '轮数上限默认值',
        # —— 运行时状态容器（**不是**坐标；字典里没有坐标项，是 v1.20 扫描器的
        #    保守召回：只登记「dict 里含坐标项」会漏，这些是无坐标的状态字典）——
        'STATS': '统计计数器（dict，值全为 int 计数）',
        '_GRID_CALIBRATED': '棋盘自检一次性标志（dict，bool）',
        '_AUTO_SKIP': '自动跳过勾选状态（dict，bool）',
        '_OCR_CH': 'OCR 通道总闸（dict，bool）',
        '_COLLECT': '补点计数器（dict，int）',
    },
}


def _num(node):
    """把 AST 节点还原成 int/float；不是纯数字返回 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    return None


def _coords_of(node):
    """从赋值节点里抽出坐标数字。
    返回 (x, y) / (x,) / None
    """
    if isinstance(node, ast.Tuple):
        vals = [_num(e) for e in node.elts]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 2:
            return (int(vals[0]), int(vals[1]))
        if len(vals) == 1:
            return (int(vals[0]),)
        return None
    v = _num(node)
    return (int(v),) if v is not None else None


def module_consts(path):
    """AST 解析 ⇒ {常量名: (lineno, 节点)}（只取模块级赋值）"""
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read(), filename=path)
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        val = node.value
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id.isupper():
                out[tgt.id] = (node.lineno, val)
    return out


def dict_items(node):
    """dict 字面量 ⇒ {key: (x, y) 或 标量}（只收坐标型 value）"""
    out = {}
    if not isinstance(node, ast.Dict):
        return out
    for k, v in zip(node.keys, node.values):
        if k is None:
            continue
        key = _num(k) if not isinstance(k, ast.Constant) else k.value
        if not isinstance(key, str):
            continue
        c = _coords_of(v)
        if c:
            out[key] = c
    return out


def scan_unregistered(pyd=None, verbose=True):
    """扫手机端所有模块级坐标常量，与 SCAN_SOURCES 求差集。

    返回 (unregistered, registered)：
        unregistered —— [(文件名, 常量名, 行号, 值摘要, 类型)]，未登记的（差集）
        registered   —— [(文件名, 常量名, 行号, 值摘要, kind)]，已登记的
    """
    pyd = pyd or PYD
    unregistered, registered = [], []

    for fname, want in sorted(SCAN_SOURCES.items()):
        path = os.path.join(pyd, fname)
        if not os.path.exists(path):
            if verbose:
                print('   ⚠ 缺文件 %s（跳过扫描）' % fname)
            continue
        consts = module_consts(path)
        exempt = EXEMPT.get(fname, {})

        for name, (shape, kind) in sorted(want.items()):
            if name not in consts:
                unregistered.append((fname, name, 0, '❌源码里没有这个名字', kind))
                continue
            lineno, node = consts[name]
            summary = summarize(node, shape)
            registered.append((fname, name, lineno, summary, kind))

        # 差集：源码里有、SCAN_SOURCES 没登记的**坐标型**模块级常量
        for name, (lineno, node) in sorted(consts.items()):
            if name in want or name in exempt:
                continue
            if not is_coord_like(node):
                continue                      # 非坐标（阈值/开关/字符串…）不归我管
            unregistered.append((fname, name, lineno, summarize(node, '?'), '?'))

    return unregistered, registered


def is_coord_like(node):
    """判断一个模块级赋值「像坐标」：tuple/list of ≥2 数字，或 dict 含坐标项"""
    if isinstance(node, (ast.Tuple, ast.List)):
        if len(_coords_of(ast.Tuple(elts=node.elts)) or ()) >= 2:
            return True
        # 2~4 元的数字 list/tuple（如 QTY_OFF）
        nums = [_num(e) for e in node.elts]
        return all(n is not None for n in nums) and len(nums) >= 2
    if isinstance(node, ast.Dict):
        return bool(dict_items(node))
    return False


def summarize(node, shape):
    """把节点渲染成一行短摘要（给人看，判一眼值合不合理）"""
    if shape == 'band':
        c = _coords_of(node)
        return repr(tuple(c)) if c else '非字面量'
    if shape in ('xy', 'x', 'y', 'quad'):
        c = _coords_of(node)
        return repr(tuple(c)) if c else '非字面量'
    if shape in ('dict', 'tuple'):
        if isinstance(node, ast.Dict):
            items = dict_items(node)
            if items:
                return '{%s}' % ', '.join('%s:%s' % (k, tuple(v)) for k, v in items.items())
            return 'dict(无坐标项)'
        return 'tuple/dict'
    v = _num(node)
    return repr(v) if v is not None else type(node).__name__


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    un, reg = scan_unregistered()
    print('=' * 92)
    print('D. 漏检防呆：手机端坐标常量 vs 面板层清单（AST 扫描）')
    print('=' * 92)
    print('已登记 %d 项：' % len(reg))
    for f, n, ln, s, k in reg:
        print('   %-18s %-22s L%-5d %-34s %s' % (f, n, ln, s, k))
    print()
    if un:
        print('❌ 未登记 %d 项（这些换分辨率时**没人验**）：' % len(un))
        for f, n, ln, s, k in un:
            print('   %-18s %-22s L%-5d %-34s %s' % (f, n, ln, s, k))
        print()
        print('   处置：① 确认它是不是面板层坐标 ② 是 ⇒ 登记进 tools/panel_consts.py')
        print('         的 SCAN_SOURCES 并补 kind/依据 ③ 不是 ⇒ 登记进 EXEMPT 并写理由')
        return 1
    print('✅ 无未登记的坐标常量：面板层清单与源码一致')
    return 0


if __name__ == '__main__':
    sys.exit(main())
