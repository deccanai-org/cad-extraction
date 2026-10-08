#!/usr/bin/env python3
"""Find SDS2 jobs (data-3) that have a STEP output in S3 and ship an IFC export and/or NC1 files near the job folder.
Inputs (downloaded into state/): move_jobs.json (manifest id -> archive), parts.tgz-derived work/parts_index.json,
contents_sds2.jsonl.gz, d3_sds2_step_listing.txt. Output: work/candidates_ifc.json
"""
import json, gzip, re, os, collections, sys
HERE = os.path.dirname(os.path.abspath(__file__))
S = lambda *p: os.path.join(HERE, *p)

def norm(s):
    s = s.lower()
    s = re.sub(r'\.(ifc|ifczip|ifcxml)$', '', s)
    s = re.sub(r'[^a-z0-9]+', '', s)
    s = re.sub(r'(job|jb)$', '', s)
    return s

def main():
    arch = {}
    for j in json.load(open(S('state/move_jobs.json'))):
        arch[j['id']] = j.get('key') or j.get('dir') or ''
    a2jid = collections.defaultdict(list)
    for k, v in arch.items():
        a2jid[v].append(k)
    parts = json.load(open(S('work/parts_index.json')))
    rows = [json.loads(l) for l in gzip.open(S('state/contents_sds2.jsonl.gz'))]
    # STEP availability
    step = collections.defaultdict(dict)
    for line in open(S('state/d3_sds2_step_listing.txt')):
        f = line.split()
        if len(f) < 4 or not f[3].endswith('.step'):
            continue
        key = f[3]; size = int(f[2])
        m = re.match(r'cad-disk-extract/zenitude-data-3/conversions/sds2-step/(_not_accepted/)?([0-9a-f]{24})/(v[0-9.]+/)?(.+)$', key)
        if not m:
            continue
        lab = (m.group(3) or 'v4/').rstrip('/')
        if m.group(1):
            lab += '_not_accepted'
        step[m.group(2)][lab] = {'key': key, 'size': size}
    for r in rows:
        ru = r.get('reuse')
        if isinstance(ru, dict) and ru.get('step_key'):
            step[r['id']]['v4c_' + ru['from']] = {'key': ru['step_key'], 'size': None}
    # IFC + roots per manifest
    out = []
    for r in rows:
        if r['id'] not in step:
            continue
        occs = []
        for p in r.get('paths', []):
            a, _, root = p.partition(' :: ')
            occs.append((a, root))
        hits = {}
        for a, root in occs:
            for jid in a2jid.get(a, []):
                pi = parts.get(jid)
                if not pi:
                    continue
                jobname = root.rstrip('/').split('/')[-1]
                top = root.split('/')[0] if '/' in root else ''
                for p, size, sha, key in pi['ifc']:
                    base = p.rsplit('/', 1)[-1]
                    if p.startswith(root):
                        rel = 'inside_job'
                    elif norm(base) and (norm(base) == norm(jobname) or norm(jobname).startswith(norm(base)) or norm(base).startswith(norm(jobname))) and len(norm(base)) >= 4:
                        rel = 'same_name'
                    elif top and p.startswith(top + '/'):
                        rel = 'same_project'
                    else:
                        rel = 'same_archive'
                    h = hits.setdefault(sha, {'sha256': sha, 'size': size, 'key': key, 'paths': [], 'rel': rel})
                    if len(h['paths']) < 3:
                        h['paths'].append(f'{a} :: {p}')
                    order = ['inside_job', 'same_name', 'same_project', 'same_archive']
                    if order.index(rel) < order.index(h['rel']):
                        h['rel'] = rel
        if hits:
            out.append({'id': r['id'], 'paths': r.get('paths', [])[:5], 'model_bytes': r.get('model_bytes'), 'steps': step[r['id']],
                        'ifc': sorted(hits.values(), key=lambda h: (['inside_job', 'same_name', 'same_project', 'same_archive'].index(h['rel']), -h['size']))})
    json.dump(out, open(S('work/candidates_ifc.json'), 'w'), indent=1)
    c = collections.Counter(h['rel'] for o in out for h in o['ifc'][:1])
    print('jobs with STEP:', len(step), ' with IFC in same manifest:', len(out), ' best relation:', dict(c))
    for o in out:
        b = o['ifc'][0]
        if b['rel'] in ('inside_job', 'same_name'):
            print(o['id'], list(o['steps']), o['paths'][0][-90:], '|', b['rel'], b['size'], b['paths'][0][-100:])

if __name__ == '__main__':
    main()
