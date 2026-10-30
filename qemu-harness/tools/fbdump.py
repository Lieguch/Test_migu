#!/usr/bin/env python3
"""Dump guest framebuffer via QMP pmemsave and convert RGB565 -> BMP."""
import socket, json, struct, os, sys

SOCK = "/data/workspace/mon.sock"
BASE = 0x40000000
W, H = 1920, 1200
FRAME = W * H * 2          # RGB565
TOTAL = FRAME * 2          # double buffered
RAW = "/data/workspace/fb.raw"

s = socket.socket(socket.AF_UNIX)
s.connect(SOCK)
s.settimeout(240)
buf = b""

def rpc(obj):
    global buf
    s.sendall((json.dumps(obj) + "\n").encode())
    while True:
        buf += s.recv(1 << 20)
        lines = buf.decode(errors="replace").split("\n")
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if "return" in d or "error" in d:
                buf = ("\n".join(lines[i + 1:])).encode()
                return d

rpc({"execute": "qmp_capabilities"})

def hmp(cmd):
    r = rpc({"execute": "human-monitor-command",
             "arguments": {"command-line": cmd}})
    return r.get("return", "")

if os.path.exists(RAW):
    os.remove(RAW)
cmd = 'pmemsave 0x%x 0x%x "%s"' % (BASE, TOTAL, RAW)
print("pmemsave ->", repr(hmp(cmd)))
if not os.path.exists(RAW):
    sys.exit("dump failed")

data = open(RAW, "rb").read()
print("raw size", len(data))

def write_bmp(path, off):
    px = data[off:off + FRAME]
    if len(px) < FRAME:
        print("short buffer for", path)
        return
    row_bytes = W * 3
    pad = (4 - row_bytes % 4) % 4
    size = 54 + (row_bytes + pad) * H
    with open(path, "wb") as f:
        f.write(b"BM" + struct.pack("<IHHI", size, 0, 0, 54))
        f.write(struct.pack("<IiiHHIIiiII", 40, W, H, 1, 24, 0,
                            (row_bytes + pad) * H, 2835, 2835, 0, 0))
        for y in range(H - 1, -1, -1):
            base = y * W * 2
            out = bytearray()
            for x in range(W):
                v = px[base + x * 2] | (px[base + x * 2 + 1] << 8)
                r5 = (v >> 11) & 0x1F
                g6 = (v >> 5) & 0x3F
                b5 = v & 0x1F
                out += bytes(((r5 << 3) | (r5 >> 2),
                              (g6 << 2) | (g6 >> 4),
                              (b5 << 3) | (b5 >> 2)))
            out += b"\x00" * pad
            f.write(out)

write_bmp("/data/workspace/fb0.bmp", 0)
write_bmp("/data/workspace/fb1.bmp", FRAME)
print("wrote fb0.bmp / fb1.bmp")
