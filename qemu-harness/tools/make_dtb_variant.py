#!/usr/bin/env python3
"""Build a DTB variant from p817.dtb with the given nodes forced to status="disabled".

Usage: make_dtb_variant.py OUT.dtb node1 node2 ...
"""
import subprocess
import sys

WS = '/data/workspace'
out = sys.argv[1]
nodes = sys.argv[2:]

dts = subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', WS + '/p817.dtb'],
                     check=True, capture_output=True, text=True).stdout


def disable(src, node):
    marker = '\t%s {' % node
    i = src.index(marker)
    end = src.index('\n\t};', i)
    block = src[i:end]
    if '\n\t\tstatus = ' in block:
        s = i + block.index('\n\t\tstatus = ')
        e = src.index(';', s)
        return src[:s] + '\n\t\tstatus = "disabled"' + src[e:]
    j = src.index('\n', i)
    return src[:j + 1] + '\t\tstatus = "disabled";\n' + src[j + 1:]


for n in nodes:
    dts = disable(dts, n)

with open(WS + '/' + out, 'wb') as f:
    subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb'], input=dts.encode(),
                   check=True, stdout=f, stderr=subprocess.DEVNULL)

for n in nodes:
    r = subprocess.run(['fdtget', WS + '/' + out, '/' + n, 'status'],
                       capture_output=True, text=True)
    print('  %-24s -> %s' % (n, r.stdout.strip() or r.stderr.strip()[:40]))
