#!/usr/bin/env python3
"""offline test of z3conv/scan/zcensus.py with a fake S3 (manifests, data-3 index, redo lists)"""
import sys, os, io, json, gzip, shutil, hashlib
sys.argv = ['zcensus.py', 'zentitude-data-4']
os.environ['CENSUS_WORK'] = '/tmp/z3c/zcensus_test'; os.environ['CENSUS_PROCS'] = '2'
shutil.rmtree('/tmp/z3c/zcensus_test', ignore_errors=True)
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/z3conv/scan')
import zcensus as zc

R = zc.ROOT; Z3 = zc.Z3
S = {}


def gz(rows):
    return gzip.compress(''.join(json.dumps(r) + '\n' for r in rows).encode())


sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
m1 = [{'path': 'a/x.ifc', 'size': 100, 'sha256': sha('i1'), 'key': f'{R}/extracted/a/x.ifc'},
      {'path': 'a/y.ifc', 'size': 200, 'sha256': sha('i2'), 'key': 'disk12:sha256:' + sha('i2')},
      {'path': 'a/m/model.db1', 'size': 50, 'sha256': sha('d1'), 'key': 'sha256:' + sha('d1')},
      {'path': 'a/m/xslib.db1', 'size': 5, 'sha256': sha('x1'), 'key': ''},
      {'path': 'a/job/main/jsetup', 'size': 9, 'sha256': sha('js'), 'key': f'{R}/extracted/a/job/main/jsetup'},
      {'path': 'a/job/main/job_mtrl', 'size': 9, 'sha256': sha('jm'), 'key': 'disk12:sha256:x'},
      {'path': 'a/job/mem/mem_idx', 'size': 9, 'sha256': sha('mi'), 'key': 'disk12:sha256:y'},
      {'path': 'a/job/mem/1', 'size': 99, 'sha256': sha('m1'), 'key': 'disk12:sha256:z'},
      {'path': 'a/broken.ifc', 'size': 1}]
m2 = [{'path': 'b/x2.ifc', 'size': 100, 'sha256': sha('i1'), 'key': 'sha256:' + sha('i1')},
      {'path': 'b/z.ifc', 'size': 300, 'sha256': sha('i3'), 'key': f'{R}/extracted/b/z.ifc'}]
S[f'{R}/_state/manifests/j1.jsonl.gz'] = gz(m1)
S[f'{R}/_state/manifests/j2.jsonl.gz'] = gz(m2)
fl = sorted([['main/jsetup', 9, sha('js'), ''], ['main/job_mtrl', 9, sha('jm'), ''], ['mem/mem_idx', 9, sha('mi'), ''], ['mem/1', 99, sha('m1'), '']])
fpc = hashlib.sha256('\n'.join(sorted(f'{r[0]}\t{r[2]}' for r in fl)).encode()).hexdigest()
idx = [{'pipeline': 'ifc', 'id': sha('i1'), 'class': 1}, {'pipeline': 'ifc', 'id': sha('i3'), 'class': 2},
       {'pipeline': 'sds2', 'id': fpc[:24], 'class': 2}]
S[f'{Z3}/_state/conv/index.jsonl.gz'] = gz(idx)
S[f'{Z3}/_state/conv/ifc/redo.json'] = json.dumps([sha('i3')]).encode()
S[f'{R}/_control/conv/ifc/jobs.json'] = json.dumps([{'id': sha('i2'), 'sha256': sha('i2')}]).encode()


class Body(io.BytesIO):
    pass


class Pg:
    def paginate(self, Bucket, Prefix):
        yield {'Contents': [{'Key': k, 'Size': len(v)} for k, v in sorted(S.items()) if k.startswith(Prefix)]}


class C:
    def download_file(self, b, k, path): open(path, 'wb').write(S[k])
    def get_object(self, Bucket, Key):
        if Key not in S: raise KeyError(Key)
        return {'Body': Body(S[Key])}
    def get_paginator(self, n): return Pg()
    def put_object(self, Bucket, Key, Body): S[Key] = Body
    def upload_file(self, path, b, k): S[k] = open(path, 'rb').read()
    def list_objects_v2(self, **kw): return {}


zc._c["c"] = C()
import multiprocessing; multiprocessing.set_start_method("fork", force=True)
zc.main()
c = json.loads(S[f'{R}/_state/conv2/scan/census.json'])
ok = True
def check(n, v):
    global ok
    print(('PASS ' if v else 'FAIL ') + n); ok &= bool(v)
check('ifc distinct 3', c['ifc']['distinct'] == 3)
check('ifc actions', c['ifc']['by_action'] == {'reused_final': 1, 'reused_open_rerun': 1, 'new': 1})
check('ifc new is disk12-only and in old jobs', c['ifc']['new_key_kinds'] == {'disk12_only': 1} and c['ifc']['new_vs_old_data4_jobs'] == {'in_old_data4_jobs': 1})
check('db1: xslib excluded, 1 new', c['db1']['distinct'] == 1 and c['db1']['by_action'] == {'new': 1})
check('sds2 matched data-3 by fpc', c['sds2']['by_action'] == {'reused_final': 1})
check('rows without sha counted', c['model_rows_without_sha'] == 1)
check('parts.tgz uploaded', f'{R}/_state/conv2/scan/parts.tgz' in S)
print('ALL PASS' if ok else 'SOME FAILED')

# ---- job builder on the same fake bucket / work dir
S['cad-disk-extract/zentitude-data-4/_control/jobs.json'] = json.dumps([{'id': 'j1', 'key': 'Zentitude-data-4/A.7z'}, {'id': 'j2', 'key': 'Zentitude-data-4/B.7z'}]).encode()
S['cad-disk-extract/zentitude-data-4/_state/sha/' + sha('d1')[:2] + '/' + sha('d1')] = b'cad-disk-extract/zentitude-data-4/extracted/a/m/model.db1'
class C2(C):
    def get_object(self, Bucket, Key):
        if Bucket == 'annotationprod':
            rows = [{'sha256': sha('i2'), 'key': 'cad-disk-extract/dataset/main/3d/P/y.ifc', 'bytes': 200, 'proof': 's3_sha256'}]
            return {'Body': Body(gzip.compress(''.join(json.dumps(r) + '\n' for r in rows).encode()))}
        return C.get_object(self, Bucket, Key)
zc._c['c'] = C2()
import zjobs
zjobs.main()
js = json.loads(S['cad-disk-extract/zentitude-data-4/_state/conv2/scan/jobs_summary.json'])
ij = json.loads(S['cad-disk-extract/zentitude-data-4/_state/conv2/ifc/jobs.json'])
dj = json.loads(S['cad-disk-extract/zentitude-data-4/_state/conv2/db1/jobs.json'])
check('ifc: 1 job, resolved from the disk12 map', len(ij) == 1 and ij[0]['input_from'] == 'disk12_map' and ij[0]['paths'][0].startswith('Zentitude-data-4/A.7z :: '))
check('ifc reuse actions', js['ifc']['actions'] == {'reuse_disk': 2, 'convert': 1} and js['ifc']['reuse_from'] == {'zenitude-data-3': 2})
check('db1: marker resolved', len(dj) == 1 and dj[0]['input_from'] == 'disk_marker' and dj[0]['input_key'].endswith('model.db1'))
check('sds2: reused, no job', js['sds2']['jobs'] == 0 and js['sds2']['actions'] == {'reuse_disk': 1})
print('ALL PASS' if ok else 'SOME FAILED')
