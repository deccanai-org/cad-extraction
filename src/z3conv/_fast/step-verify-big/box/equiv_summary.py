#!/usr/bin/env python3
"""equiv_summary.py SPEC.json OUT.json
Equivalence of streamed runs (step_verify_big.py) with full OCC read-backs (step_check.py) of the same STEP file, with the kernel's
own run-to-run variation measured on the same file.

SPEC: {model: {"full": [[json, parts, label], ...],   # >= 1 full read-back (step_check.py); 2+ measure the kernel's variation
               "ec2": [json|"-", parts, label],        # optional: the grader's stored full read-back (another full read)
               "stream": [[json, parts, label], ...]}}
Per model:
  aligned        every run has the same roots in the same order (i -> same pid / name)
  unstable       roots on which the full reads disagree with each other (OCC shape healing is not deterministic on them)
  per stream run vs the first full read: parts identical / differing; differing parts that are unstable, that equal SOME full
                 read's record, and the unexplained rest (with their healed tolerance); top-level fields that differ
  stable_totals  sums over the roots outside `unstable` (solids, faces, valid, volume, roots with an invalid solid) for every run
Verdict per stream run: 'identical' (every part and every top-level field equal to the first full read), 'equal_modulo_kernel'
(every differing part is unstable or equals another full read of the same file, and the stable totals are equal), else 'DIFFERENT'."""
import sys, os, json, gzip, math, collections

PART = ['pid', 'name', 'desc', 'solids', 'shells', 'faces', 'bbox', 'valid', 'volume', 'empty', 'nonfinite']
TOP = ['read_status', 'roots', 'transferred', 'empty_roots', 'solids', 'shells', 'faces', 'checked', 'valid', 'invalid', 'nonpos_vol',
       'nonfinite', 'valid_solids_est', 'invalid_solids_est', 'invalid_frac', 'sampled', 'check_fraction', 'products', 'approx_products',
       'markers', 'schema', 'bbox', 'roots_mapped_to_products', 'v6_tags']


def lj(p):
    if not p or p == '-' or not os.path.exists(p):
        return {}
    d = json.load(open(p))
    if 'read_status' not in d and isinstance(d.get('validate'), dict):
        d = d['validate']
    return d


def lp(p):
    out = {}
    with gzip.open(p, 'rt') as f:
        for l in f:
            if l.strip():
                r = json.loads(l); out[r['i']] = r
    return out


def key(r):
    return tuple(json.dumps(r.get(k), sort_keys=True) for k in PART)


def stable_totals(parts, unstable):
    t = collections.Counter(); vol = 0.0
    for i, r in parts.items():
        if i in unstable:
            continue
        t['roots'] += 1; t['solids'] += r.get('solids') or 0; t['faces'] += r.get('faces') or 0; t['valid'] += r.get('valid') or 0
        t['roots_with_invalid'] += int((r.get('valid') is not None) and (r.get('valid') < (r.get('solids') or 0)))
        t['empty'] += int(bool(r.get('empty')))
        vol += r.get('volume') or 0.0
    d = dict(t); d['volume_sum'] = round(vol, 3)
    return d


def main():
    spec = json.load(open(sys.argv[1]))
    out = {}
    for m, sp in spec.items():
        fulls = [(lab, lj(j), lp(p)) for j, p, lab in sp.get('full', []) if os.path.exists(p)]
        ec2 = sp.get('ec2')
        refs = list(fulls)
        if ec2 and os.path.exists(ec2[1]):
            refs.append((ec2[2], lj(ec2[0]), lp(ec2[1])))
        streams = [(lab, lj(j), lp(p)) for j, p, lab in sp.get('stream', []) if os.path.exists(p)]
        if not refs:
            out[m] = {'error': 'no full read-back'}; continue
        R0lab, R0, P0 = refs[0]
        allruns = refs + streams
        ids = set(P0)
        aligned = all(set(P) == ids for _, _, P in allruns) and all(
            (P[i].get('pid'), P[i].get('name')) == (P0[i].get('pid'), P0[i].get('name')) for _, _, P in allruns for i in ids)
        unstable = set()
        for i in ids:
            ks = {key(P[i]) for _, _, P in refs if i in P}
            if len(ks) > 1:
                unstable.add(i)
        res = {'roots': len(ids), 'aligned': aligned, 'full_reads': [l for l, _, _ in refs], 'unstable_roots': len(unstable),
               'unstable_examples': [{'i': i, 'name': P0[i].get('name'), 'runs': {l: {k: P[i].get(k) for k in ('solids', 'faces', 'valid', 'volume')}
                                                                                    for l, _, P in refs}} for i in sorted(unstable)[:8]]}
        # full vs full (kernel variation baseline)
        base = []
        for l, J, P in refs[1:]:
            d = [i for i in ids if key(P[i]) != key(P0[i])]
            tl = [k for k in TOP if J and R0 and k in J and J.get(k) != R0.get(k)]
            base.append({'run': l, 'vs': R0lab, 'parts_differing': len(d), 'top_level_differing': {k: [R0.get(k), J.get(k)] for k in tl}})
        res['full_vs_full'] = base
        res['stable_totals'] = {l: stable_totals(P, unstable) for l, _, P in allruns}
        runs = []
        for l, J, P in streams:
            dif = [i for i in ids if key(P[i]) != key(P0[i])]
            anyfull = [i for i in dif if any(key(P[i]) == key(Q[i]) for _, _, Q in refs)]
            unexpl = [i for i in dif if i not in unstable and i not in anyfull]
            tl = {k: [R0.get(k), J.get(k)] for k in TOP if R0 and J and (k in R0 or k in J) and R0.get(k) != J.get(k)}
            tl_any = {k: v for k, v in tl.items() if not any(Jr.get(k) == J.get(k) for _, Jr, _ in refs if Jr)}
            st_eq = res['stable_totals'][l] == res['stable_totals'][R0lab]
            if not dif and not tl:
                verdict = 'identical'
            elif not unexpl and st_eq and aligned:
                verdict = 'equal_modulo_kernel'
            else:
                verdict = 'DIFFERENT'
            sj = J.get('streamed') or {}
            runs.append({'run': l, 'vs': R0lab, 'verdict': verdict, 'parts_identical': len(ids) - len(dif), 'parts_differing': len(dif),
                         'differing_unstable': sum(1 for i in dif if i in unstable), 'differing_equal_to_another_full_read': len(anyfull),
                         'differing_unexplained': len(unexpl),
                         'unexplained_examples': [{'i': i, 'full': {k: P0[i].get(k) for k in PART}, 'stream': {k: P[i].get(k) for k in PART + ['tol']}}
                                                  for i in unexpl[:10]],
                         'differing_with_tol_flag': sum(1 for i in dif if P[i].get('tol')),
                         'top_level_differing_vs_first_full': tl, 'top_level_differing_vs_every_full': tl_any,
                         'stable_totals_equal': st_eq,
                         'chunks': sj.get('chunks_run'), 'chunk_target_mb': round((sj.get('chunk_target_bytes') or 0) / 2**20, 1),
                         'complete': sj.get('complete'), 'peak_tree_rss_mb': round((sj.get('peak_tree_rss_bytes') or 0) / 2**20),
                         'peak_worker_rss_mb': round((sj.get('peak_worker_rss_bytes') or 0) / 2**20), 'sec': J.get('sec')})
        res['stream_vs_full'] = runs
        out[m] = res
    json.dump(out, open(sys.argv[2], 'w'), indent=1)
    for m, r in out.items():
        if 'error' in r:
            print(m, r['error']); continue
        print(f"{m}: roots {r['roots']} aligned {r['aligned']} unstable {r['unstable_roots']} | full-vs-full: " +
              '; '.join(f"{b['run']} {b['parts_differing']} parts, top {list(b['top_level_differing'])}" for b in r['full_vs_full']))
        for s in r['stream_vs_full']:
            print(f"   {s['run']}: {s['verdict']} identical {s['parts_identical']}/{r['roots']} differing {s['parts_differing']} "
                  f"(unstable {s['differing_unstable']}, = another full {s['differing_equal_to_another_full_read']}, unexplained "
                  f"{s['differing_unexplained']}) top-level vs first full {list(s['top_level_differing_vs_first_full'])} vs every full "
                  f"{list(s['top_level_differing_vs_every_full'])} stable totals equal {s['stable_totals_equal']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
