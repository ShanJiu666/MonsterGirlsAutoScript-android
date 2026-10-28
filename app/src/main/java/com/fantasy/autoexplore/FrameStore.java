package com.fantasy.autoexplore;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;

/**
 * 最新帧的全局存放处（等价 PC 端 mapbot.Bot 的 `_img_arr`）。
 *
 * 截图线程（ImageReader 回调）写入，业务线程读取；只保留最新一帧，不落盘。
 *
 * ⭐⭐ 2026-09-29 起 `set()` 会**先把悬浮条占的那块涂平**再存 ——
 * 这是"悬浮窗可以放心显示/滚动"的地基（见 {@link OverlayService} 硬约束③）：
 *
 *   · 悬浮窗是画在游戏画面**上面**的，MediaProjection 一定会把它截进去；
 *   · 而探索循环对整帧做**全屏 OCR + 关键词子串匹配**（`'关闭'/'探索'/'开始冒险'`…），
 *     悬浮窗上那行滚动日志必然带上这些词 ⇒ 会**误判成游戏面板**而乱点；
 *   · 更要命的是 `wait_stable` 的默认采样带 `(130,1800)` 正罩着悬浮条，
 *     日志**一直在滚** ⇒ 永远等不到"连续 2 帧不变" ⇒ **循环卡死**。
 *
 * 试过 `FLAG_SECURE`（让窗口对投屏隐形，本该是最干净的解），但 2026-09-29 实测：
 * **MuMu 上一带 SECURE，整个 `screencap` 就直接失败（0 字节 / 设备内 exit=1）**，
 * 关掉立刻恢复 ⇒ 该 ROM 会拒绝整屏抓取，MediaProjection 大概率同样拿不到帧
 * ⇒ **推图直接瞎**。所以改成"涂平"：不依赖任何 ROM 行为，字节级可验证。
 *
 * 涂平的**安全性**来自悬浮条的几何（见 OverlayService 硬约束①）：
 * 它只占参考 y 1739~1816，而
 *   · 棋盘 1002~1722（含最低一行格子 1578~1722）—— 碰不到 ⇒ 模板识别不受影响
 *   · `boardLuma` 采样 1002~1722 —— 碰不到 ⇒ 暗罩判定不受影响
 *   · `wait_change` 主带 130~1700 —— 碰不到 ⇒ 只在 `around(x,y,radius)` 局部窗口里
 *     才可能覆盖到，而涂平后那块**恒定** ⇒ 不会产生假变化 ✓
 * ⇒ **改动悬浮条几何/位置时必须重新核对这四个区间**，否则会静默地把识别搞坏。
 */
public final class FrameStore {

    /** 涂平用的颜色（恒定色即可；只要不随帧变化，任何颜色都不影响稳定判定与亮度统计） */
    private static final int MASK_COLOR = 0xFF101418;

    private static volatile Bitmap latest;
    private static volatile long stampMs;

    private FrameStore() {
    }

    /** 写入最新帧（**自动涂掉悬浮条**）；返回真正存下来的那张 */
    public static void set(Bitmap bmp) {
        latest = maskOverlay(bmp);
        stampMs = System.currentTimeMillis();
    }

    /** 没有帧时返回 null（调用方必须判空） */
    public static Bitmap get() {
        return latest;
    }

    public static long stamp() {
        return stampMs;
    }

    public static boolean has() {
        return latest != null;
    }

    /**
     * 上一次涂平的**实测记账**（涂平前的亮度统计 + 矩形）。
     * ⭐ 2026-09-30 加：`DeviceApi.maskCheck()` 以前是拿**已经涂平的那张帧**去统计**那个矩形自己**
     * ⇒ 恒定纯色，永远打印「涂平生效 ✓」—— **空过**（自己给自己打分）。
     * 真问题（矩形偏了 184px、没盖住悬浮条）就是这么被它掩盖掉的。
     * 所以改成：涂平**之前**就在这张帧上量一遍，这才是能证伪的证据。
     */
    private static volatile String lastMaskInfo = "（还没涂过）";

    /** 上一次涂平的实测记账（给 mask_check 用） */
    public static String lastMaskInfo() {
        return lastMaskInfo;
    }

    /**
     * ⭐ 2026-10-08：「涂平**之前**的实测记账」改成**按需**（默认不记）。
     *
     * 记账本身要逐像素 {@code getPixel}（真机悬浮条矩形 1138×115、步长 2 ⇒ 约 3.3 万次/帧），
     * 画面在动时按刷新率出帧 ⇒ 约 200 万次/秒，**恒定燃烧**。
     * 而它的消费者只有两个 dev 口子 —— {@code DeviceApi.maskCheck()}（广播 mask_check）
     * 与 {@code OverlayService.dumpText()}（广播 overlay_dump）——
     * **脚本热路径一次都没读过**（已全仓核对）⇒ 没布防时白记等于纯浪费。
     *
     * ⚠ 涂平本身（{@code drawRect}）**不受影响**，仍然每帧照做；这里只关掉"记账"。
     * ⚠ 关掉后 {@link #lastMaskInfo()} 会停在**上一次布防时**记下的那条（或初值），
     *   不会变成 null ⇒ 消费方照旧能读能打印，不会崩、不会输出异常。
     */
    private static volatile boolean maskDiagArmed = false;

    /** 布防：让**下一帧**涂平时记一次「涂平前实测」（供 mask_check 取证据） */
    static void armMaskDiag() {
        maskDiagArmed = true;
    }

    /**
     * 把悬浮条占的设备像素矩形涂平（无悬浮条 ⇒ 原样返回）。
     * ⚠ 直接在原 Bitmap 上画（截图线程的那张本来就是拷贝，没有别处再引用）。
     */
    private static Bitmap maskOverlay(Bitmap bmp) {
        if (bmp == null) {
            return null;
        }
        int[] r = OverlayService.blankRect();
        if (r == null) {
            lastMaskInfo = "悬浮条没显示 ⇒ 无涂平（帧是原样）";
            return bmp;
        }
        try {
            int l = Math.max(0, r[0]);
            int t = Math.max(0, r[1]);
            int rr = Math.min(bmp.getWidth(), r[2]);
            int b = Math.min(bmp.getHeight(), r[3]);
            if (rr <= l || b <= t) {
                lastMaskInfo = "矩形越界（" + r[0] + "," + r[1] + "-" + r[2] + "," + r[3]
                        + "）⇒ 没涂，帧是原样";
                return bmp;
            }
            // ⭐ 涂平**之前**先量：这一块的亮度极差就是「涂平到底有没有起作用」的判据
            //   ⚠ 只在布防时记一次（见 {@link #maskDiagArmed}）—— 记账逐像素 getPixel，
            //     放进每帧热路径是恒定浪费，而脚本从不读它。
            if (maskDiagArmed) {
                maskDiagArmed = false;
                lastMaskInfo = sample(bmp, l, t, rr, b)
                        + " rect=" + l + "," + t + "-" + rr + "," + b;
            }
            Canvas c = new Canvas(bmp);
            Paint p = new Paint();
            p.setColor(MASK_COLOR);
            c.drawRect(l, t, rr, b, p);
        } catch (Throwable ignored) {
            // 涂平失败也不能让截图整个崩掉（宁可让循环自己去对付）
        }
        return bmp;
    }

    /** 亮度的 均值/最小/最大/极差（隔 2px 采样，够用且快） */
    private static String sample(Bitmap bmp, int x0, int y0, int x1, int y1) {
        long sum = 0;
        int n = 0, mn = 255, mx = 0;
        for (int y = y0; y < y1; y += 2) {
            for (int x = x0; x < x1; x += 2) {
                int px = bmp.getPixel(x, y);
                int v = (int) (0.299 * ((px >> 16) & 0xFF)
                        + 0.587 * ((px >> 8) & 0xFF) + 0.114 * (px & 0xFF));
                sum += v;
                n++;
                if (v < mn) {
                    mn = v;
                }
                if (v > mx) {
                    mx = v;
                }
            }
        }
        double mean = n == 0 ? 0 : (double) sum / n;
        return String.format(java.util.Locale.US,
                "涂平前该处亮度 均值=%.1f 最小=%d 最大=%d 极差=%d（采样%d）",
                mean, mn, mx, mx - mn, n);
    }
}
