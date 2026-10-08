#!/usr/bin/env python3
"""publisher.py - runs ON the EC2 box i-0f35da72bf742063d with its instance role; merges verified per-model bundles
into the packages' scripts/ folders.

    /opt/pm/venv/bin/python publisher.py --run RUN --target fake|packages [--allow-pids FILE | --all-pids] [--dry-run]
                                         [--models ID,ID] [--recheck] [--allow-update] [--expect FILE] [--chunk 200]

What it does, per invocation:
 1. lists s3://bim-proprietary-data/cad-disk-extract/_state/pmp/bundles/<run>/*.tar.gz; skips bundles the run's publish
    log already records as published to this target with the same ETag (unless --recheck) -> "new" bundles only;
 2. downloads + verifies each bundle completely (bundle_lib.verify_bundle: safe member names, regular files only, every
    file's bytes + sha256 against its row, header vs S3 key, optional --expect sha256 from the Modal index, layout);
 3. per package (serially, with a lock in _state/pmp/publish/locks/): reads the package's manifest.jsonl (the model must
    be a row of it: model_id + step relpath), lists the package, reads the current scripts/ tree (sha256 of every object
    from the publisher's state cache when its ETag+size are unchanged, else from the object's own metadata via HEAD; a
    scripts/ object without publisher metadata = foreign -> the package is refused), and PLANS every bundle against the
    merged state: shared files (scripts/README.md, requirements.txt, steelbuild.py, issues_lib.py) must match byte for
    byte or the bundle is refused; a model folder belongs to exactly one model_id (no clobbering another model's folder);
    a changed file in the model's own folder is refused unless --allow-update; nothing is ever deleted, so an update that
    would need a delete is refused. All checks happen BEFORE the first write of a package;
 4. (not --dry-run) uploads the model-folder files, then the new shared files (put_object with x-amz-meta-pmp-* +
    ChecksumSHA256, so S3 itself verifies every upload), re-lists the tree and REGENERATES scripts/scripts_manifest.jsonl
    from it (conditional put on the previous manifest's ETag); the manifest is written last = the commit record;
 5. re-lists the package and proves every object outside scripts/ is unchanged (same keys, ETags, sizes);
 6. appends one record per bundle (+ an invocation summary) to _state/pmp/publish/<run>.jsonl (--dry-run:
    <run>.dryrun.jsonl, plus the would-be manifest per package under _state/pmp/publish/dryrun/<run>/).

Writes are guarded in one place (Store.put): only _state/pmp/publish/... and <target root><allowed pid>/scripts/... can
be written; deletes only for the publisher's own lock files. Re-runs are idempotent: identical files are skipped, an
unchanged manifest is not rewritten, an interrupted publish is completed by the next run (the uploaded files carry
their sha256 in metadata). Exit 0 = all published / already published / would publish; 2 = some refused; 1 = errors.
"""
import argparse
import base64
import collections
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import traceback
import urllib.parse

import boto3
import botocore.config
import botocore.exceptions

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bundle_lib as BL  # noqa: E402

BUCKET = 'bim-proprietary-data'
REGION = 'ap-south-1'
STATE = 'cad-disk-extract/_state/pmp/'
BUNDLES = STATE + 'bundles/'
PUBLOG = STATE + 'publish/'
TARGETS = {'packages': 'cad-disk-extract/dataset/packages/3d_partial/', 'fake': STATE + 'fakepkg/'}
MANIFEST_REL = f'{BL.SCRIPTS}/{BL.MANIFEST_NAME}'
CODE_VERSION = 'pmp-publisher/1.1'
META = ('pmp-sha256', 'pmp-model-id', 'pmp-run', 'pmp-source', 'pmp-code-version', 'pmp-bundle-sha256')
CTYPES = {'.py': 'text/x-python; charset=utf-8', '.md': 'text/markdown; charset=utf-8', '.txt': 'text/plain; charset=utf-8',
          '.json': 'application/json', '.jsonl': 'application/x-ndjson', '.csv': 'text/csv; charset=utf-8',
          '.step': 'application/step', '.stp': 'application/step', '.ifc': 'application/x-step', '.log': 'text/plain; charset=utf-8',
          '.svg': 'image/svg+xml', '.png': 'image/png', '.gz': 'application/gzip', '.ifczip': 'application/zip'}


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def pid_hash(pid):
    return hashlib.sha1(pid.encode('utf-8')).hexdigest()[:20]


class Refuse(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(f'{code}: {message}')
        self.code, self.message, self.details = code, message, details


class Store:
    """S3 access for the publisher. Every write/delete goes through put()/delete(), which enforce the allowed prefixes."""

    def __init__(self, target, allowed_pids, dry_run):
        self.target = target
        self.root = TARGETS[target]
        self.allowed = allowed_pids          # set of pids, or None = any pid (fake target or --all-pids)
        self.dry = dry_run
        self.s3 = boto3.client('s3', region_name=REGION, config=botocore.config.Config(
            retries={'max_attempts': 10, 'mode': 'standard'}, max_pool_connections=64))
        self.n_put = 0

    def _write_ok(self, key):
        segs = key.split('/')
        if '' in segs or '.' in segs or '..' in segs:
            return False
        if key.startswith(PUBLOG):
            return True
        if self.dry or not key.startswith(self.root):
            return False
        rest = key[len(self.root):]
        pid, _, sub = rest.partition('/')
        if not pid or not sub.startswith(BL.SCRIPTS + '/') or len(sub) <= len(BL.SCRIPTS) + 1:
            return False
        return self.allowed is None or pid in self.allowed

    def put(self, key, body, **kw):
        if not self._write_ok(key):
            raise RuntimeError(f'write guard: refusing to write {key!r} (dry_run={self.dry}, target={self.target})')
        if len(key.encode('utf-8')) > 1024:
            raise Refuse('key_too_long', f'S3 key > 1024 bytes: {key[:120]}...')
        r = self.s3.put_object(Bucket=BUCKET, Key=key, Body=body, **kw)
        self.n_put += 1
        return r

    def delete(self, key):
        if not key.startswith(PUBLOG + 'locks/'):
            raise RuntimeError(f'delete guard: the publisher only deletes its own lock files, not {key!r}')
        self.s3.delete_object(Bucket=BUCKET, Key=key)

    def list(self, prefix):
        out = collections.OrderedDict()
        for page in self.s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=prefix):
            for o in page.get('Contents', []):
                out[o['Key']] = (o['ETag'].strip('"'), o['Size'])
        return out

    def get(self, key):
        """(bytes, etag) or (None, None) when absent"""
        try:
            r = self.s3.get_object(Bucket=BUCKET, Key=key)
            return r['Body'].read(), r['ETag'].strip('"')
        except botocore.exceptions.ClientError as e:
            if e.response.get('Error', {}).get('Code') in ('NoSuchKey', '404'):
                return None, None
            raise

    def head(self, key):
        return self.s3.head_object(Bucket=BUCKET, Key=key, ChecksumMode='ENABLED')

    def download(self, key, path):
        self.s3.download_file(BUCKET, key, path)


def meta_info(h, rel):
    """the publisher's per-object record from a HEAD response; raises Refuse when the object was not written by us"""
    m = {k.lower(): v for k, v in (h.get('Metadata') or {}).items()}
    if 'pmp-sha256' not in m:
        raise Refuse('foreign_file_in_scripts', f'{rel} in scripts/ was not written by the publisher (no pmp metadata)')
    sha = m['pmp-sha256']
    cs = h.get('ChecksumSHA256')
    if cs and h.get('ChecksumType', 'FULL_OBJECT') == 'FULL_OBJECT' and base64.b64decode(cs).hex() != sha:
        raise Refuse('checksum_mismatch', f'{rel}: S3 ChecksumSHA256 differs from the recorded pmp-sha256')
    uq = urllib.parse.unquote
    return dict(etag=h['ETag'].strip('"'), bytes=h['ContentLength'], sha256=sha, model_id=m.get('pmp-model-id'),
                source=uq(m.get('pmp-source', '')), code_version=uq(m.get('pmp-code-version', '')), run=m.get('pmp-run'))


S3_META_LIMIT = 2048          # S3: user metadata (UTF-8 bytes of every key + value, without "x-amz-meta-") <= 2 KB


def object_meta(row, header, run, bundle_sha256):
    """the x-amz-meta-pmp-* of one published file (the manifest is regenerated from these)"""
    q = lambda s: urllib.parse.quote(s or '', safe=" /:+()[],;=@-._~'")  # noqa: E731
    return {'pmp-sha256': row['sha256'], 'pmp-model-id': header['model_id'], 'pmp-run': run, 'pmp-source': q(row['source']),
            'pmp-code-version': q(row['code_version']), 'pmp-bundle-sha256': bundle_sha256}


def meta_bytes(meta):
    return sum(len(k.encode('utf-8')) + len(v.encode('utf-8')) for k, v in meta.items())


def is_shared(rel):
    return rel.count('/') == 1


def manifest_rows(info):
    rows = []
    for rel in sorted(info):
        c = info[rel]
        rows.append(dict(path=rel, bytes=c['bytes'], sha256=c['sha256'], model_id=None if is_shared(rel) else c['model_id'],
                         source=c['source'], code_version=c['code_version'], run=c.get('run')))
    return rows


def load_allow(path):
    raw = open(path, encoding='utf-8').read().strip()
    out = set()
    items = json.loads(raw) if raw.startswith('[') else [json.loads(x) if x.strip().startswith('{') else x.strip()
                                                         for x in raw.splitlines() if x.strip() and not x.startswith('#')]
    for x in items:
        out.add(x['pid'] if isinstance(x, dict) else str(x))
    return out


def load_expect(path):
    """{model_id: bundle sha256} from the Modal index (/vol/index/<run>.jsonl rows: bundle.sha256, upload.bundle_sha256)
    or plain rows {model_id, bundle_sha256 | sha256}. Rows without a bundle (failed models) are ignored; two different
    shas for one model or a file without any bundle sha are errors (a wrong file must not silently disable the check)."""
    out = {}
    for i, ln in enumerate(open(path, encoding='utf-8')):
        if not ln.strip():
            continue
        d = json.loads(ln)
        shas = {s for s in (d.get('bundle_sha256'), d.get('sha256'), (d.get('bundle') or {}).get('sha256'),
                            (d.get('upload') or {}).get('bundle_sha256')) if s}
        if not shas:
            continue
        if len(shas) > 1:
            raise SystemExit(f'publisher.py: --expect line {i + 1}: model {d.get("model_id")} has different bundle sha256s {sorted(shas)}')
        mid = d.get('model_id')
        if not mid or (mid in out and out[mid] != next(iter(shas))):
            raise SystemExit(f'publisher.py: --expect line {i + 1}: no model_id or a second, different sha256 for {mid}')
        out[mid] = next(iter(shas))
    if not out:
        raise SystemExit(f'publisher.py: --expect {path}: no row carries a bundle sha256 (wrong file?)')
    return out


class Publisher:
    def __init__(self, a):
        self.a = a
        self.run = a.run
        allow = load_allow(a.allow_pids) if a.allow_pids else None
        if a.target == 'packages' and allow is None and not a.all_pids:
            raise SystemExit('publisher.py: --target packages needs --allow-pids FILE (or the explicit --all-pids)')
        self.store = Store(a.target, allow, a.dry_run)
        self.allow = allow
        self.root = TARGETS[a.target]
        self.log_key = f'{PUBLOG}{self.run}{".dryrun" if a.dry_run else ""}.jsonl'
        self.expect = load_expect(a.expect) if a.expect else None
        self.fail_after = int(os.environ.get('PMP_TEST_FAIL_AFTER', '0') or 0)
        if self.fail_after and a.target != 'fake':
            raise SystemExit('publisher.py: PMP_TEST_FAIL_AFTER is a test hook for --target fake only')
        self.uploads = 0
        self.records = []
        self.work = tempfile.mkdtemp(prefix='pmp_pub_', dir=a.workdir)

    # ------------------------------------------------------------------ log
    def prior_log(self):
        body, _ = self.store.get(f'{PUBLOG}{self.run}.jsonl')
        out = []
        for ln in (body or b'').decode('utf-8').splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out

    def append_log(self, recs):
        data = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in recs).encode('utf-8')
        for attempt in range(6):
            body, etag = self.store.get(self.log_key)
            kw = dict(IfMatch=etag) if etag else dict(IfNoneMatch='*')
            try:
                self.store.put(self.log_key, (body or b'') + data, ContentType='application/x-ndjson', **kw)
                return
            except botocore.exceptions.ClientError as e:
                if e.response.get('Error', {}).get('Code') in ('PreconditionFailed', 'ConditionalRequestConflict') and attempt < 5:
                    time.sleep(1 + attempt)
                    continue
                raise

    # ------------------------------------------------------------------ locks
    def lock(self, pid):
        key = f'{PUBLOG}locks/{self.a.target}/{pid_hash(pid)}.lock'
        body = json.dumps(dict(pid=pid, run=self.run, host=socket.gethostname(), os_pid=os.getpid(), at=now_utc())).encode()
        for attempt in range(2):
            try:
                self.store.put(key, body, IfNoneMatch='*', ContentType='application/json')
                return key
            except botocore.exceptions.ClientError as e:
                if e.response.get('Error', {}).get('Code') not in ('PreconditionFailed', 'ConditionalRequestConflict'):
                    raise
                held, _ = self.store.get(key)
                try:
                    d = json.loads(held or b'{}')
                    age_h = (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(d['at'], '%Y-%m-%dT%H:%M:%SZ').replace(
                        tzinfo=dt.timezone.utc)).total_seconds() / 3600
                except Exception:  # noqa: BLE001
                    d, age_h = {}, 1e9
                if attempt == 0 and self.a.break_stale_locks and age_h > self.a.stale_lock_hours:
                    self.store.delete(key)
                    continue
                raise Refuse('locked', f'package is locked by another publisher (run {d.get("run")}, host {d.get("host")}, '
                                       f'{age_h:.1f} h ago); --break-stale-locks frees locks older than {self.a.stale_lock_hours} h')
        raise Refuse('locked', 'could not take the package lock')

    # ------------------------------------------------------------------ main
    def bundles(self):
        objs = self.store.list(f'{BUNDLES}{self.run}/')
        out = []
        want = set(x for x in (self.a.models or '').split(',') if x)
        for k, (etag, size) in objs.items():
            name = k.rsplit('/', 1)[1]
            if k.count('/') != BUNDLES.count('/') + 1 or not name.endswith('.tar.gz'):
                continue
            mid = name[:-len('.tar.gz')]
            if want and mid not in want:
                continue
            out.append(dict(key=k, etag=etag, size=size, model_id=mid))
        return out

    def go(self):
        t0 = time.time()
        bl = self.bundles()
        prior = self.prior_log()
        done = {(r.get('bundle_key'), r.get('bundle_etag'), r.get('target_root')): r for r in prior
                if r.get('kind') == 'bundle' and r.get('status') == 'published'}
        todo = []
        for b in bl:
            p = done.get((b['key'], b['etag'], self.root))
            if not self.a.recheck and p:
                self.records.append(self.rec(b, status='already_published', pid=p.get('pid'), model_folder=p.get('model_folder'),
                                             bundle_sha256=p.get('bundle_sha256'), published_at=p.get('at'),
                                             reason='same bundle (key + ETag) already published to this target by an earlier run'))
            else:
                todo.append(b)
        for i in range(0, len(todo), self.a.chunk):
            self.process_chunk(todo[i:i + self.a.chunk])
        st = collections.Counter(r['status'] for r in self.records)
        summary = dict(kind='invocation', run=self.run, target=self.a.target, target_root=self.root, dry_run=self.a.dry_run,
                       at=now_utc(), host=socket.gethostname(), code_version=CODE_VERSION, bundles_listed=len(bl),
                       bundles_processed=len(todo), status_counts=dict(st), s3_puts_before_log=self.store.n_put,
                       seconds=round(time.time() - t0, 1), recheck=self.a.recheck, allow_update=self.a.allow_update,
                       allow_pids=None if self.allow is None else len(self.allow))
        self.append_log(self.records + [summary])
        shutil.rmtree(self.work, ignore_errors=True)
        out = dict(summary=summary, log=f's3://{BUCKET}/{self.log_key}', bundles=[
            {k: r.get(k) for k in ('model_id', 'pid', 'model_folder', 'status', 'reason', 'detail', 'n_files', 'uploaded',
                                   'skipped', 'outside_unchanged', 'manifest_rows', 'warnings') if r.get(k) not in (None, [], '')}
            for r in self.records])
        txt = json.dumps(out, indent=1, ensure_ascii=False)
        print(txt if len(txt) < 20000 else json.dumps(dict(summary=summary, log=out['log'], note='per-bundle detail in the log'), indent=1))
        if st.get('error'):
            return 1
        return 2 if st.get('refused') else 0

    def rec(self, b, **kw):
        r = dict(kind='bundle', run=self.run, at=now_utc(), target=self.a.target, target_root=self.root, dry_run=self.a.dry_run,
                 bundle_key=b['key'], bundle_etag=b['etag'], bundle_bytes=b['size'], model_id=b['model_id'])
        r.update(kw)
        return r

    def process_chunk(self, chunk):
        ready = collections.defaultdict(list)
        for b in chunk:
            d = os.path.join(self.work, b['model_id'])
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
            local = os.path.join(d, 'bundle.tar.gz')
            r = self.rec(b)
            try:
                if self.expect is not None and b['model_id'] not in self.expect:
                    raise Refuse('not_in_expect', 'the --expect index (Modal) has no bundle sha256 for this model')
                self.store.download(b['key'], local)
                v = BL.verify_bundle(local, extract_to=os.path.join(d, 'x'), lenient=self.a.lenient_layout,
                                     expect=dict(run=self.run, model_id=b['model_id'], sha256=(self.expect or {}).get(b['model_id'])))
                os.remove(local)
                h = v.header
                r.update(bundle_sha256=v.sha256, pid=h['pid'], model_folder=h['model_folder'], step_relpath=h['step_relpath'],
                         step_source=h['step_source'], code_version=h['code_version'], n_files=len(v.rows), warnings=v.warnings)
                if self.allow is not None and h['pid'] not in self.allow:
                    raise Refuse('pid_not_allowed', 'the package is not in --allow-pids')
                ready[h['pid']].append((r, v))
            except BL.BundleError as e:
                r.update(status='refused', reason=e.code, detail=e.message)
                self.records.append(r)
                shutil.rmtree(d, ignore_errors=True)
            except Refuse as e:
                r.update(status='refused', reason=e.code, detail=e.message)
                self.records.append(r)
                shutil.rmtree(d, ignore_errors=True)
            except Exception as e:  # noqa: BLE001 - recorded, never swallowed
                r.update(status='error', reason='verify_failed', detail=f'{type(e).__name__}: {e}', trace=traceback.format_exc()[-1500:])
                self.records.append(r)
                shutil.rmtree(d, ignore_errors=True)
        for pid in sorted(ready):
            items = sorted(ready[pid], key=lambda x: x[1].header['model_id'])
            try:
                self.package(pid, items)
            except Refuse as e:
                for r, _ in items:
                    if r.get('status') is None:
                        r.update(status='refused', reason=e.code, detail=e.message)
                    elif r.get('status') == 'uploading':
                        r.update(status='error', reason=e.code, detail=f'after uploads started: {e.message}')
            except Exception as e:  # noqa: BLE001
                for r, _ in items:
                    if r.get('status') in (None, 'uploading'):
                        r.update(status='error', reason='publish_failed', detail=f'{type(e).__name__}: {e}',
                                 trace=traceback.format_exc()[-1500:])
            finally:
                for r, v in items:
                    self.records.append(r)
                    shutil.rmtree(os.path.dirname(v.root), ignore_errors=True)

    # ------------------------------------------------------------------ one package
    def package(self, pid, items):
        S = self.store
        pkg = f'{self.root}{pid}/'
        sp = f'{pkg}{BL.SCRIPTS}/'
        lock = None if self.a.dry_run else self.lock(pid)
        try:
            self._package(pid, items, pkg, sp)
        finally:
            if lock:
                try:
                    S.delete(lock)
                except Exception:  # noqa: BLE001
                    pass

    def _cached_state(self, pid):
        key = f'{PUBLOG}state/{self.a.target}/{pid_hash(pid)}.json'
        body, _ = self.store.get(key)
        try:
            d = json.loads(body) if body else {}
        except ValueError:
            d = {}
        return key, (d.get('objects') or {}) if d.get('pid') == pid and d.get('target_root') == self.root else {}

    def _read_tree(self, pid, objs, sp, pkg, cache, known=None):
        """{rel: info} for every object under scripts/ except the manifest; ETag+size-matched cache entries are trusted,
        everything else is HEADed (refuses on foreign objects)"""
        known = known or {}
        info, need = {}, []
        for k, (etag, size) in objs.items():
            if not k.startswith(sp):
                continue
            rel = k[len(pkg):]
            if rel == MANIFEST_REL:
                continue
            c = known.get(rel) or cache.get(rel)
            if c and c.get('etag') == etag and c.get('bytes') == size:
                info[rel] = c
            else:
                need.append((rel, k, size))
        if need:
            with cf.ThreadPoolExecutor(32) as ex:
                for (rel, k, size), h in zip(need, ex.map(lambda x: self.store.head(x[1]), need)):
                    c = meta_info(h, rel)
                    if c['bytes'] != size:
                        raise Refuse('tree_changed', f'{rel}: size changed while reading the tree')
                    info[rel] = c
        return info

    def _package(self, pid, items, pkg, sp):
        S = self.store
        objs = S.list(pkg)
        if f'{pkg}manifest.jsonl' not in objs:
            raise Refuse('package_not_found', f'no manifest.jsonl at s3://{BUCKET}/{pkg}')
        outside_before = {k: v for k, v in objs.items() if not k.startswith(sp)}
        body, _ = S.get(f'{pkg}manifest.jsonl')
        pkg_rows = {}
        for ln in (body or b'').decode('utf-8').splitlines():
            if ln.strip():
                d = json.loads(ln)
                if d.get('model_id'):
                    pkg_rows.setdefault(d['model_id'], []).append(d)
        state_key, cache = self._cached_state(pid)
        info = self._read_tree(pid, objs, sp, pkg, cache)
        planned = {k: dict(v) for k, v in info.items()}
        owner = {}                    # model folder -> model_id
        folder_of = {}                # model_id -> model folder
        for rel, c in planned.items():
            if not is_shared(rel):
                mf = rel.split('/')[1]
                if owner.setdefault(mf, c['model_id']) != c['model_id']:
                    raise Refuse('tree_inconsistent', f'scripts/{mf}/ already holds files of two models')
                folder_of.setdefault(c['model_id'], mf)
        accepted = []
        for r, v in items:
            h = v.header
            mid, mf = h['model_id'], h['model_folder']
            try:
                rows = pkg_rows.get(mid) or []
                match = [x for x in rows if x.get('relpath') == h['step_relpath']]
                if not match:
                    raise Refuse('model_not_in_package', f'the package manifest.jsonl has no row model_id={mid[:16]}... with relpath '
                                                         f'{h["step_relpath"]!r}')
                if match[0].get('step_source') and match[0]['step_source'] != h['step_source']:
                    raise Refuse('step_source_mismatch', f'bundle says {h["step_source"]}, package says {match[0]["step_source"]}')
                if owner.get(mf) not in (None, mid):
                    raise Refuse('model_folder_taken', f'scripts/{mf}/ belongs to model {owner[mf][:16]}... (never clobber another model)')
                if folder_of.get(mid) not in (None, mf):
                    raise Refuse('model_in_other_folder', f'model already published as scripts/{folder_of[mid]}/')
                for row in v.rows:
                    if len(f'{pkg}{row["path"]}'.encode('utf-8')) > 1024:
                        raise Refuse('key_too_long', f'S3 key for {row["path"][:60]}... is > 1024 bytes')
                    mb = meta_bytes(object_meta(row, h, self.run, v.sha256))
                    if mb > S3_META_LIMIT:
                        raise Refuse('metadata_too_large', f'{row["path"]}: its x-amz-meta-pmp-* would be {mb} B > {S3_META_LIMIT} B '
                                                           '(shorten the row source / code_version)')
                acts, conflicts = [], []
                for row in v.rows:
                    p = row['path']
                    cur = planned.get(p)
                    if cur is None:
                        acts.append(('upload', row))
                    elif cur['sha256'] == row['sha256'] and cur['bytes'] == row['bytes']:
                        acts.append(('skip', row))
                    elif is_shared(p):
                        conflicts.append(dict(code='shared_file_conflict', path=p, published_sha256=cur['sha256'], bundle_sha256=row['sha256'],
                                              published_by=cur.get('model_id')))
                    elif self.a.allow_update:
                        acts.append(('overwrite', row))
                    else:
                        conflicts.append(dict(code='model_file_differs', path=p, published_sha256=cur['sha256'], bundle_sha256=row['sha256']))
                mine = {row['path'] for row in v.rows}
                extra = sorted(p for p in planned if p.startswith(f'{BL.SCRIPTS}/{mf}/') and p not in mine)
                if extra:
                    conflicts.append(dict(code='would_need_delete', path=extra[0], n=len(extra),
                                          note='the published model folder holds files this bundle does not (the publisher never deletes)'))
                if conflicts:
                    raise Refuse(conflicts[0]['code'], f'{len(conflicts)} conflict(s), first: {conflicts[0]["path"]}', conflicts[:20])
            except Refuse as e:
                r.update(status='refused', reason=e.code, detail=e.message)
                if e.details:
                    r['conflicts'] = e.details
                continue
            for act, row in acts:
                if act != 'skip':
                    planned[row['path']] = dict(etag=None, bytes=row['bytes'], sha256=row['sha256'], model_id=mid, source=row['source'],
                                                code_version=row['code_version'], run=self.run)
            owner[mf] = mid
            folder_of[mid] = mf
            n_up = sum(1 for a_, _ in acts if a_ != 'skip')
            r.update(uploaded=n_up, skipped=len(acts) - n_up, overwritten=sum(1 for a_, _ in acts if a_ == 'overwrite'),
                     planned_paths=[row['path'] for a_, row in acts if a_ != 'skip'][:200])
            accepted.append((r, v, acts))
        if not accepted:
            return
        rows_preview = manifest_rows(planned)
        body_preview = ''.join(BL.row_line(x) for x in rows_preview).encode('utf-8')
        if self.a.dry_run:
            S.put(f'{PUBLOG}dryrun/{self.run}/{pid_hash(pid)}.scripts_manifest.jsonl', body_preview, ContentType='application/x-ndjson',
                  Metadata={'pmp-pid': urllib.parse.quote(pid, safe='')})
            for r, v, acts in accepted:
                r.update(status='would_publish' if r['uploaded'] else 'would_skip_identical', manifest_rows=len(rows_preview),
                         manifest_sha256=hashlib.sha256(body_preview).hexdigest(), manifest_preview=f'{PUBLOG}dryrun/{self.run}/'
                         f'{pid_hash(pid)}.scripts_manifest.jsonl')
            return
        # ---- execute: model folders first, then new shared files, manifest last
        uploaded = {}
        for r, v, acts in accepted:
            r['status'] = 'uploading'
            order = sorted(acts, key=lambda x: (is_shared(x[1]['path']), x[1]['path']))
            for act, row in order:
                if act == 'skip':
                    continue
                if is_shared(row['path']) and row['path'] in uploaded:
                    continue
                uploaded[row['path']] = self._upload(pkg, row, v)
        objs2 = S.list(pkg)
        merged = self._read_tree(pid, objs2, sp, pkg, cache, known={**info, **uploaded})
        bad = [p for p, c in planned.items() if merged.get(p, {}).get('sha256') != c['sha256']]
        if bad:
            raise RuntimeError(f'post-upload check: {len(bad)} files differ from the plan, e.g. {bad[:3]}')
        rows = manifest_rows(merged)
        mbody = ''.join(BL.row_line(x) for x in rows).encode('utf-8')
        cur, cur_etag = S.get(f'{pkg}{MANIFEST_REL}')
        if cur != mbody:
            kw = dict(IfMatch=cur_etag) if cur_etag else dict(IfNoneMatch='*')
            S.put(f'{pkg}{MANIFEST_REL}', mbody, ContentType='application/x-ndjson',
                  ChecksumSHA256=base64.b64encode(hashlib.sha256(mbody).digest()).decode(),
                  Metadata={'pmp-sha256': hashlib.sha256(mbody).hexdigest(), 'pmp-run': self.run, 'pmp-code-version': CODE_VERSION,
                            'pmp-model-id': '', 'pmp-source': 'publisher.py: generated from the merged scripts/ tree'}, **kw)
        S.put(state_key, json.dumps(dict(pid=pid, target_root=self.root, at=now_utc(), run=self.run, objects=merged),
                                    ensure_ascii=False, sort_keys=True).encode('utf-8'), ContentType='application/json')
        objs3 = S.list(pkg)
        outside_after = {k: v for k, v in objs3.items() if not k.startswith(sp)}
        unchanged = outside_after == outside_before
        msha = hashlib.sha256(mbody).hexdigest()
        for r, v, acts in accepted:
            r.update(status='published' if unchanged else 'error', manifest_rows=len(rows), manifest_sha256=msha,
                     manifest_key=f'{pkg}{MANIFEST_REL}', outside_unchanged=unchanged, n_outside=len(outside_after),
                     scripts_objects=sum(1 for k in objs3 if k.startswith(sp)))
            if not unchanged:
                r.update(reason='outside_scripts_changed', detail='objects outside scripts/ changed during the publish (not by the '
                         'publisher: it cannot write there) - investigate', outside_diff=sorted(set(outside_after.items()) ^ set(outside_before.items()))[:20])

    def _upload(self, pkg, row, v):
        p = row['path']
        local = v.files[p]
        digest = hashlib.sha256()
        with open(local, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                digest.update(b)
        if digest.hexdigest() != row['sha256'] or os.path.getsize(local) != row['bytes']:
            raise RuntimeError(f'{p}: local extracted file changed before upload')
        ext = os.path.splitext(p)[1].lower()
        meta = object_meta(row, v.header, self.run, v.sha256)
        with open(local, 'rb') as f:
            resp = self.store.put(f'{pkg}{p}', f, ContentType=CTYPES.get(ext, 'application/octet-stream'), Metadata=meta,
                                  ChecksumSHA256=base64.b64encode(digest.digest()).decode())
        self.uploads += 1
        if self.fail_after and self.uploads >= self.fail_after:
            raise RuntimeError(f'PMP_TEST_FAIL_AFTER={self.fail_after}: simulated crash after {self.uploads} uploads')
        return dict(etag=resp['ETag'].strip('"'), bytes=row['bytes'], sha256=row['sha256'], model_id=v.header['model_id'],
                    source=row['source'], code_version=row['code_version'], run=self.run)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True)
    ap.add_argument('--target', choices=sorted(TARGETS), required=True,
                    help='packages = dataset/packages/3d_partial/<pid>/scripts/ ; fake = _state/pmp/fakepkg/<pid>/scripts/ (tests)')
    ap.add_argument('--allow-pids', help='file: JSON list of pids / of objects with "pid" (e.g. new5.json) / text lines')
    ap.add_argument('--all-pids', action='store_true', help='explicitly allow every package (scale run; needs owner approval)')
    ap.add_argument('--dry-run', action='store_true', help='verify + plan only; writes only the dry-run log/plan under _state/pmp/publish/')
    ap.add_argument('--models', help='comma-separated model ids (default: every bundle of the run)')
    ap.add_argument('--recheck', action='store_true', help='re-verify bundles the log already records as published')
    ap.add_argument('--allow-update', action='store_true', help='allow replacing changed files in the model\'s OWN folder (never deletes)')
    ap.add_argument('--lenient-layout', action='store_true', help='downgrade model-folder layout problems to warnings (not safety checks)')
    ap.add_argument('--expect', help='JSONL rows {model_id, bundle_sha256} from the Modal index: bundles must match')
    ap.add_argument('--chunk', type=int, default=200, help='bundles downloaded + verified at a time (disk bound)')
    ap.add_argument('--workdir', default=None, help='local scratch (default: system temp)')
    ap.add_argument('--break-stale-locks', action='store_true')
    ap.add_argument('--stale-lock-hours', type=float, default=6.0)
    a = ap.parse_args()
    if not BL.RUN_RE.match(a.run):
        raise SystemExit(f'publisher.py: bad run name {a.run!r}')
    return Publisher(a).go()


if __name__ == '__main__':
    sys.exit(main())
