"""parts_lost.py: per-part decoder status across the reconstructed code kits (b0 = pre-bolt .. i) on every data-3 DB1 model,
reproduction check against the deployed results, and the STEP stage of every deployed output version (unversioned <= g, .h, .i).
out: report/parts_lost.json"""
import json, os, gzip, collections, glob
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
KITS = ['b0', 'c', 'f', 'g', 'h', 'i', 'j', 'jfix']
CODE_OF = {'z3-db1-2026-10-01' + k: k for k in 'bcfghij'}
ENG = json.load(open('state/engines.json'))
jobs = json.load(open('state/all_jobs.json'))
out = {'per_model': {}, 'transitions': {}, 'repro': collections.Counter(), 'repro_mismatch': [], 'step': {}}
tr = {f'{a}->{b}': collections.Counter() for a, b in zip(KITS, KITS[1:])}
tr['b0->i'] = collections.Counter()
lost_ex = collections.defaultdict(list)


DIR = {k: k + '_nb' for k in KITS}


def plist(k, i):
    p = f'dec/{DIR.get(k, k)}/{i}.json.parts.json.gz'
    if not os.path.exists(p): return None
    return {r[0]: r for r in json.load(gzip.open(p, 'rt'))}


for j in jobs:
    i = j['id']; m = {'engine': ENG.get(i)}
    P = {k: plist(k, i) for k in KITS}
    S = {}
    for k in KITS:
        sp = f'dec/{DIR.get(k, k)}/{i}.json'
        S[k] = json.load(open(sp)) if os.path.exists(sp) else None
    m['status'] = {k: (S[k] or {}).get('status') for k in KITS}
    m['written'] = {k: (sum(1 for r in P[k].values() if r[3] == 'written') if P[k] else None) for k in KITS}
    m['written_physical'] = {k: (sum(1 for r in P[k].values() if r[3] == 'written' and r[4] != 'holes_only_group') if P[k] else None) for k in KITS}
    for a, b in list(zip(KITS, KITS[1:])) + [('b0', 'i')]:
        if not P[a] or not P[b]: continue
        c = tr[f'{a}->{b}']
        wa = {p for p, r in P[a].items() if r[3] == 'written' and r[4] != 'holes_only_group'}
        wb = {p for p, r in P[b].items() if r[3] == 'written' and r[4] != 'holes_only_group'}
        for p in wa - wb:
            why = P[b][p][4] if p in P[b] else 'record_gone'
            c['lost:' + str(why)] += 1
            if len(lost_ex[f'{a}->{b}']) < 15: lost_ex[f'{a}->{b}'].append({'id': i[:12], 'pid': p, 'prof': P[a][p][1], 'was': P[a][p][4], 'now': why})
        for p in wb - wa:
            c['gained:' + str(P[b][p][4]) + '<-' + str(P[a][p][4] if p in P[a] else 'new')] += 1
        if wa - wb: m.setdefault('lost', {})[f'{a}->{b}'] = len(wa - wb)
    # reproduction: deployed result (latest code) vs my decode with that code's kit
    rp = f'res/{i}.json'
    if os.path.exists(rp):
        R = json.load(open(rp)); k = CODE_OF.get(R.get('code'))
        m['deployed_code'] = R.get('code'); m['deployed_status'] = R.get('status')
        cv = R.get('convert') or {}
        dw = (cv.get('written') - (cv.get('sources') or {}).get('bolt_group', 0)) if cv.get('written') is not None else None   # bolts off on this box
        mine = (S.get(k) or {}).get('written') if k else None
        if k and dw is not None:
            ok = dw == mine; out['repro']['match' if ok else 'mismatch'] += 1
            if not ok: out['repro_mismatch'].append({'id': i[:12], 'code': k, 'deployed_written': dw, 'mine': mine})

    # deployed STEP versions
    st = {}
    for suf in ('', '.h', '.i'):
        cp = f'out/{i}{suf}.stp.check.json'
        if not os.path.exists(cp): continue
        C = json.load(open(cp))
        spp = f'det/{i}{suf}.step_parts.jsonl.gz'
        nos = inv = 0; invp = []
        if os.path.exists(spp):
            for l in gzip.open(spp, 'rt'):
                x = json.loads(l)
                if not x.get('solids'): nos += 1
                if (x.get('valid') or 0) < (x.get('solids') or 0): inv += 1; invp.append(x.get('name', '')[:60])
        st[suf or 'u'] = {'products': C.get('products'), 'solids': C.get('solids'), 'invalid': C.get('invalid'), 'nonpos': C.get('nonpos_vol'),
                          'parts_no_solid': nos, 'parts_with_invalid': inv, 'invalid_names': collections.Counter(invp).most_common(8),
                          'render_ink': C.get('render_ink'), 'approx_products': C.get('approx_products'), 'v6_tags': C.get('v6_tags')}
    m['step'] = st
    out['per_model'][i] = m
out['transitions'] = {k: dict(v) for k, v in tr.items()}
out['lost_examples'] = lost_ex
out['repro'] = dict(out['repro'])
json.dump(out, open('report/parts_lost.json', 'w'), indent=1, default=str)
print(json.dumps({'transitions': out['transitions'], 'repro': out['repro'], 'repro_mismatch': out['repro_mismatch'][:20]}, indent=1, default=str))
