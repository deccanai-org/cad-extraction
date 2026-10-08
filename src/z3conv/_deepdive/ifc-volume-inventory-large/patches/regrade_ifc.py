#!/usr/bin/env python3
"""Re-grade finished IFC conversions (ifc/results, status ok) with census v3 + join v3 without re-converting:
download the source (job input_key, sha-checked, unpacked like the worker) -> ifc_census.py v2 -> join with the stored
STEP part list (ifc/detail/<id>.step_parts.jsonl.gz). Results whose STEP was graded text-only (STEP >= RB_MAX) get the
chunked OCC read-back first (STEP downloaded from out_key). Writes the updated result JSON to --out (local); --upload
puts result + detail files back (owner / fleet credentials only).
usage: regrade_ifc_v2.py --ids ID [ID ...] | --all  [--out DIR] [--upload] [--py PYTHON] [--work DIR]"""
import os, sys, json, gzip, shutil, argparse, subprocess, tempfile, zipfile, hashlib
import boto3

HERE = os.path.dirname(os.path.abspath(__file__))
B = 'bim-proprietary-data'; ROOT = 'cad-disk-extract/zenitude-data-3'; ST = f'{ROOT}/_state/conv/ifc'
ap = argparse.ArgumentParser()
ap.add_argument('--ids', nargs='*'); ap.add_argument('--all', action='store_true')
ap.add_argument('--out', default='regraded'); ap.add_argument('--upload', action='store_true')
ap.add_argument('--py', default=sys.executable); ap.add_argument('--work', default=None)
ap.add_argument('--chunk-mb', default='150'); ap.add_argument('--rb-max-mb', type=int, default=1024)
a = ap.parse_args()
s3 = boto3.client('s3', region_name='ap-south-1')
sys.path.insert(0, HERE)
import grade_join

os.makedirs(a.out, exist_ok=True)
jobs = {j['id']: j for j in json.loads(s3.get_object(Bucket=B, Key=f'{ST}/jobs.json')['Body'].read())}
ids = a.ids or []
if a.all:
    ids = [o['Key'].rsplit('/', 1)[-1][:-5] for p in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{ST}/results/')
           for o in p.get('Contents', []) if o['Key'].endswith('.json')]


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()


def unpack(raw, d):
    with open(raw, 'rb') as f:
        head = f.read(4)
    if head == b'PK\x03\x04':
        with zipfile.ZipFile(raw) as z:
            ms = [i for i in z.infolist() if not i.is_dir()]
            m = max([i for i in ms if i.filename.lower().endswith('.ifc')] or ms, key=lambda i: i.file_size)
            out = os.path.join(d, 'src.ifc')
            with z.open(m) as x, open(out, 'wb') as y:
                shutil.copyfileobj(x, y, 1 << 24)
            return out
    if head[:2] == b'\x1f\x8b':
        out = os.path.join(d, 'src.ifc')
        with gzip.open(raw) as x, open(out, 'wb') as y:
            shutil.copyfileobj(x, y, 1 << 24)
        return out
    return raw


for jid in ids:
    try:
        r = json.loads(s3.get_object(Bucket=B, Key=f'{ST}/results/{jid}.json')['Body'].read())
    except Exception as e:
        print(jid[:16], 'no result', e); continue
    if r.get('status') != 'ok' or ((r.get('census') or {}).get('census_version') or 1) >= 3:
        continue
    d = tempfile.mkdtemp(prefix='rg_', dir=a.work)
    try:
        job = jobs.get(jid) or {'input_key': r['input_key'], 'sha256': r.get('sha256')}
        raw = os.path.join(d, 'in.bin'); s3.download_file(B, job['input_key'], raw)
        if job.get('sha256') and sha(raw) != job['sha256']:
            print(jid[:16], 'input sha mismatch'); continue
        src = unpack(raw, d)
        relabel = [x.split('_declared_', 1)[1] for x in (r.get('input_fix') or []) if str(x).startswith('schema_') and '_declared_' in str(x)]
        if relabel:                                   # census runs on the file the converter saw (worker: fix_schema)
            import re
            data = open(src, 'rb').read()
            m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", data[:1 << 16])
            src2 = os.path.join(d, 'schema.ifc'); open(src2, 'wb').write(data[:m.start(1)] + relabel[-1].encode() + data[m.end(1):]); src = src2
        cj = os.path.join(d, 'census.json'); cp = os.path.join(d, 'src_parts.jsonl.gz')
        rc = subprocess.run([a.py, os.path.join(HERE, 'ifc_census.py'), src, cj, '--parts', cp], stdout=subprocess.DEVNULL).returncode
        if rc != 0:
            print(jid[:16], 'census rc', rc); continue
        sp = os.path.join(d, 'step_parts.jsonl.gz')
        v = r.get('validate') or {}
        if 'skipped' in v:
            stp = os.path.join(d, 'out.step'); s3.download_file(B, r['out_key'], stp)
            chk = os.path.join(d, 'check.json')
            subprocess.run([a.py, os.path.join(HERE, 'step_check_chunked.py'), stp, chk, '--parts', sp, '--chunk-mb', a.chunk_mb,
                            '--check', os.path.join(HERE, 'step_check.py'), '--py', a.py, '--workdir', os.path.join(d, 'chunks')])
            nv = json.load(open(chk))
            if nv.get('read_status') == 'ok':
                nv['readback_mode'] = f'chunked (STEP >= {a.rb_max_mb} MB, regrade)'
                for k in ('flavour_ok', 'markers_kit'):
                    nv[k] = v.get(k)
                nv['grade'] = 'ok_solid' if nv.get('solids') else ('ok_surface' if nv.get('faces') else 'empty'); nv['validated'] = True
                r['validate'] = {k: x for k, x in nv.items() if k != 'invalid_examples'}
                r['validate']['invalid_examples'] = (nv.get('invalid_examples') or [])[:10]
            os.remove(stp)
        else:
            s3.download_file(B, f'{ST}/detail/{jid}.step_parts.jsonl.gz', sp)
        r['census'] = json.load(open(cj))
        if os.path.exists(sp):
            r['join'] = grade_join.join(grade_join.load(cp), grade_join.load(sp))
        r['regraded'] = 'census_v3+join_v3'
        json.dump(r, open(os.path.join(a.out, f'{jid}.json'), 'w'))
        if a.upload:
            s3.upload_file(os.path.join(a.out, f'{jid}.json'), B, f'{ST}/results/{jid}.json')
            for p, nm in ((cj, 'census.json'), (cp, 'src_parts.jsonl.gz'), (sp, 'step_parts.jsonl.gz')):
                if os.path.exists(p):
                    s3.upload_file(p, B, f'{ST}/detail/{jid}.{nm}')
        vol = (r.get('join') or {}).get('volume') or {}
        print(jid[:16], 'ok', {k: vol.get(k) for k in ('checked', 'outside_5pct', 'checked_interval')}, (r.get('validate') or {}).get('readback_mode'))
    finally:
        shutil.rmtree(d, ignore_errors=True)
