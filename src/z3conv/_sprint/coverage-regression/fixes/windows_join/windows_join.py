#!/usr/bin/env python3
"""Per-part grading of the owner's Windows (C#) tekla-step-pipeline STEP files (reuse_from = disk-1/2-windows).

Why: that writer puts the whole model under ONE root product (AP214 assembly, children via NEXT_ASSEMBLY_USAGE_OCCURRENCE).
step_check enumerates OCC transfer roots, so it reports 1 part named after the model and the name join with the decoder
census matches nothing (coverage 0.00 whatever the file holds). Every child PRODUCT name ends in the Tekla part id,
e.g. 'B1 p2 PLATE PL12.7*82.55 A36 [5907578]', and the python decoder's per-part list (convert_one *.parts.json.gz:
[tekla_id, profile, category, status, how, guid, n_cuts]) is keyed by the same id -> an exact per-part join on the
same inventory the data-3 conversions are graded against. No geometry is created or inferred; the STEP is only read.

  scan(lines)            -> {'products', 'products_with_id', 'by_id': {id: {'solids': n, 'occ': n}}, ...}   (text pass, streaming)
  join(scan, parts, axis_dropped=0) -> {'mode': 'tekla_id', 'expected', 'matched', 'coverage', ...}
usage (CLI): windows_join.py STEP|- DECODED_PARTS.json.gz [OUT.json]
"""
import sys, re, json, gzip, math, collections

ENT = re.compile(r"^#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*)\)\s*;\s*$", re.S)
REF = re.compile(r'#(\d+)')
STR = re.compile(r"'((?:[^']|'')*)'")
TID = re.compile(r'\[(\d+)\]\s*$')
SOLID_TYPES = ('MANIFOLD_SOLID_BREP', 'BREP_WITH_VOIDS', 'FACETED_BREP')
REP_TYPES = ('ADVANCED_BREP_SHAPE_REPRESENTATION', 'SHAPE_REPRESENTATION', 'FACETED_BREP_SHAPE_REPRESENTATION',
             'MANIFOLD_SURFACE_SHAPE_REPRESENTATION')
WANT = ('PRODUCT', 'PRODUCT_DEFINITION_FORMATION', 'PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE', 'PRODUCT_DEFINITION',
        'PRODUCT_DEFINITION_SHAPE', 'SHAPE_DEFINITION_REPRESENTATION', 'NEXT_ASSEMBLY_USAGE_OCCURRENCE') + SOLID_TYPES + REP_TYPES


def cov4(m, e):
    return math.floor(m / e * 1e4) / 1e4 if e else None


def scan(lines):
    """streaming text pass over a STEP file (iterable of str lines); memory ~ O(products + solids)"""
    prod, pdf, pd, pds, sdr, reps, solids, nauo = {}, {}, {}, {}, {}, {}, set(), collections.Counter()
    buf = ''
    for line in lines:
        if not buf:
            s = line.lstrip()
            if not s.startswith('#'):
                continue
            # cheap type filter before the regex
            k = s.find('=')
            t = s[k + 1:k + 60].lstrip() if k > 0 else ''
            if not t.startswith(WANT):
                continue
        buf += line
        if not buf.rstrip().endswith(';'):
            if len(buf) > 1 << 22:
                buf = ''
            continue
        st, buf = buf.strip(), ''
        m = ENT.match(st)
        if not m:
            continue
        eid, typ, body = int(m.group(1)), m.group(2), m.group(3)
        if typ == 'PRODUCT':
            s_ = STR.findall(body); prod[eid] = s_[0] if s_ else ''
        elif typ.startswith('PRODUCT_DEFINITION_FORMATION'):
            r = REF.findall(body); pdf[eid] = int(r[-1]) if r else None
        elif typ == 'PRODUCT_DEFINITION':
            r = REF.findall(body); pd[eid] = int(r[0]) if r else None
        elif typ == 'PRODUCT_DEFINITION_SHAPE':
            r = REF.findall(body); pds[eid] = int(r[0]) if r else None
        elif typ == 'SHAPE_DEFINITION_REPRESENTATION':
            r = REF.findall(body)
            if len(r) >= 2:
                sdr[int(r[0])] = int(r[1])
        elif typ == 'NEXT_ASSEMBLY_USAGE_OCCURRENCE':
            r = REF.findall(body)
            if len(r) >= 2:
                nauo[int(r[1])] += 1                       # related (child) PRODUCT_DEFINITION
        elif typ in SOLID_TYPES:
            solids.add(eid)
        elif typ in REP_TYPES:
            # items list = first parenthesised group after the name
            i0 = body.find('(')
            i1 = body.find(')', i0)
            reps[eid] = [int(x) for x in REF.findall(body[i0:i1])] if i0 >= 0 and i1 > i0 else []
    # PRODUCT <- PDF <- PD <- PDS <- SDR -> REP -> items
    pd_of_prod = {}
    for pdid, f in pd.items():
        p = pdf.get(f)
        if p is not None:
            pd_of_prod.setdefault(p, []).append(pdid)
    rep_of_pd = {}
    for pdsid, pdid in pds.items():
        if pdsid in sdr and pdid in pd:
            rep_of_pd[pdid] = sdr[pdsid]
    by_id = {}; no_id = []; dup = 0
    for p, name in prod.items():
        m = TID.search(name or '')
        n_sol = 0; n_occ = 0
        for pdid in pd_of_prod.get(p, []):
            n_sol += sum(1 for it in reps.get(rep_of_pd.get(pdid), []) if it in solids)
            n_occ += nauo.get(pdid, 0)
        if not m:
            no_id.append((name, n_sol, n_occ)); continue
        tid = int(m.group(1))
        if tid in by_id:
            dup += 1; by_id[tid]['solids'] += n_sol; by_id[tid]['occ'] += n_occ
        else:
            by_id[tid] = {'solids': n_sol, 'occ': n_occ}
    return {'products': len(prod), 'products_with_id': len(by_id), 'duplicate_ids': dup,
            'products_without_id': len(no_id), 'products_without_id_examples': [x[0][:80] for x in no_id[:5]],
            'solid_entities': len(solids), 'solids_in_id_products': sum(v['solids'] for v in by_id.values()),
            'solids_in_other_products': sum(x[1] for x in no_id), 'by_id': by_id}


def join(sc, parts, axis_dropped=0):
    """sc: scan() result; parts: decoder per-part list [[tekla_id, profile, category, status, how, guid, n_cuts], ...]"""
    dec = {}
    for p in parts:
        try:
            dec[int(p[0])] = p
        except (TypeError, ValueError):
            continue
    exp = collections.Counter(p[2] for p in parts)
    by_id = sc['by_id']
    present = {i for i, v in by_id.items() if v['solids'] > 0}
    matched = collections.Counter(dec[i][2] for i in present if i in dec)
    unknown = sorted(i for i in present if i not in dec)
    empty = sorted(i for i, v in by_id.items() if v['solids'] == 0)
    em = exp.get('member', 0) + (axis_dropped or 0)
    cov = {'member': cov4(matched.get('member', 0), em), 'connection': cov4(matched.get('connection', 0), exp.get('connection', 0)),
           'other': cov4(matched.get('other', 0), exp.get('other', 0))}
    tot_e = em + exp.get('connection', 0) + exp.get('other', 0)
    tot_m = matched.get('member', 0) + matched.get('connection', 0) + matched.get('other', 0)
    cov['all'] = cov4(tot_m, tot_e)
    cov['feature'] = cov4(matched.get('feature', 0), exp.get('feature', 0))
    missing = collections.Counter((p[2], p[1]) for i, p in dec.items() if i not in present)
    return {'mode': 'tekla_id', 'expected': dict(exp), 'axis_dropped': axis_dropped or 0, 'matched': dict(matched), 'coverage': cov,
            'parts_source': tot_e, 'parts_step': tot_m, 'step_products': sc['products'], 'step_products_with_id': sc['products_with_id'],
            'step_products_with_solid': len(present), 'step_products_without_solid': len(empty),
            'ids_unknown_to_decoder': len(unknown), 'ids_unknown_examples': unknown[:10], 'duplicate_ids': sc.get('duplicate_ids', 0),
            'solids_outside_id_products': sc.get('solids_in_other_products', 0),
            'missing_top': [[c, pr, n] for (c, pr), n in missing.most_common(12)]}


def _lines(path):
    if path == '-':
        for l in sys.stdin.buffer:
            yield l.decode('latin-1')
    else:
        with open(path, 'r', encoding='latin-1') as f:
            yield from f


if __name__ == '__main__':
    sc = scan(_lines(sys.argv[1]))
    parts = json.load(gzip.open(sys.argv[2], 'rt'))
    r = join(sc, parts)
    if len(sys.argv) > 3:
        json.dump(r, open(sys.argv[3], 'w'))
    print(json.dumps(r))
