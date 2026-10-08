#!/usr/bin/env python3
"""offline self-test of the pkg-2026-10-02d patch (no S3 writes): STEP-content dedup in plan_project, duplicate-row merge,
ledger attach, primary_map decisions with a fake adapter"""
import sys, json, collections
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/z3conv/package')
import pkgcore as pc, pkg

class FakeAd:
    disk = 'Zenitude-data-3'
    def __init__(self, man):
        self.man = man                                  # pid -> [file rows]
    def files(self, proj):
        return self.man[proj['project_id']]
    def resolve(self, proj, items):
        for it in items:
            if 'nested.rar!' in it['source_path']:
                it['src_key'] = None; it['src_how'] = 'unresolved:no_key'
            else:
                it['src_key'] = 'k/' + it['source_path']; it['src_how'] = 'data3'
    def project_ref(self, a):
        tag = (a[len('Zenitude-data-3/'):] if a.startswith('Zenitude-data-3/') else a).replace('/', '_')
        return {'project_id': pc.project_id(self.disk, tag), 'tag': tag, 'source_key': a, 'kind': 'archive', 'job_id': tag, 'size': 1,
                'source_prefix': a + ' :: '}
    def project_of(self, a):
        return self.project_ref(a)['project_id']

ok = True
def check(name, cond):
    global ok
    print(('PASS ' if cond else 'FAIL ') + name); ok &= bool(cond)

# 1. two models, same STEP bytes (etag), different sources -> one model/step file, the second attached
A = 'Zenitude-data-3/P/A.7z'
ad = FakeAd({pc.project_id('Zenitude-data-3', 'P_A.7z'): [
    {'path': 'x/2306_ S21.ifc', 'size': 80727, 'sha256': 'a' * 64, 'key': 'cad-disk-extract/zenitude-data-3/extracted/x', 'dedup': None},
    {'path': 'x/2306_S21.ifc', 'size': 80730, 'sha256': 'b' * 64, 'key': 'cad-disk-extract/zenitude-data-3/extracted/y', 'dedup': None}]})
proj = ad.project_ref(A)
m1 = {'model_key': 'Z:ifc:m1', 'id': 'm1', 'pipeline': 'ifc', 'source_sha256': 'a' * 64, 'source_paths': [(A, 'x/2306_ S21.ifc')], 'step_key': 's/m1.step'}
m2 = {'model_key': 'Z:ifc:m2', 'id': 'm2', 'pipeline': 'ifc', 'source_sha256': 'b' * 64, 'source_paths': [(A, 'x/2306_S21.ifc')], 'step_key': 's/m2.step'}
heads = {'s/m1.step': {'ETag': '"e1"', 'ContentLength': 94515}, 's/m2.step': {'ETag': '"e1"', 'ContentLength': 94515}}
plan = pc.plan_project(ad, proj, [m1, m2], [], step_heads=heads)
check('one STEP item for identical content', len(plan['steps']) == 1)
check('second model attached (also)', len(plan['steps'][0].get('also') or []) == 1 and plan['steps'][0]['also'][0]['model_id'] == 'm2')
# 2. duplicate existing rows merged; removal queued
ex = [{'relpath': 'model/step/a.step', 'modality': 'step', 'step_source': 'ifc', 'sha256': 'c' * 64, 'model_id': 'm1', 'step_key': 's/m1.step', 'converted_from': 'model/ifc/a.ifc'},
      {'relpath': 'model/step/b.step', 'modality': 'step', 'step_source': 'ifc', 'sha256': 'c' * 64, 'model_id': 'm2', 'step_key': 's/m2.step', 'converted_from': 'model/ifc/b.ifc'}]
rec = {'removal_objects': []}
out = pc._merge_dup_steps(ex, rec)
check('duplicate row merged', len(out) == 1 and out[0].get('also_model_ids') == ['m2'] and out[0].get('also_converted_from') == ['model/ifc/b.ifc'])
check('duplicate object queued', rec['removal_objects'] and rec['removal_objects'][0]['relpath'] == 'model/step/b.step')
# 3. ledger places the attached model
lp = pc.ledger_part({'project_id': 'P', 'disk': 'Zenitude-data-3'}, out, {'ok': True})
check('ledger has both models', set(lp['placements']) == {'Zenitude-data-3:ifc:m1', 'Zenitude-data-3:ifc:m2'})
# 4. primary map: stored copy wins; pointer-only -> tie-break avoids library / (n) copies
L = 'Zenitude-data-3/Completed_Projects_Data/000_Technical Library7_Zip Jobs/MT20_023 (Issaquah).7z'
C = 'Zenitude-data-3/Completed_Projects_Data/0102_Lundahl LIC/MT20_023 (Issaquah).7z'
pidL = ad.project_ref(L)['project_id']; pidC = ad.project_ref(C)['project_id']
ad2 = FakeAd({pidL: [{'path': 'm.ifc', 'key': 'prior:sha256:1', 'dedup': 'prior', 'size': 1, 'sha256': '1'}] * 1,
              pidC: [{'path': 'm.ifc', 'key': 'prior:sha256:1', 'dedup': 'prior', 'size': 1, 'sha256': '1'}, {'path': 'n', 'key': 'x', 'dedup': None, 'size': 1, 'sha256': '2'}]})
orig_get = pc.get_json; pc.get_json = lambda b, k: None
pm = pkg.primary_map(ad2, {'Z:ifc:q': {'model_key': 'Z:ifc:q', 'pipeline': 'ifc', 'source_paths': [(L, 'm.ifc'), (C, 'm.ifc')]}})
check('pointer-only: library copy loses', pm['Z:ifc:q']['primary'] == pidC and pm['Z:ifc:q']['why'] == 'tiebreak' and pm['Z:ifc:q']['also'] == [L])
X = 'Zenitude-data-3/Completed_Jobs_Data/Server12 Completed Jobs (2).zip'; Y = 'Zenitude-data-3/Completed_Jobs_Data/Other.zip'
pidX = ad.project_ref(X)['project_id']; pidY = ad.project_ref(Y)['project_id']
ad3 = FakeAd({pidX: [{'path': 'm.ifc', 'key': 'cad-disk-extract/zenitude-data-3/extracted/Completed_Jobs_Data_Server12 Completed Jobs (2).zip/m.ifc', 'dedup': None}],
              pidY: [{'path': 'm.ifc', 'key': 'cad-disk-extract/zenitude-data-3/extracted/Completed_Jobs_Data_Server12 Completed Jobs (2).zip/m.ifc', 'dedup': 'archive'},
                     {'path': 'n1', 'key': 'z', 'dedup': None}, {'path': 'n2', 'key': 'z', 'dedup': None}]})
pm3 = pkg.primary_map(ad3, {'Z:ifc:r': {'model_key': 'Z:ifc:r', 'pipeline': 'ifc', 'source_paths': [(X, 'm.ifc'), (Y, 'm.ifc')]}})
check('stored copy wins over tie-break (even a "(2)" archive with fewer files)', pm3['Z:ifc:r']['primary'] == pidX and pm3['Z:ifc:r']['why'] == 'stored_copy')
pc.get_json = orig_get
# 5. representative path chosen after resolving: the same content in a nested archive (unresolvable) and a plain path
R = 'Zenitude-data-3/P/R.7z'
adr = FakeAd({pc.project_id('Zenitude-data-3', 'P_R.7z'): [
    {'path': 'a/nested.rar!/x.pdf', 'size': 10, 'sha256': 'd' * 64, 'key': None, 'dedup': None},
    {'path': 'b/x.pdf', 'size': 10, 'sha256': 'd' * 64, 'key': 'cad-disk-extract/zenitude-data-3/extracted/z', 'dedup': None},
    {'path': 'm/model.ifc', 'size': 5, 'sha256': 'e' * 64, 'key': 'cad-disk-extract/zenitude-data-3/extracted/m', 'dedup': None}]})
mr = {'model_key': 'Z:ifc:mr', 'id': 'mr', 'pipeline': 'ifc', 'source_sha256': 'e' * 64, 'source_paths': [(R, 'm/model.ifc')], 'step_key': 's/mr.step'}
pr = pc.plan_project(adr, adr.project_ref(R), [mr], [], step_heads={'s/mr.step': {'ETag': '"e9"', 'ContentLength': 9}})
pdfs = [it for it in pr['items'] if it['channel'].startswith('drawings')]
check('resolvable path chosen as representative', len(pdfs) == 1 and pdfs[0]['source_path'].endswith('b/x.pdf') and pr['stats']['unresolved'] == 0)
# 6. update: a file an earlier run left unresolved is added once it resolves
exist = [{'relpath': 'model/step/model.step', 'modality': 'step', 'step_source': 'ifc', 'model_id': 'mr', 'step_key': 's/mr.step', 'etag_source': 'e9', 'bytes': 9, 'sha256': 'f' * 64},
         {'relpath': 'model/ifc/model.ifc', 'modality': 'ifc', 'sha256': 'e' * 64, 'bytes': 5}]
epj = {'unresolved_files': [{'path': R + ' :: b/x.pdf', 'bytes': 10, 'sha256': 'd' * 64}]}
pu = pc.plan_project(adr, adr.project_ref(R), [mr], [], step_heads={'s/mr.step': {'ETag': '"e9"', 'ContentLength': 9}}, existing=exist, existing_pj=epj)
check('update adds the newly resolvable file only', len(pu['items']) == 1 and pu['items'][0]['source_path'].endswith('b/x.pdf') and pu['unresolved_files'] == [])
print('ALL PASS' if ok else 'SOME FAILED')
