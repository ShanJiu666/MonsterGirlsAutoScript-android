package com.fantasy.autoexplore;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * 广播命令入口（调试/自动化用，手机日常不用）：
 *
 *   adb shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
 *        -a com.fantasy.autoexplore.CMD --es cmd test_ocr
 *
 * ⚠ 必须带 `-n`（显式组件）：安卓 8+ 对**隐式广播**不投递，只写 `-a` 会毫无反应。
 *
 * ── 设备层命令 ────────────────────────────────────────────────
 *   init_ocr / test_ocr / tap_start / scan_all / dump
 *
 * ── Python 层命令（Chaquopy）──────────────────────────────────
 *   pyinfo                       环境快照（资源包路径/数据表/模板码）
 *   selftest                     端上全套自检（资源→OCR→截图→地块分类→规划器）
 *   py   --es code "<python>"    跑任意 Python 片段（⚠ **仅调试包**，release 已禁）
 *   explore --ei maps 1 ...      启动探索（后台线程）
 *                                ⭐ 还认 `--ez auto_supply true`（没体力自动用补给）
 *                                   和 `--ei bag_every 10`（每 N 张图升一次装备星级）
 *   explore_stop                 请求停止（打完手上这张图收工）
 *   explore_status               查进度（返回值里带 `red_locked`）
 *   summary                      最近一次运行的「本次统计」文本（PC 同款）
 *
 * ── 红装锁（⑥）────────────────────────────────────────────
 *   red_lock                     查红装锁（{} = 没锁）
 *   red_unlock                   解锁（处理完红装后点这个才能重新开跑）
 *
 * ── 悬浮条（M5）────────────────────────────────────────────
 *   overlay_on                   开悬浮控制条（**不必把界面拉到前台**）
 *   overlay_off                  关悬浮控制条
 *   overlay_dump                 ⭐ 读悬浮条**当前状态**（展开?/SECURE?/几何/日志行原文/最近 12 条）
 *                                —— 加了 FLAG_SECURE 之后 `screencap` 看不见它了，只能走这个口
 *   overlay_state --es state run|idle|err|lock|auto
 *                                dev：**强制状态灯颜色**（零体力验证"跑起来变绿 + 不收起"）
 *                                （⚠ **仅调试包**）
 *   mask_check                   dev：证明"机器人对自己瞎"（悬浮条那块在帧里必须是纯色）
 *                                （⚠ **仅调试包**）
 *   （或：am start -n com.fantasy.autoexplore/.MainActivity -e cmd overlay 切换）
 *
 * 例：
 *   ... --es cmd explore --ei maps 2 --ei max_round 45 --es tag t1 --ez save_first true
 * ⭐ 走广播而不是 Activity：**游戏在前台时也能触发**，不会把本应用顶到前台。
 *
 * ⚠⚠ 安全：Receiver 是 exported=true 且无鉴权 ⇒ 同设备任意 app 都能发广播。
 *   因此 `py`（= exec 任意 Python）/ `classify` / `overlay_state` / `overlay_roll` / `mask_check`
 *   这 5 个调试命令**只在 BuildConfig.DEBUG 时放行**（见 DEBUG_ONLY）；要调试请出 assembleArm64Debug。
 */
public class CommandReceiver extends BroadcastReceiver {

    public static final String ACTION = "com.fantasy.autoexplore.CMD";

    /**
     * ⭐⭐ v1.16 安全门：只在**调试包**放行的命令。
     *
     * <p>背景：本 Receiver 是 {@code exported=true} 且**无任何鉴权** ⇒ 同设备任意 app 发个广播即可触发。
     * 其中 {@code py --es code} 会走 {@code explore_android._cmd_run_snippet → exec(code)}，
     * 等价于<b>任意 Python 代码执行</b>（还能经 DeviceApi 拉起游戏、读设备信息）。
     * ⚠ release 包同样带这个 Receiver（release 只是 debug 签名 + 不混淆，**不是** debuggable）⇒ 风险一直在。
     *
     * <p>因此：下面这些命令在**非 DEBUG 构建**下一律拒绝并记日志。
     * 日常运维命令（explore / explore_stop / explore_status / summary / red_* / overlay_* /
     * feedback / pyinfo / selftest / test_ocr …）<b>不受影响</b>，照常可用。
     *
     * <p>要调试就出 {@code assembleArm64Debug}（可 run-as、DEBUG=true）。
     */
    private static final String[] DEBUG_ONLY = {
            "py",            // ⚠ exec 任意 Python —— RCE
            "classify",      // 读任意文件并跑识别（路径来自广播）
            "overlay_state", // dev 钩子：强制状态灯
            "overlay_roll",  // dev 钩子：滚动验证
            "mask_check",    // dev 钩子：涂平验证
            "set_inset",     // dev 钩子：手动注入顶部安全区（会改全局坐标换算）
    };

    private static boolean isDebugOnly(String cmd) {
        for (String d : DEBUG_ONLY) {
            if (d.equals(cmd)) {
                return true;
            }
        }
        return false;
    }

    @Override
    public void onReceive(Context ctx, Intent intent) {
        String cmd = intent.getStringExtra("cmd");
        if (cmd == null) {
            return;
        }
        Context app = ctx.getApplicationContext();
        DeviceApi.bind(app);            // 保证 DeviceApi.appCtx 就绪（没开过界面也能用 ✓）

        // ⭐ v1.16：调试命令在 release 包里直接拒（详见 DEBUG_ONLY 注释）
        if (isDebugOnly(cmd) && !BuildConfig.DEBUG) {
            AppLog.i("⛔ 命令 " + cmd + " 仅调试包可用（当前是 release 构建）⇒ 已拒绝");
            return;
        }

        AppLog.i("收到广播命令：" + cmd);
        new Thread(() -> {
            switch (cmd) {
                // ── 设备层 ──────────────────────────────
                case "init_ocr":
                    AutoPilot.ensureOcr(app);
                    break;
                case "test_ocr": {
                    AutoPilot.scan(app, 0.5f, true);
                    break;
                }
                case "tap_start": {
                    java.util.List<OcrItem> items = AutoPilot.scan(app, 0.5f, false);
                    OcrItem hit = AutoPilot.find(items, "开始冒险", "进入地图");
                    if (hit == null) {
                        AppLog.i("没找到「开始冒险/进入地图」（本帧 " + items.size() + " 条）");
                    } else {
                        AutoPilot.tapItem(hit);
                    }
                    break;
                }
                case "scan_all": {
                    java.util.List<OcrItem> items = AutoPilot.scan(app, 0.5f, true);
                    int n = Math.min(items.size(), 30);
                    for (int i = 0; i < n; i++) {
                        AppLog.i("   " + items.get(i));
                    }
                    break;
                }

                // ── Python 层 ───────────────────────────
                case "pyinfo":
                    AppLog.i("[pyinfo] " + PyBridge.call("info"));
                    break;
                case "selftest": {
                    boolean withBoard = !intent.hasExtra("board")
                            || intent.getBooleanExtra("board", true);
                    PyBridge.ensureStarted(app);
                    AppLog.i("[selftest]\n" + PyBridge.call("selftest", withBoard));
                    break;
                }
                case "py": {
                    String code = intent.getStringExtra("code");
                    if (code == null || code.trim().isEmpty()) {
                        AppLog.i("⚠ py 命令缺少 --es code");
                        break;
                    }
                    PyBridge.ensureStarted(app);
                    String r = PyBridge.call("_cmd_run_snippet", code);
                    AppLog.i("[py] " + r);
                    break;
                }
                case "classify": {
                    // ⭐ 零体力的端↔PC 等价性验证：同一张 PNG 两端各跑一次比逐格结果
                    //   --es img <设备上的路径> --es map S00003
                    PyBridge.ensureStarted(app);
                    String imgPath = intent.getStringExtra("img");
                    String mapCode = intent.getStringExtra("map");
                    if (imgPath == null) {
                        AppLog.i("⚠ classify 缺少 --es img <路径>");
                        break;
                    }
                    String r = PyBridge.call("classify_image", imgPath,
                            mapCode == null ? "S00003" : mapCode, true);
                    AppLog.i("[classify] " + (r.length() > 4000 ? r.substring(0, 4000) + "…" : r));
                    break;
                }
                case "explore": {
                    PyBridge.ensureStarted(app);
                    bringGameFront(app);        // ⭐ 2026-09-29：广播启动**也必须先把游戏切到前台**
                    String tag = intent.getStringExtra("tag");
                    String r = PyBridge.call("start",
                            intent.getIntExtra("maps", 1),
                            intent.getIntExtra("max_round", 45),
                            intent.getIntExtra("deadline", 900),
                            intent.getIntExtra("min_stamina", 25),
                            tag == null ? "" : tag,
                            intent.getBooleanExtra("opt_solver", true),
                            intent.getIntExtra("bag_every", 0),
                            intent.getBooleanExtra("save_first", true),
                            intent.getBooleanExtra("stop_at_5am", false),
                            intent.getBooleanExtra("auto_supply", false));
                    AppLog.i("[explore] " + r);
                    break;
                }
                case "explore_stop":
                    AppLog.i("[explore_stop] " + PyBridge.call("stop"));
                    break;
                case "explore_status":
                    AppLog.i("[explore_status] " + PyBridge.call("status"));
                    break;

                // ── 红装锁（⑥）──────────────────────────
                case "red_lock":
                    AppLog.i("[red_lock] " + PyBridge.call("red_lock"));
                    break;
                case "red_unlock":
                    AppLog.i("[red_unlock] " + PyBridge.call("red_unlock"));
                    break;
                case "summary":
                    AppLog.i("[summary]\n" + PyBridge.call("summary"));
                    break;
                case "overlay_on":
                    OverlayService.start(app);
                    AppLog.i("[overlay_on] 悬浮控制条已开启（不用把界面拉到前台 ✓）");
                    break;
                case "overlay_off":
                    app.stopService(new Intent(app, OverlayService.class));
                    AppLog.i("[overlay_off] 悬浮控制条已关闭");
                    break;
                case "overlay_dump":
                    // ⚠ 这个口是"看悬浮条"的**唯一**通道：加了 FLAG_SECURE 后截图/投屏里它是一片黑
                    AppLog.i("[overlay_dump]\n" + OverlayService.dump());
                    break;
                case "overlay_state":
                    // dev 验证钩子：强制状态灯颜色（零体力看"变绿 + 不收起"）
                    //   --es state run|idle|err|lock|auto
                    OverlayService.forceState(intent.getStringExtra("state"));
                    break;
                case "overlay_roll":
                    // dev 验证钩子：注入一条合成日志 + 连打 4 次 logRoll（证明"整行上下滚动"）
                    OverlayService.probeRoll();
                    break;
                case "mask_check":
                    // dev：证明"机器人对自己瞎"（悬浮条那块在帧里必须是纯色）
                    AppLog.i("[mask_check] " + DeviceApi.maskCheck());
                    break;
                case "set_inset":
                    // ⭐ v1.17：手动指定顶部安全区偏移（设备像素）。
                    //   用途：模拟器没有挖孔 ⇒ detectTopInset() 恒读 0，验不到顶块分支；
                    //   真机 Redmi/realme 是 ~132px。本命令可注入等效值，在模拟器上
                    //   复现真机那种「顶部有黑」的布局，把顶块坐标换算纳入回归。
                    //   用法：--es cmd set_inset --ei px 132    （--ei px 0 ⇒ 恢复自动）
                    DeviceApi.setTopInset(intent.getIntExtra("px", 0));
                    AppLog.i("[set_inset] 顶部安全区偏移 = " + DeviceApi.topInset()
                            + "px（0 = 恢复自动探测）");
                    break;

                case "feedback":
                    // ⭐ v1.14 一键反馈：与悬浮条「反馈」按钮**同一条代码路径** ✓
                    //   --es share 1 ⇒ 同时弹系统分享面板（默认只打包，方便脚本/调试 ✓）
                    new Thread(() -> {
                        try {
                            boolean _sh = "1".equals(intent.getStringExtra("share"));
                            // ⚠ BroadcastReceiver 自己不是 Context ⇒ 用 onReceive(ctx,…) 那个 ✓
                            Context _c = ctx.getApplicationContext();
                            String r = _sh ? Feedback.collectAndShare(_c)
                                           : Feedback.collectOnly(_c);
                            AppLog.i("[feedback] " + r);
                        } catch (Throwable t) {
                            AppLog.i("[feedback] 异常：" + t);
                        }
                    }, "cmd-feedback").start();
                    break;

                default:
                    AppLog.i("未知命令：" + cmd);
            }
        }, "cmd-" + cmd).start();
    }

    /**
     * ⭐ 把游戏切到前台（广播启动 explore 前必须做，否则脚本会对着**本应用自己的界面**跑：
     * 2026-09-29 04:41 实测 —— APK 在前台时广播 explore，OCR 43 条全是自己的按钮/日志文字，
     * "已进图" 误判、对着自己点了 12 分钟。悬浮条 ▶ 路径本来就会切（OverlayService.onStart），
     * 广播路径漏了 ⇒ 补上。游戏没起也能拉起（app 有悬浮窗权限 ⇒ 允许后台 startActivity）。）
     */
    private static void bringGameFront(Context app) {
        try {
            Intent li = app.getPackageManager().getLaunchIntentForPackage(OverlayService.GAME_PKG);
            if (li == null) {
                AppLog.i("⚠ 没找到游戏包 " + OverlayService.GAME_PKG + " ⇒ 请手动切回游戏");
                return;
            }
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            app.startActivity(li);
            AppLog.i("▶ 已切回游戏（等 1.5s 再开跑）");
            Thread.sleep(1500);             // 等游戏窗口回到前台
        } catch (Throwable t) {
            AppLog.i("⚠ 切游戏失败（" + t + "）⇒ 请手动切回游戏");
        }
    }
}
