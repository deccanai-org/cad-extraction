#!/usr/bin/env python3
"""One product through the ifcopenshell kernel under several settings, each in a child process with a hard address-space
cap and a timeout -> seconds, peak RSS, faces, volume (or the failure). Finds which stage makes a product explode.
usage: variant_test.py CONV.py IFC GUID [--cap-gb 12] [--timeout 120]"""
import sys, os, json, time, subprocess, argparse, resource
ap = argparse.ArgumentParser()
ap.add_argument('conv'); ap.add_argument('ifc'); ap.add_argument('gid')
ap.add_argument('--cap-gb', type=float, default=12); ap.add_argument('--timeout', type=int, default=120)
ap.add_argument('--child', default=None)
a = ap.parse_args()
VARIANTS = {
    'poly_dev3': {'tri': 'poly'},
    'tri_mesh': {'tri': 'tri'},
    'poly_no_openings': {'tri': 'poly', 'set': {'disable-opening-subtractions': True}},
    'poly_bool2d_off': {'tri': 'poly', 'set': {'boolean-attempt-2d': False}},
    'tri_bool2d_off': {'tri': 'tri', 'set': {'boolean-attempt-2d': False}},
    'poly_no_weld': {'tri': 'poly', 'set': {'weld-vertices': False}},
}
if a.child:
    import importlib.util
    spec = importlib.util.spec_from_file_location('conv', a.conv); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
    import ifcopenshell, ifcopenshell.geom
    os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
    v = VARIANTS[a.child]
    f = ifcopenshell.open(a.ifc); p = f.by_guid(a.gid)
    s, applied, m = M.kernel_settings(v['tri'])
    for k, val in (v.get('set') or {}).items():
        try:
            s.set(k, val)
        except Exception as e:
            print(json.dumps({'setting_error': k, 'err': str(e)[:100]})); sys.exit(3)
    t = time.time()
    sh = ifcopenshell.geom.create_shape(s, p)
    V, faces, iids = M.kernel_geometry(sh.geometry, m)
    bp = M.build_part(M.kernel_pieces(f, V, faces, iids), M.Repair(2))
    vol = sum(x.vol for x in bp[1]) if bp not in (None, 'corrupt') else None
    print(json.dumps({'sec': round(time.time() - t, 2), 'faces': len(faces), 'verts': len(V), 'solids': len(bp[1]) if vol is not None else None,
                      'mesh_vol_mm3': round(vol, 2) if vol is not None else None,
                      'maxrss_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss >> 10}))
    sys.exit(0)
cap = int(a.cap_gb * (1 << 30))
for name in VARIANTS:
    t = time.time()
    def lim():
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    try:
        r = subprocess.run([sys.executable, __file__, a.conv, a.ifc, a.gid, '--child', name], capture_output=True, text=True,
                           timeout=a.timeout, preexec_fn=lim)
        out = (r.stdout.strip().splitlines() or [''])[-1]
        res = {'variant': name, 'rc': r.returncode, 'wall': round(time.time() - t, 1)}
        try:
            res.update(json.loads(out))
        except Exception:
            res['tail'] = (r.stderr or '')[-300:]
    except subprocess.TimeoutExpired:
        res = {'variant': name, 'timeout_s': a.timeout}
    print(json.dumps(res), flush=True)
