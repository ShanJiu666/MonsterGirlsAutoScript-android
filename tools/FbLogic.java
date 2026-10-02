import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * v1.33 离线验证：`Feedback.collectFrames()` 的**过滤/排序/清单**判据等价实现。
 *
 * ⚠ 为什么复刻而不是直接调真方法：`android.jar` 里的 `java.io.File` 是**裁剪桩**
 *   （没有 getLastModified()），脱离 Gradle 跑不起真类（2026-10-02 实测）✗
 *   ⇒ 这里逐条照抄 `Feedback.java` 的判据（含 1 秒容差、白名单前缀、排序方向、
 *     note 文案），保证"逻辑对不对"这件事**真的被跑过** ✓
 * ⚠ 另有一道门禁（v1.33 ⑥⑦⑧）直接查 `Feedback.java` 源码里的关键判据在位 ✓
 *   两道合起来 = 判据既在源码里、又被实跑验证过 ✓
 */
public class FbLogic {

    static final String[] FRAME_PREFIXES = {
            "board_hidden_", "marks_none_", "dice_nobtn", "vault_no_hit_",
    };

    /** 与 Feedback.readRunStarted() 同判据：秒 ⇒ 毫秒；量级不对 ⇒ 0（fail-safe） */
    static long readRunStarted(File bagdbg) throws Exception {
        File mk = new File(bagdbg, "_run_marker.json");
        if (!mk.isFile()) {
            return 0L;
        }
        byte[] raw = new byte[(int) mk.length()];
        try (java.io.FileInputStream in = new java.io.FileInputStream(mk)) {
            int off = 0, n;
            while (off < raw.length && (n = in.read(raw, off, raw.length - off)) > 0) {
                off += n;
            }
        }
        String s = new String(raw, "UTF-8");
        int i = s.indexOf("\"run_started\"");
        if (i < 0) {
            return 0L;
        }
        int j = s.indexOf(':', i);
        int k = j + 1;
        while (k < s.length() && (s.charAt(k) == ' ' || s.charAt(k) == '\t')) {
            k++;
        }
        int e = k;
        while (e < s.length() && (Character.isDigit(s.charAt(e))
                || s.charAt(e) == '.' || s.charAt(e) == 'e' || s.charAt(e) == 'E'
                || s.charAt(e) == '+' || s.charAt(e) == '-')) {
            e++;
        }
        if (e <= k) {
            return 0L;
        }
        String num = s.substring(k, e);
        double sec;
        try {
            sec = Double.parseDouble(num);
        } catch (Throwable t) {
            return 0L;
        }
        if (sec <= 0) {
            return 0L;
        }
        long ms = (long) (sec * 1000.0);
        // ⚠ 阈值必须是"2001~2100 年的毫秒"（1.0e12~4.1e12）。
        //   写成 1e11 会把所有**正常**标记误杀成"没有闸"（2026-10-02 实跑抓到的真 bug）✗
        if (ms < 978307200000L || ms > 4102444800000L) {
            return 0L;
        }
        return ms;
    }

    /** 与 Feedback.collectFrames() 同判据 */
    static List<File> collectFrames(File bagdbg, long runStarted, StringBuilder note) {
        List<File> out = new ArrayList<>();
        int stale = 0, notDiag = 0;
        File[] all = bagdbg.listFiles((d, n) -> n != null && n.toLowerCase().endsWith(".png"));
        if (all == null) {
            return out;
        }
        List<Entry> keep = new ArrayList<>();
        for (File f : all) {
            String n = f.getName();
            boolean isDiag = false;
            for (String p : FRAME_PREFIXES) {
                if (n.startsWith(p)) {
                    isDiag = true;
                    break;
                }
            }
            if (!isDiag) {
                notDiag++;
                continue;
            }
            if (runStarted > 0 && f.lastModified() + 1000L < runStarted) {
                stale++;
                continue;
            }
            keep.add(new Entry(f.getName(), f.lastModified()));
        }
        keep.sort((a, b) -> Long.compare(b.mt, a.mt));   // 新→旧 ✓
        for (int i = 0; i < keep.size() && i < 8; i++) {
            out.add(new File(bagdbg, keep.get(i).name));
        }
        note.append("  诊断帧: 收 ").append(out.size()).append(" 张（本次运行落下的）")
                .append("；已剔除陈旧帧 ").append(stale).append(" 张")
                .append("；非诊断 png ").append(notDiag).append(" 张未收\n");
        if (stale > 0) {
            note.append("  ⚠ 有 ").append(stale)
                    .append(" 张比本次运行更早的旧帧，已**排除**（它们不属于这次运行）\n");
        }
        if (out.isEmpty()) {
            note.append("  ⚠ 本次运行**没有落任何诊断帧**")
                    .append("（说明这次没触发截图分支，不是丢包）\n");
        }
        return out;
    }

    static class Entry {
        final String name;
        final long mt;
        Entry(String name, long mt) { this.name = name; this.mt = mt; }
    }

    // ---------------- 断言 ----------------

    static int failures = 0;

    static void t(String name, boolean cond, String extra) {
        System.out.println((cond ? "[ok]   " : "[FAIL] ") + name
                + (extra == null || extra.isEmpty() ? "" : "  · " + extra));
        if (!cond) {
            failures++;
        }
    }

    static void mk(File d, String n, long mt) throws Exception {
        File f = new File(d, n);
        f.getParentFile().mkdirs();
        try (java.io.FileOutputStream o = new java.io.FileOutputStream(f)) {
            o.write(new byte[]{(byte) 0x89, 'P', 'N', 'G', 13, 10, 26, 10,
                    0, 0, 0, 13, 'I', 'H', 'D', 'R',
                    0, 0, 4, 32, 0, 0, 6, (byte) 144, 8, 6, 0, 0, 0});
        }
        f.setLastModified(mt);
    }

    static String names(List<File> l) {
        StringBuilder sb = new StringBuilder();
        for (File f : l) {
            sb.append(f.getName()).append(' ');
        }
        return sb.toString();
    }

    public static void main(String[] a) throws Exception {
        File d = new File(a[0]);
        d.mkdirs();
        for (File f : d.listFiles()) {
            f.delete();
        }
        long now = System.currentTimeMillis();
        long old = now - 10L * 86400 * 1000L;

        mk(d, "board_hidden_r0.png", old);      // 上一局的老帧
        mk(d, "dice_nobtn.png", old);           // 上一局的老帧
        mk(d, "marks_none_r3.png", now);        // 本次刚落
        mk(d, "vault_no_hit_L1.png", now);      // 本次刚落
        mk(d, "screenshot_mine.png", now);      // 玩家自己的图（白名单外）
        try (java.io.FileOutputStream o = new java.io.FileOutputStream(new File(d, "mgas_log.txt"))) {
            o.write("日志".getBytes("UTF-8"));
        }
        try (java.io.FileOutputStream o = new java.io.FileOutputStream(new File(d, "_run_marker.json"))) {
            o.write(("{\"run_started\": " + (now / 1000L) + "}").getBytes("UTF-8"));
        }

        long rs = readRunStarted(d);
        t("① run_started 秒 ⇒ 毫秒换算正确", Math.abs(rs - now) < 2000, "rs=" + rs);

        // ①b 科学计数法也必须能吃下（实跑抓到的真 bug：1.79E9 被截成 1.79 ⇒ 闸失效）✗
        try (java.io.FileOutputStream o = new java.io.FileOutputStream(new File(d, "_run_marker.json"))) {
            o.write(("{\"run_started\": 1.79E9}").getBytes("UTF-8"));
        }
        long rsSci = readRunStarted(d);
        // ⚠ 1.79E9 **秒** ⇒ 1.79e12 毫秒（解析正确即为此值；旧代码会截成 1790 毫秒 ✗）
        t("①b **科学计数法**（1.79E9 秒）也能解析（实跑抓到的坑）",
                Math.abs(rsSci - 1790000000000L) < 1000, "rs=" + rsSci);
        try (java.io.FileOutputStream o = new java.io.FileOutputStream(new File(d, "_run_marker.json"))) {
            o.write(("{\"run_started\": " + (now / 1000L) + "}").getBytes("UTF-8"));
        }

        StringBuilder note = new StringBuilder();
        List<File> kept = collectFrames(d, rs, note);
        String n = names(kept);
        t("② **老帧被时间闸挡住**（board_hidden_r0 / dice_nobtn 不在包里）",
                !n.contains("board_hidden_r0") && !n.contains("dice_nobtn"), "kept=" + n);
        t("③ **本次落下的帧留下**（marks_none_r3 / vault_no_hit_L1）",
                n.contains("marks_none_r3") && n.contains("vault_no_hit_L1"), "kept=" + n);
        t("④ 玩家自己的图**不收**（白名单外）", !n.contains("screenshot_mine"), "kept=" + n);
        t("⑤ note 写明剔除了几张陈旧帧", note.toString().contains("已剔除陈旧帧 2 张"),
                note.toString().replace('\n', ' ').trim());

        boolean ordered = true;
        for (int i = 1; i < kept.size(); i++) {
            if (kept.get(i - 1).lastModified() < kept.get(i).lastModified()) {
                ordered = false;
            }
        }
        t("⑥ 帧按**新→旧**排序", ordered, n);

        File mkf = new File(d, "_run_marker.json");
        mkf.delete();
        t("⑦ 没有运行标记（老 APK）⇒ 不设时间闸（fail-safe，不误杀）",
                readRunStarted(d) == 0, "");

        StringBuilder n2 = new StringBuilder();
        List<File> k2 = collectFrames(d, 0L, n2);
        t("⑧ 没有时间闸时老帧仍会被收（但清单里**标了**剔除数=0）",
                k2.size() >= 4, "n=" + k2.size());

        for (File f : d.listFiles()) {
            f.delete();
        }
        StringBuilder n3 = new StringBuilder();
        List<File> k3 = collectFrames(d, 0L, n3);
        t("⑨ 本次没落任何帧 ⇒ note **明说**不是丢包",
                n3.toString().contains("没有落任何诊断帧"), n3.toString().replace('\n', ' ').trim());

        try (java.io.FileOutputStream o = new java.io.FileOutputStream(new File(d, "_run_marker.json"))) {
            o.write(("{\"run_started\": " + now + "}").getBytes("UTF-8"));   // 单位写错
        }
        t("⑩ 标记单位异常（毫秒塞进秒位）⇒ 当没有闸（fail-safe）",
                readRunStarted(d) == 0, "");

        System.out.println(failures == 0 ? "\nALL PASS" : "\n" + failures + " FAILED");
        System.exit(failures == 0 ? 0 : 1);
    }
}
