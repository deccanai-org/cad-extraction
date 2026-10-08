import os, sys, re, collections
sys.path.insert(0, sys.argv[2])
import piece_table as PT
job = sys.argv[1]
b = open(os.path.join(job, "subm", "subm_idx"), "rb").read()
ids = sorted(int(n) for n in os.listdir(os.path.join(job, "subm")) if n.isdigit())
print("subm_idx bytes", len(b), "piece files", len(ids), "max id", max(ids))
for key, Lo in PT.LAYOUTS.items():
    S, o = Lo["slot"], Lo["name"]
    rx = re.compile(rb"(PL|FL|W|HSS|L|C|MC|WT|S|HP|PIPE|BPL|BLT|RB|RD|WS|HS|SQ|BAR|TS|GT|GR|ST|MT|M|Conc|[0-9]+[KL])[0-9A-Za-z /.x-]*\x00")
    good = sum(bool(rx.match(b[k * S + o:k * S + o + 0x30])) for k in ids if (k + 1) * S <= len(b))
    filled = sum(bool(re.match(rb"[!-~]", b[k * S + o:k * S + o + 1])) for k in ids if (k + 1) * S <= len(b))
    print(key, "slot", S, "rem", (len(b) - 256) % S, "n_slots", len(b) // S, "good names over piece files", good, "filled", filled, "first200 filled", sum(bool(re.match(rb"[!-~]", b[k * S + o:k * S + o + 1])) for k in range(1, min(200, len(b) // S))))
# names around the slot boundary for the first ids: find all ASCII piece-like names and their positions
pos = [m.start() for m in re.finditer(rb"(?<![ -~])(PL|W|L|HSS|C|BPL|FL)[0-9][0-9A-Za-z /.x-]*\x00", b)]
print("name hits", len(pos))
d = collections.Counter(pos[i+1] - pos[i] for i in range(len(pos)-1)).most_common(8)
print("spacing", d)
for S in (1024, 1028, 1032, 1040, 1048, 1056, 1064, 1072, 1080, 1088, 1096, 1104, 1112, 1120, 1128, 1136, 1144, 1152, 1176, 1200):
    c = collections.Counter(p % S for p in pos).most_common(2)
    print(S, c, (len(b) - 256) % S)
