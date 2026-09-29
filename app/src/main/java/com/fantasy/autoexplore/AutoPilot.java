package com.fantasy.autoexplore;

import android.content.Context;
import android.graphics.Bitmap;

import java.io.File;
import java.io.FileOutputStream;
import java.util.List;

/**
 * 自动化核心（界面层与命令层共用）：截图 → 参考系归一化 → OCR → 手势点击。
 *
 * 之所以单独抽出来：手机端入口有两个 —— ① 界面按钮；② 广播命令（调试/自动化，
 * 这样在游戏前台时也能触发，不必把本应用顶到前台）。
 */
public final class AutoPilot {

    private static final OcrEngine OCR = new OcrEngine();

    private AutoPilot() {
    }

    public static OcrEngine ocr() {
        return OCR;
    }

    public static void ensureOcr(Context ctx) {
        if (!OCR.isReady()) {
            OCR.init(ctx);
        }
    }

    /** 取当前帧并归一化成 1080×1920 参考帧 */
    public static Bitmap grabRef() {
        Bitmap f = FrameStore.get();
        if (f == null) {
            return null;
        }
        return RefMapper.toRef(f);
    }

    public static File dumpDir(Context ctx) {
        File d = new File(ctx.getExternalFilesDir(null), "dump");
        if (!d.exists()) {
            d.mkdirs();
        }
        return d;
    }

    public static void savePng(Context ctx, Bitmap bmp, String name) {
        try (FileOutputStream fos = new FileOutputStream(new File(dumpDir(ctx), name))) {
            bmp.compress(Bitmap.CompressFormat.PNG, 95, fos);
        } catch (Throwable t) {
            AppLog.i("⚠ 存图失败 " + name + "：" + t);
        }
    }

    /**
     * 识别当前帧。
     *
     * @param dump 是否把 raw/ref png 与 ocr.json 落到 files/dump/（与 PC 对拍用）
     */
    public static List<OcrItem> scan(Context ctx, float minConf, boolean dump) {
        Bitmap raw = FrameStore.get();
        if (raw == null) {
            AppLog.i("⚠ 没有帧：请先授权截图（「① 授权截图」或广播 cmd=capture）");
            return java.util.Collections.emptyList();
        }
        ensureOcr(ctx);
        Bitmap rawCopy = raw.copy(Bitmap.Config.ARGB_8888, false);
        Bitmap ref = RefMapper.toRef(rawCopy);
        if (dump) {
            savePng(ctx, rawCopy, "raw.png");
            savePng(ctx, ref, "ref.png");
        }
        long t0 = System.currentTimeMillis();
        List<OcrItem> items = OCR.recognize(ref, minConf);
        long dt = System.currentTimeMillis() - t0;
        if (dump) {
            saveOcrJson(ctx, items, dt);
        }
        AppLog.i("识别 " + items.size() + " 条，用时 " + dt + "ms");
        return items;
    }

    /** 找到第一个含关键字的文本并点它（返回是否点到） */
    public static OcrItem find(List<OcrItem> items, String... keys) {
        for (OcrItem it : items) {
            String t = it.text.replace(" ", "");
            for (String k : keys) {
                if (t.contains(k)) {
                    return it;
                }
            }
        }
        return null;
    }

    public static boolean tapItem(OcrItem it) {
        if (it == null) {
            return false;
        }
        if (!AutoTouchService.ready()) {
            AppLog.i("⚠ 无障碍服务没开：点击通道不可用");
            return false;
        }
        int dx = RefMapper.devX(it.cx);
        int dy = RefMapper.devY(it.cy);
        boolean ok = AutoTouchService.get().tap(dx, dy);
        AppLog.i("点「" + it.text + "」参考(" + it.cx + "," + it.cy + ") → 设备(" + dx + "," + dy
                + ") " + (ok ? "手势已下发 ✓" : "⚠ 手势下发失败"));
        return ok;
    }

    private static void saveOcrJson(Context ctx, List<OcrItem> items, long ms) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"ms\":").append(ms).append(",\"n\":").append(items.size())
                .append(",\"items\":[");
        for (int i = 0; i < items.size(); i++) {
            OcrItem it = items.get(i);
            if (i > 0) {
                sb.append(',');
            }
            sb.append(String.format(java.util.Locale.US,
                    "{\"text\":\"%s\",\"cx\":%d,\"cy\":%d,\"x0\":%d,\"y0\":%d,\"x1\":%d,\"y1\":%d,\"conf\":%.3f}",
                    it.text.replace("\"", "'"), it.cx, it.cy, it.x0, it.y0, it.x1, it.y1, it.conf));
        }
        sb.append("]}");
        try (FileOutputStream fos = new FileOutputStream(new File(dumpDir(ctx), "ocr.json"))) {
            fos.write(sb.toString().getBytes("UTF-8"));
            AppLog.i("OCR 结果已存：" + new File(dumpDir(ctx), "ocr.json").getAbsolutePath());
        } catch (Throwable t) {
            AppLog.i("⚠ 存 json 失败：" + t);
        }
    }
}
