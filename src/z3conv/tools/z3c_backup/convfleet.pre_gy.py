#!/usr/bin/env python3
"""Shared fleet runtime for the Zenitude-data-3 conversion kits (ifc / db1 / sds2 / grade).  runtime z3-v1
(data-4 convfleet-v5 + split control/state buckets, standard retries, jobs key from env.json, global stop)

Control (operator-writable, read-only for the boxes): s3://annotationprod/cad-disk-extract/_control/z3conv/
  <pipe>/<kit files>                        hot-reloaded code (top-level files only)
  <pipe>/{hold,stop,env.json}               hold = never finish (keep boxes alive); stop = pause; env.json = {"slots": N, "jobs_key": ...}
  stop                                      global pause for every pipeline
State + outputs (written by the boxes): s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/
  _state/conv/<pipe>/jobs.json              job list (largest first), one job per distinct content (written by the scan)
  _state/conv/<pipe>/claims/<id>.json       claim: S3 conditional create (IfNoneMatch); refreshed every 5 min;
                                            untouched > STALE_S -> taken over with IfMatch(etag)
  _state/conv/<pipe>/results/<id>.json      final result (status ok|fail, reason, stats, validation)
  _state/conv/<pipe>/retry/<id>.json        transient failures (download, disk full, worker error): retried
  _state/conv/<pipe>/deferred/<id>.json     memory-killed: min_mem_bytes for the next host
  _state/conv/<pipe>/hosts/<host>-<pid>.json heartbeat (60 s); logs/<host>-<pid>.log
v2: disk-space gating + disk watchdog (ENOSPC is transient, never a verdict); capacity shared with the other worker
processes on the same host (their S3 heartbeats); hand-off hot reload (the new code starts at once, the old process
only finishes its running jobs); one live process per code version per host (local pidfiles); `redo(result)` hook
re-opens results of older code that the new code can do better.
v3 (z3-convfleet-v2): host-wide capacity. Every worker process on a box (all pipelines, all code generations, assist loops)
publishes its running jobs in <home>/run/reg-<pid>.json (reservation, RSS, start time, cores). A job is claimed only when
  memory: sum over ALL jobs on the host of max(reservation, RSS) + this job's reservation < 85 % of RAM (75 % for an assist
          pipeline) AND MemAvailable minus the growth still owed to running jobs > this job's reservation + 4 GB;
  CPU:    max(1-min load, 10-s run queue) + cores of jobs started in the last 90 s + this job's cores <= cpu_frac x vCPU
          (0.95; 0.85 for an assist pipeline, so the box's own pipeline keeps priority);
  slots:  the pipeline's slot cap (secondary).
Each job runs in a systemd scope with MemoryMax and CPUQuota = job_cores x 100 % (hard per-job thread cap).
Memory reservation = max(the kit's estimate, the coordinator's table _state/conv/<pipe>/mem_buckets.json: 1.2 x p95 measured
peak RSS of the job's size bucket, 1.2 x this job's own measured peak). Peak RSS is sampled every second. The memory watchdog
kills the job that most exceeds its reservation (host-wide), never a job inside its reservation unless none exceeds; a killed
job retries with 1.6 x its measured peak reserved. An assist worker retires when the box's own pipeline no longer lists it.
Exit: 0 + DONE file when every job has a result (and no hold flag).
"""
import os, sys, json, time, socket, threading, subprocess, traceback, random, signal, hashlib, shutil, gzip, collections
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

B = 'bim-proprietary-data'                    # state + outputs + all source objects
ROOT = 'cad-disk-extract/zenitude-data-3'
CB = 'annotationprod'                         # control (kit code, flags, env)
CTLROOT = 'cad-disk-extract/_control/z3conv'
HOST = socket.gethostname()
PID = os.getpid()
RUNTIME = 'z3-convfleet-v2'
s3 = boto3.client('s3', region_name='ap-south-1',
                  config=Config(max_pool_connections=64, retries={'max_attempts': 40, 'mode': 'standard'},
                                connect_timeout=30, read_timeout=300))
STALE_S = int(os.environ.get('CLAIM_STALE_S', '1500'))
def mem_psi60():
    """/proc/pressure/memory 'some' avg60 (percent of time tasks stalled on memory) or None"""
    try:
        for l in open('/proc/pressure/memory'):
            if l.startswith('some'):
                return float(l.split('avg60=')[1].split()[0])
    except Exception:
        return None


def cg_cpu_s(pid):
    """CPU seconds used by the cgroup (job scope) of pid, or None"""
    try:
        path = [l for l in open(f'/proc/{pid}/cgroup') if l.startswith('0::')][0].split('::', 1)[1].strip()
        for l in open(f'/sys/fs/cgroup{path}/cpu.stat'):
            if l.startswith('usage_usec'):
                return int(l.split()[1]) / 1e6
    except Exception:
        return None


WD_REV = 2                                       # host-wide watchdog revision: only the newest revision's processes elect the leader
for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'TBB_NUM_THREADS'):
    os.environ.setdefault(_v, '1')          # many jobs per box: no per-job BLAS / OpenMP thread pools sized to the whole machine
LOGBUF = []; LOGLOCK = threading.Lock()
NCPU = os.cpu_count() or 4
RECENT_S = 90                               # a job started this recently has not shown its CPU use in the load yet
JOB_CORES = {'ifc': 3.0, 'db1': 3.0, 'sds2': 1.5, 'grade': 1.5, 'final': 1.5}   # CPUQuota per job (hard cap) and CPU projection


def primary_pipe():
    """the pipeline this box was launched for (/opt/run-<pipe>.sh from the user-data); other pipelines here are assist loops"""
    for p in ('ifc', 'db1', 'sds2', 'grade', 'final'):
        if os.path.exists(f'/opt/run-{p}.sh'):
            return p
    return None
ENOSPC_MARKS = ('No space left on device', 'Errno 28', 'ENOSPC', 'Disk quota exceeded')


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def log(msg):
    line = time.strftime('%H:%M:%S ', time.gmtime()) + msg
    print(line, flush=True)
    with LOGLOCK:
        LOGBUF.append(line); del LOGBUF[:-800]


def mem():
    d = {}
    for ln in open('/proc/meminfo'):
        k, v = ln.split(':'); d[k] = int(v.split()[0]) * 1024
    return d['MemTotal'], d['MemAvailable']


def rss_tree(pid):
    """RSS of a process and all its descendants"""
    tot = 0; stack = [pid]; seen = set()
    while stack:
        q = stack.pop()
        if q in seen: continue
        seen.add(q)
        try:
            for ln in open(f'/proc/{q}/status'):
                if ln.startswith('VmRSS:'): tot += int(ln.split()[1]) * 1024
        except Exception:
            pass
        try:
            for t in os.listdir(f'/proc/{q}/task'):
                stack += [int(x) for x in open(f'/proc/{q}/task/{t}/children').read().split()]
        except Exception:
            pass
    return tot


def cg_mem(pid):
    """anonymous memory of the systemd scope the job command runs in (cgroup v2 memory.stat 'anon'): every page counted once,
    so forked children sharing pages copy-on-write (SDS2 v5.4.1 verify / repair children) are not double counted the way a
    sum of RSS would; None outside a scope"""
    try:
        with open(f'/proc/{pid}/cgroup') as fh:
            cg = fh.read().strip().splitlines()[-1].split('::', 1)[1]
        if not cg.endswith('.scope'):
            return None
        with open(f'/sys/fs/cgroup{cg}/memory.stat') as fh:
            for ln in fh:
                if ln.startswith('anon '):
                    return int(ln.split()[1])
    except Exception:
        return None
    return None


def job_mem(pid):
    m = cg_mem(pid)
    return rss_tree(pid) if m is None else m


def dir_size(d):
    tot = 0
    for root, dirs, files in os.walk(d):
        for f in files:
            try: tot += os.lstat(os.path.join(root, f)).st_size
            except OSError: pass
    return tot


def pid_alive(pid):
    try:
        os.kill(pid, 0); return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Fleet:
    def __init__(self, pipe, code, process, need_bytes=None, files=(), need_disk=None, redo=None, redo_ids_key=None, big=None):
        self.pipe = pipe; self.code = code; self.process = process
        self.CTL = f'{CTLROOT}/{pipe}'; self.ST = f'{ROOT}/_state/conv/{pipe}'
        self.need_bytes = need_bytes or (lambda job: 2 << 30)
        self.need_disk = need_disk or (lambda job: max(1 << 30, (job.get('size') or 0) * 10))
        self.redo = redo                          # redo(result_dict) -> True: re-run this job on this code
        self.files = files                       # kit files watched for hot reload
        self.running = {}; self.lock = threading.Lock(); self.stats = {'ok': 0, 'fail': 0, 'retry': 0, 'deferred': 0}
        self.procs = {}; self.killed = {}; self.disk_killed = set(); self.plock = threading.Lock()
        self.reload = False; self.stop_now = False; self.handed_off = False
        self.id = f'{HOST}-{PID}'
        self.home = os.environ.get('CONV_HOME', '/opt/conv')
        self.work = os.environ.get('CONV_WORK', f'{self.home}/work/{pipe}')
        os.makedirs(self.work, exist_ok=True)
        total, _ = mem(); self.total = total
        self.slots = int(os.environ.get('CONV_SLOTS', '0')) or max(1, (os.cpu_count() or 4) // 2)
        self.others = {'running': 0, 'need': 0, 'disk': 0, 'big': 0}
        # at most big[1] jobs of >= big[0] bytes at once per host (all worker processes together): their outputs are
        # the ones that fill a disk (several 200 MB Tekla IFC wrote > 400 GB of STEP at once)
        b = big or (0, 0)
        self.big = (int(os.environ.get('CONV_BIG_MB', str(b[0] >> 20))) << 20, int(os.environ.get('CONV_BIG_MAX', str(b[1]))))
        self.redo_entries = []
        self.rcache = {}                          # result key -> (etag, redo?, code)
        self.redo_ids_key = os.environ.get('CONV_REDO_IDS_KEY') or redo_ids_key; self.redo_ids = set()   # ids re-run on this code (re-read every round, no reload)
        self.etags = self._etags()
        self.rundir = os.path.join(self.home, 'run'); os.makedirs(self.rundir, exist_ok=True)
        self.jobs_cache = {}
        self.primary = primary_pipe()
        self.is_primary = self.primary is None or self.primary == pipe
        self.job_cores = float(os.environ.get('CONV_JOB_CORES', '0')) or JOB_CORES.get(pipe, 2.0)
        self.cpu_frac = float(os.environ.get('CONV_CPU_FRAC', '0.9')); self.cpu_frac_assist = 0.85
        self.cpu_frac_env = 'CONV_CPU_FRAC' in os.environ
        self.runq = collections.deque(maxlen=10)
        self.mem_tabs = {}                        # pipe -> [table, etag, read time]
        self.gate = {}                            # last claim-gate reading (heartbeat)
        self.retired = False
        self.slice = self._job_slice()
        self.runaway = {}                         # jid -> MemoryMax a command of the job hit (converter memory runaway)
        self.resv_factor = 1.3; self.resv_factor_assist = 1.15; self.mem_floor = 0.08
        self.quota_cores = None                   # CPUQuota per job (env quota_cores); job_cores is the admission estimate

    # ---------------------------------------------------------------- S3 helpers
    def put(self, key, obj):
        assert key.startswith(ROOT + '/'), key
        s3.put_object(Bucket=B, Key=key, Body=json.dumps(obj, default=str).encode(), ContentType='application/json')

    def getj(self, key, bucket=B):
        try:
            return json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read())
        except ClientError:
            return None

    def exists(self, key, bucket=B):
        try:
            s3.head_object(Bucket=bucket, Key=key); return True
        except ClientError:
            return False

    def ctl_exists(self, name):
        return self.exists(f'{self.CTL}/{name}', CB)

    def ctl_env(self):
        try:
            v = self._ctl_env_raw()
            if isinstance(v, dict) and v:
                self._env_last = v
                return v
        except Exception as e:
            log(f'WARNING: env.json unreadable ({type(e).__name__}): keeping the last good copy')
        return getattr(self, '_env_last', {}) or {}

    def _ctl_env_raw(self):
        return self.getj(f'{self.CTL}/env.json', CB) or {}

    def upload(self, path, key, ctype=None):
        assert key.startswith(ROOT + '/') and '/_control/' not in key, key
        s3.upload_file(path, B, key, ExtraArgs={'ContentType': ctype} if ctype else None)

    def listing(self, sub):
        out = {}
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{self.ST}/{sub}/'):
            for o in page.get('Contents', []):
                out[o['Key'].rsplit('/', 1)[-1].rsplit('.json', 1)[0]] = o
        return out

    def _etags(self):
        out = {}
        for f in self.files:
            try:
                out[f] = s3.head_object(Bucket=CB, Key=f'{self.CTL}/{f}')['ETag']
            except ClientError:
                out[f] = None
        return out

    def done_ids(self, results):
        """result ids that count as final for this code (redo() re-opens some results of older code)"""
        need = [(k, o) for k, o in results.items() if self.rcache.get(k, (None,))[0] != o['ETag']]

        def chk(ko):
            k, o = ko
            try:
                r = json.loads(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read())
            except Exception:
                return k, None, False, None, None, ''          # not cached: read again next round
            rd = False
            if self.redo and r.get('code') != self.code:
                try:
                    rd = bool(self.redo(r))
                except Exception as e:                          # a redo rule error must not hide code/reason/finished
                    log(f'redo rule error on {k[:16]}: {type(e).__name__}: {e}')
            return k, o['ETag'], rd, r.get('code'), r.get('reason'), r.get('finished') or ''
        if need:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(32) as ex:
                for k, e, rd, c, rs, fin in ex.map(chk, need):
                    self.rcache[k] = (e, rd, c, rs, fin)
        if self.redo_ids_key:
            # {"codes": [older codes whose outputs are affected], "ids": [...]}: re-open those ids while their result
            # still comes from one of those codes
            # {"entries": [{"ids": [...] | "reasons": [...], "codes": [...], "before": "<UTC ISO>"}], or legacy {"codes", "ids"}:
            # re-open a result that matches an entry (id or failure reason; written by one of `codes` if given; finished
            # before `before` if given - so the re-run's own result is final)
            try:
                d = json.loads(s3.get_object(Bucket=CB, Key=self.redo_ids_key)['Body'].read())
                if isinstance(d, dict):
                    ents = list(d.get('entries') or [])
                    if d.get('ids'):
                        ents.append({'ids': d.get('ids'), 'codes': d.get('codes') or []})
                    self.redo_entries = [{'ids': set(e.get('ids') or []), 'reasons': set(e.get('reasons') or []),
                                          'codes': set(e.get('codes') or []), 'before': e.get('before') or ''} for e in ents]
            except Exception:
                pass
        coord_redo = set()
        try:
            coord_redo = set(self._cached_list(f'{self.ST}/redo.json'))
        except Exception:
            pass
        out = set()
        for k in results:
            c = self.rcache.get(k, (None, False, None, None, ''))
            if c[1]:
                continue
            if k in coord_redo and c[2] != self.code:
                continue
            hit = False
            for e in self.redo_entries:
                if not ((k in e['ids']) or (c[3] and c[3] in e['reasons'])):
                    continue
                if e['codes'] and c[2] not in e['codes']:
                    continue
                if e['before'] and not (c[4] and c[4] < e['before']):
                    continue
                hit = True; break
            if not hit:
                out.add(k)
        return out

    def _cached_list(self, key):
        """json list in the state bucket, cached by ETag (missing -> [])"""
        try:
            et = s3.head_object(Bucket=B, Key=key)['ETag']
        except ClientError:
            return []
        c = self.jobs_cache.get(key)
        if c and c[0] == et:
            return c[1]
        body = s3.get_object(Bucket=B, Key=key)['Body'].read()
        v = json.loads(gzip.decompress(body) if body[:2] == b'\x1f\x8b' else body)
        if isinstance(v, dict):
            v = v.get('jobs') or v.get('ids') or []
        self.jobs_cache[key] = (et, v)
        return v

    def _cached_dict(self, key):
        """json object in the state bucket, cached by ETag (missing -> {})"""
        try:
            et = s3.head_object(Bucket=B, Key=key)['ETag']
        except ClientError:
            return {}
        c = self.jobs_cache.get(key)
        if c and c[0] == et:
            return c[1]
        try:
            body = s3.get_object(Bucket=B, Key=key)['Body'].read()
            v = json.loads(body) if body.strip() else None
        except Exception:
            v = None
        if not isinstance(v, dict) or not v:
            return (c or (None, {}))[1]                    # empty / unparsable: keep the last good copy
        self.jobs_cache[key] = (et, v)
        return v

    def _assist(self, env):
        """env.json {"assist": ["ifc", ...]}: this pipeline is idle on this box -> run another pipeline's worker loop here
        (kit synced from S3, its setup.sh run once; one assist loop per pipeline per box, pidfile in the run dir)"""
        if not self.is_primary:
            return                                # an assist worker never starts further assist loops
        for a in env.get('assist') or []:
            if a == self.pipe or a not in ('ifc', 'db1', 'sds2', 'grade', 'final'):
                continue
            pf = os.path.join(self.rundir, f'assist-{a}.pid')
            try:
                if pid_alive(int(open(pf).read().strip())):
                    continue
            except Exception:
                pass
            W = self.home; scr = os.path.dirname(self.work)
            sh = (f'set -x; export AWS_DEFAULT_REGION=ap-south-1; unset LD_LIBRARY_PATH; K={W}/kit/{a}; mkdir -p $K {scr}/{a}; '
                  f'sync_kit() {{ mkdir -p $K.stage; aws s3 sync --only-show-errors s3://{CB}/{CTLROOT}/{a}/ $K.stage/ --exclude "*" --include "*.py" --include "*.sh" '
                  f'--include "*.json" --include "*.zip" --include "*.txt" --exclude "*/*"; for f in $K.stage/*; do [ -f "$f" ] || continue; b=$(basename "$f"); '
                  f'if [ -s "$f" ]; then cmp -s "$f" "$K/$b" || cp -p "$f" "$K/$b"; else echo "WARNING empty $b on S3 ignored"; fi; done; }}; sync_kit; '
                  f'bash $K/setup.sh {W} $K > {W}/setup-assist-{a}.log 2>&1; '
                  f'pyb() {{ c=""; [ -s $K/pybin.txt ] && c={W}/$(head -c 200 $K/pybin.txt | tr -d "\\r\\n "); '
                  f'if [ -n "$c" ] && [ -f "$c" ] && [ -x "$c" ]; then echo "$c" > {W}/.pybin.last.{a}; echo "$c"; '
                  f'elif [ -s {W}/.pybin.last.{a} ]; then echo "WARNING pybin invalid, last good used" >&2; cat {W}/.pybin.last.{a}; '
                  f'elif [ -x {W}/sds2env/bin/python ] && [ {a} = sds2 ]; then echo {W}/sds2env/bin/python; else echo {W}/env/bin/python; fi; }}; '
                  f'while true; do sync_kit; aws s3api head-object --bucket {CB} --key {CTLROOT}/{a}/stop > /dev/null 2>&1 && {{ sleep 300; continue; }}; PYB=$(pyb); '
                  f'CONV_HOME={W} CONV_WORK={scr}/{a} CONV_DONE={W}/DONE.{a} $PYB $K/worker.py >> {W}/worker-assist-{a}.log 2>&1; '
                  f'[ -f {W}/DONE.{a} ] && break; sleep 20; done')
            try:
                p = subprocess.Popen(['bash', '-c', sh], stdout=open(os.path.join(W, f'assist-{a}.out'), 'a'), stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
                open(pf, 'w').write(str(p.pid))
                log(f'assist: started {a} worker loop on this box (pid {p.pid})')
            except Exception as e:
                log(f'assist {a} failed: {e}')

    # ---------------------------------------------------------------- host-wide capacity
    def _job_slice(self):
        """every job scope runs under z3jobs.slice: MemoryMax = RAM - 24 GB, MemoryHigh = RAM - 32 GB, so the kernel, SSM agent, worker loops
        and uploads always keep memory (03:12Z the coordinator wedged when its jobs took it all)"""
        if os.geteuid() != 0 or not os.path.exists('/usr/bin/systemd-run'):
            return None
        try:
            mx = max(8 << 30, self.total - (24 << 30)); hi = max(6 << 30, self.total - (32 << 30))
            unit = f'[Unit]\nDescription=z3conv job scopes\n[Slice]\nMemoryAccounting=yes\nMemoryMax={mx}\nMemoryHigh={hi}\nMemorySwapMax=0\n'
            f = '/etc/systemd/system/z3jobs.slice'
            cur = open(f).read() if os.path.exists(f) else None
            if cur != unit:
                open(f + '.tmp', 'w').write(unit); os.replace(f + '.tmp', f)
                subprocess.run(['systemctl', 'daemon-reload'], timeout=60)   # loaded on demand by the first scope; never restarted (would stop jobs)
            return 'z3jobs.slice'
        except Exception as e:
            log(f'job slice setup failed: {type(e).__name__}: {e}')
            return None

    def _mem_tab(self, pipe=None):
        """coordinator's measured table _state/conv/<pipe>/mem_buckets.json (re-read at most every 2 min, ETag-cached); any pipeline's
        table (the registry holds jobs of every pipeline on the host)"""
        pipe = pipe or self.pipe
        c = self.mem_tabs.get(pipe) or [None, None, 0]
        if time.time() - c[2] < 120:
            return c[0]
        c[2] = time.time()
        try:
            key = f'{ROOT}/_state/conv/{pipe}/mem_buckets.json'
            et = s3.head_object(Bucket=B, Key=key)['ETag']
            if et != c[1]:
                c[0] = json.loads(s3.get_object(Bucket=B, Key=key)['Body'].read()); c[1] = et
        except Exception:
            pass
        self.mem_tabs[pipe] = c
        return c[0]

    def mem_override(self, jid):
        """per-model memory exception (control coord/mem_overrides.json {id prefix: GB}): reservation, expectation and the converter's
        MemoryMax all use it (e.g. two IFC models that need ~300 GB run alone on a box with that much free)"""
        if time.time() - getattr(self, '_mo_t', 0) > 120:
            self._mo_t = time.time()
            try:
                v = self.getj(f'{CTLROOT}/coord/mem_overrides.json', CB)
                if isinstance(v, dict):
                    self._mo = v
            except Exception:
                pass
        for k, gb in (getattr(self, '_mo', None) or {}).items():
            if jid and str(jid).startswith(k) and isinstance(gb, (int, float)):
                return int(gb * (1 << 30))
        return None

    def mem_need(self, job):
        """reservation: the kit's estimate, replaced by the measured bucket value (1.2 x p95 peak RSS) when the coordinator has one,
        and never below 1.2 x this job's own measured peak (earlier run)"""
        mo = self.mem_override(job.get('id'))
        if mo:
            return min(mo, int(self.total * 0.8))
        need = self.need_bytes(job)
        tb = self._mem_tab() or {}
        sz = (job.get(tb.get('size_field') or 'size') or job.get('size') or 0) * (tb.get('kind_factor') or {}).get(job.get('kind'), 1)
        for b in tb.get('buckets') or []:
            if b.get('lo', 0) <= sz < b.get('hi', 1 << 62) and b.get('reserve_bytes'):
                need = int(b['reserve_bytes']) if b.get('replace', True) else max(need, int(b['reserve_bytes']))
                break
        pk = (tb.get('peak_by_id') or {}).get(job.get('id'))
        if pk:
            need = max(need, int(float(pk) * 1.2 * (1 << 30)))
        return min(need, int(self.total * 0.8))

    def mem_expect(self, job, pipe=None):
        """memory a job is expected to hold (admission): the median measured peak of its size bucket, or its own measured peak from an
        earlier run; half the reservation when the coordinator has no table yet"""
        mo = self.mem_override(job.get('id')) if (pipe or self.pipe) == self.pipe else None
        if mo:
            return min(mo, int(self.total * 0.8))
        tb = self._mem_tab(pipe) or {}
        sz = (job.get(tb.get('size_field') or 'size') or job.get('size') or 0) * (tb.get('kind_factor') or {}).get(job.get('kind'), 1)
        ex = None
        for b in tb.get('buckets') or []:
            if b.get('lo', 0) <= sz < b.get('hi', 1 << 62) and b.get('expected_bytes'):
                ex = int(b['expected_bytes']); break
        if ex is None:
            ex = self.mem_need(job) // 2 if (pipe or self.pipe) == self.pipe else 4 << 30
        pk = (tb.get('peak_by_id') or {}).get(job.get('id'))
        if pk:
            ex = max(ex, int(float(pk) * (1 << 30)))
        return min(ex, int(self.total * 0.8))

    def _p50_runtime(self, pipe, size):
        tb = self._mem_tab(pipe) or {}
        sz = size or 0
        for b in tb.get('buckets') or []:
            if b.get('lo', 0) <= sz < b.get('hi', 1 << 62):
                return b.get('p50_runtime_s')
        return None

    def _write_reg(self):
        with self.lock:
            jobs = [{'id': k, 'need': v.get('need') or 0, 'exp': v.get('exp') or v.get('need') or 0, 'rss': v.get('rss') or 0, 'peak': v.get('peak_rss') or 0,
                     't0': v.get('t0') or 0, 'cores': v.get('cores') or self.job_cores, 'size': v.get('size')} for k, v in self.running.items()]
        with self.plock:
            pids = {k: [p.pid for p in ps] for k, ps in self.procs.items() if ps}
        for j in jobs:
            j['pids'] = pids.get(j['id'], [])
        doc = {'pid': PID, 'pipe': self.pipe, 'code': self.code, 'at': time.time(), 'primary': self.is_primary, 'jobs': jobs, 'wd_rev': WD_REV}
        f = os.path.join(self.rundir, f'reg-{PID}.json')
        try:
            with open(f + '.tmp', 'w') as fh:
                json.dump(doc, fh)
            os.replace(f + '.tmp', f)
        except Exception:
            pass

    def _host(self):
        """every job running on this host (all pipelines / generations), from the local registry files + this process; worker
        processes of older code (no registry) are counted from this pipeline's S3 heartbeats"""
        jobs = []; seen = {PID}; now_ = time.time()
        for f in os.listdir(self.rundir):
            if not (f.startswith('reg-') and f.endswith('.json')):
                continue
            try:
                x = json.load(open(os.path.join(self.rundir, f)))
                pid = int(x.get('pid') or 0)
            except Exception:
                continue
            if pid == PID:
                continue
            if not pid_alive(pid):
                try: os.remove(os.path.join(self.rundir, f))
                except OSError: pass
                continue
            if now_ - x.get('at', 0) > 60:
                continue
            seen.add(pid)
            for j in x.get('jobs') or []:
                j['pipe'] = x.get('pipe'); j['pid'] = pid
                if not j.get('exp'):                  # entry of an early v2 generation (reservation only): its bucket median
                    try:
                        j['exp'] = min(j.get('need') or 0, self.mem_expect({'id': j.get('id'), 'size': j.get('size'), 'model_bytes': j.get('size')}, j['pipe']))
                    except Exception:
                        pass
                jobs.append(j)
        with self.lock:
            for k, v in self.running.items():
                jobs.append({'id': k, 'need': v.get('need') or 0, 'exp': v.get('exp') or v.get('need') or 0, 'rss': v.get('rss') or 0, 't0': v.get('t0') or 0,
                             'cores': v.get('cores') or self.job_cores, 'pipe': self.pipe, 'pid': PID})
        for pid, o in (self.others.get('by_pid') or {}).items():
            if int(pid) not in seen:
                for j in o:
                    jobs.append(dict(j, pipe=self.pipe, pid=int(pid), legacy=True))
        # admission counts every job at max(RSS, expected); registry files of the first v2 generations have no 'exp' -> their reservation
        # (an entry claimed from an inflated legacy deferred record counts at most a quarter of the host unless its RSS is higher)
        q = int(self.total * 0.25)
        resv = sum(max(min(j.get('exp') or j.get('need') or 0, q), j.get('rss') or 0) for j in jobs)
        growth = sum(max(0, min(j.get('exp') or j.get('need') or 0, q) - (j.get('rss') or 0)) for j in jobs)
        recent = sum((j.get('cores') or 1) for j in jobs if now_ - (j.get('t0') or 0) < RECENT_S)
        # growth still to come = jobs younger than their bucket's median runtime that are below their expected memory
        gy = 0
        for j in jobs:
            if not j.get('t0'):
                continue                              # legacy entries: age unknown -> their RSS is already in MemAvailable
            p50 = self._p50_runtime(j.get('pipe'), j.get('size')) or 1800
            if now_ - j['t0'] < p50:
                gy += max(0, min(j.get('exp') or j.get('need') or 0, q) - (j.get('rss') or 0))
        rbp = collections.Counter(); cbp = collections.Counter()
        for j in jobs:
            rbp[j.get('pipe')] += max(min(j.get('exp') or j.get('need') or 0, q), j.get('rss') or 0)
            cbp[j.get('pipe')] += j.get('cores') or self.job_cores
        return {'n': len(jobs), 'resv': resv, 'growth': growth, 'growth_young': gy, 'recent_cores': recent, 'jobs': jobs,
                'resv_by_pipe': dict(rbp), 'cores_by_pipe': dict(cbp),
                'by_pipe': dict(collections.Counter(j.get('pipe') for j in jobs))}

    def _cpu(self):
        load1 = os.getloadavg()[0]
        rq = (sum(self.runq) / len(self.runq)) if self.runq else load1
        return max(load1, rq)

    # ---------------------------------------------------------------- claims
    def claim(self, jid):
        key = f'{self.ST}/claims/{jid}.json'
        body = json.dumps({'host': HOST, 'pid': PID, 'at': now(), 'code': self.code}).encode()
        try:
            s3.put_object(Bucket=B, Key=key, Body=body, IfNoneMatch='*'); return True
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') not in ('PreconditionFailed', '412', 'ConditionalRequestConflict', '409'):
                raise
        try:
            h = s3.head_object(Bucket=B, Key=key)
        except ClientError:
            return False
        if time.time() - h['LastModified'].timestamp() < STALE_S:
            return False
        try:                                      # stale: atomic takeover (only if nobody refreshed it meanwhile)
            s3.put_object(Bucket=B, Key=key, Body=body, IfMatch=h['ETag'])
            log(f'took over stale claim {jid[:16]}'); return True
        except ClientError:
            return False

    def release(self, jid):
        try:
            s3.delete_object(Bucket=B, Key=f'{self.ST}/claims/{jid}.json')
        except Exception:
            pass

    # ---------------------------------------------------------------- subprocess runner
    def run(self, jid, cmd, logf, timeout, stall=None, mem_frac=0.85, env=None, cwd=None, mem_max=None):
        """rc of cmd; 124 = overall timeout, 125 = stalled (log unchanged for `stall` s), -9 = memory kill, 128 = disk kill"""
        jt = os.path.join(self.work, jid[:40], 'tmp')
        try:
            os.makedirs(jt, exist_ok=True)
            env = dict(env if env is not None else os.environ)
            env['TMPDIR'] = env['TMP'] = env['TEMP'] = jt          # temp files on the job's disk dir, removed with the job
        except OSError:
            pass
        if os.path.exists('/usr/bin/systemd-run') and os.geteuid() == 0:
            mmax = int(self.total * mem_frac) if not mem_max else min(int(self.total * mem_frac), int(mem_max))
            cmd = ['systemd-run', '--scope', '--quiet'] + ([f'--slice={self.slice}'] if self.slice else []) + ['-p', f'MemoryMax={mmax}', '-p', 'MemorySwapMax=0',
                   '-p', f'CPUQuota={int((self.quota_cores or self.job_cores) * 100)}%'] + list(cmd)
        with open(logf, 'a') as lf:
            lf.write(f'\n$ {" ".join(map(str, cmd))[:600]}\n'); lf.flush()
            p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=cwd, start_new_session=True)
            with self.plock:
                self.procs.setdefault(jid, []).append(p)
            try:
                t0 = time.time(); last = -1; changed = t0; rc = None
                while rc is None:
                    try:
                        rc = p.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        try:
                            r_ = job_mem(p.pid)
                            with self.lock:
                                if jid in self.running:
                                    self.running[jid]['rss'] = r_
                                    self.running[jid]['peak_rss'] = max(self.running[jid].get('peak_rss', 0), r_)
                        except Exception:
                            pass
                        t = time.time()
                        if t - t0 > timeout:
                            # CPU-aware limit (lead 06:35Z): a job starved of CPU (memory.high throttling, contention) gets more wall
                            # time while it has used < 60 % of the limit in CPU seconds, up to 2x the limit
                            cs = cg_cpu_s(p.pid)
                            if cs is not None and cs < 0.6 * timeout and t - t0 < 2 * timeout:
                                if not getattr(p, '_ext_logged', False):
                                    log(f'{jid[:16]}: wall limit {timeout}s reached with only {cs:.0f} CPU-s: extended (starved, up to 2x)')
                                    p._ext_logged = True
                            else:
                                self._kill(p); rc = 124; break
                        if stall:
                            try: sz = os.path.getsize(logf)
                            except OSError: sz = last
                            if sz != last: last = sz; changed = t
                            elif t - changed > stall:
                                self._kill(p); rc = 125; break
                        if self.stop_now:
                            self._kill(p); rc = 130; break
            finally:
                with self.plock:
                    try: self.procs.get(jid, []).remove(p)
                    except ValueError: pass
        if jid in self.disk_killed:
            raise DiskFull()
        if jid in self.killed:
            rc = -9
        elif mem_max and rc in (-9, 137):
            with self.lock:
                pk = (self.running.get(jid) or {}).get('peak_rss', 0)
            if pk >= 0.85 * mem_max:                  # the command hit its own MemoryMax: converter memory runaway
                self.runaway[jid] = int(mem_max)
                rc = -9
        return rc

    def _kill(self, p):
        try: os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            try: p.kill()
            except Exception: pass
        try: p.wait(timeout=60)
        except Exception: pass

    def sh(self, cmd, timeout=600, env=None):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr

    def disk(self):
        u = shutil.disk_usage(self.work)
        return u.total, u.free

    # ---------------------------------------------------------------- threads
    def _beat(self):
        while True:
            try:
                t, a = mem(); dt, df = self.disk()
                with self.lock:
                    run = [{'id': k, 'since': v['since'], 'size': v['size'], 'need': v['need'], 'disk': v['disk'], 'rss': v.get('rss'),
                            'peak_rss': v.get('peak_rss')} for k, v in self.running.items()]
                    snap = {'host': HOST, 'pid': PID, 'code': self.code, 'runtime': RUNTIME, 'at': now(), 'slots': self.slots, 'running': run,
                            'cpus': os.cpu_count(),
                            'stats': dict(self.stats), 'mem_total_gb': t >> 30, 'mem_avail_gb': a >> 30,
                            'disk_total_gb': dt >> 30, 'disk_free_gb': df >> 30, 'others': dict(self.others),
                            'load': os.getloadavg()[0], 'reload_pending': self.reload, 'handed_off': self.handed_off,
                            'primary': self.is_primary, 'primary_pipe': self.primary, 'job_cores': self.job_cores, 'gate': dict(self.gate)}
                self.put(f'{self.ST}/hosts/{self.id}.json', snap)
                with LOGLOCK:
                    s3.put_object(Bucket=B, Key=f'{self.ST}/logs/{self.id}.log', Body='\n'.join(LOGBUF).encode())
                self._others()
            except Exception:
                pass
            time.sleep(60)

    def _others(self):
        """capacity used by the other live worker processes on this host (old code finishing its jobs, siblings)"""
        o = {'running': 0, 'need': 0, 'disk': 0, 'big': 0, 'pids': [], 'by_pid': {}}
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{self.ST}/hosts/{HOST}-'):
            for ob in page.get('Contents', []):
                if ob['Key'].endswith(f'-{PID}.json') or time.time() - ob['LastModified'].timestamp() > 180:
                    continue
                h = self.getj(ob['Key']) or {}
                if h.get('host') != HOST or h.get('pid') == PID or not pid_alive(int(h.get('pid') or 0)):
                    continue
                o['pids'].append(h.get('pid'))
                bp = o['by_pid'].setdefault(int(h.get('pid') or 0), [])
                for r in h.get('running') or []:
                    o['running'] += 1
                    if self.big[1] and (r.get('size') or 0) >= self.big[0]:
                        o['big'] += 1
                    est = self.need_bytes({'size': r.get('size'), 'model_bytes': r.get('size'), 'kind': r.get('kind')})
                    o['need'] += min(r.get('need') or est, est)                  # stored reservations of older code can be inflated
                    jx = {'id': r.get('id'), 'size': r.get('size'), 'model_bytes': r.get('size'), 'kind': r.get('kind')}
                    bp.append({'id': r.get('id'), 'need': min(r.get('need') or est, est), 'exp': min(r.get('need') or est, self.mem_expect(jx)),
                               'rss': r.get('rss') or 0, 't0': 0, 'cores': self.job_cores})
                    o['disk'] += r.get('disk') or self.need_disk({'size': r.get('size')})
        self.others = o

    def _refresh_claims(self):
        while True:
            time.sleep(300)
            with self.lock:
                ids = list(self.running)
            for jid in ids:
                try:
                    s3.put_object(Bucket=B, Key=f'{self.ST}/claims/{jid}.json',
                                  Body=json.dumps({'host': HOST, 'pid': PID, 'at': now(), 'code': self.code, 'refresh': True}).encode())
                except Exception:
                    pass

    def _scopes(self):
        """every job command on the host runs in a systemd scope: (anon bytes, scope dir, pids, age s) for each, whatever process owns it
        (also workers of older code that publish nothing)"""
        out = []; tnow = time.time()
        try:
            hz = os.sysconf('SC_CLK_TCK'); boot = float(open('/proc/stat').read().split('btime ')[1].split()[0])
        except Exception:
            hz, boot = 100, 0
        cands = []
        for base in ('/sys/fs/cgroup/system.slice', '/sys/fs/cgroup/z3jobs.slice'):
            try:
                cands += [os.path.join(base, x) for x in os.listdir(base) if x.startswith('run-') and x.endswith('.scope')]
            except OSError:
                pass
        for c in cands:
            try:
                anon = 0
                with open(os.path.join(c, 'memory.stat')) as fh:
                    for ln in fh:
                        if ln.startswith('anon '):
                            anon = int(ln.split()[1]); break
                pids = [int(x) for x in open(os.path.join(c, 'cgroup.procs')).read().split()]
                if not pids:
                    continue
                st = min(float(open(f'/proc/{q}/stat').read().rsplit(')', 1)[1].split()[19]) for q in pids)
                out.append((anon, c, pids, max(1.0, tnow - (boot + st / hz))))
            except Exception:
                continue
        return out

    def _leader(self):
        """lowest live pid among the registry writers of the newest watchdog revision on this host does the host-wide kills
        (05:55Z: an older-generation leader that scanned system.slice only left z3jobs.slice jobs thrashing at MemoryHigh, no kill)"""
        ps = []
        for f in os.listdir(self.rundir):
            if f.startswith('reg-') and f.endswith('.json'):
                try:
                    q = int(f[4:-5])
                    if not pid_alive(q):
                        continue
                    rv = json.load(open(os.path.join(self.rundir, f))).get('wd_rev') or 0
                    if rv >= WD_REV: ps.append(q)
                except Exception:
                    pass
        return min(ps + [PID]) == PID

    def _host_kill(self, a):
        """memory below the kill line: kill one job scope host-wide. First the registered job furthest above its reservation; else
        the scope that loses the least work per GB freed (youngest per GB, at least 2 GB). The owner sees its command die (-9 =
        memory kill -> deferred, retried with 1.6x its measured peak); a marker file tells a registered owner which job it was."""
        sc = self._scopes()
        if not sc:
            return False
        H = self._host(); bypid = {}
        for j in H['jobs']:
            for q in j.get('pids') or []:
                bypid[q] = j
        cand = []
        for anon, c, pids, age in sc:
            j = next((bypid[q] for q in pids if q in bypid), None)
            cand.append((anon, c, pids, age, j))
        over = [x for x in cand if x[4] is not None and x[4].get('need') and x[0] > x[4]['need']]
        if over:
            v = max(over, key=lambda x: x[0] - x[4]['need']); why = 'furthest above its reservation'
        else:
            big_ = [x for x in cand if x[0] >= 2 << 30]
            if not big_:
                return False
            v = min(big_, key=lambda x: x[3] / x[0]); why = 'least work lost per GB freed'
        anon, c, pids, age, j = v
        if j is not None:
            try:
                open(os.path.join(self.rundir, f"killed-{j['id']}"), 'w').write(str(max(anon, j.get('peak') or 0)))
            except Exception:
                pass
        try:
            open(os.path.join(c, 'cgroup.kill'), 'w').write('1')
        except Exception:
            for q in pids:
                try: os.kill(q, signal.SIGKILL)
                except Exception: pass
        log(f"WATCHDOG host-wide killed scope {os.path.basename(c)[:22]} job={(j or {}).get('id', '?')[:16]} anon={anon >> 30}GB "
            f"age={int(age)}s need={((j or {}).get('need') or 0) >> 30}GB avail={a >> 30}GB ({why})")
        return True

    def _watchdog(self):
        n = 0
        mine = os.path.join(self.rundir, f'rss-{PID}.json')
        while True:
            try:
                try:
                    with open('/proc/stat') as fh:
                        for ln in fh:
                            if ln.startswith('procs_running'):
                                self.runq.append(max(0, int(ln.split()[1]) - 1)); break
                except Exception:
                    pass
                with self.plock:
                    cand = [(sum(job_mem(p.pid) for p in ps), jid, ps) for jid, ps in self.procs.items() if ps]
                with self.lock:                   # peak RSS sampled every second (the job runner samples only every 20 s)
                    for r_, jid_, _ in cand:
                        if jid_ in self.running:
                            self.running[jid_]['rss'] = r_
                            self.running[jid_]['peak_rss'] = max(self.running[jid_].get('peak_rss', 0), r_)
                if n % 2 == 0:
                    self._write_reg()
                big = max((c[0] for c in cand), default=0)
                try:
                    json.dump({'pid': PID, 'max_rss': big, 'at': time.time()}, open(mine + '.tmp', 'w')); os.replace(mine + '.tmp', mine)
                except Exception:
                    pass
                t, a = mem()
                for jid_ in list(self.running):
                    mk = os.path.join(self.rundir, f'killed-{jid_}')
                    if os.path.exists(mk):              # the host leader killed this job's scope
                        try:
                            self.killed[jid_] = max(int(open(mk).read() or 0), (self.running.get(jid_) or {}).get('peak_rss', 0))
                            os.remove(mk)
                        except Exception:
                            pass
                if a < max(4 << 30, int(t * 0.10)):
                    if self._leader() and self._host_kill(a):
                        time.sleep(10)
                    n += 1
                    time.sleep(1)
                    continue
                if False and a < max(4 << 30, int(t * 0.10)) and cand:
                    # host-wide victim: the job furthest above its reservation (the one breaking the plan); only when no job is above
                    # its reservation, the largest. Only the owning process kills it. Processes of older code (no registry) keep
                    # the old rule (largest job on the host).
                    H = self._host()
                    # worker processes of older code on this host (any pipeline): they write rss-<pid>.json but no registry; while
                    # any is alive the registry does not see all memory -> everybody keeps the old rule (largest job on the host)
                    regp = {f[4:-5] for f in os.listdir(self.rundir) if f.startswith('reg-') and f.endswith('.json')}
                    legacy = False
                    for f in os.listdir(self.rundir):
                        if f.startswith('rss-') and f.endswith('.json') and f[4:-5] not in regp and f[4:-5] != str(PID):
                            try:
                                x = json.load(open(os.path.join(self.rundir, f)))
                                if time.time() - x.get('at', 0) < 30 and pid_alive(int(x.get('pid', 0))):
                                    legacy = True; break
                            except Exception:
                                pass
                    if not legacy and not any(j.get('legacy') for j in H['jobs']) and H['jobs']:
                        js = [j for j in H['jobs'] if (j.get('rss') or 0) > 0]
                        over = max(js, key=lambda j: (j.get('rss') or 0) - (j.get('need') or 0), default=None)
                        if over is not None and (over.get('rss') or 0) <= (over.get('need') or 0):
                            # nobody is above its reservation: lose the least work per GB freed (young jobs with a large RSS first)
                            big_ = [j for j in js if (j.get('rss') or 0) >= 2 << 30] or js
                            over = min(big_, key=lambda j: max(1.0, time.time() - (j.get('t0') or 0)) / max(j.get('rss') or 1, 1))
                        if over is not None and over.get('pid') == PID:
                            r, jid, ps = next(((c[0], c[1], c[2]) for c in cand if c[1] == over['id']), (0, None, None))
                            if jid:
                                with self.lock:
                                    pk = (self.running.get(jid) or {}).get('peak_rss', 0)
                                self.killed[jid] = max(r, pk)
                                for p in ps: self._kill(p)
                                log(f"WATCHDOG killed {jid[:16]} rss={r >> 30}GB need={(over.get('need') or 0) >> 30}GB avail={a >> 30}GB "
                                    f"(furthest above its reservation on this host)")
                                time.sleep(10)
                        n += 1
                        time.sleep(1)
                        continue
                    host_max = big
                    for f in os.listdir(self.rundir):
                        if f.startswith('rss-') and f != os.path.basename(mine):
                            try:
                                x = json.load(open(os.path.join(self.rundir, f)))
                                if time.time() - x.get('at', 0) < 30 and pid_alive(int(x.get('pid', 0))):
                                    host_max = max(host_max, x.get('max_rss', 0))
                            except Exception:
                                pass
                    if big >= host_max:
                        r, jid, ps = max(cand, key=lambda x: x[0])
                        with self.lock:
                            pk = (self.running.get(jid) or {}).get('peak_rss', 0)
                        self.killed[jid] = max(r, pk)
                        for p in ps: self._kill(p)
                        log(f'WATCHDOG killed {jid[:16]} rss={r >> 30}GB avail={a >> 30}GB (largest on host)')
                        time.sleep(10)
                n += 1
                if n % 10 == 0:
                    dt, df = self.disk()
                    if df < max(6 << 30, int(dt * 0.03)):
                        # disk nearly full: stop the most recently started job of this process (least work lost); it is
                        # released and re-run later, never recorded as a failure
                        with self.lock:
                            cand = sorted(((v['since'], k) for k, v in self.running.items() if k not in self.disk_killed), reverse=True)
                        if cand:
                            jid = cand[0][1]; self.disk_killed.add(jid)
                            with self.plock:
                                ps = list(self.procs.get(jid, []))
                            for p in ps: self._kill(p)
                            log(f'DISK WATCHDOG stopped {jid[:16]} free={df >> 30}GB')
                            time.sleep(20)
            except Exception:
                pass
            time.sleep(1)

    def _control(self):
        while True:
            time.sleep(90)
            try:
                if self.ctl_exists('stop') or self.exists(f'{CTLROOT}/stop', CB):
                    log('stop flag: finishing running jobs, claiming nothing new'); self.reload = True
                if not self.reload and self._etags() != self.etags:
                    log('new kit code on S3: hand-off (new process starts now, this one finishes its running jobs)')
                    self._handoff(); self.reload = True
                env = self.ctl_env()
                if env.get('slots'):
                    self.slots = int(env['slots'])
                if env.get('big_max'):
                    self.big = (self.big[0], int(env['big_max']))
                hs = (env.get('slots_by_cpus') or {}).get(str(os.cpu_count()))
                if hs:
                    self.slots = int(hs)
                if env.get('job_cores'):
                    self.job_cores = float(env['job_cores'])
                if env.get('quota_cores'):
                    self.quota_cores = float(env['quota_cores'])
                if env.get('resv_factor_assist'):
                    self.resv_factor_assist = float(env['resv_factor_assist'])
                if env.get('cpu_frac') and not self.cpu_frac_env:
                    self.cpu_frac = float(env['cpu_frac'])
                if env.get('cpu_frac_assist'):
                    self.cpu_frac_assist = float(env['cpu_frac_assist'])
                if env.get('resv_factor'):
                    self.resv_factor = float(env['resv_factor'])
                try:
                    adm = self.getj(f'{ROOT}/_state/conv/admission.json') or {}
                    if adm.get('resv_factor'):            # coordinator step-back (real kills): caps the env value
                        self.resv_factor = min(self.resv_factor, float(adm['resv_factor']))
                        self.resv_factor_assist = min(self.resv_factor_assist, float(adm['resv_factor']))
                except Exception:
                    pass
                if env.get('mem_floor'):
                    self.mem_floor = float(env['mem_floor'])
                if not self.reload and not self._assist_allowed():
                    log(f'assist for {self.pipe} is no longer listed by this box\'s pipeline ({self.primary}): finishing running jobs, claiming nothing new')
                    self.reload = True; self.retired = True
            except Exception:
                pass

    def _share(self):
        """fraction of this box this pipeline may use, from the box pipeline's env.json assist_share; None = no limit"""
        try:
            if self.is_primary:
                env = self.ctl_env()
                sh = env.get('assist_share') or {}
                tot = sum(float(v) for v in sh.values() if isinstance(v, (int, float)))
                return (1.0 - tot) if tot > 0 else None
            if not getattr(self, '_prim_env_t', 0) or time.time() - self._prim_env_t > 120:
                self._prim_env = self.getj(f'{CTLROOT}/{self.primary}/env.json', CB) or getattr(self, '_prim_env', {}) or {}
                self._prim_env_t = time.time()
            v = (self._prim_env.get('assist_share') or {}).get(self.pipe)
            return float(v) if isinstance(v, (int, float)) else None
        except Exception:
            return None

    def _release_now(self):
        """after the coordinator's final build (state marker final/FINAL_OK.json) a worker with nothing to do for 30 min writes DONE so
        its box powers off (user-data shutdown); the release time goes to _state/conv/<pipe>/released/<host>.json"""
        try:
            if not self.exists(f'{ROOT}/_state/conv/final/FINAL_OK.json'):
                self._idle_since = None
                return False
        except Exception:
            return False
        with self.lock:
            busy = len(self.running)
        try:
            # the box powers off when its primary writes DONE: every pipeline on this host must be idle (assist re-runs included)
            busy += self._host()['n']
        except Exception:
            busy += 1
        if busy:
            self._idle_since = None
            return False
        self._idle_since = getattr(self, '_idle_since', None) or time.time()
        if time.time() - self._idle_since < 1800:
            return False
        try:
            self.put(f'{self.ST}/released/{HOST}.json', {'host': HOST, 'pipeline': self.pipe, 'released': now(), 'primary': self.is_primary})
        except Exception:
            pass
        log('final pass done and idle 30 min: releasing (DONE)')
        return True

    def _assist_allowed(self):
        """an assist worker (pipeline other than the box's own) runs only while the box's pipeline lists it in its env.json"""
        if self.is_primary:
            return True
        try:
            env = self.getj(f'{CTLROOT}/{self.primary}/env.json', CB) or {}
        except Exception:
            return True
        return self.pipe in (env.get('assist') or [])

    def _handoff(self):
        """start the new code in a detached process right away (kit re-synced from S3); it shares this host's
        capacity with us through the heartbeats until our running jobs are finished"""
        if os.environ.get('CONV_NO_HANDOFF'):
            return
        try:                                      # the successor must not wait for us (same-code singleton rule)
            os.remove(os.path.join(self.rundir, f'{self.pipe}-{PID}.json'))
        except OSError:
            pass
        try:
            kit = os.path.dirname(os.path.abspath(sys.argv[0]))
            for page in s3.get_paginator('list_objects_v2').paginate(Bucket=CB, Prefix=f'{self.CTL}/'):
                for o in page.get('Contents', []):
                    rel = o['Key'][len(self.CTL) + 1:]
                    if not rel or '/' in rel or rel == 'jobs.json' or rel.startswith('_') or rel.endswith('.md'):
                        continue
                    if not o.get('Size'):
                        log(f'WARNING: {rel} is empty on S3: kept the local copy'); continue
                    tmp = os.path.join(kit, f'.{rel}.new'); s3.download_file(CB, o['Key'], tmp)
                    if os.path.getsize(tmp) == 0:
                        os.remove(tmp); continue
                    os.replace(tmp, os.path.join(kit, rel))
            logf = open(os.path.join(self.home, f'worker-{self.pipe}.log'), 'a')
            subprocess.Popen([sys.executable, os.path.join(kit, 'worker.py')], stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True, env=dict(os.environ))
            self.handed_off = True
        except Exception as e:
            log(f'hand-off failed ({type(e).__name__}: {e}); new code starts when this process exits')

    # ---------------------------------------------------------------- job execution
    def _work(self, job):
        jid = job['id']; d = os.path.join(self.work, jid[:40]); os.makedirs(d, exist_ok=True)
        t0 = time.time()
        res = {'id': jid, 'pipeline': self.pipe, 'code': self.code, 'runtime': RUNTIME, 'host': HOST, 'started': now(), 'size': job.get('size')}
        try:
            out = self.process(self, job, d) or {}
            res.update(out)
        except MemoryError:
            res['status'] = 'deferred'
        except DiskFull:
            res.update(status='fail', reason='disk_full_on_worker', transient=True, retry_limit=8)
        except Exception as e:
            res.update(status='fail', reason='worker_error', transient=True, error=f'{type(e).__name__}: {str(e)[:300]}',
                       trace=traceback.format_exc()[-1500:])
        if jid in self.disk_killed and res.get('status') != 'ok':
            res.update(status='fail', reason='disk_full_on_worker', transient=True, retry_limit=8)
        elif jid in self.killed and res.get('status') != 'ok':
            res['status'] = 'deferred'
        elif res.get('status') == 'fail' and any(m in json.dumps(res, default=str) for m in ENOSPC_MARKS):
            res.update(reason='disk_full_on_worker', transient=True, retry_limit=8, reason_before=res.get('reason'))
        self.disk_killed.discard(jid)
        res['sec'] = round(time.time() - t0, 1); res['finished'] = now()
        with self.lock:
            pk = (self.running.get(jid) or {}).get('peak_rss')
        if pk:
            res['peak_rss_gb'] = round(pk / 2 ** 30, 2)
        subprocess.run(['rm', '-rf', d])
        try:
            self._finish(job, res)
        except Exception as e:
            log(f'result write failed {jid[:16]}: {e}')
        with self.lock:
            self.running.pop(jid, None)
            self.stats[res['status'] if res['status'] in self.stats else 'fail'] += 1
        log(f"{res['status']:>8} {res.get('reason') or '':<24} {(job.get('size') or 0) >> 20:>6}MB {res['sec']:>7}s {jid[:16]}")

    def _finish(self, job, res):
        jid = job['id']
        if res['status'] == 'deferred':
            prev = self.getj(f'{self.ST}/deferred/{jid}.json') or {}
            # memory kill: usually concurrency on a full box, not a job bigger than the box -> re-run with 1.6x the RSS it reached
            # reserved (capped at 80% of a host), so it only starts where that much is free
            pm = prev.get('min_mem_bytes') or 0
            pm = 0 if pm > self.total * 0.8 else pm          # legacy records asked for more than a host
            with self.lock:
                pk_run = (self.running.get(jid) or {}).get('peak_rss', 0)
            peak = max(self.killed.get(jid, 0), pk_run, int((res.get('peak_rss_gb') or 0) * (1 << 30)))
            # retry reserves 1.6 x the measured peak (never less than an earlier kill asked for, nor the normal reservation)
            need = min(int(self.total * 0.8), max(int(peak * 1.6), pm, self.mem_need(job)))
            self.killed.pop(jid, None)
            runaway = self.runaway.pop(jid, None)
            kills = prev.get('kills', 0) + 1
            # only a kill of a job that really held memory counts toward the 5-kill limit (watchdog kills of 0-2 GB jobs were noise);
            # legacy records start a fresh count under this runtime
            counted = peak >= (2 << 30) and not runaway
            kv2 = (prev.get('kills_v2', 0) if prev.get('runtime') == RUNTIME else 0) + (1 if counted else 0)
            rec = {'id': jid, 'host': HOST, 'at': now(), 'kills': kills, 'kills_v2': kv2, 'kills_by_code': dict(prev.get('kills_by_code') or {}),
                   'size': job.get('size'), 'model_bytes': job.get('model_bytes'), 'peak_rss_gb': round(peak / 2 ** 30, 2),
                   'min_mem_bytes': need, 'min_mem_gb': need >> 30, 'runtime': RUNTIME}
            rec['kills_by_code'][self.code] = rec['kills_by_code'].get(self.code, 0) + 1
            if runaway:
                rec.update(reason=f'{self.pipe}_memory_runaway' if self.pipe != 'ifc' else 'v6_memory_runaway', hold_code=self.code,
                           mem_max_gb=runaway >> 30, min_mem_bytes=pm or self.mem_need(job), min_mem_gb=(pm or self.mem_need(job)) >> 30)
                self.put(f'{self.ST}/deferred/{jid}.json', rec)
                self.release(jid); return
            if kv2 >= 5:                            # killed five times while really holding memory
                res.update(status='fail', reason='out_of_memory', kills=kills, kills_v2=kv2, min_mem_gb=need >> 30)
            else:
                self.put(f'{self.ST}/deferred/{jid}.json', rec)
                self.release(jid); return
        if res.get('transient'):
            prev = self.getj(f'{self.ST}/retry/{jid}.json') or {}
            n = prev.get('attempts', 0) + 1
            if n < res.get('retry_limit', 3):
                self.put(f'{self.ST}/retry/{jid}.json', {'id': jid, 'attempts': n, 'last': res})
                self.release(jid); return
            res['attempts'] = n
        if res.get('status') not in ('ok', 'ok_stage1'):
            # a failed run never replaces an ok result: keep the stored one (stamped with this code so it is not re-run again)
            prev_r = self.getj(f'{self.ST}/results/{jid}.json') or {}
            if prev_r.get('status') in ('ok', 'ok_stage1'):
                prev_r['failed_rerun'] = {'code': self.code, 'reason': res.get('reason'), 'at': now(), 'host': HOST}
                prev_r['code_before'] = prev_r.get('code_before') or prev_r.get('code'); prev_r['code'] = self.code
                self.put(f'{self.ST}/results/{jid}.json', prev_r)
                self.release(jid); return
        self.put(f'{self.ST}/results/{jid}.json', res)
        self.release(jid)

    def _singleton(self):
        """one live process per code version per host: a second start of the same code (e.g. the boot loop restarting
        after the old code's process handed off) waits until the first one exits"""
        me = os.path.join(self.rundir, f'{self.pipe}-{PID}.json')
        waited = False
        while True:
            live = []
            for f in os.listdir(self.rundir):
                if not f.startswith(self.pipe + '-'): continue
                try:
                    x = json.load(open(os.path.join(self.rundir, f)))
                except Exception:
                    continue
                if x.get('pid') != PID and pid_alive(x.get('pid', 0)) and x.get('code') == self.code:
                    live.append(x['pid'])
                elif not pid_alive(x.get('pid', 0)):
                    try: os.remove(os.path.join(self.rundir, f))
                    except OSError: pass
            if not live:
                break
            waited = True
            time.sleep(60)
        if waited:
            # this process may have waited hours with the code it was started with: if the kit changed meanwhile, exit so the
            # boot loop starts the current code (a stale waiter once claimed jobs with old rules for 90 s before handing off)
            try:
                if self._etags() != self.etags:
                    log('kit changed while waiting for the previous process: exiting so the current code starts')
                    return False
            except Exception:
                pass
        json.dump({'pid': PID, 'code': self.code, 'at': now()}, open(me, 'w'))
        return True

    def main(self):
        if not self._assist_allowed():
            log(f'{self.pipe} assist is not listed by this box\'s pipeline ({self.primary}): idle'); time.sleep(600); return 3
        if self._singleton() is False:
            return 3
        log(f'{self.pipe} worker code={self.code} {RUNTIME} host={HOST} pid={PID} slots={self.slots} mem={self.total >> 30}GB '
            f'disk={self.disk()[0] >> 30}GB work={self.work}')
        try:
            self._others()                        # before the first claim: share the host with processes already running
            if self.others['running']:
                log(f"sharing host with pids {self.others['pids']}: {self.others['running']} jobs running there")
        except Exception as e:
            log(f'others check failed: {e}')
        for t in (self._beat, self._refresh_claims, self._watchdog, self._control):
            threading.Thread(target=t, daemon=True).start()
        while True:
            env = self.ctl_env()
            jk = os.environ.get('CONV_JOBS_KEY') or env.get('jobs_key') or f'{self.ST}/jobs.json'
            jb = B
            if jk.startswith('ctl:'):                 # canary / operator lists live in the control bucket
                jb, jk = CB, f'{self.CTL}/{jk[4:]}'
            jobs = self.jobs_cache.get(jk)
            try:
                et = s3.head_object(Bucket=jb, Key=jk)['ETag']
            except ClientError:
                log(f'no job list at {jb}/{jk}: waiting'); time.sleep(120); continue
            if not jobs or jobs[0] != et:
                body = s3.get_object(Bucket=jb, Key=jk)['Body'].read()
                jl_ = json.loads(gzip.decompress(body) if body[:2] == b'\x1f\x8b' else body)
                if isinstance(jl_, dict): jl_ = jl_['jobs']
                self.jobs_cache[jk] = jobs = (et, jl_)
            jobs = list(jobs[1])
            for xk in env.get('extra_jobs_keys') or [f'{self.ST}/jobs_reconvert.json']:
                xj = self._cached_list(xk)
                if xj:
                    have = {j['id'] for j in jobs}
                    jobs += [j for j in xj if j['id'] not in have]
            results = self.listing('results')
            done = self.done_ids(results)
            for r in filter(None, os.environ.get('CONV_RERUN', '').split(',')):      # test/repair runs only
                done.discard(r)
            open_jobs = [j for j in jobs if j['id'] not in done]
            if open_jobs:
                self._idle_since = None           # release clock (after FINAL_OK) counts only while this queue is truly empty
            try:
                # longest-first (lead 02:06Z): the finish time is set by the last long job -> every job expected to run > 1 h starts first
                # (longest first); then fresh jobs (list order), then re-runs by the coordinator's priority (class 3, most parts missing)
                prio = self._cached_dict(f'{self.ST}/priority.json') or {}
                def _rt(j):
                    sz = j.get('model_bytes') or j.get('size') or 0
                    return self._p50_runtime(self.pipe, sz) or 0
                if env.get('fresh_first'):
                    # (lead 04:15Z) a model with no STEP first: fresh jobs ahead of re-runs, longest-first within each group;
                    # (lead 05:50Z) a re-run of a job whose last run timed out ranks with the fresh jobs (long retry limit: start now)
                    def _rerun(j):
                        if j['id'] not in results:
                            return False
                        return (self.rcache.get(j['id'], (None, False, None, None, ''))[3] != 'timeout')
                    open_jobs.sort(key=lambda j: (_rerun(j), 0 if _rt(j) > 3600 else 1, -_rt(j) if _rt(j) > 3600 else 0,
                                                  prio.get(j['id'], 1 << 30)))
                else:
                    open_jobs.sort(key=lambda j: (0 if _rt(j) > 3600 else 1, -_rt(j) if _rt(j) > 3600 else 0,
                                                  j['id'] in results, prio.get(j['id'], 1 << 30)))
            except Exception:
                pass
            if not open_jobs:
                self._assist(env)
                if self.ctl_exists('hold') and not self._release_now():
                    log('all jobs have results; hold flag set: waiting'); time.sleep(90); continue
                log('ALL JOBS DONE')
                open(os.environ.get('CONV_DONE', f'{self.home}/DONE.{self.pipe}'), 'w').write(now())
                return 0
            if self.is_primary and env.get('assist_share'):
                self._assist(env)                 # shared box: the assist pipelines' loops always run (idempotent; pidfile check)
            claims = self.listing('claims')
            deferred = self.listing('deferred')
            fresh = {k for k, o in claims.items() if time.time() - o['LastModified'].timestamp() < STALE_S}
            todo = [j for j in open_jobs if j['id'] not in fresh]
            if not todo:
                self._assist(env)                 # nothing left to claim here: help another pipeline while the stragglers finish
            head = todo[:self.slots * 2]; random.shuffle(head); todo = head + todo[self.slots * 2:]
            t_round = time.time(); started = 0
            dtot = self.disk()[0]
            for job in todo:
                if self.reload or time.time() - t_round > 300:
                    break
                jid = job['id']
                need = self.mem_need(job); nd = min(self.need_disk(job), int(dtot * 0.6))
                exp = self.mem_expect(job)
                if jid in deferred:
                    dj = self.getj(f'{self.ST}/deferred/{jid}.json') or {}
                    if dj.get('hold_code') and dj.get('hold_code') == self.code:
                        continue                          # memory runaway on this converter: retried when the code changes
                    mm = int(dj.get('min_mem_bytes', 0))
                    if dj.get('runtime') != RUNTIME:
                        # legacy record: min_mem compounded 1.3x per kill (198-966 GB, not a measurement) -> at most 1.5x the bucket value
                        mm = min(mm, int(need * 1.5))
                    need = max(need, min(mm, int(self.total * 0.8)))
                    exp = max(exp, min(mm, int(self.total * 0.8)))      # a killed job retries with 1.6 x its measured peak counted
                need = min(need, int(self.total * 0.8)); exp = min(exp, need)
                if self.big[1] and (job.get('size') or 0) >= self.big[0]:
                    with self.lock:
                        nbig = sum(1 for v in self.running.values() if (v['size'] or 0) >= self.big[0]) + self.others.get('big', 0)
                    if nbig >= self.big[1]:
                        continue                  # enough big jobs on this host: take smaller ones meanwhile
                skip = False
                cores = self.job_cores
                while True:
                    with self.lock:
                        busy = len(self.running) + self.others['running']
                        # disk still to be written by running jobs = reservation minus what their dirs hold already
                        dres = sum(max(0, v['disk'] - v.get('du', 0)) for v in self.running.values())
                    H = self._host()
                    t, a = mem(); _, df = self.disk()
                    alone = H['n'] == 0
                    # memory (lead's rule, 00:05Z): every job on the host counted at max(RSS, expected = median peak of its size bucket);
                    # admit while that sum + this job's expected < 85 % of RAM (75 % for an assist pipeline) and MemAvailable would stay
                    # above 15 % of RAM. The reservation (1.2 x p95) is the watchdog's kill threshold. The CPU check below only adds to this.
                    # memory (lead 01:13Z): admit on REAL memory: MemAvailable - 8 % of RAM - growth still to come from young jobs
                    # (below their expected, younger than their bucket's median runtime) >= this job's expected; all jobs counted at
                    # max(RSS, expected) <= 1.3 x RAM (1.15 for an assist pipeline). Overshoot: the leader watchdog + 1.6x retries.
                    fac = self.resv_factor if self.is_primary else self.resv_factor_assist
                    ok_mem = (alone and a - exp > t * self.mem_floor) or \
                             (a - t * self.mem_floor - H['growth_young'] >= exp and H['resv'] + exp <= t * fac)
                    # (lead 06:35Z) memory pressure gate: no new job while the kernel stalls tasks on memory (PSI some avg60 > 10 %)
                    psi = mem_psi60()
                    if psi is not None and psi > float(self.ctl_env().get('psi_max', 10.0)):
                        ok_mem = False
                    # shares (lead 01:30Z): the box's pipeline may reserve part of the box for assist pipelines (env.json assist_share,
                    # e.g. {"ifc": 0.3} on SDS2 boxes): an assist pipeline stays within its share, the box's own pipeline within the rest
                    share = self._share()
                    if share is not None:
                        own_m = (H.get('resv_by_pipe') or {}).get(self.pipe, 0); own_c = (H.get('cores_by_pipe') or {}).get(self.pipe, 0)
                        ok_mem = ok_mem and own_m + exp <= share * t * self.resv_factor
                        ok_share_cpu = own_c + cores <= share * NCPU * self.cpu_frac
                    else:
                        ok_share_cpu = True
                    ok_disk = busy == 0 or df - dres - nd > max(10 << 30, int(dtot * 0.08))
                    load = self._cpu()
                    frac = self.cpu_frac if self.is_primary else self.cpu_frac_assist
                    ok_cpu = alone or (load + H['recent_cores'] + cores <= NCPU * frac and ok_share_cpu)
                    self.gate = {'at': now(), 'load': round(load, 1), 'recent_cores': H['recent_cores'], 'host_jobs': H['n'], 'by_pipe': H['by_pipe'],
                                 'host_resv_gb': round(H['resv'] / 2 ** 30, 1), 'growth_gb': round(H['growth_young'] / 2 ** 30, 1),
                                 'avail_gb': a >> 30, 'need_gb': round(need / 2 ** 30, 1), 'exp_gb': round(exp / 2 ** 30, 1), 'ok_mem': ok_mem, 'ok_cpu': ok_cpu, 'ok_disk': ok_disk,
                                 'cap_cpu': round(NCPU * frac, 1)}
                    if busy < self.slots and ok_mem and ok_disk and ok_cpu:
                        break
                    if busy < self.slots and ok_cpu:
                        skip = True; break         # CPU and a slot are free but this job does not fit memory / disk: try a smaller one
                    if self.reload or time.time() - t_round > 300:
                        break
                    time.sleep(3)
                    with self.lock:
                        for k, v in self.running.items():
                            if random.random() < 0.2:
                                v['du'] = dir_size(os.path.join(self.work, k[:40]))
                if skip:
                    continue
                if self.reload or time.time() - t_round > 300:
                    break
                if not self.claim(jid):
                    continue
                r0 = results.get(jid)
                if r0 is None and jid not in os.environ.get('CONV_RERUN', '') and self.exists(f'{self.ST}/results/{jid}.json'):
                    self.release(jid); continue
                with self.lock:
                    self.running[jid] = {'since': now(), 'size': job.get('size'), 'need': need, 'exp': exp, 'disk': nd, 'du': 0, 't0': time.time(), 'cores': cores}
                self._write_reg()                     # visible to the other worker processes on this host at once
                threading.Thread(target=self._work, args=(job,), daemon=True).start(); started += 1
            if self.reload:
                while True:
                    with self.lock:
                        if not self.running: break
                    time.sleep(10)
                log('exiting for hot reload / stop' + (' (handed off)' if self.handed_off else '') + (' (assist retired)' if self.retired else ''))
                if self.retired:
                    time.sleep(600)
                return 3
            if not started:
                with self.lock:
                    busy = len(self.running)
                if busy + self.others.get('running', 0) < max(1, self.slots // 2) and self.gate.get('ok_cpu', True):
                    self._assist(env)              # own queue is gated / drained here and the CPU is free: help another pipeline
                time.sleep(60 if busy else 120)


class DiskFull(Exception):
    pass


def sha256_file(p):
    """sha256sum in a child process (the worker process is GIL-bound and runs many jobs)"""
    r = subprocess.run(['sha256sum', p], capture_output=True, text=True)
    if r.returncode == 0:
        return r.stdout.split()[0]
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


_MARK = """import sys, json
pats = [p.encode() for p in json.loads(sys.argv[2])]; c = dict.fromkeys(pats, 0)
with open(sys.argv[1], 'rb') as f:
    for ln in f:
        for p in pats:
            if p in ln: c[p] += ln.count(p)
print(json.dumps({k.decode().rstrip('('): v for k, v in c.items()}))
"""


def count_markers(path, pats):
    """entity marker counts of a STEP file, counted in a child process"""
    r = subprocess.run([sys.executable, '-c', _MARK, path, json.dumps([p.decode() for p in pats])], capture_output=True, text=True, timeout=7200)
    return json.loads(r.stdout.strip().splitlines()[-1])


STEP_MARKERS = [b'FACETED_BREP(', b'POLY_LOOP', b'CLOSED_SHELL(', b'OPEN_SHELL(', b'SHELL_BASED_SURFACE_MODEL(', b'MANIFOLD_SOLID_BREP(',
                b'ADVANCED_FACE', b'TESSELLATED', b'TRIANGULATED_FACE_SET', b'PRODUCT(']


def bbox_sane(bb, lim=1e10):
    """bbox [xmin,ymin,zmin,xmax,ymax,zmax] in mm: finite, not inverted, |v| < lim (1e10 mm = 10,000 km)"""
    import math
    if not bb or len(bb) != 6: return False
    if any((not isinstance(v, (int, float))) or not math.isfinite(v) or abs(v) >= lim for v in bb): return False
    return all(bb[i] <= bb[i + 3] for i in range(3))
