#!/usr/bin/env python3
"""cpio newc (070701) reader/writer - single source of truth.

parse(data) -> (entries, trailer_bytes): entries exclude the TRAILER!!! record;
trailer_bytes is the verbatim trailer record (or b'' if none).

build(entries, trailer=b'') -> bytes: emits each record on the archive's
absolute 4-byte grid (name padded so 110+name is 4-aligned; data padded so
the record ends 4-aligned from archive start).

Entry dict keys: name(str, '/' separators), mode(int, as stored),
data(bytes), nlink, uid, gid, mtime, rdev=(maj,min), ino(0=auto).
"""
import stat

MAGIC = b'070701'


def parse(data):
    entries = []
    trailer = b''
    off = 0
    n = len(data)
    while off + 110 <= n:
        if data[off:off + 6] != MAGIC:
            raise ValueError('bad magic at %d: %r' % (off, data[off:off + 10]))
        f = lambda a, b: int(data[off + a:off + b], 16)
        ino, mode = f(6, 14), f(14, 22)
        uid, gid, nlink, mtime = f(22, 30), f(30, 38), f(38, 46), f(46, 54)
        filesize = f(54, 62)
        devmaj, devmin = f(62, 70), f(70, 78)
        rdevmaj, rdevmin, namesize = f(78, 86), f(86, 94), f(94, 102)
        name = data[off + 110:off + 110 + namesize].rstrip(b'\x00').decode('utf-8', 'replace')
        after_name = off + 110 + namesize
        file_start = (after_name + 3) & ~3
        file_data = data[file_start:file_start + filesize]
        nxt = (file_start + filesize + 3) & ~3
        if name == 'TRAILER!!!':
            trailer = data[off:]
            break
        entries.append(dict(name=name, mode=mode, data=file_data, nlink=nlink,
                            uid=uid, gid=gid, mtime=mtime,
                            rdev=(rdevmaj, rdevmin), ino=ino, devmaj=devmaj,
                            devmin=devmin))
        off = nxt
    return entries, trailer


def _hdr(ino, mode, uid, gid, nlink, mtime, filesize,
         devmaj, devmin, rdevmaj, rdevmin, namesize, chksum):
    """Format a newc header. Lowercase hex - matches the style of the
    kernel-accepted ramdisk and is accepted by Linux's case-insensitive parser."""
    return MAGIC + b''.join(
        ('%08x' % v).encode()
        for v in (ino, mode, uid, gid, nlink, mtime, filesize,
                  devmaj, devmin, rdevmaj, rdevmin, namesize, chksum))


def default_trailer():
    """Verbatim copy of the trailer observed in the working vendor cpio."""
    nb = b'TRAILER!!!\x00'
    hdr = _hdr(0, 0o755, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(nb), 0)
    return hdr + nb + b'\x00' * ((-(len(hdr) + len(nb))) & 3)


def build(entries, trailer=b''):
    out = bytearray()
    auto = 0
    for e in entries:
        auto += 1
        nb = e['name'].encode() + b'\x00'
        assert len(nb) < 512, e['name']
        mode = e['mode']
        data = e.get('data') or b''
        rdev = e.get('rdev', (0, 0))
        # preserve verbatim when parse() stored the field; only default when absent
        ino = e['ino'] if e.get('ino') is not None else auto
        nlink = e['nlink'] if e.get('nlink') is not None else (2 if stat.S_ISDIR(mode) else 1)
        hdr = _hdr(ino, mode, e.get('uid', 0), e.get('gid', 0), nlink,
                   e.get('mtime', 0), len(data), e.get('devmaj', 0),
                   e.get('devmin', 0), rdev[0], rdev[1], len(nb), 0)
        assert len(hdr) == 110
        out += hdr
        pad = (-(len(out) + len(nb))) & 3
        out += nb + b'\x00' * pad
        if data:
            out += data
            out += b'\x00' * ((-len(out)) & 3)
    out += trailer
    return bytes(out)
