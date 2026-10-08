#!/usr/bin/env python3
"""Zenitude-data-3 adapter for the general packager.

Inputs (all read-only):
  jobs        s3://annotationprod/cad-disk-extract/_control/move/z3/jobs.json   (archive jobs {id,key,size} + loose dirs {id,dir})
  manifests   bim cad-disk-extract/zenitude-data-3/_state/manifests/<job id>.jsonl.gz  rows {path,size,sha256,key,dedup}
  conv index  bim cad-disk-extract/zenitude-data-3/_state/conv/index.jsonl.gz          (build_index rows, normalised by conv_rows)
  resolution  data-3 markers _state/sha/, data-4 markers zentitude-data-4/_state/sha/, conv scan maps (contents_ifc input_key,
              sds2/files/<fpc>), Disk-2 / Disk-1 extraction of the byte-identical archive at the same path.
Project = one physical extracted archive folder (or one loose-folder job): id Zenitude-data-3__<archive path, '/' -> '_'>
(= the extraction folder name under zenitude-data-3/extracted/).
"""
from __future__ import annotations
import collections, gzip, hashlib, json, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pkgcore as pc

B = 'bim-proprietary-data'
CB = 'annotationprod'
ROOT = 'cad-disk-extract/zenitude-data-3'
Z4 = 'cad-disk-extract/zentitude-data-4'
JOBS = 'cad-disk-extract/_control/move/z3/jobs.json'
INDEX = f'{ROOT}/_state/conv/index.jsonl.gz'
SRC = 'Zenitude-data-3/'
PEERS = ('Disk-2', 'Disk-1')          # earlier extractions of byte-identical archives (data-3 is a superset of Disk-2)
# sha256 -> stored Disk-1/2 key, each entry proven by an S3-computed SHA-256 of that exact key (pinned ETag) + size (pkg-resolver)
D12MAP = os.environ.get('PKG_D12MAP', 's3://annotationprod/cad-disk-extract/agentwork/pkg-resolver/disk12_sha_map.jsonl.gz')


def _lk(p):
    return re.sub(r'[^a-z0-9]+', '', p.lower())


def _san(s):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)


def _sc(s):
    """the Disk-1/2 extraction worker's folder / member naming (safe_component): '_' runs collapsed, '!+' kept"""
    s = re.sub(r"[^A-Za-z0-9._!+\-]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_") or "_"


class Adapter:
    disk = 'Zenitude-data-3'

    def __init__(self, cache_dir=None, log=print):
        self.log = log
        self.cache_dir = cache_dir
        jobs = self._cached_json(CB, JOBS, 'jobs.json')
        self.by_src = {}
        for j in jobs:
            if j.get('key'): self.by_src[j['key']] = j
            elif j.get('dir'): self.by_src[j['dir']] = j
        self._ifc = None; self._sds2 = {}; self._peer = {}; self._mk = {}
        self._lock = threading.Lock()

    def _cached_json(self, b, k, name):
        if self.cache_dir:
            p = os.path.join(self.cache_dir, name)
            if os.path.exists(p):
                return json.load(gzip.open(p, 'rt') if p.endswith('.gz') else open(p))
        return pc.get_json(b, k)

    # ------------------------------------------------------------ projects
    def project_ref(self, archive_part: str):
        j = self.by_src.get(archive_part)
        if j is None:
            return None
        rel = archive_part[len(SRC):] if archive_part.startswith(SRC) else archive_part
        tag = rel.rstrip('/').replace('/', '_')
        return {'project_id': pc.project_id(self.disk, tag), 'tag': tag, 'source_key': archive_part,
                'kind': 'dir' if archive_part.endswith('/') else 'archive', 'job_id': j['id'], 'size': j.get('size'),
                'source_prefix': archive_part + ' :: '}

    def project_of(self, archive_part: str):
        r = self.project_ref(archive_part)
        return r['project_id'] if r else None

    def files(self, proj):
        d = None
        if self.cache_dir:
            p = os.path.join(self.cache_dir, 'man', proj['job_id'] + '.jsonl.gz')
            d = open(p, 'rb').read() if os.path.exists(p) else None
        if d is None:
            d = pc.get_bytes(B, f"{ROOT}/_state/manifests/{proj['job_id']}.jsonl.gz")
        if d is None:
            raise RuntimeError(f"no manifest for {proj['job_id']}")
        out = []
        for l in gzip.decompress(d).decode('utf-8', 'surrogateescape').splitlines():
            if l.strip():
                r = json.loads(l)
                out.append({'path': r['path'], 'size': int(r['size']), 'sha256': r['sha256'], 'key': r.get('key'),
                            'dedup': r.get('dedup')})
        return out

    # ------------------------------------------------------------ common conversion index
    def conv_rows(self, index_bytes=None):
        d = index_bytes if index_bytes is not None else pc.get_bytes(B, INDEX)
        rows = []
        for l in gzip.decompress(d).decode().splitlines():
            if not l.strip(): continue
            r = json.loads(l)
            sp = []
            for p in r.get('paths') or []:
                a, _, m = p.partition(' :: ')
                sp.append((a, m))
            rows.append({
                'model_key': f"{self.disk}:{r['pipeline']}:{r['id']}", 'disk': self.disk, 'pipeline': r['pipeline'], 'id': r['id'],
                'source_sha256': r.get('sha256'), 'fpc': r.get('fpc'), 'jsetup_sha256': r.get('jsetup_sha256'),
                'source_paths': sp, 'step_bucket': B, 'step_key': r.get('step_key'), 'class': r.get('class'),
                'grader_class': r.get('grader_class'), 'reasons': r.get('reasons') or [], 'issues': r.get('issues') or [],
                'status': r.get('status'), 'converter_code': r.get('converter_code'), 'converter': r.get('converter'),
                'verify_verdict': r.get('verify_verdict'), 'verify_evidence': r.get('verify_evidence'),
                'verify_codes': r.get('verify_codes'), 'verified': r.get('verified'), 'verify_held': r.get('verify_held'),
                'sds2_primary': r.get('sds2_primary'), 'older_revision_of': r.get('older_revision_of'),
                'revision_rank': r.get('revision_rank'), 'corpus': r.get('corpus'), 'domain': r.get('domain'),
                'graded_by': r.get('graded_by'), 'coverage_all': r.get('coverage_all'), 'parts_source': r.get('parts_source'),
                'parts_step': r.get('parts_step'), 'solids': r.get('solids'), 'invalid_solids': r.get('invalid_solids'),
                'schema': r.get('schema'), 'step_bytes': r.get('step_bytes'), 'reused': r.get('reused'),
                'rerun_pending': bool(r.get('rerun_pending'))})
        return rows

    # ------------------------------------------------------------ resolution
    def _ifc_map(self):
        if self._ifc is None:
            m = {}
            p = os.path.join(self.cache_dir or '/nonexistent', 'contents_ifc.jsonl.gz')
            raw = open(p, 'rb').read() if os.path.exists(p) else pc.get_bytes(B, f'{ROOT}/_state/conv/scan/contents_ifc.jsonl.gz')
            for l in gzip.decompress(raw).decode().splitlines():
                if l.strip():
                    r = json.loads(l)
                    if r.get('input_key'):
                        m[r['sha256']] = (r['input_key'], 'ifc_scan:' + str(r.get('input_from')))
            self._ifc = m
        return self._ifc

    def _sds2_map(self, fpc):
        if fpc not in self._sds2:
            d = pc.get_json(B, f'{ROOT}/_state/conv/sds2/files/{fpc}.json.gz') or []
            self._sds2[fpc] = {r['sha256']: r['key'] for r in d if r.get('key')}
        return self._sds2[fpc]

    def _marker(self, root, sha):
        k = (root, sha)
        if k in self._mk: return self._mk[k]
        t = pc.get_bytes(B, f'{root}/_state/sha/{sha[:2]}/{sha}')
        t = t.decode().strip() if t else None
        v = t if t and t.startswith('cad-disk-extract/') else None
        self._mk[k] = v
        return v

    def _peer_map(self, proj):
        """earlier extraction (Disk-2 / Disk-1) of the byte-identical archive at the same path: loose-key -> [(key, size)]"""
        pid = proj['project_id']
        if pid in self._peer: return self._peer[pid]
        out = {}; used = None
        if proj['kind'] == 'archive':
            rel = proj['source_key'][len(SRC):]
            for disk in PEERS:
                h = pc.head(B, f'{disk}/{rel}')
                if not h or int(h['ContentLength']) != int(proj.get('size') or -1):
                    continue
                h12 = hashlib.sha256(f"{disk}/{rel}".encode()).hexdigest()[:12]
                for flat in dict.fromkeys((_sc(rel)[:240], _san(rel))):   # worker naming first; old _san kept as fallback
                    for pref in (f'cad-disk-extract/{disk}/{flat}-{h12}/', f'cad-disk-extract/{disk}/{flat}/'):
                        ks = pc.list_keys(B, pref)
                        if ks:
                            for k, sz, et in ks:
                                out.setdefault(_lk(k[len(pref):]), []).append((k, sz))
                            used = pref; break
                    if used: break
                if used: break
        self._peer[pid] = (out, used)
        return self._peer[pid]

    def _d12_map(self):
        """{sha256: (key, bytes)} from the pkg-resolver map; {} when PKG_D12MAP is empty/'off' or the object is missing."""
        with self._lock:
            if hasattr(self, '_d12m'):
                return self._d12m
            m = {}
            if D12MAP and D12MAP != 'off':
                p = os.path.join(self.cache_dir or '/nonexistent', 'disk12_sha_map.jsonl.gz')
                if os.path.exists(p):
                    raw = open(p, 'rb').read()
                else:
                    b, _, k = D12MAP[len('s3://'):].partition('/')
                    raw = pc.get_bytes(b, k)
                for l in (gzip.decompress(raw).decode().splitlines() if raw else []):
                    if l.strip():
                        r = json.loads(l)
                        if r.get('proof') == 's3_sha256' and r.get('key', '').startswith('cad-disk-extract/'):
                            m[r['sha256']] = (r['key'], int(r['bytes']))
                self.log(f'disk12_sha_map: {len(m)} entries')
            self._d12m = m
            return m

    def _d4_index(self, sha):
        if not hasattr(self, '_d4i'):
            self._d4i = {}
            self._d4i_on = pc.head(B, f'{pc.PSTATE}/cache/d4_index/DONE.json') is not None
        if not self._d4i_on:
            return None
        sh = sha[:2]
        if sh not in self._d4i:
            self._d4i[sh] = pc.get_json(B, f'{pc.PSTATE}/cache/d4_index/{sh}.json.gz') or {}
        return self._d4i[sh].get(sha)

    def _d4_siblings(self, items, rest, top=int(os.environ.get('PKG_D4_SIBLINGS', '8'))):
        pre = f'{Z4}/extracted/'
        folders = collections.Counter(it['src_key'][len(pre):].split('/', 1)[0] for it in items
                                      if (it.get('src_key') or '').startswith(pre))
        if not folders:
            return
        if not hasattr(self, '_d4f'):
            self._d4f = {j['key'][len('Zentitude-data-4/'):].replace('/', '_'): j['id']
                         for j in (pc.get_json(B, f'{Z4}/_control/jobs.json') or []) if j.get('key')}
            self._d4m = {}
        for folder, _ in folders.most_common(top):
            jid = self._d4f.get(folder)
            if not jid:
                continue
            if jid not in self._d4m:
                d = pc.get_bytes(B, f'{Z4}/_state/manifests/{jid}.jsonl.gz')
                m = {}
                for l in (gzip.decompress(d).decode('utf-8', 'surrogateescape').splitlines() if d else []):
                    if '"cad-disk-extract/' in l:
                        r = json.loads(l)
                        if (r.get('key') or '').startswith('cad-disk-extract/'):
                            m.setdefault(r['sha256'], r['key'])
                self._d4m[jid] = m
            m = self._d4m[jid]
            for it in rest:
                if not it.get('src_key') and it['sha256'] in m:
                    it['src_key'] = m[it['sha256']]; it['src_how'] = 'data4_manifest'
            if all(it.get('src_key') for it in rest):
                return

    def resolve(self, proj, items, sds2_fpc=None, threads=24):
        """sets src_bucket / src_key / src_how on each item (None when unresolved).  Order: own data-3 object > loose source
        object > data-3 marker > (prior:) conv-scan maps (sha-proven) > data-4 marker > data-4 manifests / index >
        disk12_sha_map (S3 SHA-256-proven sha -> Disk-1/2 key, any archive) > Disk-2/Disk-1 same-archive path."""
        pend_m3 = []; pend_prior = []
        for it in items:
            k = it.get('raw_key') or ''
            it['src_bucket'] = B
            if k.startswith('cad-disk-extract/'):
                it['src_key'] = k; it['src_how'] = 'data3_archive' if it.get('dedup') == 'archive' else 'data3'
            elif k.startswith('src:'):
                it['src_key'] = k[4:]; it['src_how'] = 'data3_source'
            elif k.startswith('sha256:'):
                pend_m3.append(it)
            elif k.startswith('prior:'):
                pend_prior.append(it)
            elif it['bytes'] == 0:
                it['src_key'] = None; it['src_how'] = 'empty'
            else:
                it['src_key'] = None; it['src_how'] = 'unresolved:no_key'
        with ThreadPoolExecutor(threads) as tp:
            for it, t in zip(pend_m3, tp.map(lambda i: self._marker(ROOT, i['sha256']), pend_m3)):
                it['src_key'] = t; it['src_how'] = 'data3_marker' if t else 'unresolved:data3_marker'
        rest = []
        smap = self._sds2_map(sds2_fpc) if sds2_fpc else {}
        for it in pend_prior:
            sha = it['sha256']
            if sha in smap:
                it['src_key'] = smap[sha]; it['src_how'] = 'sds2_scan'; continue
            if pc.ext_of(it['source_path']) in ('.ifc', '.ifczip', '.ifcxml'):
                hit = self._ifc_map().get(sha)
                if hit:
                    it['src_key'], it['src_how'] = hit; continue
            rest.append(it)
        with ThreadPoolExecutor(threads) as tp:
            for it, t in zip(rest, tp.map(lambda i: self._marker(Z4, i['sha256']), rest)):
                if t: it['src_key'] = t; it['src_how'] = 'data4_marker'
        rest = [it for it in rest if not it.get('src_key')]
        if rest:                                     # data-4 manifests of sibling archives (small files have no marker)
            self._d4_siblings(items, rest)
            rest = [it for it in rest if not it.get('src_key')]
        if rest:                                     # fleet-built data-4 small-file index (build-d4-index), when present
            for it in rest:
                k = self._d4_index(it['sha256'])
                if k: it['src_key'] = k; it['src_how'] = 'data4_index'
            rest = [it for it in rest if not it.get('src_key')]
        if rest:                                     # proven sha256 -> Disk-1/2 key map (any archive; size must match too)
            dm = self._d12_map()
            for it in rest:
                e = dm.get(it['sha256'])
                if e and e[1] == it['bytes']:
                    it['src_key'] = e[0]; it['src_how'] = 'disk12_sha_map'
            rest = [it for it in rest if not it.get('src_key')]
        if rest:
            pm, used = self._peer_map(proj)
            for it in rest:
                mp = it['source_path'][len(proj['source_prefix']):]
                cands = [c for c in pm.get(_lk(mp), []) if c[1] == it['bytes']]
                if len(cands) > 1:
                    exact = [c for c in cands if c[0].endswith('/' + '/'.join(_san(x).strip('_') for x in mp.split('/')))]
                    cands = exact[:1] if len(exact) == 1 else cands
                if len(cands) == 1:
                    it['src_key'] = cands[0][0]; it['src_how'] = 'disk12_same_archive'   # proven by S3 SHA-256 at copy
                else:
                    it['src_key'] = None
                    it['src_how'] = 'unresolved:prior' + (':ambiguous' if len(cands) > 1 else (':no_peer' if not used else ':not_in_peer'))
        return items


# ---------------------------------------------------------------- fleet cache: data-4 small-file index (sha -> stored key)
def _scan_d4_manifest(jid):
    d = pc.get_bytes(B, f'{Z4}/_state/manifests/{jid}.jsonl.gz')
    out = []
    for l in (gzip.decompress(d).decode('utf-8', 'surrogateescape').splitlines() if d else []):
        if '"cad-disk-extract/' not in l:
            continue
        r = json.loads(l)
        k = r.get('key') or ''
        if k.startswith('cad-disk-extract/') and int(r.get('size') or 0) < 65536:
            out.append((r['sha256'], k))
    return jid, out


def build_d4_index(procs=32, log=print):
    """data-4 stored files < 64 KB per archive without a disk-wide marker: sha -> first stored key, 256 shards (fleet only)."""
    from concurrent.futures import ProcessPoolExecutor
    jobs = [j['id'] for j in pc.get_json(B, f'{Z4}/_control/jobs.json') if j.get('id')]
    shards = collections.defaultdict(dict); n = 0
    with ProcessPoolExecutor(procs) as ex:
        for i, (jid, rows) in enumerate(ex.map(_scan_d4_manifest, jobs, chunksize=4), 1):
            for sha, k in rows:
                shards[sha[:2]].setdefault(sha, k); n += 1
            if i % 100 == 0: log(f'd4 index: {i}/{len(jobs)} manifests, {n} rows')
    for sh, m in shards.items():
        pc.put_json(B, f'{pc.PSTATE}/cache/d4_index/{sh}.json.gz', m, gz=True)
    pc.put_json(B, f'{pc.PSTATE}/cache/d4_index/DONE.json', {'at': pc.now(), 'manifests': len(jobs), 'rows': n,
                                                            'distinct': sum(len(m) for m in shards.values())})
