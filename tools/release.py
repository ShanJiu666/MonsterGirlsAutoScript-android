# -*- coding: utf-8 -*-
"""发版 + 热更新推送 —— **一条命令搞定**（用户 2026-10-03：「发给朋友的怎么搞热更新？」）

    # ① 日常迭代（99% 的情况）：只推**逻辑热更补丁**，不构建、不装 APK
    python tools/release.py --hot-only --notes "修 XX 误判"

    # ② 改了 Java 壳 / 权限 / 依赖：推整包（会跑 gradle，几分钟）
    python tools/release.py --notes "壳改动说明"

    # ③ 只看要发什么、不推
    python tools/release.py --hot-only --dry-run

发给朋友的链路
--------------
    本脚本 → 公开仓库 `geng-haojie/MGAS-update`
             ├── manifest.json           （App 拉这个判断有没有新版）
             ├── hot/hot-<vc>-<sha8>.zip （逻辑补丁，1~2MB，放 raw）
             └── release 附件             （整包 APK ~71MB，放 releases/，不占仓库配额）
    朋友的 App 自己 HTTP 拉 —— **他不会打开 Gitee、不用注册、不用登录** ✓

⚠ 令牌从哪来（**绝不能写进会被 push 的文件里**，AGENTS.md 有明确要求）：
     ① 环境变量 `GITEE_TOKEN`
     ② 用户主目录 `~/.gitee_token`（推荐，已在任何仓库之外）
"""
import argparse
import base64
import getpass
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

try:                                    # GBK 控制台打中文/✓ 会炸，统一转 utf-8
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:                       # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # android_autoexplore/
GRADLE = os.path.join(ROOT, 'app', 'build.gradle')
PY_DIR = os.path.join(ROOT, 'app', 'src', 'main', 'python')
PACK_DIR = os.path.join(ROOT, 'app', 'src', 'main', 'assets', 'mapbot_pack')

OWNER = 'geng-haojie'
REPO = 'MGAS-update'
RAW = 'https://gitee.com/%s/%s/raw/master' % (OWNER, REPO)
API = 'https://gitee.com/api/v5/repos/%s/%s' % (OWNER, REPO)
MANIFEST_URL = RAW + '/manifest.json'
MANIFEST_API = API + '/contents/manifest.json'


def read_manifest_live():
    """读线上 manifest。

    ⚠⚠ **必须走 `contents` API，不能走 raw** —— 2026-10-03 实测：Gitee 的 raw 有**强缓存**，
       刚 push 的 manifest 读回来还是旧内容（加 `?t=<时间戳>` 破缓存**也无效**）。
       对本脚本的后果尤其严重：它是"读旧 manifest → 只改一段 → 写回"，
       读到旧的就会把**另一段覆盖成 null**（例：只发补丁时把 app 段丢掉 ⇒ 整包更新永久失效 ✗）。
       返回 {} 表示没有（首次发版）。
    """
    try:
        d = http_json(MANIFEST_API)
        if isinstance(d, dict) and d.get('content'):
            return json.loads(base64.b64decode(d['content']).decode('utf-8'))
        return {}
    except Exception as e:              # noqa: BLE001
        print('  · API 读清单失败（回落 raw，可能读到缓存）：%s' % e)
        try:
            return http_json(MANIFEST_URL)
        except Exception as e2:         # noqa: BLE001
            print('  · raw 也读不到（首次发版）：%s' % e2)
            return {}

# 补丁里带哪些文件：**只带 .py（顶层）** —— 解出来直接是模块名，
# 因为 Java 侧把 hot/active 插到 sys.path[0]，模块名 = 文件名 ✓
HOT_PATTERNS = ('.py',)
# 资源包（模板/数据表 ~57MB）默认**不进补丁**：它占体积、且改模板属于"大改"，走整包更稳。
#   ⇒ 真要热更资源时用 --with-pack（zip 里带 pack/ 前缀，Python 侧另行认领）。
KEEP_HOT_ZIPS = 5                      # 仓库配额有限（1GB），只留最近 5 个补丁


# ───────────────────────────── 小工具 ─────────────────────────────

def die(msg):
    print('✗ ' + msg)
    raise SystemExit(1)


def token():
    t = os.environ.get('GITEE_TOKEN', '').strip()
    if t:
        return t
    p = os.path.join(os.path.expanduser('~'), '.gitee_token')
    if os.path.isfile(p):
        with io.open(p, encoding='utf-8') as f:
            t = f.read().strip()
        if t:
            return t
    die('找不到 Gitee 令牌：设环境变量 GITEE_TOKEN，或写到 %s' % p)


def read_gradle():
    s = io.open(GRADLE, encoding='utf-8-sig').read()
    vc = re.search(r'versionCode\s+(\d+)', s)
    vn = re.search(r'versionName\s+"([^"]+)"', s)
    if not vc or not vn:
        die('读不到 versionCode/versionName：%s' % GRADLE)
    return int(vc.group(1)), vn.group(1)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def http_json(url, method='GET', body=None, timeout=60):
    data = None
    headers = {'User-Agent': 'MGAS-Release/1'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json; charset=utf-8'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8')
        return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:400]
        raise RuntimeError('HTTP %s %s → %s' % (e.code, url, detail))
    except urllib.error.URLError as e:
        raise RuntimeError('网络失败 %s → %s' % (url, e))


def upload_asset(release_id, path, tok):
    """上传 release 附件（手写 multipart —— 不引 requests，也不用 PowerShell 的 -Form）"""
    boundary = '----MGAS' + uuid.uuid4().hex
    buf = io.BytesIO()
    fn = os.path.basename(path)
    buf.write(('--%s\r\n' % boundary).encode())
    buf.write(('Content-Disposition: form-data; name="file"; filename="%s"\r\n'
               % fn).encode('utf-8'))
    buf.write(b'Content-Type: application/octet-stream\r\n\r\n')
    with open(path, 'rb') as f:
        shutil.copyfileobj(f, buf, 1 << 20)
    buf.write(('\r\n--%s--\r\n' % boundary).encode())
    body = buf.getvalue()
    url = ('%s/releases/%d/attach_files?access_token=%s'
           % (API, release_id, urllib.parse.quote(tok)))
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'multipart/form-data; boundary=%s' % boundary)
    print('    上传中…… %.1f MB' % (len(body) / 1024.0 / 1024.0))
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read().decode('utf-8'))


# ───────────────────────────── 打补丁 ─────────────────────────────

def build_hot_zip(vc, with_pack):
    """把 `app/src/main/python/*.py` 打成 zip（**顶层**，解出来就是模块名）。

    ⚠ 两个坑：
      ① **不带 `__pycache__`** —— .pyc 的 mtime 校验会让端上误用旧码，而且白占体积；
      ② **不带 `runs/` `templates/`** —— 那些是运行期目录，塞进补丁会把玩家的现场数据覆盖掉。
    """
    tmp = os.path.join(tempfile.gettempdir(), 'mgas_hot_%d.zip' % int(time.time()))
    names = []
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(PY_DIR)):
            if not fn.endswith(HOT_PATTERNS):
                continue
            full = os.path.join(PY_DIR, fn)
            if not os.path.isfile(full):
                continue
            z.write(full, fn)
            names.append(fn)
        if with_pack:
            # ⚠ 前缀 `pack/`：资源包热更的落点还没接（见 KEEP_HOT_ZIPS 注释），先支持打包
            for base, _dirs, files in os.walk(PACK_DIR):
                for f in files:
                    full = os.path.join(base, f)
                    rel = os.path.relpath(full, PACK_DIR).replace('\\', '/')
                    z.write(full, 'pack/' + rel)
                    names.append('pack/' + rel)
    return tmp, names


def hot_id(vc, zip_path):
    return 'hot-%d-%s' % (vc, sha256_file(zip_path)[:8])


# ───────────────────────────── 推仓库 ─────────────────────────────

def push_files(tok, files, commit_msg):
    """把若干文件提交进 MGAS-update（clone → 覆盖 → commit → push）。

    ⚠ 用 git 而不是 contents API：补丁是二进制 zip，API 要 base64 整个塞进 JSON body，
       又慢又容易在网关限流处被截。
    """
    work = os.path.join(tempfile.gettempdir(), 'mgas_update_push_%d' % int(time.time()))
    if os.path.exists(work):
        shutil.rmtree(work, ignore_errors=True)
    url = 'https://%s:%s@gitee.com/%s/%s.git' % (OWNER, urllib.parse.quote(tok), OWNER, REPO)
    print('  · clone %s' % REPO)
    r = subprocess.run(['git', 'clone', '--depth', '1', url, work],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        die('clone 失败：%s' % (r.stderr or r.stdout))
    for src, rel in files:
        dst = os.path.join(work, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        print('  · 写入 %s (%.1f KB)' % (rel, os.path.getsize(src) / 1024.0))
    cmds = [
        ['git', 'add', '-A'],
        ['git', '-c', 'user.name=MGAS-release', '-c', 'user.email=release@local',
         'commit', '-m', commit_msg],
        ['git', 'push', 'origin', 'master'],
    ]
    for c in cmds:
        r = subprocess.run(c, cwd=work, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            # commit 在"内容没变"时会返回非 0 —— 那不是错误
            # ⚠ 判定用 `'commit' in c`，**不是 `c[1] == 'commit'`**：commit 那条命令带
            #   `-c user.name=...` 前缀 ⇒ c[1] 是 '-c'，写成 c[1] 这个分支**永远不成立**
            if 'commit' in c and 'nothing to commit' in (r.stdout or '') + (r.stderr or ''):
                print('  · 无变化，跳过 commit')
                return work
            die('%s 失败：%s' % (' '.join(c[:3]), (r.stderr or r.stdout)[:800]))
    print('  ✓ 已推送 %s' % commit_msg)
    return work


def prune_old_hot(tok, keep=KEEP_HOT_ZIPS):
    """只留最近 keep 个补丁 zip（仓库配额 1GB，别攒爆 —— hb-web 的老教训）"""
    try:
        items = http_json('%s/contents/hot?access_token=%s' % (API, urllib.parse.quote(tok)))
    except Exception as e:              # noqa: BLE001
        print('  · 读 hot/ 目录失败（跳过清理）：%s' % e)
        return
    if not isinstance(items, list):
        return
    zips = sorted([i for i in items if i.get('name', '').endswith('.zip')],
                  key=lambda i: i.get('name', ''))
    for it in zips[:-keep] if len(zips) > keep else []:
        try:
            http_json('%s/contents/%s?access_token=%s&sha=%s&message=%s'
                      % (API, urllib.parse.quote(it['path']), urllib.parse.quote(tok),
                         it['sha'], urllib.parse.quote('prune old hot zip')),
                      method='DELETE')
            print('  · 清理旧补丁 %s' % it['name'])
        except Exception as e:          # noqa: BLE001
            print('  · 清理 %s 失败（不影响发版）：%s' % (it['name'], e))


# ───────────────────────────── 主流程 ─────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-build', action='store_true', help='跳过 gradle（APK 已在）')
    ap.add_argument('--hot-only', action='store_true', help='只发逻辑补丁（不构建、不发整包）')
    ap.add_argument('--apk-only', action='store_true', help='只发整包（不更新补丁段）')
    ap.add_argument('--notes', default='', help='更新说明（进 manifest，App 端留痕）')
    ap.add_argument('--manifest-only', action='store_true',
                    help='只重写 manifest.json（不构建、不建 release、不传附件）'
                         '—— 改 notes / 修清单时用，免得为一行文字重传 71MB')
    ap.add_argument('--with-pack', action='store_true',
                    help='补丁里带上 assets/mapbot_pack（默认不带；带≈几十 MB）')
    ap.add_argument('--min-shell', type=int, default=0,
                    help='补丁要求的最低壳版本（默认=当前 versionCode）')
    ap.add_argument('--dry-run', action='store_true', help='只生成、不推送')
    a = ap.parse_args()

    if a.hot_only and a.apk_only:
        die('--hot-only 与 --apk-only 不能同时用')

    vc, vn = read_gradle()
    tok = None if a.dry_run else token()
    print('== MGAS 发版 ==  versionName=%s versionCode=%d' % (vn, vc))

    # ① 读现有 manifest（**匿名可读**）—— 只更新要更新的那一段，另一段原样保留
    #   ⚠ 不保留的后果：只发补丁时 app 段丢了 ⇒ 端上以为"没有整包"，壳永远更不了 ✗
    old = read_manifest_live()
    if old:
        print('  · 现有 manifest 已读到（app=%s hot=%s）'
              % (bool(old.get('app')), bool(old.get('hot'))))
    else:
        print('  · 没有现有 manifest（首次发版）')

    manifest = {'schema': 1, 'updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'app': old.get('app'), 'hot': old.get('hot')}
    files = []

    # ② 逻辑补丁
    if not a.apk_only:
        zp, names = build_hot_zip(vc, a.with_pack)
        hid = hot_id(vc, zp)
        size = os.path.getsize(zp)
        sha = sha256_file(zp)
        rel = 'hot/%s.zip' % hid
        manifest['hot'] = {
            'id': hid,
            'minShell': a.min_shell or vc,
            'url': '%s/%s' % (RAW, rel),
            'size': size,
            'sha256': sha,
            'files': len(names),
            'notes': a.notes,
        }
        print('  · 补丁 %s：%d 个文件，%.1f KB，sha256=%s…'
              % (hid, len(names), size / 1024.0, sha[:12]))
        files.append((zp, rel))

    # ③ 整包（生成清单里的 app 段；配合 --no-build 就只复制不构建）
    #   ⚠ manifest-only **也要走这里** —— 目的正是"把 app 段的 sha256/size 重新算对"，
    #     只是**不往远端传附件**（见 ⑥）✓
    if not a.hot_only:
        print('  · 构建 APK（gradle assembleArm64Release）……')
        cmd = [sys.executable, os.path.join(ROOT, 'tools', 'pack_apk.py')]
        if a.no_build:
            cmd.append('--no-build')
        # ⚠ GBK 控制台下 pack_apk 末尾的 '✓' 会让它**构建成功后仍 exit 1** ⇒
        #   不显式传 utf-8 就会把"打包成功"误判成"打包失败"（2026-10-03 实测踩到）
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        r = subprocess.run(cmd, cwd=ROOT, env=env)
        if r.returncode != 0:
            die('打包失败（exit %d）' % r.returncode)
        apk = os.path.join(ROOT, 'MGAS-v%s-release.apk' % vn)
        if not os.path.isfile(apk):
            die('找不到 %s' % apk)
        asha = sha256_file(apk)
        manifest['app'] = {
            'versionCode': vc,
            'versionName': vn,
            'url': 'https://gitee.com/%s/%s/releases/download/v%s/%s'
                   % (OWNER, REPO, vn, os.path.basename(apk)),
            'size': os.path.getsize(apk),
            'sha256': asha,
            'notes': a.notes,
        }
        print('  · 整包 %s：%.1f MB，sha256=%s…'
              % (os.path.basename(apk), os.path.getsize(apk) / 1024.0 / 1024.0, asha[:12]))

    # ④ 写 manifest 并进推送清单
    mf = os.path.join(tempfile.gettempdir(), 'mgas_manifest.json')
    with io.open(mf, 'w', encoding='utf-8') as f:
        f.write(json.dumps(manifest, ensure_ascii=False, indent=2))
    files.append((mf, 'manifest.json'))
    print('  · manifest 就绪：')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if a.dry_run:
        print('\n[dry-run] 到此为止，没有推送。')
        return 0

    # ⑤ 推 manifest + 补丁
    push_files(tok, files, 'release v%s (%s)' % (vn, a.notes or 'update'))
    prune_old_hot(tok)

    # ⑥ 推整包（release 附件）
    if not a.hot_only and not a.manifest_only:
        apk = os.path.join(ROOT, 'MGAS-v%s-release.apk' % vn)
        tag = 'v%s' % vn
        try:
            rel = http_json('%s/releases?access_token=%s' % (API, urllib.parse.quote(tok)),
                            method='POST',
                            body={'access_token': tok, 'tag_name': tag, 'name': tag,
                                  'body': a.notes or ('MGAS %s' % vn),
                                  'target_commitish': 'master'})
        except Exception as e:          # noqa: BLE001
            rel = None
            print('  · 建 release 失败（可能已存在，改用查已有）：%s' % e)
        if rel is None or not rel.get('id'):
            rels = http_json('%s/releases?access_token=%s' % (API, urllib.parse.quote(tok)))
            match = [r for r in (rels or []) if r.get('tag_name') == tag]
            if not match:
                die('既建不了 release 也找不到 tag=%s' % tag)
            rel = match[0]
        print('  · release %s (id=%s)，上传附件……' % (tag, rel.get('id')))
        # ⚠ 先删同名旧附件：**重发同一版本号时**，那个 URL 下必须换成新包
        #   （manifest 里的 sha256 已经变了；Gitee 的同名 attach 要么冲突要么留两份，
        #    留两份的话下载会拿到旧的 ⇒ 端上 sha256 校验失败 ✗）
        try:
            atts = http_json('%s/releases/%d/attach_files?access_token=%s'
                             % (API, rel['id'], urllib.parse.quote(tok)))
            for at in (atts or []):
                if at.get('name') == os.path.basename(apk):
                    http_json('%s/releases/%d/attach_files/%d?access_token=%s'
                              % (API, rel['id'], at['id'], urllib.parse.quote(tok)),
                              method='DELETE')
                    print('  · 已删除同名旧附件 %s' % at['name'])
        except Exception as e:          # noqa: BLE001
            print('  · 查/删旧附件失败（继续尝试上传）：%s' % e)
        att = upload_asset(rel['id'], apk, tok)
        print('  ✓ 附件已上传：%s' % att.get('browser_download_url'))

    print('\n✓ 发版完成 v%s' % vn)
    print('  清单：%s' % MANIFEST_URL)
    if manifest.get('hot'):
        print('  补丁：%s' % manifest['hot']['url'])
    if manifest.get('app'):
        print('  整包：%s' % manifest['app']['url'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
