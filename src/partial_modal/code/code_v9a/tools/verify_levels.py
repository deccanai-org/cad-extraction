#!/usr/bin/env python3
"""Assembly-, mark-, piece- and model-level verification of a rebuilt model.

Membership is taken fresh from the source IFC (IfcRelAggregates, recursively for nested assemblies; marks read from
the IFC), independently of the schedules, and compared with what build_model.py selects for --assembly-id, --assembly
and --mark: its own selection code (build_model.select) run on the schedules, which includes nested sub-assemblies at
any depth. Every assembly of the IFC must also be listed in schedules/assemblies.csv (the documented list of ids).
Geometry is checked on the whole group: total volume, volume-weighted centre and combined bounding box of the rebuilt
parts against the delivered STEP and against the exact source geometry (absolute per-part values from
verification.csv), and every member part must itself be a 'match'.

The model level is ok only when every level below it is: every part a match, the model's combined geometry consistent
with both references, and every assembly, assembly mark and piece mark ok (membership and geometry).

usage: verify_levels.py SCHEDULE_DIR SOURCE.ifc
writes: assemblies_verification.csv, assembly_marks_verification.csv, piece_marks_verification.csv,
        levels_summary.json  (into SCHEDULE_DIR)
"""
import csv, json, os, sys, collections, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'kit'))
import extract                       # ifcopenshell only (no OpenCASCADE in this process)
import build_model                   # its selection code only (it imports no CAD module at load time)

TOL = dict(src_vol=1e-3, src_cen=0.05, src_bbox=0.05, del_vol=0.01, del_cen=1.0, del_bbox=1.0)


def vec(s):
    return np.array([float(x) for x in s.split()]) if s else None


def _part(r, pre):
    if pre == '':
        return float(r['volume']), np.array([float(r['cx']), float(r['cy']), float(r['cz'])]), vec(r['lo']), vec(r['hi'])
    if pre == 'd_':
        return float(r['delivered_volume']), np.array([float(r['d_cx']), float(r['d_cy']), float(r['d_cz'])]), vec(r['d_lo']), vec(r['d_hi'])
    return float(r['s_v']), np.array([float(r['s_cx']), float(r['s_cy']), float(r['s_cz'])]), vec(r['s_lo']), vec(r['s_hi'])


def group_vs(rows, pre):
    """group deviation from a reference and the bound implied by its parts' own deviations: a group is consistent when
    its combined volume / centre / bounding box deviate no more than the sum of what its (verified) parts allow"""
    R = [_part(r, '') for r in rows]
    X = [_part(r, pre) for r in rows]
    VR, VX = sum(x[0] for x in R), sum(x[0] for x in X)
    CR = sum(x[0] * x[1] for x in R) / VR
    CX = sum(x[0] * x[1] for x in X) / VX
    loR, hiR = np.min([x[2] for x in R], 0), np.max([x[3] for x in R], 0)
    loX, hiX = np.min([x[2] for x in X], 0), np.max([x[3] for x in X], 0)
    dv = abs(VR - VX) / max(VX, 1e-9)
    dc = float(np.linalg.norm(CR - CX))
    db = float(max(np.max(np.abs(loR - loX)), np.max(np.abs(hiR - hiX))))
    bv = sum(abs(r[0] - x[0]) for r, x in zip(R, X)) / max(VX, 1e-9)
    bc = sum(r[0] * float(np.linalg.norm(r[1] - x[1])) + abs(r[0] - x[0]) * float(np.linalg.norm(x[1] - CX)) for r, x in zip(R, X)) / max(VX, 1e-9)
    bb = max(float(max(np.max(np.abs(r[2] - x[2])), np.max(np.abs(r[3] - x[3])))) for r, x in zip(R, X))
    eps = 1e-6
    return dict(vol_rel=f'{dv:.2e}', centroid_mm=round(dc, 4), bbox_mm=round(db, 4), bound_vol_rel=f'{bv:.2e}', bound_centroid_mm=round(bc, 4),
                bound_bbox_mm=round(bb, 4), consistent=dv <= bv * (1 + 1e-4) + eps and dc <= bc * (1 + 1e-4) + 1e-3 and db <= bb + 1e-3)   # + rounding of the 1e-4 mm values


def check_group(ids, V):
    rows = [V[i] for i in ids if i in V]
    built = [r for r in rows if r.get('volume') not in (None, '')]          # a part that failed to build has no geometry
    out = dict(n_parts=len(ids), n_verified=len(rows), all_parts_match=all(r['status'] == 'match' for r in rows) and len(rows) == len(ids))
    if not built:
        out['geometry_ok'] = False
        return out
    if all(r.get('delivered_volume') for r in built):
        g = group_vs(built, 'd_')
        out.update({'delivered_' + k: v for k, v in g.items()})
    src = [r for r in built if r.get('s_v')]
    if src:
        g = group_vs(src, 's_')
        out.update({'source_' + k: v for k, v in g.items()})
    out['source_parts'] = len(src)
    out['geometry_ok'] = out['all_parts_match'] and len(built) == len(ids) and out.get('delivered_consistent', True) and out.get('source_consistent', True)
    return out


def main(folder, ifc_path):
    F = lambda n: os.path.join(folder, n)
    plist = list(csv.DictReader(open(F('parts.csv'), newline='', encoding='utf-8')))
    parts = {p['part_id']: p for p in plist}
    V = {r['part_id']: r for r in csv.DictReader(open(F('verification.csv'), newline='', encoding='utf-8'))}
    asm_csv = build_model.read_assemblies(folder)          # what build_model.py reads to select assemblies
    f = extract.open_ifc(ifc_path)
    # ---- membership from the IFC, recursively
    children = collections.defaultdict(list)
    parent = {}
    for rel in f.by_type('IfcRelAggregates'):
        if rel.RelatingObject.is_a('IfcElementAssembly'):
            for o in rel.RelatedObjects:
                children[rel.RelatingObject.GlobalId].append(o)
                parent[o.GlobalId] = rel.RelatingObject.GlobalId

    def leaves(gid, seen=None):
        seen = set() if seen is None else seen
        if gid in seen:
            return []
        seen.add(gid)
        out = []
        for o in children.get(gid, []):
            if o.is_a('IfcElementAssembly'):
                out += leaves(o.GlobalId, seen)
            elif o.GlobalId in parts:
                out.append(o.GlobalId)
        return out

    def descendants(gid):
        """assemblies nested in gid at any depth (not gid itself)"""
        out, todo = [], [o for o in children.get(gid, []) if o.is_a('IfcElementAssembly')]
        while todo:
            o = todo.pop()
            if o.GlobalId in out or o.GlobalId == gid:
                continue
            out.append(o.GlobalId)
            todo += [x for x in children.get(o.GlobalId, []) if x.is_a('IfcElementAssembly')]
        return out

    def depth(gid):
        d, seen = 0, {gid}
        while gid in parent and parent[gid] not in seen:
            gid = parent[gid]
            seen.add(gid)
            d += 1
        return d
    assemblies = list(f.by_type('IfcElementAssembly'))
    nested = sum(1 for a in assemblies if a.GlobalId in parent)
    # ---- marks fresh from the IFC: piece mark and assembly mark of every part, own mark of every assembly
    fresh = {}
    for pid in parts:
        e = f.by_guid(pid)
        asm = f.by_guid(parent[pid]) if pid in parent else None
        pm, am, _ = extract.marks_of(e, extract.psets(e), asm)
        fresh[pid] = (pm, am)
    own_mark = {a.GlobalId: str(extract.assembly_own_mark(a)) for a in assemblies}
    # ---- 1. every assembly by id (what --assembly-id selects: its parts and those of every assembly nested in it)
    arows, without_parts = [], 0
    for a in assemblies:
        exp = set(leaves(a.GlobalId))
        sel = {p['part_id'] for p in build_model.select(plist, asm_csv, assembly_id=a.GlobalId)}
        if not exp and not sel:
            without_parts += 1             # no member with geometry in the model: nothing to build or check
            continue
        listed = a.GlobalId in asm_csv
        direct = [o.GlobalId for o in children.get(a.GlobalId, []) if not o.is_a('IfcElementAssembly') and o.GlobalId in parts]
        mark = own_mark[a.GlobalId] or next((fresh[i][1] for i in direct if fresh[i][1]), '')
        g = check_group(sorted(exp), V)
        arows.append(dict(assembly_id=a.GlobalId, assembly_mark=mark, nested=a.GlobalId in parent, parent_id=parent.get(a.GlobalId, ''),
                          depth=depth(a.GlobalId), sub_assemblies=len(descendants(a.GlobalId)), direct_parts=len(direct),
                          listed_in_assemblies_csv=listed, expected_parts=len(exp), selected_parts=len(sel),
                          membership_ok=sel == exp and listed, missing=len(exp - sel), extra=len(sel - exp), **g))
    # ---- 2. assembly marks (what --assembly MARK selects): parts carrying the mark, plus the parts of the assemblies
    # nested in an assembly that carries it
    carriers = collections.defaultdict(set)
    for a in assemblies:
        if own_mark[a.GlobalId]:
            carriers[own_mark[a.GlobalId].lower()].add(a.GlobalId)
    for pid, (pm, am) in fresh.items():
        if am and pid in parent:
            carriers[am.lower()].add(parent[pid])
    mark_exp = collections.defaultdict(set)
    for pid, (pm, am) in fresh.items():
        if am:
            mark_exp[am.lower()].add(pid)
    for m, ids in carriers.items():
        for aid in ids:
            for sub in descendants(aid):
                mark_exp[m] |= set(leaves(sub))
    mrows = []
    for m, exp in mark_exp.items():
        if not exp:
            continue
        sel = {p['part_id'] for p in build_model.select(plist, asm_csv, assembly=m)}
        g = check_group(sorted(exp), V)
        mrows.append(dict(assembly_mark=m, assemblies=len(carriers.get(m, ())), unnumbered='(?)' in m, expected_parts=len(exp),
                          selected_parts=len(sel), membership_ok=sel == exp, missing=len(exp - sel), extra=len(sel - exp), **g))
    # ---- 3. piece marks (what --mark MARK selects): parts carrying the mark in the IFC
    piece_exp = collections.defaultdict(set)
    for pid, (pm, am) in fresh.items():
        if pm:
            piece_exp[pm.lower()].add(pid)
    prows = []
    for m, exp in piece_exp.items():
        sel = {p['part_id'] for p in build_model.select(plist, asm_csv, mark=m)}
        g = check_group(sorted(exp), V)
        prows.append(dict(piece_mark=m, unnumbered='(?)' in m, expected_parts=len(exp), selected_parts=len(sel), membership_ok=sel == exp,
                          missing=len(exp - sel), extra=len(sel - exp), **g))
    # ---- 4. model: its own parts and combined geometry, and every level below it
    model = check_group(sorted(parts), V)
    ok_all = lambda rows: all(r['membership_ok'] and r['geometry_ok'] for r in rows)
    model.update(parts_in_schedules=len(parts), parts_verified=len(V),
                 parts_and_combined_geometry_ok=model['geometry_ok'], assemblies_ok=ok_all(arows),
                 assembly_marks_ok=ok_all(mrows), piece_marks_ok=ok_all(prows))
    model['geometry_ok'] = (model['parts_and_combined_geometry_ok'] and model['assemblies_ok'] and model['assembly_marks_ok']
                            and model['piece_marks_ok'])

    def w(name, rows):
        if not rows:
            open(F(name), 'w').write('')
            return
        cols = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
        with open(F(name), 'w', newline='') as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            wr.writeheader()
            wr.writerows(rows)
    w('assemblies_verification.csv', arows)
    w('assembly_marks_verification.csv', mrows)
    w('piece_marks_verification.csv', prows)
    C = lambda rows, k: sum(1 for r in rows if r.get(k))
    summ = dict(
        assemblies=dict(total=len(arows), nested=nested, ifc_assemblies=len(assemblies), without_parts=without_parts,
                        max_depth=max((r['depth'] for r in arows), default=0),
                        listed_in_assemblies_csv=C(arows, 'listed_in_assemblies_csv'), membership_ok=C(arows, 'membership_ok'),
                        geometry_ok=C(arows, 'geometry_ok'), fully_ok=sum(1 for r in arows if r['membership_ok'] and r['geometry_ok'])),
        assembly_marks=dict(total=len(mrows), unnumbered=C(mrows, 'unnumbered'), membership_ok=C(mrows, 'membership_ok'), geometry_ok=C(mrows, 'geometry_ok'),
                            fully_ok=sum(1 for r in mrows if r['membership_ok'] and r['geometry_ok'])),
        piece_marks=dict(total=len(prows), unnumbered=C(prows, 'unnumbered'), membership_ok=C(prows, 'membership_ok'), geometry_ok=C(prows, 'geometry_ok'),
                         fully_ok=sum(1 for r in prows if r['membership_ok'] and r['geometry_ok'])),
        model=model, tolerances=TOL,
        note='model.geometry_ok requires every part, the combined model geometry, and every assembly, assembly mark and piece '
             'mark (membership and geometry); the components are listed next to it')
    json.dump(summ, open(F('levels_summary.json'), 'w'), indent=1, default=str)
    print(json.dumps(summ, default=str))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
