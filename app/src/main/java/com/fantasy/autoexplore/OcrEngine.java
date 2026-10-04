package com.fantasy.autoexplore;

import android.content.Context;
import android.graphics.Bitmap;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.FloatBuffer;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

/**
 * 端侧 OCR：ONNX Runtime + RapidOCR 的 PP-OCRv4 det/rec 模型。
 *
 * ⭐ 与 PC 端 mapbot 的 RapidOCR **逐参数同口径**（照抄 rapidocr_onnxruntime 1.4.4）：
 *   Det: limit_side_len=736 / limit_type=min、mean=std=0.5、scale=1/255、
 *        thresh=0.3、box_thresh=0.5、unclip_ratio=1.6、use_dilation=true、score_mode=fast
 *   Rec: rec_img_shape=[3,48,320]、max_wh_ratio=max(320/48, w/h)、/255 → -0.5 → /0.5、
 *        CTC 解码（blank=0、去连续重复、置信度取所选字符 softmax 均值）
 *   另外沿用 PC 的 OCR_SCALE=0.75：参考帧 1080×1920 → 810×1440 再进 det（PC 一致）。
 *
 * 输出坐标一律换算回 **1080×1920 参考系**，与 PC 端 items 可直接对拍。
 */
public class OcrEngine {

    private static final String TAG = "OcrEngine";

    public static final float OCR_SCALE = 0.75f;
    public static final int SCALED_W = Math.round(RefMapper.REF_W * OCR_SCALE);   // 810
    public static final int SCALED_H = Math.round(RefMapper.REF_H * OCR_SCALE);   // 1440

    private static final int LIMIT_SIDE = 736;
    /**
     * ⭐ v1.42：窄带 det 输入的**短边下限**（新口径用；不是 RapidOCR 的 736）。
     *
     * <p>旧口径把任何窄带放大到短边 736（band 140px ⇒ 5 倍放大，
     * det 像素达 4.17M，比整帧 1.15M 还多 3.6 倍 —— 真机 2.33s/次，比整帧还贵一倍多）。
     * <p>新口径只补到 {@code 320}：够 PP-OCRv4 的 det 检出文字，又比 736 省 57%。
     * <p>调大 → 更稳但更慢；调小 → 更快但窄带可能漏检（最窄的 140px 带是读体力值的主力，
     * <b>别低于 256</b>）。
     */
    private static final int MIN_SHORT_SIDE = 320;
    private static final float DET_MEAN = 0.5f;
    private static final float DET_STD = 0.5f;
    private static final float DET_THRESH = 0.3f;
    private static final float BOX_THRESH = 0.5f;
    private static final float UNCLIP_RATIO = 1.6f;
    private static final int MIN_SIZE = 3;
    private static final int REC_H = 48;
    private static final int REC_MAX_W = 320;
    private static final int BLANK = 0;

    private OrtEnvironment env;
    private OrtSession detSession;
    private OrtSession recSession;
    private String detInput;
    private String recInput;
    private List<String> chars;
    private boolean ready;

    // 埋点
    public volatile long tDet = 0, tRec = 0, tPre = 0;
    public volatile int nDetBoxes = 0;

    public boolean isReady() {
        return ready;
    }

    public void init(Context ctx) {
        try {
            long t0 = System.currentTimeMillis();
            env = OrtEnvironment.getEnvironment();
            OrtSession.SessionOptions opts = new OrtSession.SessionOptions();
            opts.setIntraOpNumThreads(4);

            byte[] detBytes = readAsset(ctx, "ch_PP-OCRv4_det_infer.onnx");
            byte[] recBytes = readAsset(ctx, "ch_PP-OCRv4_rec_infer.onnx");
            detSession = env.createSession(detBytes, opts);
            recSession = env.createSession(recBytes, opts);
            detInput = detSession.getInputNames().iterator().next();
            recInput = recSession.getInputNames().iterator().next();

            chars = loadChars(readAssetText(ctx, "ppocr_keys.txt"));
            ready = true;
            AppLog.i("OCR 引擎就绪：" + chars.size() + " 类，加载耗时 "
                    + (System.currentTimeMillis() - t0) + "ms");
        } catch (Throwable t) {
            ready = false;
            AppLog.i("⚠ OCR 引擎初始化失败：" + t);
            Log.e(TAG, "init failed", t);
        }
    }

    /** 字典：metadata 的 6623 个字 + 头部 blank + 尾部空格 = 6625（与模型输出类数一致） */
    private static List<String> loadChars(String text) {
        List<String> list = new ArrayList<>();
        list.add("blank");
        for (String line : text.split("\n", -1)) {
            String s = line.replace("\r", "");
            if (s.isEmpty()) {
                continue;
            }
            list.add(s);
        }
        list.add(" ");
        return list;
    }

    /** 主入口：喂 1080×1920 参考帧，拿参考系坐标的识别结果（= 整帧，等价于 recognizeBand(0,1920)） */
    public List<OcrItem> recognize(Bitmap refBmp, float minConf) {
        return recognizeBand(refBmp, 0, RefMapper.REF_H, minConf);
    }

    /**
     * ⭐⭐ v1.42【det 缩放口径】：{@code "max"}（默认，长边缩）or {@code "min"}（旧，短边放）。
     *
     * <p><b>为什么默认改成 max</b>：旧口径复刻 rapidocr 的 {@code limit_type=min} ——
     * <b>短边不足 736 就放大回 736</b>，于是「裁得越窄、det 算得越多」：
     * 真机实测读一条 140px 的体力条，det 像素（2.92M）比整帧（1.15M）<b>还多一倍半</b>，
     * 单次 2.33s —— 比识别整幅棋盘（0.98s）贵一倍多 ✗
     *
     * <p><b>识别质量不变</b>：同一张图、同一模型，只是像素更少、文字等效更大（原来被放大，
     * 现在 1:1 ⇒ 反而更清晰）。整帧两条口径完全相同 ⇒ 行为零变化。
     *
     * <p><b>回滚</b>：系统属性 {@code -DOcrLimitMode=min} 或环境变量
     * {@code MGAS_OCR_LIMIT_MODE=min} 恢复旧口径。
     */
    public static String limitMode() {
        String v = null;
        try {
            // ⚠ 用 java.lang.System 而不是 android.os.System：
            //   `android.os.System.getProperty` 在部分设备/SDK 桩上不可用，
            //   `java.lang.System.getProperty` 是标准的、端上一定能拿到 ✓
            v = java.lang.System.getProperty("OcrLimitMode");
        } catch (Throwable ignored) {
            // 某些宿主（如 pythonw / 沙箱）会抛 ⇒ 忽略，走环境变量
        }
        if (v == null) {
            try {
                v = System.getenv("MGAS_OCR_LIMIT_MODE");
            } catch (Throwable ignored) {
                v = null;
            }
        }
        if (v != null && "min".equals(v.trim().toLowerCase(Locale.US))) {
            return "min";
        }
        return "max";
    }

    /**
     * ⭐ v0.61：**只识别参考帧的 [y0ref, y1ref) 这一段**（真裁图，不是识别后过滤）。
     *
     * <p>为什么必须裁：端侧 rec 占 OCR 总时间的 ~81%（累计 203.7s vs det 43.5s），而 rec 的
     * 成本 ∝ **框数**；裁掉上下的 HUD / 底部导航就少了一大批框。PC 端同一份代码实测
     * 整帧 0.75x 1.54s / 中段 band 0.79s（省 ~50%）—— 端侧以前 band 只做"整帧识别后过滤"，
     * 等于一直按整帧付钱（真机 2.41s/次 vs PC 0.76s/次，见 09-30 日报）。
     *
     * <p>⚠ det 的 limit_type=min 会把**矮带**放大（band 高 400 ⇒ 736/min 放大约 2.45 倍
     * ⇒ det 面积反而比整帧大）⇒ 调用方负责只在 Δy ≥ BAND_CROP_MIN 时才裁
     * （见 Python `mapbot.BAND_CROP_MIN`）。
     *
     * <p>⚠ y0ref=0 &amp; y1ref=REF_H 时**逐像素复用旧路径**（ratio 必为 1、det 800×1440），
     * 保证整帧识别的口径一字不变。
     */
    public List<OcrItem> recognizeBand(Bitmap refBmp, int y0ref, int y1ref, float minConf) {
        List<OcrItem> out = new ArrayList<>();
        if (!ready || refBmp == null) {
            return out;
        }
        final int chRef = Math.max(1, y1ref - y0ref);
        final boolean full = (y0ref == 0 && chRef == RefMapper.REF_H);
        long tAll = System.currentTimeMillis();
        // ⚠ tDet/tRec/tPre 是**累计**计数器（便于看全局占比）⇒ 这里先记快照，日志里报**本次**增量
        long preBefore = tPre, detBefore = tDet, recBefore = tRec;
        try {
            long p0 = System.currentTimeMillis();
            // ① 参考帧（的这一段）→ 0.75 倍（整帧 = 810×1440，与 PC 一致）
            Bitmap cropBmp = full ? refBmp
                    : Bitmap.createBitmap(refBmp, 0, y0ref, RefMapper.REF_W, chRef);
            int sw = SCALED_W;
            int sh = Math.max(1, Math.round(chRef * OCR_SCALE));
            Bitmap scaled = Bitmap.createScaledBitmap(cropBmp, sw, sh, true);
            int[] scaledPx = new int[sw * sh];
            scaled.getPixels(scaledPx, 0, sw, 0, 0, sw, sh);

            // ② det 预处理（/32 对齐；**缩放口径见 DET_LIMIT_MODE**）
            //
            // ⭐⭐ v1.42【只给「窄带」去掉放大惩罚】—— 真机实测（Redmi/1280×2772）
            //   整局 363 秒里 **OCR 占 185 秒（51%）**、109 次、平均 1.70s/次。
            //   旧口径（复刻 rapidocr 的 `limit_type=min`）**短边不足 736 就放大回 736**
            //   ⇒ 「裁得越窄、det 算得越多」：
            //     band 0~140（读体力条）⇒ det 5664×736 = **4.17M 像素**（整帧的 3.6 倍）✗
            //   真机耗时完全印证：`enter_stam`(140px) **2.33s/次**，
            //     比占整帧 75.6% 像素的 `battle`（0.98s/次）**还贵一倍多** ✗✗
            //
            // ⚠⚠ **不能简单换成 `limit_type=max`**（我第一版就犯了这个错）：
            //   max 的语义是「**长边**超 736 就缩小」⇒ 整帧 mx=1440 ⇒ 会被缩到
            //   416×736，**整帧识别也降近 2 倍** ⇒ 识别质量受损 ✗✗
            //   （而整帧/宽带正是 `round_full` 等大头，占 OCR 次数的相当一部分）
            //
            // ⇒ 现在的口径（`banded`，默认）：
            //     · **短边已经 ≥ 736** ⇒ 什么都不做（ratio=1）——**整帧与宽带逐像素不变** ✓
            //     · **短边 < 736（窄带）** ⇒ **按原尺寸**进 det（ratio=1），不再放大
            //       ⇒ 代价是文字在 det 输入里偏小 ⇒ 用**下限保护**兜底：
            //         短边至少放大到 320（够 det 检出文字，不会退化成"啥也认不出"）✓
            //   ⇒ 影响面**只有窄带**，整帧/中带/宽带**完全零变化** ✓
            // 回滚：系统属性 `-DOcrLimitMode=min` 或环境变量 `MGAS_OCR_LIMIT_MODE=min`
            //       ⇒ 恢复旧口径（短边放大到 736）。
            float ratio;
            if ("min".equals(limitMode())) {
                float mn = Math.min(sw, sh);
                ratio = mn < LIMIT_SIDE ? (LIMIT_SIDE / mn) : 1f;
            } else {
                // ⭐ 只在「短边不足」时才按比例补到 MIN_SHORT_SIDE，**绝不缩小**
                float mn = Math.min(sw, sh);
                ratio = mn < MIN_SHORT_SIDE ? (MIN_SHORT_SIDE / mn) : 1f;
            }
            int detW = Math.round(Math.round(sw * ratio / 32f)) * 32;
            int detH = Math.round(Math.round(sh * ratio / 32f)) * 32;
            Bitmap detBmp = Bitmap.createScaledBitmap(scaled, detW, detH, true);
            int[] detPx = new int[detW * detH];
            detBmp.getPixels(detPx, 0, detW, 0, 0, detW, detH);

            float[] chw = new float[3 * detH * detW];
            int plane = detH * detW;
            for (int i = 0; i < detPx.length; i++) {
                int p = detPx[i];
                float r = ((p >> 16) & 0xff) / 255f;
                float g = ((p >> 8) & 0xff) / 255f;
                float b = (p & 0xff) / 255f;
                chw[i] = (r - DET_MEAN) / DET_STD;
                chw[plane + i] = (g - DET_MEAN) / DET_STD;
                chw[2 * plane + i] = (b - DET_MEAN) / DET_STD;
            }
            tPre += System.currentTimeMillis() - p0;

            // ③ det 推理
            long d0 = System.currentTimeMillis();
            float[] prob;
            try (OnnxTensor in = OnnxTensor.createTensor(env, FloatBuffer.wrap(chw),
                    new long[]{1, 3, detH, detW});
                 OrtSession.Result res = detSession.run(Collections.singletonMap(detInput, in))) {
                OnnxTensor ot = (OnnxTensor) res.get(0);
                FloatBuffer fb = ot.getFloatBuffer();
                prob = new float[fb.remaining()];
                fb.get(prob);
            }
            tDet += System.currentTimeMillis() - d0;

            // ④ DB 后处理 → det 输入尺寸下的框
            List<int[]> boxes = dbPostProcess(prob, detH, detW);
            nDetBoxes = boxes.size();

            // ⑤ 逐框裁剪（在 sw×sh 帧上）+ rec
            long r0 = System.currentTimeMillis();
            float sx = sw / (float) detW;
            float sy = sh / (float) detH;
            for (int[] b : boxes) {
                int x0 = clamp(Math.round(b[0] * sx), 0, sw - 1);
                int y0 = clamp(Math.round(b[1] * sy), 0, sh - 1);
                int x1 = clamp(Math.round(b[2] * sx), 1, sw);
                int y1 = clamp(Math.round(b[3] * sy), 1, sh);
                if (x1 - x0 < 2 || y1 - y0 < 2) {
                    continue;
                }
                // ⚠ 不能用 Bitmap.createBitmap(int[],…,x,y,w,h,…) —— 那个 9 参重载不是公开 API
                //   （编译期报「参数列表长度不同」）⇒ 自己按行拷贝出子图
                int cw = x1 - x0, ch = y1 - y0;
                int[] cropPx = new int[cw * ch];
                for (int yy = 0; yy < ch; yy++) {
                    System.arraycopy(scaledPx, (y0 + yy) * sw + x0, cropPx, yy * cw, cw);
                }
                Bitmap crop = Bitmap.createBitmap(cropPx, cw, ch, Bitmap.Config.ARGB_8888);
                String[] rr = recOne(crop);
                if (rr == null) {
                    continue;
                }
                String text = rr[0];
                float conf = Float.parseFloat(rr[1]);
                if (text.trim().isEmpty() || conf < minConf) {
                    continue;
                }
                // ⑥ 坐标：裁剪帧的 0.75 倍 → 1080 宽的参考系（y 再补上裁剪起点 y0ref）
                int rx0 = Math.round(x0 / OCR_SCALE);
                int ry0 = Math.round(y0 / OCR_SCALE) + y0ref;
                int rx1 = Math.round(x1 / OCR_SCALE);
                int ry1 = Math.round(y1 / OCR_SCALE) + y0ref;
                out.add(new OcrItem(text, (rx0 + rx1) / 2, (ry0 + ry1) / 2,
                        rx0, ry0, rx1, ry1, conf));
            }
            tRec += System.currentTimeMillis() - r0;
            out.sort((a, b) -> a.cy != b.cy ? Integer.compare(a.cy, b.cy)
                    : Integer.compare(a.cx, b.cx));
            AppLog.i("OCR " + out.size() + " 条 / " + boxes.size() + " 框，"
                    + (System.currentTimeMillis() - tAll) + "ms"
                    + (full ? "" : " band " + y0ref + "~" + y1ref)
                    + "（本次 det " + (tDet - detBefore) + "｜rec " + (tRec - recBefore)
                    + "｜预处理 " + (tPre - preBefore) + "）");
        } catch (Throwable t) {
            AppLog.i("⚠ OCR 异常：" + t);
            Log.e(TAG, "recognize failed", t);
        }
        return out;
    }

    // ---------------- DB 后处理（照抄 rapidocr DBPostProcess） ----------------

    private List<int[]> dbPostProcess(float[] prob, int h, int w) {
        boolean[] mask = new boolean[h * w];
        for (int i = 0; i < h * w; i++) {
            mask[i] = prob[i] > DET_THRESH;
        }
        // cv2.dilate 2×2（anchor 默认中心）: dst(y,x)=max(src(y,x),src(y,x+1),src(y+1,x),src(y+1,x+1))
        boolean[] dil = new boolean[h * w];
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                boolean v = mask[y * w + x];
                if (!v && x + 1 < w) {
                    v = mask[y * w + x + 1];
                }
                if (!v && y + 1 < h) {
                    v = mask[(y + 1) * w + x];
                }
                if (!v && x + 1 < w && y + 1 < h) {
                    v = mask[(y + 1) * w + x + 1];
                }
                dil[y * w + x] = v;
            }
        }
        // 连通域（8 邻域，等价 findContours 的外轮廓）
        boolean[] seen = new boolean[h * w];
        int[] stack = new int[h * w];
        List<int[]> boxes = new ArrayList<>();
        for (int start = 0; start < h * w; start++) {
            if (!dil[start] || seen[start]) {
                continue;
            }
            int sp = 0;
            stack[sp++] = start;
            seen[start] = true;
            int minX = w, maxX = -1, minY = h, maxY = -1;
            while (sp > 0) {
                int id = stack[--sp];
                int y = id / w, x = id % w;
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
                for (int dy = -1; dy <= 1; dy++) {
                    for (int dx = -1; dx <= 1; dx++) {
                        if (dx == 0 && dy == 0) {
                            continue;
                        }
                        int nx = x + dx, ny = y + dy;
                        if (nx < 0 || ny < 0 || nx >= w || ny >= h) {
                            continue;
                        }
                        int nid = ny * w + nx;
                        if (dil[nid] && !seen[nid]) {
                            seen[nid] = true;
                            stack[sp++] = nid;
                        }
                    }
                }
            }
            int bw = maxX - minX + 1, bh = maxY - minY + 1;
            if (Math.min(bw, bh) < MIN_SIZE) {
                continue;
            }
            // box_score_fast：框内 prob 均值
            float sum = 0;
            int n = 0;
            for (int y = minY; y <= maxY; y++) {
                for (int x = minX; x <= maxX; x++) {
                    sum += prob[y * w + x];
                    n++;
                }
            }
            float score = n > 0 ? sum / n : 0f;
            if (score < BOX_THRESH) {
                continue;
            }
            // unclip：distance = area * ratio / length（矩形解析式）
            float area = (float) bw * bh;
            float perim = 2f * (bw + bh);
            float d = perim > 0 ? area * UNCLIP_RATIO / perim : 0f;
            float ux0 = minX - d, uy0 = minY - d, ux1 = maxX + d, uy1 = maxY + d;
            float uw = ux1 - ux0, uh = uy1 - uy0;
            if (Math.min(uw, uh) < MIN_SIZE + 2) {
                continue;
            }
            boxes.add(new int[]{
                    clamp(Math.round(ux0), 0, w), clamp(Math.round(uy0), 0, h),
                    clamp(Math.round(ux1), 0, w), clamp(Math.round(uy1), 0, h)});
        }
        return boxes;
    }

    // ---------------- rec 单框识别 ----------------

    private String[] recOne(Bitmap crop) {
        try {
            int w = crop.getWidth(), h = crop.getHeight();
            float ratio = w / (float) h;
            float maxWhRatio = Math.max(REC_MAX_W / (float) REC_H, ratio);
            int imgW = (int) (REC_H * maxWhRatio);
            int resizedW = (int) Math.ceil(REC_H * ratio);
            if (resizedW > imgW) {
                resizedW = imgW;
            }
            Bitmap rs = Bitmap.createScaledBitmap(crop, resizedW, REC_H, true);
            int[] px = new int[resizedW * REC_H];
            rs.getPixels(px, 0, resizedW, 0, 0, resizedW, REC_H);

            float[] chw = new float[3 * REC_H * imgW];
            int plane = REC_H * imgW;
            for (int y = 0; y < REC_H; y++) {
                for (int x = 0; x < resizedW; x++) {
                    int p = px[y * resizedW + x];
                    float r = ((p >> 16) & 0xff) / 255f;
                    float g = ((p >> 8) & 0xff) / 255f;
                    float b = (p & 0xff) / 255f;
                    int idx = y * imgW + x;
                    chw[idx] = (r - 0.5f) / 0.5f;
                    chw[plane + idx] = (g - 0.5f) / 0.5f;
                    chw[2 * plane + idx] = (b - 0.5f) / 0.5f;
                }
            }
            float[] logits;
            int steps;
            int classes;
            try (OnnxTensor in = OnnxTensor.createTensor(env, FloatBuffer.wrap(chw),
                    new long[]{1, 3, REC_H, imgW});
                 OrtSession.Result res = recSession.run(Collections.singletonMap(recInput, in))) {
                OnnxTensor ot = (OnnxTensor) res.get(0);
                long[] shape = ot.getInfo().getShape();
                steps = (int) shape[1];
                classes = (int) shape[2];
                FloatBuffer fb = ot.getFloatBuffer();
                logits = new float[steps * classes];
                fb.get(logits);
            }
            // CTC 解码：argmax → 去连续重复 → 去 blank → 置信度取所选字符概率均值
            StringBuilder sb = new StringBuilder();
            float confSum = 0;
            int confN = 0;
            int prev = -1;
            for (int t = 0; t < steps; t++) {
                int best = 0;
                float bestP = -1;
                int base = t * classes;
                for (int c = 0; c < classes; c++) {
                    float v = logits[base + c];
                    if (v > bestP) {
                        bestP = v;
                        best = c;
                    }
                }
                if (best != BLANK && best != prev) {
                    if (best < chars.size()) {
                        sb.append(chars.get(best));
                        confSum += bestP;
                        confN++;
                    }
                }
                prev = best;
            }
            float conf = confN > 0 ? confSum / confN : 0f;
            return new String[]{sb.toString(), Float.toString(conf)};
        } catch (Throwable t) {
            Log.w(TAG, "rec 单框失败: " + t);
            return null;
        }
    }

    // ---------------- 工具 ----------------

    private static int clamp(int v, int lo, int hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    private static byte[] readAsset(Context ctx, String name) throws Exception {
        try (InputStream is = ctx.getAssets().open(name);
             ByteArrayOutputStream bos = new ByteArrayOutputStream()) {
            byte[] buf = new byte[1 << 16];
            int n;
            while ((n = is.read(buf)) > 0) {
                bos.write(buf, 0, n);
            }
            return bos.toByteArray();
        }
    }

    private static String readAssetText(Context ctx, String name) throws Exception {
        return new String(readAsset(ctx, name), "UTF-8");
    }
}
