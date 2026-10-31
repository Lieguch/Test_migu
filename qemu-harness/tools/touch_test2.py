#!/usr/bin/env python3
"""Touch-chain test on the faithful boot, with GIC state probes.

Timeline:
  0 s   boot (factory kernel + factory DTB + factory TWRP ramdisk, no cmdline)
 22 s   read GIC ISENABLER2/ISPENDR2  (SPI 88 = gpio7 bank irq)
        inject "tap x y"
 28 s   read GIC again + sample PC
        quit

The harness' gpio7 model prints every register access to stderr, so the
verdict comes from touch_qemu.err:  a working chain shows
   R 040  (rockchip_irq_demux reads GPIO_INT_STATUS)
   W 04c  (EOI)
   i2c reads at 0x814e / 0x814f..  (driver fetches the point)
"""
import json, os, socket, subprocess, sys, time

WS = "/data/workspace"
QEMU = WS + "/qemu-src/build/qemu-system-arm"
SOCK = "/tmp/qm_t2.sock"
FIFO = WS + "/touch.fifo"
LOG = WS + "/t2_serial.log"
ERR = WS + "/t2_qemu.err"

X = sys.argv[1] if len(sys.argv) > 1 else "600"
Y = sys.argv[2] if len(sys.argv) > 2 else "800"
T_TAP = int(sys.argv[3]) if len(sys.argv) > 3 else 22

# GICD: base 0xffc01000, ISENABLER<n> = 0x100+4n, ISPENDR<n> = 0x200+4n
GIC_ISEN2 = 0xffc01108   # SPIs 64..95
GIC_ISPEN2 = 0xffc01208

subprocess.run(["pkill", "-f", "qemu-system-arm"])
time.sleep(1)
for f in (SOCK, LOG, ERR):
    if os.path.exists(f) and not f.endswith(".fifo"):
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

def hmp(line, t=20.0):
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
        s.settimeout(0.4)
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

def gic(tag):
    for name, addr in (("ISENABLER2", GIC_ISEN2), ("ISPENDR2", GIC_ISPEN2)):
        print("%s %s: %s" % (tag, name, hmp("xp /1xw %#x" % addr).strip()), flush=True)

print("waiting %d s" % T_TAP, flush=True)
time.sleep(T_TAP)
gic("before")
print("PC0:", [l for l in hmp("info registers").splitlines() if l.startswith("R15")], flush=True)

with open(FIFO, "w") as f:
    f.write("tap %s %s\n" % (X, Y))
print("tap injected %s %s" % (X, Y), flush=True)

time.sleep(6)
gic("after")
print("PC1:", [l for l in hmp("info registers").splitlines() if l.startswith("R15")], flush=True)
time.sleep(2)
print(hmp("quit"))
p.kill()
print("done", flush=True)
