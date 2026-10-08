#!/usr/bin/env python3
"""Batch driver (agent box only): NC1 hole check + IFC recall for every paired data-3 SDS2 job with a STEP.

Per job (pairs.json from pair_jobs.py): STEP labels v4c and v5.3 (v5.2 / v5.1 / v5 stand in when v5.3 is not out yet);
  - NC1: the job's NC1 files (inside_job / sibling / same_project, distinct sha) parsed once; nc1_holes_check per label
  - IFC: up to 3 IFC exports (inside_job / sibling / same_name first, else the 2 largest same_project); one digest per
    IFC sha (cached), sds2_ifc_recall per (label, IFC)
STEP indexes are cached per S3 key (pickle) and the STEP is deleted after indexing. Results:
  $W/out/{nc1,ifc}/<job>_<label>[_<ifc8>].json|.md  -> s3://.../agentwork/sds2-recall-nc1/out/...
usage: run_jobs.py [--workers 10] [--ifc-workers 4] [--ids a,b] [--max-step-gb 3] [--max-ifc-mb 900] [--phase nc1,ifc]
"""
import os, sys, json, time, pickle, hashlib, traceback, collections, argparse, threading, re
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import boto3
from botocore.config import Config

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
B = 'bim-proprietary-data'
D3 = 'cad-disk-extract/zenitude-data-3'
RES = f'{D3}/_state/agentwork/sds2-recall-nc1'
W = os.environ.get('W', '/work/agentwork/sds2-recall-nc1')
CACHE = os.path.join(W, 'cache'); DL = os.path.join(W, 'dl'); OUT = os.path.join(W, 'out'); NC1C = os.path.join(W, 'nc1cache')
for d in (CACHE, DL, OUT, NC1C, os.path.join(OUT, 'nc1'), os.path.join(OUT, 'ifc')):
    os.makedirs(d, exist_ok=True)
NC1_RELS = ('inside_job', 'sibling', 'same_project')
IFC_RELS = ('inside_job', 'sibling', 'same_name')
_c = {}


def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'},
                                                                            max_pool_connections=64))
    return _c['c']


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def put(local, key):
    for i in range(3):
        try:
            s3().upload_file(local, B, key); return
        except Exception:
            time.sleep(2)


def pick_labels(steps):
    labs = [l for l in ('v4c', 'v5.3') if l in steps]
    if 'v5.3' not in steps:
        for l in ('v5.2', 'v5.1', 'v5'):
            if l in steps:
                labs.append(l); break
    return labs


def safe(s):
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', s)[:60]


def step_index(key, max_bytes):
    """cached stepidx index of an S3 STEP"""
    import stepidx
    cp = os.path.join(CACHE, 'step_' + hashlib.sha1(key.encode()).hexdigest()[:16] + '.pkl')
    if os.path.exists(cp):
        return pickle.load(open(cp, 'rb')), None
    try:
        size = s3().head_object(Bucket=B, Key=key)['ContentLength']
    except Exception as e:
        return None, f'head failed: {e!r}'[:200]
    if size > max_bytes:
        return None, f'skipped_size {size}'
    dst = os.path.join(DL, hashlib.sha1(key.encode()).hexdigest()[:16] + '.step')
    s3().download_file(B, key, dst)
    t0 = time.time()
    try:
        ix = stepidx.index_step(dst, log=log)
    finally:
        os.remove(dst)
    ix['index_sec'] = round(time.time() - t0, 1); ix['step_bytes'] = size
    tmp = cp + '.tmp'
    pickle.dump(ix, open(tmp, 'wb'), protocol=4); os.replace(tmp, cp)
    return ix, None


MONTH = r'(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)'
DATE_TOK = re.compile(r'^(\d{1,2}' + MONTH + r'\d{0,4}|' + MONTH + r'\d{0,4}|\d{1,2}(st|nd|rd|th)|\d{1,4}|\d{6}|\d{8}|\d{1,4}(am|pm))$')
GENERIC = {'job', 'jb', 'backup', 'back', 'bkup', 'bk', 'abm', 'model', 'models', 'old', 'new', 'final', 'copy', 'rev', 'revised', 'mttl',
           'before', 'after', 'b4abm', 'for', 'ref', 'fab', 'current', 'latest', 'main', 'the', 'of', 'and', 'rar', 'zip', '7z', 'jobdata'}


def name_tokens(s):
    """identity tokens of a job name: lower-case alphanumeric runs minus dates / times / pure numbers and generic words
    ('SHOAL CREEK BLDG-B 22OCT12_JOB' -> {shoal, creek, bldg, b}; 'WF_7312_111313_JOB.rar!' -> {wf})"""
    toks = re.findall(r'[a-z]+\d*[a-z]*|\d+[a-z]*', (s or '').lower())
    return {t for t in toks if t not in GENERIC and not DATE_TOK.match(t)}


def name_match(order, names):
    """NC1 header order line (SDS2's job name at export time) vs the job's folder names: identity token sets equal, or
    one a subset of the other (master job vs building job; job number dropped) - building letters / codes must agree"""
    B = name_tokens(order)
    if not B:
        return 0.0
    best = 0.0
    for n in names:
        A = name_tokens(n)
        if not A:
            continue
        if A == B:
            return 1.0
        small = A if len(A) <= len(B) else B
        if (A <= B or B <= A) and any(len(t) >= 3 for t in small):
            best = max(best, 0.9)
    return best


def job_names(o):
    """the job folder name and its parent folder names (the NC1 header 'order' line is SDS2's job name)"""
    out = {o.get('name') or ''}
    for p in o.get('paths', [])[:4]:
        root = p.split(' :: ')[-1].rstrip('/')
        comps = [c for c in re.split(r'/|!/', root) if c]
        out.update(comps[-2:])
    return [n for n in out if n]


def select_parts(parts, o, thr=0.85):
    """inside_job / sibling NC1 files: all; same_project files: only those whose 'order' (SDS2 job name) matches the job
    by identity tokens (name_match)"""
    names = job_names(o)
    sim = {}
    for p in parts:
        od = (p.get('order') or '').strip()
        if od not in sim:
            sim[od] = name_match(od, names)
    keep = [p for p in parts if p['rel'] in ('inside_job', 'sibling') or sim[(p.get('order') or '').strip()] >= thr]
    orders = collections.Counter((p.get('order') or '').strip() for p in parts)
    info = {'parts_total': len(parts), 'parts_kept': len(keep), 'job_names': names[:6], 'rule': 'identity tokens equal or subset',
            'orders': [[od, n, round(sim[od], 2)] for od, n in orders.most_common(12)]}
    return keep, info


def fetch_nc1(files):
    """NC1 files (resolved keys) -> parsed parts, distinct by sha"""
    import nc1_holes_check as N

    def one(e):
        p = os.path.join(NC1C, e['sha256'][:2], e['sha256'])
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            try:
                b = s3().get_object(Bucket=B, Key=e['key'])['Body'].read()
            except Exception:
                return None
            open(p + '.tmp', 'wb').write(b); os.replace(p + '.tmp', p)
        txt = open(p, 'rb').read().decode('latin-1')
        part = N.parse_nc1(txt, e['path'])
        part['sha256'] = e['sha256']; part['rel'] = e['rel']
        return part
    seen = set(); todo = []
    for e in files:
        if e.get('key') and e['rel'] in NC1_RELS and e['sha256'] not in seen:
            seen.add(e['sha256']); todo.append(e)
    with ThreadPoolExecutor(24) as ex:
        parts = [p for p in ex.map(one, todo) if p]
    return parts


def get_json(key):
    try:
        return json.loads(s3().get_object(Bucket=B, Key=key)['Body'].read())
    except Exception:
        return None


def sds2_version(jid, e):
    """SDS2 job version: step key path (disk-2 run 2 shards/<ver>/), the output's job.json, the reused result, data-3 result"""
    m = re.search(r'/(\d\.\d{3}|\d{4}\.\d{1,3})/', e.get('step') or '')
    if m:
        return m.group(1)
    for k in (e.get('job_json'), e.get('manifest'), e.get('result_key'), f'{D3}/_state/conv/sds2/results/{jid}.json'):
        if not k:
            continue
        d = get_json(k)
        if d:
            v = d.get('version') or (d.get('stage2') or {}).get('version')
            if v:
                return str(v)
    return None


def nc1_job(jid, o, max_bytes):
    import nc1_holes_check as N
    t0 = time.time()
    labs = pick_labels(o['steps'])
    res = {'id': jid, 'name': o['name'], 'labels': labs, 'nc1': {}}
    allparts = fetch_nc1(o['nc1_files'])
    parts, sel = select_parts(allparts, o)
    orders = collections.Counter((p.get('order') or '').strip() for p in parts)
    res['nc1_parts'] = len(parts); res['nc1_orders'] = orders.most_common(5); res['nc1_selection'] = sel
    res['nc1_sets'] = o['nc1_sets'][:10]
    if not parts:
        res['nc1_status'] = 'no_nc1_for_this_job' if allparts else 'no_nc1_resolved'
        json.dump(res, open(os.path.join(OUT, 'nc1', f'{jid}_selection.json'), 'w'), default=str)
        return res
    for lab in labs:
        e = o['steps'][lab]
        tag = f"{jid}_{lab}"
        outj = os.path.join(OUT, 'nc1', tag + '.json')
        if os.path.exists(outj):
            res['nc1'][lab] = json.load(open(outj))['summary']; continue
        try:
            ix, err = step_index(e['step'], max_bytes)
            if ix is None:
                res['nc1'][lab] = {'status': 'error', 'error': err}; continue
            if not parts or e.get('stage') == 1:
                continue
            man = get_json(e['manifest']) if e.get('manifest') else None
            rows, pieces, diag = N.check(ix, parts)
            summ = N.summarize(rows, pieces, diag, man)
            summ.update({'job_id': jid, 'job': o['name'], 'label': lab, 'step_key': e['step'], 'stage': e.get('stage'),
                         'sds2_version': sds2_version(jid, e),
                         'step_source': e.get('source', 'fleet'), 'nc1_selection': sel,
                         'step_bytes': ix.get('step_bytes'), 'index_sec': ix.get('index_sec'), 'nc1_orders': orders.most_common(5),
                         'nc1_sets': o['nc1_sets'][:10], 'job_paths': o['paths'][:2]})
            json.dump({'summary': summ, 'rows': rows}, open(outj, 'w'), default=str)
            open(outj[:-5] + '.md', 'w').write(N.to_md(summ, rows, f"{o['name']} ({lab})"))
            put(outj, f'{RES}/out/nc1/{tag}.json'); put(outj[:-5] + '.md', f'{RES}/out/nc1/{tag}.md')
            res['nc1'][lab] = summ
        except Exception as ex:
            traceback.print_exc()
            res['nc1'][lab] = {'status': 'error', 'error': repr(ex)[:300]}
    res['sec'] = round(time.time() - t0, 1)
    return res


def pick_ifcs(o):
    good = [h for h in o['ifc'] if h['rel'] in IFC_RELS and h.get('input_key')]
    return sorted(good, key=lambda h: (IFC_RELS.index(h['rel']), -h['size']))[:3]


def ifc_digest(h, threads, max_ifc):
    import ifc_products
    cp = os.path.join(CACHE, f"ifc_{h['sha256'][:16]}.npz")
    if os.path.exists(cp):
        return cp, None
    if h['size'] > max_ifc:
        return None, f"skipped_size {h['size']}"
    if h.get('kind') not in (None, 'ifc'):
        return None, f"kind {h.get('kind')} not digested"
    dst = os.path.join(DL, h['sha256'][:16] + '.ifc')
    try:
        s3().download_file(B, h['input_key'], dst)
        d = ifc_products.digest(dst, threads=threads, log=log)
        ifc_products.save(d, cp + '.tmp.npz'); os.replace(cp + '.tmp.npz', cp)
        return cp, None
    except Exception as ex:
        traceback.print_exc()
        return None, repr(ex)[:300]
    finally:
        if os.path.exists(dst):
            os.remove(dst)


def ifc_job(jid, o, max_bytes, max_ifc):
    import sds2_ifc_recall as R
    t0 = time.time()
    labs = pick_labels(o['steps'])
    res = {'id': jid, 'name': o['name'], 'labels': labs, 'ifc': {}}
    for h in pick_ifcs(o):
        cp = os.path.join(CACHE, f"ifc_{h['sha256'][:16]}.npz")
        if not os.path.exists(cp):
            res['ifc'][h['sha256'][:8]] = {'status': 'no_digest'}; continue
        for lab in labs:
            e = o['steps'][lab]
            tag = f"{jid}_{lab}_{h['sha256'][:8]}"
            outj = os.path.join(OUT, 'ifc', tag + '.json')
            if os.path.exists(outj):
                res['ifc'][tag] = {k: v for k, v in json.load(open(outj)).items() if k in ('status', 'overall', 'registration')}; continue
            try:
                ix, err = step_index(e['step'], max_bytes)
                if ix is None:
                    res['ifc'][tag] = {'status': 'error', 'error': err}; continue
                cpix = os.path.join(CACHE, 'step_' + hashlib.sha1(e['step'].encode()).hexdigest()[:16] + '.pkl')
                r = R.run(e['step'], cp, 25.0, lab, o['name'], log=log, index_cache=cpix)
                r.update({'job_id': jid, 'ifc_rel': h['rel'], 'ifc_path': h['path'], 'ifc_key': h['input_key'], 'ifc_sha256': h['sha256'],
                          'sds2_version': sds2_version(jid, e), 'step_source': e.get('source', 'fleet'),
                          'step_key': e['step'], 'stage': e.get('stage'), 'job_paths': o['paths'][:2]})
                json.dump(r, open(outj, 'w'), indent=1, default=str)
                open(outj[:-5] + '.md', 'w').write(R.to_md(r))
                put(outj, f'{RES}/out/ifc/{tag}.json'); put(outj[:-5] + '.md', f'{RES}/out/ifc/{tag}.md')
                res['ifc'][tag] = {k: r.get(k) for k in ('status', 'overall', 'registration')}
            except Exception as ex:
                traceback.print_exc()
                res['ifc'][tag] = {'status': 'error', 'error': repr(ex)[:300]}
    res['sec'] = round(time.time() - t0, 1)
    return res


def prep_one(jid, o):
    """ground-truth inventory of one paired job: NC1 parts kept for the job (order filter), holes, IFC candidates"""
    allparts = fetch_nc1(o['nc1_files'])
    parts, sel = select_parts(allparts, o)
    return {'id': jid, 'name': o['name'], 'labels': sorted(o['steps']), 'model_bytes': o.get('model_bytes'), 'action': o.get('action'),
            'nc1_files_paired': len(o['nc1_files']), 'nc1_files_resolved': sum(1 for e in o['nc1_files'] if e.get('key')),
            'parts_total': len(allparts), 'parts_kept': len(parts), 'parts_kept_with_holes': sum(1 for p in parts if p['holes']),
            'holes_kept': sum(len(p['holes']) for p in parts), 'codes': dict(collections.Counter(p['code'] for p in parts)),
            'selection': sel, 'ifc_candidates': [[h['rel'], h['size'], h['path'][-120:]] for h in pick_ifcs(o)], 'paths': o['paths'][:2]}


def prep(a):
    pairs = json.load(open(os.path.join(W, 'inv', 'pairs.json')))
    todo = [(jid, o) for jid, o in pairs.items() if any(e.get('key') for e in o['nc1_files']) or pick_ifcs(o)]
    log(f'prep: {len(todo)} paired jobs with resolved NC1 or an IFC candidate')
    out = {}
    with ProcessPoolExecutor(a.workers) as ex:
        fut = {ex.submit(prep_one, jid, o): jid for jid, o in todo}
        for f in as_completed(fut):
            try:
                r = f.result(); out[r['id']] = r
            except Exception as e:
                out[fut[f]] = {'id': fut[f], 'error': repr(e)[:300]}
    p = os.path.join(W, 'inv', 'nc1_sel.json')
    json.dump(out, open(p, 'w'), default=str); put(p, f'{RES}/inv/nc1_sel.json')
    c = collections.Counter()
    for r in out.values():
        c['jobs'] += 1; c['with_nc1_kept'] += bool(r.get('parts_kept')); c['with_ifc'] += bool(r.get('ifc_candidates'))
        c['with_step'] += bool(r.get('labels')); c['nc1_kept_and_step'] += bool(r.get('parts_kept') and r.get('labels'))
        c['ifc_and_step'] += bool(r.get('ifc_candidates') and r.get('labels'))
        c['parts_kept'] += r.get('parts_kept') or 0; c['holes_kept'] += r.get('holes_kept') or 0
    log('prep done', dict(c))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=10); ap.add_argument('--ifc-workers', type=int, default=4)
    ap.add_argument('--ifc-threads', type=int, default=2)
    ap.add_argument('--ids'); ap.add_argument('--max-step-gb', type=float, default=3.0); ap.add_argument('--max-ifc-mb', type=float, default=900)
    ap.add_argument('--phase', default='nc1,ifc'); ap.add_argument('--tag', default='run')
    ap.add_argument('--no-digest', action='store_true', help='IFC phase: use cached IFC digests only (another run is digesting)')
    a = ap.parse_args()
    if a.phase == 'prep':
        return prep(a)
    pairs = json.load(open(os.path.join(W, 'inv', 'pairs.json')))
    extra = os.path.join(W, 'inv', 'agent_steps.json')          # STEPs this agent converted (conv_jobs.py), merged per label
    if os.path.exists(extra):
        for jid, d in json.load(open(extra)).items():
            if jid in pairs:
                for lab, e in d.items():
                    pairs[jid]['steps'].setdefault(lab, e)
    ids = a.ids.split(',') if a.ids else None
    jobs = {}
    for jid, o in pairs.items():
        if ids and jid not in ids:
            continue
        if not pick_labels(o['steps']):
            continue
        has_nc1 = any(e['rel'] in NC1_RELS and e.get('key') for e in o['nc1_files'])
        has_ifc = bool(pick_ifcs(o))
        if has_nc1 or has_ifc:
            jobs[jid] = (o, has_nc1, has_ifc)
    log(f'{len(jobs)} jobs: nc1 {sum(1 for v in jobs.values() if v[1])}, ifc {sum(1 for v in jobs.values() if v[2])}')
    maxb = int(a.max_step_gb * 1e9); maxi = int(a.max_ifc_mb * 1e6)
    prog = {'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'jobs': len(jobs), 'nc1_done': 0, 'ifc_digests_done': 0,
            'ifc_done': 0, 'errors': []}
    pp = os.path.join(OUT, f'progress_{a.tag}.json')

    def save_prog():
        prog['updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        json.dump(prog, open(pp, 'w'), indent=1, default=str); put(pp, f'{RES}/out/progress_{a.tag}.json')
    summ_nc1 = {}; summ_ifc = {}
    # IFC digests run alongside the NC1 phase (separate pool)
    ifc_list = {}
    if 'ifc' in a.phase and not a.no_digest:
        for jid, (o, _, hi) in jobs.items():
            if hi:
                for h in pick_ifcs(o):
                    ifc_list[h['sha256']] = h
    log(f'{len(ifc_list)} IFC digests needed')
    exi = ProcessPoolExecutor(a.ifc_workers) if ifc_list else None
    fut_i = {exi.submit(ifc_digest, h, a.ifc_threads, maxi): sha for sha, h in sorted(ifc_list.items(), key=lambda kv: kv[1]['size'])} if exi else {}
    order = sorted(jobs, key=lambda j: sum((jobs[j][0]['steps'][l].get('step_size') or 3e8) for l in pick_labels(jobs[j][0]['steps'])))
    if 'nc1' in a.phase:
        with ProcessPoolExecutor(a.workers) as ex:
            fut = {ex.submit(nc1_job, jid, jobs[jid][0], maxb): jid for jid in order if jobs[jid][1]}
            for f in as_completed(fut):
                jid = fut[f]
                try:
                    r = f.result(); summ_nc1[jid] = r
                    log('nc1 done', jid, jobs[jid][0]['name'][:40], {l: (v.get('matched_parts') or {}).get('hole_recall') if isinstance(v, dict) else None for l, v in r['nc1'].items()}, r.get('sec'))
                except Exception as e:
                    prog['errors'].append([jid, 'nc1', repr(e)[:200]])
                prog['nc1_done'] += 1
                prog['ifc_digests_done'] = sum(1 for x in fut_i if x.done())
                if prog['nc1_done'] % 5 == 0:
                    save_prog()
        save_prog()
    if 'ifc' in a.phase:
        digest_err = {}
        for f in as_completed(fut_i):
            try:
                cp, err = f.result()
            except Exception as e:
                cp, err = None, repr(e)[:300]
            if err:
                digest_err[fut_i[f]] = err
        prog['ifc_digests_done'] = len(fut_i); prog['ifc_digest_errors'] = digest_err
        save_prog()
        with ProcessPoolExecutor(a.workers) as ex:
            fut = {ex.submit(ifc_job, jid, jobs[jid][0], maxb, maxi): jid for jid in order if jobs[jid][2]}
            for f in as_completed(fut):
                jid = fut[f]
                try:
                    r = f.result(); summ_ifc[jid] = r
                    log('ifc done', jid, jobs[jid][0]['name'][:40], {k: (v.get('overall') or {}).get('ifc_recall') if isinstance(v, dict) and v.get('overall') else v.get('status') for k, v in r['ifc'].items()}, r.get('sec'))
                except Exception as e:
                    prog['errors'].append([jid, 'ifc', repr(e)[:200]])
                prog['ifc_done'] += 1
                if prog['ifc_done'] % 5 == 0:
                    save_prog()
    if exi:
        exi.shutdown(wait=True)
    json.dump({'nc1': summ_nc1, 'ifc': summ_ifc}, open(os.path.join(OUT, f'batch_{a.tag}.json'), 'w'), default=str)
    put(os.path.join(OUT, f'batch_{a.tag}.json'), f'{RES}/out/batch_{a.tag}.json')
    prog['finished'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    save_prog()
    log('all done')


if __name__ == '__main__':
    main()
