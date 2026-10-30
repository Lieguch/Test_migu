#!/usr/bin/env python3
"""QEMU monitor client v2: two PC samples + guest-VIRTUAL memory dumps
(uses 'x' so MMU translation works) for offline disassembly."""
import re
import socket

PATH = '/tmp/qmon.sock'


def drain(s, timeout=1.5):
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

pcs = []
for i in range(3):
    regs = cmd(s, 'info registers')
    m = re.search(r'R15=([0-9a-f]+)', regs)
    pc = int(m.group(1), 16) if m else None
    pcs.append(pc)
    print('sample %d: PC=%s LR=%s' % (
        i + 1,
        '0x%08x' % pc if pc else None,
        re.search(r'R14=([0-9a-f]+)', regs).group(1) if 'R14=' in regs else '?'))
    import time
    time.sleep(1.0)

if pcs[0]:
    pc = pcs[0]
    for addr, label in ((pc - 0x60, 'PC-0x60'), (pc, 'PC'), (pc + 0x20, 'PC+0x20')):
        out = cmd(s, 'x /48xb 0x%08x' % addr, 2.0)
        # keep only the hex data lines
        lines = [l for l in out.splitlines() if ':' in l and re.match(r'^[0-9a-f]{8,16}:', l.strip())]
        print('--- x at [%s] 0x%08x ---' % (label, addr))
        for l in lines:
            print(l)
    lr = int(re.search(r'R14=([0-9a-f]+)', cmd(s, 'info registers')).group(1), 16)
    out = cmd(s, 'x /48xb 0x%08x' % (lr - 0x10), 2.0)
    lines = [l for l in out.splitlines() if ':' in l and re.match(r'^[0-9a-f]{8,16}:', l.strip())]
    print('--- x at [LR-0x10] 0x%08x ---' % (lr - 0x10))
    for l in lines:
        print(l)
s.close()
