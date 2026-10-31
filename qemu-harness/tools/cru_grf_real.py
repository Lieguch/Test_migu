#!/usr/bin/env python3
"""Replace the two FAKE blocks (CRU + GRF reading 0xFFFFFFFF everywhere) with a
register-file model, and give GRF only the one thing the kernel actually waits
for: the PLL lock bits.

Evidence for 0x284 / bits 5..9 — the P817 DTB itself declares every PLL's
status register (p817.dts pll_cons):
    aPLL status-reg = <0x284 6>   dPLL <0x284 5>   cPLL <0x284 7>
    gPLL <0x284 8>                nPLL <0x284 9>
and clk-pll.c:180 polls `grf_readl(status_offset) & (1 << status_shift)`.
Reading 0xFFFFFFFF for the whole 4 KiB (old model) also faked every clock-gate,
reset and pinctrl status bit — which is exactly what the audit flagged (S1-A).
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
if 'rk3288_grf_read' in src:
    print('ALREADY_PATCHED')
    sys.exit(0)

OLD_BLOCK = """/* A region whose reads answer 0xFFFFFFFF (every lock/status bit set) and
 * whose writes are dropped.  Used for CRU + GRF so that the RK clock
 * driver's pll_wait_lock() polling completes instead of deadlocking. */
static uint64_t rk3288_allones_read(void *opaque, hwaddr off, unsigned size)
{
    return 0xFFFFFFFF;
}

static void rk3288_allones_write(void *opaque, hwaddr off, uint64_t val,
                                 unsigned size)
{
    /* dropped */
}

static const MemoryRegionOps rk3288_allones_ops = {
    .read = rk3288_allones_read,
    .write = rk3288_allones_write,
    .valid.min_access_size = 1,
    .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

static void rk3288_add_allones(MemoryRegion *sysmem, hwaddr base,
                               hwaddr size, const char *name)
{
    MemoryRegion *r = g_new(MemoryRegion, 1);
    memory_region_init_io(r, NULL, &rk3288_allones_ops, NULL, name, size);
    memory_region_add_subregion(sysmem, base, r);
}"""

NEW_BLOCK = """/* CRU / GRF as register files (writes stored, reads return what was written),
 * NOT as "read 0xFFFFFFFF".  The old all-ones stub made every clock-gate state,
 * reset state and pinctrl mux/pull/drv bit read back as 1 — a whole 4 KiB of
 * fabricated state (audit S1-A).
 *
 * The one status the kernel genuinely polls is the PLL lock bit, and the DTB
 * names it explicitly (p817.dts pll_cons, status-reg):
 *     aPLL <0x284 6>  dPLL <0x284 5>  cPLL <0x284 7>  gPLL <0x284 8>  nPLL <0x284 9>
 * clk-pll.c:180 waits on grf_readl(status_offset) & (1 << status_shift), so GRF
 * offset 0x284 reports those five bits as locked.  Everything else is 0 until
 * the guest writes it. */
static uint32_t rk3288_cru_regs[RK3288_CRU_SIZE / 4];
static uint32_t rk3288_grf_regs[RK3288_GRF_SIZE / 4];

#define RK3288_GRF_PLL_STATUS 0x284u
#define RK3288_GRF_PLL_LOCKED 0x000003e0u   /* bits 5..9 = dPLL,cPLL,aPLL,gPLL,nPLL */

static uint64_t rk3288_cru_read(void *opaque, hwaddr off, unsigned size)
{
    uint32_t v = (off / 4 < RK3288_CRU_SIZE / 4) ? rk3288_cru_regs[off / 4] : 0;

    rk3288_hit_note(4, off, "cru", v);
    return v;
}

static void rk3288_cru_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
    if (off / 4 < RK3288_CRU_SIZE / 4) {
        rk3288_cru_regs[off / 4] = val;
    }
}

static uint64_t rk3288_grf_read(void *opaque, hwaddr off, unsigned size)
{
    uint32_t v = (off / 4 < RK3288_GRF_SIZE / 4) ? rk3288_grf_regs[off / 4] : 0;

    if (off == RK3288_GRF_PLL_STATUS) {
        v |= RK3288_GRF_PLL_LOCKED;
    }
    rk3288_hit_note(5, off, "grf", v);
    return v;
}

static void rk3288_grf_write(void *opaque, hwaddr off, uint64_t val, unsigned size)
{
    if (off / 4 < RK3288_GRF_SIZE / 4) {
        rk3288_grf_regs[off / 4] = val;
    }
}

static const MemoryRegionOps rk3288_cru_ops = {
    .read = rk3288_cru_read, .write = rk3288_cru_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

static const MemoryRegionOps rk3288_grf_ops = {
    .read = rk3288_grf_read, .write = rk3288_grf_write,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .endianness = DEVICE_NATIVE_ENDIAN,
};"""

CALL_OLD = """    rk3288_add_allones(sysmem, RK3288_CRU_BASE, RK3288_CRU_SIZE, "rk3288-cru");
    rk3288_add_allones(sysmem, RK3288_GRF_BASE, RK3288_GRF_SIZE, "rk3288-grf");"""
CALL_NEW = """    rk3288_add_io(sysmem, RK3288_CRU_BASE, RK3288_CRU_SIZE, &rk3288_cru_ops, "rk3288-cru");
    rk3288_add_io(sysmem, RK3288_GRF_BASE, RK3288_GRF_SIZE, &rk3288_grf_ops, "rk3288-grf");"""

HIT_OLD = "static uint8_t rk3288_hit[4][RK3288_LOG_WORDS / 32];"
HIT_NEW = "static uint8_t rk3288_hit[6][RK3288_LOG_WORDS / 32];"

for a, b, tag in ((OLD_BLOCK, NEW_BLOCK, 'block'), (CALL_OLD, CALL_NEW, 'calls'),
                  (HIT_OLD, HIT_NEW, 'hit')):
    if src.count(a) != 1:
        sys.exit('FATAL: anchor %s count=%d' % (tag, src.count(a)))
    src = src.replace(a, b)

bak = P + '.bak_pre_crugrf'
if not os.path.exists(bak):
    shutil.copy2(P, bak)

out = src.replace('\n', '\r\n').encode('utf-8')
tmp = P + '.tmp'
open(tmp, 'wb').write(out)
chk = open(tmp, 'rb').read()
assert chk.count(b'\r\n') == chk.count(b'\n')
os.replace(tmp, P)
print('PATCHED after=%s bytes=%d' % (hashlib.sha256(out).hexdigest()[:16], len(out)))
