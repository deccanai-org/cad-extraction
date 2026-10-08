"""zx_worker.py - archive extraction worker for the new source disks (Zentitude-data-4, Zenitude-data-3, ...).

One process per box. Jobs: s3://annotationprod/<ROOT>/_control/jobs.json = [{"id","key","size"}...] (largest first).
For each job: claim (S3 conditional put) -> download the archive from the source bucket to NVMe -> 7-Zip extract
(never prompts: empty password) -> unpack nested archives into "<name>!/" (encrypted ones are recorded, not tried)
-> upload every file to s3://annotationprod/<ROOT>/extracted/<flattened archive path>/<member path>
-> per-archive manifest (path, size, sha256, flags) + result JSON -> clean scratch.
Heartbeat: <ROOT>/_state/hosts/<host>.json every 30 s (read by the status publisher).
Exit: writes /opt/zx/DONE when every job has a result and nothing is claimed by a live host, unless <ROOT>/_control/hold exists.
"""
import gzip, hashlib, json, os, re, shutil, socket, subprocess, sys, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = os.environ.get('ZX_REGION', 'ap-south-1')
SRC_BUCKET = os.environ.get('ZX_SRC_BUCKET', 'bim-proprietary-data')
SRC_STRIP = os.environ['ZX_SRC_STRIP']                    # e.g. "Zentitude-data-4/"
DST = os.environ.get('ZX_DST', 'annotationprod')            # output bucket
ROOT = os.environ['ZX_ROOT']                              # e.g. "cad-disk-extract/zentitude-data-4"
CTL_BUCKET = os.environ.get('ZX_CTL_BUCKET', DST)          # operator-written control files (code, jobs, env, stop, hold, prior index)
CTL = os.environ.get('ZX_CTL_PREFIX', f'{ROOT}/_control')
PRIOR = os.environ.get('ZX_PRIOR_LABEL', 'disk12')          # pointer label for content earlier disks already stored
PRIOR_INDEX = os.environ.get('ZX_PRIOR_INDEX', f'{CTL}/disk12_sha64.bin')
SCRATCH = os.environ.get('ZX_SCRATCH', '/scratch')
SLOTS = int(os.environ.get('ZX_SLOTS', '4'))
UP_THREADS = int(os.environ.get('ZX_UP_THREADS', '96'))
SEVENZ = os.environ.get('ZX_7Z', '/usr/local/bin/7zz')
CODE = 'zx-2026-10-01r'
MODE = os.environ.get('ZX_MODE', 'extract')      # 'repair': re-extract listed archives only to upload content whose sha marker has no object
JOBS_KEY = f'{CTL}/' + ('repair_jobs.json' if MODE == 'repair' else 'jobs.json')
RES_PFX = f'{ROOT}/_state/' + ('repair_results/' if MODE == 'repair' else 'results/')
CLAIM_PFX = f'{ROOT}/_state/' + ('repair_claims/' if MODE == 'repair' else 'claims/')
MAXSIZE = float(os.environ.get('ZX_MAXSIZE', 'inf'))   # only claim archives up to this size (small-disk helper boxes)
HOST = socket.gethostname()
PROC = os.environ.get('ZX_PROC_TAG', 'p0')
NESTED_EXT = ('.zip', '.7z', '.rar', '.tar', '.tgz', '.gz', '.bz2', '.xz', '.cab')
RANSOM_EXT = ('.wiki', '.zepto', '.locky', '.crypt', '.encrypted', '.id-f086238f')
MAX_DEPTH = 15

s3 = boto3.client('s3', region_name=REGION, config=Config(max_pool_connections=UP_THREADS + 64,
                                                          retries={'max_attempts': 30, 'mode': 'standard'},
                                                          connect_timeout=20, read_timeout=120))
dl_cfg = TransferConfig(multipart_threshold=64 * 2**20, multipart_chunksize=128 * 2**20, max_concurrency=32)
up_cfg = TransferConfig(multipart_threshold=128 * 2**20, multipart_chunksize=128 * 2**20, max_concurrency=8)
state = {'host': HOST, 'proc': PROC, 'code': CODE, 'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'running': {}, 'done': 0, 'failed': 0}
lock = threading.Lock()


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def put_json(key, obj, **kw):
    return s3.put_object(Bucket=DST, Key=key, Body=json.dumps(obj, indent=1).encode(), ContentType='application/json', **kw)


def get_json(key, bucket=None):
    try:
        return json.loads(s3.get_object(Bucket=bucket or DST, Key=key)['Body'].read())
    except ClientError as e:
        if e.response['Error']['Code'] in ('NoSuchKey', '404'):
            return None
        raise


def exists(key, bucket=None):
    try:
        s3.head_object(Bucket=bucket or DST, Key=key)
        return True
    except ClientError:
        return False


def scratch_free():
    st = os.statvfs(SCRATCH)
    return st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize


def scratch_ok(job):
    """Claim only if the box has room for this archive: free >= 2.5 x archive size + 500 GB margin."""
    free, _ = scratch_free()
    return free >= 2.5 * (job.get('size') or 0) + 500e9


def heartbeat_loop():
    while True:
        free, total = scratch_free()
        with lock:
            hb = dict(state, updated=now(), scratch_used_pct=round(100 * (1 - free / total), 1) if total else None)
        try:
            put_json(f'{ROOT}/_state/hosts/{HOST}-{PROC}.json', hb)
        except Exception as e:
            print('heartbeat failed', e, flush=True)
        time.sleep(30)


def host_alive(host):
    import calendar
    r = s3.list_objects_v2(Bucket=DST, Prefix=f'{ROOT}/_state/hosts/{host}')
    for o in r.get('Contents', []):
        hb = get_json(o['Key'])
        if hb and time.time() - calendar.timegm(time.strptime(hb['updated'], '%Y-%m-%dT%H:%M:%SZ')) < 600:
            return True
    return False


def job_alive(host, jid):
    """True if any worker process on `host` with a fresh heartbeat (< 10 min) lists `jid` as running."""
    import calendar
    r = s3.list_objects_v2(Bucket=DST, Prefix=f'{ROOT}/_state/hosts/{host}')
    for o in r.get('Contents', []):
        hb = get_json(o['Key'])
        if hb and time.time() - calendar.timegm(time.strptime(hb['updated'], '%Y-%m-%dT%H:%M:%SZ')) < 600 and jid in hb.get('running', {}):
            return True
    return False


def claim(job):
    """Conditional create of the claim object; take over a claim only if no live worker is running that job
    (a crashed process on a live box must not block its archive forever)."""
    key = f"{CLAIM_PFX}{job['id']}.json"
    body = {'host': HOST, 'proc': PROC, 'at': now(), 'code': CODE}
    try:
        put_json(key, body, IfNoneMatch='*')
        return True
    except ClientError as e:
        if e.response['Error']['Code'] not in ('PreconditionFailed', 'ConditionalRequestConflict'):
            raise
    try:
        r = s3.get_object(Bucket=DST, Key=key)
        old = json.loads(r['Body'].read())
        if old.get('host') == HOST and old.get('proc') == PROC:
            return False
        import calendar
        claimed_at = calendar.timegm(time.strptime(old.get('at', now()), '%Y-%m-%dT%H:%M:%SZ'))
        if time.time() - claimed_at < 900 or job_alive(old.get('host', ''), job['id']):
            return False
        put_json(key, dict(body, took_over_from=old), IfMatch=r['ETag'])
        return True
    except ClientError:
        return False


def flatten(src_key):
    return src_key[len(SRC_STRIP):].replace('/', '_')


def run(cmd, **kw):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors='replace', **kw)


def list_encrypted(archive):
    """Return (is_encrypted, member_names) using a header-only listing with an empty password."""
    r = run([SEVENZ, 'l', '-slt', '-p', archive], timeout=600)
    names, enc, cur = [], False, None
    for line in r.stdout.splitlines():
        if line.startswith('Path = '):
            cur = line[7:]
        elif line.startswith('Encrypted = +'):
            enc = True
            if cur:
                names.append(cur)
    return enc, names[:2000], r.returncode


NAME_MAX = 240   # bytes per path component we allow on disk (Linux limit is 255)


def short_component(comp):
    b = os.fsencode(comp)
    if len(b) <= NAME_MAX:
        return comp
    stem, dot, ext = comp.rpartition('.')
    ext = ('.' + ext) if dot and len(os.fsencode(ext)) <= 16 else ''
    h = hashlib.sha1(b).hexdigest()[:8]
    cut = b[:NAME_MAX - 12 - len(os.fsencode(ext))]
    return os.fsdecode(cut).rstrip() + '~' + h + ext


def list_entries(archive):
    """[(path, is_dir)] from a header-only listing (bytes-safe)."""
    r = subprocess.run([SEVENZ, 'l', '-slt', '-p', '-ba', archive], stdin=subprocess.DEVNULL, capture_output=True, timeout=3600)
    out, cur, isdir = [], None, False
    for line in r.stdout.split(b'\n'):
        line = line.rstrip(b'\r')
        if line.startswith(b'Path = '):
            if cur is not None:
                out.append((cur, isdir))
            cur, isdir = os.fsdecode(line[7:]), False
        elif line.startswith(b'Folder = +'):
            isdir = True
        elif line.startswith(b'Attributes = ') and b'D' in line[13:14]:
            isdir = True
    if cur is not None:
        out.append((cur, isdir))
    return out


def extract(archive, out_dir):
    """7-Zip extract (never prompts). If some names are too long for Linux, stream each missing file out with
    `7z e -so -spd` to a shortened name. Returns (rc, stderr, {short_rel: original_rel})."""
    os.makedirs(out_dir, exist_ok=True)
    r = run([SEVENZ, 'x', '-y', '-p', '-bso0', '-bsp0', '-mmt=on', f'-o{out_dir}', archive], timeout=6 * 3600)
    err = r.stderr or ''
    longmap = {}
    if 'File name too long' in err or 'errno=36' in err:
        for path, isdir in list_entries(archive):
            if isdir:
                continue
            rel = path.replace('\\', '/')
            if os.path.exists(os.path.join(out_dir, rel)):
                continue
            short = '/'.join(short_component(c) for c in rel.split('/'))
            dest = os.path.join(out_dir, short)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'wb') as fh:
                q = subprocess.run([SEVENZ, 'e', '-so', '-p', '-spd', archive, path], stdin=subprocess.DEVNULL, stdout=fh,
                                   stderr=subprocess.PIPE, timeout=6 * 3600)
            if q.returncode == 0:
                longmap[short] = rel
        if longmap:
            remaining = [l for l in err.splitlines() if 'File name too long' not in l and 'errno=36' not in l and l.strip()]
            err = '\n'.join(remaining) + f'\n[long-name fallback: {len(longmap)} files written with shortened names]'
            if not any('ERROR' in l for l in remaining):
                return 0, err[-2000:], longmap
    return r.returncode, err[-2000:], longmap


def unpack_nested(root, report, depth=1):
    if depth > MAX_DEPTH:
        return
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(NESTED_EXT):
                continue
            path = os.path.join(dirpath, fn)
            target = path + '!'
            if os.path.exists(target) or os.path.getsize(path) == 0:
                continue
            rel = os.path.relpath(path, report['_extract_root'])
            enc, names, lrc = list_encrypted(path)
            if enc:
                report['encrypted_blocked'].append({'nested': rel, 'members': names})
                continue
            rc, err, lm = extract(path, target)
            if lm:
                nrel = os.path.relpath(target, report['_extract_root'])
                report.setdefault('_longmap', {}).update({f'{nrel}/{k}': f'{nrel}/{v}' for k, v in lm.items()})
            item = {'nested': rel, 'rc': rc, 'depth': depth}
            if rc != 0:
                item['stderr'] = err[-500:]
                report['nested_errors'].append(item)
            report['nested'].append(item)
            if rc in (0, 1):
                unpack_nested(target, report, depth + 1)


# --- PDF CAD/document classification (same rules as pdf_classify.py), from the local file ---
CAD = re.compile(rb'autocad|autodesk|acad|dwg|tekla|sds ?/ ?2|sds2|design data|microstation|bentley|revit|navisworks|solidworks|'
                 rb'inventor|smartplant|smart ?3d|intergraph|hexagon|smartsketch|isogen|aveva|pdms|e3d|cadworx|bricscad|draftsight|'
                 rb'progecad|zwcad|gstarcad|advance steel|prosteel|strucad|designjet|plotwave|hpgl|archicad|vectorworks|sketchup|'
                 rb'rhino|catia|creo|teigha|open design|dwg ?true ?view|trueview|volo view|cadpdf|pdf-?xchange for autocad', re.I)
DOC = re.compile(rb'microsoft|word|excel|powerpoint|outlook|pdfmaker|libreoffice|openoffice|quartz|skia|chrome|wkhtml|scan|canon|'
                 rb'xerox|ricoh|konica|kyocera|sharp|epson|brother|lexmark|toshiba|imagerunner|crystal reports|reportlab|itext|'
                 rb'jasper|fpdf|tcpdf|nitro|foxit phantom|abbyy|omnipage|paperport|mfp', re.I)
META = re.compile(rb'/(?:Producer|Creator)\s*\((.{0,300}?)\)|<(?:pdf:Producer|xmp:CreatorTool)>(.{0,300}?)</', re.S)
BOX = re.compile(rb'/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]')


def classify(head, tail):
    blob = head + tail
    meta = b' '.join((a or b) for a, b in META.findall(blob))
    dims = []
    for m in BOX.findall(blob):
        try:
            x0, y0, x1, y1 = map(float, m)
            dims.append(max(abs(x1 - x0), abs(y1 - y0)))
        except ValueError:
            pass
    big = max(dims) if dims else 0
    if meta and CAD.search(meta):
        return 'cad', 'producer'
    if big >= 1190:
        return 'cad', 'page>=A3'
    if meta and DOC.search(meta):
        return 'document', 'producer'
    if big > 0:
        return 'document', 'page<A3'
    return 'unknown', ''




def pdf_class_local(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(65536); f.seek(0, 2); n = f.tell(); tail = b''
            if n > 65536:
                f.seek(n - 65536); tail = f.read()
        return classify(head, tail)[0]
    except Exception:
        return 'unknown'


def fix_name(rel):
    """S3 keys must be UTF-8. Names from old archives can be in a legacy code page (surrogate-escaped by Python).
    Returns (utf8_name, raw_hex_or_None): cp1252 decoding for non-UTF-8 bytes; the raw bytes are kept for the manifest."""
    raw = os.fsencode(rel)
    try:
        return raw.decode('utf-8'), None
    except UnicodeDecodeError:
        return raw.decode('cp1252', errors='backslashreplace'), raw.hex()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(8 * 2**20), b''):
            h.update(b)
    return h.hexdigest()


import array, bisect
DISK12 = array.array('Q')   # sorted first-8-bytes of every sha256 Disk-1/Disk-2 already stored (from union.sqlite)


def load_disk12():
    if not len(DISK12):
        DISK12.frombytes(s3.get_object(Bucket=CTL_BUCKET, Key=PRIOR_INDEX)['Body'].read())


def in_disk12(digest):
    h = int(digest[:16], 16)
    i = bisect.bisect_left(DISK12, h)
    return i < len(DISK12) and DISK12[i] == h


SMALL = 64 * 1024   # below this, store directly (one PUT) instead of a global dedup marker (two requests)


def upload_tree(root, prefix, job_id, longmap=None):
    """Hash every file, dedup inside the archive locally, then: small files -> one PUT; larger files -> disk-wide sha256
    marker (conditional PUT) and upload only if new. Manifest records every path with its sha256 and where the bytes live."""
    files = []
    for dirpath, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dirpath, fn)
            if not os.path.islink(p):
                files.append(p)
    with lock:
        state['running'][job_id].update(files_total=len(files), files_uploaded=0)
    nthreads = max(8, UP_THREADS // max(SLOTS, 1))

    pdf_cls = {}

    def meta(p):
        rel, raw_hex = fix_name(os.path.relpath(p, root).replace(os.sep, '/'))
        digest = sha256_file(p)
        if rel.lower().endswith('.pdf'):
            pdf_cls[digest] = pdf_class_local(p)
        return p, rel, raw_hex, os.path.getsize(p), digest

    DIRECT = 64 * 2**20   # below this: one direct PUT (no transfer manager / thread pool per file)

    # Objects an earlier attempt of this job already stored (same key + same size): re-runs PUT only what is missing.
    existing = {}
    try:
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=DST, Prefix=prefix + '/'):
            for o in page.get('Contents', []):
                existing[o['Key']] = o['Size']
    except Exception as e:                            # listing failed: fall back to uploading everything
        print(now(), PROC, job_id, 'existing-object listing failed, full upload:', repr(e)[:200], flush=True)
        existing = {}

    with ThreadPoolExecutor(nthreads) as ex:
        metas = list(ex.map(meta, files))
    leader = {}
    for p, rel, raw_hex, size, digest in metas:
        leader.setdefault(digest, f'{prefix}/{rel}')
    errors = []
    stored = {}

    def put_leader(item):
        p, rel, raw_hex, size, digest = item
        key = f'{prefix}/{rel}'
        if leader[digest] != key:
            return
        if size > 0 and in_disk12(digest):          # content already stored by the Disk-1/Disk-2 extraction
            stored[digest] = (PRIOR, f'{PRIOR}:sha256:{digest}')
            return
        healed = False
        if existing.get(key) == size:                  # stored by an earlier attempt of this job (its marker points here)
            stored[digest] = ('stored', key)
            return
        if size >= SMALL:
            mkey = f'{ROOT}/_state/sha/{digest[:2]}/{digest}'
            try:
                s3.put_object(Bucket=DST, Key=mkey, Body=key.encode(), IfNoneMatch='*')
            except ClientError as e:
                if e.response['Error']['Code'] not in ('PreconditionFailed', 'ConditionalRequestConflict'):
                    raise
                # The marker exists. A worker killed between writing a marker and finishing its upload leaves a marker with no
                # object, so check the target; if it is missing, upload these identical bytes to the marker's target key.
                try:
                    tgt = s3.get_object(Bucket=DST, Key=mkey)['Body'].read().decode().strip()
                except Exception:
                    tgt = None
                if tgt == key and existing.get(key) == size:      # stored here by an earlier attempt of this same job
                    stored[digest] = ('stored', key)
                    return
                if not (tgt and tgt.startswith(ROOT + '/') and not exists(tgt)):
                    stored[digest] = ('disk', f'sha256:{digest}')
                    return
                key, healed = tgt, True
        if not healed and existing.get(key) == size:
            stored[digest] = ('stored', key)
            return
        for attempt in range(5):
            try:
                if size < DIRECT:
                    with open(p, 'rb') as fh:
                        s3.put_object(Bucket=DST, Key=key, Body=fh.read())
                else:
                    s3.upload_file(p, DST, key, Config=up_cfg)
                stored[digest] = ('disk', f'sha256:{digest}') if healed else ('stored', key)
                if healed:
                    with lock:
                        state['healed'] = state.get('healed', 0) + 1
                return
            except Exception as e:
                if attempt == 4:
                    errors.append([rel, str(e)[:200]])
                    if size >= SMALL and not healed:
                        try:
                            s3.delete_object(Bucket=DST, Key=f'{ROOT}/_state/sha/{digest[:2]}/{digest}')
                        except Exception:
                            pass
                    return
                time.sleep(2 ** attempt)

    def counted(item):
        put_leader(item)
        with lock:
            state['running'][job_id]['files_uploaded'] += 1

    with ThreadPoolExecutor(nthreads) as ex:
        list(ex.map(counted, metas))
    entries = []
    for p, rel, raw_hex, size, digest in metas:
        key = f'{prefix}/{rel}'
        how, where = stored.get(digest, ('error', None))
        if how == 'error':
            continue
        e = {'path': rel, 'size': size, 'sha256': digest}
        if leader[digest] == key and how == 'stored':
            e['key'] = key
        else:
            e['key'] = where if how in ('disk', PRIOR) else leader[digest]
            e['dedup'] = how if how in ('disk', PRIOR) else 'archive'
        if raw_hex:
            e['raw_name_hex'] = raw_hex
        if longmap and rel in longmap:
            e['orig_path'] = longmap[rel]          # name was too long for the filesystem; stored under a shortened name
        if digest in pdf_cls:
            e['pdf_class'] = pdf_cls[digest]
        flags = []
        low = rel.lower()
        if any(low.endswith(x) or x in low for x in RANSOM_EXT) or '[bitlocker@foxmail.com' in low:
            flags.append('ransomware_encrypted')
        if size == 0:
            flags.append('zero_bytes')
        if flags:
            e['flags'] = flags
        entries.append(e)
    return entries, errors


def repair_tree(root, job, report):
    """Repair mode: job['targets'] = {sha256: [marker target key, size]}. Hash only files whose size matches a wanted size; upload each
    wanted content once to its marker's target key (if still missing), so every existing 'sha256:' pointer resolves again."""
    want = job['targets']
    sizes = {v[1] for v in want.values()}
    files = []
    for dirpath, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dirpath, fn)
            if not os.path.islink(p):
                files.append(p)
    done, errors, lk = {}, [], threading.Lock()

    def one(p):
        try:
            size = os.path.getsize(p)
        except OSError:
            return
        if size not in sizes:
            return
        d = sha256_file(p)
        if d not in want:
            return
        with lk:
            if d in done:
                return
            done[d] = 'working'
        tgt = want[d][0]
        if exists(tgt):
            done[d] = 'already_present'
            return
        for attempt in range(5):
            try:
                if size < 64 * 2**20:
                    with open(p, 'rb') as fh:
                        s3.put_object(Bucket=DST, Key=tgt, Body=fh.read())
                else:
                    s3.upload_file(p, DST, tgt, Config=up_cfg)
                done[d] = 'uploaded'
                return
            except Exception as e:
                if attempt == 4:
                    with lk:
                        errors.append([tgt, str(e)[:200]]); done.pop(d, None)
                    return
                time.sleep(2 ** attempt)
    with ThreadPoolExecutor(max(8, UP_THREADS // max(SLOTS, 1))) as ex:
        list(ex.map(one, files))
    missing = [d for d in want if d not in done]
    report.update(files_scanned=len(files), wanted=len(want), uploaded=sum(v == 'uploaded' for v in done.values()),
                  already_present=sum(v == 'already_present' for v in done.values()), not_found_count=len(missing),
                  not_found=missing[:500], upload_errors=errors[:100], upload_error_count=len(errors),
                  uploaded_bytes=sum(want[d][1] for d, v in done.items() if v == 'uploaded'))


def process_loose(job):
    """Loose (non-archive) source files: the bytes already live in the source bucket, so nothing is copied. Hash, classify and
    record each one in the manifest with key 'src:<source key>' (dedup = PRIOR if an earlier disk already stored the content)."""
    jid = job['id']
    work = os.path.join(SCRATCH, jid)
    os.makedirs(work, exist_ok=True)
    report = {'id': jid, 'type': 'loose', 'host': HOST, 'code': CODE, 'started': now(), 'source_files': len(job.get('keys', [])), 'dir': job.get('dir')}
    with lock:
        state['running'][jid] = {'key': 'loose:' + job.get('dir', ''), 'size': job.get('size'), 'phase': 'hash', 'since': now()}
    errors, entries = [], []
    if 'keys' not in job:                      # folder job: list the folder's own non-archive files
        keys, tok = [], None
        while True:
            kw = dict(Bucket=SRC_BUCKET, Prefix=job['dir'], Delimiter='/')
            if tok:
                kw['ContinuationToken'] = tok
            r = s3.list_objects_v2(**kw)
            keys += [[o['Key'], o['Size']] for o in r.get('Contents', [])
                     if not o['Key'].endswith('/') and not o['Key'].lower().endswith(NESTED_EXT)]
            if not r.get('IsTruncated'):
                break
            tok = r['NextContinuationToken']
        job = dict(job, keys=keys)
        report['source_files'] = len(keys)

    def one(item):
        key, size = item
        rel = key[len(SRC_STRIP):] if key.startswith(SRC_STRIP) else key
        try:
            p = os.path.join(work, hashlib.sha1(key.encode()).hexdigest())
            s3.download_file(SRC_BUCKET, key, p, Config=dl_cfg)
            digest = sha256_file(p)
            e = {'path': rel, 'size': size, 'sha256': digest, 'key': 'src:' + key, 'loose': True}
            if size > 0 and in_disk12(digest):
                e['dedup'] = PRIOR
            else:
                e['dedup'] = 'source'
            if rel.lower().endswith('.pdf'):
                e['pdf_class'] = pdf_class_local(p)
            low = rel.lower(); flags = []
            if any(low.endswith(x) or x in low for x in RANSOM_EXT) or '[bitlocker@foxmail.com' in low:
                flags.append('ransomware_encrypted')
            if size == 0:
                flags.append('zero_bytes')
            if flags:
                e['flags'] = flags
            os.remove(p)
            return e
        except Exception as ex:
            errors.append([rel, str(ex)[:200]])
            return None
    with ThreadPoolExecutor(32) as ex:
        entries = [e for e in ex.map(one, job['keys']) if e]
    report.update(files=len(entries), bytes=sum(e['size'] for e in entries), stored_files=0, stored_bytes=0,
                  dedup_files=len(entries), dedup_bytes=sum(e['size'] for e in entries),
                  already_in_disk12_files=sum(1 for e in entries if e.get('dedup') == PRIOR),
                  already_in_disk12_bytes=sum(e['size'] for e in entries if e.get('dedup') == PRIOR),
                  upload_errors=errors[:200], upload_error_count=len(errors), nested_count=0, encrypted_nested=0,
                  ransomware_files=sum(1 for e in entries if 'ransomware_encrypted' in e.get('flags', [])),
                  zero_byte_files=sum(1 for e in entries if 'zero_bytes' in e.get('flags', [])),
                  status='ok' if not errors else ('partial' if entries else 'failed'), finished=now())
    s3.put_object(Bucket=DST, Key=f'{ROOT}/_state/manifests/{jid}.jsonl.gz', Body=gzip.compress('\n'.join(json.dumps(e) for e in entries).encode()))
    put_json(f'{RES_PFX}{jid}.json', report)
    shutil.rmtree(work, ignore_errors=True)
    return report['status']


def process(job):
    if job.get('type') == 'loose':
        return process_loose(job)
    jid, key = job['id'], job['key']
    work = os.path.join(SCRATCH, jid)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    arc = os.path.join(work, os.path.basename(key))
    out = os.path.join(work, 'x')
    prefix = f'{ROOT}/extracted/{flatten(key)}'
    report = {'id': jid, 'source': f's3://{SRC_BUCKET}/{key}', 'size': job.get('size'), 'host': HOST, 'code': CODE,
              'started': now(), 'dest_prefix': f's3://{DST}/{prefix}/', 'encrypted_blocked': [], 'nested': [],
              'nested_errors': [], '_extract_root': out}
    with lock:
        state['running'][jid] = {'key': key, 'size': job.get('size'), 'phase': 'download', 'since': now()}
    t0 = time.time()
    s3.download_file(SRC_BUCKET, key, arc, Config=dl_cfg)
    report['download_s'] = round(time.time() - t0, 1)
    with lock:
        state['running'][jid]['phase'] = 'extract'
    enc, names, _ = list_encrypted(arc)
    if enc:
        report['top_level_encrypted'] = True
        report['encrypted_blocked'].append({'nested': '(top level)', 'members': names})
    t0 = time.time()
    rc, err, lm = extract(arc, out)
    report['_longmap'] = dict(lm)
    report.update(extract_rc=rc, extract_stderr=err[-1500:], extract_s=round(time.time() - t0, 1))
    os.remove(arc)
    if rc in (0, 1) or os.path.isdir(out):
        with lock:
            state['running'][jid]['phase'] = 'nested'
        unpack_nested(out, report)
        if MODE == 'repair':
            with lock:
                state['running'][jid]['phase'] = 'repair'
            repair_tree(out, job, report) if os.path.isdir(out) else report.update(not_found_count=len(job['targets']))
            report['status'] = 'ok' if not report.get('upload_error_count') and not report.get('not_found_count') else 'partial'
            report['finished'] = now()
            for k in ('_extract_root', '_longmap'):
                report.pop(k, None)
            put_json(f'{RES_PFX}{jid}.json', report)
            shutil.rmtree(work, ignore_errors=True)
            return report['status']
        with lock:
            state['running'][jid]['phase'] = 'upload'
        t0 = time.time()
        entries, errors = upload_tree(out, prefix, jid, report.get('_longmap') or {}) if os.path.isdir(out) else ([], [])
        report['upload_s'] = round(time.time() - t0, 1)
    else:
        entries, errors = [], []
        if MODE == 'repair':                          # never touch the extraction manifest/result in repair mode
            report.update(status='failed', not_found_count=len(job['targets']), finished=now())
            for k in ('_extract_root', '_longmap'):
                report.pop(k, None)
            put_json(f'{RES_PFX}{jid}.json', report)
            shutil.rmtree(work, ignore_errors=True)
            return 'failed'
    report.update(files=len(entries), bytes=sum(e['size'] for e in entries),
                  stored_files=sum(1 for e in entries if not e.get('dedup')),
                  stored_bytes=sum(e['size'] for e in entries if not e.get('dedup')),
                  dedup_files=sum(1 for e in entries if e.get('dedup')),
                  dedup_bytes=sum(e['size'] for e in entries if e.get('dedup')),
                  already_in_disk12_files=sum(1 for e in entries if e.get('dedup') == PRIOR),
                  already_in_disk12_bytes=sum(e['size'] for e in entries if e.get('dedup') == PRIOR),
                  upload_errors=errors[:200],
                  upload_error_count=len(errors),
                  ransomware_files=sum(1 for e in entries if 'ransomware_encrypted' in e.get('flags', [])),
                  zero_byte_files=sum(1 for e in entries if 'zero_bytes' in e.get('flags', [])),
                  nested_count=len(report['nested']), encrypted_nested=len(report['encrypted_blocked']))
    report['status'] = ('ok' if rc == 0 and not errors and not report['nested_errors'] else
                        'partial' if entries else 'failed')
    report['finished'] = now()
    report['long_name_files'] = len(report.get('_longmap') or {})
    report.pop('_extract_root', None)
    report.pop('_longmap', None)
    man = gzip.compress('\n'.join(json.dumps(e) for e in entries).encode())
    s3.put_object(Bucket=DST, Key=f'{ROOT}/_state/manifests/{jid}.jsonl.gz', Body=man)
    put_json(f'{RES_PFX}{jid}.json', report)
    shutil.rmtree(work, ignore_errors=True)
    return report['status']


def list_ids(prefix):
    ids, tok = set(), None
    while True:
        kw = dict(Bucket=DST, Prefix=prefix)
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        ids.update(o['Key'].rsplit('/', 1)[-1].split('.')[0] for o in r.get('Contents', []))
        if not r.get('IsTruncated'):
            return ids
        tok = r['NextContinuationToken']


def load_jobs():
    jobs = get_json(JOBS_KEY, CTL_BUCKET) or []
    jobs.sort(key=lambda j: (j.get('prio', 5), -(j.get('size') or 0)))
    return jobs


CODE_ETAG = {}


def code_changed():
    """True when a newer worker was published (hot reload between jobs) or the stop flag asks for a newer version."""
    try:
        et = s3.head_object(Bucket=CTL_BUCKET, Key=f'{CTL}/zx_worker.py')['ETag']
    except Exception:
        return False
    first = CODE_ETAG.setdefault('etag', et)
    if et != first:
        return True
    try:
        need = s3.get_object(Bucket=CTL_BUCKET, Key=f'{CTL}/stop')['Body'].read().decode().strip()
        return (not need) or need > CODE
    except Exception:
        return False


def slot_loop(jobs, idx):
    """Claim -> process until every job in jobs.json has a result. Re-reads jobs.json when idle, so appended jobs are picked up.
    Exits between jobs when a newer worker is published, so the boot loop restarts it on the new code."""
    idle_since = None
    code_changed()
    while True:
        if code_changed():
            print(now(), PROC, 'slot', idx, 'exit: newer worker code / stop flag', flush=True)
            return
        done = list_ids(RES_PFX)
        claimed = list_ids(CLAIM_PFX)
        todo = [j for j in jobs if j['id'] not in done and (j.get('size') or 0) <= MAXSIZE]
        if not todo:
            jobs = load_jobs()
            if all(j['id'] in done for j in jobs) or MAXSIZE < float('inf'):
                return
            continue
        picked = None
        unclaimed = [j for j in todo if j['id'] not in claimed]
        import random
        for j in unclaimed or random.sample(todo, min(8, len(todo))):   # unclaimed first; else a RANDOM few claims for dead owners
            if not scratch_ok(j):
                continue
            if claim(j):
                picked = j
                break
        if not picked:
            idle_since = idle_since or time.time()
            time.sleep(60)
            jobs = load_jobs()
            continue
        idle_since = None
        try:
            st = process(picked)
            with lock:
                state['done'] += 1
            print(now(), PROC, 'slot', idx, picked['id'], st, flush=True)
        except Exception:
            tb = traceback.format_exc()
            print(now(), PROC, 'slot', idx, picked['id'], 'EXCEPTION', tb, flush=True)
            with lock:
                state['failed'] += 1
            try:
                put_json(f"{ROOT}/_state/errors/{picked['id']}.{HOST}.{PROC}.json", {'at': now(), 'host': HOST, 'traceback': tb[-4000:]})
                s3.delete_object(Bucket=DST, Key=f"{CLAIM_PFX}{picked['id']}.json")
            except Exception:
                pass
            time.sleep(30)
        finally:
            with lock:
                state['running'].pop(picked['id'], None)
            shutil.rmtree(os.path.join(SCRATCH, picked['id']), ignore_errors=True)


def all_done(jobs):
    return all(exists(f"{RES_PFX}{j['id']}.json") for j in jobs)


def run_proc(tag):
    global PROC, s3
    PROC = tag
    state['proc'] = tag
    s3 = boto3.client('s3', region_name=REGION, config=Config(max_pool_connections=UP_THREADS + 64,
                                                              retries={'max_attempts': 30, 'mode': 'standard'},
                                                              connect_timeout=20, read_timeout=120))
    main_one()


def main_one():
    load_disk12()
    jobs = load_jobs()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threads = [threading.Thread(target=slot_loop, args=(jobs, i)) for i in range(SLOTS)]
    for i, t in enumerate(threads):
        t.start()
        time.sleep(3)
    for t in threads:
        t.join()
    print(now(), PROC, 'process exit; done', state['done'], 'failed', state['failed'], flush=True)


if __name__ == '__main__':
    import multiprocessing as mp
    ov = get_json(f'{CTL}/' + ('zx_env_repair.json' if MODE == 'repair' else 'zx_env.json'), CTL_BUCKET) or {}   # fleet-wide overrides (procs/slots/threads)
    SLOTS = int(ov.get('slots', SLOTS)); UP_THREADS = int(ov.get('up_threads', UP_THREADS))
    if 'procs' in ov:
        os.environ['ZX_PROCS'] = str(ov['procs'])
    nprocs = int(os.environ.get('ZX_PROCS', '1'))
    base = os.environ.get('ZX_PROC_TAG', 'p')
    procs = [mp.Process(target=run_proc, args=(f'{base}{i}',)) for i in range(nprocs)]
    for p in procs:
        p.start()
        time.sleep(2)
    for p in procs:
        p.join()
    jobs = get_json(JOBS_KEY, CTL_BUCKET)
    if all_done(jobs) and not exists(f'{CTL}/hold', CTL_BUCKET):
        open('/opt/zx/DONE', 'w').write(now())
    print(now(), 'worker exit', flush=True)
