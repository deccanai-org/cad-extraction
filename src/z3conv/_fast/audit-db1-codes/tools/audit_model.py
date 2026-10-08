"""audit_model.py ID [ID...]: instrumented code-f run (kit_audit = code f + audit dump, geometry identical) ->
runs/audit/<id>.ifc, <id>.json (convert stats), <id>.audit.json (per bolt: group, axis, hits; per part: how),
<id>.rel10.json (source relation records type 10 = bolt group -> part, decoded from the stride-17 relation table)"""
import sys, os, json, re, collections, gzip, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'kit_audit'))
import db1step, db1old
from db1dec import load
CAT = json.load(open(os.path.join(ROOT, 'kit_audit', 'tekla_profiles.json')))
out_d = os.path.join(ROOT, 'runs', 'audit'); os.makedirs(out_d, exist_ok=True)
ids = {l.strip()[:12]: l.strip() for l in open(os.path.join(ROOT, 'ids.txt'))}


def rel_table(data):
    o = db1old.Old(data); N = len(o.I_all) - 400; I = o.I_all
    rv = np.zeros(N, bool); Mr = N - 20
    rv[:Mr] = (I[:Mr] > 0) & (I[4:Mr + 4] >= 0) & (I[4:Mr + 4] <= 2000) & (I[8:Mr + 8] > 0) & (I[12:Mr + 12] > 0)
    off = o.runs(rv, 17)
    return [(int(I[q]), int(I[q + 4]), int(I[q + 8]), int(I[q + 12])) for q in off]


for a in sys.argv[1:]:
    i = ids[a[:12]]
    if os.path.exists(os.path.join(out_d, i + '.rel10.json')):
        print(i[:12], 'cached'); continue
    src = os.path.join(ROOT, 'src', i + '.db1')
    os.environ['DB1_AUDIT'] = os.path.join(out_d, i + '.audit.json')
    st = db1step.convert(src, os.path.join(out_d, i + '.ifc'), CAT)
    pl = st.pop('parts_list', None)
    with gzip.open(os.path.join(out_d, i + '.parts.json.gz'), 'wt') as g:
        json.dump(pl, g)
    json.dump(st, open(os.path.join(out_d, i + '.json'), 'w'), default=str)
    rels = rel_table(load(src))
    json.dump({'types': dict(collections.Counter(t for _, t, _, _ in rels)), 'rel10': [(a_, b_) for _, t, a_, b_ in rels if t == 10]},
              open(os.path.join(out_d, i + '.rel10.json'), 'w'))
    print(i[:12], st.get('status'), st.get('written'), flush=True)
