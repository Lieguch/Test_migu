#!/usr/bin/env python3
"""Faithful chain + taps + targeted RAM window dump (HMP dump-guest-memory with
begin/length), so the 512 MB window that holds TWRP's /tmp/recovery.log can be
grepped in seconds instead of dumping all 2 GB.
"""
import json, os, socket, subprocess, sys, time

WS = "/data/workspace"
QEMU = WS + "/qemu-src/build/qemu-system-arm"
SOCK = "/tmp/qm_p3.sock"
FIFO = WS + "/touch.fifo"
LOG = WS + "/p3_serial.log"
ERR = WS + "/p3_qemu.err"
SEG = "/data/workspace/p3seg.bin"
BEGIN = 0x70000000
LEN = 0x10000000

TAPS = [(600, 960), (300, 600), (900, 600)]

subprocess.run(["pkill", "-f", "qemu-system-arm"])
time.sleep(1)
for f in (SOCK, LOG, ERR, SEG):
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

def hmp(line, t=180.0):
    s.settimeout(t)
    s.sendall((json.dumps({"execute": "human-monitor-command",
                           "arguments": {"command-line": line}}) + "\n").encode())
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
    for ln in reversed(buf.decode("utf-8", "replace").strip().splitlines()):
        if ln.startswith("{"):
            try:
                return json.loads(ln).get("return", "")
            except Exception:
                pass
    return ""

time.sleep(20)
for i, (x, y) in enumerate(TAPS):
    with open(FIFO, "w") as f:
        f.write("tap %d %d\n" % (x, y))
    print("tap %d %d at t+%ds" % (x, y, 20 + 6 * i), flush=True)
    time.sleep(6)

time.sleep(4)
print("seg dump %#x+%#x" % (BEGIN, LEN), flush=True)
print(hmp("dump-guest-memory %s %#x %#x" % (SEG, BEGIN, LEN)).strip(), flush=True)
time.sleep(6)
print("seg size", os.path.getsize(SEG) if os.path.exists(SEG) else "missing", flush=True)
try:
    print(hmp("quit", 5))
except Exception:
    pass
p.kill()
print("done", flush=True)
