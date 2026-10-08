"""diag.py MODEL_ID OUTDIR [maxparts] : root-cause the L3/L4 parts of one model (base ifc2step6 imported as module)"""
import sys, os, json, time, collections, math, tempfile, traceback
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ifc2step6 as V
import boto3
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
mid, outdir = sys.argv[1], sys.argv[2]
maxp = int(sys.argv[3]) if len(sys.argv) > 3 else 40
os.makedirs(outdir, exist_ok=True)
cen = {o['id']: o for o in json.load(open('census_out.json'))}
o = cen[mid]
bad = o['bad'][:maxp]
wd = tempfile.mkdtemp(dir=outdir)
raw = os.path.join(wd, 'in.bin')
s3.download_file(B, o['input_key'], raw)
info = {}
src = V.prepare_input(raw, wd, info)
f, src = V.open_ifc(src, wd, info)
import ifcopenshell.util.unit
sc = float(ifcopenshell.util.unit.calculate_unit_scale(f)) * 1000.0
prec = 2
rep = V.Repair(prec)
tc = V.Transcoder(f, sc)
apps = []
try:
    for a in f.by_type('IfcApplication'):
        apps.append('%s %s' % (a.ApplicationFullName, a.Version))
except Exception:
    pass

from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
from OCC.Core.gp import gp_Pnt
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SHELL, TopAbs_FACE, TopAbs_SOLID, TopAbs_EDGE
from OCC.Core.TopoDS import topods
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.ShapeFix import ShapeFix_Solid, ShapeFix_Shell
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRep import BRep_Tool
from OCC.Core.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCC.Core.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCC.Core.TopExp import topexp

def occ_faces(faces, X):
    out = []
    for fc in faces:
        ws = []
        for lp in fc:
            mp = BRepBuilderAPI_MakePolygon()
            for i in lp:
                mp.Add(gp_Pnt(*X[i].tolist()))
            mp.Close()
            if not mp.IsDone():
                ws = None; break
            ws.append(mp.Wire())
        if not ws:
            continue
        mf = BRepBuilderAPI_MakeFace(ws[0], True)
        if not mf.IsDone():
            continue
        for w in ws[1:]:
            mf.Add(w)
        out.append(mf.Face())
    return out

def sew_try(faces, X, tol):
    fs = occ_faces(faces, X)
    sw = BRepBuilderAPI_Sewing(tol)
    for fc in fs:
        sw.Add(fc)
    sw.Perform()
    sh = sw.SewedShape()
    res = {'tol': tol, 'nfree': sw.NbFreeEdges(), 'nmult': sw.NbMultipleEdges(), 'ndeg': sw.NbDegeneratedShapes()}
    shells = []
    ex = TopExp_Explorer(sh, TopAbs_SHELL)
    while ex.More():
        shells.append(topods.Shell(ex.Current())); ex.Next()
    res['shells'] = len(shells)
    ok = 0; vols = []; valid = []
    for s in shells:
        try:
            ms = BRepBuilderAPI_MakeSolid(s)
            so = ms.Solid()
            fx = ShapeFix_Solid(so); fx.Perform(); so2 = fx.Solid()
            v = bool(BRepCheck_Analyzer(so2).IsValid())
            g = GProp_GProps(); brepgprop.VolumeProperties(so2, g); vol = g.Mass()
            vols.append(round(vol, 1)); valid.append(v)
        except Exception as e:
            vols.append(None); valid.append(False)
    res['vols'] = vols; res['valid'] = valid
    return res

def topo(faces, X):
    """edge use statistics, boundary loops, gap distances"""
    A, Bb, F = rep.edge_arrays(faces)
    nv = len(X)
    if len(A) == 0:
        return {}
    key = np.minimum(A, Bb) * nv + np.maximum(A, Bb)
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    d = {'edges': int(len(uk)), 'e1': int((cnt == 1).sum()), 'e2': int((cnt == 2).sum()), 'e3p': int((cnt > 2).sum())}
    # directed consistency on 2-edges
    bnd = cnt[inv] == 1
    ba, bb_ = A[bnd], Bb[bnd]
    if len(ba):
        L = np.linalg.norm(X[ba] - X[bb_], axis=1)
        d['bnd_len_total'] = round(float(L.sum()), 2)
        d['bnd_len_max'] = round(float(L.max()), 2)
        bv = np.unique(np.concatenate([ba, bb_]))
        P = X[bv]
        # nearest other boundary vertex distance
        dm = []
        for k in range(min(len(bv), 400)):
            dd = np.linalg.norm(P - P[k], axis=1); dd[k] = 1e18
            dm.append(float(dd.min()))
        dm = np.array(dm)
        d['bv'] = int(len(bv))
        d['gap_nn_q'] = [round(float(np.quantile(dm, q)), 3) for q in (0.0, 0.5, 0.9, 1.0)]
        # boundary vertex distance to nearest boundary edge (not incident): T-junction / overlap gaps
        segs_a = X[ba]; segs_b = X[bb_]
        dv = []
        for k in range(min(len(bv), 400)):
            p = P[k]
            dvec = segs_b - segs_a
            L2 = np.einsum('ij,ij->i', dvec, dvec); L2[L2 == 0] = 1
            t = np.clip(np.einsum('ij,ij->i', p - segs_a, dvec) / L2, 0, 1)
            proj = segs_a + dvec * t[:, None]
            dist = np.linalg.norm(proj - p, axis=1)
            inc = (ba == bv[k]) | (bb_ == bv[k])
            dist[inc] = 1e18
            dv.append(float(dist.min()))
        dv = np.array(dv)
        d['gap_edge_q'] = [round(float(np.quantile(dv, q)), 3) for q in (0.0, 0.5, 0.9, 1.0)]
        # boundary loops (chains)
        nxt = collections.defaultdict(list)
        for a_, b_ in zip(ba.tolist(), bb_.tolist()):
            nxt[a_].append(b_)
        d['bnd_branch'] = int(sum(1 for v in nxt.values() if len(v) > 1))
        # planarity of the boundary as a whole + count of loops
        seen = set(); loops = []
        for a0 in list(nxt.keys()):
            if a0 in seen: continue
            lp = [a0]; seen.add(a0); cur = a0; ok = False
            for _ in range(100000):
                nx = [x for x in nxt.get(cur, []) if x not in seen or x == a0]
                if not nx: break
                cur = nx[0]
                if cur == a0: ok = True; break
                seen.add(cur); lp.append(cur)
            loops.append((len(lp), ok))
        d['bnd_loops'] = loops[:12]
        d['bnd_loops_n'] = len(loops)
        pl = []
        for lp_ in loops[:0]:
            pass
    # orientation check: 2-edges same direction
    two = np.flatnonzero(cnt == 2)
    order = np.argsort(inv, kind='stable')
    return d

def loop_planar_dev(lp, X):
    P = X[lp]
    c = P.mean(0)
    n = V.newell(P)
    ln = np.linalg.norm(n)
    if ln == 0: return None
    n = n / ln
    return float(np.abs((P - c) @ n).max())

out = {'id': mid, 'apps': apps, 'schema': f.schema, 'sc': sc, 'parts': []}
t0 = time.time()
for p in bad:
    r = {'gid': p['gid'], 'cls': p['cls'], 'src': p['src'], 'faces_out': p['faces'], 'why': p.get('why'), 'tags': p['tags']}
    try:
        pr = f.by_guid(p['gid'])
        items, rid = V.body_items(pr)
        r['rid'] = rid
        def itypes(it, d=0):
            t = it.is_a()
            if t == 'IfcMappedItem' and d < 6:
                return 'Map(' + ','.join(itypes(si, d + 1) for si in it.MappingSource.MappedRepresentation.Items) + ')'
            if t in ('IfcFacetedBrep', 'IfcFacetedBrepWithVoids'):
                return '%s[%d]' % (t, len(it.Outer.CfsFaces))
            if t == 'IfcShellBasedSurfaceModel':
                return '%s[%s]' % (t, ','.join('%s:%d' % (s.is_a(), len(s.CfsFaces)) for s in it.SbsmBoundary))
            return t
        r['items'] = [itypes(it) for it in items]
        r['rep_types'] = sorted(set(rr.RepresentationType or '' for rr in pr.Representation.Representations))
        if p['src'] == 'tc':
            pieces = tc.product(pr, items)
        else:
            pieces = None
            import ifcopenshell.geom
            s_, _, m_ = V.kernel_settings('poly')
            sh = ifcopenshell.geom.create_shape(s_, pr)
            Vv, fcs, iids = V.kernel_geometry(sh.geometry, m_)
            pieces = [V.Piece(Vv, fcs, V.kernel_role(f, fcs, iids), 1)]
        r['pieces'] = []
        for pc in pieces or []:
            q = {'role': pc.role, 'nv': int(len(pc.V)), 'nf_raw': len(pc.faces)}
            # raw topology on source indices but welded at prec
            w = rep.weld(pc.V)
            if w is None:
                q['corrupt'] = True; r['pieces'].append(q); continue
            Q, inv = w
            X = Q.astype(np.float64) / rep.qs
            # raw (unwelded index) topology: source vertex identity
            rawfaces = [[list(lp) for lp in fc] for fc in pc.faces]
            q['raw_topo'] = topo(rawfaces, pc.V)
            fs = rep.clean_faces(pc.faces, inv, X)
            q['nf_clean'] = len(fs)
            q['topo_clean'] = topo(fs, X)
            fs = rep.dedup_faces(fs)
            q['nf_dedup'] = len(fs); q['twins'] = len(rep.last_twins)
            fs2, nm = rep.sew(fs, X, rep.tol_sew)
            if nm:
                fs = rep.dedup_faces(fs2)
            q['sewn'] = nm
            fs, nt = rep.tjunctions(fs, X)
            q['tj'] = nt
            q['topo_final'] = topo(fs, X)
            shs = rep.shells(fs, X, pc.role)
            q['comps'] = [(len(s.faces), s.closed, round(s.vol, 1)) for s in shs][:20]
            q['ncomps'] = len(shs)
            # planarity of faces
            devs = [loop_planar_dev(fc[0], X) for fc in fs if len(fc[0]) > 3]
            devs = [x for x in devs if x is not None]
            q['max_planar_dev'] = round(max(devs), 4) if devs else 0
            bb = X.min(0), X.max(0)
            q['bbox'] = [round(float(x), 1) for x in (bb[1] - bb[0])]
            q['mesh_vol'] = round(rep.signed_volume(fs, X), 1)
            # OCC sewing ladder on the open components
            lad = []
            for tol in (0.01, 0.1, 0.5, 1.0, 2.0):
                try:
                    lad.append(sew_try(fs, X, tol))
                except Exception as e:
                    lad.append({'tol': tol, 'err': str(e)[:80]})
                if lad[-1].get('valid') and all(lad[-1]['valid']) and lad[-1].get('nfree') == 0:
                    break
            q['occ_ladder'] = lad
            r['pieces'].append(q)
            if len(r['pieces']) > 6:
                break
    except Exception as e:
        r['error'] = traceback.format_exc()[-600:]
    out['parts'].append(r)
out['sec'] = round(time.time() - t0, 1)
json.dump(out, open(os.path.join(outdir, mid[:16] + '.diag.json'), 'w'), indent=1)
import shutil; shutil.rmtree(wd, ignore_errors=True)
print('done', mid, len(out['parts']), out['sec'])
