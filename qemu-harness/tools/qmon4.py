#!/usr/bin/env python3
"""qmon4: dump the full spinning function (0xc001dae0..0xc001dc40) for
offline disassembly, and sample the polled register twice."""
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

blob = {}
for base in range(0xc001dae0, 0xc001dc40, 0x100):
    blob.update(parse_hexdump(cmd(s, 'x /128xb 0x%08x' % base)))

print('=== polled register 0xfed2000c (sample 1) ===')
print(cmd(s, 'x /4xb 0xfed2000c'))
time.sleep(2)
print('=== polled register 0xfed2000c (sample 2, +2s) ===')
print(cmd(s, 'x /4xb 0xfed2000c'))
print('=== PC again ===')
regs = cmd(s, 'info registers')
print(re.search(r'R15=[0-9a-f]+', regs).group(0) if 'R15=' in regs else regs)

# write the function dump as a binary for offline objdump
buf = bytes(blob.get(a, 0xff) for a in range(min(blob), max(blob) + 1))
with open('/data/workspace/spin_func.bin', 'wb') as f:
    f.write(buf)
print('=== wrote spin_func.bin: %d bytes, base 0x%08x ===' % (len(buf), min(blob)))

with open('/tmp/hexdump.txt', 'w') as f:
    for a in range(min(blob), max(blob) + 1, 16):
        row = ' '.join('%02x' % blob.get(a, 0xff) for a in range(a, min(a + 16, max(blob) + 1)))
        f.write('%08x: %s\n' % (a, row))
print('=== hexdump.txt written ===')
s.close()
