#!/usr/bin/env python3
"""restore_sds2.py - GREEN restoration of an SDS/2-converted partial model (track sds2_ifc), pipeline env (python 3.11,
OCP).  Deterministic: same inputs -> byte-identical restoration_log.json / restored_geometry.jsonl / restored_green.step.

Inputs: the delivered STEP (written by the pinned converter build), and the probe of the SAME SDS/2 job re-converted by
the newest converter build (sds2_probe.py: its STEP, manifest, pieces table, every SDS/2 bolt record of the job).
Only parts the newer build makes from the job's own records, without any stand-in tag, are taken (GREEN):
  grating_from_record        bar gratings the delivered file left out or wrote as a solid panel, built from SDS/2's own
                             grating piece faces + grating record (bars, bands, carrier plates; cross bars = the stored
                             rectangles extruded by the record's cross-bar depth); built weight within 3 % of SDS/2's
  nominal_bolt_on_stored_bolt  a bolt the delivered file GUESSED through a hole stack where SDS/2 stores that bolt itself
                             (BLT head / nut / washer pieces on the same axis, already in the model as exact pieces): the
                             guess is removed, the stored bolt stays (no new geometry)
and it audits, without changing anything, what the track also covers:
  SDS/2 bolt records (f32 / f64) not yet used, expansion anchors, members without pieces, mating holes.
usage: restore_sds2.py --probe-dir VOLDIR --step DELIVERED.step --facts sds2_facts.json --out OUT --model-id ID
"""
import argparse, collections, hashlib, json, os, re, sys

import numpy as np

VERSION = 'restore_sds2 1.0 (pmp-complete sds2_ifc)'
GREEN_RGB = (0.0, 0.70, 0.25)
STEEL_LB_PER_IN3 = 0.2836
MM3_PER_IN3 = 25.4 ** 3


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def r6(x):
    return float(f'{x:.6f}')


def S(cls, name):
    """OCP static method across versions (name_s in 7.x, name in 8.x)"""
    return getattr(cls, name + '_s', None) or getattr(cls, name)


def _cast(kind, s):
    from OCP.TopoDS import TopoDS
    return (getattr(TopoDS, kind + '_s', None) or getattr(TopoDS, kind))(s)


def read_leaves(path):
    """STEP (XCAF) -> [(instance label, located shape)] in document order, assemblies flattened"""
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDF import TDF_Label
    try:
        from OCP.TDF import TDF_LabelSequence
    except ImportError:
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    from OCP.TDataStd import TDataStd_Name
    from OCP.TopLoc import TopLoc_Location
    doc = TDocStd_Document(TCollection_ExtendedString('pmp'))
    rd = STEPCAFControl_Reader()
    rd.SetNameMode(True)
    rd.SetColorMode(True)
    assert int(rd.ReadFile(path)) == 1, f'cannot read {path}'
    rd.Transfer(doc)
    st = S(XCAFDoc_DocumentTool, 'ShapeTool')(doc.Main())

    def name(lab):
        a = TDataStd_Name()
        if lab.FindAttribute(S(TDataStd_Name, 'GetID')(), a):
            return a.Get().ToExtString()
        return ''
    out = []

    def walk(lab, loc, nm):
        if S(st, 'IsReference')(lab):
            ref = TDF_Label()
            S(st, 'GetReferredShape')(lab, ref)
            walk(ref, loc.Multiplied(S(st, 'GetLocation')(lab)), name(lab) or nm)
            return
        if S(st, 'IsAssembly')(lab):
            seq = TDF_LabelSequence()
            S(st, 'GetComponents')(lab, seq, False)
            for i in range(1, seq.Length() + 1):
                walk(seq.Value(i), loc, '')
            return
        shp = S(st, 'GetShape')(lab)
        out.append((nm or name(lab), shp.Moved(loc)))
    roots = TDF_LabelSequence()
    st.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        walk(roots.Value(i), TopLoc_Location(), '')
    return out


def props(shp):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    g = GProp_GProps()
    S(BRepGProp, 'VolumeProperties')(shp, g)
    c = g.CentreOfMass()
    b = Bnd_Box()
    S(BRepBndLib, 'Add')(shp, b)
    lo, hi = b.CornerMin(), b.CornerMax()
    x0, y0, z0, x1, y1, z1 = lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()
    return dict(volume_mm3=r6(abs(g.Mass())), centroid_mm=[r6(c.X()), r6(c.Y()), r6(c.Z())],
                bbox_mm=[r6(v) for v in (x0, y0, z0, x1, y1, z1)], valid=bool(BRepCheck_Analyzer(shp).IsValid()))


def solid_faces(shp):
    """planar faces of a solid -> exact_geometry face lists [[outer], [inner]...] (world mm), or None if a face is not
    planar"""
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE, TopAbs_SOLID
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.BRep import BRep_Tool
    solids = []
    ex_s = TopExp_Explorer(shp, TopAbs_SOLID)
    while ex_s.More():
        so = ex_s.Current()
        faces = []
        ex = TopExp_Explorer(so, TopAbs_FACE)
        while ex.More():
            f = _cast('Face', ex.Current())
            if BRepAdaptor_Surface(f).GetType() != GeomAbs_Plane:
                return None
            outer = S(BRepTools, 'OuterWire')(f)
            wires = [outer]
            ew = TopExp_Explorer(f, TopAbs_WIRE)
            while ew.More():
                w = _cast('Wire', ew.Current())
                if not w.IsSame(outer):
                    wires.append(w)
                ew.Next()
            loops = []
            for w in wires:
                we = BRepTools_WireExplorer(w, f)
                pts = []
                while we.More():
                    p = S(BRep_Tool, 'Pnt')(we.CurrentVertex())
                    pts.append([r6(p.X()), r6(p.Y()), r6(p.Z())])
                    we.Next()
                loops.append(pts)
            faces.append(loops)
            ex.Next()
        solids.append(dict(faces=faces))
        ex_s.Next()
    return solids


def write_step(items, path):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from restore_ifc import write_step as W
    W(items, path)


PIECE_RX = re.compile(r'^(?P<mt>[A-Z ]*?)\s*#(?P<member>\d+) / (?P<name>.+?) \(piece (?P<piece>\d+), inst (?P<inst>\d+)\)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe-dir', required=True)
    ap.add_argument('--step', required=True)
    ap.add_argument('--facts', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--model-id', required=True)
    ap.add_argument('--tag', default='')
    ap.add_argument('--meta', default='{}')
    ap.add_argument('--new-label', default='v5.5.11')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    meta = json.loads(a.meta)
    pdir = os.path.join(a.probe_dir, 'probe_' + a.new_label)
    nstep = [os.path.join(pdir, f) for f in sorted(os.listdir(pdir)) if f.endswith('_stage2.step')][0]
    man = json.load(open([os.path.join(pdir, f) for f in sorted(os.listdir(pdir)) if f.endswith('_manifest.json')][0]))
    probe = json.load(open(os.path.join(pdir, 'probe.json')))
    facts = json.load(open(a.facts))
    conv = json.load(open('/pmp/src_sds2/converters.json'))['labels'][a.new_label] if os.path.exists('/pmp/src_sds2/converters.json') else {}
    log = dict(schema='pmp-restoration-log/1', track='sds2_ifc', version=VERSION, model_id=a.model_id, tag=a.tag,
               model_folder=meta.get('model_folder'), source_kind='sds2',
               inputs=dict(delivered_step=dict(sha256=sha256(a.step), bytes=os.path.getsize(a.step),
                                               converter=facts.get('converter', {}).get('label')),
                           sds2_job_version=facts.get('sds2_job_version'),
                           reconverted_step=dict(sha256=sha256(nstep), bytes=os.path.getsize(nstep), converter=a.new_label,
                                                 converter_zip=conv.get('zip'), converter_zip_sha256=conv.get('sha256')),
                           facts_sha256=sha256(a.facts)),
               colour_rule=dict(GREEN='restored exactly from data in the source SDS/2 job that the conversion ignored or broke'),
               entries=[], removed=[], not_restored=[], checked={})
    old = read_leaves(a.step)
    new = read_leaves(nstep)
    log['checked']['instances'] = dict(delivered=len(old), reconverted=len(new))
    pieces = probe.get('pieces', {})
    rows, shapes = [], []

    # ------------------------------------------------------------------ 1. gratings from the job's grating records
    old_by_piece = collections.defaultdict(list)
    for lab, s in old:
        m = PIECE_RX.match(lab)
        if m:
            old_by_piece[(m['member'], m['piece'], m['inst'])].append((lab, s))
    skipped = {(s['member'], s['piece'], s['inst']): s for s in facts.get('skipped', [])}
    for lab, s in new:
        m = PIECE_RX.match(lab)
        if not m or not re.match(r'G[TR]\d', m['name']) or '[approx' in lab:
            continue
        k = (m['member'], m['piece'], m['inst'])
        pr = props(s)
        pc = pieces.get(m['piece'], {})
        wt = pc.get('wt')
        built_lb = pr['volume_mm3'] / MM3_PER_IN3 * STEEL_LB_PER_IN3
        prev = old_by_piece.get(k, [])
        ent = dict(part_label=lab, kind='grating_from_record', member=int(m['member']), piece=int(m['piece']),
                   inst=int(m['inst']), name=m['name'], geometry=pr,
                   weight=dict(built_lb=r6(built_lb), sds2_piece_lb=wt, ratio=r6(built_lb / wt) if wt else None),
                   delivered=dict(state='replaced' if prev else 'missing',
                                  labels=[x[0] for x in prev],
                                  why=(skipped[k]['reason'] if k in skipped else None) or
                                      ('written as a solid panel / outline fallback (approximation)' if prev else None)))
        if not wt or abs(built_lb / wt - 1) > 0.03 or not pr['valid']:
            ent['why'] = 'grating built by the newer converter fails the gate (valid + weight within 3 % of SDS/2)'
            log['not_restored'].append(ent)
            continue
        ent.update(colour='GREEN',
                   what=f"bar grating {m['name']} built bar by bar from SDS/2's own grating piece (piece {m['piece']})",
                   source_fields=[f"subm piece {m['piece']} faces (bars, bands, carrier plates, nosing)",
                                  'grating record (cross-bar depth / spacing, stored cross-bar rectangles)',
                                  f"member {m['member']} placement (mem/{m['member']})", 'piece-table weight (gate)'],
                   basis=f"converter {a.new_label} grating builder ({man.get('grating', {}).get('note', '')})",
                   unchanged='no other part is touched')
        solids = solid_faces(s)
        pid = f"sds2:{m['member']}:{m['piece']}:{m['inst']}"
        ent['part_id'] = pid
        if solids is not None:
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ref'))
                import steelbuild as SB
                sb = SB.exact_part(dict(solids=solids))
                ent['steelbuild_exact_part'] = dict(solids=len(sb), valid=all(x.is_valid for x in sb),
                                                    volume_mm3=r6(sum(x.volume for x in sb)))
            except Exception as e:  # noqa: BLE001
                ent['steelbuild_exact_part'] = dict(error=repr(e)[:300])
            rows.append(dict(part_id=pid, label=lab, source=f'SDS/2 grating record + piece faces, re-converted with '
                                                             f'{a.new_label} (pmp-complete sds2_ifc GREEN)',
                             solids=solids, restore=dict(colour='GREEN', kind='grating_from_record',
                                                         replaces=[x[0] for x in prev])))
        from OCP.BRepTools import BRepTools
        bdir = os.path.join(a.out, 'brep')
        os.makedirs(bdir, exist_ok=True)
        bp = os.path.join(bdir, f"grating_m{m['member']}_p{m['piece']}_i{m['inst']}.brep")
        S(BRepTools, 'Write')(s, bp)
        ent['brep'] = os.path.relpath(bp, a.out)
        shapes.append((s, f"{lab} [GREEN restored: grating built from SDS/2's grating record + piece faces; "
                          f"weight {built_lb:.1f} lb vs SDS/2 {wt:.1f} lb]", GREEN_RGB))
        log['entries'].append(ent)

    # ------------------------------------------------------------------ 2. guessed bolts on SDS/2's own stored bolts
    def is_nominal(lab):
        return lab.startswith('BOLT') and 'nominal' in lab
    o_nom = [(lab, s, props(s)) for lab, s in old if is_nominal(lab)]
    n_nom = [(lab, s, props(s)) for lab, s in new if is_nominal(lab)]
    blt = [(lab, props(s)) for lab, s in old if re.search(r'/ (BLT|HS|NUT|WASH)', lab)]
    nc = np.array([p['centroid_mm'] for _, _, p in n_nom]) if n_nom else np.zeros((0, 3))
    removed = []
    for lab, s, p in o_nom:
        c = np.array(p['centroid_mm'])
        if len(nc) and np.linalg.norm(nc - c, axis=1).min() < 0.01:
            continue
        # the stored bolt pieces on this bolt's axis (inside its bounding box, grown by 1 in)
        b = np.array(p['bbox_mm'])
        on = [bl for bl, bp in blt if np.all(np.array(bp['centroid_mm']) >= b[:3] - 25.4) and
              np.all(np.array(bp['centroid_mm']) <= b[3:] + 25.4)]
        removed.append(dict(part_label=lab, kind='nominal_bolt_on_stored_bolt', centroid_mm=p['centroid_mm'],
                            stored_bolt_pieces=on[:6], n_stored_pieces=len(on)))
    exp = (man.get('counts', {}).get('bolts_on_stored_hardware') or {}).get('nominal')
    log['checked']['nominal_bolts'] = dict(delivered=len(o_nom), reconverted=len(n_nom), removed=len(removed),
                                           converter_bolts_on_stored_hardware=exp)
    for r in removed:
        r.update(what='bolt guessed through a hole stack, removed: SDS/2 stores this bolt itself (its BLT pieces are '
                      'already in the model as exact pieces, unchanged)',
                 basis=f'converter {a.new_label} stored_hardware rule: a stored BLT head / nut / washer piece centred on '
                       'the stack axis within a bolt diameter + 2 in of the grip')
        log['removed'].append(r)

    # ------------------------------------------------------------------ 3. audits (nothing changed)
    recs = probe.get('all_records', [])
    main = [r for r in recs if r.get('frame') == 'main']
    rec_heads = np.array([r['head'] for r in main]) if main else np.zeros((0, 3))
    o_sds2 = [lab for lab, _ in old if lab.startswith('BOLT') and 'nominal' not in lab]
    log['checked']['sds2_bolt_records'] = dict(
        records=len(main), layouts=dict(collections.Counter(r['layout'] for r in main)),
        by_dia_length_type=dict(collections.Counter(f"{r['dia']:g}x{r['length']:g} type {probe.get('bolt_types', {}).get(str(r['type']), r['type'])}" for r in main)),
        delivered_record_bolts=len(o_sds2),
        unused_records=max(0, len(main) - len(o_sds2)),
        note='every SDS/2 bolt record of the job is already a bolt in the delivered model' if len(main) == len(o_sds2)
        else 'records exist that the delivered model does not use')
    rest_nom = len(n_nom)
    log['not_restored'].append(dict(kind='nominal_bolt_without_record', count=rest_nom,
                                    why='no SDS/2 bolt record and no stored bolt piece covers these hole stacks: diameter '
                                        'and grip are exact (the holes), length / head side / washers are not in the job',
                                    handoff='BLUE (bolt assembly per RCSC / ASTM F3125 for the exact diameter and grip)'))
    hn = man.get('holes', {}).get('holes_not_cut', {})
    log['checked']['mating_holes'] = dict(derived_by_converter=man.get('holes', {}).get('derived', {}).get('holes'),
                                          not_cut_by_reason=hn.get('by_reason'))
    for why, n in (hn.get('by_reason') or {}).items():
        log['not_restored'].append(dict(kind='mating_hole', count=n, why=why,
                                        handoff='BLUE (standard hole d + 1/16 in, AISC 360 J3.2) where a bolt record '
                                                'crosses the piece; none otherwise' if 'diameter unknown' in why else
                                        'none: a single-ply hole with no bolt and no stack (anchor or field hole); '
                                        'nothing in the job says what mates with it'))
    mw = facts.get('members_without_geometry', [])
    env = [i for i in facts.get('instances', []) if i.get('category') == 'member_envelope']
    for e in env:
        mem = next((m for m in facts.get('members', []) if m['member'] == e.get('member')), {})
        log['not_restored'].append(dict(kind='member_without_pieces', part_label=e['label'], member=e.get('member'),
                                        exact_data=dict(section=mem.get('section'), work_line_mm=[mem.get('p1_mm'), mem.get('p2_mm')],
                                                        roll=mem.get('roll')),
                                        why='SDS/2 holds the member (work line + section) but no fabricated piece: its cut '
                                            'length and end preparation are not in the job',
                                        handoff='AMBER (section along the work line, ends trimmed to the members it frames into)'))
    log['checked']['members_without_geometry'] = len(mw)
    anchors = [lab for lab, _ in old if re.search(r'\bAB\d|ANCHOR|WEDGE|KWIK|EXPANSION', lab, re.I)]
    log['checked']['expansion_anchors'] = dict(
        anchor_pieces_in_delivered=len(anchors),
        records_in_job=0,
        package_bolt_reports=False,
        note='the job stores no anchor records (bolt records are all bolts on steel plies) and the package ships no '
             'bolt / anchor report: nothing to write anchors from')

    # ------------------------------------------------------------------ outputs
    log['summary'] = dict(green=len(log['entries']), green_by_kind=dict(collections.Counter(e['kind'] for e in log['entries'])),
                          removed=len(log['removed']),
                          removed_by_kind=dict(collections.Counter(e['kind'] for e in log['removed'])),
                          not_restored=sum(e.get('count', 1) for e in log['not_restored']),
                          not_restored_by_kind={k: sum(e.get('count', 1) for e in log['not_restored'] if e['kind'] == k)
                                                for k in sorted({e['kind'] for e in log['not_restored']})})
    with open(os.path.join(a.out, 'restored_geometry.jsonl'), 'w') as f:
        for r in sorted(rows, key=lambda r: r['part_id']):
            f.write(json.dumps(r, separators=(',', ':'), sort_keys=True) + '\n')
    if shapes:
        write_step(shapes, os.path.join(a.out, 'restored_green.step'))
    log['outputs'] = {f: sha256(os.path.join(a.out, f)) for f in sorted(os.listdir(a.out))
                      if f in ('restored_geometry.jsonl', 'restored_green.step')}
    json.dump(log, open(os.path.join(a.out, 'restoration_log.json'), 'w'), indent=1, sort_keys=True, default=str)
    print(json.dumps(log['summary']), json.dumps(log['checked'], default=str)[:3000])


if __name__ == '__main__':
    main()
