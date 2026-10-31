import struct, sys

path = sys.argv[1] if len(sys.argv) > 1 else "recovery.img"
d = open(path, "rb").read()
o = d.find(b"ANDROID!")
if o < 0:
    print("no ANDROID! magic")
    sys.exit(1)
print("header at", hex(o))
h = d[o:o + 1660]
k, rds, kaddr, raddr, ss, saddr, tags, psz, dt, unused = struct.unpack("<10I", h[8:48])
name = h[48:64].split(b"\x00")[0]
cmd = h[64:576].split(b"\x00")[0]
extra = h[1632:1660].split(b"\x00")[0]
print("kernel_size", k, "kernel_addr", hex(kaddr))
print("ramdisk_size", rds, "ramdisk_addr", hex(raddr))
print("page_size", psz, "dt_size", dt)
print("name", name)
print("cmdline:", cmd.decode("utf-8", "replace"))
print("extra_cmdline:", extra.decode("utf-8", "replace"))

# also locate dtb / resource inside
for tag in (b"RKDT", b"RSCE", b"KRNL"):
    print(tag, d.find(tag, o, o + 0x2000000))

# dump the section after boot header: find second stage
