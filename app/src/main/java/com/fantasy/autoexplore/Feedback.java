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
 *        · `board_hidden_*.png` —— "被判成面板挡住棋盘"时的现场帧（最多 5 张）
 *        · `last_summary.json` —— 最近一次跑的统计（私有目录，应用自己能读 ✓）
 *   ② 用**系统分享面板**把它发出去（微信/QQ 直接选）—— 朋友不用会找文件、不用会跑 adb ✓
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
    private static final int MAX_FRAMES = 5;
    private static final long MAX_BYTES = 40L * 1024 * 1024;      // 包体上限，防超长录屏帧

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
            File[] frames = pub.listFiles((d, n) -> n != null && n.startsWith("board_hidden_")
                    && n.endsWith(".png"));
            if (frames != null) {
                java.util.Arrays.sort(frames, (a, b) -> Long.compare(b.lastModified(),
                        a.lastModified()));
                for (int i = 0; i < frames.length && i < MAX_FRAMES; i++) {
                    extras.add(frames[i]);
                }
            }
            addIfExists(extras, new File(pub, "vault_no_hit_L1.png"));
            addIfExists(extras, new File(pub, "vault_no_hit_L2.png"));
            File runs = new File(ctx.getFilesDir(), "runs");
            addIfExists(extras, new File(runs, "last_summary.json"));

            String deviceTxt = deviceInfo(ctx);
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

    private static String deviceInfo(Context ctx) {
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
        sb.append("\n（这份文件 + mgas_log.txt + board_hidden_*.png 就是定位问题所需的东西 ✓）\n");
        return sb.toString();
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
            File f = zipToPublicFile(zipName, extras, deviceInfo(ctx));
            return f == null ? "生成失败" : ("已生成 " + f.getAbsolutePath());
        } catch (Throwable t) {
            return "生成失败 " + t;
        }
    }

    @SuppressWarnings("unused")
    private static void unusedWriterRef(Writer w) {   // 保留 import 以便后续扩展文本输出
    }
}
