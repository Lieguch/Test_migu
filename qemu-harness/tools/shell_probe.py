#!/usr/bin/env python3
"""Drive the guest shell over a unix serial socket: wait for the prompt, run cmds, dump output.

Usage: shell_probe.py /tmp/ser.sock 'cmd1' 'cmd2' ...
"""
import os
import socket
import sys
import time

PATH = sys.argv[1]
CMDS = sys.argv[2:]

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(PATH)


def read(t=3.0, cap=200000):
    s.settimeout(t)
    out = b''
    try:
        while True:
            b = s.recv(65536)
            if not b:
                break
            out += b
            if len(out) > cap:
                break
    except socket.timeout:
        pass
    return out.decode('utf-8', 'replace')


buf = ''
deadline = time.time() + 240
while time.time() < deadline:
    buf += read(3.0)
    if 'msh' in buf and '#' in buf.split('msh')[-1]:
        break
print('--- boot tail ---')
print(buf[-400:])

for c in CMDS:
    s.sendall((c + '\n').encode())
    time.sleep(1.2)
    out = read(4.0)
    print('=== $ %s' % c)
    print(out)
    buf += out

s.close()
