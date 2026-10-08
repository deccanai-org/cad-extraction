#!/usr/bin/env python3
"""Zentitude-data-4 adapter for the general packager (phase 2: the other disks through the same pipeline).

Same contract as adapter_zen3 (projects = one extracted archive folder / loose-folder job; files from the disk's manifests; the
common conversion index; resolution of every packaged file to a stored object), with the data-4 inputs:
  jobs        bim cad-disk-extract/zentitude-data-4/_control/jobs.json            archive jobs {id,key,size} / loose dirs {id,dir}
  manifests   bim cad-disk-extract/zentitude-data-4/_state/manifests/<job id>.jsonl.gz
  conv index  bim cad-disk-extract/zentitude-data-4/_state/conv2/index.jsonl.gz    (disk-lane index; rows copied from data-3 for
              contents converted there carry reused_from_disk - those models are packaged by their primary disk, never here)
  keys        data-4 real objects (cad-disk-extract/zentitude-data-4/extracted/...), data-4 markers ('sha256:' -> _state/sha/),
              Disk-1/2 pointers ('disk12:sha256:<sha>'): the conv2 scan maps (input keys, sds2 file lists), the pkg-resolver
              disk12_sha_map (S3 sha256-proven), the Disk-1 extraction of the byte-identical archive at the same path.
Project id: Zentitude-data-4__<archive path, '/' -> '_'>.
"""
from __future__ import annotations
import gzip, json, os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pkgcore as pc
import adapter_zen3 as z3

B = z3.B
ROOT = 'cad-disk-extract/zentitude-data-4'
ST2 = f'{ROOT}/_state/conv2'
JOBS = f'{ROOT}/_control/jobs.json'
INDEX = f'{ST2}/index.jsonl.gz'
SRC = 'Zentitude-data-4/'
PEERS = ('Disk-1',)                      # data-4 holds every Disk-1 archive byte-identical (src identity audit 2026-09-30)


class Adapter(z3.Adapter):
    disk = 'Zentitude-data-4'
    extracted = f'{ROOT}/extracted/'     # stored-copy prefix (primary map: the archive whose extraction stored the copy)
    pkg_tag = 'zen4'

    def __init__(self, cache_dir=None, log=print):
        self.log = log
        self.cache_dir = cache_dir
        jobs = self._cached_json(B, JOBS, 'jobs_zen4.json') or []
        self.by_src = {}
        for j in jobs:
            if j.get('key'): self.by_src[j['key']] = j
            elif j.get('dir'): self.by_src[j['dir']] = j
        self._ifc = None; self._sds2 = {}; self._peer = {}; self._mk = {}
        import threading
        self._lock = threading.Lock()

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

    def files(self, proj):
        d = None
        if self.cache_dir:
            p = os.path.join(self.cache_dir, 'man4', proj['job_id'] + '.jsonl.gz')
            d = open(p, 'rb').read() if os.path.exists(p) else None
        if d is None:
            d = pc.get_bytes(B, f"{ROOT}/_state/manifests/{proj['job_id']}.jsonl.gz")
        if d is None:
            raise RuntimeError(f"no manifest for {proj['job_id']}")
        out = []
        for l in gzip.decompress(d).decode('utf-8', 'surrogateescape').splitlines():
            if l.strip():
                r = json.loads(l)
                if not r.get('sha256'):
                    continue
                out.append({'path': r['path'], 'size': int(r.get('size') or 0), 'sha256': r['sha256'], 'key': r.get('key'),
                            'dedup': r.get('dedup')})
        return out

    # ------------------------------------------------------------ conversion index
    def conv_rows(self, index_bytes=None):
        d = index_bytes if index_bytes is not None else pc.get_bytes(B, INDEX)
        rows = super().conv_rows(d)
        raw = [json.loads(l) for l in gzip.decompress(d).decode().splitlines() if l.strip()]
        for r, x in zip(rows, raw):
            r['reused_from_disk'] = x.get('reused_from_disk')        # converted on another disk: packaged by that disk's primary
            r['input_not_found'] = x.get('status') == 'input_not_found'
        return rows

    # ------------------------------------------------------------ resolution
    def _ifc_map(self):
        if self._ifc is None:
            m = {}
            raw = pc.get_bytes(B, f'{ST2}/scan/contents_ifc.jsonl.gz')
            for l in (gzip.decompress(raw).decode().splitlines() if raw else []):
                if l.strip():
                    r = json.loads(l)
                    if r.get('input_key'):
                        m[r['sha256']] = (r['input_key'], 'ifc_scan:' + str(r.get('input_from')))
            raw = pc.get_bytes(B, f'{ST2}/scan/contents_db1.jsonl.gz')
            for l in (gzip.decompress(raw).decode().splitlines() if raw else []):
                if l.strip():
                    r = json.loads(l)
                    if r.get('input_key'):
                        m[r['sha256']] = (r['input_key'], 'db1_scan:' + str(r.get('input_from')))
            self._ifc = m
        return self._ifc

    def _sds2_map(self, fpc):
        if fpc not in self._sds2:
            d = pc.get_json(B, f'{ST2}/sds2/files/{fpc}.json.gz') or []
            self._sds2[fpc] = {r['sha256']: r['key'] for r in d if r.get('key')}
        return self._sds2[fpc]

    def _peer_map(self, proj):
        """the Disk-1 extraction of the byte-identical archive at the same path: loose-key -> [(key, size)]"""
        pid = proj['project_id']
        if pid in self._peer: return self._peer[pid]
        out = {}; used = None
        if proj['kind'] == 'archive':
            rel = proj['source_key'][len(SRC):]
            for disk in PEERS:
                h = pc.head(B, f'{disk}/{rel}')
                if not h or int(h['ContentLength']) != int(proj.get('size') or -1):
                    continue
                import hashlib
                h12 = hashlib.sha256(f"{disk}/{rel}".encode()).hexdigest()[:12]
                for flat in dict.fromkeys((z3._sc(rel)[:240], z3._san(rel))):
                    for pref in (f'cad-disk-extract/{disk}/{flat}-{h12}/', f'cad-disk-extract/{disk}/{flat}/'):
                        ks = pc.list_keys(B, pref)
                        if ks:
                            for k, sz, et in ks:
                                out.setdefault(z3._lk(k[len(pref):]), []).append((k, sz))
                            used = pref; break
                    if used: break
                if used: break
        self._peer[pid] = (out, used)
        return self._peer[pid]

    def resolve(self, proj, items, sds2_fpc=None, threads=24):
        """own data-4 object > data-4 marker > (disk12:) conv2 scan maps (sha-proven) > disk12_sha_map > Disk-1 same-archive path"""
        pend_mk = []; pend_d12 = []
        for it in items:
            k = it.get('raw_key') or ''
            it['src_bucket'] = B
            if k.startswith('cad-disk-extract/'):
                it['src_key'] = k; it['src_how'] = 'data4'
            elif k.startswith('src:'):
                it['src_key'] = k[4:]; it['src_how'] = 'data4_source'
            elif k.startswith('sha256:'):
                pend_mk.append(it)
            elif k.startswith('disk12:') or k.startswith('prior:'):
                pend_d12.append(it)
            elif it['bytes'] == 0:
                it['src_key'] = None; it['src_how'] = 'empty'
            else:
                it['src_key'] = None; it['src_how'] = 'unresolved:no_key'
        with ThreadPoolExecutor(threads) as tp:
            for it, t in zip(pend_mk, tp.map(lambda i: self._marker(ROOT, i['sha256']), pend_mk)):
                it['src_key'] = t; it['src_how'] = 'data4_marker' if t else 'unresolved:data4_marker'
        rest = []
        smap = self._sds2_map(sds2_fpc) if sds2_fpc else {}
        for it in pend_d12:
            sha = it['sha256']
            if sha in smap:
                it['src_key'] = smap[sha]; it['src_how'] = 'sds2_scan'; continue
            hit = self._ifc_map().get(sha)
            if hit:
                it['src_key'], it['src_how'] = hit; continue
            rest.append(it)
        if rest:
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
                cands = [c for c in pm.get(z3._lk(mp), []) if c[1] == it['bytes']]
                if len(cands) > 1:
                    exact = [c for c in cands if c[0].endswith('/' + '/'.join(z3._san(x).strip('_') for x in mp.split('/')))]
                    cands = exact[:1] if len(exact) == 1 else cands
                if len(cands) == 1:
                    it['src_key'] = cands[0][0]; it['src_how'] = 'disk12_same_archive'   # proven by S3 SHA-256 at copy
                else:
                    it['src_key'] = None
                    it['src_how'] = 'unresolved:disk12' + (':ambiguous' if len(cands) > 1 else (':no_peer' if not used else ':not_in_peer'))
        return items
