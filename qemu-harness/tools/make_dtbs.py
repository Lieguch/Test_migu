#!/usr/bin/env python3
"""Build DTB variants with the hanging video-codec nodes disabled.

p817.dtb (original, untouched) -> decompile -> insert status="disabled"
into the requested nodes -> recompile to p817_vN.dtb
"""
import subprocess
import sys

WS = '/data/workspace'
NODES_V1 = ['vpu_service@ff9a0000']
NODES_V2 = ['vpu_service@ff9a0000', 'hevc_service@ff9c0000', 'iep@ff900000']

subprocess.run(['dtc', '-I', 'dtb', '-O', 'dts', f'{WS}/p817.dtb'],
               check=True, stdout=open('/tmp/p817_base.dts', 'w'), stderr=subprocess.DEVNULL)

with open('/tmp/p817_base.dts') as f:
    dts = f.read()


def add_disabled(src, node):
    marker = '\t%s {' % node
    i = src.index(marker)
    # find end of this node block: next '\t};' at column 0-tab level
    end = src.index('\n\t};', i)
    block = src[i:end]
    if '\n\t\tstatus = ' in block:
        # replace existing value
        s = i + block.index('\n\t\tstatus = ')
        e = src.index(';', s)
        return src[:s] + '\n\t\tstatus = "disabled"' + src[e:]
    j = src.index('\n', i)
    return src[:j + 1] + '\t\tstatus = "disabled";\n' + src[j + 1:]


def build(name, nodes):
    out = dts
    for n in nodes:
        out = add_disabled(out, n)
    with open('/tmp/p817_%s.dts' % name, 'w') as f:
        f.write(out)
    with open('%s/p817_%s.dtb' % (WS, name), 'wb') as f:
        subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '/tmp/p817_%s.dts' % name],
                       check=True, stdout=f, stderr=subprocess.DEVNULL)
    # verify
    for n in nodes:
        r = subprocess.run(['fdtget', f'{WS}/p817_{name}.dtb', '/' + n, 'status'],
                           capture_output=True, text=True)
        print('  p817_%s.dtb: %s -> %s' % (name, n, r.stdout.strip()))


print('building v1 (vpu only):')
build('v1', NODES_V1)
print('building v2 (vpu+hevc+iep):')
build('v2', NODES_V2)
print('done')
