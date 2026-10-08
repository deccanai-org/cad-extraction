"""Shared helpers for the pmp (partial-tier parametric pipeline) Modal stages. Standard library only, so every stage
image (pipeline, src_db1, src_sds2, the light orchestrator) can import it.

Size classes and resources, job normalisation, downloads from pre-signed URLs, publishing a staged folder onto the
Modal Volume, stage logs, memory sampling, naming.
"""
import calendar, hashlib, json, os, re, shutil, socket, threading, time, unicodedata, urllib.error, urllib.parse, \
    urllib.request

VOL = '/vol'                       # mount point of the Modal Volume "pmp-out" in every stage container
CODE_ROOT = '/pmp/code'            # code/<variant>/{tools,kit} inside the pipeline image
PLUGIN_ROOT = '/pmp'               # /pmp/src_db1, /pmp/src_sds2, /pmp/issues (plug-in components)
TEMPLATES = '/pmp/app/templates'   # scripts_README.md, requirements.txt (shipped shared files)
PMP_APP_VERSION = 'pmp-app-2026-10-07a'

# ---------------------------------------------------------------------------------------------------------------
# size classes (delivered STEP bytes, decimal, as the pmx fleet: 1e7 / 1e8 / 5e8 / 1e9)
# J = worker processes handed to the tools (EXACT_JOBS env, --jobs), as the fleet's resources() table.
# cpu = Modal CPU request (Modal bills physical cores; one core = 2 hyperthreads, so cpu = J/2 gives J threads, the
# vCPU count a fleet job of that class was sized for). mem_gib = Modal memory request (soft: the container may grow
# past it; fleet measured peaks 10-07: M <= 21 GB, L <= 25 GB typical, XL 10-130 GB). step_timeout = job.py's TMO table
# (per pipeline step). timeout = the Modal function timeout (24 h is Modal's maximum); a stage stops starting steps
# STOP_MARGIN seconds before it so that its summary is always written (a step cut short is rc 124, as job.py).
# disk_gib: None = Modal's default ephemeral disk; Modal accepts an explicit ephemeral_disk only from 512 GiB up.
# ---------------------------------------------------------------------------------------------------------------
CLASSES = ['S', 'M', 'L', 'XL']
TOO_BIG = 10 ** 9                  # >= 1 GB delivered STEP: not run in v1 -> recorded as 'too_big_v1'
RES = {
    'S':  dict(J=4,  cpu=2.0,  mem_gib=8,   disk_gib=None, timeout=4 * 3600,  step_timeout=3600),
    'M':  dict(J=8,  cpu=4.0,  mem_gib=24,  disk_gib=None, timeout=8 * 3600,  step_timeout=7200),
    'L':  dict(J=16, cpu=8.0,  mem_gib=48,  disk_gib=512,  timeout=16 * 3600, step_timeout=4 * 3600),
    'XL': dict(J=32, cpu=16.0, mem_gib=128, disk_gib=512,  timeout=24 * 3600, step_timeout=8 * 3600),
}
STOP_MARGIN = 900                  # seconds kept free before the Modal timeout for publishing outputs

# which pipeline code variant runs a model, by the source of its IFC (md5-identical to the bench copies that produced
# the sample results; code/<variant>/MD5SUMS is checked in the container before a run)
CODE_BY_SOURCE = {
    'package_ifc': 'code_v9a',            # IFC-sourced models: the fleet's v9a (code_db1b would change 92 T-profile models)
    'regenerated_from_db1': 'code_db1b',  # v9a + IfcTShapeProfileDef + kernel-unbuildable cut tools
    'emitted_from_sds2': 'code_sds2',     # v9a + exact parts with tools (SDS/2 emitter IFCs) + occstep delivered measures
}
SOURCE_KINDS = tuple(CODE_BY_SOURCE)
STEP_SOURCE_TO_KIND = {'ifc': 'package_ifc', 'db1': 'regenerated_from_db1', 'sds2': 'emitted_from_sds2'}


def size_class(nbytes):
    b = int(nbytes or 0)
    return 'S' if b < 10**7 else 'M' if b < 10**8 else 'L' if b < 5 * 10**8 else 'XL' if b < 10**9 else 'too_big_v1'


def next_class(cls):
    i = CLASSES.index(cls) if cls in CLASSES else len(CLASSES)
    return CLASSES[i + 1] if i + 1 < len(CLASSES) else None


# ---------------------------------------------------------------------------------------------------------- naming
NAME_MAX = 100


def sanitize(base):
    """a readable, shell- and file-system-safe folder name from a STEP basename (the perfect-tier staging rule: each run
    of characters other than letters, digits, '.', '_' and '-' becomes one '_')"""
    s = unicodedata.normalize('NFKD', base).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^A-Za-z0-9._-]+', '_', s)
    s = re.sub(r'_+', '_', s).strip('._-')
    s = s[:NAME_MAX].rstrip('._-')
    return s or 'model'


def step_stem(relpath):
    b = os.path.basename(str(relpath).replace('\\', '/'))
    return b[:-5] if b.lower().endswith('.step') else (os.path.splitext(b)[0] or b)


FOLDER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,%d}$' % (NAME_MAX + 20))


# ------------------------------------------------------------------------------------------------------------- jobs
class JobError(ValueError):
    pass


def _first(j, *keys):
    for k in keys:
        if j.get(k) not in (None, ''):
            return j[k]
    return None


def normalise_job(j):
    """the job dict every stage works from (docs/README.md "Job schema"). Accepts the jobs component's rows
    (model_id, relpath, model_folder, step_source, bytes, size class, partial, converter, urls{...}) and aliases.
    Never guesses the source kind from the authoring tool (an SDS/2-authored IFC is still a package-IFC model)."""
    j = dict(j)
    if j.get('_normalised'):
        return j
    j['id'] = _first(j, 'id', 'model_id')
    if not j['id']:
        raise JobError('job without id / model_id')
    j['id'] = str(j['id'])
    if not re.fullmatch(r'[0-9A-Za-z._-]{6,128}', j['id']):
        raise JobError(f'model id {j["id"]!r} is not a safe folder name')
    # jobs component rows: step = {key, bytes, sha256, etag}, source = {kind, relpath, package, pkg_prefix, key, sha256}
    if isinstance(j.get('step'), dict):
        j['step_info'] = j.pop('step')
        j.setdefault('step_sha256', j['step_info'].get('sha256'))
        if j.get('bytes') is None:
            j['bytes'] = j['step_info'].get('bytes')
    if isinstance(j.get('source'), dict):
        si = j['source_info'] = j.pop('source')
        j.setdefault('converted_from', si.get('relpath'))
        if si.get('package') == '3d' and si.get('pkg_prefix'):
            j.setdefault('converted_from_package', si['pkg_prefix'].rstrip('/'))
        if (si.get('format') or si.get('kind')) == 'ifc' and si.get('sha256'):
            j.setdefault('source_ifc_sha256', si['sha256'])
    j['step'] = _first(j, 'step', 'relpath', 'step_relpath')
    if not j['step']:
        raise JobError('job without step / relpath (the delivered STEP inside the package)')
    if not j.get('pid'):
        raise JobError('job without pid')
    urls = dict(j.get('urls') or j.get('get_urls') or {})
    for k in ('step', 'ifc', 'db1', 'sds2', 'source'):
        if j.get(k + '_url') and k not in urls:
            urls[k] = j.pop(k + '_url')
    # the source file's URL under the name of its format (urls.source -> urls.ifc / db1 / sds2)
    sk = str(j.get('step_source') or '').lower()
    if urls.get('source') and sk in ('ifc', 'db1', 'sds2') and not urls.get(sk):
        urls[sk] = urls['source']
    j['urls'] = urls
    put = _first(j, 'put_url', 'bundle_put_url') or urls.pop('put', None) or urls.pop('bundle', None)
    j['put_url'] = put
    kind = j.get('source_kind') or STEP_SOURCE_TO_KIND.get(str(j.get('step_source') or '').lower())
    if kind not in SOURCE_KINDS:
        raise JobError(f'unknown or missing source_kind {kind!r} (step_source {j.get("step_source")!r})')
    j['source_kind'] = kind
    if j.get('bytes') is None:
        raise JobError('job without bytes (delivered STEP size)')
    j['bytes'] = int(j['bytes'])
    c = _first(j, 'cls', 'size_class', 'class')
    j['cls'] = c if c in CLASSES or c == 'too_big_v1' else size_class(j['bytes'])
    j['step_sha256'] = _first(j, 'step_sha256', 'sha256')
    j.setdefault('gen', 1)
    j.setdefault('stem', j['id'][:16])
    j.setdefault('code_version', CODE_BY_SOURCE[kind])
    if j['code_version'] not in CODE_BY_SOURCE.values():
        raise JobError(f'unknown code_version {j["code_version"]!r}')
    mf = j.get('model_folder')
    j['model_folder_given'] = bool(mf)
    j['model_folder'] = mf or sanitize(step_stem(j['step']))
    if not FOLDER_RE.match(j['model_folder']) or j['model_folder'].lower() in ('readme.md', 'requirements.txt', 'steelbuild.py',
                                                                               'issues_lib.py', 'scripts_manifest.jsonl'):
        raise JobError(f'model folder {j["model_folder"]!r} is not a safe / free name')
    if kind == 'package_ifc':
        j['ifc'] = _first(j, 'ifc', 'converted_from')
        if not j['ifc']:
            raise JobError('package_ifc job needs converted_from (the package IFC relpath)')
        # IFC models are content-addressed: the model id is the sha256 of the IFC the STEP was converted from
        if not j.get('source_ifc_sha256') and re.fullmatch(r'[0-9a-f]{64}', j['id']):
            j['source_ifc_sha256'] = j['id']
    else:
        j['ifc'] = j.get('ifc') or (j['id'] + '.ifc')
    j['_normalised'] = True
    return j


def job_runnable(j):
    """(ok, reason): whether the job can start (URLs present, size in scope)"""
    if j['cls'] == 'too_big_v1':
        return False, 'too_big_v1'
    if not j['urls'].get('step'):
        return False, 'no_step_url'
    if j['source_kind'] == 'package_ifc' and not j['urls'].get('ifc'):
        return False, 'no_ifc_url'
    exp = [url_expiry(u) for u in j['urls'].values() if isinstance(u, str)]
    exp = [e for e in exp if e]
    if exp and min(exp) < time.time() + 1800:
        return False, 'get_urls_expire_within_30min'
    return True, None


def redact_job(j):
    """job without pre-signed URLs (bearer tokens): what is written to the volume / index / logs"""
    r = {k: v for k, v in j.items() if k not in ('urls', 'put_url', 'get_urls') and not k.endswith('_url')}
    urls = dict(j.get('urls') or {})
    r['url_keys'] = sorted(urls)
    r['url_objects'] = {k: url_object(v) for k, v in urls.items() if isinstance(v, str)}
    if j.get('put_url'):
        r['put_object'] = url_object(j['put_url'])
        r['put_expires'] = url_expiry(j['put_url'])
    return r


def url_object(url):
    """bucket/key of a pre-signed S3 URL, without the query string (safe to log)"""
    try:
        u = urllib.parse.urlsplit(url)
        if '.s3' in u.netloc and not u.netloc.startswith('s3'):
            return urllib.parse.unquote(u.netloc.split('.')[0] + u.path)
        return urllib.parse.unquote(u.path.lstrip('/'))
    except Exception:
        return '?'


def url_expiry(url):
    """epoch seconds at which a SigV4 pre-signed URL expires (None if not a SigV4 URL)"""
    try:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        t0 = calendar.timegm(time.strptime(q['X-Amz-Date'][0], '%Y%m%dT%H%M%SZ'))
        return t0 + int(q['X-Amz-Expires'][0])
    except Exception:
        return None


# -------------------------------------------------------------------------------------------------------- transfer
class DownloadError(RuntimeError):
    pass


def download(url, dest, sha256=None, nbytes=None, tries=6, log=None):
    """stream a pre-signed GET URL to dest (atomic rename), sha256 while streaming. Retries transient errors with
    back-off (restart from 0). 4xx = expired / bad signature / missing -> no retry. Returns {bytes, sha256, seconds,
    object}. Raises DownloadError with a URL-free message."""
    obj = url_object(url)
    exp = url_expiry(url)
    if exp and exp < time.time() + 60:
        raise DownloadError(f'pre-signed URL expired for {obj}')
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    tmp = dest + '.part'
    last = None
    for i in range(tries):
        t0 = time.time()
        try:
            h, n = hashlib.sha256(), 0
            req = urllib.request.Request(url, headers={'User-Agent': 'pmp/1'})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as f:
                while True:
                    b = r.read(8 << 20)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    n += len(b)
            d = h.hexdigest()
            if nbytes is not None and n != int(nbytes):
                raise DownloadError(f'{obj}: got {n} bytes, expected {nbytes}')
            if sha256 and d != sha256:
                raise DownloadError(f'{obj}: sha256 {d} != expected {sha256}')
            os.replace(tmp, dest)
            if log:
                log(f'downloaded {obj} {n} B sha256 {d[:12]} in {time.time() - t0:.1f}s')
            return {'bytes': n, 'sha256': d, 'seconds': round(time.time() - t0, 1), 'object': obj}
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if 400 <= e.code < 500 and e.code not in (408, 429):
                break
        except DownloadError as e:
            last = str(e)
            break
        except Exception as e:
            last = f'{type(e).__name__}: {str(e)[:200]}'
        if log:
            log(f'download retry {i + 1} {obj}: {last}')
        time.sleep(min(60, 5 * (i + 1)))
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise DownloadError(f'download failed for {obj}: {last}')


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def step_data_sha256(path):
    """sha256 of a STEP file's DATA section (the header above it carries only the file name and the write time) -
    the determinism measure of e2e.py"""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for line in fh:
            if line.startswith(b'DATA;'):
                h.update(line)
                break
        for line in fh:
            h.update(line)
    return h.hexdigest()


class StageLog:
    """append-only stage log on local disk (published to /<id>/logs/ with the stage's outputs)"""

    def __init__(self, path, prefix=''):
        self.path = path
        self.prefix = prefix
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def __call__(self, msg):
        line = time.strftime('%H:%M:%S ') + str(msg)
        with open(self.path, 'a') as f:
            f.write(line + '\n')
        print(self.prefix + line, flush=True)


def publish(src, dst):
    """replace folder dst on the volume by the local folder src: copy to dst.tmp, swap, drop the old copy.
    A model is handled by one orchestrator at a time, so there is no concurrent writer of dst."""
    tmp = dst.rstrip('/') + '.tmp'
    old = dst.rstrip('/') + '.old'
    for p in (tmp, old):
        shutil.rmtree(p, ignore_errors=True)
    os.makedirs(os.path.dirname(dst.rstrip('/')), exist_ok=True)
    shutil.copytree(src, tmp)
    if os.path.exists(dst):
        os.rename(dst, old)
    os.rename(tmp, dst)
    shutil.rmtree(old, ignore_errors=True)


def write_json(path, obj, indent=1):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=indent, sort_keys=False, default=str)
        f.write('\n')
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def record_start(model_id, stage, token):
    """one line per container start of a stage call in /vol/<id>/logs/starts.jsonl (the caller commits the volume).
    Modal restarts a preempted container with the same input: the same call token then appears more than once, so a
    stage can report how often it was (re)started and the run index can count the compute lost to preemption.
    Returns the number of starts of this call token so far (1 = first start)."""
    p = os.path.join(VOL, model_id, 'logs', 'starts.jsonl')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    n = 0
    try:
        for line in open(p):
            try:
                n += json.loads(line).get('token') == token
            except Exception:
                pass
    except OSError:
        pass
    with open(p, 'a') as f:
        f.write(json.dumps({'token': token, 'stage': stage, 'start': n + 1, 'task_id': os.environ.get('MODAL_TASK_ID'),
                            'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, sort_keys=True) + '\n')
    return n + 1


def container_info(cls=None):
    r = RES.get(cls) or {}
    return {'host': socket.gethostname(), 'task_id': os.environ.get('MODAL_TASK_ID'),
            'region': os.environ.get('MODAL_REGION'), 'cloud': os.environ.get('MODAL_CLOUD_PROVIDER'),
            'image_id': os.environ.get('MODAL_IMAGE_ID'), 'cpu': r.get('cpu'), 'mem_gib': r.get('mem_gib'),
            'nproc': os.cpu_count()}


def check_md5sums(code_dir):
    """the code variant in the image is the one its MD5SUMS lists (the bench copy that produced the sample results).
    Returns {'ok', 'checked', 'bad': [...]}"""
    p = os.path.join(code_dir, 'MD5SUMS')
    if not os.path.exists(p):
        return {'ok': False, 'checked': 0, 'bad': ['MD5SUMS missing']}
    bad, n = [], 0
    for line in open(p):
        if not line.strip():
            continue
        h, f = line.split(None, 1)
        f = f.strip()
        n += 1
        try:
            got = hashlib.md5(open(os.path.join(code_dir, f), 'rb').read()).hexdigest()
        except OSError:
            got = None
        if got != h:
            bad.append(f)
    return {'ok': not bad, 'checked': n, 'bad': bad}


class MemSampler:
    """peak memory of this container: cgroup memory.peak when the runtime exposes it, else the max over 5 s samples
    of the summed RSS of this process tree (psutil when available)"""

    def __init__(self, every=5.0):
        self.every, self.peak, self.stop = every, 0.0, False
        self.cg = next((p for p in ('/sys/fs/cgroup/memory.peak', '/sys/fs/cgroup/memory/memory.max_usage_in_bytes')
                        if os.path.exists(p)), None)
        threading.Thread(target=self._run, daemon=True).start()

    def _sample(self):
        if self.cg:
            try:
                return int(open(self.cg).read().split()[0]) / 2**30
            except Exception:
                pass
        try:
            import psutil
            me = psutil.Process()
            tot = me.memory_info().rss
            for c in me.children(recursive=True):
                try:
                    tot += c.memory_info().rss
                except Exception:
                    pass
            return tot / 2**30
        except Exception:
            return 0.0

    def _run(self):
        while not self.stop:
            self.peak = max(self.peak, self._sample())
            time.sleep(self.every)

    def done(self):
        self.stop = True
        self.peak = max(self.peak, self._sample())
        return round(self.peak, 2), ('cgroup' if self.cg else 'rss_samples')


class CpuMeter:
    """cpu seconds used by this container (cgroup v2 cpu.stat usage_usec, else this process tree's times)"""

    def __init__(self):
        self.t0 = self._read()

    @staticmethod
    def _read():
        try:
            for line in open('/sys/fs/cgroup/cpu.stat'):
                if line.startswith('usage_usec'):
                    return int(line.split()[1]) / 1e6
        except Exception:
            pass
        t = os.times()
        return t.user + t.system + t.children_user + t.children_system

    def done(self):
        return round(self._read() - self.t0, 1)
