#!/usr/bin/env python3
"""Weight flags of the coordinator (build_index classify_sds2_manifest) on wdump outputs.
old rule : total ratio outside 0.95-1.05 -> 'sds2 weight 5%'; any family (n >= 5) off by > 5 % -> 'sds2 family weight'
new rule : (proposal) the same bands on untagged converter-built solids only (tagged stand-ins are graded as stand-ins); SDS2-exact families outside 0.85-1.2 -> info
usage: gradesim.py BASE_DIR PATCH_DIR [ids...]  -> per job flags before (old rule, v5.4) / after (old + new rule, patch)"""
import json, glob, os, sys

NMIN, TOL = 5, 0.05


def old_flags(d):
    w = d.get('weights') or {}
    sr = (w.get('step_lb') or 0) / w['sds2_lb'] if w.get('sds2_lb') else None
    fams = w.get('by_family') or {}
    off = sorted(f for f, x in fams.items() if x.get('ratio') is not None and (x.get('n') or 0) >= NMIN and abs(x['ratio'] - 1) > TOL)
    return dict(ratio=None if sr is None else round(sr, 4), w5=sr is not None and not 0.95 <= sr <= 1.05, fams=off)


def new_flags(d):
    w = d.get('weights') or {}
    bs = w.get('by_source') or {}
    fams = w.get('by_family') or {}
    if not bs:
        return None
    ex, bu, st = bs.get('exact') or {}, bs.get('built') or {}, bs.get('standin') or {}
    ref = (ex.get('sds2_lb') or 0) + (st.get('sds2_lb') or 0)
    den = ref + (bu.get('sds2_lb') or 0)
    sr1 = (ref + (bu.get('step_lb') or 0)) / den if den else None
    off = sorted(f for f, x in fams.items() if isinstance(x.get('built'), dict) and x['built'].get('ratio') is not None
                 and (x['built'].get('n') or 0) >= NMIN and abs(x['built']['ratio'] - 1) > TOL)
    info = sorted(f"{f} {x['exact']['ratio']}" for f, x in fams.items() if isinstance(x.get('exact'), dict) and x['exact'].get('ratio') is not None
                  and (x['exact'].get('n') or 0) >= NMIN and not 0.85 <= x['exact']['ratio'] <= 1.2)
    return dict(ratio=None if sr1 is None else round(sr1, 4), w5=sr1 is not None and not 0.95 <= sr1 <= 1.05, fams=off, info=info)


if __name__ == '__main__':
    A, B = sys.argv[1], sys.argv[2]
    rows = []
    for f in sorted(glob.glob(f'{B}/*.json')):
        i = os.path.basename(f)[:-5]
        if not os.path.exists(f'{A}/{i}.json'):
            continue
        a, b = json.load(open(f'{A}/{i}.json')), json.load(open(f))
        if 'weights' not in a or 'weights' not in b:
            continue
        o0, o1, n1 = old_flags(a), old_flags(b), new_flags(b)
        rows.append((i, b['job'], o0, o1, n1))
        print(f"{b['job'][:38]:38s} v5.4: w5={o0['w5']!s:5} {o0['ratio']} fams={','.join(o0['fams']) or '-'} | patch old-rule: w5={o1['w5']!s:5} "
              f"fams={','.join(o1['fams']) or '-'} | patch new-rule: w5={n1 and n1['w5']!s:5} {n1 and n1['ratio']} fams={n1 and (','.join(n1['fams']) or '-')}"
              f" info={n1 and n1['info']}")
    def cnt(k, j):
        return sum(1 for r in rows if r[j] and (r[j][k] if k == 'w5' else bool(r[j][k])))
    print(f"\njobs {len(rows)} | weight-5% flag: v5.4 {cnt('w5', 2)}, patch+old rule {cnt('w5', 3)}, patch+new rule {cnt('w5', 4)}"
          f" | family flag: v5.4 {cnt('fams', 2)}, patch+old rule {cnt('fams', 3)}, patch+new rule {cnt('fams', 4)}")
