package com.fantasy.autoexplore;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * 方案 A · 深空玻璃 —— 设计令牌与绘图原语。
 *
 * <p>事实来源是 {@code docs/ui_design/scheme_a.py} 里那套 dp 数字；本类只是把它们
 * 逐条翻译成 Android 代码。改配色/圆角/字号请**先改那边再同步这里**，别只改一处。
 *
 * <p>⚠ 本类**只负责画**，不持有任何状态、不调 Python、不读写 Prefs —— 业务仍在
 * MainActivity / OverlayService。
 */
final class UiKit {

    // ── 画布基准 ────────────────────────────────────────────────
    /** 设计稿宽 360dp；真实屏宽按 dp 换算即可，所有尺寸都用 dp 表达 */
    static final float DESIGN_W_DP = 360f;

    // ── 背景 ────────────────────────────────────────────────────
    static final int BG_TOP = 0xFF06090F;
    static final int BG_MID = 0xFF090D1A;
    static final int BG_BOTTOM = 0xFF070B13;

    // ── 文字 ────────────────────────────────────────────────────
    static final int INK = 0xFFE7EFFA;
    static final int INK_2 = 0xFFB0C2D6;
    static final int INK_3 = 0xFF8091A8;
    static final int INK_4 = 0xFF607086;

    // ── 强调 / 语义 ──────────────────────────────────────────────
    static final int ACCENT = 0xFF22D3EE;
    static final int ACCENT_D = 0xFF3B82F6;
    static final int OK = 0xFF34D399;
    static final int WARN = 0xFFFBBF24;
    static final int DANGER = 0xFFF87171;

    // ── 面板 ────────────────────────────────────────────────────
    /** 卡片底：白 α13 ≈ 5.1% */
    static final int CARD = 0x22FFFFFF;
    static final int CARD_LINE = 0x44FFFFFF;
    static final int HAIR = 0x2EFFFFFF;

    private UiKit() {
    }

    // ══════════════════════════════════════════════════════════
    // 度量
    // ══════════════════════════════════════════════════════════
    static int dp(Context c, float v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    static float dpf(Context c, float v) {
        return v * c.getResources().getDisplayMetrics().density;
    }

    // ══════════════════════════════════════════════════════════
    // 背景
    // ══════════════════════════════════════════════════════════
    /** 整页深空竖向渐变（三段）。柔光斑**预烘焙**成一张图更省，这里先用渐变保证观感一致。 */
    static View backdrop(Context c) {
        GradientDrawable g = new GradientDrawable(
                GradientDrawable.Orientation.TOP_BOTTOM, new int[]{BG_TOP, BG_MID, BG_BOTTOM});
        View v = new View(c);
        v.setBackground(g);
        return v;
    }

    // ══════════════════════════════════════════════════════════
    // 文本
    // ══════════════════════════════════════════════════════════
    /**
     * 创建一段文本。
     *
     * <p>⚠ 对齐口径：设计稿里的 anchor 指**墨迹包围盒**。TextView 没有这种 anchor，
     * 所以这里统一用 {@code includeFontPadding=false} + 固定行距，
     * 让"上边缘"尽量贴近墨迹上缘（与预设图差 1~2px，可接受）。
     */
    static TextView text(Context c, String s, float sp, boolean bold, int color) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setIncludeFontPadding(false);
        if (bold) {
            t.setTypeface(Typeface.DEFAULT_BOLD);
        }
        return t;
    }

    static TextView title(Context c, String s) {
        return text(c, s, 24, true, INK);
    }

    static TextView sub(Context c, String s) {
        return text(c, s, 11, false, INK_3);
    }

    /** 卡片小节标题（11.5sp Bold，青蓝弱化色） */
    static TextView sectionTitle(Context c, String s) {
        return text(c, s, 11.5f, true, 0xFF7CB2D6);
    }

    static TextView hint(Context c, String s) {
        return text(c, s, 9.5f, false, INK_4);
    }

    // ══════════════════════════════════════════════════════════
    // 容器
    // ══════════════════════════════════════════════════════════
    static LinearLayout column(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        return l;
    }

    static LinearLayout row(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        return l;
    }

    /**
     * 玻璃卡片：底色白 α5% + 1dp 描边。
     *
     * <p>⚠ 柔光/投影在 Android 端要 {@code setLayerType(LAYER_TYPE_SOFTWARE)} 或
     * {@code Paint.setShadowLayer}，两者都会拖慢滚动 —— 这里**不用投影**，
     * 靠"半透明底 + 描边"撑层次（静止界面下与预设图的观感差异可忽略）。
     */
    static LinearLayout card(Context c, float radiusDp) {
        LinearLayout box = column(c);
        GradientDrawable g = new GradientDrawable();
        g.setColor(CARD);
        g.setCornerRadius(dpf(c, radiusDp));
        g.setStroke(Math.max(1, dp(c, 1)), CARD_LINE);
        box.setBackground(g);
        int padH = dp(c, 20), padV = dp(c, 18);
        box.setPadding(padH, padV, padH, padV);
        return box;
    }

    static void margins(View v, int l, int t, int r, int b) {
        if (v.getLayoutParams() instanceof LinearLayout.LayoutParams) {
            LinearLayout.LayoutParams lp = (LinearLayout.LayoutParams) v.getLayoutParams();
            lp.setMargins(l, t, r, b);
            v.setLayoutParams(lp);
        }
    }

    static LinearLayout.LayoutParams lpW(int w, int h) {
        return new LinearLayout.LayoutParams(w, h);
    }

    static LinearLayout.LayoutParams lpWeight(float wgt) {
        return new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, wgt);
    }

    // ══════════════════════════════════════════════════════════
    // 圆角块 / 开关 / 圆环
    // ══════════════════════════════════════════════════════════
    static GradientDrawable pill(Context c, int fill, int strokeColor, float radiusDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dpf(c, radiusDp));
        if (strokeColor != 0) {
            g.setStroke(Math.max(1, dp(c, 1)), strokeColor);
        }
        return g;
    }

    static GradientDrawable gradientPill(Context c, int top, int bottom, float radiusDp) {
        GradientDrawable g = new GradientDrawable(
                GradientDrawable.Orientation.TOP_BOTTOM, new int[]{top, bottom});
        g.setCornerRadius(dpf(c, radiusDp));
        return g;
    }

    /**
     * 自绘圆环进度（设计稿：r=34dp、线宽 8dp、起点 -90°）。
     *
     * <p>比 ProgressBar 可控：颜色/线宽/轨道都能对上预设图。
     */
    static class RingView extends View {
        private final Paint track = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint prog = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint center = new Paint(Paint.ANTI_ALIAS_FLAG);
        private float pct = 0f;
        private String label = "";
        private String unit = "";
        private boolean showBang = false;

        RingView(Context c, int color) {
            super(c);
            track.setStyle(Paint.Style.STROKE);
            track.setStrokeWidth(dpf(c, 8));
            track.setColor(0x38FFFFFF);
            prog.setStyle(Paint.Style.STROKE);
            prog.setStrokeWidth(dpf(c, 8));
            prog.setStrokeCap(Paint.Cap.ROUND);
            prog.setColor(color);
            center.setTextAlign(Paint.Align.CENTER);
            center.setColor(INK);
            center.setTypeface(Typeface.DEFAULT_BOLD);
        }

        void set(float p, String label, String unit, boolean bang) {
            this.pct = Math.max(0f, Math.min(1f, p));
            this.label = label == null ? "" : label;
            this.unit = unit == null ? "" : unit;
            this.showBang = bang;
            invalidate();
        }

        void setColor(int c) {
            prog.setColor(c);
            invalidate();
        }

        @Override
        protected void onMeasure(int w, int h) {
            int r = dp(getContext(), 68) + dp(getContext(), 8);
            setMeasuredDimension(resolveSize(r, w), resolveSize(r, h));
        }

        @Override
        protected void onDraw(Canvas cv) {
            float cx = getWidth() / 2f, cy = getHeight() / 2f;
            float r = Math.min(cx, cy) - prog.getStrokeWidth() / 2f - dp(getContext(), 1);
            cv.drawCircle(cx, cy, r, track);
            if (pct > 0f) {
                android.graphics.RectF box = new android.graphics.RectF(cx - r, cy - r, cx + r, cy + r);
                cv.drawArc(box, -90f, 360f * pct, false, prog);
            }
            if (showBang) {
                center.setTextSize(dpf(getContext(), 20));
                cv.drawText("!", cx, cy + center.getTextSize() * 0.35f, center);
            } else if (!label.isEmpty()) {
                center.setTextSize(dpf(getContext(), 15));
                cv.drawText(label, cx, cy + center.getTextSize() * 0.32f, center);
                if (!unit.isEmpty()) {
                    center.setTextSize(dpf(getContext(), 8.5f));
                    center.setColor(INK_4);
                    cv.drawText(unit, cx, cy + dp(getContext(), 13), center);
                    center.setColor(INK);
                }
            }
        }
    }

    /**
     * 自绘开关（32×19dp、滑块白 r7.1）。
     *
     * <p>⚠ 不用 {@code SwitchCompat}：它的 thumb/track 尺寸与本设计对不上，
     * 强行调会牵出一堆 inset 常量。
     */
    static class Toggle extends View {
        private boolean on;
        private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final int onColor;
        private final int offColor;
        private Runnable onChange;

        Toggle(Context c, boolean on, int onColor) {
            super(c);
            this.on = on;
            this.onColor = onColor;
            this.offColor = 0xFF585F6E;
            setClickable(true);
            setFocusable(true);
        }

        void setOn(boolean v) {
            if (on == v) {
                return;
            }
            on = v;
            invalidate();
        }

        boolean isOn() {
            return on;
        }

        void onChange(Runnable r) {
            onChange = r;
        }

        @Override
        protected void onMeasure(int w, int h) {
            setMeasuredDimension(dp(getContext(), 32), dp(getContext(), 19));
        }

        @Override
        public boolean performClick() {
            on = !on;
            invalidate();
            if (onChange != null) {
                onChange.run();
            }
            return true;
        }

        @Override
        protected void onDraw(Canvas cv) {
            float h = getHeight(), w = getWidth();
            p.setColor(on ? onColor : offColor);
            cv.drawRoundRect(0, 0, w, h, h / 2, h / 2, p);
            float kr = h / 2 - dpf(getContext(), 2.6f);
            float kx = on ? w - h / 2 - dpf(getContext(), 2.6f) : h / 2 + dpf(getContext(), 2.6f);
            p.setColor(Color.WHITE);
            cv.drawCircle(kx, h / 2, kr, p);
        }
    }

    /**
     * 状态色点（就绪条 / 运行中指示）。
     */
    static View dot(Context c, int color, float sizeDp) {
        View v = new View(c);
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setColor(color);
        v.setBackground(g);
        v.setLayoutParams(lpW(dp(c, sizeDp), dp(c, sizeDp)));
        return v;
    }

    /** 细分隔线（白 α11，0.7dp → 取 1px） */
    static View hair(Context c) {
        View v = new View(c);
        v.setBackgroundColor(0x1CFFFFFF);
        v.setLayoutParams(new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, Math.max(1, dp(c, 0.7f))));
        return v;
    }
}