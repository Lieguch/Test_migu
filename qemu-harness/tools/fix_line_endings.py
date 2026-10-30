#!/usr/bin/env python3
"""Restore CRLF line endings so the patch stays a single semantic hunk.

The first patch pass used text-mode read (universal newlines) + newline=''
write, which silently converted the whole file CRLF->LF (-1545 bytes).
This script re-applies CRLF and verifies byte-level diff scope against the backup.
"""
import os
import sys

P = '/data/workspace/qemu-src/hw/arm/rk3288.c'
BAK = P + '.bak_20261030'

raw_bak = open(BAK, 'rb').read()
crlf = raw_bak.count(b'\r\n')
lf = raw_bak.count(b'\n')
print('backup: bytes=%d crlf=%d lf_total=%d' % (len(raw_bak), crlf, lf))
if crlf != lf:
    print('WARN: backup is not uniformly CRLF; aborting normalization')
    sys.exit(3)

cur = open(P, 'rb').read()
if b'\r\n' in cur:
    print('ALREADY_CRLF bytes=%d' % len(cur))
    sys.exit(0)

out = cur.replace(b'\n', b'\r\n')
tmp = P + '.tmp'
with open(tmp, 'wb') as f:
    f.write(out)
chk = open(tmp, 'rb').read()
assert chk.count(b'\r\n') == chk.count(b'\n'), 'mixed endings'
os.replace(tmp, P)

# verify: line-level diff against backup must be exactly the PMU hunk
a = raw_bak.decode('utf-8').split('\r\n')
b = open(P, 'rb').read().decode('utf-8').split('\r\n')
import difflib
d = [l for l in difflib.unified_diff(a, b, 'bak', 'new', lineterm='', n=0) if l[:1] in '+-' and not l.startswith(('+++', '---'))]
print('changed_lines=%d bytes=%d (bak %d)' % (len(d), len(open(P, 'rb').read()), len(raw_bak)))
print('removed:')
for l in d:
    if l.startswith('-'):
        print('  ' + l)
print('added(first 6):')
for l in [x for x in d if x.startswith('+')][:6]:
    print('  ' + l)
