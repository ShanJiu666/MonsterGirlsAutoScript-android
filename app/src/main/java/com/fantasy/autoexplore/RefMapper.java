package com.fantasy.autoexplore;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;

/**
 * 参考系换算（全分辨率适用的核心）。v2 · 2026-09-29 真机实测后重写。
 *
 * <h2>游戏在非 9:16 屏上的真实布局方式（1080×2400 实测）</h2>
 * 游戏把 UI 分成两段，<b>不是</b>整屏等比缩放：
 * <ul>
 *   <li><b>顶块</b>（参考 y ≤ {@link #TOP_SPLIT_REF}）：顶部 HUD/标题栏，<b>锚顶</b> —— 设备 y == 参考 y（W=1080 时）</li>
 *   <li><b>其余</b>（棋盘 / 底部面板 / 底部导航 / 各弹窗按钮）：<b>锚底</b> —— 设备 y = 参考 y + (H − 1920)，纯平移、
 *       <b>不缩放</b>（格距 144 在 2400 屏上仍是 144）</li>
 *   <li>x 方向：宽度恒等于设计稿 1080 ⇒ x 1:1（底部导航五个按钮 x 与 1920 屏逐像素一致，Δ ≤ 1px）</li>
 *   <li>中间「世界场景」是弹性区（多出来的高度全被它吃掉），脚本从不在那里点东西</li>
 * </ul>
 * 实测数据（1080×2400 vs 1080×1920 基线）：底部导航 +480.0、进入地图 +479.6、深渊入口 +480.5、
 * 顶部 HUD ±1；按本模型把 2400 实拍图合成 1080×1920 参考帧后，PC 分类器 35/35 格、中位分 0.910
 * （与 1920 基线 0.910 完全一致）⇒ 模型成立。
 *
 * <h2>换算公式（anchored 模式，shift = H − 1920·kx ≥ 0）</h2>
 * <pre>
 *   kx    = W / 1080                       （宽度驱动缩放；9:16 屏上同时也是 1920/H）
 *   shift = H − 1920·kx                    （9:16 屏 = 0 ⇒ 与旧「整屏等比」逐像素一致 ✓）
 *   devX(x) = x·kx
 *   devY(y) = y·kx              (y ≤ 300，顶块)
 *   devY(y) = y·kx + shift      (y &gt;  300，锚底区)
 *   devLen(l) = l·kx            （两段斜率都是 kx ⇒ 尺寸换算全屏统一）
 * </pre>
 *
 * <p>⚠ H &lt; 1920·kx（比 9:16 更"矮胖"的屏，如 1200×1920）：两段会重叠，模型不适用
 * ⇒ 自动回退旧的「整屏等比 + 居中留黑边」（9:16 家族的行为不变）。</p>
 *
 * <h2>历史 bug（保留警示）</h2>
 * 旧 toRef 的目标框写成 {@code 1080k × 1920k}，而 9:16 屏上它恰好等于 W×H ⇒ drawBitmap
 * 是 1:1 平移、根本没缩放（720×1280 只占画布左上角、1440×2560 被裁）。已改。
 */
public final class RefMapper {

    public static final int REF_W = 1080;
    public static final int REF_H = 1920;
    /**
     * 顶块边界（参考 y）。实测：y=277（当前难度）仍是锚顶，y=746（选图列表）已是锚底；
     * 中间 300~746 是弹性"世界场景"（脚本不在那里点击）⇒ 取 300。
     * ⚠ 若以后发现有 UI 元素落在 300~746 且是锚顶的，再调这个值。
     */
    public static final int TOP_SPLIT_REF = 300;

    // ── anchored 模式参数 ──
    private static volatile float kx = 1f;       // device-per-ref（x、y 斜率相同）
    private static volatile float shift = 0f;    // 锚底区整体下移量
    private static volatile boolean anchored = true;
    /**
     * 顶块的安全区偏移（状态栏/挖孔，设备像素）。真机（Redmi 1280×2772 实测）：
     * 游戏 UI 顶块从**状态栏下沿**开始 ⇒ 整块 +132px；锚底区不受影响；
     * 模拟器无刘海/挖孔 ⇒ 0（行为与旧版一致）。
     */
    private static volatile float topInset = 0f;

    // ── fallback（矮胖屏）的旧等比参数 ──
    private static volatile float s = 1f;        // ref-per-device
    private static volatile float dx = 0f;
    private static volatile float dy = 0f;

    private static volatile int screenW = REF_W;
    private static volatile int screenH = REF_H;

    private RefMapper() {
    }

    public static void setScreen(int w, int h) {
        if (w <= 0 || h <= 0) {
            return;
        }
        screenW = w;
        screenH = h;
        kx = w / (float) REF_W;
        shift = h - REF_H * kx;
        anchored = shift >= -0.5f;
        topInset = Math.min(Math.max(0f, topInset), Math.max(0f, shift));   // 顶块不压过锚底区
        if (!anchored) {                         // 矮胖屏：回退整屏等比 + 居中留黑边
            s = Math.min(REF_W / (float) w, REF_H / (float) h);
            dx = (REF_W - w * s) / 2f;
            dy = (REF_H - h * s) / 2f;
        }
        AppLog.i("屏幕 " + w + "x" + h + " ⇒ " + (anchored
                ? ("锚定模型 kx=" + fmt(kx) + " shift=" + Math.round(shift)
                   + " 顶块偏移=" + Math.round(topInset)
                   + (isRefRes() && topInset == 0 ? "（参考分辨率 ⇒ 零变换）"
                                 : (shift == 0 && topInset == 0 ? "（9:16 ⇒ 与旧等比一致）"
                                                                : "（顶块锚顶+其余锚底）")))
                : ("矮胖屏 ⇒ 回退等比 s=" + fmt(s) + " 黑边=(" + Math.round(dx) + "," + Math.round(dy) + ")")));
    }

    /** device-per-ref（参考坐标 × k = 设备坐标）。⚠ 别拿它做"设备高度→参考高度"（那是 {@link #refPerDev}） */
    public static float k() {
        return anchored ? kx : (1f / s);
    }

    /** ref-per-device（设备像素长度 × 它 = 参考像素长度）。
     *  ⚠ 方向与 {@link #k()} 相反：k 是 device-per-ref（=kx），这里必须是 1/kx。
     *  （2026-09-29 修：之前 anchored 分支误返回 kx，720p 上"参考高"显示 40 应为 90） */
    public static float refPerDev() {
        return anchored ? (1f / kx) : s;
    }

    /**
     * ⭐ 顶块安全区偏移自动检测（真机专用）：取「挖孔安全区 top」与「状态栏高度」的较大者；
     * 没有挖孔（模拟器）⇒ 0，保持旧行为。在 App 启动/截图通道启动时调用一次。
     */
    public static void detectTopInset(android.content.Context ctx) {
        try {
            if (android.os.Build.VERSION.SDK_INT < 30) {
                setTopInset(0);
                return;
            }
            android.view.WindowManager wm =
                    (android.view.WindowManager) ctx.getSystemService(android.content.Context.WINDOW_SERVICE);
            android.view.WindowInsets wi = wm.getMaximumWindowMetrics().getWindowInsets();
            android.view.DisplayCutout cut = wi == null ? null : wi.getDisplayCutout();
            if (cut == null) {                       // 模拟器/无挖孔 ⇒ 0
                setTopInset(0);
                return;
            }
            int id = android.content.res.Resources.getSystem()
                    .getIdentifier("status_bar_height", "dimen", "android");
            int sbh = id > 0
                    ? android.content.res.Resources.getSystem().getDimensionPixelSize(id) : 0;
            setTopInset(Math.max(cut.getSafeInsetTop(), sbh));
        } catch (Throwable t) {
            setTopInset(0);
        }
    }

    /** 设置顶块安全区偏移（设备像素，App 启动时自动检测；模拟器=0）。 */
    public static void setTopInset(float inset) {
        float v = Math.max(0f, inset);
        if (Math.abs(v - topInset) < 0.5f) {
            return;
        }
        topInset = v;
        AppLog.i("顶部安全区偏移 = " + Math.round(topInset) + "px（真机状态栏/挖孔；模拟器=0）");
    }

    public static int screenW() {
        return screenW;
    }

    public static int screenH() {
        return screenH;
    }

    public static boolean isRefRes() {
        return screenW == REF_W && screenH == REF_H;
    }

    /** 参考坐标 → 设备像素 */
    public static int devX(float x) {
        if (isRefRes()) {
            return Math.round(x);
        }
        if (anchored) {
            return Math.round(x * kx);
        }
        return Math.round((x - dx) / s);
    }

    /** 参考坐标 → 设备像素（y 按「顶块锚顶(+安全区) / 其余锚底」分段） */
    public static int devY(float y) {
        if (isRefRes() && topInset == 0) {
            return Math.round(y);
        }
        if (anchored) {
            return Math.round(y <= TOP_SPLIT_REF ? y * kx + topInset : y * kx + shift);
        }
        return Math.round((y - dy) / s);
    }

    /**
     * 参考系**长度** → 设备像素长度（宽/高/间距这类"尺寸"，**不含平移**）。
     * ⚠ 别拿 {@link #devX} 来算宽度：那条带偏移，只有"坐标"才需要。
     */
    public static int devLen(float ref) {
        if (isRefRes()) {
            return Math.round(ref);
        }
        if (anchored) {
            return Math.round(ref * kx);
        }
        return Math.round(ref / s);
    }

    /** 设备像素 → 参考坐标 */
    public static float refX(float x) {
        if (isRefRes()) {
            return x;
        }
        if (anchored) {
            return x / kx;
        }
        return x * s + dx;
    }

    /** 设备像素 → 参考坐标（y 与 {@link #devY} 互逆，分段一致） */
    public static float refY(float y) {
        if (isRefRes() && topInset == 0) {
            return y;
        }
        if (anchored) {
            return y <= TOP_SPLIT_REF * kx + topInset ? (y - topInset) / kx : (y - shift) / kx;
        }
        return y * s + dy;
    }

    // ── 居中弹窗空间（v0.31 · 2026-09-30 方案 B）─────────────────────────
    //
    // ⭐⭐ 真机实锤（1280×2772：boss「战斗」钮设备 y=1186 ⇒ 归一化帧 y=582；PC 同一按钮
    //     在参考系 y=791）⇒ 游戏的**弹窗**不守「顶块锚顶+其余锚底」——它们锚定**设备屏幕中心**。
    //     PC（1080×1920）上弹窗空间==参考系（1:1），所以 PC 标定的面板常数
    //     （FIGHT_Y=735、按钮 y 带 650~860、boss-fixed (541,735)…）全都是**弹窗系**坐标。
    //     归一化帧（棋盘系）里弹窗内容的 y 恒 = 弹窗系 y − C（两段映射斜率同为 1/kx ⇒ 纯平移）：
    //       C = 960 + (shift − H/2) / kx
    //     9:16 屏 / 矮胖屏回退 ⇒ C = 0（弹窗系==归一化帧，行为与 PC 完全一致）。
    //     点弹窗系 (x,y)：设备 y = H/2 + (y−960)·kx（**不走顶块分段**、不受 topInset 影响）。
    //     例：真机 C=209，boss 战斗钮弹窗系 791 ⇒ 设备 1386+(791−960)·1.1852=1186 ✓；
    //         2400 屏 C=240；720p C=0。底部导航/顶部 HUD 不用这套（原模型已对 ✓）

    /** 弹窗系 → 归一化帧 的 y 偏移 C（弹窗系 y = 归一化帧 y + C）。PC/9:16/矮胖屏 = 0 */
    public static float dialogShift() {
        if (!anchored) {
            return 0f;
        }
        float c = REF_H / 2f + (shift - screenH / 2f) / kx;
        return Math.abs(c) < 0.5f ? 0f : c;
    }

    /** 弹窗系 y → 设备 y（弹窗锚设备屏幕中心：不走顶块分段、不受 topInset 影响）。
     *  9:16 屏上数学上与 {@link #devY}（锚底段）等价；kx=1 时即恒等。 */
    public static int devYDialog(float y) {
        if (!anchored) {
            return Math.round((y - dy) / s);
        }
        return Math.round(screenH / 2f + (y - REF_H / 2f) * kx);
    }

    /**
     * 把整屏帧归一化成 1080×1920 参考帧。
     * <ul>
     *   <li>anchored：**两段拼接** —— 顶块 (0,0,W,300kx) → (0,0,1080,300)；
     *       锚底区 (0,300kx+shift,W,H) → (0,300,1080,1920)（段内等比 1/kx，正好铺满）。
     *       中间被丢掉的 (300kx, 300kx+shift) 是弹性世界场景，脚本用不到。</li>
     *   <li>非 anchored（矮胖屏）：旧整屏等比 + 居中留黑边。</li>
     * </ul>
     */
    public static Bitmap toRef(Bitmap screen) {
        if (screen == null) {
            return null;
        }
        setScreen(screen.getWidth(), screen.getHeight());
        if (screen.getWidth() == REF_W && screen.getHeight() == REF_H && topInset == 0) {
            return screen;                        // 参考分辨率且无安全区 ⇒ 零变换（连 Bitmap 都不重建）
        }
        Bitmap out = Bitmap.createBitmap(REF_W, REF_H, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(out);
        c.drawColor(0xFF000000);
        Paint p = new Paint(Paint.FILTER_BITMAP_FLAG);
        int w = screen.getWidth();
        int h = screen.getHeight();
        if (anchored) {
            int topSrc = Math.round(topInset);                        // 顶块起点 = 状态栏下沿
            int topSrcEnd = Math.round(topInset + TOP_SPLIT_REF * kx);
            int botStart = Math.round(TOP_SPLIT_REF * kx + shift);    // = H − 1620·kx
            if (botStart < topSrcEnd) {                               // 理论不会（已钳制）
                botStart = topSrcEnd;
            }
            // ① 顶块：从安全区下沿起、x/y 同乘 kx
            c.drawBitmap(screen, new Rect(0, topSrc, w, topSrcEnd),
                    new RectF(0, 0, REF_W, TOP_SPLIT_REF), p);
            // ② 锚底区：y 平移 shift、x/y 同乘 kx（段内恰好铺满 300~1920）
            c.drawBitmap(screen, new Rect(0, botStart, w, h),
                    new RectF(0, TOP_SPLIT_REF, REF_W, REF_H), p);
        } else {
            // 矮胖屏回退：整屏等比缩放、居中、留黑边（不裁切）
            Rect src = new Rect(0, 0, w, h);
            c.drawBitmap(screen, src, new RectF(dx, dy, dx + w * s, dy + h * s), p);
        }
        return out;
    }

    private static String fmt(float v) {
        return String.format(java.util.Locale.US, "%.4f", v);
    }

    /**
     * 把整屏帧重投影成 1080×1920 **弹窗帧**（v0.31 方案 B）。
     *
     * 弹窗锚定设备屏幕中心 ⇒ 设备行 [H/2 − 960kx, H/2 + 960kx] → [0, 1920]，x 全宽 → 1080。
     * 与 {@link #toRef} 的两个区别：
     * <ul>
     *   <li><b>不丢中间弹性区</b> —— 面板 X 关闭符（dlg≈225）在真机落在被 toRef 丢弃的
     *       设备行段里，归一化帧上根本看不见；弹窗帧里它就在 dlg 225 ✓</li>
     *   <li><b>不做顶块分段</b> —— 弹窗锚屏幕中心，与状态栏/挖孔无关</li>
     * </ul>
     * 9:16 屏上与 toRef 逐像素一致（src 恰好是整屏）；矮胖屏回退同 toRef。
     * PC（1080×1920）直接原帧返回。
     */
    public static Bitmap toDlg(Bitmap screen) {
        if (screen == null) {
            return null;
        }
        setScreen(screen.getWidth(), screen.getHeight());
        if (screen.getWidth() == REF_W && screen.getHeight() == REF_H) {
            return screen;
        }
        Bitmap out = Bitmap.createBitmap(REF_W, REF_H, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(out);
        c.drawColor(0xFF000000);
        Paint p = new Paint(Paint.FILTER_BITMAP_FLAG);
        int w = screen.getWidth();
        int h = screen.getHeight();
        if (anchored) {
            float half = REF_H / 2f * kx;
            Rect src = new Rect(0, Math.round(screenH / 2f - half),
                    w, Math.round(screenH / 2f + half));
            c.drawBitmap(screen, src, new RectF(0, 0, REF_W, REF_H), p);
        } else {
            Rect src = new Rect(0, 0, w, h);
            c.drawBitmap(screen, src, new RectF(dx, dy, dx + w * s, dy + h * s), p);
        }
        return out;
    }
}
