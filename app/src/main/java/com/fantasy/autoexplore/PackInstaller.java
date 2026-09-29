package com.fantasy.autoexplore;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * 资源包安装器：把 `assets/mapbot_pack`（模板 + 数据表）解到 filesDir/mapbot_pack。
 *
 * 为什么必须解包：mapbot 的识别模块用 `glob` + `cv2.imread(路径)` 逐个读 PNG，
 * 必须存在**真实文件**（APK 内的 assets 不是文件系统）。只在首启解一次（带标记文件）。
 */
public final class PackInstaller {

    private static final String MARK = ".pack_v2";

    private PackInstaller() {
    }

    public static synchronized String ensure(Context ctx) {
        File root = new File(ctx.getFilesDir(), "mapbot_pack");
        File mark = new File(root, MARK);
        if (mark.exists()) {
            return root.getAbsolutePath();
        }
        long t0 = System.currentTimeMillis();
        AppLog.i("首次解包模板/数据表 → " + root.getAbsolutePath());
        try {
            int n = copyAssetDir(ctx, "mapbot_pack", root);
            try (FileOutputStream fos = new FileOutputStream(mark)) {
                fos.write("ok".getBytes());
            }
            AppLog.i("解包完成：" + n + " 个文件，" + (System.currentTimeMillis() - t0) + "ms");
        } catch (Throwable t) {
            AppLog.i("⚠ 解包失败：" + t);
        }
        return root.getAbsolutePath();
    }

    private static int copyAssetDir(Context ctx, String assetPath, File dst) throws Exception {
        String[] children = ctx.getAssets().list(assetPath);
        int count = 0;
        if (children == null || children.length == 0) {
            // 是文件
            if (!dst.getParentFile().exists()) {
                dst.getParentFile().mkdirs();
            }
            try (InputStream is = ctx.getAssets().open(assetPath);
                 OutputStream os = new FileOutputStream(dst)) {
                byte[] buf = new byte[1 << 16];
                int n;
                while ((n = is.read(buf)) > 0) {
                    os.write(buf, 0, n);
                }
            }
            return 1;
        }
        if (!dst.exists()) {
            dst.mkdirs();
        }
        for (String c : children) {
            if (c.startsWith(".")) {
                continue;
            }
            count += copyAssetDir(ctx, assetPath + "/" + c, new File(dst, c));
        }
        return count;
    }
}
