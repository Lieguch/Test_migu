#!/usr/bin/env python3
"""Faithful-chain touch injection test.

Boot: factory kernel + factory DTB + factory TWRP ramdisk, no cmdline,
      -m 2048 (exactly the device recipe).  The only extra is the harness'
      own injection channel (RK3288_TOUCH_FIFO), which changes nothing about
      the guest.

Timeline: wait for TWRP UI, mark the log, inject one tap, wait, quit.
Then the caller greps the serial log for the gpio7 / i2c signature.
"""
import json, os, socket, subprocess, sys, time

WS = "/data/workspace"
QEMU = WS + "/qemu-src/build/qemu-system-arm"
SOCK = "/tmp/qm_touch.sock"
FIFO = WS + "/touch.fifo"
LOG = WS + "/touch_run.log"
MARK = WS + "/touch_mark.txt"

X = sys.argv[1] if len(sys.argv) > 1 else "600"
Y = sys.argv[2] if len(sys.argv) > 2 else "800"
BOOT_WAIT = int(sys.argv[3]) if len(sys.argv) > 3 else 75

subprocess.run(["pkill", "-f", "qemu-system-arm"])
time.sleep(1)
for f in (SOCK, LOG, MARK):
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
    "-qmp", "unix:%s,server,nowait" % SOCK,
    "-serial", "file:" + LOG,
    "-display", "none",
], stdout=subprocess.DEVNULL, stderr=open(WS + "/touch_qemu.err", "wb"), env=env)

deadline = time.time() + 40
s = None
while time.time() < deadline:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCK)
        break
    except OSError:
        s = None
        time.sleep(1)
if s is None:
    raise SystemExit("no qmp")
s.settimeout(2.0)
try:
    s.recv(65536)
except socket.timeout:
    pass
s.sendall(b'{"execute":"qmp_capabilities"}\n')
time.sleep(0.5)

def rpc(obj, t=30.0):
    s.settimeout(t)
    s.sendall((json.dumps(obj) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        c = s.recv(65536)
        if not c:
            raise SystemExit("closed")
        buf += c
    while True:
        s.settimeout(0.5)
        try:
            more = s.recv(65536)
            if not more:
                break
            buf += more
        except socket.timeout:
            break
    out = None
    for ln in buf.decode("utf-8", "replace").strip().splitlines():
        if ln.startswith("{"):
            try:
                out = json.loads(ln)
            except Exception:
                pass
    return out

print("waiting %d s for TWRP UI" % BOOT_WAIT, flush=True)
time.sleep(BOOT_WAIT)

before = os.path.getsize(LOG) if os.path.exists(LOG) else 0
open(MARK, "w").write("before=%d\n" % before)
print("log before tap:", before, flush=True)

# inject one tap through the harness' own channel
with open(FIFO, "w") as f:
    f.write("tap %s %s\n" % (X, Y))
print("injected tap %s %s" % (X, Y), flush=True)

time.sleep(12)
after = os.path.getsize(LOG) if os.path.exists(LOG) else 0
print("log after tap:", after, "delta", after - before, flush=True)

# keep a ram snapshot of the interesting window for the caller
try:
    rpc({"execute": "quit"}, 3)
except Exception:
    pass
p.kill()
print("done", flush=True)
