#!/usr/bin/env python3
"""Shared fleet runtime for the Zentitude-data-4 conversion kits (ifc / db1 / sds2).  runtime v2

S3 layout (everything under s3://annotationprod/cad-disk-extract/zentitude-data-4/):
  _control/conv/<pipe>/jobs.json            job list (largest first), one job per distinct new content
  _control/conv/<pipe>/{hold,stop,env.json} hold = never finish (keep boxes alive); stop = pause; env.json = {"slots": N}
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
Exit: 0 + DONE file when every job has a result (and no hold flag).
"""
import os, sys, json, time, socket, threading, subprocess, traceback, random, signal, hashlib, shutil
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

B = 'annotationprod'
ROOT = 'cad-disk-extract/zentitude-data-4'
HOST = socket.gethostname()
PID = os.getpid()
RUNTIME = 'convfleet-v5'
s3 = boto3.client('s3', region_name='ap-south-1',
                  config=Config(max_pool_connections=64, retries={'max_attempts': 10, 'mode': 'adaptive'},
                                connect_timeout=30, read_timeout=300))
STALE_S = int(os.environ.get('CLAIM_STALE_S', '1500'))
LOGBUF = []; LOGLOCK = threading.Lock()
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
        self.CTL = f'{ROOT}/_control/conv/{pipe}'; self.ST = f'{ROOT}/_state/conv/{pipe}'
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

    # ---------------------------------------------------------------- S3 helpers
    def put(self, key, obj):
        assert key.startswith(ROOT + '/'), key
        s3.put_object(Bucket=B, Key=key, Body=json.dumps(obj, default=str).encode(), ContentType='application/json')

    def getj(self, key):
        try:
            return json.loads(s3.get_object(Bucket=B, Key=key)['Body'].read())
        except ClientError:
            return None

    def exists(self, key):
        try:
            s3.head_object(Bucket=B, Key=key); return True
        except ClientError:
            return False

    def upload(self, path, key, ctype=None):
        assert key.startswith(ROOT + '/'), key
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
                out[f] = s3.head_object(Bucket=B, Key=f'{self.CTL}/{f}')['ETag']
            except ClientError:
                out[f] = None
        return out

    def done_ids(self, results):
        """result ids that count as final for this code (redo() re-opens some results of older code)"""
        if not self.redo and not self.redo_ids_key:
            return set(results)
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
                d = json.loads(s3.get_object(Bucket=B, Key=self.redo_ids_key)['Body'].read())
                if isinstance(d, dict):
                    ents = list(d.get('entries') or [])
                    if d.get('ids'):
                        ents.append({'ids': d.get('ids'), 'codes': d.get('codes') or []})
                    self.redo_entries = [{'ids': set(e.get('ids') or []), 'reasons': set(e.get('reasons') or []),
                                          'codes': set(e.get('codes') or []), 'before': e.get('before') or ''} for e in ents]
            except Exception:
                pass
        out = set()
        for k in results:
            c = self.rcache.get(k, (None, False, None, None, ''))
            if c[1]:
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
    def run(self, jid, cmd, logf, timeout, stall=None, mem_frac=0.85, env=None, cwd=None):
        """rc of cmd; 124 = overall timeout, 125 = stalled (log unchanged for `stall` s), -9 = memory kill, 128 = disk kill"""
        if os.path.exists('/usr/bin/systemd-run') and os.geteuid() == 0:
            cmd = ['systemd-run', '--scope', '--quiet', '-p', f'MemoryMax={int(self.total * mem_frac)}', '-p', 'MemorySwapMax=0'] + list(cmd)
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
                        t = time.time()
                        if t - t0 > timeout:
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
                    run = [{'id': k, 'since': v['since'], 'size': v['size'], 'need': v['need'], 'disk': v['disk']} for k, v in self.running.items()]
                    snap = {'host': HOST, 'pid': PID, 'code': self.code, 'runtime': RUNTIME, 'at': now(), 'slots': self.slots, 'running': run,
                            'stats': dict(self.stats), 'mem_total_gb': t >> 30, 'mem_avail_gb': a >> 30,
                            'disk_total_gb': dt >> 30, 'disk_free_gb': df >> 30, 'others': dict(self.others),
                            'load': os.getloadavg()[0], 'reload_pending': self.reload, 'handed_off': self.handed_off}
                self.put(f'{self.ST}/hosts/{self.id}.json', snap)
                with LOGLOCK:
                    s3.put_object(Bucket=B, Key=f'{self.ST}/logs/{self.id}.log', Body='\n'.join(LOGBUF).encode())
                self._others()
            except Exception:
                pass
            time.sleep(60)

    def _others(self):
        """capacity used by the other live worker processes on this host (old code finishing its jobs, siblings)"""
        o = {'running': 0, 'need': 0, 'disk': 0, 'big': 0, 'pids': []}
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{self.ST}/hosts/{HOST}-'):
            for ob in page.get('Contents', []):
                if ob['Key'].endswith(f'-{PID}.json') or time.time() - ob['LastModified'].timestamp() > 180:
                    continue
                h = self.getj(ob['Key']) or {}
                if h.get('host') != HOST or h.get('pid') == PID or not pid_alive(int(h.get('pid') or 0)):
                    continue
                o['pids'].append(h.get('pid'))
                for r in h.get('running') or []:
                    o['running'] += 1
                    if self.big[1] and (r.get('size') or 0) >= self.big[0]:
                        o['big'] += 1
                    o['need'] += r.get('need') or self.need_bytes({'size': r.get('size'), 'kind': r.get('kind')})
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

    def _watchdog(self):
        n = 0
        while True:
            try:
                t, a = mem()
                if a < max(4 << 30, int(t * 0.06)):
                    with self.plock:
                        cand = [(sum(rss_tree(p.pid) for p in ps), jid, ps) for jid, ps in self.procs.items() if ps]
                    if cand:
                        r, jid, ps = max(cand, key=lambda x: x[0])
                        self.killed[jid] = r
                        for p in ps: self._kill(p)
                        log(f'WATCHDOG killed {jid[:16]} rss={r >> 30}GB avail={a >> 30}GB')
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
                if self.exists(f'{self.CTL}/stop'):
                    log('stop flag: finishing running jobs, claiming nothing new'); self.reload = True
                if not self.reload and self._etags() != self.etags:
                    log('new kit code on S3: hand-off (new process starts now, this one finishes its running jobs)')
                    self._handoff(); self.reload = True
                env = self.getj(f'{self.CTL}/env.json') or {}
                if env.get('slots') and not os.environ.get('CONV_SLOTS'):
                    self.slots = int(env['slots'])
            except Exception:
                pass

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
            for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{self.CTL}/'):
                for o in page.get('Contents', []):
                    rel = o['Key'][len(self.CTL) + 1:]
                    if not rel or '/' in rel or rel == 'jobs.json' or rel.startswith('_') or rel.endswith('.md'):
                        continue
                    tmp = os.path.join(kit, f'.{rel}.new'); s3.download_file(B, o['Key'], tmp); os.replace(tmp, os.path.join(kit, rel))
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
            need = max(int(self.total * 1.3), (prev.get('min_mem_bytes') or 0) * 3 // 2, self.killed.get(jid, 0) * 2)
            self.killed.pop(jid, None)
            kills = prev.get('kills', 0) + 1
            if need > (2 << 40) or kills >= 4:     # no host we launch has this much memory
                res.update(status='fail', reason='out_of_memory', kills=kills, min_mem_gb=need >> 30)
            else:
                self.put(f'{self.ST}/deferred/{jid}.json', {'id': jid, 'host': HOST, 'at': now(), 'kills': kills,
                                                           'min_mem_bytes': need, 'min_mem_gb': need >> 30})
                self.release(jid); return
        if res.get('transient'):
            prev = self.getj(f'{self.ST}/retry/{jid}.json') or {}
            n = prev.get('attempts', 0) + 1
            if n < res.get('retry_limit', 3):
                self.put(f'{self.ST}/retry/{jid}.json', {'id': jid, 'attempts': n, 'last': res})
                self.release(jid); return
            res['attempts'] = n
        self.put(f'{self.ST}/results/{jid}.json', res)
        self.release(jid)

    def _singleton(self):
        """one live process per code version per host: a second start of the same code (e.g. the boot loop restarting
        after the old code's process handed off) waits until the first one exits"""
        me = os.path.join(self.rundir, f'{self.pipe}-{PID}.json')
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
            time.sleep(60)
        json.dump({'pid': PID, 'code': self.code, 'at': now()}, open(me, 'w'))

    def main(self):
        self._singleton()
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
            jobs = json.loads(s3.get_object(Bucket=B, Key=os.environ.get('CONV_JOBS_KEY') or f'{self.CTL}/jobs.json')['Body'].read())
            if isinstance(jobs, dict): jobs = jobs['jobs']
            results = self.listing('results')
            done = self.done_ids(results)
            for r in filter(None, os.environ.get('CONV_RERUN', '').split(',')):      # test/repair runs only
                done.discard(r)
            open_jobs = [j for j in jobs if j['id'] not in done]
            if not open_jobs:
                if self.exists(f'{self.CTL}/hold'):
                    log('all jobs have results; hold flag set: waiting'); time.sleep(300); continue
                log('ALL JOBS DONE')
                open(os.environ.get('CONV_DONE', f'{self.home}/DONE.{self.pipe}'), 'w').write(now())
                return 0
            claims = self.listing('claims')
            deferred = self.listing('deferred')
            fresh = {k for k, o in claims.items() if time.time() - o['LastModified'].timestamp() < STALE_S}
            todo = [j for j in open_jobs if j['id'] not in fresh]
            head = todo[:self.slots * 2]; random.shuffle(head); todo = head + todo[self.slots * 2:]
            t_round = time.time(); started = 0
            dtot = self.disk()[0]
            for job in todo:
                if self.reload or time.time() - t_round > 300:
                    break
                jid = job['id']
                need = self.need_bytes(job); nd = min(self.need_disk(job), int(dtot * 0.6))
                if jid in deferred:
                    dj = self.getj(f'{self.ST}/deferred/{jid}.json') or {}
                    need = max(need, dj.get('min_mem_bytes', 0))
                    if need > self.total * 0.9:
                        continue                  # leave it to a bigger host
                need = min(need, int(self.total * 0.8))
                if self.big[1] and (job.get('size') or 0) >= self.big[0]:
                    with self.lock:
                        nbig = sum(1 for v in self.running.values() if (v['size'] or 0) >= self.big[0]) + self.others.get('big', 0)
                    if nbig >= self.big[1]:
                        continue                  # enough big jobs on this host: take smaller ones meanwhile
                while True:
                    with self.lock:
                        busy = len(self.running) + self.others['running']
                        resv = sum(v['need'] for v in self.running.values()) + self.others['need']
                        # disk still to be written by running jobs = reservation minus what their dirs hold already
                        dres = sum(max(0, v['disk'] - v.get('du', 0)) for v in self.running.values())
                    t, a = mem(); _, df = self.disk()
                    ok_mem = busy == 0 or (resv + need < t * 0.85 and a > need + (4 << 30))
                    ok_disk = busy == 0 or df - dres - nd > max(10 << 30, int(dtot * 0.08))
                    if busy < self.slots and ok_mem and ok_disk:
                        break
                    if self.reload or time.time() - t_round > 300:
                        break
                    time.sleep(3)
                    with self.lock:
                        for k, v in self.running.items():
                            if random.random() < 0.2:
                                v['du'] = dir_size(os.path.join(self.work, k[:40]))
                if self.reload or time.time() - t_round > 300:
                    break
                if not self.claim(jid):
                    continue
                r0 = results.get(jid)
                if r0 is None and jid not in os.environ.get('CONV_RERUN', '') and self.exists(f'{self.ST}/results/{jid}.json'):
                    self.release(jid); continue
                with self.lock:
                    self.running[jid] = {'since': now(), 'size': job.get('size'), 'need': need, 'disk': nd, 'du': 0}
                threading.Thread(target=self._work, args=(job,), daemon=True).start(); started += 1
            if self.reload:
                while True:
                    with self.lock:
                        if not self.running: break
                    time.sleep(10)
                log('exiting for hot reload / stop' + (' (handed off)' if self.handed_off else ''))
                return 3
            if not started:
                with self.lock:
                    busy = len(self.running)
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
