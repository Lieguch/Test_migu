#!/usr/bin/env python3
"""Add UART RX to the rk3288 harness model so the guest shell can be driven.

Before: RBR always 0 and LSR had no DR bit -> the fiq debugger's debug_getc()
(rk_fiq_debugger.c:92-106, reads UART_LSR & UART_LSR_DR then UART_RX) never saw
input, so `msh#` accepted nothing. Now the chardev feeds a 256-byte ring.

CRLF-safe: the file is uniformly CRLF; patch on LF, write back as CRLF.
"""
import hashlib
import os
import shutil
import sys

P = '/data/workspace/qemu-src/hw/arm/rk3288.c'
raw = open(P, 'rb').read()
if raw.count(b'\r\n') != raw.count(b'\n'):
    sys.exit('FATAL: mixed line endings, refusing to patch')
src = raw.decode('utf-8').replace('\r\n', '\n')
sha0 = hashlib.sha256(raw).hexdigest()

if 'RK_UART_RX_SIZE' in src:
    print('ALREADY_PATCHED %s' % sha0[:16])
    sys.exit(0)

A1 = """    uint8_t scr;
    CharBackend chr;
};"""
B1 = """    uint8_t scr;
    CharBackend chr;
    /* RX ring: the fiq debugger polls UART_LSR.DR then reads UART_RX
     * (rk_fiq_debugger.c:92-106), so bytes must actually be queued here. */
    uint8_t rx[256];
    unsigned rx_head, rx_tail;
};"""

A2 = """    case 0:  /* RBR (no RX data) or DLL */
        return (s->lcr & 0x80) ? s->dll : 0;"""
B2 = """    case 0:  /* RBR (RX data) or DLL */
        if (s->lcr & 0x80) {
            return s->dll;
        }
        if (s->rx_head != s->rx_tail) {
            uint8_t c = s->rx[s->rx_tail];

            s->rx_tail = (s->rx_tail + 1) & 0xff;
            return c;
        }
        return 0;"""

A3 = """    case 5:  /* LSR: THRE | TEMT always set => transmitter always ready */
        return 0x60;"""
B3 = """    case 5:  /* LSR: THRE|TEMT (TX ready) + DR (RX data available) */
        return 0x60 | ((s->rx_head != s->rx_tail) ? 0x01 : 0);"""

A4 = """         * 0x02 = TFNF set, BUSY/RFNE clear (no RX data available). */
        return 0x02;"""
B4 = """         * 0x02 = TFNF set; bit0 = RFNE (RX FIFO not empty). */
        return 0x02 | ((s->rx_head != s->rx_tail) ? 0x01 : 0);"""

A5 = """    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->iomem);
    sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq);
}"""
B5 = """    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->iomem);
    sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq);
    /* Wire the chardev so host -> guest bytes reach the RX ring. */
    qemu_chr_fe_set_handlers(&s->chr, rk3288_uart_can_receive,
                             rk3288_uart_receive, NULL, NULL, s, NULL, true);
}"""

A6 = """static void rk3288_uart_realize(DeviceState *dev, Error **errp)"""
B6 = """static int rk3288_uart_can_receive(void *opaque)
{
    RK3288UartState *s = opaque;

    return ((s->rx_head + 1) & 0xff) != s->rx_tail;
}

static void rk3288_uart_receive(void *opaque, const uint8_t *buf, int size)
{
    RK3288UartState *s = opaque;
    int i;

    for (i = 0; i < size; i++) {
        unsigned next = (s->rx_head + 1) & 0xff;

        if (next == s->rx_tail) {
            break;                      /* full: drop, like an overrun */
        }
        s->rx[s->rx_head] = buf[i];
        s->rx_head = next;
    }
}

static void rk3288_uart_realize(DeviceState *dev, Error **errp)"""

for a, b, tag in ((A1, B1, 'struct'), (A2, B2, 'RBR'), (A3, B3, 'LSR'),
                  (A4, B4, 'USR'), (A5, B5, 'realize'), (A6, B6, 'handlers')):
    if src.count(a) != 1:
        sys.exit('FATAL: anchor %s count=%d' % (tag, src.count(a)))
    src = src.replace(a, b)

bak = P + '.bak_uartrx'
if not os.path.exists(bak):
    shutil.copy2(P, bak)

out = src.replace('\n', '\r\n').encode('utf-8')
tmp = P + '.tmp'
open(tmp, 'wb').write(out)
chk = open(tmp, 'rb').read()
assert chk.count(b'\r\n') == chk.count(b'\n'), 'line endings broken'
assert b'rk3288_uart_receive' in chk and b'RK_UART_RX_SIZE' not in chk
os.replace(tmp, P)
print('PATCHED before=%s after=%s bytes=%d' % (sha0[:16], hashlib.sha256(out).hexdigest()[:16], len(out)))
