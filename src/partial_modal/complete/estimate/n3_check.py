"""n3_ifc_approx (31-2214 GCP3_STL, Tekla IFC2X3): the 6 source parts missing from the delivered STEP are 6 'Bolt assembly'
IfcMechanicalFasteners (3/4 in x 100 mm, 2 bolts each) at the end-wall joist-girder seats. Each holds two IfcMappedItems
of one bolt map that share ONE transformation operator whose LocalOrigin points at #0 - an entity the file does not
have (the exporter lost the per-bolt offsets; the same dangling operator also crashed our extract stage). The bolt
SHAPE (the map's faceted Brep) and the assembly PLACEMENT are in the source; only the two bolt offsets are unknown.
Estimate: the offsets of the 66 intact joist-girder seat assemblies of the same model (2 bolts, 5 in gauge, symmetric
about the girder centre line), applied symmetric about this assembly's origin, which sits on the girder centre line and
at the middle of the 6 in bearing angle."""
import json
import os
import re

import numpy as np

import est_common as E

IFC_PATH = os.path.join(E.INPUTS, 'n3', 'model.ifc')


class IFC:
    def __init__(self, path):
        txt = open(path, errors='replace').read()
        self.E = {}
        for m in re.finditer(r"^#(\d+)=\s*(.*?);\s*$", txt, re.M):
            self.E[int(m.group(1))] = m.group(2)

    def refs(self, s):
        return [int(x) for x in re.findall(r'#(\d+)', s)]

    def nums(self, s):
        return [float(x) for x in re.findall(r'[-\d.]+(?:E[-+]?\d+)?', s[s.index('('):])]

    def pt(self, i):
        return np.array(self.nums(self.E[i]))

    def ax2(self, i):
        a = [x.strip() for x in self.E[i][self.E[i].index('(') + 1:self.E[i].rindex(')')].split(',')]
        o = self.pt(int(a[0][1:]))
        z = self.pt(int(a[1][1:])) if a[1] != '$' else np.array([0, 0, 1.0])
        x = self.pt(int(a[2][1:])) if a[2] != '$' else np.array([1.0, 0, 0])
        z = z / np.linalg.norm(z)
        x = x - (x @ z) * z
        x /= np.linalg.norm(x)
        M = np.eye(4)
        M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = x, np.cross(z, x), z, o
        return M

    def place(self, i):
        s = self.E[i]
        a = [x.strip() for x in s[s.index('(') + 1:s.rindex(')')].split(',')]
        rel = self.ax2(int(a[1][1:]))
        return rel if a[0] == '$' else self.place(int(a[0][1:])) @ rel

    def brep_faces(self, brep):
        shell = self.refs(self.E[brep])[0]
        faces = []
        for fc in self.refs(self.E[shell]):
            loops = []
            for b in self.refs(self.E[fc]):
                lp = self.refs(self.E[b])[0]
                loops.append([self.pt(q) for q in self.refs(self.E[lp])])
            faces.append(loops)
        return faces


def assemblies(f):
    """IfcMechanicalFastener -> (gid, placement matrix, [(map, operator offset or None)])"""
    out = {}
    for k, s in f.E.items():
        if not s.startswith('IFCMECHANICALFASTENER'):
            continue
        r = f.refs(s)
        if len(r) < 3:
            continue
        srs = [x for x in f.refs(f.E[r[2]]) if f.E[x].startswith('IFCSHAPEREPRESENTATION')]
        items = [i for x in srs for i in f.refs(f.E[x].split(',', 3)[3])]
        its = []
        for it in items:
            mp, op = f.refs(f.E[it])[:2]
            o = f.refs(f.E[op])
            off = f.pt(o[0]) if o and o[0] in f.E else None
            its.append((mp, op, off))
        out[k] = (s.split("'")[1], f.place(r[1]), its, s)
    return out


def make(tag, *a):
    t = E.Tree.__new__(E.Tree)
    t.tag = tag
    t.job = E.jobs()[tag]
    t.inputs = {os.path.relpath(IFC_PATH, E.ROOT): E.sha256_file(IFC_PATH)}
    bt = E.baseline_tree(tag)
    existing = set()
    if bt and os.path.exists(os.path.join(bt, 'schedules', 'parts.csv')):
        existing = {r['part_id'] for r in E.read_csv(os.path.join(bt, 'schedules', 'parts.csv'))}
    patch, log = E.new_patch(t), E.new_log(t)
    f = IFC(IFC_PATH)
    asm = assemblies(f)
    parts_json = json.load(open(os.path.join(E.INPUTS, 'n3', 'parts.json')))
    delivered = {p['gid'] for p in parts_json['parts']}
    # the reference pattern: intact 2-bolt 3/4 in assemblies (joist-girder seats)
    pats = {}
    for k, (gid, M, its, s) in asm.items():
        if len(its) == 2 and all(o is not None for _, _, o in its) and s.split(',')[-2].startswith('19.04'):
            key = tuple(sorted(tuple(np.round(o, 1)) for _, _, o in its))
            pats[key] = pats.get(key, 0) + 1
    ref = max(pats, key=pats.get)
    gauge = float(np.linalg.norm(np.array(ref[0]) - np.array(ref[1])))
    n_ref = pats[ref]
    broken = [(k, v) for k, v in sorted(asm.items()) if any(o is None for _, _, o in v[2])]
    for k, (gid, M, its, s) in broken:
        mp = its[0][0]
        rep = f.refs(f.E[mp])[1]
        breps = [i for i in f.refs(f.E[rep].split(',', 3)[3]) if f.E[i].startswith('IFCFACETEDBREP')]
        faces_map = [fc for b in breps for fc in f.brep_faces(b)]
        mo = f.ax2(f.refs(f.E[mp])[0])                      # the map's MappingOrigin (identity here)
        sols = []
        for sgn in (-1.0, 1.0):
            T = M.copy()
            off = np.array([sgn * gauge / 2, 0.0, 0.0])
            sols.append({'faces': [[[[round(float(c), 6) for c in (M @ np.append(mo[:3, :3] @ p + mo[:3, 3] + off, 1.0))[:3]]
                                     for p in loop] for loop in fc] for fc in faces_map], 'voids': []})
        centres = [np.round((M @ np.array([sgn * gauge / 2, 0, 0, 1.0]))[:3], 2).tolist() for sgn in (-1.0, 1.0)]
        basis = (f'estimated: the source holds this assembly\'s placement and its bolt shape, but both bolt items share one '
                 f'transformation operator whose origin points at #0, an entity missing from the file, so the two bolt offsets are '
                 f'lost; the model\'s {n_ref} intact 2-bolt 3/4 in joist-girder seat assemblies all use the same pattern - 2 bolts '
                 f'{gauge:.1f} mm apart, symmetric about the girder centre line; this origin lies on the girder centre line and at '
                 f'the middle of the 6 in bearing angle, so the bolts go {gauge / 2:.1f} mm either side of it along the assembly x '
                 f'axis')
        op = {'op': 'replace_part' if gid in existing else 'add_part', 'id': f'est:bolts:{gid}', 'colour': 'AMBER',
              'geometry': {'kind': 'faceted', 'solids': sols},
              'provenance': {'what': f'bolt assembly 3/4 in x 100 mm, 2 bolts at {gauge:.1f} mm gauge (dropped from the delivered STEP)',
                             'source': f'IFC #{k} {gid}: placement, NominalDiameter 19.05, NominalLength 100; bolt shape = '
                                       f'representation map #{mp} (faceted Brep)',
                             'basis': basis,
                             'evidence': {'confidence': 0.6, 'bolt_centres_world': centres, 'reference_pattern': [list(x) for x in ref],
                                          'reference_assemblies': n_ref, 'dangling_operator': its[0][1]}}}
        if gid in existing:
            op['part_id'] = gid
        else:
            op['part'] = {'part_id': gid, 'role': 'bolt', 'ifc_class': 'IfcMechanicalFastener', 'name': 'Bolt assembly 3/4 x 100 (2 bolts)',
                          'designation': 'BOLT 19.05 x 100'}
        patch['ops'].append(op)
        log['estimates'].append({'kind': 'bolt_offsets_lost_in_source', 'part_id': gid, 'ifc_entity': k,
                                 'in_delivered_step': gid in delivered, 'origin_world': np.round(M[:3, 3], 2).tolist(),
                                 'bolt_centres_world': centres, 'gauge_mm': round(gauge, 2), 'reference_assemblies': n_ref,
                                 'confidence': {'bolt_shape_and_assembly_position': 0.95, 'bolt_offsets': 0.6, 'overall': 0.6},
                                 'basis': basis})
    log['summary']['bolt_assemblies'] = len(broken)
    log['n3_note'] = ('the n3 baseline pipeline failed (extract crash on this same dangling operator), so these ops are written '
                      'against the IFC GlobalIds; when the n3 scripts_tree of the fixing track already lists a GlobalId the op is a '
                      'replace_part (re-run make_estimates.py --only n3_ifc_approx after that tree exists)')
    log['left_to_other_tracks'] = ['n3 has no other gap in the conversion log (2,793 / 2,793 delivered parts exact, level 0); the '
                                   'pipeline failure itself is the integration / IFC track\'s']
    return t, patch, log
