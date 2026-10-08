"""Reference-model calibration diag: fetch main/ + mem/ of data-3 jobs (no subm), report type-string offsets per slot and
what read_members does with a given decoder tree. usage: refdiag.py <decode dir> <out.jsonl> <id8> ..."""
import sys, os, re, json, gzip, collections, traceback
from concurrent.futures import ThreadPoolExecutor
import boto3
sys.path.insert(0, sys.argv[1])
import sds2job
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
F = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/'
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
STR = rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|HORIZONTAL BRACE|MISC|STAIR|JOIST|Wall|Ref Point|DWF Import|IFC Import|SDNF Import|DGN Import|Reference Model|ReferenceModel|REFERENCE MODEL)\x00"
out = open(sys.argv[2], 'a')
for id8 in sys.argv[3:]:
    r = dict(id=id8)
    try:
        key = s3.list_objects_v2(Bucket=B, Prefix=F + id8)['Contents'][0]['Key']
        mf = json.loads(gzip.decompress(s3.get_object(Bucket=B, Key=key)['Body'].read()))
        jd = f'/work/agentwork/sds2v54/refjobs/{id8}'
        def one(f):
            parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
            if 'subm' in parts and parts[-1] != 'subm_idx':
                return
            if not any(p in ('main', 'mem', 'subm') for p in parts):
                return
            i = max(k for k, p in enumerate(parts) if p in ('main', 'mem', 'subm'))
            path = os.path.join(jd, *parts[i:]); os.makedirs(os.path.dirname(path), exist_ok=True)
            if not f.get('key'): open(path, 'wb').close(); return
            if not os.path.exists(path): s3.download_file(B, f['key'], path)
        with ThreadPoolExecutor(16) as ex: list(ex.map(one, mf))
        r['version'] = sds2job.read_version(jd)
        idx = open(os.path.join(jd, 'mem', 'mem_idx'), 'rb').read()
        ids = sorted(int(n) for n in os.listdir(os.path.join(jd, 'mem')) if n.isdigit())
        r['mem_idx'] = len(idx); r['ids'] = ids[:10]; r['n_ids'] = len(ids)
        slots = [s for s in (1280, 1416, 2494, 2944, 2976, 3204, 3404, 3600) if (len(idx) - 256) % s == 0 and (len(idx) - 256) // s > max(ids or [0])]
        r['slots'] = slots
        hits = [(m.start(), m.group(1).decode()) for m in re.finditer(STR, idx)]
        r['strings'] = collections.Counter(h[1] for h in hits).most_common(12)
        r['offsets'] = {s: collections.Counter(f'{t}@{p % s}' for p, t in hits).most_common(8) for s in slots}
        r['slot_of_hits'] = {s: sorted({p // s for p, t in hits})[:10] for s in slots}
        try:
            mem, L = sds2job.read_members(jd)
            r['layout'] = L; r['types'] = collections.Counter(m.type for m in mem).most_common(8)
        except Exception as e:
            r['read_members_error'] = f'{type(e).__name__}: {e}'
    except Exception as e:
        r['error'] = traceback.format_exc()[-600:]
    out.write(json.dumps(r) + '\n'); out.flush()
    print(json.dumps(r)[:600], flush=True)
