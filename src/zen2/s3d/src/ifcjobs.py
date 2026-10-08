"""Plan + run IFC generation per area chunk (resumable).

ifcjobs.py plan   -> WORK/jobs/ifc.json
ifcjobs.py run [--workers 10] [--only JOBID ...] [--kind piping|structure|equipment]
Outputs OUT/ifc/<area>/<area>__<kind>__NNN.ifc and WORK/ifcdone/<jobid>.json (manifest with origin, counts, bbox).
"""
import os, sys, json, time, math, glob, gzip, argparse, collections, traceback
import numpy as np
from common import *

JOBF = os.path.join(WORK, 'jobs', 'ifc.json')
DONE = os.path.join(WORK, 'ifcdone')
FAILF = os.path.join(WORK, 'fail', 'ifc.jsonl')
PIPE_MAX = 1200        # piping components per IFC chunk
PIPE_SPLIT = 1500      # a single pipeline heavier than this is split into parts
PIPE_PART = 1400
STRUCT_MAX = 8000     # members per IFC chunk
EQUIP_MAX = 600       # equipment per IFC chunk


def area_safe(a):
    return safe_name((a or '_unassigned').replace('/', '__'), 90)


def plan():
    jobs = []
    # piping: from done markers
    by_area = collections.defaultdict(list)
    for f in glob.glob(os.path.join(WORK, 'done', 'piping', 'pb*.json')):
        for r in json.load(open(f)).get('results', []):
            if 'error' in r or not r.get('n'):
                continue
            by_area[r['area']].append((r['name'], r['json'], r['n'] + r['counts'].get('_supports', 0) * 2))
    for area, pls in sorted(by_area.items()):
        pls.sort()
        chunk, n, k = [], 0, 0
        for name, js, w in pls:
            if w > PIPE_SPLIT:
                # very large pipeline (catalog SpecTest lines): split into parts so every STEP stays OCC-readable
                if chunk:
                    jobs.append({'id': 'pip__%s__%03d' % (area_safe(area), k), 'kind': 'piping', 'area': area, 'inputs': [c[1] for c in chunk]})
                    chunk, n, k = [], 0, k + 1
                np_ = math.ceil(w / PIPE_PART)
                for i in range(np_):
                    jobs.append({'id': 'pip__%s__%03dp%02d' % (area_safe(area), k, i), 'kind': 'piping', 'area': area, 'inputs': [js], 'part': [i, np_]})
                k += 1
                continue
            if chunk and n + w > PIPE_MAX:
                jobs.append({'id': 'pip__%s__%03d' % (area_safe(area), k), 'kind': 'piping', 'area': area, 'inputs': [c[1] for c in chunk]})
                chunk, n, k = [], 0, k + 1
            chunk.append((name, js)); n += w
        if chunk:
            jobs.append({'id': 'pip__%s__%03d' % (area_safe(area), k), 'kind': 'piping', 'area': area, 'inputs': [c[1] for c in chunk]})
    # structure / equipment: one job per area file (chunked inside)
    for kind, sub, mx in (('structure', 'structure', STRUCT_MAX), ('equipment', 'equipment', EQUIP_MAX)):
        for f in sorted(glob.glob(os.path.join(OUT, 'json', sub, '*.jsonl.gz'))):
            nm = os.path.basename(f)[:-len('.jsonl.gz')]
            n = sum(1 for _ in gzip.open(f, 'rt'))
            pre = 'st2' if kind == 'structure' else kind[:3]       # st2 = structure with ACIS solids, curved members, slabs
            for k in range(max(1, math.ceil(n / mx))):
                jobs.append({'id': '%s__%s__%03d' % (pre, nm, k), 'kind': kind, 'area_file': os.path.relpath(f, OUT),
                             'chunk': k, 'nchunks': max(1, math.ceil(n / mx)), 'n_total': n, 'acis': kind == 'structure'})
    os.makedirs(os.path.dirname(JOBF), exist_ok=True)
    json.dump(jobs, open(JOBF, 'w'))
    c = collections.Counter(j['kind'] for j in jobs)
    print('ifc jobs', len(jobs), dict(c))


def _load_area_chunk(job):
    recs = [json.loads(l) for l in gzip.open(os.path.join(OUT, job['area_file']), 'rt')]
    if job['kind'] == 'structure':
        def pos(r):
            if r.get('start'):
                return r['start']
            b = r.get('bbox') or [0, 0, 0, 0, 0, 0]
            return [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2]
        recs = [r for r in recs if (r['kind'] == 'member' and r.get('start') and r.get('end')) or r['kind'] in ('curved_member', 'slab')]
        for r in recs:
            r['_pos'] = pos(r)
        # spatial order so that chunks are compact
        recs.sort(key=lambda r: (int(r['_pos'][0] // 40), int(r['_pos'][1] // 40), r['_pos'][2], r['oid']))
    else:
        recs.sort(key=lambda r: ((r.get('origin') or [0, 0, 0])[0] // 40, (r.get('origin') or [0, 0, 0])[1] // 40, r['oid']))
    n = len(recs)
    per = math.ceil(n / job['nchunks']) if job['nchunks'] else n
    return recs[job['chunk'] * per:(job['chunk'] + 1) * per]


def build(job):
    import ifcgen
    t0 = time.time()
    if job['kind'] == 'piping':
        Js = [read_json(os.path.join(OUT, p)) for p in job['inputs']]
        if job.get('part'):
            i, np_ = job['part']
            J = Js[0]; C = J['components']; per = math.ceil(len(C) / np_)
            J['components'] = C[i * per:(i + 1) * per]
            keep = {c['oid'] for c in J['components']}
            J['supports'] = [s_ for s_ in J.get('supports', []) if s_.get('supported_part') in keep]
            J['name'] = J.get('name')
        area = job['area']
        pts = np.array([q['xyz'] for J in Js for C in J['components'] for q in C['ports'] if q.get('xyz')] or [[0, 0, 0]])
        items = Js
    else:
        items = _load_area_chunk(job)
        area = items[0]['area'] if items else '_'
        if job['kind'] == 'structure':
            pts = np.array([m['_pos'] for m in items] or [[0, 0, 0]])
            if job.get('acis'):
                import pickle as _pk
                want = {m['oid'] for m in items}; got = 0
                ad = os.path.join(WORK, 'acis', 'areas', area_safe(area))
                geo = {}
                for pf in glob.glob(os.path.join(ad, '*.pkl')):
                    d = _pk.load(open(pf, 'rb'))
                    geo.update({k: v for k, v in d.items() if k in want})
                for m in items:
                    g = geo.get(m['oid'])
                    if g is not None:
                        m['_acis'] = g; got += 1
        else:
            pts = np.array([e['origin'] for e in items if e.get('origin')] or [[0, 0, 0]])
    lo, hi = np.percentile(pts, 1, axis=0), np.percentile(pts, 99, axis=0)
    origin = np.round(((lo + hi) / 2) / 10.0) * 10.0
    name = 'MLNG@1 %s %s %s' % (area, job['kind'], job['id'].rsplit('__', 1)[-1])
    W = ifcgen.IfcW(name, origin, area, {'Area': area, 'Discipline': job['kind'], 'Chunk': job['id']})
    cnt = collections.Counter()
    fails = []
    if job['kind'] == 'piping':
        for J in items:
            try:
                cnt.update(ifcgen.add_pipeline(W, J)); cnt['pipelines'] += 1
            except Exception as e:
                fails.append({'stage': 'ifc', 'item': J.get('name'), 'reason': '%s: %s' % (type(e).__name__, str(e)[:160])})
        gcls = 'IfcDistributionSystem'
    elif job['kind'] == 'structure':
        for m in items:
            try:
                if m['kind'] == 'member':
                    e = ifcgen.add_member(W, m)
                    cnt['members' if e is not None else 'members_skipped'] += 1
                    if e is not None and m.get('_acis') and m['_acis'].get('complete'):
                        cnt['members_acis_solid'] += 1
                else:
                    e = ifcgen.add_acis_object(W, m)
                    cnt[m['kind'] + ('s' if e is not None else 's_no_geometry')] += 1
            except Exception as e:
                cnt['members_failed'] += 1
                if len(fails) < 20:
                    fails.append({'stage': 'ifc', 'item': m.get('oid'), 'reason': '%s: %s' % (type(e).__name__, str(e)[:160])})
        gcls = 'IfcGroup'
    else:
        for E in items:
            try:
                cnt.update(ifcgen.add_equipment(W, E)); cnt['equipment'] += 1
            except Exception as e:
                cnt['equipment_failed'] += 1
                if len(fails) < 20:
                    fails.append({'stage': 'ifc', 'item': E.get('oid'), 'reason': '%s: %s' % (type(e).__name__, str(e)[:160])})
        gcls = 'IfcGroup'
    rel = 'ifc/%s/%s.ifc' % (area_safe(area), job['id'])
    path = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    W.write(path + '.tmp', group_cls=gcls)
    os.replace(path + '.tmp', path)
    man = {'id': job['id'], 'kind': job['kind'], 'area': area, 'ifc': rel, 'origin': [float(v) for v in origin],
           'bytes': os.path.getsize(path), 'elements': len(W.contained), 'by_class': dict(W.stats), 'counts': dict(cnt),
           'bbox_p1_p99': [float(v) for v in list(lo) + list(hi)], 'sec': round(time.time() - t0, 1), 'at': utcnow(), 'fails': fails}
    return man


def _worker(job):
    try:
        man = build(job)
        os.makedirs(DONE, exist_ok=True)
        write_json(os.path.join(DONE, job['id'] + '.json'), man, gz=False)
        if man['fails']:
            os.makedirs(os.path.dirname(FAILF), exist_ok=True)
            with open(FAILF, 'a') as f:
                for x in man['fails']:
                    f.write(json.dumps(dict(x, job=job['id'])) + '\n')
        return {'id': job['id'], 'elements': man['elements'], 'mb': round(man['bytes'] / 1e6, 1), 'sec': man['sec']}
    except Exception as e:
        os.makedirs(os.path.dirname(FAILF), exist_ok=True)
        with open(FAILF, 'a') as f:
            f.write(json.dumps({'stage': 'ifc', 'item': job['id'], 'reason': '%s: %s' % (type(e).__name__, str(e)[:300])}) + '\n')
        return {'id': job['id'], 'error': '%s: %s' % (type(e).__name__, e), 'tb': traceback.format_exc()[-800:]}


def summary():
    tot = collections.Counter(); files = 0; byk = collections.Counter(); mb = 0.0
    for f in glob.glob(os.path.join(DONE, '*.json')):
        m = json.load(open(f)); files += 1; byk[m['kind']] += 1; mb += m['bytes'] / 1e6
        tot.update(m['by_class']); tot.update({'n_' + k: v for k, v in m['counts'].items()})
    s = {'ifc_files': files, 'by_kind': dict(byk), 'total_mb': round(mb, 1), 'totals': dict(tot)}
    json.dump(s, open(os.path.join(WORK, 'ifc_summary.json'), 'w'), indent=1)
    return s


def run(workers, only=None, kind=None):
    jobs = json.load(open(JOBF))
    if only:
        jobs = [j for j in jobs if j['id'] in only]
    if kind:
        jobs = [j for j in jobs if j['kind'] == kind]
    todo = [j for j in jobs if not os.path.exists(os.path.join(DONE, j['id'] + '.json'))]
    # big first for better packing
    todo.sort(key=lambda j: -(len(j.get('inputs', [])) * 30 + j.get('n_total', 0) / max(1, j.get('nchunks', 1))))
    log('ifc: %d/%d jobs to run, %d workers' % (len(todo), len(jobs), workers))
    import multiprocessing as mp
    t0 = time.time(); n = 0
    with mp.get_context('fork').Pool(workers, maxtasksperchild=20) as pool:
        for r in pool.imap_unordered(_worker, todo):
            n += 1
            log('%d/%d %.0fs %s' % (n, len(todo), time.time() - t0, json.dumps(r)[:300]))
            if n % 10 == 0:
                summary()
    log('ifc done %s' % json.dumps(summary()))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd'); ap.add_argument('--workers', type=int, default=10)
    ap.add_argument('--only', nargs='*'); ap.add_argument('--kind')
    a = ap.parse_args()
    if a.cmd == 'plan':
        plan()
    elif a.cmd == 'run':
        run(a.workers, a.only, a.kind)
    elif a.cmd == 'summary':
        print(json.dumps(summary(), indent=1))
