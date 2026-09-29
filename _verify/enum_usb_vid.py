# -*- coding: utf-8 -*-
"""枚举注册表里的 USB 设备 VID/PID（找手机的 ADB 接口）"""
import sys
import winreg

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Enum\USB')
n = winreg.QueryInfoKey(k)[0]
print('USB 枚举键总数:', n)
for i in range(n):
    sub = winreg.EnumKey(k, i)
    up = sub.upper()
    # 只列 vivo/通用 ADB 常见 VID + 全部打印紧凑形式
    try:
        sk = winreg.OpenKey(k, sub)
        friendly, _ = winreg.QueryValueEx(sk, 'FriendlyName')
    except Exception:
        friendly = '?'
    mark = ' <== ' if ('2D95' in up or 'ADB' in up.upper() or '18D1' in up) else ''
    print('%-28s %s%s' % (sub, friendly, mark))
