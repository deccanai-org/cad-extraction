"""cutter_probe.py DEC_AFTER_JSON PROFILE... : obj_type-11 cut bodies of the given profiles: length, parents (profile / length), and the
real parts of the same profile"""
import sys, json, collections
d = json.load(open(sys.argv[1])); want = set(sys.argv[2:])
P = {p[0]: p for p in d['parts']}
par = collections.defaultdict(list)
for p_, cs in d['cut_rel'].items():
    for c in cs: par[c].append(int(p_))
for w in want:
    cut = [p for p in d['parts'] if p[1] == w and p[2]]
    real = [p for p in d['parts'] if p[1] == w and not p[2] and not p[3]]
    print('==', w, 'cut bodies', len(cut), 'lengths', collections.Counter(round(p[5]) for p in cut).most_common(6), '| real parts', len(real), collections.Counter(round(p[5]) for p in real).most_common(6))
    pc = collections.Counter()
    for p in cut:
        for q in par.get(p[0], []):
            pp = P.get(q); pc[(pp[1], round(pp[5])) if pp else ('not decoded', 0)] += 1
    print('   parents', pc.most_common(8))
