#!/usr/bin/env python3
"""Remove the stale 'Echo con directly' comment left above the patched case."""
import os

P = '/data/workspace/qemu-src/hw/arm/rk3288.c'
STALE = """    /* PWRDN_ST: per-domain power status.  Measured 2026-10-22 (t65): the
     * power-domain handshake helper (0xc0021bfc) wrote PWRDN_CON = 0x80
     * (bit7) and polled PWRDN_ST for the SAME bit (mask 0x80), i.e. the
     * ST ack bit is 1:1 with the CON enable bit (RK3288 TRM:
     * pd_vio_pwr_st = 1<<7 == the vio pwren bit).  Echo con directly. */
"""
src = open(P, encoding='utf-8').read()
if STALE not in src:
    print('STALE_COMMENT_ABSENT (already clean)')
else:
    out = src.replace(STALE, '')
    tmp = P + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(out)
    chk = open(tmp, encoding='utf-8').read()
    assert 'Echo con directly' not in chk
    assert 'if (con & (1u << 14))' in chk
    os.replace(tmp, P)
    print('STALE_COMMENT_REMOVED')
