#!/usr/bin/env python3
"""Apply shellfix to every FACETED_BREP of an existing ifc2step5 STEP file (AP214 faceted, POLY_LOOP faces) and write a
repaired copy.  Used to (a) test the repair on the STEP files already produced (Disk-1/2 reuse, z3 runs) and (b) repair
reused STEP files without re-converting.  Text level: untouched entities are copied byte for byte; a reversed face gets
new POLY_LOOP / bound / PLANE / FACE_SURFACE entities; every repaired brep is replaced (in its shape representation) by
one FACETED_BREP per closed piece.  (Coordinates the old writer already truncated to 9 significant digits cannot be
recovered here: such files must be re-converted with the precision fix, see README.)

usage: step_shellfix.py IN.step OUT.step [--stats OUT.json]
"""
import sys, os, re, json, math, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shellfix import repair_shell, piece_closed

ENT = re.compile(r"^#(\d+)=([A-Z_0-9]+)\((.*)\);\s*$")
REF = re.compile(r"#(\d+)")


def _r(v):
    if v == 0.0:
        return "0."
    s = "%.15g" % v
    if "e" in s or "E" in s:
        m, _, e = s.partition("e")
        if "." not in m:
            m += "."
        return m + "E" + str(int(e))
    if "." not in s:
        s += "."
    return s


def newell(pts):
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1, z1 = pts[i]; x2, y2, z2 = pts[(i + 1) % n]
        nx += (y1 - y2) * (z1 + z2); ny += (z1 - z2) * (x1 + x2); nz += (x1 - x2) * (y1 + y2)
    l = math.sqrt(nx * nx + ny * ny + nz * nz)
    return None if l < 1e-12 else (nx / l, ny / l, nz / l)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--stats')
    ap.add_argument('--keep-open-in-brep', action='store_true', help='write pieces that are not closed inside the '
                    'FACETED_BREP as before (default: as OPEN_SHELL in a SHELL_BASED_SURFACE_MODEL = surface part)')
    a = ap.parse_args()
    lines = open(a.inp, encoding='latin-1').read().split('\n')
    pts, loops, bounds, faces, shells, breps, reps = {}, {}, {}, {}, {}, {}, {}
    where = {}
    maxid = 0
    for ln, line in enumerate(lines):
        m = ENT.match(line)
        if not m:
            continue
        i, t, b = int(m.group(1)), m.group(2), m.group(3)
        maxid = max(maxid, i)
        if t == 'CARTESIAN_POINT':
            c = b[b.index('(', 1) + 1:b.rindex(')')].split(',')
            pts[i] = tuple(float(x) for x in c)
        elif t == 'POLY_LOOP':
            loops[i] = [int(x) for x in REF.findall(b)]
        elif t in ('FACE_OUTER_BOUND', 'FACE_BOUND'):
            r = REF.findall(b); bounds[i] = (int(r[0]), b.rstrip().endswith('.T.'), t == 'FACE_OUTER_BOUND')
        elif t == 'FACE_SURFACE':
            r = [int(x) for x in REF.findall(b)]
            faces[i] = (r[:-1], b.rstrip().endswith('.T.'))
        elif t == 'CLOSED_SHELL':
            shells[i] = [int(x) for x in REF.findall(b)]; where[i] = ln
        elif t == 'FACETED_BREP':
            breps[i] = int(REF.findall(b)[0]); where[i] = ln
        elif t == 'FACETED_BREP_SHAPE_REPRESENTATION':
            reps[i] = ln
    nid = [maxid]

    def new(body):
        nid[0] += 1; extra.append('#%d=%s;' % (nid[0], body)); return nid[0]
    extra = []
    dircache = {}

    def direction(x, y, z):
        k = (round(x, 6), round(y, 6), round(z, 6))
        if k not in dircache:
            dircache[k] = new("DIRECTION('',(%s,%s,%s))" % tuple(_r(c) for c in k))
        return dircache[k]
    replace = {}           # brep id -> [new brep ids]
    surf_items = set()     # SHELL_BASED_SURFACE_MODEL ids among them
    new_brep_ids = set()
    drop = set()
    agg = collections.Counter(); nrep = 0
    for bid, sid in breps.items():
        fids = shells.get(sid)
        if not fids or any(f not in faces for f in fids):
            agg['breps_skipped_nonpoly'] += 1; continue
        fl = []
        for f in fids:
            bl, same = faces[f]
            ls = []
            for bd in bl:
                lid, ori, outer = bounds[bd]
                lp = loops[lid] if ori == same else loops[lid][::-1]
                ls.insert(0, lp) if outer else ls.append(lp)
            fl.append(ls)
        orig = [[list(lp) for lp in f] for f in fl]
        pieces, info = repair_shell(fl, pts)            # fl: inner loops may be re-wound in place
        closed = [piece_closed(fl, pc) for pc in pieces]
        if not info and (all(closed) or a.keep_open_in_brep):
            continue
        nrep += 1; agg.update(info)
        new_breps = []; open_shells = []
        for pc, cl_ in zip(pieces, closed):
            fout = []
            for fi, rev in pc:
                ls = [lp[::-1] for lp in fl[fi]] if rev else fl[fi]
                if fi < len(orig) and ls == orig[fi]:
                    fout.append(fids[fi]); continue      # face unchanged: original entity reused
                n = newell([pts[p] for p in ls[0]])
                if n is None:
                    fout.append(fids[fi]); continue
                nb = []
                for k, lp in enumerate(ls):
                    nl = new("POLY_LOOP('',(%s))" % ",".join("#%d" % p for p in lp))
                    nb.append(new("%s('',#%d,.T.)" % ("FACE_OUTER_BOUND" if k == 0 else "FACE_BOUND", nl)))
                rx, ry, rz = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
                cx, cy, cz = ry * n[2] - rz * n[1], rz * n[0] - rx * n[2], rx * n[1] - ry * n[0]
                cl = math.sqrt(cx * cx + cy * cy + cz * cz) or 1.0
                ax = new("AXIS2_PLACEMENT_3D('',#%d,#%d,#%d)" % (ls[0][0], direction(*n), direction(cx / cl, cy / cl, cz / cl)))
                pl = new("PLANE('',#%d)" % ax)
                fout.append(new("FACE_SURFACE('',(%s),#%d,.T.)" % (",".join("#%d" % x for x in nb), pl)))
            if cl_ or a.keep_open_in_brep:
                sh = new("CLOSED_SHELL('',(%s))" % ",".join("#%d" % f for f in fout))
                new_breps.append(new("FACETED_BREP('',#%d)" % sh)); new_brep_ids.add(new_breps[-1])
            else:
                open_shells.append(new("OPEN_SHELL('',(%s))" % ",".join("#%d" % f for f in fout)))
                agg['open_pieces_as_surface'] += 1
        if open_shells:
            new_breps.append(new("SHELL_BASED_SURFACE_MODEL('',(%s))" % ",".join("#%d" % x for x in open_shells)))
            surf_items.update(new_breps[-1:])
        replace[bid] = new_breps
        drop.add(where[bid]); drop.add(where[sid])
    # rewrite representations
    for rid, ln in reps.items():
        line = lines[ln]
        m = ENT.match(line); b = m.group(3)
        if not any(('#%d' % k) in b for k in replace):
            continue
        def sub(mo):
            k = int(mo.group(1))
            return ",".join("#%d" % x for x in replace[k]) if k in replace else mo.group(0)
        nb_ = REF.sub(sub, b)
        items = [int(x) for x in REF.findall(nb_)][:-1]   # last ref = context
        typ = m.group(2)
        if any(i in surf_items for i in items):
            # FACETED_BREP_SHAPE_REPRESENTATION may only hold faceted breps: mixed -> SHAPE_REPRESENTATION,
            # surface only -> MANIFOLD_SURFACE_SHAPE_REPRESENTATION
            solid_left = any(i in new_brep_ids or (i in breps and i not in replace) for i in items)
            typ = 'SHAPE_REPRESENTATION' if solid_left else 'MANIFOLD_SURFACE_SHAPE_REPRESENTATION'
        lines[ln] = '#%d=%s(%s);' % (int(m.group(1)), typ, nb_)
    end = max(ln for ln, l in enumerate(lines) if l.strip() == 'ENDSEC;')      # end of the DATA section
    with open(a.out, 'w', encoding='latin-1') as fo:
        for ln, line in enumerate(lines):
            if ln in drop:
                continue
            if ln == end and extra:
                fo.write('\n'.join(extra) + '\n')
            fo.write(line + ('\n' if ln < len(lines) - 1 else ''))
    st = {'breps': len(breps), 'breps_repaired': nrep, 'new_entities': nid[0] - maxid, **agg}
    if a.stats:
        json.dump(st, open(a.stats, 'w'))
    print(json.dumps(st))


if __name__ == '__main__':
    main()
