#!/usr/bin/env python3
"""QEMU monitor client v3: TLB mapping for the polled VA, its live value,
and a kernel-memory string sweep around the LR region (kallsyms strings)."""
import re
import socket

PATH = '/tmp/qmon.sock'


def drain(s, timeout=2.0):
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


s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(PATH)
drain(s, 1.0)

print('=== x /16xb 0xfed2000c (polled value) ===')
print(cmd(s, 'x /16xb 0xfed2000c'))
print('=== x /16xb 0xfed20000 ===')
print(cmd(s, 'x /16xb 0xfed20000'))
print('=== info tlb ===')
print(cmd(s, 'info tlb'))

# sweep kernel strings near LR data region: dump 0xc0757000..0xc0759000
print('=== string sweep near 0xc0757000 ===')
text = ''
for base in range(0xc0756000, 0xc075a000, 0x400):
    out = cmd(s, 'x /256xb 0x%08x' % base, 3.0)
    for line in out.splitlines():
        m = re.match(r'^\s*([0-9a-f]{8,16}):\s*((?:0x[0-9a-f]{2}\s*)+)$', line)
        if m:
            addr = int(m.group(1), 16)
            for i, h in enumerate(re.findall(r'0x([0-9a-f]{2})', m.group(2))):
                text += chr(int(h, 16)) if 0x20 <= int(h, 16) < 0x7f else '\x00'
for m in re.finditer(r'[\x20-\x7e]{6,}', text):
    print(m.group(0))
s.close()
