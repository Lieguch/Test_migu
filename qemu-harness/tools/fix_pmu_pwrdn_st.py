#!/usr/bin/env python3
"""P0 fix: PMU PWRDN_ST per-domain bit mapping (HEVC CON bit14 -> ST bit10).

Audit: HARNESS-FAKE-AUDIT-2026-10-30.md §1
Idempotent; atomic write; keeps a timestamped backup.
"""
import hashlib
import os
import shutil
import sys

P = '/data/workspace/qemu-src/hw/arm/rk3288.c'
OLD = "    case 0x0c: v = rk3288_pmu_pwrdn_con; break;"
NEW = """    /* PWRDN_ST: 逐域把 CON 位映射到 ST 位。
     * 内核两张表（arch/arm/mach-rockchip/rk3288.c:174-186 / 234-246）：
     *   pmu_st_map: CPU0-3=0..3 BUS=5 PERI=6 VIO=7 VIDEO=8 GPU=9 HEVC=10 SCU=11
     *   pmu_pd_map: 同上，唯一例外 PD_HEVC=14
     * ⇒ 除 HEVC 外 ST/CON 同位；HEVC 必须 CON bit14 -> ST bit10。
     * 旧模型直接回显 CON，导致 PD_HEVC 断电轮询（ST bit10）永不成立：
     * 实测 PC=0xc001db78 R0=9(PD_HEVC) R1=0 R2=0x400；
     * boot_v1 0.637s / boot_v2 3.258s 均卡死于此。 */
    case 0x0c: {
        uint32_t con = rk3288_pmu_pwrdn_con;
        uint32_t st  = con & ~(1u << 10);

        if (con & (1u << 14)) {
            st |= (1u << 10);
        }
        v = st;
        break;
    }"""

src = open(P, encoding='utf-8').read()
sha_before = hashlib.sha256(src.encode()).hexdigest()

if NEW.split('\n')[0] in src:
    print('ALREADY_PATCHED sha256=%s' % sha_before)
    sys.exit(0)

if src.count(OLD) != 1:
    print('FATAL: anchor count=%d (expected 1)' % src.count(OLD))
    sys.exit(2)

bak = P + '.bak_20261030'
if not os.path.exists(bak):
    shutil.copy2(P, bak)

out = src.replace(OLD, NEW)
tmp = P + '.tmp'
with open(tmp, 'w', encoding='utf-8', newline='') as f:
    f.write(out)
chk = open(tmp, encoding='utf-8').read()
assert 'if (con & (1u << 14))' in chk, 'write verify failed'
assert chk.count('case 0x0c: {') == 1, 'duplicate case'
assert OLD not in chk, 'old line still present'
os.replace(tmp, P)
sha_after = hashlib.sha256(open(P, 'rb').read()).hexdigest()
print('PATCHED before=%s after=%s backup=%s' % (sha_before[:16], sha_after[:16], bak))
