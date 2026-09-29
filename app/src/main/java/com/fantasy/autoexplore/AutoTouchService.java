package com.fantasy.autoexplore;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;

/**
 * 点击通道 = 无障碍手势（无 root，产生**真实触摸事件流**）。
 *
 * 对应 PC 端 airtest 的 touch/swipe/keyevent：这里换成
 * dispatchGesture（点/滑）与 performGlobalAction（返回/主页）。
 */
public class AutoTouchService extends AccessibilityService {

    private static final String TAG = "AutoTouch";
    private static volatile AutoTouchService instance;

    public static AutoTouchService get() {
        return instance;
    }

    public static boolean ready() {
        return instance != null;
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        AppLog.i("无障碍服务已连接（点击通道就绪）");
    }

    @Override
    public void onDestroy() {
        instance = null;
        AppLog.i("无障碍服务已断开");
        super.onDestroy();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // 本应用不消费任何事件，只用它的手势能力
    }

    @Override
    public void onInterrupt() {
    }

    /** 单击（ms 为按住时长，60~80ms 与手指轻点接近） */
    public boolean tap(float x, float y, int ms) {
        Path p = new Path();
        p.moveTo(x, y);
        GestureDescription.StrokeDescription s = new GestureDescription.StrokeDescription(p, 0, ms);
        return dispatchGesture(new GestureDescription.Builder().addStroke(s).build(), null, null);
    }

    public boolean tap(float x, float y) {
        return tap(x, y, 70);
    }

    /** 滑动 */
    public boolean swipe(float x1, float y1, float x2, float y2, int ms) {
        Path p = new Path();
        p.moveTo(x1, y1);
        p.lineTo(x2, y2);
        GestureDescription.StrokeDescription s = new GestureDescription.StrokeDescription(p, 0, ms);
        return dispatchGesture(new GestureDescription.Builder().addStroke(s).build(), null, null);
    }

    /** 系统返回 */
    public boolean back() {
        return performGlobalAction(GLOBAL_ACTION_BACK);
    }

    public boolean home() {
        return performGlobalAction(GLOBAL_ACTION_HOME);
    }

    /** 带回调的点击（等手势真正完成/取消） */
    public void tapSync(float x, float y, int ms, Runnable done) {
        Path p = new Path();
        p.moveTo(x, y);
        GestureDescription.StrokeDescription s = new GestureDescription.StrokeDescription(p, 0, ms);
        Handler h = new Handler(Looper.getMainLooper());
        boolean ok = dispatchGesture(new GestureDescription.Builder().addStroke(s).build(),
                new GestureResultCallback() {
                    @Override
                    public void onCompleted(GestureDescription gd) {
                        h.post(done);
                    }

                    @Override
                    public void onCancelled(GestureDescription gd) {
                        Log.w(TAG, "手势被取消");
                        h.post(done);
                    }
                }, h);
        if (!ok) {
            h.post(done);
        }
    }
}
