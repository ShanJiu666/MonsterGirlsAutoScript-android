# 幻想少女公会 · 自动探索手机版（APK）

> 2026-09-29 第一阶段落地：**设备层（截图/点击）+ 视觉层（端侧 OCR）+ 参考系归一化**。
> 全部走官方 API，**不需要 root、不需要 adb、不需要电脑**。

## 1. 现在能做到什么

| 能力 | 实现 | 说明 |
|---|---|---|
| 截图 | `CaptureService`：MediaProjection → VirtualDisplay → ImageReader | 官方 API；每次启动需用户点一次系统授权框 |
| 点击/滑动/返回 | `AutoTouchService`：无障碍 `dispatchGesture` | 产生**真实触摸事件**，与 airtest 效果等价 |
| 全分辨率 | `RefMapper`：一切坐标/模板走 **1080×1920 参考系** | 运行时按真实屏幕算 k / offset，自动归一化 |
| 识别 | `OcrEngine`：ONNX Runtime + RapidOCR PP-OCRv4 det/rec | **逐参数照抄 PC 端 RapidOCR**，坐标可直接对拍 |
| 自检/对拍 | 主界面 ⑤ 识别 + dump（`ref.png` / `ocr.json`） | 拉到电脑与 PC 端 rapidocr 逐条比对 |

## 2. 构建（本机已跑通的环境）

```bash
cd D:/幻想少女公会/android_autoexplore
JAVA_HOME="D:/android-build/jdk17/jdk-17.0.20+8" \
  "/d/android-build/gradle-8.7/bin/gradle.bat" assembleFullDebug
# 产物：app/build/outputs/apk/full/debug/app-debug.apk（双 ABI，MuMu 调试用）

# 发版（arm64-only，124MB → ~77MB）：
#   "/d/android-build/gradle-8.7/bin/gradle.bat" assembleArm64Release
# 产物：app/build/outputs/apk/arm64/release/app-release.apk（debug 签名，真机可覆盖升级）
```

- **ABI 按 flavor 拆（2026-09-29 v0.38 起）**：x86_64 全套（Python + onnxruntime ≈47MB）只为 MuMu 模拟器调试存在，
  发版只打 arm64。⚠ `abiFilters` 不能写 `defaultConfig`（对 buildType 取并集挡不掉）也不能写 buildType
  （Chaquopy 直接报错）⇒ 只能走 flavor：`arm64`（发版）/ `full`（开发/模拟器）。
  ⚠ **没有 `assembleDebug` 这个 task 了**——变体名变成 fullDebug / arm64Release 等四个组合。
- 构建命令前加 `CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD=200000`（防沙箱删除守卫打断 Gradle 内部 pip）。

- JDK 17：`D:/android-build/jdk17/jdk-17.0.20+8`（已写进 `gradle.properties` 的 `org.gradle.java.home`）
- Gradle 8.7：`D:/android-build/gradle-8.7`（不用 wrapper，直接调）
- SDK：`D:/android-build/sdk`（build-tools 34.0.0 / platform android-34，见 `local.properties`）
- AGP 8.5.2 + `com.microsoft.onnxruntime:onnxruntime-android:1.17.0`（首次构建需联网拉依赖）
- ABI 只打 `arm64-v8a` + `x86_64`（手机 / MuMu 模拟器各一套，砍掉一半体积）

## 3. 安装与授权（MuMu 16384 实测流程）

```bash
ADB="D:/MuMu Player 12/shell/adb.exe"
$ADB connect 127.0.0.1:16384
$ADB -s 127.0.0.1:16384 install -r app/build/outputs/apk/debug/app-debug.apk

# 无障碍服务（免手点，直接写 secure 设置）
$ADB -s 127.0.0.1:16384 shell settings put secure enabled_accessibility_services \
  com.fantasy.autoexplore/com.fantasy.autoexplore.AutoTouchService
$ADB -s 127.0.0.1:16384 shell settings put secure accessibility_enabled 1

# 悬浮窗（控制条用；MuMu 没装 appops 可执行文件，必须走 `cmd appops`）
$ADB -s 127.0.0.1:16384 shell cmd appops set com.fantasy.autoexplore SYSTEM_ALERT_WINDOW allow

$ADB -s 127.0.0.1:16384 shell am start -n com.fantasy.autoexplore/.MainActivity
```

> 截图授权框是**系统弹窗**，必须点一次「立即开始/开始录制」（安卓 14 起每次启动都要点，无法持久化）。
> 位置可用 `uiautomator dump` 解出来（MuMu 1080×1920 实测「立即开始」= **(849,1277)**）。
> ⚠ **重装 APK 会杀掉 `CaptureService`** ⇒ 每次 `install -r` 之后都要重新授权一次截图。

## 4. OCR 与 PC 端为什么能对拍

端侧实现完全照抄 `rapidocr_onnxruntime 1.4.4` 的参数（详见 `OcrEngine.java` 头部注释）：

| 项 | 值 |
|---|---|
| 进 det 前的缩放 | **0.75**（参考系 1080×1920 → 810×1440，等同 PC `OCR_SCALE`） |
| det `limit_side_len / limit_type` | 736 / min ⇒ min(810,1440)=810 > 736 ⇒ ratio=1，按 /32 对齐成 **800×1440** |
| det `mean / std / scale` | 0.5 / 0.5 / 1/255 |
| det `thresh / box_thresh / unclip_ratio` | 0.3 / 0.5 / 1.6，`use_dilation=true`（2×2） |
| rec 输入 | `[3,48,320]`，`max_wh_ratio = max(320/48, w/h)`，/255 → −0.5 → /0.5 |
| 解码 | CTC：blank=0、去连续重复、置信度=所选字符 softmax 均值 |
| 字典 | 模型 metadata 的 6623 字 + blank + 空格 = **6625 类**（与模型输出对齐 ✓） |

## 5. 实测结果（2026-09-29 00:2x，MuMu 16384 / Android 12）

| 环节 | 结果 |
|---|---|
| 截图通道 | ✓ `开始截图 1080x1920 dpi=480`（MediaProjection 授权一次后持续出帧） |
| 点击通道 | ✓ 无障碍连接即就绪（`settings put secure` 直接开，无需手点） |
| OCR 引擎 | ✓ 加载 598ms（6625 类字典） |
| 单帧识别 | ✓ **41 条 / 48 框，2016ms**（det 960 ｜ rec 978 ｜ 预处理 30）——模拟器 x86_64 上 |
| 识别质量 | ✓ 认出 `清凉沙滩` / `夏日海滩入侵` / `当前难度156` / `1245/2500`（体力）/ `深渊46~50` / `进入地图` / `开始冒险`，conf 0.99+ |
| 与 PC 对拍 | ✓ PC 38 条 vs 端侧 41 条；同文本配对 35 条，**|Δx| / |Δy| 中位都是 1px**；差异仅「PC 把 `14:19:09`+`09:15:54` 并成一框、端侧正确拆开」这类边界 |
| 手势点击 | ✓ 广播 `cmd=tap_start` → 点 `进入地图(903,1617)` 手势下发 → **游戏真的切进探索图**（夏日海滩[100]，5×7 棋盘，体力 1223/2500），前后帧平均像素差 63.8 |

⇒ **无 root 全链路已打通**：截图 → 参考系归一化 → 端侧 OCR → 找按钮 → 无障碍手势 → 游戏响应，
且识别结果与 PC 端坐标口径可直接混用。

## 6. 第二阶段：端上自己推图（Chaquopy 跑 mapbot 决策层）

> 2026-09-29 落地。设备层留在 Kotlin，**决策层整体搬进 APK 的 Python 运行时**。

### 6.1 分层与职责

```
Kotlin：截图 / OCR / 手势 / 参考系归一化 / 日志        ← 需要系统 API
   ↑ DeviceApi（全是静态方法，Python 侧 jclass('…DeviceApi') 直接调）
Python（Chaquopy 3.11）：
   mapbot.py           Android 版 Bot（**与 PC 同名同语义**：snap/img/ocr/tap/swipe/wait_change/wait_stable）
   spots/marks/badge/buypanels/grid_detect/layout/targets_cfg   ← 识别与坐标（PC 原样搬）
   mapgen/mapsim/mapsolve/strategy                              ← 规划（纯逻辑，与设备无关）
   explore_loop.py     PC 端 4400 行状态机（**整体搬，只打 5 处补丁**）
   explore_android.py  装配层：环境变量 → 开关 → 驱动
```

### 6.2 为什么是「整体搬 explore_loop」而不是重写

先审计跨端调用面，结果极其干净 —— 它**只**通过 `b`（Bot）碰设备：

| 跨端点 | 次数 | 处理 |
|---|---|---|
| `subprocess` | 3 | ② adb 回退键 → Android 走无障碍 `b.back()`；其余在 `tasklist` 查锁里（Android 不用） |
| `loopguard` | 10 | ③④ 进程查重/设备锁 → Android 单实例，直接放行 |
| `mapcollect`（内存通道） | 3 | 无需处理：`COLLECT_REAL_MAPS=False` 默认关（**无 root 读不了内存**） |
| `ADB` | 4 | Android 版 `mapbot.ADB = None` + 上面的分支兜住 |

⇒ 于是 5 处补丁搞定：①`SUPPLY_TPL` 相对路径→绝对 ②adb 回退键 ③查重放行 ④设备锁放行
⑤加 Android 中断钩子（广播 stop 与「04:58 收工」共用同一挂载点，**打完手上这张才停**）。

移植是**可重放的脚本**（PC 端改完重跑即可同步）：

```bash
python tools/build_pack.py     # ① 打资源包：templates/(unit 裁前3帧) + server_datatable.json → assets/mapbot_pack
python tools/port_android.py   # ② 搬 11 个纯逻辑模块 + 资源根改环境变量
python tools/port_loop.py      # ③ 搬 explore_loop.py + 打 5 处补丁
```

### 6.3 两个关键的路径改造

Chaquopy 里 `__file__` 指向 APK 内的**只读**资源，**旁边没有 templates/**。所以：

- `tools/build_pack.py` 把资源打 `assets/mapbot_pack/`，首启由 `PackInstaller` 解到 `filesDir/mapbot_pack`
  （标记文件 `.pack_v2`；模板模块用 `glob + cv2.imread(路径)` 逐个读 PNG，**必须是真实文件**）
- 模块里的「资源根」统一改成**环境变量优先**（`explore_android._bootstrap()` 在 import 前设好）：
  `MAPBOT_ROOT` / `MAPBOT_RUNS` / `MAPBOT_DT`；未设置时**回退 PC 原行为** ⇒ 同一份代码在电脑上仍能跑（便于对拍）

⭐ `templates/unit` 是 10469 个动画帧（21.7MB），但 `spots.py` 的 `_TPL_FRAMES` 默认**只取每 sid 排序后前 3 帧**
⇒ 包里只放前 3 帧（1268 帧 / 2.3MB），结果与 PC **逐字节一致**。
⚠ 代价：Android 上不能再拿 `MAPBOT_TPL_FRAMES=0` 回退全量（帧不在包里）。

### 6.4 端上自检与广播命令

```bash
ADB="D:/MuMu Player 12/shell/adb.exe"; D=127.0.0.1:16384
$ADB -s $D shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
  -a com.fantasy.autoexplore.CMD --es cmd selftest      # 资源→OCR→截图→地块分类→规划器
$ADB -s $D shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
  -a com.fantasy.autoexplore.CMD --es cmd pyinfo        # 环境快照
$ADB -s $D shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
  -a com.fantasy.autoexplore.CMD --es cmd explore --ei maps 1 --ez save_first true
$ADB -s $D shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
  -a com.fantasy.autoexplore.CMD --es cmd explore_status
$ADB -s $D shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
  -a com.fantasy.autoexplore.CMD --es cmd explore_stop
```

日志：`adb logcat -s AutoExplore`（Python 的 `print` 已 tee 到同一路）。

### 6.5 验证结果（2026-09-29 01:2x，MuMu 16384）

```
[1] 资源 ✓  解包 1968 文件 / 647ms   datatable ✓   17 个地图码
[2] import 12 个逻辑模块 ✓（含 cv2 / numpy 原生库）
[3] 截图 1080x1920 ✓  点击(无障碍) ✓       [5] OCR 40 条 2341ms
```

⭐ **端↔PC 等价性（零体力，最强证据）**：同一张真实棋盘帧 `runs/_fixtures/inmap_a.png`
两端各跑一次分类，**35/35 格全等**：

| 比对项 | sid | name | revealed | anchor | score 最大差 | ratio 最大差 |
|---|---|---|---|---|---|---|
| 不一致数 | **0** | **0** | **0** | **0** | **0.0000** | **0.0000** |

⇒ 跨 cv2（端 4.5.1 ↔ PC 4.6.0）与 numpy（1.26.2 ↔ 1.26.4）仍**零偏差**
⇒ `spots/marks/badge` 的判定阈值（`BUY_SCORE_MIN=0.85`、`SAT_MAX=40`、`ratio 0.65/1.0`…）
**原样沿用 PC 标定值即可**，无需在手机上重新标定。

⚠ **自检输出必须报 score**：分类器对**任何**画面都返回固定 35 格（棋盘 7×5），
非棋盘画面也会被硬凑满格（实测选图界面被凑出"游乐设施×6…"）⇒ 只看"认出 N 格"会**误判成功**。
现改为同时报 `score min/中位/max` + "像不像棋盘"判定（中位 ≥0.80 像 / <0.70 判不是棋盘）。
复现命令见 `cmd=classify`。

详细报告：`_verify/验证报告.md`（含原始数据 `board_pc.json` / `board_dev.json`）。

### 6.6 已知边界（v1 未覆盖）

| 项 | 状态 |
|---|---|
| **真机跑完整一张图** | ✅ **2026-09-29 打通**（见 §6.8） |
| **内存通道**（读 `blockBoard`/`roadMap` 真值） | ❌ 无 root 用不了 ⇒ 纯视觉；`COLLECT_REAL_MAPS` 恒关。规划走 `EffPolicy` + 观测盘 solver |
| 非 16:9 手机 | ⚠ `RefMapper` 现在按全屏统一缩放；异形屏若有**游戏自身黑边**会错位（MuMu 1080×1920 无此问题）。真机要按游戏内容区取框 |
| 悬浮窗控制条（M5） | ✅ **已做**（见 §6.8） |
| 崩溃恢复 / 热管理（M5 其余） | 未做 |
| 多机回归矩阵（M6） | 未做 |

### 6.7 排障备忘

- ⚠ `cmd=py` 的 `--es code` 走 adb shell 会被**远端 shell 再解析**：代码里的 `;` 会被当命令分隔符
  ⇒ 用 `exec(__import__('base64').b64decode('…').decode())` 这种**单表达式、无分号**的形态传
- ⚠ 沙箱删除守卫会打断 Gradle 内部的 pip（`installDebugPythonRequirements` 报"pip 退出码 1"，
  而日志里 pip 其实 "Successfully installed"）⇒ 构建命令前加 `CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD=200000`
- ⚠ 增量构建 ~20s，全量（首次拉 Chaquopy 轮子）可达 17 分钟（源站 arm64 只有 20~35 kB/s）
- ⚠ `adb shell run-as <pkg> cat <文件>` 取**二进制**（截图/png）会走 shell 的 CR/LF 转换 ⇒ 文件损坏
  （`cv2.imread` 返回 `None`）⇒ 二进制一律用 **`adb exec-out run-as … cat`**

### 6.8 悬浮窗控制条（M5）

**为什么要有它**：此前只能靠 `adb shell am broadcast` 启动/停止，日常在手机上根本没法用。
现在 APK 自带一条常驻悬浮条：**打开本应用 → 点「⑫ 悬浮条：开」→ 切回游戏 → 点左下角气泡 → ▶**。

```
收起： ● MGAS                       ← 灰=空闲 / ▶ 绿=运行中 / ! 红=出错 / ⛔ 红=红装锁
展开： ▁▁▁▁▁▁▁ 当前行动（浅底黑字，整行上下滚动）▁▁▁▁▁▁▁   ← 上行（v0.13 起）
       ● MGAS [1图] [▶] [■] [✕]                        ← 下行（按钮）
       1图  点一下 1图 ↔ 连刷（连刷 = 一直刷到体力不够进图为止；落地在 `Prefs.mapsChoice`）
       ▶   **点一下就开始**（不做二次确认/倒计时 —— 用户明确要求；防误触靠 1图 限张数 + ■ 随时停）
       ■   停止（停在两张图之间，打完手上这张收工 ✓ 不留半张）
       ✕   收起
       日志行 = **当前行动**（一句话），点一下往回翻历史（`↺n`），再点回到最新
```
**两行竖向布局**（2026-09-29 v0.9→v0.13 逐步定稿，见 §6.10）：上行日志 34 + 下行按钮 56 = **90px**。
⚠ 历史：更早的"两行"版本展开态顶边到 1665 ⇒ **压住棋盘最低一行**；中间的"单行"版本虽不越界，
但用户看不到日志行 ⇒ 最终回到两行，靠**字号压进预算**（详见 §6.10 的高度预算表）。

**默认位置 = 参考系 `(20,1725)`**（棋盘 1002~1722 下沿与底部导航 ≈1820 之间的空档），
可拖动；展开态闲置 **15 秒自动收起**，但 ⭐ **运行中永远不收起**（见 §6.9）。

#### 六条硬约束（都是踩出来的）

1. **按钮里一个中文字都不能有**：悬浮条会被 `MediaProjection` **一起截进图里**，而探索循环做
   **全屏 OCR + 关键词判定**（`'探索产出'`/`'领取'`/`'关闭'`/`'开始冒险'`…）。出现这类字 ⇒ 误判成游戏面板 ⇒ 乱点。
   ⇒ 只用 `AI ▶ ■ ↻ ✕ ●` 和 `1x…10x`；**同理不能弹 Toast**（Toast 也在截图里）⇒ 状态全靠气泡颜色。
2. **定位必须走 `RefMapper.devX/devY`，不能用 `dp()`**：`dp()` 按屏幕密度换算，
   1080×1920@480dpi 下 `dp(1725) = 5175px` ⇒ **直接飞出屏幕**（第一次就是这么错的）。
3. **必须先 `setExpanded(false)` 再 `addView`**：反过来写（先 addView 再设 GONE）实测**首帧仍是展开的 750px 宽**
   （`mFrame=[20,1725][770,1816]`，截图里六枚按钮全露）——窗口的首次测量没吃到后续的可见性变更。
4. **启动探索前必须把游戏切到前台**：本应用界面上就有「⑥ 点开始冒险」这种字，循环对着本应用截图会去点它。
   ⇒ `OverlayService.onStart()` 与 `MainActivity.pyExploreStart()` 都会先 `bringGameFront()` 再启动。
5. ⭐⭐ **任何一下点击都必须有可见反馈**（2026-09-29 用户报「点浮窗的开始没反应」的根因）：
   日志显示点击**收到了**，但当时的反馈只有"▶ 字色变黄"，在花花绿绿的游戏画面上**根本看不出来**
   ⇒ 用户以为按钮坏了。⇒ 现在每次点击都 `flash()` 闪一下蓝底；每个按钮打独立日志
   （`[ovl] 点 ▶/■/✻/1x/气泡`），下次"点空"和"没反馈"能一眼区分。
   **触屏上「没有即时反馈」≈「坏了」——这条比任何功能都重要。**
   ⚠ 反过来也成立：**别为了防误触加"两段式确认"**。第一版做成"点两次才开跑"，
   用户直接反馈"不要有倒计时 / 倒计时完了也没开始" —— 多一步确认 = 多一次困惑。
   要防误触就用**别的显式手段**：默认张数调小 + `■` 随时能停。
6. **按钮留够最小宽度**（`▶` 192px / `1x` 144px）且固定不随文案变化：既让手指不容易点空，
   也避免 `1x`→`10x` 变宽把 ▶ 挤走位置。

#### 广播（调试用，不必把界面拉到前台）

```bash
$ADB -s $D shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
  -a com.fantasy.autoexplore.CMD --es cmd overlay_on      # 开
# … overlay_off 关；或 am start -n …/.MainActivity -e cmd overlay 切换
```

#### 实测（2026-09-29 02:5x ~ 03:0x，MuMu 16384，v0.7）

| 项 | 结果 |
|---|---|
| 服务 | `isForeground=true foregroundId=1011`（`foregroundServiceType=specialUse`） |
| 几何 | 收起 `bar(dev)=254x77`、展开 `1080x77`；**顶边(参考 y)=1739 底边=1816** ⇒ 顶边 ≥ 1722 ✓ |
| 涂平矩形 | 收起 `[20,1739][274,1816]`、展开 `[20,1739][1080,1816]`（`mask_check` 实测见 §6.9） |
| SECURE | `secure: false` ✓（**必须是 false**，见 §6.9） |
| 三态 | 收起 254px → 点气泡展开 **1080px** → `✕` 收起 ✓ |
| 闲置收起 | 空闲态 15s 自动收起 ✓；**强制运行态等 20s 仍 `expanded: true`** ✓ |
| ▶ 单击直接开始 | `[ovl] 点 ▶ ⇒ 开始` → 立刻走启动路径 ✓（当次无截图权限 ⇒ 只拉授权界面，**零体力**）✓ |
| ▶ 点完**不收起** | 点 ▶ 后 `bar 设备 1080x77 … 展开=true`（旧版是 `setExpanded(false)` ⇒ 用户看不到绿）✓ |
| 点击反馈 | 每次点击 `flash()` 闪蓝 ✓ |
| 按钮坐标（设备像素，y=1777） | `1图/连刷`≈**300~360**、`▶`≈**420~500**、`■`≈**620**、`✕`≈**700** |

> 坐标是**扫描点击 + 读日志**测出来的（`[ovl] 点 ▶ ⇒ 开始` 等每按钮独立日志）。
> `uiautomator dump` **拿不到悬浮窗节点**（`TYPE_APPLICATION_OVERLAY` 窗口没进 dump，只有 1859 字节的 app 窗口），
> 想自动化点按钮只能扫描或按上面这张表。

#### ⭐ 真机跑通一整张图（走悬浮条 ▶，非广播）

```
▶ started
▶ Android 探索启动：maps=1 max_round=45 deadline=900s solver=True save_first=True
[bot] Android 通道：截屏=True 点击=True
== 第 1 张图 ==   进图前体力 1377
{'enter': 'clicked', 'at': (903, 1617)} → {'enter': 'in_map', 'stamina': 1353}
{'solver': 'ok', 'cost': 9, 'steps': 2, 'targets': 1, 'order': ['2,3','3,1']}
board：35 格真识别（草地/营地/宝箱/海螺/勇者之墓/游乐设施/海边游客…）
{'battle': 'started', 'at': (539,734)} → {'battle': 'closed', 'at': (577,1440), 'win': True}
本图结束：done（耗时 62 秒）  ==== 全部结束，共 95 秒
[explore_status] {'running': False, 'result': 'done', 'error': ''}
```

- 统计：**刷完 1 张**、首领关 1 场(胜 1)、全部战斗 1 场(胜 1)、平均 76 秒/张
- 耗时分布：截图 3.3s｜**OCR 52.2s / 22 次**（端上 ≈2.4s/次，是当前最大瓶颈）｜棋盘识别 3.3s（3 次）｜点击等待 5.0s
- 产物在设备上 `/data/user/0/com.fantasy.autoexplore/files/runs/`：
  `loop/loop_log.json`、`r_<hhmmss>_0.png`（round-0 真实棋盘帧）、`last_summary.json`
- 证据已回拉到 `_verify/`：`dev_last_summary.json`、`dev_loop_log.json`、`dev_board_r0.png`

与 PC 的关系、规划全文见仓库根目录 `自动探索APK化规划.md`。

### 6.9 悬浮条第二轮：跑马灯日志行 + 「当前行动」（2026-09-29 02:5x）

用户三条原话：
> 「悬浮窗开启后要能滚动显示日志内容，就显示一行」
> 「文字要一行一行飘，现在的不行。运行后图标变绿也要能看到，现在直接收起看不到了」
> 「最好文字播放的是当前的行动」

#### ① ⭐⭐ 为什么不能用 `FLAG_SECURE`（重要禁区）

最初的想法是"给悬浮窗加 `FLAG_SECURE`，让投屏/截图里看不见它" —— 这是最干净的解。
**但 MuMu 上实测直接死掉**：

| 试验 | `adb exec-out screencap -p` |
|---|---|
| 悬浮窗带 `FLAG_SECURE` | **0 字节**（设备内 `exit=1`，SurfaceFlinger 拒绝整屏抓取） |
| 去掉 `FLAG_SECURE` | 立刻恢复（≈300KB 正常 PNG） |

⇒ 该 ROM 对 `FLAG_SECURE` 是**整屏拒绝**，MediaProjection 大概率同样拿不到帧 ⇒ **推图直接瞎**。
⇒ **`FLAG_SECURE` 在本工程是禁区**，别再加回来。

**替代方案 = 「涂平」**：在 `FrameStore.set()`（**唯一写入点**）里把悬浮条矩形涂成恒定纯色
`0xFF101418`。既解决"文字被 OCR 认出来"，也解决"滚动文字让 `wait_stable` 永远等不到稳定"。
不依赖任何 ROM 行为，**字节级可验证**。

```bash
$ADB -s $D shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
  -a com.fantasy.autoexplore.CMD --es cmd mask_check
# [mask_check] rect=20,1739-986,1815 帧=1080x1920 采样=18876
#             亮度 均值=19.0 最小=19 最大=19 极差=0 ⇒ 涂平生效 ✓（帧里是纯色，认不出悬浮条上的字）
```
`极差=0` = 帧里那块**一个杂色像素都没有** ⇒ 全屏 OCR 拿它没办法 ✓（`0xFF101418` 的亮度正好 19.0）

#### ② 悬浮条几何必须对着这四个区间核

涂平"零副作用"**完全靠几何**。改悬浮条位置/高度后，**必须重新核这张表**：

| 用途 | 参考 y 区间 | 悬浮条 1739~1816 是否碰得到 |
|---|---|---|
| 棋盘 7×5（含最低一行 1578~1722） | 1002~1722 | ❌ 碰不到 |
| `boardLuma` 暗罩采样 | 1002~1722 | ❌ 碰不到 |
| `wait_change` 主带 | 130~1700 | ❌ 碰不到（只在 `around(x,y,r)` 局部窗口才可能覆盖，而涂平后那块**恒定**⇒ 不产生假变化） |
| `wait_stable` 默认带 | 130~1800 | ⚠ **会罩到** ⇒ 正因如此才必须涂平（滚动的文字 = 永远不稳定） |

#### ③ 跑马灯（自绘，`MarqueeView`）

- 不用 `TextView` 的 `ellipsize=MARQUEE`：它依赖窗口焦点/`isSelected`，而本窗口是 `FLAG_NOT_FOCUSABLE`，跑不跑看 ROM 脸色。
- 参数：`TEXT_REF=22`（参考系像素 ≈11sp@1080p）、`FRAME_MS=40`（25fps）、`SCROLL_STEP=3.0`（**75px/s**）、`GAP_REF=60`。
- 两种动作：**新句子从右侧滑入**（`slideIn`，≈0.5s 走完视口宽）＋ **装不下就持续左移**（首尾相接无缝）。
  装得下就**完全不动**（省电 + 别让画面乱动）。
- ⚠ `onMeasure` 必须自己实现：裸 `View` 在 `WRAP_CONTENT` 高度下 `getDefaultSize` 会返回**可用高度 1920**
  ⇒ 把悬浮条撑成全屏、涂平矩形变成半个屏幕（实测踩过 `bar(dev): 1080x1920`）。
- 实测（连续 4 次 dump，同一句 `⛔ 发现红装 ⇒ 已停下（去界面点「红装解锁」再开跑）`）：

```
[采样1] slideIn=59 offset=0      ← 正在从右侧飘入
[采样2] slideIn=0  offset=183
[采样3] slideIn=0  offset=372
[采样4] slideIn=0  offset=564    ← 每 ~2.5s 走 ~190px ≈ 75px/s ✓
```

#### ④ 「当前行动」翻译层（`describeAction`）

循环日志有两类：**人话行**（`== 第 1 张图 ==   进图前体力 1377`）与**机器行**（`{'solver': 'ok', ...}`）。
直接播又长又难看，所以翻成一句短的；**翻不出来（噪声/大 JSON）就沿用上一条**。

已验证的翻译（`overlay_dump` 的「最近 12 条」会逐条列出）：

| 原始日志 | 当前行动 |
|---|---|
| `== 第 3 张图 ==   进图前体力 1377` | `第 3 张图 · 准备进图（体力 1377）` |
| `{'enter': 'in_map', 'stamina': 1353}` | `已进图（体力 1353）· 正在读棋盘` |
| `{'solver': 'ok', 'cost': 12, 'steps': 3, 'targets': 2}` | `规划完成：cost 12 / 3 步 / 目标 2` |
| `{'battle': 'closed', …, 'win': True}` | `战斗结束：胜` |
| `board：35 格真识别（…）` | `识别棋盘：35 格` |
| `· 发现 3 块紫/橙探索地块（…）⇒ 去探索+派遣（空闲槽 1 个）` | `紫/橙探索地块 ⇒ 去探索 + 派遣` |
| `· 已派遣一支探索队（上方还剩 2 个空闲槽）` | `已派遣一支探索队 ✓` |
| `· 三个探索槽已满，关掉派遣面板（不派遣 ✓）` | `探索槽已满 ⇒ 不派遣，关掉面板` |
| `本图结束：done（耗时 62 秒）  ==== 全部结束，共 95 秒` | `全部结束（共 95 秒）` |
| `体力不够进图，停止` | `体力不够进图 ⇒ 收工` |
| `没体力了，进背包用 结实补给` | `没体力 ⇒ 用「结实补给」` |
| `red_equip：…` | `⛔ 发现红装 ⇒ 已停下（去界面点「红装解锁」再开跑）` |
| `[ovl]…` / `收到广播命令…` / `[overlay_dump]…` / `[py]…` | （不播报，沿用上一条） |

⚠ **踩过的两个坑**：
1. `val(s,key)` 必须**跳过 `: `**，否则 `'win': True` 取出 `": True"` ⇒ 显示成「战斗结束：负」。
2. ⭐ **整屏 OCR 词表 dump 行会被误判成行动**：循环会把识别到的所有面板文字打进日志
   （`关闭 探索 开始冒险 进入地图 一键派遣 探索配队 探索产出 派遣 领取`），
   旧的 `s.contains("派遣") ⇒ 紫金地块 ⇒ 派遣` 直接命中 ⇒ 播出一句**根本不存在的行动**。
   ⇒ 修法两道：① 新判据 `ocrKeywordHits(s) >= 3` ⇒ 判为词表、不播报（真实行动行最多撞 2 个）；
   ② 派遣规则改成只认**完整真文案**（`紫/橙探索地块` / `已派遣` / `探索槽已满`）。

#### ⑤ 「点 ▶ 不收起 + 变绿」

`onStart()` 里 **先给反馈、再干活**：不管后面是"没截图权限"还是"无障碍没开"，
点完立刻 `setExpanded(true)` + 切日志行模式；失败原因写在日志行里。
（旧版是 `setExpanded(false)` ⇒ 用户原话"运行后图标变绿也要能看到，现在直接收起看不到了"。）

实测（`logcat` + 应用自己的日志面板）：
```
[ovl] 点 ▶ ⇒ 开始
还没有截图权限 ⇒ 拉起授权界面，授完再点 ▶
[ovl] bar 设备 1080x77 … 展开=true …      ← ★ 点完仍然展开
```
且 `overlay_state --es state run` 强制运行态后等 **20 秒（> 闲置 15s）仍 `expanded: true`** ✓、
气泡变 `▶ MGAS`（绿 `0xFF66FF88`，截图见 `_verify/ovl_run_green_bar.png`）。

#### ⑥ 两个 dev 验证钩子（用户日常走不到，只有 `adb broadcast` 能触发）

| 命令 | 作用 |
|---|---|
| `overlay_state --es state run\|idle\|err\|lock\|auto` | **强制状态灯颜色** ⇒ 零体力验证"跑起来变绿 + 不收起"（真跑一张图要 25 体力，不值得） |
| `mask_check` | 证明"机器人对自己瞎"（见上面 ①） |

⚠ `overlay_state` 用完**必须 `--es state auto` 清掉**，否则状态灯永远不跟随真实状态。

> **零体力验证姿势**（本项目反复用）：重装 APK ⇒ `FrameStore.has()==false` ⇒ 此时点 ▶ 只会拉授权界面、
> 完全不烧体力，可以放心点。验证完再点授权框「立即开始」`(849,1277)` 恢复。
> `overlay_dump` 里的 `frame:` 字段直接告诉你在哪个状态。

#### ⑦ 本轮修掉的一个真 bug（2026-09-29 03:0x）

**▶ 点完不收起**：旧 `onStart()` 把 `setExpanded(false)` 放在最前面（"点完就收起来，别挡视线"），
与用户"跑起来也要能看到"直接冲突。现在改成**先展开 + 切日志模式，再判权限/无障碍**。

### 6.10 悬浮条第三轮：两行定稿 + 浅底黑字 + 自愈（2026-09-29 03:2x，v0.9→v0.13）

用户四条原话（按顺序）：
> 「悬浮窗要在按钮上面。滚动方式是**整行上下滚动**，不是现在的左右」
> 「要在按钮上面啊，并且是**黑色字**」
> 「**软件名字上幻少自动刷图**」
> 「**字放大一点，黑体**」→（下一句澄清）「字大一点黑体说的是**日志**的字体」

#### ① 高度预算：94px 怎么分（改字号前必看）

底边钉参考 `y=1816`、顶边不许过 `BOARD_Y1_REF=1722` ⇒ **总共只有 94 参考 px**。

| 版本 | `LOG_ROW_H_REF` | `LOG_TEXT_REF` | `CHIP_TEXT_REF` | 展开态总高 | 顶边 | 结论 |
|---|---|---|---|---|---|---|
| 上一轮「单行」 | —（同行） | 22 | 15sp(45px) | 77 | 1739 | 日志行与按钮挤一行，用户看不到日志 ⇒ 弃 |
| v0.9 两行 | 28 | 22 | 34 | 84 | 1732 | ✅ 定稿雏形 |
| **v0.13 定稿** | **34** | **28（加粗）** | 34 | **90** | **1726** | ✅ 用户"放大一点"后仍留 4px 余量 |

⚠ `CHIP_TEXT_REF` 从 15sp 换成**参考系像素 34**（`TypedValue.COMPLEX_UNIT_PX`）：
sp 会随系统字体缩放变，一变大就顶穿 1722。**日志行同理：字号/行高全部走 `RefMapper.devLen()`**。

#### ② 「日志在按钮上面 + 黑色字」= 浅底黑字

用户口径是**两条**：位置（在按钮上方）**和**颜色（黑字）。黑字必须配浅底才看得见，所以：

```java
private static final int LOG_TEXT_COLOR = 0xFF000000;   // 黑字（用户口径）
private static final int LOG_BG_COLOR   = 0xFFF2F4F7;   // 浅底
private static final float LOG_TEXT_REF = 28f;          // 22 → 28（放大）
private static final android.graphics.Typeface LOG_TF =// 黑体 = 加粗等宽
        android.graphics.Typeface.create(android.graphics.Typeface.MONOSPACE,
                                         android.graphics.Typeface.BOLD);
```
- 浅底还顺带解决一个**感知问题**：日志文字原来压在 App 自己的日志面板上，分不清哪行是悬浮条的
  ⇒ 有了浅底圆角条，一眼就是"按钮上方那一行是我的"。
- ⚠ **按钮不加粗**：用户明确「字大一点黑体说的是**日志**的字体」⇒ `chip()` 保持常规字重。
- `bar.addView(tvLog, 0)`：**插到 index 0** 才是"在按钮上面"（`btnRow` 先 `addView` 占了 index 0）。

#### ③ 滚动方式：整行上下滚动（替换原来的左右跑马灯）

`MarqueeView` 整段重写，不再左右滚，改**竖向推**：

| 元素 | 位置公式 | 含义 |
|---|---|---|
| 上一句 | `baseY − h * roll` | 0 → −h，**向上移出** |
| 新一句 | `baseY + h * (1 − roll)` | +h → 0，**由下方推上来** |

`FRAME_MS=33`、`ROLL_STEP=0.09`（≈11 帧 / 0.36s 滚完）；装不下的整句用
`TextUtils.ellipsize(…, END)` 省略号收尾（**不再左右移**）。
滚完 `prev=null` ⇒ **完全静态**（不要动 `wait_stable`）。

**证据**（dev 钩子 `overlay_roll`，见 ④）：
```
[roll_probe +0ms]   roll=0.0000  行高=0   新句y=1   旧句y=0
[roll_probe +90ms]  roll=0.0900  行高=34  新句y=31  旧句y=-3
[roll_probe +180ms] roll=0.3600  行高=34  新句y=22  旧句y=-12
[roll_probe +400ms] roll=0.9000  行高=34  新句y=3   旧句y=-31
```
新句 y：31→22→3（+h→0）、旧句 y：−3→−12→−31（0→−h）⇒ 正是"整行上下推" ✓

#### ④ 新 dev 钩子：`overlay_roll`

```bash
$ADB -s $D shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
  -a com.fantasy.autoexplore.CMD --es cmd overlay_roll
# 注入一条带序号的合成日志 + 在 +0/+90/+180/+400ms 各打一条 logRoll，1.2s 后把 logForce 交回自动
```
和 `overlay_state` / `mask_check` 一样，**只有 adb 能触发**；真跑一张图要 25 体力，不值得。

#### ⑤ 本轮修掉的三个真 bug

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 1 | **悬浮条能被拖到屏幕中部**（参考 y 422~499）⇒ 涂平把画面中段抹平、盖住棋盘 | `installDrag` 竖直方向**没有夹子**（水平有） | 加 `safeBottom = sh − bh − devY(1722)`，`lp.y` 夹在 `[0, safeBottom]`；水平照旧自由 |
| 2 | 拖到顶后**一展开又越界**：收起态 `bh=56` 夹在 `lp.y≤142`（顶边正 1722），展开 `bh=84` ⇒ 顶边掉到 **1694** | 夹子按**当时**高度算 | ① `barMaxH`（见过的最大高度）参与夹子；② `afterLayout()` 加**自愈**：顶边越界就改 `lp.y` 回推 |
| 3 | 自愈后 `blankRect` **停在旧几何**（`[20,1722][229,1778]`，只有收起态那么大）⇒ 悬浮条右半边+下沿**漏进截图** | 自愈分支里 `return` 了，没走到下面发涂平矩形那段 | 去掉 `return`，让它继续用**新的 `lp.y`** 算 `BLANK_RECT` |
| 4 | 长按气泡的 `logForce` 在 TRUE/FALSE 之间**来回翻，永远回不到「自动」**（注释却写"再长按恢复自动"） | `(logForce != null && logForce) ? FALSE : TRUE` | 改**三态循环**：`null → TRUE → FALSE → null` |

实测（v0.12/v0.13）：
```
收起态拖到顶： xy(dev,离底)=20,142   bar 209x56  顶边 1722 ✓
再展开：       [ovl] 顶边越界 ⇒ 自愈回推：离底 114（顶边钉回 参考 y=1722）
               bar 960x90 ⇒ 顶边 1726 ✓   blankRect [20,1726][980,1816]  ← 与条子完全吻合
长按三态：     强制显示 → 强制隐藏 → 恢复自动（跟随运行状态）✓
```

#### ⑥ 顺带修掉的一个 PC/端上联动 bug（黄金宝库卡死）

用户报「**刚刚卡在黄金宝库购买界面**」。`logcat` 证据链：
`{'vault':'buy','ring':1,'cost':10000}` → `vault_pick` 每轮 `FileNotFoundError: …/files/mapbot_pack/runs/_qty.png`
→ `{'finish':'too_many_errors'}` → `{'unstick':'collect_panel'}` → `back_to_menu`。
**与悬浮窗无关**：`buypanels.read_qty()` 把临时 PNG 写到
`VAULT.get('tmp', dirname(buypanels.py))/runs/_qty.png`，而 `VAULT` **根本没有 `'tmp'` 键**
⇒ 回退到只读资源根 `files/mapbot_pack/`（没有 `runs/`）⇒ 每轮必炸。
修法 = 新增 `_qty_tmp_path()`（`mapbot.RUNS` 优先 + `makedirs` + 环境变量 + 模块旁 runs + `tempfile` 兜底），
改 PC 源后用 `android_autoexplore/tools/port_android.py` 重跑（**只改资源根表达式、不改 `.py` 里的字面量**）。

#### ⑦ 软件名 = 幻少自动刷图

| 位置 | 改动 |
|---|---|
| `res/values/strings.xml` | `app_name` / `acc_label` → **幻少自动刷图**（`（点击/滑动）`） |
| `OverlayService` 通知 | 渠道名 + `setContentTitle("MGAS · 幻少自动刷图")` |
| `CaptureService` 通知 | 渠道名 → 幻少自动刷图 |

⚠ 包名仍是 `com.fantasy.autoexplore`（改包名会**换掉应用身份** ⇒ 无障碍授权、截图授权、`runs/` 目录全丢）——
**只改显示名，不动包名**。

#### ⑧ v0.13 实测（2026-09-29 03:3x，MuMu 16384 / Android 12）

| 项 | 结果 |
|---|---|
| 展开几何 | `bar(dev)=960x90` ⇒ **顶边(参考 y)=1726 ≥ 1722** ✓ |
| 涂平 | 展开 `blankRect=[20,1726][980,1816]`；`mask_check` **均值 19.0 / 极差 0** ✓ |
| SECURE | `secure: false` ✓ |
| 日志位置 | 截图 `_verify/v13_bar_zoom.png`：浅底圆角条**在按钮行正上方** ✓ |
| 日志字 | 黑字（`0xFF000000`）+ 加粗等宽 + 28px（32 字宽 709px，旧 22px 时 551px）✓ |
| 上下滚动 | `roll 0→0.09→0.36→0.90`，新句 y 31→22→3、旧句 y −3→−12→−31 ✓ |
| 拖动夹子 | 收起态拖到顶 `lp.y=142`（顶边 1722）✓；展开后自愈 `lp.y=114`（顶边 1726）✓ |
| 标题 | 界面 ActionBar + 启动器名 = **幻少自动刷图** ✓ |

归档：`AutoExplore-v0.13-幻少自动刷图-日志浅底黑字-debug.apk`
（中间版本 v0.9 两行、v0.10 两行自愈、v0.12 长按三态也一并留在同目录备查）

### 6.11 ⭐ 全分辨率适配：锚定模型 + 三分辨率真机验证（2026-09-29 04:0x~05:0x，v0.15/v0.16）

用户口径：「适应各种分辨率」「让脚本能在各种分辨率都能正常运行」。
规划全文见 **`分辨率适配规划.md`**（自包含：现状/禁区/实验步骤/决策树/成熟方案对比）。

#### ① 决定性实测：游戏在非 9:16 屏上**不是等比缩放**

用 `MuMuManager.exe`（`D:/MuMu Player 12/nx_main/`）把 16384 临时改成 1080×2400（要重启+清 `wm size` override），
逐屏 OCR 地标 + 进一张图量棋盘，结论：

| 元素 | 1080×1920 基线 | 1080×2400 实测 | 规律 |
|---|---|---|---|
| 顶部 HUD（体力/PID/标题栏） | y 38~277 | **不变**（Δ≤1px） | **锚顶** |
| 底部导航（公会/角色/开始冒险/斗技场/图鉴） | y 1888.5 | 2368.5（**+480**） | **锚底** |
| 进入地图 / 快速扫荡 | y 1618 | 2097.6（+479.6） | 锚底 |
| 深渊入口 / 星界秘境 | y 746~1029 | 1226~1509（+480） | 锚底 |
| x 方向（全部元素） | — | **Δ≤1px** | 宽度恒 1080 设计稿 |
| 棋盘格距 | 144 | **144（不缩放）** | 锚底平移 |

⇒ **顶块（y≤300）锚顶 + 其余锚底（y_dev = y_ref + (H−1920·kx)，纯平移）+ x 乘 kx=W/1080**；
多出来的高度全被中间"世界场景"吃掉（脚本从不在那里点击）。
**验证**：按模型把 2400 实拍图合成 1080×1920 参考帧 → PC 分类器 **35/35 格、中位分 0.910**（与基线 0.910 一致）。

#### ② 实现：只改 `RefMapper.java`（一个类管全部换算）

- `devY(y)`：`y≤300 ⇒ y·kx`（顶块）；`y>300 ⇒ y·kx + shift`（锚底），`shift = H − 1920·kx`
- `toRef()`：**两段拼接** —— 顶块 (0,0,W,300kx)→(0,0,1080,300)；锚底区 (0,300kx+shift,W,H)→(0,300,1080,1920)
- 9:16 屏 shift=0 ⇒ **与旧整屏等比逐像素一致**（零回归）；1080×1920 走 `isRefRes` 连 Bitmap 都不重建
- 比九:16 更"矮胖"的屏（H<1920kx）：两段会重叠 ⇒ 自动回退旧等比+居中留黑边
- 顺手修了个潜伏 bug：`afterLayout` 的 `hRef = devH × k()`（方向反了，1080×1920 上两者都是 1 没暴露）⇒ 改用新的 `refPerDev()`
- ⚠ PC 端 `ADAPTIVE_LAYOUT` **继续保持 False**：APK 的帧已被 RefMapper 归一化，再按真实屏缩放 = 双重缩放

#### ③ 三分辨率真机验证（每张图 25 体力，共 3 张 + 2 张废图）

| 分辨率 | 进图 | 棋盘识别 | 结局 |
|---|---|---|---|
| 1080×1920（基线） | 体力 1307→1283 | r0 已揭示4/暗格24、规划 7 体 4 步 | ✅ **done 104 秒，战斗 1 场(胜)** |
| 1080×2400 | 体力 1305→1281 | **21 格 0.89~0.96**、派遣槽 2→1→0 全派满 | ✅ **done 104 秒** |
| 720×1280 | 体力 1300→1275 | r0 已揭示4/暗格21、规划 10 体 4 步 | ✅ **done 99 秒** |
| 720×1280 地标 | — | 开始冒险 (360.5,1260) = 基线×0.667 误差≤0.5px | ✅ 等比路径成立 |

证据：`_verify/` 的 `layout_1080x2400.json`、`synth_ref_1920.png`（合成参考帧）、`dev_loop_log_multires.json`、
`_test_multires.py`（离线 10 分辨率几何+分类）。

#### ④ 顺带修掉的两个真 bug

1. **广播 `explore` 没把游戏切前台**（04:41 实测：APK 在前台时启动，OCR 43 条全是自己的按钮/日志文字，
   "已进图" 误判、对着自己点 12 分钟）⇒ `CommandReceiver.bringGameFront()`（悬浮条 ▶ 路径本来就会切）。
2. （上一轮）`afterLayout` hRef 方向反了（见 ②）。

#### ⑤ 实验操作备忘（以后再测别的分辨率照抄）

```bash
MM="D:/MuMu Player 12/nx_main/MuMuManager.exe"
"$MM" control -v 0 shutdown                     # 关（要等 is_process_started=false）
"$MM" setting -v 0 -k resolution_width.custom -val 1080 -k resolution_height.custom -val 2400
"$MM" control -v 0 launch                       # 开（等 is_android_started=true）
adb shell "wm size reset; wm density reset"     # ⚠ 必做：MuMu 会留 Override size 把显示锁在 16:9
# ...测完恢复：
"$MM" setting -v 0 -k resolution_width.custom -val 1080 -k resolution_height.custom -val 1920
"$MM" setting -v 0 -k resolution_dpi.custom   -val 480     # ⚠ custom 模式会把 dpi 改掉，要一起还原
```
⚠ 重启后截图授权失效要重授；登录界面的协议勾选框 `input tap` 可能无效，用 `input swipe X Y X Y 300` 长按。




