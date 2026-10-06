# -*- coding: utf-8 -*-
"""make_app_icon.py · 生成 MGAS 启动器图标（**机甲核心魔偶**，官方像素头像）

用法（在仓根或任意目录都可）：
    python android_autoexplore/tools/make_app_icon.py

════════════════════════════════════════════════════════════════════════
为什么是「机甲核心魔偶」、为什么头像不是手绘的
════════════════════════════════════════════════════════════════════════
用户口径：「MGAS头像改成机甲核心魔偶的像素头像」，并提示
「幻想少女公会那边有头像 head_atlas.png|json」⇒ **用官方图集，别手绘**。

* 官方图集：`D:\\幻想少女公会\\headless_battle\\ui\\assets\\img\\head_atlas.png`
  （`head_atlas.json`：`cell=30, cols=16` ⇒ 索引 i → `divmod(i, 16)` 得 row/col）
* 「机甲核心魔偶」在 `server_datatable.json` 里**只出现一次**：
  表 `Unique` / 行 `unique_143` / 字段 `PositiveTags`，同一行的
  `IDs = M31302_000`、`Owner = 核心魔偶`、`Name = 全面压制`、`FullScreen = 1`
  ⇒ 「机甲核心魔偶」**就是 `M31302_000` 的机甲形态**，它的官方 30×30 头像
  = 图集索引 **167**（row 10, col 7）✓
* 头像像素已按索引 167 切好、**入库**在 `tools/icon/head_M31302_000.png`
  （30×30 RGBA，1947 B）—— 本脚本只读这一份，**不再依赖游戏仓在场** ✓

⚠ 上一版是**手绘蓝发少女**，依据是旧 docstring 里一句「图集那格是半身、还烘了背景」
—— 那句话**是错的**（官方图集每个角色都有一格干净的 30×30 头像）✗
⇒ 现在头像**逐像素取自官方图集**，只允许 NEAREST 放大，绝不重采样。

════════════════════════════════════════════════════════════════════════
画布为什么是 48 格（不是 30）
════════════════════════════════════════════════════════════════════════
* 30×30 的官方格**原样 1:1 贴上去**（不缩放 —— 缩放真像素画会丢真像素、发糊 ✗）；
  不透明包围盒 23×20 ⇒ 落在 x 12..34、y 14..33。
* 自适应图标 108dp，**只有中心 66dp 圆保证可见** ⇒ 头像最外那个不透明像素
  必须落在圆心 33dp 内。该像素距圆心 **13.73 格**：
      40 格画布 → 13.73/40×108 = **37.1dp** ⇒ **会被圆形启动器切掉** ✗
      48 格画布 → 13.73/48×108 = **30.9dp** ⇒ 稳稳在圆内 ✓
* 48 同时整除各密度旧版尺寸（48/96/144/192 = 1/2/3/4 倍）⇒ 栅格尽量落在整格边界。

产出（覆盖写 `app/src/main/res/`）：
    mipmap-<dpi>/ic_launcher.png             旧版方形图标
    mipmap-<dpi>/ic_launcher_round.png       旧版圆形图标
    mipmap-<dpi>/ic_launcher_foreground.png  自适应前景（108dp，只有头像）
    mipmap-<dpi>/ic_launcher_background.png  自适应背景（108dp，底板）
    out/final_512.png、final_1024.png、final_1024_round.png   人工审阅用
⚠ 图标在 `res/` 里 ⇒ **只能整包重装**才上真机，热更新永远带不到（见 AGENTS.md §2.2）
"""
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
RES = os.path.join(PROJ, 'app', 'src', 'main', 'res')
OUT = os.path.join(HERE, 'out')
HEAD_SRC = os.path.join(HERE, 'icon', 'head_M31302_000.png')

LOGIC = 48                    # 逻辑格数（见文件头「画布为什么是 48 格」）
CX = CY = LOGIC / 2.0 - 0.5   # 画布中心（23.5, 23.5）

DPI = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}

P = {
    'void':   (0x12, 0x11, 0x1A),
    'bg':     (0x26, 0x24, 0x33),
    'bg_hi':  (0x2E, 0x2B, 0x3C),
    'grid':   (0x3B, 0x39, 0x4D),
    'halo':   (0x00, 0x3D, 0x7A),
    'halo2':  (0x00, 0x2B, 0x57),
}


# ----------------------------------------------------------- PNG 编解码 --
def write_png(path, w, h, rgba):
    """最小 PNG 编码器（RGBA / bit depth 8 / color type 6）。"""
    raw = bytearray()
    for y in range(h):
        raw.append(0)                      # filter type 0
        raw += rgba[y*w*4:(y+1)*w*4]

    def chunk(typ, data):
        c = struct.pack('>I', len(data)) + typ + data
        return c + struct.pack('>I', zlib.crc32(typ + data) & 0xFFFFFFFF)

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)


def read_png(path):
    """最小 PNG 解码器（只支持 RGBA / bpp=4 —— 图集格就是这个格式）。"""
    with open(path, 'rb') as f:
        d = f.read()
    pos, idat, w, h = 8, b'', None, None
    while pos < len(d):
        ln = struct.unpack('>I', d[pos:pos+4])[0]
        typ = d[pos+4:pos+8]
        if typ == b'IHDR':
            w, h, _bd, _ct, _cm, _fm, _il = struct.unpack(
                '>IIBBBBB', d[pos+8:pos+8+ln])
        elif typ == b'IDAT':
            idat += d[pos+8:pos+8+ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    bpp = 4
    stride = w * bpp
    out = bytearray()
    prev = bytearray(stride)
    i = 0
    for _y in range(h):
        f = raw[i]
        i += 1
        line = bytearray(raw[i:i+stride])
        i += stride
        for x in range(stride):
            a = line[x-bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x-bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x]+a) & 255
            elif f == 2:
                line[x] = (line[x]+b) & 255
            elif f == 3:
                line[x] = (line[x]+(a+b)//2) & 255
            elif f == 4:
                p = a+b-c
                pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x]+pr) & 255
        out += line
        prev = line
    return w, h, out


# --------------------------------------------------- 官方图集头像格读取 --
def load_cells(path):
    """读 30×30 RGBA 格 ⇒ [(x, y, (r,g,b)), ...]（丢掉 alpha<100 的柔边）。"""
    w, h, buf = read_png(path)
    cells = []
    for y in range(h):
        for x in range(w):
            o = (y*w + x) * 4
            a = buf[o+3]
            if a >= 100:                   # 只认实体像素，忽略抗锯齿边
                cells.append((x, y, (buf[o], buf[o+1], buf[o+2])))
    return w, h, cells


def bbox(cells):
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    return min(xs), min(ys), max(xs), max(ys)


def place_native(cells):
    """把图集格**原样 1:1** 摆到画布中心（不缩放）。"""
    x0, y0, x1, y1 = bbox(cells)
    bw, bh = x1-x0+1, y1-y0+1
    dx = (LOGIC - bw) // 2
    dy = (LOGIC - bh) // 2
    return ([(x-x0+dx, y-y0+dy, c) for x, y, c in cells],
            (dx, dy, bw, bh))


# --------------------------------------------------------------- 底板 --
def plate():
    """底板：抖色 + 地图网格边 + 一圈**很暗**的能量环（给头像做框，不抢戏）。"""
    g = [[P['bg']]*LOGIC for _ in range(LOGIC)]
    for y in range(LOGIC):
        for x in range(LOGIC):
            if (x*2 + y) % 7 == 0:
                g[y][x] = P['bg_hi']
    for y in range(LOGIC):
        for x in range(LOGIC):
            if min(x, y, LOGIC-1-x, LOGIC-1-y) <= 1 and (x % 5 == 0 or y % 5 == 0):
                g[y][x] = P['grid']
    for y in range(LOGIC):
        for x in range(LOGIC):
            d2 = (x-CX)**2 + (y-CY)**2
            if 256 <= d2 <= 306:           # r 16.0 .. 17.5
                g[y][x] = P['halo']
            elif 306 < d2 <= 361:          # r 17.5 .. 19.0
                g[y][x] = P['halo2']
    return g


# ------------------------------------------------------------- 组装 --
_w, _h, _cells = load_cells(HEAD_SRC)
_head_cells, (_dx, _dy, _bw, _bh) = place_native(_cells)
HEAD_BOX = (_dx, _dy, _dx+_bw-1, _dy+_bh-1)

# 只有头像、其余透明 —— 自适应前景层（背景层由启动器/背景图提供）
head_px = [[None]*LOGIC for _ in range(LOGIC)]
for _x, _y, _c in _head_cells:
    head_px[_y][_x] = _c

# 完整方形图标 = 底板 + 官方头像（原生比例）
px = plate()
for _x, _y, _c in _head_cells:
    px[_y][_x] = _c


# --------------------------------------------------------- 栅格工具 --
def buf_from(grid):
    """LOGIC×LOGIC 网格 ⇒ RGBA 字节串（None = 透明）。"""
    b = bytearray(LOGIC*LOGIC*4)
    for y in range(LOGIC):
        for x in range(LOGIC):
            c = grid[y][x]
            if c:
                d = (y*LOGIC + x) * 4
                b[d], b[d+1], b[d+2], b[d+3] = c[0], c[1], c[2], 255
    return b


def scale_nn(src, out_size):
    """NEAREST 放大到 out_size（**绝不插值** —— 像素画必须保持硬边）。"""
    f = out_size / float(LOGIC)
    o = bytearray(out_size*out_size*4)
    for y in range(out_size):
        sy = min(LOGIC-1, int(y/f))
        for x in range(out_size):
            sx = min(LOGIC-1, int(x/f))
            s = (sy*LOGIC + sx) * 4
            d = (y*out_size + x) * 4
            o[d:d+4] = src[s:s+4]
    return o


def masked(radius):
    """方形图标按 radius 切圆角（旧版 round 图标用）。"""
    g = [list(r) for r in px]
    for y in range(LOGIC):
        for x in range(LOGIC):
            if (x-CX)**2 + (y-CY)**2 > radius**2:
                g[y][x] = None
    return g


def bg_grid():
    """自适应背景层：纯底板（启动器自己会蒙版）。"""
    g = [[P['bg']]*LOGIC for _ in range(LOGIC)]
    for y in range(LOGIC):
        for x in range(LOGIC):
            if (x*2 + y) % 7 == 0:
                g[y][x] = P['bg_hi']
    for y in range(LOGIC):
        for x in range(LOGIC):
            if min(x, y, LOGIC-1-x, LOGIC-1-y) <= 2 and (x % 5 == 0 or y % 5 == 0):
                g[y][x] = P['grid']
    return g


# --------------------------------------------------- 安全区自检（dp）--
def safe_zone_dp():
    """头像最外不透明像素距圆心多少 dp（自适应图标保证可见半径 = 33dp）。

    ⚠ 这个数**必须 ≤ 33**，否则圆形启动器会切到头像 ✗ —— 40 格画布就是栽在这
      （37.1dp）；换 48 格后是 30.9dp ✓
    """
    import math
    worst = 0.0
    for _x, _y, _c in _head_cells:
        r = math.hypot(_x-CX, _y-CY)
        if r > worst:
            worst = r
    return worst, worst / LOGIC * 108.0


if __name__ == '__main__':
    _r, _dp = safe_zone_dp()
    _bx0, _by0, _bx1, _by1 = bbox(_cells)
    print('图集格 %dx%d  不透明 %d px  包围盒 x %d..%d y %d..%d'
          % (_w, _h, len(_cells), _bx0, _bx1, _by0, _by1))
    print('画布 %dx%d  头像落在 x %d..%d y %d..%d（原生 1:1，%d px）'
          % (LOGIC, LOGIC, HEAD_BOX[0], HEAD_BOX[2], HEAD_BOX[1], HEAD_BOX[3],
             len(_head_cells)))
    print('头像最外像素距圆心 %.2f 格 = %.1f dp；自适应保证可见半径 33.0 dp ⇒ %s'
          % (_r, _dp, '在圆内 ✓' if _dp <= 33.0 else '会被切 ✗'))
    assert _dp <= 33.0, '头像超出 66dp 安全圆：%.1f dp > 33 dp' % _dp

    os.makedirs(OUT, exist_ok=True)
    square = buf_from(masked(24.0))
    circle = buf_from(masked(23.04))
    fg = buf_from(head_px)
    bg = buf_from(bg_grid())

    write_png(os.path.join(OUT, 'final_512.png'), 512, 512, scale_nn(square, 512))
    write_png(os.path.join(OUT, 'final_1024.png'), 1024, 1024, scale_nn(square, 1024))
    write_png(os.path.join(OUT, 'final_1024_round.png'), 1024, 1024,
              scale_nn(circle, 1024))

    for name, s in DPI.items():
        d = os.path.join(RES, 'mipmap-' + name)
        os.makedirs(d, exist_ok=True)
        fs = int(round(s * 108 / 48.0))     # 该密度下 108dp 的像素数
        write_png(os.path.join(d, 'ic_launcher.png'), s, s, scale_nn(square, s))
        write_png(os.path.join(d, 'ic_launcher_round.png'), s, s, scale_nn(circle, s))
        write_png(os.path.join(d, 'ic_launcher_foreground.png'), fs, fs,
                  scale_nn(fg, fs))
        write_png(os.path.join(d, 'ic_launcher_background.png'), fs, fs,
                  scale_nn(bg, fs))
        print('  mipmap-%-8s 旧版 %3dpx  自适应 %3dpx' % (name, s, fs))
    print('已写入 %s' % RES)
