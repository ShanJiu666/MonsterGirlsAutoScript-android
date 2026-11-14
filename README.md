# MGAS Android · 游戏探索自动刷图工具（安卓端）

> 截屏 → 端侧 OCR / 模板匹配 → 无障碍手势点击，自动跑游戏的「探索」玩法。
>
> **不做**：不读改游戏内存、不注入进程、不改网络数据包、不改游戏文件、不需要 root。
> 纯视觉 + 模拟输入，等价于「有个手在替你点」。

---

## 先读这个

### 我只是想用，不想编译

去 **[Releases](../../releases)** 下最新的 `MGAS-vX.Y-release.apk` 装上即可。

> 第一次装系统会问「是否允许安装未知应用」—— 安卓对所有非商店 APK 都会问。
> 本应用**不会**自己下载整包：App 内「检查更新」只取几百 KB 的逻辑补丁。

### 我下的是源码

| 想找什么 | 去哪 |
|---|---|
| 决策层（纯 Python，19 个模块） | `app/src/main/python/` |
| Java 壳（截图 / 手势 / 悬浮条 / 更新） | `app/src/main/java/com/fantasy/autoexplore/` |
| 识别资源（模板 / 配表） | `app/src/main/assets/mapbot_pack/` |
| 回归门禁（1294 条断言） | `tools/verify_explore_slots_fix.py` |
| 出包 / 发版 / 热更 | `tools/` |
| **逐版改动档案（证据档）** | **[CHANGELOG.md](CHANGELOG.md)** |

---

## 装上之后（三步授权，各点一次）

1. **① 授权截图** —— MediaProjection 录屏权限（**每次重装都会掉**，掉了要重给）
2. **② 无障碍设置** —— 点击通道（常驻）
3. **③ 悬浮窗权限** —— 悬浮条显示用

然后：**诊断页 → ▶ 准备启动**（开悬浮条 + 切游戏）→ 在悬浮条上点 **▶** 真启动；`■` 停止。

---

## 更新

App 内「检查更新」只下载**逻辑补丁**（几百 KB，重启 App 生效）。
壳 / 权限 / 资源包有改动时，到 [Releases](../../releases) 取新 APK 手动装 —— 刻意设计，不偷偷装整包。

---

## 反馈

QQ 反馈群 **1067971799**（App 诊断页也有入口）。
反馈前先点一次「一键反馈」，它会把日志 + 机型 + 现场帧打成 zip。

---

## 构建与门禁

```bash
export JAVA_HOME=<你的 jdk17>
gradle assembleArm64Release        # 真机包；模拟器用 assembleFullDebug

# 改完必跑（必须带 utf-8，否则 GBK 打印崩、失败清单被吞）
PYTHONIOENCODING=utf-8 python tools/verify_explore_slots_fix.py
```

---

## 免责与许可

使用前请读 **[DISCLAIMER.md](DISCLAIMER.md)**：本软件免费开源（[MIT](LICENSE)）、纯视觉自动化，
可能违反游戏用户协议、账号风险自担，与游戏厂商无任何关联。
