/**
 * HotVcLogic.java · 独立自测「补丁 id → 构建版本 → 是否比 APK 旧」这套判据
 * （对应 `Updater.patchBuildVc()` + `bootRecover()` 里那两道闸）
 *
 * ⚠ 为什么不 import Updater 直接测：`Updater` 依赖 android.jar（裁剪桩）+
 *   `android.util.Log` 等，脱离 Gradle 起不来真类 ⇒ **判据等价复刻 + 独立实跑** ✓
 *   （与 `FbLogic.java` 同一个理由与先例 ✓）
 *
 * ⚠ 为什么值得单测：这套判据决定"**要不要丢掉一个补丁**" ⇒ 判错方向就会
 *   ①把好补丁误删（白丢热更）②或让旧补丁留着**静默遮蔽新 APK**（真机已咬过一次 ✗）
 *
 * 编译运行：javac -encoding UTF-8 -d <out> HotVcLogic.java && java -cp <out> HotVcLogic
 * 退出码 0 = 全过；非 0 = 有失败（并打印 FAIL 行）
 */
public class HotVcLogic {

    /** 与 `Updater.patchBuildVc()` 逐字等价（`hot-<vc>-<sha8>` ⇒ `<vc>`；判不出 ⇒ -1） */
    static int patchBuildVc(String id) {
        try {
            String s = String.valueOf(id == null ? "" : id).trim();
            if (!s.startsWith("hot-")) {
                return -1;
            }
            String rest = s.substring(4);
            int dash = rest.indexOf('-');
            String num = dash > 0 ? rest.substring(0, dash) : rest;
            return Integer.parseInt(num.trim());
        } catch (Throwable t) {
            return -1;
        }
    }

    /** 与 `bootRecover()` 的判据等价：true = 这个补丁**比 APK 旧**，该丢 */
    static boolean isStale(String id, int appVc) {
        int pvc = patchBuildVc(id);
        return pvc >= 0 && pvc < appVc;
    }

    static int fails = 0;

    static void eq(String label, Object got, Object want) {
        boolean ok = String.valueOf(got).equals(String.valueOf(want));
        if (!ok) {
            fails++;
        }
        System.out.println((ok ? "  ok   " : "  FAIL ") + label
                + "  got=" + got + " want=" + want);
    }

    public static void main(String[] args) {
        System.out.println("=== HotVcLogic：补丁 id 解析 ===");
        // 真机出现过的真实 id（tools/release.py 的 hot_id() 产出：hot-%d-%s）
        eq("hot-147-eac36a20 的 vc", patchBuildVc("hot-147-eac36a20"), 147);
        eq("hot-148-d90df713 的 vc", patchBuildVc("hot-148-d90df713"), 148);
        eq("hot-144-e8d89bd7 的 vc", patchBuildVc("hot-144-e8d89bd7"), 144);
        // 边界/异常 —— 一律 -1（**保守：判不出就绝不动它** ✓）
        eq("空串 ⇒ -1", patchBuildVc(""), -1);
        eq("null ⇒ -1", patchBuildVc(null), -1);
        eq("不是 hot- 开头 ⇒ -1", patchBuildVc("patch-147-abc"), -1);
        eq("版本不是数字 ⇒ -1", patchBuildVc("hot-abc-deadbeef"), -1);
        eq("只有 hot- ⇒ -1", patchBuildVc("hot-"), -1);
        eq("没有 sha 段也认（hot-150）", patchBuildVc("hot-150"), 150);
        eq("前后空格容错", patchBuildVc("  hot-151-0011aabb  "), 151);

        System.out.println();
        System.out.println("=== isStale：比 APK 旧才丢（核心判据）===");
        // ⭐ 真机那个事故：APK 已升到 148，活跃补丁还是 147 ⇒ **必须丢** ✓
        eq("APK=148 / 补丁=147 ⇒ 丢", isStale("hot-147-eac36a20", 148), true);
        eq("APK=148 / 补丁=148 ⇒ 留", isStale("hot-148-d90df713", 148), false);
        eq("APK=148 / 补丁=149 ⇒ 留（比 APK 新，也能用）", isStale("hot-149-xxxx", 148), false);
        eq("APK=145 / 补丁=148 ⇒ 留", isStale("hot-148-d90df713", 145), false);
        // ⚠ 判不出 ⇒ **留**（保守：宁可留着，也不误删一个好补丁 ✓）
        eq("判不出 ⇒ 留", isStale("garbage", 148), false);

        System.out.println();
        if (fails == 0) {
            System.out.println("ALL PASS");
            return;
        }
        System.out.println("FAILED: " + fails);
        System.exit(1);
    }
}
