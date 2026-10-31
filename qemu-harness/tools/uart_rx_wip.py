#!/usr/bin/env python3
"""WIP: UART RX (ring + IIR/IRQ) + one debug print, so we can tell whether host
bytes ever reach the model.

Applies to the VERIFIED source (sha256 3f5b6184...). Backup is named
`rk3288.c.bak_pre_uartrx` on purpose: `.bak_20261030` is the PRE-PMU-FIX backup
and must never be used to restore.
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
print('source sha before: %s' % sha0[:16])

if 'rk3288_uart_receive' in src:
    print('ALREADY_PATCHED')
    sys.exit(0)

EDITS = []

EDITS.append(("""    uint8_t scr;
    CharBackend chr;
};""", """    uint8_t scr;
    CharBackend chr;
    /* RX ring.  The console drivers poll UART_LSR.DR then read UART_RX
     * (rk_fiq_debugger.c:92-106) or take the RX interrupt, so host bytes
     * must be queued here. */
    uint8_t rx[256];
    unsigned rx_head, rx_tail;
};"""))

EDITS.append(("""static void rk3288_uart_realize(DeviceState *dev, Error **errp)""",
              """static int rk3288_uart_can_receive(void *opaque)
{
    RK3288UartState *s = opaque;

    return ((s->rx_head + 1) & 0xff) != s->rx_tail;
}

static void rk3288_uart_receive(void *opaque, const uint8_t *buf, int size)
{
    RK3288UartState *s = opaque;
    int i;

    fprintf(stderr, "[uart] RX n=%d ier=%02x\\n", size, s->ier);
    for (i = 0; i < size; i++) {
        unsigned next = (s->rx_head + 1) & 0xff;

        if (next == s->rx_tail) {
            break;
        }
        s->rx[s->rx_head] = buf[i];
        s->rx_head = next;
    }
    if (size > 0 && (s->ier & 0x01)) {
        qemu_irq_raise(s->irq);
    }
}

static void rk3288_uart_realize(DeviceState *dev, Error **errp)"""))

EDITS.append(("""    case 0:  /* RBR (no RX data) or DLL */
        return (s->lcr & 0x80) ? s->dll : 0;""",
              """    case 0:  /* RBR (RX data) or DLL */
        if (s->lcr & 0x80) {
            return s->dll;
        }
        if (s->rx_head != s->rx_tail) {
            uint8_t c = s->rx[s->rx_tail];

            s->rx_tail = (s->rx_tail + 1) & 0xff;
            if (s->rx_head == s->rx_tail) {
                qemu_irq_lower(s->irq);
            }
            return c;
        }
        return 0;"""))

EDITS.append(("""    case 2:  /* IIR: no interrupt pending (TX path is polled via LSR) */
        return 0x01;""",
              """    case 2:  /* IIR: 0x04 = received data available, 0x01 = none */
        if ((s->ier & 0x01) && s->rx_head != s->rx_tail) {
            return 0x04;
        }
        return 0x01;"""))

EDITS.append(("""    case 5:  /* LSR: THRE | TEMT always set => transmitter always ready */
        return 0x60;""",
              """    case 5:  /* LSR: THRE|TEMT (TX ready) + DR (RX data available) */
        return 0x60 | ((s->rx_head != s->rx_tail) ? 0x01 : 0);"""))

EDITS.append(("""         * 0x02 = TFNF set, BUSY/RFNE clear (no RX data available). */
        return 0x02;""",
              """         * 0x02 = TFNF; bit0 = RFNE (RX FIFO not empty). */
        return 0x02 | ((s->rx_head != s->rx_tail) ? 0x01 : 0);"""))

EDITS.append(("""    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->iomem);
    sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq);
}""",
              """    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->iomem);
    sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq);
    qemu_chr_fe_set_handlers(&s->chr, rk3288_uart_can_receive,
                             rk3288_uart_receive, NULL, NULL, s, NULL, true);
}"""))

for i, (a, b) in enumerate(EDITS):
    if src.count(a) != 1:
        sys.exit('FATAL: edit %d anchor count=%d' % (i, src.count(a)))
    src = src.replace(a, b)

bak = P + '.bak_pre_uartrx'
if not os.path.exists(bak):
    shutil.copy2(P, bak)

out = src.replace('\n', '\r\n').encode('utf-8')
tmp = P + '.tmp'
open(tmp, 'wb').write(out)
chk = open(tmp, 'rb').read()
assert chk.count(b'\r\n') == chk.count(b'\n')
os.replace(tmp, P)
print('PATCHED after=%s bytes=%d' % (hashlib.sha256(out).hexdigest()[:16], len(out)))
