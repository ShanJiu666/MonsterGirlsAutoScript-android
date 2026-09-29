# -*- coding: utf-8 -*-
"""扫手机的无线调试连接端口（32768~60999 随机）"""
import socket
import sys
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
IP = '192.168.2.7'
LO, HI = 30000, 61000

def probe(port):
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect((IP, port))
        return port
    except Exception:
        return None
    finally:
        s.close()

open_ports = []
with ThreadPoolExecutor(max_workers=400) as ex:
    for r in ex.map(probe, range(LO, HI)):
        if r:
            open_ports.append(r)
print('开放端口:', open_ports)
