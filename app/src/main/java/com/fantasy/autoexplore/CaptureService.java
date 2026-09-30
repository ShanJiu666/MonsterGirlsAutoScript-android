package com.fantasy.autoexplore;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.WindowManager;

import java.nio.ByteBuffer;

/**
 * 截图通道 = MediaProjection（官方 API，无 root）。
 *
 * 链路：MediaProjection → VirtualDisplay → ImageReader(RGBA_8888) → Bitmap → FrameStore
 *
 * ⚠ 安卓 14+ 硬性要求：
 *   ① 必须先 startForeground(…, FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION) 再拿 MediaProjection；
 *   ② 拿到的 MediaProjection 必须 registerCallback（否则 createVirtualDisplay 会抛异常）。
 */
public class CaptureService extends Service {

    public static final String EXTRA_CODE = "code";
    public static final String EXTRA_DATA = "data";
    private static final String TAG = "CaptureService";
    private static final String CHAN = "autoexplore";
    private static final int NOTIF_ID = 1001;

    private MediaProjection projection;
    private VirtualDisplay vdisplay;
    private ImageReader reader;
    private HandlerThread thread;
    private Handler handler;

    private final MediaProjection.Callback cb = new MediaProjection.Callback() {
        @Override
        public void onStop() {
            Log.w(TAG, "MediaProjection 被系统停止");
            release();
            stopSelf();
        }
    };

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) {
            stopSelf();
            return START_NOT_STICKY;
        }
        int code = intent.getIntExtra(EXTRA_CODE, 0);
        Intent data = intent.getParcelableExtra(EXTRA_DATA);
        if (data == null) {
            stopSelf();
            return START_NOT_STICKY;
        }

        createChannel();
        Notification n = new Notification.Builder(this, CHAN)
                .setContentTitle(getString(R.string.app_name))
                .setContentText("截图通道运行中")
                .setSmallIcon(android.R.drawable.ic_menu_view)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
        } else {
            startForeground(NOTIF_ID, n);
        }

        startCapture(code, data);
        return START_NOT_STICKY;
    }

    private void startCapture(int code, Intent data) {
        release();
        MediaProjectionManager mpm =
                (MediaProjectionManager) getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        projection = mpm.getMediaProjection(code, data);
        if (projection == null) {
            Log.e(TAG, "getMediaProjection 返回 null");
            stopSelf();
            return;
        }
        projection.registerCallback(cb, new Handler(getMainLooper()));

        int[] size = realScreenSize();
        int w = size[0], h = size[1];
        int dpi = realDensity();
        RefMapper.detectTopInset(this);       // ⭐ 真机安全区（状态栏/挖孔）；无界面也能拿到（服务有窗口度量）

        thread = new HandlerThread("capture");
        thread.start();
        handler = new Handler(thread.getLooper());

        reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2);
        reader.setOnImageAvailableListener(this::onFrame, handler);

        vdisplay = projection.createVirtualDisplay("autoexplore", w, h, dpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.getSurface(), null, handler);
        Log.i(TAG, "开始截图 " + w + "x" + h + " dpi=" + dpi);
        AppLog.i("截图通道已启动：" + w + "x" + h + "（dpi " + dpi + "）");
        staleRescues = 0;
        handler.postDelayed(watchdog, WATCHDOG_MS);
    }

    // ⭐ 2026-09-30 截图流看门狗：MediaProjection 偶发断流（ImageReader 不再出帧，
    //   FrameStore 冻结在旧帧 ⇒ 机器人变"瞎子"：OCR 全空、点击打在真实画面的无关位置、
    //   wait_change 永远等不到变化 —— 模拟器 00:2x 连续两场 boss 后退图失败即此：
    //   画面正常、无障碍正常、唯独机器人看不见，90 秒退图超时）。
    //   ⇒ 每 4s 查 FrameStore 帧龄：>8s 先重建 ImageReader 并 setSurface 重挂
    //     （复用同一 projection，无需重新授权，setSurface 必触发一帧新画面）；
    //     连 3 次都救不活才明确报错让人处理。静止画面误报由"重挂必出新帧"天然排除。
    private static final long WATCHDOG_MS = 4000;
    private static final long STALE_MS = 8000;
    private int staleRescues = 0;

    private final Runnable watchdog = new Runnable() {
        @Override
        public void run() {
            try {
                long age = System.currentTimeMillis() - FrameStore.stamp();
                if (FrameStore.has() && age > STALE_MS) {
                    staleRescues++;
                    if (staleRescues <= 3) {
                        AppLog.i("截图流 " + (age / 1000) + "s 无新帧 ⇒ 自救 #" + staleRescues
                                + "（重建 ImageReader）");
                        rebuildReader();
                    } else {
                        AppLog.i("截图流断流且自救失败 ×" + staleRescues
                                + " ⇒ 需重新授权截图（重启应用后点①授权截图）");
                    }
                } else {
                    staleRescues = 0;
                }
            } catch (Throwable t) {
                Log.w(TAG, "watchdog: " + t);
            }
            if (handler != null) {
                handler.postDelayed(this, WATCHDOG_MS);
            }
        }
    };

    private void rebuildReader() {
        try {
            if (reader != null) {
                reader.setOnImageAvailableListener(null, null);
                reader.close();
            }
            int[] size = realScreenSize();
            reader = ImageReader.newInstance(size[0], size[1], PixelFormat.RGBA_8888, 2);
            reader.setOnImageAvailableListener(this::onFrame, handler);
            if (vdisplay != null) {
                vdisplay.setSurface(reader.getSurface());
            }
            Log.i(TAG, "ImageReader 已重建");
        } catch (Throwable t) {
            Log.w(TAG, "rebuildReader: " + t);
        }
    }

    /** 真实屏幕像素（含状态栏/导航栏，与 PC 端 adb screencap 口径一致） */
    private int[] realScreenSize() {
        DisplayMetrics dm = new DisplayMetrics();
        WindowManager wm = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
        if (Build.VERSION.SDK_INT >= 30) {
            android.view.WindowMetrics wmx = wm.getMaximumWindowMetrics();
            android.graphics.Rect r = wmx.getBounds();
            return new int[]{r.width(), r.height()};
        }
        wm.getDefaultDisplay().getRealMetrics(dm);
        return new int[]{dm.widthPixels, dm.heightPixels};
    }

    private int realDensity() {
        if (Build.VERSION.SDK_INT >= 30) {
            return getResources().getDisplayMetrics().densityDpi;
        }
        DisplayMetrics dm = new DisplayMetrics();
        WindowManager wm = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
        wm.getDefaultDisplay().getRealMetrics(dm);
        return dm.densityDpi;
    }

    /** ImageReader 回调：转 Bitmap（处理 rowStride 填充） */
    private void onFrame(ImageReader ir) {
        Image img = null;
        try {
            img = ir.acquireLatestImage();
            if (img == null) {
                return;
            }
            Image.Plane p = img.getPlanes()[0];
            ByteBuffer buf = p.getBuffer();
            int w = img.getWidth();
            int h = img.getHeight();
            int rowStride = p.getRowStride();
            int pixelStride = p.getPixelStride();

            Bitmap bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
            if (pixelStride == 4 && rowStride == w * 4) {
                bmp.copyPixelsFromBuffer(buf);
            } else {
                int[] pixels = new int[w * h];
                byte[] row = new byte[rowStride];
                for (int y = 0; y < h; y++) {
                    buf.position(y * rowStride);
                    int n = Math.min(rowStride, buf.remaining());
                    buf.get(row, 0, n);
                    ByteBuffer rb = ByteBuffer.wrap(row);
                    rb.asIntBuffer().get(pixels, y * w, w);
                }
                bmp.setPixels(pixels, 0, w, 0, 0, w, h);
            }
            FrameStore.set(bmp);
        } catch (Throwable t) {
            Log.w(TAG, "取帧失败: " + t);
        } finally {
            if (img != null) {
                img.close();
            }
        }
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm.getNotificationChannel(CHAN) == null) {
                nm.createNotificationChannel(
                        new NotificationChannel(CHAN, "MGAS", NotificationManager.IMPORTANCE_LOW));
            }
        }
    }

    private void release() {
        if (handler != null) {
            handler.removeCallbacks(watchdog);
        }
        try {
            if (vdisplay != null) {
                vdisplay.release();
            }
        } catch (Throwable ignored) {
        }
        vdisplay = null;
        try {
            if (reader != null) {
                reader.close();
            }
        } catch (Throwable ignored) {
        }
        reader = null;
        try {
            if (projection != null) {
                projection.unregisterCallback(cb);
                projection.stop();
            }
        } catch (Throwable ignored) {
        }
        projection = null;
    }

    @Override
    public void onDestroy() {
        release();
        if (thread != null) {
            thread.quitSafely();
        }
        thread = null;
        AppLog.i("截图通道已停止");
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
