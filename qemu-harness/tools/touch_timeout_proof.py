#!/usr/bin/env python3
"""Coordinate-free proof that userspace (TWRP) really receives the touch.

TWRP blanks the screen after its 60 s UI timeout; the blank path is
  TWFunc::Set_Brightness -> rk_disp_pwr_disable -> System suspend -> GTP enter sleep
and any input event resets that timeout.  Baseline (no touch) blanks at ~74 s.

So: keep tapping every 8 s.  If the kernel log never shows
"System suspend"/"GTP enter sleep" within the window, userspace consumed the
events.  The factory chain is used unchanged.
"""
import json, os, socket, subprocess, sys, time

WS = "/data/workspace"
QEMU = WS + "/qemu-src/build/qemu-system-arm"
SOCK = "/tmp/qm_p4.sock"
FIFO = WS + "/touch.fifo"
LOG = WS + "/p4_serial.log"
ERR = WS + "/p4_qemu.err"

STOP = int(sys.argv[1]) if len(sys.argv) > 1 else 95
PERIOD = 8

subprocess.run(["pkill", "-f", "qemu-system-arm"])
time.sleep(1)
for f in (SOCK, LOG, ERR):
    if os.path.exists(f):
        os.remove(f)
if not os.path.exists(FIFO):
    os.mkfifo(FIFO)

env = dict(os.environ)
env["RK3288_TOUCH_FIFO"] = FIFO

p = subprocess.Popen([
    QEMU, "-machine", "rk3288", "-m", "2048",
    "-kernel", WS + "/t78_stage/stock_zImage",
    "-dtb", WS + "/t78_stage/p817.dtb",
    "-initrd", WS + "/t78_stage/twrp287_ramdisk.gz",
    "-serial", "file:" + LOG,
    "-display", "none",
], stdout=subprocess.DEVNULL, stderr=open(ERR, "wb"), env=env)

t0 = time.time()
n = 0
while time.time() - t0 < STOP:
    if p.poll() is not None:
        break
    el = time.time() - t0
    if el > 25 and n < 40:
        with open(FIFO, "w") as f:
            f.write("tap %d %d\n" % (600 - (n % 3) * 100, 960))
        n += 1
        print("tap #%d at %.0fs" % (n, el), flush=True)
        time.sleep(PERIOD)
    else:
        time.sleep(1)

p.kill()
print("taps:", n, flush=True)
