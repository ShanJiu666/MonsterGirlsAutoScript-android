package com.fantasy.autoexplore;

import android.util.Log;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * 日志（同时进 logcat、界面滚动区、悬浮窗日志行）—— 手机上没有控制台，界面就是控制台。
 *
 * ⭐ 2026-09-29（用户："日志显示改成和电脑上窗口类似的日志"）：
 *   PC 端 GUI 的日志框里是**循环原始输出**（`explore_loop.say()` 那些行，带前导空格的缩进），
 *   **没有时间戳前缀**。手机屏幕窄，每行再顶 9 个字符的 `HH:mm:ss ` 会把正文挤到折行
 *   ⇒ 拆开：
 *     · **界面/快照** = 原始行（`● MGAS`、`== 第 1 张图 ==` …），与 PC 窗口一致 ✓
 *     · **logcat**     = 仍带 `HH:mm:ss` 前缀（事后排查要时间轴 ✓）
 *
 * ⭐ 同日：监听改成**多播**（`addListener`/`removeListener`）—— 界面和悬浮窗日志行要**同时**收；
 *   原来只有一个 listener 槽位，两处都设会互相顶掉（后设的赢）✗
 */
public final class AppLog {

    private static final String TAG = "AutoExplore";
    private static final List<String> lines = new ArrayList<>();
    private static final CopyOnWriteArrayList<Listener> listeners = new CopyOnWriteArrayList<>();

    public interface Listener {
        void onLine(String line);
    }

    private AppLog() {
    }

    /** 追加一个监听（可多个；记得在 onDestroy 里 {@link #removeListener}） */
    public static void addListener(Listener l) {
        if (l != null && !listeners.contains(l)) {
            listeners.add(l);
        }
    }

    public static void removeListener(Listener l) {
        listeners.remove(l);
    }

    /** 兼容旧调用：**清掉其它监听**只留这一个（新代码请用 addListener） */
    public static void setListener(Listener l) {
        listeners.clear();
        addListener(l);
    }

    public static synchronized void i(String msg) {
        String plain = msg == null ? "null" : msg;
        Log.i(TAG, stamp() + " " + plain);           // logcat 带时间戳
        lines.add(plain);                            // 界面不带（PC 窗口风格）
        if (lines.size() > 400) {
            lines.remove(0);
        }
        for (Listener l : listeners) {
            try {
                l.onLine(plain);
            } catch (Throwable ignored) {
                // ⚠ 单个监听出错不能拖垮日志本身（悬浮窗那侧尤其容易抛）
            }
        }
    }

    public static synchronized List<String> snapshot() {
        return new ArrayList<>(lines);
    }

    public static synchronized void clear() {
        lines.clear();
    }

    private static String stamp() {
        java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("HH:mm:ss",
                java.util.Locale.US);
        return f.format(new java.util.Date());
    }
}
