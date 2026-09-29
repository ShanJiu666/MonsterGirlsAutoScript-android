package com.fantasy.autoexplore;

import android.content.Context;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/**
 * Chaquopy（Python）桥：把 Java 侧的命令转成 Python 调用。
 *
 * ⭐ Python 层入口 = `explore_android`（模块内自己做环境变量装配，见该文件头注释）。
 * ⚠ Python 启动是**一次性**的（`Python.start` 只能调一次）⇒ 用 ensureStarted 包住。
 */
public final class PyBridge {

    private static volatile boolean started = false;
    private static volatile Context appCtx;

    private PyBridge() {
    }

    /**
     * 记录 ApplicationContext。绑定之后，任何 `call(...)` 都会**自动保证 Python 已启动**
     * —— 否则广播入口（没有走界面）会撞
     * `RuntimeException: Cannot use GenericPlatform on Android`。
     */
    public static void bind(Context ctx) {
        appCtx = ctx.getApplicationContext();
    }

    /** 保证 Python 运行时已起来（幂等 ✓ 线程安全 ✓） */
    public static synchronized void ensureStarted(Context ctx) {
        if (ctx != null) {
            appCtx = ctx.getApplicationContext();
        }
        if (started) {
            return;
        }
        Context c = appCtx;
        if (c == null) {
            throw new IllegalStateException("PyBridge.bind(context) 还没调用过");
        }
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(c));
            AppLog.i("Chaquopy Python 已启动：" + Python.getInstance().getModule("sys")
                    .get("version").toString().split("\\n")[0]);
        }
        started = true;
    }

    public static PyObject module(String name) {
        ensureStarted(null);
        return Python.getInstance().getModule(name);
    }

    /** 调 `explore_android.<fn>(...)` 并返回字符串结果（异常也转成字符串，不抛给调用方） */
    public static String call(String fn, Object... args) {
        try {
            PyObject r = module("explore_android").callAttr(fn, args);
            return r == null ? "" : r.toString();
        } catch (Throwable t) {
            AppLog.i("⚠ Python 调用 " + fn + " 失败：" + t);
            return "error: " + t;
        }
    }
}
