#!/usr/bin/env python3
"""Extract printable text around the TWRP recovery log found in a guest RAM dump."""
import sys

path = "/tmp/ram_faith.dump"
needle = b"Starting TWRP"
back = int(sys.argv[1],0) if len(sys.argv) > 1 else 0x4000
fwd = int(sys.argv[2],0) if len(sys.argv) > 2 else 0x10000

with open(path, "rb") as f:
    data_head = f.read(8)
    f.seek(0)
    off = -1
    while True:
        chunk = f.read(1 << 24)
        if not chunk:
            break
        i = chunk.find(needle)
        if i >= 0:
            off = f.tell() - len(chunk) + i
            break
        f.seek(f.tell() - len(needle))
if off < 0:
    print("not found")
    sys.exit(1)
print("offset", hex(off))
with open(path, "rb") as f:
    f.seek(max(0, off - back))
    blob = f.read(back + fwd)
txt = blob.decode("latin-1")
# keep only lines that look like log lines
out = []
for ln in txt.splitlines():
    clean = "".join(ch if 32 <= ord(ch) < 127 else ("\t" if ch == "\t" else "") for ch in ln)
    if len(clean.strip()) >= 3:
        out.append(clean.rstrip())
print("\n".join(out))
