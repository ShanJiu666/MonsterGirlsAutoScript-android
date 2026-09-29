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
     * 把悬浮条占的设备像素矩形涂平（无悬浮条 ⇒ 原样返回）。
     * ⚠ 直接在原 Bitmap 上画（截图线程的那张本来就是拷贝，没有别处再引用）。
     */
    private static Bitmap maskOverlay(Bitmap bmp) {
        if (bmp == null) {
            return null;
        }
        int[] r = OverlayService.blankRect();
        if (r == null) {
            return bmp;
        }
        try {
            int l = Math.max(0, r[0]);
            int t = Math.max(0, r[1]);
            int rr = Math.min(bmp.getWidth(), r[2]);
            int b = Math.min(bmp.getHeight(), r[3]);
            if (rr <= l || b <= t) {
                return bmp;
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
}
