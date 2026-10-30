#!/usr/bin/env python3
"""qmon5: dump the FULL region around the spinning PC in 32-byte chunks
(no gaps), twice over 2s, so the loop can be disassembly-decoded exactly."""
import re
import socket
import time

PATH = '/tmp/qmon.sock'


def drain(s, timeout=2.5):
    s.settimeout(timeout)
    out = b''
    try:
        while True:
            b = s.recv(8192)
            if not b:
                break
            out += b
            if len(out) > 524288:
                break
    except socket.timeout:
        pass
    return out


def cmd(s, c, timeout=3.0):
    s.sendall((c + '\n').encode())
    return drain(s, timeout).decode('utf-8', 'replace')


def parse_hexdump(out):
    data = {}
    for line in out.splitlines():
        m = re.match(r'^\s*([0-9a-f]{8,16}):\s*((?:0x[0-9a-f]{2}\s*)+)$', line)
        if m:
            addr = int(m.group(1), 16)
            for i, h in enumerate(re.findall(r'0x([0-9a-f]{2})', m.group(2))):
                data[addr + i] = int(h, 16)
    return data


s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(PATH)
drain(s, 1.0)

pcs = []
words = {}
for i in range(2):
    regs = cmd(s, 'info registers')
    m = re.search(r'R15=([0-9a-f]+)', regs)
    lr = re.search(r'R14=([0-9a-f]+)', regs)
    pc = int(m.group(1), 16) if m else 0
    pcs.append(pc)
    words[i] = {
        'R0': re.search(r'R00=([0-9a-f]+)', regs).group(1),
        'R1': re.search(r'R01=([0-9a-f]+)', regs).group(1),
        'R2': re.search(r'R02=([0-9a-f]+)', regs).group(1),
        'R3': re.search(r'R03=([0-9a-f]+)', regs).group(1),
        'R12': re.search(r'R12=([0-9a-f]+)', regs).group(1),
        'PC': '%08x' % pc,
        'LR': lr.group(1) if lr else '?',
    }
    time.sleep(2.0)

for i, w in words.items():
    print('sample %d: %s' % (i + 1, w))

pc = pcs[0]
if pc:
    blob = {}
    for base in range(pc - 0x100, pc + 0x80, 0x20):  # 32-byte chunks: no gaps
        blob.update(parse_hexdump(cmd(s, 'x /32xb 0x%08x' % base)))
    buf = bytes(blob.get(a, 0xff) for a in range(min(blob), max(blob) + 1))
    with open('/data/workspace/spin_v2.bin', 'wb') as f:
        f.write(buf)
    with open('/data/workspace/spin_v2.info', 'w') as f:
        f.write('base=0x%08x pc=0x%08x\n' % (min(blob), pc))
        f.write('regs=%r\n' % words)
    print('wrote spin_v2.bin %d bytes base 0x%08x' % (len(buf), min(blob)))
s.close()
