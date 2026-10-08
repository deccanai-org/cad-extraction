#!/usr/bin/env python3
"""Readable schedules derived from the build tables of one model (they are views: the build reads parts/profiles/solids/
cuts/openings/exact_geometry): members.csv, plates.csv, bolts.csv (joint schedule), welds.csv, assemblies.csv.

assemblies.csv lists every assembly of the source model, one row each: its own parts (n_parts, part_ids: the parts whose
assembly_id is this assembly) and, from assembly_tree.csv (extract.py), its parent assembly (parent_id, '' at the top),
its nesting depth (0 = top), its direct sub-assemblies and n_parts_total, the parts `build_model.py --assembly-id` builds
for it (its own and those of every assembly nested in it, at any depth). An assembly whose members are only other
assemblies is listed too (n_parts 0). A view with no rows is written as its header line.
usage: views.py SCHEDULE_DIR"""
import csv, json, math, os, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'kit'))


def n(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def r3(v):
    return '' if v is None else round(v, 3)


def first(d, *keys):
    for k in keys:
        if d.get(k) not in (None, '', 0, 0.0):
            return d[k]
    return ''


def main(folder):
    F = lambda x: os.path.join(folder, x)
    parts = list(csv.DictReader(open(F('parts.csv'))))
    profiles = {r['profile_id']: r for r in csv.DictReader(open(F('profiles.csv')))}
    solids = list(csv.DictReader(open(F('solids.csv'))))
    cuts = collections.Counter(c['solid_id'] for c in csv.DictReader(open(F('cuts.csv'))))
    opens = collections.Counter(o['part_id'] for o in csv.DictReader(open(F('openings.csv'))))
    props = {}
    if os.path.exists(F('part_properties.jsonl')):
        for l in open(F('part_properties.jsonl')):
            r = json.loads(l)
            props[r['part_id']] = r
    body = collections.defaultdict(list)
    for s in solids:
        if s['role'] == 'body':
            body[s['part_id']].append(s)
    import steelbuild
    outlines = json.load(open(F('profile_outlines.json')))
    paths = json.load(open(F('paths.json'))) if os.path.exists(F('paths.json')) else {}   # swept solids
    area_cache = {}

    def area(pid):
        if pid not in area_cache:
            try:
                area_cache[pid] = steelbuild.profile_face(profiles[pid], outlines.get(pid)).area
            except Exception:
                area_cache[pid] = None
        return area_cache[pid]

    members, plates, bolts, welds = [], [], [], []
    asm = collections.defaultdict(list)
    for p in parts:
        pid = p['part_id']
        pr = props.get(pid, {})
        P = pr.get('properties', {})
        if p['assembly_id']:
            asm[p['assembly_id']].append(p)
        b = body.get(pid, [])
        s0 = b[0] if b else None
        prof = profiles.get(s0['profile_id']) if s0 else None
        L = math.sqrt(sum(n(s0[k]) ** 2 for k in ('vx', 'vy', 'vz'))) if s0 else None
        start = [n(s0[k]) for k in ('ox', 'oy', 'oz')] if s0 else None
        vec = [n(s0[k]) for k in ('vx', 'vy', 'vz')] if s0 else None
        end = [a + v for a, v in zip(start, vec)] if s0 else None
        path = paths.get(s0['solid_id']) if s0 else None
        if path:                          # swept: the length along the path, from its first to its last point
            pp = path['points'] + (path['points'][:1] if path.get('closed') else [])
            L = sum(math.dist(a, b) for a, b in zip(pp, pp[1:]))
            start, end = [float(c) for c in pp[0]], [float(c) for c in pp[-1]]
        base = dict(part_id=pid, part_mark=p['part_mark'], assembly_mark=p['assembly_mark'], name=p['name'], ifc_class=p['ifc_class'],
                    designation=p['designation'], material=p['material'], geometry=p['geometry'])
        if p['role'] == 'member':
            members.append(dict(base, profile_id=s0['profile_id'] if s0 else '', profile_kind=prof['kind'] if prof else '',
                                d=prof.get('d', '') if prof else '', b=prof.get('b', '') if prof else '', tw=prof.get('tw', '') if prof else '',
                                tf=prof.get('tf', '') if prof else '', t=prof.get('t', '') if prof else '', r=prof.get('r', '') if prof else '',
                                radius=prof.get('radius', '') if prof else '', slope_rad=prof.get('slope', '') if prof else '',
                                section_area_mm2=r3(area(s0['profile_id'])) if s0 else '',
                                length_mm=r3(L), start_x=r3(start[0]) if start else '', start_y=r3(start[1]) if start else '', start_z=r3(start[2]) if start else '',
                                end_x=r3(end[0]) if end else '', end_y=r3(end[1]) if end else '', end_z=r3(end[2]) if end else '',
                                web_dir_x=s0['xx'] if s0 else '', web_dir_y=s0['xy'] if s0 else '', web_dir_z=s0['xz'] if s0 else '',
                                n_solids=len(b), n_cuts=sum(cuts[s['solid_id']] for s in b), n_openings=opens[pid]))
        elif p['role'] in ('plate', 'accessory') and (not prof or prof['kind'] in ('RECT', 'POLY') or not b):
            plates.append(dict(base, role=p['role'], thickness_mm=r3(L) if prof and prof['kind'] in ('RECT', 'POLY') and not path else '',
                               outline_kind=prof['kind'] if prof else '', outline_b=prof.get('b', '') if prof else '', outline_d=prof.get('d', '') if prof else '',
                               outline_area_mm2=r3(area(s0['profile_id'])) if s0 else '',
                               origin_x=r3(start[0]) if start else '', origin_y=r3(start[1]) if start else '', origin_z=r3(start[2]) if start else '',
                               n_solids=len(b), n_cuts=sum(cuts[s['solid_id']] for s in b), n_openings=opens[pid]))
        elif p['role'] == 'bolt':
            bolts.append(dict(base, standard=first(P, 'Tekla Bolt.Bolt standard', 'AISC_EM11_Pset_Bolt.BoltStandard', 'AISC_EM11_Pset_Bolt.BoltGrade'),
                              bolt_size_mm=first(P, 'Tekla Bolt.Bolt size', 'AISC_EM11_Pset_Bolt.BoltDiameter'),
                              bolt_length_mm=first(P, 'Tekla Bolt.Bolt length', 'AISC_EM11_Pset_Bolt.BoltLength'),
                              bolt_count=first(P, 'Tekla Bolt.Bolt count'), hole_diameter_mm=first(P, 'Tekla Bolt.Bolt hole diameter', 'AISC_EM11_Pset_BoltHole/SlotHole.BoltHoleDiameter'),
                              slotted_x_mm=first(P, 'Tekla Bolt.Slotted hole x', 'AISC_EM11_Pset_BoltHole/SlotHole.SlottedHoleLength'),
                              nut=first(P, 'Tekla Bolt.Nut name', 'AISC_EM11_Pset_Nut.NutStandard'), washer=first(P, 'Tekla Bolt.Washer name'),
                              location=first(P, 'Tekla Bolt.Location'), field_assembled=first(P, 'AISC_EM11_Pset_Bolt.BoltFieldAssembled'),
                              n_solids=len(b), position_x=r3(start[0]) if start else '', position_y=r3(start[1]) if start else '', position_z=r3(start[2]) if start else ''))
        elif p['role'] == 'weld':
            welds.append(dict(base, weld_type=first(P, 'AISC_EM11_Pset_Weld.WeldType1'), size_mm=first(P, 'AISC_EM11_Pset_Weld.d'),
                              length_mm=first(P, 'AISC_EM11_Pset_Weld.l'), field_weld=first(P, 'AISC_EM11_Pset_Weld.FieldWeld'),
                              intermittent=first(P, 'AISC_EM11_Pset_Weld.Intermittent'), n_solids=len(b),
                              position_x=r3(start[0]) if start else '', position_y=r3(start[1]) if start else '', position_z=r3(start[2]) if start else ''))
    # assembly hierarchy of the source model (extract.py); without it (older schedules) only assemblies with parts
    tree = list(csv.DictReader(open(F('assembly_tree.csv'), newline='', encoding='utf-8'))) if os.path.exists(F('assembly_tree.csv')) else []
    node = {t['assembly_id']: t for t in tree}
    subs = collections.defaultdict(list)
    for t in tree:
        if t['parent_id']:
            subs[t['parent_id']].append(t['assembly_id'])

    def total(aid):
        """parts of an assembly and of every assembly nested in it"""
        seen, todo, n = set(), [aid], 0
        while todo:
            a = todo.pop()
            if a in seen:
                continue
            seen.add(a)
            n += len(asm.get(a, []))
            todo += subs.get(a, [])
        return n
    assemblies = []
    for aid in list(asm) + [t['assembly_id'] for t in tree if t['assembly_id'] not in asm]:
        ps = asm.get(aid, [])
        t = node.get(aid, {})
        row = dict(assembly_id=aid, assembly_mark=ps[0]['assembly_mark'] if ps else t.get('assembly_mark', ''),
                   drawing_ref=next((x['drawing_ref'] for x in ps if x['drawing_ref']), '') if ps else t.get('drawing_ref', ''),
                   n_parts=len(ps), roles=' '.join(f'{k}:{v}' for k, v in collections.Counter(x['role'] for x in ps).most_common()),
                   part_ids=' '.join(x['part_id'] for x in ps))
        if tree:
            row.update(parent_id=t.get('parent_id', ''), depth=t.get('depth', ''), name=t.get('name', ''), n_parts_total=total(aid),
                       sub_assemblies=' '.join(subs.get(aid, [])))
        assemblies.append(row)

    base_cols = ['part_id', 'part_mark', 'assembly_mark', 'name', 'ifc_class', 'designation', 'material', 'geometry']
    empty_cols = {    # the columns of a view that has no rows (same as the rows above would carry)
        'members.csv': base_cols + ['profile_id', 'profile_kind', 'd', 'b', 'tw', 'tf', 't', 'r', 'radius', 'slope_rad', 'section_area_mm2',
                                    'length_mm', 'start_x', 'start_y', 'start_z', 'end_x', 'end_y', 'end_z', 'web_dir_x', 'web_dir_y',
                                    'web_dir_z', 'n_solids', 'n_cuts', 'n_openings'],
        'plates.csv': base_cols + ['role', 'thickness_mm', 'outline_kind', 'outline_b', 'outline_d', 'outline_area_mm2', 'origin_x',
                                   'origin_y', 'origin_z', 'n_solids', 'n_cuts', 'n_openings'],
        'bolts.csv': base_cols + ['standard', 'bolt_size_mm', 'bolt_length_mm', 'bolt_count', 'hole_diameter_mm', 'slotted_x_mm', 'nut',
                                  'washer', 'location', 'field_assembled', 'n_solids', 'position_x', 'position_y', 'position_z'],
        'welds.csv': base_cols + ['weld_type', 'size_mm', 'length_mm', 'field_weld', 'intermittent', 'n_solids', 'position_x',
                                  'position_y', 'position_z'],
        'assemblies.csv': ['assembly_id', 'assembly_mark', 'drawing_ref', 'n_parts', 'roles', 'part_ids', 'parent_id', 'depth', 'name',
                           'n_parts_total', 'sub_assemblies']}

    def w(name, rows):
        if not rows:
            with open(F(name), 'w', newline='') as fh:
                csv.DictWriter(fh, fieldnames=empty_cols[name]).writeheader()
            return
        cols = list(rows[0].keys())
        with open(F(name), 'w', newline='') as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            wr.writeheader()
            wr.writerows(rows)
    w('members.csv', members)
    w('plates.csv', plates)
    w('bolts.csv', bolts)
    w('welds.csv', welds)
    w('assemblies.csv', assemblies)
    return dict(members=len(members), plates=len(plates), bolts=len(bolts), welds=len(welds), assemblies=len(assemblies),
                assemblies_nested=sum(1 for t in tree if t['parent_id']), assemblies_without_own_parts=sum(1 for r in assemblies if not r['n_parts']))


if __name__ == '__main__':
    print(main(sys.argv[1]))
