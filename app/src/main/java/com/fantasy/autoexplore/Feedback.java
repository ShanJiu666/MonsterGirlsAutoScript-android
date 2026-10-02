package com.fantasy.autoexplore;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.DisplayMetrics;
import android.view.WindowManager;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * Feedback —— ⭐ 2026-10-01 v1.14【一键反馈】。
 *
 * 用户口径（原话）：「能不能加个按钮能更方便让朋友发他的问题给我」
 *
 * 干什么：悬浮条上那颗「反馈」一点 ⇒
 *   ① 把**诊断所需的一切**打成一个 zip：
 *        · `mgas_log.txt`     —— Python 侧每轮收尾落的可读日志（统计 + 最近 400 条）
 *        · `device.txt`       —— 机型 / 系统版本 / **屏幕分辨率与 dpi** / 应用版本 / 悬浮条几何
 *                              ⭐ v1.33 另含**本次运行的现场帧清单**（文件名/时刻/尺寸/大小）
 *        · 诊断帧 png          —— **只收本次运行落下的**（`board_hidden_*` / `marks_none_*` /
 *                              `dice_nobtn` / `vault_no_hit_*`，最多 8 张）
 *        · `last_summary.json` —— 最近一次跑的统计（私有目录，应用自己能读 ✓）
 *   ② 用**系统分享面板**把它发出去（微信/QQ 直接选）—— 朋友不用会找文件、不用会跑 adb ✓
 *
 * ⭐⭐⭐ v1.33【只带"这一局"的帧】—— 用户 2026-10-02 报：
 *   「反馈包里的图**不是他刚刚运行的图**，和之前的图一样」✗
 *   根因：诊断帧写**固定文件名**，Python 侧静默覆盖且从不清理 ⇒ 这一局没触发那个分支
 *        就没新文件，目录里剩的还是上次的旧帧，而这里把它们一股脑全塞进包 ✓
 *        （实证：realme 两包相隔 3 小时，`board_hidden_r0.png` 的 md5 完全相同）
 *   两端各修一半：Python 侧**开跑先清干净**（`_clear_stale_diag_frames()`），
 *     这里再加一道**时间闸**（只收 mtime ≥ 本次运行的帧）⇒ 就算还有残留也带不出去 ✓
 *
 * 为什么走 MediaStore（而不是 androidx FileProvider / 直接 file:// URI）：
 *   · `file://` 在 API 24+ 会抛 `FileUriExposedException` ✗
 *   · FileProvider 要引 androidx 依赖（本工程**没有** androidx，加依赖要联网拉包 ✗）
 *   · `MediaStore.Downloads` 在 API 29+ **不需要任何存储权限**，而且直接给出可分享的
 *     `content://` URI ✓（API 26~28 退化成"写公共文件 + 只分享路径文本"）
 *
 * ⚠ 只做"收集 + 分享"，**不改任何运行状态**（随时可点，重复点只是多打几个包 ✓）。
 */
public final class Feedback {

    private static final String TAG = "MGAS反馈";
    private static final String PUB_DIR = Environment.getExternalStorageDirectory()
            + "/Download/autoexplore";
    private static final int MAX_FRAMES = 8;
    private static final long MAX_BYTES = 40L * 1024 * 1024;      // 包体上限，防超长录屏帧
    /** ⭐ v1.33：本次运行标记文件（Python 侧 `_clear_stale_diag_frames()` 写的） */
    private static final String RUN_MARKER = "_run_marker.json";
    /** 诊断帧白名单前缀 —— 只有这些名字的 png 才是"现场帧"（其余是玩家自己的东西，不该进包） */
    private static final String[] FRAME_PREFIXES = {
            "board_hidden_", "marks_none_", "dice_nobtn", "vault_no_hit_",
    };

    private Feedback() {
    }

    /** 收集 + 分享；返回一句给人看的结果（同时也会写进悬浮条日志行 ✓）。 */
    public static String collectAndShare(Context ctx) {
        String msg;
        Uri shareUri = null;
        File plainFile = null;
        try {
            String ts = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date());
            String zipName = "MGAS反馈_" + ts + ".zip";
            List<File> extras = new ArrayList<>();
            File pub = new File(PUB_DIR, "bagdbg");
            addIfExists(extras, new File(pub, "mgas_log.txt"));
            // ⭐⭐⭐ v1.33 治【反馈包里的图是陈货】：只收**本次运行**落下的帧
            //   （用户 2026-10-02 原话：「反馈包里的图不是他刚刚运行的图，和之前的图一样」✗
            //    字节级实证：realme 两包相隔 3 小时，`board_hidden_r0.png` 的 md5 完全相同）
            //   三道闸：
            //     ① 白名单前缀（只认诊断帧，不夹带玩家自己的图片 ✓）
            //     ② mtime ≥ 运行标记里的 `run_started`（**比本次运行早的旧帧一律不带** ✓）
            //     ③ 落不到闸子的（老版本 APK 没写过标记）⇒ 照收，但清单里**标"可能陈旧"** ✓
            StringBuilder frameNote = new StringBuilder();
            long runStarted = readRunStarted(pub);
            List<File> frames = collectFrames(pub, runStarted, frameNote);
            for (File f : frames) {
                extras.add(f);
            }
            File runs = new File(ctx.getFilesDir(), "runs");
            addIfExists(extras, new File(runs, "last_summary.json"));

            String deviceTxt = deviceInfo(ctx, runStarted, frames, frameNote);
            if (Build.VERSION.SDK_INT >= 29) {
                shareUri = zipViaMediaStore(ctx, zipName, extras, deviceTxt);
            }
            if (shareUri == null) {                 // API 26~28 / MediaStore 失败 ⇒ 退化
                plainFile = zipToPublicFile(zipName, extras, deviceTxt);
            }
            if (shareUri == null && plainFile == null) {
                msg = "反馈包生成失败（存储不可写）";
            } else if (shareUri != null) {
                boolean ok = share(ctx, shareUri, zipName);
                msg = ok ? ("反馈包已生成 · 分享面板已打开（选微信/QQ 发我）")
                         : ("反馈包已生成在 Download/autoexplore/" + zipName);
            } else {
                boolean ok = shareText(ctx, plainFile, zipName);
                msg = ok ? ("反馈包在 Download/autoexplore/" + zipName + " · 已打开分享")
                         : ("反馈包在 Download/autoexplore/" + zipName);
            }
        } catch (Throwable t) {
            msg = "反馈失败：" + t;
            AppLog.i(TAG + " " + t);
        }
        AppLog.i("\u203a " + msg);          // › 前缀 ⇒ 进悬浮条日志行 ✓
        return msg;
    }

    // ---------------- 包内容 ----------------

    private static void addIfExists(List<File> out, File f) {
        try {
            if (f != null && f.isFile() && f.length() > 0) {
                out.add(f);
            }
        } catch (Throwable ignored) {
        }
    }

    /**
     * ⭐ v1.33：读本次运行的起始时刻（毫秒）。读不到 ⇒ 返回 0（= 不设时间闸）。
     *
     * 来源：Python 侧 `_clear_stale_diag_frames()` 在**每次开跑**时写的 `_run_marker.json`。
     * 解析刻意宽松：只抠出第一个形如 `"run_started": <数字>` 的数，不引 JSON 库
     * （本工程没有 androidx / 也没有第三方 JSON，org.json 虽在但轻量手抠更可控 ✓）。
     */
    private static long readRunStarted(File bagdbg) {
        File mk = new File(bagdbg, RUN_MARKER);
        if (!mk.isFile()) {
            return 0L;
        }
        try {
            String s = readText(mk);
            int i = s.indexOf("\"run_started\"");
            if (i < 0) {
                return 0L;
            }
            int j = s.indexOf(':', i);
            if (j < 0) {
                return 0L;
            }
            int k = j + 1;
            while (k < s.length() && (s.charAt(k) == ' ' || s.charAt(k) == '\t')) {
                k++;
            }
            // ⚠⚠ 必须吃下 **JSON 数字的全部形态**：整数 / 小数 / **科学计数法**
            //   （2026-10-02 离线实跑当场抓到：`1.79E9` 这种写法会让"只认数字和点"的
            //    解析截成 `1.79` ⇒ 毫秒算成 1790 ⇒ 时间闸**全程失效**、
            //    所有陈旧帧照收不误 ✗✗ 症状与"根本没修"完全一样，极难察觉）
            int e = k;
            while (e < s.length() && (Character.isDigit(s.charAt(e))
                    || s.charAt(e) == '.' || s.charAt(e) == 'e' || s.charAt(e) == 'E'
                    || s.charAt(e) == '+' || s.charAt(e) == '-')) {
                e++;
            }
            if (e <= k) {
                return 0L;
            }
            String num = s.substring(k, e);
            double sec;
            try {
                sec = Double.parseDouble(num);
            } catch (Throwable t) {
                AppLog.i(TAG + " 运行标记数值解析失败（" + num + "）⇒ 不设时间闸");
                return 0L;
            }
            if (sec <= 0) {
                return 0L;
            }
            long ms = (long) (sec * 1000.0);
            // ⚠ 单位是**秒**（Python `time.time()`）。换算后必须落在"2001~2100 年的毫秒"里：
            //   正常值 ≈ 1.0e12 ~ 4.1e12；写成毫秒的话换算后会到 1e15 ⇒ 判为无效 ✓
            //   （阈值别拍脑袋：`1e11` 比真实毫秒还小，会把**所有正常标记**误杀成"没有闸" ✗
            //     —— 2026-10-02 离线实跑当场抓到这一条，才没让它进 APK ✓）
            if (ms < 978307200000L || ms > 4102444800000L) {
                AppLog.i(TAG + " 运行标记时间戳量级不对（" + ms + "）⇒ 不设时间闸");
                return 0L;
            }
            return ms;
        } catch (Throwable t) {
            AppLog.i(TAG + " 读运行标记失败（不设时间闸）：" + t);
            return 0L;
        }
    }

    private static String readText(File f) {
        StringBuilder sb = new StringBuilder();
        try (java.io.InputStream in = new java.io.FileInputStream(f)) {
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) {
                sb.append(new String(buf, 0, n, "UTF-8"));
            }
        } catch (Throwable t) {
            return "";
        }
        return sb.toString();
    }

    /**
     * ⭐ v1.33：挑出**该带进包的诊断帧**（新→旧排），并把判定过程写进 `note`。
     *
     * @param runStarted 本次运行起始（毫秒）；0 = 没有时间闸（老版本 APK）
     */
    private static List<File> collectFrames(File bagdbg, long runStarted, StringBuilder note) {
        List<File> out = new ArrayList<>();
        int stale = 0, notDiag = 0;
        File[] all;
        try {
            all = bagdbg.listFiles((d, n) -> n != null && n.toLowerCase(Locale.US).endsWith(".png"));
        } catch (Throwable t) {
            all = null;
        }
        if (all == null) {
            return out;
        }
        List<File> keep = new ArrayList<>();
        for (File f : all) {
            String n = f.getName();
            boolean isDiag = false;
            for (String p : FRAME_PREFIXES) {
                if (n.startsWith(p)) {
                    isDiag = true;
                    break;
                }
            }
            if (!isDiag) {
                notDiag++;
                continue;
            }
            if (runStarted > 0 && f.lastModified() + 1000L < runStarted) {
                stale++;                     // ⭐ 早于本次运行 ⇒ 陈货，不带
                continue;
            }
            keep.add(f);
        }
        keep.sort((a, b) -> Long.compare(b.lastModified(), a.lastModified()));   // 新→旧 ✓
        for (int i = 0; i < keep.size() && i < MAX_FRAMES; i++) {
            out.add(keep.get(i));
        }
        note.append("  诊断帧: 收 ").append(out.size()).append(" 张（本次运行落下的）")
            .append("；已剔除陈旧帧 ").append(stale).append(" 张")
            .append("；非诊断 png ").append(notDiag).append(" 张未收\n");
        if (stale > 0) {
            note.append("  ⚠ 有 ").append(stale)
                .append(" 张比本次运行更早的旧帧，已**排除**（它们不属于这次运行）\n");
        }
        if (out.isEmpty()) {
            note.append("  ⚠ 本次运行**没有落任何诊断帧**")
                .append("（说明这次没触发截图分支，不是丢包）\n");
        }
        return out;
    }

    private static String deviceInfo(Context ctx, long runStarted, List<File> frames,
                                     StringBuilder frameNote) {
        StringBuilder sb = new StringBuilder();
        sb.append("MGAS 反馈包\n");
        sb.append("生成时间: ").append(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
                .format(new Date())).append('\n');
        try {
            PackageInfo pi = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0);
            sb.append("应用版本: ").append(pi.versionName)
              .append(" (versionCode ").append(pi.versionCode).append(")\n");
        } catch (Throwable t) {
            sb.append("应用版本: 读取失败 ").append(t).append('\n');
        }
        sb.append("机型: ").append(Build.MANUFACTURER).append(' ').append(Build.MODEL).append('\n');
        sb.append("系统: Android ").append(Build.VERSION.RELEASE)
          .append(" (API ").append(Build.VERSION.SDK_INT).append(")\n");
        try {
            WindowManager wm = (WindowManager) ctx.getSystemService(Context.WINDOW_SERVICE);
            DisplayMetrics dm = new DisplayMetrics();
            wm.getDefaultDisplay().getRealMetrics(dm);
            sb.append("屏幕: ").append(dm.widthPixels).append('x').append(dm.heightPixels)
              .append("  dpi=").append(dm.densityDpi)
              .append("  density=").append(dm.density).append('\n');
        } catch (Throwable t) {
            sb.append("屏幕: 读取失败 ").append(t).append('\n');
        }
        try {
            sb.append("悬浮条: ").append(OverlayService.dump()).append('\n');
        } catch (Throwable t) {
            sb.append("悬浮条: 读取失败 ").append(t).append('\n');
        }
        // ⭐⭐ v1.33【本次运行的帧清单】—— 治"图不是我刚跑的那张"的自证闸：
        //   逐张写清「文件名 / 落盘时刻 / 尺寸 / 大小」⇒ 收件人一眼能对
        //   "包里的图" 与 "包里的日志" 是不是同一局 ✗ 以前这里**什么证据都没有** ✓
        sb.append("\n---- 本次运行的现场帧 ----\n");
        if (runStarted > 0) {
            sb.append("本次运行开始于: ")
              .append(fmtMs(runStarted)).append('\n');
        } else {
            sb.append("本次运行开始于: 未知（没有运行标记 —— 该包由 v1.32 及更早的 APK 生成）\n");
        }
        sb.append(frameNote == null ? "" : frameNote.toString());
        if (frames != null && !frames.isEmpty()) {
            for (File f : frames) {
                try {
                    sb.append("  · ").append(f.getName())
                      .append("  落盘 ").append(fmtMs(f.lastModified()))
                      .append("  ").append(sizeOfPng(f))
                      .append('\n');
                } catch (Throwable ignored) {
                }
            }
        }
        sb.append("\n（这份文件 + mgas_log.txt + 上面列出的帧 就是定位问题所需的东西 ✓）\n");
        return sb.toString();
    }

    private static String fmtMs(long ms) {
        try {
            return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
                    .format(new Date(ms));
        } catch (Throwable t) {
            return String.valueOf(ms);
        }
    }

    /** 读 PNG 头里的宽高（IHDR）—— 纯字节解析，不解码整图 ✓ */
    private static String sizeOfPng(File f) {
        try (java.io.RandomAccessFile ra = new java.io.RandomAccessFile(f, "r")) {
            byte[] h = new byte[26];
            if (ra.read(h) != 26) {
                return "?x?";
            }
            int w = ((h[16] & 0xff) << 24) | ((h[17] & 0xff) << 16)
                    | ((h[18] & 0xff) << 8) | (h[19] & 0xff);
            int ht = ((h[20] & 0xff) << 24) | ((h[21] & 0xff) << 16)
                    | ((h[22] & 0xff) << 8) | (h[23] & 0xff);
            return w + "x" + ht + " " + (f.length() / 1024) + "KB";
        } catch (Throwable t) {
            return "?x?";
        }
    }

    private static void writeZip(OutputStream os, List<File> extras, String deviceTxt)
            throws IOException {
        ZipOutputStream z = new ZipOutputStream(os);
        try {
            z.putNextEntry(new ZipEntry("device.txt"));
            z.write(deviceTxt.getBytes("UTF-8"));
            z.closeEntry();
            long total = 0;
            for (File f : extras) {
                if (f.length() > MAX_BYTES) {
                    continue;
                }
                total += f.length();
                if (total > MAX_BYTES) {
                    break;
                }
                z.putNextEntry(new ZipEntry(f.getName()));
                try (FileInputStream in = new FileInputStream(f)) {
                    byte[] buf = new byte[64 * 1024];
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        z.write(buf, 0, n);
                    }
                }
                z.closeEntry();
            }
        } finally {
            z.finish();
            z.close();
        }
    }

    /** API 29+：写进 MediaStore.Downloads（**无需任何权限**）并拿到可分享的 content:// URI */
    private static Uri zipViaMediaStore(Context ctx, String name, List<File> extras,
                                       String deviceTxt) {
        OutputStream os = null;
        Uri item = null;
        try {
            android.content.ContentValues cv = new android.content.ContentValues();
            cv.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
            cv.put(MediaStore.MediaColumns.MIME_TYPE, "application/zip");
            cv.put(MediaStore.MediaColumns.RELATIVE_PATH,
                    Environment.DIRECTORY_DOWNLOADS + "/autoexplore");
            item = ctx.getContentResolver().insert(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
            if (item == null) {
                return null;
            }
            os = ctx.getContentResolver().openOutputStream(item);
            if (os == null) {
                return null;
            }
            writeZip(os, extras, deviceTxt);
            os.flush();
            AppLog.i(TAG + " zip -> " + item);
            return item;
        } catch (Throwable t) {
            AppLog.i(TAG + " MediaStore 写包失败（退化到公共文件）：" + t);
            return null;
        } finally {
            try {
                if (os != null) {
                    os.close();
                }
            } catch (Throwable ignored) {
            }
        }
    }

    /** 退化路径（API 26~28 / MediaStore 不可用）：直接写公共 Download 目录 */
    private static File zipToPublicFile(String name, List<File> extras, String deviceTxt) {
        try {
            File dir = new File(PUB_DIR);
            if (!dir.exists() && !dir.mkdirs()) {
                return null;
            }
            File out = new File(dir, name);
            try (FileOutputStream fos = new FileOutputStream(out)) {
                writeZip(fos, extras, deviceTxt);
            }
            return out;
        } catch (Throwable t) {
            AppLog.i(TAG + " 写公共包失败：" + t);
            return null;
        }
    }

    // ---------------- 分享 ----------------

    private static boolean share(Context ctx, Uri uri, String name) {
        try {
            Intent send = new Intent(Intent.ACTION_SEND);
            send.setType("application/zip");
            send.putExtra(Intent.EXTRA_STREAM, uri);
            send.putExtra(Intent.EXTRA_SUBJECT, name);
            send.putExtra(Intent.EXTRA_TEXT,
                    "MGAS 反馈包（内含日志 + 机型信息 + 现场帧）。麻烦把这个文件发给我，谢谢！");
            send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            Intent chooser = Intent.createChooser(send, "把 MGAS 反馈包发给开发者");
            chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(chooser);
            return true;
        } catch (Throwable t) {
            AppLog.i(TAG + " 分享失败：" + t);
            return false;
        }
    }

    /** 只能给路径时：分享一段**文本**（朋友在微信里长按/从文件管理器附上那个 zip ✓） */
    private static boolean shareText(Context ctx, File f, String name) {
        try {
            Intent send = new Intent(Intent.ACTION_SEND);
            send.setType("text/plain");
            send.putExtra(Intent.EXTRA_SUBJECT, name);
            send.putExtra(Intent.EXTRA_TEXT,
                    "MGAS 反馈包路径：Download/autoexplore/" + name
                            + "\n（请把这个文件发给我；内含日志 + 机型信息 + 现场帧）");
            Intent chooser = Intent.createChooser(send, "把 MGAS 反馈包发给开发者");
            chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(chooser);
            return true;
        } catch (Throwable t) {
            AppLog.i(TAG + " 文本分享失败：" + t);
            return false;
        }
    }

    /** 给命令行/广播用：只生成、不弹分享面板（调试方便 ✓） */
    public static String collectOnly(Context ctx) {
        try {
            String ts = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date());
            String zipName = "MGAS反馈_" + ts + ".zip";
            List<File> extras = new ArrayList<>();
            File pub = new File(PUB_DIR, "bagdbg");
            addIfExists(extras, new File(pub, "mgas_log.txt"));
            StringBuilder note = new StringBuilder();
            long rs = readRunStarted(pub);
            List<File> fr = collectFrames(pub, rs, note);
            extras.addAll(fr);
            File out = zipToPublicFile(zipName, extras, deviceInfo(ctx, rs, fr, note));
            return out == null ? "生成失败" : ("已生成 " + out.getAbsolutePath());
        } catch (Throwable t) {
            return "生成失败 " + t;
        }
    }

    @SuppressWarnings("unused")
    private static void unusedWriterRef(Writer w) {   // 保留 import 以便后续扩展文本输出
    }
}
