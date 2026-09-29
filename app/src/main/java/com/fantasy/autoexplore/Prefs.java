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

    /** 每 N 张图做一次「背包一键升级」（0 = 关闭）。默认 10（与 PC `--bag-every` 默认值一致） */
    public static final int BAG_EVERY_DEFAULT = 10;

    private Prefs() {
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
        return sp(c).getInt(K_MAPS_CHOICE, 0);
    }

    public static void setMapsChoice(Context c, int v) {
        sp(c).edit().putInt(K_MAPS_CHOICE, v).apply();
    }
}
