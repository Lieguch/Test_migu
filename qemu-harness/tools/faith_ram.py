#!/usr/bin/env python3
"""Faithful boot (kernel + factory DTB + factory TWRP ramdisk, no cmdline),
then dump guest RAM over QMP and extract /tmp/recovery.log from it.

Answers two questions with evidence:
  1. did Android init finish and start /sbin/recovery ?
  2. what did TWRP itself log ?
"""
import json, os, re, socket, subprocess, sys, time

WS = "/data/workspace"
QEMU = WS + "/qemu-src/build/qemu-system-arm"
SOCK = "/tmp/qm_faith.sock"
DUMP = "/tmp/ram_faith.dump"
LOG = WS + "/ram_boot.log"
WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 70

subprocess.run(["pkill", "-f", "qemu-system-arm"])
time.sleep(1)
for f in (SOCK, DUMP, LOG):
    if os.path.exists(f):
        os.remove(f)

p = subprocess.Popen([
    QEMU, "-machine", "rk3288", "-m", "2048",
    "-kernel", WS + "/t78_stage/stock_zImage",
    "-dtb", WS + "/t78_stage/p817.dtb",
    "-initrd", WS + "/t78_stage/twrp287_ramdisk.gz",
    "-qmp", "unix:%s,server,nowait" % SOCK,
    "-serial", "file:" + LOG,
    "-display", "none",
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
    raise SystemExit("no socket")
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

print("guest time budget: %d s" % WAIT, flush=True)
time.sleep(WAIT)

r = rpc({"execute": "human-monitor-command",
         "arguments": {"command-line": "info registers"}}, 10)
txt = (r or {}).get("return", "")
print("PC:", [l for l in txt.splitlines() if l.startswith("R15")], flush=True)

print("dumping guest memory ...", flush=True)
print(rpc({"execute": "dump-guest-memory",
           "arguments": {"protocol": "file:" + DUMP, "paging": False}}, t=600), flush=True)
try:
    rpc({"execute": "quit"}, 3)
except Exception:
    pass
p.kill()

if not os.path.exists(DUMP):
    raise SystemExit("no dump")
print("dump size", os.path.getsize(DUMP), flush=True)

data = open(DUMP, "rb").read()
needles = [b"Starting TWRP", b"recovery.log", b"gt9xx", b"goodix"]
for n in needles:
    idx = data.find(n)
    print("%-16s first@%s count=%d" % (n.decode(), hex(idx) if idx >= 0 else "-",
                                       data.count(n)), flush=True)
