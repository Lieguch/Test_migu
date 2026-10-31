#!/usr/bin/env python3
"""Does a host byte ever reach the UART model? Boot, wait for the shell, type, check stderr."""
import os
import socket
import subprocess
import time

WS = '/data/workspace'
SOCK = '/tmp/ser_rx.sock'
ERR = WS + '/rx_test.err'
OUT = WS + '/rx_test.txt'

f = open(OUT, 'w')


def log(m):
    f.write(m + '\n')
    f.flush()


try:
    os.unlink(SOCK)
except OSError:
    pass

q = subprocess.Popen(
    ['./qemu-src/build/qemu-system-arm', '-machine', 'rk3288', '-m', '512',
     '-kernel', 'zImage', '-dtb', 'p817_v4.dtb', '-initrd', 'initramfs_msh2.cpio',
     '-append', 'console=ttyS2,115200 init=/init rdinit=/init panic=1',
     '-serial', 'unix:%s,server,nowait' % SOCK, '-display', 'none'],
    cwd=WS, stderr=open(ERR, 'w'), stdout=subprocess.DEVNULL)
log('qemu pid=%d' % q.pid)

for _ in range(90):
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
            if len(out) > 300000:
                break
    except socket.timeout:
        pass
    return out.decode('utf-8', 'replace')


buf = ''
t0 = time.time()
while time.time() - t0 < 150:
    buf += read(3.0)
    if 'msh#' in buf:
        break
log('prompt=%s after %.0fs' % ('msh#' in buf, time.time() - t0))

# type a few bytes; also try CR
for payload in (b'echo hi\r', b'\r', b'abc\n'):
    s.sendall(payload)
    time.sleep(2.0)
    got = read(3.0)
    log('sent %r -> guest bytes %r' % (payload, got[-120:]))

time.sleep(1)
s.close()
q.terminate()
time.sleep(1)

err = open(ERR, 'r', errors='replace').read()
hits = [l for l in err.splitlines() if l.startswith('[uart] RX')]
log('uart_rx_hits=%d' % len(hits))
for l in hits[:5]:
    log('  ' + l)
log('DONE')
f.close()
