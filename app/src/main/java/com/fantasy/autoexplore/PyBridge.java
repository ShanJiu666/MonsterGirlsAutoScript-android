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

    /**
     * 保证 Python 运行时已起来（幂等 ✓ 线程安全 ✓）。
     *
     * <p>⭐⭐ 2026-10-03 热更新接进来，**三步的先后次序是硬约束**：
     * <ol>
     *   <li>{@code Updater.bootRecover} —— 在 Python 起来<b>之前</b>把热更补丁激活/回滚掉。
     *       晚了就没意义：模块一旦被 import 就进了 {@code sys.modules}，再换目录也不会重载。</li>
     *   <li>{@code Python.start} + 把热更目录插到 {@code sys.path[0]} —— 必须早于**任何**
     *       {@code getModule("explore_android")}（本工程唯一的 Python 入口就是 {@link #module}，
     *       所以插在这里一定能抢先 ✓）。</li>
     *   <li>{@code Updater.onPythonStarted} —— 自检。⚠ 必须在 {@code started = true} **之后**调：
     *       它内部会走 {@link #call} → {@link #ensureStarted}，重入时直接 return，不会递归。</li>
     * </ol>
     */
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
        Updater.bootRecover(c);                 // ① 激活 / 回滚（必须在 start 之前）
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(c));
            AppLog.i("Chaquopy Python 已启动：" + Python.getInstance().getModule("sys")
                    .get("version").toString().split("\\n")[0]);
        }
        injectHotPath(c);                       // ② 热更目录插 sys.path[0]
        started = true;
        Updater.onPythonStarted(c);             // ③ 自检（可回滚；重入安全）
    }

    /**
     * 把热更目录插到 {@code sys.path[0]}。
     *
     * <p>原理：Chaquopy 的 APK 内置模块放在 {@code assets/chaquopy/*.imy}（zip 形态），
     * 标准 import 按 {@code sys.path} 顺序找 —— 真实目录排在前面就能<b>覆盖同名模块</b> ✓。
     * 补丁里带哪些模块就换哪些，其余照旧走内置（这是分模块热更的关键）。
     *
     * <p>⚠ 只在 {@link #ensureStarted} 调一次（那里有 {@code started} 挡着），不需要去重；
     * 目录被回滚删掉后这条 path 自然失效，Python 回落内置版 —— 这正是我们要的 ✓。
     */
    private static void injectHotPath(Context c) {
        try {
            String hot = Updater.hotActivePath(c);
            if (hot == null) {
                return;
            }
            PyObject path = Python.getInstance().getModule("sys").get("path");
            path.callAttr("insert", 0, hot);
            AppLog.i("热更目录已插入 sys.path[0]：" + hot);
        } catch (Throwable t) {
            AppLog.i("⚠ 插入热更目录失败（继续用内置版本）：" + t);
        }
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
