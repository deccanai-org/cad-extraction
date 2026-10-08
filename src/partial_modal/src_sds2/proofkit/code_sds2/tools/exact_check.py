#!/usr/bin/env python3
"""Build check of faceted parts (OpenCASCADE side; exact.py runs it in its own process, as IfcOpenShell and build123d
carry different OpenCASCADE builds): every record of IN.jsonl is built exactly as steelbuild builds an 'exact' part and
compared with the polyhedron its faces state (divergence theorem, stepfacets.mass): one valid solid per closed body,
the same volume (BUILD_VOL_REL) and centroid (BUILD_CEN_MM). Writes {part_id: '' | reason} to OUT.json.
usage: exact_check.py IN.jsonl OUT.json [--jobs N]"""
import argparse, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'kit'))

BUILD_VOL_REL = 1e-5     # the solid OpenCASCADE builds through the faces must be the polyhedron they state (seen on
BUILD_CEN_MM = 1e-3      # sound IFC faces: <= 5e-7 and <= 5e-5 mm; a self-overlapping face: volume of opposite sign)


def check(rec):
    import steelbuild, stepfacets
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    try:
        bodies = [s for s in rec['solids'] if not steelbuild._is_sheet(s['faces'])]
        S = steelbuild.exact_part(rec)
        if not S or len(S) != len(bodies):
            return rec['part_id'], 'built %d solids for %d bodies' % (len(S), len(bodies))
        if not all(s.is_valid for s in S):
            return rec['part_id'], 'built solid not valid'
        V, Mo = 0.0, np.zeros(3)
        for s in S:
            g = GProp_GProps()
            BRepGProp.VolumeProperties_s(s.wrapped, g)
            c = g.CentreOfMass()
            V += g.Mass()
            Mo += g.Mass() * np.array([c.X(), c.Y(), c.Z()])
        as_mass = [{'outer': [[np.asarray(lp, float) for lp in fc] for fc in s['faces']],
                    'voids': [[[np.asarray(lp, float) for lp in fc] for fc in v] for v in s.get('voids', [])]} for s in bodies]
        vd, cd, _, _ = stepfacets.mass(as_mass)
        if V <= 0 or abs(V - vd) > BUILD_VOL_REL * abs(vd):
            return rec['part_id'], 'built volume %.6g vs faces %.6g' % (V, vd)
        if np.linalg.norm(Mo / V - cd) > BUILD_CEN_MM:
            return rec['part_id'], 'built centroid %.2e mm off the faces' % np.linalg.norm(Mo / V - cd)
        return rec['part_id'], ''
    except Exception as e:
        return rec['part_id'], 'build error ' + type(e).__name__


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp')
    ap.add_argument('out')
    ap.add_argument('--jobs', type=int, default=os.cpu_count())
    a = ap.parse_args()
    recs = [json.loads(l) for l in open(a.inp) if l.strip()]
    res = {}
    if recs:
        from concurrent.futures.process import BrokenProcessPool
        try:
            with ProcessPoolExecutor(min(a.jobs, len(recs))) as ex:
                res = dict(ex.map(check, recs, chunksize=4 if len(recs) > 64 else 1))
        except BrokenProcessPool:               # a native crash: check one by one, the crashing part fails
            for r in recs:
                try:
                    with ProcessPoolExecutor(1) as ex:
                        res.update(dict(ex.map(check, [r])))
                except BrokenProcessPool:
                    res[r['part_id']] = 'native crash while building'
    json.dump(res, open(a.out, 'w'), indent=0, sort_keys=True)
    print(len(res), 'checked', sum(1 for v in res.values() if not v), 'ok')


if __name__ == '__main__':
    main()
