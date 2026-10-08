"""parent_cutters.py DEC_AFTER_JSON PROFILE : for parents of the profile, the cutters linked to them (profile, length, ANTIMATERIAL or op-part)"""
import sys, json, collections
d = json.load(open(sys.argv[1])); P = {p[0]: p for p in d['parts']}
c = collections.Counter(); n = 0
for p_, cs in d['cut_rel'].items():
    pp = P.get(int(p_))
    if not pp or pp[1] != sys.argv[2]: continue
    n += 1
    for ch in cs:
        q = P.get(ch)
        c[(q[1], round(q[5]), 'ANTI' if q[6] == 'ANTIMATERIAL' else 'op') if q else ('not decoded',)] += 1
print(sys.argv[1].split('/')[-1][:16], sys.argv[2], 'parents with cuts', n, c.most_common(12))
