package com.fantasy.autoexplore;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * 界面设置项（持久化）—— 让**界面**和**悬浮条**用同一份设置。
 *
 * 为什么需要它：悬浮条上的 ▶ 是日常真正的入口（开着悬浮条就不用回界面），
 * 而「没体力自动用补给」「每 X 张图升星」这些开关是**在界面上勾的**
 * ⇒ 两边必须读同一份值，否则"勾了却没生效"（这类"看着像坏了"的体验最要命）。
 *
 * 存 SharedPreferences（`files/…/shared_prefs/autoexplore.xml`），卸载即清 ✓
 */
public final class Prefs {

    private static final String FILE = "autoexplore";
    private static final String K_AUTO_SUPPLY = "auto_supply";
    private static final String K_BAG_EVERY = "bag_every";
    private static final String K_MAPS_CHOICE = "maps_choice";
    private static final String K_SHOW_DEBUG = "show_debug";
    // ⭐ v1.78【收工日常五颗勾选】—— 与 PC 窗口上那一排**同名同默认值** ✓
    //   ⚠ 全部**默认关**：会改游戏状态的动**绝不默认做** ✗
    //     （与 `.auto_supply` 同一口径：别偷偷花东西 ✓）
    private static final String K_GUILD_TASKS = "guild_tasks";
    private static final String K_GUILD_ALCHEMY = "guild_alchemy";
    // ⭐ v2.06：悬浮条的**记忆位置**（用户拖到哪，下次还放哪）
    //   -9999 = 没设过（用默认锚点）
    // ⭐ 2026-11-14：**首次打开必须读一次免责声明**（用户口径）
    //   key 带版本号：以后声明内容有大改时把它改成 disclaimer_v2 ⇒ 老用户会再被问一次 ✓
    private static final String K_DISCLAIMER = "disclaimer_v2";
    private static final String K_OVL_LOCK = "ovl_lock";   // 位置锁定开关
    private static final String K_OVL_Y = "ovl_y";
    private static final String K_OVL_X = "ovl_x";

    // ⭐ v1.91：日常**前置**（刷图之前先做，而不是只在收工后做）
    private static final String K_DAILY_FIRST = "daily_first";
    private static final String K_GUILD_INTEL = "guild_intel";
    private static final String K_RECRUIT_FREE = "recruit_free";
    // ⚠ 免广告**例外**：PC 用户口径是「**默认有免广**」⇒ 默认勾上 ✓
    //   但语义仍是「勾 = 这个号有免广，未勾则一下都不碰」✓
    private static final String K_AD_FREE = "ad_free";
    /** 每 N 张图做一次「背包一键升级」（0 = 关闭）。默认 10（与 PC `--bag-every` 默认值一致） */
    public static final int BAG_EVERY_DEFAULT = 10;

    private Prefs() {
    }

    /** 免责声明确认过没有（默认**没确认**⇒ 首次打开会弹一次） */
    public static boolean disclaimerAgreed(Context c) {
        return sp(c).getBoolean(K_DISCLAIMER, false);
    }

    public static void setDisclaimerAgreed(Context c, boolean v) {
        sp(c).edit().putBoolean(K_DISCLAIMER, v).apply();
    }

    /** 是否显示调试按钮（默认**关**：正常人只要「开始/停止」两个键） */
    public static boolean showDebug(Context c) {
        return sp(c).getBoolean(K_SHOW_DEBUG, false);
    }

    public static void setShowDebug(Context c, boolean v) {
        sp(c).edit().putBoolean(K_SHOW_DEBUG, v).apply();
    }

    private static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /** 没体力时自动进背包使用「结实补给」 */
    public static boolean autoSupply(Context c) {
        return sp(c).getBoolean(K_AUTO_SUPPLY, false);
    }

    public static void setAutoSupply(Context c, boolean v) {
        sp(c).edit().putBoolean(K_AUTO_SUPPLY, v).apply();
    }

    /** 每几张图去背包做一次装备一键升星（0 = 关闭） */
    public static int bagEvery(Context c) {
        return sp(c).getInt(K_BAG_EVERY, BAG_EVERY_DEFAULT);
    }

    public static void setBagEvery(Context c, int v) {
        sp(c).edit().putInt(K_BAG_EVERY, Math.max(0, v)).apply();
    }

    /** 本次跑几张：0 = 「1图」，1 = 「连刷至体力耗尽」 */
    public static int mapsChoice(Context c) {
        // ⭐ v2.22 用户口径（2026-10-26）：「默认配置为连刷」
        //   0 = 1图 ／ 1 = 连刷 ⇒ 默认 1
        return sp(c).getInt(K_MAPS_CHOICE, 1);
    }

    public static void setMapsChoice(Context c, int v) {
        sp(c).edit().putInt(K_MAPS_CHOICE, v).apply();
    }

    // ══════ v1.78：收工日常五颗勾选 ══════
    //  ⚠ 语义逐条写清（**这些不是"开关"，是授权**）：
    //    · guildTasks   派遣任务 ⇒ 把 4 把椅子都派出去 + 领掉已完成奖励（**不放弃、不召回** ✓）
    //    · guildAlchemy 炼金     ⇒ 顶楼点「满星」→「开始炼金」
    //                    ⚠ **会消耗 6 件 5★ 满星装备**（换成金币+结晶，**不可逆** ✗）
    //    · guildIntel   情报领奖 ⇒ 纯领奖、零消耗 ✓
    //    · recruitFree  免费招募 ⇒ 会**消耗当天那次免费机会**（用掉了自动跳过，不花宝石 ✓）
    //    · adFree       免广告   ⇒ 勾 = **这个号有免广**；未勾则四个入口**一下都不碰** ✓
    /** 派遣任务（公会 2 楼 4 把椅子）*/
    public static boolean guildTasks(Context c) {
        return sp(c).getBoolean(K_GUILD_TASKS, true);
    }

    public static void setGuildTasks(Context c, boolean v) {
        sp(c).edit().putBoolean(K_GUILD_TASKS, v).apply();
    }

    /** 炼金（会自动投满星开炼 —— **不可逆，消耗 6 件满星装备**）*/
    /** ⭐ v1.91 日常前置：true = 刷图**之前**先做完公会把日常（默认 false = 老行为，收工后做） */
    public static boolean dailyFirst(Context c) {
        return sp(c).getBoolean(K_DAILY_FIRST, false);
    }

    public static void setDailyFirst(Context c, boolean v) {
        sp(c).edit().putBoolean(K_DAILY_FIRST, v).apply();
    }

    public static boolean guildAlchemy(Context c) {
        return sp(c).getBoolean(K_GUILD_ALCHEMY, true);
    }

    public static void setGuildAlchemy(Context c, boolean v) {
        sp(c).edit().putBoolean(K_GUILD_ALCHEMY, v).apply();
    }

    /** 公会「情报」领奖（每日 + 每周，纯领奖）*/
    public static boolean guildIntel(Context c) {
        return sp(c).getBoolean(K_GUILD_INTEL, true);
    }

    public static void setGuildIntel(Context c, boolean v) {
        sp(c).edit().putBoolean(K_GUILD_INTEL, v).apply();
    }

    /** 免费指定招募（每天 1 次；用掉了自动跳过，不花宝石）*/
    public static boolean recruitFree(Context c) {
        return sp(c).getBoolean(K_RECRUIT_FREE, true);
    }

    public static void setRecruitFree(Context c, boolean v) {
        sp(c).edit().putBoolean(K_RECRUIT_FREE, v).apply();
    }

    // ══════ v2.06 悬浮条记忆位置 ══════
    //  ⚠ 为什么需要：用户 2026-10-21「你这是把限制线往下走了？比之前低好多」——
    //    根因是 RefMapper 的坐标模型（等比缩放+底部对齐）与这台 20:9 手机
    //    实际"满屏渲染"不一致 ⇒ 算出来的锚点天生偏下。
    //    ⇒ 与其猜那条线在哪，不如让用户拖到满意位置并记住。
    /** 悬浮条离底距离（设备像素）；-9999 = 未设置 ⇒ 用默认锚点 */
    /** 位置是否已锁定（true = 用记忆位置，false = 可自由拖动/回默认） */
    public static boolean overlayLocked(Context c) {
        return sp(c).getBoolean(K_OVL_LOCK, true);   // ⭐ 默认锁定（记住上次拖的位置）
    }

    public static void setOverlayLocked(Context c, boolean v) {
        sp(c).edit().putBoolean(K_OVL_LOCK, v).apply();
    }

    /** 悬浮条**顶边**位置（设备像素）；-9999 = 未设置 */
    public static int overlayTop(Context c) {
        return sp(c).getInt("ovl_top", -9999);
    }

    public static void setOverlayTop(Context c, int v) {
        sp(c).edit().putInt("ovl_top", v).apply();
    }

    public static int overlayY(Context c) {
        return sp(c).getInt(K_OVL_Y, -9999);
    }

    public static void setOverlayY(Context c, int v) {
        sp(c).edit().putInt(K_OVL_Y, v).apply();
    }

    /** 悬浮条左边距（设备像素）；-9999 = 未设置 */
    public static int overlayX(Context c) {
        return sp(c).getInt(K_OVL_X, -9999);
    }

    public static void setOverlayX(Context c, int v) {
        sp(c).edit().putInt(K_OVL_X, v).apply();
    }

    /** 清除记忆位置（回到默认锚点） */
    public static void clearOverlayPos(Context c) {
        sp(c).edit().remove(K_OVL_Y).remove(K_OVL_X).apply();
    }

    /** 这个号有没有「免广告」（= 月卡权益那条）—— ⭐ PC 口径：**默认有** ✓ */
    public static boolean adFree(Context c) {
        // ⭐ v2.22 用户口径：「免广默认关闭，但有记忆」
        //   记忆 = SharedPreferences 本身（用户勾过就是 true，关过就是 false，
        //   直到再次修改）。默认值只在**从未设置过**时生效。
        return sp(c).getBoolean(K_AD_FREE, false);
    }

    public static void setAdFree(Context c, boolean v) {
        sp(c).edit().putBoolean(K_AD_FREE, v).apply();
    }

    // ══════ v2.131 预言石碑「遇到就停」四个开关（对齐 PC `bot_gui.py:2003` 那页）══════
    //  ⚠ 之前安卓端**没有这个入口**：`explore_loop.STOP_LUCKY/PEACE/ELEM_PURPLE/
    //    ELEM_ORANGE` 是写死的模块常量 = True ⇒ 用户看到「抽到元素·紫色就停」
    //    却**找不到地方关** ✗（2026-11-09 用户原话：「『遇到就停』这个选项没在 app 里显示啊」）
    //  ⚠ 默认值（用户 2026-11-09 明确指定：「**四个开关就幸运和元素橙默认打开**」）：
    //    · 幸运      **开**  → 抽到就停脚本、保现场
    //    · 和平·金属 **关**  → 只记录，不停
    //    · 元素·紫   **关**  → 只记录，不停（真机 21:56 那把就是被它停掉的）
    //    · 元素·橙   **开**  → 抽到就停脚本、保现场
    //  永远只是**没设过**时的默认值；用户勾过就按勾的来（SharedPreferences 本身即记忆）✓
    public static boolean stopLucky(Context c) {
        return sp(c).getBoolean("stop_lucky", true);
    }

    public static void setStopLucky(Context c, boolean v) {
        sp(c).edit().putBoolean("stop_lucky", v).apply();
    }

    public static boolean stopPeace(Context c) {
        return sp(c).getBoolean("stop_peace", false);
    }

    public static void setStopPeace(Context c, boolean v) {
        sp(c).edit().putBoolean("stop_peace", v).apply();
    }

    public static boolean stopElemPurple(Context c) {
        return sp(c).getBoolean("stop_elem_purple", false);
    }

    public static void setStopElemPurple(Context c, boolean v) {
        sp(c).edit().putBoolean("stop_elem_purple", v).apply();
    }

    public static boolean stopElemOrange(Context c) {
        return sp(c).getBoolean("stop_elem_orange", true);
    }

    public static void setStopElemOrange(Context c, boolean v) {
        sp(c).edit().putBoolean("stop_elem_orange", v).apply();
    }
}
