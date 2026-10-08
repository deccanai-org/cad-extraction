#!/usr/bin/env python3
"""Ground-truth pair scan (runs in-region). For every Tekla DB1 job (Disk-1/2 census, data-4 jobs, data-3 jobs):
list the model folder, find Tekla IFC exports and DSTV NC1 files; for each Tekla IFC join its element Tags ('ID<guid>')
with the GUID strings stored in the DB1 -> same-model evidence + fastener/opening counts. Output JSONL (one row per DB1).
  pairscan.py JOBS_JSON OUT_JSONL [threads]"""
import sys, os, re, json, gzip, zlib, io, time, threading, concurrent.futures as cf, collections
import boto3, botocore
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1', config=botocore.config.Config(max_pool_connections=96, retries={'max_attempts': 8, 'mode': 'standard'}))
RXG = re.compile(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
RXT = re.compile(rb"'ID([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})'")
RXF = re.compile(rb"IFCMECHANICALFASTENER\('[^']*',[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,'ID([0-9A-Fa-f-]{36})'")
MAX_IFC = 300 << 20; MAX_DB1 = 400 << 20; MAX_LIST = 20000
BIG = threading.BoundedSemaphore(3)      # at most 3 large downloads/decompressions in flight (memory)

def listing(prefix):
    out = []; tok = None
    while True:
        kw = dict(Bucket=B, Prefix=prefix, MaxKeys=1000)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += [(o['Key'], o['Size']) for o in r.get('Contents', [])]
        if not r.get('IsTruncated') or len(out) >= MAX_LIST: break
        tok = r['NextContinuationToken']
    return out

def head_bytes(key, n):
    return s3.get_object(Bucket=B, Key=key, Range=f'bytes=0-{n - 1}')['Body'].read()

def get(key):
    return s3.get_object(Bucket=B, Key=key)['Body'].read()

def stream_guids(key):
    """GUID strings of a (gzip) DB1, streamed in 16 MB chunks with overlap (no full decompression in memory)"""
    body = s3.get_object(Bucket=B, Key=key)['Body']; first = body.read(2); out = set(); tail = b''
    dec = zlib.decompressobj(16 + zlib.MAX_WBITS) if first == b'\x1f\x8b' else None
    buf = first
    while True:
        chunk = body.read(16 << 20)
        if not chunk and not buf: break
        data = (buf + chunk) if buf else chunk; buf = b''
        if dec is not None:
            try: data = dec.decompress(data)
            except Exception: break
        s = tail + data
        out.update(x.decode().upper() for x in RXG.findall(s))
        tail = s[-64:]
        if not chunk: break
    return out

def ifc_scan(key):
    """tags + fastener tags + counts, streamed line-wise"""
    body = s3.get_object(Bucket=B, Key=key)['Body']; T = set(); F = set(); op = parts = 0
    for line in body.iter_lines(chunk_size=1 << 20):
        if b"'ID" in line:
            m = RXT.search(line)
            if m: T.add(m.group(1).decode().upper())
            m = RXF.search(line)
            if m: F.add(m.group(1).decode().upper())
        if b'IFCOPENINGELEMENT(' in line: op += 1
        if b'IFCBEAM(' in line or b'IFCCOLUMN(' in line or b'IFCPLATE(' in line or b'IFCMEMBER(' in line: parts += 1
    return T, F, op, parts

def inflate(raw):
    if raw[:2] != b'\x1f\x8b': return raw
    try: return gzip.decompress(raw)
    except Exception: return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)

def engine_of(key):
    try:
        raw = head_bytes(key, 65536)
        d = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
        m = re.search(rb'(\d+\.\d+)', d[:16]); return m.group(1).decode() if m else None
    except Exception as e:
        return 'err:' + type(e).__name__

def scan(job):
    key = job['key']; row = dict(job); t0 = time.time()
    folder = key.rsplit('/', 1)[0] + '/'
    try:
        L = listing(folder)
    except Exception as e:
        row['error'] = 'list:' + str(e)[:100]; return row
    row['folder_objects'] = len(L)
    ifcs = [(k, s) for k, s in L if k.lower().endswith('.ifc') and 2000 < s < MAX_IFC]
    nc = [(k, s) for k, s in L if re.search(r'\.(nc1|nc)$', k.lower())]
    rep = [(k, s) for k, s in L if re.search(r'\.(xsr|csv|xls|xlsx|txt)$', k.lower()) and 'report' in k.lower()]
    row['nc_count'] = len(nc); row['nc_sample'] = [k for k, s in nc[:5]]
    row['nc_dirs'] = sorted(collections.Counter(k.rsplit('/', 1)[0] for k, s in nc).items(), key=lambda x: -x[1])[:5]
    row['reports'] = len(rep)
    row['db1_siblings'] = sum(1 for k, s in L if k.lower().endswith('.db1') and k != key)
    if not row.get('engine'): row['engine'] = engine_of(key)
    out = []; G = None
    for k, s in sorted(ifcs, key=lambda x: x[1])[:12]:
        try:
            h = head_bytes(k, 3000)
        except Exception:
            continue
        tek = b'Tekla Structures' in h or b'Tekla structures' in h
        rec = dict(key=k, size=s, tekla=tek, grid=b'GridExporter' in h)
        m = re.search(rb"FILE_NAME\s*\(\s*'([^']*)'", h); rec['file_name'] = m.group(1).decode('latin1')[-100:] if m else None
        m = re.search(rb"Tekla [Ss]tructures[^'\n]{0,60}", h); rec['tekla_ver'] = m.group(0).decode('latin1') if m else None
        if tek and not rec['grid']:
            try:
                if s > (50 << 20):
                    with BIG: T, F, op, parts = ifc_scan(k)
                else:
                    T, F, op, parts = ifc_scan(k)
                rec.update(tags=len(T), fasteners=len(F), openings=op, parts=parts)
                if T and (job.get('size') or 0) < MAX_DB1:
                    if G is None:
                        if (job.get('size') or 0) > (30 << 20):
                            with BIG: G = stream_guids(key)
                        else:
                            G = stream_guids(key)
                        row['db1_guids'] = len(G)
                    rec['joined'] = len(T & G); rec['fast_joined'] = len(F & G)
                    rec['join_frac'] = round(len(T & G) / len(T), 4)
            except Exception as e:
                rec['error'] = type(e).__name__ + ':' + str(e)[:80]
        out.append(rec)
    row['ifcs'] = out; row['sec'] = round(time.time() - t0, 1)
    return row

if __name__ == '__main__':
    jobs = json.load(open(sys.argv[1])); outp = sys.argv[2]; th = int(sys.argv[3]) if len(sys.argv) > 3 else 48
    done = set()
    if os.path.exists(outp):
        for l in open(outp):
            try: done.add(json.loads(l)['key'])
            except Exception: pass
    jobs = [j for j in jobs if j['key'] not in done]
    lock = threading.Lock(); n = 0; t0 = time.time()
    with open(outp, 'a') as fo, cf.ThreadPoolExecutor(th) as ex:
        for r in ex.map(scan, jobs):
            with lock:
                fo.write(json.dumps(r) + '\n'); fo.flush(); n += 1
                if n % 200 == 0: print(n, len(jobs), round(time.time() - t0), flush=True)
    print('DONE', n, flush=True)
