#!/usr/bin/env python3
"""Insert a forward declaration for rk3288_hit_note (used by the new CRU/GRF
models that sit above its definition)."""
import hashlib
import os
import sys

P = '/data/workspace/qemu-src/hw/arm/rk3288.c'
DECL = 'static void rk3288_hit_note(int region, hwaddr off, const char *who, uint32_t val);'
ANCHOR = 'static uint32_t rk3288_cru_regs[RK3288_CRU_SIZE / 4];'

raw = open(P, 'rb').read()
if raw.count(b'\r\n') != raw.count(b'\n'):
    sys.exit('FATAL: mixed line endings')
src = raw.decode('utf-8').replace('\r\n', '\n')
if DECL in src:
    print('ALREADY')
    sys.exit(0)
if src.count(ANCHOR) != 1:
    sys.exit('FATAL: anchor count=%d' % src.count(ANCHOR))
src = src.replace(ANCHOR, DECL + '\n\n' + ANCHOR)
out = src.replace('\n', '\r\n').encode('utf-8')
tmp = P + '.tmp'
open(tmp, 'wb').write(out)
chk = open(tmp, 'rb').read()
assert chk.count(b'\r\n') == chk.count(b'\n')
os.replace(tmp, P)
print('FORWARD_DECL_OK %s' % hashlib.sha256(out).hexdigest()[:16])
