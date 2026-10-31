#!/usr/bin/env python3
"""Boot the CI kernel, wait for the shell, run a command set, write a report.

Everything is written to REPORT (unbuffered), so a killed parent loses nothing.
"""
import os
import socket
import subprocess
import sys
import time

WS = '/data/workspace'
SOCK = '/tmp/ser_shell.sock'
REPORT = WS + '/shell_report.txt'
QERR = WS + '/shell_qemu.err'

CMDS = [
    'cat /proc/version',
    'ls -l /dev/input',
    'grep -iE "goodix|gt9|88" /proc/interrupts | head -8',
    'ls /sys/bus/i2c/devices 2>/dev/null',
    'dmesg | tail -6',
]


def log(f, msg):
    f.write(msg + '\n')
    f.flush()


f = open(REPORT, 'w')
for p in (SOCK,):
    try:
        os.unlink(p)
    except OSError:
        pass

qemu = subprocess.Popen(
    ['./qemu-src/build/qemu-system-arm', '-machine', 'rk3288', '-m', '512',
     '-kernel', 'zImage', '-dtb', 'p817_v2.dtb', '-initrd', 'initramfs_sh.cpio',
     '-append', 'console=ttyS2,115200 init=/init rdinit=/init panic=1',
     '-serial', 'unix:%s,server,nowait' % SOCK, '-display', 'none'],
    cwd=WS, stderr=open(QERR, 'w'), stdout=subprocess.DEVNULL)
log(f, 'qemu pid=%d' % qemu.pid)

# wait for the socket
for _ in range(60):
    if os.path.exists(SOCK):
        break
    time.sleep(1)

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(SOCK)


def read(t=3.0):
    s.settimeout(t)
    out = b''
    try:
        while True:
            b = s.recv(65536)
            if not b:
                break
            out += b
            if len(out) > 400000:
                break
    except socket.timeout:
        pass
    return out.decode('utf-8', 'replace')


buf = ''
deadline = time.time() + 200
while time.time() < deadline:
    chunk = read(3.0)
    buf += chunk
    if 'msh#' in buf or 'msh #' in buf:
        break
log(f, '--- prompt seen: %s' % ('YES' if ('msh#' in buf or 'msh #' in buf) else 'NO'))
log(f, 'boot tail:\n' + buf[-500:])

for c in CMDS:
    s.sendall((c + '\n').encode())
    time.sleep(1.5)
    out = read(4.0)
    log(f, '\n=== $ %s\n%s' % (c, out.strip()))

s.close()
qemu.terminate()
log(f, '\nDONE')
f.close()
