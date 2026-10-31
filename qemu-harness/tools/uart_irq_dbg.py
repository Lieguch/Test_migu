#!/usr/bin/env python3
"""Instrument the UART IRQ path: log raise / IIR read / RBR pop, to tell whether
the guest's ISR actually runs after a host byte arrives."""
import hashlib
import os
import sys

P = '/data/workspace/qemu-src/hw/arm/rk3288.c'
raw = open(P, 'rb').read()
if raw.count(b'\r\n') != raw.count(b'\n'):
    sys.exit('FATAL: mixed line endings')
src = raw.decode('utf-8').replace('\r\n', '\n')
if 'DBG_IRQ' in src:
    print('ALREADY')
    sys.exit(0)

EDITS = [
    ("""    if (size > 0 && (s->ier & 0x01)) {
        qemu_irq_raise(s->irq);
    }""",
     """    if (size > 0 && (s->ier & 0x01)) {
        fprintf(stderr, "[uart] DBG_IRQ raise\\n");
        qemu_irq_raise(s->irq);
    }"""),
    ("""    case 2:  /* IIR: 0x04 = received data available, 0x01 = none */
        if ((s->ier & 0x01) && s->rx_head != s->rx_tail) {
            return 0x04;
        }
        return 0x01;""",
     """    case 2:  /* IIR: 0x04 = received data available, 0x01 = none */
        if ((s->ier & 0x01) && s->rx_head != s->rx_tail) {
            fprintf(stderr, "[uart] DBG_IIR=04\\n");
            return 0x04;
        }
        return 0x01;"""),
    ("""            s->rx_tail = (s->rx_tail + 1) & 0xff;
            if (s->rx_head == s->rx_tail) {""",
     """            s->rx_tail = (s->rx_tail + 1) & 0xff;
            fprintf(stderr, "[uart] DBG_POP %02x\\n", c);
            if (s->rx_head == s->rx_tail) {"""),
]

for i, (a, b) in enumerate(EDITS):
    if src.count(a) != 1:
        sys.exit('FATAL: edit %d count=%d' % (i, src.count(a)))
    src = src.replace(a, b)

out = src.replace('\n', '\r\n').encode('utf-8')
tmp = P + '.tmp'
open(tmp, 'wb').write(out)
assert open(tmp, 'rb').read().count(b'\r\n') == open(tmp, 'rb').read().count(b'\n')
os.replace(tmp, P)
print('INSTRUMENTED %s' % hashlib.sha256(out).hexdigest()[:16])
