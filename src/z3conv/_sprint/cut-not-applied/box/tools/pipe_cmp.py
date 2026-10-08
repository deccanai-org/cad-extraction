"""pipe_cmp.py ID [ID...] : deployed kit vs patched kit, full pipeline outputs (pipes/kit/<id>, pipes/kitp/<id>):
decoder counts, OCC read-back validity, per-part STEP volumes joined by GlobalId, volume removed by the newly applied cuts per parent,
phantom cut bodies no longer written as steel, and weight per profile bucket vs the model folder's Tekla part list (when present)."""
import sys, os, json, gzip, collections, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from report_parse import pick, bucket
RHO = 7.85e-6     # kg / mm3 (Tekla default steel density 7850 kg/m3)
def load(d):
    o = {}
    for k in ('convert', 'check', 'join', 'pipe'):
        p = os.path.join(d, k + '.json')
        o[k] = json.load(open(p)) if os.path.exists(p) else {}
    pl = os.path.join(d, 'convert.json.parts.json.gz')
    o['parts'] = json.load(gzip.open(pl, 'rt')) if os.path.exists(pl) else []
    sp = os.path.join(d, 'step_parts.jsonl.gz')
    o['step'] = [json.loads(l) for l in gzip.open(sp, 'rt')] if os.path.exists(sp) else []
    return o
def per_part(o):
    vol = {}
    for s in o['step']:
        if s.get('pid') and s.get('volume') is not None: vol[s['pid']] = vol.get(s['pid'], 0) + s['volume']
    out = {}
    for pid, prof, cat, st, how, gid, nc in o['parts']:
        if st != 'written' or how in ('bolt_group', 'holes_only_group'): continue
        out[pid] = (prof, how, nc, vol.get(gid))
    return out
allres = {}
for ID in sys.argv[1:]:
    A, B = load(os.environ.get('PIPE_A', 'pipes/kit') + f'/{ID}'), load(os.environ.get('PIPE_B', 'pipes/kitp') + f'/{ID}')
    if not A['parts'] or not B['parts']:
        print('==', ID, 'missing outputs'); continue
    ca, cb = A['convert'], B['convert']; ka, kb = A['check'], B['check']
    pa, pb = per_part(A), per_part(B)
    # parents with more cuts after the patch: removed volume
    rem = []; grow = []; noeff = 0; newcut_parents = 0
    for pid, (prof, how, nc, v) in pb.items():
        if pid in pa and nc > pa[pid][2] and v is not None and pa[pid][3] is not None:
            newcut_parents += 1
            d = pa[pid][3] - v
            if d < -1e-3 * max(1.0, pa[pid][3]): grow.append((pid, prof, round(pa[pid][3]), round(v)))
            elif d <= 1e-4 * pa[pid][3]: noeff += 1
            else: rem.append(d)
    phantom = [(pid, x) for pid, x in pa.items() if pid not in pb]          # written before, cut body (or gone) after
    recovered = [(pid, x) for pid, x in pb.items() if pid not in pa]
    vol_ph = sum(x[3] or 0 for _, x in phantom); vol_rc = sum(x[3] or 0 for _, x in recovered)
    totA = sum((x[3] or 0) for x in pa.values()); totB = sum((x[3] or 0) for x in pb.values())
    r = dict(id=ID, engine=A['pipe'].get('engine'),
             written=(ca.get('written'), cb.get('written')), cuts_applied=(ca.get('cuts_applied'), cb.get('cuts_applied')),
             cut_body_unbuilt=((ca.get('skipped') or {}).get('cut_body_unbuilt', 0), (cb.get('skipped') or {}).get('cut_body_unbuilt', 0)),
             cut_parts=((ca.get('skipped') or {}).get('cut_part_excluded', 0), (cb.get('skipped') or {}).get('cut_part_excluded', 0)),
             solids=(ka.get('solids'), kb.get('solids')), invalid=(ka.get('invalid'), kb.get('invalid')), nonpos=(ka.get('nonpos_vol'), kb.get('nonpos_vol')),
             empty_roots=(ka.get('empty_roots'), kb.get('empty_roots')), step_rc=(A['pipe'].get('step_rc'), B['pipe'].get('step_rc')),
             step_sec=(A['pipe'].get('step_sec'), B['pipe'].get('step_sec')), render_ink=(ka.get('render_ink'), kb.get('render_ink')),
             join_cov=((A['join'].get('coverage') or {}).get('all'), (B['join'].get('coverage') or {}).get('all')),
             vol_outside_5pct=(((A['join'].get('volume') or {}).get('outside_5pct')), ((B['join'].get('volume') or {}).get('outside_5pct'))),
             parents_with_new_cuts=newcut_parents, removed_kg=round(sum(rem) * RHO, 1), parents_material_removed=len(rem), parents_cut_no_effect=noeff,
             parents_volume_grew=len(grow), grew_examples=grow[:5],
             phantom_parts_no_longer_steel=len(phantom), phantom_kg=round(vol_ph * RHO, 1), phantom_profiles=collections.Counter(x[0] for _, x in phantom).most_common(6),
             recovered_parts=len(recovered), recovered_kg=round(vol_rc * RHO, 1), recovered_profiles=collections.Counter(x[0] for _, x in recovered).most_common(6),
             steel_kg=(round(totA * RHO, 1), round(totB * RHO, 1)))
    f, rows = pick(os.path.join('reports', ID))
    if rows:
        rq = collections.Counter(); rw = collections.Counter()
        for mk, prof, q, L, w in rows: rq[bucket(prof)] += q; rw[bucket(prof)] += w
        def agg(p):
            c = collections.Counter(); w = collections.Counter()
            for pid, (prof, how, nc, v) in p.items():
                c[bucket(prof)] += 1; w[bucket(prof)] += (v or 0) * RHO
            return c, w
        cA, wA = agg(pa); cB, wB = agg(pb)
        keys = sorted(set(rq) | set(cA) | set(cB), key=lambda k: -rw.get(k, 0))
        tab = []
        for k in keys:
            if rq[k] == 0 and cA[k] == cB[k]: continue
            tab.append((k, rq[k], round(rw[k], 1), cA[k], round(wA[k], 1), cB[k], round(wB[k], 1)))
        inrep = [k for k in keys if rq[k] > 0]
        r['report'] = dict(file=os.path.basename(f), report_parts=sum(rq.values()), report_kg=round(sum(rw.values()), 1),
                           model_kg_in_report_buckets=(round(sum(wA[k] for k in inrep), 1), round(sum(wB[k] for k in inrep), 1)),
                           abs_kg_err_report_buckets=(round(sum(abs(wA[k] - rw[k]) for k in inrep), 1), round(sum(abs(wB[k] - rw[k]) for k in inrep), 1)),
                           abs_count_err_all=(sum(abs(cA[k] - rq[k]) for k in keys), sum(abs(cB[k] - rq[k]) for k in keys)),
                           model_kg_outside_report_buckets=(round(sum(wA[k] for k in keys if rq[k] == 0), 1), round(sum(wB[k] for k in keys if rq[k] == 0), 1)),
                           table=tab[:40])
    allres[ID] = r
    print(json.dumps(r, default=str))
json.dump(allres, open('res/pipe_cmp.json', 'w'), default=str, indent=1)
