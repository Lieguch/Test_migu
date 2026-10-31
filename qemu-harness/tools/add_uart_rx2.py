#!/usr/bin/env python3
"""UART RX stage 2: raise the UART IRQ and report IIR=0x04 while data is pending.

rk_serial's console RX is interrupt-driven: it enables IER.RDI, and on IRQ reads
IIR to find out *why*. The model previously returned IIR=0x01 ("no interrupt")
forever, so even with bytes queued the driver never drained them.
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

if 'UART_IIR_RX' in src:
    print('ALREADY_PATCHED')
    sys.exit(0)

A1 = """    case 2:  /* IIR: no interrupt pending (TX path is polled via LSR) */
        return 0x01;"""
B1 = """    case 2:  /* IIR: 0x04 = "received data available" while RX is pending,
              * 0x01 = no interrupt.  rk_serial's ISR keys off this value. */
        if ((s->ier & 0x01) && s->rx_head != s->rx_tail) {
            return 0x04;                        /* UART_IIR_RX */
        }
        return 0x01;"""

A2 = """        if (s->rx_head != s->rx_tail) {
            uint8_t c = s->rx[s->rx_tail];

            s->rx_tail = (s->rx_tail + 1) & 0xff;
            return c;
        }
        return 0;"""
B2 = """        if (s->rx_head != s->rx_tail) {
            uint8_t c = s->rx[s->rx_tail];

            s->rx_tail = (s->rx_tail + 1) & 0xff;
            if (s->rx_head == s->rx_tail) {
                qemu_irq_lower(s->irq);         /* FIFO drained */
            }
            return c;
        }
        return 0;"""

A3 = """        s->rx[s->rx_head] = buf[i];
        s->rx_head = next;
    }
}"""
B3 = """        s->rx[s->rx_head] = buf[i];
        s->rx_head = next;
    }
    if (size > 0 && (s->ier & 0x01)) {
        qemu_irq_raise(s->irq);                 /* IER.RDI: data ready */
    }
}"""

for a, b, tag in ((A1, B1, 'IIR'), (A2, B2, 'drain'), (A3, B3, 'raise')):
    if src.count(a) != 1:
        sys.exit('FATAL: anchor %s count=%d' % (tag, src.count(a)))
    src = src.replace(a, b)

bak = P + '.bak_uartrx2'
if not os.path.exists(bak):
    shutil.copy2(P, bak)

out = src.replace('\n', '\r\n').encode('utf-8')
tmp = P + '.tmp'
open(tmp, 'wb').write(out)
chk = open(tmp, 'rb').read()
assert chk.count(b'\r\n') == chk.count(b'\n')
os.replace(tmp, P)
print('PATCHED before=%s after=%s' % (sha0[:16], hashlib.sha256(out).hexdigest()[:16]))
