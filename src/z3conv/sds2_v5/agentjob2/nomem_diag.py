"""0-member jobs with piece files: what could place them? usage: nomem_diag.py <decode> <out.jsonl> <job id>..."""
import sys, os, json, gzip, re, collections, traceback, shutil, struct
import numpy as np
import boto3
sys.path.insert(0, sys.argv[1])
import brep, sds2job
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
F = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/'; W = '/work/agentwork/sds2v54'
out = open(sys.argv[2], 'a')
from concurrent.futures import ThreadPoolExecutor
for jid in sys.argv[3:]:
    r = dict(id=jid); jd = f'{W}/jobs_nm/{jid[:8]}'
    try:
        key = s3.list_objects_v2(Bucket=B, Prefix=F + jid[:8])['Contents'][0]['Key']
        mf = json.loads(gzip.decompress(s3.get_object(Bucket=B, Key=key)['Body'].read()))
        r['files'] = collections.Counter((f['p'].replace('\\', '/').split('/')[-2] if '/' in f['p'] else '') for f in mf).most_common(6)
        sub = [f for f in mf if re.search(r'(^|/)subm/\d+$', f['p'].replace('\\', '/'))]
        keep = [f for f in mf if not re.search(r'(^|/)(subm|mem)/\d+$', f['p'].replace('\\', '/'))]
        keep += sub[::max(1, len(sub) // 300)]
        def one(f):
            parts = [p.lower() if p.lower() in ('main', 'mem', 'subm', 'jsetup', 'job_mtrl', 'mem_idx', 'subm_idx') else p for p in f['p'].replace('\\', '/').split('/') if p]
            i = max([k for k, p in enumerate(parts) if p in ('main', 'mem', 'subm')] or [0])
            path = os.path.join(jd, *parts[i:]); os.makedirs(os.path.dirname(path), exist_ok=True)
            if f.get('key'): open(path, 'wb').write(s3.get_object(Bucket=B, Key=f['key'])['Body'].read())
            else: open(path, 'wb').close()
        with ThreadPoolExecutor(16) as ex: list(ex.map(one, keep))
        r['version'] = sds2job.read_version(jd)
        mi = os.path.join(jd, 'mem', 'mem_idx')
        if os.path.exists(mi):
            b = open(mi, 'rb').read(); r['mem_idx'] = len(b); r['mem_idx_nonzero'] = int(np.count_nonzero(np.frombuffer(b, np.uint8)))
            r['mem_idx_strings'] = collections.Counter(m.group().decode() for m in re.finditer(rb'[A-Za-z][ -~]{3,30}(?=\x00)', b)).most_common(8)
        r['mem_files'] = sorted(os.listdir(os.path.join(jd, 'mem')))[:8] if os.path.isdir(os.path.join(jd, 'mem')) else None
        try:
            from piece_table import read_pieces
            P = read_pieces(jd); r['table_pieces'] = len(P)
            r['table_names'] = collections.Counter(p['name'][:14] for p in P.values()).most_common(10)
        except Exception as e:
            r['table_error'] = repr(e)[:120]
        C = []; E = []
        for f in sorted(os.listdir(os.path.join(jd, 'subm'))):
            if not f.isdigit(): continue
            rr = brep.parse(open(os.path.join(jd, 'subm', f), 'rb').read())
            if rr is None: continue
            V, Fc = rr; used = sorted({q for x in Fc for q in x})
            if not used: continue
            C.append(V[used].mean(0)); E.append(np.ptp(V[used], 0).max())
        if C:
            C = np.array(C); E = np.array(E)
            r['pieces_parsed'] = len(C); r['centre_std'] = np.round(C.std(0), 1).tolist(); r['centre_span'] = np.round(np.ptp(C, 0), 1).tolist()
            r['extent_median'] = round(float(np.median(E)), 2)
        # other folders that could hold placements
        r['dirs'] = sorted(d_ for d_ in os.listdir(jd))
    except Exception:
        r['error'] = traceback.format_exc()[-300:]
    shutil.rmtree(jd, ignore_errors=True)
    out.write(json.dumps(r, default=str) + '\n'); out.flush()
