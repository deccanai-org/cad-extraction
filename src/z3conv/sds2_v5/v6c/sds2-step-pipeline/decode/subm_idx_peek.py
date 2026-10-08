"""subm_idx slot size (from name-string spacing), per-slot string offsets, and _link file format."""
import os, sys, re, collections, struct
import numpy as np

job = sys.argv[1]
sd = os.path.join(job, "subm")
b = open(os.path.join(sd, "subm_idx"), "rb").read()
pos = [(m.start(), m.group()) for m in re.finditer(rb"(?<![ -~])(W\d+x[\d.]+|L\d[ -~]*?x[\d/ ]+|FL[\d/]+x[\d/ ]+|HSS[\dx/.]+|C\d+x[\d.]+)\x00", b)]
sp = collections.Counter(pos[i + 1][0] - pos[i][0] for i in range(len(pos) - 1))
print("name spacing top:", sp.most_common(6))
slot = sp.most_common(1)[0][0]
print("slot", slot, "(size-256)%slot =", (len(b) - 256) % slot, "cap", (len(b) - 256) / slot)
print("name offset in slot:", collections.Counter(p % slot for p, _ in pos).most_common(3))
# strings per slot for first few numbered subm
for n in (1, 2, 3, 1001, 1002):
    s = b[n * slot:(n + 1) * slot]
    print(f"slot {n}:", [(hex(m.start()), m.group().decode()) for m in re.finditer(rb"[A-Za-z0-9#][ -~]{2,}", s)][:14])
# link files
links = sorted(f for f in os.listdir(sd) if f.endswith("_link"))
print("link files:", len(links))
for f in links[:3]:
    x = open(os.path.join(sd, f), "rb").read()
    print(f, len(x), x[:96].hex())
    print("   as >i:", struct.unpack(f">{min(len(x)//4, 24)}i", x[:4 * min(len(x)//4, 24)]))
