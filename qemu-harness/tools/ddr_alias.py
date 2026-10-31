#!/usr/bin/env python3
"""Back the DDR register window at 0xfedd0000 too.

Evidence (faithful boot, stock kernel, factory DTB, empty cmdline):
  first real fault is a WRITE with DFSR 0x808 / DFAR 0xfedd00c0
  (= RK_DDR_VIRT + 0xc0).  The CI kernel's iomap maps virt 0xfedd0000 to
  phys 0xff610000, but the vendor kernel evidently reaches a physical
  0xfedd0000 that nothing backs, so the bus returns an external abort.
  0xfedd0000 sits below the 0xff000000 catch-all window and above RAM, i.e.
  it is simply unmapped.  Back it with the same DDR ops.
"""
import hashlib
import os
import sys

P = '/data/workspace/qemu-src/hw/arm/rk3288.c'
raw = open(P, 'rb').read()
if raw.count(b'\r\n') != raw.count(b'\n'):
    sys.exit('FATAL: mixed line endings')
src = raw.decode('utf-8').replace('\r\n', '\n')
sha0 = hashlib.sha256(raw).hexdigest()
print('before %s' % sha0[:16])

if 'rk3288-ddr-alias' in src:
    print('ALREADY')
    sys.exit(0)

ANCHOR = """    rk3288_add_io(sysmem, RK3288_DDR_BASE,  RK3288_DDR_SIZE, &rk3288_ddr_ops, "rk3288-ddr");"""
ADD = """    rk3288_add_io(sysmem, RK3288_DDR_BASE,  RK3288_DDR_SIZE, &rk3288_ddr_ops, "rk3288-ddr");
    /* 0xfedd0000 = RK_DDR_VIRT.  The CI kernel maps it to phys 0xff610000, but the
     * vendor kernel reaches a *physical* 0xfedd0000 (DFSR 0x808 / DFAR 0xfedd00c0,
     * a write) which sat below the 0xff000000 catch-all and above RAM, i.e. was
     * unmapped -> external abort -> abort handler recursion.  Back it. */
    rk3288_add_io(sysmem, 0xfedd0000ULL, RK3288_DDR_SIZE, &rk3288_ddr_ops,
                  "rk3288-ddr-alias");"""

if src.count(ANCHOR) != 1:
    sys.exit('FATAL: anchor count=%d' % src.count(ANCHOR))
src = src.replace(ANCHOR, ADD)

bak = P + '.bak_pre_ddralias'
if not os.path.exists(bak):
    import shutil
    shutil.copy2(P, bak)

out = src.replace('\n', '\r\n').encode('utf-8')
tmp = P + '.tmp'
open(tmp, 'wb').write(out)
assert open(tmp, 'rb').read().count(b'\r\n') == open(tmp, 'rb').read().count(b'\n')
os.replace(tmp, P)
print('PATCHED after=%s' % hashlib.sha256(out).hexdigest()[:16])
