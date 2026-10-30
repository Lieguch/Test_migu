#!/usr/bin/env python3
"""QEMU monitor client: dump CPU state and memory around PC for offline
disassembly. Connects to the unix-socket monitor of a running QEMU."""
import re
import socket
import sys
import time

PATH = '/tmp/qmon.sock'


def drain(s, timeout=1.0):
    s.settimeout(timeout)
    out = b''
    try:
        while True:
            b = s.recv(8192)
            if not b:
                break
            out += b
            if len(out) > 262144:
                break
    except socket.timeout:
        pass
    return out


def cmd(s, c, timeout=2.0):
    s.sendall((c + '\n').encode())
    return drain(s, timeout).decode('utf-8', 'replace')


s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(PATH)
drain(s, 1.0)

print('=== info status ===')
print(cmd(s, 'info status'))
print('=== info cpus ===')
print(cmd(s, 'info cpus'))

for i in range(2):
    print('=== info registers (sample %d) ===' % (i + 1))
    regs = cmd(s, 'info registers')
    print(regs)
    m = re.search(r'\b(?:R15|PC)\s*=?\s*([0-9a-fA-Fx]{8,10})', regs)
    if m and i == 0:
        pc = int(m.group(1).replace('0x', ''), 16)
        time.sleep(1.0)
        break
else:
    pc = None

if pc is not None:
    print('PC = 0x%08x' % pc)
    for i, addr in enumerate((pc - 0x40, pc - 0x8, pc)):
        out = cmd(s, 'xp /64xb 0x%08x' % addr, 2.0)
        print('--- xp at 0x%08x ---' % addr)
        print(out)
s.close()
