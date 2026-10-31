import sys

path = sys.argv[1]
off = int(sys.argv[2], 0)
ln = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x8000
f = open(path, "rb")
f.seek(off)
blob = f.read(ln)
txt = blob.decode("latin-1")
for line in txt.splitlines():
    clean = "".join(c if 32 <= ord(c) < 127 else "" for c in line).rstrip()
    if not clean:
        continue
    if clean.startswith(("I:", "E:", "W:", "Starting", "Recovery", "=>", "Unable",
                         "Failed", "Can not", "Updating", "Partition Logs", "tw_")):
        print(clean)
