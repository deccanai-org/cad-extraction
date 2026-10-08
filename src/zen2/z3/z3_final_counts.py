"""Data-3 final counts (runs on the coordinator with the instance role), one pass over every manifest row.

Pass A (per manifest, parallel): for every row
  - ext (same normaliser as stats_agg), size, sha64, loose flag
  - old = the content is in the Disk-1/2 + Z4 index (prior_sha64.bin: size > 0 and sha64 in the index; the same test the
    worker used for the first copy). Every copy counts, not just the first one in an archive.
  - SDS2 job folders (parent of main/jsetup or mem/mem_idx): rows inside them, old / new
  - PDF rows: sha256, size, worker class, old, loose, where the bytes live (key)
Pass B: PDFs the worker left 'unknown' -> data-4's resolved per-sha class (classes.sqlite) -> the Disk-1/2 run's per-sha class
  (union.sqlite cad_pdf / other_pdf) -> whole-file pdfinfo (producer/creator + page sizes; data-4 rule).
Writes <ROOT>/_state/stats/final_counts.json and the corrected pdf_classes.json; ext_summary.json gets the corrected old/new raw
counts (unique counts are unchanged: they already come from distinct sha256)."""
import boto3, json, gzip, os, re, sys, time, sqlite3, subprocess, tempfile, collections, threading
import numpy as np
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from botocore.config import Config

B = 'bim-proprietary-data'; ROOT = 'cad-disk-extract/zenitude-data-3'; Z4 = 'cad-disk-extract/zentitude-data-4'
CTL_B = 'annotationprod'; CTL = 'cad-disk-extract/_control/move/z3'
W = os.environ.get('FC_WORK', '/work/z3final')
D4_DB = f'{Z4}/_state/box_backup/cad-zen2-files/work/pdfcache/classes.sqlite'
UNION = f'{Z4}/_state/box_backup/cad-zen2-files/work/idx/union.sqlite'
_c = {}


def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 40, 'mode': 'standard'},
                                                                            max_pool_connections=100, read_timeout=300))
    return _c['c']


def ext_of(base):                                       # = stats_agg.ext_of applied to the file name
    base = base.lower()
    if '.' not in base:
        return '(none)'
    e = base.rsplit('.', 1)[-1]
    if len(e) > 12 or not e.replace('_', '').isalnum():
        return '(other)'
    if len(e) == 4 and e[0] in 'jmp' and e[1:].isdigit():
        return e[0] + '###'
    if e.startswith('p_'):
        return 'p_*'
    return e


PRIOR = None


def load_prior():
    global PRIOR
    if PRIOR is None:
        p = os.path.join(W, 'prior_sha64.bin')
        PRIOR = np.fromfile(p, dtype='<u8')
        PRIOR.sort()
    return PRIOR


def is_old(h, size):
    if size <= 0:
        return False
    P = load_prior()
    i = np.searchsorted(P, np.uint64(h))
    return i < len(P) and P[i] == np.uint64(h)


def pass_a(jid):
    """-> (jid, by_ext {ext: [raw, bytes, old_raw, old_bytes]}, loose {..same..}, sds2 [files, bytes, old_files, old_bytes, roots],
           pdf rows file path, rows)"""
    out_pdf = os.path.join(W, 'pdf', jid + '.json')
    tmp = os.path.join(W, 'm', jid + '.jsonl.gz')
    s3().download_file(B, f'{ROOT}/_state/manifests/{jid}.jsonl.gz', tmp)
    P = load_prior()
    by_ext, loose = {}, {}
    rows = 0
    paths, hs, szs = [], [], []
    roots = set()
    pdf = []
    any_loose = False
    with gzip.open(tmp, 'rb') as fh:
        for line in fh:
            if len(line) < 3:
                continue
            e = json.loads(line)
            p = e['path']; size = e.get('size') or 0; sha = e['sha256']; h = int(sha[:16], 16)
            base = p[p.rfind('/') + 1:]
            x = ext_of(base)
            paths.append(p); hs.append(h); szs.append(size)
            rows += 1
            lb = base.lower()
            if lb in ('jsetup', 'mem_idx'):
                parent = p[:p.rfind('/') + 1] if '/' in p else ''
                pl = parent.lower()
                if lb == 'jsetup' and pl.endswith('main/'):
                    roots.add(parent[:-len('main/')])
                elif lb == 'mem_idx' and pl.endswith('mem/'):
                    roots.add(parent[:-len('mem/')])
            if x == 'pdf':
                pdf.append([sha, size, e.get('pdf_class'), e.get('key') or '', 1 if e.get('loose') else 0, len(paths) - 1])
            if e.get('loose'):
                any_loose = True
    h = np.array(hs, dtype=np.uint64); sz = np.array(szs, dtype=np.int64)
    i = np.searchsorted(P, h); i[i >= len(P)] = 0
    old = (P[i] == h) & (sz > 0)
    # per-ext tallies
    exts = [ext_of(p[p.rfind('/') + 1:]) for p in paths]
    for x, s, o in zip(exts, sz.tolist(), old.tolist()):
        t = by_ext.get(x)
        if t is None:
            t = by_ext[x] = [0, 0, 0, 0]
        t[0] += 1; t[1] += s
        if o:
            t[2] += 1; t[3] += s
    # loose subset (loose-folder manifests hold only loose rows)
    if any_loose:
        loose = {k: list(v) for k, v in by_ext.items()}
    # SDS2: rows inside a job folder (any ancestor folder of the path is a job root)
    sds = [0, 0, 0, 0, len(roots)]
    if roots:
        top = '' in roots

        def in_job(p):
            if top:
                return True
            i = p.find('/')
            while i >= 0:
                if p[:i + 1] in roots:
                    return True
                i = p.find('/', i + 1)
            return False
        for p, s, o in zip(paths, sz.tolist(), old.tolist()):
            if in_job(p):
                sds[0] += 1; sds[1] += s
                if o:
                    sds[2] += 1; sds[3] += s
    for r in pdf:
        r.append(bool(old[r.pop(5)]))
    json.dump(pdf, open(out_pdf, 'w'))
    os.remove(tmp)
    return jid, by_ext, loose, sds, rows, len(pdf)


# ---------------- pass B: PDF classes ----------------
def pdf_rules():
    src = open(os.path.join(W, 'pdf_classify.py')).read()
    ns = {'re': re}
    exec(src[src.index('CAD = re.compile'):src.index('def classify')], ns)
    return ns['CAD'], ns['DOC']


SIZE = re.compile(r'Page\s+\d+\s+size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts')


def find_key(sha, keys):
    for k in keys:
        if k.startswith('cad-disk-extract/'):
            return k
        if k.startswith('src:'):
            return k[4:]
    for marker in (f'{ROOT}/_state/sha/{sha[:2]}/{sha}', f'{Z4}/_state/sha/{sha[:2]}/{sha}'):
        try:
            k = s3().get_object(Bucket=B, Key=marker)['Body'].read().decode().strip()
            if k.startswith('cad-disk-extract/'):
                return k
        except Exception:
            pass
    return None


def full_parse(args):
    sha, keys, CAD, DOC = args
    key = find_key(sha, keys)
    if not key:
        return sha, 'unknown', 'full:no_copy'
    try:
        size = s3().head_object(Bucket=B, Key=key)['ContentLength']
        d = '/dev/shm' if size < 300_000_000 else W
        with tempfile.NamedTemporaryFile(dir=d, suffix='.pdf') as t:
            s3().download_fileobj(B, key, t); t.flush()
            r = subprocess.run(['pdfinfo', '-f', '1', '-l', '5', t.name], capture_output=True, timeout=120)
        out, err = r.stdout.decode('latin-1'), r.stderr.decode('latin-1')
    except subprocess.TimeoutExpired:
        return sha, 'unknown', 'full:timeout'
    except Exception:
        return sha, 'unknown', 'full:read_error'
    meta = ' '.join(l.split(':', 1)[1].strip() for l in out.splitlines() if l.startswith(('Producer:', 'Creator:'))).encode('latin-1', 'replace')
    big = max([max(float(w), float(h)) for w, h in SIZE.findall(out)] or [0])
    if meta and CAD.search(meta):
        return sha, 'cad', 'full:producer'
    if big >= 1190:
        return sha, 'cad', 'full:page>=A3'
    if meta and DOC.search(meta):
        return sha, 'document', 'full:producer'
    if big > 0:
        return sha, 'document', 'full:page<A3'
    if 'Incorrect password' in err or 'encrypt' in err.lower():
        return sha, 'unknown', 'full:encrypted'
    return sha, 'unknown', 'full:not_a_pdf' if ('May not be a PDF' in err or 'Syntax Error' in err) else 'full:no_pages'


def patch_ext_summary(final, ts):
    """ext_summary.json: replace the old/new RAW split (worker flagged only the first copy per archive) with the content-based one
    from final_counts; unique / new-unique counts are untouched. Raw files per extension must agree exactly, else no patch."""
    c = s3()
    key = f'{ROOT}/_state/stats/ext_summary.json'
    es = json.loads(c.get_object(Bucket=B, Key=key)['Body'].read())
    src = open(os.path.join(W, 'stats_agg.py')).read()
    ns = {}
    exec(src[src.index('CATS = {'):src.index('def list_keys')], ns)
    cat_of = ns['cat_of']
    bad = []

    def fix_rows(rows, fc):
        for r in rows:
            v = fc.get(r['type'])
            if not v or v[0] != r['files'] or v[1] != r['bytes']:
                bad.append([r['type'], r['files'], v[:2] if v else None]); continue
            r['prior_files'], r['prior_bytes'] = v[2], v[3]
            r['new_files'], r['new_bytes'] = r['files'] - v[2], r['bytes'] - v[3]

    def cats(rows):
        d = collections.defaultdict(collections.Counter)
        for r in rows:
            d[cat_of(r['type'])].update({k: v for k, v in r.items() if k != 'type'})
        return sorted(({'type': k, **dict(v)} for k, v in d.items()), key=lambda r: -r['files'])

    fix_rows(es['by_extension'], final['by_ext'])
    fix_rows(es.get('loose_by_extension') or [], final['loose_by_ext'])
    if bad:
        print('ext_summary NOT patched, raw mismatch:', bad[:20], flush=True)
        return
    es['by_category'] = cats(es['by_extension']); es['loose_by_category'] = cats(es.get('loose_by_extension') or [])
    for tk, rows in (('totals', es['by_extension']), ('loose', es.get('loose_by_extension') or [])):
        t = es[tk]
        t['prior_files'] = sum(r['prior_files'] for r in rows); t['prior_bytes'] = sum(r['prior_bytes'] for r in rows)
        t['new_files'] = t['files'] - t['prior_files']; t['new_bytes'] = t['bytes'] - t['prior_bytes']
    sd, fs = es.get('sds2') or {}, final['sds2']
    if sd and sd.get('files') == fs['files']:
        sd['files_prior'] = fs['files_old']; sd['files_new'] = fs['files'] - fs['files_old']
    else:
        print('sds2 not patched', sd.get('files'), fs['files'], flush=True)
    es['new_rule'] = ('new = content whose sha256 is not in the Disk-1 / Disk-2 / Z4 index; raw old/new counts every copy by content '
                      '(final_counts.json), unique counts each content once')
    es['raw_split_from'] = f'final_counts.json {ts}'
    c.put_object(Bucket=B, Key=key, Body=json.dumps(es).encode(), ContentType='application/json')
    print('ext_summary patched: totals', {k: es['totals'][k] for k in ('files', 'prior_files', 'new_files', 'unique_files', 'new_unique')}, flush=True)


def main():
    os.makedirs(os.path.join(W, 'm'), exist_ok=True); os.makedirs(os.path.join(W, 'pdf'), exist_ok=True)
    c = s3()
    for key, dst in ((f'{CTL}/prior_sha64.bin', 'prior_sha64.bin'),):
        if not os.path.exists(os.path.join(W, dst)):
            c.download_file(CTL_B, key, os.path.join(W, dst))
    jobs = json.loads(c.get_object(Bucket=CTL_B, Key=f'{CTL}/jobs.json')['Body'].read())
    jobs = jobs['jobs'] if isinstance(jobs, dict) else jobs
    size = {j['id']: j.get('size') or 0 for j in jobs}
    ids = sorted(size, key=lambda j: -size[j])
    if len(sys.argv) > 1 and sys.argv[1] != 'all':
        ids = [j for j in ids if j in sys.argv[1:]]
    t0 = time.time()
    by_ext, loose, sds, rows, npdf, per = {}, {}, [0, 0, 0, 0, 0], 0, 0, {}
    with ProcessPoolExecutor(int(os.environ.get('FC_PROCS', '16'))) as ex:
        for n, (jid, be, lo, sd, r, npf) in enumerate(ex.map(pass_a, ids, chunksize=1)):
            for k, v in be.items():
                t = by_ext.setdefault(k, [0, 0, 0, 0])
                for i in range(4): t[i] += v[i]
            for k, v in lo.items():
                t = loose.setdefault(k, [0, 0, 0, 0])
                for i in range(4): t[i] += v[i]
            for i in range(5): sds[i] += sd[i]
            rows += r; npdf += npf; per[jid] = r
            if n % 250 == 0:
                print(time.strftime('%H:%M:%S'), 'pass A', n, '/', len(ids), 'rows', rows, round(time.time() - t0), 's', flush=True)
    print('pass A done: rows', rows, 'pdf rows', npdf, round(time.time() - t0), 's', flush=True)
    # ---- pass B
    import glob
    pdf_rows = []
    for f in glob.glob(os.path.join(W, 'pdf', '*.json')):
        if os.path.basename(f)[:-5] in per:
            pdf_rows += json.load(open(f))
    cls = {}; keys = collections.defaultdict(list); why = collections.Counter()
    for sha, sz, pc, key, lo, old in pdf_rows:
        v = pc[0] if isinstance(pc, (list, tuple)) and pc else pc
        if v in ('cad', 'document'):
            cls[sha] = (v, 'worker')
        if key and len(keys[sha]) < 3:
            keys[sha].append(key)
    unk = sorted({r[0] for r in pdf_rows} - set(cls))
    print('unique pdf', len({r[0] for r in pdf_rows}), 'worker-classified', len(cls), 'unknown', len(unk), flush=True)
    for name, key in (('classes.sqlite', D4_DB), ('union.sqlite', UNION)):
        if not os.path.exists(os.path.join(W, name)):
            c.download_file(B, key, os.path.join(W, name))
    d4 = sqlite3.connect(f'file:{W}/classes.sqlite?mode=ro', uri=True)
    un = sqlite3.connect(f'file:{W}/union.sqlite?mode=ro', uri=True)
    q = "SELECT 1 FROM digests WHERE disk=? AND kind='sha' AND bucket=? AND digest=?"
    rest = []
    for sha in unk:
        r = d4.execute('SELECT cls FROM cls WHERE sha=?', (sha,)).fetchone()
        if r and r[0] in ('cad', 'document'):
            cls[sha] = (r[0], 'data4_index'); continue
        d = bytes.fromhex(sha)
        cad = any(un.execute(q, (k, 'cad_pdf', d)).fetchone() for k in ('Disk-1', 'Disk-2'))
        oth = any(un.execute(q, (k, 'other_pdf', d)).fetchone() for k in ('Disk-1', 'Disk-2'))
        if cad or oth:
            cls[sha] = ('cad' if cad else 'document', 'disk12_index'); continue
        rest.append(sha)
    print('after indexes: still unknown', len(rest), flush=True)
    CAD, DOC = pdf_rules()
    with ThreadPoolExecutor(64) as ex:
        for i, (sha, v, w) in enumerate(ex.map(full_parse, [(s, keys.get(s, []), CAD, DOC) for s in rest])):
            cls[sha] = (v, w)
            if i % 5000 == 0:
                print(time.strftime('%H:%M:%S'), 'full parse', i, '/', len(rest), flush=True)
    for sha, (v, w) in cls.items():
        why[(v, w.split(':')[0] if w.startswith('full') else w, w if w.startswith('full') else '')] += 1
    # ---- PDF tallies (raw = every row; unique = distinct sha; old = content in Disk-1/2/Z4; new = the rest)
    def tally(rs):
        T = {k: {'raw': 0, 'unique': 0, 'new_raw': 0, 'new_unique': 0, 'raw_bytes': 0, 'unique_bytes': 0, 'new_unique_bytes': 0}
             for k in ('cad', 'document', 'unknown')}
        seen = {}
        for sha, sz, pc, key, lo, old in rs:
            k = cls.get(sha, ('unknown', ''))[0]
            t = T[k]; t['raw'] += 1; t['raw_bytes'] += sz
            if not old: t['new_raw'] += 1
            if sha not in seen:
                seen[sha] = 1; t['unique'] += 1; t['unique_bytes'] += sz
                if not old: t['new_unique'] += 1; t['new_unique_bytes'] += sz
        u = len(seen); nu = sum(t['new_unique'] for t in T.values())
        return {'pdf_paths': len(rs), 'pdf_unique': u, 'pdf_new_unique': nu, 'classes': T}
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    pc_out = dict(tally(pdf_rows), updated=ts, jobs_counted=len(per), loose=tally([r for r in pdf_rows if r[4]]),
                  sources={f'{a}|{b}|{w}': n for (a, b, w), n in why.items()},
                  rule='cad = CAD/plot producer or page >= A3; document = office/scanner producer or smaller page. Class from the extraction '
                       "worker's head/tail read; PDFs it could not read were resolved from data-4's per-sha class, then the Disk-1/2 run's "
                       'per-sha class, then a whole-file pdfinfo read (sources). old/new by content: new = sha256 not in Disk-1/2/Z4.')
    final = {'checked_at': ts, 'jobs': len(per), 'rows': rows, 'by_ext': by_ext, 'loose_by_ext': loose,
             'sds2': {'files': sds[0], 'bytes': sds[1], 'files_old': sds[2], 'bytes_old': sds[3], 'job_folders': sds[4]},
             'pdf_rows': len(pdf_rows), 'seconds': round(time.time() - t0),
             'rule': 'every manifest row; old = size > 0 and the content sha64 is in the Disk-1/2 + Z4 index (every copy, not only the first '
                     'copy per archive); new = the rest'}
    if len(sys.argv) > 1 and sys.argv[1] != 'all':
        print(json.dumps(final)[:1500]); print(json.dumps(pc_out)[:1500]); return
    c.put_object(Bucket=B, Key=f'{ROOT}/_state/stats/final_counts.json', Body=json.dumps(final).encode(), ContentType='application/json')
    c.put_object(Bucket=B, Key=f'{ROOT}/_state/stats/pdf_classes.json', Body=json.dumps(pc_out).encode(), ContentType='application/json')
    patch_ext_summary(final, ts)
    print('DONE rows', rows, 'pdf', pc_out['pdf_paths'], pc_out['classes'], flush=True)


if __name__ == '__main__':
    main()
