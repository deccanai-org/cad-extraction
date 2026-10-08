#!/usr/bin/env python3
"""IFC audit targeted proofs (read-only). Writes proofs.json to the audit prefix.
  absurd   : products whose geometry / placement uses absurd coordinates (> 1e10 mm) in the two bbox_absurd class-3 models
  hss      : 3a5129c1 HSS4x4x1/4 column: kernel volume vs STEP part volume vs the model's own quantity sets
  precision: e7f6f3e6 (class 1, ifc2step5 '%.9g' writer, 3.95e9 mm from origin): STEP coordinates vs source coordinates
  oom      : 2bcccd9a (1.4 MB IFC, s6 run out_of_memory): deployed ifc2step6 6.0.1 under a 40 GB cap, peak RSS + phase
"""
import os, sys, json, gzip, re, time, subprocess, collections, traceback, math
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
OUTK = 'cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc'
W = '/work/agentwork/audit-ifc'; P = os.path.join(W, 'proofs'); os.makedirs(P, exist_ok=True)
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 10, 'mode': 'standard'}))
cont = {json.loads(l)['id']: json.loads(l) for l in gzip.open(os.path.join(W, 'contents_ifc.jsonl.gz'), 'rt')}
info = json.load(open(os.path.join(W, 'model_info.json')))
OUT = {}


def full(prefix):
    return next(k for k in cont if k.startswith(prefix))


def fetch(mid):
    p = os.path.join(P, mid[:16] + '.ifc')
    if not os.path.exists(p):
        s3.download_file(B, cont[mid]['input_key'], p)
    return p


def absurd(prefix):
    import ifcopenshell, ifcopenshell.util.unit, ifcopenshell.util.placement
    mid = full(prefix); path = fetch(mid)
    t0 = time.time(); f = ifcopenshell.open(path)
    sc = float(ifcopenshell.util.unit.calculate_unit_scale(f)) * 1000.0     # mm per unit
    bad_pts = []
    n_pts = 0
    for p in f.by_type('IfcCartesianPoint'):
        n_pts += 1
        c = p.Coordinates
        if any((not math.isfinite(x)) or abs(x) * sc > 1e10 for x in c):
            bad_pts.append(p)
    # products whose placement translation is absurd
    bad_place = []
    prods = [pr for pr in f.by_type('IfcProduct') if pr.Representation is not None and not pr.is_a('IfcOpeningElement')]
    for pr in prods:
        try:
            M = ifcopenshell.util.placement.get_local_placement(pr.ObjectPlacement) if pr.ObjectPlacement else None
            if M is not None and any((not math.isfinite(float(x))) or abs(float(x)) * sc > 1e10 for x in (M[0][3], M[1][3], M[2][3])):
                bad_place.append(pr)
        except Exception:
            pass
    # walk inverses from the absurd points up to products (capped)
    hit = collections.Counter(); hit_ids = set(); examples = []
    for p in bad_pts[:5000]:
        seen = {p.id()}; frontier = [p]; depth = 0
        while frontier and depth < 14:
            nxt = []
            for e in frontier:
                for inv in f.get_inverse(e):
                    if inv.id() in seen:
                        continue
                    seen.add(inv.id())
                    if inv.is_a('IfcProduct'):
                        if inv.id() not in hit_ids:
                            hit_ids.add(inv.id()); hit[inv.is_a()] += 1
                            if len(examples) < 12:
                                examples.append([inv.GlobalId, inv.is_a(), inv.Name])
                    elif inv.is_a('IfcProductDefinitionShape') or inv.is_a('IfcRepresentation') or inv.is_a('IfcRepresentationItem') \
                            or inv.is_a('IfcRepresentationMap') or inv.is_a('IfcObjectPlacement') or inv.is_a('IfcProfileDef') \
                            or inv.is_a('IfcPlacement') or inv.is_a('IfcLoop') or inv.is_a('IfcFace') or inv.is_a('IfcConnectedFaceSet') \
                            or inv.is_a('IfcCartesianPointList') or inv.is_a('IfcCurve') or inv.is_a('IfcGeometricRepresentationContext'):
                        nxt.append(inv)
            frontier = nxt; depth += 1
    return {'id': mid, 'schema': f.schema, 'mm_per_unit': sc, 'points': n_pts, 'absurd_points': len(bad_pts),
            'absurd_point_examples': [[p.id(), [float(x) for x in p.Coordinates]] for p in bad_pts[:8]],
            'products_with_body': len(prods), 'products_absurd_placement': len(bad_place),
            'absurd_placement_examples': [[pr.GlobalId, pr.is_a(), pr.Name] for pr in bad_place[:8]],
            'products_reached_from_absurd_points': len(hit_ids), 'by_class': dict(hit.most_common(15)), 'examples': examples,
            'applications': sorted({'%s %s' % (a.ApplicationFullName, a.Version) for a in f.by_type('IfcApplication')})[:4],
            'sec': round(time.time() - t0, 1)}


def hss():
    import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element, ifcopenshell.util.unit
    mid = full('3a5129c14f17f9b0'); path = fetch(mid)
    f = ifcopenshell.open(path)
    gids = ['2C1YkKCh1E$B4hqOlfdFxD', '2C1YkKCh1E$B4hqOlfdFxB']
    sp = {}
    try:
        body = s3.get_object(Bucket=B, Key=f'{ST}/ifc/detail/{mid}.v6.step_parts.jsonl.gz')['Body'].read()
        for l in gzip.decompress(body).decode().splitlines():
            r = json.loads(l); sp[r.get('pid')] = r
    except Exception as e:
        sp = {'_err': str(e)}
    s = ifcopenshell.geom.settings()
    res = []
    vu = None
    try:
        vu = float(ifcopenshell.util.unit.calculate_unit_scale(f, 'VOLUMEUNIT'))
    except Exception as e:
        vu = str(e)
    for g in gids:
        pr = f.by_guid(g)
        sh = ifcopenshell.geom.create_shape(s, pr)
        V = sh.geometry.verts; F = sh.geometry.faces; vol = 0.0
        for i in range(0, len(F), 3):
            a, b, c = F[i], F[i + 1], F[i + 2]
            ax, ay, az = V[3 * a:3 * a + 3]; bx, by_, bz = V[3 * b:3 * b + 3]; cx, cy, cz = V[3 * c:3 * c + 3]
            vol += (ax * (by_ * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by_ * cx)) / 6.0
        q = {}
        for rel in pr.IsDefinedBy or []:
            if rel.is_a('IfcRelDefinesByProperties'):
                pd = rel.RelatingPropertyDefinition
                if pd.is_a('IfcElementQuantity'):
                    for qq in pd.Quantities:
                        if qq.is_a('IfcQuantityVolume') or qq.is_a('IfcQuantityLength') or qq.is_a('IfcQuantityArea'):
                            q[f'{pd.Name}.{qq.Name}'] = qq[3]
        rep = [it.is_a() for r in pr.Representation.Representations for it in r.Items]
        res.append({'gid': g, 'name': pr.Name, 'kernel_volume_mm3': round(abs(vol) * 1e9, 1), 'quantities_raw': q,
                    'step_part': {k: sp.get(g, {}).get(k) for k in ('volume', 'solids', 'valid', 'faces', 'bbox')} if isinstance(sp, dict) else None,
                    'rep_items': rep})
    return {'id': mid, 'volume_unit_m3_per_file_unit': vu, 'columns': res}


def precision():
    mid = full('e7f6f3e68d0ed451'); path = fetch(mid)
    sk = info[mid]['step_key']
    stp = os.path.join(P, 'e7f6.step'); s3.download_file(B, sk, stp)
    txt = open(stp, errors='replace').read()
    pts = [tuple(float(x) for x in m.group(1).split(',')) for m in re.finditer(r"CARTESIAN_POINT\('[^']*',\(([^)]*)\)\)", txt)]
    big = [p for p in pts if max(abs(x) for x in p) > 1e8]
    grid10 = sum(1 for p in big if all(abs(x - round(x / 10.0) * 10.0) < 1e-6 for x in p if abs(x) > 1e9))
    src = open(path, errors='replace').read()
    spts = [tuple(float(x) for x in m.group(1).split(',')) for m in re.finditer(r"IFCCARTESIANPOINT\(\(([^)]*)\)\)", src)]
    return {'id': mid, 'step_key': sk, 'step_points': len(pts), 'step_points_gt_1e8mm': len(big),
            'step_points_on_10mm_grid_(coords>1e9)': grid10, 'step_point_examples': big[:6],
            'source_points': len(spts), 'source_point_examples_large': [p for p in spts if max(abs(x) for x in p) > 1e5][:6],
            'step_header': txt[:600]}


def oom():
    mid = full('2bcccd9a54ff28c3'); path = fetch(mid)
    kit = os.path.join(P, 'kit'); os.makedirs(kit, exist_ok=True)
    s3c = boto3.session.Session().client('s3', region_name='ap-south-1')
    conv = os.path.join(kit, 'ifc2step6.py')
    s3c.download_file('annotationprod', 'cad-disk-extract/_control/z3conv/ifc/ifc2step6.py', conv)
    res = {}
    def tree_rss(root):
        kids = collections.defaultdict(list)
        for d in os.listdir('/proc'):
            if d.isdigit():
                try:
                    pp = int(open(f'/proc/{d}/stat').read().rsplit(')', 1)[1].split()[1]); kids[pp].append(int(d))
                except Exception:
                    pass
        tot = 0; st = [root]
        while st:
            x = st.pop(); st.extend(kids.get(x, []))
            try:
                for line in open(f'/proc/{x}/status'):
                    if line.startswith('VmRSS:'):
                        tot += int(line.split()[1]) << 10
            except Exception:
                pass
        return tot
    for tag, extra in (('verify', []), ('no_verify', ['--no-verify'])):
        out = os.path.join(P, f'oom_{tag}.step'); log = os.path.join(P, f'oom_{tag}.log')
        cmd = ['/opt/conv/env/bin/python', conv, path, out, '--mode', 'hybrid', '--prec', '2', '--threads', '2'] + extra
        t0 = time.time(); peak = 0; killed = None; phases = []
        with open(log, 'w') as lf:
            p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=dict(os.environ, DEFLECTION='0.005', ANG_DEFLECTION='0.6'))
            while p.poll() is None:
                r = tree_rss(p.pid); peak = max(peak, r)
                phases.append([round(time.time() - t0), round(r / 2**30, 2)])
                if r > (60 << 30):
                    killed = 'tree RSS > 60 GB'; subprocess.run(['pkill', '-9', '-P', str(p.pid)]); p.kill(); break
                if time.time() - t0 > 1500:
                    killed = 'timeout 1500 s'; subprocess.run(['pkill', '-9', '-P', str(p.pid)]); p.kill(); break
                time.sleep(1)
            p.wait()
        st = {}
        try:
            st = json.load(open(out + '.stats.json'))
        except Exception:
            pass
        lg = open(log, errors='replace').read()
        res[tag] = {'rc': p.returncode, 'killed': killed, 'sec': round(time.time() - t0, 1), 'peak_tree_rss_gb': round(peak / 2**30, 2),
                    'rss_trace_every_10s': phases[::10][:120], 'log_tail': lg[-2500:],
                    'stats': {k: st.get(k) for k in ('parts', 'peak_rss_mb', 'levels', 'tags', 'verify', 'faces', 'out_bytes', 'transcode_products', 'tess_products', 'total_sec')}}
    return {'id': mid, 'size': os.path.getsize(path), 'runs': res}


for name, fn in (('absurd_746974a2', lambda: absurd('746974a288646288')), ('absurd_4efa1dc5', lambda: absurd('4efa1dc5f109c13f')),
                 ('hss_3a5129c1', hss), ('precision_e7f6f3e6', precision), ('oom_2bcccd9a', oom)):
    if len(sys.argv) > 1 and name.split('_')[0] not in sys.argv[1].split(','):
        continue
    t0 = time.time()
    try:
        OUT[name] = fn()
    except Exception as e:
        OUT[name] = {'error': f'{type(e).__name__}: {str(e)[:300]}', 'trace': traceback.format_exc()[-1200:]}
    OUT[name]['_sec'] = round(time.time() - t0, 1)
    json.dump(OUT, open(os.path.join(W, 'proofs.json'), 'w'), default=str, indent=1)
    s3.upload_file(os.path.join(W, 'proofs.json'), B, OUTK + '/proofs.json')
    print(name, 'done', OUT[name].get('_sec'), flush=True)
