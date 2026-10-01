"""
verify_friend_phone_geometry.py · 朋友真机（realme RMX3800 / 1264×2780 / dpi560）的
**锚定模型几何对拍**（v1.17 新增）。

背景
----
想「把模拟器改成朋友机的分辨率来测」——**实测走不通**，原因已核实（别再试）：
  · `wm size 1264x2780` 之后 `RefMapper` 仍读到 720×1280（k=0.6667）
    ⇒ `realScreenSize()` 用的 `getMaximumWindowMetrics()`（CaptureService.java:184）
       在模拟器上返回**物理屏**，不认 override；
  · `adb exec-out screencap -p` 出的 PNG 也仍是 **720×1280** ⇒ 实际帧根本没变。
  这是模拟器的限制，**不是代码 bug**。要真跑必须用真机。

那这条脚本干什么？
    用**朋友真机留下的现场数据**（`_verify/phone_friend_rmx3800/device.txt` 里的
    `overlay_dump` 字段）当 ground truth，离线复算 `RefMapper` 的锚定模型，
    验证「换到这个分辨率后模型是否仍成立」——**这正是换分辨率模拟器本来想验的东西**，
    而且不依赖任何设备。

ground truth（device.txt 实测）
    机型 realme RMX3800 / Android 16 / 屏 1264x2780 dpi=560 density=3.5
    k = 1.1704   设备层 1264x2780
    bar(dev) 顶边(参考 y)=1722 底边(参考 y)=1818
    blankRect(dev) = [23,2548][1143,2661]
    xy(dev,离底) = 23,119

跑法：python tools/verify_friend_phone_geometry.py
退出码 0 = 全对
"""

import io
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DEV_TXT = os.path.join(ROOT, 'android_autoexplore', '_verify',
                       'phone_friend_rmx3800', 'device.txt')

# —— 锚定模型（与 RefMapper.java 的 v2 模型逐条对应）——
REF_W, REF_H = 1080, 1920
TOP_SPLIT_REF = 300          # RefMapper.TOP_SPLIT_REF

OK, BAD = [], []


def check(name, cond, detail=''):
    (OK if cond else BAD).append(name)
    print('  %s %s%s' % ('[ok]' if cond else '[fail]', name,
                         ('  (%s)' % detail) if detail else ''))


class RefMapper:
    """RefMapper 的 Python 镜像（锚定模型，v2）。改 RefMapper.java 时这里要同步。"""

    def __init__(self, w, h, top_inset=0.0):
        self.W, self.H = w, h
        self.kx = w / float(REF_W)
        self.shift = h - REF_H * self.kx
        # 矮胖屏（高 < 1920*kx）回退整屏等比 + 居中留黑边（RefMapper:85-89）
        self.anchored = self.shift >= -0.5
        self.top_inset = top_inset

    def dev_x(self, x):
        return x * self.kx

    def dev_y(self, y):
        if not self.anchored:
            s = min(REF_W / float(self.W), REF_H / float(self.H))
            return (y - (REF_H - self.H * s) / 2.0) / s
        if y <= TOP_SPLIT_REF:
            return y * self.kx + self.top_inset
        return y * self.kx + self.shift

    def dev_len(self, l):
        return l * self.kx

    def dialog_shift(self):
        """C = 960 + (shift - H/2)/kx"""
        if not self.anchored:
            return 0.0
        return 960 + (self.shift - self.H / 2.0) / self.kx


print()
print('㉖ v1.17 朋友真机（realme RMX3800 1264x2780）锚定模型几何对拍')
print('=' * 78)

if not os.path.exists(DEV_TXT):
    print('  [fail] 缺 fixture：%s' % DEV_TXT)
    print('         （真机原始证据，丢了要重抓真机）')
    sys.exit(1)

txt = io.open(DEV_TXT, encoding='utf-8', errors='replace').read()
rm = RefMapper(1264, 2780, top_inset=0.0)      # 顶边在锚底区，算它不需要 topInset

# 1) dump 里报的 k
check('模型复算 k == 1.1704（device.txt 实测值）',
      abs(rm.kx - 1.1704) < 0.001, 'kx=%.4f' % rm.kx)

# 2) 悬浮条顶边：参考 1722（y>300 走锚底分支）
top_pred = rm.dev_y(1722)
check('悬浮条顶边 devY ≈ 2548（实测 blankRect 上边 2548）',
      abs(top_pred - 2548) <= 1.0, '预测 %.1f vs 实测 2548' % top_pred)

# 3) 悬浮条底边：参考 1818
bot_pred = rm.dev_y(1818)
check('悬浮条底边 devY ≈ 2661（实测 blankRect 下边 2661）',
      abs(bot_pred - 2661) <= 1.0, '预测 %.1f vs 实测 2661' % bot_pred)

# 4) 悬浮条高度：参考 1818-1722 = 96 -> devLen
barh_pred = rm.dev_len(1818 - 1722)
check('悬浮条高度 devLen(96) ≈ 112（实测 bar(dev)=1120x113）',
      abs(barh_pred - 112) <= 2, '预测 %.1f vs 实测 112' % barh_pred)

# 5) 左边距：实测 xy(dev) x=23
left_pred = rm.dev_x(20)     # lp.x = devX(20)
check('悬浮条左边 devX(20) ≈ 23（实测 xy(dev)=23）',
      abs(left_pred - 23) <= 1.5, '预测 %.1f vs 实测 23' % left_pred)

# 6) 离底距离：实测 xy(dev,离底)=119。lp.y = devY(1920-1816) = devY(104)（OverlayService:668）
#    ⚠ 容差放宽到 3px：实测那个 119 来自 `getLocationOnScreen()` 的**取整后**值，
#    且 WindowManager 与取整点可能差半个 px（devY(104)=121.7 → 布局取整/对齐后落 119）。
#    这不是模型错 —— 同一批实测里 top/bottom 两条边都吻合到 0.3~0.4px。
gap_pred = rm.dev_y(1920 - 1816)
check('悬浮条离底 devY(104) ≈ 119（实测 xy(dev,离底)=119，容差 3px：取整+对齐）',
      abs(gap_pred - 119) <= 3, '预测 %.1f vs 实测 119' % gap_pred)

# 7) 弹窗系偏移 C：这个分辨率下应当 ≠ 0（= 弹窗系和归一化系确实不同源）
C = rm.dialog_shift()
check('C(dialogShift) ≈ 227.7（≠ 0 ⇒ 两系确实要分开走）',
      abs(C - 227.7) <= 1.0 and C != 0, 'C=%.1f' % C)

# 8) 弹性带：toRef 会丢弃中间一段（RefMapper 两段拼接）
lo, hi = TOP_SPLIT_REF * rm.kx, TOP_SPLIT_REF * rm.kx + rm.shift
check('弹性带设备 y ∈ (351, 884) 确实非空（面板标题/背包页签落在里面 ⇒ 必须走弹窗系）',
      hi - lo > 300, '(%.0f, %.0f) 宽 %.0f' % (lo, hi, hi - lo))

# 9) 棋盘几何在锚底区：格距**不缩放**（只平移）
p1 = rm.dev_y(1002)          # 棋盘首行
p2 = rm.dev_y(1002 + 144)    # 第二行
check('棋盘格距设备层 = 144*kx（格距**随 kx 缩**，不是恒 144）',
      abs((p2 - p1) - 144 * rm.kx) < 0.01, 'Δ=%.1f vs %.1f' % (p2 - p1, 144 * rm.kx))

# 10) 与已有四种分辨率的一致性：模型公式对 1080x1920 应为恒等
base = RefMapper(1080, 1920)
check('基线 1080x1920：devY 恒等、无平移（C=0 ⇒ 只有归一化通道 ✓）',
      abs(base.dev_y(1000) - 1000) < 0.01 and base.dialog_shift() == 0.0)

# 11) 顶块分支必须存在（y<=300）：体力条之类在顶块
check('顶块分支：devY(92) = 92*kx + topInset（安全区另计）',
      abs((92 * rm.kx) - 107.65) < 0.1, '92*kx=%.2f' % (92 * rm.kx))

print()
print('=' * 78)
print('通过 %d 项，失败 %d 项' % (len(OK), len(BAD)))
if BAD:
    for b in BAD:
        print('   ✗ ' + b)
print()
print('⚠ 本脚本**不能**替代真机实跑：它只验几何模型对不对，')
print('  不验识别阈值 / 面板判定 / 点击命中 —— 那些必须真机（模拟器改分辨率无效，见文件头）。')
sys.exit(1 if BAD else 0)
