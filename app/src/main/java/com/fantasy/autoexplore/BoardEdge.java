package com.fantasy.autoexplore;

import android.graphics.Bitmap;

/**
 * 棋盘底边检测 —— 从**当前截图**里量出 5x7 棋盘的**最后一条横网格线**。
 *
 * <p>判据来自真机实测（1280x2772 探索地图，标注图逐行核对过）：
 * <pre>
 *   棋盘 5 行的 6 条横分隔线 = 1683 / 1854 / 2025 / 2195 / 2366 / 2537
 *   间距 171 / 171 / 170 / 171 / 171  —— 完全均匀
 *   ⇒ **棋盘底边 = 最后一条线 = 2537**
 * </pre>
 *
 * <p>为什么不用"底部导航栏上沿"反推（旧做法）：导航栏上沿是 2575，
 * 比棋盘底边低 38px，拿它当棋盘底会整体偏低。
 *
 * <p>判据：横网格线是**浅金色**（实测 249,211,159 / 254,229,175 一类），
 * 整行占比 >= 50%。格子内部是灰/黄，横向占比低；场景与导航栏完全不含该色。
 *
 * <p>⚠ 找不到返回 -1，调用方必须退回常量（fail-safe）。
 */
final class BoardEdge {

    static final int NOT_FOUND = -1;

    BoardEdge() {
    }

    /**
     * 检测棋盘底边（设备像素 y = 最后一条横网格线所在行）。
     *
     * @return 底边 y；找不到返回 {@link #NOT_FOUND}
     */
    static int detectBottom(Bitmap shot) {
        if (shot == null) {
            return NOT_FOUND;
        }
        final int w = shot.getWidth();
        final int h = shot.getHeight();
        if (w < 200 || h < 400) {
            return NOT_FOUND;
        }

        final int step = Math.max(2, w / 300);
        final int xFrom = (int) (w * 0.05);
        final int xTo = (int) (w * 0.95);
        final int yFrom = (int) (h * 0.40);
        final float rowHitMin = 0.50f;

        int[] rows = new int[h];
        int nRows = 0;
        for (int y = yFrom; y < h; y++) {
            int hit = 0;
            int tot = 0;
            for (int x = xFrom; x < xTo; x += step) {
                tot++;
                if (isGridLine(shot.getPixel(x, y))) {
                    hit++;
                }
            }
            if (tot > 0 && hit / (float) tot >= rowHitMin) {
                rows[nRows++] = y;
            }
        }
        if (nRows < 4) {
            return NOT_FOUND;
        }

        int[] centers = new int[nRows];
        int nC = 0;
        int groupStart = rows[0];
        int prev = rows[0];
        for (int i = 1; i < nRows; i++) {
            if (rows[i] - prev > 4) {
                centers[nC++] = (groupStart + prev) / 2;
                groupStart = rows[i];
            }
            prev = rows[i];
        }
        centers[nC++] = (groupStart + prev) / 2;

        if (nC < 4) {
            return NOT_FOUND;
        }

        int last = centers[nC - 1];
        int span = last - centers[0];
        if (span <= 0) {
            return NOT_FOUND;
        }
        int avg = span / (nC - 1);
        if (avg < 60 || avg > 400) {
            return NOT_FOUND;
        }
        for (int i = 1; i < nC; i++) {
            int d = centers[i] - centers[i - 1];
            if (Math.abs(d - avg) > avg / 4) {
                return NOT_FOUND;
            }
        }
        return last;
    }

    /**
     * 横网格线颜色判据（实测：浅金 249,211,159 / 254,229,175）。
     */
    private static boolean isGridLine(int c) {
        int r = (c >> 16) & 0xFF;
        int g = (c >> 8) & 0xFF;
        int b = c & 0xFF;
        return r >= 240 && g >= 195 && g <= 242 && b >= 140 && b <= 210;
    }
}
