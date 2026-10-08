import sys, os, re
sys.path.insert(0, sys.argv[1])
from piece_table import slot_size, LAYOUTS
W = '/work/agentwork/sds2-pieces-not-built/jobs/'


def slot_size_job(job, b):
    # the SDS2 fixer's v5work draft (piece_table.slot_size_job), unchanged
    try:
        ids = sorted(int(n) for n in os.listdir(os.path.join(job, "subm")) if n.isdigit())
    except OSError:
        ids = []
    first = slot_size(b)
    if len(ids) < 20:
        return first
    step = max(1, len(ids) // 400)
    sample = ids[::step]
    rx = re.compile(rb"(PL|FL|W|HSS|L|C|MC|WT|S|HP|PIPE|BPL|BLT|RB|RD|WS|HS|SQ|BAR|TS|GT|GR|ST|MT|M|Conc|[0-9]+[KL])[0-9A-Za-z /.x-]*\x00")

    def score(key):
        S, o = LAYOUTS[key]["slot"], LAYOUTS[key]["name"]
        return sum(bool(rx.match(b[k * S + o:k * S + o + 0x30])) for k in sample if (k + 1) * S <= len(b))
    sc = {k: score(k) for k in LAYOUTS}
    best = max(sc, key=lambda k: (sc[k], (len(b) - 256) % LAYOUTS[k]["slot"] == 0))
    if sc[best] >= max(10, 2 * sc[first]) and sc[best] >= 0.5 * len(sample):
        return best
    return first


n = same = 0
for d in sorted(os.listdir(W)):
    p = os.path.join(W, d, 'subm', 'subm_idx')
    if not os.path.isfile(p):
        continue
    b = open(p, 'rb').read()
    a, j = slot_size(b), slot_size_job(os.path.join(W, d), b)
    n += 1; same += (a == j)
    if a != j:
        print('DIFF', d, a, j)
print('jobs', n, 'same layout', same)
