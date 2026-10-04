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
    private TextView sumView;
    private TextView statusView;
    private Button overlayBtn;
    private CheckBox cbSupply;
    private EditText etBagEvery;
    private boolean overlayOn = false;
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

    /** 界面自动刷新（可见时才跑）：后台读 Python → 回主线程画（⚠ 绝不在 UI 线程调 Python） */
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            new Thread(() -> {
                String t = "";
                String r = "{}";
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
                final String ft = t == null ? "" : t.trim();
                final String fr = r == null ? "{}" : r.trim();
                ui.post(() -> {
                    redLockText = (fr.isEmpty() || "{}".equals(fr)) ? "无" : "有（先解锁）";
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

    // ---------------- UI ----------------

    // ⭐ 2026-09-29 UI 优化（用户「顺便优化下软件的 ui」）：卡片分区 + 统一配色 + 状态芯片。
    //   ⚠ 只动观感：所有按钮的 onClick / Prefs 读写 / 成员引用一条没改 ✓
    private static final int UI_BG = 0xFF0B0E13;          // 窗口底
    private static final int UI_CARD = 0xFF161C26;        // 卡片底
    private static final int UI_CARD_LINE = 0xFF26303F;   // 卡片描边
    private static final int UI_PANEL = 0xFF10141B;       // 日志/统计面板底
    private static final int UI_TXT = 0xFFD8E2F0;         // 普通字
    private static final int UI_SUB = 0xFF7FA6D9;         // 小节标题
    private static final int UI_BTN = 0xFF232B3A;         // 普通按钮底
    private static final int UI_BTN_ACCENT = 0xFF1E3450;  // 授权组按钮底
    private static final int UI_BTN_WARN = 0xFF4A3A1D;    // 红装解锁按钮底

    private View buildUi() {
        int pad = dp(12);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        root.setBackgroundColor(UI_BG);

        // ── 状态芯片（就绪=绿 / 有未就绪项=橙）──
        statusView = new TextView(this);
        statusView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        statusView.setTypeface(Typeface.DEFAULT_BOLD);
        statusView.setPadding(dp(10), dp(7), dp(10), dp(7));
        chip(statusView, 0xFF12291A, 0xFF1F5C33);
        LinearLayout.LayoutParams stLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        stLp.bottomMargin = dp(10);
        root.addView(statusView, stLp);

        // ⭐ 整页可滚动（2026-09-29 用户口径：「整体可以往下滑啊，不要压缩太多」）：
        //    控制卡**全部保留、不压缩**，放不下的部分往下滑；日志/统计固定高度常驻底部
        ScrollView outer = new ScrollView(this);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        outer.addView(content, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        // ══════ 卡片①：探索（正常人只用这一区）════════
        LinearLayout card1 = card("探索");
        // ⭐ v0.24 口径：这个按钮**不直接启动脚本** —— 只是「准备」（开悬浮条 + 切游戏前台 +
        //    检查就绪 + 在悬浮条提醒用户去点 ▶）。真启动只能从悬浮条的 ▶ 来。
        //    历史：v0.23 之前这里直接调 `PyBridge.call("start", ...)` ⇒ 玩家点一下脚本就跑
        //    ⇒ 经常撞上"游戏还停在登录页/大厅/选图界面 ⇒ 瞎跑"，所以改成"两步确认"。
        LinearLayout rowA = new LinearLayout(this);
        rowA.setOrientation(LinearLayout.HORIZONTAL);
        Button bStart = btn("▶ 准备启动", BTN_START, v -> pyExploreStart());
        bStart.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        bStart.setMinimumHeight(dp(46));
        bStart.setMinHeight(dp(46));
        rowA.addView(bStart, lp());
        Button bStop = btn("■ 停止探索", BTN_STOP, v -> pyExploreStop());
        bStop.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        bStop.setMinimumHeight(dp(46));
        bStop.setMinHeight(dp(46));
        rowA.addView(bStop, lp());
        card1.addView(rowA);

        LinearLayout rowB = new LinearLayout(this);
        rowB.setOrientation(LinearLayout.HORIZONTAL);
        overlayBtn = btn("悬浮条：关", BTN_NORMAL, v -> toggleOverlay());
        rowB.addView(overlayBtn, lp());
        rowB.addView(btn("回到游戏", BTN_NORMAL, v -> bringGameFront()), lp());
        card1.addView(rowB);

        // ── 探索设置（④ 自动补给 / ⑤ 每 X 张升星）──
        //  ⚠ 这些值存 Prefs：**悬浮条的 ▶ 也读这一份** ⇒ 界面上勾了，悬浮条开跑就生效 ✓
        LinearLayout row8 = new LinearLayout(this);
        row8.setOrientation(LinearLayout.HORIZONTAL);
        row8.setGravity(android.view.Gravity.CENTER_VERTICAL);

        cbSupply = new CheckBox(this);
        cbSupply.setText("没体力自动用补给");
        cbSupply.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        cbSupply.setTextColor(UI_TXT);
        cbSupply.setChecked(Prefs.autoSupply(this));
        cbSupply.setOnCheckedChangeListener((v, on) -> {
            Prefs.setAutoSupply(this, on);
            AppLog.i("设置：没体力自动用补给 = " + (on ? "开 ✓" : "关"));
        });
        row8.addView(cbSupply);

        TextView lbBag = new TextView(this);
        lbBag.setText("　每");
        lbBag.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        lbBag.setTextColor(UI_TXT);
        row8.addView(lbBag);

        etBagEvery = new EditText(this);
        etBagEvery.setText(String.valueOf(Prefs.bagEvery(this)));
        etBagEvery.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        etBagEvery.setTextColor(UI_TXT);
        etBagEvery.setInputType(InputType.TYPE_CLASS_NUMBER);
        etBagEvery.setWidth(dp(52));
        etBagEvery.setGravity(android.view.Gravity.CENTER);
        // ⭐⭐ 2026-10-01 修（用户报「设了每 1 张图升一次，却完全没去升过」）：
        //   原来**只在"失去焦点"时提交** ⇒ 在 MGAS 里把 10 改成 1、然后直接去悬浮条点 ▶
        //   或切回游戏时，EditText 的**视图级焦点并没有变**（窗口失焦 ≠ 视图失焦）
        //   ⇒ `onFocusChange` 不触发 ⇒ Prefs 里还是老值（默认 10）⇒ 悬浮条 ▶ 读到 10
        //   ⇒ 日志里 `bag_every=10`、一次都没升星。
        //   真机实锤（15:24 那轮）：logcat 里**连一条「设置：每 …」都没有** = 提交函数
        //   一次都没跑过 ✓
        //   ⇒ 改成**边打边存**（只写 Prefs、**绝不动 setText**）。老注释担心的
        //     "1 存成 1、再打 0 变 01 打不出 10" 是 **setText 把光标复位**造成的，
        //     这里不 setText ⇒ 那个坑不存在 ✓；空串（正在删改）跳过 ⇒ 不会存成 0 ✗
        etBagEvery.addTextChangedListener(new android.text.TextWatcher() {
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
        etBagEvery.setOnFocusChangeListener((v, has) -> {
            if (!has) {
                commitBagEvery();
            }
        });
        row8.addView(etBagEvery);

        TextView lbBag2 = new TextView(this);
        lbBag2.setText("张图升级装备星级");
        lbBag2.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        lbBag2.setTextColor(UI_TXT);
        row8.addView(lbBag2);
        card1.addView(row8);

        // ⑭ 单独一行：跟设置挤一行会被压成"竖排"（实测）
        LinearLayout row8b = new LinearLayout(this);
        row8b.setOrientation(LinearLayout.HORIZONTAL);
        row8b.addView(btn("⑭ 红装解锁（发现红装后点这里才能重新开跑）", BTN_WARN, v -> pyRedUnlock()), lp());
        card1.addView(row8b);
        content.addView(card1);

        // ══════ 卡片②：首次设置（各点一次就行）════════
        LinearLayout card2 = card("首次设置（各点一次就行）");
        LinearLayout rowC = new LinearLayout(this);
        rowC.setOrientation(LinearLayout.HORIZONTAL);
        rowC.addView(btn("① 授权截图", BTN_ACCENT, v -> requestCapture()), lp());
        rowC.addView(btn("② 无障碍设置", BTN_ACCENT, v -> openAccessibility()), lp());
        rowC.addView(btn("③ 悬浮窗权限", BTN_ACCENT, v -> openOverlayPerm()), lp());
        card2.addView(rowC);
        content.addView(card2);

        // ⭐ v1.41 热更新卡（用户 2026-10-03：「发给朋友的怎么搞热更新？」）
        //   逻辑补丁**不用在这里点** —— 悬浮条一起来就自动查、自动下、重启即生效；
        //   这张卡主要管**整包**：点一下 → 下载 → 系统安装器弹出 → 点「安装」。
        LinearLayout card4 = card("更新");
        LinearLayout rowU = new LinearLayout(this);
        rowU.setOrientation(LinearLayout.HORIZONTAL);
        rowU.addView(btn("检查更新（补丁+整包）", BTN_ACCENT, v -> doUpdate("auto")), lp());
        rowU.addView(btn("只看状态", BTN_NORMAL, v -> doUpdate("check")), lp());
        card4.addView(rowU);
        content.addView(card4);

        // ══════ 卡片④：特殊方块勾选（用户口径：**放在「更新」下面**）════════
        //  学 PC 端 `0e43db5` / `2ab3105`：
        //  用户口径（PC 端原话）：「窗口加上特殊方块勾选，其中**商人和宝库默认勾选**，
        //    其他的默认不勾选（就是拉黑），**暂时也无法勾选**」✓
        //  语义（`targets_cfg` 顶部注释）：`types` 里 **true = 主动去处理**；
        //    缺/False ⇒ `is_blocked(name)` = True ⇒ **拉黑**（不进目标、也不借道 ✓）
        //  ⚠ 勾选变化**立刻落盘** ✓（PC 端 `2ab3105` 修的坑：攒着不写 ⇒ 改了没用 ✗）
        //  ⚠ 取消勾选要**显式写 False** ✓ —— 不能删键，否则 `load()` 的
        //    `setdefault(k, True)` 会把它补回 True ⇒ 取消勾选**永远无效** ✗✗
        //  ⚠⚠ 真机踩到的坑：**不能在 `buildUi()` 里调 Python** ✗ ——
        //    `DeviceApi.bind()` 是 `setContentView(buildUi())` **之后**才调的
        //    ⇒ 那时 `PyBridge` 还没绑 ⇒ `IllegalStateException: bind 还没调用过`
        //    ⇒ 整个勾选排填不出来（真机实测：卡片在、里面只有一行"读不到清单"）
        //    ⇒ 所以这里**只搭骨架**，行由 `fillSpecialRows()` 在 bind 之后填 ✓
        cardSp = card("特殊方块（不勾 = 拉黑）");
        TextView spHint = new TextView(this);
        spHint.setText("商人和宝库默认勾选；其余特殊方块暂时锁定（= 拉黑）。"
                + "改动立刻生效，下一轮规划就按新口径走 ✓");
        spHint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        spHint.setTextColor(UI_SUB);
        cardSp.addView(spHint);
        spBody = new LinearLayout(this);
        spBody.setOrientation(LinearLayout.VERTICAL);
        cardSp.addView(spBody);
        spLoading = new TextView(this);
        spLoading.setText("（正在读清单…）");
        spLoading.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        spLoading.setTextColor(UI_SUB);
        spBody.addView(spLoading);
        content.addView(cardSp);

        // ══════ 卡片③：调试（**按钮默认关闭**：Prefs.showDebug 默认 false ⇒ 整盒藏起）════════
        LinearLayout card3 = card("调试");
        LinearLayout rowD = new LinearLayout(this);
        rowD.setOrientation(LinearLayout.HORIZONTAL);
        CheckBox cbDebug = new CheckBox(this);
        cbDebug.setText("显示调试按钮（排查用）");
        cbDebug.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        cbDebug.setTextColor(UI_TXT);
        cbDebug.setChecked(Prefs.showDebug(this));
        rowD.addView(cbDebug);
        rowD.addView(btn("清空日志", BTN_NORMAL, v -> {
            AppLog.clear();
            logView.setText("");
        }), new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 0.55f));
        card3.addView(rowD);

        LinearLayout debugBox = new LinearLayout(this);
        debugBox.setOrientation(LinearLayout.VERTICAL);
        debugBox.setVisibility(Prefs.showDebug(this) ? View.VISIBLE : View.GONE);
        cbDebug.setOnCheckedChangeListener((v, on) -> {
            Prefs.setShowDebug(this, on);
            debugBox.setVisibility(on ? View.VISIBLE : View.GONE);
        });
        LinearLayout rowE = new LinearLayout(this);
        rowE.setOrientation(LinearLayout.HORIZONTAL);
        rowE.addView(btn("初始化 OCR", BTN_NORMAL, v -> initOcr()), lp());
        rowE.addView(btn("测识别+dump", BTN_NORMAL, v -> testOcr()), lp());
        debugBox.addView(rowE);
        LinearLayout rowF = new LinearLayout(this);
        rowF.setOrientation(LinearLayout.HORIZONTAL);
        rowF.addView(btn("点开始冒险", BTN_NORMAL, v -> tapStart()), lp());
        rowF.addView(btn("导出截图", BTN_NORMAL, v -> dumpFrame()), lp());
        debugBox.addView(rowF);
        LinearLayout rowG = new LinearLayout(this);
        rowG.setOrientation(LinearLayout.HORIZONTAL);
        rowG.addView(btn("环境快照", BTN_NORMAL, v -> pyInfo()), lp());
        rowG.addView(btn("端上自检", BTN_NORMAL, v -> pySelftest()), lp());
        debugBox.addView(rowG);
        card3.addView(debugBox);
        content.addView(card3);
        root.addView(outer, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        // ── 推图日志（PC 窗口风格：等宽字体）—— **固定高度常驻**（不跟上面的滚动走，永远看得到）──
        root.addView(sectionLabel("推图日志（PC 窗口同款）"));
        logView = new TextView(this);
        logView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 10);
        logView.setTypeface(Typeface.MONOSPACE);      // ⭐ 等宽：`== 第 1 张图 ==` 这类缩进才对得齐
        logView.setTextColor(0xFFC8D4E4);
        logView.setMovementMethod(new ScrollingMovementMethod());
        logView.setBackgroundColor(UI_PANEL);
        logView.setPadding(dp(8), dp(6), dp(8), dp(6));
        root.addView(logView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(150)));

        // ── 本次统计（= PC 窗口下面那个独立统计框）—— 固定高度常驻 ──
        root.addView(sectionLabel("本次统计"));
        sumView = new TextView(this);
        sumView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 10);
        sumView.setTypeface(Typeface.MONOSPACE);
        sumView.setTextColor(0xFFC8D4E4);
        sumView.setMovementMethod(new ScrollingMovementMethod());
        sumView.setBackgroundColor(UI_PANEL);
        sumView.setPadding(dp(8), dp(6), dp(8), dp(6));
        root.addView(sumView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(110)));
        return root;
    }

    // ── UI 小工具（卡片 / 圆角 / 按钮样式）──

    /** 按钮样式代号 */
    private static final int BTN_NORMAL = 0;
    private static final int BTN_START = 1;
    private static final int BTN_STOP = 2;
    private static final int BTN_ACCENT = 3;
    private static final int BTN_WARN = 4;

    /** 一张圆角卡片（带小节标题），返回内容容器 */
    private LinearLayout card(String title) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable g = new GradientDrawable();
        g.setColor(UI_CARD);
        g.setCornerRadius(dp(12));
        g.setStroke(dp(1), UI_CARD_LINE);
        box.setBackground(g);
        box.setPadding(dp(10), dp(8), dp(10), dp(10));
        TextView tv = sectionLabel(title);
        box.addView(tv);
        return box;
    }

    /** 小节标题（蓝灰色小字） */
    private TextView sectionLabel(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setTextColor(UI_SUB);
        tv.setPadding(0, dp(2), 0, dp(6));
        return tv;
    }

    /**
     * 「特殊方块」勾选排 —— 学 PC 端 `0e43db5` / `2ab3105` / `5de0e9c`。
     *
     * <p>用户口径（PC 端原话）：「窗口加上特殊方块勾选，其中<b>商人和宝库默认勾选</b>，
     * 其他的默认不勾选（就是拉黑），<b>暂时也无法勾选</b>」✓
     *
     * <p>语义：`targets_cfg.types` 里 <b>true = 主动去处理</b>；缺/False ⇒ 拉黑 ✓
     * <p>勾选变化<b>立刻落盘</b> ✓（PC 端 `2ab3105` 修的坑：攒着不写 ⇒ 改了没用 ✗）
     * <p>可勾的两个 = `explore_android.SP_EDITABLE`（旅行商人 / 黄金宝库），
     * 其余 `locked=true` ⇒ <b>灰掉</b>（用户口径「暂时无法勾选」✓）
     *
     * <p>⚠⚠ 真机踩到的坑：<b>不能在 `buildUi()` 里调它</b> ✗ ——
     * `DeviceApi.bind()` 是 `setContentView(buildUi())` <b>之后</b>才调，
     * 那时 `PyBridge` 还没绑 ⇒ `IllegalStateException: bind 还没调用过`
     * ⇒ 卡片建出来了、里面只有一行「读不到清单」（真机实测 ✗）
     * ⇒ 所以本方法<b>幂等 + 可重试</b>：在 bind 之后调一次，
     * 没成功就让 tick 每轮再试（Python 冷启动慢也能补上 ✓）
     */
    private void fillSpecialRows() {
        if (spFilled || spBody == null) {
            return;
        }
        String js = PyBridge.call("special_list");
        org.json.JSONArray arr = null;
        try {
            org.json.JSONObject o = new org.json.JSONObject(
                    (js == null || js.isEmpty()) ? "{}" : js);
            arr = o.optJSONArray("items");
        } catch (Throwable e) {
            AppLog.i("特殊方块：解析列表失败 " + e);
        }
        if (arr == null || arr.length() == 0) {
            if (spLoading != null) {
                spLoading.setText("（正在读清单…若一直这样，看日志）");
            }
            return;                    // 不置 spFilled ⇒ 下一轮 tick 会再试 ✓
        }
        spBody.removeAllViews();
        spFilled = true;
        LinearLayout box = spBody;
        // 排布：横向流式放，每行最多 2 个（手机上再窄也不挤 ✓）
        LinearLayout row = null;
        for (int i = 0; i < arr.length(); i++) {
            org.json.JSONObject it = arr.optJSONObject(i);
            if (it == null) {
                continue;
            }
            final String nm = it.optString("name", "");
            final boolean on = it.optBoolean("on", false);
            final boolean locked = it.optBoolean("locked", true);
            if (i % 2 == 0) {
                row = new LinearLayout(this);
                row.setOrientation(LinearLayout.HORIZONTAL);
                row.setGravity(android.view.Gravity.CENTER_VERTICAL);
                box.addView(row);
            }
            CheckBox cb = new CheckBox(this);
            cb.setText(nm + (locked ? "（锁定）" : ""));
            cb.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
            cb.setTextColor(locked ? UI_SUB : UI_TXT);
            cb.setChecked(on);
            cb.setEnabled(!locked);            // 锁定的灰掉（用户口径「暂时无法勾选」✓）
            if (!locked) {
                cb.setOnCheckedChangeListener((v, val) -> {
                    String r = PyBridge.call("special_set", nm, val);
                    AppLog.i("特殊方块「" + nm + "」⇒ "
                            + (val ? "勾选·主动处理" : "取消·拉黑") + "（" + r + "）");
                });
            }
            row.addView(cb, lp());
        }
    }

    /** 给任意 View 铺圆角底（状态芯片用） */
    private void chip(View v, int bg, int line) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(bg);
        g.setCornerRadius(dp(9));
        g.setStroke(dp(1), line);
        v.setBackground(g);
    }

    private Button btn(String text, int style, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        int bg = UI_BTN;
        int fg = UI_TXT;
        switch (style) {
            case BTN_START:
                bg = 0xFF1D4A2C;
                fg = 0xFF8CFF9E;
                break;
            case BTN_STOP:
                bg = 0xFF4A1D1D;
                fg = 0xFFFF9E9E;
                break;
            case BTN_ACCENT:
                bg = UI_BTN_ACCENT;
                fg = 0xFFB0D8FF;
                break;
            case BTN_WARN:
                bg = UI_BTN_WARN;
                fg = 0xFFFFD98A;
                break;
            default:
                break;
        }
        GradientDrawable g = new GradientDrawable();
        g.setColor(bg);
        g.setCornerRadius(dp(10));
        g.setStroke(dp(1), 0x33FFFFFF);
        b.setBackground(g);
        b.setTextColor(fg);
        // ⭐ Material Button 默认 minHeight=48dp ⇒ 8 行按钮就吃掉 1150px。收到 34dp，
        //    再配合「整页可滚动 + 日志/统计固定高度常驻」（2026-09-29 用户口径：
        //    「也可能做成整体可以往下滑啊，不要压缩太多」⇒ 不压缩，改成滚动）✓
        b.setMinimumHeight(dp(34));
        b.setMinHeight(dp(34));
        b.setPadding(dp(6), dp(2), dp(6), dp(2));
        b.setOnClickListener(l);
        return b;
    }

    private LinearLayout.LayoutParams lp() {
        return new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void appendLog(String line) {
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

    /** 「每 X 张图升级装备星级」提交（失去焦点 / onPause 时）—— 空/非法就回落默认 10 */
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

    private void refreshStatus() {
        statusView.setText(String.format(Locale.US,
                "截图：%s ｜ 点击通道：%s ｜ 红装锁：%s",
                FrameStore.has() ? "就绪" : "未授权",
                AutoTouchService.ready() ? "就绪" : "未开启",
                redLockText));
        // ⭐ v0.26：OCR 不再上芯片 —— 第一次 OCR 时自动初始化（非前置条件，用户口径），
        //   显示「未初始化」反而让用户以为要去手动点（实际不用）
        boolean ok = FrameStore.has() && AutoTouchService.ready()
                && "无".equals(redLockText);
        statusView.setTextColor(ok ? 0xFF8CFFB0 : 0xFFFFC08A);
        // ⭐ 芯片底色跟着变：全就绪=绿底，缺哪样=橙底（一眼看出还差什么）
        chip(statusView, ok ? 0xFF12291A : 0xFF33220E,
                ok ? 0xFF1F5C33 : 0xFF6B4A1D);
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
        if (req == REQ_CAPTURE && res == RESULT_OK && data != null) {
            Intent i = new Intent(this, CaptureService.class);
            i.putExtra(CaptureService.EXTRA_CODE, res);
            i.putExtra(CaptureService.EXTRA_DATA, data);
            if (Build.VERSION.SDK_INT >= 26) {
                startForegroundService(i);
            } else {
                startService(i);
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

