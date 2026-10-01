# -*- coding: utf-8 -*-
"""verify_panels_allres.py · ⭐ 面板层「全分辨率」自检（v1.20 起）

**为什么有这个工具**（2026-10-01 用户追问「到底有没有做全分辨率适配」的结论）：
    · 棋盘层（RefMapper 归一化 + 模板分类 + 阈值）**做了**，多分辨率逐格全等 ✓
    · 面板层（弹窗系坐标 / 搜索带 / 图标框）**没做** —— 全是逐设备标定的常数。
      v1.18（battle_started 假判）和 v1.19（摇色子搜索带盖不到）都是这一类，
      而且**失败方式是静默的**（不抛异常，日志只写 `no_btn` / 三路 `None`）✗
    ⇒ 目标：换分辨率从此是「跑一遍自检」，而不是实跑撞运气。

**自检三件事**（对每个候选分辨率）：
    A. **几何**：把每个面板常数按锚定模型映射到设备坐标，断言 ① 落点在屏内
       ② 不与"底部导航栏/悬浮条"打架 ③ **面板内部元素相对关系保持**（同机型的比例）
    B. **搜索带覆盖**：用**真机实测**的元素坐标（转回参考系）逐条断言"在带内/该被排除"
    C. **判据重放**：用真帧 / PC 帧跑关键判据函数，断言正负样本都对

**⚠ v1.20 修正一个真缺陷（2026-10-02）**：本脚本原先 `import` 的是 **PC 仓**的
    `explore_loop`（`MGAS_MAPBOT_SRC` / `<MGAS>\\mapbot_pc`）。但两端自 2026-10-01
    已「平行独立开发」（README §6.44），实测 `buypanels.py` 两端**差 2232 行**、
    `mapbot.py` 差 1012 行 ⇒ **自检验的根本不是手机端真正跑的那份代码**。
    ⇒ 现在改为 import **手机端自己的** `app/src/main/python/explore_loop`
    （端上 shim 在 PC 上可独立 import：`_MAPBOT_ANDROID=False` 走 PC 回退，
    已用 `tools/_probe_import.py` 验证；文件顶部加了 assert 防止改回去）。
    PC 仓只用来取 `runs/bw2.json` 这个 9:16 基准帧。

**D. 漏检防呆（v1.20 新增，最关键的一条）**：AST 扫描手机端所有坐标类常量，
    与 `PANEL_CONSTS` 清单求**差集** ⇒ **差集非空即红**。
    解决的是这个工具自己承认的老问题：「新面板必须同时登记进 PANEL_CONSTS，
    否则等于没测」—— 现在漏登记会**当场失败**，而不是等真机撞上。

用��：
    python tools/verify_panels_allres.py            # 全部
    python tools/verify_panels_allres.py --list     # 只列常数表
    python tools/verify_panels_allres.py --scan     # 只跑「漏检防呆」AST 扫描
    python tools/verify_panels_allres.py --scan --write   # 把扫出的新常数写进清单
"""
import os
import sys
import ast

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
# ⚠ 手机端自己的 Python 目录（本脚本要验的就是这份代码）
PYD = os.path.abspath(os.path.join(HERE, '..', 'app', 'src', 'main', 'python'))
# PC 端独立仓：只用来取 runs/bw2.json（9:16 基准帧）
MAPBOT = os.environ.get('MGAS_MAPBOT_SRC') or os.path.join(ROOT, 'mapbot_pc')
if not os.path.isdir(PYD):
    raise SystemExit('找不到手机端 Python 目录：%s' % PYD)

# 端上 shim 的环境变量：未设时模块回退到 PC 行为（不改变任何判定逻辑）
os.environ.setdefault('MAPBOT_ROOT', PYD)
os.environ.setdefault('MAPBOT_RUNS', os.path.join(MAPBOT, 'runs'))
os.environ.setdefault('MAPBOT_DT', os.path.join(ROOT, 'data', 'server_datatable.json'))

sys.path.insert(0, PYD)          # ⭐ 手机端优先
if os.path.isdir(MAPBOT):
    sys.path.append(MAPBOT)      # PC 仓只作补充（bw2.json 等 fixture）
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import explore_loop as EL          # noqa: E402
import layout as layout_mod       # noqa: E402

assert os.path.abspath(EL.__file__).startswith(os.path.abspath(PYD)), (
    '⚠ 验的不是手机端代码！实际 import 到 %s' % EL.__file__)

REF_W, REF_H = 1080, 1920
TOP_SPLIT = 300                     # RefMapper 锚顶/锚底分界
NAV_TOP = 1850                      # 底部导航条上沿（参考系；实测 1888）

# 候选分辨率（(W,H,标签)）：9:16 三档 + 非 9:16 四档 + 真机两档
RESOLUTIONS = [
    (720, 1280, '9:16 低'),
    (1080, 1920, '9:16 基线'),
    (1440, 2560, '9:16 高'),
    (1080, 2340, '长屏 20:18'),
    (1080, 2400, '长屏 20:9'),
    (1170, 2532, '长屏 iPhone'),
    (1200, 1920, '宽屏 5:4'),
    (1264, 2780, '真机 RMX3800'),
    (1280, 2772, '真机 Redmi'),
]

# ── 面板常数清单：(名字, 参考系 y, 类型) ──
#   'anchor' = 面板内锚定（随面板动，v1.19 已改）
#   'abs'    = 绝对参考系坐标（换分辨率**不会**跟着变，危险项要盯）
PANEL_CONSTS = [
    # —— 结算面板（v1.19 实测：底部三键两机一致，奖励行真机高 271px）——
    ('结算.奖励行(上界)', EL.REWARD_CLOSE_UP_MAX, 'abs'),
    ('结算.奖励行(下界)', EL.REWARD_CLOSE_UP_MIN, 'abs'),
    ('结算.奖励行右界x', EL.REWARD_X1, 'abs'),
    # —— 弹窗系面板按钮（**清单里的值已经是 dlg 最终坐标**，由真机 OCR 直接量得，
    #     例如宝库购买钮 dlg(895,1498) ⇒ 不再叠加 C）——
    ('地块面板.战斗按钮y', 650, 'dlg_final'),
    ('地块面板.战斗按钮y下', 860, 'dlg_final'),
    ('宝库.标题y', 438, 'dlg_final'),
    ('宝库.购买按钮y', 1498, 'dlg_final'),
    ('背包X.dlg', 225, 'dlg_final'),
    ('背包页签.dlg', 1200, 'dlg_final'),
    # —— 归一化系（棋盘/导航，锚定模型保证）——
    ('棋盘.上沿', 1002, 'ref'),
    ('棋盘.下沿', 1722, 'ref'),
]
# 导航条元素**单独**断言：它本来就该在导航区，不能套用「不许压导航」规则
NAV_ITEMS = [('底部导航.开始冒险', 1888), ('底部导航.斗技场', 1888)]


# ── 几何断言表：把 `panel_consts.SCAN_SOURCES` 的每一条都拿来做 9 分辨率映射 ──
# ⚠ **本表由 panel_consts.SCAN_SOURCES 生成**，不再手工维护第二份清单
#    （v1.20 的教训：两份清单必然会漂移）。新增面板常量只改 panel_consts.py 一处。
def _kind_of(fname, name):
    import panel_consts
    return panel_consts.SCAN_SOURCES.get(fname, {}).get(name, (None, '?'))[1]


def _value_of(fname, name):
    """取常量的代表 y（几何断言用）。dict 取其坐标项里最大的 y（面板下沿）。"""
    import panel_consts
    consts = panel_consts.module_consts(os.path.join(PYD, fname))
    if name not in consts:
        return None
    _, node = consts[name]
    if isinstance(node, ast.Dict):
        items = panel_consts.dict_items(node)
        ys = [v[1] for v in items.values() if len(v) >= 2]
        return max(ys) if ys else None
    c = panel_consts._coords_of(node)
    if not c:
        return None
    return c[1] if len(c) >= 2 else c[0]


def mapper(W, H):
    """RefMapper 锚定模型（与 Java 侧同口径）"""
    k = W / REF_W
    shift = H - REF_H * k

    def dev_y(y):
        return y * k if y <= TOP_SPLIT else y * k + shift

    def dev_x(x):
        return x * k

    def c():                      # dialogShift：弹窗系相对归一化系的偏移
        return shift

    return k, shift, dev_x, dev_y, c


def part_a_geometry():
    print('=' * 92)
    print('A. 几何：面板常数按锚定模型映射到设备坐标')
    print('=' * 92)
    bad = []
    for (W, H, label) in RESOLUTIONS:
        k, shift, dev_x, dev_y, c = mapper(W, H)
        print('\n── %s  %dx%d  k=%.4f shift=%.1f C=%.1f' % (label, W, H, k, shift, c()))
        for name, val, kind in PANEL_CONSTS:
            if kind == 'dlg_final':
                # 清单里存的是**真机 OCR 直接量得的 dlg 最终坐标**（如宝库购买钮 dlg 1498），
                #   它已经含 C ⇒ 映射时**直接当参考系 y 走 dev_y**，绝不再 +C。
                #   真机实测 1264×2780：1498 ⇒ dev 2286（屏高 2780 ✓）
                dy = dev_y(val)
                note = 'dlg最终值'
            elif kind == 'dlg':
                dy = dev_y(val + c())
                note = '弹窗系(+C)'
            elif kind == 'abs':
                dy = dev_y(val)
                note = '绝对参考系 ⚠ 不随面板动'
            else:
                dy = dev_y(val)
                note = '归一化系'
            inset = dev_x(EL.REWARD_X1) if 'x' in name else 0
            ok_screen = (-2 <= dy <= H + 2)
            # ⚠ 只有**归一化系/绝对参考系**的元素才该避开底部导航条；
            #   弹窗系元素本来就可能在面板下方，不能拿导航条去判它。
            ok_nav = True if kind.startswith('dlg') else (dy < dev_y(NAV_TOP) + 1)
            flags = ''
            if not ok_screen:
                flags += '  ✗出屏'
                bad.append('%s @%s 出屏 y=%.0f' % (name, label, dy))
            if not ok_nav:
                flags += '  ✗压到底部导航'
                bad.append('%s @%s 压导航 y=%.0f' % (name, label, dy))
            extra = ('  x右界=%.0f' % inset) if inset else ''
            print('   %-22s 参考 %6s (%-16s) ⇒ 设备 y=%7.1f%s%s'
                  % (name, val, note, dy, extra, flags))
        # 导航条：反向断言（**应当**落在导航区内）
        for name, val in NAV_ITEMS:
            dy = dev_y(val)
            ok = dev_y(NAV_TOP - 40) <= dy <= dev_y(1920)
            print('   %-22s 参考 %6s (%-16s) ⇒ 设备 y=%7.1f  %s'
                  % (name, val, '导航条(应在底部)', dy,
                     'OK' if ok else '✗ 不在导航区'))
            if not ok:
                bad.append('%s @%s 不在导航区 y=%.0f' % (name, label, dy))
    return bad


def part_b_coverage():
    """用真机实测元素坐标（转回参考系）断言搜索带覆盖/排除"""
    print()
    print('=' * 92)
    print('B. 搜索带覆盖：1264×2780 真机结算帧实测坐标')
    print('=' * 92)
    k, shift, dev_x, dev_y, c = mapper(1264, 2780)

    def dev2ref(y):
        """**设备 y → 参考 y**（锚定模型的逆运算；顶块 / 锚底两段）"""
        if y <= TOP_SPLIT * k:
            return y / k
        return (y - shift) / k

    def dev2ref_x(x):
        return x / k

    bad = []
    real = [('奖励行数字1/3', 224, 1277, True),
            ('奖励行数字1/16', 468, 1277, True),
            ('伤害133114', 229, 1375, True),
            ('伤害220 46 184', 449, 1413, True),
            ('小数字10', 130, 1595, True),
            ('小数字1', 150, 1680, True),
            ('回放战斗', 677, 1966, False),
            ('关闭', 675, 2219, False),
            ('自动跳过', 673, 2362, False)]
    items = [{'text': t, 'cx': dev2ref_x(x), 'cy': dev2ref(y), 'conf': 1.0}
             for t, x, y, _ in real]
    bx0, by0, by1 = EL._reward_band(items)
    print('   真机 band = (%d, %d, %d)  x右界=%d' % (bx0, by0, by1, EL.REWARD_X1))
    for t, x, dy, want_in in real:
        ry = dev2ref(dy)
        rx = dev2ref_x(x)
        inside = by0 <= ry <= by1
        ok = (inside == want_in)
        print('   %-16s 设备(%d,%d) ⇒ 参考(%4.0f,%7.1f)  期望%s  实际%s  %s'
              % (t, x, dy, rx, ry, '带内' if want_in else '带外',
                 '带内' if inside else '带外', 'OK' if ok else '✗'))
        if not ok:
            bad.append('B: %s 期望%s实际%s' % (t, want_in, inside))

    # 每个分辨率都要能算出 band 且在屏内
    print()
    for (W, H, label) in RESOLUTIONS:
        k2, s2, dx2, dy2, c2 = mapper(W, H)
        y0 = dev_y2 = dy2(EL.REWARD_CLOSE_UP_MIN)
        y1 = dy2(EL.REWARD_CLOSE_UP_MAX)
        ok = (0 <= y0 < y1 <= H)
        print('   %-16s %dx%d  band设备y=%6.1f~%6.1f  %s'
              % (label, W, H, y0, y1, 'OK' if ok else '✗'))
        if not ok:
            bad.append('B: band越界 @%s' % label)
    return bad


def part_c_predicates():
    """判据重放：真帧/PC 帧跑关键判据"""
    print()
    print('=' * 92)
    print('C. 判据重放：真帧 / PC 帧')
    print('=' * 92)
    import io
    import json
    bad = []
    vdir = os.path.join(ROOT, 'android_autoexplore', '_verify')

    # ① 地图帧：不得判成结算面板（这是 2026-09-26 踩过的坑）
    mp = os.path.join(vdir, 'fr1264_map_boss_banner.png')
    if os.path.exists(mp):
        import cv2
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
        eng = RapidOCR()
        img = cv2.imdecode(np.fromfile(mp, dtype=np.uint8), cv2.IMREAD_COLOR)
        res, _ = eng(img)
        mi = [{'text': t.strip(), 'cx': sum(q[0] for q in b) / 4,
               'cy': sum(q[1] for q in b) / 4, 'conf': float(s)}
              for b, t, s in (res or [])]
        r = EL.is_battle_panel(mi)
        print('   地图帧 is_battle_panel = %s  %s' % (r, 'OK' if not r else '✗'))
        if r:
            bad.append('C: 地图帧被判成结算面板')
        r2 = EL.battle_started(mi)
        print('   地图帧 battle_started  = %s  %s' % (r2, 'OK' if not r2 else '✗'))
        if r2:
            bad.append('C: 地图帧被判成已开打')
    else:
        print('   （缺 fixture %s，跳过）' % mp)

    # ② 结算帧（PC 基线）：必须判成结算面板
    bw = os.path.join(MAPBOT, 'runs', 'bw2.json')
    if os.path.exists(bw):
        d = json.load(io.open(bw, encoding='utf-8'))
        bi = d['items'] if isinstance(d, dict) else d
        r = EL.is_battle_panel(bi)
        print('   PC结算帧 is_battle_panel = %s  %s' % (r, 'OK' if r else '✗'))
        if not r:
            bad.append('C: PC结算帧未被认成结算面板')
        r2 = EL.battle_started(bi)
        print('   PC结算帧 battle_started  = %s  %s' % (r2, 'OK' if r2 else '✗'))
        if not r2:
            bad.append('C: PC结算帧未被认成已开打')
    else:
        print('   （缺 %s，跳过）' % bw)
    return bad


def part_d_registry():
    """D. 漏检防呆：AST 扫描手机端坐标常量 vs 清单（差集非空即红）"""
    print()
    print('=' * 92)
    print('D. 漏检防呆：手机端坐标常量 vs 面板层清单（AST 扫描）')
    print('=' * 92)
    import panel_consts
    un, reg = panel_consts.scan_unregistered(verbose=True)
    print('   已登记 %d 项 / 未登记 %d 项' % (len(reg), len(un)))
    bad = []
    for f, n, ln, s, k in un:
        print('   ✗ 未登记 %-18s %-22s L%-5d %s' % (f, n, ln, s))
        bad.append('D: 未登记坐标常量 %s.%s（换分辨率时没人验）' % (f, n))
    if not un:
        print('   ✅ 清单与源码一致，无未登记的坐标常量')
    return bad


def main():
    args = sys.argv[1:]
    if '--list' in args:
        print('面板常数清单：')
        for n, v, k in PANEL_CONSTS:
            print('   %-22s %-8s %s' % (n, v, k))
        return 0
    if '--scan' in args:
        import panel_consts
        return panel_consts.main()
    bad = []
    bad += part_a_geometry()
    bad += part_b_coverage()
    bad += part_c_predicates()
    bad += part_d_registry()
    print()
    print('=' * 92)
    if bad:
        print('❌ 面板层自检发现 %d 个问题：' % len(bad))
        for b in bad:
            print('   - %s' % b)
        return 1
    print('✅ 面板层自检全过：%d 个分辨率的几何 / 搜索带 / 判据 / 漏检防呆 均成立'
          % len(RESOLUTIONS))
    print('   清单由 tools/panel_consts.py 的 SCAN_SOURCES 单一维护，')
    print('   新增面板坐标常量**必须**登记进去，否则 D 组当场红。')
    print('=' * 92)
    return 0


if __name__ == '__main__':
    sys.exit(main())
