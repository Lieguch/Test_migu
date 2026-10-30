#!/usr/bin/env python3
"""
Create a cpio newc initramfs from a directory tree.
Output: D:/output/initramfs.cpio (uncompressed cpio newc format)

Format per entry (4-byte aligned from file start):
  header (110 bytes) + name (NUL-terminated) + pad_to_4(abs_offset)
  + file_data + pad_to_4(abs_offset)
"""
import os

SRC = 'D:/output/initramfs_build'
OUT = 'D:/output/initramfs.cpio'

def cpio_header(name, filesize, mode=0o755):
    """Build a 110-byte cpio newc header (header only, no name)."""
    name_bytes = name.encode('utf-8') + b'\x00'
    namesize = len(name_bytes)
    hdr = bytearray(110)
    hdr[0:6] = b'070701'          # c_magic
    hdr[6:14] = f'{0:08x}'.encode()   # c_ino
    hdr[14:22] = f'{mode:08x}'.encode()  # c_mode
    hdr[22:30] = f'{0:08x}'.encode()   # c_uid
    hdr[30:38] = f'{0:08x}'.encode()   # c_gid
    hdr[38:46] = f'{1:08x}'.encode()   # c_nlink
    hdr[46:54] = f'{0:08x}'.encode()   # c_mtime
    hdr[54:62] = f'{filesize:08x}'.encode()  # c_filesize
    hdr[62:70] = f'{0:08x}'.encode()   # c_maj
    hdr[70:78] = f'{0:08x}'.encode()   # c_min
    hdr[78:86] = f'{0:08x}'.encode()   # c_rmaj
    hdr[86:94] = f'{0:08x}'.encode()   # c_rmin
    hdr[94:102] = f'{namesize:08x}'.encode()  # c_namesize
    hdr[102:110] = f'{0:08x}'.encode()  # c_chksum
    return bytes(hdr)

def pad_to_4(n):
    return (4 - (n % 4)) % 4

def walk_and_emit(f, base_dir, base_name=''):
    for entry in sorted(os.listdir(base_dir)):
        if entry in ('.', '..'):
            continue
        full_path = os.path.join(base_dir, entry)
        rel_name = os.path.join(base_name, entry) if base_name else entry
        st = os.lstat(full_path)
        mode = st.st_mode

        if os.path.isdir(full_path):
            dir_mode = (mode & 0o7777) | 0o040000  # S_IFDIR
            f.write(cpio_header(rel_name, 0, dir_mode))
            name_bytes = rel_name.encode('utf-8') + b'\x00'
            f.write(name_bytes)
            # Align absolute file offset to 4
            f.write(b'\x00' * pad_to_4(f.tell()))
            walk_and_emit(f, full_path, rel_name)
        else:
            with open(full_path, 'rb') as fh:
                file_data = fh.read()
            filesize = len(file_data)
            f.write(cpio_header(rel_name, filesize, mode & 0o7777))
            name_bytes = rel_name.encode('utf-8') + b'\x00'
            f.write(name_bytes)
            f.write(b'\x00' * pad_to_4(f.tell()))
            f.write(file_data)
            f.write(b'\x00' * pad_to_4(f.tell()))

with open(OUT, 'wb') as f:
    # Root directory entry
    f.write(cpio_header('', 0, 0o040755))
    f.write(b'\x00')  # empty name with NUL (1 byte)
    f.write(b'\x00' * pad_to_4(f.tell()))
    walk_and_emit(f, SRC)
    # CPIO trailer
    f.write(cpio_header('TRAILER!!!', 0))
    f.write(b'TRAILER!!!\x00')
    f.write(b'\x00' * pad_to_4(f.tell()))

import os as _os
print(f'Created {OUT}')
print(f'Size: {_os.path.getsize(OUT)} bytes')
