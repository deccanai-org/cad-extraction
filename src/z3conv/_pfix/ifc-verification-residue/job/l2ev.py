#!/usr/bin/env python3
"""Evidence for parts that ifc2step6 dev3 still writes at L2 (alternative source), taken from the produced STEP itself.
Per L2 part:
  source   - IFC product (eid, GlobalId, class, name), body representation (identifier, item ids / types) and what the
             converter used at L0 vs L2 (sidecar `src`, fallback history `why`)
  STEP     - the grader's own read-back of this run (step_check per-root record: solids, BRepCheck-valid solids,
             volume) and an independent OCC re-read of the produced STEP root (valid, volume, vertices)
  exact    - volume of the exact kernel B-rep of the same IFC product (ifcopenshell, no tessellation, OCC GProp) and
             the largest distance of (up to 300) STEP vertices of the part to that exact B-rep
  census   - census inventory record (expected volume: analytic `an` or quantity `q`) and the ratio STEP / expected
usage: l2ev.py RUNDIR IFC OUT.jsonl [--max 40] [--levels 2]"""
import sys, os, re, json, gzip, math, tempfile, argparse, collections
ap = argparse.ArgumentParser()
ap.add_argument('rundir'); ap.add_argument('ifc'); ap.add_argument('out')
ap.add_argument('--max', type=int, default=40); ap.add_argument('--levels', default='2')
a = ap.parse_args()
levels = set(int(x) for x in a.levels.split(','))
P = json.load(open(os.path.join(a.rundir, 'out.step.parts.json')))
sel = [p for p in P['parts'] if p['level'] in levels][:a.max]
out = open(a.out, 'w')
if not sel:
    out.write(json.dumps({'rundir': a.rundir, 'l2_parts': 0}) + '\n'); sys.exit(0)
want = {p['gid'] for p in sel}


def loadgz(fn):
    try:
        return [json.loads(l) for l in gzip.open(fn, 'rt') if l.strip()]
    except Exception:
        return []


src = {r.get('gid'): r for r in loadgz(os.path.join(a.rundir, 'src_parts.jsonl.gz'))}
stp = {}
for r in loadgz(os.path.join(a.rundir, 'step_parts.jsonl.gz')):
    if r.get('pid') in want:
        stp[r['pid']] = r
# ---- STEP: map roots to PRODUCT ids (text pass as in step_check), read the L2 roots
stepf = os.path.join(a.rundir, 'out.step')
ent_re = re.compile(r"^#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*)\)\s*;\s*$", re.S)
prod, pdf, pd, pds, sdr = {}, {}, {}, {}, {}
buf = ''
for line in open(stepf, encoding='latin-1'):
    if not ('PRODUCT' in line or 'SHAPE_DEFINITION_REPRESENTATION' in line or buf):
        continue
    buf += line
    if not buf.rstrip().endswith(';'):
        continue
    st, buf = buf, ''
    m = ent_re.match(st.strip())
    if not m:
        continue
    eid, typ, body = int(m.group(1)), m.group(2), m.group(3)
    refs = [int(x) for x in re.findall(r'#(\d+)', body)]
    if typ == 'PRODUCT':
        s = re.findall(r"'((?:[^']|'')*)'", body); prod[eid] = s[0] if s else ''
    elif typ == 'PRODUCT_DEFINITION_FORMATION':
        pdf[eid] = refs[-1]
    elif typ == 'PRODUCT_DEFINITION':
        pd[eid] = refs[0]
    elif typ == 'PRODUCT_DEFINITION_SHAPE':
        pds[eid] = refs[0]
    elif typ == 'SHAPE_DEFINITION_REPRESENTATION':
        sdr[eid] = refs[0]


def pid_of(eid):
    if eid in sdr:
        eid = pds.get(sdr[eid])
    if eid in pd:
        return prod.get(pdf.get(pd[eid]))
    return None


from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_VERTEX, TopAbs_FACE
from OCC.Core.BRep import BRep_Tool, BRep_Builder
from OCC.Core.TopoDS import topods, TopoDS_Shape
from OCC.Core.BRepTools import breptools
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCC.Core.gp import gp_Pnt
rd = STEPControl_Reader(); rd.ReadFile(stepf)
model = rd.WS().Model()
occ = {}
for i in range(1, rd.NbRootsForTransfer() + 1):
    ent = rd.RootForTransfer(i)
    try:
        e = int(model.StringLabel(ent).ToCString().lstrip('#'))
    except Exception:
        continue
    g = pid_of(e)
    if g not in want:
        continue
    if not rd.TransferRoot(i):
        occ[g] = {'empty': True}; continue
    sh = rd.Shape(rd.NbShapes())
    sols = []
    ex = TopExp_Explorer(sh, TopAbs_SOLID)
    while ex.More():
        sols.append(ex.Current()); ex.Next()
    vals, vols = [], []
    for s in sols:
        vals.append(bool(BRepCheck_Analyzer(s).IsValid()))
        gp = GProp_GProps(); brepgprop.VolumeProperties(s, gp); vols.append(gp.Mass())
    pts = []
    ex = TopExp_Explorer(sh, TopAbs_VERTEX)
    while ex.More():
        p_ = BRep_Tool.Pnt(topods.Vertex(ex.Current())); pts.append((p_.X(), p_.Y(), p_.Z())); ex.Next()
    nf = 0
    ex = TopExp_Explorer(sh, TopAbs_FACE)
    while ex.More():
        nf += 1; ex.Next()
    occ[g] = {'solids': len(sols), 'valid': vals, 'volume': round(sum(vols), 3), 'faces': nf, 'pts': sorted(set(pts))}
# ---- IFC: exact B-rep of the same product
import ifcopenshell, ifcopenshell.geom
f = ifcopenshell.open(a.ifc)
stx = ifcopenshell.geom.settings()
stx.set('use-world-coords', True)
try:
    stx.set('iterator-output', ifcopenshell.ifcopenshell_wrapper.SERIALIZED)
except Exception:
    pass
for p in sel:
    g = p['gid']
    rec = {'gid': g, 'cls': p['cls'], 'name': p['name'], 'level': p['level'], 'src_L0': p['src'], 'tags': p['tags'], 'why': p['why'],
           'sidecar_solids': p['solids'], 'sidecar_surfaces': p['surface_models'], 'sidecar_mesh_volume_mm3': p['volume_mm3']}
    try:
        pr = f.by_guid(g)
        rep = pr.Representation
        reps = [(r.RepresentationIdentifier, r.RepresentationType, [(it.id(), it.is_a()) for it in r.Items or []]) for r in (rep.Representations if rep else [])]
        rec['ifc'] = {'eid': pr.id(), 'class': pr.is_a(), 'name': pr.Name, 'representations': reps,
                      'openings': len(getattr(pr, 'HasOpenings', None) or [])}
        mi = [it for r in (rep.Representations if rep else []) for it in (r.Items or []) if it.is_a('IfcMappedItem')]
        if mi:
            rec['ifc']['mapped_source_items'] = [(it.MappingSource.id(), [(x.id(), x.is_a()) for x in it.MappingSource.MappedRepresentation.Items]) for it in mi]
    except Exception as e:
        rec['ifc_err'] = str(e)[:200]; pr = None
    exact = None
    if pr is not None:
        try:
            sh = ifcopenshell.geom.create_shape(stx, pr)
            brep = sh.geometry.brep_data if hasattr(sh, 'geometry') and hasattr(sh.geometry, 'brep_data') else getattr(sh, 'brep_data', None)
            if brep is None:
                brep = sh.brep_data
            fn = tempfile.mktemp(suffix='.brep'); open(fn, 'w').write(brep)
            exact = TopoDS_Shape(); breptools.Read(exact, fn, BRep_Builder()); os.remove(fn)
            gp = GProp_GProps(); brepgprop.VolumeProperties(exact, gp)
            rec['exact_brep_volume_mm3'] = round(gp.Mass() * 1e9, 3)
        except Exception as e:
            rec['exact_err'] = str(e)[:200]
    o = occ.get(g)
    if o is not None:
        pts = o.pop('pts', [])
        rec['occ_reread'] = o
        if exact is not None and pts:
            step_ = max(1, len(pts) // 300)
            dmax = 0.0
            for (x, y, z) in pts[::step_]:
                d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(x / 1000.0, y / 1000.0, z / 1000.0)).Vertex(), exact)
                if d.IsDone():
                    dmax = max(dmax, d.Value() * 1000.0)
            rec['max_vertex_distance_to_exact_mm'] = round(dmax, 4)
            rec['vertices_checked'] = len(pts[::step_])
    s = stp.get(g)
    if s is not None:
        rec['grader_step_check'] = {k: s.get(k) for k in ('solids', 'valid', 'volume', 'faces', 'shells')}
    c = src.get(g)
    if c is not None:
        ev = c.get('an') or c.get('q')
        rec['census'] = {k: c.get(k) for k in ('cls', 'cat', 'name', 'an', 'q', 'qk', 'pt', 'cv', 'standin')}
        v = (s or {}).get('volume') or (o or {}).get('volume')
        if ev and v:
            rec['census_ratio'] = round(v / ev, 4)
    if rec.get('exact_brep_volume_mm3') and (o or {}).get('volume'):
        rec['step_vs_exact_ratio'] = round(o['volume'] / rec['exact_brep_volume_mm3'], 6)
    out.write(json.dumps(rec, default=str) + '\n'); out.flush()
