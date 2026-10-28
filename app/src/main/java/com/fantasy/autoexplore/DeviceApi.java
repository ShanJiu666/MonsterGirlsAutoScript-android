package com.fantasy.autoexplore;

import android.content.Context;
import android.graphics.Bitmap;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.List;
import java.util.Locale;

/**
 * Python（Chaquopy）与设备的桥：mapbot 的逻辑层通过这个类拿到
 * **截图 / OCR / 点击 / 等画面变化**，坐标一律 1080×1920 参考系。
 *
 * 全部方法是静态的，Python 侧直接：
 *     from java import jclass
 *     DEV = jclass('com.fantasy.autoexplore.DeviceApi')
 *     png = DEV.grabRefPng()
 */
public final class DeviceApi {

    private static final String TAG = "DeviceApi";
    private static volatile double lastDim = 1.0;
    private static volatile Context appCtx;

    /**
     * ⭐⭐ **立即停止**的中断标志（v0.25 / 2026-09-30）
     *
     * 用户口径：「停止键点了要立即停止，不要等打完这张图」（v0.13 已采纳）。
     * 但 v0.13 ~ v0.24 的检查点只在 `one_round` "每次点击前"，**`wait_change` / `wait_stable`
     * 是 Java native 阻塞调用（60~80ms 一帧轮询），最坏等 maxSec 秒才返回** ⇒ 用户感觉"还在跑"。
     *
     * 修法：Python 端 `explore_android.stop()` 会**同时**做两件事：
     *   ① 写 `_ANDROID_STOP = True`（explore_loop 的检查点查这个 ⇒ 后续点击不再做）
     *   ② 调本类的 `requestInterrupt()` 把 Java 端 wait 循环立即踹出
     *
     * ⚠ **单写多读 / 单线程访问**（explore_loop 是单线程的，没有并发）⇒ `volatile` 足够；
     *   ⚠ **`waitStable` / `waitChange` 检测到中断后会把标志清回 false**（一次性），
     *   避免下次正常 wait 也被立刻踹出去。
     */
    private static volatile boolean INTERRUPT_WAIT = false;

    /** Python 端（`explore_android.stop`）调一下 ⇒ Java 端正在跑的 wait 立即返回 false */
    public static void requestInterrupt() {
        INTERRUPT_WAIT = true;
        Log.i(TAG, "[stop] INTERRUPT_WAIT 置位（Java 端 wait 立即返回 false）");
    }

    /**
     * ⭐⭐ 2026-10-02 v1.26：**帧龄（毫秒）** —— 给 Python 判"机器人是不是瞎了"
     *
     * 背景（用户真机实报）：`CaptureService` 的看门狗发现截图流断流后**只在 Java 侧记日志**，
     * Python 那头完全不知情 ⇒ 它继续拿**冻结的旧帧**做判断、**继续点地图格子** ✗✗
     * 用户看到的就是「点了战斗格、还没打就去点下一个格子」。
     * ⇒ 把帧龄暴露出来，Python 自己决定"帧不新鲜就别点、直接停"。
     *
     * @return 帧龄 ms；**没有帧**返回 -1（首次启动还没拿到帧时也是 -1，别当断流 ✗）
     */
    public static long frameAgeMs() {
        try {
            if (!FrameStore.has()) {
                return -1L;
            }
            return System.currentTimeMillis() - FrameStore.stamp();
        } catch (Throwable t) {
            return -1L;
        }
    }

    /**
     * ⭐ v1.31：取帧是否走"行距填充"慢路径（真机 1264 宽会走 ⇒ 历史上正是它 R↔B 互换 ✗）
     *
     * @return `[走慢路径? 1/0, 行距, 宽度*4]`；拿不到返回 `[0,0,0]`
     */
    public static int[] capturePath() {
        try {
            int w = FrameStore.has() ? FrameStore.get().getWidth() : 0;
            return new int[]{CaptureService.slowPath() ? 1 : 0,
                    CaptureService.slowRowStride(), w * 4};
        } catch (Throwable t) {
            return new int[]{0, 0, 0};
        }
    }

    /** 测试/手动复位用（一般不用调；wait 检测到中断会自动清回 false） */
    public static void clearInterrupt() {
        INTERRUPT_WAIT = false;
    }

    /** 内部 helper：检查 + 自动清（一次性触发） */
    private static boolean consumeInterrupt() {
        if (INTERRUPT_WAIT) {
            INTERRUPT_WAIT = false;
            return true;
        }
        return false;
    }

    private DeviceApi() {
    }

    public static void bind(Context ctx) {
        appCtx = ctx.getApplicationContext();
        PyBridge.bind(appCtx);          // Python 桥也需要 context（自动启动 Chaquopy）
    }

    // ---------------- 截图 ----------------

    public static boolean hasFrame() {
        return FrameStore.has();
    }

    /**
     * dev 自检（广播 `mask_check`）：证明**"机器人对自己瞎"**这条地基还在。
     *
     * ⚠⚠ 2026-09-30 重写：旧版只统计「{@link FrameStore} 里那张**已经涂平**的帧」上「那个矩形自己」
     * ⇒ 恒定纯色，**永远**打印「涂平生效 ✓」—— 自己给自己打分（空过）。
     * 真事故（涂平矩形整体偏了 184px，既没盖住悬浮条、又把棋盘一行格子抹成纯色）
     * 就是这么被它掩盖的。所以现在分两段报：
     *   ① **涂平前**该处的亮度极差（{@link FrameStore#lastMaskInfo()}，涂平那一刻记的账）
     *      —— 极差大 ⇒ 那里本来有内容（说明涂平确实在做事）；极差≈0 ⇒ 那里本来就空，涂不涂都一样
     *   ② **涂平后**同一处是否恒为涂平色（这一段是"结论"，但必须配上 ① 才有意义）
     * ⚠ 用**原始设备帧**（不是参考帧）：`blankRect` 本来就是设备像素，别做二次换算。
     */
    public static String maskCheck() {
        int[] r = OverlayService.blankRect();
        if (r == null) {
            return "悬浮条没显示 ⇒ 无从检查（先 overlay_on）";
        }
        Bitmap raw = FrameStore.get();
        if (raw == null) {
            return "FrameStore 里没有帧（截图权限没授）⇒ 无从检查（点 ▶ 会拉授权框）";
        }
        int x0 = Math.max(0, r[0]);
        int y0 = Math.max(0, r[1]);
        int x1 = Math.min(raw.getWidth() - 1, r[2] - 1);
        int y1 = Math.min(raw.getHeight() - 1, r[3] - 1);
        // ⚠⭐ 2026-10-08：涂平时的「涂平前实测」改成**按需记账**（FrameStore.maskDiagArmed）——
        //   它逐像素 getPixel，放进每帧热路径是恒定浪费（约 200 万次/秒），
        //   而脚本从不读它。这里布防后等一帧新的帧产生，记账才落到**当前画面**上
        //   ⇒ 本方法给出的证据口径与以前完全一致（一字不少）。
        FrameStore.armMaskDiag();
        try {
            Thread.sleep(120);                      // 真机 ~30fps ⇒ 120ms 内必定出新帧
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
        }
        String before = "① 涂平时记账：" + FrameStore.lastMaskInfo();
        if (x1 <= x0 || y1 <= y0) {
            return before + "\n② 矩形越界：rect=" + r[0] + "," + r[1] + "-" + r[2] + "," + r[3]
                    + " 帧=" + raw.getWidth() + "x" + raw.getHeight();
        }
        long sum = 0;
        int n = 0, mn = 255, mx = 0;
        for (int y = y0; y <= y1; y += 2) {
            for (int x = x0; x <= x1; x += 2) {
                int px = raw.getPixel(x, y);
                int l = (int) (0.299 * ((px >> 16) & 0xFF)
                        + 0.587 * ((px >> 8) & 0xFF) + 0.114 * (px & 0xFF));
                sum += l;
                n++;
                if (l < mn) {
                    mn = l;
                }
                if (l > mx) {
                    mx = l;
                }
            }
        }
        double mean = n == 0 ? 0 : (double) sum / n;
        return before + "\n" + String.format(Locale.US,
                "② 涂平后 rect=%d,%d-%d,%d 帧=%dx%d 采样=%d 亮度 均值=%.1f 最小=%d 最大=%d 极差=%d ⇒ %s",
                x0, y0, x1, y1, raw.getWidth(), raw.getHeight(), n, mean, mn, mx, mx - mn,
                (mx - mn) <= 2 ? "那块是纯色 ✓（帧里认不出悬浮条上的字）"
                        : "⚠ 帧里还能看见悬浮条内容");
    }

    public static long frameStamp() {
        return FrameStore.stamp();
    }

    /** 当前帧归一化成 1080×1920 参考帧后的 PNG 字节（无帧 → null） */
    public static byte[] grabRefPng() {
        Bitmap raw = FrameStore.get();
        if (raw == null) {
            return null;
        }
        try {
            Bitmap ref = RefMapper.toRef(raw);
            ByteArrayOutputStream bos = new ByteArrayOutputStream(1 << 19);
            ref.compress(Bitmap.CompressFormat.PNG, 90, bos);
            return bos.toByteArray();
        } catch (Throwable t) {
            Log.w(TAG, "grabRefPng 失败: " + t);
            return null;
        }
    }

    /**
     * ⭐ 当前帧重投影成 1080×1920 **弹窗帧**后的 PNG 字节（v0.31 方案 B，无帧 → null）。
     * 弹窗（boss/战斗事件/探索/结算面板）锚设备屏幕中心，与棋盘的底锚不是同一坐标系；
     * 弹窗帧里弹窗内容 == PC 参考系坐标（PC 标定的面板常数原样可用），
     * 且不丢 toRef 会丢掉的弹性区（面板 X 关闭符在弹窗帧 dlg≈225 可见）。
     */
    public static byte[] grabDlgPng() {
        Bitmap raw = FrameStore.get();
        if (raw == null) {
            return null;
        }
        try {
            Bitmap dlg = RefMapper.toDlg(raw);
            ByteArrayOutputStream bos = new ByteArrayOutputStream(1 << 19);
            dlg.compress(Bitmap.CompressFormat.PNG, 90, bos);
            return bos.toByteArray();
        } catch (Throwable t) {
            Log.w(TAG, "grabDlgPng 失败: " + t);
            return null;
        }
    }

    // ---------------- OCR ----------------

    /**
     * ⭐ v0.34：对**弹窗帧**做 OCR，返回 JSON（坐标为**弹窗系**）。
     *
     * 真机上所有面板**标题**（战斗事件/探索产出/偶遇强敌/旅行商人/…）都落在
     * {@link RefMapper#toRef} 丢弃的弹性区 ⇒ 归一化帧 OCR 永远看不见 ⇒ 只靠标题的
     * 分支在真机全瞎。弹窗帧不丢弹性区，标题就在弹窗系原位（== PC 参考系坐标）✓
     */
    public static String ocrDlgJson(float minConf) {
        if (appCtx == null) {
            return "[]";
        }
        Bitmap raw = FrameStore.get();
        if (raw == null) {
            return "[]";
        }
        try {
            Bitmap dlg = RefMapper.toDlg(raw);
            AutoPilot.ensureOcr(appCtx);
            List<OcrItem> items = AutoPilot.ocr().recognize(dlg, minConf);
            StringBuilder sb = new StringBuilder("[");
            for (int i = 0; i < items.size(); i++) {
                OcrItem it = items.get(i);
                if (i > 0) {
                    sb.append(',');
                }
                sb.append(String.format(Locale.US,
                        "{\"text\":\"%s\",\"cx\":%d,\"cy\":%d,\"x0\":%d,\"y0\":%d,\"x1\":%d,\"y1\":%d,\"conf\":%.3f}",
                        it.text.replace("\\", "\\\\").replace("\"", "'"),
                        it.cx, it.cy, it.x0, it.y0, it.x1, it.y1, it.conf));
            }
            return sb.append(']').toString();
        } catch (Throwable t) {
            Log.w(TAG, "ocrDlgJson 失败: " + t);
            return "[]";
        }
    }

    /** OCR 结果 JSON（参考系坐标）：[{"text","cx","cy","x0","y0","x1","y1","conf"},…] */
    public static String ocrJson(float minConf) {
        if (appCtx == null) {
            return "[]";
        }
        List<OcrItem> items = AutoPilot.scan(appCtx, minConf, false);
        return itemsJson(items);
    }

    /**
     * ⭐ v0.61：**只识别参考帧 [y0,y1) 这一段**（真裁图）的 OCR 结果 JSON。
     *
     * 端侧 rec 占 OCR 总时间 ~81%，成本 ∝ 框数 ⇒ 裁掉 HUD/导航条能少一大批框
     * （PC 实测同口径省 ~50%）。调用方（Python `mapbot.Bot.ocr`）只在 band 高 ≥
     * BAND_CROP_MIN 时走这里 —— 更矮的带会被 det 的 limit_side_len 放大，反而更慢。
     *
     * @return 识别结果 JSON；**失败时返回 null**（区别于"识别成功但没有文字"的 "[]"），
     *         好让 Python 侧据以回退到整帧路径。
     */
    public static String ocrBandJson(float minConf, int y0, int y1) {
        if (appCtx == null) {
            return null;
        }
        Bitmap raw = FrameStore.get();
        if (raw == null) {
            return null;
        }
        try {
            // ⚠ 以前这里是 `RefMapper.toRef(raw.copy(ARGB_8888, false))`。
            //   那次整帧拷贝**没有可观察效果**：`toRef` 只读 screen（new Canvas(out) +
            //   drawColor + drawBitmap），**从不改它**；而 FrameStore.get() 返回的是
            //   截图线程每帧 Bitmap.createBitmap 新建的整帧（见 CaptureService），
            //   不会被就地改写。真机 1280×2772 = 每次 14.19MB 分配 + 14.19MB 拷贝，
            //   而它每次点击都会走一次 ⇒ 删掉是**逐位等价**的。
            Bitmap ref = RefMapper.toRef(raw);
            AutoPilot.ensureOcr(appCtx);
            List<OcrItem> items = AutoPilot.ocr().recognizeBand(ref, y0, y1, minConf);
            return itemsJson(items);
        } catch (Throwable t) {
            Log.w(TAG, "ocrBandJson 失败: " + t);
            return null;
        }
    }

    /**
     * 对**任意一张 PNG** 做 OCR（Python 侧 `mapbot._ocr()` 用）。
     *
     * 场景：PC 的 `buypanels.read_qty` 会把某格数量角标裁出来**放大 8 倍**再 OCR。
     * 端侧 OCR 引擎只吃 1080×1920 参考帧 ⇒ Python 侧已把图缩放并贴到黑底参考帧左上角，
     * 这里直接解码后喂给同一个引擎（口径与全屏 OCR **完全一致**）。
     *
     * 返回与 `ocrJson` 同构的 JSON；坐标是参考帧坐标（调用方只用 text/conf）。
     */
    public static String ocrPng(byte[] png, float minConf) {
        if (appCtx == null || png == null || png.length == 0) {
            return "[]";
        }
        Bitmap bmp;
        try {
            bmp = android.graphics.BitmapFactory.decodeByteArray(png, 0, png.length);
        } catch (Throwable t) {
            Log.w(TAG, "ocrPng 解码失败: " + t);
            return "[]";
        }
        if (bmp == null) {
            return "[]";
        }
        try {
            AutoPilot.ensureOcr(appCtx);
            if (bmp.getWidth() != RefMapper.REF_W || bmp.getHeight() != RefMapper.REF_H) {
                // ⚠ 这里**不能**用 RefMapper.toRef()：它会 setScreen(这张图的尺寸)，
                //   把全局屏幕映射改坏（后面的 devX/devY/wait 观察窗全错）。
                //   Python 侧本来就先把图贴上 1080×1920 黑底才进来，这段只是兜底 ⇒ 直接拉伸。
                bmp = Bitmap.createScaledBitmap(bmp, RefMapper.REF_W, RefMapper.REF_H, true);
            }
            List<OcrItem> items = AutoPilot.ocr().recognize(bmp, minConf);
            return itemsJson(items);
        } catch (Throwable t) {
            Log.w(TAG, "ocrPng 识别失败: " + t);
            return "[]";
        }
    }

    private static String itemsJson(List<OcrItem> items) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < items.size(); i++) {
            OcrItem it = items.get(i);
            if (i > 0) {
                sb.append(',');
            }
            sb.append(String.format(Locale.US,
                    "{\"text\":\"%s\",\"cx\":%d,\"cy\":%d,\"x0\":%d,\"y0\":%d,\"x1\":%d,\"y1\":%d,\"conf\":%.3f}",
                    it.text.replace("\\", "\\\\").replace("\"", "'"),
                    it.cx, it.cy, it.x0, it.y0, it.x1, it.y1, it.conf));
        }
        return sb.append(']').toString();
    }

    // ---------------- 手势 ----------------

    public static boolean touchReady() {
        return AutoTouchService.ready();
    }

    public static boolean tapRef(float x, float y) {
        if (!AutoTouchService.ready()) {
            return false;
        }
        return AutoTouchService.get().tap(RefMapper.devX(x), RefMapper.devY(y));
    }

    /**
     * ⭐ 弹窗系点击（v0.31 方案 B）：boss/战斗事件/探索/结算等居中面板锚定**设备屏幕中心**，
     * 与棋盘的「底锚」不是同一坐标系 ⇒ y 走 {@link RefMapper#devYDialog}。
     * PC / 9:16 屏上与 {@link #tapRef} 数学等价（C=0）⇒ 行为一字不变。
     */
    public static boolean tapRefDialog(float x, float y) {
        if (!AutoTouchService.ready()) {
            return false;
        }
        return AutoTouchService.get().tap(RefMapper.devX(x), RefMapper.devYDialog(y));
    }

    public static boolean tapRefHold(float x, float y, int ms) {
        if (!AutoTouchService.ready()) {
            return false;
        }
        return AutoTouchService.get().tap(RefMapper.devX(x), RefMapper.devY(y), ms);
    }

    public static boolean swipeRef(float x1, float y1, float x2, float y2, int ms) {
        if (!AutoTouchService.ready()) {
            return false;
        }
        return AutoTouchService.get().swipe(RefMapper.devX(x1), RefMapper.devY(y1),
                RefMapper.devX(x2), RefMapper.devY(y2), ms);
    }

    public static boolean backKey() {
        return AutoTouchService.ready() && AutoTouchService.get().back();
    }

    // ---------------- 等画面变化（避免 Python 反复取 PNG） ----------------

    public static double lastDim() {
        return lastDim;
    }

    /**
     * 等画面变化：与调用时的参考帧比，区域平均像素差 ≥ thr 就返回 true。
     * around(x,y,radius) 传 x>=0 时只看点击点周围（局部揭格更灵敏，同 PC 口径）。
     */
    public static boolean waitChange(double maxSec, int y0, int y1, double thr,
                                     double minSec, int ax, int ay, int radius) {
        Bitmap ref = FrameStore.get();
        if (ref == null) {
            sleep(minSec);
            return false;
        }
        // ⭐ 2026-10-01 修（全分辨率真 bug）：FrameStore 里是**原始设备帧**，
        //   而 y0/y1/ax/ay/radius 全是 **1080×1920 参考系**坐标（Python 侧契约，
        //   见 mapbot.py「Python 侧看不到像素尺寸差异」）—— 旧代码直接拿参考坐标
        //   在原始帧上采样 ⇒ 只在 1080×1920（kx=1、shift=0）上碰巧正确；
        //   真机 1280×2772（shift≈496）上观察窗整体**上移约 500px**（点的底行格子
        //   根本不在窗口里 ⇒ 每次点击都白等满超时；点击验证失真 ⇒ 误重试/连点）。
        //   ⇒ 采样前先把参考系坐标换算成设备像素（band 跨顶块/锚底两段时中间会多含
        //     一段弹性区，那是静态背景，对变化/稳定判定无害，且比"整段错位"好得多）。
        RefMapper.setScreen(ref.getWidth(), ref.getHeight());
        int rx0 = 0, rx1 = ref.getWidth();
        int ry0 = Math.max(0, Math.min(RefMapper.devY(y0), ref.getHeight()));
        int ry1 = Math.max(0, Math.min(RefMapper.devY(y1), ref.getHeight()));
        if (ry1 < ry0) {                    // 矮胖屏回退时理论不会，防一下
            int t = ry0;
            ry0 = ry1;
            ry1 = t;
        }
        if (ax >= 0) {
            int dx = RefMapper.devX(ax);
            int dy = RefMapper.devY(ay);
            int rr = RefMapper.devLen(radius);
            rx0 = Math.max(0, dx - rr);
            rx1 = Math.min(ref.getWidth(), dx + rr);
            ry0 = Math.max(0, dy - rr);
            ry1 = Math.min(ref.getHeight(), dy + rr);
        }
        int[] a = sample(ref, rx0, ry0, rx1, ry1, 6, 4);
        double refLuma = boardLuma(ref);
        long t0 = System.currentTimeMillis();
        while ((System.currentTimeMillis() - t0) < maxSec * 1000) {
            sleep(0.06);
            // ⭐ v0.25 立即停止：Python 端 `explore_android.stop()` 会置位 ⇒ 这里立刻返回
            if (consumeInterrupt()) {
                Log.i(TAG, "[stop] waitChange 被中断 ⇒ 立刻返回 false");
                return false;
            }
            if ((System.currentTimeMillis() - t0) < minSec * 1000) {
                continue;
            }
            Bitmap now = FrameStore.get();
            if (now == null || now.getWidth() != ref.getWidth()) {
                continue;
            }
            int[] b = sample(now, rx0, ry0, rx1, ry1, 6, 4);
            double d = meanAbsDiff(a, b);
            if (d >= thr) {
                double l = boardLuma(now);
                lastDim = refLuma > 1 ? (l / refLuma) : 1.0;
                return true;
            }
        }
        Bitmap now = FrameStore.get();
        if (now != null) {
            double l = boardLuma(now);
            lastDim = refLuma > 1 ? (l / refLuma) : 1.0;
        }
        return false;
    }

    /** 等画面**连续 need 次几乎不变**（thr 以下） */
    public static boolean waitStable(double maxSec, double thr, int need, int y0, int y1) {
        Bitmap prev = FrameStore.get();
        if (prev == null) {
            sleep(0.3);
            return false;
        }
        // ⭐ 2026-10-01 修：同 waitChange —— y0/y1 是参考系坐标，帧是原始设备帧，必须换算
        RefMapper.setScreen(prev.getWidth(), prev.getHeight());
        int dy0 = Math.max(0, Math.min(RefMapper.devY(y0), prev.getHeight()));
        int dy1 = Math.max(0, Math.min(RefMapper.devY(y1), prev.getHeight()));
        if (dy1 < dy0) {
            int t = dy0;
            dy0 = dy1;
            dy1 = t;
        }
        int[] a = sample(prev, 0, dy0, prev.getWidth(), dy1, 6, 4);
        int stable = 0;
        long t0 = System.currentTimeMillis();
        while ((System.currentTimeMillis() - t0) < maxSec * 1000) {
            sleep(0.08);
            // ⭐ v0.25 立即停止：同上 waitChange
            if (consumeInterrupt()) {
                Log.i(TAG, "[stop] waitStable 被中断 ⇒ 立刻返回 false");
                return false;
            }
            Bitmap now = FrameStore.get();
            if (now == null || now.getWidth() != prev.getWidth()) {
                continue;
            }
            int[] b = sample(now, 0, dy0, now.getWidth(), dy1, 6, 4);
            double d = meanAbsDiff(a, b);
            a = b;
            if (d < thr) {
                stable++;
                if (stable >= need) {
                    return true;
                }
            } else {
                stable = 0;
            }
        }
        return false;
    }

    // ---------------- 资源包（模板/数据表） ----------------

    /** 首次调用时把 assets/mapbot_pack 解到 filesDir/mapbot_pack（约 57MB，只解一次） */
    public static String packRoot() {
        if (appCtx == null) {
            return "";
        }
        return PackInstaller.ensure(appCtx);
    }

    /** ⭐ 2026-10-01 崩溃自恢复：拉起游戏到前台（MGAS 有悬浮窗权限 ⇒ 后台启动 Activity 豁免） */
    public static boolean bringGame() {
        try {
            android.content.Intent it = appCtx.getPackageManager()
                    .getLaunchIntentForPackage("com.chillyroom.monstergirls.yw");
            if (it == null) {
                AppLog.i("拉起游戏失败：未安装或包不可见（Manifest queries）");
                return false;
            }
            it.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK
                    | android.content.Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            appCtx.startActivity(it);
            return true;
        } catch (Throwable t) {
            AppLog.i("拉起游戏异常: " + t);
            return false;
        }
    }

    public static String runsRoot() {
        if (appCtx == null) {
            return "";
        }
        File d = new File(appCtx.getFilesDir(), "runs");
        if (!d.exists()) {
            d.mkdirs();
        }
        return d.getAbsolutePath();
    }

    // ---------------- 热更新（v1.41，见 Updater 类注释） ----------------

    /**
     * 热更状态一句话（诊断 / 反馈包用）。
     *
     * ⚠ 为什么反馈包里要有这个：朋友报"更新完还是老样子"时，第一件事就是确认
     *   **到底哪一层生效了** —— 补丁 id、有没有坏包、壳版本，缺一个都判不了。
     */
    public static String hotInfo() {
        if (appCtx == null) {
            return "appCtx 未绑定";
        }
        return Updater.statusLine(appCtx);
    }

    /** 当前生效的热更目录（Python 侧拿它填 `MAPBOT_HOT`，没有则空串） */
    public static String hotDir() {
        if (appCtx == null) {
            return "";
        }
        String p = Updater.hotActivePath(appCtx);
        return p == null ? "" : p;
    }

    /**
     * ⭐ 触发更新（Python 侧也能调；悬浮条 / 广播走的是同一条路）。
     *
     * @param mode check / hot / apk / auto（语义见 {@link Updater#run}）
     * @return 给人看的一句话
     * ⚠ **会阻塞**（网络下载，整包几十秒）⇒ 调用方必须自己在后台线程里调。
     */
    public static String update(String mode) {
        if (appCtx == null) {
            return "appCtx 未绑定";
        }
        return Updater.run(appCtx, mode == null || mode.isEmpty() ? "check" : mode);
    }

    public static String filesDir() {
        return appCtx == null ? "" : appCtx.getFilesDir().getAbsolutePath();
    }

    public static void log(String s) {
        AppLog.i(s == null ? "null" : s);
    }

    // ---------------- 内部 ----------------

    private static void sleep(double sec) {
        try {
            Thread.sleep((long) (sec * 1000));
        } catch (InterruptedException ignored) {
        }
    }

    /** 隔行隔列采样（比整块 getPixels 便宜得多，均值仍无偏） */
    private static int[] sample(Bitmap bmp, int x0, int y0, int x1, int y1,
                                int stepRow, int stepCol) {
        int w = Math.max(1, x1 - x0);
        int rows = Math.max(1, (y1 - y0 + stepRow - 1) / stepRow);
        int cols = Math.max(1, (w + stepCol - 1) / stepCol);
        int[] out = new int[rows * cols];
        int[] row = new int[w];
        int i = 0;
        for (int y = y0; y < y1; y += stepRow) {
            try {
                bmp.getPixels(row, 0, w, x0, y, w, 1);
            } catch (Throwable t) {
                break;
            }
            for (int x = 0; x < w && i < out.length; x += stepCol) {
                out[i++] = row[x];
            }
        }
        return out;
    }

    private static double meanAbsDiff(int[] a, int[] b) {
        int n = Math.min(a.length, b.length);
        if (n == 0) {
            return 0;
        }
        long sum = 0;
        for (int i = 0; i < n; i++) {
            int pa = a[i], pb = b[i];
            sum += Math.abs(((pa >> 16) & 0xff) - ((pb >> 16) & 0xff))
                    + Math.abs(((pa >> 8) & 0xff) - ((pb >> 8) & 0xff))
                    + Math.abs((pa & 0xff) - (pb & 0xff));
        }
        return sum / (3.0 * n);
    }

    /**
     * ⭐ 2026-10-01 v1.17：**手动设置顶部安全区偏移**（设备像素）。
     *
     * <p>用途：模拟器没有挖孔/状态栏 ⇒ {@code detectTopInset()} 恒读到 0，
     * 于是「顶块锚顶 + 其余锚底」这个模型在模拟器上**测不到 topInset 分支**
     * （真机 Redmi 是 132px，realme 同量级）。
     * 本方法让测试可以注入一个 inset，在模拟器上复现真机那种「顶部有黑/挖孔」的布局，
     * 从而把顶块相关的坐标换算也纳入回归。
     *
     * <p>传 0 即恢复自动（下次 {@code detectTopInset} 会覆盖它）。
     */
    public static void setTopInset(int px) {
        RefMapper.setTopInset((float) Math.max(0, px));
    }

    /** 读回当前顶部安全区偏移（设备像素，v1.17 新增）。 */
    public static int topInset() {
        return RefMapper.topInsetPx();
    }

    /** 棋盘带亮度（PC 端用来判「面板把棋盘压暗了」）。
     *  ⭐ 2026-10-01 修：1002/1722 是**参考系**行号，帧是原始设备帧 ⇒ 必须走 devY
     *    （旧代码在真机 1280×2772 上量的是参考 427~1016 那段世界场景，根本不是棋盘） */
    private static double boardLuma(Bitmap bmp) {
        RefMapper.setScreen(bmp.getWidth(), bmp.getHeight());
        int y0 = Math.max(0, Math.min(RefMapper.devY(1002), bmp.getHeight()));
        int y1 = Math.max(0, Math.min(RefMapper.devY(1722), bmp.getHeight()));
        if (y1 - y0 < 50) {
            return 1;
        }
        int[] s = sample(bmp, 0, y0, bmp.getWidth(), y1, 12, 8);
        long sum = 0;
        for (int p : s) {
            sum += (((p >> 16) & 0xff) * 299 + ((p >> 8) & 0xff) * 587 + (p & 0xff) * 114) / 1000;
        }
        return s.length > 0 ? sum / (double) s.length : 1;
    }
}
