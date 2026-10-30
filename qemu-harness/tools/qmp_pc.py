import socket,json,re,sys
sock=sys.argv[1] if len(sys.argv)>1 else "/data/workspace/mon.sock"
s=socket.socket(socket.AF_UNIX); s.connect(sock); s.settimeout(20)
buf=b""
def rpc(obj):
    global buf
    s.sendall((json.dumps(obj)+"\n").encode())
    while True:
        buf+=s.recv(1<<20)
        txt=buf.decode(errors="replace"); lines=txt.split("\n")
        for i,l in enumerate(lines):
            if not l.strip(): continue
            try: d=json.loads(l)
            except Exception: continue
            if "return" in d or "error" in d:
                buf=("\n".join(lines[i+1:])).encode(); return d
print("cap:",rpc({"execute":"qmp_capabilities"}))
def hmp(c): return rpc({"execute":"human-monitor-command","arguments":{"command-line":c}}).get("return","")
reg=hmp("info registers"); print(reg)
pc=None
for l in reg.splitlines():
    m=re.search(r"R15=([0-9a-f]{8})",l)
    if m: pc=int(m.group(1),16)
print("PARSED_PC=",hex(pc) if pc else None)
if pc:
    print("=== disas pc-32 ===");  print(hmp("x/14i 0x%x"%(pc-32)))
