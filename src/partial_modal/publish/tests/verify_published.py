"""Read-only check of a published scripts/ tree (run on the Mac with AWS_PROFILE=bim):
    python3 publish/tests/verify_published.py --root cad-disk-extract/_state/pmp/fakepkg/ --pid PID --out DIR [--fixtures DIR]
Downloads <root><pid>/scripts/, then checks: scripts_manifest.jsonl lists exactly the files present (minus itself), every row's
bytes + sha256 match the downloaded content, shared rows have model_id null, each model folder holds one model_id, and
(optional) the content equals the local fixture trees."""
import argparse, hashlib, json, os, subprocess, sys
ap = argparse.ArgumentParser()
ap.add_argument('--root', required=True); ap.add_argument('--pid', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--fixtures', nargs='*', default=[])
a = ap.parse_args()
env = dict(os.environ, AWS_PROFILE=os.environ.get('AWS_PROFILE', 'bim'))
src = f's3://bim-proprietary-data/{a.root}{a.pid}/scripts/'
dst = os.path.join(a.out, 'scripts')
subprocess.run(['aws', 's3', 'sync', '--only-show-errors', '--delete', src, dst], check=True, env=env)
files = {}
for dp, dn, fn in os.walk(dst):
    for f in fn:
        p = os.path.join(dp, f)
        files['scripts/' + os.path.relpath(p, dst).replace(os.sep, '/')] = p
rows = [json.loads(x) for x in open(files.pop('scripts/scripts_manifest.jsonl'), encoding='utf-8')]
bad = []
paths = [r['path'] for r in rows]
if paths != sorted(paths): bad.append('manifest not sorted')
if set(paths) != set(files): bad.append(f'manifest vs tree: only in manifest {sorted(set(paths)-set(files))[:3]}, only in tree {sorted(set(files)-set(paths))[:3]}')
owner = {}
for r in rows:
    p = files.get(r['path'])
    if not p: continue
    data = open(p, 'rb').read()
    if len(data) != r['bytes'] or hashlib.sha256(data).hexdigest() != r['sha256']: bad.append(f'sha/bytes mismatch {r["path"]}')
    shared = r['path'].count('/') == 1
    if shared and r['model_id'] is not None: bad.append(f'shared row with model_id {r["path"]}')
    if not shared:
        mf = r['path'].split('/')[1]
        if owner.setdefault(mf, r['model_id']) != r['model_id']: bad.append(f'two models in {mf}')
    for k in ('source', 'code_version'):
        if not r.get(k): bad.append(f'{r["path"]}: empty {k}')
for fx in a.fixtures:   # local fixture scripts/ trees: their files must be published byte-identically
    for dp, dn, fn in os.walk(fx):
        for f in fn:
            lp = os.path.join(dp, f); rel = 'scripts/' + os.path.relpath(lp, fx).replace(os.sep, '/')
            if rel not in files or open(files[rel], 'rb').read() != open(lp, 'rb').read(): bad.append(f'fixture differs/missing {rel}')
print(json.dumps(dict(pid=a.pid, files=len(files), manifest_rows=len(rows), model_folders=owner, problems=bad), indent=1))
sys.exit(1 if bad else 0)
