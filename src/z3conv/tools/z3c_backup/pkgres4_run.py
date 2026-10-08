"""pkg-resolver for DATA-4 (port of agentwork/pkg-resolver/code for data-3): sha256 -> stored Disk-1/2 key for the data-4 package files
whose extraction stored only a 'disk12:sha256:<hash>' pointer and that the packager could not resolve (unresolved:disk12:*).
Stages (resumable, outputs in /opt/pkgres4/work):
  1 scan   ranged reads of every Disk-1/2 per-archive result JSON (_state/ec2-results + _state/results) up to "extensions":
           which archives list each needed sha (res_hits.jsonl)
  2 cands  list those archives' extraction prefixes (old worker naming), candidate keys of EQUAL SIZE ranked
           path-suffix > basename > extension (cand.jsonl)
  3 prove  S3 SHA-256 of each candidate WITHOUT downloading: UploadPartCopy (CopySourceIfMatch=ETag) into a never-completed
           multipart upload with ChecksumAlgorithm=SHA256 under bim cad-disk-extract/_state/packaging/pkg-resolver-d4/_shaprobe/;
           every upload is aborted at the end (nothing stored) (verify.jsonl)
  4 map    proven rows {sha256, bytes, key, proof:'s3_sha256', bucket, etag, found_by, checked_at} + the existing data-3 map ->
           bim cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz (+ summary.json, unresolved_remaining)
READ-ONLY on every Disk-1/2 / data-4 object; writes only under cad-disk-extract/_state/packaging/pkg-resolver-d4/."""
import json, gzip, re, hashlib, collections, os, sys, time, base64, uuid, threading, pickle
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor

B = 'bim-proprietary-data'; W = '/opt/pkgres4/work'; OUTP = 'cad-disk-extract/_state/packaging/pkg-resolver-d4/'
OLDMAP = ('annotationprod', 'cad-disk-extract/agentwork/pkg-resolver/disk12_sha_map.jsonl.gz')
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=128, retries={'max_attempts': 10, 'mode': 'standard'}))
os.makedirs(W, exist_ok=True)
STAGES = (sys.argv[1] if len(sys.argv) > 1 else '1234')


def log(*a):
    print(time.strftime('%H:%M:%SZ', time.gmtime()), *a, flush=True)


def sc(v):
    v = re.sub(r"[^A-Za-z0-9._!+\-]+", "_", v)
    return re.sub(r"_+", "_", v).strip("_") or "_"


def _san(s): return re.sub(r'[^A-Za-z0-9._-]+', '_', s)
def _lk(p): return re.sub(r'[^a-z0-9]+', '', p.lower())
def ext(p):
    b = p.rsplit('/', 1)[-1].lower(); return b.rsplit('.', 1)[-1] if '.' in b else ''


# ---------------------------------------------------------------- needed items (data-4 unresolved disk12 files)
un = json.load(open('/opt/pkgd4r3/unresolved_all.json'))
items = collections.defaultdict(lambda: {'bytes': None, 'paths': set(), 'projects': set()})
for pid, us in un.items():
    if not pid.startswith('Zentitude-data-4__'):
        continue
    for u in us:
        it = items[u['sha256']]; it['bytes'] = u['bytes']; it['projects'].add(pid)
        it['paths'].add(u['path'].split(' :: ', 1)[1] if ' :: ' in u['path'] else u['path'].split('/', 1)[-1])
log('need sha', len(items), 'files', sum(len(v) for k, v in un.items() if k.startswith('Zentitude-data-4__')))

# ---------------------------------------------------------------- 1 scan
HITS = f'{W}/res_hits.jsonl'
if '1' in STAGES and not os.path.exists(HITS + '.done'):
    keys = []
    for pre in ('cad-disk-extract/_state/ec2-results/', 'cad-disk-extract/_state/results/'):
        for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=pre):
            keys += [(o['Key'], o['Size']) for o in pg.get('Contents', []) if o['Key'].endswith('.json')]
    log('result files', len(keys), round(sum(s for _, s in keys) / 1e9, 1), 'GB')
    lock = threading.Lock(); st = collections.Counter(); out = open(HITS, 'w')

    def one(ks):
        k, size = ks; buf = b''; pos = 0; step = 1 << 20; i = -1
        while True:
            end = min(size, pos + step) - 1
            buf += s3.get_object(Bucket=B, Key=k, Range=f'bytes={pos}-{end}')['Body'].read(); pos = end + 1
            i = buf.find(b'"extensions"')
            if i >= 0 or pos >= size: break
            step = min(step * 2, 64 << 20)
        txt = buf[:i].decode('utf-8', 'surrogateescape').rstrip().rstrip(',') + '}' if i >= 0 else buf.decode('utf-8', 'surrogateescape')
        d = json.loads(txt); hits = {}
        for cat, lst in (d.get('sha256') or {}).items():
            for h in lst:
                if h in items: hits.setdefault(h, cat)
        rec = {'result_key': k, 'source_key': d.get('source_key'), 'disk': d.get('disk'), 'status': d.get('status'), 'hits': hits}
        with lock:
            out.write(json.dumps(rec) + '\n'); st['done'] += 1; st['bytes'] += len(buf); st['hits'] += len(hits)
            if st['done'] % 250 == 0: log('scan', dict(st))
    for attempt in range(3):
        try:
            with ThreadPoolExecutor(32) as ex: list(ex.map(one, keys))
            break
        except Exception as e:
            log('scan error, retry whole stage', type(e).__name__, e); out.close(); out = open(HITS, 'w'); st.clear()
    out.close(); open(HITS + '.done', 'w').write('ok'); log('scan done', dict(st))

res = [json.loads(l) for l in open(HITS)] if os.path.exists(HITS) else []
arch_of = collections.defaultdict(list); cat_of = collections.Counter()
for r in res:
    for h, cat in r['hits'].items():
        arch_of[h].append(r['source_key']); cat_of[cat] += 1
log('sha found in some Disk-1/2 result', len(arch_of), 'of', len(items), 'categories', dict(cat_of))

# ---------------------------------------------------------------- 2 candidates
CAND = f'{W}/cand.jsonl'
if '2' in STAGES and not os.path.exists(CAND + '.done'):
    archives = sorted({a for v in arch_of.values() for a in v})
    LST = f'{W}/listings.pkl'
    listing = pickle.load(open(LST, 'rb')) if os.path.exists(LST) else {}

    def prefixes(source_key):
        disk, rel = source_key.split('/', 1); h12 = hashlib.sha256(source_key.encode()).hexdigest()[:12]; out = []
        for flat in (sc(rel)[:240], _san(rel)):
            for p in (f'cad-disk-extract/{disk}/{flat}-{h12}/', f'cad-disk-extract/{disk}/{flat}/'):
                if p not in out: out.append(p)
        return out

    def do_list(a):
        if a in listing: return a, listing[a]
        got = []
        for p in prefixes(a):
            ks = []
            for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=p):
                ks += [(o['Key'], o['Size'], o['ETag'].strip('"')) for o in pg.get('Contents', [])]
            if ks: got.append((p, ks))
        return a, got
    with ThreadPoolExecutor(48) as ex:
        for a, got in ex.map(do_list, archives): listing[a] = got
    pickle.dump(listing, open(LST, 'wb'))
    log('archives', len(archives), 'listed keys', sum(len(ks) for g in listing.values() for _, ks in g),
        'archives without a prefix', sum(1 for a in archives if not listing[a]))
    idx = {}
    for a in archives:
        bysize = collections.defaultdict(list)
        for p, ks in listing[a]:
            for k, sz, et in ks: bysize[sz].append((k[len(p):], k, et))
        idx[a] = bysize
    out = open(CAND, 'w'); stat = collections.Counter()
    for sha, it in items.items():
        nb = it['bytes']; seen = set(); ranked = []
        tok = [[sc(c) for c in pth.replace('!/', '/').split('/')] for pth in it['paths']]
        exts = {ext(pth) for pth in it['paths']}; bases = {_lk(pth.rsplit('/', 1)[-1]) for pth in it['paths']}
        for a in arch_of.get(sha, []):
            for member, k, et in idx[a].get(nb, []):
                if k in seen: continue
                best = None
                for t in tok:
                    for i in range(len(t)):
                        suf = '/'.join(t[i:])
                        if member == suf or member.endswith('/' + suf): best = (len(t) - i, 'path_suffix'); break
                    if best: break
                if best is None and _lk(member.rsplit('/', 1)[-1]) in bases: best = (0, 'basename')
                if best is None and ext(member) in exts: best = (-1, 'size_ext')
                if best is None: continue
                seen.add(k); ranked.append((best[0], k, et, best[1]))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        stat[ranked[0][3] if ranked else ('no_result_lists_sha' if sha not in arch_of else 'no_equal_size_key')] += 1
        out.write(json.dumps({'sha': sha, 'bytes': nb, 'archives': arch_of.get(sha, [])[:8], 'projects': sorted(it['projects']),
                              'paths': sorted(it['paths'])[:3], 'cands': [[k, et, how] for _, k, et, how in ranked[:8]], 'n_cands': len(ranked)}) + '\n')
    out.close(); open(CAND + '.done', 'w').write(json.dumps(stat)); log('candidates', dict(stat))

# ---------------------------------------------------------------- 3 prove
VER = f'{W}/verify.jsonl'
if '3' in STAGES and not os.path.exists(VER + '.done'):
    cands = {}; nbytes = {}
    for l in open(CAND):
        r = json.loads(l); cands[r['sha']] = r['cands']; nbytes[r['sha']] = r['bytes']
    done = collections.defaultdict(list)
    if os.path.exists(VER):
        for l in open(VER):
            r = json.loads(l); done[r['want']].append(r)
    MAXTRY = 6
    todo = [s for s in cands if cands[s] and not any(x['match'] for x in done[s]) and len(done[s]) < min(MAXTRY, len(cands[s]))]
    log('prove: shas with candidates', sum(1 for s in cands if cands[s]), 'todo', len(todo))
    lock = threading.Lock(); mpus = []; state = {'mpu': None, 'part': 10000}; n = collections.Counter()
    reg = open(f'{W}/mpu_ids.txt', 'a'); out = open(VER, 'a')

    def next_slot():
        with lock:
            if state['part'] >= 10000:
                k = OUTP + '_shaprobe/' + time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
                m = s3.create_multipart_upload(Bucket=B, Key=k, ChecksumAlgorithm='SHA256')
                state['mpu'] = (k, m['UploadId']); state['part'] = 0; mpus.append(state['mpu']); reg.write(f"{k}\t{m['UploadId']}\n"); reg.flush()
            state['part'] += 1
            return state['mpu'], state['part']

    def one(sha):
        tried = {x['key'] for x in done[sha]}
        for k, et, how in cands[sha]:
            if k in tried: continue
            if len(tried) >= MAXTRY: break
            tried.add(k)
            try:
                (dk, uid), pn = next_slot()
                r = s3.upload_part_copy(Bucket=B, Key=dk, UploadId=uid, PartNumber=pn, CopySource={'Bucket': B, 'Key': k},
                                        CopySourceIfMatch='"' + et + '"')
                got = base64.b64decode(r['CopyPartResult']['ChecksumSHA256']).hex()
                rec = {'want': sha, 'bytes': nbytes[sha], 'key': k, 'etag': et, 'how': how, 'sha256': got, 'match': got == sha,
                       'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            except Exception as e:
                rec = {'want': sha, 'bytes': nbytes[sha], 'key': k, 'etag': et, 'how': how, 'sha256': None, 'match': False, 'error': str(e)[:200]}
            with lock:
                out.write(json.dumps(rec) + '\n'); n['tried'] += 1; n['ok'] += rec['match']; n['err'] += 'error' in rec
                if n['tried'] % 5000 == 0: log('prove', dict(n)); out.flush()
            if rec['match']: return
    try:
        with ThreadPoolExecutor(96) as ex: list(ex.map(one, todo))
    finally:
        out.close()
        for k, uid in mpus:
            for a in range(5):
                try: s3.abort_multipart_upload(Bucket=B, Key=k, UploadId=uid); break
                except Exception as e: log('abort retry', k, e); time.sleep(2)
        open(f'{W}/mpu_aborted.txt', 'a').write(''.join(f'{k}\t{uid}\n' for k, uid in mpus))
        log('prove done', dict(n), 'multipart uploads aborted', len(mpus))
    open(VER + '.done', 'w').write(json.dumps(n))

# ---------------------------------------------------------------- 4 map
if '4' in STAGES:
    proven = {}
    for l in open(VER):
        r = json.loads(l)
        if r['match'] and r['want'] not in proven:
            proven[r['want']] = {'sha256': r['want'], 'bytes': r['bytes'], 'key': r['key'], 'proof': 's3_sha256', 'bucket': B, 'etag': r['etag'],
                                 'found_by': 'd4_results_archive_' + r['how'], 'checked_at': r['at']}
    old = gzip.decompress(s3.get_object(Bucket=OLDMAP[0], Key=OLDMAP[1])['Body'].read()).decode().splitlines()
    rows = {}
    for l in old:
        if l.strip():
            x = json.loads(l); rows[x['sha256']] = x
    n_old = len(rows)
    for sha, x in proven.items(): rows.setdefault(sha, x)
    body = gzip.compress(''.join(json.dumps(x) + '\n' for x in rows.values()).encode())
    s3.put_object(Bucket=B, Key=OUTP + 'disk12_sha_map_all.jsonl.gz', Body=body, ContentType='application/gzip')
    left = collections.Counter(); rem = []
    for l in open(CAND):
        r = json.loads(l)
        if r['sha'] not in proven:
            why = 'no_result_lists_sha' if not r['archives'] else ('no_equal_size_key' if not r['cands'] else 'candidates_hash_differently')
            left[why] += 1; rem.append(dict(r, why=why))
    s3.put_object(Bucket=B, Key=OUTP + 'unresolved_remaining.jsonl.gz', Body=gzip.compress(''.join(json.dumps(x) + '\n' for x in rem).encode()))
    files_res = sum(len([1 for u in us if u['sha256'] in proven]) for p, us in un.items() if p.startswith('Zentitude-data-4__'))
    summ = {'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'need_sha': len(items), 'proven_sha': len(proven),
            'files_resolved': files_res, 'unresolved_sha_by_reason': dict(left), 'map_rows_old': n_old, 'map_rows_all': len(rows),
            'found_by': dict(collections.Counter(x['found_by'] for x in proven.values()))}
    s3.put_object(Bucket=B, Key=OUTP + 'summary.json', Body=json.dumps(summ, indent=1).encode(), ContentType='application/json')
    json.dump(summ, open(f'{W}/summary.json', 'w'), indent=1); log('MAP', summ)
