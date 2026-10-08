import sys, gzip, collections, numpy as np
sys.path.insert(0, 'kit')
import db1old
data = open(sys.argv[1], 'rb').read()
if data[:2] == b'\x1f\x8b': data = gzip.decompress(data)
import re
eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, _ = db1old.read(data, eng)
o = db1old.Old(data)
S = M[0]['stride']
bg = [m for m in M if m.get('bolt')]
print('engine', eng, 'stride', S, 'groups', len(bg))
# per byte offset beyond the decoded fields: distribution of int32 values for slotted vs not
def slotted(p):
    f = p.split('/'); return f[1] != '0' or f[2] != '0'
var = []
for k in range(0, S - 3):
    a = collections.Counter(); b = collections.Counter()
    for m in bg:
        v = int(o.I_all[m['off'] + k])
        (a if slotted(m['prof']) else b)[v] += 1
    if len(a) + len(b) > 2:
        var.append((k, a.most_common(3), b.most_common(3)))
for x in var: print(x)
