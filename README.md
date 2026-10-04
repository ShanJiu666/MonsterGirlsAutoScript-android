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
Python（Chaquopy 3.10）：
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
⑤加 Android 中断钩子。

⚠ **停止语义已于 v0.14 起改为「立即停止」**（2026-10-01 复核，旧文写的"打完手上这张才停" **已作废** ✗）：
点悬浮条 ■ ⇒ ① Python `_ANDROID_STOP = True`（`stop_requested()` 在轮首/每次点击前抢先接住）
② Java `requestInterrupt()`（**踹出** `waitChange`/`waitStable` 的 native 等待循环）
③ v0.93 起纯 Python 的 `time.sleep` 也切成 0.1s 片查停止位（`mapbot._sleep` ✓）。
真机实测延迟：最坏 **11.37s → ≤0.1s**（`_verify/.../autoexplore_stop2.log` 量化过 ✓）。
`past_stop_time()`（04:58 收工）仍**故意**等到图边界 —— 那是"收工"不是"急停"，两者别混 ✓

⭐⭐⭐ **2026-10-01 起 PC 端与手机端已正式分开、两端平行独立开发**（详见
`../mapbot_pc/README.md` §0）。本仓的 `app/src/main/python/*.py` 是**手机端自己的源码**，
不再是"每次改 PC 都必须重跑脚本"的强制生成物。下列两个 `port_*.py` 现在是
「**想把 PC 上的某个改动/修复搬到手机时**」跑一次的**搬运工具**：

```bash
python tools/build_pack.py     # ① 打资源包：templates/(unit 裁前3帧) + server_datatable.json → assets/mapbot_pack
python tools/port_android.py   # ② 【可选·搬运】11 个纯逻辑模块 + 资源根改环境变量
python tools/port_loop.py      # ③ 【可选·搬运】explore_loop.py + 打 5 处补丁
```

- ②③ 是**覆盖式写入、没有合并** ⇒ 跑前两个脚本会先查手机端有无**未提交改动**，
  有就**中止**并提示；跑完**务必 `git diff app/src/main/python` 看差异**。
- 手机端改了就直接改手机端，**不需要**回灌 PC。两端逻辑漂移是允许的。

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
       ■   停止（**立即停止** ✓ 不等这张图打完；双通道：Python `_ANDROID_STOP` + Java `requestInterrupt`，
           等待循环也切成 0.1s 片查停止位 —— 真机实测延迟最坏 11.37s → **≤0.1s**）
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

### 6.12 v0.38 ABI 拆分 + v0.39 色子初始大拇指修复（2026-09-29 晚）

**v0.38（ABI 按 flavor 拆）**：x86_64 全套（Python + onnxruntime ≈47MB）只为 MuMu 调试存在 ⇒ 发版改打
`assembleArm64Release`（**70.8MB**，124MB→70.8）。⚠ `abiFilters` 写 `defaultConfig` 对 buildType 是取并集
挡不掉、写 buildType 被 Chaquopy 直接拒绝 ⇒ 只能走 **flavor**（`arm64` 发版 / `full` 开发+模拟器）；
**没有 `assembleDebug` 这个 task 了**。Chaquopy 单 ABI 时把 Python 包合进 `requirements-common.imy`
（数学上 = 原 common + 该 ABI 份，已解开确认 cv2/numpy .so 全在）。release 用 debug 签名 ⇒ 真机可覆盖升级。
⚠ release 包**不可 run-as**（not debuggable）⇒ 拿不到 files/runs 内部文件；排查期用 `assembleArm64Debug`
（同 70MB + debuggable）。

**v0.39（摇色子初始大拇指修复）**：用户目击「奖励行初始就摇出了指定大拇指装备，脚本还继续用幸运草重投」。
现场取证（`_verify/dice_phone/`）：第 1 摇后 `dice_0.png` 奖励行无拇指、loop_log `mark_routes` 三路由全 null
（分数 0.008~0.043 = 真没有），第 2 摇 `dlg+C` 路由 0.904 认出 ⇒ **判定本身是准的，根因是
`handle_dice` 进场不检测初始奖励行、无脑先摇第 1 次**——把结算面板初始就出的追踪装备重投掉 + 白耗 1 草。
修法（改 PC 源 `tools/mapbot/explore_loop.py` 后重放 `port_loop.py`）：三路由检测抽成 `_mark_routes()`，
进循环前先查一次，初始命中 ⇒ `initial_recommend` + 一次都不摇（fail-open：检测异常照旧进循环）。
PC 基线复核：`dice_ok_0/2` 真拇指 0.92~0.96 ✓、`dice_ok_1` 无拇指正确返回空 ✓（绿框=每格都有，
**认的是右上角小绿拇指**，别拿绿框当判据）。

### 6.13 v0.40：模拟器（720×1600 长屏）复测 + 宝库 panel_gone 修复（2026-09-29 深夜）

用户把测试转到 MuMu 16384（当前 **720×1600，20:9 长屏，C=240**——与真机 1280×2772/C=209 同构，
能复现坐标系问题；debug 包可 run-as 取数据）。连刷 19+ 张全 done、商人 bought 1 ✓。

- **色子 initial_check 验证 ✓**：两场推荐战完整记录（`_verify/mumu_loop_log2.json`）——
  初始奖励行真无拇指（三路 null）⇒ 进循环，第 2 摇 dlg+C 0.943/0.945 认出即停。
  「初始有 ⇒ 不摇」的检测函数与「初始无 ⇒ 正常摇」两半都闭环。
  （真机 22:46 用户看到的「初始被摇掉」跑在 arm64Debug 旧代码上——v0.39 当时还没装。）
- **修 v0.39 重构引入的 TypeError**：三路由全空时 `_mark_routes` 返回 None ⇒ `hits[:4]` 抛
  `TypeError('NoneType' not subscriptable)`（`match_err`，近失诊断被吞，但行为不受影响）
  ⇒ 改返回 `(_best or [])`。
- **修黄金宝库 panel_gone 误判**（真机 22:59 实锤：`{'vault':'panel_gone'}` 与 popups
  `dlg_frame_retry` 的宝库文案同帧并存）：宝库是 **A 类居中弹窗**，标题弹窗系 y≈384 →
  归一化帧 y≈175，落在 `_items` 的 band(300,1560) 外 ⇒ 归一化帧永远找不到标题。
  ⇒ 新增 `buypanels._has_dlg()`（归一化帧找不到标题时补一次**弹窗帧 OCR** 判存在性；
    PC 无 ocr_dlg 自动跳过），三处判定点全补（vault_pick / vault_flow 圈循环 / 收尾关 X）。
    按钮/格子定位不动——它们在 band 内且与 b.tap 同源自洽（第一个宝库能买的原因）。
- **RefMapper.setScreen 刷屏修复**：参数不变不打日志（之前每帧一条「锚定模型…」把
  logcat 环形缓冲几分钟冲满，几十分钟前的排查证据全被冲掉）。
- ⚠ MuMu 16384 被改到 720×1600 后没恢复——下次要 1080×1920 基线时记得用 MuMuManager 改回
  （README §6.11⑤ 的流程，dpi 也要还原 480）。

### 6.14 ⭐⭐ v0.65：真机「探索格子满了还一直点探索」死循环（2026-09-30，用户报）

**现象**（用户原话「真机那边运行的 MGAS 卡在探索地块了，明明探索格子满了，还一直点探索」）：
`adb logcat -s AutoExplore` 里同一个动作**连打 18 轮**、整张图 105 秒、0 战斗 0 装备、
体力 25 白花，只能人工点 ■：

```
{'round': 1, 'stamina': 287}
{'explore': 'first_high_value', 'at': (274, 790.4374389648438)}     ← ×18
...
{'round': 18, 'stamina': 291}
```

**根因（两条，都在真机帧里实证）**：

| # | 事实 | 后果 |
|---|---|---|
| ① | 倒计时被 OCR **吃掉一个冒号**：`04:24:31` → `04:24831`（conf 0.87） | 严格式 `\d{1,2}:\d{2}:\d{2}` 只中 2 条 ⇒ `TOTAL(3) - busy(2) = 空闲 1` **假空闲** |
| ② | 该账号 HUD 那一行是 **4 个槽**（角标 1/2/3/4，其中 1 个"待领取"只有进度条没有倒计时） | `EXPLORE_SLOTS_TOTAL - busy` 反推法从根上不成立（就算不丢冒号也会算出"空闲 1"） |

③（放大器）旧代码在紫/橙格分支里**点完「探索」直接 `return handled`、不验证**：
游戏侧槽满时点「探索」毫无反应、地块面板不关 ⇒ 下一轮又看到同一个面板 ⇒ 又点一次。

**修法**（`tools/mapbot/explore_loop.py` 改完重跑 `tools/port_loop.py` 同步到 APK）：

1. **废除 `TOTAL - busy` 反推**：空闲数**只认正面证据「空闲」二字**；认不到 ⇒ 这一帧不下结论
   （`explore_slots_free` 返回 None，调用方保留旧值）—— 两个方向都不能拍死：拍成"满"会让
   认不到「空闲」的机器**永远派不出探索队**，拍成"空闲"就是这次的死循环。
2. **点完必须验证**（与「探索产出」分支同口径）：`panel_gone` 判游戏有没有受理；
   **连两次都没反应 ⇒ 判满本图**（`slots_full_latched`）+ 记 `slots_free=0`
   ⇒ 后面的紫/橙格直接走「战斗」分支（用户 09-26 口径「满了就改战斗」）；
   面板连「战斗」按钮都没有时**顺手拉黑这格**，免得来回空转。
3. **轮首每轮刷新** slots_free（旧版只在**轮尾**算 ⇒ 任何走 `handled`/`battle` 提前 return
   的轮次都不更新 ⇒ 值一直停在旧读数上，这是"第 2 轮就满了、第 3~18 轮还在点"的直接原因）。
4. **兜底网**：同一动作签名连续 **4** 轮 ⇒ `force_unstick` 强制脱困 + 拉黑当前格
   （`{'loop_guard': 'same_action'}`），任何"同类动作连点不停"都走得掉。
5. `EXPLORE_SLOTS_TOTAL` 3 → **4**，并降级为"空闲数封顶"（不再参与反推）；
   倒计时计数改**容错式**（允许吃掉一个冒号）只用于日志/诊断。

**回归**：`python android_autoexplore/tools/verify_explore_slots_fix.py`（**18 项全绿**）
- fixture = 事故现场的真机帧 OCR（`_verify/phone_slots_full_0930.json`，含 `04:24831`）
- 断言：严格式 2 / 容错式 3、新口径给 None（旧口径给"假空闲 1"）、「空闲」= 硬证据、
  `popups` 第 1 次点、第 2 次判满写回 `slots_free=0`、**第 3 次不再点「探索」**（改点「战斗」）、
  轮首刷新/总闸门/旧反推式已删除（源码断言）
- 端上实测（v0.65 装好后 `py` 广播）：真机帧三条倒计时被 OCR 合并成**一条**文本
  `"04:10:4804:15:29 04:27:53"` ⇒ 容错计数仍给 **3**，`explore_slots_free` 给 **None** ✓

**产物**：`AutoExplore-v0.66-MGAS-探索槽满不再空转-release.apk`（= `MGAS.apk`，
versionCode 66 / versionName 0.66，74243391 字节；已装机并在端上核对
`EXPLORE_SLOTS_TOTAL=4` / `explore_slots_free` 存在 / 实时读帧给 `free=None`）。
（v0.65 是同一改动的中间构建，只在装上后补了"总闸门不许管宝库/商人条目"这一处，已被 0.66 取代。）
⚠ 重装 APK 会杀 CaptureService ⇒ 必须重新「① 授权截图」（选**整个屏幕**）；
无障碍若显示"未开启"多按一次 `settings put secure enabled_accessibility_services …`
即可（芯片文案只在 onCreate/onResume 刷新，可能是旧的，以 `DeviceApi.touchReady()` 为准）。

### 6.15 v0.67：升星设置「设了不生效」根因 + 体力成本审计（2026-10-01）

#### ① 用户报「设了每 1 张图升一次，却完全没去升过」——**设置根本没存进去**

- 真机铁证（`_verify/phone_stamina_0930/autoeplore_full.log`）：
  启动行是 `… bag_every=10 …`（用户明明填了 1），而且**整段 logcat 里一条
  `设置：每 … 张图升级装备星级` 都没有** ⇒ `commitBagEvery()` **一次都没执行过**。
- 根因：那个数字框原来**只在「失去焦点」时提交**（`etBagEvery.setOnFocusChangeListener`）。
  真机上你是「填完数字 → 去悬浮条点 ▶ / 切回游戏」，此时 **窗口失焦 ≠ 视图失焦**
  ⇒ `onFocusChange` 根本不触发 ⇒ Prefs 里还是旧值（默认 10）⇒ 悬浮条 ▶ 读到 10。
- 修法：
  1. `etBagEvery.addTextChangedListener(...)` ⇒ **边打边存**（`saveBagEveryQuiet()`：
     只写 Prefs、**绝不 setText** —— 老注释担心的"打 1 再打 0 变成 01"是 `setText`
     把光标复位造成的，不 setText 就没这个坑 ✓；空串=正在删改 ⇒ 跳过，不写 0 ✗）
  2. `onPause()` 再规范化收尾一次（空/非法回落默认值）
  3. 每次真的改了值都会打一条 `设置：每 N 张图升级装备星级`（= 以后看 logcat 就知道生效没有 ✓）

#### ② 顺手加的**体力成本审计**（零行为影响，为「不点 1 体力的、去点 4 体力的」准备）

- `model_cost(sid, marks)`：数据表口径的空地 1 / 内容格·探索 SpotSize / 内容格·战斗 ×2
- 每轮日志多两项：`entry['order_cost']`（点序前 12 格 + 成本 + sid + 标记）、
  `entry['taps']` 从 `['r,c', 秒, 是否变化]` 扩成 `['r,c', 秒, 是否变化, sid, 成本]`
- 现场存档 + 三种候选机制的判据：`_verify/phone_stamina_0930/README.md`
- 回归：`python android_autoexplore/tools/verify_explore_slots_fix.py`（**26 项**，
  其中 8 项是成本口径：草地=1 / 102=2 / 102+战斗=4 / 211=4 / 221=5、带打标记=10）

**产物**：`AutoExplore-v0.67-MGAS-升星设置即时生效+体力成本审计-release.apk`（= `MGAS.apk`，
versionCode 67 / versionName 0.67，74243391 字节，已装机 + 已重授权截图/无障碍）。

### 6.16 v0.68：升星流程两处真机病（「没有正常升星」+「升星时去点进入地图」）

用户 2026-10-01 连报两条（v0.67 实跑中）：
「装备升星脚本出问题了，没有正常升星」／「装备升星的时候还要先点下进入地图是干什么。。」

#### ① ⚠⚠ 升星收尾会**真的开图**（点中「进入地图」= 扣 25 体力）

`bag_upgrade` 第 ⑥ 步"回选图界面"的点击候选原本是

```python
if t in ('开始冒险', '进入地图') and i.get('cy', 0) > 1700:   # ✗✗ 危险
```

「进入地图」在选图界面上就是**真·开图按钮**（`y≈1618`，真机映射后可能越过 1700）
⇒ 只要那一格被 OCR 读成「进入地图」并排进候选，这一下就**扣 25 体力、把刚升完星的收尾
直接顶进地图**（用户当场看到的就是这个 ✗）。
**修**：只点**底部导航中间的「开始冒险」图标锚点** `START_ADV=(540,1828)`
（用户 09-27 实测「点中间那格不会开图」✓）；「进入地图 / 快速扫荡」只保留在
**上面那句"回到选图界面了吗"的只读判据**里，绝不参与点击 ✓

#### ② 「没有正常升星」= 背包界面的识别在真机上不可靠（已加全套可诊断）

真机日志（`_verify/phone_stamina_0930/autoexplore_bag*.log`）：

```
15:34:16 ⚙ 背包一键升级：开始  →  15:34:31 ⚙ 背包没打开（重试 3 次 ✗）✗        ← 第一次：背包根本没开
15:36:09 ⚙ 背包一键升级：开始  →  15:36:19 · 装备页 → 点 (370,360)（兜底坐标 ✓）
                                → 15:36:22 · 一键升级 → 点了「(兜底)」(928,1789) ✓
                                → 15:36:25 · 确认弹框 → 点最右「8」(958,1206) ✓  ← 全靠兜底坐标
```

⇒ 说明：① 有时**连背包都开不出来**；② 即使"跑通"，**OCR 既没认出「装备」页签、
也没认出「一键升星」，模板 `bag_upgrade_btn.png` 也没命中** ⇒ 全程走 PC 标定的兜底坐标，
在真机上属于"碰运气"。根因方向：**公会/背包这套 Unity UI 不守探索棋盘的锚定模型**
（真机 20:9 与参考系 1080×1920 不同构），文字可能落在 `toRef` 丢弃的弹性区、
模板也匹配不上（老注释 `_find_ui_tpl` 就写过这条，但当时只按 720×1600 验过）。

**本轮已做（0.68）**：
1. **开背包前先确认在不在公会界面**（公会/邮件/商店/招募 任一），不在就先
   「**OCR 找『公会』二字**进公会」（分辨率无关 ✓，找不到才退写死坐标）
   —— 原流程第 1 轮会**盲点公会界面的 BAG_BTN(964,1680)**，而人此刻在选图界面，
   那一击落点不可控，之后全在错画面上找背包 ✗
2. 每轮把**「点了哪 / 模板分数 / 屏幕上认到啥」say 出来**（结构化条目要等 `flush(log)`
   跑完才打印，真机上根本来不及看 ✗）；失败时再打一遍**最后一屏的文字** ✓
3. 新增日志键：`bag: guild_not_reached` / `open_bag_miss {at, texts}` ✓

**产物**：`AutoExplore-v0.68-MGAS-升星流程修（不再点进入地图）+可诊断-release.apk`
（= `MGAS.apk`，versionCode 68 / versionName 0.68，已装机 + 已重授权）。
回归 `tools/verify_explore_slots_fix.py` = **31 项**（新增 5 项：收尾不点进入地图 /
点锚点 / 先确认公会 / 失败 say 文本 / 每轮可诊断）。

**⚠ 下一步（需要用户配合，零风险）**：若下轮日志仍是"认不到装备/一键升星"，
说明背包/公会 UI 必须**按真机重标定** —— 请手动打开「公会 → 背包 → 装备页」，
我只读截一张图（`screencap`），据此：① 用**弹窗帧 OCR（`ocr_dlg`）+ `tap_dlg`** 或
② 按真机重裁 `templates/ui/*.png` 并改 `EQUIP_TAB/UPGRADE_BTN` 的真机值。

### 6.17 v0.69：自动升星**重写**（用户要求「全分辨率适用」）

老流程在真机上"能跑但靠碰运气"（§6.16②）⇒ 本轮按"**分辨率无关**"重写，
**取消所有 PC 绝对坐标作为主路径**。四条新口径：

| # | 口径 | 为什么这就算"全分辨率适用" |
|---|---|---|
| ① | **双通道识别**：先归一化帧（`b.ocr` → `b.tap`），没查着再查**弹窗帧**（`b.ocr_dlg` → `b.tap_dlg`） | 弹窗系坐标**锚设备屏幕中心**（`devYDialog = H/2 + (y−960)·kx`）⇒ 分辨率一变自己跟着缩放 ✓；PC/9:16 的 C=0 ⇒ 只有归一化通道，行为与旧版一致 ✓ |
| ② | **纯文字驱动 + 面板内相对位置**：目标 =「背包」/「装备·装备栏」/「一键升星·一键升级·一键升阶·一键强化」/「确定·确认」；**取消一切绝对 y 过滤**，多个候选取**最上**（页签在面板顶）或**最右下**（按钮在面板右下） | 老判据 `'装备' in t and cy < 700` 在真机上会把页签滤掉（面板位置随分辨率变）⇒ 实测永远走兜底坐标 ✗，这就是"改了也没用"的那一半根因 |
| ③ | **模板两帧 × 多尺度 0.80~1.20**（`_tpl_hit` 抽成"吃任意帧"版）→ 仍找不到才退锚点，且**只在"已确认在背包里 / 在公会界面"**时才允许 | 老版只在归一化帧上按 0.90~1.15 匹配；面板在真机上可能落在 `toRef` 可见区之外或非等比缩放 ⇒ 放宽尺度 + 加一帧 ✓ |
| ④ | **真机自证**：每步 `say` 出「哪个通道 / 命中什么 / 点哪」；关键帧写一份到 `/sdcard/Download/autoexplore/bagdbg/` | release 包**不可 `run-as`** ⇒ 私有 `runs/` 拿不出来 ✗；公共目录 PC 侧 `adb pull` 直接能看，用来做**最后一版按真机标定** ✓ |

配套小修：`_MAPBOT_ROOT` 在 PC 侧原来**没定义** ⇒ 一调 `_find_ui_tpl` 就 `NameError`
（被 `bag_upgrade` 的兜底 except 吞成 `bag: error`）；`_pub_dump` 用 `cv2.imencode + tofile`
（`cv2.imwrite` 在**含中文的路径**上会静默失败 ✗，PC 侧就踩这个）。

**回归**：`python android_autoexplore/tools/verify_explore_slots_fix.py` = **40 项**，新增 9 项：
- 「装备」页签取最上且**不看绝对 y**（真机 bug 的直接守门）、「一键升星」取最右下；
- 双通道：归一化帧命中给 `norm` / 归一化没中退弹窗帧给 `dlg` / 两帧都没有给 `None`；
- **多尺度模板**：合成模板按 0.85 / 1.00 / 1.15 三种缩放贴进 1080×1920 画布，
  `_tpl_hit` 三次都命中（score 1.000，中心偏差 ≤6px）✓

**产物**：`AutoExplore-v0.69-MGAS-升星重写（全分辨率：双通道+多尺度模板）-release.apk`
（= `MGAS.apk`，versionCode 69 / versionName 0.69，已装机 + 已重授权，
装机后核对：手机内 `explore_loop.pyc` 与构建产物 sha1 相同 `86f56b653b8b`）。

### 6.18 v0.70~v0.73：升星崩溃修 + 进图体力门限 + 补给链路 + **性能账**（2026-10-01）

用户连着报了四件事，逐条对应：

| 用户报 | 真因（日志/帧实证） | 修法 |
|---|---|---|
| 「升星没变化，还是去打开头像，打不开背包」 | **我上一版埋的闭包 bug**：`bag_upgrade` 里的嵌套判据函数 `_in_guild()` 内层生成式引用了未绑定名 `i`（外层又有 `for i in items2:` ⇒ `i` 成了 cell）⇒ 首次调用 `NameError: free variable 'i'…` ⇒ **整条升星流程当场崩**（15:41/15:51 两轮实锤） | 判据函数挪到**模块级** `_guild_on()`；开背包改成**文字「背包」优先**（真机公会帧里那两个字清楚可见 ✓） |
| 「装备升星没变化」 | 真机公会帧离线核对：`guild_bag_icon.png` 命中 **(964,1680) score 0.978** ✓（= 写死坐标 BAG_BTN，说明模板与锚点都对）；但背包界面的 `bag_tab_equip.png`/`bag_upgrade_btn.png` **在公会帧上不匹配**（0.38/0.61）—— 它们属于背包帧，而流程一直崩在开背包之前 ⇒ 拿不到帧 | 每一步都把帧落到 `/sdcard/Download/autoexplore/bagdbg/`，下一次跑完即可按**真机帧**重裁这两个模板（或改走弹窗帧） |
| 「体力不够 50 怎么还去点进入地图」 | 安卓悬浮条那条调用把第 4 个位置参数 `min_stamina` **写死 25**（PC GUI 是连刷 50 / 单图 25）⇒ 29 体力照样进图；日志文案却写着「连刷下限」✗ | `OverlayService` 按模式算 `minStamina`（连刷 50 / 单图 25）并打进启动日志（`体力下限 N`） |
| 「刚刚不到 25 还去点击进入地图」 | `ensure_in_map` 的判定是 `if st is not None and st < MIN_STAMINA` ⇒ **读不到体力整段跳过、直接进图**（fail-open ✗）；且 `enter_map` 的等待循环会**重复点「进入地图」**而不再复查 | 改成 **fail-closed**：窄带→全屏各重读 3 次，仍读不到就**不进图**并说明原因；`enter_map` **每次点前复查体力**，`< 下限` 就不点 |

**性能账（用户问「又在做加法，跑一张图会不会变慢」）**——实测数字（`_tmpman/bench_round_overhead.py`，
输入用真机帧 OCR 结果，n=2000）：

```
explore_slots_free(items)               0.017 ms/次     ← 槽位纯计算（无额外 OCR）
count_slot_timers(items)                0.013 ms/次
entry[order_cost]（12 格 + model_cost）  0.020 ms/次
每次点击的 model_cost                    0.001 ms/次
same_action 签名                         ≈0 ms/次
⇒ 每轮热路径新增合计 ≈ 0.05 毫秒（一轮真机 3~6 秒 ⇒ 可忽略 ✓）
```

真正会多花时间的只有这几处，且都有开关：

| 项 | 频率 | 成本 | 开关 |
|---|---|---|---|
| 进图前体力窄带复查 | 每次进图 1 次 | ≈0.25 s | ——（安全必需） |
| 「探索」点完的验证 OCR | 仅紫/橙格弹面板且判定要探索 | ≈2 s/次，最多 2 次/图 | 无（这条正是修死循环的关键） |
| 升星/补给「归一化帧没认到 ⇒ 补弹窗帧 OCR」 | 仅没认到时 | ≈2 s/处 | 无（认到了就不花） |
| **落帧诊断**（PNG 落盘） | 默认只落**关键帧+失败帧**（3~5 张/图） | ≈0.1~0.3 s/张 ⇒ ≈1 s/图 | `MAPBOT_BAG_DUMP=0` 全关；`MAPBOT_BAG_DUMP_ALL=1` 全落 |
| ⚠ **每 1 张图升星**（用户设置） | 每张图 | **15~25 s/图**（开公会→背包→装备→一键升星→确认→退回，每步 1.5~2.8 s 等待） | 把数字改成 `3~5`，或标定完再开 |

**产物**：`AutoExplore-v0.73-MGAS-落帧可关+体力门限+升星全分辨率-release.apk`（= `MGAS.apk`，
versionCode 73 / versionName 0.73，已装机 + 已重授权）。回归
`tools/verify_explore_slots_fix.py` = **49 项**。

### 6.19 v0.74~v0.76：背包页签**只在弹窗帧里**（"打开背包就没后续"的真根因）

用户报「自动吃体力、自动装备升星都无法正常工作：都是**打开背包就没后续**了」，
并给出人工口径：

```
吃体力：打开背包 → 点「道具」→ 找结实补给 → 使用 → 返回 → 关闭背包 → 回选图界面
升  星：打开背包 → 点「装备」→ 右下「一键升星」→ 点右边「金币图标+数字」→ 返回 → 关闭背包 → 回选图
```

真机取证（用户手动停在道具页，我只读抓帧）后**两个根因**：

**① 「背包开了没」不能靠 OCR 认字**（v0.74 修）
`supply0_bag.png` 证明背包**其实开成功了**（物品网格 + 「筛选」都在），但老判据
`any('背包' in text)` 在这台真机上恒 False（美术字标题 OCR 读不到，只认到数量 1931/2280）
⇒ 判"没开" ⇒ **又点一次背包图标**（那一下正好点在已开的背包上 ⇒ 把它关掉）⇒ 来回空转 ✗
⇒ 改用**颜色判据**（实测棕色面板占比：公会 0.29 ｜ 选图 0.22 ｜ **背包面板 0.91~0.94**
⇒ 阈值 0.60 干净分开；面积占比 ⇒ 天然与分辨率无关 ✓）。另外每次点击都加**生效验证**
（画面差 <2 = 没生效）+ 阶梯重试（同点 → 下移 45px → 长按 350ms → 换映射）。

**② 页签（素材/装备/符文/宝箱/道具）落在 `toRef()` 丢弃的弹性带里**（v0.75 修）
用户原话：「就是直接点道具那两个字。上面一排素材/装备/符文/宝箱/道具都能点」。
归一化帧里**根本没有这一排**（OCR 读不到、`bag_tab_*.png` 模板匹配 0.38/0.61 也不中 ✗），
但**弹窗帧**（`grabDlgPng`：不丢弹性带）里一把认全（真机实测 dump）：

```
DLG 背包 @(539,211)   X @(1023,215)   筛选 @(199,1758)
DLG 素材 @(152,315)  装备 @(346,314)  符文 @(540,315)  宝箱 @(732,315)  道具 @(925,315)
```

⇒ 新增 `_bag_switch_tab(b, name)`：**弹窗帧精确匹配文字 → `tap_dlg` → 画面差验证**；
吃补给流程先切「道具」、升星流程先切「装备」✓。
顺带验证：**结实补给识图在道具页命中 0.972**（阈值 0.90 ✓，中心 ref(623,481)），
在材料页只有 0.767 ⇒ 之前识图失败是因为**停错页**，不是模板坏了 ✓
（`find_supply_icon` 的模板路径此前在 Android 上取的是 APK 只读目录 ⇒ 恒 None，也已修 ✓）。

### 6.20 v0.80：规划显示 + 「每轮重解 vs 进图解一次」的时间/体力对拍（2026-10-01）

用户两问：「现在地图里还是进图规划一次吗？怎么看不到规划了」「这样不会花的时间更长吗」。

**① 规划可见性**：规划一直在算（`solver_order` 每轮跑），但它原来是 `say()`（只进 logcat 与
应用内日志）；**只有 `status()` 会上悬浮条** ⇒ 用户盯悬浮条看不到 ✗。现在 `solver_order`
成功时额外发 `status('规划：体力 N / M 步 → r,c …')`；连续 3 轮算不出改走 EffPolicy 时也发
`status('规划：改用片感知兜底…')`（不再静默降级）。

**② 「每轮重解」到底花不花时间**（真机内存盘 `tools/mapbot/runs/maps_dataset.jsonl` 全量对拍，
96 张 × 2 轮、`--marks-in-fog`）：

```
全知最优：平均 7.08
策略      平均体力  完成盘体力  完成率   vs最优    点击   空转  轮   规划ms
cur      6.92     6.73     91.7%   -5.03%   2.58   0.17  1.4   0.7     ← 每轮重解（现行）
base     7.08     7.18     91.7%   +1.39%   2.33   0.00  0.0   0.0     ← 进图只解一次（旧）
· cur  vs 全知最优：相等 11 / 更贵 0 / 更省 0（最大差 +0 体）
· base vs 全知最优：相等 1  / 更贵 5 / 更省 4（最大差 +5 体）
```

⇒ **规划 0.7 ms/轮**（一轮里 OCR 1.9~2.2 s、点击等待 1.3~2.8 s/次 ⇒ 占比 0.03%）；
且每轮重解在开雾条件下**11/11 与全知最优完全相等**，而"进图只解一次"有 5 张更贵（最坏 +5 体力）
⇒ **保留每轮重解** ✓。
⚠ 小样本（12 张 / 10 对盘、方差 ±1.6 体）曾给出"cur 更贵 0.5 体"的相反结论 —— **是噪声**，
全量复测否定它；以后这类判断一律用全量语料 + 开雾跑，别用小样本拍板。

**产物**：`AutoExplore-v0.80-MGAS-规划上悬浮条-升星收尾修-release.apk`（= `MGAS.apk`，
versionCode 80 / versionName 0.80，已装机 + 已重授权）。回归 = **58 项**。

**§6.19 的产物**：`AutoExplore-v0.76-MGAS-背包全链路按真机标定（页签弹窗系+X关闭+一键升星1550）-release.apk`
（= `MGAS.apk`，versionCode 76 / versionName 0.76，已装机 + 已重授权）。
回归 `tools/verify_explore_slots_fix.py` = **54 项**（当时；现为 63 项）。

### 6.21 全分辨率体检（2026-10-01 用户要求「全面查一下 MGAS，看看还有没有地方是定死位置的」）

**工具**：`android_autoexplore/tools/audit_hardcoded_coords.py`（可重复跑；跳过注释与
docstring，避免把文档里的示例坐标误报成代码 ✓）。回归套件 §⑨ 已把它固化成守门断言。

**关键算术（真机 1280×2772 为例）** —— 这解释了"为什么某些写死坐标在 PC 上好好的、在手机上点空"：

```
kx    = W/1080           = 1.1852
shift = H − 1920·kx      = 496.4
devY(y) = y·kx + topInset   (y ≤ 300，顶部锚顶段)
devY(y) = y·kx + shift      (y > 300，锚底段)
toRef 两段拼接 ⇒ **中间那条弹性带被丢弃**：设备 y ∈ (topInset+300·kx, 300·kx+shift)
  真机实测 = (487.6, 852.0)
```

⇒ 凡是**视觉上落在设备 y 488~852** 的控件（背包页签行、背包右上角 X…），
**归一化帧里根本没有它的坐标** ⇒ 任何 ref 常量都会点空（真机实测页签偏 ~300px、
X 偏 ~145px）⇒ 这类控件**只能走弹窗系**（`ocr_dlg` / `tap_dlg`）✓

**结论**（Java 层 + Python 层全查）：

| 层 | 结论 |
|---|---|
| Java | `RefMapper` 统一做 ref→设备映射（`devX/devY/devYDialog` + `detectTopInset()` 自动测安全区）；`OverlayService` 几何用 dp + `*_REF` 常量经映射换算；**零写死设备像素点击** ✓ |
| Python | 15 个坐标常量：底部导航/顶部 HUD 类 ✓ 锚定区（真机已实证）；页签与背包 X 类 ⚠ **落在弹性带** ⇒ 已改走弹窗系 |
| Python | 函数体内写死的点击：**从 5 处降到 2 处**，剩下 2 处是升星"确认按钮"的**有意双通道兜底**（C=0 时两系同值 ✓） |

**本轮改的 6 处**（都在 `explore_loop.py`）：

| 位置 | 旧写法 | 问题 | 新写法 |
|---|---|---|---|
| `_close_bag` 兜底 | `b.tap(96, 96)` | ref y=96 ⇒ 锚顶段 ⇒ 真机设备 y≈246 = **顶部 HUD**（PID/头像）⇒ 关不掉还可能误触 ✗ | 文字 → 面板颜色判据 → **弹窗系 X** → 归一化 X |
| 页签（装备/道具） | `b.tap(EQUIP_TAB)` / `b.tap(ITEM_TAB)` | 真机在弹性带内 ⇒ 偏 ~300px 点空 ✗ | `_panel_tap(…, 'dlg')` + `BAG_TAB_DLG` |
| 派遣面板「返回」×2 | `b.tap(275, 1507)` | 居中面板的归一化 y 被弹性带挤掉 ✗ | `_panel_tap`（同点/下移/长按/**换通道**） |
| 补给退图「返回」/「关闭」 | `b.tap(BACK_BTN)` / `b.tap(CLOSE_TR_PT)` | 同上 | `_panel_tap` |
| 新增 `_panel_tap()` | —— | 面板按钮跨两套坐标系，`tries=2` 的阶梯不够用 | `tries=4`（含换通道），仍以 `b.tap` 真实回报判生效 ⇒ 正常只点 1 下 ✓ |

**产物**：`AutoExplore-v0.81-MGAS-全分辨率体检（面板点击统一换通道+页签与X走弹窗系）-release.apk`
（= `MGAS.apk`，versionCode 81 / versionName 0.81）。回归 = **63 项**。

### 6.22 v0.82：黄金宝库「幸运草识别不出」+ **生成物防漂移守门**（2026-10-01）

用户报「这次有黄金宝库试试能不能正常购买」→ 实机结果：**买成了**（`16:57:03 黄金宝库买完（第 1 个）✓`，
整条链全走弹窗系 `tap_dlg`/`img_dlg` ⇒ 与分辨率无关 ✓）。随即又报「第二圈有个幸运草，但是没识别出来就没选」。

**根因**：`buypanels.match_item_icon` 的图标尺度**写死** `ICON_SCALE = 4.5` 且只试
`4.3 / 4.5 / 4.7`（±4.4%）⇒ 真机上图标实际尺寸只要差出这个范围（面板缩放、图标内边距与 PC 不同…）
就**整批落到阈值 0.55 以下** ⇒ `vault_pick` 报 `no_icon_hit` ⇒ 退成「随意选」⇒ 幸运草被漏 ✗

**修法**（`tools/mapbot/buypanels.py`）：

| 项 | 旧 | 新 |
|---|---|---|
| 尺度来源 | 写死 4.5 | **由格子间距推出**：`pitch(144) × ICON_FILL(0.94) / 源图 30px = 4.512` ⇒ PC 行为不变 ✓，换分辨率时跟着面板走 ✓ |
| 扫描档位 | 3 档（±4.4%） | 9 档（−25%~+20%） |
| 兜底 | 无 | 一格都没命中 ⇒ **宽扫一轮**（0.5×~1.6×，10 档） |
| 搜索偏移 | ±4 px | ±7 px |
| 诊断 | 只有 `no_icon_hit` | 每格最好分数进日志（`{'vault_debug': …}`）+ **认不出自动落帧**到 `/sdcard/Download/autoexplore/bagdbg/vault_no_hit_L*.png`（下次可直接用真机帧重裁模板 ✓） |

**⚠⚠ 顺手抓到的结构性问题（比这个 bug 更值得记）**：Android 侧的 `buypanels.py`（以及
`spots/mapgen/targets_cfg/...` 共 11 个模块）是**另一份手工副本**，`port_loop.py` 只管
`explore_loop.py` ⇒ 两份**已经漂移**（PC 侧新代码到不了手机 ✗ —— 幸运草这个 bug 就是漂移的产物）。
现在：① 一律用 `android_autoexplore/tools/port_android.py` 重新生成那 11 个模块；
② 回归套件 §⑩ **逐字节**校验「生成物 vs 手机侧文件」（复刻 `patch()` + 该模块的 `EXACT` 替换），
PC 改了手机没跟上会直接红 ✓。

**产物**：`AutoExplore-v0.82-MGAS-宝库图标尺度自适应（pitch推+宽扫兜底）+生成物防漂移-release.apk`
（= `MGAS.apk`，versionCode 82 / versionName 0.82）。回归 = **66 项**。

### 6.23 v0.83：宝库奖励口径定案 + 认不出就点开详情读名（2026-10-01）

**① 「幸运草」= 「四叶草」（同一物品，用户口语）** —— 我此前把它当成**两样东西**排序，是错的 ✗。
游戏 `GoldenVault` 表里只有两项高阶奖励：

```
四叶草   D00002_000   数量 1 / 2 / 4 / 8     （用户口语叫「幸运草」）
天赋果实 D00002_001   数量 5 / 10 / 20 / 50
其余：神石 / 装备 / 符文 / 传承装备（Weight 高但价值低）
```

**② 用户口径定案（原话「同挡位优先天赋果实，不是越大越好」）**
⇒ `vault_tier_of` 返回 `(档位, 平分决胜)`：

| 比什么 | 规则 |
|---|---|
| 第一关键字 | **档位 = 数量**（草 1/2/4/8 → 档 1/2/3/4；果 5/10/20/50 → 档 1/2/3/4） |
| 同档位 | **天赋果实优先**（`PREF_FRUIT=1 > PREF_CLOVER=0`） |
| 非草非果 | `(0, 0)` ⇒ 永远赢不过草/果（这就是「优先幸运草和四叶草」的实际含义 ✓） |

实测对照（守门断言同口径）：`8 草 vs 50 果 ⇒ 果胜`（同档 4）／`8 草 vs 20 果 ⇒ 草胜`（档 4 vs 3）
／`8 草 vs 神石 ⇒ 草胜` ✓

**③ 用户口径（原话「如果识别不到，就点击进去看是什么，有草/果就选，没有就选默认或其它」）**
⇒ 图标模板**一个都没命中**时不再"随便点第一格"，改为 `_probe_name()`：
**逐格点开详情 → OCR 读名称** → 命中草/果就选；都没有才回落到默认格 ✓
（只在兜底路径发生 ⇒ 正常路径零额外点击 ✓；每格读名后点空白处收起详情 ✓）

**④ 规划「很差劲」的真因（同批修）**：`st['cells']` 原来是**单帧整体覆盖** ⇒ 任何一帧被
面板/动画污染，已知格就丢了。真机铁证（同一张图 17:10~17:12）：已揭示 **10 → 11 → 9**
（揭示不可逆，不该变少 ✗）⇒ 求解器以为要重新开路 ⇒ cost 乱跳 **2 → 17 → 7** ✗
⇒ 新增 `st['obs']`＝**跨轮只增不减的观测累积**（已揭示永不翻回；sid/name 取更可信的那帧；
标记取并集），规划器输入改用它 ✓。离线 96 张盘对拍**不变**（`cur` 仍 10/10 与全知最优相等）✓

**产物**：`AutoExplore-v0.83-MGAS-宝库同档优先果实+认不出点开详情读名+观测累积-release.apk`
（= `MGAS.apk`，versionCode 83 / versionName 0.83，已装机 + 已重授权）。回归 = **73 项**。

### 6.24 v0.84：宝库「点开**瞬间**就被关掉」真因 + 弹窗地块拉黑（2026-10-01）

**① 病根（真机帧实测，用户手动停在宝库面板时抓帧取证 ✓）**

```
弹窗帧：黄金宝库 @dlg(690,438) conf0.998 ｜ 购买 @dlg(895,1498) conf1.000 ｜ 10000 @dlg(914,1541)
归一化帧(band 130~1080，点击循环实际用的那份)：只有「不管你看到多少宝物…只能领取一件哦」
  ⇒ 标题/按钮的归一化 y ≈1289 ⇒ **被 band 截掉** ✗
```

点击循环里点完每格靠 `panel_seen(it2)`（**归一化** band 130~1080）判"弹面板了吗"：
宝库两条签名都在带外 ⇒ 判 **False** ⇒ 循环**不 break**、继续按点序点下一格
⇒ 那一击正落在宝库面板上 ⇒ **面板被自己的下一次点击关掉** ✗ —— 用户说的"瞬间"就是这个
（不是 3 轮兜底那条路，那条要 20 秒以上）。

**修法**：① `panel_seen()` 与点击循环补一手**真·弹窗帧** OCR（`dlg_ocr`，覆盖到弹窗系 1769）
② 新增 `vault_title_seen()`（真机实测标题在 dlg 438 **读得到** —— 旧文档"标题在丢弃带里
永远认不到"**不准确**，丢弃带是 dlg>509）⇒ **标题 or 按钮**任一命中即认定 ✓
③ 按钮 y 带 `1400~1530` → `1330~1650`（真机 1498 在内；文案变化时也不掉出 ✓）

**② 弹窗地块：勾选 = 主动处理 / 不勾 = 拉黑（用户口径「能自由选择」）**
`targets_cfg.is_blocked(name)` 由**勾选配置推导**（不再是硬编码黑名单）：

| 状态 | 行为 |
|---|---|
| 特殊地块（商人/宝库/两种宝箱怪/勇者之墓/祭坛/礼包/预言石碑…）**勾上** | 主动去处理 ✓ |
| 同上**没勾** | **拉黑**：不是目标（`is_target` 先判 ✓）且**不参与开路**（从 `nones_extra` 剔除 ✓） |

（默认不勾的那批：金属/机巧/献祭宝箱怪、预言石碑/石板、勇者之墓、传承祭坛、限时礼包 ✓）

**产物**：`AutoExplore-v0.84-MGAS-宝库面板识别走真弹窗帧（修点开瞬间被关）+弹窗地块拉黑-release.apk`
（= `MGAS.apk`，versionCode 84 / versionName 0.84，已装机 + 已重授权）。回归 = **84 项**
（新增 6 项，其中 2 项**直接用真机帧**离线复核：弹窗帧认得出 / 归一化 band 认不出 ✓）。





**装备页真机标定（2026-10-01，用户手动停页面 + 我只读抓帧，两条通道互验一致）**：

| 元素 | 归一化帧 (ref) | 弹窗帧 (dlg) | 说明 |
|---|---|---|---|
| 页签 素材/装备/符文/宝箱/道具 | **看不见**（弹性带） | (152/345/540/732/925, 315) | 只能 `tap_dlg` ✓ |
| 背包右上角 X | **看不见**（弹性带） | (1023, 215) | 关背包用它 ✓ |
| 底部「筛选」 | (199,1550) | (199,1758) | —— |
| **「一键升星」** | **(923,1550)** ✓ | (923,1759) | 差 209 = C ⇒ 自洽 ✓ |
| HUD 体力 | (337,92) ✓ | —— | 读取窗口 cy<130 ✓ |

⚠ 关键教训：旧常量 `UPGRADE_BTN=(928,1789)` 是**弹窗系**的值被当**归一化系**用
⇒ 真机上差了 ~200px ⇒ 「点了一键升星没反应」✗。**两套坐标系的常量绝不能混用**。

### 6.25 v0.85~v0.94：宝库全链路 + 派遣 + 停止 + 拉黑（2026-10-01 深夜，连续十轮真机）

这十轮全是「用户报现象 → 我查日志/抓真机帧 → 定位 → 修 → **用真机帧或执行级测试验证**」的循环。
其中**五次是我的回归**（写代码时引入的），教训写在每条里 ✓

| 版本 | 用户报的现象 | 真因（证据） | 修法 |
|---|---|---|---|
| v0.85 | 「盘上有宝库却没识别到就退了」 | 中途接手时那一帧被残留面板盖住 ⇒ `buy_hidden` 空 ⇒ 判"没目标"退图（**识别本身没问题**：帧里 0.974 ✓） | `st['buy_seen']` **跨轮宝库记忆**（认到过就不忘）+ 已揭示格**名字变了立刻清记忆**（防幽灵目标） |
| v0.86 | 宝库点开就崩 | **我误删了 `ICON_THR = 0.55`**（改 `_icon_scales()` 时连它一起删了，代码还在用）⇒ `NameError` 每轮崩 ⇒ 买不成 | 补回常量 + **AST 守门**（任何"被读取但从未定义"的大写名直接报红） |
| v0.87 | 「第一层还没选择奖励就乱点了」 | `vault_flow` **裸调用没 try/except** ⇒ 崩了抛到上层 ⇒ 面板没人管而主循环继续点棋盘 ⇒ 点击全落面板上；且无论成败都 `STATS['vaults'] += 1`（谎报"买完"） | 包 try/except + **只有走完才计数** + 失败必 `ensure_closed` 收面板 |
| v0.88 | 「点搓（错）位置了」 | `VAULT` 的 `blank/(540,1700)` 在**面板外**、`back/(539,1212)` 落在**奖励格**上、`buy` 偏 54px（真机帧实测） | 按真机帧**逐像素**重标定；`blank` 用**列纹理 std≈0** 选真空白（不是目测） |
| v0.89 | 「卡在正在开箱 / 宝库没走完」 | 我写错解包：候选已是 `(分数,坐标)` 却又解包一次 ⇒ `TypeError: 'float' object is not subscriptable` | 两步写清 + **执行级测试**（假 bot 真跑 `vault_pick`）进回归；顺带修「数量读错被当最高档」（夹到 1~4 档） |
| v0.90 | 「要点派遣，脚本没点到一键派遣」 | 「探索配队」是**居中弹窗**，而 `DISPATCH_BTN` 走**归一化系数** ⇒ 真机偏 **249px**（= C·kx，C=209.4 ✓） | 面板按钮走弹窗系 |
| v0.91 | 「位置还是不对」 | 更根本：代码**从没用 OCR 读到的按钮**（日志里明明读到「键派遣」），一直点**写死的常量** ✗ | 改用 **OCR 现读坐标**（取最右下、排除"探索预计时间"），与分辨率/文案变化无关 |
| v0.92 | 「还是点不到」 | **通道串味**（我又犯一次）：`it2` 来自归一化帧，我却用 `tap_dlg` 点 ⇒ 偏 209px | 改用 `_tap()`（按 `_OCR_CH` 自动选通道 ⇒ **同源**）+ 日志记 `ch` |
| v0.93 | 「停止按钮不立即停」 | 真机日志量化：请求→停止最坏 **11.37 秒**（白等全在 `wait_change/wait_stable/wait_end`） | 等待循环**可中断**（每 0.06~0.1s 查停止位）；**Android `mapbot.py` 是独立副本**，Java `requestInterrupt()` 管不到纯 Python `sleep` ⇒ 补 `_sleep()` |
| v0.94 | 「跑铁血高地时点开了金属宝箱怪」 | 拉黑只把宝箱怪从**开路池**剔了，**没剔出规划模型** ⇒ solver 照样把它排进点序（真机：规划第一步 `3,2` 就是它，点完白转 26 秒） | 在 `_cells_for_model` 里**直接删出模型**（solver/eff 共用那份 ✓） |
| v0.95 | 「其他地图能否正常跑」（用户问） | 离线核查发现：15 张图名有**很像的组**（清凉沙滩/夏日海滩、迷失森林/幽暗密林/枯木丛林、废弃矿洞/洞穴深处…），OCR 掉字到**单字**时 `code_of` 会**在同组里猜错成员** ⇒ 用错模板集 ⇒ 整盘全错 ⚠ | `_candidate_codes()` + `_disambiguate_map()`：**用真实帧各建一次盘、比高分格数**选图，按图名缓存（每图最多付一次 ≈0.2~0.5s ✓） |

**「其他地图能否正常跑」离线核查结论**（2026-10-01）：

| 检查项 | 结果 |
|---|---|
| 地图名↔code 映射 | 15 张**无缺口** ✓ |
| `templates/unit/<code>/` 地块模板 | **15 张图全部齐、缺 0 个** ✓（S00003 有 33 个 sid、34 帧的宝库等） |
| 分类器能否建起来 | **15 张图全部可建**（条目 78~94、分组 8~11、建盘 0.08~0.12s）✓ |
| 棋盘几何 | 所有图**共用同一套** `GRID`（x0=36/y0=1002/pitch=144/7×5）✓ |
| 规划链路 | 真机语料里**非夏日海滩的 2 张盘**（枯木丛林/遗忘之海）能建盘 + 求解 ✓ |
| 图名识别 | 15 个标准写法**全认对** ✓；认不出返回 `None` 不瞎猜 ✓；**歧义已能实测消歧** ✓ |
| ⚠ 实战 | **仍未在真机上跑过其它图的完整链路**（进图→识别→打→退图）—— 语料 96 张里 94 张是夏日海滩 ⇒ 只能真机验 |

**跨端铁律（v0.93 踩出来的）**：`mapbot.py`（Android 版）**不在任何生成器里**，是手写独立副本
⇒ 改 PC 的 `mapbot.py` 对手机**零影响** ✗。三个生成器的分工见 §6.2 与 `port_loop.py` docstring。

**产物**：`AutoExplore-v0.95-MGAS-其他地图图名消歧（真实帧实测选图）-release.apk`
（= `MGAS.apk`，versionCode 95 / versionName 0.95，已装机 + 已重授权）。回归 = **133 项**
（含 5 类**真机帧/执行级**验证：宝库签名离线复核、`vault_pick` 真跑、停止可中断计时、
拉黑剔除、图名消歧选图）。

### 6.26 v0.96：宝库永不丢（「能直接点就先点」）+ 修粘性幽灵目标（2026-10-01）

**用户报**（原话）：「看看正在跑的……**黄金宝库明明都揭示了能直接点，他又去打了两个战斗地块**」
—— 真机帧 `bagdbg/board_now_ref.png`（22:33:13 抓的**枯木丛林**盘）就是现场：
(2,7) 的黄金宝库亮着、直接可点，而机器人跑去点了 (4,5)/(4,6) 两个格，各弹一次「拦路」战斗。

**三条真根因**（每条都有真机证据，全部已修）：

| # | 根因 | 证据 | 修法 |
|---|---|---|---|
| ① | `revealed = ratio(格亮度/命中模板亮度) ≥ 0.75` —— **模板一换就抖**：已揭示的宝库被判「未揭示」⇒ 既不进 `buy`、又被当「点不动」⇒ **看着宝库不打，去开路/打拦路** ✗ | 真机同款抖动实测：NCC **0.95+** 却 ratio **0.638**（离线复现于 `_tmpman/vault_priority_check.py`；帧上真值 ratio 0.99） | 新增 **验证式探点**：强匹配(≥0.85)+名字是宝库/商人 ⇒ **也去点一下**（雾格点了画面不变、游戏不消耗 ⇒ 无损）；上限 `BUY_PROBE_MAX=3` 次/格/图（防"一直点不开"空转 ✓） |
| ② | **sticky 清理是死代码**：`(st['cells'] or {}).get('board')` —— `st['cells']` 是分类器原样 dict（键 `(r,c)`，**没有 `board` 键**）⇒ `_still_buy` **恒为空** ⇒「买完/消耗就剔出粘性集」永不生效 ⇒ 粘性宝库挂满 **20 轮** = **幽灵目标** | `autoexplore_vaultskip.log` 22:30~22:32：每轮都是「**[rN] 没有目标了**」却「**还剩 1 个目标**」，然后满地图开路、把体力花在拦路战斗上 | `vault_still_there(st)`：按**当前帧 ∪ 跨轮累积观测 `st['obs']`** 判「名字里还有宝库/商人」；买掉后名字变空地 ⇒ 立刻剔除 ✓ |
| ③ | 点序是「揭一格 → 试一次目标」**交替** ⇒ 第一下永远是**开路格**（枯木丛林那类图的开路格常触发「拦路」战斗） | 同上日志：计划「最省体力 1，1 步 → 2,7」却先点 (4,6)；`buy_px` 只含本帧的 `buy/buy_hidden` ⇒ 本帧认不到时 `cands` 用 `cold<2` 把宝库格滤掉 | **已揭示的商人/宝库排到点序最前**（用户口径：能直接点就先点）；`buy_px` 免拉黑范围**扩到「粘性集 + 跨轮记忆 + 探点」**（"永不拉黑"对**认到过**的宝库成立 ✓） |

另修：**已揭示的宝库不许被 `done` 永久钉死**（点开过一次面板就再也不点 ✗）——
只要本帧它还是「已揭示 + 强匹配的宝库/商人」，就从 `done` 里放回（真买掉 ⇒ 本帧不再进 `buy` ⇒
不会重复点已消耗格 ✓）。

**回归**：`android_autoexplore/tools/verify_explore_slots_fix.py` **133 → 147 项**（新增 6 项静态守门 +
7 项**真机帧执行级**：帧上认出 (2,7) 黄金宝库 / `revealed_only` 判据此时为空（= 旧代码就是在这儿丢的）/
探点有上限 / `vault_still_there` 认得出且买掉后立刻清理）。
⚠ 顺带修正一条**过期断言**：套件里「夏日海滩帧 + 单字『海』⇒ 选 S00003」是拿**已被换掉**的旧帧写的
（`bagdbg/board_now_ref.png` 现在是**枯木丛林**帧）⇒ 改成在这张帧上为真的两条：
单字「林」3 候选 ⇒ 实测选中 **S20003**（= 真值 ✓）；单字「海」只许在同组候选里选 ✓。

**产物**：`AutoExplore-v0.96-MGAS-宝库永不丢（能直接点就先点）+粘性幽灵目标修-release.apk`
（= `MGAS.apk`，versionCode 96 / versionName 0.96，md5 `286b01f4…`，**已装机**）。
⚠ 装机后**截图授权失效**（`install -r` 杀 CaptureService，属已知现象）⇒ 需重新点「① 授权截图」
（下拉「应用范围」选**整个屏幕** → 开始）。

### 6.27 v0.97：宝库「奖励展示是模态」+ 修 `say` 崩溃（2026-10-01）

**用户真机报**（原话）：「购买第一层后，点击了好几个奖励才选择奖励，选择后**不点返回就直接点购买**，
真机现在在有返回弹窗的界面」——真机日志（22:50）逐条对上了，**三个真 bug**：

| # | 根因 | 证据（真机） | 修法 |
|---|---|---|---|
| ① | `_back_btn` 的**位置判据漂移**：v0.88 把 `VAULT['back']` 从「返回」按钮 (539,1212) 改成了**面板内安全空白 (660,1590)**（那是给"点一下收起详情"用的），而判据窗口**锚在这个值上** ⇒ 窗口漂到 y 1500~1680，真机「返回」实测在 **dlg(538,1267)** ⇒ **恒判 None** ⇒ 收不掉奖励展示，转身就去点「购买」✗ | 抓帧 OCR：`返回 @dlg(538,1267)`；旧判据在 10 条真机条目上测**命中 0** | 新增 **`VAULT_BACK_ZONE=(539,1240)`**（与兜底落点解耦，±170/±120）+「面板中下部任意『返回』」文字兜底 ✓ |
| ② | `buypanels.py` 里 **`say` 从来没定义/导入**（全文件只有第 736 行用它）⇒ 走到「读不到按钮 ⇒ 标定坐标保底」这条分支就 `NameError` ⇒ **整条宝库流程当场中断** | logcat：`{'vault':'flow_error','e':'NameError("name \'say\' is not defined")'}` | 模块内加 `say()` 兜底：惰性取 `explore_loop.say`（两端日志同口径），取不到就 `print`（照样进 logcat）✓ |
| ③ | **奖励展示（「恭喜获得…」/「返回」）是模态**，旧流程照样去点「购买」：`for _ in range(4)` 连点 4 次、且「保底」分支闭眼按标定坐标点购买 | logcat：连续 4 条 `{'vault':'buy','ring':2,'cost':20000}` 后崩 | ① 新增 `_reward_showing()`：**看到「恭喜获得/返回」就先收掉，收不干净 ⇒ 本轮到此为止，绝不去点购买**（`stuck_reward_after_claim` / `fallback_blocked_by_reward` 两条闸门）；② **同价「购买」再现 = 上次没生效 ⇒ 不再连点**（`buy_no_effect`）✓ |

另附（用户"点好几个奖励"的体感优化）：`vault_pick` 探名（图标认不出 ⇒ 点开前 3 格读名）现在
**探到想要的（幸运草/四叶草/天赋果实）立刻收手**（`probe_early_stop`）⇒ 少点几下乱点 ✓。

**回归**：`android_autoexplore/tools/verify_explore_slots_fix.py` **147 → 159 项**（新增 6 项静态守门 +
6 项**真机帧执行级**：真机「返回」必须被认出／旧判据认不出（= 根因）／该帧判为模态／
模态收不掉时**一次购买都不点**／确实在点返回／`say` 不抛 NameError）。

**产物**：`AutoExplore-v0.97-MGAS-宝库奖励展示模态（先返回再购买）+修say崩溃-release.apk`
（versionCode 97 / versionName 0.97，md5 `9eb3de2d…`；⚠ 该归档文件已被 v0.98 覆盖，见 §6.28）。
⚠ 同样需要重新授权「① 授权截图」（选**整个屏幕**）。

### 6.28 v0.98：宝库选奖励「检测奖励格 + 按颜色认草/果」（2026-10-01）

**用户真机报**（原话）：「这宝库选择奖励界面**纯在乱点**啊，东点一下西点一下。
**不应该识别到天赋果实和幸运草直接选这俩其中一个吗**」

**根因（一条，但结果很严重）：网格常数比真机实际位置高 ~51px** ——
面板高度随提示文案/按钮文案变（真机这屏提示是两行）⇒ 真机实测奖励格行中心
**942 / 1085 / 1231**，而 `VAULT['gy0']=746` 推出的是 **890 / 1034 / 1178**。
旧代码在格子**上方 51px** 处裁 135px 窗口认图标 ⇒ 全盘 NCC 掉到 **0.12~0.31**
（真机 log：`vault_debug near` 全低分 + `no_icon_hit`）⇒ 退成"逐格点开读名"
⇒ 用户看到的**东点一下西点一下** ✗。
⚠ 同一个偏移也让**点击**偏了：`claim pick (539,746)` / 探点 `(395,1034)` 都不在格心上。

**修法（三步，先便宜后贵，全部零乱点）**：
1. **检测奖励格**（`vault_tiles`）：奖励格一定有**彩色底**（空格/已领格是棕底）
   ⇒ 用"高饱和 + 非棕"掩码找连通块、按尺寸(100~185)与位置(面板中下部)过滤、
   中心 60px 去重 ⇒ 拿到**这一圈真实存在的格心**（真机两帧实测：圈2 = 8~9 格、圈1 = 16~21 格）✓
   （顺带把点击位置也修到格心上了）
2. **按颜色认种类**（`sprite_kind`，**尺度无关**）：去掉格子底色后看精灵的色调占比 ——
   真机标定：粉果实×10 **pink 0.571**｜绿四叶草 **green 0.353**；
   误命中（红宝石/棕装备/水晶）pink **0.16~0.18**、green **0.00**
   ⇒ 阈值 pink **0.35** / green **0.25**（**洋红**判据 R>150 且 B>0.55R，不是"红"，否则红宝石会被当成天赋果实 ✗）
3. 认出就直接按既有档位规则选一件（**先比档位(数量)、同档天赋果实优先**）；
   认不出才退到模板匹配（**在修正后的格心上**：天赋果实模板实测 **0.931** ≫ 阈值 0.55 ✓）
   → 最后才是"点开读名"那条兜底路。

**真机帧执行级验证**（`_tmpman/vault_icon_pick_check.py`）：
真机两帧（`vault_no_hit_L2/L1.png`）上，圈 2 帧里
`vault_pick` **一次点击都没有**、直接返回 `(540,1234) 天赋果实×10(色判) tier2`
（同帧另一格认出绿四叶草 green 0.353），日志里**不再出现 `probe`/`no_icon_hit`** ✓

**产物**：`AutoExplore-v0.98-MGAS-宝库选奖励：检测奖励格+颜色认草果（不再乱点）-release.apk`
（= `MGAS.apk`，versionCode 98 / versionName 0.98，md5 `52a7024a…`）。
⚠ 装机后需重新授权「① 授权截图」。

### 6.29 v0.99：拉黑格**不再被当成空地**（修「规划很差 / 看成能连锁」）（2026-10-01）

**用户真机报**（原话）：「真机最近一次规划很差啊，**是把拉黑的看成能连锁了**？」——**猜对了**，
而且是 v0.94 那次修法拉出来的：

| 环节 | v0.94（错） | v0.99（对） |
|---|---|---|
| `_cells_for_model` 里怎么处理拉黑格 | **从模型里 pop 掉** | **留在模型里** + `blocked=True` / `target=False` |
| 后果 | pop ⇒ `MapSim` 不建块 ⇒ `board[cell] = -1`，而 `mapsolve.Problem.consumed_cells()` 把 **`board < 0` 一律当"已消耗的格"**（2026-09-30 为"已经走出去的地图"补的 F3 语义），`block_revealed()` 又是"与任一已消耗格 4 邻接 ⇒ 已揭示" | `board ≥ 0` ⇒ **不算已消耗** ⇒ 不参与连通/揭示推理 ✓ |

⇒ 老行为的三条坏后果（全是"规划很差"的直接来源）：
① 拉黑格被当**空地** ⇒ 它旁边的**雾格**被判"已揭示、可点" ⇒ 计划里出现点不动的格；
② 连通空地的**连锁**会**穿过**这个洞 ⇒ 体力/步数被严重低估（= 用户说的"看成能连锁"）；
③ `_build_cache` 的 `EMPTY_ADJ`（可点集合）也把它算进去 ⇒ 可见范围虚高。

**游戏口径佐证**：`金属宝箱怪`（sid `S00001_009`）是 `SpecialSpot=2 / SpotSize=1` 的**内容格**，
游戏里同样**阻断连通草地**的连锁穿透 ⇒ 留在模型里当"不可点的内容格"才是 1:1 ✓

**执行级验证**（`_tmpman/blocked_chain_check.py`，造"中间一个拉黑宝箱怪"的假盘）：
老行为 `board=-1 / consumed=True`（复现）｜新行为 `board=3 / consumed=False`、非目标、非 plain ✓。
回归 `verify_explore_slots_fix.py` **169 → 170 项全绿**（原来那两条"必须被剔掉"的断言已按新语义改写）。

**产物**：`AutoExplore-v0.99-MGAS-拉黑格不再被当空地连锁（修规划虚高）-release.apk`
（versionCode 99 / versionName 0.99，md5 `867929ab…`）。
⚠ 装机后需重新授权「① 授权截图」。

### 6.30 v1.00：点序**硬过滤**拉黑地块（规划里有也不点）（2026-10-01）

**用户追问**（原话）：「规划没有拉黑特殊地块？还是**规划那里并且去点了**」——两条都要堵：

| 层 | v0.99 状态 | v1.00 补的 |
|---|---|---|
| **模型/规划**（`_cells_for_model` + `mapsim`/`mapsolve`） | 拉黑格留在模型里当"不可点的内容格"（`blocked/target=False`、非 plain）⇒ 不参与连通/连锁/揭示、不是目标 ✓ | —— |
| **求解器的"可点步"** | ⚠ 点掉一个**内容格**在模型里也算"消耗一个块 + 让邻居算已揭示"（真机确实会揭邻居）⇒ solver **可能**把宝箱怪当**便宜的开路步**排进点序 ✗ | **点序进 keep 之前硬过滤**：`order = [p for p in order if p not in _blk_set]`（`_blk_set = _blocked_px(st, c)`，**solver plan 里的也剔**）+ 落日志 `blocked_in_order`（"规划里到底有没有它"一眼可见 ✓） |

⇒ 现在是双保险：规划尽量不排它，**真排了也点不到**。回归 **170 → 171 项全绿**。
⚠ 诚实说明：我没能用最小场景把"求解器一定会排它"独立复现出来（自造场景里求解器返回的
坐标空间没对齐），所以这条是**按代码路径**堵的 —— 验证手段就是真机日志里的 `blocked_in_order`
（出现即说明求解器确实排过、而过滤生效了 ✓）。

**产物**：`AutoExplore-v1.00-MGAS-点序硬过滤拉黑地块（规划里有也不点）-release.apk`
（versionCode 100 / versionName 1.00，md5 `ec607a4a…`）。
⚠ 装机后需重新授权「① 授权截图」。

### 6.31 v1.01~v1.06：雾格「剪影识别」定 plain（2026-10-01，与用户逐轮定案）

**用户真机报**：「真机刚刚那次规划又出问题了……好像规划的没看到 **5,4** 有个能挡住连锁的」
（后续确认：**5,4 那轮是铁血高地**）＋「不要这么搞。**要优化识别模型**，认出雾格里那块不能穿过」
＋「去掉保守的那个」「还是别用保守的了，**不优雅**」

**根因（两条，第二条是第一版漏掉的）**：
1. **雾格的名字不可信**：雾是平坦覆盖，会把真身洗成"像草地"⇒ 分类器隔着雾猜，真机把挡连锁的
   物体猜成「草地/草丛」且 **score 0.95**（铁血高地那轮 `'5,4': ('001','草地',0.952,0.644)`）
   ⇒ 模型当空地 ⇒ `connected_plain` 让连锁**穿过**它 ⇒ 假便宜计划（2 步/9 体力）✗
2. ⚠ **多格块丢剪影**（我第一版没发现，是 A/B 对拍抓出来的）：块的代表格（anchor）**常常是平坦那一格**
   —— 真机实证 `(5,3)` 属于 6 格块 `anchor=(3,2)`，anchor 剪影 **0.016**（平坦）而 `(5,3)` 自己
   **0.271**（下面是大木桩）⇒ 只读 anchor ⇒ **整块被当空地** ⇒ 连锁照样穿过去 ✗✗

**修法（按格实测，不是一刀切）**：
- `spots.fog_silhouette()`：雾格算「雾底 + 暗剪影」占比（雾底 = 中位亮度，剪影 = 明显暗于
  `median−max(12,2.2·MAD)` 的像素，稳健抗噪），阈值 `FOG_SIL_MIN = 0.04`；
  **真机铁血高地同帧实测**：雾下有物体 **0.064~0.292** ／ 雾下平坦 **0.014~0.016**（4 倍空档 ✓）
- `mapsim.Block.plain`：**雾格只认剪影** —— 有物体 ⇒ 非空地（挡连锁）／平坦 ⇒ 空地；
  未揭示以下不再看那个不可信的名字 ✓（已揭示格照旧按真实分类 ✓）
- 多格块取**成员剪影最大值**（任一成员看出有东西 ⇒ 整块非空地 ✓）
- 保守口径（`fog_unknown` 一律挡连锁）**已按用户要求彻底移除**（残留 0 ✓）

**验证**：真机帧 fixture `bagdbg/iron_highland_fog_dev.png`（1280×2772）＋ A/B 对拍
（`_tmpman/fog_sil_ab.py`：集成值 == 独立原型值，逐格差 **0.000**）＋ 回归
`verify_explore_slots_fix.py` **171 → 180 项全绿**，含执行级一正一反锚点：
`(2,2)=0.169`、`(5,3)=0.271`、`(3,1)=0.292` ⇒ 非空地；`(1,7)=0.014` ⇒ 仍是空地 ✓

**产物**：`AutoExplore-v1.06-MGAS-雾格剪影定plain（多格块取成员最大）-release.apk`
（versionCode 106 / versionName 1.06，md5 `26554afc…`）。
⚠ 装机后需重新授权「① 授权截图」。

### 6.32 v1.07：把「体力不足 ⇒ 收工」说在悬浮条上（2026-10-01）

**用户报**（原话）：「什么情况，现在怎么连启动都启动不了了，**完全用不了**」

**真因：不是坏，是体力低于下限后按规则静默收工**（logcat 铁证，两次点 ▶ 都是 6 秒就停）：
```
00:21:24 ▶ 启动探索：连刷（maps=999，进图 25 体力/张，体力下限 50）  自动补给=false
00:21:31    体力 35 < 50（连刷下限），收工          ← 一次点击都没做（点击等待 0.0s(0 次)）
00:22:25 ▶ 启动探索：…（用户又点了一次）
00:22:32    体力 37 < 50（连刷下限），收工
```
- 当时 HUD 是 **40/2500**，而**自动补给是关的**（`{'pre_gate':'stamina', …, 'auto_supply': False}`）
  ⇒ 脚本一算"进图会把体力打光"就停；
- 这句原因**只进了控制台**（`say`），悬浮条上只写「体力不够了 · 收工」⇒ 用户看不出毛病 ✗
  （09-30 那次成功时 `自动补给=true` ⇒ 会自动吃结实补给继续，所以从没遇到这个门槛）

**修法（三条文案 + 一条启动提示，全部避开 OCR 关键词）**：
| 场合 | 新悬浮条文案 |
|---|---|
| 点 ▶ 启动瞬间 | `已启动 · 体力下限 50 ｜ 自动补给关（体力不够会直接收工，建议开上）` |
| 体力 < 下限 | `体力 37 不足（要 50）· 开自动补给可自动吃结实补给`（开着补给但没吃够时换成"请手动补一次"） |
| 体力读不到 | `体力读不到（要 ≥50）· 先不进图，请看一眼体力` |

⚠ 文案必须避开 `OverlayService.sanitize()` 的 OCR 关键词（探索/派遣/领取/关闭/开始冒险…），
否则会被糊成 `▓` —— 回归里加了这条断言（4 条文案 × 9 个关键词全过 ✓）。

**产物**：`AutoExplore-v1.07-MGAS-体力不足与启动前提说明白（悬浮条提示）-release.apk`
（versionCode 107 / versionName 1.07，md5 `41fb12ea…`）。
⚠ 装机后需重新授权「① 授权截图」。

### 6.33 v1.08：收工行带原因 + 战斗日志写清「打的是什么格子」（2026-10-01）

**用户原话①**：「现在悬浮窗还是只写了收工，**没有写是因为体力不够 50 才收工**」
**用户原话②**：「战斗时日志要写出打这个格子是什么格子，**拦路的就写拦路格，首领就写首领格，
四叶草就写四叶草格，大拇指就写大拇指格**。同时有多种就都写出来，比如
**当前格子标志：首领，四叶草，大拇指，红装**」

**① 收工原因为什么还是没显示**：v1.07 我只改了 `status('体力 N 不足…')`，但紧接着
`run_maps` 收尾又会写一条 `status('收工：刷完 N 张 · 平均 X 秒/张')`
—— **后写的把前一句顶掉了** ✗。而且 `STATS['stopped']`（真正的结束原因）从来没拼进那行。
⇒ 两处都修：体力不足时**写入** `STATS['stopped'] = '体力 N 不足（要 M）'`，
收工行改成 `收工：刷完 N 张 · <结束原因>`（原"平均秒/张"在没有原因时仍保留 ✓）。

**② 格子中文名**（新增 `MARK_CN` / `mark_cn()` / `tile_phrase()`）：

| 标记 | 中文 | 文案 |
|---|---|---|
| 无标记（被挡路） | — | **拦路格** |
| `boss` | 首领 | **首领格** |
| `clover` | 四叶草 | **四叶草格** |
| `recommend` | 大拇指 | **大拇指格** |
| `redEquip` | 红装 | **红装格** |
| 多种同时存在 | — | **格子标志：首领，四叶草，大拇指，红装**（用户样例逐字一致 ✓） |

三处都接上：**开打**（`开打 · 首领格`）、**战斗中**（`战斗中 · 四叶草格`）、
**结算**（`战斗胜利 ✓ · 格子标志：…`）；控制台那行也补了中文（`开打 · 首领格（标记 ['boss']）`）。
⚠ 文案照样避开 `OverlayService.sanitize()` 的关键词（7 种组合 × 3 个场合 × 9 个关键词全过 ✓）。

**产物**：`AutoExplore-v1.08-MGAS-收工带原因+战斗日志写清格子-release.apk`
（versionCode 108 / versionName 1.08，md5 `0fd503c2…`）。
回归 `verify_explore_slots_fix.py` **185 → 192 项全绿**。
⚠ 装机后需重新授权「① 授权截图」。

### 6.34 v1.10（续）：宝库「选不了奖励」= 圈层约束丢失 + 按钮被当成奖励格（2026-10-01）

> v1.09（wait 观察窗全分辨率 / `panel_seen` 死代码）与 v1.10（骰子图标兜底 + 价格标红跳过）
> 由本会话更早的轮次完成（归档 `AutoExplore-v1.09-…` / `AutoExplore-v1.10-MGAS-骰子图标兜底…`）。
> 本节是**在其之上**的修复，仍是同一个 versionCode **110 / 1.10** 重打包。

**用户报**：「宝库又选不了奖励了」

**真机 logcat 铁证**（同一轮里 ring 1/2/3 的 `pick` **全是同一个坐标**）：
```
{'vault':'tiles_detected','n':21,…}   {'vault':'color_none','cells':21}
{'vault':'icon_hit','name':'四叶草','qty':0,'score':0.577,'at':(540,1089)}
{'vault':'claim','ring':1,'pick':(540,1089),…}   ← (540,1089) = **正中心**
{'vault':'claim','ring':2,'pick':(540,1089),…}   ← 同一个
{'vault':'claim','ring':3,'pick':(540,1089),…}
```
两个真 bug，都是 v0.98 那一版埋的：

| # | 根因 | 证据 | 修法 |
|---|---|---|---|
| ① | **圈层约束丢失**：v0.98 把 `cells` 直接换成"检测到的**全部**彩色格" ⇒ 三层共用同一批格 | 上面 logcat：三层 pick 全是 (540,1089) 正中心。游戏只允许选**当前那一圈**（`RefreshDefaultSelectingIndex` 按 `currentLevel` 定 `selectingIndex`，非本圈的选择直接 return）⇒ 1/2 圈点正中心 = **空操作** ⇒ "选不了奖励" ✗ | 新增 `_vault_lattice()`（点阵判行列）+ `tile_ring()`（切比雪夫距中心）；`vault_pick` **只留本圈**，本圈一个都没检出才退回理论圈 ✓ |
| ② | **右下角按钮被当成奖励格**：`_tile_mask` 按"高饱和彩色"找格，而「选择奖励/购买」按钮 (895,1521) 同样是高饱和彩色块、尺寸也落在 100~185 内 ⇒ 混进 `cells` | 真机帧上 `vault_pick(1)` 返回 **(895,1525)** = 按钮自己 ⇒ 点它 = 点按钮但一格未选 ⇒ 选不了 ✗ | 同一函数用于**过滤**：按钮行号 = (1521−746)/144 = **5.38**（点阵只有 0~4）⇒ 剔掉 ✓ |

**验证**（真机帧 `fixture_vault_all_rings.png`，5×5 全彩色）：
外圈切出 **16** 格 ✓；`vault_pick(1/2/3)` 的 pick = `(828,1233)` / `(392,942)` / `(540,1089)`
⇒ **不全相同** ✓ 且各在**本圈** ✓；`_vault_lattice(895,1521) is None` ✓。
回归 **192 → 196 项**（+4 项圈层/点阵守门）。

**产物**：`AutoExplore-v1.10-MGAS-宝库圈层约束修复（选不了奖励）+点阵过滤-release.apk`
（= `MGAS.apk`，versionCode **110** / versionName **1.10**，md5 `9c1b956c…`，**已装机**）。

### 6.36 v1.11：修「面板挡住棋盘」误判 + 不再无限循环（2026-10-01）

**用户报**（原话）：「我发给朋友这个软件后他**进图就显示面板挡住了棋盘，正在收起，一直卡在这**，
但实际上棋盘上啥都没有」

**根因（两条，第二条才是"一直卡"的关键）**：

| # | 根因 | 说明 |
|---|---|---|
| ① | `board_hidden()` 的两条判据都是**绝对阈值**（`ratio<0.55` 数 ≥15 / `light==0 且 gray≥25`），而 `ratio = 画面亮度 / 模板亮度` **依赖设备**（机型 gamma / 亮度 / 缩放差异会让整盘偏暗）⇒ **设备偏暗 ≠ 面板遮住**，但被当成遮住 ✗ | 真机在别的机型上：棋盘正常、只是整体暗 ⇒ 每张图都判"被挡" |
| ② | 判"被挡"3 次 ⇒ `board_not_visible` ⇒ `why='stuck'` ⇒ 退图失败 ⇒ `game_recover` ⇒ **下一张图** ⇒ 同样判"被挡" ⇒ ⋯ **永远出不来**（`run_maps` 里没有任何"连续 stuck"的刹车）✗ | 用户看到的就是"一直卡在这" |

**修法**：
1. **判据改成"以本帧最亮格为基准"的相对口径**：
   ```python
   _mx = max(ratio)                       # 本帧最亮的一格（正常盘必然是"已揭示"那格）
   if light == 0 and gray >= 25 and _mx < 0.40:   # ← 加 _mx<0.40：设备偏暗 ≠ 面板遮
       return True
   _thr = 0.55 * _mx                      # ← 阈值按本帧缩放
   return (ratio < _thr 的格数) >= 15
   ```
   ⚠ **只收窄、不放松**：真面板遮罩会把整盘压到 0.25~0.35 ⇒ `_mx` 也很小 ⇒ 两条判据照样成立 ✓
2. **连续 2 张 `stuck`/`blank` ⇒ 整局停下**（`STATS['stuck_maps']`），悬浮条写明原因；
3. **首次判"被挡"就存诊断帧**（`_pub_dump('board_hidden_r%d')` → `/sdcard/Download/autoexplore/bagdbg/`）
   —— 我们手上**没有别的机型的帧**，没有它就无法给阈值标定 ✗

**验证**（执行级，直接调真 `board_hidden`）：

| 画面 | 期望 | 实测 |
|---|---|---|
| 正常盘（雾29+亮6） | 不判被挡 | ✓ |
| **暗设备 k=0.7 / 0.5**（朋友那类） | **不判被挡** | ✓（旧代码：判被挡 ✗） |
| 面板盖中间（只露 3 格） | **判被挡**（09-26 修过的老判据，不许回归） | ✓ |
| 全盘被遮罩 | 判被挡 | ✓ |

回归 **196 → 201 项**（+5 项 v1.11 守门）。**产物**：`AutoExplore-v1.11-MGAS-修面板误判卡死+不再无限循环-release.apk`
（= `MGAS.apk`，versionCode **111** / versionName **1.11**，md5 `c3fe17c2…`，**已装机**）。
⚠ 仍需重新授权「① 授权截图」。
⚠ **待办**：收到朋友那台机的 `board_hidden_r*.png` 诊断帧后，用它做 fixture 把这套阈值再标定一次
（现在是按"覆盖率/亮度模型"推的，有真帧就能直接量）。

### 6.37 v1.12/v1.13：修两处"没有上限"的死循环 + 给别人的手机留一份可回传日志（2026-10-01）

**用户报**（朋友那台机）：「进图就显示面板挡住了棋盘，正在收起，一直卡在这，
**但实际上棋盘上啥都没有**」→ 后续：「这次**连地图都进不去了，显示正在把游戏拉回来**」

| 版本 | 修的东西 | 根因 |
|---|---|---|
| **v1.11** | `board_hidden()` 误判 | 两条判据都是**绝对阈值**（0.55/0.85），而 `ratio` 依赖设备（机型 gamma/亮度）⇒ **设备偏暗被当成面板遮住** ⇒ 每张图都判"被挡"。改成**以本帧最亮格为基准**的相对口径（`_mx<0.40` + `_thr=0.55*_mx`），**只收窄不放松**（真遮罩仍判得出、"盖中间"老判据不回归 ✓） |
| **v1.12** | ① `optimal_order` 的求解器调用**没有时间上限**（只有 `max_states=40000`）② `game_recover` 成功后 `continue`、下一张再失败又恢复 ⇒ **无限"拉回来"** | ① 棋盘一旦被切碎，A* 几万状态展开 = **几分钟满载空转、全程不打日志**（另一处 `solver_order` 早就有 `max_secs=8`，这一处漏了）⇒ 补 8 秒上限 + 前后落日志；② 加 `STATS['recover_n']`，连续 3 次仍跑不动 ⇒ 停整局并提示发日志 ✓ |
| **v1.13** | **朋友圈里根本拿不到日志** | `MGAS` 是 release 包 ⇒ 私有 `files/runs/**` 不可 `run-as` 拉出 ✗；朋友也不会跑 logcat。⇒ `flush()` 把最新日志挂到全局，`dump_summary()` 抄一份**可读文本**到公共目录 `/sdcard/Download/autoexplore/bagdbg/mgas_log.txt`（含统计 + 最近 400 条日志），让朋友直接发这个文件 ✓ ⚠ 只在端上写（PC 上 `os.name` 守卫，否则会在盘根建 `D:\sdcard\…` ✗ 本轮已踩到并清理） |

**验证**：回归 **201 → 205 项**（v1.11 五项画面判据 + v1.12 四项上限守门）。

**产物**：`AutoExplore-v1.13-MGAS-一键回传日志（朋友机用）+防循环-release.apk`
（= `MGAS.apk`，versionCode **113** / versionName **1.13**，md5 `11fc0e54…`，**已装机**）。
⚠ 仍需重新授权「① 授权截图」。

**给朋友的操作（三步）**：
1. 装这个 APK → 重新授权「① 授权截图」（**应用范围选「整个屏幕」**）；
2. 跑一次；如果还是停在"面板挡住了棋盘 / 正在把游戏拉回来"，让它停；
3. 用文件管理器把 **`内部存储/Download/autoexplore/bagdbg/mgas_log.txt`** 发回来
   （同目录下的 `board_hidden_r*.png` 如果能一起发更好 —— 那是**他那台机**的真实帧，
   我拿到就能像铁血高地雾格那样把 `board_hidden` 的阈值**按真帧标定**并做成常驻 fixture）。


### 6.38 v1.14：一键反馈按钮 + **工程已从仓库分离到 `D:\MGAS`**（2026-10-01）

**用户要求**（原话）：「能不能加个按钮能更方便让朋友发他的问题给我」

**做了**：悬浮条最右加一颗 **「反馈」**（`btnFb`，在 ✕ 之后）——
一点 ⇒ 打包 **日志 + 机型/分辨率 + 现场帧** → `Download/autoexplore/MGAS反馈_<时间>.zip`
→ **弹系统分享面板**（微信/QQ 直接选人发）。
- 实现：`app/src/main/java/com/fantasy/autoexplore/Feedback.java`（新文件）
- 包内容：`mgas_log.txt`（Python 每轮收尾落的可读日志）、`board_hidden_*.png`（判"被面板挡住"
  时的现场帧，最多 5 张）、`last_summary.json`、`device.txt`（机型 / Android 版本 /
  **屏幕分辨率与 dpi** / 应用版本 / 悬浮条几何 —— 分辨率相关 bug 全靠它）
- **为什么走 MediaStore**：`file://` 在 API 24+ 抛 `FileUriExposedException` ✗；
  FileProvider 要引 androidx（本工程**没有** androidx 依赖，加依赖要联网拉包 ✗）；
  `MediaStore.Downloads` 在 API 29+ **不需要任何存储权限**，且直接给出可分享的 `content://` URI ✓
- 同一条代码路径也挂了广播命令：`--es cmd feedback`（只打包）/ `+ --es share 1`（打包并弹分享）
- **实测**（真机）：`[feedback] 已生成 …/MGAS反馈_20261001_052445.zip`、
  `MGAS反馈 zip -> content://media/external/downloads/1000020280`、
  悬浮条出现 `› 反馈包已生成 · 分享面板已打开（选微信/QQ 发我）`，**零异常** ✓
- ⚠ 用法提醒：**先让脚本跑到出问题那一刻、再点「反馈」**（`mgas_log.txt` 是每轮收尾才刷新的）

**同时：工程从「幻想少女公会」仓库分离**（用户要求「分离出来，新建个文件夹叫 MGAS」）：
```
D:\MGAS\                           ← 新家（与仓库同级）
├── android_autoexplore\           ← 原 D:\幻想少女公会\android_autoexplore（10.85 GB，含 101 个 APK 归档）
├── mapbot_pc\                     ← 原 D:\幻想少女公会\tools\mapbot（PC 端源）
└── data\server_datatable.json     ← 数据表副本
```
- 两个 port 工具与回归套件里的**写死绝对路径已改成"按自身位置推算"**
  （`MGAS_MAPBOT_SRC` / `MGAS_PY_DST` 可覆盖 + 老布局兜底）⇒ 在新位置直接跑通 ✓
- 仓库那侧 `tools\mapbot` 改成**目录联接（junction）**指向 `D:\MGAS\mapbot_pc`：
  仓库里 4 个诊断脚本与文档里的旧路径照旧可用，且是**同一份文件**（不分叉 ✓）
- 仓库侧留说明：`D:\幻想少女公会\docs\MGAS已分离.md`；MGAS 侧有顶层 `D:\MGAS\README.md`

**产物**：`AutoExplore-v1.14-MGAS-一键反馈按钮（日志+机型+现场帧打包分享）+已分离到D盘MGAS-release.apk`
（= `MGAS.apk`，versionCode **114** / versionName **1.14**，md5 `9f2b3c71…`，**已装机**）。
回归 **205 项通过 / 0 失败 / 1 显式跳过**（在新位置 `D:\MGAS` 下跑的 ✓）。

### 6.35 本轮「整体体检」查到的**两个工作区级事故**（不是代码 bug，但危害更大）

| # | 现象 | 危害 | 处置 |
|---|---|---|---|
| ① | **PC 数据表被回退成 09-14 旧版**：`unpack_apk/dump/server_datatable.json` 由 4.0MB（0928：15 图 / 含 `夏日海滩 S00003` / Equip 1634 / Role 214）变成 3.8MB（14 图 / **无夏日海滩** / Equip 1534 / Role 204） | 回归 6 项当场变红（成本表 / 图名歧义 / 全名路径 / 宝库帧识别）；**下次重打数据包会把旧表打进 APK** ⇒ 端上少 32 条 Area_Spot / 100 件装备 / 10 个角色 ✗ | 从 `fetch_20260928/server_datatable.json` 恢复（md5 `19e8d46084`）；核对**包内** `assets/mapbot_pack/server_datatable.json` 同 md5 ✓（端上本来是对的，只有 PC 侧被回退） |
| ② | **`android_autoexplore/_verify/` 的真机 fixture 被清空**（`phone_slots_full_0930.json` + 整个 `bagdbg/*.png|json`） | 套件**直接崩**在 `json.load`；更糟的是十几处"缺 fixture ⇒ 当通过"让 **192 项"全绿"里混着一堆没跑过的断言** ✗ | ① 从设备 `/sdcard/Download/autoexplore/bagdbg/` 拉回，并用**稳定名**固化（`fixture_vault_all_rings.png` / `iron_highland_fog_dev.png`，不再用每轮被覆盖的 `vault_no_hit_L*.png`）；② 套件新增 `skip()`：**跳过单独计数**、结尾打印「以下 N 项没真正验证」⇒ 再也不会被"全绿"骗 ✓（本轮把 8 处静默跳过改为显式 `skip`） |

⚠ 另修一处**假失败**：`is_target` 的判据命中文本仍写 `if is_blocked(name):`，而实现早已改成
`is_blocked(name, d)`（传 cfg 下去，修"静默丢配置"）⇒ 断言改成两种写法都接受 ✓



⚠ 中间版本 v1.01（雾格一律挡连锁·保守）/v1.02（撤销保守）/v1.03（剪影一票否决）/
v1.04（又上保守）/v1.05（再撤保守）都是与用户来回定案的过程版，最终以 **v1.06** 为准。



⚠⚠ 教训（本文件同款坑再犯）：**不能**用 PowerShell `Set-Content`/`-replace` 改 `app\build.gradle`
—— 会给文件加 **UTF-8 BOM** ⇒ Gradle 直接 `Could not compile build file` ✗
（这次就是这么把 v0.98 第一次构建搞失败的；改法：`.NET WriteAllText + UTF8Encoding($false)`，
或干脆用编辑器改 ✓）

### 6.39 v1.16：堵掉 `CommandReceiver` 的 RCE 面 + **v1.11~v1.15 补提交推 Gitee**（2026-10-01 下午）

**起因**：接手 AI 通读源码时发现 —— `CommandReceiver` 是 **`exported=true` 且无任何鉴权**，
而它的 `py --es code` 分支走 `PyBridge.call("_cmd_run_snippet", code)`
⇒ `explore_android._cmd_run_snippet` → **`exec(code)` 任意 Python 代码执行**。
⚠ **release 包同样带这个 Receiver**（release 只是 debug 签名 + `minifyEnabled false`，**不是** debuggable），
所以这不是「只在开发包才有」的问题。
⇒ **同设备任意 app 发一条广播就能执行任意 Python**（还能经 `DeviceApi.bringGame()` 拉起游戏、
读设备信息/截图帧）。

**修法**（最小改动，不动日常用法）：
- `CommandReceiver.java` 加 `DEBUG_ONLY = {py, classify, overlay_state, overlay_roll, mask_check}`
- 在 `onReceive` 里、**起线程之前**拦：`if (isDebugOnly(cmd) && !BuildConfig.DEBUG) { 记日志; return; }`
- `app/build.gradle` 显式开 `buildFeatures { buildConfig true }`
  （⚠ **AGP 8.x 默认不生成 `BuildConfig`**；`gradle.properties` 里那个 `buildconfig=true` 是旧开关、不生效）
- **日常运维命令全部不受影响**：`explore` / `explore_stop` / `explore_status` / `summary` /
  `red_lock` / `red_unlock` / `overlay_on|off|dump` / `feedback` / `pyinfo` / `selftest` / `test_ocr` 照常用
- 要调试请出 `assembleArm64Debug`（DEBUG=true 且可 `run-as`）

**回归**：新增 7 条断言（㉕ 组），含「拦截发生在起线程前」「日常命令不受影响」「buildConfig 已开」
⇒ **211 → 218 项，通过 218 / 失败 0 / 跳过 1**（跳过的 1 项是 v0.98 颜色认种，
那帧里没草/果，与本改动无关）。

**真机/模拟器实测**（MuMu 16384 / Android 15 / x86_64，release 包，`flags` 无 `DEBUGGABLE`）：
```
$ am broadcast -n …/.CommandReceiver -a com.fantasy.autoexplore.CMD --es cmd py --es code 'print(1+1)'
  ⛔ 命令 py 仅调试包可用（当前是 release 构建）⇒ 已拒绝      ← RCE 通道已封 ✓
$ 同上逐条：pyinfo / explore_status / overlay_dump   ⇒  正常执行 ✓（日常运维不受影响）
$ 同上逐条：mask_check / classify                    ⇒  ⛔ 已拒绝 ✓
```
⇒ **同设备任意 app 发的广播在 release 包上不再能执行任意 Python**。要调试请出 `assembleArm64Debug`。

**顺带把 v1.11~v1.15 补提交并推上 Gitee**：此前 HEAD 停在 `3051601`(v1.10)，
而**远端 `master` 还停在 `fb6d12c` = v0.38 初始入库**（落后 15 个版本）⇒ 现已推到 `5d8492e`。
⚠ 本次一并**恢复了被 `b178afe` 那次全量 revert 顺带删掉的 `_verify/` 真机 fixture**
（`phone_slots_full_0930.json` + `bagdbg/` 26 张帧 + 朋友机 `phone_friend_rmx3800/`）——
**这些是真机原始证据，丢了要重抓真机**，已随本次入库。

### 6.40 v1.17：⭐⭐ **改 MuMu 分辨率的正确方法**（`wm size` 是**无效**的，别再试）＋ 朋友真机几何对拍（2026-10-01 下午）

**起因**：用户要求「把模拟器分辨率换成朋友真机的分辨率，测脚本能否正常运行」。

#### ⚠ 先说结论：`adb shell wm size/density` 对 MuMu **完全无效**（已实测，别再浪费时间）

```bash
$ adb shell wm size 1264x2780 && adb shell wm density 560   # 显示 Override 成功
$ adb shell wm size                                          # 但 Physical size 仍是 720x1280
$ adb shell "getprop ro.product.cpu.abilist"  …               # RefMapper 读到 k=0.6667
$ adb exec-out screencap -p | 解析 PNG 头                     # 出的图仍是 720x1280
```
根因：`CaptureService.realScreenSize()` 用的 `getMaximumWindowMetrics()`（`CaptureService.java:184`）
在模拟器上返回**物理屏**，不认 override ⇒ 实际帧根本没变。

#### ✅ 正确方法：改 MuMu 实例的 `customer_config.json`（`wm size` 之前就是这么改的）

**两个关键点，少一个都不生效**：
1. `setting.resolution.current` = `"宽.000000:高.000000:dpi.000000"`
2. ⚠ **`setting.resolution.mode.choose` 必须切成 `"resolution.mode.custom"`**
   —— 默认是 `"resolution.mode.phone"`，MuMu 会用**手机预设 720×1280 覆盖**掉 `current`（这就是只改 current 却没效果的原因）
3. 改完**必须重启该实例**（配置在启动时读取）

```bash
# ① 找到在跑的是哪个实例
"D:/MuMu Player 12/nx_main/mumu-cli.exe" info -v 1        # 列出实例名
"D:/MuMu Player 12/nx_main/mumu-cli.exe" info -v all      # 带 adb_port
#   ★ 实例目录名 ≠ index：configs/extra_config.json 里的 "relateId"/"playerName" 才是真的
#     （踩过：改 15.0-2 的配置，重启的却是 index=1，白跑一趟）

# ② 改配置（改前务必备份）
D:\MuMu Player 12\vms\<实例>\configs\customer_config.json
#   "resolution": { "current": "1264.000000:2780.000000:560.000000",
#                   "mode": { "choose": "resolution.mode.custom", ... } }

# ③ 重启该实例
"D:/MuMu Player 12/nx_main/mumu-cli.exe" control -v <index> restart     # errcode 0 = ok
# 等 ~50s 起来
```

**实测（已生效 ✅）**：
```
$ adb shell wm size   →  Physical size: 1264x2780     （不再是 720x1280）
$ adb shell wm density→  Physical density: 560
$ adb exec-out screencap -p → PNG 实际尺寸 1264x2780
```
⚠ 重启后**三项授权要重做**（无障碍 / 悬浮窗 / **截图授权**），且**截图授权必须点系统弹窗**（MuMu 1080×1920 = (849,1277)；
真机则要「应用范围→整个屏幕」）。没授权时 MGAS 日志报「⚠ 没有帧：请先授权截图」，
此时 `RefMapper` 仍显示 720×1280 —— **那不是配置没生效，是没帧**。

#### 顺带：朋友真机（realme RMX3800 1264×2780）锚定模型几何对拍

新增 `tools/verify_friend_phone_geometry.py`（**不依赖设备**，用真机留下的
`_verify/phone_friend_rmx3800/device.txt` 里的 overlay_dump 当 ground truth 离线复算），
**11 项全过**：

| 项 | 模型预测 | 真机实测 | 差 |
|---|---|---|---|
| k | 1.1704 | 1.1704 | 0 |
| 悬浮条顶边 devY(1722) | 2548.3 | **2548** | 0.3px |
| 悬浮条底边 devY(1818) | 2660.6 | **2661** | 0.4px |
| 高度 devLen(96) | 112.4 | 112 | 0.4px |
| 左边 devX(20) | 23.4 | 23 | 0.4px |
| C = dialogShift | 227.7 | — | ≠0 ⇒ 两系必须分开走 |
| 弹性带 | (351, 884) | — | 非空 ⇒ 面板标题/背包页签只能走弹窗系 |

⇒ **锚定模型在 1264×2780 上成立**（几何层面）。
⚠ 但这只验几何，**不验识别阈值/面板判定/点击命中** —— 那些必须真机或改好分辨率的模拟器实跑。

**回归**：主门禁新增 v1.17 组（5 项）⇒ **223 项，通过 223 / 失败 0 / 跳过 1**。

#### ⭐ 实测：1264×2780 上跑起来的结果（MuMu，已授权）

```
状态芯片：截图：就绪 ｜ 点击通道：就绪 ｜ 红装锁：无          ← 三绿 ✓
日志：屏幕 1264x2780 ⇒ 锚定模型 kx=1.1704 shift=533 顶块偏移=0（顶块锚顶+其余锚底）
      ↑ 与离线预测的 kx=1.1704 / shift=532.9 **完全一致** ✓
selftest：[1]资源 ✓  [2]import 12 模块 ✓  [3]截图/无障碍 ✓
          [4] 截图 1080x1920 ✓ 266ms        ← 归一化正确
          [5] OCR 24~27 条 ✓ 2541~4671ms
          [6] 分类 35 格 2.7~2.9s（中位分低 ⇒ 当时画面不是棋盘，正常）
          [7] EffPolicy ✓ 1 步 11ms
⇒ 管道全通：新分辨率下截图→归一化→OCR→分类→规划 都正常，只是耗时略高（分辨率变大）。
```

**⭐ 顺带发现的一个坑（手动点屏幕时也会踩）**：
> `adb shell input tap` 打的是**设备像素**，而 `ocr.json` / 悬浮条 dump 里的坐标是
> **归一化参考系 1080×1920**。在新分辨率下必须换算：
> `devX = x*kx`、`devY = y*kx + shift`（y>300）。
> 实测：OCR 读到「确定」在参考系 (568,1086) ⇒ 设备要点 **(665,1804)**；
> 直接拿 568,1086 去 tap **点空**（我第一次就这么点了，画面纹丝不动）。
> ⚠ 同理，`_pub_dump` 落的诊断帧（`board_hidden_*.png`）是**归一化帧 1080×1920**，
> 不是设备帧 —— 拿它按设备坐标去裁会越界（我也踩了一次）。

#### ⚠ 本轮实测的一个**误判**（不是新分辨率的 bug，别记到坐标头上）

自动登录确实工作：`explore` 命令 → `run_maps` 开头自动 `game_recover()`（纯 OCR 导航）
→ 把游戏从热更公告页拉到了登录页。日志：
```
› 开跑（1 张）· 正在找游戏画面
› 第 1 张图 · 准备进图
   已进图，体力 ?                              ← ⚠ 这里就误判了
› 第 1 张图 · 已进图，正在看棋盘
   [r0] 棋盘被挡（读成暗格/压暗，面板挡住棋盘？）→ 关面板 2 个（第 1 次）
   [r2] 棋盘被挡 → 万能位兜底关面板（第 2 次）
   [r3] 棋盘被挡 → 万能位兜底关面板（第 3 次）
   本图结束：stuck（耗时 62 秒）
```
拉下诊断帧 `board_hidden_r0.png` 目视：**画面是游戏登录页**（开始游戏 + 隐私政策 + 健康游戏忠告），
**这个 MuMu 实例上的游戏没有登录态**。所以：
- 「已进图」是把登录页误判成了图内；
- 棋盘区（参考系 1002~1722）落在登录页的空白文字区 ⇒ 判「被挡/暗格」⇒ 反复关面板直到 stuck。

⇒ **这是账号没登录，不是分辨率/坐标系/识别的问题**。归一化、OCR、锚定模型在 1264×2780 上都正常
（见上面 selftest 七段全通）。要测完整链路，需**先在这个 MuMu 实例里登录游戏**。

> ⚠ 顺带暴露一个**真改进点**：`in_map()` 对「登录页」的否定证据不够强 ——
> 登录页没有「结束冒险/开始冒险」之类的字，也没有棋盘亮格，
> 但 v1.15 新加的「选图界面专属文字」（深渊NN/星界秘境）和「必须有真·已揭示亮格」都拦不住它。
> **可加一条负面证据：读到「开始游戏」或「我已详细阅读并同意」⇒ 一定不在图里**
> （登录页有这两个字；图内和选图界面都没有）。这与 `game_recover` 的 `_game_main_ok`（`:6944-6951`）
> 已有判据一致，可以直接复用。

#### ⭐⭐ v1.17：顶块（顶部黑/挖孔）怎么验 —— 「减顶部」行不通，改用**注入 topInset**

**先说「减顶部」为什么不行**（用户提的思路，算给你看）：
```
真机 1264x2780 + topInset=132  →  kx=1.1704, shift=532.9
「减高」成 1264x2648 + topInset=0 →  kx=1.1704, shift=400.9   ← shift 也少 132
```
⇒ 减的是**总高**，于是 `shift` 跟着少 132，**棋盘/悬浮条整体上移 132** ——
等于把真机差异搬到锚底区，**什么都没验到**。
要成立必须是「**总高仍 2780、但游戏视口只占下面 2648**」（顶部 132 留黑），这样 `shift` 才 = 532.9。

**模拟器上造不出这个状态**（三条路都试过）：
| 尝试 | 结果 |
|---|---|
| `wm overscan 132,0,0,0` | MuMu 的 wm 不支持该命令 |
| `policy_control` 强制显示状态栏 | 状态栏存在但游戏全屏，`topInset` 仍读 0 |
| 改 `status_bar_height` 资源 | 无 root（`su: not found`），读不了 `/system/overlay` |

⇒ **改成给 MGAS 加注入开关**（v1.17，这是干净做法，也能进回归）：
- `RefMapper.topInsetPx()`（新公开读取口）+ `DeviceApi.setTopInset(int)` / `topInset()`
- 广播命令 `cmd=set_inset --ei px 132`（进 `DEBUG_ONLY`，只在 debug 包放行；用 `assembleArm64Debug` 测）

**实测（MuMu 1264×2780，注入 132 后）—— 结论：这正是想要的效果**：
```
日志：顶部安全区偏移 = 132px
overlay_dump：k: 1.1704（不变）  顶边(参考 y)=1722（不变）
              blankRect(dev) 上边 = 2548   ← 与真机实测 2548 吻合 ✓
```
算式核对：
| 区域 | 公式 | 注入 132 后 | 是否符合预期 |
|---|---|---|---|
| 体力条 ref 92 | `92*kx+132` | 239.7 | ✅ 顶块整体下移 132 |
| 图名[难度] ref 200 | `200*kx+132` | 366.1 | ✅ |
| 顶块底缘 ref 300 | `300*kx+132` | 483.1 | ✅ |
| **棋盘首行** ref 1002 | `1002*kx+shift` | **1705.6** | ✅ **与 inset 无关，不变** |
| 悬浮条顶边 ref 1722 | `1722*kx+shift` | **2548.3** | ✅ 与实测 2548 吻合 |
| `toRef` 顶块源 | `[inset, inset+300*kx)` | `[132, 483)` | ✅ 顶部黑边被排除 |
| 锚底区源 | `[300*kx+shift, H)` | `[884, 2780)` | ✅ 不变 |

⇒ **顶块随 inset 下移、锚底区完全不受影响** —— 这就是真机同分辨率下的真实行为，
现在**可以在模拟器上验了**（以前只能真机）。
`set_inset --ei px 0` 可恢复自动探测（已验证能恢复）。

#### ⚠ v1.17 实测顺手发现的一个**独立 bug**：悬浮条 bar 尺寸算错

| 分辨率 | kx | 实测 bar(dev) | 折算回参考系 |
|---|---|---|---|
| 720×1280（改之前） | 0.6667 | 640×60 | **960 × 90** ✅ 符合预期 |
| 1264×2780（现在） | 1.1704 | **412×76** | **352 × 65** ✗ 宽度差 2.7 倍 |

- **与 topInset 无关**：注入 132 / 恢复 0，bar 都是 412×76 ⇒ 是另一回事
- 顶边仍 ≥1722（1751/1722 都过），`blankRect` 与 bar 自洽 ⇒ **不影响涂平安全性**
- 但宽度明显算错 ⇒ 像是 `wrap_content` 下文本在窄窗口换行，或 `afterLayout` 自愈改了 `lp.y`
  却没重算 `lp.width`。
- **待查**（别当已修）。⚠ 它只影响控制界面观感，**不影响脚本决策**。

### 6.41 v1.18：修「地图自身任务横幅被当成已开打」＋ ⭐ **模拟器注入点击卡死**的排障手册（2026-10-01 晚）

用户口径：「继续测试 MGAS 项目，全分辨率测试」。在 **1264×2780**（朋友真机 realme RMX3800 分辨率，MuMu 实例「全分辨率测试」）上实跑，一次跑出**两个**问题。

#### ① 现场时间线（1 张图，tag `fullres1264`，可复现）

```
14:27:59 开跑（体力 2100）
14:28:22 已进图，体力 2075                      ← 进图 OK
14:28:48 [r0] 标记格 1｜已揭示 4 / 暗格 24｜规划 8 体力 4 步   ← 棋盘 OK
14:29:00 点 (540,1074) → 弹面板
14:29:08 / 14:29:36 / 14:30:05  连打 4 轮「开打 · 拦路格」，每轮都判"已开打"
14:30:54 [r7] 同一个动作连续 4 轮没变化 ⇒ 强制脱困（拉黑这一格）
14:31:15 用户点 ■ 停止；统计：全部战斗 0 场、消耗 27 体力
```

#### ② 根因 A（**代码 bug，已修**）：`battle_started()` 的宽子串被判据反噬

`explore_loop.py:2475` 旧实现是**子串**匹配：

```python
if ('回合' in t) or ('加速' in t) or ('自动跳过' in t) or t.startswith('第'): return True
if (L['win'] in t) or (L['lose'] in t): return True          # L['win'] = '战斗胜利'
```

而《遗忘之海》地图 HUD **自带两条常驻文案**（进图第 0 帧就有，与脚本打没打过无关）：

| 横幅 | 含义 | 命中的旧判据 |
|---|---|---|
| `★首领战斗不超过8回合` | 完成任务的条件 | `'回合' in t` |
| `首领战斗胜利` + `首领战斗2人存活` | 该任务的**达成状态** | `L['win'] in t` |

⇒ 点完「战斗」再 OCR 一次就**必然**判"已进战斗" ⇒ `wait_end` 空等 20 秒 → `back_in_map`
⇒ 那块格子根本没打 ⇒ 下一轮原样再来（**死循环**）。

**离线铁证**（不依赖设备，回归 ㉘ 组已固化）：拿设备落的诊断帧 `_verify/fr1264_map_boss_banner.png`
（归一化帧 1080×1920）跑一遍旧/新判据：

```
地图帧（应 False）      旧 True ✗ ／ 新 False ✓     命中文本：['首领战斗胜利', '★首领战斗不超过8回合']
结算帧 runs/bw2.json（应 True） 旧 True ✓ ／ 新 True ✓   命中：['战斗胜利','第1/10回合','加速','回放战斗','自动跳过']
```

**修法**（`mapbot_pc/explore_loop.py` → `port_loop.py` → `app/src/main/python/explore_loop.py`）：

```python
_ROUND_RE = re.compile(r'^第\s*\d+\s*(?:[/／]\s*\d+\s*)?回合$')   # 整条，"第1/10回合"/"第3回合"
_BATTLE_STRONG = ('加速', '自动跳过', '回放战斗')                   # 战斗/结算专属控件
_MAP_OBJ_MARK = ('★', '不超过')                                    # 地图任务标记
# ① 胜负标题**整条等值**（"首领战斗胜利" 不算）② 回合**整条正则** ③ 强信号词不得出现在地图文案里
```

⚠ 别把它当"收紧到不认"：真战斗/结算帧的特征词**逐条单测**（回归 ⑧ 组 8 项）全部照旧命中 ✓。

#### ③ 根因 B（**环境问题，比代码更致命**）：MuMu 的「注入式点击」整个死掉

现场先以为"点运行进不去图就停了"，实测把锅分清了：

| 测试 | 结果 |
|---|---|
| `adb shell input keyevent HOME` | ✓ 有效（按键通道正常） |
| `input tap` 打游戏（进入地图/快速扫荡/帮助/公会）、`input swipe`、`motionevent` | ✗ **全部 0 反应** |
| `input tap` 打在 **MGAS 自己 App 的 UI**（悬浮条开关 / 清空日志） | ✗ 关注区帧差 **0.00**（连自己 App 都不响应） |
| 用户用鼠标点悬浮条 ▶ / ■ | ✓ 有效（`[ovl] 点 ▶ ⇒ 开始`） |
| 游戏进程 | 没卡死（39% CPU、画面在动、还在跟服务器对时） |

⇒ **宿主鼠标输入能用，但 adb / 无障碍注入的触摸全被丢掉**。脚本的进图/开打全走无障碍手势 ⇒
`{'enter':'clicked'}` 后面永远跟 `{'enter':'timeout'}` ⇒ 「进不去图就停了」。

**处置（实测有效）**：`"D:/MuMu Player 12/nx_main/mumu-cli.exe" control -v <index> restart`
（本机实例 index **2**「全分辨率测试」，`info -v all` 里带 `adb_port`；重启 17s，**分辨率保持 1264×2780/dpi560**）⇒ 注入点击立刻恢复。

**重启后要重做的授权**（Android 15 三个都要）：
1. **截图**：点 MGAS 的「①授权截图」→ 系统弹「要与"MGAS"共享屏幕吗？」→
   ⚠ 默认是**共享一个应用**（会只截 MGAS 自己 = 没用）⇒ 先点选项行 → 选 **共享整个屏幕** → 「共享屏幕」
2. **无障碍**：`settings put secure enabled_accessibility_services com.fantasy.autoexplore/com.fantasy.autoexplore.AutoTouchService`
   （重启后常仍绑着；没生效就"关掉再写回"强制重绑，`dumpsys accessibility` 里要能看到 `Bound services: … MGAS（点击/滑动）`）
3. **悬浮窗**：一般保留 ✓

**排障口径（写进肌肉记忆）**：`点运行进不去图` 先跑一次**注入点击自检**——
`adb shell input tap <MGAS 自己 UI 的按钮>` 看帧差；**0 反应 = 模拟器注入卡死 ⇒ 重启实例**，
别去改坐标/怀疑分辨率（本次就这么被带偏过一次）。

#### ④ 修复后当场复测（同一实例、同一分辨率）

```
15:30:22 ⚠ 画面无游戏特征（重启后游戏没开）⇒ 自动恢复
15:30:53 ⚙ 登录页 → 点「开始游戏」          ← 注入点击生效 ✓（这一步以前会永远卡住）
15:31:46  已进图，体力 2100→2075            ← 进图成功 ✓
15:32:28  开打 · 格子标志：首领，大拇指       ← 真开打（标记格）
15:33:50  本图结束：done（124 秒）｜统计：刷完 1 张、首领关 1 胜 1、全部战斗 1 胜 1、140 秒/张
```

#### ⑤ 验收数字

- 回归主门禁：**223 → 242 项**（新增 ㉘ 组 19 项：旧判据已删/正则已加/地图帧负样本 4 项/结算帧正样本 2 项/特征词单测 8 项/边界 2 项）⇒ **通过 242 / 失败 0 / 跳过 1**（跳过的仍是 v0.98 颜色认种，与本改动无关）
- 端↔PC：把设备归一化帧（1080×1920）拉回 PC 重跑分类 → 35 格、score 中位 **0.925**（0.645~0.964）⇒ 该分辨率下归一化+分类没问题
- **展开态悬浮条在新分辨率下的实测**：设备 **1120×116**（参考 **957×99**）⇒ 宽度 957≈960 ✓
  （⚠ **修正 v1.17 的那条"bar 尺寸算错"**：那是拿**收起态 412×76** 去比**展开态 960 宽**得出的假警报；
  真差异只在**高度参考 99 vs 设计 84~90** ⇒ 展开时参考顶边 1717，比硬约束 1722 高 5px，
  涂平矩形按 View 实测走、没抹到棋盘，但「顶边 ≥1722」这条在展开态被破 5px，**待查**）

**产物**：`AutoExplore-v1.18-MGAS-修地图横幅假判（battle_started 整条匹配）-release.apk`（= `MGAS.apk`，versionCode **118** / versionName **1.18**）
**新增 fixture**：`_verify/fr1264_map_boss_banner.png`（含首领横幅的地图帧）、`_verify/fr1264_r0_board.png`（进图第 0 帧）

### 6.42 v1.19：⭐⭐ 「全分辨率」到底做了没有 —— 一句话答复 + 修「摇色子搜索带」（2026-10-01 晚）

用户追问：「问题还是多啊。怎么又不摇色子了。。这些问题为什么换个分辨率就又出来了？到底有没有做全分辨率适配」。

#### ① 一句话答复：**棋盘层做了，面板层没做**（这就是"换个分辨率问题又出来"的机制）

| 层 | 全分辨率？ | 证据 |
|---|---|---|
| **参考系 / 归一化**（`RefMapper.toRef/toDlg`，顶块锚顶 + 其余锚底 + `shift`/`C`） | ✅ 真做了 | 1264×2780 上 k=1.1704 / C=227.7 与真机吻合；多分辨率重采样 **35 格逐格全等** |
| **棋盘识别**（模板 + 阈值 + 规划） | ✅ | PC↔端阈值差 0.0000；设备归一化帧回 PC 分类中位 **0.925** |
| **面板层**（弹窗系坐标、搜索带、图标尺度、文字判据） | ❌ **没有** | 都是**逐设备标定**的常数；`C` 一变，弹窗帧与归一化帧的关系跟着变 ⇒ 面板功能**静默不触发**（不报错，日志只写 `no_btn`） |

第二类系统性原因（与分辨率**间接**相关）：**大量判据是子串匹配**。v1.18 修的 `battle_started` 与本节修的骰子带，是同一族病的两个实例。

#### ② 本轮实锤：为什么 1264×2780 上不摇色子

v1.18 那轮日志（设备端 dump）：

```
{'popup': 'fight_panel', 'cell_marks': ['recommend'], 'entry': 'dlg_btn'}
{'battle': 'started', 'at': (804, 733.66), 'marks': ['recommend']}
{'dice': 'initial_check', 'k': 0, 'C': 228, 'best': {'dlg+C': None, 'dlg': None, 'ref': None}}
{'dice': 'initial_check_near', 'top': [('近失', 0.42, 0.397, 464, 1163, 4.4), …]}   ← 阈值 0.70，差 0.28
{'dice': 'no_btn', 'rolls': 0, 'cand': [{'t':'189'…}, {'t':'1','cx':122,'cy':979}]}
{'dice': 'done', 'rolls': 0}
```

取证方式（**不靠猜**）：起一个并发录制（1.0s/张 设备原帧，`_tmpman/fr1264/rec/`，共 215 张），
再用 `scan_rec.py`（帧差找战斗段）→ `ocr_hot.py`（只 OCR 战斗段）逐张读文本。

**真结算帧长这样**（`_verify/fr1264_result_panel.png` 设备原帧，OCR）：

```
战斗胜利  第4/10回合  回放战斗  关闭  自动跳过
1/3  1/16  5/5     133114     220 46 184      ← 奖励行 = 纯图标+数字，没有任何「骰」字
```

**转回参考系 1080×1920 后，两台机器对比**：

| 元素 | PC 9:16 | 真机 1264×2780 | 差 |
|---|---|---|---|
| 奖励行数字 | 907 / 994~1001 | **636 / 752** | **−271** |
| 回放战斗 | 1223 | 1224 | 1 |
| **关闭** | 1440 | **1441** | 1 |
| 自动跳过 | 1563 | 1563 | 0 |

⇒ 面板**底部三键两机完全一致**（锚定模型成立 ✓），**只有奖励行在真机上高 271px**（战斗 UI 纵向压缩）。

而旧代码的两个搜索框**都写死在 9:16 的位置上**：

```python
文字带： it['cx'] < sx(400) and sy(700) <= it['cy'] <= sy(1180)
图标框： box=(40, 840 + C, 1020, 1140 + C)
```

真机奖励行 636~752 ⇒ **完全在 700~1180 之外** ⇒ 文字通道必然空（`no_btn`），
图标三路全 `None`、只剩 0.40「近失」⇒ `rolls=0`，一次都不摇。

#### ③ 修法：搜索框**锚定「关闭」按钮**，不写死绝对 y

```python
REWARD_X1 = 560                  # 骰子/大拇指检测右界（实测图标 x 134~464）
REWARD_CLOSE_UP_MIN = 520        # 奖励行最低
REWARD_CLOSE_UP_MAX = 1020       # 奖励行最高（必须在「回放战斗」上方）

def _reward_box(items=None, c=0):
    y0, y1 = REWARD_CLOSE_UP_MIN, REWARD_CLOSE_UP_MAX
    if items:
        _cl = bottom_close(items)              # ← 锚「关闭」
        if _cl:
            y1 = max(REWARD_CLOSE_UP_MIN, min(REWARD_CLOSE_UP_MAX, int(_cl['cy']) - 260))
    return (20, y0 + c, REWARD_X1 + c, y1 + c)
```

`handle_dice` 的**两处**（文字带 + 三路图标框 + 近失诊断）全部改走它。

⚠⚠ **写这一段时踩的坑（别再犯）**：第一版把上界写成 `min(REWARD_CLOSE_UP_MAX, close-60)`，
而 `MAX=1180 < close-60=1380` ⇒ 永远取 1180 ⇒ **"锚定关闭"完全没生效**，我还以为是自己算错。
凡是有 `min(A, 动态值)` 的 clamp，**必须先确认 A 是不是该方向的天花板**，否则等于没 clamp。
⇒ 现在的顺序是 `min(1020, close-260)`：1020 是天花板（挡住「回放战斗」），close-260 负责跟随。

#### ④ 验收

- 回归主门禁：**242 → 254 项**（新增 ㉙ 组 12 项）⇒ **通过 254 / 失败 0 / 跳过 1**
  ㉙ 组含：真机结算帧 band 收紧断言、**奖励行 6 条数字被覆盖**、**底部三键被排除**、
  **旧写死带"盖不到"这一事实本身**（= bug 根因钉死）、PC 9:16 基线帧仍覆盖（防把基线弄坏）
- 离线对拍 `_tmpman/fr1264/verify_reward_band.py`：真机 band `(20,520,1020)` 覆盖
  `1/3 / 1/16 / 133114 / 220 46 184 / 10 / 1`，排除 `回放战斗 / 关闭 / 自动跳过` ✓
- PC 9:16 band 同值，PC 帧的 `关闭/自动跳过` 同样在带外 ✓

**产物**：`AutoExplore-v1.19-MGAS-摇色子搜索带锚定关闭按钮（修1264x2780不摇）-release.apk`（versionCode **119** / versionName **1.19**）
**新增 fixture**：`_verify/fr1264_result_panel.png`、`_verify/fr1264_result_panel2.png`（1264×2780 设备原帧）

#### ⑤ 遗留（**下一步要做的正事**，别再拖）

- ⏳ **面板层全分辨率自检工具** `tools/verify_panels_allres.py`（尚未写）：
  对 N 个分辨率按锚定模型推导每个面板常数的落点/搜索带，断言 (a) 落点屏内且在面板矩形内
  (b) 搜索带覆盖真机实测坐标 (c) 用各分辨率真帧重放面板判据。
  **目标：换分辨率从此是「跑一遍自检」，而不是实跑撞运气。**
- ⏳ 展开态悬浮条参考高 99 ⇒ 顶边 1717 < 硬约束 1722（差 5px，涂平按实测走没抹棋盘）
- ⏳ 端侧日志噪音：`ResourceWarning: unclosed file server_datatable.json` / `matmul` RuntimeWarning
- ⏳ MGAS 无版本控制（`D:\MGAS\.git` 不存在）—— 本轮所有修改只落在文件里

#### ⑥ 取证工具（都可重复跑）

| 脚本 | 用途 |
|---|---|
| `_tmpman/fr1264/frame_recorder.py` | 1.0s/张 连续抓**设备原帧**（MGAS 自己的 `b.snap()` 只存归一化帧，答不了"设备上在哪"） |
| `_tmpman/fr1264/scan_rec.py` | 帧差找战斗段（>6.0），避免对 200+ 张全 OCR |
| `_tmpman/fr1264/ocr_hot.py` | 只 OCR 战斗段 ±2 帧，标出「真结算/战斗控件/骰子按钮」 |
| `_tmpman/fr1264/dice_geo.py` | 按锚定模型算各元素参考系 y，和现有常量对拍 |
| `_tmpman/fr1264/verify_reward_band.py` | 验收新 band 在真帧/PC 帧上的覆盖与排除 |
| `_tmpman/fr1264/run_and_capture.py` | 一条龙：起录制 + 起 bot + 轮询 + 收帧 + 存日志 |
| `tools/verify_reward_band_allres.py` | ⭐ 常驻回归（主门禁 ㉛ 组）：奖励行 band 双分辨率审计，7 项断言 |
| `tools/fr1264_scan_reward_frames.py` | 在录像里找「真有大拇指奖励」的帧（验收图标通道前的必要一步） |
| `tools/fr1264_dice_verdict.py` | 对比真机近失分 vs PC 正样本真标记分，判 `no_btn` 是不是正确行为 |
| `tools/fr1264_bubble_confound.py` | 定位 `is_battle_panel` 哪条判据触发（⚠ 抓帧伪影排查用） |
| `tools/fr1264_bubble_real_frame.py` | 用 **bot 自己的帧**复核气泡有没有污染 OCR（伪影 vs 真 bug 的分界） |
| `tools/fr1264_scale_mismatch.py` | 同坐标不同分时，扫各尺度定位"真机上画得更小/更大" |

⚠ `run_and_capture.py` 踩过：**`subprocess` 读 logcat 会撞 GBK 解码错误**（`UnicodeDecodeError: 'gbk'`）
⇒ 长任务里统一用 `cmd /c adb … > 文件` 拿原始字节，或给 subprocess 显式 `encoding='utf-8', errors='replace'`。

---

### 6.43 v1.19 复盘：把「离线验收等于没验」补上（2026-10-01 晚 ~ 20:00~21:00）

**起点**：v1.19（§6.42）改了骰子/大拇指搜索带，但当时的**离线验收是无效的**——
用的是 `rec/f0044_0061.6.png`，而那一场是**首领战、奖励行里根本没有大拇指装备**，
所以 `find_reward_mark` 返回空是**正确答案**，等于什么都没验。本节把这件事查到底。

#### ① 三个"卡住验收"的疑问，逐个查清

| 疑问 | 结论 | 证据 |
|---|---|---|
| 全片 215 张真机帧里有没有带大拇指奖励的帧？ | **一张都没有** | `scan_reward_frames.py` 整图扫 `find_reward_mark`（阈值 0.70）全 0 命中 → **素材里没有正样本**，不是代码错 |
| 720×1280 那次 recommend 战斗的 `no_btn` 是不是 bug？ | **是正确行为** | 近失分 0.451/0.411，而 PC 正样本真标记 **0.92/0.92**（`dice_ok_0.png` @ (614,936) 缩放 4.5）；0.41~0.45 落在噪声带（全图放宽到 0.30 扫，2.0~4.9 各尺度最高才 0.43）⇒ **那场本来就没有推荐奖励**（推荐战 ≠ 必有推荐奖励） |
| `is_battle_panel` 在地图帧上误判成结算面板？ | **是抓帧伪影，不是 bug** | `adb exec-out screencap` 的**原始截图绕过 MediaProjection**，悬浮条没被涂平；OCR 把气泡的 `战斗胜利 ✓ · 首领格` 切成 `战斗胜利`+`首领格` 两段，前者**恰好等值**命中严格判据。bot **自己抓的帧**（走 `maskOverlay`）逐张复核 → **0 误判** |

⚠ 第三条值得记：**取证手段会影响结论**。用 `adb screencap` 判"面板层有没有 bug"会得到假阳性；
判游戏画面必须用 bot 自己的帧（`runs/`、`rec/`），或先确认涂平生效。

#### ② 补上的回归：`tools/verify_reward_band_allres.py`（已接进主门禁 ㉛ 组）

把上面这些从"一次性脚本"变成**常驻断言**（7 项）：

- ⓐ 真机 1264×2780 奖励行**左半区**被 band 覆盖（`1/3 / 1/16 / 133114 / 220 46 184 / 10 / 1`）
- ⓑ 面板底部三键 `回放战斗/关闭/自动跳过` **不**落进 band
- ⓒ **旧写死 box 确实盖不全**（真机 7 条里 5 条完全盖不到）= v1.19 修的是真 bug，钉死
- ⓓ 新 box 覆盖左半区**全部**条目（防"为了不误伤而漏掉"）
- ⓔ PC 9:16 基准帧 `runs/bw2.json` **不过度收紧**（正负同时成立）
- ⓕ 徽章阈值 `0.70/0.70` + 尺度带 `4.1~4.9` 未被动过（真标记 0.92@4.5 不能被拒）

**主门禁：263 → 270 项，通过 270 / 失败 0 / 跳过 1**（跳过那 1 项是 `v0.98 ③ 颜色认种`，
fixture 帧里没有草/果，与本轮无关）。

⚠ **别把 `REWARD_X1=560` 的 x 界当成 bug 改宽**：真机实测 `5/5` 在参考 x=611，
它在**右半区、是属性数字不是骰子**；骰子/大拇指恒在左半区（实测 x 134~464）。
断言只覆盖左半区就是设计意图，不是覆盖不全。

#### ③ 两个分辨率都跑过的实况（MuMu 双实例）

| 实例 | 分辨率 | k | 面板判据 | band | 悬浮条顶边(参考 y) |
|---|---|---|---|---|---|
| `127.0.0.1:16448` | 1264×2780 | 1.1704 | ✓ 正常 | ✓ 覆盖 | **1722** ✓ |
| `127.0.0.1:7555` | 720×1280 | 0.6667 | ✓ 正常 | ✓ 覆盖 | **1727** ✓ |

§6.42⑤ 遗留的「展开态顶边 1717 < 1722」**已不复现**（两处实测都 ≥1722），可从遗留清单划掉。
本轮 `127.0.0.1:16448` 中途掉线（`MuMu` 端口别名失效，7555 是同一实例），
之后全部取证改在 7555 上做。

#### ④ 遗留清单更新

- ✅ `tools/verify_panels_allres.py`（§6.42 遗留①）**已存在并接进门禁 ㉚ 组**
- ✅ 悬浮条顶边 1717 < 1722 —— **不复现**，划掉
- ✅ v1.19 搜索带的离线验收缺口 —— **本节补上**（㉛ 组）
- ⏳ 端侧日志噪音：`ResourceWarning: unclosed file server_datatable.json` / `matmul` RuntimeWarning
- ✅ **PC 端已有独立版本控制**（2026-10-01 建仓 `mapbot_pc/`，11366 文件 / 25.4MB）——
  本节此前记的「PC 端无版本控制兜底」**已解决**
- ⏳ 仍缺「**真机大拇指奖励帧**」这个正样本 fixture：图标通道的**端到端**验收
  （真机上真找到标记并摇到色子）只能等实跑撞上，一旦撞上立刻
  `adb pull` 存进 `_verify/` 并在 `verify_reward_band_allres.py` 里加一条正样本断言

---

### 6.44 ⭐⭐ 两端正式分开（2026-10-01 晚 ~21:00）

**决定**（用户）：PC 端与手机端**正式分开**，并且是**平行独立开发**（不是"上游源 + 下游生成物"）。

#### ① 三个决定各自的后果

| 决定 | 做了什么 | 带来的影响 |
|---|---|---|
| PC 端建独立 git 仓 | `mapbot_pc/` 从零 `git init`，11366 文件 / 25.4MB 入仓 | PC 端第一次有回滚能力；`runs/`(1.2GB)/`_archive/` 不入仓 |
| 601 个 `_*.py` 归档不删 | 移到 `_archive/`（反编译参考另放 `_archive/反编译参考/`） | 根目录 793 → 192 文件，可读性大幅改善 |
| **两端平行独立开发** | `port_*.py` 从「强制同步步骤」降级为「**可选搬运工具**」 | **本节 ② 是重点**：不能再把手机端代码当成生成物看待 |

#### ② 因为"平行独立"，必须改掉的三处认知（否则以后一定踩）

1. **`app/src/main/python/*.py` 是手机端自己的源码**，不是"每次改 PC 都必须重放"的生成物。
   手机端改完**不需要**回头动 PC。
2. **两个 `port_*.py` 是覆盖式写入、没有合并** —— 这次给它们都加了守卫
   （`_guard_overwrite()`）：手机端对应文件有**未提交改动**时**直接中止**并提示，
   避免静默冲掉手机端已分叉的代码。
3. **两端逻辑漂移是合法的**。判据是**各自的行为**（门禁全绿 + 实跑正常），
   **不是**"两边源码一致"。以后 review 时看到 `mapbot_pc/explore_loop.py` 和
   `app/src/main/python/explore_loop.py` 有 diff，**不必当成 bug**。

#### ③ 顺手记下的一个 git 坑（`mapbot_pc` 建仓时踩的）

`.gitignore` **不支持行尾注释**。写成

```gitignore
runs/        # 每轮跑出来的帧，~1.2GB     ← ❌ 整行（含 #）被当字面模式，永不匹配
```

结果是 `runs/` 11172 个文件、1.2GB 全被 `git add` 进去，`.gitignore` 形同虚设。
⇒ **每条规则必须独占一行，注释另起一行**（已写进 `mapbot_pc/.gitignore` 头部警示）。
排查手法：`git check-ignore -v <真实文件路径>`（要用**文件路径**，用目录名测会误判）。

#### ④ 两边的版本控制现状

| 端 | 路径 | 仓 | 规模 |
|---|---|---|---|
| PC | `D:\MGAS\mapbot_pc\` | 独立仓（`master`） | 11366 文件 / 25.4MB |
| 手机 | `D:\MGAS\android_autoexplore\` | `gitee.com/geng-haojie/MGAS.git` | — |
| 顶层 `D:\MGAS\` | — | **不在 git 里**（只是这两个仓的容器目录） | — |

---

### 6.45 ⭐⭐ 手机端与 PC 端**完全平行**（各自自洽，不需要对方在场）

用户 2026-10-01 定：「**现在手机和电脑完全平行**」。
含义不是「分了两个目录」，而是：**各自能独立 clone、独立开发、独立跑门禁**。

#### ① 已实证（把对方目录改名后跑自己的门禁）

| 场景 | PC 门禁 | 手机端门禁 |
|---|---|---|
| **两仓都在** | `13/0/0` ✅ | `286/0/1` ✅ |
| **手机端仓隐藏** | `13/0/0` ✅ | — |
| **PC 仓隐藏** | — | `285/0/2` ✅（跳过的 2 项在摘要里写明原因） |

#### ② 拆掉的 5 处交叉依赖（都是「以前觉得天经地义、其实是自己加的锁」）

1. **门禁 import 的是 PC 的 `explore_loop`** ⇒ 改成本仓的
   `app/src/main/python/explore_loop.py`（**APK 里跑的那一份**，验的才是真家伙）。
2. **`port_android.py`/`port_loop.py` 找不到 PC 源就 `raise SystemExit`**
   ⇒ 任何 `import` 它们的工具（包括门禁）会直接崩 ⇒ 改成**只警告不崩**
   （它们只是可选搬运工具，不是构建/测试前置条件）。
3. **基准帧 `runs/bw2.json` 从 PC 仓读**（而那个目录还被 gitignore 了）
   ⇒ 随本仓入库为 `_verify/bw2_pc_result_panel.json`。
4. **资源根指错**：`app/src/main/python/templates` 是**空目录**（历史遗留），
   模板真身在 `assets/mapbot_pack/templates` ⇒ 全部要模板的用例
   `FileNotFoundError`（"地块分类失败"）。已改成**数文件**再决定，
   不能只看目录存在。
5. **17 处路径写成 `<MGAS>/android_autoexplore/...`** ⇒ 改成仓内相对（`PROJ`），
   **换个目录 clone 也不会找不到文件**。

#### ③ 顺带修掉一个**真 bug**（不是为拆依赖，是拆依赖时才暴露的）

门禁改用本仓源码后，暴露手机端 `mapbot.py` 的 `wait_change`/`wait_stable`
**把整段时长一次性阻塞在 Kotlin 里** ⇒ Python 侧**根本没机会**看停止位
⇒ 用户报「点 ■ 后还要运行一会」（PC 端 v0.98 早已修：轮询里问 `_stop_flag()`）。
⇒ 手机端改成**切片调用**（`SLICE=0.30s`，每片之间问一次停止位），
停止延迟最坏 0.3s。**这是拆依赖时抓出来的真问题，不是顺手改的。**

#### ④ 门禁 ⑩ 的语义随「平行」改了

以前查「生成物必须与 PC 逐字节一致」（强制同步时代的产物）⇒ 现在查
「**漂移是否已登记**」；**PC 仓不在时整组跳过**（不是失败）——
两端既然平行，「没装对方」是**正常状态**。

#### ⑤ 可选：想用 PC 端做对拍

```powershell
$env:MGAS_PC_SRC = 'D:\MGAS\mapbot_pc'      # 可选，默认不需要
& $py tools\verify_explore_slots_fix.py
```

---

### 6.45 ⭐⭐ v1.20：面板层「全分辨率」补齐（2026-10-02）

**起因**：用户「手机端追求全分辨率适应，稳定」。§6.42 的结论是**棋盘层做了、面板层没做**，
而这一节就是把那半边补上，并把「换分辨率」从**实跑撞运气**变成**跑一遍自检**。

#### ① 先修一个更严重的问题：自检验的根本不是手机端代码

`tools/verify_panels_allres.py` 原来 `import` 的是 **PC 仓** 的 `explore_loop`
（`MGAS_MAPBOT_SRC` / `<MGAS>\mapbot_pc`）。但 §6.44 之后两端已「平行独立开发」，
实测两端源码差异：

| 模块 | 与 PC 的 diff 行数 |
|---|---|
| `buypanels.py` | **2232** |
| `mapbot.py` | **1012** |
| `explore_loop.py` | 125 |

⇒ **自检跑的是 PC 那份，手机端面板层改了什么它一概看不见** —— 门禁是绿的，端上照样失准。

**修法**：改为 import **手机端自己的** `app/src/main/python/explore_loop`
（端上 shim 在 PC 上可独立 import：`_MAPBOT_ANDROID=False` 走 PC 回退，已用探针验证），
并在文件顶部加 `assert os.path.abspath(EL.__file__).startswith(PYD)` —— 防止以后被改回去。
PC 仓退化为只提供 `runs/bw2.json`（9:16 基准帧）。

#### ② 核心：**漏检防呆**（新增 `tools/panel_consts.py`）

`verify_panels_allres.py` 的覆盖度**完全取决于一张手工维护的 `PANEL_CONSTS` 清单**，
而工具自己在结尾就承认过：

> ⚠ 但这只覆盖**已列入清单**的常数；新面板必须同时登记进 `PANEL_CONSTS`，否则等于没测

「必须手工登记」而**漏登记没人会发现** ⇒ 这就是「面板层没做全分辨率」的**机制性根因**。

**做法**：用 **AST**（不是正则 —— 正则会把 docstring/注释里的示例坐标当代码，那类误报 v1.19 踩过）
扫手机端所有模块级坐标常数，与清单求**差集**，**差集非空即红**。

**第一次运行就抓出 8 项从未被验证的东西**，分类后：

| 抓到的东西 | 判定 |
|---|---|
| `BAG_FILTER_DLG (199,1758)` | **真坐标**（背包弹窗系筛选钮）⇒ 登记 |
| `_AUTO_SKIP_BOX (465,1559)` | **真坐标**（结算面板「自动跳过」勾选框）⇒ 登记 |
| `_BAG_TPL_SCALES` | 多尺度比例（非坐标，但会失准）⇒ 登记 |
| `STATS` / `_OCR_CH` / `_COLLECT` / `_GRID_CALIBRATED` / `_AUTO_SKIP` | 运行时状态字典，**非坐标** ⇒ 进 `EXEMPT` 且**必须写理由** |

⇒ 常量清单从 11 项扩到 **34 项**，且**从今往后漏登记会当场红**。

**守门本身也要验**（否则等于写了个不会红的检查）：往 `buypanels.py` 注入
`_TEST_NEW_PANEL_CONST = (123,456)` ⇒ 扫描器立刻报「未登记」并 exit≠0；移除后恢复绿。

#### ③ 修一个真 bug：宝库/商人搜索带在宽屏盖不住购买钮

`buypanels.BAND = (300, 1560)` 是**归一化帧**的 OCR 搜索带。面板内容**锚设备屏幕中心**
⇒ 同一元素在归一化系里的位置 = `dlg_y − C`，而
`C = 960 + (shift − H/2)/kx` **随分辨率变**（9:16 ⇒ 0，真机 1264×2780 ⇒ 227.7）。

9 个分辨率实测（判据元素，弹窗系 → 归一化系）：

| 判据元素 | dlg_y | 9:16 基线 | 20:9 | **5:4 宽(1200×1920)** | 真机 Redmi |
|---|---|---|---|---|---|
| 购买钮 | 1498 | 1498✓ | 1258✓ | **1594 ✗** | 1289✓ |
| 价格 | 1541 | 1541✓ | 1301✓ | **1637 ✗** | 1332✓ |
| 返回.兜底上界 | 1520 | 1520✓ | 1280✓ | **1616 ✗** | 1311✓ |

**C < 0（宽屏矮胖，H < 1920·kx）时元素下移** ⇒ 旧上界 1560 盖不住 ⇒ `_btn` 恒返回
`(None,None,None)` ⇒ `no_select_btn` ⇒ **整层不买不选**，而且**不报错**（同 v1.19 族）。

**修法**：上界 `1560 → 1720`（锚定模型推导 + 83px 余量给文案行数浮动），
下界 300 不动（再往上是被 `toRef` 丢弃的弹性区，取不到）。
⚠ PC 上 C 恒 0 ⇒ **对 PC 行为零影响**（只放宽不收紧）。

**新增** `tools/verify_panel_band_allres.py`：9 分辨率 × 6 判据元素，含一条
**「旧上界 1560 确实盖不住宽屏」**的断言 —— 把「修的是真 bug」这件事钉死，防改回去。

#### ④ 顺手修：端侧日志噪音的**根因**，不是掩盖

| 噪音 | 根因 | 处置 |
|---|---|---|
| `ResourceWarning: unclosed file server_datatable.json` | `json.load(open(path))` 靠 GC 回收（`mapgen.load_tables` / `spots.map_table` / `spots.spot_rows` / `spots.verify_cmd`） | 改成 `with` 块，**从源头修掉** |
| `RuntimeWarning: ... matmul` | ONNX int32 归一化除法的标准警告 | `explore_android` 里**按 message 窄过滤** |

⚠ **绝不用 `filterwarnings('ignore')`** —— 那会把真警告一起吞掉
（「缺数据被当成通过」的同族问题：把信号静音等于把问题静音）。

#### ⑤ 顺带修一个门禁自身的**假失败**（重要）

跑全量门禁时 `fixed.py` 自检 4 项红。但直接跑 `fixed.py` 是 **exit 0、完全正常**。
根因：门禁用 `subprocess` 跑它时**没传 UTF-8 环境**，`fixed.py` 打印 `'✓'`
在 GBK 控制台抛 `UnicodeEncodeError` ⇒ exit≠0。

⇒ 这正是《错误教训》B2「**回归红了先分清是代码错还是环境错**」的一个新实例，
而根因在**门禁 harness**、不在被测代码。修法：新增 `_ENV()` 统一给**所有**子进程
传 `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`。

#### ⑥ 验收

- **主门禁 270 → 295 项，通过 295 / 失败 0 / 跳过 1**（跳过仍是 `v0.98 ③ 颜色认种`，
  fixture 帧里没有草/果 —— 按 B5② 的规矩显式 skip + 计数，不当通过）
- 四个自检**单独跑全部 exit 0**：`verify_panels_allres` / `panel_consts` /
  `verify_panel_band_allres` / `verify_reward_band_allres`
- 新增门禁组：㉜ 漏检防呆（7 项）、㉝ 面板搜索带 9 分辨率（6 项）

#### ⑦ 遗留（下一步）

- ⏳ **真机复验**：本轮改动（尤其 BAND 放宽）只过了**离线门禁**。按《错误教训》B3
  「离线推理必须真机复验」，BAND 放宽需要在**真机**上跑一局宝库确认没有多 OCR 到导航条
  —— 等用户安排（当前无 MuMu/真机在线）
- ⏳ 仍缺「**真机大拇指奖励帧**」正样本 fixture（§6.43 遗留，图标通道端到端验收）
- ⏳ 端侧 OCR 2.4s/次仍是循环耗时大头
- ⏳ M5 剩余（崩溃恢复/热管理）、M6 多机回归矩阵

### 6.46 ⭐ v1.21：又一台真机「面板挡住了棋盘」误判（nubia NX809J 1216×2688）（2026-10-02）

**起因**：桌面反馈夹来了新包 `MGAS反馈_20261002_003748.zip`
（机型 **nubia NX809J / Android 16 / 1216×2688 / v1.20**，`last_summary` 里那一局刷完 6 张图、
9 战 9 胜）。包里带着 `board_hidden_r2.png` —— 那是**判「被挡」时才存**的诊断帧，
说明这一局里 `board_hidden()` 又误报了一次。

#### ① 先把「到底是不是误判」钉死

用本仓 `tools/fb_probe_20261001.py` 把那一帧离线跑一遍（35 格全识别、score 0.9+）：

| 判据 | 数值 | 结论 |
|---|---|---|
| 棋盘区几何 | 棋盘 `y 1002~1722`；涂平压条 `y 1722~1819`（**正好从棋盘下沿开始**）⇒ 一格都没盖到 | 无遮挡 ✓ |
| 「结束冒险」面板 | `y 560~1030`，在棋盘**上方** | 不盖棋盘 ✓ |
| 已揭示格 | 8 格，ratio 0.867~1.196（中位 **1.058**，营地/海边小屋清清楚楚） | 画面正常 ✓ |
| 雾格 | 0.573~0.724（中位 **0.650**） | 就是普通雾格 ✓ |
| 旧 `board_hidden()` | **True** ✗ | **误判** |

⇒ 这是**第二次**同类翻车（第一次是 §6.36 的 realme RMX3800），而且 v1.11 的修法**没盖住它**。

#### ② 根因：判据②的基准取「本帧**最亮**格」，会被单格过亮抬到雾格之上

```python
_mx  = max(ratio)          # ← v1.11~v1.20 的基准
_thr = 0.55 * _mx          # ← 阈值跟着最亮格走
被压暗 = (ratio < _thr) 的格数 >= 15
```

该帧最亮那一格是「海边小屋」**1.196**（比模板本身还亮）⇒ `_thr = 0.55×1.196 = 0.658`，
而**雾格恒在 0.650** ⇒ 18 格被判"被压暗" ⇒ 触发判据② ✗。

v1.11 的注释自己写过「未揭示格恒 ~0.65 ⇒ 0.55 这个阈值不会误伤普通暗格」——
**那句话只在 `_mx ≤ 1.18` 时成立**；`_mx` 由单格决定，跨过 1.18 就整盘翻车。
「刚进图/大半盘还是雾」的帧最容易踩到（雾格最多）。

#### ③ 用两帧真机 + 历史基准**量**出阈值该放哪

写了个标定脚本 `tools/fb_calib_boardhidden.py`（把仓里所有棋盘帧都跑一遍 ratio 分布）：

| 帧 | 已揭示格 ratio（中位） | 雾格 ratio（中位） | **雾格/已揭示** | 旧阈值 | 旧判定 |
|---|---|---|---|---|---|
| nubia NX809J 1216×2688（本次反馈） | 0.867~1.196（**1.058**） | 0.573~0.724（**0.650**） | **0.61** | 0.658 | ✗ 误判 |
| realme RMX3800 1264×2780（§6.36 那次） | 0.777~0.849（**0.849**） | 0.361~0.425（**0.413**） | **0.487** | 0.467 | ✗ 误判 |
| 真·面板盖住棋盘（doc `m0_r008`） | ~1.0 | — | — | — | ✓ 该判 |

⇒ **雾格/已揭示 = 0.49~0.61**，**真面板/已揭示 = 0.25~0.35** ⇒ 两者之间只有一条窄缝，
阈值取缝中点 **0.42**（两侧余量 16% / 17%）。

#### ④ 修法（**只收窄、不放松**）

```python
_lit = [ratio for 每格 if ratio >= 0.75]        # = spots.py 的 revealed 口径（同源 ✓）
_ref = median(_lit) if _lit else _mx            # ← 基准改成"已揭示格的**中位**亮度"
_thr = 0.42 * _ref
被压暗 = (ratio < _thr) 的格数 >= 15
```

- 中位数对**单个过亮格免疫**（1.196 那种抬不动 8 格的中位）✓
- 判据①（全盘无亮格 且 最亮格 <0.40）与「≥15 格」**原样不动** ⇒ 真·全盘遮罩照样抓到 ✓
- 常量一律具名（`REVEAL_RATIO_MIN` / `DIM_RATIO_MAX`）+ 写清"按实测标定，别凭感觉调"

#### ⑤ 验证（执行级，直接调真 `board_hidden`）

新增门禁组 **㉞ v1.21（8 项）**：

| 用例 | 期望 | 旧实现 | 新实现 |
|---|---|---|---|
| 正常盘（雾29+亮6） | 不判被挡 | ✓ | ✓ |
| 暗设备 k=0.7 / 0.5 | 不判被挡 | ✓ | ✓ |
| **雾格盘 + 过亮格 1.196（nubia 形态）** | **不判被挡** | **✗ 判被挡** | ✓ |
| 雾格盘 + 过亮格 + 真面板 | 判被挡 | ✓ | ✓ |
| 面板盖中间（只露 3 格） | 判被挡（不许回归） | ✓ | ✓ |
| 全盘被遮罩 | 判被挡 | ✓ | ✓ |
| **真机帧** nubia / realme（归一化 1080×1920） | 判 **False** | ✗ 判 True | ✓ |
| **真机帧** `dlg16.png`（真·全盘遮罩） | 判 **True**（不许放松） | ✓ | ✓ |

- 两帧真机反馈帧已收进仓当 fixture：
  `_verify/phone_friend_nubia_nx809j/board_hidden_r2.png`（＋ device.txt / mgas_log.txt）
  `_verify/phone_friend_rmx3800/board_hidden_r0.png`（＋ 原有 device.txt）
- 顺带离线复核：仓里 `_verify/phone_stamina_0930/bagdbg/iron_highland_fog_dev.png`
  （铁血高地雾格真机帧，棋盘全在）旧判据也判「被挡」⇒ 新判据判 False ✓
  ⚠ 那是**原始设备帧**（1280×2772 非归一化）⇒ 只当旁证，**没**进执行级门禁

#### ⑥ 顺带把一条**遗留红**修绿：两端漂移登记漏了 `layout`

门禁 ⑩（两端源码漂移登记）上一轮是**红的**：`未登记: layout`。
查明原因：PC 端 2026-10-02 把自己**参考分辨率**从 1080×1920 换成 **720×1280**
（PC 提速层前提，`AGENTS.md` §1b），而手机端是**归一化 1080×1920 参考系**
（RefMapper 两段拼接，`GRID=36/1002/144` 与 APK 里那份源码绑死）⇒ **手机端不能跟**。
⇒ 按门禁自己的规矩把 `layout` 登记进 `_ALLOWED_DRIFT` 并写清理由（**有意分叉，勿覆盖**）✓

#### ⑦ 验收

- **主门禁 285 → 295 项，通过 295 / 失败 0 / 跳过 1**（跳过仍是 `v0.98 ③ 颜色认种`）
- 四个自检**单独跑全部 exit 0**：`verify_panels_allres` / `panel_consts` /
  `verify_panel_band_allres` / `verify_reward_band_allres`
- 版本号 `versionCode 121` / `versionName 1.21`
  （⚠ 顺手把上一轮**没提交**的 120 一起带上了：HEAD 里还是 119 —— 见 §6.36 那类"APK 版本
  与 git 不一致"的老坑）
- **产物**：`AutoExplore-v1.21-MGAS-修nubia新机型「面板挡住棋盘」误判（判据基准改已揭示格中位）-release.apk`
  （= `app/build/outputs/apk/arm64/release/app-arm64-release.apk`，74.3 MB，md5 `618d0470…`）
  ⚠ 装机后**仍需重新授权「① 授权截图」**（MediaProjection 的老规矩）
- 已核对 **APK 里真的是新代码**：`assets/chaquopy/app.imy` 292437 → **293832**
  （与 v1.20 那个包逐字节不同，sha256 不同）⇒ 不是"构建缓存没生效"的空包

#### ⑧ 遗留（下一步）

- ⏳ **真机复验**：本修法只过了「两帧真机反馈帧 + 合成用例」的离线门禁。
  §6.36 那台 realme 的雾格/已揭示只有 **0.487**（离阈值 0.42 只剩 16% 余量）
  ⇒ 需要一台**同款偏暗机型**实跑一局确认不再误判（当前无真机在线）
- ⏳ **同族嫌疑**：`_board_dimmed()` 用的是**绝对** `ratio ≥ 0.85`。
  realme 那帧**一格都没到 0.85**（最高 0.849）⇒ 它在 rnd==0 会恒判"暗罩"、
  白等 2×2 秒（**fail-open，不致命**，但那是同一个"绝对阈值 + 偏暗设备"的病根）
  ⇒ 要不要一起改，等真机复验后定
- ⏳ 反馈包里那局的 `棋盘识别 31.5s/29 次`（≈1.1s/次）仍是端上耗时大头

### 6.47 ⭐ v1.22：`不使用幸运草` / `进不去图` 两个包 —— **先补证据链**，再谈修（2026-10-02）

**用户把反馈包按症状改了名**，两个包都是 v1.20、都是 nubia：

| 包 | 机型 | 症状（用户命名） | 那包里的硬数据 |
|---|---|---|---|
| `不使用幸运草.zip` | nubia NX809J 1216×2688 | 遇见大拇指格子**不使用幸运草** | `大拇指装备 0 件（推荐战 2 场 / 胜 2；摇色子拿到 0）` |
| `进不去图.zip` | nubia NX729J 1116×2480 | 图推不动 | `no_plan` → `blank_board ×2` → `targets_done(gray_left 29)`；0 战斗、0 张图 |

#### ① 先说清楚：这一包**无法自证**（而这本身就是个 bug）

`不使用幸运草` 那包的 `mgas_log.txt` 只剩 5 条（`recover` / `stop` / `map`）——
那局的日志被**后一次运行覆盖**了。所以"到底没摇，还是摇了 3 次没中"**判不出来**。

追下去发现根因在代码里：摇色子的判据原来埋在 `wait_end()` 里，
**不满足条件时一个字都不记** ✗

```python
if not diced and 'recommend' in list(marks):
    if result_streak < 2:
        ... 复核一帧 ...
    if result_streak >= 2:      # ← 只有走到这里才有 handle_dice 的日志
        handle_dice(...)        #    走不到 = 全程静默 ⇒ 反馈包永远证明不了 ✗✗
```

⇒ **判据静默 = 反馈包聋哑**。这与 v1.11 给 `board_hidden` 加诊断帧是同一族问题，
只是这次漏在**日志**上。

#### ② 修法（三条，都只加证据/兜底，不动已修好的判定）

1. **判据抽成纯函数** `dice_gate(marks, exact, win_streak, result_streak, on_result, diced)`
   ⇒ 返回 `('roll', 原因)` / `(None, 原因)`，**离线可对拍**（门禁 ㉟⑥ 跑 7 种情形 ✓）
2. **无论摇不摇都留一条日志**：`{'dice_skip': 原因, win, on_result, result_streak,
   win_streak, marks, exact, texts:[面板前 24 条文本]}` ⇒ 下一包一眼定论 ✓
3. **兜底 `win_only`**：连读两帧「战斗胜利」、但本机 OCR 读不到结算面板的
   【正面】/【负面】/「关闭」（`on_result` 恒 False）⇒ **也去试摇一次**。
   安全性：`handle_dice()` 在非结算面板上只会记 `{'dice':'no_btn'}` 就返回
   （它的骰子按钮判据要求文字含 `骰/重投/命运/重掷/掷`，地图 UI 里没有这些字 ✓）

#### ③ 顺带抓到两个包**共同的可疑点**：标记"近失"（很可能就是同一个根因）

给"整帧扫不到标记"加了诊断（`marks.probe_top()`：**每个模板各自最好那处**的裸分，
不设闸门）——拿两个包的真机帧一跑：

| 帧 | `scan_board()` | 最好的候选（形状/配色） | 该类型闸门 | 判定 |
|---|---|---|---|---|
| NX729J（`进不去图`） | **空** | `boss` **0.741/0.841** @格(2,4) | 0.90 / 0.85 | 近失 ✗ |
| NX809J（`不使用幸运草`） | **空** | `clover_live` 0.916/**0.584** @(3,1) | 0.90 / 0.75 | 近失 ✗ |
| MuMu（对照，好帧） | `3,1: boss` | `boss` 0.934/0.896 @(3,1) | 0.90 / 0.85 | 命中 ✓ |
| 1264×2780（对照） | `5,5: boss` | `boss` 0.952/0.921 @(5,5) | 0.90 / 0.85 | 命中 ✓ |

- 两帧**肉眼都看得见格子上的标记图标**（NX729J 那枚就在 (2,4)，截图存档见
  `_verify/phone_friend_nubia_nx729j/`），但代码扫不到；
- 压到闸门之下的是**配色分**（NCC）：机身偏暗/偏色把逐通道相关性拉低
  （0.841 vs 要求 0.85 —— 只差 0.009）；
- 后果正好对上两个症状：**扫不到 boss ⇒ 没有目标 ⇒ `no_plan`/`blank_board`/提前退图**；
  **扫不到 recommend ⇒ 那一格压根不被当成大拇指格 ⇒ 永不摇色子/不用幸运草** ✗

⚠ **本版不动任何阈值**：那条闸门是 2026-09-26「boss↔红装串味 / 每张图都误报幸运草」
踩出来的，松它要**单独标定 + 真机复验**（`SHAPE_MIN/COLOR_MIN/TYPE_MIN` 一改，
误报会立刻回来）。所以本版只做两件事：**把近失钉成 fixture + 记录在案**
（门禁 ㉟⑧⑨：`probe_top` 必须报出那条近失；同时把"这帧扫不到"这个**现状**也钉住 ——
哪天标定修好，⑨ 会红，提醒把它改成"必须扫到" ✓）。

#### ④ 验收

- **主门禁 295 → 307 项，通过 307 / 失败 0 / 跳过 1**（新增 ㉟ v1.22 九项）
- 四个自检**单独跑全部 exit 0**
- 顺带把**漂移登记**补全（PC 端换 720p 基准带出的 `spots` / `grid_detect`，加手机侧的
  `marks.probe_top`）—— 三项都是**有意分叉**，理由写进 `_ALLOWED_DRIFT`
- **产物**：`AutoExplore-v1.22-MGAS-摇色子补证据链（dice_skip日志+win_only兜底）+标记近失诊断-release.apk`
  （版本 `versionCode 122` / `versionName 1.22`；74.3 MB，md5 `02fdea21…`；
  `assets/chaquopy/app.imy` 293832 → **296247** ⇒ 打进去的确实是新代码 ✓）
  ⚠ 装机后**仍需重新授权「① 授权截图」**（MediaProjection 老规矩）

#### ⑤ 下一步（**下一包就能定论**）

- ⏳ **真机复验（最高优先）**：装上 v1.22 再复现一次，反馈包里会直接出现
  `{'dice_skip': ...}`（说明**为什么没摇**）或 `{'dice': 'no_btn'/'abort_no_confirm'}`（摇了没成）
  —— 这条不用猜，日志自己会说 ✓
- ⏳ **标记闸门标定**（`marks.SHAPE_MIN/COLOR_MIN/TYPE_MIN`）：需要一批"偏暗/偏色机型"的
  **正样本真机帧**（带标记的）+ 负样本（无标记）一起标，别只在两帧上松阈值；
  正样本现在是 `_verify/phone_friend_nubia_nx729j/`（boss 近失）等 ✓
- ⏳ `进不去图` 的 `no_plan`/`blank_board` 通路：本次只确认"标记扫不到会直接导致它"，
  没有独立的第二根因证据 ⇒ 等标记那条结论定了再看
- ✅ **已由 §6.48 定论**（v1.22 的证据链当天就抓到了真根因 ⇒ 见下一节）

### 6.48 ⭐⭐⭐ v1.23：**真机实跑抓到「遇见大拇指格不摇色子」的真根因**（2026-10-02）

v1.22 的证据链当场就派上用场了：装到用户手机（Redmi 1280×2772）跑了一把，
**有大拇指格、没摇色子** —— 而且这回日志把链路记得清清楚楚。

#### ① 真机日志（`_tmpman/live_122.log`，v1.22 实跑）

```
r0  marks = {'4,4': ['boss'], '1,6': ['recommend']}      ← 标记识别完全正常 ✓
r0  {'popup': 'fight_panel', 'cell_marks': ['boss'],  'entry': 'dlg_btn'}
r0  {'battle': 'no_battle_in_5s', ...} / {'battle': 'not_started'} / {'battle': 'blocked'}
r2  {'popup': 'result_panel', ... '关闭' (577,1440) ...} → {'popup': 'result_closed'}
r3  {'popup': 'fight_panel', 'cell_marks': ['recommend'], 'entry': 'dlg_btn'}   ← 大拇指格 (1,6)
r3  {'battle': 'no_battle_in_5s'} / {'not_started'} / {'blocked'}
r4  {'popup': 'result_panel', ...} → {'popup': 'result_closed'}   ← **一条 dice 日志都没有** ✗
r6  {'marks_dropped_panel': '1,6', 'marks': ['recommend']} → targets_done(gray_left 21) → 退图
```

#### ② 根因：**结算面板走了另一条路，而那条路上没有摇色子**

- `handle_dice()` 只挂在 **`wait_end()`** 里（点「战斗」后等结算那条路）；
- 真机上点完「战斗」到**真正开打 >5 秒**（`no_battle_in_5s`）⇒ `wait_end` 先放弃了；
- 战斗照样打完 ⇒ **下一轮**才看到结算面板 ⇒ 被 **`popups()` 的 `result_panel` 分支**接走，
  而那个分支**只关面板、从不摇色子**（作者当年只在注释里写了"供实现摇色子用"，
  实现没跟上 ✗）
- ⇒ **大拇指标记白丢、一次幸运草都没花** = 用户报的「遇见大拇指格子不使用幸运草」✗✗

⚠ 顺带澄清：这一台**标记识别是好的**（`boss`/`recommend` 都扫到了）——
§6.47 那条"标记近失"是**另一台 nubia** 的问题，两个都要修，但不是一个病。

#### ③ 修法

1. **`popups()` 的结算面板分支：落在大拇指格上 ⇒ 先摇色子再关**
   （摇色子按钮就在这块面板上；`near()` 提到分支之前，只认**本格**标记 ⇒ 防邻格白摇 ✓）
2. **跨路径防重复**：`st['diced_rc']` 记"这一格已摇过"，`wait_end` 也带格号入参
   ⇒ 同一格的结算面板不会被两条路径各摇一次（每次重投都要花 1 个幸运草 ✗）

#### ④ 验收

- **主门禁 307 → 314 项，通过 314 / 失败 0 / 跳过 1**（新增 ㊱ v1.23 七项）
- 其中 ⑤⑥⑦ 是**执行级**：用假 bot 直接调真 `popups()` ——
  - 大拇指格的结算面板 ⇒ 日志出 `{'popup': 'result_dice', ...}` 且真的进了 `handle_dice` ✓
  - 摇完**仍然把面板关掉**（点 (577,1440)）✓、`st['diced_rc']` 记上 ✓
  - **首领格**的结算面板不摇色子（只关，不回归）✓
- 四个面板自检 exit 0
- **产物**：`AutoExplore-v1.23-MGAS-修「大拇指格不摇色子」真根因（结算面板也要摇+跨路径防重复）-release.apk`
  （`versionCode 123` / `versionName 1.23`）

#### ⑤ 下一步

- ⏳ **真机再跑一把有大拇指的图**：这次应该看到
  `{'popup': 'result_dice', ...}` → `{'dice': 'panel'/'no_btn'/'got_recommend'}` →
  `{'popup': 'result_closed'}`。若出 `no_btn`，说明这块面板上**没有**重投按钮
  （= 奖励行本来没有可重投项，或按钮文字不在搜索带里）⇒ 拿那条日志再定 ✓
- ⏳ §6.47 的**标记闸门标定**（偏暗机型）仍未做

### 6.49 ⭐⭐⭐ v1.24：「不摇色子」第二刀 —— **重投按钮根本没有文字**（2026-10-02）

v1.23 装到真机（Redmi 1280×2772）又跑了一把，用户仍报「不摇色子」。
反馈包（用户命名 `不摇色子.zip`）里这次证据齐了：

```
{"popup":"result_dice","rc":[3,4],"marks":["boss","recommend"]}    ← v1.23 的结算面板分支生效 ✓
{"dice":"initial_check", "best":{"dlg+C":null,"dlg":null,"ref":null}}
{"dice":"no_btn","rolls":0,"band":[520,1020],
 "cand":[{"t":"1/84",...},{"t":"422 596 96",...},
         {"t":"16","cx":111,"cy":906},{"t":"1","cx":118,"cy":979}]}  ← 只有数字，没有按钮文字 ✗
```

**根因**：`handle_dice` 只按**文字**（骰/重投/命运/重掷/掷）找重投按钮，
而这块面板上那个按钮**根本没有文字** —— 它是**奖励行左边那个「🍀 + 数字」图标按钮**
（上面大数字=剩余骰子数，下面 `🍀 1`=重投消耗 1 个幸运草）。

游戏面板原图实测（1080×1920 归一化帧；面板是**锚底系**，所以拿「关闭」当锚点最稳）：

| 元素 | PC 帧 | 真机 OCR | 偏移 |
|---|---|---|---|
| 「关闭」 | y=1445 | **y=1441** | — |
| 🍀 重投按钮 | ≈ (114, 979) | `'1' @ (118, 979)` | **关闭 y − 466** ✓ |

⇒ 两路互证（图上量的位置 = 真机 OCR 读到的那个数字条目）⇒ 偏移 **−466** 跨分辨率稳定。

**修法**

1. 新增 `clover_btn()`：**结构定位** —— 优先用 OCR 到的那个「短数字」条目
   （跨分辨率自适应 ✓），找不到再退回「关闭上方 466」的锚点推算；
   连「关闭」都认不到 ⇒ **返回 None，不乱点** ✓
2. `handle_dice` 在 `no_btn` 之前先试这个兜底（日志 `{'dice':'clover_btn_fallback'}`），
   点完**照旧**要求「是否重掷？」确认框弹出才算数（没弹就放弃，两次即止 ✓）
   ⇒ 万一点错位置，也只是"没反应"，不会乱点、不会白花幸运草
3. 判不出来时把这块面板**存成诊断帧** `dice_nobtn`（`_pub_dump` ⇒ 反馈包自动带上 ✓）
   —— 下次真出问题，手里就有真机面板原图，不用再靠推位置

**验收**：门禁 **314 → 321 项，通过 321 / 失败 0 / 跳过 1**（新增 ㊲ 七项，
其中 ④~⑦ 执行级：真机那份面板条目 ⇒ 选中 (118,979)（不是 16/240/关闭）；
只有「关闭」⇒ 推算 (114,975)；认不到关闭 ⇒ None；离锚点 ±160 外的数字不选 ✓）。
四个面板自检 exit 0。版本 `123 → 124`，产物
`AutoExplore-v1.24-MGAS-修「不摇色子」第二刀（重投按钮没文字⇒结构定位兜底）-release.apk`，**已装机**。

**下一步**：真机再跑一把有大拇指的图 ⇒ 应看到
`{'dice':'clover_btn_fallback', 'at':(118,979)}` → `{'dice':'reroll_confirm'}` → `{'dice':'after'}`；
若出现 `{'dice':'no_confirm_popup'}` 说明这个位置点下去没弹确认框（那就是还差一点位置/或那不是按钮），
反馈包里的 `dice_nobtn` 帧会直接给出答案 ✓

### 6.50 ⭐⭐⭐ v1.25：「不摇色子」第三刀 —— 确认框 OCR 多带一个字 + 弹框挂着还去点正文（2026-10-02）

> ⭐ **取证方式升级**：`dump_summary()` 早就会把最近 400 条日志写到**公共目录**
> `/sdcard/Download/autoexplore/bagdbg/mgas_log.txt` —— 无线 adb 直接
> `adb pull` 就能读，**不用再点「反馈」生成包**（§6.38 的反馈包仍然有用：它带帧）。

v1.24 装到真机（Redmi 1280×2772）又跑了一把，日志：

```
{"dice":"clover_btn_fallback","at":[118,979]}       ← v1.24 的结构定位**命中** ✓
{"dice":"reroll_confirm","at":[774,802],"rolls":1}  ← 弹框弹出+点「确定」⇒ **真摇了 1 次** ✓✓
{"dice":"after","rolls":1,"reward_mark_hits":0}     ← 摇完奖励行没出大拇指（本该继续摇）
{"dice":"panel","rolls":1,"items":[…"命运之骰"…
        {"t":"是否继续重掷？"},{"t":"取消","cx":304,"cy":803},{"t":"石确定","cx":774,"cy":802}]}
{"dice":"no_confirm_popup","rolls":1,"streak":1} → streak=2 → {"dice":"abort_no_confirm"}
                                                     ← **只摇 1 次就放弃** ✗✗
```

**根因两条**

| # | 根因 | 后果 |
|---|---|---|
| ① | 弹框判据是 `exb()`（**整条等值** `text == '确定'`），本机 OCR 读成 **「石确定」**（多一个"石"字 —— 弹框边上的石纹装饰被并进框里）⇒ 认不出弹框 | 摇完第 1 次后不再点「确定」⇒ 只摇 1 次 |
| ② | 弹框还挂着时，「找骰子按钮」那条路会把**弹框正文**「每次重掷必定高于当前点数，最高20点」（含「重掷」）当成按钮点掉 | 用户看到的**乱点** |

**修法**

1. 新增 `dice_dialog(items)`：**宽容识别** —— 标题词（命运之骰/是否继续重掷…）判"弹框挂着"；
   「确定/取消」用**包含**匹配，且标签长度 ≤6（防把正文长句当按钮 ✗）；
   确定取最右、取消取最左（真机 取消(304,803) / 确定(774,802) ✓）
2. A 段改用它；**弹框还挂着 ⇒ 直接回 A 再点确定**（`dialog_still_up`）；
   认到弹框却找不出「确定」⇒ **停**（`dialog_unparsed`），**绝不走 B** ⇒ 不会再点正文 ✓
3. 收尾「取消」也走宽容识别

**验收**：门禁 **321 → 329 项，通过 329 / 失败 0 / 跳过 1**（新增 ㊳ 八项；⑤~⑧ 执行级用的是
**真机日志原样抄下来的**那组条目：必须认出「石确定」@(774,802)、正文长句不许当选、
普通结算面板返回 None、只有「确定」没有标题词也不当弹框 ✓）。四个面板自检 exit 0。
版本 `124 → 125`，产物
`AutoExplore-v1.25-MGAS-修「不摇色子」第三刀（确认框OCR带字⇒宽容识别+弹框挂着不点正文）-release.apk`，
**已装机**。

**下一步**：真机再跑一把有大拇指的图 ⇒ 期望日志：
`clover_btn_fallback` → `reroll_confirm`(rolls=1) → `after`(0 hits) → **`dialog_still_up`** →
`reroll_confirm`(rolls=2) → … 直到 `got_recommend` 或摇满 3 次 ⇒ `done {'rolls': 3}`

### 6.51 ⭐⭐⭐ v1.26 真机两条：**截图断流还瞎点** + **点完战斗没等到开打就去点下一格**（2026-10-02）

> **取证方式**（用户提醒后确认）：`dump_summary()` 会把最近 400 条日志写到
> `/sdcard/Download/autoexplore/bagdbg/mgas_log.txt` ⇒ 无线 adb `pull` 直接读，
> **不用点「反馈」生成包**（反馈包只在需要**帧**时才有用）✓

#### ① 「点了战斗格、还没打就去点下一个格子」= 机器人**瞎了**还在点

用户报的这句话，那一局的日志是：

```
02:03:35 截图流 9s 无新帧 ⇒ 自救 #1（重建 ImageReader）
02:03:40 截图流 13s 无新帧 ⇒ 自救 #2
02:03:44 截图流 17s 无新帧 ⇒ 自救 #3
02:03:48 截图流断流且自救失败 ×4 ⇒ 需重新授权截图（重启应用后点①授权截图）
   …… 一直 ×56（02:07:16）
```

`CaptureService` 的看门狗发现断流后**只在 Java 侧记日志**，Python 完全不知情 ⇒
它继续拿**冻结的旧帧**判图、**继续点地图格子** ✗✗（战斗面板在游戏里开着，它却在点别的格子）

**修法**：把帧龄暴露给 Python，**帧不新鲜就别点** ——
`DeviceApi.frameAgeMs()`（`FrameStore.stamp()`，没帧返回 −1）+ Python `frame_age_ms()`；
主循环里帧龄 **>8s 连续 2 轮** ⇒ `{'finish':'capture_stale'}` **停整局**，
悬浮条写「截图断了 · 请点①授权截图」✓（返回 None = PC 端/还没帧 ⇒ 不判断，不会误停 ✓）

⚠ **装机后 MediaProjection 授权必然失效** ⇒ 重装/重启后**必须先点「① 授权截图」**再跑
（这次就是没点，跑了 5 分钟瞎子；以前也有同样的坑）。

#### ② 「5 秒没等到开打」≠「没打起来」

同一局有帧时的另一条：`{'battle':'no_battle_in_5s'}` → `not_started` → `blocked`
⇒ 上层"开路模式"就去点下一格；**下一轮却看到了结算面板**（战斗其实打完了）✗

真机点完「战斗」到**真正开打 >5 秒**很常见（模拟器上不会，所以老口径是 5s）⇒

- `start_fight()` 等待 **5s → 15s**，看到战斗**立刻早退**（不白等）
- **认到结算面板也算"打过了"**（`result_panel_instead`）—— 自动跳过/极速战斗会直接进结算 ✓
- 原逻辑保留：只有"点了完全没反应"才允许再点一次（防点到状态图标/回放 ✗）

**验收**：门禁 **329 → 335 项，通过 335 / 失败 0 / 跳过 1**（新增 ㊴ 六项；⑤⑥ 执行级把 `time`
换成假时钟直接调真 `start_fight()`：15s 无动静 ⇒ 失败且**只点 1 次**；直接进结算 ⇒ 返回 True
且记 `result_panel_instead` ✓）。四个面板自检 exit 0。版本 `125 → 126`，产物
`AutoExplore-v1.26-MGAS-修截图断流还瞎点+点完战斗没等到开打就去点下一格-release.apk`，**已装机**。

### 6.52 ⭐⭐⭐ v1.27 修「宝库买完了，却永远显示还剩 1 个目标」= **幽灵目标**（2026-10-02）

用户原话：「最近这把大拇指、探索、宝库都没问题了，**就是现在显示还有一个目标，
但是我看着已经没目标了**」。

真机日志（`bagdbg/mgas_log.txt`，adb 直接拉）里 r11 那一轮：

```
[r11] 没有目标了，准备退图
第 1 张图 · 正在找路（还剩 1 个目标）        ← 同一轮里两句自相矛盾 ✗
```

**根因**：悬浮条数字 = `len(marked) + len(pending_buy)`，而「没有目标了」那句只看
`marked` / `buy` / `buy_hidden` ⇒ 说明这三个都空了，**幽灵在 `pending_buy` 里**
（`sticky` 粘性集或 `buy_seen` 跨轮记忆）。为什么清不掉：

- 宝库**买完之后那张贴图还在**（仍被认成宝库/商人、score ≥ `BUY_MEMORY_MIN` 0.60）
- ⇒ `buy_seen` 每轮都被**重新刷新**，永远等不到「4 轮没再出现」的清理
- ⇒ `pending_buy` 恒非空 ⇒ 永远「还剩 1 个目标」，还满地图去找它 ✗✗

**修法**（v1.27）

1. 宝库流程**成功**（`vault: done`）时，当场把该格登记进 `st['buy_consumed']`
   （日志 `{'vault':'consumed','rc':[r,c]}`），并从 `buy_seen` / `buy_sticky` 里删掉 ✓
2. `buy` / `buy_hidden` **早期**就按 `buy_consumed` 过滤（防止那张贴图又把它加回目标）✓
3. `pending_buy`（含 sticky / 记忆两条来源）再过滤一次 ✓
4. 已消耗的格子**不再进** `buy_seen` 记忆（拒绝幽灵重生）✓
5. 新增诊断 `{'targets_ghost': {...}}`：**没有标记却有 pending 目标**时，
   把 `buy` / `buy_hidden` / `sticky` / `mem` / `consumed` 五个来源逐一点名 ⇒
   下次再出幽灵，日志一句话就能定位 ✓

**验收**：门禁 **335 → 341 项，通过 341 / 失败 0 / 跳过 1**（新增 ㊵ 六项，⑥ 执行级：
已买完那格的像素中心 ⇒ 过滤后 `pending` 为空 ✓）。四个面板自检 exit 0。
版本 `126 → 127`，产物
`AutoExplore-v1.27-MGAS-修「宝库买完还显示还剩1个目标」幽灵目标-release.apk`，**已装机**。

### 6.53 ⭐⭐ v1.28 按用户口径：**进图只规划一次**，走完还有目标 ⇒ 切回兜底（老方案）（2026-10-02）

用户原话：「**规划就刚进入规划一次，后续不再规划。走完规划的还有目标就用之前的保底方案走**」

> ⚠ **这条是反复过的**，把两边的账都记在这儿，别再来回翻：
> - 2026-09-27 用户要过「每张图只在进图后规划一次」→ 代码就是这么写的
> - 2026-09-30 被离线对拍**推翻**（`_bench_online.py --corpus`，96 张真机内存盘）：
>   进图时**目标集残缺**（未揭示的标记格/商人还没认出来）⇒ 比全知最优贵
>   **+9.2%**（marks 可见）/ **+26.1%**（marks 藏雾里），最坏单盘贵 **16 体力**
> - 2026-10-02（本条）用户再次明确要「进图一次」⇒ **按用户口径改回**：
>   可预期、不在图里反复改主意；代价以 09-30 那组数字为准（会多花体力）

**实现**（判据抽成纯函数 `plan_next(st, rest_n, targets_left)`，可离线对拍 ✓）

| 情形 | 动作 | 日志 |
|---|---|---|
| 还没规划过 | 现在算一次（= 进图那一下） | `{'plan':'once','cells':[...]}` |
| 计划还有没做完的步 | **继续照走，绝不重算** ✓ | — |
| 计划走完、**还有目标** | 切 **EffPolicy 片感知兜底**（就是"之前的保底方案"） | `{'plan':'exhausted','targets_left':N}` |
| 计划连着 **3 轮没推进**（格子点不动/被挡） | 也切兜底（**安全网**，不再死抱走不通的计划 ✗） | `{'plan':'stuck','targets_left':N}` |
| 计划走完、也没目标了 | 什么都不做，交给收尾逻辑 | — |

悬浮条同步提示：`规划走完 · 改用兜底策略` / `计划推不动 · 改用兜底策略` ✓

**验收**：门禁 **341 → 351 项，通过 351 / 失败 0 / 跳过 1**（新增 ㊶ 十项；
⑤~⑩ 执行级直接调真 `plan_next()`：第一轮 `plan/first`、有计划 `keep/has_rest`、
同批步数连着 3 轮 ⇒ `eff/stuck`、步数有减少 ⇒ 计数清零、走完有目标 ⇒ `eff/exhausted`、
走完没目标 ⇒ `none/no_targets` ✓）。四个面板自检 exit 0。版本 `127 → 128`，产物
`AutoExplore-v1.28-MGAS-进图只规划一次+走完还有目标切兜底-release.apk`，**已装机**。

### 6.54 ⭐⭐⭐ v1.29 修「进图发了会呆就退出了」+ 规划口径改回「每轮重解」（2026-10-02）

#### ① 主修：**探索模式**（真机反馈包 `进图发了会呆就退出了.zip`，realme RMX3800 / v1.28）

日志逐轮（`bagdbg/mgas_log.txt`，adb 直接拉）：

```
r0/r1  marks_scan: none + solver: no_plan + finish: blank_board ×2   （40s / 90s 发呆 ✗）
r2     popup_none_dlg: probe（找不到面板）+ universal_close: popup_none
r3     finish: targets_done, gray_left: 24   ← **24 个暗格一格没开就退图** ✗✗
```

**根因**：点序只在「有标记 or 有商人/宝库」时才构建 ⇒ 这一帧没认出任何标记
（`marks_scan: none`，近失分 recommend 0.769 / boss 0.734，都低于闸门）
⇒ `order=[]` ⇒ 判"盘上空白" ⇒ **发呆** → 再按"目标做完"**退图** ✗

**修法**：`need_explore(marked, pending_buy, grays_n, clicks)`（纯函数 ✓）——
没目标但盘还没探开（暗格 ≥ `EXPLORE_MIN_GRAY = 8`）⇒ **先探图**（沿已揭示的可点格往外开，
把标记/宝库逼出来），并且：

- `targets_done` 退图被拦住（`and not _explore`）✓ —— 不再"空手退图"
- 点序构建放行探索模式（`(marked or buy_any or _explore)`）✓
- 探图预算 `EXPLORE_MAX_CLICKS = 40` ⇒ 不会为了探图无限花体力 ✓
- 日志 `{'explore':'mode','grays':N,'clicks':K}` + 悬浮条「没标记，先探图（还剩 N 个暗格）」✓

#### ② 规划口径：按用户 10-02 晚「**那换回来吧**」⇒ 每轮重解（省体力那条）

**两条路都留在代码里，用开关切**（`PLAN_ONCE`；这条历史上来回翻过两次，别再手改逻辑 ✗）：

| 开关 | 行为 | 取舍 |
|---|---|---|
| `PLAN_ONCE=0`（**默认，当前**） | 每轮用最新观测**重解**、覆盖旧计划 | **省体力**（离线 96 张对拍 +9.2%~+26.1% 的优势）；走法会中途变 |
| `PLAN_ONCE=1`（或 `MAPBOT_PLAN_ONCE=1`） | 进图只规划一次 + 走完/推不动切兜底 | 可预期、不在地图里改主意；**多花体力** |

⏱ **时间成本实测可忽略**（这条从来不是"快慢"问题）：真机 solver 自报 `secs 0.0`；
离线 96 张真机盘 p50 0.65ms / p95 1.4ms / p99 1.9ms（A* 重构后；"秒~分钟级"是旧 Dijkstra）。

**验收**：门禁 **351 → 362 项，通过 362 / 失败 0 / 跳过 1**（新增 ㊶ 12 项规划口径 +
㊷ 9 项探索模式；㊷⑥~⑨ 执行级用的就是**真机日志原样数字**）。四个面板自检 exit 0。
版本 `128 → 129`，产物
`AutoExplore-v1.29-MGAS-修「进图发呆就退图」探索模式+规划改回每轮重解-release.apk`，**已装机**。

### 6.55 ⭐⭐⭐ v1.31【真机整屏偏紫的根因】**取帧慢路径 R↔B 互换**（2026-10-02）

用户在这条上连问三句，把方向钉死了：

1. 「**啥都没识别出来**」
2. 「**用包里的图就行**」⇒ 我去看那张图：r1c1 明摆着**大拇指图标**、r3c2 也有标记（肉眼可见）
3. 「**人看和截图都是正常的，就反馈包里的不正常**」⇒ **显示/游戏没问题，是我们自己取帧这条链** ✗✗

**根因**（`CaptureService.onFrame()`）：

```java
if (pixelStride == 4 && rowStride == w * 4) {
    bmp.copyPixelsFromBuffer(buf);          // 快路径：Redmi 1280 宽 ⇒ 走这条 ✓ 颜色正常
} else {
    rb.asIntBuffer().get(pixels, y * w, w); // 慢路径：RGBA 字节当 int 读（= ABGR）✗
    bmp.setPixels(pixels, 0, w, 0, 0, w, h); // setPixels 要 ARGB ⇒ **R↔B 互换** ✗✗
}
```

**触发条件 = 屏宽 1264** 的 realme RMX3800：`1264*4 = 5056`，GPU 行距按 64 对齐补到 **5120**
⇒ `rowStride != w*4` ⇒ **只有它走慢路径** ⇒ 暖色棋盘被换成**蓝紫**、金色图标变紫
⇒ 标记形状/配色分全在闸门下面 ⇒「啥都没识别出来」✓（1280 宽的 Redmi 走快路径 ⇒ 正常 ✓
完美对上用户那句「另一个设备就是正常的」）

**实证**（反馈帧 `board_hidden_r0.png`）：

| | 通道均值 B:G:R | boss 标记 @(3,2) |
|---|---|---|
| 反馈帧（偏紫） | **1.37 : 0.75 : 0.89**（蓝主导 ✗） | shape 0.732 / color 0.830 ⇒ **漏** ✗ |
| 对照组（正常帧） | 0.87 : 0.98 : 1.16（红主导 ✓） | — |
| **把 R↔B 换回来** | — | **shape 0.914 / color 0.901 ⇒ 命中 `boss`** ✓✓ |

**修法**：慢路径**去掉行距填充后交给 `copyPixelsFromBuffer()`** —— 与已验证正确的快路径
**同一套转换**；并把"走了哪条路 + 实际行距"暴露给 Python（`DeviceApi.capturePath()`）
＋ 首次走慢路径时记一行日志（`w / rowStride / 期望`）⇒ 反馈包能自证 ✓

**验收**：门禁 **365 → 369 项，通过 369 / 失败 0 / 跳过 1**（新增 ㊹ 四项：旧的两行必须消失、
必须走同源转换、诊断必须暴露、必须记日志）。四个面板自检 exit 0。版本 `130 → 131`，产物
`AutoExplore-v1.31-MGAS-修取帧R比B互换（真机整屏偏紫→识别全崩的根因）-release.apk`，**已装机**。

### 6.56 ⭐ v1.32 APK 命名统一 + 取帧通道序自证（2026-10-02）

**命名规范**（用户 2026-10-02 定：「之后 apk 命名格式为 MGAS-v版本号-release」）：

```
MGAS-v1.32-release.apk     ← 交付用（版本号现场读 app/build.gradle 的 versionName ✓）
MGAS.apk                   ← 固定别名，永远指向最新那一版（方便 adb install ✓）
```

用 `tools/pack_apk.py` 出包（**别再手写长中文名** ✗）：

```bash
python tools/pack_apk.py            # 构建 + 按规范名复制
python tools/pack_apk.py --no-build # APK 已经有了，只改名
```

⚠ 版本号**现场读**，不写死；复制用 Python（PowerShell 重定向/`Set-Content` 会加 BOM、毁二进制 ✗）

**取帧通道序自证**（承接 v1.31 的 R↔B 互换修复）：每局开头记一条

```
{"capture_path": {"slow": true, "row_stride": 5120, "w4": 5056}}
```

＋ 走慢路径时控制台/悬浮条念「取帧走**慢路径**（行距填充 rowStride=5120 期望=5056）」。
⇒ 以后反馈包里能一眼分辨「取帧真换了通道」还是「帧是旧的/别的毛病」✓

> ⚠ **教训**：bagdbg 里**固定文件名**的落帧（如 `board_hidden_r0.png`）会被**上一局**的旧帧冒充新帧
> —— 2026-10-02 就因此把一张 9 小时前的紫图当成"新截图"分析过一轮 ✗
> ⇒ 看证据先看**文件名/时间戳**（新落帧用 `marks_none_r*.png`），别拿老名字当新证据 ✗

> 💡 这条同时解释了前两台机器「偏暗机型标记近失」（boss 形状 0.741 / 配色 0.841）：
> 同一族取帧通道/色彩问题，只是宽高比不同、补位方式不同，严重程度不一样 ✓

### 6.57 ⭐⭐⭐ v1.41 两层热更新：APK 发给朋友**之后**怎么更新（2026-10-03）

**用户口径**（原话）：「发给朋友的怎么搞热更新？」

**先答最容易被误解的一点**：更新包放公开 Gitee 仓库 ⇒ **朋友不用打开 Gitee、不用注册、不用登录**。
那只是我放文件的"网盘"，App 自己发 HTTP 请求去拉（`Updater.MANIFEST_URL`）。

#### 两层，各管各的

| 层 | 换什么 | 体积 | 朋友要做什么 |
|---|---|---|---|
| **逻辑热更** | `app/src/main/python/*.py`（12~14 个模块，业务逻辑全在这） | **300 KB** | **什么都不用做**：悬浮条一起来就后台下载 → 下次冷启动自动生效 |
| **APK 自更新** | Java 壳 / 权限 / 依赖 / 资源包 | ~71 MB | 进界面点一次「检查更新」→ 系统安装器弹一下 → 点「安装」 |

实测体积：14 个 `.py` 压完 **300.5 KB**（`hot-141-8a8a040c.zip`）——
所以日常改识别逻辑的代价从"发 71MB + 朋友重装"降到"2 秒静默下载"。

#### 更新源（公开仓库 `geng-haojie/MGAS-update`）

```
manifest.json            ← App 拉这个判断有没有新版（raw 直读）
hot/hot-<vc>-<sha8>.zip  ← 逻辑补丁（raw 直读；只留最近 5 个，防仓库配额爆）
release 附件 v<x.y>      ← 整包 APK（放 releases/，**不占**仓库 1GB 配额）
```

**2026-10-03 匿名实测**（不带 token、不带 Referer）：

| 通道 | 结果 |
|---|---|
| `raw/master/manifest.json` | `200` ✓ |
| `releases/download/v0-test/xxx` | `200` ✓ |
| 建仓库时 API 传 `private=false` | ⚠ **Gitee 实际建成 private=True** ⇒ 必须再 PATCH 一次 `private=false` 才是公开 |

#### 我这边：一条命令

```bash
python tools/release.py --hot-only --notes "修 XX 误判"   # 日常（不构建，秒级）
python tools/release.py --notes "壳改动"                  # 改 Java 时（跑 gradle）
python tools/release.py --hot-only --dry-run              # 只看要发什么
```

- 版本号**现场读** `app/build.gradle`（不写死）；补丁 id = `hot-<versionCode>-<zip sha8>`
- 只发补丁时**保留 manifest 里的 app 段**，反之亦然 ⇒ 不会因为"只发一半"让另一端以为没更新
- 令牌从 `GITEE_TOKEN` 或 `~/.gitee_token` 读，⚠ **绝不进仓库**（`.gitignore` 也加了防呆条目）

#### ⭐⭐ 回滚：这一层的正确性比"能更新"更重要

Python 补丁有语法错/import 失败会让**整个脚本不可用**，而朋友**不会看日志、更不会报给我** ⇒
必须有自动兜底。状态机在 `filesDir/hot/state.json`：

```
① 下载 → 解到 hot/pending/（写 meta.json）
② **下次冷启动** bootRecover()：pending → active，state{active, confirmed=false}
③ Python 起来后 onPythonStarted() 调 explore_android.hot_selftest()
     · 通过  → confirmed=true（此后不再自检）
     · 不通过 → **当场**把 active 挪到 hot/bad/（留证据不删）→ sys.path 那条失效
                → 回落 APK 内置版 → **卸掉已加载的补丁模块** → 再自检一次
④ 若上次激活后从未确认过（激活完就被杀），下次启动 bootRecover() 直接判坏包回滚
```

两个容易写错的点，都已在代码里钉住：
- **`hot_selftest()` 必须真的 import 一遍**（连锁 `mapbot`/`explore_loop`/`cv2`）——
  "文件在不在"永远为真，那种检查等于没检查（《错误教训》同族问题）
- **回滚后要卸掉已加载的补丁模块**（`hot_reset_modules()`）——
  否则"补丁里的 `mapbot` 加载成功、`explore_loop` 失败"会留下**一半补丁一半内置**的混血状态，比全内置难查得多
- 同一个坏包 id 进 `rolledBack` ⇒ **不会再自动重装**（否则每次启动都下 300KB 再回滚）

#### 为什么没往悬浮条上加「更新」按钮

悬浮条的按钮行有**严格高度预算**（`chip()` 注释：按钮行高度必须精确可控，否则换密度就顶穿 1722），
现有 6 颗按钮是用户逐轮验收过的 ⇒ 加第 7 颗有真实布局回归风险，而**逻辑补丁根本不需要按钮**（全自动）。
⇒ 决定：悬浮条**只加自动检查**（`Updater.run(ctx,"bg")`，整包只提示不带下载），
手动入口放界面「更新」卡（`MainActivity.doUpdate`）＋ adb 广播。

#### 验证（adb，**跑的就是朋友那条代码路径**）

```bash
adb shell am broadcast -n com.fantasy.autoexplore/.CommandReceiver \
     -a com.fantasy.autoexplore.CMD --es cmd update --es mode check   # 只查
     ... --es cmd update --es mode hot     # 下补丁（重启后生效）
     ... --es cmd update --es mode apk     # 下整包 + 弹系统安装器
     ... --es cmd update_status            # 热更状态（补丁 id / 待激活 / 上次回滚）
```

#### 踩过的坑（写在这里省下一轮）

| 坑 | 现象 | 处置 |
|---|---|---|
| **Gitee `raw/` 有强缓存** | 刚 push 的 `manifest.json`，读回来还是旧内容（连加 `?t=<时间戳>` 破缓存**都无效**）⇒ 表现成"我发了新版，端上永远说已是最新" ✗✗；发版脚本还会因此把**另一段覆盖成 null** | 清单**必须走 `api/v5/.../contents/`**（实时）；raw 只作回落。⚠ 补丁/APK 走 raw 没事 —— 文件名带内容 sha，内容一变名字就变，天然免疫缓存 |
| **API 建 Gitee 仓库给 `private=false`** | 实际建成私有，匿名 raw 403 `Access denied` | 建完再 PATCH 一次 `private=false` |
| **MuMu 的 `PackageInstaller.Session` 是坏的** | createSession/openWrite/fsync/commit **全不抛异常**，回调却 `status=-1/msg=null`，系统日志里连一条 PackageInstaller 都没有、界面不弹；同机 `adb install` 同一个包却成功 | 弃用 Session，改 **MediaStore 写 `Download/autoexplore/` + `ACTION_VIEW`**（= 文件管理器点 APK 的标准路径），提示里带文件路径兜底 |
| **MuMu 把 APK 安装 intent 劫持到自家商店** | `ACTION_VIEW` 后前台是 `com.mumu.store` 而不是安装器 | 模拟器上**验证不了安装成功路径** ⇒ 必须真机首测（见下） |
| PowerShell 5.1 上传附件 | `Invoke-RestMethod` **没有 `-Form`** 参数 | 用 `curl.exe`，或 Python 手写 multipart（`release.py` 走后者） |
| `pack_apk.py` 在 GBK 控制台**构建成功后仍 exit 1** | 末尾 `print('…✓…')` 抛 `UnicodeEncodeError` ⇒ `release.py` 误判"打包失败" | 脚本内 `sys.stdout.reconfigure(encoding='utf-8')`，调用方另传 `PYTHONIOENCODING=utf-8`（双保险） |
| `manifest` 只更新一段 | 另一段丢失 ⇒ 那一层永远更不了 | 发版脚本先读现有 manifest 再合并；`--manifest-only` 用于只改清单（不必重传 71MB） |
| 手工造坏包验证时用**旧快照**恢复 | 把刚发的完整清单覆盖回"只有 hot 段"的旧版 | 恢复**要用 `release.py --manifest-only` 重新生成**，别用旧快照 |

#### ⚠ 尚未实测的一项（如实记下）

**"安装成功"这最后一跳没有在真机上验证过**：手头只有两台 MuMu（x86_64/Android 12），
其中安装 UI 被模拟器自家商店接管 ⇒ 只能验证到"**下载 71MB + sha256 校验通过 + 把包写进
`Download/autoexplore/` + 拉起安装 intent**"。
⇒ 第一次给朋友之前，**用一台真机跑一遍首测清单**：
① 装新包 → ② 进「更新」卡点「检查更新」→ ③ 看到"安装界面应弹出" → ④ 点系统「安装」→
⑤ 确认版本号变了、数据（截图授权除外）没丢。

### 6.58 ⭐⭐⭐ v1.60 照抄 PC 揭示判据（两趟相对法 + 模型层 0.75 覆写）+ `camp_nb` 同口径（2026-10-05）

**来源**：未决第 1 条（`会话接力.md` §3 ↔ `PC规划算法对照报告.md` §D 的 M35 / M50 / M51）。

**病**（用户报）：手机端**已揭示的格会被判成雾**（`observed=False`）⇒ `Block.plain` 走雾剪影分支
⇒ **空地连锁断裂** ⇒「2 步的事弄成 4 步」；外加「求解器可点、`cells_for_plan` 却找不到已揭示格
⇒ 走兜底 `cells[0]` ⇒ 计划点雾格」（PC 那条注释写着「**不该发生**」）。

#### 抄了什么（**结构逐字抄 PC**）

| # | PC 位置 | 抄成什么 |
|---|---|---|
| ① | `mapbot_pc/spots.py:705-736` | `revealed ⟺ ratio ≥ max(地板, 本帧第10分位 × 1.06)`（**必须两趟**）；`REVEAL_REL_Q=0.10` / `REVEAL_REL_K=1.06` 逐字照抄 |
| ② | `mapbot_pc/explore_loop.py:1009-1029` | `_cells_for_model` 里 `ratio ≥ 0.75` **覆写**（`MODEL_REVEAL_RATIO_MIN`，值 **0.75 逐字照抄**，位置也在 `_rescue` 之前） |
| ③ | `mapbot_pc/mapsolve.py:88-93 / 151 / 403-415` | 营地揭示源**单一来源** `Problem.camp_reveal`：`block_revealed` / `visible` / `camp_nb` **三处都只读它**（PC 的第三处用整块 ⇒ 那是 PC 的疏漏，**故意不抄**）＋ `elif` 兜底照抄 |

#### ⚠⚠ 唯一的分叉：**地板不是 PC 的 0.66，是手机端标定的 0.80**（有实测，不是口味）

PC 的 0.66 安全，是因为 PC 的 `ratio` 分母 = **该格自己的模板亮度** ⇒ 雾带很窄（≈0.65）。
手机端 v1.35 起分母 = **本图模板亮度中位**（治"换图就废"）⇒ 雾带按格子美术亮度**摊开**：
真机草原帧实测雾格 **0.685~0.761**（= p10 的 **1.26 倍**）⇒ PC 的 ×1.06 **盖不住**。

逐格回代（`_tmpman/probe_v160_reveal.py`，6 张真机帧；草原两帧有人工标注真值）：

| 地板 | 草原帧A（35 格，真值 3 格） | 草原帧B（35 格，真值 3 格） |
|---|---|---|
| **0.66**（PC 逐字） | **FP 28 格**（雾格 0.685~0.735 全被判已揭示 ✗✗） | **FP 23 格** ✗✗ |
| **0.80**（默认） | FP 0 / FN 0 ✓ | FP 0 / FN 0 ✓ |

⇒ 0.66 在手机端不是"宽一点严一点"，是**直接坏掉**（下游 `_infer_chain_consumed` 会把整盘雾格
反推成"已消耗" ⇒ 模型空掉）。**门禁 v1.60 ⑦ 把这条固化成反向断言**（0.66 ⇒ FP≥20），
谁把地板改回去，门禁必红 ✓。想现场对拍 PC：`MAPBOT_REVEAL_FLOOR=0.66`（**只作取证**）。

#### 两层为什么都要（PC 说"只抄一半比不抄更糟"）

| 层 | 判据 | 实测（真机草原帧，**用代码自己的 ratio**） |
|---|---|---|
| `spots.revealed` | `max(0.80, p10×1.06)` | FP 0；FN = **营地**（它 ratio=**0.780** < 0.80） |
| 模型层（喂 `mapsolve`） | `ratio ≥ 0.75` | **FN 归零**（营地 0.780 被捞回 = 病被修 ✓）；FP = `2,3` 符文岩石 **0.780** |

- 模型层比 `spots` **低** ⇒ 唯一效果 = 放行 `ratio ∈ [0.75, 0.80)` 的格 —— **这正是**"已揭示被判成雾
  ⇒ `observed=False` ⇒ 剪影分支 ⇒ 连锁断裂"那一族（营地就是典型：真实已揭示，却被 0.80 判雾）。
- 实测那一个 FP（`2,3` 符文岩石）**不是空地** ⇒ **不会**"假连锁穿雾"（门禁 v1.60 ⑥b 守这条不变量）。
- ⚠ 这里还有一条**门禁自身的教训**：v1.36 ⑨ 原来是**自己重算** `mean/L_map` 来验阈值，
  而它对营地格算出 **0.861**、代码 `state()` 算的是 **0.780** ⇒ **自己算的那版把真 bug 整个盖住了** ✗✗
  ⇒ v1.60 ⑤/⑥/⑩ 一律改成**调 `Board.state()` / `_cells_for_model` 真流水线** ✓

#### `camp_nb` ≡ `block_revealed`（同口径）

- 之前：`camp_nb` 用「**营地块 ∪ 营地格**」的 4 邻（v1.55 加的），`block_revealed` 只看 `camp_cells`
  ⇒ 求解器可点、选格时找不到已揭示格 ⇒ 兜底 `cells[0]` ⇒ **点雾格** ✗
- 现在：`camp_reveal` 一处定义、三处消费；邻接算法只有 `_camp_nb_blocks()` 一份
  ⇒ **不变量**：`camp_nb` 里每一块在空状态下都 `block_revealed=True`（门禁 ⑮ 守）。
- v1.55 的**块角营地**那半不丢：营地格 4 邻全是自己那块时，`camp_reveal` 放宽成整块（成对生效 ✓）。
- 反向断言（门禁 ⑮d）：与**营地块**相邻、但与**营地格**不相邻的格（PC 真机那把的 boss，ratio 0.665 是雾）
  **不许**进 `camp_nb` ✓。

#### 验收

- 门禁 **659 → 681 项，通过 681 / 失败 0 / 跳过 1**（新增 ㊿⭐ 22 项：源码守门 4 + 真机帧实跑 4 +
  反例 1 + 模型层 5 + camp_reveal 7 + **相对项生效性实测 1**）
- 四个面板自检 **exit 0**（`verify_panels_allres` / `panel_consts` / `verify_panel_band_allres` /
  `verify_reward_band_allres`）
- 版本 `1.59 → 1.60`，产物 `MGAS-v1.60-release.apk`（71.0 MB，`aapt dump badging` 实测
  `versionCode=160 / versionName=1.60`），**已装机**（Redmi 25053RT47C / 无线 adb）
- ⭐ **交付核对（用户要求）**：真机 `lastUpdateTime = 2026-10-05 01:59:03` **晚于**最后一次改源码
  （`tools/verify_explore_slots_fix.py` 01:52:19、`build.gradle` 00:52:01、
  `app/src/main` 下**任何**源码最晚 00:46:14）✓ —— 并且 APK 里打的是**新代码**
  （解包 `assets/chaquopy/app.imy` 实测 `spots.pyc` 含 `REVEAL_REL_FLOOR`、
  `explore_loop.pyc` 含 `MODEL_REVEAL_RATIO_MIN`、`mapsolve.pyc` 含 `camp_reveal` ✓）
- ⭐⭐ **端上实跑核对（零体力，`python tools\probe_device_vs_desktop.py`）**：
  装 arm64 **debug** 包，用 App **自己那条** `classify_image()` 路径
  （它的 docstring 就写着「零体力的端↔PC 等价性验证」）跑两张真机帧，
  再把结果与桌面逐格对拍 ⇒ **35 格 × 6 字段全部一致**（`sid/name/score/ratio/revealed/anchor`；
  浮点只留 2e-3 容差，实测端↔桌面最多差 **0.001**）
  ⇒ **证明端上跑的就是这份代码**，不是"我改了仓库、手机上是旧的" ✓
  （端侧 `spots.state()` 0.50s / 0.71s 一帧，`rev_evidence` 也是 `rel` ✓）
  ⚠ 跑完**务必装回 release 包**（别把 debug 包留给用户 ✗）

#### ⚠⚠⚠ 本轮最重要的**负面**实测：相对项在地板 0.80 下**恒不生效**

> 写进 README 是因为**下一个人极可能以为"相对法已经生效、病已全好"** ✗

相对项生效 ⟺ `p10 × 1.06 > 地板` ⟺ `p10 > 0.7547`。实测（**33 张真棋盘帧，已按图名正确消歧
+ 过 `board_hidden` 闸门**；复跑：`python tools\probe_reveal_rel_binds.py`）：

| 帧 | p10 | p10×1.06 | 相对项 |
|---|---|---|---|
| `bagdbg/board_now_ref.png`（最高的一帧） | 0.698 | 0.740 | **否** |
| `草地帧B`（S10002） | 0.649 | 0.688 | 否 |
| `草地帧A`（S10002） | 0.623 | 0.660 | 否 |
| `nubia NX809J` | 0.586 | 0.621 | 否 |

⇒ **33/33 帧相对项都没超过地板**，两臂（绝对 0.80 vs 相对法）**逐格差 0 格**
⇒ **当前 v1.60 的 `spots` 层，行为 == v1.36 的绝对 0.80**；
真正在修"已揭示被判成雾"的是**第二层**（模型层 `ratio ≥ 0.75` 覆写）✓
（门禁 v1.60 ⑯ 把这条固化：最高 p10 必须 < 0.7547，红了就说明换到了"整盘偏亮"的帧）

**根因：两端的 `ratio` 量纲不同**

| | 分母 | 雾格 | 「雾」的性质 |
|---|---|---|---|
| **PC** | **该格自己的模板亮度** | 恒 ≈**0.65**（与格子美术无关） | **一个常数** ⇒ 取 **p10**（雾下沿）就够 ✓ |
| **手机端**（v1.35 起） | **本图模板亮度中位** | **随美术亮度摊开 0.685~0.761** | **一段分布** ⇒ p10 只给**下沿** ✗ |

⇒ PC 那条 `p10×1.06` 在手机端**盖不住雾的上沿**。实测「雾上沿」落在本帧约 **80 分位**
（复跑：`python tools\probe_reveal_quantile.py`）—— 也就是说，**手机端若真要用相对法，该取的
分位是"雾上沿"（≈80 分位）而不是 PC 的 p10**，且阈值量级与经验标定的 0.80 相当 ✓
⚠ **本轮没有改这个**（用户口径是"照抄 PC"）⇒ 记为下一轮的候选，**动手前先读这一节**。

#### ⚠ 还没做的（下一轮）

- **真机复跑一局**（要 25 体力 + 重授权 MediaProjection）确认"空地连锁 / 规划步数 / 不再点雾格"；
  本轮的结论来自**离线逐格回代 + 门禁 + 端上逐格等价**，**仍不是"真跑一局"**。
- 两个回滚开关（现场可用，不用重装）：`MAPBOT_REVEAL_FLOOR`（地板，0.80 → 0.66 复现 PC 逐字）、
  `MAPBOT_MODEL_REVEAL_MIN`（模型层，0.75 → 0.80 复现 v1.36 行为）。
- ⭐ **本轮没能在真机帧上抓到"空地连锁断裂被修"的实例**：扫了 32 张真棋盘帧，
  `plain` 系格落在 `[0.75, 0.80)` 的 **0 个**（只有 1 个 ratio 0.645 的仍断，模型层也救不了
  ⇒ 那是"已揭示得还不够亮"，属另一类）⇒ v1.60 的效果**在本机 corpus 上无实证**，
  必须靠真机复跑。**注意别把这条读成"改动没用"**：用户报的「2 步的事弄成 4 步」是 v1.59
  真机日志实证的（`plan_blocks` 里相邻同 sid 两格一个 plain 一个非 plain），
  本机 corpus 只是**没有同类帧**而已。

















