"""Validate our rebuilt PCFs against Smart 3D's original isometric PCFs (DRAWNGDocumentData, read-only).

Match by UCI (= S3D part oid, present in both). Per matched part: PCF type, SKEY, end points (<= 1 mm, pipes may be split
into several original records), bores. Also record counts by type, and welds/gaskets/bolts/supports by UCI.
Originals were generated when the iso was issued; the model may have changed since ("drift"): parts only in one side.

pcfval.py run [--workers 8]  -> OUT/pairs/pcf_validation.jsonl.gz, WORK/pcf_validation.json
"""
import os, sys, json, gzip, glob, math, pickle, time, collections, argparse, traceback
from common import *
import docblob, pcfparse

PD = os.path.join(WORK, 'pairs')
SKIP = {'FLOW-ARROW', 'END-POSITION-CLOSED', 'END-POSITION-OPEN', 'END-POSITION-NULL', 'END-CONNECTION-PIPELINE', 'END-CONNECTION-EQUIPMENT',
        'END-CONNECTION-NULL', 'MESSAGE-SQUARE', 'MESSAGE-CIRCLE', 'MESSAGE-TRIANGLE', 'MESSAGE-ROUND', 'ISO-SPLIT-POINT', 'DIMENSION'}
ITEMS = {'WELD', 'GASKET', 'BOLT', 'SUPPORT'}
TOL = 1.0   # mm


def group(t):
    t = (t or '').upper()
    for k in ('VALVE', 'INSTRUMENT', 'FLANGE', 'REDUCER', 'TEE', 'OLET', 'ELBOW', 'BEND', 'PIPE'):
        if t.startswith(k):
            return {'BEND': 'ELBOW', 'TEE': 'TEE' if t != 'TEE-STUB' else 'TEE-STUB'}.get(k, k)
    return t


def choose_docs():
    sheets = pickle.load(open(os.path.join(PD, 'sheets.pkl'), 'rb'))
    D = pickle.load(open(os.path.join(PD, 'docs.pkl'), 'rb'))
    pcf_by_mgr = collections.defaultdict(list)
    for d in D['docs']:
        if (d['FileType'] or '').lower() == 'pcf':
            pcf_by_mgr[d['mgr'].upper()].append(d)
    best = {}
    for s in sheets:
        if s.get('target_cls') != 210007 or not s.get('mgr'):
            continue
        ds = pcf_by_mgr.get(s['mgr'].upper())
        if not ds:
            continue
        pl = s['target'].upper()
        d = max(ds, key=lambda d: d['FileSize'] or 0)
        key = (str(s['TimeLastUpdated']), d['FileSize'] or 0)
        cand = best.get(pl)
        n = (cand[2] + 1) if cand else 1
        if cand is None or key > cand[0]:
            best[pl] = (key, {'doc': d['doc'].upper(), 'file': d['FileName'], 'sheet': s['sheet'].upper(), 'sheet_file': s['FileName'],
                              'sheet_updated': str(s['TimeLastUpdated'])}, n)
        else:
            best[pl] = (cand[0], cand[1], n)
    return {pl: dict(v[1], n_candidate_sheets=v[2]) for pl, v in best.items()}


def pts(c):
    out = [p[:3] for p in c['ep']]
    return out


def compare(O, U, pc=None):
    pc = pc or {}
    oc = [c for c in O['comps'] if c['type'] not in SKIP]
    uc = [c for c in U['comps'] if c['type'] not in SKIP]
    r = collections.OrderedDict()
    r['orig_ref'] = O['ref']; r['ours_ref'] = U['ref']
    r['orig_counts'] = dict(collections.Counter(c['type'] for c in oc))
    r['ours_counts'] = dict(collections.Counter(c['type'] for c in uc))
    ob = collections.defaultdict(list); ub = collections.defaultdict(list)
    for c in oc:
        if c['uci']:
            ob[c['uci'].split('-P')[0] if c['type'] == 'TEE-STUB' else c['uci']].append(c)
    for c in uc:
        if c['uci']:
            ub[c['uci'].split('-P')[0] if c['type'] == 'TEE-STUB' else c['uci']].append(c)
    s = collections.Counter()
    mism = []
    for u in set(ob) | set(ub):
        A, B = ob.get(u), ub.get(u)
        kind = 'item' if (A or B)[0]['type'] in ITEMS else 'comp'
        if A and not B:
            s[kind + '_only_orig'] += 1; continue
        if B and not A:
            s[kind + '_only_ours'] += 1; continue
        s[kind + '_matched'] += 1
        if kind == 'item':
            continue
        ta, tb = group(A[0]['type']), group(B[0]['type'])
        if ta == tb:
            s['type_ok'] += 1
        else:
            s['type_diff'] += 1
            if len(mism) < 8:
                mism.append({'uci': u, 'orig': A[0]['type'], 'ours': B[0]['type']})
        ka, kb = A[0]['skey'], B[0]['skey']
        cls_ = pc.get(u)
        if cls_:
            LEARN.append((cls_[0], cls_[1], A[0]['type'], ka, B[0]['type'], kb))
        if ka and kb:
            s['skey_compared'] += 1
            base_ok = ka[:2] == kb[:2]
            if ka == kb or (ka.endswith('**') and base_ok):
                s['skey_ok'] += 1
            elif len(mism) < 16:
                mism.append({'uci': u, 'type': ta, 'skey_orig': ka, 'skey_ours': kb})
            s['skey_exact'] += ka == kb
            s['skey_base_ok'] += base_ok
            s['skey_orig_wildcard'] += ka.endswith('**')
        # end points: every point of ours must coincide with an original point of the same part, and vice versa for non-pipes
        PA = [p for c in A for p in c['ep']]; PB = [p for c in B for p in c['ep']]
        if PA and PB:
            s['points_compared'] += 1
            def near(p, L):
                best = None
                for q in L:
                    d = math.dist(p[:3], q[:3])
                    if best is None or d < best[0]:
                        best = (d, q)
                return best
            dmax = 0.0; bore_ok = True
            for p in PB:
                d, q = near(p, PA)
                dmax = max(dmax, d)
                if p[3] and q[3] and abs(p[3] - q[3]) > 0.5:
                    bore_ok = False
            if ta != 'PIPE':
                for p in PA:
                    dmax = max(dmax, near(p, PB)[0])
            s['pts_le_5mm'] += dmax <= 5.0
            s['pts_le_25mm'] += dmax <= 25.0
            s['pts_%s_n' % ta] += 1
            s['pts_%s_le1' % ta] += dmax <= TOL
            s['pts_%s_le5' % ta] += dmax <= 5.0
            if dmax <= TOL:
                s['points_ok'] += 1
            else:
                s['points_diff'] += 1
                s['points_diff_gt_10mm'] += dmax > 10
                if len(mism) < 24:
                    mism.append({'uci': u, 'type': ta, 'max_dev_mm': round(dmax, 2)})
            s['bore_compared'] += 1
            s['bore_ok'] += bore_ok
        if ta in ('TEE', 'OLET', 'TEE-STUB'):
            BA = [p for c in A for p in c['bp']]; BB = [p for c in B for p in c['bp']]
            if BA and BB:
                s['branch_compared'] += 1
                s['branch_ok'] += min(math.dist(BB[0][:3], q[:3]) for q in BA) <= TOL
    r['stats'] = dict(s)
    r['identical_part_set'] = s['comp_only_orig'] == 0 and s['comp_only_ours'] == 0
    r['mismatch_samples'] = mism
    return r


_c = None
LEARN = []


def _work(batch):
    global _c
    if _c is None:
        _c = connect(MDB)
    out = []
    ids = [b[1]['doc'] for b in batch]
    blobs = {}
    for i in range(0, len(ids), 50):
        cols, rows = query(_c, "SELECT CAST(oid AS char(36)), DataBlob, FileCompressed FROM dbo.DRAWNGDocumentData WHERE oid IN (%s)" % guid_list(ids[i:i + 50]))
        for o, b, fc in rows:
            blobs[o.upper()] = (b, fc)
    for pl, info, ours in batch:
        rec = collections.OrderedDict(pipeline=pl, name=ours['name'], area=ours['area'], ours_pcf=ours['pcf_file'], orig=info)
        try:
            b, fc = blobs[info['doc']]
            txt, how = docblob.decode(b, fc)
            O = pcfparse.parse(txt.decode('latin1'))
            U = pcfparse.parse(open(os.path.join(OUT, ours['pcf_file'])).read())
            pc = {}
            try:
                J = read_json(os.path.join(OUT, ours['json']))
                pc = {C['oid']: (C.get('part_class'), C.get('skey_source')) for C in J['components']}
            except Exception:
                pass
            rec.update(compare(O, U, pc))
        except Exception as e:
            rec['error'] = '%s: %s' % (type(e).__name__, str(e)[:200])
        out.append(rec)
    ev = list(LEARN); LEARN.clear()
    return out, ev


def run(workers):
    docs = choose_docs()
    pl_out = {}
    for f in glob.glob(os.path.join(WORK, 'done', 'piping', 'pb*.json')):
        for r in json.load(open(f))['results']:
            if 'error' not in r:
                pl_out[r['pl'].upper()] = r
    items = [(pl, info, pl_out[pl]) for pl, info in docs.items() if pl in pl_out]
    log('pipelines with an original PCF: %d (of %d with our PCF)' % (len(items), len(pl_out)))
    batches = [items[i:i + 150] for i in range(0, len(items), 150)]
    import multiprocessing as mp
    tot = collections.Counter(); per_type_o = collections.Counter(); per_type_u = collections.Counter()
    n_err = 0; ident = 0; n = 0
    sub = collections.Counter()           # stats restricted to pipelines whose part set is unchanged since the iso
    od = os.path.join(OUT, 'pairs'); os.makedirs(od, exist_ok=True)
    with gzip.open(os.path.join(od, 'pcf_validation.jsonl.gz.tmp'), 'wt') as f, mp.get_context('fork').Pool(workers) as pool:
        learn = collections.Counter()
        for res, ev in pool.imap_unordered(_work, batches):
            learn.update(ev)
            for rec in res:
                f.write(json.dumps(rec, default=str) + '\n'); n += 1
                if 'error' in rec:
                    n_err += 1; continue
                tot.update(rec['stats']); per_type_o.update(rec['orig_counts']); per_type_u.update(rec['ours_counts'])
                if rec['identical_part_set']:
                    ident += 1; sub.update(rec['stats'])
            log('pcf validation %d/%d' % (n, len(items)))
    os.replace(os.path.join(od, 'pcf_validation.jsonl.gz.tmp'), os.path.join(od, 'pcf_validation.jsonl.gz'))

    # learned Smart 3D iso conventions per part class (majority of matched originals)
    bycls = collections.defaultdict(collections.Counter)
    for (pcls, src, ot, ok, ut, uk), n_ in learn.items():
        bycls[pcls][(ot, ok, ut, uk)] += n_
    learned = {}
    for pcls, c in bycls.items():
        tot_ = sum(c.values())
        (ot, ok, ut, uk), top = c.most_common(1)[0]
        otc = collections.Counter(); okc = collections.Counter()
        for (a, b, _, _), v in c.items():
            otc[a] += v; okc[b] += v
        learned[pcls or '?'] = {'n': tot_, 'orig_type': otc.most_common(1)[0][0], 'orig_type_share': round(otc.most_common(1)[0][1] / tot_, 3),
                                'orig_skey': okc.most_common(1)[0][0], 'orig_skey_share': round(okc.most_common(1)[0][1] / tot_, 3),
                                'ours_type': ut, 'ours_skey': uk}
    json.dump(learned, open(os.path.join(WORK, 'skey_learned.json'), 'w'), indent=1)

    def rates(s):
        g = lambda a, b: round(100.0 * s[a] / s[b], 2) if s[b] else None
        return {'parts_matched_by_uci': s['comp_matched'], 'parts_only_in_original': s['comp_only_orig'], 'parts_only_in_ours': s['comp_only_ours'],
                'part_match_pct_of_original': round(100.0 * s['comp_matched'] / max(1, s['comp_matched'] + s['comp_only_orig']), 2),
                'type_agreement_pct': g('type_ok', 'comp_matched'), 'skey_agreement_pct_wildcard_aware': g('skey_ok', 'skey_compared'),
                'endpoints_within_1mm_pct': g('points_ok', 'points_compared'), 'endpoints_off_gt_10mm': s['points_diff_gt_10mm'],
                'bore_agreement_pct': g('bore_ok', 'bore_compared'), 'endpoints_within_5mm_pct': g('pts_le_5mm', 'points_compared'),
                'endpoints_within_25mm_pct': g('pts_le_25mm', 'points_compared'),
                'skey_exact_pct': g('skey_exact', 'skey_compared'), 'skey_base_pct': g('skey_base_ok', 'skey_compared'),
                'orig_skey_wildcard_pct': g('skey_orig_wildcard', 'skey_compared'),
                'endpoints_by_type': {t: {'n': s['pts_%s_n' % t], 'le1mm_pct': g('pts_%s_le1' % t, 'pts_%s_n' % t), 'le5mm_pct': g('pts_%s_le5' % t, 'pts_%s_n' % t)}
                                      for t in ('PIPE', 'ELBOW', 'TEE', 'TEE-STUB', 'OLET', 'REDUCER', 'FLANGE', 'VALVE', 'INSTRUMENT', 'CAP', 'MISC-COMPONENT') if s['pts_%s_n' % t]}, 'branch_point_agreement_pct': g('branch_ok', 'branch_compared'),
                'welds_gaskets_bolts_supports_matched_by_uci': s['item_matched'], 'items_only_in_original': s['item_only_orig'],
                'items_only_in_ours': s['item_only_ours']}
    summary = {'generated': utcnow(), 'pipelines_compared': n - n_err, 'errors': n_err,
               'original_source': 'Smart 3D isometric PCF (latest iso sheet per pipeline) from DRAWNGDocumentData',
               'match_key': 'UCI (Smart 3D part oid) in both PCFs; points tolerance 1 mm',
               'all': rates(tot), 'pipelines_with_unchanged_part_set': ident, 'unchanged_part_set': rates(sub),
               'record_counts_original': dict(per_type_o.most_common()), 'record_counts_ours': dict(per_type_u.most_common()),
               'per_pipeline': 'pairs/pcf_validation.jsonl.gz'}
    json.dump(summary, open(os.path.join(WORK, 'pcf_validation.json'), 'w'), indent=1)
    write_json(os.path.join(od, 'pcf_validation_summary.json'), summary, gz=False)
    log(json.dumps(summary, indent=1)[:3000])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd'); ap.add_argument('--workers', type=int, default=8); a = ap.parse_args()
    run(a.workers)
