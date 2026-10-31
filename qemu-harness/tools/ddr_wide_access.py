#!/usr/bin/env python3
"""Allow 64-bit accesses to the DDR register window.

The first real fault in the faithful boot is DFSR 0x808 / DFAR 0xfedd00c0
(RK_DDR_VIRT + 0xc0, a WRITE, synchronous external abort).  The DDR ops
declared max_access_size = 4, so a 64-bit store from the guest (strd / lrd)
is rejected by QEMU as an invalid access -> external abort -> the abort
handler re-faults -> machine dies.  Real hardware accepts the wider access.
"""
import hashlib
import os
import shutil
import sys

P = '/data/workspace/qemu-src/hw/arm/rk3288.c'
raw = open(P, 'rb').read()
if raw.count(b'\r\n') != raw.count(b'\n'):
    sys.exit('FATAL: mixed line endings')
src = raw.decode('utf-8').replace('\r\n', '\n')
sha0 = hashlib.sha256(raw).hexdigest()
print('before %s' % sha0[:16])
if 'RK3288_DDR_WIDE' in src:
    print('ALREADY')
    sys.exit(0)

A_READ = """static uint64_t rk3288_ddr_read(void *opaque, hwaddr off, unsigned size)
{
    unsigned blk = off >> 12;          /* 0=PCTL0 1=PUBL0 2=PCTL1 3=PUBL1 */
    hwaddr  rel = off & 0xfff;
    uint32_t v;"""
B_READ = """static uint64_t rk3288_ddr_read(void *opaque, hwaddr off, unsigned size)
{
    unsigned blk = off >> 12;          /* 0=PCTL0 1=PUBL0 2=PCTL1 3=PUBL1 */
    hwaddr  rel = off & 0xfff;
    uint32_t v;

    /* RK3288_DDR_WIDE: the guest issues 64-bit loads/stores here; split them
     * instead of letting QEMU reject the access size (which surfaces as an
     * external abort -> abort-handler recursion). */
    if (size == 8) {
        uint64_t lo = rk3288_ddr_read(opaque, off, 4);
        uint64_t hi = rk3288_ddr_read(opaque, off + 4, 4);

        return lo | (hi << 32);
    }"""

A_WRITE = """static void rk3288_ddr_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
    unsigned blk = off >> 12;"""
B_WRITE = """static void rk3288_ddr_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
    unsigned blk = off >> 12;

    if (size == 8) {
        rk3288_ddr_write(opaque, off, val & 0xffffffffu, 4);
        rk3288_ddr_write(opaque, off + 4, val >> 32, 4);
        return;
    }"""

A_OPS = """static const MemoryRegionOps rk3288_ddr_ops = {
    .read = rk3288_ddr_read, .write = rk3288_ddr_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};"""
B_OPS = """static const MemoryRegionOps rk3288_ddr_ops = {
    .read = rk3288_ddr_read, .write = rk3288_ddr_write,
    .valid.min_access_size = 1, .valid.max_access_size = 8,
    .endianness = DEVICE_NATIVE_ENDIAN,
};"""

for a, b, tag in ((A_READ, B_READ, 'read'), (A_WRITE, B_WRITE, 'write'), (A_OPS, B_OPS, 'ops')):
    if src.count(a) != 1:
        sys.exit('FATAL: anchor %s count=%d' % (tag, src.count(a)))
    src = src.replace(a, b)

bak = P + '.bak_pre_wide'
if not os.path.exists(bak):
    shutil.copy2(P, bak)

out = src.replace('\n', '\r\n').encode('utf-8')
tmp = P + '.tmp'
open(tmp, 'wb').write(out)
assert open(tmp, 'rb').read().count(b'\r\n') == open(tmp, 'rb').read().count(b'\n')
os.replace(tmp, P)
print('PATCHED after=%s' % hashlib.sha256(out).hexdigest()[:16])
