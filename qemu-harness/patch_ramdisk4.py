#!/usr/bin/env python3
"""Edit a (gzipped) cpio newc: replace contents and/or add a new entry.

Usage:
  patch_ramdisk4.py <in> <out> --set <name> <file> [--set <name> <file> ...]
                    --add <name> <file> <mode_hex> [--add ...]
"""
import gzip
import os
import sys

MAGIC = b'070701'
FIELDS = ('ino', 'mode', 'uid', 'gid', 'nlink', 'mtime', 'filesize',
          'devmaj', 'devmin', 'rdevmaj', 'rdevmin', 'namesize', 'check')


def parse(data):
    off, n, out = 0, len(data), []
    while True:
        if off + 110 > n or data[off:off + 6] != MAGIC:
            break
        f = [int(data[off + 6 + 8 * i:off + 14 + 8 * i], 16) for i in range(13)]
        namesize = f[11]
        name = data[off + 110:off + 110 + namesize - 1].decode('utf-8', 'replace')
        pad = (4 - (110 + namesize) % 4) % 4
        dstart = off + 110 + namesize + pad
        content = data[dstart:dstart + f[6]]
        off = dstart + f[6] + ((4 - f[6] % 4) % 4)
        e = dict(zip(FIELDS, f))
        e['name'] = name
        e['content'] = content
        out.append(e)
        if name == 'TRAILER!!!':
            break
    return out


def entry_bytes(e):
    name_b = e['name'].encode() + b'\0'
    e['namesize'] = len(name_b)
    e['filesize'] = len(e['content'])
    hdr = MAGIC + b''.join(b'%08X' % e[k] for k in FIELDS)
    assert len(hdr) == 110
    buf = hdr + name_b
    buf += b'\0' * ((4 - len(buf) % 4) % 4)
    buf += e['content']
    buf += b'\0' * ((4 - len(e['content']) % 4) % 4)
    return buf


def main():
    args = sys.argv[1:]
    src, dst = args[0], args[1]
    rest = args[2:]
    sets, adds = [], []
    i = 0
    while i < len(rest):
        if rest[i] == '--set':
            sets.append((rest[i + 1], rest[i + 2])); i += 3
        elif rest[i] == '--add':
            adds.append((rest[i + 1], rest[i + 2], int(rest[i + 3], 16))); i += 4
        else:
            i += 1

    raw = open(src, 'rb').read()
    gz = raw[:2] == b'\x1f\x8b'
    if gz:
        raw = gzip.decompress(raw)
    ents = parse(raw)
    max_ino = max(e['ino'] for e in ents)

    for name, path in sets:
        new = open(path, 'rb').read()
        hit = 0
        for e in ents:
            if e['name'] == name:
                print(f"set {name}: {len(e['content'])} -> {len(new)} B")
                e['content'] = new
                hit += 1
        if not hit:
            print(f"WARN not found for --set: {name}", file=sys.stderr)

    trailer = ents[-1]
    for name, path, mode in adds:
        if any(e['name'] == name for e in ents):
            print(f"skip add, exists: {name}")
            continue
        content = open(path, 'rb').read()
        max_ino += 1
        e = dict(ino=max_ino, mode=mode, uid=0, gid=0, nlink=1, mtime=0,
                 filesize=len(content), devmaj=0, devmin=0, rdevmaj=0, rdevmin=0,
                 namesize=len(name) + 1, check=0, name=name, content=content)
        ents.insert(ents.index(trailer), e)
        print(f"add {name}: {len(content)} B mode=0o{mode:o} ino={max_ino}")

    out = b''.join(entry_bytes(e) for e in ents)
    if gz:
        out = gzip.compress(out, 6)
    tmp = dst + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(out)
    os.replace(tmp, dst)
    print(f"entries={len(ents)} out={len(out)} B -> {dst}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
