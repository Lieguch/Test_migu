#!/usr/bin/env python3
"""Probe HMP help for pmemsave and try QMP dump-guest-memory."""
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

def rpc(obj, t=30.0):
    s.settimeout(t)
    s.sendall((json.dumps(obj) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            raise SystemExit("closed")
        buf += chunk
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

def hmp(line, t=30.0):
    r = rpc({"execute": "human-monitor-command", "arguments": {"command-line": line}}, t)
    return (r or {}).get("return", "")

time.sleep(15)
print("=== help pmemsave ===")
print(hmp("help pmemsave")[:600])
print("=== command list (mem) ===")
print("\n".join(l for l in hmp("help").splitlines() if "mem" in l.lower())[:800])

print("=== try dump-guest-memory qmp ===")
r = rpc({"execute": "dump-guest-memory",
         "arguments": {"protocol": "file:/tmp/ram.dump", "paging": False}}, t=180)
print(r)
time.sleep(2)
if os.path.exists("/tmp/ram.dump"):
    print("dump size", os.path.getsize("/tmp/ram.dump"))
try:
    rpc({"execute": "quit"}, 3)
except Exception:
    pass
