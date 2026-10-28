package com.fantasy.autoexplore;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.projection.MediaProjectionManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.text.method.ScrollingMovementMethod;
import android.util.TypedValue;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileOutputStream;
import java.util.List;
import java.util.Locale;

/**
 * 手机版自动探索（MGAS）· 设备层 + 视觉层 + 决策层
 *
 * 界面即控制台：授权 → 截图 → OCR → 点击，每步都能单独自测；
 * 识别结果与截图会落到 files/dump/，可拉到电脑和 PC 端逐条对拍。
 *
 * ⭐ 2026-09-29（用户 6 条需求）：
 *   ① 日志区改成 **PC 窗口风格**（等宽字体、**不带时间戳前缀**）+ 下方独立「本次统计」面板
 *   ④ 「没体力自动用补给」勾选框 ⑤ 「每 X 张图升级装备星级」（默认 10）⑥ 「红装解锁」按钮
 *   （③ 1图/连刷 在悬浮条上；设置项存在 {@link Prefs}，悬浮条与界面读同一份 ✓）
 */
public class MainActivity extends Activity {

    private static final int REQ_CAPTURE = 1001;
    /** 界面自动刷新节拍（状态 + 统计） */
    private static final long TICK_MS = 2000;

    private final Handler ui = new Handler(Looper.getMainLooper());
    /** ⭐ 2026-09-30：日志订阅句柄。**必须用 addListener 存句柄**——见 onCreate 里的说明。 */
    private AppLog.Listener logListener;
    private TextView logView;
    /** 当前页：0=运行 1=配置 2=诊断 */
    private int page = 0;
    /** 页面容器（切页时换它的 child） */
    private LinearLayout pageHost;
    /** 底栏三个 tab（切页时重画激活态） */
    private final TextView[] navTabs = new TextView[3];
    /** 首页日志/统计切换：0=日志 1=统计 */
    private int logTab = 0;
    private TextView tabLog, tabSum;
    /** 大字状态 + 副标题 + 环形（每 tick 刷新） */
    private TextView bigStatus, subStatus;
    private UiKit.RingView ring;
    /** 三格读数：体力 / 幸运草 / 金币 */
    private TextView statStamina, statClover, statCoin;
    /** 主按钮（待机=启动 / 运行中=停止 / 红装锁=解锁），复用一个位置 */
    private TextView mainBtn;
    private int mainBtnMode = 0;
    /** 就绪条的三颗点与三格值 */
    private View dotCapture, dotTouch, dotLock;
    private TextView valCapture, valTouch, valLock;
    private TextView sumView;
    private TextView statusView;
    private TextView overlayBtn;
    private CheckBox cbSupply;
    // ⭐ v1.78：收工日常五颗勾选（与 Prefs 一一对应 ✓）
    private CheckBox cbGuildTasks;
    private CheckBox cbGuildAlchemy;
    private CheckBox cbGuildIntel;
    private CheckBox cbRecruitFree;
    private CheckBox cbAdFree;
    /** ⭐ v1.91 日常前置（刷图前先做日常） */
    private CheckBox cbDailyFirst;
    private EditText etBagEvery;
    private boolean overlayOn = false;
    /** 当前是否在跑（由 tick 从 Python status 读，供主按钮/大字区切换） */
    private volatile boolean running = false;
    /** 上一次画过的统计文本（变了才重设，避免光标/滚动乱跳） */
    private String lastSummary = null;
    /** 红装锁状态文案（由后台 tick 更新；refreshStatus 只负责画，不再同步调 Python） */
    private volatile String redLockText = "?";

    // ── 特殊方块勾选（v1.46；学 PC 端 `0e43db5` / `2ab3105`）──
    /** 勾选排所在卡片（放「更新」下面 —— 用户口径 ✓） */
    private LinearLayout cardSp;
    /** 勾选行的容器（buildUi 只搭骨架；行由 `fillSpecialRows()` 在 PyBridge 绑好后填 ✓） */
    private LinearLayout spBody;
    /** 占位/错误提示行 */
    private TextView spLoading;
    /** 已成功填过一次就不重复填（避免每次 tick 都重建 View ✓） */
    private boolean spFilled = false;
    /** ⭐ v1.79：空清单的日志只打一次（tick 每 2 秒一次，别刷屏） */
    private boolean spLoggedFail = false;

    /** 界面自动刷新（可见时才跑）：后台读 Python → 回主线程画（⚠ 绝不在 UI 线程调 Python） */
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            new Thread(() -> {
                String t = "";
                String r = "{}";
                String st = "{}";
                try {
                    t = PyBridge.call("summary");
                } catch (Throwable e) {
                    t = "";
                }
                try {
                    r = PyBridge.call("red_lock");
                } catch (Throwable e) {
                    r = "{}";
                }
                // ⭐ 主按钮要靠它区分"待机/跑图中"（与悬浮条同一个判据源，别各读各的）
                try {
                    st = PyBridge.call("status");
                } catch (Throwable e) {
                    st = "{}";
                }
                // ⭐ 三格读数：**只读旧值、不触发新 OCR**（见 explore_android.hud 的注释）
                String hudJson = "{}";
                try {
                    hudJson = PyBridge.call("hud");
                } catch (Throwable e) {
                    hudJson = "{}";
                }
                final String ft = t == null ? "" : t.trim();
                final String fr = r == null ? "{}" : r.trim();
                final String fs = st == null ? "{}" : st.trim();
                final String fh = hudJson == null ? "{}" : hudJson.trim();
                ui.post(() -> {
                    redLockText = (fr.isEmpty() || "{}".equals(fr)) ? "无" : "有（先解锁）";
                    running = fs.contains("'running': True");
                    applyHud(fh);
                    showSummary(ft);
                    // ⭐ v1.46：特殊方块勾选**兜底重试** ——
                    //   Python 冷启动要几秒，onCreate 里那一次可能还没就绪；
                    //   这里每轮试到填上为止（`spFilled` 置位后本调用直接返回 ✓）
                    fillSpecialRows();
                    refreshStatus();
                });
            }, "ui-poll").start();
            ui.postDelayed(this, TICK_MS);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        RefMapper.detectTopInset(this);           // ⭐ 真机安全区（状态栏/挖孔）自动检测；模拟器=0
        setContentView(buildUi());
        // ⭐⭐ 2026-09-30 修（真 bug）：原来用 `AppLog.setListener(...)`，而它的语义是
        //   **"清掉其它监听、只留这一个"**（见 AppLog 注释）⇒ MainActivity 每次 onCreate
        //   都会把**悬浮控制条**的日志订阅顶掉 ⇒ 悬浮条那一行从此不再更新（停在旧句）。
        //   实测触发路径：`am start` 重开界面、或从游戏切回 MGAS（Activity 被回收后重建）。
        //   ⇒ 改成 addListener + onDestroy 里 removeListener（多播，互不干扰）。
        logListener = line -> ui.post(() -> appendLog(line));
        AppLog.addListener(logListener);
        DeviceApi.bind(getApplicationContext());      // ⭐ Python 桥依赖 appCtx（解包/OCR/RUNS）
        // ⚠ 必须在 bind **之后**才能填特殊方块勾选（真机踩过：
        //   bind 之前调 ⇒ `PyBridge.bind 还没调用过` ⇒ 整个勾选排空 ✗）
        //   这里先试一次；Python 冷启动慢就在 tick 里继续重试 ✓
        fillSpecialRows();

        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 7);
        }
        AppLog.i("启动完成：首次用先点 ① 授权截图 / ② 无障碍设置 / ③ 悬浮窗权限（各一次），"
                + "然后点「▶ 准备启动」（=开悬浮条+切游戏+提示），再到悬浮条点 ▶ 真启动");
        AppLog.i("屏幕 " + getResources().getDisplayMetrics().widthPixels + "x"
                + getResources().getDisplayMetrics().heightPixels + "（参考系 1080x1920）");
        runIntentCmd(getIntent());
        refreshStatus();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshStatus();
        ui.removeCallbacks(tick);
        ui.postDelayed(tick, TICK_MS);        // 界面可见时才轮询（别在后台白烧电/白跑 Python）
        applyLogTab();
        announceHotUpdate();                  // ⭐ v1.45g：刚热更过就**弹窗**告诉用户
        // ⭐ v1.45g 兜底：补丁也可能**刚在后台**被激活（悬浮条服务先起了 Python
        //   ⇒ bootRecover 比 onResume 晚一点）⇒ 3 秒后再查一次，避免"擦肩而过" ✗
        ui.postDelayed(this::announceHotUpdate, 3000);
    }

    /**
     * ⭐⭐ v1.45g：**热更要让用户一眼看见**（用户 2026-10-04：「太不明显了吧，
     * 能不能弹窗口让用户更容易看出更新过」）。
     *
     * <p>补丁在冷启动时由 {@code Updater.bootRecover} 激活；那边只写日志 ⇒ 用户
     * 无从判断"到底更没更上"。这里在界面可见时弹一次**真弹窗**（补丁 id + 更新说明）。
     * <p>取值即清（{@code takeAnnounce}）⇒ 只弹一次，不会每次回前台都弹 ✗。
     */
    private void announceHotUpdate() {
        try {
            String s = Updater.takeAnnounce();
            if (s == null || s.isEmpty()) {
                return;
            }
            String[] p = s.split("\\|", 2);
            String id = p[0];
            String notes = (p.length > 1 ? p[1] : "");
            new android.app.AlertDialog.Builder(this)
                    .setTitle("✅ 已更新")
                    .setMessage("补丁 " + id + " 已生效并通过自检。"
                            + (notes.isEmpty() ? "" : "\n\n更新说明：" + notes))
                    .setPositiveButton("知道了", null)
                    .show();
            AppLog.i("[更新] 已向用户播报补丁 " + id);
        } catch (Throwable t) {
            AppLog.i("[更新] ⚠ 播报弹窗失败：" + t);
        }
    }

    @Override
    protected void onPause() {
        // ⭐⭐ 2026-10-01：切走/切游戏前把「每 X 张图升星」落盘（双保险 —— TextWatcher
        //   已经边打边存，这里只做一次规范化收尾：空/非法回落默认值 ✓）
        try {
            commitBagEvery();
        } catch (Throwable ignored) {
        }
        ui.removeCallbacks(tick);
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        // ⭐ 2026-09-30：把日志订阅还回去（配对 onCreate 的 AppLog.addListener）。
        //   漏了这步 ⇒ 每重建一次 Activity 就多一个僵尸监听，越积越多（还各自持有 View）。
        if (logListener != null) {
            AppLog.removeListener(logListener);
            logListener = null;
        }
        super.onDestroy();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        runIntentCmd(intent);
    }

    /** Activity 侧的命令入口：am start -n com.fantasy.autoexplore/.MainActivity -e cmd test_ocr */
    private void runIntentCmd(Intent it) {
        if (it == null) {
            return;
        }
        String cmd = it.getStringExtra("cmd");
        if (cmd == null || cmd.isEmpty()) {
            return;
        }
        AppLog.i("收到命令：" + cmd);
        switch (cmd) {
            case "init_ocr":
                initOcr();
                break;
            case "capture":
                ui.postDelayed(this::requestCapture, 300);
                break;
            case "test_ocr":
                ui.postDelayed(this::testOcr, 400);
                break;
            case "tap_start":
                ui.postDelayed(this::tapStart, 400);
                break;
            case "probe":
                ui.postDelayed(() -> pyCall("探针", () ->
                        PyBridge.call("probe_popup")), 400);
                break;
            case "dump":
                ui.postDelayed(this::dumpFrame, 400);
                break;
            case "pyinfo":
                ui.postDelayed(this::pyInfo, 400);
                break;
            case "selftest":
                ui.postDelayed(() -> pyCall("端上自检", () ->
                        PyBridge.call("selftest", true)), 600);
                break;
            case "overlay":
                ui.postDelayed(this::toggleOverlay, 300);
                break;
            // dev 验证钩子：adb am start -e cmd overlay_expand -e on true
            //   悬浮窗带 FLAG_NOT_FOCUSABLE，input tap 注入不进去 ⇒ 展开态只能这样触发
            case "overlay_expand":
                ui.postDelayed(() -> {
                    OverlayService.forceExpand(!"false".equals(it.getStringExtra("on")));
                }, 400);
                break;
            case "red_unlock":
                ui.postDelayed(this::pyRedUnlock, 400);
                break;
            case "summary":
                ui.postDelayed(() -> pyCall("本次统计", () -> PyBridge.call("summary")), 400);
                break;
            default:
                AppLog.i("未知命令：" + cmd);
        }
    }

    // ══════════════════════════════════════════════════════════════
    // UI · 方案 A（深空玻璃）
    // ══════════════════════════════════════════════════════════════
    //  三级信息架构：运行 / 配置 / 诊断。事实来源是
    //  docs/ui_design/scheme_a.py —— 改颜色/圆角/字号先改那边再同步这里。
    //
    //  ⚠ 本段**只换显示**：所有 onClick → 既有方法、所有 Prefs 读写、
    //    PyBridge 调用参数顺序**一个都没动**。
    //  ⚠ 门禁 verify_explore_slots_fix.py 直接读本文件文本，这些标识符必须保留：
    //    cbDailyFirst / fillSpecialRows / special_set / 「特殊方块（不勾 = 拉黑）」
    //    announceHotUpdate() / AlertDialog.Builder(this) / showUpdateResult

    /**
     * 整页外壳：标题栏 + 可换页的内容区 + 固定底栏。
     *
     * <p>⚠ 真机踩到的坑（沿用老注释）：**不能在 buildUi() 里调 Python** ——
     * {@code DeviceApi.bind()} 是在 {@code setContentView(buildUi())} **之后**才调，
     * 那时 PyBridge 还没绑 ⇒ {@code IllegalStateException: bind 还没调用过}
     * ⇒ 特殊方块勾选排会整片空白。所以这里只搭骨架，
     * 行由 {@link #fillSpecialRows()} 在 bind 之后填、并由 tick 兜底重试。
     */
    private View buildUi() {
        LinearLayout root = UiKit.column(this);
        root.setBackground(new android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{UiKit.BG_TOP, UiKit.BG_MID, UiKit.BG_BOTTOM}));
        // ⚠ 真机踩到的坑（v2.02 首装）：底栏画到 y=2607~2648，正好被**系统手势条**压住
        //   ⇒ 三个 tab 只剩一半可点，而且看着像"没画完"。
        //   根因：Activity 没有处理 window insets，内容铺到了系统栏底下。
        //   ⚠ 不能用 fitsSystemWindows（它会把背景也一起缩，渐变就断了）
        //   ⇒ 自己在根布局上补上下 padding（值从系统栏 insets 拿，见下面 applyInsets()）
        applySystemInsets(root);

        // ── 内容区（切页只换这里）──
        pageHost = UiKit.column(this);
        ScrollView sc = new ScrollView(this);
        sc.setFillViewport(true);
        sc.addView(pageHost, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));
        root.addView(sc, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        // ── 底栏 ──
        root.addView(buildNav(), new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, UiKit.dp(this, 64)));

        renderPage();
        return root;
    }

    /**
     * 给根布局补上系统栏 padding（状态栏顶 + 手势条底）。
     *
     * <p>⚠ 用 {@code OnApplyWindowInsetsListener} 而不是 {@code fitsSystemWindows} ——
     * 后者会把**背景渐变**也一起缩进去，顶部会露出一条纯色。
     * <p>⚠ 兜底：拿不到 insets（老 ROM / 分发事件被吃掉）时退回
     * {@code RefMapper} 检测到的 topInset + 48dp 手势条高度，
     * 保证最坏情况底栏也不会被手势条吃掉。
     */
    private void applySystemInsets(final View root) {
        final int fallbackTop = RefMapper.topInsetPx();
        final int fallbackBottom = UiKit.dp(this, 48);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int top = fallbackTop, bottom = fallbackBottom;
            try {
                if (Build.VERSION.SDK_INT >= 30) {
                    android.graphics.Insets bar = insets.getInsets(
                            android.view.WindowInsets.Type.systemBars()
                                    | android.view.WindowInsets.Type.displayCutout());
                    top = bar.top;
                    bottom = bar.bottom;
                } else {
                    top = insets.getSystemWindowInsetTop();
                    bottom = insets.getSystemWindowInsetBottom();
                }
            } catch (Throwable ignored) {
            }
            v.setPadding(0, top, 0, bottom);
            return insets;
        });
        // 立刻要一次（有些 ROM 不会主动分发）
        root.requestApplyInsets();
    }

    /** 底部三页导航（高 64dp；激活项青色 + 上方 20×2 指示条） */
    /**
     * 底部三页导航。
     *
     * <p>⚠⚠ 真机踩到的坑（v2.02 首装，用户原话「下面的切换栏错位了」）：
     * 在**垂直** LinearLayout 里 {@code addView(child)} 不传 LayoutParams 时，
     * 默认是 {@code (MATCH_PARENT, WRAP_CONTENT)} —— 不是 WRAP_CONTENT ✗
     * ⇒ TextView 撑满整格宽，而 TextView 自身默认 gravity 是 LEFT
     * ⇒ 文字贴在格子最左边（看着像"三个字挤在 x=0 / 1/3 / 2/3"），
     *   而指示条是显式 20dp 宽 ⇒ 被父级居中 ⇒ **一个居中一个靠左**，视觉上就是错位。
     * 修法：文字显式 {@code setGravity(CENTER)} + 显式 WRAP_CONTENT 参数（双保险）。
     */
    private View buildNav() {
        LinearLayout bar = UiKit.row(this);
        bar.setBackgroundColor(0xF2070B13);
        String[] names = {"运行", "配置", "诊断"};
        for (int i = 0; i < names.length; i++) {
            final int idx = i;
            LinearLayout cell = UiKit.column(this);
            cell.setGravity(android.view.Gravity.CENTER);
            cell.setPadding(0, UiKit.dp(this, 8), 0, UiKit.dp(this, 8));

            // 指示条（激活时可见）
            View tick = new View(this);
            tick.setBackground(UiKit.pill(this, UiKit.ACCENT, 0, 1f));
            LinearLayout.LayoutParams tlp = UiKit.lpW(UiKit.dp(this, 18), UiKit.dp(this, 2));
            tlp.bottomMargin = UiKit.dp(this, 6);
            tick.setVisibility(View.INVISIBLE);
            cell.addView(tick, tlp);

            TextView lbl = UiKit.text(this, names[i], 10, false, 0xFF68788E);
            lbl.setGravity(android.view.Gravity.CENTER);        // ⚠ 关键：否则贴左
            lbl.setIncludeFontPadding(false);
            cell.addView(lbl, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
            navTabs[i] = lbl;

            cell.setOnClickListener(v -> {
                page = idx;
                renderPage();
                refreshNav();
            });
            bar.addView(cell, UiKit.lpWeight(1f));
        }
        return bar;
    }

    private void refreshNav() {
        for (int i = 0; i < navTabs.length; i++) {
            boolean on = i == page;
            navTabs[i].setTextColor(on ? UiKit.ACCENT : 0xFF68788E);
            navTabs[i].setTypeface(on ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
            // 指示条 = 父容器的第 0 个 child
            View cell = (View) navTabs[i].getParent();
            if (cell instanceof LinearLayout) {
                View tick = ((LinearLayout) cell).getChildAt(0);
                tick.setVisibility(on ? View.VISIBLE : View.INVISIBLE);
            }
        }
    }

    /** 切页：重建 pageHost 的内容 */
    private void renderPage() {
        if (pageHost == null) {
            return;
        }
        pageHost.removeAllViews();
        if (page == 0) {
            buildRunPage(pageHost);
        } else if (page == 1) {
            buildConfigPage(pageHost);
        } else {
            buildDiagPage(pageHost);
        }
        refreshNav();
        refreshStatus();
    }

    // ── 页头：大标题 + 副标题（右侧可放状态胶囊）──
    private LinearLayout pageHeader(String title, String subtitle) {
        LinearLayout box = UiKit.column(this);
        LinearLayout r = UiKit.row(this);
        r.addView(UiKit.title(this, title), UiKit.lpWeight(1f));
        r.addView(UiKit.sub(this, subtitle));
        box.addView(r);
        return box;
    }

    // ══════════════════════════════════════════════════════════
    // 页 1 · 运行
    // ══════════════════════════════════════════════════════════
    private void buildRunPage(LinearLayout host) {
        int m = UiKit.dp(this, 16);
        host.setPadding(m, UiKit.dp(this, 14), m, UiKit.dp(this, 12));

        // 标题
        LinearLayout hd = UiKit.column(this);
        hd.addView(UiKit.title(this, "MGAS"));
        hd.addView(UiKit.sub(this, "幻想少女公会 · 自动探索"));
        host.addView(hd, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(hd, 0, 0, 0, UiKit.dp(this, 12));

        // 就绪条：三格（圆点 + 标签 + 值）
        host.addView(buildReadyBar(), UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                UiKit.dp(this, 40)));
        UiKit.margins(host.getChildAt(host.getChildCount() - 1), 0, 0, 0, UiKit.dp(this, 12));

        // 主状态卡
        LinearLayout card = UiKit.card(this, 22);
        LinearLayout top = UiKit.row(this);
        TextView big = UiKit.text(this, "就绪 · 等待启动", 22, true, UiKit.INK);
        bigStatus = big;
        LinearLayout left = UiKit.column(this);
        left.addView(UiKit.text(this, "当前状态", 10, false, UiKit.INK_4));
        left.addView(big);
        top.addView(left, UiKit.lpWeight(1f));
        ring = new UiKit.RingView(this, UiKit.ACCENT);
        ring.set(0f, "", "", false);
        top.addView(ring);
        card.addView(top);

        subStatus = UiKit.text(this, "点下面按钮后由悬浮条接管，切回游戏即自动开跑",
                10.5f, false, UiKit.INK_3);
        card.addView(subStatus, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(subStatus, 0, UiKit.dp(this, 6), 0, UiKit.dp(this, 8));

        card.addView(UiKit.hair(this));
        LinearLayout stats = UiKit.row(this);
        stats.addView(statCell("体力", "--", UiKit.ACCENT, 0), UiKit.lpWeight(1f));
        stats.addView(statCell("幸运草", "--", UiKit.OK, 1), UiKit.lpWeight(1f));
        stats.addView(statCell("金币", "--", UiKit.WARN, 2), UiKit.lpWeight(1f));
        card.addView(stats, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(stats, 0, UiKit.dp(this, 10), 0, 0);

        host.addView(card, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(card, 0, 0, 0, UiKit.dp(this, 14));

        // 主按钮（位置固定，内容随状态换）
        mainBtn = UiKit.text(this, "▶  准备启动", 17, true, 0xFF05121E);
        mainBtn.setGravity(android.view.Gravity.CENTER);
        mainBtn.setBackground(UiKit.gradientPill(this, 0xFF40E2F6, 0xFF247AE2, 28));
        mainBtn.setPadding(0, UiKit.dp(this, 16), 0, UiKit.dp(this, 16));
        mainBtn.setOnClickListener(v -> onMainBtn());
        mainBtnMode = 0;
        host.addView(mainBtn, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(mainBtn, 0, 0, 0, UiKit.dp(this, 10));

        // 次按钮：悬浮条 / 回到游戏
        LinearLayout sub = UiKit.row(this);
        overlayBtn = ghostButton("悬浮条：关", v -> toggleOverlay());
        sub.addView(overlayBtn, UiKit.lpWeight(1f));
        TextView back = ghostButton("回到游戏", v -> bringGameFront());
        LinearLayout.LayoutParams lp2 = UiKit.lpWeight(1f);
        lp2.leftMargin = UiKit.dp(this, 10);
        sub.addView(back, lp2);
        host.addView(sub, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(sub, 0, 0, 0, UiKit.dp(this, 14));

        // 日志 / 统计 卡
        host.addView(buildLogCard(), UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
    }

    private LinearLayout statCell(String label, String value, int color, int idx) {
        LinearLayout c = UiKit.column(this);
        c.addView(UiKit.text(this, label, 9.5f, false, UiKit.INK_4));
        TextView v = UiKit.text(this, value, 17, true, color);
        c.addView(v);
        if (idx == 0) {
            statStamina = v;
        } else if (idx == 1) {
            statClover = v;
        } else {
            statCoin = v;
        }
        return c;
    }

    private View buildReadyBar() {
        LinearLayout bar = UiKit.row(this);
        bar.setBackground(UiKit.pill(this, 0x17FFFFFF, 0x26FFFFFF, 13));
        bar.setPadding(UiKit.dp(this, 14), 0, UiKit.dp(this, 8), 0);

        for (int i = 0; i < 3; i++) {
            LinearLayout cell = UiKit.row(this);
            View d = UiKit.dot(this, UiKit.INK_4, 5.6f);
            cell.addView(d);
            LinearLayout col = UiKit.column(this);
            cell.addView(col);
            UiKit.margins(col, UiKit.dp(this, 8), 0, 0, 0);
            String[] labels = {"截图", "点击通道", "红装锁"};
            col.addView(UiKit.text(this, labels[i], 9, false, UiKit.INK_4));
            TextView val = UiKit.text(this, "--", 11.5f, false, UiKit.INK_2);
            col.addView(val);
            if (i == 0) {
                dotCapture = d;
                valCapture = val;
            } else if (i == 1) {
                dotTouch = d;
                valTouch = val;
            } else {
                dotLock = d;
                valLock = val;
            }
            LinearLayout.LayoutParams cp = UiKit.lpWeight(1f);
            bar.addView(cell, cp);
            if (i < 2) {
                View line = new View(this);
                line.setBackgroundColor(0x24FFFFFF);
                bar.addView(line, UiKit.lpW(Math.max(1, UiKit.dp(this, 0.7f)), UiKit.dp(this, 20)));
            }
        }
        return bar;
    }

    private LinearLayout buildLogCard() {
        LinearLayout card = UiKit.card(this, 18);
        LinearLayout head = UiKit.row(this);
        head.addView(UiKit.sectionTitle(this, "运行日志"), UiKit.lpWeight(1f));

        // 日志 / 统计 分段切换（合并了旧 logView + sumView 两块常驻面板）
        LinearLayout seg = UiKit.row(this);
        seg.setBackground(UiKit.pill(this, 0x17FFFFFF, 0x24FFFFFF, 11));
        seg.setPadding(UiKit.dp(this, 2), UiKit.dp(this, 2), UiKit.dp(this, 2), UiKit.dp(this, 2));
        tabLog = tab("日志", true);
        tabSum = tab("统计", false);
        seg.addView(tabLog, UiKit.lpW(UiKit.dp(this, 52), UiKit.dp(this, 18)));
        seg.addView(tabSum, UiKit.lpW(UiKit.dp(this, 52), UiKit.dp(this, 18)));
        head.addView(seg);
        card.addView(head);

        View line = UiKit.hair(this);
        card.addView(line);
        UiKit.margins(line, 0, UiKit.dp(this, 10), 0, UiKit.dp(this, 8));

        logView = UiKit.text(this, "", 9.5f, false, 0xFF96AAC0);
        logView.setTypeface(Typeface.MONOSPACE);
        logView.setLineSpacing(UiKit.dpf(this, 6), 1f);
        logView.setMovementMethod(new ScrollingMovementMethod());
        logView.setVerticalScrollBarEnabled(true);
        card.addView(logView, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                UiKit.dp(this, 206)));

        sumView = UiKit.text(this, "", 9.5f, false, 0xFF96AAC0);
        sumView.setTypeface(Typeface.MONOSPACE);
        sumView.setLineSpacing(UiKit.dpf(this, 6), 1f);
        sumView.setMovementMethod(new ScrollingMovementMethod());
        sumView.setVisibility(View.GONE);
        card.addView(sumView, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                UiKit.dp(this, 206)));
        return card;
    }

    private TextView tab(String label, boolean active) {
        TextView t = UiKit.text(this, label, 9.5f, active, active ? 0xFF9CEAFA : 0xFF76849A);
        t.setGravity(android.view.Gravity.CENTER);
        t.setOnClickListener(v -> {
            logTab = "日志".contentEquals(label) ? 0 : 1;
            applyLogTab();
        });
        return t;
    }

    private void applyLogTab() {
        boolean log = logTab == 0;
        if (logView != null) {
            logView.setVisibility(log ? View.VISIBLE : View.GONE);
        }
        if (sumView != null) {
            sumView.setVisibility(log ? View.GONE : View.VISIBLE);
        }
        if (tabLog != null) {
            tabLog.setTextColor(log ? 0xFF9CEAFA : 0xFF76849A);
            tabLog.setBackground(log ? UiKit.pill(this, 0x3822D3EE, 0x5A22D3EE, 9) : null);
        }
        if (tabSum != null) {
            tabSum.setTextColor(log ? 0xFF76849A : 0xFF9CEAFA);
            tabSum.setBackground(log ? null : UiKit.pill(this, 0x3822D3EE, 0x5A22D3EE, 9));
        }
    }

    private TextView ghostButton(String label, View.OnClickListener l) {
        TextView b = UiKit.text(this, label, 12.5f, false, UiKit.INK_2);
        b.setGravity(android.view.Gravity.CENTER);
        b.setBackground(UiKit.pill(this, 0x0DFFFFFF, 0x1AFFFFFF, 16));
        b.setPadding(0, UiKit.dp(this, 10), 0, UiKit.dp(this, 10));
        b.setOnClickListener(l);
        return b;
    }

    /** 主按钮点击：按当前模式分派（启动 / 停止 / 红装解锁） */
    private void onMainBtn() {
        if (mainBtnMode == 1) {
            pyExploreStop();
        } else if (mainBtnMode == 2) {
            pyRedUnlock();
        } else {
            pyExploreStart();
        }
    }

    // ══════════════════════════════════════════════════════════
    // 页 2 · 配置
    // ══════════════════════════════════════════════════════════
    private void buildConfigPage(LinearLayout host) {
        int m = UiKit.dp(this, 16);
        host.setPadding(m, UiKit.dp(this, 14), m, UiKit.dp(this, 12));
        host.addView(pageHeader("配置", "改动立刻生效"));
        UiKit.margins(host.getChildAt(host.getChildCount() - 1), 0, 0, 0, UiKit.dp(this, 14));

        // ── 卡：探索 ──
        LinearLayout c1 = UiKit.card(this, 20);
        c1.addView(UiKit.sectionTitle(this, "探索"));
        c1.addView(toggleRow("没体力自动用补给", "结实补给 ≥1 时自动吃，吃完继续刷",
                Prefs.autoSupply(this), on -> {
                    Prefs.setAutoSupply(MainActivity.this, on);
                    AppLog.i("设置：没体力自动用补给 = " + (on ? "开 ✓" : "关"));
                }));
        View h1 = UiKit.hair(this);
        c1.addView(h1);
        UiKit.margins(h1, 0, UiKit.dp(this, 10), 0, UiKit.dp(this, 10));
        c1.addView(stepperRow());
        host.addView(c1, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(c1, 0, 0, 0, UiKit.dp(this, 12));

        // ── 卡：特殊方块（卡片标题与文案必须保留，门禁直接查文本）──
        cardSp = UiKit.card(this, 20);
        LinearLayout spHead = UiKit.row(this);
        spHead.addView(UiKit.sectionTitle(this, "特殊方块（不勾 = 拉黑）"), UiKit.lpWeight(1f));
        spHead.addView(UiKit.text(this, "共 8 类", 9.5f, false, UiKit.INK_4));
        cardSp.addView(spHead);
        TextView spHint = UiKit.text(this, "拉黑类不勾 = 不点也不借道；可点类不勾 = 不专门拿",
                9.5f, false, UiKit.INK_4);
        cardSp.addView(spHint);
        UiKit.margins(spHint, 0, UiKit.dp(this, 4), 0, UiKit.dp(this, 8));

        spBody = UiKit.column(this);
        cardSp.addView(spBody);
        spLoading = UiKit.text(this, "（正在读清单…）", 10, false, UiKit.INK_4);
        spBody.addView(spLoading);
        // ⚠⚠ 真机 bug（v2.02，用户原话「特殊方块还在显示正在读清单」）：
        //   切页会**重建 spBody**，但 spFilled 还是上一轮留下的 true，
        //   而新容器里已经有 1 个子 View（就是这行 spLoading）⇒
        //   fillSpecialRows() 守卫 `spFilled && childCount > 0` 成立 ⇒ **直接 return**
        //   ⇒ 永远停在「正在读清单…」，一次都不会去调 special_list ✗
        //   ⇒ 重建容器 = 必须同时复位标记，让它重新去读一遍。
        spFilled = false;
        AppLog.i("特殊方块：配置页重建 ⇒ 复位 spFilled，准备重读清单");
        host.addView(cardSp, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(cardSp, 0, 0, 0, UiKit.dp(this, 12));

        // ── 卡：收工日常 ──
        LinearLayout c3 = UiKit.card(this, 20);
        c3.addView(UiKit.sectionTitle(this, "收工日常 · 体力刷完后自动做"));
        c3.addView(toggleRow("公会日常 · 派遣任务", "4 把椅子都派出去 + 领已完成奖励",
                Prefs.guildTasks(this), on -> {
                    Prefs.setGuildTasks(MainActivity.this, on);
                    AppLog.i("设置：公会日常·派遣 = " + (on ? "开 ✓" : "关"));
                }));
        c3.addView(toggleRow("公会日常 · 炼金", "消耗 6 件 5★ 满星装备，不可逆",
                Prefs.guildAlchemy(this), on -> {
                    Prefs.setGuildAlchemy(MainActivity.this, on);
                    AppLog.i("设置：公会日常·炼金 = " + (on ? "开 ✓" : "关"));
                }));
        c3.addView(toggleRow("公会日常 · 情报领奖", "每日逐条 + 每周最上面，纯领奖",
                Prefs.guildIntel(this), on -> {
                    Prefs.setGuildIntel(MainActivity.this, on);
                    AppLog.i("设置：公会日常·情报 = " + (on ? "开 ✓" : "关"));
                }));
        c3.addView(toggleRow("免费指定招募", "用掉当天免费机会，不花宝石",
                Prefs.recruitFree(this), on -> {
                    Prefs.setRecruitFree(MainActivity.this, on);
                    AppLog.i("设置：免费招募 = " + (on ? "开 ✓" : "关"));
                }));
        c3.addView(toggleRow("我有免广告", "自动领取 金币×3 / 四叶草×3 / 体力×3",
                Prefs.adFree(this), on -> {
                    Prefs.setAdFree(MainActivity.this, on);
                    AppLog.i("设置：免广告 = " + (on ? "开 ✓" : "关"));
                }));

        // 日常前置（琥珀强调条：它改变执行顺序）
        LinearLayout df = UiKit.row(this);
        df.setBackground(UiKit.pill(this, 0x18FBBF24, 0x54FBBF24, 12));
        df.setPadding(UiKit.dp(this, 12), UiKit.dp(this, 8), UiKit.dp(this, 12), UiKit.dp(this, 8));
        LinearLayout dl = UiKit.column(this);
        dl.addView(UiKit.text(this, "⚡ 日常前置", 11, true, 0xFFFFD98A));
        dl.addView(UiKit.text(this, "刷图之前先做完，而不是等收工", 9.5f, false, 0xFFD0B892));
        df.addView(dl, UiKit.lpWeight(1f));
        cbDailyFirst = new CheckBox(this);
        UiKit.Toggle dfT = new UiKit.Toggle(this, Prefs.dailyFirst(this), UiKit.WARN);
        dfT.setOn(Prefs.dailyFirst(this));
        dfT.onChange(() -> {
            cbDailyFirst.setChecked(dfT.isOn());
            Prefs.setDailyFirst(MainActivity.this, dfT.isOn());
            AppLog.i("设置：日常前置 = " + (dfT.isOn() ? "开 ✓（刷图前先做）" : "关（收工后做）"));
        });
        df.addView(dfT);
        // ⚠ cbDailyFirst 是**门禁要求的标识符**（v1.91 ②）：真状态机仍是它，
        //   自绘开关只是视图层，两边同步（见上面 onChange）。
        cbDailyFirst.setChecked(Prefs.dailyFirst(this));
        cbDailyFirst.setVisibility(View.GONE);
        c3.addView(df);
        UiKit.margins(df, 0, UiKit.dp(this, 12), 0, 0);

        host.addView(c3, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
    }

    /** 一行开关：标题 + 一行说明 + 右侧自绘开关 */
    private View toggleRow(String title, String desc, boolean on,
                           java.util.function.Consumer<Boolean> apply) {
        LinearLayout row = UiKit.row(this);
        row.setPadding(0, UiKit.dp(this, 9), 0, UiKit.dp(this, 9));
        LinearLayout col = UiKit.column(this);
        col.addView(UiKit.text(this, title, 13.5f, false, on ? UiKit.INK : UiKit.INK_2));
        col.addView(UiKit.text(this, desc, 9.5f, false, UiKit.INK_4));
        row.addView(col, UiKit.lpWeight(1f));
        UiKit.Toggle t = new UiKit.Toggle(this, on, UiKit.ACCENT);
        t.onChange(() -> {
            apply.accept(t.isOn());
            ((TextView) col.getChildAt(0)).setTextColor(t.isOn() ? UiKit.INK : UiKit.INK_2);
        });
        row.addView(t);
        return row;
    }

    /**
     * 「每 X 张图升星」—— **可直接填数字** + 两侧微调按钮。
     *
     * <p>⚠ 用户口径（2026-10-19）：「升级装备星级的地方要能自己填数字」——
     * 纯步进器点 100 下才能到 100，不可接受。
     *
     * <p>⚠⚠ 输入法坑（老版本踩过、这里必须保住）：
     * **不能在 TextWatcher 里 setText()** —— 那会把光标复位，打「10」变「01」。
     * ⇒ 这里 TextWatcher **只读不写**，只在「失焦 / 收回键盘 / 点别处」时做一次规范化。
     */
    private View stepperRow() {
        LinearLayout row = UiKit.row(this);
        row.addView(UiKit.text(this, "每 __ 张图升级装备星级", 13.5f, false, UiKit.INK),
                UiKit.lpWeight(1f));

        LinearLayout box = UiKit.row(this);
        box.setBackground(UiKit.pill(this, 0x17FFFFFF, 0x26FFFFFF, 15));
        int pad = UiKit.dp(this, 4);
        box.setPadding(pad, pad, pad, pad);

        TextView minus = stepBtn("−");

        // ⭐ 输入框：可点、可打字；数字键盘；居中
        EditText value = new EditText(this);
        value.setText(String.valueOf(Prefs.bagEvery(this)));
        value.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f);
        value.setTextColor(UiKit.INK);
        value.setTypeface(Typeface.DEFAULT_BOLD);
        value.setGravity(android.view.Gravity.CENTER);
        value.setInputType(InputType.TYPE_CLASS_NUMBER);
        value.setBackground(null);                 // 不要 EditText 默认下划线
        value.setPadding(0, 0, 0, 0);
        value.setIncludeFontPadding(false);
        value.setSelectAllOnFocus(true);           // 点进去全选 ⇒ 直接打字覆盖
        value.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_DONE);
        etBagEvery = value;                        // ⚠ 保持老字段名：onPause 的 commitBagEvery 还认它

        // ⚠ TextWatcher 只**存不写**（写会复位光标 ⇒ 打 10 变 01）
        value.addTextChangedListener(new android.text.TextWatcher() {
            @Override
            public void afterTextChanged(android.text.Editable s) {
                saveBagEveryQuiet(s == null ? "" : s.toString());
            }

            @Override
            public void beforeTextChanged(CharSequence s, int st, int c, int a) {
            }

            @Override
            public void onTextChanged(CharSequence s, int st, int b, int c) {
            }
        });
        // 失焦时规范化（空/非法回落默认值），这一次才允许 setText
        value.setOnFocusChangeListener((v, has) -> {
            if (!has) {
                commitBagEvery();
            }
        });

        TextView plus = stepBtn("+");
        minus.setOnClickListener(v -> bumpBagEvery(-1, value));
        plus.setOnClickListener(v -> bumpBagEvery(+1, value));

        box.addView(minus, UiKit.lpW(UiKit.dp(this, 26), UiKit.dp(this, 28)));
        box.addView(value, UiKit.lpW(UiKit.dp(this, 46), UiKit.dp(this, 28)));
        box.addView(plus, UiKit.lpW(UiKit.dp(this, 26), UiKit.dp(this, 28)));
        row.addView(box);
        return row;
    }

    private TextView stepBtn(String s) {
        TextView t = UiKit.text(this, s, 14, false, UiKit.INK_2);
        t.setGravity(android.view.Gravity.CENTER);
        t.setBackground(UiKit.pill(this, 0x0FFFFFFF, 0x1FFFFFFF, 13));
        return t;
    }

    /**
     * 步进器加减：基于**当前输入框里的值**算，而不是 Prefs 里的旧值。
     *
     * <p>⚠ 用户可能刚手打了 37 还没失焦就点 +，此时 Prefs 还是旧值 10 ——
     * 读输入框才不会把 37 吃掉。
     */
    private void bumpBagEvery(int delta, TextView value) {
        int v;
        try {
            v = Integer.parseInt(value.getText().toString().trim());
        } catch (Throwable e) {
            v = Prefs.bagEvery(this);
        }
        v += delta;
        if (v < 0) {
            v = 0;
        }
        if (v > 99) {
            v = 99;
        }
        value.setText(String.valueOf(v));          // 这里可以 setText：是按钮点的，不是打字
        Prefs.setBagEvery(this, v);
        AppLog.i("设置：每 " + v + " 张图升级装备星级" + (v == 0 ? "（= 关闭）" : ""));
    }
    // ══════════════════════════════════════════════════════════
    // 页 3 · 诊断
    // ══════════════════════════════════════════════════════════
    private void buildDiagPage(LinearLayout host) {
        int m = UiKit.dp(this, 16);
        host.setPadding(m, UiKit.dp(this, 14), m, UiKit.dp(this, 12));

        LinearLayout hd = UiKit.row(this);
        hd.addView(UiKit.title(this, "诊断"));
        // 状态胶囊
        statusView = UiKit.text(this, "检查中", 9.5f, false, UiKit.OK);
        statusView.setGravity(android.view.Gravity.CENTER);
        statusView.setPadding(UiKit.dp(this, 12), UiKit.dp(this, 6),
                UiKit.dp(this, 12), UiKit.dp(this, 6));
        hd.addView(statusView);
        host.addView(hd);
        host.addView(UiKit.sub(this, "授权 / 更新 / 调试 都在这一页"));

        // ── 授权三件 ──
        LinearLayout p1 = UiKit.card(this, 20);
        p1.addView(UiKit.sectionTitle(this, "首次设置（各点一次）"));
        p1.addView(permRow(0, "① 授权截图", "MediaProjection，装机会掉", v -> requestCapture()));
        p1.addView(permRow(1, "② 无障碍设置", "点击通道，常驻", v -> openAccessibility()));
        p1.addView(permRow(2, "③ 悬浮窗权限", "悬浮条显示用", v -> openOverlayPerm()));
        host.addView(p1, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(p1, 0, UiKit.dp(this, 12), 0, UiKit.dp(this, 12));

        // ── 更新 ──
        LinearLayout p2 = UiKit.card(this, 20);
        p2.addView(UiKit.sectionTitle(this, "更新"));
        LinearLayout up = UiKit.row(this);
        LinearLayout ul = UiKit.column(this);
        ul.addView(UiKit.text(this, "检查补丁与整包", 13, true, UiKit.INK));
        ul.addView(UiKit.text(this, "补丁重启即生效；整包走系统安装器", 9.5f, false, UiKit.INK_4));
        up.addView(ul, UiKit.lpWeight(1f));
        TextView chk = UiKit.text(this, "检查更新", 10.5f, false, 0xFF9CEAFA);
        chk.setGravity(android.view.Gravity.CENTER);
        chk.setBackground(UiKit.pill(this, 0x1C22D3EE, 0x6022D3EE, 14));
        chk.setPadding(UiKit.dp(this, 14), UiKit.dp(this, 8),
                UiKit.dp(this, 14), UiKit.dp(this, 8));
        chk.setOnClickListener(v -> doUpdate("auto"));
        up.addView(chk);
        UiKit.margins(up, 0, UiKit.dp(this, 8), 0, 0);
        p2.addView(up);
        host.addView(p2, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(p2, 0, 0, 0, UiKit.dp(this, 12));

        // ── 调试（默认折叠）──
        LinearLayout p3 = UiKit.card(this, 20);
        LinearLayout dbgHead = UiKit.row(this);
        dbgHead.addView(UiKit.sectionTitle(this, "调试"), UiKit.lpWeight(1f));
        dbgHead.addView(UiKit.text(this, "默认隐藏", 9.5f, false, UiKit.INK_4));
        p3.addView(dbgHead);

        CheckBox cbDebug = new CheckBox(this);
        cbDebug.setText("显示调试按钮（排查用）");
        cbDebug.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        cbDebug.setTextColor(UiKit.INK_2);
        cbDebug.setChecked(Prefs.showDebug(this));
        p3.addView(cbDebug);

        LinearLayout debugBox = UiKit.column(this);
        debugBox.setVisibility(Prefs.showDebug(this) ? View.VISIBLE : View.GONE);
        cbDebug.setOnCheckedChangeListener((v, on) -> {
            Prefs.setShowDebug(this, on);
            debugBox.setVisibility(on ? View.VISIBLE : View.GONE);
        });

        LinearLayout g1 = UiKit.row(this);
        g1.addView(dbBtn("初始化 OCR", "载 det+rec", v -> initOcr()), UiKit.lpWeight(1f));
        LinearLayout.LayoutParams gp = UiKit.lpWeight(1f);
        gp.leftMargin = UiKit.dp(this, 10);
        g1.addView(dbBtn("测识别 + dump", "存帧落盘", v -> testOcr()), gp);
        debugBox.addView(g1);

        LinearLayout g2 = UiKit.row(this);
        g2.addView(dbBtn("点开始冒险", "盲点一次", v -> tapStart()), UiKit.lpWeight(1f));
        LinearLayout.LayoutParams gp2 = UiKit.lpWeight(1f);
        gp2.leftMargin = UiKit.dp(this, 10);
        g2.addView(dbBtn("导出截图", "files/dump", v -> dumpFrame()), gp2);
        UiKit.margins(g2, 0, UiKit.dp(this, 8), 0, 0);
        debugBox.addView(g2);

        LinearLayout g3 = UiKit.row(this);
        g3.addView(dbBtn("环境快照", "版本/模型", v -> pyInfo()), UiKit.lpWeight(1f));
        LinearLayout.LayoutParams gp3 = UiKit.lpWeight(1f);
        gp3.leftMargin = UiKit.dp(this, 10);
        g3.addView(dbBtn("端上自检", "PyBridge 通", v -> pySelftest()), gp3);
        UiKit.margins(g3, 0, UiKit.dp(this, 8), 0, 0);
        debugBox.addView(g3);

        LinearLayout g4 = UiKit.row(this);
        g4.addView(dbBtn("清空日志", "清屏", v -> {
            AppLog.clear();
            if (logView != null) {
                logView.setText("");
            }
        }), UiKit.lpWeight(1f));
        LinearLayout.LayoutParams gp4 = UiKit.lpWeight(1f);
        gp4.leftMargin = UiKit.dp(this, 10);
        g4.addView(dbBtn("天赋果实记录", "只看不跑", v -> pyFruitReport()), gp4);
        UiKit.margins(g4, 0, UiKit.dp(this, 8), 0, 0);
        debugBox.addView(g4);

        p3.addView(debugBox);
        host.addView(p3, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
        UiKit.margins(p3, 0, 0, 0, UiKit.dp(this, 12));

        // ── 一键反馈 ──
        LinearLayout fb = UiKit.row(this);
        fb.setBackground(UiKit.pill(this, 0x16FBBF24, 0x4CFBBF24, 13));
        fb.setPadding(UiKit.dp(this, 14), UiKit.dp(this, 10),
                UiKit.dp(this, 14), UiKit.dp(this, 10));
        LinearLayout fl = UiKit.column(this);
        fl.addView(UiKit.text(this, "一键反馈", 12, false, 0xFFFFD98A));
        fl.addView(UiKit.text(this, "打包日志 + 机型 + 现场帧，走系统分享", 8.5f, false, 0xFFC8B08C));
        fb.addView(fl, UiKit.lpWeight(1f));
        TextView share = UiKit.text(this, "打包并分享 ›", 10, false, 0xFFFFD98A);
        share.setOnClickListener(v -> {
            AppLog.i("点「一键反馈」⇒ 打包日志 + 机型信息 + 现场帧");
            final Context c = getApplicationContext();
            new Thread(() -> {
                try {
                    Feedback.collectAndShare(c);
                } catch (Throwable t) {
                    AppLog.i("[反馈] 异常：" + t);
                }
            }, "fb").start();
        });
        fb.addView(share);
        host.addView(fb, UiKit.lpW(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
    }

    /**
     * 授权项一行：状态点 + 标题/说明 + 右侧「已就绪 / 去设置」。
     *
     * <p>⚠ 用户口径（2026-10-19）：「单项设置完成要立即显示已就绪，现在看不出缺哪个」——
     * 旧版这一行**只有静态的「去设置 ›」**，做完回来也还是那句，
     * 用户必须回到「运行」页看三格条才知道生效没 ⇒ 就地显示状态。
     *
     * <p>@param kind 0=截图 1=无障碍 2=悬浮窗；由 {@link #refreshPermissions()} 按它取真值
     */
    private View permRow(int kind, String title, String desc, View.OnClickListener l) {
        LinearLayout row = UiKit.row(this);
        row.setBackground(UiKit.pill(this, 0x0DFFFFFF, 0x1AFFFFFF, 13));
        row.setPadding(UiKit.dp(this, 12), UiKit.dp(this, 9),
                UiKit.dp(this, 12), UiKit.dp(this, 9));

        View dot = new View(this);
        dot.setBackground(dotBg(UiKit.INK_4));
        LinearLayout.LayoutParams dlp = UiKit.lpW(UiKit.dp(this, 6), UiKit.dp(this, 6));
        dlp.rightMargin = UiKit.dp(this, 9);
        row.addView(dot, dlp);

        LinearLayout col = UiKit.column(this);
        col.addView(UiKit.text(this, title, 12.5f, false, UiKit.INK));
        col.addView(UiKit.text(this, desc, 9, false, UiKit.INK_4));
        row.addView(col, UiKit.lpWeight(1f));

        TextView go = UiKit.text(this, "去设置 ›", 10, false, UiKit.ACCENT);
        row.addView(go);
        row.setOnClickListener(l);
        UiKit.margins(row, 0, UiKit.dp(this, 6), 0, 0);

        permDots[kind] = dot;
        permLabels[kind] = go;
        return row;
    }

    /** 授权三项的状态点 / 状态文字（key = 0 截图 1 无障碍 2 悬浮窗） */
    private final View[] permDots = new View[3];
    private final TextView[] permLabels = new TextView[3];

    /**
     * 刷新「首次设置」三项的就地状态。
     *
     * <p>⚠ tick 每 2 秒调一次（见 onCreate 的 tick），所以**用户从系统设置页返回后
     * 最多 2 秒就能看到变成「已就绪」** —— 不用回运行页看三格条。
     */
    private void refreshPermissions() {
        boolean[] ok = new boolean[]{
                FrameStore.has(),
                AutoTouchService.ready(),
                Settings.canDrawOverlays(this),
        };
        String[] okText = {"已就绪", "已就绪", "已就绪"};
        String[] noText = {"去设置 ›", "去设置 ›", "去设置 ›"};
        for (int i = 0; i < permDots.length; i++) {
            if (permDots[i] == null || permLabels[i] == null) {
                continue;
            }
            permDots[i].setBackground(dotBg(ok[i] ? UiKit.OK : UiKit.INK_4));
            permLabels[i].setText(ok[i] ? okText[i] : noText[i]);
            permLabels[i].setTextColor(ok[i] ? UiKit.OK : UiKit.ACCENT);
        }
    }

    private View dbBtn(String title, String desc, View.OnClickListener l) {
        LinearLayout b = UiKit.column(this);
        b.setBackground(UiKit.pill(this, 0x0DFFFFFF, 0x1AFFFFFF, 12));
        b.setPadding(UiKit.dp(this, 12), UiKit.dp(this, 8),
                UiKit.dp(this, 12), UiKit.dp(this, 8));
        b.addView(UiKit.text(this, title, 11.5f, false, UiKit.INK_2));
        b.addView(UiKit.text(this, desc, 8.5f, false, UiKit.INK_4));
        b.setOnClickListener(l);
        return b;
    }

    /**
     * 特殊方块勾选排（胶囊 chip 版）。语义与老版完全一致。
     *
     * <p>⚠⚠ 真机踩到的坑（沿用老注释）：不能在 buildUi() 里调它 ——
     * DeviceApi.bind() 在 setContentView() 之后才调，那时 PyBridge 还没绑，
     * 会抛 IllegalStateException: bind 还没调用过 ⇒ 卡片在、里面只有一行「读不到清单」。
     * 所以本方法幂等 + 可重试：bind 之后调一次，没成功就让 tick 每轮再试。
     */
    private void fillSpecialRows() {
        if (spBody == null) {
            return;
        }
        // ⚠ 守卫判据：**容器里只有那行「正在读清单…」⇒ 视为没填过**。
        //   旧写法只看 `childCount > 0`，而加载提示本身就是 1 个子 View
        //   ⇒ 永远判定"已填好"⇒ 一次都不重试（真机 v2.02 的 bug）
        boolean onlyLoading = spBody.getChildCount() <= 1
                && spBody.getChildAt(0) == spLoading;
        if (spFilled && !onlyLoading && spBody.getChildCount() > 0) {
            return;
        }
        if (spFilled && onlyLoading) {
            AppLog.i("特殊方块：容器里只剩加载提示 ⇒ 当作没填，重试一次");
            spFilled = false;
        } else if (spFilled && spBody.getChildCount() == 0) {
            AppLog.i("特殊方块：spBody 被清空过 ⇒ 重填一次");
            spFilled = false;
        }
        String js = null;
        try {
            js = PyBridge.call("special_list");
        } catch (Throwable e) {
            AppLog.i("特殊方块：调用 special_list 异常 ⇒ " + e);
        }
        org.json.JSONArray arr = null;
        try {
            org.json.JSONObject o = new org.json.JSONObject(
                    (js == null || js.isEmpty()) ? "{}" : js);
            arr = o.optJSONArray("items");
        } catch (Throwable e) {
            AppLog.i("特殊方块：解析列表失败 " + e
                    + " ｜ 原文前120字=" + (js == null ? "null"
                    : js.substring(0, Math.min(120, js.length()))));
        }
        if (arr == null || arr.length() == 0) {
            final String why = (js == null) ? "PyBridge 还没就绪"
                    : (js.isEmpty() ? "Python 返回空串"
                       : (arr == null ? "JSON 里没有 items 数组" : "items 是空数组"));
            if (spLoading != null) {
                spLoading.setText("（正在读清单…若一直这样，看日志）");
            }
            if (js != null && !js.isEmpty() && !spLoggedFail) {
                spLoggedFail = true;
                AppLog.i("特殊方块：清单为空 ⇒ " + why + " ｜ 原文前120字="
                        + js.substring(0, Math.min(120, js.length())));
            }
            return;
        }
        spBody.removeAllViews();
        spLoading = null;          // 提示行已被移除，别再拿它做判据
        spFilled = true;
        try {
            int nLocked = 0;
            for (int i = 0; i < arr.length(); i++) {
                org.json.JSONObject o = arr.optJSONObject(i);
                if (o != null && o.optBoolean("locked", true)) {
                    nLocked++;
                }
            }
            AppLog.i("特殊方块：勾选排已填 " + arr.length() + " 个（锁定 " + nLocked + " 个）");
        } catch (Throwable ignored) {
        }

        // ── 排版：**按实测宽度换行**，不再"每行硬塞 3 个" ──
        //   ⚠ 真机踩到的坑（v2.02 首装，用户原话「特殊方块排版有问题」）：
        //     旧写法是 `used = (used+1) % 3` —— 每行固定 3 个，但 chip 宽度随名字长短变化
        //     ⇒ 长名字（如「机巧宝箱怪」）被挤成**两行文字**，比邻居高一倍，整排歪掉 ✗
        //   ⇒ 改成：用量宽函数先算每颗 chip 的宽度，累加超过容器宽就换行。
        //     容器宽 = 卡片内容宽（屏宽 - 两侧 16 外边距 - 卡片左右 20 内边距）。
        int avail = getResources().getDisplayMetrics().widthPixels
                - UiKit.dp(this, 16 * 2)      // 页面左右外边距
                - UiKit.dp(this, 20 * 2)      // 卡片左右内边距
                - UiKit.dp(this, 4);          // 余量，防浮点误差把最后一颗挤下去
        final int gap = UiKit.dp(this, 8);

        // 先按「拉黑类 / 可点类」分组 —— 两类的"不勾"语义不同，混排会让人误读
        java.util.List<org.json.JSONObject> blocks = new java.util.ArrayList<>();
        java.util.List<org.json.JSONObject> picks = new java.util.ArrayList<>();
        for (int i = 0; i < arr.length(); i++) {
            org.json.JSONObject it = arr.optJSONObject(i);
            if (it == null) {
                continue;
            }
            if (it.optBoolean("block_class", true)) {
                blocks.add(it);
            } else {
                picks.add(it);
            }
        }

        if (!blocks.isEmpty()) {
            TextView cap = UiKit.text(this, "拉黑类（不勾 = 不点，也不借道）", 9.5f, false, UiKit.INK_4);
            spBody.addView(cap, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
            LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT);
            clp.topMargin = UiKit.dp(this, 8);
            cap.setLayoutParams(clp);
            chipFlow(blocks, avail, gap);
        }
        if (!picks.isEmpty()) {
            TextView cap = UiKit.text(this, "可点类（不勾 = 不专门拿，挡路仍会点）", 9.5f, false, UiKit.INK_4);
            LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT);
            clp.topMargin = UiKit.dp(this, 12);
            spBody.addView(cap, clp);
            chipFlow(picks, avail, gap);
        }
    }

    /**
     * 把一组特殊方块画成**按宽度流式换行**的 chip。
     *
     * <p>⚠ 宽度必须实测：中文字宽不均（「旅行商人」4 字 vs 「机巧宝箱怪」5 字），
     * 固定每行 N 个一定会把长的挤换行 —— 那就是真机上看到的"排版有问题"。
     */
    private void chipFlow(java.util.List<org.json.JSONObject> items, int avail, int gap) {
        LinearLayout row = null;
        int usedW = 0;
        for (org.json.JSONObject it : items) {
            final String nm = it.optString("name", "");
            final boolean on = it.optBoolean("on", false);
            final boolean locked = it.optBoolean("locked", true);
            final boolean blockClass = it.optBoolean("block_class", true);

            TextView ch = UiKit.text(this,
                    nm + (locked ? "" : (on ? "  ✓" : "  ○")),
                    11.5f, false,
                    locked ? 0xFF6E7C90 : (on ? 0xFF9CEAFA : 0xFF78849A));
            ch.setGravity(android.view.Gravity.CENTER);
            ch.setSingleLine(true);                    // ⚠ 关键：不许换行（换行就歪）
            ch.setBackground(locked
                    ? UiKit.pill(this, 0x08FFFFFF, 0x14FFFFFF, 15)
                    : (on ? UiKit.pill(this, 0x1E22D3EE, 0x6E22D3EE, 15)
                          : UiKit.pill(this, 0x0FFFFFFF, 0x24FFFFFF, 15)));
            ch.setPadding(UiKit.dp(this, 14), UiKit.dp(this, 7),
                    UiKit.dp(this, 14), UiKit.dp(this, 7));
            ch.setTag(it);
            ch.setContentDescription(locked ? nm + "（锁定）"
                    : (blockClass ? nm + "〔不勾=拉黑〕" : nm + "〔不勾=不专门拿〕"));
            if (!locked) {
                ch.setOnClickListener(v -> toggleSpecial(v));
            }

            // 量宽：文字宽 + 左右 padding（含 ✓/○ 标记）
            android.graphics.Paint pt = ch.getPaint();
            int textW = (int) Math.ceil(pt.measureText(ch.getText().toString()));
            int chipW = textW + UiKit.dp(this, 28);

            if (row == null || (usedW > 0 && usedW + gap + chipW > avail)) {
                row = UiKit.row(this);
                LinearLayout.LayoutParams rlp = new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT);
                rlp.topMargin = UiKit.dp(this, 8);
                spBody.addView(row, rlp);
                usedW = 0;
            }
            LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT);
            if (usedW > 0) {
                cp.leftMargin = gap;
            }
            row.addView(ch, cp);
            usedW += (usedW > 0 ? gap : 0) + chipW;
        }
    }

    /** 点一颗特殊方块：立刻落盘 + 就地改观感（不重建，避免滚动位置乱跳） */
    private void toggleSpecial(android.view.View v) {
        org.json.JSONObject o2 = (org.json.JSONObject) v.getTag();
        String name2 = o2.optString("name", "");
        boolean locked = o2.optBoolean("locked", true);
        if (locked) {
            AppLog.i("特殊方块「" + name2 + "」是锁定项（暂不可勾选）");
            return;
        }
        boolean nowOn = !o2.optBoolean("on", false);
        boolean blk = o2.optBoolean("block_class", true);
        String r = PyBridge.call("special_set", name2, nowOn);
        try {
            o2.put("on", nowOn);
        } catch (Throwable ignored) {
        }
        TextView tv = (TextView) v;
        tv.setText(name2 + (nowOn ? "  ✓" : "  ○"));
        tv.setTextColor(nowOn ? 0xFF9CEAFA : 0xFF78849A);
        tv.setBackground(nowOn
                ? UiKit.pill(this, 0x1E22D3EE, 0x6E22D3EE, 15)
                : UiKit.pill(this, 0x0FFFFFFF, 0x24FFFFFF, 15));
        AppLog.i("特殊方块「" + name2 + "」⇒ "
                + (nowOn ? "勾选·主动处理"
                         : (blk ? "取消·拉黑（不点、不借道）"
                                : "取消·不专门拿（挡路仍会点）"))
                + "（" + r + "）");
    }

    /**
     * 刷新状态：运行页就绪条 + 大字区 + 主按钮，诊断页状态胶囊。
     *
     * <p>每个控件都判空 —— 它们只在自己那一页被创建（切页会重建），
     * 而 tick 每 2 秒无条件调用本方法，不判空就是 NPE。
     */
    private void refreshStatus() {
        boolean cap = FrameStore.has();
        boolean touch = AutoTouchService.ready();
        boolean locked = "有（先解锁）".equals(redLockText);
        boolean ready = cap && touch && !locked;

        if (dotCapture != null) {
            setDot(dotCapture, cap);
            valCapture.setText(cap ? "就绪" : "未授权");
        }
        if (dotTouch != null) {
            setDot(dotTouch, touch);
            valTouch.setText(touch ? "就绪" : "未开启");
        }
        if (dotLock != null) {
            dotLock.setBackground(dotBg(locked ? UiKit.WARN : UiKit.OK));
            valLock.setText(locked ? "有" : "无");
        }

        if (mainBtn != null) {
            if (locked) {
                setMainBtn(2, "⑭ 红装解锁（点这里才能重新开跑）",
                        UiKit.gradientPill(this, 0xFF7A5410, 0xFF563A0C, 28),
                        0xFFFFD98A);
            } else if (running) {
                setMainBtn(1, "■  停止探索",
                        UiKit.gradientPill(this, 0xFF9C2E3A, 0xFF6C1C28, 28),
                        0xFFFFE8E8);
            } else {
                setMainBtn(0, "▶  准备启动",
                        UiKit.gradientPill(this, 0xFF40E2F6, 0xFF247AE2, 28),
                        0xFF05121E);
            }
        }

        if (bigStatus != null) {
            if (locked) {
                bigStatus.setText("发现红装");
                bigStatus.setTextColor(UiKit.INK);
                subStatus.setText("解锁后才能重新开跑；解锁键在下面橙色条");
                ring.setColor(UiKit.WARN);
                ring.set(0f, "", "", true);
            } else if (running) {
                bigStatus.setText("正在跑图");
                subStatus.setText("计划执行中 · 进度看悬浮条或下面日志");
                ring.setColor(UiKit.ACCENT);
            } else if (ready) {
                bigStatus.setText("就绪 · 等待启动");
                subStatus.setText("点下面按钮后由悬浮条接管，切回游戏即自动开跑");
                ring.setColor(UiKit.ACCENT);
                ring.set(0f, "", "", false);
            } else {
                bigStatus.setText("还不能开跑");
                subStatus.setText(!cap ? "缺「① 授权截图」"
                        : (!touch ? "缺「② 无障碍设置」" : "先处理红装锁"));
                ring.setColor(UiKit.WARN);
                ring.set(0f, "", "", false);
            }
        }

        refreshPermissions();
        if (statusView != null) {
            statusView.setText(ready ? "全部就绪" : "有未完成项");
            statusView.setTextColor(ready ? UiKit.OK : UiKit.WARN);
            statusView.setBackground(UiKit.pill(this,
                    ready ? 0x1A34D399 : 0x1AFBBF24,
                    ready ? 0x8034D399 : 0x80FBBF24, 11));
        }
    }

    /**
     * 把 hud() 的三格读数刷到运行页。
     *
     * <p>⚠ 取不到时显示 "—" 而**不是 0**：0 会让用户以为"体力真的空了"，
     * 这正是本项目反复踩的「判据静默失效」那一族的反面 —— 读不到就要看得出来。
     */
    private void applyHud(String json) {
        if (json == null || json.isEmpty() || "{}".equals(json)) {
            return;
        }
        try {
            org.json.JSONObject o = new org.json.JSONObject(json);
            if (statStamina != null) {
                statStamina.setText(fmt(o.optInt("stamina", -1)));
            }
            if (statClover != null) {
                statClover.setText(fmt(o.optInt("clover", -1)));
            }
            if (statCoin != null) {
                int coin = o.optInt("coin", -1);
                statCoin.setText(coin < 0 ? "—" : String.format(Locale.US, "%,d", coin));
            }
        } catch (Throwable ignored) {
        }
    }

    private String fmt(int v) {
        return v < 0 ? "—" : String.valueOf(v);
    }

    private void setMainBtn(int mode, String label, GradientDrawable bg, int fg) {
        mainBtnMode = mode;
        mainBtn.setText(label);
        mainBtn.setTextColor(fg);
        mainBtn.setBackground(bg);
    }

    private void setDot(View v, boolean ok) {
        v.setBackground(dotBg(ok ? UiKit.OK : UiKit.WARN));
    }

    private GradientDrawable dotBg(int color) {
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setColor(color);
        return g;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void appendLog(String line) {
        if (logView == null) {
            return;              // 当前不在运行页 ⇒ 日志仍在 AppLog 里，切回来会重放
        }
        logView.append(line + "\n");
        scrollToEnd(logView);
    }

    /** 把「本次统计」面板内容换成 PC 那份 `summary_text()`（变了才重设，别每 2 秒闪一次） */
    private void showSummary(String txt) {
        if (txt == null) {
            txt = "";
        }
        if (txt.equals(lastSummary)) {
            return;
        }
        lastSummary = txt;
        if (sumView == null) {
            return;
        }
        sumView.setText(txt.isEmpty() ? "（还没跑过；跑完一张图后这里会出现 PC 同款统计）" : txt);
        // ⚠ 统计面板**停在顶部**（要看到 `════════ 本次统计 ════════` 那一行）；
        //   只有日志区是"跟着尾巴走"（showSummary 里别调 scrollToEnd ✗ 实测会只看到最后两行）
        sumView.scrollTo(0, 0);
    }

    private void scrollToEnd(TextView v) {
        if (v.getLayout() != null) {
            int scroll = v.getLayout().getLineTop(v.getLineCount()) - v.getHeight();
            if (scroll > 0) {
                v.scrollTo(0, scroll);
            }
        }
    }

    private void commitBagEvery() {
        if (etBagEvery == null) {
            return;
        }
        int v;
        try {
            v = Integer.parseInt(etBagEvery.getText().toString().trim());
        } catch (Throwable t) {
            v = Prefs.BAG_EVERY_DEFAULT;
        }
        if (v < 0) {
            v = 0;
        }
        Prefs.setBagEvery(this, v);
        etBagEvery.setText(String.valueOf(v));
        AppLog.i("设置：每 " + v + " 张图升级装备星级" + (v == 0 ? "（= 关闭）" : ""));
    }

    /**
     * ⭐⭐ 2026-10-01：「每 X 张图升星」**边打边存**（TextWatcher 用）
     *
     * 为什么不能直接调 `commitBagEvery()`：它会 `setText()` ⇒ 光标复位 ⇒ 打「10」
     * 会变成「01」（老注释踩过这个坑，于是改成"只在失去焦点时提交"——而那个时机的
     * 触发条件在真机上根本不成立，见字段创建处的长注释）。
     * 这里**只写 Prefs、不碰文本**：空串（正在删改）跳过，打全了自然就存对了 ✓
     */
    private void saveBagEveryQuiet(String txt) {
        String t = (txt == null ? "" : txt.trim());
        if (t.isEmpty()) {
            return;                       // 正在删/改 ⇒ 保留旧值，别写成 0 ✗
        }
        int v;
        try {
            v = Integer.parseInt(t);
        } catch (Throwable e) {
            return;
        }
        if (v < 0 || v == Prefs.bagEvery(this)) {
            return;
        }
        Prefs.setBagEvery(this, v);
        AppLog.i("设置：每 " + v + " 张图升级装备星级" + (v == 0 ? "（= 关闭）" : ""));
    }

    // ---------------- 动作 ----------------

    private void requestCapture() {
        MediaProjectionManager mpm =
                (MediaProjectionManager) getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        startActivityForResult(mpm.createScreenCaptureIntent(), REQ_CAPTURE);
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        // ⭐ v2.10 诊断：把回调的真实参数打出来。
        //   之前"授权了但没帧"，就是因为不知道这个回调到底有没有被调用、res 是什么。
        AppLog.i("[截图授权] onActivityResult req=" + req + " res=" + res
                + " data=" + (data == null ? "null" : "有"));
        if (req == REQ_CAPTURE && res != RESULT_OK) {
            AppLog.i("[截图授权] 用户取消或系统拒绝（res=" + res + "）⇒ 没有截图通道");
        }
        if (req == REQ_CAPTURE && res == RESULT_OK && data == null) {
            AppLog.i("[截图授权] ⚠ RESULT_OK 但 data 为 null ⇒ 系统没给 projection 令牌");
        }
        if (req == REQ_CAPTURE && res == RESULT_OK && data != null) {
            Intent i = new Intent(this, CaptureService.class);
            i.putExtra(CaptureService.EXTRA_CODE, res);
            i.putExtra(CaptureService.EXTRA_DATA, data);
            try {
                if (Build.VERSION.SDK_INT >= 26) {
                    startForegroundService(i);
                } else {
                    startService(i);
                }
                AppLog.i("[截图授权] 已启动 CaptureService ✓");
            } catch (Throwable t) {
                AppLog.i("[截图授权] ⚠ 启动 CaptureService 失败：" + t);
            }
            ui.postDelayed(this::refreshStatus, 1500);
        }
    }

    private void openAccessibility() {
        startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
    }

    private void openOverlayPerm() {
        startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:" + getPackageName())));
    }

    /**
     * 悬浮条开关。没权限先去授权页；开了之后会常驻一个小气泡（参考系左下角）。
     *
     * ⚠ 悬浮条上的按钮**只能放符号/ASCII**：它会盖在游戏画面上、并被截图一起 OCR，
     *   出现「探索/关闭/领取」这类中文会被误判成游戏面板（详见 OverlayService 类注释）。
     */
    private void toggleOverlay() {
        if (!Settings.canDrawOverlays(this)) {
            AppLog.i("还没「显示在其他应用上层」权限 ⇒ 先给一下再回来点");
            openOverlayPerm();
            return;
        }
        overlayOn = !overlayOn;
        if (overlayOn) {
            OverlayService.start(this);
            AppLog.i("已开启悬浮控制条：左下角「● MGAS」小气泡 → 点它展开 → ▶ 开始 / ■ 停止（可拖动）");
        } else {
            OverlayService.stop(this);
            AppLog.i("已关闭悬浮控制条");
        }
        if (overlayBtn != null) {
            overlayBtn.setText(overlayOn ? "悬浮条：开" : "悬浮条：关");
        }
    }

    private void initOcr() {
        new Thread(() -> {
            AutoPilot.ensureOcr(this);
            ui.post(this::refreshStatus);
        }, "ocr-init").start();
    }

    private void testOcr() {
        new Thread(() -> {
            List<OcrItem> items = AutoPilot.scan(this, 0.5f, true);
            int n = Math.min(items.size(), 25);
            for (int i = 0; i < n; i++) {
                AppLog.i("   " + items.get(i));
            }
            ui.post(this::refreshStatus);
        }, "ocr-test").start();
    }

    private void tapStart() {
        new Thread(() -> {
            Bitmap before = FrameStore.get();
            List<OcrItem> items = AutoPilot.scan(this, 0.5f, false);
            OcrItem hit = AutoPilot.find(items, "开始冒险", "进入地图");
            if (hit == null) {
                AppLog.i("没找到「开始冒险/进入地图」（本帧 " + items.size() + " 条）");
                return;
            }
            AutoPilot.tapItem(hit);
            try {
                Thread.sleep(1300);
            } catch (InterruptedException ignored) {
            }
            Bitmap ref = AutoPilot.grabRef();
            if (ref != null) {
                AutoPilot.savePng(this, ref, "after_tap.png");
                AppLog.i("已存 after_tap.png（可对比确认是否真点到）" + (before != null ? "" : ""));
            }
        }, "tap-test").start();
    }

    private void dumpFrame() {
        Bitmap f = FrameStore.get();
        if (f == null) {
            AppLog.i("⚠ 没有帧");
            return;
        }
        File dir = new File("/sdcard/Download/autoexplore");
        dir.mkdirs();
        File out = new File(dir, "frame_" + System.currentTimeMillis() + ".png");
        try (FileOutputStream fos = new FileOutputStream(out)) {
            f.compress(Bitmap.CompressFormat.PNG, 100, fos);
            AppLog.i("已导出：" + out.getAbsolutePath());
        } catch (Throwable t) {
            AppLog.i("⚠ 导出失败：" + t);
        }
    }

    // ---------------- Python 层（Chaquopy） ----------------

    /** 通用：起后台线程跑 Python，结果写日志 */
    private void pyCall(String label, java.util.concurrent.Callable<String> job) {
        new Thread(() -> {
            try {
                PyBridge.ensureStarted(getApplicationContext());
                String r = job.call();
                AppLog.i("[" + label + "] " + r);
            } catch (Throwable t) {
                AppLog.i("[" + label + "] ⚠ " + t);
            }
            ui.post(() -> {
                refreshStatus();
                // ⭐ v1.45g：热更补丁是在 `ensureStarted → bootRecover` 里激活的
                //   ⇒ **弹窗必须在这里也查一次**，否则会错过时机：
                //   进界面时补丁还没激活（onResume 查了个空），
                //   点了「准备启动/自检」才激活 —— 那时若不查，就再也没人查了 ✗
                announceHotUpdate();
            });
        }, "py-" + label).start();
    }

    private void pyInfo() {
        pyCall("pyinfo", () -> PyBridge.call("info"));
    }

    private void pySelftest() {
        pyCall("端上自检", () -> PyBridge.call("selftest", true));
    }

    /**
     * ⭐ v1.41 热更新入口（悬浮条 / 广播 / 这里**同一条代码路径** ⇒ 我 adb 测的就是朋友跑的那条）。
     *
     * @param mode {@code auto} = 补丁优先、没补丁就下整包并弹安装 ／ {@code check} = 只查不动
     * ⚠ 必须后台线程：整包 70MB 下载几十秒，主线程会 ANR ✗
     */
    private void doUpdate(String mode) {
        new Thread(() -> {
            final String r;
            try {
                r = Updater.run(getApplicationContext(), mode);
            } catch (Throwable t) {
                AppLog.i("[更新] ⚠ " + t);
                final String e = "更新异常：" + t;
                ui.post(() -> showUpdateResult(e));
                return;
            }
            AppLog.i("[更新] " + r);
            ui.post(() -> {
                refreshStatus();
                showUpdateResult(r);
            });
        }, "ui-update").start();
    }

    /**
     * ⭐⭐ v1.45g：把更新结果**弹出来**（以前只写日志 ⇒ 用户以为"点了没反应" ✗）。
     *
     * <p>用户 2026-10-04 口径：点了「检查更新」要能立刻看出**发生了什么**
     * （已是最新／补丁已下载待重启生效／需要更新整包／失败原因）。
     */
    /**
     * 🌱 看天赋果实记录（v1.78 新增）。
     *
     * 用户口径（PC 原文）：「类似**小助手的天赋果实记录**，做好放到**工具栏**里」
     *   ＋「**自动扫描**，工具那里能看到天赋果实获取记录」
     *
     * ⚠ 这个按钮**只读记录、不动游戏**：真正的扫描在「体力 < 100 收工」时自动做 ✓
     *   （不给「立即扫」按钮 —— 扫一次要点开背包、翻页、识图，
     *     放在工具栏里让人随手点会打断正在跑的那一局 ✗）
     */
    private void pyFruitReport() {
        pyCall("天赋果实记录", () -> {
            try {
                PyBridge.ensureStarted(getApplicationContext());
                return PyBridge.call("_cmd_run_snippet",
                        "import fruit; print(fruit.report_text())");
            } catch (Throwable t) {
                return "读取失败：" + t;
            }
        });
    }

    private void showUpdateResult(String msg) {
        try {
            new android.app.AlertDialog.Builder(this)
                    .setTitle("更新")
                    .setMessage(msg)
                    .setPositiveButton("知道了", null)
                    .show();
        } catch (Throwable t) {
            AppLog.i("[更新] ⚠ 结果弹窗失败：" + t);
        }
    }

    /**
     * 「▶ 准备启动」：**不直接启动脚本**，只做准备工作。
     *
     * 用户口径（v0.24 / 2026-09-30）：
     *   · 「点 App 的 ▶ 不要再直接运行脚本」
     *   · 「要到悬浮条里点 ▶ 才开始」
     *   · 「按 ■ 停止，停止后回到 选图/启动/暂停 那几个按钮」
     *
     * 行为：
     *   ① 若悬浮条没开 ⇒ 自动开（权限缺失时 toggleOverlay 引导去开，不影响本次）
     *   ② 把游戏切到前台（脚本的截图/点击对象必须是游戏，不是 MGAS 自己）
     *   ③ 检查 4 项就绪（截图 / 无障碍 / OCR / 红装锁）⇒ 任一未就绪：把"还差什么"推到悬浮条
     *   ④ 全部就绪 ⇒ 推送"已就绪 ⇒ 去选图界面点悬浮条 ▶"的提醒
     *   ⭐ **不调 PyBridge.call("start", ...)** —— 真启动只能从悬浮条的 ▶ 来
     */
    private void pyExploreStart() {
        // ⭐ 用户口径：「点开始探索要自动打开悬浮条」（用户原话，v0.23 已采纳）：
        //   跑起来后人在游戏里，悬浮条是游戏内唯一的 停止/看进度 入口 ⇒ 没开就顺手开上
        if (!overlayOn) {
            toggleOverlay();
        }
        // ⭐ 一定要把游戏切回前台 —— 探索循环靠"全屏截图 + OCR 关键词"判定面板，
        //   而本应用界面上就有「开始冒险 / 进入地图」这些字（见 bringGameFront 注释）。
        bringGameFront();
        // ② 就绪检查：缺哪个就在悬浮条上把"该去做什么"写出来
        //   ⭐ v0.26：OCR **不算前置条件** —— `AutoPilot.scan/ensureOcr` 会在第一次 OCR 时
        //     自动初始化（用户口径：OCR 初始化不是必要的）⇒ 不检查、不提示。
        String hint;
        if (!FrameStore.has()) {
            hint = "⚠ 还没「① 授权截图」⇒ 切回 MGAS 授权一次";
        } else if (!AutoTouchService.ready()) {
            hint = "⚠ 还没「② 无障碍设置」⇒ 切回 MGAS 把无障碍打开";
        } else if ("有（先解锁）".equals(redLockText)) {
            hint = "⛔ 红装锁未解 ⇒ 切回 MGAS 点「红装解锁」再来";
        } else {
            // ⭐ 全部就绪 ⇒ 切游戏选图界面 → 点悬浮条 ▶ 启动
            hint = "已就绪 ⇒ 切到游戏「选图界面」 ⇒ 点悬浮条 ▶ 启动";
        }
        OverlayService.setPendingHint(hint);
        AppLog.i("[准备] " + hint + "（脚本启动入口已挪到悬浮条 ▶）");
        ui.post(this::refreshStatus);                 // 状态芯片刷新一次（红装/OCR 状态可能变了）
    }

    /** ⑥ 红装解锁：删掉红装锁文件，之后就能重新开跑 ✓ */
    private void pyRedUnlock() {
        pyCall("红装解锁", () -> {
            String r = PyBridge.call("red_unlock");
            AppLog.i("红装锁状态：" + PyBridge.call("red_lock"));
            return r;
        });
    }

    /**
     * 把游戏切到前台。
     *
     * ⚠ **必须切**：探索循环靠"全屏截图 + OCR 关键词"判定面板，而本应用界面上就有
     *   「⑥ 点开始冒险」「⑪ 停止探索」这些字 —— 如果循环对着本应用截图，会把它们
     *   当成游戏按钮去点（`'开始冒险'`/`'进入地图'` 正是循环的关键词）⇒ 乱点。
     */
    private void bringGameFront() {
        try {
            Intent li = getPackageManager()
                    .getLaunchIntentForPackage("com.chillyroom.monstergirls.yw");
            if (li == null) {
                AppLog.i("⚠ 没找到游戏包 ⇒ 请手动切回游戏再启动探索");
                return;
            }
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(li);
        } catch (Throwable t) {
            AppLog.i("⚠ 切游戏失败：" + t);
        }
    }

    private void pyExploreStop() {
        pyCall("停止探索", () -> {
            String s = PyBridge.call("stop");
            return s + "  " + PyBridge.call("status");
        });
    }
}

