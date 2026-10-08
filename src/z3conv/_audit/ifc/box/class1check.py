#!/usr/bin/env python3
"""IFC audit: run graph2.py on every class-1 IFC model (double body representations, faceted B-rep voids) and compare the
sampled products with the part volumes of the model's current STEP (detail step_parts). Output class1check.jsonl.gz."""
import os, sys, json, gzip, time, subprocess, collections, shutil
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan as S

W = S.W; OUTD = os.path.join(W, 'c1out'); os.makedirs(OUTD, exist_ok=True)


def verdicts(rec, mi, mid, s3):
    key = S.detail_key(mi, mid)
    try:
        body = s3.get_object(Bucket=S.B, Key=key)['Body'].read()
        rows = [json.loads(l) for l in gzip.decompress(body).decode().splitlines() if l.strip()]
    except Exception as e:
        rec['step_parts_error'] = f'{type(e).__name__}'; return
    bypid = collections.defaultdict(list); byname = collections.defaultdict(list)
    for r in rows:
        bypid[r.get('pid')].append(r); byname[r.get('name')].append(r)
    g = rec.get('g2') or {}
    for smp in g.get('multi_body_samples') or []:
        c = bypid.get(smp['gid']) or byname.get(smp.get('name')) or []
        vols = [x.get('volume') for x in c if x.get('volume')]
        pv = smp.get('product_volume'); reps = [v for v in (smp.get('rep_volumes') or {}).values() if isinstance(v, (int, float))]
        if not vols or not pv:
            smp['verdict'] = 'no_step_volume' if not vols else 'no_kernel_volume'; continue
        sv = min(vols, key=lambda v: min(abs(v / pv - 1), abs(v / max(1e-9, sum(reps)) - 1)))
        smp['step_vol'] = sv; smp['step_over_body'] = round(sv / pv, 4); smp['step_over_sum_reps'] = round(sv / sum(reps), 4) if reps else None
        smp['verdict'] = 'step_double' if reps and len(reps) > 1 and abs(sv / sum(reps) - 1) < 0.01 and abs(sv / pv - 1) > 0.05 else \
            ('step_single' if abs(sv / pv - 1) < 0.01 else 'step_other')
    for smp in g.get('brep_voids_samples') or []:
        c = bypid.get(smp['gid']) or byname.get(smp.get('name')) or []
        vols = [x.get('volume') for x in c if x.get('volume')]
        o, v = smp.get('outer_shell_mm3'), smp.get('voids_mm3')
        if not vols or not o:
            smp['verdict'] = 'no_step_volume' if not vols else 'no_shell_volume'; continue
        if not v or v < 0.001 * o:
            smp['verdict'] = 'voids_negligible'; continue
        sv = min(vols, key=lambda x: min(abs(x / (o + v) - 1), abs(x / (o - v) - 1)))
        smp['step_vol'] = sv; smp['step_over_outer_plus_voids'] = round(sv / (o + v), 4); smp['step_over_outer_minus_voids'] = round(sv / (o - v), 4)
        smp['verdict'] = 'step_voids_as_solids' if abs(sv / (o + v) - 1) < 0.005 else ('step_voids_correct' if abs(sv / (o - v) - 1) < 0.005 else 'step_other')


def one(args):
    c, mi = args
    mid = c['id']; outp = os.path.join(OUTD, mid + '.json')
    if os.path.exists(outp):
        return 'skip'
    d = os.path.join(W, 'src2', mid[:20]); os.makedirs(d, exist_ok=True)
    rec = {'id': mid, 'info': mi}; s3 = S.s3c()
    try:
        raw = os.path.join(d, 'in.bin'); s3.download_file(S.B, c['input_key'], raw)
        tmp = {}
        src = S.unpack(raw, os.path.join(d, 'unz'), tmp)
        head = open(src, 'rb').read(1 << 16)
        import re
        m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", head)
        sch = m.group(1).decode().upper() if m else ''
        if sch in ('IFC2X2_FINAL', 'IFC2X_FINAL', 'IFC2X2', 'IFC2X', 'IFC2X3_TC1'):
            data = open(src, 'rb').read(); m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", data[:1 << 16])
            src2 = os.path.join(d, 'rl.ifc'); open(src2, 'wb').write(data[:m.start(1)] + b'IFC2X3' + data[m.end(1):]); src = src2
        gj = os.path.join(d, 'g2.json')
        for py in (S.PY, S.PY84):
            try:
                p = subprocess.run([py, os.path.join(W, 'graph2.py'), src, gj], capture_output=True, timeout=1800)
                if p.returncode == 0 and os.path.exists(gj):
                    rec['g2'] = json.load(open(gj)); break
                rec.setdefault('errs', []).append(p.stderr.decode('latin1', 'replace')[-300:])
            except subprocess.TimeoutExpired:
                rec.setdefault('errs', []).append('timeout')
        if rec.get('g2') and (rec['g2'].get('multi_body_samples') or rec['g2'].get('brep_voids_samples')):
            verdicts(rec, mi, mid, s3)
    except Exception as e:
        rec['error'] = f'{type(e).__name__}: {str(e)[:200]}'
    finally:
        shutil.rmtree(d, ignore_errors=True)
    json.dump(rec, open(outp, 'w'), default=str)
    return 'ok'


if __name__ == '__main__':
    cont = {json.loads(l)['id']: json.loads(l) for l in gzip.open(os.path.join(W, 'contents_ifc.jsonl.gz'), 'rt')}
    info = json.load(open(os.path.join(W, 'model_info.json')))
    todo = [(cont[m], i) for m, i in info.items() if i.get('class') == 1 and m in cont]
    todo.sort(key=lambda x: x[0].get('size') or 0)
    print('class-1 models', len(todo), flush=True)
    t0 = time.time()
    with Pool(int(sys.argv[1]) if len(sys.argv) > 1 else 8, maxtasksperchild=25) as p:
        st = collections.Counter(p.imap_unordered(one, todo, chunksize=2))
    with gzip.open(os.path.join(W, 'class1check.jsonl.gz'), 'wt') as f:
        for x in sorted(os.listdir(OUTD)):
            f.write(open(os.path.join(OUTD, x)).read().strip() + '\n')
    S.s3c().upload_file(os.path.join(W, 'class1check.jsonl.gz'), S.B, S.OUTK + '/class1check.jsonl.gz')
    print('done', dict(st), round(time.time() - t0), flush=True)
