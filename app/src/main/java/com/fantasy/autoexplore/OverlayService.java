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
 *   MGAS  点它 = 展开/收起（也是**拖动手柄**）；长按 = 强制显示/隐藏**日志行**（只动日志行！）
 *         ⚠ 长按三态：自动 → 强制显示 → 强制隐藏 → 自动。它**绝不**影响 张数/▶ 的可见性
 *           （2026-09-30 修：旧版把 ▶ 挂在这个开关上 ⇒ 拖动时手一抖误触长按 ⇒ 启动按钮消失）
 *   1图   点它切换「本次跑几张」：**1图 ⇄ 连刷**（连刷 = 一直刷到体力耗尽）
 *   ▶     开始（**点一下就走**，无二次确认/倒计时 —— 用户明确要求"点一下就开始"）
 *         可见性 = 「展开 且 没在跑」⇒ 空闲时永远找得到它，跑起来才收掉（不能重复启动）
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
    // ══ 方案 A（深空玻璃）令牌 —— 与 MainActivity / docs/ui_design/scheme_a.py 同源 ══
    //  ⚠ 悬浮条**比应用内更不透明**：它压在明亮的游戏美术上，α 太低会糊成一片
    private static final int BAR_BG = 0xF50A0E15;
    private static final int BAR_LINE = 0x3822D3EE;
    private static final int BAR_HAIR = 0x1CFFFFFF;
    /** 普通按钮：白 α9 / 描边 α18 */
    private static final int CHIP_BG = 0x17FFFFFF;
    private static final int CHIP_LINE = 0x2EFFFFFF;
    /** 点击瞬间高亮（青） */
    private static final int CHIP_BG_TAP = 0x5522D3EE;
    /** 危险（停止） */
    private static final int CHIP_DANGER_BG = 0xF07C2A34;
    private static final int CHIP_DANGER_LINE = 0x6EF87171;
    /** 警示（反馈） */
    private static final int CHIP_WARN_BG = 0x22FBBF24;
    private static final int CHIP_WARN_LINE = 0x82FBBF24;
    /** 主按钮（启动）：青→蓝渐变 */
    private static final int BTN_TOP = 0xFF40E2F6;
    private static final int BTN_BOTTOM = 0xFF247AE2;
    /** 文字色 */
    private static final int TXT_LOG = 0xFFDEEAF7;
    private static final int TXT_CHIP = 0xFFB0C2D6;
    private static final int TXT_CHIP_DIM = 0xFF78849A;
    private static final int TXT_DANGER = 0xFFFFD6D6;
    private static final int TXT_WARN = 0xFFFFD98A;
    private static final int TXT_PRIMARY = 0xFF05121E;
    /** 状态色 */
    private static final int C_IDLE = 0xFF8894A4;
    private static final int C_RUN = 0xFF34D399;
    private static final int C_LOCK = 0xFFF87171;

    /** 日志行保留多少条（往回翻最多翻这么多） */
    private static final int LOG_KEEP = 60;
    /** 日志行里最多留多少字符（太长就截断；超宽的部分由省略号收尾） */
    private static final int LOG_MAX_CHARS = 110;
    /** ⭐ **两行布局**（2026-09-29 用户口径：「悬浮窗要在按钮上面」）：
     *  上行 = 日志（整行、全宽、**上下滚动**、**浅底黑字**），下行 = 按钮。
     *  高度预算：底边钉 1816、顶边必须 ≥ 1722 ⇒ 总共只能有 **94 参考 px**。
     *  这里用 34（日志）+ 56（按钮）= **90** ⇒ 顶边 1726，留 4px 余量 ✓
     *  （2026-09-29 用户又要求「字放大一点，黑体」：日志 22→28 px + 加粗）*/
    // ⚠⚠⚠ v2.27 用户反馈「启动后显示的日志文字会被遮挡 / 显示不全」
    //   实测：行高 34 参考(=40 设备) vs 字号 28 参考(=33 设备)，
    //   而文字实际占高 ≈ 字号×1.2 = 40 ⇒ **富余 0px** ⇒ 字形下半被 View 边界裁掉 ✗
    //   ⇒ 34 → 44（设备 52），给文字留 12px 余量 ✓
    //   ⚠ 总高预算（34+56=90）会变成 44+56=100，仍 < 94 的旧预算…
    //     但用户已定「位置自己拖、锁顶边（方案 A）」，高度不再受 1722 硬约束限制，
    //     条子向下长即可 ⇒ 安全。
    private static final int LOG_ROW_H_REF = 44;
    /** 日志字号（参考系像素） */
    private static final float LOG_TEXT_REF = 28f;
    /** 日志行文字色（方案 A：深底浅字，与 App 内一致） */
    private static final int LOG_TEXT_COLOR = TXT_LOG;
    /** 日志行底色：**不再单独铺浅底** —— 整条已有一块深空玻璃底板，
     *  再叠一块浅色会把条子切成两截（旧版浅底是为了"黑字看得见"，
     *  现在字变浅了，那个理由不成立） */
    private static final int LOG_BG_COLOR = 0x00000000;
    /** 按钮字号（参考系像素）。⚠ 两行后必须压小：原来 15sp(45px) 会把总高顶到 100+ ⇒ 越过 1722 */
    private static final float CHIP_TEXT_REF = 34f;
    /** 按钮竖向内边距（参考系像素）——和字号一起决定按钮行高度 */
    private static final int CHIP_PAD_V_REF = 8;
    /**
     * 允许条子**向下**多让出的参考 px（给手势条留位，但绝不向上越棋盘）。
     *
     * <p>棋盘下沿 = 1722，参考底边 = 1816 ⇒ 中间本来就有 94px 的夹缝。
     * 手势条（约 44 参考 px）应该塞进这 94px 里，而不是把条子整体往上顶。
     */
    private static final int REF_BUDGET_SLACK = 44;

    /** 棋盘方块底边占屏高的比例（1280×2772 实测 2570/2772 ≈ 0.9272；无帧兜底用） */
    private static final float BOARD_BOTTOM_RATIO = 0.9272f;

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
    private TextView bubble, btnCount, btnStart, btnStop, btnClose, btnFb;
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
    /**
     * dev 验证钩子：强制展开/收起。
     *
     * <p>为什么要它：悬浮窗带 {@code FLAG_NOT_FOCUSABLE}，{@code adb shell input tap}
     * 注入不进去 ⇒ 展开态**只能手点**，自动化验证做不到。这个口让
     * {@code adb am broadcast --es cmd overlay_expand --es on true} 能触发同一条路径，
     * 便于量几何（顶边是否贴限制线）。
     */
    static void forceExpand(boolean ex) {
        final OverlayService o = INSTANCE;
        if (o == null) {
            AppLog.i("[overlay_expand] 悬浮条没开");
            return;
        }
        o.ui.post(() -> {
            o.setExpanded(ex);
            AppLog.i("[overlay_expand] 强制 " + (ex ? "展开" : "收起"));
        });
    }

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
                ui.post(() -> {
                    paint(st);
                    // ⭐ v2.09：棋盘底边检测需要一张**当前截图**，而悬浮条创建时
                    //   往往还没帧（人在 App 里 / 刚切游戏还没出图）。
                    //   ⇒ 每个 poll 周期若还没测到，就再试一次 —— 一旦有帧就自动生效，
                    //     并把条子重新贴到实测位置。
                    // ⭐⭐⭐ v2.34【用户口径 2026-10-26】：「每次启动第一张图进去后
                    //   会自动把悬浮窗顶边对齐棋盘底边」
                    //   ⇒ 每个 poll 周期检查一次：若能测到棋盘底边，且与当前顶边差 >3px，
                    //     就自动对齐一次（然后写入记忆，不再反复调整）。
                    if (!autoAlignedOnce) {
                        int board = measuredBoardBottom();
                        if (board > 0) {
                            autoAlignedOnce = true;
                            int curTop = 0;
                            int[] lc = new int[2];
                            try {
                                bar.getLocationOnScreen(lc);
                                curTop = lc[1];
                            } catch (Throwable ignored) {
                            }
                            if (curTop > 0 && Math.abs(curTop - board) > 3) {
                                AppLog.i("[ovl] 自动对齐：当前顶=" + curTop
                                        + " 棋盘底边=" + board + " ⇒ 对齐");
                                Prefs.setOverlayTop(OverlayService.this, board);
                                settlePosition();
                            } else {
                                AppLog.i("[ovl] 自动对齐：已在位（顶=" + curTop
                                        + " 棋盘底=" + board + "）");
                            }
                        }
                    }
                });
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
    /**
     * !! v2.88 [让路]：把悬浮条临时隐藏 ms 毫秒（给脚本点被它盖住的按钮用）
     *
     *   ---- 为什么需要 ----
     *     用户 2026-10-31 报：「悬浮窗在下面挡住公会角色开始冒险，无法切换到公会做日常」
     *     悬浮窗带 FLAG_NOT_FOCUSABLE，但会吃掉落在它身上的触摸（本文件第 94 行已写明）
     *     => 脚本 tapRef 点到的那一点若正好在悬浮条矩形里，手势被悬浮条截走，
     *        游戏根本收不到 => 公会/开始冒险/背包底部按钮全部点不动
     *
     *   ---- 为什么不是 FLAG_NOT_TOUCHABLE ----
     *     那样确实不挡了，但 停止按钮 / 拖动 / 点气泡展开 也一起失灵
     *     => 只能在点的那一瞬间让路，点完立刻恢复
     *
     *   ---- 为什么是 INVISIBLE ----
     *     缩小仍会占位；INVISIBLE 的窗口不参与触摸命中测试 => 手势直达游戏
     *     420ms 覆盖「抬起手指 + 游戏开始处理」；位置/尺寸都不动，
     *     恢复后与原来完全一致（不会因为让路而漂移）
     */
    public static void hideBriefly(final int ms) {
        final OverlayService o = INSTANCE;
        if (o == null) {
            return;
        }
        o.ui.post(() -> {
            try {
                if (o.bar == null || o.bar.getVisibility() != android.view.View.VISIBLE) {
                    return;
                }
                o.bar.setVisibility(android.view.View.INVISIBLE);
                o.ui.postDelayed(() -> {
                    try {
                        if (o.bar != null) {
                            o.bar.setVisibility(android.view.View.VISIBLE);
                        }
                    } catch (Throwable ignored) {
                    }
                }, Math.max(120, ms));
            } catch (Throwable ignored) {
            }
        });
    }

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

        // ⭐⭐ v1.41 热更【自动】检查（用户 2026-10-03：「发给朋友的怎么搞热更新？」）
        //   朋友**不该有任何操作** ⇒ 悬浮条一起来就在后台拉一次清单：
        //     · 有逻辑补丁 → 自动下（1~2MB），日志提示"重启生效"
        //       （重启后由 Updater.bootRecover 激活 + onPythonStarted 自检，坏包自动回滚 ✓）
        //     · 有整包     → **只提示**，不自动下 70MB（见 Updater.run 的 "bg" 分支）
        //   ⚠ 全程兜异常：更新这件事**绝不能影响悬浮条本身**（它是游戏里唯一的停止入口）。
        //   ⚠ 网络慢/断网时这里会挂在后台线程上，不阻塞任何 UI ✓
        new Thread(() -> {
            try {
                String r = Updater.run(getApplicationContext(), "bg");
                if (r != null && !r.isEmpty()) {
                    AppLog.i("› " + r);
                }
            } catch (Throwable t) {
                AppLog.i("› 自动检查更新失败（不影响使用）：" + t);
            }
        }, "ovl-update").start();
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

    /**
     * 一枚圆角小按钮（**只放符号/ASCII**，见类注释）；底色 drawable 存在 tag 里，方便改色。
     *
     * <p>方案 A 起支持四种样式；样式只影响**观感**，点击行为仍由调用点决定：
     * <ul>
     *   <li>{@link #S_NORMAL} 白 α9 —— 张数、✕</li>
     *   <li>{@link #S_PRIMARY} 青蓝渐变 —— 全条唯一的"现在该按这个"（启动）</li>
     *   <li>{@link #S_DANGER} 暗红 —— 停止</li>
     *   <li>{@link #S_WARN} 琥珀 —— 反馈</li>
     * </ul>
     *
     * <p>⚠ 字号走**参考系像素**（不是 sp）：两行布局后按钮行高度必须精确可控，
     * 否则换个密度就顶穿 1722（见 LOG_ROW_H_REF 的高度预算）。
     */
    /** 给 chip 的 tag 第二槽用的 key（避免用 R.id —— 本项目没有 ViewBinding/R 生成 id 的约定） */
    private static final int TAG_STYLE = 0x7F0A0001;

    private static final int S_NORMAL = 0;
    private static final int S_PRIMARY = 1;
    private static final int S_DANGER = 2;
    private static final int S_WARN = 3;

    private TextView chip(String text, int color) {
        return chipStyle(text, color, S_NORMAL);
    }

    private TextView chipStyle(String text, int color, int style) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(TypedValue.COMPLEX_UNIT_PX, RefMapper.devLen(CHIP_TEXT_REF));
        t.setTextColor(color);
        t.setIncludeFontPadding(false);              // 去掉字体内边距（省高度）
        t.setGravity(android.view.Gravity.CENTER);
        t.setIncludeFontPadding(false);
        // ⚠ 按钮**不加粗**：用户 2026-09-29 明确「字大一点/黑体说的是**日志**的字体」
        // ⚠ 竖向 padding = 0：行高已由 btnRow 的 LayoutParams 钉死 56 参考 px，
        //   再给 padding 就会把 chip 撑出边界（v2.02 实测条高 75 > 预算）
        // ⚠⚠ 量纲必须统一：字号是**参考系像素**（devLen），内边距也必须用 devLen。
        //   v2.02 实测：这里用 dp(11)（= 屏幕密度 dp，在 480dpi 上 ≈33px），
        //   而字只有 34 参考 px ⇒ 左右各白塞 33px ⇒ 胶囊**空出一大截**，
        //   看起来就是"文字显示不全 / 右边缺一块"。
        int ph = RefMapper.devLen(11), pv = 0;
        t.setPadding(ph, pv, ph, pv);
        t.setSingleLine(true);
        GradientDrawable g = new GradientDrawable();
        switch (style) {
            case S_PRIMARY:
                g = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
                        new int[]{BTN_TOP, BTN_BOTTOM});
                g.setCornerRadius(RefMapper.devLen(20));
                g.setStroke(dp(1), 0x5A78E6FF);
                break;
            case S_DANGER:
                g.setColor(CHIP_DANGER_BG);
                g.setCornerRadius(RefMapper.devLen(20));
                g.setStroke(dp(1), CHIP_DANGER_LINE);
                break;
            case S_WARN:
                g.setColor(CHIP_WARN_BG);
                g.setCornerRadius(RefMapper.devLen(20));
                g.setStroke(dp(1), CHIP_WARN_LINE);
                break;
            default:
                g.setColor(CHIP_BG);
                g.setCornerRadius(RefMapper.devLen(20));
                g.setStroke(dp(1), CHIP_LINE);
                break;
        }
        t.setBackground(g);
        t.setTag(g);
        t.setTag(TAG_STYLE, style);                 // flash 恢复底色时要用
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        p.rightMargin = RefMapper.devLen(5);
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
        Object st = v.getTag(TAG_STYLE);
        if (st instanceof Integer && (Integer) st == S_PRIMARY) {
            // 渐变按钮改不了 setColor（会盖掉 shader）⇒ 闪一下描边
            g.setStroke(dp(2), 0xCCFFFFFF);
            ui.postDelayed(() -> applyBaseBg(v), 180);
            return;
        }
        g.setColor(CHIP_BG_TAP);
        ui.postDelayed(() -> applyBaseBg(v), 180);
    }

    private GradientDrawable bgOf(TextView v) {
        return (v != null && v.getTag() instanceof GradientDrawable)
                ? (GradientDrawable) v.getTag() : null;
    }

    /** 恢复该按钮的常态底色（按 style 分派，别一律刷成白 α9） */
    private void applyBaseBg(TextView v) {
        GradientDrawable g = bgOf(v);
        if (g == null) {
            return;
        }
        Object st = v.getTag(TAG_STYLE);
        int style = (st instanceof Integer) ? (Integer) st : S_NORMAL;
        switch (style) {
            case S_PRIMARY:
                g.setStroke(dp(1), 0x5A78E6FF);
                break;
            case S_DANGER:
                g.setColor(CHIP_DANGER_BG);
                break;
            case S_WARN:
                g.setColor(CHIP_WARN_BG);
                break;
            default:
                g.setColor(CHIP_BG);
                break;
        }
    }

    /** 条底板：深空玻璃 + 青描边（方案 A 令牌）。收起态变**胶囊**形 */
    private void applyBarBg() {
        if (bar == null) {
            return;
        }

        // ⚠ 收起/展开**都保留深空玻璃底板**（用户 2026-10-19 澄清：
        //   「为啥改成透明？按之前的限制出现位置就行啊」——
        //   他要的是**位置回到原约束**，不是去掉底板）。
        GradientDrawable g = new GradientDrawable();
        g.setColor(BAR_BG);
        g.setCornerRadius(expanded ? dp(16) : dp(22));
        g.setStroke(dp(1), BAR_LINE);
        bar.setBackground(g);
    }

    private void buildView() {
        choiceIdx = Math.max(0, Math.min(MAP_LABELS.length - 1, Prefs.mapsChoice(this)));
        // ⚠ 先把屏幕尺寸喂给 RefMapper：`afterLayout` 要用它算"涂平矩形"（FrameStore 依赖），
        //   而第一次截图（toRef 会顺带设）可能还没发生 ⇒ 不设就按 1080×1920 算，非该分辨率会错。
        // ⭐⭐ 2026-09-30 修：这里**必须**用真实屏幕（含系统导航栏），不能用 `dm.heightPixels`
        //   —— 真机 1280×2772 上后者是 2588（少 184px），而截图帧是 2772 ⇒ 两条口径混用，
        //   涂平矩形会整体偏 184px（偏进棋盘里！详见 afterLayout 的长注释）。
        //   RefMapper 的 devY/devX/toRef 本来就是为"截图帧坐标系"服务的 ⇒ 传真实尺寸才是自洽的。
        int[] rs = realScreen();
        RefMapper.setScreen(rs[0], rs[1]);

        // ── ① **两行**：上行 = 日志（整行、上下滚动），下行 = 按钮 ──
        //    用户口径 2026-09-29：「悬浮窗要在按钮上面。滚动方式是整行上下滚动，不是现在的左右」
        //    ⚠ 高度预算见 LOG_ROW_H_REF：日志 28 + 按钮 56 = 84 ⇒ 顶边 1732 ≥ 1722 ✓
        bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.VERTICAL);
        bar.setGravity(Gravity.START);
        // ⭐ 方案 A：整条一块深空玻璃面板（旧版是两个各自为政的方块）
        //   ⚠⚠ 真机铁证（v2.02 首装）：竖向 padding 会把 90 的预算撑成 97+
        //     ⇒ 顶边从 1726 掉到 1598，**越过棋盘下沿 1722 达 124px** ⇒ 会盖住最低一行格子
        //     （识别错 + 那几格点不动，见类注释硬约束①）。
        //   ⇒ **只加横向 padding**，纵向一点都不加（高度必须原封不动按 34+56 走）。
        // 收起/展开都需要左右内边距（里面都是胶囊，文字不能贴边）
        bar.setPadding(RefMapper.devLen(10), 0, RefMapper.devLen(10), 0);
        applyBarBg();

        // 下行：按钮（气泡 / 张数 / ▶ / ■ / ✕）
        btnRow = new LinearLayout(this);
        btnRow.setOrientation(LinearLayout.HORIZONTAL);
        btnRow.setGravity(Gravity.CENTER_VERTICAL);
        // ⚠ 按钮行高度**钉死**（不靠 chip 的 padding 撑）——
        //   旧实现靠 padding 隐式撑高，一改样式就悄悄变高 ⇒ 顶边越过棋盘（v2.02 实测 75）。
        //   展开态 56（日志 34 + 按钮 56 = 90 预算）；收起态 44（只剩一枚胶囊）。
        addBtnRow();

        // ⭐ 方案 A：气泡 → **状态胶囊**（色点由 paint() 换色，文案直接写状态）
        //   旧版只有 "● MGAS" 一个符号，用户要回 App 才知道是"跑图中"还是"红装锁"
        bubble = chipStyle("MGAS", TXT_CHIP, S_NORMAL);
        bubbleOriginText = "MGAS";

        bubble.setOnClickListener(v -> {
            flash(bubble);
            AppLog.i("[ovl] 点气泡 → " + (expanded ? "收起" : "展开"));
            setExpanded(!expanded);
        });
        // ⭐ 精简后长按 = **低频操作入口**（张数 / 反馈 / 日志行），不再挤在按钮行
        bubble.setOnLongClickListener(v -> {
            flash(bubble);
            keepAlive();
            showMoreMenu();
            return true;
        });
        installDrag(bubble);
        btnRow.addView(bubble);

        // ⭐ 2026-10-19 用户口径「悬浮窗太臃肿了，简洁一些」⇒ 做减法：
        //   张数切换从**独立按钮**降级为**长按气泡弹出**（它一天改一次，不该常驻占位）
        btnCount = chip(MAP_LABELS[choiceIdx], TXT_CHIP);
        btnCount.setOnClickListener(v -> {
            flash(btnCount);
            keepAlive();
            choiceIdx = (choiceIdx + 1) % MAP_LABELS.length;
            btnCount.setText(MAP_LABELS[choiceIdx]);
            Prefs.setMapsChoice(this, choiceIdx);
            AppLog.i("[ovl] 张数 ⇒ " + MAP_LABELS[choiceIdx]
                    + (choiceIdx == 0 ? "（约 " + STAMINA_PER_MAP + " 体力）"
                                      : "（一直刷到体力不够进图为止）"));
        });
        // ⚠ 不 addView ⇒ 不进按钮行（仍保留对象，供长按菜单 toggle 文案）

        btnStart = chipStyle("▶ 启动", TXT_PRIMARY, S_PRIMARY);
        btnStart.setOnClickListener(v -> {
            flash(btnStart);
            keepAlive();
            AppLog.i("[ovl] 点 ▶ ⇒ 开始");
            onStart();
        });
        btnRow.addView(btnStart);
        // ⚠ 精简：btnStart 与 btnStop 在 applyMode() 里**互斥显示**（同一位置换身），
        //   所以按钮行任意时刻最多 = 状态胶囊 + 1 个主按钮

        btnStop = chipStyle("■ 停止", TXT_DANGER, S_DANGER);
        btnStop.setOnClickListener(v -> {
            flash(btnStop);
            keepAlive();
            AppLog.i("[ovl] 点 ■ ⇒ 立刻停止（不等这张图打完）");
            new Thread(() -> AppLog.i("■ " + PyBridge.call("stop")), "ovl-stop").start();
        });
        btnRow.addView(btnStop);

        // ⭐ 精简：✕ 不再常驻 —— 点气泡本身就能收起（这是更自然的交互），
        //   而且旧版 ✕ 挨着停止键，误触一次就把条子收了找不到启动。
        btnClose = chip("✕", TXT_CHIP_DIM);
        btnClose.setOnClickListener(v -> {
            flash(btnClose);
            AppLog.i("[ovl] 点 ✕ ⇒ 收起");
            setExpanded(false);
        });
        // ⚠ 不 addView ⇒ 不进按钮行

        // ⭐⭐⭐ 2026-10-01 v1.14【反馈】用户口径：「能不能加个按钮能更方便让朋友发他的问题给我」
        //   一点 = 把 日志 + 机型信息 + 现场帧 打成 zip 并**弹系统分享面板**（微信/QQ 直接发）✓
        //   ⚠ 按钮文案走 `sanitize()`：本工程的 OCR 关键词表里没有「反馈」⇒ 不会被糊成 ▓ ✓
        //   ⚠ 放最右下（✕ 之后）：不容易误触（它只多打一个包，不改变任何运行状态 ✓）
        btnFb = chipStyle("反馈", TXT_WARN, S_WARN);
        btnFb.setOnClickListener(v -> {
            flash(btnFb);
            keepAlive();
            AppLog.i("[ovl] 点「反馈」⇒ 打包日志 + 机型信息 + 现场帧");
            final Context c = getApplicationContext();
            new Thread(() -> {
                try {
                    Feedback.collectAndShare(c);
                } catch (Throwable t) {
                    AppLog.i("[ovl] 反馈异常：" + t);
                }
            }, "ovl-feedback").start();
        });
        // ⭐ 精简：反馈也收进长按菜单（它是低频操作；常驻会跟"停止"抢注意力）
        // ⚠ 不 addView ⇒ 不进按钮行

        // ── ② 日志行（**在按钮上面**，整行全宽、自己画、上下滚动）──
        //    ⭐ 2026-09-29 用户口径：「要在按钮上面啊，并且是**黑色字**」
        //    ⇒ 给日志行铺一块**浅色底 + 黑字**：① 黑字必须配浅底才看得见（游戏底是深色）
        //      ② 浅底把这一行和身后的游戏/App 文字**分开**，一眼就是"按钮上方那一行是我的"
        tvLog = new MarqueeView(this);
        // ⚠⚠ 宽度问题三轮踩了三次，结论钉死在这里：
        //   ① MATCH_PARENT + 外层 WRAP_CONTENT ⇒ 解析成 0 宽（父看子、子看父，无解）
        //   ② 固定像素宽 ⇒ MarqueeView.onMeasure 的 fill 分支失效
        //      （它按 p.width == MATCH_PARENT 判断"铺满"）⇒ 又缩成文字宽
        //      ⇒ 文字被自己的宽度截断（用户看到的"日志显示不全"）
        //   ③ 正解：MATCH_PARENT + **给父级 bar 一个确定宽度**（见 buildView 末尾）。
        //      父级有确定宽 ⇒ MATCH_PARENT 有解 ⇒ fill 分支成立 ⇒ 按可用宽省略
        LinearLayout.LayoutParams lpl = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, RefMapper.devLen(LOG_ROW_H_REF));
        tvLog.setLayoutParams(lpl);
        // 方案 A：不再单铺浅底（整条已有玻璃底板）—— LOG_BG_COLOR 是透明的
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
        // ⭐⭐⭐ v2.41【用户拍板 2026-10-26】：「日志是显示不全，上边被遮挡了」
        //   根因：日志行在**第 0 行（上方）**，而悬浮条顶边贴住棋盘底边
        //   ⇒ 日志行那一块正好压在棋盘最后一行格子上 ⇒ 上半截被盖 ✗
        //   ⇒ 改成 **按钮在上、日志在下**：
        //       [MGAS ▶启动]     ← 贴着棋盘底边
        //       [第1张图·准备进图] ← 在最下面，永远不会被上方内容遮挡 ✓
        //   addBtnRow() 会 removeView(btnRow) 再加回末尾 ⇒ 只要保持"日志先 add"，

        // v2.45 修（上一版把这行误删了）：
        //   诊断实证 tvLog 状态: idx=-1 n=1 => tvLog 根本不在 bar 里，
        //   所以 getWidth() 恒为 0、什么都画不出来。
        //   必须显式 addView 才进布局树。
        bar.addView(tvLog, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, RefMapper.devLen(LOG_ROW_H_REF)));

        lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                        ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                        : WindowManager.LayoutParams.TYPE_PHONE,
                // ⚠ 这里**不要**加 FLAG_SECURE（见硬约束②：MuMu 上会让整屏抓取直接失败）
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        // ⚠ Gravity.BOTTOM：lp.y 变成「离屏幕底的距离」⇒ 底边**恒定**，只横向生长
        lp.gravity = Gravity.BOTTOM | Gravity.START;
        lp.setTitle("MGAS");                         // 便于 `dumpsys window` 里认人
        // v2.21：左边距同样记住用户拖的位置
        int savedX = Prefs.overlayX(getApplicationContext());
        lp.x = (savedX >= 0) ? savedX : RefMapper.devX(20);
        // ⚠⚠ 真机 bug（v2.02，用户原话「悬浮窗还是低了，显示不全」）：
        //   Gravity.BOTTOM 下 lp.y 是**离屏幕底**的距离，而屏幕底包含系统手势条区。
        //   参考 y=1816 是「1080×1920 无手势条」时代的口径 ⇒ 映射到 1280×2772 后
        //   底边正好压进手势条里，最后一行文字被系统条盖住 / 被裁掉。
        //   ⇒ 额外让出导航栏高度（读系统 insets，拿不到就用 48dp 兜底）。
        // ⚠⚠ v2.02 二次实测：直接加 navInset 会把**底边从 1722 抬到 1678**
        //   ⇒ 顶边跟着进到棋盘区（1722 以上），盖住最低一行格子 ✗
        //   正确做法：底边**不许越过棋盘下沿**（1722），
        //   让出的手势条空间从「条子内部」省 —— 见 BAR_BOTTOM_REF 的收紧。
        // ⭐ 位置回到**最初的硬约束**（OverlayService 类注释硬约束①）：
        //   底边钉死 参考 y=1816，展开态 90 高 ⇒ 顶边 1726 ≥ 棋盘下沿 1722 ✓。
        //   ⚠ 我中途试过 +手势条偏移、锚棋盘下沿两种改法，都会让位置漂走
        //     （用户 2026-10-19：「按之前的限制出现位置就行啊」）⇒ 回退到原口径。
        navInset = navBarHeight();
        // ⚠⚠⚠ Gravity.BOTTOM 的基准不是"物理屏高"，而是**窗口可用区高度**
        //   （dumpsys 实测 parent=[0,0][1280,2720]，比物理 2772 少 52px 手势条）
        //   ⇒ 用物理屏高算 lp.y 会整体偏低 52px（真机实测 frame 落在 2545~2597，
        //     而目标是底边 2649 ⇒ 差 52）。
        int[] rs0 = realScreen();
        int physical = rs0[1];
        int usable = physical - nav();   // = 父窗口高度
        // !! v2.92b【Gravity.BOTTOM 的基准是**物理屏高**，不是可用区】
        //   实测（1280x2640，手势条 156）：lp.y=0、h=78 时顶边落在设备 2563
        //     => 2640 − 78 = 2562，即**基准 = 物理 2640**
        //   而旧代码按「可用区 2484」算 => 恒差 156px（正好一条手势条）
        //     => 悬浮条被压到屏幕最底、甚至盖住底部导航（用户：位置还是错的）
        //   => 改用物理屏高做基准 ✓
        lp.y = anchorY(physical);
        AppLog.i("悬浮条定位：展开=" + expanded + " ⇒ lp.y=" + lp.y
                + "（可用区 " + usable + " = 物理 " + physical + " − 手势条 " + nav() + "）"
                + "  " + (expanded ? "顶边贴限制线 1722" : "底边钉 1816"));

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
            // ⭐ 加窗后**必须再定位一次**：addView 之前 bar.getHeight() 还是 0，
            //   anchorY() 只能用默认值估算 ⇒ 首帧位置会差一截（用户看到"没贴住"）。
            //   这里等布局完成再按真实高度钉一次顶边。
            bar.post(() -> {
                settleRetried = false;
                settlePosition();
                afterLayout();
            });
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
        // ⭐⭐ 2026-09-30 修：这里的屏幕高**必须**是「真实屏幕」（含系统导航栏，= 截图帧高）。
        //   以前直接吃 RefMapper.screenH()，可它在真机上是个**会跳的值**：
        //     · buildView() 喂的是 `dm.heightPixels` = **2588**（1280×2772 的机器少了底部导航栏 184px）
        //     · 而 RefMapper.toRef()/toDlgRef() 每次截图又会用帧尺寸把它改成 **2772**
        //   ⇒ 同一个 screenH 在 2588/2772 之间跳，涂平矩形跟着跳 184px（实测铁证：
        //     mask_check 报矩形 y 2353~2468，而条子真身在屏幕 y 2537~2652）。
        //   后果有两个，都很难查：
        //     ① 涂平**没盖住**悬浮条（机器人照样 OCR 到条子上的字，含 `关闭/探索/开始冒险`
        //        这类关键词 ⇒ 可能被当成游戏面板）—— 「让机器人对自己瞎」其实是失效的；
        //     ② 涂错的地方是**棋盘**！错位矩形 参考 y 1566~1663 正落在棋盘 1002~1722 内
        //        ⇒ 那一行格子被抹成纯色：识别错 + 点不动（硬约束①说的就是这个事故）。
        //   ⇒ 改成用 getMaximumWindowMetrics()（与 CaptureService.realScreenSize / adb screencap 同口径）。
        int[] rs = realScreen();
        RefMapper.setScreen(rs[0], rs[1]);   // 顺手把 RefMapper 也校准到同一口径（幂等，只在变化时打日志）
        int sw = RefMapper.screenW(), sh = RefMapper.screenH();
        barMaxH = Math.max(barMaxH, bar.getHeight());
        barMaxW = Math.max(barMaxW, bar.getWidth());
        // ⭐⭐ 自愈兜底（2026-09-29 实测踩到）：拖动夹子是按**当时**高度算的
        //   —— 收起态 bh=56 时夹在 lp.y≤142（顶边正好 1722），可**一展开** bh 变 84
        //   ⇒ 顶边掉到 1694，又把棋盘最低一行盖住（涂平抹掉 ⇒ 识别错 + 点不动）。
        //   所以这里不依赖"拖动时算对"：只要顶边越界就改 lp.y 把它推回去（幂等，改完再走一次）。
        // ⚠⚠⚠ v2.02 定位（用户连报三次「位置不对」，这里是真凶）：
        //   原逻辑 = 「顶边越界 ⇒ 把顶边钉回 1722」。
        //   但条子**高度是变的**（收起 52 / 展开 106 设备px）⇒ 钉顶边等于**改底边**：
        //     展开态：顶边钉 1722 ⇒ 底边 = 1722 + 106 = 1828，可屏幕只到 2772，
        //             换算回参考就成了 1615~1705（实测值）⇒ 位置整体上移、且再无定数 ✗
        //   而用户的约束是「**底边**钉 1816、**顶边**别越过 1722」——
        //   正确做法是**底边优先**：底边永远钉 1816，高度变了就让顶边自己动。
        //   只有一种情况要干预：底边太靠下、导致顶边仍然越过 1722 ⇒ **那说明高度超预算**，
        //   这时该压的是**内容高度**（由 addBtnRow 的 44/50/56 保证），不是平移整条。
        //   ⇒ 本段只做**校验与告警**，不再改 lp.y（改了就永远定不住）。
        // ⚠⚠ 基准必须用**可用区高度**，不是物理屏高：
        //   Gravity.BOTTOM 下 lp.y 是"离窗口可用区底边"的距离，
        //   而可用区 = 物理屏 − 手势条（实测 2772−52=2720）。
        //   v2.02 用物理屏算 ⇒ 位置偏 52px，日志也一起报错。
        int usableH = sh - nav();
        int bottomPx = usableH - lp.y;
        int topPx = bottomPx - bar.getHeight();
        // ⭐ 诊断：把"窗口底边 / 顶边"用**设备坐标**直接打出来，
        //   避免 refY() 的分段反算把结论带偏（v2.02 实测过：日志报 1728~1772
        //   而真实 frame 是 2597~2649，两者对不上，排查时会误判）。
        // ⚠ v2.06：snapTopToLimit() 已**停用**。
        //   它是"按真实顶边反推 lp.y"的自校正，在有记忆位置后只会和用户拖的位置打架
        //   （实测：用户拖到 y=329，被 snap 改回 562 并写进了记忆 ⇒ 位置漂移 233px）。
        //   现在位置权威 = 用户拖到哪就是哪（Prefs.overlayY），不再自动纠正。
        if (tvLog != null) {
            android.view.ViewGroup.LayoutParams tlp0 = tvLog.getLayoutParams();
            AppLog.i("[ovl] tvLog 状态: vis=" + tvLog.getVisibility()
                    + " w=" + tvLog.getWidth() + " h=" + tvLog.getHeight()
                    + " lp=" + (tlp0 == null ? "null"
                        : (tlp0.width + "x" + tlp0.height))
                    + " barW=" + (bar != null ? bar.getWidth() : -1)
                    + " idx=" + childIndexOf(bar, tvLog)
                    + " n=" + (bar != null ? bar.getChildCount() : -1));
        }
        AppLog.i("[ovl] 几何：设备 顶=" + topPx + " 底=" + bottomPx
                + " 高=" + bar.getHeight() + " lp.y=" + lp.y
                + " 物理屏=" + sh + " 展开=" + expanded);
        // 顶边越界的**唯一正确修法**：压内容高度（日志行），绝不平移整条。
        // 底边钉 1816 是硬约束，一平移就漂（v2.02 连错三次都是因为这个）。
        int overDev = RefMapper.devY(BOARD_Y1_REF) - topPx;
        if (overDev > 0 && expanded && logMode && tvLog != null) {
            int curH = tvLog.getHeight();
            if (curH > 0) {
                int newH = Math.max(RefMapper.devLen(20), curH - overDev);
                if (newH < curH) {
                    android.view.ViewGroup.LayoutParams vlp = tvLog.getLayoutParams();
                    vlp.height = newH;
                    tvLog.setLayoutParams(vlp);
                    AppLog.i("[ovl] 顶边越界 " + overDev + "px => 压日志行 "
                            + curH + "->" + newH + "（不动整条位置）");
                }
            }
        }
        if (topPx < RefMapper.devY(BOARD_Y1_REF)) {
            AppLog.i("[ovl] ⚠ 顶边(参考 " + Math.round(RefMapper.refY(topPx))
                    + ") 越过棋盘下沿 " + BOARD_Y1_REF + " 共 "
                    + Math.round(BOARD_Y1_REF - RefMapper.refY(topPx))
                    + "px ⇒ 条子太高，请压 addBtnRow 的高度，不要平移整条");
        }
        // ⭐⭐ 涂平矩形 & 几何自检**一律以 getLocationOnScreen 为准**。
        //   v2.02 教训：自己按 lp.y 推算，连基准（物理屏 vs 可用区）都会搞错，
        //   而错了的后果是"抹掉棋盘一行格子"——用户只看到点不动，根本查不到这儿。
        int l = Math.max(0, lp.x);
        int r = Math.min(sw, lp.x + bar.getWidth());
        int b = Math.min(sh, usableH - lp.y);          // 先用公式兜底
        int t = Math.max(0, b - bar.getHeight());
        // ⭐ 再加一道**实测复核**（2026-09-30）：窗口坐标万一和"我算的"不一致（改 gravity / 加 flag /
        //   系统改导航栏策略都可能），涂平就会静默偏 —— 而它偏的后果是「抹掉棋盘一行格子」，
        //   用户只会看到"怎么点不动"，根本查不到这儿。所以直接问 View 要绝对屏幕坐标，差 >4px 就以实测为准。
        int[] loc = new int[2];
        boolean measured = false;
        try {
            bar.getLocationOnScreen(loc);
            measured = (loc[1] > -bar.getHeight() && loc[1] < sh + bar.getHeight());
        } catch (Throwable ignored) {
        }
        if (measured && Math.abs(loc[1] + bar.getHeight() - b) > 4) {
            AppLog.i("[ovl] ⚠ 涂平矩形与实测不符：按 lp 算得底边 " + b
                    + "，View 实测底边 " + (loc[1] + bar.getHeight()) + " ⇒ 以实测为准");
            l = Math.max(0, loc[0]);
            r = Math.min(sw, loc[0] + bar.getWidth());
            b = Math.min(sh, loc[1] + bar.getHeight());
            t = Math.max(0, loc[1]);
        }
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
        // ⚠ 阈值留 10px 容差：实测条子两行 = 115 设备px = 97 参考px，而预算只有 94
        //   ⇒ 顶边落在 参考 1719，比棋盘下沿 1722 **高 3px**（真机跑满 10 张图实测无影响：
        //   那 3px 是最后一行的描边，格子中心/模板都不在那儿）。以前这里每展开一次就刷一条
        //   「会盖住最低一行格子」的红色警告 ⇒ 真出事时反而没人当回事（狼来了）。
        //   ⇒ 只有**真的**越过 10px（说明预算被改坏了）才报。
        // ⚠ 阈值收到 4px：预算只余 4（1726-1722），超过就该响 —— 旧值 10 会放过 5~9px 的越界
        if (topRef < BOARD_Y1_REF - 4) {
            AppLog.i("⚠⚠ 悬浮条顶边 参考 y=" + Math.round(topRef) + " 越过了棋盘下沿 "
                    + BOARD_Y1_REF + " 足 " + Math.round(BOARD_Y1_REF - topRef)
                    + "px ⇒ 会盖住最低一行格子（识别错 + 那几格点不动）！"
                    + " 请调小 LOG_ROW_H_REF / CHIP_TEXT_REF（高度预算见类注释硬约束①）");
        }
    }

    /**
     * 真实屏幕像素（含状态栏/导航栏，与「截图帧」「adb screencap」同一口径）。
     * ⚠⚠ **不要**改用 `getResources().getDisplayMetrics()` —— 那个不含系统导航栏
     * （真机 1280×2772 上给的是 2588，差 184px），而 MediaProjection 的帧、`dispatchGesture`
     * 的坐标、RefMapper 的映射全都在"真实屏幕"坐标系里 ⇒ 混用必错 184px。
     * 抄的是 {@link CaptureService#realScreenSize}（Screenshots 那条链已经验证过口径对）。
     */
    private int[] realScreen() {
        try {
            WindowManager w = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Rect r = w.getMaximumWindowMetrics().getBounds();
                if (r.width() > 0 && r.height() > 0) {
                    return new int[]{r.width(), r.height()};
                }
            }
            android.util.DisplayMetrics dm = new android.util.DisplayMetrics();
            w.getDefaultDisplay().getRealMetrics(dm);
            if (dm.widthPixels > 0 && dm.heightPixels > 0) {
                return new int[]{dm.widthPixels, dm.heightPixels};
            }
        } catch (Throwable ignored) {
        }
        return new int[]{RefMapper.screenW(), RefMapper.screenH()};   // 兜底：别返回 0
    }

    /** 运行中？（用状态灯那一套判据，别另起一套） */
    private boolean isRunningState() {
        return "run".equals(lastState) || "lock".equals(lastState) || "err".equals(lastState);
    }

    /** 按「运行状态 + 手动覆盖」决定这一排显示什么 */
    /**
     * 长按气泡弹出的**低频操作菜单**（精简后这些都不常驻）。
     *
     * <p>⚠ 用 {@link PopupWindow} 而不是 Dialog：本服务跑在悬浮窗里，
     * Dialog 需要 Activity 上下文，会抛 BadTokenException。
     * <p>⚠ 必须 setOutsideTouchable(true) + 可点背景在**菜单格子**上，
     * 否则点了外面不消失、挡住游戏。
     */
    /**
     * 按**当前实际高度**把条子底边钉回参考 y=BAR_BOTTOM_REF（1816）。
     *
     * <p>展开（89）与收起（56）高度不同，而 {@code lp.y}（Gravity.BOTTOM 下 = 离屏幕底）
     * 必须跟着变；只靠 afterLayout 的自愈会让顶边先越界一帧 ——
     * 那一帧恰好把棋盘最低一行抹平（真机 v2.02 实测抓到）。
     */
    /**
     * 系统导航栏 / 手势条高度（px）。
     *
     * <p>⚠ 悬浮窗用 {@code Gravity.BOTTOM} 时，{@code lp.y} 的距离基准是**屏幕物理底边**，
     * 而手势条就压在那一段上 ⇒ 不主动让开就会被盖住（真机 v2.02 实测：
     * 最后一行日志被裁掉一半）。这里读真实 insets，拿不到用 48dp 兜底。
     */
    private int navBarHeight() {
        try {
            int[] rs = realScreen();
            int bottom = 0;
            if (Build.VERSION.SDK_INT >= 30) {
                WindowManager w = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
                if (w != null) {
                    android.view.WindowInsets ins = w.getCurrentWindowMetrics().getWindowInsets();
                    android.graphics.Insets bar = ins.getInsets(
                            android.view.WindowInsets.Type.navigationBars());
                    bottom = bar.bottom;
                }
            }
            if (bottom <= 0) {
                // 兜底：真实屏高与"可用内容高"的差（老 ROM 没有 getCurrentWindowMetrics 时的近似）
                int dmH = getResources().getDisplayMetrics().heightPixels;
                bottom = Math.max(0, rs[1] - dmH);
            }
            if (bottom <= 0) {
                bottom = dp(48);
            }
            return bottom;
        } catch (Throwable t) {
            return dp(48);
        }
    }

    /**
     * 缓存的手势条高度。**-1 = 还没算过**（绝不能把 0 当成"没有手势条"）。
     *
     * <p>v2.02 真机 bug（用户原话「启动后会自动往下位移」）：
     * buildView 给 navInset 赋了值，但 settlePosition 可能在赋值前后各跑一次，
     * 初始值 0 时 usable 会算成物理屏 2772（当成没手势条）
     * 导致 lp.y 从正确的 71 漂到 129，条子整体下移 58px。
     *
     * <p>修改方法：统一走 nav() 取值，没算过就现算，任何调用点都拿不到 0。
     */
    private int navInset = -1;
    /** 校准迭代计数（每次布局回调走一步，最多 6 步） */
    private int settleTries = 0;
    /** settlePosition 的一次性重试标记（展开瞬间高度可能还是旧值） */
    private boolean settleRetried = false;
    /** 「进图后自动对齐棋盘底边」是否已执行过（每次拉起悬浮条只做一次） */
    private boolean autoAlignedOnce = false;

    private int nav() {
        if (navInset < 0) {
            navInset = navBarHeight();
            AppLog.i("[ovl] 手势条高度 = " + navInset + "px");
        }
        return navInset;
    }

    /**
     * 计算 {@code lp.y}（Gravity.BOTTOM ⇒ 离可用区底边的距离）。
     *
     * <p>两套锚点（用户 2026-10-19 明确）：
     * <ul>
     *   <li><b>收起态</b>：底边钉 参考 1816（沿用它一直以来的口径）</li>
     *   <li><b>展开态（启动后）</b>：<b>顶边</b>紧贴限制线 参考 1722 —— 用户原话
     *       「悬浮条启动位置就要紧贴限制线最上面」</li>
     * </ul>
     * <p>⚠ 两种模式都**不许越过 1722**，这是硬约束①（盖住棋盘 ⇒ 识别错 + 点不动）。
     */
    /**
     * 主动测量条子高度（不依赖 {@code getHeight()} 的时序）。
     *
     * <p>⚠ {@code updateViewLayout} 之后布局还没跑完，{@code bar.getHeight()} 返回上一帧的值，
     * 按旧高度算锚点会差一个"新高度 − 旧高度"。这里显式 measure 一次。
     */
    private int measureBarHeight() {
        if (bar == null) {
            return RefMapper.devLen(44);
        }
        int have = bar.getHeight();
        try {
            int wSpec = android.view.View.MeasureSpec.makeMeasureSpec(
                    Math.max(1, bar.getWidth()), android.view.View.MeasureSpec.EXACTLY);
            int hSpec = android.view.View.MeasureSpec.makeMeasureSpec(
                    0, android.view.View.MeasureSpec.UNSPECIFIED);
            bar.measure(wSpec, hSpec);
            have = Math.max(have, bar.getMeasuredHeight());
        } catch (Throwable ignored) {
        }
        return have > 0 ? have : RefMapper.devLen(44);
    }

    /**
     * 悬浮条**顶边**应该落在的设备 y 坐标。
     *
     * <p>优先用实测棋盘底边（{@link BoardEdge}），失败退回常量换算。
     * 这是"绝对目标"，与 lp.y 的基准无关。
     */
    private int targetTopY() {
        int board = measuredBoardBottom();
        if (board > 0) {
            return board + 2;                 // 紧贴棋盘方块底部
        }
        return RefMapper.devY(BOARD_Y1_REF); // 兜底（历史常量）
    }

    /** 缓存的实测棋盘底边（-1 = 还没测过 / 测不到） */
    private int boardBottomCache = -1;
    /** 上次测量的时间 */
    private long boardBottomAt = 0L;

    /**
     * 实测棋盘底边（设备像素）。带 8 秒缓存 —— 全屏扫描是 O(w×h)，不能每个 tick 都跑。
     */
    private int measuredBoardBottom() {
        long now = System.currentTimeMillis();
        if (boardBottomCache > 0 && now - boardBottomAt < 2000L) {
            return boardBottomCache;
        }
        boardBottomAt = now;
        try {
            android.graphics.Bitmap f = FrameStore.get();
            if (f == null) {
                return boardBottomCache;      // 没有帧 ⇒ 沿用上次结果
            }
            int y = BoardEdge.detectBottom(f);
            if (y > 0) {
                if (y != boardBottomCache) {
                    AppLog.i("[ovl] 实测棋盘底边 = " + y + "px"
                            + "（常量 devY(1722)=" + RefMapper.devY(BOARD_Y1_REF) + "）");
                }
                boardBottomCache = y;
                return y;
            }
        } catch (Throwable t) {
            AppLog.i("[ovl] 棋盘底边检测失败：" + t);
        }
        return boardBottomCache;
    }

    /**
     * 棋盘方块**真实底边**（设备像素）。
     *
     * <p>⚠⚠⚠ v2.31（用户 2026-10-26「上限定的太低了」「挡住棋盘看不到东西」）：
     * 常量 {@code BOARD_Y1_REF=1722} 在这台机上换算成 **2537**，
     * 而实测棋盘方块底边是 **2570** —— 常量比真实棋盘**还高 33px**，
     * 于是既留了空隙、又允许盖住棋盘，两个毛病同时存在 ✗
     *
     * <p>取值优先级：
     * <ol>
     *   <li>{@link BoardEdge} 实测（有截图帧时最准）</li>
     *   <li>实测比例兜底 {@link #BOARD_BOTTOM_RATIO}（无帧时也不会错太多）</li>
     * </ol>
     */
    private int boardBottomY() {
        // ⭐⭐⭐ v2.33【用户 2026-10-26 核对标注图后确认】：
        //   「棋盘底边位置对的啊，为什么悬浮窗顶边不棋盘底边对齐？」
        //
        //   实测（1280×2772 探索地图，网格线检测验证）：
        //     棋盘 5 行的 6 条横线 = 1683 / 1854 / 2025 / 2195 / 2366 / **2537**
        //     间距 171 完全均匀 ⇒ **棋盘底边 = 2537**
        //   而 devY(1722) 恰好 = 2537 ✓ 常量是对的，别再用 0.9289 那个错比例。
        //
        //   ⇒ 顶边对齐棋盘底边 2537。
        //   ⭐ v2.34：**优先用 BoardEdge 实测**（进图第一张后自动对齐），
        //      拿不到帧才退回 devY(1722) 常量。
        // !! v2.91【实测值必须校验】—— 用户 2026-11-01：
        //   「自动吸附到棋盘下面，为什么吸附到的实际位置和真机上不一样？」
        //   真机铁证：在「世界图鉴」界面时 bar 被吸到 参考 y 1369~1469
        //     （应该在 1716~1816）—— 骑在棋盘上；
        //     几何日志：设备 顶=1831 lp.y=534 => boardBottomY() 回了 1831，
        //     而 devY(1722) 应该是 2405。
        //   病：measuredBoardBottom() 是 BoardEdge 从**当前画面**量棋盘底边，
        //     可当前画面根本不是地图（世界图鉴/公会/背包）=> 量出来的是垃圾值，
        //     却被无条件当成真值 => 悬浮条被吸到莫名其妙的地方 X
        //   修：实测值与常量 devY(1722) 相差超过 **80 设备 px** 就判为不可信，
        //     退回常量 ✓（正常地图上实测与常量本来就只差几 px）
        int measured = measuredBoardBottom();
        int _refBottom = RefMapper.devY(BOARD_Y1_REF);
        if (measured > 0 && Math.abs(measured - _refBottom) <= 80) {
            return measured;
        }
        if (measured > 0) {
            AppLog.i("[ovl] 实测棋盘底=" + measured + " 与常量 " + _refBottom
                    + " 相差过大（多半不在地图界面）=> 退回常量");
        }
        return _refBottom;
    }

    private int anchorY(int usableH) {
        // v2.36 用户决定 2026-10-26：「记忆位置也没用了吧」
        //   ⇒ 对，有自动对齐后**记忆位置失效**（每次进图都会被拉回棋盘底边）。
        //   ⇒ 删掉记忆分支，永远顶边锚定棋盘底边：
        //      顶边 = boardBottomY()（BoardEdge 实测 / devY(1722) 兜底）
        //      展开时高度往下长，顶边不动 ✓
        int h = measureBarHeight();
        int topY = boardBottomY();
        return Math.max(0, usableH - (topY + h));
    }

    /** View 在父容器里的下标（-1 = 不在） */
    private int childIndexOf(android.view.ViewGroup g, android.view.View v) {
        if (g == null || v == null) {
            return -1;
        }
        for (int i = 0; i < g.getChildCount(); i++) {
            if (g.getChildAt(i) == v) {
                return i;
            }
        }
        return -1;
    }

    private void settlePosition() {
        if (bar == null || lp == null) {
            return;
        }
        // ⭐ v2.13：**撤掉闭环校准**（用户 2026-10-26 定案方案 A）。
        //   校准会自我振荡：lp.y 一变 → 窗口 parent 高度在 2720/2772 间切换
        //   → 读到的真实坐标跟着跳 → 又改 lp.y …… 日志实证在 2499/2575 之间反复横跳 ✗
        //   ⇒ 回到最朴素的做法：按固定锚点摆一次就完事，不再追问真实坐标。
        int[] rs = realScreen();
        int sh = rs[1];
        // !! v2.92c：这里原来是 anchorY(sh - nav())（可用区），会和上面 line 982 的
        //   物理屏高口径**打架**；而且本函数**后执行**、直接把 lp.y 覆盖掉
        //   => 实测 lp.y 恒为 0 => 悬浮条被压到屏幕最底（用户：位置还是错的）
        //   统一成**物理屏高**（与 Gravity.BOTTOM 的实际基准一致）✓
        int offY = anchorY(sh);
        if (lp.y != offY) {
            lp.y = offY;
            try {
                wm.updateViewLayout(bar, lp);
            } catch (Throwable ignored) {
            }
        }
    }

    private void showMoreMenu() {
        try {
            LinearLayout box = new LinearLayout(this);
            box.setOrientation(LinearLayout.VERTICAL);
            GradientDrawable g = new GradientDrawable();
            g.setColor(BAR_BG);
            g.setCornerRadius(dp(14));
            g.setStroke(dp(1), BAR_LINE);
            box.setBackground(g);
            box.setPadding(dp(6), dp(6), dp(6), dp(6));

            box.addView(menuItem("张数：" + MAP_LABELS[choiceIdx], () -> {
                choiceIdx = (choiceIdx + 1) % MAP_LABELS.length;
                Prefs.setMapsChoice(this, choiceIdx);
                AppLog.i("[ovl] 张数 ⇒ " + MAP_LABELS[choiceIdx]);
                if (btnCount != null) {
                    btnCount.setText(MAP_LABELS[choiceIdx]);
                }
            }));
            String logLabel = (logForce == null) ? "日志行：自动"
                    : (logForce ? "日志行：强制开" : "日志行：强制关");
            box.addView(menuItem(logLabel, () -> {
                logForce = (logForce == null) ? Boolean.TRUE
                        : (logForce ? Boolean.FALSE : null);
                AppLog.i("[ovl] 日志行 " + (logForce == null ? "恢复自动"
                        : (logForce ? "强制显示" : "强制隐藏")));
                applyMode();
            }));
            box.addView(menuItem("重新对齐棋盘底边", () -> {
                // v2.36：记忆已废弃 ⇒ 这个菜单项改成"立刻强制对齐一次"
                boardBottomCache = -1;          // 清缓存，强制重新检测
                boardBottomAt = 0L;
                autoAlignedOnce = false;
                settlePosition();
                AppLog.i("[ovl] 手动重新对齐 ⇒ 棋盘底边=" + boardBottomY());
            }));
            box.addView(menuItem("反馈（打包日志）", () -> {
                AppLog.i("[ovl] 反馈 ⇒ 打包日志 + 机型信息 + 现场帧");
                final Context cc = getApplicationContext();
                new Thread(() -> {
                    try {
                        Feedback.collectAndShare(cc);
                    } catch (Throwable t) {
                        AppLog.i("[ovl] 反馈异常：" + t);
                    }
                }, "ovl-feedback").start();
            }));
            box.addView(menuItem("收起", () -> setExpanded(false)));

            final android.widget.PopupWindow pw = new android.widget.PopupWindow(box,
                    android.view.ViewGroup.LayoutParams.WRAP_CONTENT,
                    android.view.ViewGroup.LayoutParams.WRAP_CONTENT, true);
            pw.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(0x00000000));
            pw.setOutsideTouchable(true);
            pw.setClippingEnabled(true);
            // 菜单挂在气泡**上方**（条子在屏幕底部，往下弹会被切掉）
            MENU_REF = pw;
            pw.showAsDropDown(bubble, 0, -bubble.getHeight() - dp(190));
            AppLog.i("[ovl] 长按 ⇒ 展开更多菜单");
        } catch (Throwable t) {
            AppLog.i("[ovl] 菜单弹出失败：" + t);
        }
    }

    /** 菜单里的一行（高 40dp）；点击后由调用方关闭菜单 */
    private TextView menuItem(String label, Runnable action) {
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextColor(TXT_CHIP);
        t.setTextSize(TypedValue.COMPLEX_UNIT_PX, RefMapper.devLen(30));
        t.setIncludeFontPadding(false);
        t.setGravity(android.view.Gravity.CENTER_VERTICAL);
        t.setPadding(dp(16), 0, dp(20), 0);
        GradientDrawable g = new GradientDrawable();
        g.setColor(0x00000000);
        g.setCornerRadius(dp(10));
        t.setBackground(g);
        t.setMinimumHeight(dp(40));
        t.setOnClickListener(v -> {
            try {
                action.run();
            } finally {
                android.widget.PopupWindow pw = MENU_REF;
                if (pw != null) {
                    pw.dismiss();
                    MENU_REF = null;
                }
                keepAlive();
            }
        });
        return t;
    }

    /** 当前打开的菜单（点了任意一项后关闭；静态引用避免层层传参） */
    private static android.widget.PopupWindow MENU_REF;

    /**
     * 按当前状态重设按钮行高度。
     *
     * <p>展开 + 有日志行 ⇒ 56（日志 34 + 按钮 56 = 90 预算）
     * <p>其余（收起 / 空闲不露日志）⇒ 44（只剩一枚胶囊的高度）
     *
     * <p>⚠ 高度必须**显式给**：靠 chip 的 padding 隐式撑会随样式漂移，
     * v2.02 首装就因此把条子撑到 97、顶边越过棋盘 124px。
     */
    private void addBtnRow() {
        if (bar == null || btnRow == null) {
            return;
        }
        try {
            bar.removeView(btnRow);
        } catch (Throwable ignored) {
        }
        // ⚠⚠⚠ v2.28 找到「行与行重叠」的根因：
        //   日志行高 = LOG_ROW_H_REF(44) 参考 px，按钮行高 = 56 参考 px，
        //   两者相加 100 参考 px；而 bar 的**实测高度只有 90 设备 px**（≈76 参考）。
        //   ⇒ 内容比窗口高 ⇒ LinearLayout 把两行压扁、互相重叠 ✗
        //   修：bar 的高度必须显式包含两行之和（日志行 + 按钮行），别只给按钮行。
        int btnH = (expanded && logMode) ? 56 : (expanded ? 50 : 44);
        int logH = (expanded && logMode) ? LOG_ROW_H_REF : 0;
        // !! v2.92【夹缝不够就按比例压矮】—— 用户 2026-11-01：进图后吸附位置还是错的
        //   本机实测（1280x2640 @520dpi）：
        //     物理 2640 − 手势条 156 = 可用区 2484
        //     棋盘下沿 devY(1722) = 2405  =>  夹缝只有 79 设备 px
        //     而两行 44+56=100 参考 px = 119 设备 px
        //   => 119 > 79：要么顶边压棋盘、要么底边溢出可用区
        //      （实测落到 参考 y 1742~1842，比设计值 1716~1816 低 26）
        //   原设计假设夹缝 94 参考 px（1280x2772 那类机器），这台只有 66。
        //   修：装不下就按比例压矮两行，保证 顶边=棋盘下沿 且 底边≤可用区底。
        try {
            int _avail = realScreen()[1] - nav() - RefMapper.devY(BOARD_Y1_REF);
            int _need = RefMapper.devLen(logH + btnH);
            if (_avail > 0 && _need > _avail) {
                double _r = (double) _avail / (double) _need;
                int _log2 = (int) Math.round(logH * _r);
                int _btn2 = (int) Math.round(btnH * _r);
                if (_log2 < 24) { _log2 = 24; }
                if (_btn2 < 30) { _btn2 = 30; }
                AppLog.i("[ovl] 夹缝不足 " + _avail + " < 需要 " + _need
                        + " => 压矮 日志" + logH + "->" + _log2
                        + " 按钮" + btnH + "->" + _btn2);
                logH = _log2;
                btnH = _btn2;
            }
        } catch (Throwable ignored) {
        }
        boolean wide = expanded;
        int w = wide
                ? Math.max(1, realScreen()[0] - RefMapper.devX(40))
                : LinearLayout.LayoutParams.WRAP_CONTENT;

        // ⭐ 关键：**父级 bar 也要有确定宽度**，否则里面 MATCH_PARENT 的日志行无解（=0 宽）。
        bar.setPadding(RefMapper.devLen(10), 0, RefMapper.devLen(10), 0);
        LinearLayout.LayoutParams blp = wide
                ? new LinearLayout.LayoutParams(w, LinearLayout.LayoutParams.WRAP_CONTENT)
                : new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.WRAP_CONTENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT);
        bar.setLayoutParams(blp);

        // ⭐ v2.41 按钮行插到**第 0 行**（上方），日志行在下面
        bar.addView(btnRow, new LinearLayout.LayoutParams(
                wide ? LinearLayout.LayoutParams.MATCH_PARENT : w, RefMapper.devLen(btnH)));
        try {
            bar.removeView(btnRow);
            bar.addView(btnRow, 0, new LinearLayout.LayoutParams(
                    wide ? LinearLayout.LayoutParams.MATCH_PARENT : w, RefMapper.devLen(btnH)));
        } catch (Throwable ignored) {
        }

        // ⭐ 关键：**bar 高度 = 日志行 + 按钮行**（展开态两行都要算进去）
        if (wide) {
            blp.height = RefMapper.devLen(logH + btnH);
            bar.setLayoutParams(blp);
        }

        // ⚠⚠⚠ v2.43 真机 bug（用户 2026-10-26「又完全不显示日志了」）：
        //   窗口宽已修到 1233，但 tvLog.getWidth() 仍是 **0** ✗
        //   —— MATCH_PARENT 在这个「先加日志、后插按钮到第0行」的顺序下没被解析。
        //   ⇒ 直接给 tvLog 一个**明确宽度**（等于 bar 内容宽），不依赖 MATCH_PARENT。
        if (tvLog != null) {
            LinearLayout.LayoutParams tlp = (LinearLayout.LayoutParams) tvLog.getLayoutParams();
            if (tlp == null) {
                tlp = new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT, RefMapper.devLen(LOG_ROW_H_REF));
            }
            if (wide) {
                tlp.width = Math.max(1, w - RefMapper.devLen(20));   // 扣 bar 的左右 padding
                tlp.height = RefMapper.devLen(LOG_ROW_H_REF);
            }
            tvLog.setLayoutParams(tlp);
        }

        // ⚠⚠⚠ v2.39 修崩溃（NPE，AndroidRuntime FATAL）：
        //   v2.37 在这里直接读 `lp.height`，但 addBtnRow() 在 **buildView 阶段**
        //   （bar 还没 addView）就被调用 ⇒ 那时 bar.getLayoutParams() 是 null
        //   ⇒ `line 1491: Attempt to read from field LayoutParams.height on a null object`
        //   ⇒ **整个 OverlayService 起不来**（悬浮条彻底消失）✗✗
        //
        //   修：① lp 可能为 null ⇒ 判空；② bar 还没布局完 ⇒ 只设 View 的 LayoutParams，
        //       窗口高度留给 afterLayout（那时 lp 一定在）。
        // v2.42 真机 bug（用户 2026-10-26「又完全不显示日志了」）：
        //   诊断实证：宽=0 视口=1234 原文px=642 字=23/23
        //   —— 文字有（642px/23 字），但 tvLog.getWidth()=0 => 画不出来。
        //   根因：窗口 lp.width 从没设过（一直 WRAP_CONTENT），
        //         按钮行插到第 0 行后窗口宽度由按钮行决定（实测 351px），
        //         日志行 MATCH_PARENT 拿不到确定宽度 => 塌成 0。
        //   修：同时把窗口 lp.width 设成确定值（与 bar 同宽）。
        try {
            if (lp != null && bar.getParent() != null) {
                int wantH = RefMapper.devLen(logH + btnH);
                // ⚠⚠ v2.47 真机 bug（用户 2026-10-26「收起后多余的条没隐藏」）：
                //   旧写法只在 wide 时设 lp.width = 1233，**收起时没恢复**
                //   ⇒ 窗口宽度一直 1233，收起后仍留一条横幅 ✗
                //   ⇒ 收起必须把 lp.width / lp.height 都恢复成 WRAP_CONTENT。
                int wantW2 = wide ? w : LinearLayout.LayoutParams.WRAP_CONTENT;
                int wantH2 = wide ? wantH : LinearLayout.LayoutParams.WRAP_CONTENT;
                boolean changed = false;
                if (lp.height != wantH2) {
                    lp.height = wantH2;
                    changed = true;
                }
                if (lp.width != wantW2) {
                    lp.width = wantW2;
                    changed = true;
                }
                if (changed) {
                    wm.updateViewLayout(bar, lp);
                }
            }
        } catch (Throwable ignored) {
        }
    }

    private void applyMode() {
        if (bar == null) {
            return;
        }
        // ⭐⭐ 2026-09-30 修（用户原话「悬浮窗的启动按钮呢？？」）：
        //   张数/▶ **只能**看「展开 + 没在跑」，绝不能再挂在 logForce 上！
        //   旧写法 `(expanded && !wantLog)` 的后果：长按气泡切日志时顺手把 ▶ 和 张数 藏掉，
        //   而长按在真机上**极容易在拖动时误触**（拖动起步窗口 500ms/6dp，手一抖就是长按）
        //   ⇒ 用户看到的就是「启动按钮不见了」，而条子上只剩 ■ ✕，完全无从下手。
        //   实测复现：长按一次后 logcat 打「强制隐藏」，条子从 `● MGAS|■|✕` 变回
        //   `● MGAS|连刷|▶|■|✕`（即在此之前 ▶ 是被 logForce 藏掉的）。
        //   ⇒ 按钮可见性 = 运行状态；`logForce` 只管**日志行自己**露不露脸（见下）。
        // ⚠ 判据必须是 isRunningState() 而不是「wantLog」：跑起来才把 ▶ 收掉（跑着也不能重复启动）。
        // ⚠ 「准备启动」提醒挂起时（hintUntilStart）**强制**露日志行 —— 那句提醒就是「点 ▶ 启动」，
        //   要是被收起态/强制隐藏吃掉，用户就找不到下一步了。
        // ⚠ 用户口径（2026-10-19）：「悬浮窗太窄了，看不到完整文字了，日志也看不到」
        //   ⇒ **展开态 = 全宽 + 日志行常驻**（上一轮为了"简洁"把它藏了，结果看不到日志 ✗）
        //   简洁要做在**按钮数量**上（6 个 → 1 个主按钮 + 1 个胶囊），不是砍掉日志行。
        boolean showLog = hintUntilStart
                || ((logForce != null) ? logForce : expanded);
        logMode = showLog;
        int vis = expanded ? View.VISIBLE : View.GONE;
        // 上行：日志行（展开时默认露脸；收起态只留气泡，条子最矮）
        tvLog.setVisibility(showLog ? View.VISIBLE : View.GONE);
        // ⭐ 收起态：气泡退化成**一颗纯色小圆点**（无文字、无背景框）。
        //   ⚠ 用户口径（2026-10-19）：「收起后 MGAS 文字显示不全」「收起后不要有黑框」
        //   ⇒ 收起时根本不该有文字：一颗 18dp 的圆点 + 状态色，
        //     点它展开、拖它移动 —— 功能一点没少，视觉噪音归零。
        // ⚠ 收起/展开都显示 "MGAS" 胶囊 —— 收起态也是它，只是不带按钮
        bubble.setText(bubbleOriginText);
        bubble.setPadding(RefMapper.devLen(11), 0, RefMapper.devLen(13), 0);
        bubble.setBackground(UiKitPill());
        bubble.setCompoundDrawablesWithIntrinsicBounds(
                dotDrawable(RefMapper.devLen(7)), null, null, null);
        bubble.setCompoundDrawablePadding(RefMapper.devLen(6));
        // ⭐ 精简版：下行只有【状态胶囊 + 一个主按钮】
        //   待机 ⇒ 启动（青蓝渐变）；跑起来 ⇒ 停止（红）
        //   张数/反馈/✕ 都收进长按菜单，不再常驻
        boolean idle = !isRunningState();
        btnStart.setVisibility(expanded && idle ? View.VISIBLE : View.GONE);
        btnStop.setVisibility(expanded && !idle ? View.VISIBLE : View.GONE);
        btnCount.setVisibility(View.GONE);
        btnClose.setVisibility(View.GONE);
        // ⭐⭐ 2026-10-04 用户口径：「悬浮窗的反馈按钮只有展开的时候才能看到，和启动停止那些类似，
        //   **不要关闭了也能看到**」⇒ 反馈与 ■/✕ **同类**：只在展开态露出。
        //   ⚠ 原来 `btnFb` 建好之后**从没调过 setVisibility** ⇒ 收起态也一直露着（用户看到的 bug）✗
        btnFb.setVisibility(View.GONE);
        if (!showLog) {
            // ⚠⚠ v2.12：收起时**彻底停掉跑马灯并清空绘制内容**。
            //   旧版只 setVisibility(GONE)，但 MarqueeView 自己的 postDelayed(step)
            //   还在跑（它只判 isShown()，而窗口缩小那一刻 isShown 仍为 true）
            //   ⇒ 最后一帧的文字被画进窗口缓冲、随窗口缩小时**留在屏幕上**——
            //     用户看到的就是「收起后还有日志文字残留」✗
            tvLog.stopAndClear();
        } else if (expanded && !logMode) {
            tvLog.showActionOnly();
        }
        if (btnClose != null) {
            // 展开时 ✕ = 收起按钮；日志行隐藏时它同时兼任"显示日志"
            btnClose.setText(expanded ? "✕" : "✕");
        }
        applyBarBg();
        addBtnRow();
        // v2.40 补：applyLogText() 是唯一往 tvLog 写文字的入口，
        //   但它不在 applyMode 的调用链里，只在 onLog/paint 等事件时叫。
        //   结果：展开时日志行可见、有高度、但 text 为空 => 什么都看不见。
        //   诊断日志实证 原文px=0。这里补一次。
        if (showLog) {
            applyLogText();
        }
        bar.post(this::afterLayout);
        bar.post(this::settlePosition);
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
            // ⚠⚠⚠ v2.14 真机 bug（用户 2026-10-26「收起还是有日志的字」）：
            //   showLog = hintUntilStart || (logForce ?? expanded)
            //   而「准备启动」的提示会把 hintUntilStart 置 true ⇒ **收起也被强制露出日志行**
            //   ⇒ 屏幕上留着一截「已就…」的字 ✗
            //   用户口径：**主动收起就是彻底收起**，提示语不该把条子撑开。
            //   ⇒ 收起时一并撤掉提示（下次展开/启动会重新给）。
            hintUntilStart = false;
            hintText = null;
        }
        // ⚠⚠⚠ 顺序很关键（v2.02 实测「启动后往下位移」就是这个）：
        //   settlePosition() 要按**新的高度**算锚点，而新高度要等 applyMode() 改完
        //   布局之后才有 ⇒ 必须 **先 applyMode，再在布局回调里 settlePosition**。
        //   旧顺序（先 settle）拿到的是收起态的高度，算出来永远差一截。
        applyMode();
        if (bar != null) {
            // 双保险：立刻定一次（用旧高度也能先摆对）＋ 布局完成后再定一次（用真高度）
            settlePosition();
            bar.post(() -> {
                settlePosition();
                bar.post(this::settlePosition);
            });
        }
        if (ex) {
            AppLog.i("[ovl] 展开（两行：上行=当前行动，下行=按钮）");
            keepAlive();
        }
    }

    // ───────────────────────── 日志行 ─────────────────────────

    /** AppLog 每来一条就走这里（**已回到主线程**，见 onCreate 的 listener）。
     *
     *  ⭐ 2026-09-30：**只收 Python 明确标了 `› ` 的「当前行动」**，其余（开发日志）直接丢
     *  —— 它们留在界面控制台与 logcat 里给开发看，不占悬浮条那一行（见上面 UI_MARK 段）。
     */
    private void onLog(String line) {
        if (line == null) {
            return;
        }
        String s = sanitize(line);
        if (!s.startsWith(UI_MARK)) {
            return;                     // 开发日志 ⇒ 不进悬浮条（不碰 action / logBuf）
        }
        String act = s.substring(UI_MARK.length()).trim();
        if (act.isEmpty()) {
            return;
        }
        logBuf.addLast(act);            // 历史只留"行动"，往回翻才不会被噪声淹没
        while (logBuf.size() > LOG_KEEP) {
            logBuf.removeFirst();
        }
        if (logBack > logBuf.size()) {
            logBack = logBuf.size();
        }
        if (logBack == 0) {
            action = act;
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

    // ── 「当前的行动」（悬浮条日志行）──────────────────────────────
    // ⭐⭐ 2026-09-30（用户口径）：悬浮条上的日志是**给用户看的** ——
    //   「用户只需要知道现在在干什么」，不需要看「识别了 N 条 / 用时 xx ms / band 区间 /
    //   x0 y0 格距 / cost 步数」这些。
    //
    //   旧实现是「从原始日志流里**猜**哪条是行动」：`describeAction()` 一堆正则 + 最后一条
    //   `if (len <= 46 && 无 '{') 照播` 兜底 ⇒ 任何短技术行都漏上悬浮条
    //   （`识别棋盘：35 格`、`分类兜底：低门槛重试拿到 30 格`、`自动跳过已勾选` …），
    //   2026-09-29 为它打的 band-aid 就有好几处，属于典型的"在错的层上修"。
    //
    //   现在换成**显式契约**（一处定义、两端生效、零猜测）：
    //     · Python `explore_loop.status()` 打印 `› <一句人话>`  ⇒ **只有它**进悬浮条；
    //     · 其余所有 print()/say()（开发日志）⇒ 只进界面控制台与 logcat。
    //
    //   ⚠ 想加/改悬浮条文案 ⇒ **改 Python 的 status() 调用**，不要回来在这里加正则。
    /** Python 侧「当前行动」的传输标记（见 explore_loop.UI_MARK）。只用于识别，不画到屏幕上。 */
    private static final String UI_MARK = "\u203a";      // ›

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
        // ⚠⚠⚠ v2.29 修「启动后日志行变小/被遮挡」：
        //   旧顺序是 setExpanded(true) → logForce=null → applyMode()。
        //   但 setExpanded 内部**已经调过一次 applyMode()**，那时 logForce 还是旧值
        //   （可能是 FALSE）⇒ showLog=false ⇒ logMode=false ⇒ addBtnRow 按"无日志行"算高度
        //   （logH=0）⇒ bar 只给按钮行高度 ⇒ **日志行被压成 0 高/重叠** ✗
        //   ⇒ 必须**先清 logForce，再 setExpanded**，让那次 applyMode 就算对。
        logForce = null;                 // 交回自动：运行中必然显示日志
        setExpanded(true);
        applyMode();                     // 已展开时 setExpanded 会 early-return，这里补一次
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
        // ⭐ v1.78：收工日常五颗勾选（= PC 窗口上那一排，语义与默认值都对齐 ✓）
        //   ⚠ 全部从 Prefs 读 ⇒ 界面上勾了这里就生效（不会「勾了没反应」✗）
        final boolean guildTasks = Prefs.guildTasks(this);
        final boolean guildAlchemy = Prefs.guildAlchemy(this);
        final boolean guildIntel = Prefs.guildIntel(this);
        final boolean recruitFree = Prefs.recruitFree(this);
        final boolean adFree = Prefs.adFree(this);
        final boolean dailyFirst = Prefs.dailyFirst(this);   // ⭐ v1.91 日常前置
        // ⭐⭐ 2026-10-01 修（用户报「体力不够 50 怎么还去点进入地图」）：
        //   **进图体力下限原来写死 25** ⇒ 连刷模式下也是 25 ⇒ 29 体力照样进图 ✗
        //   （真机实证：`进图前体力 29` → 进图扣 25；而日志还写着「连刷下限」✗）
        //   PC 侧 GUI 的规矩是：**连刷 <50 就停、跑单张 <25 才拦**（README/交接文档一致 ✓）
        //   ⇒ 这里按同一个规矩算，并打进启动日志（以后一眼能看到门限 ✓）
        final int minStamina = (maps == MAPS_CONTINUOUS) ? 50 : 25;
        AppLog.i("▶ 启动探索：" + MAP_LABELS[choiceIdx]
                + "（maps=" + maps + "，进图 " + STAMINA_PER_MAP + " 体力/张，"
                + "体力下限 " + minStamina + "）"
                + "  自动补给=" + autoSupply + "  升星=每 " + bagEvery + " 张");
        // ⭐ v1.78：把五颗勾选也打进启动日志 —— 以后一眼能看到「这次做不做日常」✓
        AppLog.i("   收工日常：派遣=" + guildTasks + " 炼金=" + guildAlchemy
                + " 情报=" + guildIntel + " 免费招募=" + recruitFree
                + " 免广告=" + adFree + " 日常前置=" + dailyFirst);
        new Thread(() -> {
            // ⭐ v0.26（用户口径）：**悬浮条 ▶ 不再自动切游戏前台**。
            //   正常流程 = 在 MGAS 点「▶ 准备启动」（那里负责切游戏 + 提醒）→ 人在游戏选图
            //   界面 → 点悬浮条 ▶ 开跑；此时再切一次纯属多余。
            //   若人不在游戏（比如停在 MGAS 界面）⇒ Python `self_ui_hits()` 防护会判出
            //   "画面是 MGAS 自己" 并明确报错（不会乱点）⇒ 切回游戏再点 ▶ 即可。
            // ⚠ 参数顺序必须与 explore_android.start 的形参一致（**15 个位置参数**）：
            //   maps, max_round, deadline, min_stamina, tag, opt_solver,
            //   bag_every, save_first, stop_at_5am, auto_supply,
            //   guild_tasks, guild_alchemy, guild_intel, recruit_free, ad_free
            //   ⚠ **只能往后追加**（中间插一个会让所有老调用点静默错位 ✗ ——
            //     本项目历史上踩过一次：`start(**kw)` 收不到位置参数）
            // ⚠ v1.91 追加第 16 个位置参数 `dailyFirst`（**只能往后追加**）
            // ⭐⭐⭐ v2.26 用户反馈（2026-10-26）：「怎么启动不会自动回到游戏了？」
            //   根因：onStart() 只在**权限缺失**时 startActivity 跳设置页，
            //   正常启动路径**从来没调用过 bringGameFront()** ✗
            //   ⇒ 点完 ▶ 人还停在 MGAS 界面，脚本却在对着 App 截图（会把
            //     「开始冒险/进入地图」这些文字当成游戏面板去点）。
            //   ⇒ 真启动前**先切回游戏**，与 MainActivity.pyExploreStart 同一口径 ✓
            String front = bringGameFront();
            AppLog.i("[ovl] 启动前切游戏：" + front);
            try {
                Thread.sleep(600);          // 给系统一点时间把游戏拉到前台
            } catch (InterruptedException ignored) {
            }
            // ⭐ v2.131 追加第 17~20 个位置参数（预言石碑四个「遇到就停」，
            //   **只能往后追加**）：stopLucky, stopPeace, stopElemPurple, stopElemOrange
            String r = PyBridge.call("start", maps, 45, 900, minStamina, "", true,
                    bagEvery, true, false, autoSupply,
                    guildTasks, guildAlchemy, guildIntel, recruitFree, adFree,
                    dailyFirst,
                    Prefs.stopLucky(this), Prefs.stopPeace(this),
                    Prefs.stopElemPurple(this), Prefs.stopElemOrange(this));
            AppLog.i("▶ " + r);
        }, "ovl-start").start();
    }

    /**
     * 拖动手柄（气泡）：左右上下随便放，避免挡住游戏里的点击点。
     * ⚠ `Gravity.BOTTOM` ⇒ `lp.y` 是**离屏幕底的距离**：手指往下 `dy>0` ⇒ y **变小**。
     */
    private void installDrag(View handle) {
        final android.os.Handler handleH = new android.os.Handler(getMainLooper());
        final View handleView = handle;
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
                        // ⚠⚠ 必须**吃掉 DOWN**（return true）。
                        //   旧写法 return false 把事件交回 View ⇒ View 自己的长按检测接管
                        //   ⇒ 想拖动时稍慢一点就弹「更多菜单」（真机实测：一次 swipe 直接弹菜单，
                        //     条子没动）✗
                        //   ⇒ 改成自己管：DOWN 吃掉 → MOVE 拖 → UP 未移动则当点击 →
                        //     长按用 postDelayed 自己实现（500ms 未移动才弹菜单）。
                        handleView.postDelayed(longPress, android.view.ViewConfiguration
                                .getLongPressTimeout());
                        return true;
                    case MotionEvent.ACTION_MOVE: {
                        int dx = (int) (e.getRawX() - rawX);
                        int dy = (int) (e.getRawY() - rawY);
                        if (Math.abs(dx) > dp(6) || Math.abs(dy) > dp(6)) {
                            moved = true;
                        }
                        if (moved) {
                            int sw = RefMapper.screenW();
                            // ⚠⚠⚠ 基准必须是**可用区高**（物理屏 − 手势条），不是物理屏！
                            //   Gravity.BOTTOM 下 lp.y 是"离窗口可用区底边"的距离，
                            //   本机实测 parent 高 2720（物理 2772 − 手势条 52）。
                            //   v2.05 这里用了 RefMapper.screenH()=2772 ⇒ 上限多给 52px
                            //   ⇒ **能把它往上托 52px、越过限制线盖住棋盘**（用户原话
                            //   「我开启悬浮条后，还能往上托悬浮条」就是这个）。
                            int sh = Math.max(1, RefMapper.screenH() - nav());
                            int bw = Math.max(barMaxW, bar != null ? bar.getWidth() : 0);
                            if (bw <= 0) {
                                bw = dp(64);
                            }
                            // ⚠ 竖直夹取用**当前高度**（不是"见过的最大高度"）。
                            //   旧写法用 barMaxH 是怕"收起时按 56 夹、一展开顶边就掉"，
                            //   但现在展开有 settlePosition 重新锚顶（见 anchorY），那个担心已不成立；
                            //   反过来用 barMaxH 会让收起态一拖动就往下跳（bh=106 却只有 52 高）。
                            // ⚠⚠ 这里**必须用设备像素**，不能用 dp()！
                            //   本机 520dpi ⇒ dp(44) = 143px，比条子本身（52px）还大 3 倍
                            //   ⇒ safeBottom 被压成 40 ⇒ 一拖动就把条子往下挤 91px（实测）✗
                            int bh = (bar != null && bar.getHeight() > 0)
                                    ? bar.getHeight() : RefMapper.devLen(44);
                            if (bh <= 0) {
                                bh = RefMapper.devLen(44);
                            }
                            lp.x = Math.max(0, Math.min(Math.max(0, sw - bw), downX + dx));
                            // ⭐⭐ 竖直方向**夹住**：顶边绝不允许高过棋盘下沿（BOARD_Y1_REF）
                            //   —— 涂平会把悬浮条那块**抹成纯色**：盖住棋盘 ⇒ 那几格既识别不到
                            //   也点不动（2026-09-29 实测被拖到参考 y 422~499，整段画面被抹掉）。
                            //   水平方向不限制（在底部那条空档里左右挪是安全的）。
                            //   `Gravity.BOTTOM` ⇒ lp.y 是"离底距离"：top = sh − lp.y − bh ≥ devY(1722)
                            // ⭐ 恢复硬约束①：顶边**不许高过** devY(1722)（棋盘下沿）。
                            //   v2.07 回退——上一版放开后条子能被推到棋盘上，
                            //   涂平会把那几格抹成纯色 ⇒ 既识别不到也点不动。
                            // ⭐⭐⭐ v2.30【用户口径 2026-10-26】：「悬浮窗还是不能乱动啊，
                            //   挡住棋盘就看不到很多东西了」
                            //   ⇒ **恢复硬约束**：顶边不许高过棋盘下沿 devY(1722)。
                            //
                            //   为什么必须限：涂平会把悬浮条那块**抹成纯色**（见 FrameStore.maskOverlay），
                            //   盖住棋盘 ⇒ 那几格既识别不到、也点不动。
                            //   用户能在底部空白区自由左右/上下微调，但不能上到棋盘里 ✓
                            // 上限 = 实测棋盘底边（再往上就盖住棋盘了）
                            // v2.36：**放开上限**（有自动对齐兜底，不必靠限制防永久遮挡）
                            //   只夹屏幕边界，别拖出屏幕外找不回来。
                            int safeBottom = Math.max(0, sh - bh - dp(2));
                            lp.y = Math.max(0, Math.min(safeBottom, downY - dy));
                            try {
                                wm.updateViewLayout(bar, lp);
                            } catch (Throwable ignored) {
                            }
                            bar.post(OverlayService.this::afterLayout);   // 涂平矩形跟着走 ✓
                        }
                        return moved;
                    }
                    case MotionEvent.ACTION_UP:
                        handleView.removeCallbacks(longPress);
                        if (moved) {
                            // v2.36：只记 x（左边距有用），y 不再记忆
                            //   —— 顶边由自动对齐说了算
                            Prefs.setOverlayX(OverlayService.this, lp.x);
                            AppLog.i("[ovl] 位置已移动 x=" + lp.x + " y=" + lp.y
                                    + "（进图后会自动对齐棋盘底边）");
                        }
                        if (!moved) {
                            // 没拖动 ⇒ 当点击（展开/收起）
                            v.performClick();
                        }
                        return true;
                    case MotionEvent.ACTION_CANCEL:
                        handleView.removeCallbacks(longPress);
                        return true;
                    default:
                        return moved;
                }
            }

            /** 500ms 内没移动 ⇒ 长按：弹「更多菜单」 */
            private final Runnable longPress = new Runnable() {
                @Override
                public void run() {
                    if (!moved) {
                        showMoreMenu();
                    }
                }
            };
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
    /** 状态胶囊左侧那颗色点（用 compound drawable，纯代码画一个圆） */
    /**
     * 更新状态色点。
     *
     * <p>⚠ 收起态与展开态的**点大小不同**（18 vs 7 参考 px），
     * 所以这里只改**颜色**，尺寸交给 applyMode 决定 —— 否则每次 tick 都会
     * 把收起态的圆点缩回 7px（真机可复现的"点忽大忽小"）。
     */
    private void paintDot(int color) {
        if (bubble == null) {
            return;
        }
        stateColor = color;
        int sizePx = RefMapper.devLen(expanded ? 7 : 18);
        GradientDrawable dot = new GradientDrawable();
        dot.setShape(GradientDrawable.OVAL);
        dot.setColor(color);
        dot.setSize(sizePx, sizePx);
        bubble.setCompoundDrawablesWithIntrinsicBounds(dot, null, null, null);
    }

    /** 气泡的原始文案（展开态用；收起态不显示文字） */
    private String bubbleOriginText = "MGAS";

    /** 当前状态色（paint() 里更新，收起态圆点用它） */
    private int stateColor = C_IDLE;

    /** 一颗实心圆 drawable（状态点 / 收起态圆点共用） */
    private GradientDrawable dotDrawable(int sizePx) {
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.OVAL);
        d.setColor(stateColor);
        d.setSize(sizePx, sizePx);
        return d;
    }

    /** 展开态气泡的胶囊底 */
    private GradientDrawable UiKitPill() {
        GradientDrawable g = new GradientDrawable();
        g.setColor(CHIP_BG);
        g.setCornerRadius(RefMapper.devLen(20));
        g.setStroke(dp(1), CHIP_LINE);
        return g;
    }

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
        // ⭐ 方案 A：状态**直接写在胶囊上**（不用回 App 才知道发生了什么）
        if ("run".equals(st)) {
            color = C_RUN;
            bubble.setText("MGAS");
        } else if ("lock".equals(st)) {
            color = C_LOCK;
            bubble.setText("MGAS");
        } else if ("err".equals(st)) {
            color = C_LOCK;
            bubble.setText("MGAS");
        } else {
            color = C_IDLE;
            bubble.setText("MGAS");
        }
        bubble.setTextColor(color);
        stateColor = color;
        paintDot(color);
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
        // ⭐ 2026-09-30 加：条子在屏幕上的**真实**位置（绝对坐标）。有它就能一眼看出
        //   blankRect 有没有对上（对不上 = 涂平跑偏 ⇒ 既没盖住自己、又抹了棋盘）
        if (bar != null && bar.getHeight() > 0) {
            int[] loc = new int[2];
            boolean ok = false;
            try {
                bar.getLocationOnScreen(loc);
                ok = true;
            } catch (Throwable ignored) {
            }
            sb.append("barOnScreen: ").append(ok
                    ? ("x " + loc[0] + "~" + (loc[0] + bar.getWidth())
                       + "  y " + loc[1] + "~" + (loc[1] + bar.getHeight()))
                    : "取不到（getLocationOnScreen 抛了）").append('\n');
        }
        sb.append("涂平记账: ").append(FrameStore.lastMaskInfo()).append('\n');
        if (tvLog != null) {
            sb.append("logW(dev): ").append(tvLog.getWidth()).append('\n');
            sb.append("logShown: ").append(tvLog.shownText()).append('\n');
            sb.append("logRoll: ").append(tvLog.debugRoll()).append('\n');
        }
        sb.append("action: ").append(action).append('\n');
        sb.append("logBack: ").append(logBack).append("  buf=").append(logBuf.size()).append('\n');
        List<String> tail = new ArrayList<>(logBuf);
        int from = Math.max(0, tail.size() - 12);
        sb.append("--- 最近 ").append(tail.size() - from).append(" 条「当前行动」---\n");
        for (int i = from; i < tail.size(); i++) {
            sb.append("  ").append(tail.get(i)).append('\n');
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
            paint.setTypeface(LOG_TF);          // 等宽、**常规字重**（用户口径「别加粗」，见 LOG_TF）
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
            // v2.44 真机 bug（用户「又完全不显示日志了」）：
            //   诊断实证 宽=0 视口=1234 原文px=642 字=23/23
            //   文字有、视口宽有，但 measured width = 0。
            //   根因：非 fill 分支 Math.min(avail, 文字宽)，而 avail 有时是 0
            //         => min(0, 642) = 0 => View 宽 0 => 画不出来。
            //   修：avail<=0 时退回文字宽；仍为 0 则给个保底宽度。
            // v2.46 真机（用户「日志显示不全」）：
            //   诊断实证 宽=166 视口=120 原文px=166 绘制px=120 字=6/7
            //   —— 宽度被卡在"文字宽"上（166），视口只有 120，字被截成 "MGAS ..."
            //   根因：非 fill 分支 Math.min(avail, 文字宽) 是"收缩到文字"逻辑，
            //         但我们的布局本来就给了 1209 的 LayoutParams.width，
            //         这里再 min 一次等于把它砍回文字宽 ✗
            //   修：**LayoutParams 给了确定宽就用它**，只有 WRAP_CONTENT 才按文字收缩。
            int lpW = (p != null) ? p.width : LinearLayout.LayoutParams.WRAP_CONTENT;
            int w;
            if (fill) {
                w = avail;
            } else if (lpW > 0) {
                w = lpW;                      // 布局已指定确定宽度 ⇒ 照用
            } else {
                int tw2 = (int) Math.ceil(textWidth());
                w = (avail <= 0) ? Math.max(1, tw2) : Math.min(avail, Math.max(1, tw2));
            }
            if (w <= 0) {
                w = RefMapper.devLen(200);
            }
            int h = (p != null && p.height > 0)
                    ? p.height : (int) Math.ceil(paint.descent() - paint.ascent());
            setMeasuredDimension(w, resolveSize(h, heightSpec));
        }

        /** 停掉动画并清空内容（收起态用；防窗口缩小时残留上一帧文字） */
        void stopAndClear() {
            removeCallbacks(step);
            text = "";
            prev = null;
            drawn = "";
            drawnPrev = "";
            roll = 1f;
            invalidate();
            requestLayout();
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

        /**
         * 视口宽（扣掉左右内边距）。
         *
         * <p>⚠⚠ v2.12：**首帧 getWidth() 还是 0**，那时 ellipsize 会把整句截成空/省略号，
         * 用户看到的就是「日志文字看不全」。⇒ 拿不到宽度时退回**父容器可用宽**。
         */
        private float viewW() {
            float w = getWidth();
            if (w <= 0) {
                android.view.ViewParent par = getParent();
                if (par instanceof android.view.View) {
                    android.view.View pv = (android.view.View) par;
                    w = pv.getWidth() - pv.getPaddingLeft() - pv.getPaddingRight();
                }
            }
            if (w <= 0) {
                // 最后兜底：整幅屏幕宽（总比 0 好，至少不会全截断）
                android.util.DisplayMetrics dm = getResources().getDisplayMetrics();
                w = dm.widthPixels;
            }
            return Math.max(0f, w - getPaddingLeft() - getPaddingRight());
        }

        /** 按当前宽度把"本句/上一句"都算成可绘制串（装不下 ⇒ 省略号收尾；⚠ 不左右滚） */
        private void remeasure() {
            float w = viewW();
            drawn = ellipsize(text, w);
            drawnPrev = ellipsize(prev, w);
            // 诊断：宽度与命中情况（只在内容变化时打，别刷屏）
            if (AppLog.DEBUG_LAYOUT) {
                AppLog.i("[marquee] 宽=" + Math.round(getWidth())
                        + " 视口=" + Math.round(w)
                        + " 原文px=" + Math.round(paint.measureText(text))
                        + " 绘制px=" + Math.round(paint.measureText(drawn))
                        + " 字=" + drawn.length() + "/" + text.length());
            }
            lastW = getWidth();
        }

        /**
         * 按宽度截断（装不下加省略号）。
         *
         * <p>⚠⚠ v2.18 换成**自己算**，不用 {@code TextUtils.ellipsize}：
         *   实测日志行窗口宽 1040px，而文字只用到约 800px 就被截 ⇒
         *   TextUtils 内部对 width 的处理（预留省略号宽度 + 浮点取整）偏保守，
         *   在我们的组合下会**多截掉一截**。
         *   这里用 measureText 逐字二分，宽度用满为止。
         */
        private String ellipsize(String s, float w) {
            if (s == null || s.isEmpty()) {
                return "";
            }
            float full = paint.measureText(s);
            if (w <= 0 || full <= w) {
                return s;
            }
            String ell = "…";
            float ew = paint.measureText(ell);
            if (w <= ew) {
                return ell;
            }
            // 二分找"能放下的最长前缀"
            int lo = 0, hi = s.length();
            while (lo < hi) {
                int mid = (lo + hi + 1) / 2;
                if (paint.measureText(s, 0, mid) + ew <= w) {
                    lo = mid;
                } else {
                    hi = mid - 1;
                }
            }
            return lo > 0 ? s.substring(0, lo) + ell : ell;
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
            // ⚠⚠⚠ v2.23 修「跑马灯一行字都没有」：
            //   旧逻辑只在 getWidth() != lastW 时重算。可 setLine() 常发生在**布局完成前**
            //   （那时 getWidth()=0 ⇒ drawn=""），之后宽度虽然变了，但
            //   lastW 也被 remeasure 记成了最终宽度 ⇒ 条件不再成立 ⇒ **永远不重算** ✗
            //   ⇒ 现在：**只要 drawn 空但有 text，就立刻重算**（幂等，多算一次无所谓）。
            if (getWidth() != lastW || (drawn.isEmpty() && !text.isEmpty())) {
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
