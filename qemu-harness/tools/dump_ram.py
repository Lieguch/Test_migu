#!/usr/bin/env python3
"""Boot the factory chain under QMP, then pull guest RAM and extract
/tmp/recovery.log from inside the (rootfs) ramdisk.

No cmdline is passed: kernel + factory DTB + factory TWRP ramdisk only.
"""
import json, os, socket, subprocess, sys, time

WS = "/data/workspace"
QEMU = WS + "/qemu-src/build/qemu-system-arm"
SOCK = "/tmp/qm_ram.sock"
OUT = WS + "/ram.bin"

def qmp_init(path, wait=60):
    deadline = time.time() + wait
    while time.time() < deadline:
        if os.path.exists(path):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(path)
                return s
            except OSError:
                pass
        time.sleep(1)
    raise SystemExit("qmp socket never appeared")

def cmd(s, line, t=30.0):
    s.settimeout(t)
    s.sendall((json.dumps({"execute": "human-monitor-command",
                           "arguments": {"command-line": line}}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        buf += s.recv(65536)
    while True:
        s.settimeout(0.5)
        try:
            more = s.recv(65536)
            if not more:
                break
            buf += more
        except socket.timeout:
            break
    # last json line wins
    for ln in reversed(buf.decode("utf-8", "replace").strip().splitlines()):
        if ln.startswith("{"):
            try:
                return json.loads(ln).get("return", "")
            except Exception:
                pass
    return ""

subprocess.run(["pkill", "-f", "qemu-system-arm"])
time.sleep(1)
for f in (SOCK, OUT):
    if os.path.exists(f):
        os.remove(f)

proc = subprocess.Popen([
    QEMU, "-machine", "rk3288", "-m", "2048",
    "-kernel", WS + "/t78_stage/stock_zImage",
    "-dtb", WS + "/t78_stage/p817.dtb",
    "-initrd", WS + "/t78_stage/twrp287_ramdisk.gz",
    "-qmp", "unix:%s,server,nowait" % SOCK,
    "-serial", "file:" + WS + "/ram_boot.log",
    "-display", "none",
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

s = qmp_init(SOCK)
s.settimeout(2.0)
try:
    s.recv(65536)
except socket.timeout:
    pass
s.sendall(b'{"execute":"qmp_capabilities"}\n')
time.sleep(0.5)
try:
    s.recv(65536)
except socket.timeout:
    pass

print("booting, waiting 60 s of guest time ...", flush=True)
time.sleep(60)

ram = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x80000000
print(cmd(s, "info registers")[:200], flush=True)
print("pmemsave %#x bytes -> %s" % (ram, OUT), flush=True)
r = cmd(s, "pmemsave 0 %#x %s" % (ram, OUT), t=300)
print("pmemsave:", r, flush=True)
print("size:", os.path.getsize(OUT) if os.path.exists(OUT) else "missing", flush=True)

print(cmd(s, "quit"))
s.close()
time.sleep(2)
try:
    proc.wait(timeout=10)
except Exception:
    proc.kill()
print("done", flush=True)
