#!/usr/bin/env python3
"""Pair every data-3 SDS2 job with (a) the NC1 / DSTV files and (b) the IFC exports found next to it, and list its STEP
outputs per converter label. Runs on the agent box after inv_scan.py.

Relation of a file to a job occurrence '<archive> :: <job root>' (same archive manifest only):
  inside_job    path starts with the job root
  sibling       path starts with the job root's parent folder (e.g. MT16_002 (X)/17.Others/<job>/ and .../17.Others/CNC/)
  same_project  same top folder, in an archive whose SDS2 roots, NC1 and IFC rows all sit under one top folder
  same_name     (IFC only) file stem equals / prefixes the job folder name (the previous agent's rule)
  same_archive  anything else in the archive (not used for checks)
Output: $W/inv/pairs.json (+ S3)
"""
import os, sys, json, gzip, re, time, collections
import boto3

B = 'bim-proprietary-data'; CB = 'annotationprod'
D3 = 'cad-disk-extract/zenitude-data-3'
RES = f'{D3}/_state/agentwork/sds2-recall-nc1'
W = os.environ.get('W', '/work/agentwork/sds2-recall-nc1')
INV = os.path.join(W, 'inv')
s3 = boto3.client('s3', region_name='ap-south-1')
ORDER = ['inside_job', 'sibling', 'same_name', 'same_project', 'same_archive']


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def norm(s):
    s = s.lower()
    s = re.sub(r'\.(ifc|ifczip|ifcxml)$', '', s)
    s = re.sub(r'[^a-z0-9]+', '', s)
    s = re.sub(r'(job|jb)$', '', s)
    return s


def rel_of(path, root, single_top):
    if path.startswith(root):
        return 'inside_job'
    r = root.rstrip('/')
    parent = r.rsplit('/', 1)[0] + '/' if '/' in r else ''
    if parent and path.startswith(parent):
        return 'sibling'
    top = root.split('/')[0]
    if single_top and '/' in root and path.split('/')[0] == top:
        return 'same_project'
    return 'same_archive'


def main():
    t0 = time.time()
    steps = json.load(open(os.path.join(INV, 'steps.json')))
    jobs = json.loads(s3.get_object(Bucket=CB, Key='cad-disk-extract/_control/move/z3/jobs.json')['Body'].read())
    a2m = collections.defaultdict(list)
    for j in jobs:
        a = j.get('key') or j.get('dir') or ''
        a2m[a].append(j['id'])
    sds = [json.loads(l) for l in gzip.open(os.path.join(INV, 'contents_sds2.jsonl.gz'), 'rt')]
    p = os.path.join(INV, 'contents_ifc.jsonl.gz')
    if not os.path.exists(p):
        s3.download_file(B, f'{D3}/_state/conv/scan/contents_ifc.jsonl.gz', p)
    ifcs = [json.loads(l) for l in gzip.open(p, 'rt')]
    nc1_keys = json.load(open(os.path.join(INV, 'nc1_keys.json'))) if os.path.exists(os.path.join(INV, 'nc1_keys.json')) else {}
    nc1 = collections.defaultdict(list)
    for l in gzip.open(os.path.join(INV, 'nc1_d3.jsonl.gz'), 'rt'):
        r = json.loads(l)
        if (r['path'] or '').lower().endswith('.nc1'):
            nc1[r['mid']].append((r['path'], r['size'], r['sha256']))
    ifc_by_m = collections.defaultdict(list)
    for c in ifcs:
        for pth in c['paths']:
            a, _, rp = pth.partition(' :: ')
            for mid in a2m.get(a, []):
                ifc_by_m[mid].append((rp, c))
    # top folders per manifest (SDS2 roots + NC1 + IFC rows)
    tops = collections.defaultdict(set)
    for r in sds:
        for pth in r.get('paths', []):
            a, _, root = pth.partition(' :: ')
            for mid in a2m.get(a, []):
                tops[mid].add(root.split('/')[0])
    for mid, rows in nc1.items():
        for pth, _, _ in rows:
            tops[mid].add(pth.split('/')[0])
    for mid, rows in ifc_by_m.items():
        for rp, _ in rows:
            tops[mid].add(rp.split('/')[0])
    out = {}
    nstat = collections.Counter()
    for r in sds:
        jid = r['id']
        best_nc1 = {}; best_ifc = {}
        for pth in r.get('paths', []):
            a, _, root = pth.partition(' :: ')
            jobname = root.rstrip('/').split('/')[-1]
            for mid in a2m.get(a, []):
                single = len(tops[mid]) == 1
                for path, size, sha in nc1.get(mid, []):
                    rel = rel_of(path, root, single)
                    if rel == 'same_archive':
                        continue
                    folder = path.rsplit('/', 1)[0]
                    e = best_nc1.get(sha)
                    if e is None or ORDER.index(rel) < ORDER.index(e['rel']):
                        best_nc1[sha] = {'sha256': sha, 'size': size, 'path': path, 'folder': folder, 'rel': rel, 'mid': mid,
                                         'key': nc1_keys.get(sha)}
                for rp, c in ifc_by_m.get(mid, []):
                    rel = rel_of(rp, root, single)
                    base = rp.rsplit('/', 1)[-1]
                    if rel in ('same_project', 'same_archive') and norm(base) and len(norm(base)) >= 4 and (
                            norm(base) == norm(jobname) or norm(jobname).startswith(norm(base)) or norm(base).startswith(norm(jobname))):
                        rel = 'same_name'
                    if rel == 'same_archive':
                        continue
                    e = best_ifc.get(c['sha256'])
                    if e is None or ORDER.index(rel) < ORDER.index(e['rel']):
                        best_ifc[c['sha256']] = {'sha256': c['sha256'], 'size': c['size'], 'path': f'{a} :: {rp}', 'rel': rel,
                                                 'input_key': c.get('input_key'), 'kind': c.get('kind')}
        st = steps.get(jid, {})
        if not best_nc1 and not best_ifc:
            continue
        sets = collections.defaultdict(lambda: {'n': 0, 'rel': None})
        for e in best_nc1.values():
            s_ = sets[e['folder']]; s_['n'] += 1
            if s_['rel'] is None or ORDER.index(e['rel']) < ORDER.index(s_['rel']):
                s_['rel'] = e['rel']
        out[jid] = {'id': jid, 'name': (r.get('paths') or [''])[0].split(' :: ')[-1].rstrip('/').split('/')[-1],
                    'paths': r.get('paths', [])[:4], 'model_bytes': r.get('model_bytes'), 'action': r.get('action'),
                    'steps': st, 'nc1_files': sorted(best_nc1.values(), key=lambda e: e['path']),
                    'nc1_sets': [{'folder': k, **v} for k, v in sorted(sets.items(), key=lambda kv: -kv[1]['n'])],
                    'ifc': sorted(best_ifc.values(), key=lambda e: (ORDER.index(e['rel']), -e['size']))}
        nstat['jobs_with_nc1'] += bool(best_nc1); nstat['jobs_with_ifc'] += bool(best_ifc)
        nstat['jobs_with_nc1_and_step'] += bool(best_nc1 and st); nstat['jobs_with_ifc_and_step'] += bool(best_ifc and st)
        for lab in st:
            nstat[f'step_{lab}_with_nc1'] += bool(best_nc1); nstat[f'step_{lab}_with_ifc'] += bool(best_ifc)
    json.dump(out, open(os.path.join(INV, 'pairs.json'), 'w'))
    s3.upload_file(os.path.join(INV, 'pairs.json'), B, f'{RES}/inv/pairs.json')
    rels = collections.Counter(min((e['rel'] for e in o['nc1_files']), key=ORDER.index) for o in out.values() if o['nc1_files'])
    reli = collections.Counter(o['ifc'][0]['rel'] for o in out.values() if o['ifc'])
    unres = sum(1 for o in out.values() for e in o['nc1_files'] if not e.get('key'))
    tot = sum(len(o['nc1_files']) for o in out.values())
    summ = {'jobs_paired': len(out), **nstat, 'nc1_best_rel': dict(rels), 'ifc_best_rel': dict(reli), 'nc1_files_paired': tot,
            'nc1_files_unresolved': unres, 'sec': round(time.time() - t0)}
    json.dump(summ, open(os.path.join(INV, 'pairs_summary.json'), 'w'), indent=1)
    s3.upload_file(os.path.join(INV, 'pairs_summary.json'), B, f'{RES}/inv/pairs_summary.json')
    log('pairs', json.dumps(summ))


if __name__ == '__main__':
    main()
