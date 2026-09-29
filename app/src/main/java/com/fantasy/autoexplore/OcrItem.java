package com.fantasy.autoexplore;

/**
 * 一条 OCR 结果（坐标一律是 **1080×1920 参考系**，与 PC 端 mapbot 的 items 同构）。
 */
public class OcrItem {

    public String text;
    public int cx;
    public int cy;
    public int x0;
    public int y0;
    public int x1;
    public int y1;
    public float conf;

    public OcrItem(String text, int cx, int cy, int x0, int y0, int x1, int y1, float conf) {
        this.text = text;
        this.cx = cx;
        this.cy = cy;
        this.x0 = x0;
        this.y0 = y0;
        this.x1 = x1;
        this.y1 = y1;
        this.conf = conf;
    }

    @Override
    public String toString() {
        return String.format(java.util.Locale.US, "%s@(%d,%d) conf=%.2f", text, cx, cy, conf);
    }
}
