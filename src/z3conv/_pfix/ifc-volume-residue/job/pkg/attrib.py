#!/usr/bin/env python3
"""Attribute every volume-tolerance failure of a run_case2 work dir to converter or grader (census).
usage: attrib.py WORKDIR OUT.json [--max N] [--all-sample K]
Per matched part counted by grade_join as outside (non-curved > 5 %, curved outside 0.90..1.05):
  E  census expectation (grade_join.expected_volume: an | q), S STEP read-back volume (step_parts), sidecar mesh volume,
  X  exact ifcopenshell/OCC B-rep volume of the product (openings applied), X0 same without openings,
  representation description (items through mapped items / booleans, profile + dims), openings and their bodies,
  every IfcQuantityVolume / IfcQuantityWeight, file units.
cause: converter (|S/X-1| > 1 %; curved parts: tessellation) | census (|X/E-1| > 5 %) | both | marginal | unknown"""
import sys, os, json, gzip, collections, math, argparse, random, time
sys.path.insert(0, os.environ.get('KIT', '/work/agentwork/ifc-volume-residue/pkg/kit'))
import grade_join as GJ
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.unit
import ifcopenshell.ifcopenshell_wrapper as WR
from OCC.Core.BRepTools import breptools
from OCC.Core.TopoDS import TopoDS_Shape
from OCC.Core.BRep import BRep_Builder
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID

ap = argparse.ArgumentParser(); ap.add_argument('wd'); ap.add_argument('out'); ap.add_argument('--max', type=int, default=250)
ap.add_argument('--all-sample', type=int, default=0, help='also attribute K random in-band parts (control)')
a = ap.parse_args()
T0 = time.time()
wd = a.wd
ifc = next((os.path.join(wd, n) for n in ('hdr.ifc', 'merged.ifc', 'schema.ifc', 'unz.ifc', 'unz.ifcXML', 'in.bin') if os.path.exists(os.path.join(wd, n))), None)
src = GJ.load(os.path.join(wd, 'src_parts.jsonl.gz'))
stp = GJ.load(os.path.join(wd, 'step_parts.jsonl.gz'))
side = {}
try:
    for p in json.load(open(os.path.join(wd, 'out.step.parts.json')))['parts']:
        side.setdefault(p.get('gid'), p)
except Exception:
    pass
bypid = {}
for s in stp:
    if GJ.present(s) and s.get('pid'):
        bypid.setdefault(s['pid'], s)
outside, inband = [], []
for p in src:
    s = bypid.get(p.get('gid'))
    if s is None:
        continue
    v = s.get('volume'); e = GJ.expected_volume(p)
    if not v or not e or e <= 0 or (s.get('solids') or 0) == 0:
        continue
    r = v / e
    curved = bool(p.get('an') and p.get('pt') in GJ.CURVED)
    if abs(r - 1) > 0.05:
        if curved and GJ.CURVED_BAND[0] <= r <= GJ.CURVED_BAND[1]:
            continue
        outside.append((p, s, r))
    else:
        inband.append((p, s, r))
n_out = len(outside)
# diverse sample when there are many: round-robin over (class, census kind, profile)
if len(outside) > a.max:
    groups = collections.defaultdict(list)
    for t in outside:
        groups[(t[0]['cls'], 'an' if t[0].get('an') else t[0].get('qk'), t[0].get('pt'))].append(t)
    pick = []
    while len(pick) < a.max:
        for k in list(groups):
            if groups[k]:
                pick.append(groups[k].pop(0))
                if len(pick) >= a.max:
                    break
            else:
                del groups[k]
        if not groups:
            break
    outside = pick
rng = random.Random(1)
ctrl = rng.sample(inband, min(a.all_sample, len(inband))) if a.all_sample else []

f = ifcopenshell.open(ifc)
L_SI = float(ifcopenshell.util.unit.calculate_unit_scale(f, 'LENGTHUNIT') or 1.0)
try:
    V_SI = float(ifcopenshell.util.unit.calculate_unit_scale(f, 'VOLUMEUNIT'))
except Exception:
    V_SI = None
units = []
try:
    for ua in f.by_type('IfcUnitAssignment'):
        for u in ua.Units:
            if u.is_a('IfcNamedUnit') and str(getattr(u, 'UnitType', '')) in ('LENGTHUNIT', 'VOLUMEUNIT', 'MASSUNIT', 'AREAUNIT'):
                if u.is_a('IfcSIUnit'):
                    units.append(f"{u.UnitType}:SI:{u.Prefix or ''}{u.Name}")
                elif u.is_a('IfcConversionBasedUnit'):
                    units.append(f"{u.UnitType}:{u.Name}:{u.ConversionFactor.ValueComponent.wrappedValue if u.ConversionFactor else ''}")
                else:
                    units.append(f"{u.UnitType}:{u.is_a()}")
except Exception as ex:
    units.append(f'error {ex}')
apps = []
try:
    apps = sorted({(x.ApplicationFullName or '') + ' ' + (x.Version or '') for x in f.by_type('IfcApplication')})[:3]
except Exception:
    pass


def mk_settings(no_open=False):
    st = ifcopenshell.geom.settings()
    st.set('use-world-coords', True)
    try:
        st.set('iterator-output', WR.SERIALIZED)
    except Exception:
        pass
    if no_open:
        st.set('disable-opening-subtractions', True)
    return st


ST1 = mk_settings(False); ST0 = mk_settings(True)
FN = '/tmp/_attr_%d.brep' % os.getpid()


def brep_volume(st, e):
    try:
        sh = ifcopenshell.geom.create_shape(st, e)
        g = sh.geometry if hasattr(sh, 'geometry') else sh
        data = g.brep_data
        if isinstance(data, bytes):
            open(FN, 'wb').write(data)
        else:
            open(FN, 'w').write(data)
        shape = TopoDS_Shape(); breptools.Read(shape, FN, BRep_Builder())
        gp = GProp_GProps(); brepgprop.VolumeProperties(shape, gp)
        ns = 0; ex = TopExp_Explorer(shape, TopAbs_SOLID)
        while ex.More():
            ns += 1; ex.Next()
        return gp.Mass() * 1e9, ns, None
    except Exception as ex:
        return None, None, f'{type(ex).__name__}: {str(ex)[:120]}'


def r4(x):
    return None if x is None else round(x, 4)


def prof(pr, depth=0):
    t = pr.is_a()[3:]
    try:
        if pr.is_a('IfcParameterizedProfileDef'):
            vals = []
            for i in range(pr.__len__()):
                nm = pr.attribute_name(i)
                if nm in ('ProfileType', 'ProfileName', 'Position'):
                    continue
                v = pr[i]
                if isinstance(v, float):
                    vals.append(f'{nm}={v:.5g}')
            return t + '(' + ','.join(vals) + ')' + (f" '{pr.ProfileName}'" if getattr(pr, 'ProfileName', None) else '')
        if pr.is_a('IfcArbitraryClosedProfileDef'):
            c = pr.OuterCurve
            n = len(c.Points) if c.is_a('IfcPolyline') else (len(c.Segments) if c.is_a('IfcCompositeCurve') else '?')
            voids = len(pr.InnerCurves) if pr.is_a('IfcArbitraryProfileDefWithVoids') else 0
            return f'{t}({c.is_a()[3:]}:{n}' + (f',voids={voids}' if voids else '') + ')'
        if pr.is_a('IfcDerivedProfileDef'):
            return f'{t}(' + prof(pr.ParentProfile, depth + 1) + ')'
        if pr.is_a('IfcCompositeProfileDef'):
            return f'{t}(' + ';'.join(prof(x, depth + 1) for x in pr.Profiles) + ')'
    except Exception as ex:
        return t + f'(?{type(ex).__name__})'
    return t


def desc(it, depth=0):
    t = it.is_a()
    if depth > 6:
        return t[3:]
    try:
        if t == 'IfcMappedItem':
            tr = it.MappingTarget
            ex = []
            for n in ('Scale', 'Scale2', 'Scale3'):
                v = getattr(tr, n, None)
                if v not in (None, 1.0):
                    ex.append(f'{n}={v:.5g}')
            if tr.is_a('IfcCartesianTransformationOperator3DnonUniform'):
                ex.append('nonUniform')
            return 'Map[' + ' '.join(ex) + '](' + ','.join(desc(x, depth + 1) for x in it.MappingSource.MappedRepresentation.Items) + ')'
        if t in ('IfcBooleanResult', 'IfcBooleanClippingResult'):
            return f'{t[3:]}[{it.Operator}](' + desc(it.FirstOperand, depth + 1) + ',' + desc(it.SecondOperand, depth + 1) + ')'
        if t in ('IfcExtrudedAreaSolid', 'IfcExtrudedAreaSolidTapered'):
            dr = it.ExtrudedDirection.DirectionRatios
            n = math.sqrt(sum(x * x for x in dr)) or 1
            obl = '' if abs(abs(dr[2]) / n - 1) < 1e-9 else f' cz={abs(dr[2]) / n:.4f}'
            return f'Extr[{prof(it.SweptArea)}; d={it.Depth:.5g}{obl}]'
        if t in ('IfcRevolvedAreaSolid',):
            return f'Revolve[{prof(it.SweptArea)}; a={it.Angle:.4g}]'
        if t in ('IfcSweptDiskSolid',):
            return f'SweptDisk[r={it.Radius:.4g}, ri={it.InnerRadius}]'
        if t in ('IfcFacetedBrep', 'IfcFacetedBrepWithVoids'):
            return f'{t[3:]}[{len(it.Outer.CfsFaces)}f]'
        if t in ('IfcPolygonalBoundedHalfSpace', 'IfcHalfSpaceSolid', 'IfcBoxedHalfSpace'):
            return t[3:]
        if t == 'IfcShellBasedSurfaceModel':
            return f'SBSM[{len(it.SbsmBoundary)}]'
    except Exception as ex:
        return t[3:] + f'(?{type(ex).__name__})'
    return t[3:]


def body_desc(e):
    rep = getattr(e, 'Representation', None)
    if rep is None:
        return None, []
    reps = [r for r in rep.Representations if r.RepresentationIdentifier in (None, 'Body', 'Facetation')]
    rids = [f'{r.RepresentationIdentifier}:{r.RepresentationType}:{len(r.Items)}' for r in reps]
    items = []
    for r in reps:
        for it in r.Items:
            items.append(desc(it))
    return rids, items


def quantities(e):
    out = []
    try:
        for rel in getattr(e, 'IsDefinedBy', None) or []:
            if not rel.is_a('IfcRelDefinesByProperties'):
                continue
            pd = rel.RelatingPropertyDefinition
            if not pd.is_a('IfcElementQuantity'):
                continue
            for q in pd.Quantities:
                if q.is_a('IfcQuantityVolume'):
                    out.append([pd.Name, q.Name, 'V', q.VolumeValue, q.Unit.is_a() if q.Unit else None])
                elif q.is_a('IfcQuantityWeight'):
                    out.append([pd.Name, q.Name, 'W', q.WeightValue, q.Unit.is_a() if q.Unit else None])
                elif q.is_a('IfcQuantityLength') and (q.Name or '').lower() in ('length', 'width', 'height', 'depth', 'thickness'):
                    out.append([pd.Name, q.Name, 'L', q.LengthValue, None])
                elif q.is_a('IfcQuantityArea') and 'cross' in (q.Name or '').lower():
                    out.append([pd.Name, q.Name, 'A', q.AreaValue, None])
    except Exception as ex:
        out.append(['error', str(ex)[:80]])
    return out[:12]


recs = []
for kind, lst in (('outside', outside), ('control', ctrl)):
    for p, s, r in lst:
        try:
            e = f.by_guid(p['gid'])
        except Exception:
            e = None
        if e is None:
            continue
        E = GJ.expected_volume(p); S = s.get('volume')
        X, nx, err = brep_volume(ST1, e)
        ops = [o.RelatedOpeningElement for o in (getattr(e, 'HasOpenings', None) or [])]
        X0, nx0, err0 = (brep_volume(ST0, e) if ops else (X, nx, err))
        rids, items = body_desc(e)
        op_items = []
        for o in ops[:6]:
            _, oi = body_desc(o)
            op_items.append(';'.join(oi)[:160])
        sd = side.get(p['gid']) or {}
        curved = bool(p.get('an') and p.get('pt') in GJ.CURVED)
        conv = (S / X - 1) if X else None
        grad = (X / E - 1) if X else None
        tags = sd.get('tags') or []
        approx = 'approx-curved' in tags
        if X is None or X <= 0:
            cause = 'unknown'
        else:
            ct = abs(conv) > 0.01
            gt = abs(grad) > 0.05
            if ct and gt:
                cause = 'both'
            elif ct:
                cause = 'converter_tessellation' if approx and abs(conv) <= 0.08 else 'converter'
            elif gt:
                cause = 'census'
            else:
                cause = 'marginal'
        recs.append({'kind': kind, 'gid': p['gid'], 'cls': p['cls'], 'name': p.get('name'), 'census': {k: p.get(k) for k in ('an', 'pt', 'q', 'qk', 'op', 'cv')},
                     'E': round(E, 1), 'S': S, 'X': round(X, 1) if X else None, 'X0': round(X0, 1) if X0 else None, 'nsolX': nx,
                     'S_E': r4(r), 'S_X': r4(S / X) if X else None, 'X_E': r4(X / E) if X else None, 'X0_E': r4(X0 / E) if X0 else None,
                     'X_X0': r4(X / X0) if (X and X0) else None, 'cause': cause, 'curved_an': curved,
                     'rids': rids, 'items': items[:6], 'n_items': len(items), 'openings': len(ops), 'op_items': op_items,
                     'quantities': quantities(e), 'side': {k: sd.get(k) for k in ('src', 'level', 'tags', 'solids', 'surface_models', 'faces', 'volume_mm3', 'why')},
                     'step': {k: s.get(k) for k in ('solids', 'valid', 'faces', 'volume')}, 'err': err})
summ = collections.Counter(r['cause'] for r in recs if r['kind'] == 'outside')
by = collections.Counter((r['cause'], r['cls'], 'an:' + str(r['census']['pt']) if r['census']['an'] else 'q:' + str(r['census']['qk'])) for r in recs if r['kind'] == 'outside')
out = {'wd': wd, 'ifc': os.path.basename(ifc), 'apps': apps, 'units': units, 'L_SI': L_SI, 'V_SI': V_SI, 'outside_total': n_out,
       'attributed': sum(1 for r in recs if r['kind'] == 'outside'), 'summary': dict(summ),
       'by': [[list(k), v] for k, v in by.most_common()], 'sec': round(time.time() - T0, 1), 'parts': recs}
json.dump(out, open(a.out, 'w'), indent=0, default=str)
print(json.dumps({k: out[k] for k in ('wd', 'apps', 'units', 'outside_total', 'attributed', 'summary', 'sec')}, default=str))
