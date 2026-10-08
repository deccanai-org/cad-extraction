#!/usr/bin/env python3
"""IFC -> per-product geometry digest (cached), the reference side of sds2_ifc_recall.py.

For every IfcProduct with a body (ifcopenshell geometry iterator, world coordinates, converted to millimetres):
guid, IFC class, Name (SDS2 exports: member / material piece mark), ObjectType / Description (SDS2: section or
'Plate'), Tag, the containing IfcElementAssembly name, vertex count, PCA axes, extents along them, PCA-box centre and
the axis-aligned bbox. The same PCA-box statistics are computed on the STEP side (stepidx), so the two can be compared.
usage: python ifc_products.py <file.ifc> -o digest.npz [--threads 4]
"""
import os, sys, time, json, argparse, collections
import numpy as np
import ifcopenshell, ifcopenshell.geom


def pca_stats(v):
    mu = v.mean(0)
    D = v - mu
    C = D.T @ D / max(len(v), 1)
    w, V = np.linalg.eigh(C)
    V = V[:, ::-1]
    Q = D @ V
    qmin, qmax = Q.min(0), Q.max(0)
    return V, qmax - qmin, mu + V @ ((qmin + qmax) / 2)


def digest(path, threads=4, log=print):
    t0 = time.time()
    f = ifcopenshell.open(path)
    schema = f.schema
    # length unit -> mm factor is handled by ifcopenshell (geometry in metres); record the declared unit
    units = []
    for u in f.by_type('IfcConversionBasedUnit') + f.by_type('IfcSIUnit'):
        try:
            if u.UnitType == 'LENGTHUNIT':
                units.append(u.Name if u.is_a('IfcConversionBasedUnit') else f"{u.Prefix or ''}{u.Name}")
        except Exception:
            pass
    hdr = f.header.file_name
    origin = getattr(hdr, 'originating_system', '') or ''
    assy = {}
    for rel in f.by_type('IfcRelAggregates'):
        try:
            parent = rel.RelatingObject
            if parent.is_a('IfcElementAssembly'):
                for ch in rel.RelatedObjects:
                    assy[ch.id()] = (parent.Name or '', parent.ObjectType or parent.Description or '')
        except Exception:
            pass
    t1 = time.time()
    s = ifcopenshell.geom.settings()
    s.set('use-world-coords', True)
    try:
        s.set('disable-opening-subtractions', True)
    except Exception:
        pass
    it = ifcopenshell.geom.iterator(s, f, threads)
    rows = []; C = []; E = []; A = []; BMIN = []; BMAX = []; NV = []
    if it.initialize():
        while True:
            sh = it.get()
            try:
                e = f.by_id(sh.id)
            except Exception:
                e = f.by_guid(sh.guid)
            v = np.asarray(sh.geometry.verts, float).reshape(-1, 3) * 1000.0
            if len(v):
                V, ext, cen = pca_stats(v)
                a = assy.get(e.id(), ('', ''))
                rows.append([e.GlobalId, e.is_a(), e.Name or '', getattr(e, 'ObjectType', '') or '', e.Description or '',
                             getattr(e, 'Tag', '') or '', a[0], a[1]])
                C.append(cen); E.append(ext); A.append(V); BMIN.append(v.min(0)); BMAX.append(v.max(0)); NV.append(len(v))
            if not it.next():
                break
    t2 = time.time()
    log(f'{os.path.basename(path)}: {schema}, units {units}, origin {origin!r}, {len(rows)} products with bodies; open {t1 - t0:.0f}s geom {t2 - t1:.0f}s')
    return {'rows': rows, 'center': np.array(C).reshape(-1, 3), 'ext': np.array(E).reshape(-1, 3), 'axes': np.array(A).reshape(-1, 3, 3),
            'bmin': np.array(BMIN).reshape(-1, 3), 'bmax': np.array(BMAX).reshape(-1, 3), 'nverts': np.array(NV),
            'meta': {'path': path, 'schema': schema, 'units': units, 'origin': origin, 'sec_open': round(t1 - t0, 1), 'sec_geom': round(t2 - t1, 1),
                     'size': os.path.getsize(path)}}


def save(d, out):
    np.savez_compressed(out, rows=np.array(d['rows'], dtype=object), center=d['center'], ext=d['ext'], axes=d['axes'],
                        bmin=d['bmin'], bmax=d['bmax'], nverts=d['nverts'], meta=np.array([json.dumps(d['meta'])], dtype=object))


def load(path):
    z = np.load(path, allow_pickle=True)
    return {'rows': z['rows'].tolist(), 'center': z['center'], 'ext': z['ext'], 'axes': z['axes'], 'bmin': z['bmin'], 'bmax': z['bmax'],
            'nverts': z['nverts'], 'meta': json.loads(z['meta'][0])}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('ifc'); ap.add_argument('-o', required=True); ap.add_argument('--threads', type=int, default=4)
    a = ap.parse_args()
    d = digest(a.ifc, a.threads)
    save(d, a.o)
    print(collections.Counter(r[1] for r in d['rows']).most_common())


if __name__ == '__main__':
    main()
