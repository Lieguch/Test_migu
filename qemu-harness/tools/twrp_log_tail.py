#!/usr/bin/env python3
"""Print the tail of TWRP's /tmp/recovery.log found inside a guest RAM dump."""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/pf.dump"
needle = b"Starting TWRP"
fwd = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x8000

with open(path, "rb") as f:
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
    print("recovery.log not found")
    sys.exit(1)
print("recovery.log @", hex(off))
with open(path, "rb") as f:
    f.seek(off)
    blob = f.read(fwd)

txt = blob.decode("latin-1")
for ln in txt.splitlines():
    clean = "".join(ch if 32 <= ord(ch) < 127 else "" for ch in ln).rstrip()
    if not clean:
        continue
    if clean.startswith(("I:", "E:", "W:", "Starting", "Recovery", "=>", "Unable",
                         "Failed", "Can not", "Updating", "Partition Logs")):
        print(clean)
