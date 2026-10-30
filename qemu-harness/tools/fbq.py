#!/usr/bin/env python3
"""Dump guest framebuffer via QMP pmemsave. usage: fbq.py <out.raw> [bytes]"""
import socket, json, sys

out = sys.argv[1]
size = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x465000
s = socket.socket(socket.AF_UNIX)
s.connect("/data/workspace/mon.sock")
s.settimeout(240)
buf = b""

def rpc(o):
    global buf
    s.sendall((json.dumps(o) + "\n").encode())
    while True:
        buf += s.recv(1 << 20)
        L = buf.decode(errors="replace").split("\n")
        for i, l in enumerate(L):
            if not l.strip():
                continue
            try:
                d = json.loads(l)
            except Exception:
                continue
            if "return" in d or "error" in d:
                buf = ("\n".join(L[i + 1:])).encode()
                return d

rpc({"execute": "qmp_capabilities"})
cmd = 'pmemsave 0x40000000 0x%x "%s"' % (size, out)
r = rpc({"execute": "human-monitor-command",
         "arguments": {"command-line": cmd}})
print("pmemsave:", repr(r.get("return", r)))
