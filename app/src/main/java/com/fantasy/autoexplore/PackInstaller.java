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

    /**
     * ⭐⭐⭐ v1.68：标记名**必须随资源包内容变** —— 它是「已解包」的唯一判据。
     *
     * ⛔ 旧值 `.pack_v3` 从 v1.08 起没动过，而 `ensure()` 是「标记在就直接 return」
     *   ⇒ **已装过旧版的真机永远拿不到新加的模板** ✗✗
     *   本轮就撞上了：v1.68 新增 `templates/ui/slot_done.png`（槽位「已完成」领取判据），
     *   而 v1.67 的机器上 `.pack_v3` 早就在 ⇒ 解包整段跳过 ⇒ 新模板**不存在**
     *   ⇒ 判据在真机上**恒不可用**，而代码**不报错、不崩、门禁也可能全绿** ✗
     *   —— 与 PC 端热更 T13j~T13n 那条（「代码到了、图没到」）是**同一族** bug ✓
     * ⚠ **以后每次往 `assets/mapbot_pack/` 加/改资源，都要把这里的版本号 +1**
     *   （门禁 `v1.68 A⑨` 守着这件事与 Python 侧的外置目录回退同时存在 ✓）
     *
     * ⭐ v2.108：`.pack_v12` → `.pack_v13` —— 换了「情报」按钮模板
     *   （旧 `templates/guild_intel_btn.png` 122×72 与当前 UI 尺度不符 ⇒ 匹配最高 0.537
     *     < 0.90 ⇒ 该层从未命中 ⇒ 每次都掉到盲点兜底 ⇒ 点低 330px）。
     *   新模板 `templates/ui/guild_intel_btn.png` 129×136，真帧实测命中 1.000 ✓
     *   ⚠ 不提版本号 ⇒ 已装 .pack_v12 的设备**永远拿不到**新模板，而且不报错 ✗
     *
     * ⭐ v2.108b：`.pack_v13` → `.pack_v14` —— 情报按钮模板**再换一次**：
     *   129×136 整块（含右上角红点徽标）在"奖励已领完"的帧上只有 **0.863 < 0.90**
     *   ⇒ 改成 **146×53 只裁红底条**，有/无徽标两帧都是 1.000 ✓
     */
    private static final String MARK = ".pack_v14";

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
