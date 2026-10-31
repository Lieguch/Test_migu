#!/usr/bin/env python3
"""List the late_initcall (level 6) table around ddrfreq_init, symbolized.

The kernel crashed right after ddrfreq_init() printed its table, so the entry
that follows it in __initcall6_start[] is the first suspect.
"""
import struct
import subprocess

ELF = '/data/workspace/stock_vmlinux.elf'
START = 0xc0bb3bfc      # __initcall6_start
END = 0xc0bb46d8        # __con_initcall_start (end of the initcall arrays)
TARGET = 0xc0027508     # ddrfreq_init

data = open(ELF, 'rb').read()
segs = []
out = subprocess.run(['arm-linux-gnueabihf-readelf', '-lW', ELF],
                     capture_output=True, text=True).stdout
for line in out.splitlines():
    p = line.split()
    if len(p) >= 6 and p[0] == 'LOAD':
        segs.append((int(p[1], 16), int(p[2], 16), int(p[4], 16)))


def read(va, n):
    for off, vaddr, filesz in segs:
        if vaddr <= va < vaddr + filesz:
            fo = off + (va - vaddr)
            return data[fo:fo + n]
    return None


syms = subprocess.run(['arm-linux-gnueabihf-nm', '-n', ELF],
                      capture_output=True, text=True).stdout
table = []
for line in syms.splitlines():
    p = line.split()
    if len(p) >= 3:
        try:
            table.append((int(p[0], 16), p[2]))
        except ValueError:
            pass
table.sort()


def sym(a):
    lo, hi, best = 0, len(table) - 1, ('?', 0)
    while lo <= hi:
        mid = (lo + hi) // 2
        if table[mid][0] <= a:
            best = (table[mid][1], a - table[mid][0])
            lo = mid + 1
        else:
            hi = mid - 1
    return '%s+0x%x' % best


n = (END - START) // 4
buf = read(START, n * 4)
vals = list(struct.unpack('<%dI' % n, buf))
print('entries:', n)
for i, v in enumerate(vals):
    mark = '   <<< ddrfreq_init' if v == TARGET else ''
    if TARGET == v:
        idx = i
    print('%3d  0x%08x  %s%s' % (i, v, sym(v), mark))

print('\n--- neighbours of ddrfreq_init ---')
for j in range(max(0, idx - 2), min(n, idx + 6)):
    print('%3d  0x%08x  %s%s' % (j, vals[j], sym(vals[j]),
                                 '   <<< ddrfreq_init' if j == idx else ''))
