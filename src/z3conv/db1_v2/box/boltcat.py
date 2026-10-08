#!/usr/bin/env python3
"""Harvest Tekla's own bolt-assembly geometry from Tekla IFC exports (IfcMechanicalFastener 'Bolt assembly' + pset
'Tekla Bolt'/'Tekla Fastener'). Per bolt: the mapped representation's IfcExtrudedAreaSolid items along the bolt axis
(local +y in the Tekla export): head (polygon before the shank start), shank (circle d/2, depth L), washers (circles
outside the grip), nut (polygon after the grip), hole cylinders (circle = hole diameter). Output JSONL rows per (file,
standard, size, flags) with item lists; aggregate later.  boltcat.py KEYS_JSON OUT_JSONL [threads] [max_files]"""
import sys, os, re, json, time, threading, tempfile, concurrent.futures as cf, collections, random
import boto3, botocore
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1', config=botocore.config.Config(max_pool_connections=64, retries={'max_attempts': 8, 'mode': 'standard'}))

def poly_dims(prof):
    """arbitrary closed profile -> (kind, across_flats, across_corners)"""
    try:
        pts = [p.Coordinates for p in prof.OuterCurve.Points]
    except Exception:
        return ('arb', None, None)
    import math
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    r = [math.hypot(x, y) for x, y in zip(xs, ys)]
    n = len(set((round(x, 2), round(y, 2)) for x, y in zip(xs, ys)))
    return ('poly%d' % n, round(min(max(xs) - min(xs), max(ys) - min(ys)), 3), round(2 * max(r), 3))

def harvest(path):
    import ifcopenshell, ifcopenshell.util.element as ue, ifcopenshell.util.unit as uu
    f = ifcopenshell.open(path); sc = uu.calculate_unit_scale(f) * 1000.0
    hdr = str(f.header.file_name.originating_system) if f.header else ''
    groups = collections.defaultdict(lambda: {'n': 0, 'items': None, 'ex': None})
    for e in f.by_type('IfcMechanicalFastener'):
        ps = {}
        for k, v in ue.get_psets(e).items():
            if 'Bolt' in k or 'Fastener' in k: ps.update(v)
        std = ps.get('Bolt standard'); size = ps.get('Bolt size'); L = ps.get('Bolt length')
        key = (std, size, ps.get('Washer type'), ps.get('Nut type'), ps.get('Washer name'), ps.get('Nut name'))
        g = groups[json.dumps(key)]; g['n'] += 1
        if g['items'] is not None: continue
        try:
            it = e.Representation.Representations[0].Items[0]
            if not it.is_a('IfcMappedItem'): continue
            items = []
            for x in it.MappingSource.MappedRepresentation.Items:
                if not x.is_a('IfcExtrudedAreaSolid'): items.append({'type': x.is_a()}); continue
                p = x.SweptArea; pos = x.Position.Location.Coordinates
                ax = x.Position.Axis.DirectionRatios if x.Position.Axis else (0, 0, 1)
                rec = {'depth': round(x.Depth * sc, 3), 'pos': [round(c * sc, 3) for c in pos], 'axis': [round(c, 3) for c in ax]}
                if p.is_a('IfcCircleProfileDef'): rec.update(kind='circle', dia=round(2 * p.Radius * sc, 3))
                elif p.is_a('IfcArbitraryClosedProfileDef'):
                    k_, af, ac = poly_dims(p); rec.update(kind=k_, af=af and round(af * sc, 3), ac=ac and round(ac * sc, 3))
                else: rec.update(kind=p.is_a())
                items.append(rec)
            g['items'] = items
            g['ex'] = {'d': e.NominalDiameter and round(e.NominalDiameter * sc, 3), 'L': e.NominalLength and round(e.NominalLength * sc, 3), 'pset': {k: v for k, v in ps.items() if k != 'id'}}
        except Exception as ex:
            g['err'] = str(ex)[:100]
    return hdr, groups

def work(key):
    try:
        if s3.head_object(Bucket=B, Key=key)['ContentLength'] > (150 << 20): return None
        h = s3.get_object(Bucket=B, Key=key, Range='bytes=0-2999')['Body'].read()
        if b'Tekla' not in h and b'TEKLA' not in h: return None
        with tempfile.NamedTemporaryFile(suffix='.ifc', dir='/opt/v2/tmp', delete=True) as tf:
            s3.download_file(B, key, tf.name)
            import subprocess
            n = subprocess.run(['grep', '-c', 'IFCMECHANICALFASTENER(', tf.name], capture_output=True, text=True).stdout.strip()
            if not n or n == '0': return {'key': key, 'fasteners': 0}
            hdr, groups = harvest(tf.name)
        return {'key': key, 'fasteners': sum(g['n'] for g in groups.values()), 'system': hdr[:120],
                'groups': [{'key': json.loads(k), **v} for k, v in groups.items()]}
    except Exception as e:
        return {'key': key, 'error': type(e).__name__ + ':' + str(e)[:100]}

if __name__ == '__main__':
    os.makedirs('/opt/v2/tmp', exist_ok=True)
    keys = json.load(open(sys.argv[1])); outp = sys.argv[2]
    th = int(sys.argv[3]) if len(sys.argv) > 3 else 16; mx = int(sys.argv[4]) if len(sys.argv) > 4 else 3000
    random.seed(11); random.shuffle(keys)
    n = withf = 0; t0 = time.time()
    with open(outp, 'w') as fo, cf.ThreadPoolExecutor(th) as ex:
        for r in ex.map(work, keys):
            n += 1
            if r is None: continue
            fo.write(json.dumps(r) + '\n'); fo.flush()
            if r.get('fasteners'): withf += 1
            if n % 100 == 0: print(n, withf, round(time.time() - t0), flush=True)
            if withf >= mx or time.time() - t0 > 4 * 3600: break
    print('DONE', n, withf, flush=True)
