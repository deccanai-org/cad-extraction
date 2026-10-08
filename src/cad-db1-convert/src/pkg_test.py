import os, json, sys, importlib
os.environ['PKG_SOURCES'] = 'db1'
sys.path.insert(0, 'src'); import pkg_step as P
P.DEST = 'cad-disk-extract/_control/packaging/test/main'; P.STATE = 'cad-disk-extract/_control/packaging/test/state'
s3 = P.s3(); B = P.B
pre2 = f'{P.DEST}/2d/TESTPROJ/'
# a 2d project that already went through the IFC pass shape (flat conversions) + one db1 model
man = [{"project_id": "TESTPROJ", "relpath": "model/db1/Foo.db1", "modality": "db1", "role": "steel_model", "bytes": 3, "source_key": "x"},
       {"project_id": "TESTPROJ", "relpath": "model/step/Foo.step", "modality": "step", "role": "steel_model", "bytes": 3,
        "converted_from": "model/ifc/Foo.ifc", "converter": "ifc2step5.py --mode hybrid --prec 2"},
       {"project_id": "TESTPROJ", "relpath": "model/step/Native.step", "modality": "step", "role": "steel_model", "bytes": 3}]
s3.put_object(Bucket=B, Key=pre2 + 'manifest.jsonl', Body='\n'.join(json.dumps(r) for r in man).encode())
s3.put_object(Bucket=B, Key=pre2 + 'project.json', Body=json.dumps({"id": "TESTPROJ", "route": "2d", "slots": {"model_step": 2}, "missing": ["model_step"],
              "conversions": {"step_added": 1, "by_converter": {"ifc2step5.py": 1}, "added_at": "t0"}}).encode())
for k in ('model/db1/Foo.db1', 'model/step/Foo.step', 'model/step/Native.step', 'drawings/a.pdf'):
    s3.put_object(Bucket=B, Key=pre2 + k, Body=b'abc')
src_step = 'cad-disk-extract/_control/packaging/test/src/db1out.stp'; s3.put_object(Bucket=B, Key=src_step, Body=b'ISO-10303-21;')
plan = dict(project='TESTPROJ', route='2d', prefix=pre2, move_to_3d=True,
            adds=[dict(name='Foo-abc123.step', out_key=src_step, bytes=13, converted_from='model/db1/Foo.db1', converter='db1dec+db1step (db1-2026-09-25c) -> ifc2step5.py --mode hybrid --prec 2')])
print('apply ->', P.apply_one(plan))
pre3 = f'{P.DEST}/3d/TESTPROJ/'
print('3d objects', sorted(o['Key'][len(pre3):] for o in P.list_keys(pre3)))
print('2d left', len(P.list_keys(pre2)))
pj = json.loads(s3.get_object(Bucket=B, Key=pre3 + 'project.json')['Body'].read())
print('project.json', {k: pj.get(k) for k in ('route', 'slots', 'missing', 'conversions', 'model_step_by_source', 'files')})
rows = [json.loads(l) for l in s3.get_object(Bucket=B, Key=pre3 + 'manifest.jsonl')['Body'].read().decode().splitlines()]
print('step rows', [(r['relpath'], r.get('step_source'), r.get('converted_from')) for r in rows if r['relpath'].startswith('model/step/')])
# cleanup scratch
for o in P.list_keys('cad-disk-extract/_control/packaging/test/'): s3.delete_object(Bucket=B, Key=o['Key'])
print('cleaned', len(P.list_keys('cad-disk-extract/_control/packaging/test/')))
