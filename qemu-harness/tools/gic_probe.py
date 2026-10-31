#!/usr/bin/env python3
"""Did the raised UART IRQ actually reach the GIC? Send a byte, then read
GICD_ISPENDR1 (0xffc01204) and GICD_ISENABLER1 (0xffc01104) over QMP.

SPI 57 (serial2) = bit 25 of word 1.
"""
import json
import os
import socket
import subprocess
import time

WS = '/data/workspace'
SER = '/tmp/ser_gic.sock'
QMP = '/tmp/qmp_gic.sock'
OUT = WS + '/gic_probe.txt'
ERR = WS + '/gic_qemu.err'

f = open(OUT, 'w')


def log(m):
    f.write(m + '\n')
    f.flush()


for p in (SER, QMP):
    try:
        os.unlink(p)
    except OSError:
        pass

q = subprocess.Popen(
    ['./qemu-src/build/qemu-system-arm', '-machine', 'rk3288', '-m', '512',
     '-kernel', 'zImage', '-dtb', 'p817_v2.dtb', '-initrd', 'initramfs_msh2.cpio',
     '-append', 'console=ttyS2,115200 init=/init rdinit=/init panic=1',
     '-serial', 'unix:%s,server,nowait' % SER,
     '-qmp', 'unix:%s,server,nowait' % QMP, '-display', 'none'],
    cwd=WS, stderr=open(ERR, 'w'), stdout=subprocess.DEVNULL)
log('qemu pid=%d' % q.pid)

for _ in range(90):
    if os.path.exists(SER) and os.path.exists(QMP):
        break
    time.sleep(1)

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(SER)
buf = ''
t0 = time.time()
while time.time() - t0 < 150:
    s.settimeout(3.0)
    try:
        buf += s.recv(65536).decode('utf-8', 'replace')
    except socket.timeout:
        pass
    if 'msh#' in buf:
        break
log('prompt=%s' % ('msh#' in buf))

m = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
m.connect(QMP)
m.settimeout(3.0)


def qmp(cmd, args=None):
    body = {'execute': cmd}
    if args:
        body['arguments'] = args
    m.sendall((json.dumps(body) + '\n').encode())
    out = b''
    t = time.time()
    while time.time() - t < 3:
        try:
            out += m.recv(65536)
        except socket.timeout:
            break
        if b'"return"' in out or b'"error"' in out:
            break
    return out.decode('utf-8', 'replace')


def hmp(line):
    r = qmp('human-monitor-command', {'command-line': line})
    try:
        return json.loads(r)['return']
    except Exception:
        return r


try:
    m.recv(4096)                       # greeting
except socket.timeout:
    pass
qmp('qmp_capabilities')

log('--- before input ---')
log('ISPENDR1 : ' + hmp('xp /1xw 0xffc01204').strip())
log('ISENABLER1: ' + hmp('xp /1xw 0xffc01104').strip())

s.sendall(b'x')
time.sleep(2.0)
log('--- after one byte ---')
log('ISPENDR1 : ' + hmp('xp /1xw 0xffc01204').strip())
log('ISENABLER1: ' + hmp('xp /1xw 0xffc01104').strip())
log('rx_hits: %d' % open(ERR, errors='replace').read().count('[uart] RX'))

s.close()
m.close()
q.terminate()
log('DONE')
f.close()
