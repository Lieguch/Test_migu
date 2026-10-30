#!/usr/bin/env python3
"""Scan p817.dtb for the node at 0xffaf0000 and list vpu/vcodec-related nodes."""
import re
import struct

D = '/data/workspace/p817.dtb'
d = open(D, 'rb').read()

print("=== occurrences of u32 ffaf0000 (BE) ===")
for m in re.finditer(b'\xff\xaf\x00\x00', d):
    s, e = max(0, m.start() - 96), min(len(d), m.end() + 96)
    txt = re.findall(rb'[\x20-\x7e]{4,}', d[s:e])
    print('@%#x:' % m.start(), b' | '.join(txt)[:240])

print("\n=== counts of interesting strings ===")
for pat in (b'vpu', b'vcodec', b'vpu_service', b'vopb', b'vopl', b'edp', b'hdmi',
            b'gpu', b'iep', b'rga', b'vop'):
    print('%-14s %d' % (pat.decode(), d.count(pat)))

# --- minimal FDT walk: dump node names with reg/address ---
# header
magic, totalsize, off_dt_struct, off_dt_strings, off_mem_rsvmap, version, size_dt_strings, size_dt_struct = struct.unpack('>8I', d[:32])
print("\nFDT magic=%08x totalsize=%d off_struct=%d off_strings=%d ver=%d"
      % (magic, totalsize, off_dt_struct, off_dt_strings, version))
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9
strings = d[off_dt_strings:off_dt_strings + size_dt_strings]

def cstr(o):
    e = strings.index(b'\x00', o)
    return strings[o:e].decode('utf-8', 'replace')

p = off_dt_struct
depth = 0
path = []
events = []
while p < off_dt_struct + size_dt_struct:
    tag = struct.unpack('>I', d[p:p + 4])[0]
    p += 4
    if tag == FDT_BEGIN_NODE:
        e = d.index(b'\x00', p)
        name = d[p:e].decode('utf-8', 'replace')
        p = (e + 1 + 3) & ~3
        path.append(name)
        if any(k in name for k in ('vpu', 'vcodec', 'vop', 'iep', 'gpu', 'hdmi',
                                   'edp', 'rga', 'video')):
            print('NODE: /' + '/'.join(path))
    elif tag == FDT_END_NODE:
        if path:
            path.pop()
    elif tag == FDT_PROP:
        ln, noff = struct.unpack('>II', d[p:p + 8])
        p += 8
        val = d[p:p + ln]
        p = (p + ln + 3) & ~3
        name = cstr(noff)
        if name in ('reg', 'compatible', 'status'):
            if len(path) > 0 and any(k in '/'.join(path) for k in
                                     ('vpu', 'vcodec', 'vop', 'iep', 'gpu', 'hdmi')):
                if name == 'reg':
                    print('   reg of /%s = %s' % ('/'.join(path),
                          ' '.join('%08x' % struct.unpack('>I', val[i:i+4])[0]
                                   for i in range(0, len(val) - 3, 4))))
                else:
                    print('   %s of /%s = %r' % (name, '/'.join(path), val))
    elif tag == FDT_NOP:
        continue
    elif tag == FDT_END:
        break
