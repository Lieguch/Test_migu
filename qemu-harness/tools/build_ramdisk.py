#!/usr/bin/env python3
"""build_ramdisk.py - surgery on the vendor ramdisk for QEMU boot (runs on ibx).

Takes the kernel-accepted /data/workspace/initramfs.cpio (Windows-made:
backslash paths, mode fields without file-type bits) and produces a clean,
spec-standard newc archive:
  * paths: backslash -> forward slash
  * modes: S_IFDIR|0755 for dirs, S_IFREG|0755 for ELF/shebang, S_IFREG|0644 else
  * 'init' entry replaced by our static init2
  * adds 'sbin/msh' (static shell), 'dev/console' (chr 5:1), 'dev/null' (chr 1:3)
Verifies by reparsing, then writes /data/workspace/initramfs_msh.cpio.
"""
import stat as S
import sys

sys.path.insert(0, '/data/workspace')
import cpio_lib

SRC = '/data/workspace/initramfs.cpio'
OUT = '/data/workspace/initramfs_msh.cpio'


def norm_mode(name, data):
    if data[:4] == b'\x7fELF':
        return S.S_IFREG | 0o755
    if data[:2] == b'#!':
        return S.S_IFREG | 0o755
    return S.S_IFREG | 0o644


def main():
    with open(SRC, 'rb') as f:
        data = f.read()
    entries, trailer = cpio_lib.parse(data)
    print('parsed %d entries + %dB trailer from %s (%d B)'
          % (len(entries), len(trailer), SRC, len(data)))

    with open('/data/workspace/init2', 'rb') as f:
        init_bin = f.read()
    with open('/data/workspace/msh', 'rb') as f:
        msh_bin = f.read()

    new_entries = []
    seen = set()
    for e in entries:
        name = e['name'].replace('\\', '/')
        if name == 'init':
            e2 = dict(e)
            e2['name'] = name
            e2['mode'] = S.S_IFREG | 0o755
            e2['data'] = init_bin
            new_entries.append(e2)
            seen.add(name)
            continue
        e2 = dict(e)
        e2['name'] = name
        if S.S_ISDIR(e['mode']):
            e2['mode'] = S.S_IFDIR | 0o755
        else:
            e2['mode'] = norm_mode(name, e['data'])
        new_entries.append(e2)
        seen.add(name)

    # appended static nodes/binaries (parent dirs already exist upstream)
    for name, mode, blob, rdev in (
            ('sbin/msh', S.S_IFREG | 0o755, msh_bin, (0, 0)),
            ('dev/console', S.S_IFCHR | 0o600, b'', (5, 1)),
            ('dev/null', S.S_IFCHR | 0o666, b'', (1, 3))):
        if name not in seen:
            new_entries.append(dict(name=name, mode=mode, data=blob, rdev=rdev))

    out = cpio_lib.build(new_entries, trailer)
    with open(OUT, 'wb') as f:
        f.write(out)

    # verify: reparse the produced archive; structure must be clean
    e2, t2 = cpio_lib.parse(out)
    assert t2 == trailer, 'trailer mangled'
    print('wrote %s: %d entries, reparsed cleanly, %d B' % (OUT, len(e2), len(out)))
    names = [e['name'] for e in e2]
    for want in ('init', 'sbin/msh', 'sbin/sh', 'dev/console', 'dev/null'):
        print('  %-14s %s' % (want, 'OK' if want in names else 'MISSING'))
    # our init must actually be in there
    for e in e2:
        if e['name'] == 'init':
            assert e['data'] == init_bin, 'init payload mismatch'
            print('  init payload: %d B (0o%o) OK' % (len(e['data']), e['mode']))
        if e['name'] == 'sbin/msh':
            assert e['data'] == msh_bin, 'msh payload mismatch'


if __name__ == '__main__':
    main()
