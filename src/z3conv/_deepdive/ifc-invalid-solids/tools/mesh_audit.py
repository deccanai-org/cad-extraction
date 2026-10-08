#!/usr/bin/env python3
"""Kernel-free audit of every FACETED_BREP in an ifc2step5 STEP file (text parse, exact point ids as written).

Per brep (CLOSED_SHELL of POLY_LOOP faces): faces, holes, connected components (faces sharing an edge),
edge-use histogram (1 = boundary/open, 2 = manifold, >2 = non-manifold), orientation conflicts (edge used twice in the
same direction), signed volume (divergence theorem over the loops as written), components with negative volume,
and components geometrically nested in / overlapping another component (bbox containment test).
usage: mesh_audit.py FILE.step OUT.jsonl [--names a,b,...]
"""
import sys, re, json, collections, argparse, math

ENT = re.compile(r"^#(\d+)=([A-Z_0-9]+)\((.*)\);\s*$")
REF = re.compile(r"#(\d+)")


def parse(path):
    pts, loops, bounds, faces, shells, breps, reps, sdr, pds, pd, pdf, prod = {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}
    for line in open(path, encoding='latin-1'):
        m = ENT.match(line)
        if not m:
            continue
        i, t, b = int(m.group(1)), m.group(2), m.group(3)
        if t == 'CARTESIAN_POINT':
            c = b[b.index('(', 1) + 1:b.rindex(')')].split(',')
            pts[i] = tuple(float(x) for x in c)
        elif t == 'POLY_LOOP':
            loops[i] = [int(x) for x in REF.findall(b)]
        elif t in ('FACE_OUTER_BOUND', 'FACE_BOUND'):
            r = REF.findall(b); bounds[i] = (int(r[0]), b.rstrip().endswith('.T.'), t == 'FACE_OUTER_BOUND')
        elif t in ('FACE_SURFACE', 'FACE', 'ADVANCED_FACE'):
            r = [int(x) for x in REF.findall(b)]
            faces[i] = r[:-1] if t != 'FACE' else r
        elif t in ('CLOSED_SHELL', 'OPEN_SHELL'):
            shells[i] = [int(x) for x in REF.findall(b)]
        elif t == 'FACETED_BREP':
            breps[i] = int(REF.findall(b)[0])
        elif t.endswith('SHAPE_REPRESENTATION'):
            reps[i] = [int(x) for x in REF.findall(b)]
        elif t == 'SHAPE_DEFINITION_REPRESENTATION':
            r = [int(x) for x in REF.findall(b)]; sdr[r[1]] = (r[0], i)
        elif t == 'PRODUCT_DEFINITION_SHAPE':
            pds[i] = int(REF.findall(b)[0])
        elif t == 'PRODUCT_DEFINITION':
            pd[i] = int(REF.findall(b)[0])
        elif t == 'PRODUCT_DEFINITION_FORMATION':
            pdf[i] = int(REF.findall(b)[0])
        elif t == 'PRODUCT':
            s = re.findall(r"'((?:[^']|'')*)'", b); prod[i] = s[0] if s else ''
    brep_prod = {}
    for rid, items in reps.items():
        pds_id, sdr_id = sdr.get(rid, (None, None))
        pd_id = pds.get(pds_id)
        nm = prod.get(pdf.get(pd.get(pd_id)))
        for it in items:
            if it in breps:
                brep_prod[it] = (nm, sdr_id, pd_id)
    return pts, loops, bounds, faces, shells, breps, brep_prod


def audit_shell(face_loops, pts):
    """face_loops: list of faces, each a list of point-id loops (outer first). Returns dict."""
    eu = collections.defaultdict(list)   # undirected edge -> [(face, direction)]
    for fi, ls in enumerate(face_loops):
        for lp in ls:
            n = len(lp)
            for k in range(n):
                a, b = lp[k], lp[(k + 1) % n]
                if a == b:
                    continue
                eu[(min(a, b), max(a, b))].append((fi, a < b))
    hist = collections.Counter(min(len(v), 3) for v in eu.values())
    conflicts = sum(1 for v in eu.values() if len(v) == 2 and v[0][1] == v[1][1])
    # components (faces linked through 2-use edges and non-manifold edges)
    par = list(range(len(face_loops)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for v in eu.values():
        for k in range(1, len(v)):
            ra, rb = find(v[0][0]), find(v[k][0])
            if ra != rb:
                par[ra] = rb
    comps = collections.defaultdict(list)
    for fi in range(len(face_loops)):
        comps[find(fi)].append(fi)
    cinfo = []
    for c in comps.values():
        vol = 0.0; bb = [1e30] * 3 + [-1e30] * 3
        for fi in c:
            for lp in face_loops[fi]:
                P = [pts[p] for p in lp]
                for q in P:
                    for d in range(3):
                        bb[d] = min(bb[d], q[d]); bb[d + 3] = max(bb[d + 3], q[d])
                o = P[0]
                for k in range(1, len(P) - 1):
                    a, b = P[k], P[k + 1]
                    vol += (o[0] * (a[1] * b[2] - a[2] * b[1]) - o[1] * (a[0] * b[2] - a[2] * b[0]) + o[2] * (a[0] * b[1] - a[1] * b[0])) / 6.0
        cinfo.append({'faces': len(c), 'vol': vol, 'bb': bb})
    nested = 0; overlap = 0
    for i, a in enumerate(cinfo):
        for j, b in enumerate(cinfo):
            if i == j:
                continue
            if all(a['bb'][d] >= b['bb'][d] - 1e-6 and a['bb'][d + 3] <= b['bb'][d + 3] + 1e-6 for d in range(3)):
                nested += 1
            elif i < j and all(a['bb'][d] < b['bb'][d + 3] and b['bb'][d] < a['bb'][d + 3] for d in range(3)):
                overlap += 1
    return {'faces': len(face_loops), 'edges': len(eu), 'edge_use': {str(k): v for k, v in sorted(hist.items())},
            'orient_conflicts': conflicts, 'components': len(cinfo), 'neg_components': sum(1 for c in cinfo if c['vol'] < 0),
            'vol': round(sum(c['vol'] for c in cinfo), 3), 'nested_pairs': nested, 'overlap_pairs': overlap,
            'comp_vols': [round(c['vol'], 1) for c in cinfo][:20]}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('out'); ap.add_argument('--names')
    a = ap.parse_args()
    pts, loops, bounds, faces, shells, breps, brep_prod = parse(a.step)
    want = set(a.names.split(',')) if a.names else None
    agg = collections.Counter()
    with open(a.out, 'w') as fo:
        for bid, sid in breps.items():
            nm, sdr_id, pd_id = brep_prod.get(bid, (None, None, None))
            if want and nm not in want:
                continue
            fl = []
            for f in shells[sid]:
                ls = []
                for bd in faces[f]:
                    lid, ori, outer = bounds[bd]
                    lp = loops[lid] if ori else loops[lid][::-1]
                    ls.insert(0, lp) if outer else ls.append(lp)
                fl.append(ls)
            r = audit_shell(fl, pts); r['brep'] = bid; r['name'] = nm; r['sdr'] = sdr_id; r['pd'] = pd_id
            fo.write(json.dumps(r) + '\n')
            agg['breps'] += 1
            agg['open'] += r['edge_use'].get('1', 0) > 0
            agg['nonmanifold'] += r['edge_use'].get('3', 0) > 0
            agg['orient_conflict'] += r['orient_conflicts'] > 0
            agg['multi_component'] += r['components'] > 1
            agg['neg_component'] += r['neg_components'] > 0
            agg['nested'] += r['nested_pairs'] > 0
            agg['overlap'] += r['overlap_pairs'] > 0
            agg['neg_total_vol'] += r['vol'] <= 0
    print(json.dumps({'file': a.step, **agg}))


if __name__ == '__main__':
    main()
