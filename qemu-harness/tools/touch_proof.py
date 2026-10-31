#!/usr/bin/env python3
"""Userspace proof: tap the running TWRP, then pull /tmp/recovery.log out of
guest RAM and show the part after the taps.

Boot stays the factory chain (kernel + factory DTB + factory TWRP ramdisk,
no cmdline, -m 2048).  Only the harness' injection FIFO is used.
"""
import json, os, socket, subprocess, sys, time

WS = "/data/workspace"
QEMU = WS + "/qemu-src/build/qemu-system-arm"
SOCK = "/tmp/qm_pf.sock"
FIFO = WS + "/touch.fifo"
LOG = WS + "/pf_serial.log"
ERR = WS + "/pf_qemu.err"
DUMP = "/tmp/pf.dump"

TAPS = [(int(a.split(",")[0]), int(a.split(",")[1]))
        for a in sys.argv[1:]] or [(600, 960), (300, 960), (900, 960)]
T_FIRST = 20
T_DUMP = T_FIRST + 6 * len(TAPS) + 4

subprocess.run(["pkill", "-f", "qemu-system-arm"])
time.sleep(1)
for f in (SOCK, LOG, ERR, DUMP):
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
], stdout=subprocess.DEVNULL, stderr=open(ERR, "wb"), env=env)

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

def rpc(obj, t=600.0):
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

time.sleep(T_FIRST)
for i, (x, y) in enumerate(TAPS):
    with open(FIFO, "w") as f:
        f.write("tap %d %d\n" % (x, y))
    print("tap %d %d at t+%ds" % (x, y, T_FIRST + 6 * i), flush=True)
    time.sleep(6)

time.sleep(T_DUMP - T_FIRST - 6 * len(TAPS))
print("dumping ...", flush=True)
print(rpc({"execute": "dump-guest-memory",
           "arguments": {"protocol": "file:" + DUMP, "paging": False}}), flush=True)

# dump-guest-memory is async: it answers immediately and later emits
# DUMP_COMPLETED.  Wait for that event, otherwise "quit" truncates the file.
s.settimeout(240.0)
buf = b""
deadline = time.time() + 240
while time.time() < deadline:
    try:
        chunk = s.recv(65536)
    except socket.timeout:
        break
    if not chunk:
        break
    buf += chunk
    if b"DUMP_COMPLETED" in buf:
        break
print("dump event seen:", b"DUMP_COMPLETED" in buf, flush=True)
# give QEMU time to flush every segment; "quit" right after the event truncates
time.sleep(10)
p.kill()
print("dump size", os.path.getsize(DUMP), flush=True)
