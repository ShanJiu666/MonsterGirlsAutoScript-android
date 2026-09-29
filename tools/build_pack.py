# -*- coding: utf-8 -*-
"""build_pack.py · 把 PC 端 mapbot 的运行期资源打成 Android assets/mapbot_pack

规则
----
* `templates/unit/<code>/<sid>/` 全量有 ~640 帧/sid（动画帧），但 PC 端 spots.py
  的 `_TPL_FRAMES` 默认只取 **每 sid 排序后前 3 帧** ⇒ 只打包前 3 帧，
  结果与 PC 逐字节一致（21.7MB → 2.3MB）。
  ⚠ 之后 Android 端 **不能** 再用 `MAPBOT_TPL_FRAMES=0` 回退（帧不在包里）。
* `templates/` 其余子目录（marks/items/area*/explore_purple）与根目录散图全带。
* 数据表只带一份：`unpack_apk/dump/server_datatable.json`
  （已核 `Area_Spot` 与 fetch_20260924 版**逐字节一致**，差异只在 Bond/Relics/Sub_Skill）。
"""
import os
import shutil

SRC = r'D:\幻想少女公会\tools\mapbot'
DST = r'D:\幻想少女公会\android_autoexplore\app\src\main\assets\mapbot_pack'
DT = r'D:\幻想少女公会\unpack_apk\dump\server_datatable.json'

UNIT_KEEP = 3          # 与 spots._TPL_FRAMES 默认值一致

stats = {}


def cp(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    stats['files'] = stats.get('files', 0) + 1
    stats['bytes'] = stats.get('bytes', 0) + os.path.getsize(src)


def main():
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    os.makedirs(DST, exist_ok=True)

    tsrc = os.path.join(SRC, 'templates')
    tdst = os.path.join(DST, 'templates')
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

    cp(DT, os.path.join(DST, 'server_datatable.json'))

    print(f"打包完成 → {DST}")
    print(f"  文件数 {stats['files']}  体积 {stats['bytes']/1e6:.1f} MB")
    print(f"  unit 模板：保留 {unit_kept} 帧，丢弃 {unit_all} 帧（磁盘省 {stats['bytes']/1e6:.1f} MB 中的大部分）")


if __name__ == '__main__':
    main()
