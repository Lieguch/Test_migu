import socket,json,sys
s=socket.socket(socket.AF_UNIX); s.connect("/data/workspace/mon.sock"); s.settimeout(20)
buf=b""
def rpc(o):
    global buf
    s.sendall((json.dumps(o)+"\n").encode())
    while True:
        buf+=s.recv(1<<20); lines=buf.decode(errors="replace").split("\n")
        for i,l in enumerate(lines):
            if not l.strip(): continue
            try: d=json.loads(l)
            except Exception: continue
            if "return" in d or "error" in d:
                buf=("\n".join(lines[i+1:])).encode(); return d
rpc({"execute":"qmp_capabilities"})
def hmp(c): return rpc({"execute":"human-monitor-command","arguments":{"command-line":c}}).get("return","")
for addr in sys.argv[1:]:
    print("=== mem",addr,"===")
    print(hmp("x/8xw %s"%addr))
