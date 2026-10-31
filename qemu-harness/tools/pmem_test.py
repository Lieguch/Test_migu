#!/usr/bin/env python3
"""Minimal HMP probe: run a few pmemsave variants and report."""
import json, os, socket, subprocess, sys, time

WS = "/data/workspace"
QEMU = WS + "/qemu-src/build/qemu-system-arm"
SOCK = "/tmp/qm_t.sock"

subprocess.run(["pkill", "-f", "qemu-system-arm"])
time.sleep(1)
if os.path.exists(SOCK):
    os.remove(SOCK)

subprocess.Popen([
    QEMU, "-machine", "rk3288", "-m", "512",
    "-kernel", WS + "/t78_stage/stock_zImage",
    "-dtb", WS + "/t78_stage/p817.dtb",
    "-initrd", WS + "/t78_stage/twrp287_ramdisk.gz",
    "-qmp", "unix:%s,server,nowait" % SOCK,
    "-serial", "null", "-display", "none",
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

def hmp(line, t=20.0):
    s.settimeout(t)
    s.sendall((json.dumps({"execute": "human-monitor-command",
                           "arguments": {"command-line": line}}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        buf += s.recv(65536)
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

time.sleep(20)
for test in ["pmemsave 0 4096 /tmp/t1.bin",
             "pmemsave 0 0x1000 /tmp/t2.bin",
             "pmemsave 0 16777216 /tmp/t3.bin"]:
    print(test, "->", hmp(test).strip()[:120], flush=True)
for f in ("/tmp/t1.bin", "/tmp/t2.bin", "/tmp/t3.bin"):
    if os.path.exists(f):
        print(f, os.path.getsize(f), flush=True)
print(hmp("info status"))
print(hmp("quit"))
