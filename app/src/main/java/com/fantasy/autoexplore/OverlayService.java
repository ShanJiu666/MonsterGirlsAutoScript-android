package com.fantasy.autoexplore;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.text.TextPaint;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * 悬浮窗控制条 —— **给正常人用的入口**（此前只能靠 adb 广播，日常没法用）。
 *
 * ```
 * 收起：  ● MGAS
 * 空闲：  ● MGAS [1图] [▶] [■]        [ 当前行动（跑马灯） ]
 * 运行：  ▶ MGAS [■]                  [ 第 3 张图 · 进图中 ……→ ]
 * ```
 *
 *   ●/▶/!/⛔ 状态灯：灰=空闲 / ▶绿=运行中 / !红=出错过 / ⛔红=红装锁
 *   MGAS  点它 = 展开/收起（也是**拖动手柄**）；长按 = 强制显示/隐藏日志行
 *   1图   点它切换「本次跑几张」：**1图 ⇄ 连刷**（连刷 = 一直刷到体力耗尽）
 *   ▶     开始（**点一下就走**，无二次确认/倒计时 —— 用户明确要求"点一下就开始"）
 *   ■     停止（停在两张图之间，打完手上这张才收工 ✓ 不会留半张）
 *   日志行 显示**当前的行动**（由原始日志翻译成一句人话），**平滑跑马灯**向左飘；
 *          点一下 = 往回翻一条（显示 `↺n` + 原始日志）；长按 = 回到最新
 *
 * ⚠ 每一下点击都会 `flash()` 一次（底色闪蓝）—— "点了没反应"在触屏上等于"坏了"。
 *
 * ⚠⚠⚠ **四条硬约束**（都是真机上踩出来的，改动前务必读完）
 *
 * ① **悬浮条绝不能盖到棋盘（参考 y ≤ 1722）**。
 *    棋盘几何（`layout.py`）：`grid_y0=1002, grid_cy=144, rows=5` ⇒ 最低一行占 **1578~1722**；
 *    真实日志里最低一行的格子中心恰好是 `(108/252/396/540/684, 1650)`。
 *    盖住它会同时坏事：
 *      · 那几格的美术被挡 ⇒ **模板识别错**（不是"看不清"，是给出错的 sid）
 *      · 点击落在它身上会被悬浮窗**吃掉** ⇒ 那 5 格点不动
 *    ⇒ 本条的几何是**两行、高 84、底边钉在参考 y=1816**（棋盘下沿 1722 与底部导航图标 1828 之间）：
 *      **上行 = 日志（整行上下滚动）**、**下行 = 按钮**（用户口径 2026-09-29「悬浮窗要在按钮上面」）。
 *      高度预算 = 1816 − 1722 = **94px**，当前用 28（日志）+ 56（按钮）= 84 ⇒ 顶边 1732 ✓
 *      （⚠ 最初的两行版顶边到 1665，已经压住最低一行；那是"日志行单独占一行的竖向两行"，
 *        没能压进 94px。要点：**字号必须走参考系像素** `devLen()`，别用 sp —— 换个密度就顶穿。）
 *    改布局后必须量：`--es cmd overlay_dump` 会报 `bar(dev)` 与 `顶边(参考 y)`，必须 ≥ 1722。
 *    ⚠ 拖动也被夹在安全带里（`installDrag`：顶边不许高过 1722），否则一拖就把棋盘抹平。
 *
 * ② **不要用 `FLAG_SECURE`**。曾经加过（想让悬浮窗对截图隐形，以免日志里的
 *    「关闭/探索/开始冒险」被循环的**全屏 OCR 子串匹配**（`explore_loop.fb`）误判成游戏面板，
 *    也以免跑马灯一直在动把 `wait_stable`（默认带 `(130,1800)`，正罩着本条）**永远等不到稳定**）。
 *    但 2026-09-29 在 MuMu 上实测：**悬浮窗一带上 SECURE，整个 `screencap` 直接失败（0 字节，
 *    设备内 `exit=1`）**，关掉立刻正常 ⇒ MuMu 的 SurfaceFlinger 遇到安全窗口会拒绝整屏抓取，
 *    MediaProjection 大概率同样取不到帧 ⇒ **推图会直接瞎**。⇒ 拆掉，改用 ③。
 *
 * ③ ⭐ **正解：让机器人"对自己瞎"** —— `FrameStore.set()` 里把悬浮条那块**涂平**
 *    （见 `FrameStore.maskOverlay`）。它同时解决 ② 想解决的两件事：
 *      · 涂平后那块**没有任何文字** ⇒ OCR 拿不到关键词 ✓
 *      · 涂平后那块**恒定不变** ⇒ `wait_stable` / `wait_change`（含 `around` 局部窗口）
 *        照样能稳定 ✓
 *    而"涂平"之所以零副作用，正是靠 ① 的几何：本条只占 1739~1816，
 *    碰不到棋盘(≤1722)、碰不到 `boardLuma`(1002~1722)、碰不到 `wait_change` 主带(130~1700)。
 *    ⇒ ①②③ 是一套的：**动几何就要重新确认涂平区不碰任何采样区**。
 *
 * ④ 想定位就**只能用 `RefMapper.devX/devY`**，不能 `dp()`
 *    （dp 按屏幕密度算，1080×1920@480dpi 下 dp(1725)=5175px，直接飞出屏幕 ✗）。
 *    算**宽度/尺寸**要用 `RefMapper.devLen()`（`devX` 带居中偏移，只有"坐标"能用）。
 *    ⚠ 尺寸用 sp/dp 是**可以**的（已核算：本条参考系高度 ≤77 < 94 的预算），别再改字号内边距而不复量。
 *
 * 触碰隔离：`FLAG_NOT_FOCUSABLE`（不抢焦点），但**会吃掉落在它身上的触摸**
 *   ⇒ `Gravity.BOTTOM` 把底边钉死、只横向生长；收起只能手动（用户 2026-09-29 口径：不自动收缩）
 *     （**运行中不收**：用户明确要求"跑起来也要能看到日志"），✕ / 点气泡 / 点 ■ 可立刻收起。
 */
public class OverlayService extends Service {

    private static final String CHAN = "autoexplore";
    private static final int NOTIF_ID = 1011;
    /** 游戏包名（点 ▶ 前顺手切回游戏；切不动就算了，只写日志） */
    static final String GAME_PKG = "com.chillyroom.monstergirls.yw";
    /** 可选的「本次跑几张」（点一下在两者间切换）—— 见 {@link #MAP_LABELS} */
    private static final String[] MAP_LABELS = {"1图", "连刷"};
    /** 「连刷」时下发的张数上限（真正停下来的判据是"体力不够进图"，这个数只是别写成无限） */
    private static final int MAPS_CONTINUOUS = 999;
    /** 每张图的进图体力（与 PC 口径一致） */
    private static final int STAMINA_PER_MAP = 25;
    /** 按钮底色 / 点击瞬间的高亮 */
    private static final int CHIP_BG = 0xD9303030;
    private static final int CHIP_BG_TAP = 0xFF3D6FB4;

    /** 日志行保留多少条（往回翻最多翻这么多） */
    private static final int LOG_KEEP = 60;
    /** 日志行里最多留多少字符（太长就截断；超宽的部分由省略号收尾） */
    private static final int LOG_MAX_CHARS = 110;
    /** ⭐ **两行布局**（2026-09-29 用户口径：「悬浮窗要在按钮上面」）：
     *  上行 = 日志（整行、全宽、**上下滚动**、**浅底黑字**），下行 = 按钮。
     *  高度预算：底边钉 1816、顶边必须 ≥ 1722 ⇒ 总共只能有 **94 参考 px**。
     *  这里用 34（日志）+ 56（按钮）= **90** ⇒ 顶边 1726，留 4px 余量 ✓
     *  （2026-09-29 用户又要求「字放大一点，黑体」：日志 22→28 px + 加粗）*/
    private static final int LOG_ROW_H_REF = 34;
    /** 日志字号（参考系像素） */
    private static final float LOG_TEXT_REF = 28f;
    /** 日志行**黑字**（用户口径）——必须配浅底才看得见，见 {@link #LOG_BG_COLOR} */
    private static final int LOG_TEXT_COLOR = 0xFF000000;
    /** 日志行**浅色底**：把这一行和身后的游戏/App 文字分开，一眼看清"按钮上方那行是我的" */
    private static final int LOG_BG_COLOR = 0xFFF2F4F7;
    /** 按钮字号（参考系像素）。⚠ 两行后必须压小：原来 15sp(45px) 会把总高顶到 100+ ⇒ 越过 1722 */
    private static final float CHIP_TEXT_REF = 34f;
    /** 按钮竖向内边距（参考系像素）——和字号一起决定按钮行高度 */
    private static final int CHIP_PAD_V_REF = 8;
    /** 底边固定在参考系 y=1816（收/展都钉这里） */
    private static final int BAR_BOTTOM_REF = 1816;
    /** 棋盘下沿（参考 y）——顶边绝不允许越过它，见硬约束① */
    private static final int BOARD_Y1_REF = 1722;
    /** 底边离屏幕底多少（参考系像素）。`Gravity.BOTTOM` 下 `lp.y` 用的就是它。
     *  ⚠ 必须走 {@link RefMapper#devY}：BOTTOM 下 `lp.y` 是「离屏幕底的距离」，而
     *  `devY(1920−y)` 恰好等于它（居中留黑边时也成立，推导见 README §6.9） */
    private static final int BAR_BOTTOM_OFFSET_REF = RefMapper.REF_H - BAR_BOTTOM_REF;
    /** ⚠ 已停用（用户 2026-09-29 口径「不要自动收缩的问题」）。**别再拿它去 postDelayed**。 */
    private static final long IDLE_COLLAPSE_MS = 15000L;

    /**
     * 会被探索循环当"游戏面板关键词"的词 ⇒ 日志行里一律糊掉（硬约束③的双保险：
     * 涂平已经让循环看不见它了，这里再兜一层，防止"哪天涂平忘了/失效"）。
     * 与 `explore_loop.py` 的 `fb(items, …)` 关键词表对齐（**长的排前面**，便于整体替换）。
     */
    private static final String[] OCR_KEYWORDS = {
            "开始冒险", "进入地图", "一键派遣", "探索配队", "探索产出",
            "关闭", "探索", "派遣", "领取",
    };

    /** 便于广播 `overlay_dump` 读当前状态（服务可能没起 ⇒ null） */
    private static volatile OverlayService INSTANCE;
    /** 悬浮条当前占的设备像素矩形 {left,top,right,bottom}；null = 没显示。
     *  ⭐ 给 `FrameStore.maskOverlay` 用（"让机器人对自己瞎"），见硬约束③ */
    private static volatile int[] BLANK_RECT;

    private WindowManager wm;
    private WindowManager.LayoutParams lp;
    /** 外层竖向两行：`[日志行]` / `[按钮行]`（见 LOG_ROW_H_REF 注释） */
    private LinearLayout bar;
    /** 下行：气泡 + 张数 + ▶ + ■ + ✕ */
    private LinearLayout btnRow;
    private MarqueeView tvLog;
    private TextView bubble, btnCount, btnStart, btnStop, btnClose;
    /** 展开（true）时可见按钮 + 日志行；收起（false）只剩气泡 */
    private boolean expanded = false;
    /** 日志行是否要显示（运行中自动 true；长按气泡可手动强开/强关） */
    private boolean logMode = false;
    /** 手动覆盖：null=跟随运行状态；TRUE/FALSE=长按气泡强制 */
    private Boolean logForce = null;
    /** 见过的**最大**条高（收起 56 / 展开 84）——拖动夹子按它算，否则一展开就顶穿 1722 */
    private int barMaxH = 0;
    /** 见过的**最大**条宽（收起 209 / 展开 960）——同理，免得展开后右端被屏幕切掉 */
    private int barMaxW = 0;
    private int choiceIdx = 0;
    /** 上一次画过的状态（只在**变化时**重绘 ⇒ 画面别乱闪） */
    private String lastState = null;

    /** 最近的日志行（`addLast` 追加 / 满了 `removeFirst`） */
    private final ArrayDeque<String> logBuf = new ArrayDeque<>();
    /** 0 = 跟随最新；n>0 = 往回第 n 条（点日志行开始往回翻） */
    private int logBack = 0;
    /** 最近一次「当前的行动」（由日志翻译来；没翻译出来就沿用上一条） */
    private String action = "MGAS 就绪";

    private final Handler ui = new Handler(Looper.getMainLooper());
    private AppLog.Listener logListener;

    /** 收起只能手动（✕ 或点气泡）：**绝不自动收起**
     * —— 2026-09-29 用户口径「不要自动收缩的问题」。
     * 历史：曾按 IDLE_COLLAPSE_MS=15s 空闲收起，用户嫌"日志看着看着就没了"。
     * 想关掉整条悬浮条请去界面点「悬浮条：关」（`OverlayService.stop`）。 */
    private final Runnable collapseIdle = () -> {
        // ⚠ 留作手动调用的占位（不调度 = 永不触发）；别再 postDelayed 它。
        setExpanded(false);
    };

    /** 有操作就续"自动收起"的倒计时 —— 现已**禁用**（用户要求不自动收缩），保留签名少动调用点 */
    private void keepAlive() {
        // ⭐ 有意留空：不再 schedule collapseIdle。
        //   把下次想"加回自动收起"的人拦在这里：先问用户（09-29 被明确否决过）。
    }

    /**
     * ⭐ dev 验证钩子（广播 `overlay_state --es state run|idle|err|lock|auto`）：
     * 强制状态灯颜色，用来**零体力**验证"跑起来图标变绿 + 悬浮条不收起"这条外观需求
     * （真跑一张图要 25 体力，不值得）。`auto` = 取消强制，回到真实 `explore_status`。
     * 用户日常走不到这里（只有 adb 广播能触发）。
     */
    private static volatile String stateForce = null;

    /** 把强制状态翻成 `explore_android.status()` 同款 JSON（`paint()` 就是按这些子串判的） */
    private static String statusJsonFor(String name) {
        if ("run".equals(name)) {
            return "{'running': True, 'result': '', 'error': ''}";
        }
        if ("lock".equals(name)) {
            return "{'running': False, 'result': '', 'error': '', 'red_locked': True}";
        }
        if ("err".equals(name)) {
            return "{'running': False, 'result': 'error', 'error': 'dev'}";
        }
        return "{'running': False, 'result': '', 'error': ''}";
    }

    /** 广播入口：设/取消强制状态并立刻重画一次 */
    static void forceState(String name) {
        OverlayService s = INSTANCE;
        if (s == null) {
            AppLog.i("[ovl] 悬浮条没在跑 ⇒ 先 overlay_on");
            return;
        }
        s.ui.post(() -> {
            s.stateForce = (name == null || name.isEmpty() || "auto".equals(name)) ? null : name;
            AppLog.i("[ovl] 强制状态 = " + (s.stateForce == null ? "（取消，跟随真实）" : s.stateForce));
            s.ui.removeCallbacks(s.poll);
            s.ui.post(s.poll);
        });
    }

    /**
     * ⭐ dev 验证钩子（广播 `overlay_roll`）：**零体力**证明"整行上下滚动"。
     * ① 强制展开 + 日志行可见 ② 注入一条**带序号**的合成日志（序号保证文本必变 ⇒ `setLine`
     * 一定会重置 `roll=0`）③ 在 +0/+90/+180/+400ms 各打一条 `[roll_probe]`。
     * 期望：`roll` 从 0 涨到 1，同时「上一句」从"有"变"无"、`旧句y` 从 0 变 −h、`新句y` 从 +h 变 0。
     * 用户日常走不到这里（只有 adb 广播能触发）。
     */
    static void probeRoll() {
        OverlayService s = INSTANCE;
        if (s == null) {
            AppLog.i("[roll_probe] 悬浮条没在跑 ⇒ 先 overlay_on");
            return;
        }
        ROLL_PROBE_SEQ++;
        final String t = "⟳ 滚动验证 #" + ROLL_PROBE_SEQ + "（整行上下推）";
        s.ui.post(() -> {
            s.setExpanded(true);
            s.logForce = Boolean.TRUE;              // 空闲态也让日志行露脸
            s.applyMode();
            s.tvLog.setLine(t, MarqueeView.STYLE_ACTION);
            AppLog.i("[roll_probe] 注入：" + t);
        });
        for (final long d : new long[]{0L, 90L, 180L, 400L}) {
            s.ui.postDelayed(() -> AppLog.i("[roll_probe +" + d + "ms] " + s.tvLog.debugRoll()), d);
        }
        // 收尾：把 logForce 交回自动（不然以后一展开就常驻日志行，和空闲态按钮抢位置）
        s.ui.postDelayed(() -> {
            s.logForce = null;
            s.applyMode();
            AppLog.i("[roll_probe] 结束（logForce 交回自动）");
        }, 1200L);
    }

    private static int ROLL_PROBE_SEQ = 0;

    /** ⭐ 「准备启动」提醒：界面点 ▶ 准备启动 ⇒ 悬浮条展开显示这句，等用户到选图界面自己点 ▶ */
    private static volatile String pendingHint = null;

    /**
     * 设置「准备启动」提醒。**两种用法都支持**：
     * ① 悬浮条还没起 ⇒ 存到静态字段，等 onCreate() 消费（首次开悬浮条时）
     * ② 悬浮条已起 ⇒ 直接 post 到 UI 线程：展开 + 在日志行显示 + 锁住不被新日志刷掉
     *   （这是常态：玩家按 App 的 ▶，悬浮条早就在屏幕上 ⇒ 必须走这条路径）
     * 真跑（点悬浮条 ▶）开始时由 {@link #onStart()} 清掉。
     */
    public static void setPendingHint(String hint) {
        OverlayService s = INSTANCE;
        if (s != null && s.tvLog != null) {
            final OverlayService ss = s;
            final String hh = hint;
            ss.ui.post(() -> {
                ss.hintUntilStart = true;
                ss.hintText = hh;
                ss.setExpanded(true);
                ss.tvLog.setLine(hh, MarqueeView.STYLE_ACTION);
                AppLog.i("[准备] 悬浮条提醒 ⇒ " + hh);
            });
            pendingHint = null;              // 静态兜底也清掉（万一 INSTANCE 之后才挂上）
            return;
        }
        pendingHint = hint;
    }

    /** 提醒是否还挂着（挂起期间日志行不被动覆盖；真跑开始时清除） */
    private boolean hintUntilStart = false;
    private String hintText = null;

    private final Runnable poll = new Runnable() {
        @Override
        public void run() {
            String force = stateForce;
            if (force != null) {                        // dev 钩子：直接喂假状态
                final String fake = statusJsonFor(force);
                ui.post(() -> paint(fake));
                ui.postDelayed(this, 2500);
                return;
            }
            new Thread(() -> {
                String s;
                try {
                    s = PyBridge.call("status");
                } catch (Throwable t) {
                    s = "";
                }
                final String st = s;
                ui.post(() -> paint(st));
            }, "ovl-poll").start();
            ui.postDelayed(this, 2500);
        }
    };

    public static void start(Context ctx) {
        Intent i = new Intent(ctx, OverlayService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            // ⚠ 从广播/后台起服务必须走 startForegroundService（8.0+ 后台 startService 会被拒）
            ctx.startForegroundService(i);
        } else {
            ctx.startService(i);
        }
    }

    public static void stop(Context ctx) {
        ctx.stopService(new Intent(ctx, OverlayService.class));
    }

    /**
     * 悬浮条占的设备像素矩形（给 `FrameStore` 涂平用）；服务没跑/没显示 ⇒ null。
     * ⚠ 返回值**不要改**（共享数组）。
     */
    public static int[] blankRect() {
        return BLANK_RECT;
    }

    /** 供广播 `overlay_dump` 读当前状态（**服务可能没起** ⇒ 直接回 off） */
    public static String dump() {
        final OverlayService o = INSTANCE;
        if (o == null) {
            return "overlay: off（悬浮条没开）";
        }
        final String[] out = new String[1];
        final CountDownLatch latch = new CountDownLatch(1);
        o.ui.post(() -> {
            try {
                out[0] = o.dumpText();
            } catch (Throwable t) {
                out[0] = "overlay: dump 异常 " + t;
            } finally {
                latch.countDown();
            }
        });
        try {
            latch.await(1500, TimeUnit.MILLISECONDS);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
        String txt = out[0] == null ? "overlay: 读超时" : out[0];
        // ⭐ 再落一份文件：logcat 会把多行消息**合成一行**（长内容还会被截），
        //   要看完整内容（尤其"最近 N 条日志"）就走文件 →
        //   `adb shell cat /sdcard/Download/autoexplore/overlay_dump.txt`（同「导出截图」的目录）
        try {
            java.io.File dir = new java.io.File("/sdcard/Download/autoexplore");
            if (dir.exists() || dir.mkdirs()) {
                try (java.io.FileOutputStream fos = new java.io.FileOutputStream(
                        new java.io.File(dir, "overlay_dump.txt"))) {
                    fos.write(txt.getBytes(java.nio.charset.Charset.forName("UTF-8")));
                }
            }
        } catch (Throwable ignored) {
            // 没存储权限就算了，logcat 那条仍在
        }
        return txt;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        DeviceApi.bind(getApplicationContext());     // 顺带绑好 Python 桥（call 会自动起 Chaquopy）
        INSTANCE = this;
        wm = (WindowManager) getSystemService(WINDOW_SERVICE);
        buildView();
        foregroundize();
        // ⭐ 顺序要紧：**先灌历史、再订阅**
        //   反过来（先订阅再灌）会把 buildView/foregroundize 期间产生的行收两遍
        //   ⇒ 日志行里看到重复（2026-09-29 实测踩到）
        for (String s : AppLog.snapshot()) {
            onLog(s);
        }
        logListener = line -> ui.post(() -> onLog(line));
        AppLog.addListener(logListener);
        // ⭐ 2026-09-29 用户口径：界面点「▶ 准备启动」⇒ 悬浮条**展开**并用日志行提醒
        //   「到 选图界面 后点 ▶ 启动」，脚本不自动跑（真机游戏可能停在登录/大厅 ⇒ 自动跑会瞎跑）
        if (pendingHint != null) {
            String h = pendingHint;
            pendingHint = null;
            hintUntilStart = true;
            hintText = h;
            setExpanded(true);
            if (tvLog != null) {
                tvLog.setLine(h, MarqueeView.STYLE_ACTION);
            }
        }
        ui.post(poll);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        addBarOrWarn();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        ui.removeCallbacks(poll);
        ui.removeCallbacks(collapseIdle);
        if (logListener != null) {
            AppLog.removeListener(logListener);
            logListener = null;
        }
        if (INSTANCE == this) {
            INSTANCE = null;
        }
        BLANK_RECT = null;              // ⚠ 必须清：否则机器人会继续涂一块没有悬浮条的空白
        if (bar != null && bar.getParent() != null) {
            try {
                wm.removeView(bar);
            } catch (Throwable ignored) {
            }
        }
        AppLog.i("悬浮控制条已关闭");
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // ───────────────────────── UI ─────────────────────────

    private int dp(int v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                getResources().getDisplayMetrics()));
    }

    /** 一枚圆角小按钮（**只放符号/ASCII**，见类注释）；底色 drawable 存在 tag 里，方便改色 */
    private TextView chip(String text, int color) {
        TextView t = new TextView(this);
        t.setText(text);
        // ⚠ 字号走**参考系像素**（不是 sp）：两行布局后按钮行高度必须精确可控，
        //   否则换个密度就顶穿 1722（见 LOG_ROW_H_REF 的高度预算）
        t.setTextSize(TypedValue.COMPLEX_UNIT_PX, RefMapper.devLen(CHIP_TEXT_REF));
        t.setTextColor(color);
        t.setIncludeFontPadding(false);              // 去掉字体内边距（省高度）
        // ⚠ 按钮**不加粗**：用户 2026-09-29 明确「字大一点/黑体说的是**日志**的字体」⇒
        //   按钮保持原样（34 参考 px、常规字重），别顺手改
        int ph = dp(9), pv = RefMapper.devLen(CHIP_PAD_V_REF);
        t.setPadding(ph, pv, ph, pv);
        t.setSingleLine(true);
        GradientDrawable g = new GradientDrawable();
        g.setColor(CHIP_BG);
        g.setCornerRadius(dp(14));
        g.setStroke(dp(1), 0x66FFFFFF);
        t.setBackground(g);
        t.setTag(g);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        p.rightMargin = dp(6);
        t.setLayoutParams(p);
        return t;
    }

    /**
     * ⭐ **任何一下点击都给一次可见反馈**（底色闪一下蓝）。
     *
     * 起因：用户报"点开始没反应" —— 实际是点了（日志有），但**屏幕上什么变化都看不出来**
     * ⇒ 用户以为坏了。触屏上"没有即时反馈"≈"坏了"，这条必须补。
     */
    private void flash(TextView v) {
        GradientDrawable g = bgOf(v);
        if (g == null) {
            return;
        }
        g.setColor(CHIP_BG_TAP);
        ui.postDelayed(() -> applyBaseBg(v), 180);
    }

    private GradientDrawable bgOf(TextView v) {
        return (v != null && v.getTag() instanceof GradientDrawable)
                ? (GradientDrawable) v.getTag() : null;
    }

    /** 恢复该按钮的常态底色 */
    private void applyBaseBg(TextView v) {
        GradientDrawable g = bgOf(v);
        if (g == null) {
            return;
        }
        g.setColor(CHIP_BG);
    }

    private void buildView() {
        choiceIdx = Math.max(0, Math.min(MAP_LABELS.length - 1, Prefs.mapsChoice(this)));
        // ⚠ 先把屏幕尺寸喂给 RefMapper：`afterLayout` 要用它算"涂平矩形"（FrameStore 依赖），
        //   而第一次截图（toRef 会顺带设）可能还没发生 ⇒ 不设就按 1080×1920 算，非该分辨率会错
        android.util.DisplayMetrics dm = getResources().getDisplayMetrics();
        RefMapper.setScreen(dm.widthPixels, dm.heightPixels);

        // ── ① **两行**：上行 = 日志（整行、上下滚动），下行 = 按钮 ──
        //    用户口径 2026-09-29：「悬浮窗要在按钮上面。滚动方式是整行上下滚动，不是现在的左右」
        //    ⚠ 高度预算见 LOG_ROW_H_REF：日志 28 + 按钮 56 = 84 ⇒ 顶边 1732 ≥ 1722 ✓
        bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.VERTICAL);
        bar.setGravity(Gravity.START);

        // 下行：按钮（气泡 / 张数 / ▶ / ■ / ✕）
        btnRow = new LinearLayout(this);
        btnRow.setOrientation(LinearLayout.HORIZONTAL);
        btnRow.setGravity(Gravity.CENTER_VERTICAL);
        bar.addView(btnRow);

        bubble = chip("● MGAS", 0xFFAAAAAA);
        bubble.setOnClickListener(v -> {
            flash(bubble);
            AppLog.i("[ovl] 点气泡 → " + (expanded ? "收起" : "展开"));
            setExpanded(!expanded);
        });
        bubble.setOnLongClickListener(v -> {
            flash(bubble);
            // ⭐ 三态循环：自动(null) → 强制显示(TRUE) → 强制隐藏(FALSE) → 自动…
            //   ⚠ 以前写成 `(logForce != null && logForce) ? FALSE : TRUE` ⇒ 在 TRUE/FALSE 之间
            //   来回翻，**永远回不到"自动"**（和注释"再长按恢复自动"不符，2026-09-29 实测踩到）
            logForce = (logForce == null) ? Boolean.TRUE
                    : (logForce ? Boolean.FALSE : null);
            AppLog.i("[ovl] 长按气泡 ⇒ 日志行 " + (logForce == null ? "恢复自动（跟随运行状态）"
                    : (logForce ? "强制显示" : "强制隐藏")));
            applyMode();
            keepAlive();
            return true;
        });
        installDrag(bubble);
        btnRow.addView(bubble);

        btnCount = chip(MAP_LABELS[choiceIdx], 0xFFB0E0FF);
        btnCount.setOnClickListener(v -> {
            flash(btnCount);
            keepAlive();
            choiceIdx = (choiceIdx + 1) % MAP_LABELS.length;
            btnCount.setText(MAP_LABELS[choiceIdx]);
            Prefs.setMapsChoice(this, choiceIdx);       // 界面/下次启动都读同一份 ✓
            AppLog.i("[ovl] 点张数 ⇒ " + MAP_LABELS[choiceIdx]
                    + (choiceIdx == 0 ? "（约 " + STAMINA_PER_MAP + " 体力）"
                                      : "（一直刷到体力不够进图为止）"));
        });
        btnRow.addView(btnCount);

        btnStart = chip("▶", 0xFF8CFF9E);
        btnStart.setOnClickListener(v -> {
            flash(btnStart);
            keepAlive();
            AppLog.i("[ovl] 点 ▶ ⇒ 开始");
            onStart();
        });
        btnRow.addView(btnStart);

        btnStop = chip("■", 0xFFFF9E9E);
        btnStop.setOnClickListener(v -> {
            flash(btnStop);
            keepAlive();
            AppLog.i("[ovl] 点 ■ ⇒ 立刻停止（不等这张图打完）");
            new Thread(() -> AppLog.i("■ " + PyBridge.call("stop")), "ovl-stop").start();
        });
        btnRow.addView(btnStop);

        btnClose = chip("✕", 0xFFFFFFFF);
        btnClose.setOnClickListener(v -> {
            flash(btnClose);
            AppLog.i("[ovl] 点 ✕ ⇒ 收起");
            setExpanded(false);
        });
        btnRow.addView(btnClose);

        // ── ② 日志行（**在按钮上面**，整行全宽、自己画、上下滚动）──
        //    ⭐ 2026-09-29 用户口径：「要在按钮上面啊，并且是**黑色字**」
        //    ⇒ 给日志行铺一块**浅色底 + 黑字**：① 黑字必须配浅底才看得见（游戏底是深色）
        //      ② 浅底把这一行和身后的游戏/App 文字**分开**，一眼就是"按钮上方那一行是我的"
        tvLog = new MarqueeView(this);
        LinearLayout.LayoutParams lpl = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, RefMapper.devLen(LOG_ROW_H_REF));
        lpl.leftMargin = dp(2);
        tvLog.setLayoutParams(lpl);
        GradientDrawable lg = new GradientDrawable();
        lg.setColor(LOG_BG_COLOR);
        lg.setCornerRadius(dp(6));
        tvLog.setBackground(lg);
        tvLog.setPadding(dp(7), 0, dp(7), 0);
        tvLog.setOnClickListener(v -> cycleLogBack());
        tvLog.setOnLongClickListener(v -> {
            logBack = 0;
            applyLogText();
            keepAlive();
            return true;
        });
        bar.addView(tvLog, 0);          // ⭐ 插到第 0 行 ⇒ 日志在按钮**上方**

        lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                        ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                        : WindowManager.LayoutParams.TYPE_PHONE,
                // ⚠ 这里**不要**加 FLAG_SECURE（见硬约束②：MuMu 上会让整屏抓取直接失败）
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        // ⚠ Gravity.BOTTOM：lp.y 变成「离屏幕底的距离」⇒ 底边**恒定**，只横向生长
        lp.gravity = Gravity.BOTTOM | Gravity.START;
        lp.setTitle("MGAS");                         // 便于 `dumpsys window` 里认人
        lp.x = RefMapper.devX(20);
        lp.y = RefMapper.devY(BAR_BOTTOM_OFFSET_REF);
        AppLog.i("悬浮条底边钉在 参考 y=" + BAR_BOTTOM_REF + " ⇒ 设备偏移 (" + lp.x + "," + lp.y
                + ")  k=" + RefMapper.k() + "（两行/高度恒定 84，不碰棋盘与采样带）");

        // ⭐ 先按「收起态」摆好，**再** addView：
        //    这样窗口的第一次测量拿到的就是气泡宽度，不依赖"加窗后再 relayout"这件事
        //    （实测：addView 之后才 setVisibility(GONE)，首帧仍是展开的宽 ✗）
        applyMode();
        addBarOrWarn();
    }

    /** 加窗（失败时把"为什么"讲清楚——多半是少了「显示在其他应用上层」权限） */
    private void addBarOrWarn() {
        if (bar != null && bar.getParent() != null) {
            AppLog.i("[ovl] 悬浮条已在窗口里，跳过 addView");
            return;
        }
        if (!android.provider.Settings.canDrawOverlays(this)) {
            AppLog.i("⚠ 没有「显示在其他应用上层」权限 ⇒ 悬浮条加不上去。"
                    + "去 设置 → 应用 → 特殊权限 → 显示在其他应用上层，给「"
                    + getString(R.string.app_name) + "」放行");
            return;
        }
        try {
            wm.addView(bar, lp);
            AppLog.i("✓ 悬浮条已显示：左下角小气泡，点它展开 → ▶ 开始 / ■ 停止（可拖动）");
            bar.post(this::afterLayout);
        } catch (Throwable t) {
            AppLog.i("⚠ 悬浮窗添加失败：" + t);
        }
    }

    /**
     * 布局稳定后：① 发布"涂平矩形"（硬约束③）② 量几何是否越界（硬约束①）
     * ③ ⭐ **自愈**：顶边一旦高过棋盘下沿（BOARD_Y1_REF）就把窗口往下推回去
     */
    private void afterLayout() {
        if (bar == null || lp == null || bar.getWidth() <= 0 || bar.getHeight() <= 0) {
            return;
        }
        int sw = RefMapper.screenW(), sh = RefMapper.screenH();
        barMaxH = Math.max(barMaxH, bar.getHeight());
        barMaxW = Math.max(barMaxW, bar.getWidth());
        // ⭐⭐ 自愈兜底（2026-09-29 实测踩到）：拖动夹子是按**当时**高度算的
        //   —— 收起态 bh=56 时夹在 lp.y≤142（顶边正好 1722），可**一展开** bh 变 84
        //   ⇒ 顶边掉到 1694，又把棋盘最低一行盖住（涂平抹掉 ⇒ 识别错 + 点不动）。
        //   所以这里不依赖"拖动时算对"：只要顶边越界就改 lp.y 把它推回去（幂等，改完再走一次）。
        int bottomPx = sh - lp.y;
        if (bottomPx - bar.getHeight() < RefMapper.devY(BOARD_Y1_REF)) {
            int fixed = Math.max(0, sh - bar.getHeight() - RefMapper.devY(BOARD_Y1_REF));
            if (lp.y != fixed) {
                lp.y = fixed;
                AppLog.i("[ovl] 顶边越界 ⇒ 自愈回推：离底 " + fixed
                        + "（顶边钉回 参考 y=" + BOARD_Y1_REF + "）");
                try {
                    wm.updateViewLayout(bar, lp);
                } catch (Throwable ignored) {
                }
                // ⚠ **不能 return**：下面那段才是发"涂平矩形"的地方，直接走会把 BLANK_RECT
                //   停在旧几何（收起 209x56）⇒ 悬浮条右半边和下沿漏进截图被识别
                //   （2026-09-29 实测：自愈后 blankRect=[20,1722][229,1778]，而条子实际 960x84）
            }
        }
        int l = Math.max(0, lp.x);
        int r = Math.min(sw, lp.x + bar.getWidth());
        int b = Math.min(sh, sh - lp.y);
        int t = Math.max(0, b - bar.getHeight());
        BLANK_RECT = (r > l && b > t) ? new int[]{l, t, r, b} : null;

        float topRef = RefMapper.refY(t);
        float bottomRef = RefMapper.refY(b);
        // ⚠ 设备高度→参考高度要用 refPerDev()（=1/kx）；旧代码误用 k()（=kx，方向反了），
        //   1080×1920 上两者都是 1 所以从没暴露（2026-09-29 修）
        float hRef = bar.getHeight() * RefMapper.refPerDev();
        AppLog.i("[ovl] bar 设备 " + bar.getWidth() + "x" + bar.getHeight()
                + "（参考高 " + Math.round(hRef) + "）占 参考 y " + Math.round(topRef)
                + "~" + Math.round(bottomRef) + " 展开=" + expanded
                + " 日志=" + logMode + " 涂平=" + (BLANK_RECT == null ? "无" : "有")
                + " 设备屏 " + sw + "x" + sh);
        if (topRef < BOARD_Y1_REF) {
            AppLog.i("⚠⚠ 悬浮条顶边 参考 y=" + Math.round(topRef) + " 越过了棋盘下沿 "
                    + BOARD_Y1_REF + " ⇒ 会盖住最低一行格子（识别错 + 那几格点不动）！"
                    + " 请调小 LOG_ROW_H_REF / CHIP_TEXT_REF（高度预算见类注释硬约束①）");
        }
    }

    /** 运行中？（用状态灯那一套判据，别另起一套） */
    private boolean isRunningState() {
        return "run".equals(lastState) || "lock".equals(lastState) || "err".equals(lastState);
    }

    /** 按「运行状态 + 手动覆盖」决定这一排显示什么 */
    private void applyMode() {
        if (bar == null) {
            return;
        }
        boolean wantLog = (logForce != null) ? logForce : isRunningState();
        logMode = wantLog;
        int vis = expanded ? View.VISIBLE : View.GONE;
        // 上行：日志行只在展开时露脸（收起态只留气泡，条子最矮）
        tvLog.setVisibility(expanded ? View.VISIBLE : View.GONE);
        // 下行：张数/▶ 只在"空闲且展开"时露脸；跑起来就把位置让给日志
        int busyVis = (expanded && !wantLog) ? View.VISIBLE : View.GONE;
        btnCount.setVisibility(busyVis);
        btnStart.setVisibility(busyVis);
        btnStop.setVisibility(vis);
        btnClose.setVisibility(vis);
        if (!wantLog && expanded) {
            tvLog.showActionOnly();
        }
        bar.post(this::afterLayout);
    }

    private void setExpanded(boolean ex) {
        if (bar != null && expanded == ex) {
            if (ex) {
                keepAlive();
            }
            return;
        }
        expanded = ex;
        if (!ex) {
            ui.removeCallbacks(collapseIdle);
        }
        applyMode();
        if (ex) {
            AppLog.i("[ovl] 展开（两行：上行=当前行动，下行=按钮）");
            keepAlive();
        }
    }

    // ───────────────────────── 日志行 ─────────────────────────

    /** AppLog 每来一条就走这里（**已回到主线程**，见 onCreate 的 listener） */
    private void onLog(String line) {
        if (line == null) {
            return;
        }
        String s = sanitize(line);
        if (s.isEmpty()) {
            return;
        }
        logBuf.addLast(s);
        while (logBuf.size() > LOG_KEEP) {
            logBuf.removeFirst();
        }
        if (logBack > logBuf.size()) {
            logBack = logBuf.size();
        }
        // ⭐ "当前的行动" = 从这条日志翻译出来的一句人话；翻译不出来（噪声/大 JSON）就沿用上一条
        String act = describeAction(line);
        if (act != null && logBack == 0) {
            action = act;
        }
        if (logBack == 0) {
            applyLogText();
        }
    }

    /**
     * 硬约束③的双保险：把**会被当成游戏面板关键词**的字换掉，
     * 顺手把多行压成一行（日志行只有一行高）、去掉 PC 日志的前导缩进。
     */
    private String sanitize(String raw) {
        String s = raw.replace('\r', ' ').replace('\n', ' ');
        int i = 0;
        while (i < s.length() && (s.charAt(i) == ' ' || s.charAt(i) == '\t')) {
            i++;
        }
        s = s.substring(i);
        for (String k : OCR_KEYWORDS) {
            s = s.replace(k, "▓");
        }
        if (s.length() > LOG_MAX_CHARS) {
            s = s.substring(0, LOG_MAX_CHARS) + "…";
        }
        return s.trim();
    }

    // ── 「当前的行动」翻译层 ──────────────────────────────────────
    // 用户要求："最好文字播放的是当前的行动"。循环的原始日志有两大类：
    //   · 人话行：`== 第 1 张图 ==   进图前体力 1377`、`board：35 格真识别（…）`、`本图结束：done（耗时 62 秒）`
    //   · 机器行：`{'enter': 'in_map', 'stamina': 1353}`、`{'solver': 'ok', 'cost': 9, ...}`
    // 直接播原始行既难看（多行会被 logcat/文本流拆开）又占宽度，所以翻成短句。
    // 翻不出来（自己的噪声行、超大 JSON、闲话）就返回 null，日志行沿用上一条行动。

    /** 浮条/调试自己打的噪声行：不进"当前行动" */
    private static boolean isNoise(String s) {
        return s.startsWith("[ovl]") || s.startsWith("[overlay_") || s.startsWith("收到广播命令")
                || s.startsWith("[py") || s.startsWith("[summary]") || s.startsWith("[selftest]")
                || s.startsWith("[classify]") || s.startsWith("[red_") || s.startsWith("[explore_")
                || s.startsWith("悬浮条") || s.startsWith("✓ 悬浮条") || s.startsWith("悬浮控制条");
    }

    /** 一行里撞上几个 OCR 关键词（≥3 ⇒ 是整屏 OCR 词表 dump，不是行动） */
    private static int ocrKeywordHits(String s) {
        int n = 0;
        for (String k : OCR_KEYWORDS) {
            if (s.contains(k)) {
                n++;
            }
        }
        return n;
    }

    /** 取出 `key` 后面紧跟的值（到 `,`/`}`/`)` 为止）；取不到返回 null */
    private static String val(String s, String key) {
        int i = s.indexOf(key);
        if (i < 0) {
            return null;
        }
        i += key.length();
        // ⚠ 必须跳过 `: ` 分隔符 —— 漏了这步会把 `'win': True` 取成 `": True"`，
        //   于是 `"True".equalsIgnoreCase(": True")` 为假 ⇒ **胜负判反**（2026-09-29 实测踩到）
        while (i < s.length() && (s.charAt(i) == ':' || s.charAt(i) == ' ')) {
            i++;
        }
        int j = i;
        while (j < s.length() && s.charAt(j) != ',' && s.charAt(j) != '}' && s.charAt(j) != ')') {
            j++;
        }
        String v = s.substring(i, j).trim();
        if (v.length() > 1 && (v.charAt(0) == '\'' || v.charAt(0) == '"')) {
            v = v.substring(1);
            if (v.endsWith("'") || v.endsWith("\"")) {
                v = v.substring(0, v.length() - 1);
            }
        }
        return v.isEmpty() ? null : v;
    }

    /** `numBefore` 的限定版：只从 `fromKey` 之后开始找 */
    private static String numBeforeAfter(String s, String fromKey, String unit) {
        int k = s.indexOf(fromKey);
        if (k < 0) {
            return null;
        }
        return numBefore(s.substring(k + fromKey.length()), unit);
    }

    /** 取出 `unit` 前面那串数字（形如 `耗时 62 秒` → `62`）；取不到返回 null */
    private static String numBefore(String s, String unit) {
        int i = s.indexOf(unit);
        while (i >= 0) {
            int a = i;
            while (a > 0 && (Character.isDigit(s.charAt(a - 1)) || s.charAt(a - 1) == ' ')) {
                a--;
            }
            String n = s.substring(a, i).trim();
            if (!n.isEmpty()) {
                return n;
            }
            i = s.indexOf(unit, i + unit.length());
        }
        return null;
    }

    /** 把一条原始日志翻成"当前行动"；返回 null = 这条不值得当行动播报 */
    private static String describeAction(String raw) {
        if (raw == null || raw.isEmpty()) {
            return null;
        }
        String s = raw.trim();
        if (isNoise(s)) {
            return null;
        }
        // ⭐ 「整屏 OCR 词表 dump 行」不是行动：循环把识别到的所有面板文字打进日志
        //   （`关闭 探索 开始冒险 进入地图 一键派遣 探索配队 探索产出 派遣 领取`），
        //   里面必然含「派遣 / 探索 / 关闭」⇒ 会被下面的规则误判成"紫金地块 ⇒ 派遣"（2026-09-29 实测踩到）。
        //   判据：一行里撞上 ≥3 个 OCR 关键词 ⇒ 是面板词表。真实行动行最多撞 2 个
        //   （`发现 N 块紫/橙探索地块 … ⇒ 去探索+派遣` = 探索/派遣）。
        if (ocrKeywordHits(s) >= 3) {
            return null;
        }
        // ── 危险/收尾类（最高优先级，必须看得见）──
        if (s.contains("red_equip") || s.contains("红装")) {
            return "⛔ 发现红装 ⇒ 已停下（去界面点「红装解锁」再开跑）";
        }
        if (s.contains("体力不够") || s.contains("体力不足") || s.contains("不够进图")) {
            return "体力不够进图 ⇒ 收工";
        }
        if (s.contains("全部结束")) {
            String secs = numBeforeAfter(s, "全部结束", "秒");
            return "全部结束" + (secs == null ? "" : "（共 " + secs + " 秒）");
        }
        if (s.contains("补给")) {
            return "没体力 ⇒ 用「结实补给」";
        }
        if (s.contains("一键升级") || s.contains("升星")) {
            return "背包：装备一键升星";
        }
        // ── 紫/橙探索地块（俗称"紫金地块"）──
        // ⚠ 不能用 `s.contains("派遣")` 兜：整屏 OCR 词表里就有「派遣/一键派遣」⇒ 已在上面的
        //   `ocrKeywordHits>=3` 里拦掉；这里再要求**完整的真日志文案**（见 explore_loop.py）
        if (s.contains("紫/橙探索地块") || s.contains("紫橙探索地块")) {
            return s.contains("槽已满")
                    ? "紫/橙探索地块 ⇒ 探索槽已满，改战斗"
                    : "紫/橙探索地块 ⇒ 去探索 + 派遣";
        }
        if (s.contains("已派遣")) {
            return "已派遣一支探索队 ✓";
        }
        if (s.contains("探索槽已满") || s.contains("三槽全满")) {
            return "探索槽已满 ⇒ 不派遣，关掉面板";
        }
        // ── 流程类 ──
        int k = s.indexOf("第");
        if (k >= 0 && s.contains("张图")) {
            int e = s.indexOf("张图");
            String n = s.substring(k + 1, e).trim();
            String st = val(s, "进图前体力");
            if (st == null) {
                st = val(s, "体力");
            }
            return "第 " + n + " 张图 · 准备进图" + (st == null ? "" : "（体力 " + st + "）");
        }
        String enter = val(s, "'enter'");
        if ("in_map".equals(enter)) {
            String st = val(s, "'stamina'");
            return "已进图" + (st == null ? "" : "（体力 " + st + "）") + " · 正在读棋盘";
        }
        if ("clicked".equals(enter)) {
            return "点「进入地图」中…";
        }
        if (s.contains("fog_wait")) {
            return "等暗罩/雾退去…";
        }
        if (s.contains("'shot'") || s.contains("shot")) {
            String f = val(s, "'file'");
            return "已存棋盘截图" + (f == null ? "" : " " + f);
        }
        String solver = val(s, "'solver'");
        if ("ok".equals(solver)) {
            String cost = val(s, "'cost'");
            String steps = val(s, "'steps'");
            String tg = val(s, "'targets'");
            return "规划完成：cost " + cost + " / " + steps + " 步 / 目标 " + tg;
        }
        if (solver != null) {
            return "规划 " + solver + " ⇒ 换策略重算";
        }
        if (s.contains("'round'")) {
            // ⚠ `round` 是**0 基**的，直接播 "第 0 轮" 会让人以为出错了 ⇒ 只播体力
            String st = val(s, "'stamina'");
            return "读棋盘" + (st == null ? "…" : "（体力 " + st + "）");
        }
        if (s.contains("'battle'")) {
            String win = val(s, "'win'");
            if (s.contains("started")) {
                return "战斗中…";
            }
            if (win != null) {
                return "战斗结束：" + ("True".equalsIgnoreCase(win) ? "胜" : "负");
            }
            return "战斗结束";
        }
        if (s.contains("board：") || s.contains("格真识别")) {
            // 形如 `board：35 格真识别（草地/营地/…）` —— 数字和「格」之间可能有空格 ✓
            int b = s.indexOf("格真识别");
            if (b > 0) {
                int a = b;
                while (a > 0 && (Character.isDigit(s.charAt(a - 1)) || s.charAt(a - 1) == ' ')) {
                    a--;
                }
                String n = s.substring(a, b).trim();
                return "识别棋盘：" + (n.isEmpty() ? "?" : n) + " 格";
            }
            return "识别棋盘…";
        }
        if (s.contains("本图结束")) {
            String secs = numBefore(s, "秒");
            return "本图结束：" + (s.contains("done") ? "完成" : "结束")
                    + (secs == null ? "" : "（" + secs + " 秒）");
        }
        if (s.contains("'pre'") && s.contains("menu")) {
            return "在大厅/菜单 · 准备进图";
        }
        if (s.contains("Android 探索启动")) {
            return s.replace("▶ ", "");
        }
        // ── 兜底：短的人话行照播，长 JSON / 看不懂的不播 ──
        if (s.length() <= 46 && s.indexOf('{') < 0) {
            return s;
        }
        return null;
    }

    /** 点日志行：0（跟随最新）→ 1（上一条）→ … → 最老 → 回到 0 */
    private void cycleLogBack() {
        if (logBuf.isEmpty()) {
            return;
        }
        keepAlive();
        logBack = (logBack + 1) % (logBuf.size() + 1);
        applyLogText();
    }

    /** 把"当前该显示的那一句"交给跑马灯 */
    private void applyLogText() {
        if (tvLog == null) {
            return;
        }
        // ⭐ 「准备启动」提醒挂起期间：日志行固定显示提醒，不被别的日志刷掉（点 ▶ 启动时清除）
        if (hintUntilStart && hintText != null) {
            tvLog.setLine(hintText, MarqueeView.STYLE_ACTION);
            return;
        }
        if (logBack == 0) {
            tvLog.setLine(action, MarqueeView.STYLE_ACTION);
        } else {
            tvLog.setLine("↺" + logBack + " " + nthFromEnd(logBack), MarqueeView.STYLE_HISTORY);
        }
    }

    /** 从尾部数第 n 条（n 已保证 ≤ size） */
    private String nthFromEnd(int n) {
        Iterator<String> it = logBuf.descendingIterator();
        String cur = "";
        for (int i = 0; i < n && it.hasNext(); i++) {
            cur = it.next();
        }
        return cur;
    }

    // ───────────────────────── 动作 ─────────────────────────

    /** ▶ **点一下直接开跑**（无二次确认/倒计时；防误触靠 张数 限幅 + ■ 随时停） */
    private void onStart() {
        hintUntilStart = false;              // ⭐ 真跑开始 ⇒ 撤掉「准备启动」提醒
        hintText = null;
        // ⭐⭐ **先给反馈、再干活**：不管后面是"没截图权限"还是"无障碍没开"，用户点完必须
        //   立刻看到"跑起来的样子"（条子展开 + 切日志行 + 状态灯），失败原因写在日志行里。
        //   否则点了 ▶ 条子没反应 ⇒ 用户以为按钮坏了（2026-09-29 用户原话：
        //   "运行后图标变绿也要能看到，现在直接收起看不到了"）。
        setExpanded(true);
        logForce = null;                 // 交回自动：运行中必然显示日志
        applyMode();
        keepAlive();
        if (!FrameStore.has()) {
            AppLog.i("还没有截图权限 ⇒ 拉起授权界面，授完再点 ▶");
            Intent i = new Intent(this, MainActivity.class);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            i.putExtra("cmd", "capture");
            startActivity(i);
            return;
        }
        if (!AutoTouchService.ready()) {
            AppLog.i("无障碍服务没开 ⇒ 打开设置页（开了手势才能生效）");
            Intent i = new Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
            return;
        }
        // ⭐ v0.26 保险：悬浮窗权限没给就不启动（正常到不了这——服务能跑=权限在），
        //   用户口径：没授权截图/无障碍/悬浮窗 **一律不准启动**
        if (!android.provider.Settings.canDrawOverlays(this)) {
            AppLog.i("悬浮窗权限没给 ⇒ 打开授权页（授完再点 ▶）");
            Intent i = new Intent(android.provider.Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    android.net.Uri.parse("package:" + getPackageName()));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
            return;
        }
        // ⭐ 张数/补给/升星 都从界面上的设置读（界面勾了这里就生效 ✓ 不会"勾了没反应"）
        final int maps = (choiceIdx == 1) ? MAPS_CONTINUOUS : 1;
        final int bagEvery = Prefs.bagEvery(this);
        final boolean autoSupply = Prefs.autoSupply(this);
        AppLog.i("▶ 启动探索：" + MAP_LABELS[choiceIdx]
                + "（maps=" + maps + "，进图 " + STAMINA_PER_MAP + " 体力/张）"
                + "  自动补给=" + autoSupply + "  升星=每 " + bagEvery + " 张");
        new Thread(() -> {
            // ⭐ v0.26（用户口径）：**悬浮条 ▶ 不再自动切游戏前台**。
            //   正常流程 = 在 MGAS 点「▶ 准备启动」（那里负责切游戏 + 提醒）→ 人在游戏选图
            //   界面 → 点悬浮条 ▶ 开跑；此时再切一次纯属多余。
            //   若人不在游戏（比如停在 MGAS 界面）⇒ Python `self_ui_hits()` 防护会判出
            //   "画面是 MGAS 自己" 并明确报错（不会乱点）⇒ 切回游戏再点 ▶ 即可。
            // ⚠ 参数顺序必须与 explore_android.start 的形参一致（**10 个位置参数**）：
            //   maps, max_round, deadline, min_stamina, tag, opt_solver,
            //   bag_every, save_first, stop_at_5am, auto_supply
            String r = PyBridge.call("start", maps, 45, 900, 25, "", true,
                    bagEvery, true, false, autoSupply);
            AppLog.i("▶ " + r);
        }, "ovl-start").start();
    }

    /**
     * 拖动手柄（气泡）：左右上下随便放，避免挡住游戏里的点击点。
     * ⚠ `Gravity.BOTTOM` ⇒ `lp.y` 是**离屏幕底的距离**：手指往下 `dy>0` ⇒ y **变小**。
     */
    private void installDrag(View handle) {
        handle.setOnTouchListener(new View.OnTouchListener() {
            private int downX, downY;
            private float rawX, rawY;
            private boolean moved;

            @Override
            public boolean onTouch(View v, MotionEvent e) {
                switch (e.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        downX = lp.x;
                        downY = lp.y;
                        rawX = e.getRawX();
                        rawY = e.getRawY();
                        moved = false;
                        return false;       // 交回 click（可点视图自己会吃掉 DOWN ⇒ 后续 MOVE 照样送到这）
                    case MotionEvent.ACTION_MOVE: {
                        int dx = (int) (e.getRawX() - rawX);
                        int dy = (int) (e.getRawY() - rawY);
                        if (Math.abs(dx) > dp(6) || Math.abs(dy) > dp(6)) {
                            moved = true;
                        }
                        if (moved) {
                            int sw = RefMapper.screenW(), sh = RefMapper.screenH();
                            int bw = Math.max(barMaxW, bar != null ? bar.getWidth() : 0);
                            if (bw <= 0) {
                                bw = dp(64);
                            }
                            // ⚠ 竖直用**见过的高度的最大值**（不是当前高度）：收起态 56 时若按 56 夹，
                            //   一展开成 84 顶边就掉到 1694（afterLayout 里还有一道自愈兜底）
                            int bh = Math.max(barMaxH, bar != null ? bar.getHeight() : 0);
                            if (bh <= 0) {
                                bh = dp(64);
                            }
                            lp.x = Math.max(0, Math.min(Math.max(0, sw - bw), downX + dx));
                            // ⭐⭐ 竖直方向**夹住**：顶边绝不允许高过棋盘下沿（BOARD_Y1_REF）
                            //   —— 涂平会把悬浮条那块**抹成纯色**：盖住棋盘 ⇒ 那几格既识别不到
                            //   也点不动（2026-09-29 实测被拖到参考 y 422~499，整段画面被抹掉）。
                            //   水平方向不限制（在底部那条空档里左右挪是安全的）。
                            //   `Gravity.BOTTOM` ⇒ lp.y 是"离底距离"：top = sh − lp.y − bh ≥ devY(1722)
                            int safeBottom = Math.max(0, sh - bh - RefMapper.devY(BOARD_Y1_REF));
                            lp.y = Math.max(0, Math.min(safeBottom, downY - dy));
                            try {
                                wm.updateViewLayout(bar, lp);
                            } catch (Throwable ignored) {
                            }
                            bar.post(OverlayService.this::afterLayout);   // 涂平矩形跟着走 ✓
                        }
                        return moved;
                    }
                    default:
                        return moved;
                }
            }
        });
    }

    /** 把游戏切到前台（探索循环截图/点击的对象必须是游戏） */
    private String bringGameFront() {
        try {
            Intent li = getPackageManager().getLaunchIntentForPackage(GAME_PKG);
            if (li == null) {
                return "⚠ 没找到游戏包 " + GAME_PKG + " ⇒ 请手动切回游戏";
            }
            li.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
            startActivity(li);
            return "已切回游戏";
        } catch (Throwable t) {
            return "⚠ 切游戏失败（" + t + "）⇒ 请手动切回游戏";
        }
    }

    /**
     * 更新状态灯 + 切换显示模式。
     * ⚠ **只在状态真的变了才碰 View**：这个窗口会被一起截进去，若每 2.5 秒闪一次，
     *   循环里那些"等画面稳定"的调用可能会被自己干扰。
     */
    private void paint(String status) {
        if (bubble == null) {
            return;
        }
        String st = "idle";
        if (status != null && status.contains("'red_locked': True")) {
            st = "lock";                    // 上次发现红装还没处理 ⇒ 拒绝开跑，得先解锁
        } else if (status != null && status.contains("'running': True")) {
            st = "run";
        } else if (status != null && status.contains("'result': 'error'")) {
            st = "err";
        }
        if (st.equals(lastState)) {
            return;
        }
        // ⭐ 2026-09-29 用户口径：「停止后悬浮窗状态没回到最初的连刷，启动那个界面」
        //   一轮结束转回空闲 ⇒ 长按强开/强关的日志行**交回自动**、往回翻归零
        //   ⇒ 悬浮条恢复成启动前的样子（● MGAS + 连刷/▶/■/✕）
        //   （长按误触在真机上很容易发生：拖动起步 500ms 内没动 6dp 就会触发长按）
        if ("idle".equals(st) && lastState != null) {
            logForce = null;
            logBack = 0;
            applyLogText();
        }
        lastState = st;
        int color;
        if ("run".equals(st)) {
            color = 0xFF66FF88;
            bubble.setText("▶ MGAS");          // 绿 = 跑起来了
        } else if ("lock".equals(st)) {
            color = 0xFFFF4D4D;
            bubble.setText("⛔ MGAS");        // 红 = 红装锁（去界面点「红装解锁」）
        } else if ("err".equals(st)) {
            color = 0xFFFF6B6B;
            bubble.setText("! MGAS");          // 红 = 出错（去界面看日志）
        } else {
            color = 0xFFAAAAAA;
            bubble.setText("● MGAS");          // 灰 = 空闲
        }
        bubble.setTextColor(color);
        applyMode();                           // ⭐ 运行 ⇒ 自动把宽度让给日志行
    }

    // ───────────────────────── 自检输出（广播 overlay_dump）─────────────────────────

    private String dumpText() {
        StringBuilder sb = new StringBuilder();
        sb.append("overlay: on\n");
        sb.append("expanded: ").append(expanded).append("  logMode: ").append(logMode)
                .append("  logForce: ").append(logForce).append("  state: ").append(lastState).append('\n');
        sb.append("stateForce: ").append(stateForce == null ? "-（跟随真实）" : stateForce).append('\n');
        sb.append("frame: ").append(FrameStore.has() ? "有（截图权限已授）" : "无（截图权限未授 ⇒ 点 ▶ 只会拉授权框，零体力）").append('\n');
        sb.append("secure: ").append(lp != null
                && (lp.flags & WindowManager.LayoutParams.FLAG_SECURE) != 0)
                .append("（必须是 false，见硬约束②）\n");
        sb.append("gravity: ").append(lp == null ? "-" : String.valueOf(lp.gravity)).append('\n');
        sb.append("xy(dev,离底): ").append(lp == null ? "-" : (lp.x + "," + lp.y)).append('\n');
        sb.append("k: ").append(fmt(RefMapper.k())).append("  设备屏 ")
                .append(RefMapper.screenW()).append('x').append(RefMapper.screenH()).append('\n');
        sb.append("bubble: ").append(bubble == null ? "-" : bubble.getText()).append('\n');
        if (bar != null && lp != null && bar.getHeight() > 0) {
            int t = RefMapper.screenH() - lp.y - bar.getHeight();
            sb.append("bar(dev): ").append(bar.getWidth()).append('x').append(bar.getHeight())
                    .append("  ⇒ 顶边(参考 y)=").append(Math.round(RefMapper.refY(t)))
                    .append(" 底边(参考 y)=").append(Math.round(RefMapper.refY(RefMapper.screenH() - lp.y)))
                    .append("  （顶边必须 ≥ ").append(BOARD_Y1_REF).append("）\n");
        }
        int[] r = BLANK_RECT;
        sb.append("blankRect(dev): ").append(r == null ? "无（悬浮条没显示）"
                : ("[" + r[0] + "," + r[1] + "][" + r[2] + "," + r[3] + "]")).append('\n');
        if (tvLog != null) {
            sb.append("logW(dev): ").append(tvLog.getWidth()).append('\n');
            sb.append("logShown: ").append(tvLog.shownText()).append('\n');
            sb.append("logRoll: ").append(tvLog.debugRoll()).append('\n');
        }
        sb.append("action: ").append(action).append('\n');
        sb.append("logBack: ").append(logBack).append("  buf=").append(logBuf.size()).append('\n');
        List<String> tail = new ArrayList<>(logBuf);
        int from = Math.max(0, tail.size() - 12);
        sb.append("--- 最近 ").append(tail.size() - from)
                .append(" 条（原始 → 当前行动翻译）---\n");
        for (int i = from; i < tail.size(); i++) {
            String raw = tail.get(i);
            String act = describeAction(raw);
            sb.append("  ").append(raw).append('\n');
            sb.append("    → ").append(act == null ? "（不播报，沿用上一条）" : act).append('\n');
        }
        return sb.toString();
    }

    private static String fmt(float v) {
        return String.format(java.util.Locale.US, "%.4f", v);
    }

    private void foregroundize() {
        // ① 先把通知造出来（造失败就直接放弃转前台：悬浮窗本身不依赖前台服务）
        Notification n;
        try {
            NotificationManager nm =
                    (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                    && nm.getNotificationChannel(CHAN) == null) {
                nm.createNotificationChannel(new NotificationChannel(CHAN, "MGAS",
                        NotificationManager.IMPORTANCE_LOW));
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                n = new Notification.Builder(this, CHAN)
                        .setContentTitle("MGAS · 自动探索")
                        .setContentText("悬浮控制条运行中（点「MGAS」展开，可拖动）")
                        .setSmallIcon(android.R.drawable.ic_menu_compass)
                        .build();
            } else {
                n = new Notification.Builder(this)
                        .setContentTitle("MGAS · 自动探索")
                        .setContentText("悬浮控制条运行中")
                        .setSmallIcon(android.R.drawable.ic_menu_compass)
                        .build();
            }
        } catch (Throwable t) {
            AppLog.i("（提示）通知构造失败，跳过前台服务：" + t);
            return;
        }
        // ② 带类型转前台（Android 14 起 specialUse 必须显式声明类型），失败退回普通前台
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(NOTIF_ID, n);
            }
        } catch (Throwable t) {
            AppLog.i("（提示）带类型的前台服务失败，退回普通前台服务：" + t);
            try {
                startForeground(NOTIF_ID, n);
            } catch (Throwable t2) {
                // ⚠ 起不来前台服务不影响悬浮窗本身（同进程里 CaptureService 通常已是前台服务）
                AppLog.i("（提示）悬浮条没能转前台服务：" + t2);
            }
        }
    }

    // ───────────────────────── 自绘跑马灯 ─────────────────────────

    /**
     * 单行**整行上下滚动**的日志行（自绘）。
     *
     * 用户口径（2026-09-29）：
     *   · 「文字要一行一行飘」→ 新的一句要**动**着进来，不能硬切
     *   · 「滚动方式是整行上下滚动，不是现在的左右」→ **上下**滚（旧版是左右跑马灯）
     *   · 「悬浮窗要在按钮上面」→ 本 View 是悬浮条的第一行（见 buildView）
     *
     * 实现 = `roll` 0→1 的进度插值：
     *   · 上一句：从原位**向上移出**（`y − h·roll`）
     *   · 新一句：从下方**推上来**（`y + h·(1−roll)`）
     * 两句都画在本 View 的裁剪区里 ⇒ 视觉上就是整行向上滚，而且**永远只占一行高**
     * （高度恒定 ⇒ 涂平矩形与几何不随内容变化）。
     *
     * ⚠ 不再做左右滚动：装不下的句子用**省略号**收尾（整行全宽 ≈ 48 字，行动播报够用）。
     * ⚠ 静置时**完全不动**（不 invalidate）—— 否则 `wait_stable` 永远等不到"画面不变"。
     */
    static final class MarqueeView extends View {

        static final int STYLE_ACTION = 0;      // 当前行动（浅蓝）
        static final int STYLE_HISTORY = 1;     // 往回翻出来的原始日志（琥珀）

        private static final int FRAME_MS = 33;         // ~30fps
        private static final float ROLL_STEP = 0.09f;   // 每帧进度 ⇒ 约 11 帧(0.36s)滚完一句
        /** ⭐ 等宽（**常规字重**，不加粗 —— 2026-09-29 用户口径「悬浮窗黑色字别加粗啊」） */
        private static final android.graphics.Typeface LOG_TF = android.graphics.Typeface.MONOSPACE;

        private final TextPaint paint = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        /** 当前这一句 */
        private String text = "";
        private int style = STYLE_ACTION;
        /** 上一句（滚动期间向上移出；滚完置 null） */
        private String prev = null;
        private int prevStyle = STYLE_ACTION;
        /** 滚动进度：0 = 刚开始（新句还在下方），1 = 就位 */
        private float roll = 1f;
        /** 省略号处理后的实际绘制串（只在 setLine / 宽度变化时算一次） */
        private String drawn = "";
        private String drawnPrev = "";
        private int lastW = -1;

        MarqueeView(Context c) {
            super(c);
            paint.setTypeface(LOG_TF);
            setWillNotDraw(false);
            syncMetrics();
        }

        /** 字号跟着参考系走（每次量/画前同步一次，避免构造时 RefMapper 还没就绪） */
        private void syncMetrics() {
            paint.setTextSize(RefMapper.devLen(LOG_TEXT_REF));
            paint.setTypeface(LOG_TF);          // ⭐ 黑体（加粗等宽）——用户口径
        }

        /**
         * ⚠ 必须自己实现：裸 {@link View} 在 `WRAP_CONTENT` 高度下会按 `getDefaultSize`
         * 返回**可用高度**（= 整屏 1920）⇒ 把整个悬浮条撑成全屏
         * （2026-09-29 实测 `bar(dev): 1080x1920`、涂平矩形变成半个屏幕）。
         * 宽度按 `MATCH_PARENT`（整行铺满），高度取上边给的固定值（`LOG_ROW_H_REF`）。
         */
        @Override
        protected void onMeasure(int widthSpec, int heightSpec) {
            syncMetrics();
            ViewGroup.LayoutParams p = getLayoutParams();
            boolean fill = p != null && p.width == LinearLayout.LayoutParams.MATCH_PARENT;
            int avail = MeasureSpec.getSize(widthSpec);
            int w = fill ? avail : Math.min(avail, (int) Math.ceil(textWidth()));
            int h = (p != null && p.height > 0)
                    ? p.height : (int) Math.ceil(paint.descent() - paint.ascent());
            setMeasuredDimension(w, resolveSize(h, heightSpec));
        }

        void setLine(String t, int st) {
            String nt = t == null ? "" : t;
            if (nt.equals(text) && st == style) {
                return;
            }
            prev = text.isEmpty() ? null : text;    // 空串不算"上一句"
            prevStyle = style;
            text = nt;
            style = st;
            roll = 0f;                              // ⭐ 从下方推上来 ⇒「整行上下滚动」
            remeasure();
            invalidate();
            kick();
        }

        /** 只看当前行动（着色用） */
        void showActionOnly() {
            style = STYLE_ACTION;
            invalidate();
        }

        String shownText() {
            return text;
        }

        String debugRoll() {
            return "roll=" + fmt(roll)
                    + " 本句=" + text.length() + "字/" + Math.round(paintWidth(drawn)) + "px"
                    + " 视口=" + Math.round(viewW()) + "px"
                    + " 行高=" + getHeight()
                    + " 上一句=" + (prev == null ? "无" : prev.length() + "字")
                    + " 新句y=" + Math.round(rollOffsetFor(false))
                    + " 旧句y=" + Math.round(rollOffsetFor(true))
                    + " ｜" + cut(text) + "｜" + cut(prev);
        }

        /** 绘制时的纵向位移（参考系 px）：新句从 +h 推到 0，旧句从 0 推到 −h */
        private float rollOffsetFor(boolean previous) {
            float h = Math.max(1, getHeight());
            return previous ? -(h * roll) : (h * (1f - roll));
        }

        private String cut(String s) {
            if (s == null || s.isEmpty()) {
                return "-";
            }
            return s.length() <= 24 ? s : s.substring(0, 24) + "…";
        }

        @Override
        protected void onSizeChanged(int w, int h, int ow, int oh) {
            super.onSizeChanged(w, h, ow, oh);
            syncMetrics();
            remeasure();
            kick();
        }

        @Override
        protected void onVisibilityChanged(View changed, int vis) {
            super.onVisibilityChanged(changed, vis);
            if (vis == VISIBLE) {
                // 展开/重新露脸时也让它"滚"一次（不然是硬切）
                roll = 0f;
                remeasure();
                kick();
            } else {
                removeCallbacks(step);
            }
        }

        @Override
        protected void onDetachedFromWindow() {
            removeCallbacks(step);
            super.onDetachedFromWindow();
        }

        private float textWidth() {
            return text.isEmpty() ? 0f : paint.measureText(text);
        }

        private float paintWidth(String s) {
            return (s == null || s.isEmpty()) ? 0f : paint.measureText(s);
        }

        /** 视口宽（扣掉左右内边距） */
        private float viewW() {
            return Math.max(0f, getWidth() - getPaddingLeft() - getPaddingRight());
        }

        /** 按当前宽度把"本句/上一句"都算成可绘制串（装不下 ⇒ 省略号收尾；⚠ 不左右滚） */
        private void remeasure() {
            float w = viewW();
            drawn = ellipsize(text, w);
            drawnPrev = ellipsize(prev, w);
            lastW = getWidth();
        }

        private String ellipsize(String s, float w) {
            if (s == null || s.isEmpty()) {
                return "";
            }
            if (w <= 0 || paint.measureText(s) <= w) {
                return s;
            }
            return android.text.TextUtils.ellipsize(
                    s, paint, w, android.text.TextUtils.TruncateAt.END).toString();
        }

        private void kick() {
            removeCallbacks(step);
            if (!isShown()) {
                return;
            }
            if (roll < 1f) {
                postDelayed(step, FRAME_MS);
            } else {
                prev = null;                // 滚完 ⇒ 彻底静态（省电，别晃 wait_stable）
                drawnPrev = "";
                invalidate();
            }
        }

        private final Runnable step = new Runnable() {
            @Override
            public void run() {
                roll = Math.min(1f, roll + ROLL_STEP);
                if (roll >= 1f) {
                    prev = null;            // 上一句已经移出视口
                    drawnPrev = "";
                }
                invalidate();
                if (roll < 1f && isShown()) {
                    postDelayed(this, FRAME_MS);
                }
            }
        };

        @Override
        protected void onDraw(Canvas c) {
            super.onDraw(c);
            if (getWidth() != lastW) {      // 首帧/换宽度时补算一次（setLine 可能早于布局）
                remeasure();
            }
            if (drawn.isEmpty() && drawnPrev.isEmpty()) {
                return;
            }
            int h = getHeight();
            if (h <= 0) {
                return;
            }
            int pl = getPaddingLeft();
            float baseY = getPaddingTop() + (h - getPaddingTop() - getPaddingBottom()) / 2f
                    - (paint.descent() + paint.ascent()) / 2f;
            // ① 上一句：由原位**向上移出**（0 → −h）
            if (roll < 1f && !drawnPrev.isEmpty()) {
                paint.setColor(LOG_TEXT_COLOR);
                c.drawText(drawnPrev, pl, baseY - h * roll, paint);
            }
            // ② 新一句：由下方**推上来**（+h → 0）⇒ 这就是「整行上下滚动」
            if (!drawn.isEmpty()) {
                paint.setColor(LOG_TEXT_COLOR);
                c.drawText(drawn, pl, baseY + h * (1f - roll), paint);
            }
        }
    }
}
