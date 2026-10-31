#!/usr/bin/env python3
"""Find where the value 0xea000663 lives in the kernel image and map it to a symbol."""
import struct
import subprocess

ELF = '/data/workspace/stock_vmlinux.elf'
VALUE = 0xea000663

data = open(ELF, 'rb').read()
pat = struct.pack('<I', VALUE)
offs = []
i = data.find(pat)
while i >= 0 and len(offs) < 10:
    offs.append(i)
    i = data.find(pat, i + 1)
print('occurrences:', len(offs), offs)

# map file offset -> vaddr using program headers
segs = []
out = subprocess.run(['arm-linux-gnueabihf-readelf', '-lW', ELF],
                     capture_output=True, text=True).stdout
for line in out.splitlines():
    p = line.split()
    if len(p) >= 6 and p[0] == 'LOAD':
        off, vaddr, filesz = int(p[1], 16), int(p[2], 16), int(p[4], 16)
        segs.append((off, vaddr, filesz))

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


def sym(addr):
    lo, hi = 0, len(table) - 1
    best = ('?', 0)
    while lo <= hi:
        mid = (lo + hi) // 2
        if table[mid][0] <= addr:
            best = (table[mid][1], addr - table[mid][0])
            lo = mid + 1
        else:
            hi = mid - 1
    return '%s+0x%x' % best


for o in offs:
    va = None
    for off, vaddr, filesz in segs:
        if off <= o < off + filesz:
            va = vaddr + (o - off)
            break
    if va:
        print('  offset 0x%x -> vaddr 0x%x  %s' % (o, va, sym(va)))
    else:
        print('  offset 0x%x -> (not in a LOAD segment)' % o)
