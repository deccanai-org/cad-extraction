"""build_kits.py: reconstruct each z3-db1 code's decoder kit from S3 object versions of _control/z3conv/db1/ (versioned bucket).
kit(T) = for every decoder file the newest version with LastModified <= T + 5 s. Only small decoder files are copied; the large
single-version files (tekla_profiles.json, bolt_catalog.json, layouts.json, db1dec.py) are fetched once on the box (latest == only version)."""
import json, subprocess, os, datetime as dt
V = json.load(open('/tmp/aud_db1/vers/versions.json'))['Versions']
PFX = 'cad-disk-extract/_control/z3conv/db1/'
SNAP = {  # label -> worker/deploy time (UTC) of the code (worker.py CODE constant at that time)
    'b0': '2026-10-01T21:02:24', 'b1': '2026-10-01T21:15:37', 'b2': '2026-10-01T21:30:51', 'c': '2026-10-01T21:43:14',
    'c2': '2026-10-01T21:47:27', 'd': '2026-10-01T21:50:45', 'e': '2026-10-01T21:52:45', 'f': '2026-10-01T22:11:08',
    'g': '2026-10-01T22:37:58', 'h': '2026-10-01T22:47:26', 'i': '2026-10-01T23:12:18'}
SMALL = ('db1step.py', 'db1bolts.py', 'db1old.py', 'db1prof.py', 'convert_one.py', 'tekla_profiles_overlay.json')
env = dict(os.environ, AWS_PROFILE='annotationprod-publish')
man = {}
for lab, t in SNAP.items():
    T = dt.datetime.fromisoformat(t + '+00:00') + dt.timedelta(seconds=5)
    d = os.path.join('kits', lab); os.makedirs(d, exist_ok=True); man[lab] = {}
    for fn in SMALL:
        c = [x for x in V if x['Key'] == PFX + fn and dt.datetime.fromisoformat(x['LastModified'].replace('Z', '+00:00')) <= T]
        if not c:
            continue
        x = max(c, key=lambda x: x['LastModified'])
        man[lab][fn] = {'version': x['VersionId'], 'modified': x['LastModified'], 'size': x['Size']}
        out = os.path.join(d, fn)
        if not (os.path.exists(out) and os.path.getsize(out) == x['Size']):
            r = subprocess.run(['aws', 's3api', 'get-object', '--bucket', 'annotationprod', '--key', x['Key'], '--version-id', x['VersionId'], out],
                               env=env, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
json.dump({'snapshots': SNAP, 'files': man}, open('kits/manifest.json', 'w'), indent=1)
for lab in SNAP:
    print(lab, {k: v['size'] for k, v in man[lab].items()})
