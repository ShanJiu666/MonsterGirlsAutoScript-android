# -*- coding: utf-8 -*-
"""build_pack.py · 把 PC 端 mapbot 的运行期资源打成 Android assets/mapbot_pack

规则
----
* templates/unit/<code>/<sid>/ 全量有 ~640 帧/sid（动画帧），但 PC 端 spots.py
  的 _TPL_FRAMES 默认只取 **每 sid 排序后前 3 帧** ⇒ 只打包前 3 帧，
  结果与 PC 逐字节一致（21.7MB → 2.3MB）。
  ⚠ 之后 Android 端 **不能** 再用 MAPBOT_TPL_FRAMES=0 回退（帧不在包里）。
* templates/ 其余子目录（marks/items/area*/explore_purple）与根目录散图全带。
* 数据表只带一份：server_datatable.json
  （已核 Area_Spot 与 fetch_20260924 版**逐字节一致**，差异只在 Bond/Relics/Sub_Skill）。

路径（2026-11 修：以前写死 D:\幻想少女公会\… ⇒ 在本仓跑会往**另一个仓**建资源，
却照样打印「打包完成」，属于静默做错事。现在全部由 __file__ 推导）
----
仓根 = 本文件（<仓根>/tools/build_pack.py）所在 tools/ 的父目录。

  SRC (PC 端 mapbot 源)  env MAPBOT_PACK_SRC
                        默认 <仓根>/../mapbot_pc → <仓根>/tools/mapbot（历史布局）
  DT  (游戏配表)         env MAPBOT_PACK_DT
                        默认 <仓根>/../data/server_datatable.json
                             → <仓根>/app/src/main/assets/mapbot_pack/server_datatable.json（仓内已打包那份）
  DST (打进 APK 的资源)  env MAPBOT_PACK_DST
                        默认 <仓根>/app/src/main/assets/mapbot_pack

用法
----
    python tools/build_pack.py            # 真打包（**会先清空 DST 再重建**）
    python tools/build_pack.py --check    # 只读自检：打印三个路径 + 是否存在 + 退出码
    python tools/build_pack.py --paths    # 同 --check（别名）

退出码：0 = 成功 / 自检通过；2 = 路径或输入不合格（源不存在、目录为空、配表缺失）。
⚠ 输入不合格时**一个文件都不写、一个字都不打印「完成」**。
"""
import os
import shutil
import sys

try:                                    # Windows 管道下也别让中文变乱码
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)            # 仓根 = tools/ 的父目录（由 __file__ 推导）

ENV_SRC = 'MAPBOT_PACK_SRC'
ENV_DT = 'MAPBOT_PACK_DT'
ENV_DST = 'MAPBOT_PACK_DST'

SRC_CANDIDATES = (
    os.path.join(REPO, os.pardir, 'mapbot_pc'),                      # 容器布局：PC 仓与本仓同级
    os.path.join(REPO, 'tools', 'mapbot'),                           # 历史布局：mapbot 曾在本仓 tools/ 下
)
DT_CANDIDATES = (
    os.path.join(REPO, os.pardir, 'data', 'server_datatable.json'),  # 容器布局：共享配表
    os.path.join(REPO, 'app', 'src', 'main', 'assets', 'mapbot_pack',
                 'server_datatable.json'),                           # 兜底：仓内已打包的那份
)
DST_DEFAULT = os.path.join(REPO, 'app', 'src', 'main', 'assets', 'mapbot_pack')

UNIT_KEEP = 3          # 与 spots._TPL_FRAMES 默认值一致

stats = {}


def _resolve(env_name, candidates):
    """返回 (绝对路径, 来源说明)。env 优先；否则取第一个存在的候选；都不存在就给首个候选。"""
    raw = (os.environ.get(env_name) or '').strip()
    if raw:
        return os.path.abspath(raw), 'env ' + env_name
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c), '默认候选'
    return os.path.abspath(candidates[0]), '默认候选（不存在）'


def resolve_all():
    src, src_from = _resolve(ENV_SRC, SRC_CANDIDATES)
    dt, dt_from = _resolve(ENV_DT, DT_CANDIDATES)
    raw_dst = (os.environ.get(ENV_DST) or '').strip()
    dst = os.path.abspath(raw_dst) if raw_dst else DST_DEFAULT
    dst_from = 'env ' + ENV_DST if raw_dst else '默认'
    return src, src_from, dst, dst_from, dt, dt_from


def _count_files(root):
    n = 0
    for _dirpath, _dirnames, filenames in os.walk(root):
        n += len(filenames)
    return n


def check_inputs(src, dt):
    """返回错误清单（空 = 合格）。**只读**：不建目录、不删文件。"""
    errs = []
    if not os.path.isdir(src):
        errs.append('SRC 源目录不存在：%s（用环境变量 %s 覆盖）' % (src, ENV_SRC))
    else:
        tsrc = os.path.join(src, 'templates')
        if not os.path.isdir(tsrc):
            errs.append('SRC 下没有 templates/：%s' % tsrc)
        else:
            n = _count_files(tsrc)
            if n == 0:
                errs.append('SRC 源目录为空（templates/ 下 0 个文件）：%s' % tsrc)
    if not os.path.isfile(dt):
        errs.append('DT 配表不存在或不是文件：%s（用环境变量 %s 覆盖）' % (dt, ENV_DT))
    return errs


def print_paths():
    """--check / --paths：只读打印三处解析结果，绝不写任何文件。"""
    src, src_from, dst, dst_from, dt, dt_from = resolve_all()
    tsrc = os.path.join(src, 'templates')
    print('=' * 78)
    print('build_pack 路径自检（只读，不会覆盖 assets）')
    print('=' * 78)
    print('仓根 REPO : %s' % REPO)
    print('            （= 本文件所在 tools/ 的父目录，由 __file__ 推导）')
    print('SRC 源    : %s  [%s]  %s' % (src, src_from, '存在' if os.path.isdir(src) else '缺失'))
    print('            templates/ %s%s'
          % ('存在' if os.path.isdir(tsrc) else '缺失',
             '，%d 个文件' % _count_files(tsrc) if os.path.isdir(tsrc) else ''))
    print('DST 目标  : %s  [%s]  %s（输出路径；自检不会碰它）'
          % (dst, dst_from, '已存在' if os.path.isdir(dst) else '尚未生成'))
    print('DT  配表  : %s  [%s]  %s' % (dt, dt_from, '存在' if os.path.isfile(dt) else '缺失'))
    print('-' * 78)
    errs = check_inputs(src, dt)
    if errs:
        for e in errs:
            print('✗ ' + e)
        print('⇒ 自检失败（输入不合格），退出码 2')
        return 2
    print('✓ 输入合格（SRC / DT 均可打包）；DST 属输出，不参与判定')
    return 0


def cp(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    stats['files'] = stats.get('files', 0) + 1
    stats['bytes'] = stats.get('bytes', 0) + os.path.getsize(src)


def main():
    src, src_from, dst, dst_from, dt, dt_from = resolve_all()

    # ⚠ 校验必须在**任何破坏性操作之前** —— 否则源不对时 DST 已被清空，等于又静默干了坏事
    errs = check_inputs(src, dt)
    if errs:
        print('✗ build_pack 中止：输入不合格，未写入任何文件。', file=sys.stderr)
        for e in errs:
            print('  ✗ ' + e, file=sys.stderr)
        print('  提示：python tools/build_pack.py --check 可只看路径', file=sys.stderr)
        return 2

    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)

    tsrc = os.path.join(src, 'templates')
    tdst = os.path.join(dst, 'templates')
    unit_kept = unit_all = 0

    for dirpath, dirnames, filenames in os.walk(tsrc):
        dirnames.sort()
        rel = os.path.relpath(dirpath, tsrc)
        rel_parts = rel.split(os.sep) if rel != '.' else []
        # templates/unit/<code>/<sid>/*.png —— 只留前 UNIT_KEEP 帧
        if len(rel_parts) == 3 and rel_parts[0] == 'unit':
            for i, fn in enumerate(sorted(filenames)):
                if i < UNIT_KEEP:
                    cp(os.path.join(dirpath, fn), os.path.join(tdst, rel, fn))
                    unit_kept += 1
                else:
                    unit_all += 1
            continue
        for fn in sorted(filenames):
            cp(os.path.join(dirpath, fn), os.path.join(tdst, rel, fn) if rel_parts else os.path.join(tdst, fn))

    cp(dt, os.path.join(dst, 'server_datatable.json'))

    print(f"打包完成 → {dst}")
    print(f"  源 SRC {src} [{src_from}]")
    print(f"  配表 DT {dt} [{dt_from}]")
    print(f"  文件数 {stats['files']}  体积 {stats['bytes']/1e6:.1f} MB")
    print(f"  unit 模板：保留 {unit_kept} 帧，丢弃 {unit_all} 帧（磁盘省 {stats['bytes']/1e6:.1f} MB 中的大部分）")
    return 0


if __name__ == '__main__':
    args = list(sys.argv[1:])
    if not args:
        sys.exit(main())
    if args[0] in ('--check', '--paths'):
        sys.exit(print_paths())
    if args[0] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)
    print('✗ 未知参数：%s（只支持 --check / --paths / -h）' % ' '.join(args), file=sys.stderr)
    sys.exit(2)
