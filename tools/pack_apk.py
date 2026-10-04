# -*- coding: utf-8 -*-
"""打包产物命名 —— **统一格式：`MGAS-v<版本号>-release.apk`**（用户 2026-10-02 定）

    python tools/pack_apk.py            # 构建后调用：把 app-arm64-release.apk 换成规范名
    python tools/pack_apk.py --no-build # 只改名（APK 已经在）

规范（用户原话「之后 apk 命名格式为 MGAS-v版本号-release」）：
    `MGAS-v1.32-release.apk`      ← 交付用（版本号取自 `app/build.gradle` 的 versionName ✓）
    `MGAS.apk`                    ← 固定别名，永远指向**最新那一版**（方便 adb install ✓）

⚠ 版本号**现场读 build.gradle**，不写死 ✗（v1.20 就栽在"包是 120、git 里是 119"）
⚠ 全程用 Python 复制：PowerShell 的 `Set-Content`/重定向会加 BOM 或毁二进制 ✗
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # android_autoexplore/
GRADLE = os.path.join(ROOT, 'app', 'build.gradle')

# ⚠ 2026-10-03 实测踩到：本机 pwsh 是 GBK 控制台，脚本末尾 print('…✓…') 会抛
#   UnicodeEncodeError ⇒ **APK 明明已经复制好了，退出码却是 1** ⇒ 调用方
#   （tools/release.py）会误判"打包失败"✗ 教训同 AGENTS §2「PYTHONIOENCODING 别省」。
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:                       # noqa: BLE001
    pass
BUILT = os.path.join(ROOT, 'app', 'build', 'outputs', 'apk', 'arm64', 'release',
                     'app-arm64-release.apk')


def version_name():
    s = io.open(GRADLE, encoding='utf-8-sig').read()
    m = re.search(r'versionName\s+"([^"]+)"', s)
    if not m:
        raise SystemExit('读不到 versionName：%s' % GRADLE)
    return m.group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-build', action='store_true', help='跳过 gradle 构建')
    a = ap.parse_args()
    if not a.no_build:
        env = dict(os.environ)
        env['JAVA_HOME'] = env.get('JAVA_HOME') or r'D:\android-build\jdk17\jdk-17.0.20+8'
        env['CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD'] = '200000'
        r = subprocess.run([r'D:\android-build\gradle-8.7\bin\gradle.bat', 'assembleArm64Release'],
                           cwd=ROOT, env=env)
        if r.returncode != 0:
            raise SystemExit('构建失败（exit %d）' % r.returncode)
    if not os.path.exists(BUILT):
        raise SystemExit('找不到构建产物：%s' % BUILT)
    ver = version_name()
    dst = os.path.join(ROOT, 'MGAS-v%s-release.apk' % ver)
    shutil.copyfile(BUILT, dst)
    shutil.copyfile(BUILT, os.path.join(ROOT, 'MGAS.apk'))
    print('规范名：%s（%.1f MB）' % (os.path.basename(dst),
                                    os.path.getsize(dst) / 1024.0 / 1024.0))
    print('固定别名：MGAS.apk（永远指向最新 ✓）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
