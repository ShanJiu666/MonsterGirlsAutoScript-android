package com.fantasy.autoexplore;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.provider.Settings;
import android.util.Base64;

import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * ⭐⭐⭐ 热更新（用户 2026-10-03 口径：「发给朋友的怎么搞热更新？」）
 *
 * <h3>两层，各管各的</h3>
 * <table border="1">
 *   <tr><th>层</th><th>换什么</th><th>体积</th><th>朋友要做什么</th></tr>
 *   <tr><td><b>逻辑热更</b></td><td>{@code app/src/main/python/*.py}（12 个模块，业务逻辑全在这）</td>
 *       <td>1~2 MB</td><td><b>什么都不用做</b>：后台下载 → 下次冷启动自动生效</td></tr>
 *   <tr><td><b>APK 自更新</b></td><td>Java 壳 / 权限 / 资源包 / 依赖</td>
 *       <td>~70 MB</td><td>点一次「更新」→ 系统安装器弹一下 → 点「安装」</td></tr>
 * </table>
 *
 * <h3>更新源</h3>
 * 公开 Gitee 仓库 {@code geng-haojie/MGAS-update}（**匿名可读**，2026-10-03 实测 raw=200、
 * release 附件=200）。朋友<b>永远不打 Gitee、不注册、不登录</b> —— 这里只是 HTTP 拉文件。
 * <ul>
 *   <li>{@code manifest.json} → raw 直读（本类 {@link #MANIFEST_URL}）</li>
 *   <li>逻辑补丁 zip → raw 直读（1~2MB，不占 release 配额）</li>
 *   <li>APK → **release 附件**（{@code /releases/download/<tag>/xxx.apk}）；不放 raw 是因为
 *       仓库总配额只有 1GB，塞几个 70MB 的包就爆（hb-web 的老教训）</li>
 * </ul>
 *
 * <h3>⭐⭐ 回滚：这一层的正确性比"能更新"更重要</h3>
 * Python 补丁一旦有语法错 / import 失败，会让<b>整个脚本不可用</b>，而朋友<b>不会</b>去看日志、
 * 更不会报给我 —— 所以必须有自动兜底。状态机（{@code filesDir/hot/state.json}）：
 * <pre>
 *   ① 下载 → 解到 hot/pending/（写 meta.json）
 *   ② **下次冷启动**：bootRecover() 把 pending → active，写 state{active, confirmed=false}
 *   ③ Python 起来后 onPythonStarted() 调 explore_android.hot_selftest()
 *        · 通过  → state.confirmed = true（此后不再自检）
 *        · 不通过 → **立刻**把 active 挪到 hot/bad/，回落 APK 内置版本，并再自检一次
 *   ④ 若上次激活后**从未**确认过（比如激活完就被杀），下次启动 bootRecover() 直接判坏包回滚
 * </pre>
 * ⚠ 回滚后 {@code sys.path} 仍指着一个<b>已不存在</b>的目录 —— 这是**故意的**：Python 找不到
 * 就自然回落 .imy 内置版，不需要重启进程（import 失败不会在 {@code sys.modules} 留残留）。
 *
 * <h3>⭐⭐⭐ v2.133（2026-11-14 用户拍板）：<b>更新前必须确认</b></h3>
 * <ul>
 *   <li>{@link #plan} = <b>只探测</b>（读清单 + 本地 {@code state.json}；<b>不下载、不写盘</b>）</li>
 *   <li>{@code run(bg)} / {@code run(auto)} = 只回一句提示，<b>一律不安装</b></li>
 *   <li>{@code run(hot)} / {@code run(apk)} = 用户在确认框点「立即更新」<b>之后</b>才真下载/安装</li>
 * </ul>
 * ⚠ 为什么要把"后台自动装补丁"撤掉：用户原话「<b>所有更新前都要弹确认</b>（含后台发现的补丁）」
 *   ＋「后台检查保留，但只<b>发现并提示</b>，<b>一律不安装</b>」——
 *   原来 {@code bg} 一发现补丁就静默 {@code applyHot}，人根本不知道装了什么 ✗
 *
 * <h3>为什么 APK 装法用 PackageInstaller.Session 而不是 FileProvider / MediaStore</h3>
 * · {@code file://} 在 API 24+ 抛 {@code FileUriExposedException} ✗<br>
 * · FileProvider 要引 androidx（本工程**没有** androidx，加依赖要联网拉包 ✗）<br>
 * · MediaStore.Downloads 适合"分享文件"，但<b>安装包</b>走它各 ROM 行为不一 ✗<br>
 * · {@code PackageInstaller.Session} 是系统安装器自己的接口（API 21+，本工程 minSdk 26 ✓），
 *   不需要 content:// URI、不落公共目录、不需要任何存储权限 ✓
 */
public final class Updater {

    private static final String TAG = "MGAS更新";

    /**
     * 更新源清单。
     *
     * <p>⚠⚠ **必须走 API contents 通道**，不能走 raw —— 2026-10-03 实测：
     * Gitee 的 `raw/` 有**强缓存**，刚 push 上去的 manifest 读回来还是旧的
     * （连加 `?t=<时间戳>` 破缓存都**无效**）⇒ 会表现成"我发了新版，端上永远说已是最新" ✗✗
     * 而 `api/v5/.../contents/` 是实时的 ✓（代价：匿名有速率限制，回落见 {@link #fetchManifest}）。
     *
     * <p>补充：**补丁 zip / APK 走 raw 没问题** —— 它们的文件名带内容 sha（`hot-141-8a8a040c.zip`），
     * 内容一变文件名就变，天然免疫缓存 ✓（这是"用内容哈希命名"顺带解决掉的坑）。
     */
    public static final String MANIFEST_RAW =
            "https://gitee.com/geng-haojie/MGAS-update/raw/master/manifest.json";
    public static final String MANIFEST_API =
            "https://gitee.com/api/v5/repos/geng-haojie/MGAS-update/contents/manifest.json";

    private static final String UA = "MGAS-Updater/1";
    private static final int CONNECT_MS = 8000;
    private static final int READ_MS = 30000;
    /** 逻辑补丁上限（正常 1~3MB；给足余量，超了说明发错包了） */
    private static final long MAX_HOT_BYTES = 24L * 1024 * 1024;
    /** APK 上限（当前 ~71MB；release 附件单文件限 100MB） */
    private static final long MAX_APK_BYTES = 200L * 1024 * 1024;

    private Updater() {
    }

    // ───────────────────────── 目录 ─────────────────────────

    public static File hotRoot(Context c) {
        return new File(c.getFilesDir(), "hot");
    }

    /** 当前生效的热更模块目录（Python {@code sys.path[0]} 指向它） */
    public static File hotActive(Context c) {
        return new File(hotRoot(c), "active");
    }

    private static File hotPending(Context c) {
        return new File(hotRoot(c), "pending");
    }

    private static File hotBad(Context c) {
        return new File(hotRoot(c), "bad");
    }

    private static File stateFile(Context c) {
        return new File(hotRoot(c), "state.json");
    }

    /**
     * 给 {@code PyBridge} 用：**该插进 sys.path 的目录**（没有生效补丁 ⇒ null）。
     * ⚠ 只有 {@code state.active} 存在且目录真的在，才返回 —— 否则会插一个空目录，
     *   虽然无害但会让"到底有没有热更"这件事变得说不清。
     */
    public static String hotActivePath(Context c) {
        try {
            JSONObject st = readState(c);
            if (!st.has("active")) {
                return null;
            }
            File a = hotActive(c);
            return a.isDirectory() ? a.getAbsolutePath() : null;
        } catch (Throwable t) {
            return null;
        }
    }

    // ───────────────────────── 启动期：激活 / 回滚 ─────────────────────────

    /**
     * ⭐ 冷启动第一件事（**必须在 Python 起来之前**，见 {@code PyBridge.ensureStarted}）。
     *
     * <p>干两件事，顺序不能反：
     * <ol>
     *   <li><b>回滚</b>：active 存在但 {@code confirmed=false} ⇒ 上次激活后从没成功跑起来过
     *       ⇒ 判坏包，挪去 {@code hot/bad/}（留证据，不删）</li>
     *   <li><b>激活</b>：pending 就绪（有 meta.json）⇒ 换成 active，写 {@code confirmed=false}
     *       等自检</li>
     * </ol>
     */
    /**
     * ⭐⭐ v1.45g：**刚激活、还没告诉用户的补丁**（`MainActivity` 起来后弹窗用）。
     *
     * <p>用户 2026-10-04 原话：「我点击检查更新后重启 app 了，这样是热更新好了吗？
     * <b>太不明显了吧</b>，能不能弹窗口让用户更容易看出更新过」——
     * 以前激活**只写日志**，用户根本不知道更没更上（因此白跑过一轮 A/B）。
     * <p>格式 {@code "<补丁id>|<更新说明>"}；{@link #takeAnnounce()} 取走即清（只弹一次）。
     */
    private static volatile String pendingAnnounce = null;

    /** 取走"刚更新的播报"（取一次就清空 ⇒ 不会每次进界面都弹） */
    public static String takeAnnounce() {
        String s = pendingAnnounce;
        pendingAnnounce = null;
        return s;
    }

    /**
     * 补丁 id 里编的**构建版本** —— id 形如 `hot-<vc>-<sha8>`（见 `tools/release.py` 的
     * `hot_id()`）⇒ 解析出 `<vc>`；解析不出返回 **-1**（保守：判不了就不动它 ✓）。
     */
    private static int patchBuildVc(String id) {
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

    public static synchronized void bootRecover(Context ctx) {
        try {
            File hot = hotRoot(ctx);
            File active = hotActive(ctx);
            File pending = hotPending(ctx);
            JSONObject st = readState(ctx);
            final int myVc = myVersionCode(ctx);

            // ⭐⭐⭐ v1.49【比 APK **旧**的补丁 ⇒ 直接丢弃】—— 治「旧补丁静默遮蔽新 APK」
            //   真机事故（2026-10-04，v1.48）：装完新 APK 后，手机上活跃的还是
            //     `hot-147`（v1.47 时构建的）⇒ 而补丁层含 `explore_loop.py` 等**业务模块**
            //     ⇒ 它**盖住**了 APK v1.48 的新代码 ⇒ 新功能**静默不生效** ✗✗
            //     症状和上一次（桥层被遮蔽）**一模一样**：功能没用，而**看 APK 完全正常** ✗
            //   根因：原来只判 `minShell ≤ appVersionCode` ⇒ 只知道"**能不能用**"，
            //     不知道"**够不够新**" ⇒ 旧补丁永远算"可用" ✗
            //   ⇒ 补丁 id 是 `hot-<vc>-<sha8>`，**构建版本就编在 id 里** ⇒ 解析出来比一下 ✓
            //     判据：`id 版本 < app 版本` ⇒ **APK 的代码按构造一定更新** ⇒ 补丁必陈旧 ✓
            //   ⚠ 解析不出（老格式/异常）⇒ **不动它**（保守 ✓，绝不误删好补丁）
            if (active.isDirectory()) {
                String aid = st.optString("active", "");
                int avc = patchBuildVc(aid);
                if (avc >= 0 && avc < myVc) {
                    File bad = new File(hotBad(ctx), "stale-" + aid + "-" + stamp());
                    if (move(active, bad)) {
                        AppLog.i(TAG + " ⚠ 补丁 " + aid + " 是 **v" + avc
                                + "** 时构建的，而当前 APK 是 **v" + myVc
                                + "** ⇒ 补丁比 APK 旧 ⇒ **已丢弃**"
                                + "（APK 内置代码按构造更新 ✓；取证留在 hot/bad/）");
                        st.remove("active");
                        st.remove("confirmed");
                        st.put("staleDropped", aid);
                        writeState(ctx, st);
                    }
                }
            }

            // ① 回滚未确认的 active
            if (active.isDirectory()) {
                String id = st.optString("active", "");
                boolean confirmed = st.optBoolean("confirmed", false);
                if (!id.isEmpty() && !confirmed) {
                    File bad = new File(hotBad(ctx), id + "-" + stamp());
                    if (move(active, bad)) {
                        AppLog.i(TAG + " ⚠ 补丁 " + id + " 上次激活后**没能启动**"
                                + " ⇒ 已自动回滚到内置版本（取证留在 hot/bad/）");
                        st.remove("active");
                        st.put("confirmed", false);
                        st.put("rolledBack", id);
                        writeState(ctx, st);
                    }
                }
            }

            // ② 激活 pending（下载已完成、只等一次冷启动）
            //    ⭐ v1.49：先拦"比 APK 旧"的 pending（见上面 active 那段的长注释 ✓）
            //      —— 否则一个陈旧 pending 会被激活 ⇒ 又遮蔽新 APK ✗
            if (pending.isDirectory() && new File(pending, "meta.json").isFile()) {
                String pid = readMeta(pending).optString("id", "?");
                int pvc = patchBuildVc(pid);
                if (pvc >= 0 && pvc < myVc) {
                    File bad = new File(hotBad(ctx), "stale-pend-" + pid + "-" + stamp());
                    if (move(pending, bad)) {
                        AppLog.i(TAG + " ⚠ pending 补丁 " + pid + " 是 v" + pvc
                                + " 时构建的（< APK v" + myVc + "）⇒ **不激活**，已归档");
                    }
                }
            }
            if (pending.isDirectory() && new File(pending, "meta.json").isFile()) {
                String pid = readMeta(pending).optString("id", "?");
                if (active.isDirectory()) {
                    // 上一次的 active 已被确认过（否则上面就回滚了）⇒ 直接归档，不再占 sys.path
                    move(active, new File(hotBad(ctx), "prev-" + stamp()));
                }
                if (move(pending, active)) {
                    st.put("active", pid);
                    st.put("confirmed", false);
                    st.put("activatedAt", now());
                    writeState(ctx, st);
                    AppLog.i(TAG + " 补丁 " + pid + " 已激活（等自检确认）");
                    // ⭐⭐ v1.45g：**记一笔，等界面起来弹窗告诉用户**
                    //   用户 2026-10-04 原话：「我点击检查更新后重启app了，这样是热更新好了吗？
                    //   **太不明显了吧**，能不能弹窗口让用户更容易看出更新过」
                    //   ⇒ 以前激活**只写日志** ⇒ 用户根本不知道更没更上（因此白跑了一轮 A/B）
                    String _notes = "";
                    try {
                        _notes = readMeta(active).optString("notes", "");
                    } catch (Throwable ignored) {
                    }
                    pendingAnnounce = pid + "|" + _notes;
                } else {
                    AppLog.i(TAG + " ⚠ 补丁 " + pid + " 激活失败（rename 不动？）");
                }
            }
            if (!hot.exists()) {
                hot.mkdirs();
            }
        } catch (Throwable t) {
            AppLog.i(TAG + " bootRecover 异常：" + t);
        }
    }

    /**
     * ⭐⭐ Python 起来之后立刻调用（{@code PyBridge.ensureStarted} 尾部）。
     *
     * <p>只有"刚激活、还没确认过"的补丁才自检 —— 自检 = 让 Python 真的 import 一遍
     * {@code explore_android}（它会连锁 import mapbot / explore_loop / cv2 …），
     * <b>任何一个环节坏掉都会当场暴露</b>，然后<b>在同一次启动内</b>回滚，朋友无感。
     */
    public static void onPythonStarted(Context ctx) {
        try {
            JSONObject st = readState(ctx);
            if (!st.has("active") || st.optBoolean("confirmed", false)) {
                return;
            }
            String id = st.optString("active", "?");
            String r = PyBridge.call("hot_selftest");
            if (r != null && r.startsWith("ok")) {
                st.put("confirmed", true);
                writeState(ctx, st);
                AppLog.i(TAG + " ✓ 补丁 " + id + " 自检通过：" + r);
                return;
            }
            // 自检失败 ⇒ 同一次启动内回滚（把 active 挪走，sys.path 上的路径自然失效）
            File active = hotActive(ctx);
            if (move(active, new File(hotBad(ctx), id + "-selftest-" + stamp()))) {
                st.remove("active");
                st.put("rolledBack", id);
                st.put("confirmed", false);
                writeState(ctx, st);
                AppLog.i(TAG + " ⚠ 补丁 " + id + " **自检失败** ⇒ 已回滚：" + r);
            }
            // ⚠⚠ 回滚后必须**卸掉已经加载成功的那部分补丁模块**，否则会留下
            //   "一半补丁一半内置"的混血状态 —— 那比全内置难查得多：
            //   例：补丁里的 mapbot 加载成功、explore_loop 失败 ⇒ 回滚后 mapbot 还是补丁那份。
            //   ⚠ 顺序：**先移走目录再卸** —— 这样 hot_reset_modules 自己必然是从内置 .imy 加载的 ✓
            String n = PyBridge.call("hot_reset_modules");
            String r2 = PyBridge.call("hot_selftest");
            AppLog.i(TAG + " 回滚后内置版自检：" + (r2 == null ? "null" : r2)
                    + "（卸下补丁模块 " + n + " 个）");
        } catch (Throwable t) {
            AppLog.i(TAG + " onPythonStarted 异常：" + t);
        }
    }

    // ───────────────────────── 对外总入口 ─────────────────────────

    /**
     * ⭐ 热更状态一句话（给反馈包 / {@code pyinfo} / 悬浮条日志用）。
     *
     * <p>为什么值得单独写一行诊断：朋友说"更新完还是老样子"时，必须先分清是
     * <b>没下到</b> / <b>下了没激活</b> / <b>激活了但自检回滚了</b> —— 三种现象一样、
     * 处置完全不同。这一行把这三态一次说清。
     */
    public static String statusLine(Context c) {
        try {
            JSONObject st = readState(c);
            String active = st.optString("active", "");
            String rolled = st.optString("rolledBack", "");
            boolean conf = st.optBoolean("confirmed", false);
            File pend = hotPending(c);
            boolean pendReady = pend.isDirectory() && new File(pend, "meta.json").isFile();

            StringBuilder sb = new StringBuilder();
            sb.append("壳 v").append(versionName(c)).append("(").append(myVersionCode(c)).append(")");
            sb.append(" · 补丁=");
            if (active.isEmpty()) {
                sb.append("无（用内置）");
            } else {
                sb.append(active).append(conf ? "(已确认)" : "(待自检)");
            }
            if (pendReady) {
                sb.append(" · 待激活=").append(readMeta(pend).optString("id", "?"));
            }
            if (!rolled.isEmpty()) {
                sb.append(" · 上次回滚=").append(rolled);
            }
            String p = hotActivePath(c);
            if (p != null) {
                sb.append(" · dir=").append(p);
            }
            return sb.toString();
        } catch (Throwable t) {
            return "热更状态读取失败：" + t;
        }
    }

    // ───────────────────── 更新探测（**无副作用**，v2.133）─────────────────────

    /**
     * ⭐⭐⭐ v2.133：**只探测、不动手**（用户 2026-11-14：「所有更新前都要弹确认」）。
     *
     * @return {@code null} = 无需更新；否则
     *         {@code {"kind":"hot"|"apk","id":...,"versionName":...,"size":<long>,"notes":"..."}}
     *
     * <p>⚠⚠ <b>本方法只许读清单与本地状态</b>（清单 = 一次 HTTP GET；状态 = {@code hot/state.json}）：
     * <b>绝不许下载、绝不许写文件</b> —— 它在用户点「立即更新」<b>之前</b>被界面调用，
     * 一旦这里偷偷装包，"更新前确认"就变成假的 ✗（门禁 v2.133 A① 按结构钉住）。
     *
     * <p>⚠ 网络/解析失败<b>照常抛</b>，别吞成 null —— 吞了界面会显示"已是最新"，
     * 那正是本仓反复踩的"判据 fail-open"坑（v1.62 veto 被冲掉 / v1.63 band 裁掉 HUD /
     * v1.64 mk 是 dict / v1.71 轮首读成 None）。
     */
    public static JSONObject plan(Context ctx) throws Exception {
        return planOf(ctx, fetchManifest());
    }

    /**
     * {@link #plan} 的判定体（顺手给 {@link #run} 复用 —— 一次检查只拉一份清单）。
     *
     * <p>⚠ 同样**无副作用**：只读清单 + {@code state.json}（{@link #hotVerdict} 靠它判
     * 「已装过 / 已拉黑 / 比 APK 旧」），不下载、不写盘。
     */
    private static JSONObject planOf(Context ctx, JSONObject m) throws Exception {
        final int myVc = myVersionCode(ctx);
        // ⚠ 这里**只取 hot 段**：整包（app 段）按用户口径完全不参与"要不要更新"的判断，
        //   见下面 return null 之前那段注释。
        JSONObject hot = m.optJSONObject("hot");

        // 补丁优先（小、无感）—— 判据与 run(hot) 完全同源，别写第二份
        if (hot != null && "可用".equals(hotVerdict(ctx, hot, myVc))) {
            JSONObject p = new JSONObject();
            p.put("kind", "hot");
            p.put("id", hot.optString("id", "?"));
            p.put("versionName", versionName(ctx));
            p.put("size", hot.optLong("size", 0));
            p.put("notes", hot.optString("notes", ""));
            return p;
        }
        // ⭐⭐ 2026-11-14 用户改口径（原话：「更新系统能直接更新整包吗？」⇒ 要能）：
        //   ① 热补丁优先（上面那段：小、无感）—— 有补丁就先更补丁
        //   ② 没有可用补丁、且清单里整包版本更高 ⇒ 返回 kind=apk ⇒ 界面弹确认框
        //      （确认框里会写明 71MB / 走系统安装器 / 需授权「安装未知应用」）
        //   ③ 两条都没有 ⇒ null ⇒ 界面回「已是最新」
        //   ⚠ 权限检查在 installApk **开头**（download 之前）：没授权只会跳设置页 +
        //     回一句「回来再点一次更新」（用户 2026-11-14 明确要「不自动继续」）。
        //   ⚠ 门禁 v2.135 A①/③/④ 钉着这三件事，改这里先看断言。
        JSONObject app = m.optJSONObject("app");
        if (app != null && !app.isNull("url") && app.optInt("versionCode", 0) > myVc) {
            JSONObject p = new JSONObject();
            p.put("kind", "apk");
            p.put("id", String.valueOf(app.optInt("versionCode", 0)));
            p.put("versionName", app.optString("versionName",
                    String.valueOf(app.optInt("versionCode", 0))));
            p.put("size", app.optLong("size", 0));
            p.put("notes", app.optString("notes", ""));
            return p;
        }
        return null;
    }

    /** 把 {@link #plan} 的结果变成一句**给用户看**的提示（后台只提示、不安装） */
    private static String hintOf(JSONObject p) {
        String size = mb(p.optLong("size", 0));
        String tail = "），去 MGAS 界面点「检查更新」确认安装";
        if ("hot".equals(p.optString("kind", "apk"))) {
            return "有新补丁 " + p.optString("id", "?") + "（" + size + tail;
        }
        return "有新整包 v" + p.optString("versionName", "?") + "（" + size + tail;
    }

    /**
     * 一个入口，四种用法（悬浮条按钮 / 广播 / 界面都用它，避免三份逻辑分叉）。
     *
     * @param mode {@code check} 只查并报告 ／ <b>{@code bg} / {@code auto} 只探测 + 回一句提示
     *             （v2.133：<b>一律不安装</b>）</b> ／ {@code hot} 补丁（下载待重启生效）
     *             ／ {@code apk} 整包（下载 + 弹系统安装器）
     * @return 一句/几行给人看的结果（调用方会写进悬浮条日志行）
     * @see #plan 无副作用的探测（界面"先确认再更新"用它，别用 {@code run(auto)}）
     */
    public static String run(Context ctx, String mode) {
        try {
            int myVc = myVersionCode(ctx);
            int myHotShell = shellOf(ctx);
            JSONObject m = fetchManifest();
            JSONObject app = m.optJSONObject("app");
            JSONObject hot = m.optJSONObject("hot");

            String hotVerdict = hotVerdict(ctx, hot, myVc);
            String apkVerdict = apkVerdict(ctx, app, myVc);

            if ("check".equals(mode)) {
                return "当前 v" + versionName(ctx) + "(" + myVc + ")"
                        + " · 补丁：" + hotVerdict
                        + " · 整包：" + apkVerdict;
            }

            // ⭐⭐ v2.133（用户 2026-11-14 拍板）：
            //   ①「**所有更新前都要弹确认**（含后台发现的补丁）」
            //   ②「后台检查保留，但只**发现并提示**，**一律不安装**」
            //   ⇒ bg 从"一发现补丁就静默 applyHot"改成"只探测 + 回一句提示"
            //   返回 null = 没啥可说 ⇒ 调用方静默，不往日志刷噪音。
            if ("bg".equals(mode)) {
                JSONObject p = planOf(ctx, m);
                return p == null ? null : hintOf(p);
            }

            // ⭐⭐ v2.133：`auto` 原来是「补丁优先、没有就整包」⇒ **直接下载并安装** ✗
            //   用户口径是"点「检查更新」→ 看清版本号/大小/公告 → 我再决定"
            //   ⇒ auto 与 bg 同口径：**只探测、只回提示**；
            //     真下载只走界面确认之后的 run(hot) / run(apk)
            if ("auto".equals(mode)) {
                JSONObject p = planOf(ctx, m);
                if (p == null) {
                    return "已是最新（v" + versionName(ctx) + "）· 补丁：" + hotVerdict;
                }
                return hintOf(p);
            }

            // ⭐ hot / apk = **用户在确认框点了「立即更新」之后**那条路（界面 / 广播调它）
            if ("hot".equals(mode)) {
                if (hot != null && "可用".equals(hotVerdict)) {
                    return applyHot(ctx, hot);
                }
                return "补丁：" + hotVerdict + "（不用更）";
            }
            if ("apk".equals(mode)) {
                if (app != null && app.optInt("versionCode", 0) > myVc) {
                    return installApk(ctx, app);
                }
                return "整包：" + apkVerdict + "（不用更）";
            }
            // 其余（含 null 传进来）：只报状态，不动手
            return "已是最新（v" + versionName(ctx) + "）· 补丁：" + hotVerdict;
        } catch (Throwable t) {
            String msg = "更新检查失败：" + t;
            AppLog.i(TAG + " " + msg);
            return msg;
        }
    }

    /** 补丁可用性判据（三种"不可用"，每种都要能说清为什么 —— 否则线上没法排查） */
    private static String hotVerdict(Context ctx, JSONObject hot, int myVc) {
        if (hot == null || hot.isNull("url")) {
            return "无";
        }
        String id = hot.optString("id", "?");
        // ① 这个补丁要求的**最低壳版本**：补丁可能用了新壳才有的 Java 接口 ⇒ 壳太老不许装
        int minShell = hot.optInt("minShell", 0);
        if (myVc < minShell) {
            return "需要先更新整包（补丁要求壳 ≥ " + minShell + "，本机 " + myVc + "）";
        }
        // ② 已经装过同一个补丁
        JSONObject st = readState(ctx);
        if (id.equals(st.optString("active", ""))) {
            return "已是最新";
        }
        if (id.equals(st.optString("rolledBack", ""))) {
            // ③ 同一个坏包不许自动重装（否则每次启动都下 2MB 再回滚，纯浪费流量）
            return "该补丁上次自检失败已拉黑（等下一个 id）";
        }
        // ⭐⭐⭐ v1.50【比当前 APK **旧**的补丁 ⇒ 从源头就不下】
        //   这是 v1.49「陈旧补丁自动丢弃」的**上游**那半 —— 两半配合才完整：
        //     · v1.49：已经在 `hot/active` 里的陈旧补丁 ⇒ **丢弃**（清场 ✓）
        //     · v1.50（本条）：清单里挂着的陈旧补丁 ⇒ **直接报"不可用"、根本不下载** ✓
        //   ⚠ 为什么需要这半：只做 v1.49 的话，清单里还挂着旧补丁 ⇒
        //     悬浮条一起来（`run(ctx,"bg")`）就**再下一遍 0.3MB** ⇒ 下次启动又丢一次 ✗
        //     症状是**每启动一次白下一次 + 日志里一行"已丢弃"**（不出错，但纯浪费 + 看着吓人）
        //   判据：`hot-<vc>-<sha8>` 里的 `<vc>` < 当前 APK 版本 ⇒ APK 代码按构造更新 ✓
        //   ⚠ 判不出（老格式）⇒ **不拦**（保守：宁可多下一次，也别漏掉真该用的补丁 ✓）
        int bid = patchBuildVc(id);
        if (bid >= 0 && bid < myVc) {
            return "比当前 APK 旧（补丁 v" + bid + " < 本机 v" + myVc
                    + "）⇒ 不用下（APK 内置代码按构造更新）";
        }
        return "可用";
    }

    private static String apkVerdict(Context ctx, JSONObject app, int myVc) {
        if (app == null || app.isNull("url")) {
            return "无";
        }
        int vc = app.optInt("versionCode", 0);
        if (vc <= myVc) {
            return "已是最新";
        }
        return "有新版 v" + app.optString("versionName", String.valueOf(vc))
                + "（" + mb(app.optLong("size", 0)) + "）";
    }

    // ───────────────────────── 逻辑热更 ─────────────────────────

    /** 下载补丁 → 校验 sha256 → 解到 pending（**下次冷启动由 bootRecover 激活**） */
    private static String applyHot(Context ctx, JSONObject hot) throws Exception {
        String id = hot.getString("id");
        String url = hot.getString("url");
        long size = hot.optLong("size", 0);
        String sha = hot.optString("sha256", "");

        File pend = hotPending(ctx);
        deleteRec(pend);
        if (!pend.mkdirs()) {
            throw new IOException("建不了 pending 目录：" + pend);
        }
        File zip = new File(hotRoot(ctx), "dl.zip");
        if (zip.exists() && !zip.delete()) {
            AppLog.i(TAG + " 旧 dl.zip 删不掉（不影响，会被覆盖）");
        }
        download(url, zip, MAX_HOT_BYTES);
        if (size > 0 && zip.length() != size) {
            zip.delete();
            throw new IOException("补丁大小不符：下到 " + zip.length() + "，清单写 " + size);
        }
        if (!sha.isEmpty()) {
            String got = sha256(zip);
            if (!got.equalsIgnoreCase(sha)) {
                zip.delete();
                throw new IOException("补丁 sha256 不符（下到 " + got.substring(0, 12)
                        + "…，清单写 " + sha.substring(0, Math.min(12, sha.length())) + "…）");
            }
        }
        int n = unzip(zip, pend);
        zip.delete();
        JSONObject meta = new JSONObject();
        meta.put("id", id);
        meta.put("sha256", sha);
        meta.put("files", n);
        meta.put("installedAt", now());
        meta.put("notes", hot.optString("notes", ""));
        writeText(new File(pend, "meta.json"), meta.toString());

        // ⚠ 报"补丁大小"要报**补丁包**的大小（`hot.size`），不是 meta.json 的大小
        //   —— 2026-10-03 实测踩到：写成 `new File(pend,"meta.json").length()` ⇒ 日志里
        //   永远是「0.0MB」，看起来像"什么都没下到"，排查时会被误导 ✗
        String msg = "补丁 " + id + " 已就绪（" + n + " 个文件，"
                + mb(hot.optLong("size", 0)) + "）· **重启 MGAS 生效**";
        AppLog.i(TAG + " " + msg);
        return msg;
    }

    // ───────────────────────── APK 自更新 ─────────────────────────

    /**
     * 下载整包 → sha256 校验 → 放进公共 `Download/autoexplore/` → 交系统安装器。
     *
     * <h3>为什么不用 {@code PackageInstaller.Session}（改过一版，记下来）</h3>
     * 2026-10-03 在 MuMu（Android 12）实测：Session 的 createSession / openWrite / fsync / commit
     * <b>全都不抛异常</b>，回调却是 {@code status=-1 / msg=null}，而且<b>系统日志里连一条
     * PackageInstaller 记录都没有</b>、安装界面也不弹。同一台机器上 {@code adb install} 同一个包
     * 却成功 ⇒ 不是包的问题，是这个 ROM 的 Session 通道坏了/被裁（appops 命令都没有）。
     *
     * <p>⇒ 改用<b>兼容性最好的标准路径</b>（等价于"用户在文件管理器里点这个 APK"）：
     * ① {@code MediaStore.Downloads} 把包写进公共 `Download/autoexplore/`（API 29+ 免任何权限，
     * 这套写法在 v1.14 的反馈包上已真机实测通过 ✓）；② {@code ACTION_VIEW} + `content://` URI
     * 交系统安装器；③ <b>提示里带上文件路径兜底</b> —— 界面万一没弹，朋友手动点那个包也能装。
     */
    private static String installApk(Context ctx, JSONObject app) throws Exception {
        int vc = app.getInt("versionCode");
        String vn = app.optString("versionName", String.valueOf(vc));
        String url = app.getString("url");
        String sha = app.optString("sha256", "");

        // Android 8+ 装未知来源要先拿到「安装未知应用」授权 —— 没给就跳设置页，并说清下一步
        PackageManager pm = ctx.getPackageManager();
        if (Build.VERSION.SDK_INT >= 26 && !pm.canRequestPackageInstalls()) {
            try {
                Intent i = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + ctx.getPackageName()));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                ctx.startActivity(i);
                String m = "请先允许本应用「安装未知应用」，回来再点一次更新";
                AppLog.i(TAG + " " + m);
                return m;
            } catch (Throwable t) {
                AppLog.i(TAG + " 跳「未知来源」设置失败：" + t);
            }
        }

        File dir = ctx.getExternalFilesDir(null);
        if (dir == null) {
            dir = new File(ctx.getFilesDir(), "upd");       // 兜底（外部存储不可用）
        }
        // ⚠ 文件名用 **versionName**（不是 versionCode）：一眼看得出是哪个版本，
        //   也避免"清单是为测试抬过的假 versionCode"这种脏名字（2026-10-03 实测踩到 MGAS-v999.apk）
        String name = "MGAS-v" + vn + ".apk";
        File dst = new File(dir, name);
        download(url, dst, MAX_APK_BYTES);
        if (dst.length() < 1024 * 1024) {
            throw new IOException("下到的 APK 太小（" + dst.length() + "B）⇒ 多半是错页/被拦");
        }
        if (!sha.isEmpty()) {
            String got = sha256(dst);
            if (!got.equalsIgnoreCase(sha)) {
                throw new IOException("APK sha256 不符（下到 " + got.substring(0, 12) + "…）");
            }
        }

        Uri uri = publishToDownloads(ctx, dst, name);
        if (uri == null) {
            String m = "整包 v" + vn + " 已下载到 " + dst.getAbsolutePath()
                    + "，请用文件管理器手动安装";
            AppLog.i(TAG + " " + m);
            return m;
        }
        try {
            Intent i = new Intent(Intent.ACTION_VIEW)
                    .setDataAndType(uri, "application/vnd.android.package-archive")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                            | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            ctx.startActivity(i);
        } catch (Throwable t) {
            String m = "整包已放到 Download/autoexplore/" + name + "，但拉不起安装器（" + t
                    + "）⇒ 请到文件管理器里点它安装";
            AppLog.i(TAG + " " + m);
            return m;
        }
        String msg = "整包 v" + vn + " 已下载（" + mb(dst.length())
                + "）· 安装界面应弹出，点「安装」即可"
                + "（包也在 Download/autoexplore/" + name + "，没弹就手动点它）";
        AppLog.i(TAG + " " + msg);
        return msg;
    }

    /**
     * 把 APK 写进公共 `Download/autoexplore/`，返回可交给安装器的 `content://` URI。
     *
     * <p>⚠ 为什么不用 FileProvider：那要引 androidx（本工程没有，加依赖得联网拉包 ✗）；
     * {@code MediaStore.Downloads} 在 API 29+ 免权限，且这套写法在本工程反馈包（v1.14）上
     * 已真机实测通过 ✓。API 26~28 写公共目录要 {@code WRITE_EXTERNAL_STORAGE}（本工程不申请）
     * ⇒ 返回 null，让调用方给"手动安装"的指引。
     */
    private static Uri publishToDownloads(Context ctx, File src, String name) {
        if (Build.VERSION.SDK_INT < 29) {
            return null;
        }
        OutputStream os = null;
        try {
            android.content.ContentValues cv = new android.content.ContentValues();
            cv.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
            cv.put(MediaStore.MediaColumns.MIME_TYPE, "application/vnd.android.package-archive");
            cv.put(MediaStore.MediaColumns.RELATIVE_PATH,
                    Environment.DIRECTORY_DOWNLOADS + "/autoexplore");
            Uri item = ctx.getContentResolver().insert(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
            if (item == null) {
                AppLog.i(TAG + " MediaStore 拒绝插入（返回 null）⇒ 走手动安装路径");
                return null;
            }
            os = ctx.getContentResolver().openOutputStream(item);
            if (os == null) {
                return null;
            }
            try (InputStream in = new BufferedInputStream(new FileInputStream(src))) {
                copy(in, os);
            }
            os.flush();
            AppLog.i(TAG + " 整包已写入公共下载目录：" + item);
            return item;
        } catch (Throwable t) {
            AppLog.i(TAG + " 写公共下载目录失败（走手动安装路径）：" + t);
            return null;
        } finally {
            try {
                if (os != null) {
                    os.close();
                }
            } catch (Throwable ignored) {
            }
        }
    }

    /** 供 {@link CommandReceiver} 的 {@code install_result} 分支调用 */
    public static String describeInstallResult(Intent it) {
        int status = it.getIntExtra(PackageInstaller.EXTRA_STATUS, Integer.MIN_VALUE);
        String msg = it.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
        switch (status) {
            case PackageInstaller.STATUS_SUCCESS:
                return "✓ 安装成功（" + msg + "）";
            case PackageInstaller.STATUS_FAILURE_ABORTED:
                return "安装被取消/中止（" + msg + "）";
            case PackageInstaller.STATUS_FAILURE_BLOCKED:
                return "安装被系统拦截（" + msg + "）—— 多半是「安装未知应用」没允许";
            case PackageInstaller.STATUS_FAILURE_CONFLICT:
                return "安装冲突（" + msg + "）—— 多半是签名不一致（别用别的渠道的包覆盖）";
            case PackageInstaller.STATUS_FAILURE_INCOMPATIBLE:
                return "不兼容（" + msg + "）—— 检查 ABI（要 arm64）与 minSdk";
            case PackageInstaller.STATUS_FAILURE_INVALID:
                return "包无效（" + msg + "）—— 下载可能坏了，重下一次";
            case PackageInstaller.STATUS_FAILURE_STORAGE:
                return "存储不足（" + msg + "）";
            default:
                return "安装结果 status=" + status + " msg=" + msg;
        }
    }

    // ───────────────────────── 网络 / 校验 / 解压 ─────────────────────────

    /**
     * 拉更新清单：**优先 API contents（实时）**，失败才回落 raw（可能有缓存）。
     *
     * <p>为什么不能只用 raw：见 {@link #MANIFEST_RAW} 的注释 —— Gitee raw 有强缓存，
     * 刚发的清单读回来还是旧的，表现为"发了新版端上却说已是最新"。
     * 回落的意义：API 有匿名速率限制，被限流时至少还能拿到（可能是几分钟前的）清单，
     * 总比"检查更新失败"强 ✓
     */
    private static JSONObject fetchManifest() throws Exception {
        try {
            String s = httpGet(MANIFEST_API, 512 * 1024);
            JSONObject o = new JSONObject(s);
            String b64 = o.optString("content", "");
            if (b64.isEmpty()) {
                throw new IOException("contents 响应里没有 content");
            }
            b64 = b64.replace("\n", "").replace("\r", "");
            byte[] raw = Base64.decode(b64, Base64.DEFAULT);
            return new JSONObject(new String(raw, "UTF-8"));
        } catch (Throwable t) {
            AppLog.i(TAG + " API 通道读清单失败 ⇒ 回落 raw（可能是缓存版）：" + t);
            return new JSONObject(httpGet(MANIFEST_RAW, 512 * 1024));
        }
    }

    private static String httpGet(String url, long maxBytes) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(CONNECT_MS);
        c.setReadTimeout(READ_MS);
        c.setRequestProperty("User-Agent", UA);
        c.setInstanceFollowRedirects(true);
        try {
            int code = c.getResponseCode();
            if (code != 200) {
                throw new IOException("HTTP " + code);
            }
            StringBuilder sb = new StringBuilder();
            try (InputStream in = new BufferedInputStream(c.getInputStream())) {
                byte[] buf = new byte[8192];
                int n;
                long total = 0;
                while ((n = in.read(buf)) > 0) {
                    total += n;
                    if (total > maxBytes) {
                        throw new IOException("清单超过 " + maxBytes + "B（不对劲）");
                    }
                    sb.append(new String(buf, 0, n, "UTF-8"));
                }
            }
            return sb.toString();
        } finally {
            c.disconnect();
        }
    }

    private static void download(String url, File dst, long maxBytes) throws IOException {
        File p = dst.getParentFile();
        if (p != null && !p.exists() && !p.mkdirs()) {
            throw new IOException("建不了目录：" + p);
        }
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(CONNECT_MS);
        c.setReadTimeout(READ_MS);
        c.setRequestProperty("User-Agent", UA);
        c.setInstanceFollowRedirects(true);
        try {
            int code = c.getResponseCode();
            if (code != 200) {
                throw new IOException("HTTP " + code + " @ " + url);
            }
            long total = 0;
            try (InputStream in = new BufferedInputStream(c.getInputStream());
                 OutputStream os = new FileOutputStream(dst)) {
                byte[] buf = new byte[64 * 1024];
                int n;
                while ((n = in.read(buf)) > 0) {
                    total += n;
                    if (total > maxBytes) {
                        throw new IOException("下载超过上限 " + maxBytes + "B，已中止");
                    }
                    os.write(buf, 0, n);
                }
                os.flush();
            }
        } finally {
            c.disconnect();
        }
    }

    private static void copy(InputStream in, OutputStream os) throws IOException {
        byte[] buf = new byte[64 * 1024];
        int n;
        while ((n = in.read(buf)) > 0) {
            os.write(buf, 0, n);
        }
    }

    private static String sha256(File f) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new BufferedInputStream(new FileInputStream(f))) {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) {
                md.update(buf, 0, n);
            }
        }
        StringBuilder sb = new StringBuilder();
        for (byte b : md.digest()) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }

    /** 解压 zip 到 dst（返回文件数）。⚠ 做目录穿越防护，别把包里的 {@code ../../} 放到外面 */
    private static int unzip(File zip, File dst) throws IOException {
        int n = 0;
        try (ZipInputStream zis = new ZipInputStream(
                new BufferedInputStream(new FileInputStream(zip)))) {
            ZipEntry e;
            while ((e = zis.getNextEntry()) != null) {
                String name = e.getName();
                if (name.contains("..") || name.startsWith("/") || name.startsWith("\\")) {
                    AppLog.i(TAG + " ⚠ 跳过可疑条目：" + name);
                    continue;
                }
                File out = new File(dst, name);
                if (e.isDirectory()) {
                    out.mkdirs();
                    continue;
                }
                File par = out.getParentFile();
                if (par != null && !par.exists()) {
                    par.mkdirs();
                }
                try (OutputStream os = new FileOutputStream(out)) {
                    byte[] buf = new byte[64 * 1024];
                    int k;
                    while ((k = zis.read(buf)) > 0) {
                        os.write(buf, 0, k);
                    }
                }
                n++;
            }
        }
        return n;
    }

    // ───────────────────────── 小工具 ─────────────────────────

    private static JSONObject readState(Context c) {
        try {
            File f = stateFile(c);
            if (!f.isFile()) {
                return new JSONObject();
            }
            return new JSONObject(readText(f));
        } catch (Throwable t) {
            AppLog.i(TAG + " state.json 损坏 ⇒ 当没有热更处理：" + t);
            return new JSONObject();
        }
    }

    private static void writeState(Context c, JSONObject o) {
        try {
            hotRoot(c).mkdirs();
            writeText(stateFile(c), o.toString());
        } catch (Throwable t) {
            AppLog.i(TAG + " 写 state.json 失败：" + t);
        }
    }

    private static JSONObject readMeta(File dir) {
        try {
            return new JSONObject(readText(new File(dir, "meta.json")));
        } catch (Throwable t) {
            return new JSONObject();
        }
    }

    private static String readText(File f) throws IOException {
        StringBuilder sb = new StringBuilder();
        try (InputStream in = new BufferedInputStream(new FileInputStream(f))) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                sb.append(new String(buf, 0, n, "UTF-8"));
            }
        }
        return sb.toString();
    }

    private static void writeText(File f, String s) throws IOException {
        try (OutputStream os = new FileOutputStream(f)) {
            os.write(s.getBytes("UTF-8"));
            os.flush();
        }
    }

    private static boolean move(File from, File to) {
        try {
            File par = to.getParentFile();
            if (par != null && !par.exists()) {
                par.mkdirs();
            }
            if (to.exists()) {
                deleteRec(to);
            }
            return from.renameTo(to);
        } catch (Throwable t) {
            AppLog.i(TAG + " 移动 " + from + " → " + to + " 失败：" + t);
            return false;
        }
    }

    private static void deleteRec(File f) {
        try {
            if (f == null || !f.exists()) {
                return;
            }
            if (f.isDirectory()) {
                File[] cs = f.listFiles();
                if (cs != null) {
                    for (File c : cs) {
                        deleteRec(c);
                    }
                }
            }
            if (!f.delete()) {
                AppLog.i(TAG + " 删不掉：" + f);
            }
        } catch (Throwable ignored) {
        }
    }

    private static int myVersionCode(Context c) {
        try {
            PackageInfo pi = c.getPackageManager().getPackageInfo(c.getPackageName(), 0);
            return pi.versionCode;
        } catch (Throwable t) {
            return BuildConfig.VERSION_CODE;
        }
    }

    private static String versionName(Context c) {
        try {
            PackageInfo pi = c.getPackageManager().getPackageInfo(c.getPackageName(), 0);
            return pi.versionName;
        } catch (Throwable t) {
            return BuildConfig.VERSION_NAME;
        }
    }

    /**
     * ⭐ 当前**壳**版本 = 应用版本 + 已生效补丁的 id。
     * 目的：补丁清单里写 {@code minShell} 时，我可以说"这个补丁要求壳 ≥ 141"，
     * 而壳版本就是 versionCode（补丁不改变它 ⇒ 判据稳定 ✓）。
     */
    private static int shellOf(Context c) {
        return myVersionCode(c);
    }

    private static String mb(long bytes) {
        return String.format(Locale.US, "%.1fMB", bytes / 1024.0 / 1024.0);
    }

    private static long now() {
        return System.currentTimeMillis() / 1000L;
    }

    private static String stamp() {
        return new SimpleDateFormat("MMdd_HHmmss", Locale.US).format(new Date());
    }
}
