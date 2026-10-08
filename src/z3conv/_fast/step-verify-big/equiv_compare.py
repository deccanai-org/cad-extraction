#!/usr/bin/env python3
"""Compare a streamed result (step_verify_big.py) with a full OCC read-back (step_check.py) of the same STEP file.
usage: equiv_compare.py FULL.json FULL.parts.jsonl.gz STREAM.json STREAM.parts.jsonl.gz [OUT.json] [--label L]
(FULL.json may be a grader result record (its validate block is used) or "-" for a parts-only comparison)
Top-level signals are compared field by field; parts are joined by root index `i` (global root order) and the
(pid, name) pair is checked to be the same product; per part: solids, shells, faces, bbox, valid, volume, empty, nonfinite."""
import sys, os, json, gzip, math, argparse, collections

TOP = ['read_status', 'roots', 'transferred', 'empty_roots', 'solids', 'shells', 'faces', 'checked', 'valid', 'invalid', 'nonpos_vol',
       'nonfinite', 'valid_solids_est', 'invalid_solids_est', 'invalid_frac', 'sampled', 'check_fraction', 'products', 'approx_products',
       'markers', 'schema', 'bbox', 'roots_mapped_to_products', 'invalid_examples', 'v6_tags']
PART = ['pid', 'name', 'desc', 'solids', 'shells', 'faces', 'bbox', 'valid', 'volume', 'empty', 'nonfinite']


def load_parts(p):
    out = []
    with gzip.open(p, 'rt') as f:
        for l in f:
            if l.strip():
                out.append(json.loads(l))
    return out


def same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('full'); ap.add_argument('full_parts'); ap.add_argument('stream'); ap.add_argument('stream_parts')
    ap.add_argument('out', nargs='?'); ap.add_argument('--label', default='')
    a = ap.parse_args()
    def loadj(p):
        if p in ('-', '', None) or not os.path.exists(p):
            return {}
        d = json.load(open(p))
        if 'read_status' not in d and isinstance(d.get('validate'), dict):
            d = d['validate']                             # a grader result record: its validate block is the step_check output
        return d
    F = loadj(a.full); S = loadj(a.stream)
    top = {}
    for k in TOP:
        if F and S and (k in F or k in S):
            fv, sv = F.get(k), S.get(k)
            eq = same(fv, sv)
            note = None
            if not eq and k == 'invalid_examples' and isinstance(fv, list) and isinstance(sv, list) and 10 in (len(fv), len(sv)):
                # stored grader results keep only the first 10 (worker.py: invalid_examples[:10]): compare that prefix
                n_ = min(len(fv), len(sv)); eq = fv[:n_] == sv[:n_]; note = f'compared first {n_} (stored result truncated to 10)'
            top[k] = {'full': fv, 'stream': sv, 'equal': eq}
            if note:
                top[k]['note'] = note
    fp = load_parts(a.full_parts); sp = load_parts(a.stream_parts)
    fi = {p['i']: p for p in fp}; si = {p['i']: p for p in sp}
    n = 0; exact = 0; mism = collections.Counter(); ex = []
    vol_abs = 0.0; vol_rel = 0.0; bbox_max = 0.0
    only_full = sorted(set(fi) - set(si)); only_stream = sorted(set(si) - set(fi))
    for i in sorted(set(fi) & set(si)):
        x, y = fi[i], si[i]; n += 1
        bad = []
        for k in PART:
            if not same(x.get(k), y.get(k)):
                bad.append(k)
                if k == 'volume' and isinstance(x.get(k), (int, float)) and isinstance(y.get(k), (int, float)):
                    d = abs(x[k] - y[k]); vol_abs = max(vol_abs, d)
                    if x[k]:
                        vol_rel = max(vol_rel, d / abs(x[k]))
                if k == 'bbox' and x.get(k) and y.get(k):
                    bbox_max = max(bbox_max, max(abs(u - v) for u, v in zip(x[k], y[k])))
        if bad:
            for k in bad:
                mism[k] += 1
            if len(ex) < 20:
                ex.append({'i': i, 'fields': bad, 'full': {k: x.get(k) for k in bad + ['pid', 'name']}, 'stream': {k: y.get(k) for k in bad + ['pid', 'name']}})
        else:
            exact += 1
    rep = {'label': a.label, 'full': a.full, 'stream': a.stream,
           'top_level_all_equal': (all(v['equal'] for v in top.values()) if top else None), 'top_level': top,
           'parts_full': len(fp), 'parts_stream': len(sp), 'parts_compared': n, 'parts_identical': exact,
           'parts_only_in_full': len(only_full), 'parts_only_in_stream': len(only_stream),
           'mismatch_by_field': dict(mism), 'max_volume_abs_diff': vol_abs, 'max_volume_rel_diff': vol_rel, 'max_bbox_abs_diff': bbox_max,
           'mismatch_examples': ex}
    s = json.dumps(rep, indent=1)
    if a.out:
        open(a.out, 'w').write(s)
    print(json.dumps({k: rep[k] for k in ('label', 'top_level_all_equal', 'parts_full', 'parts_stream', 'parts_compared', 'parts_identical',
                                          'parts_only_in_full', 'parts_only_in_stream', 'mismatch_by_field', 'max_volume_abs_diff',
                                          'max_volume_rel_diff')}))
    for k, v in top.items():
        if not v['equal']:
            print('  top-level differs:', k, 'full =', json.dumps(v['full'])[:200], '| stream =', json.dumps(v['stream'])[:200])
    return 0


if __name__ == '__main__':
    sys.exit(main())
