#!/usr/bin/env python3
"""Second input-resolution pass for a phase-2 disk (after zjobs.py): contents left 'unresolved_input' because this disk stored only a
Disk-1/2 pointer for them.

  python3 zjobs2.py <disk>

For each occurrence (archive :: member path) of such a content:
  1. DB1: the earlier Disk-1/2 runs' own source keys (db1-v2 result input_key/key, Windows pipeline result source_key)
  2. the Disk-1 / Disk-2 extraction of the byte-identical archive at the same path (same size): the member at the same path
     (the extraction workers' folder naming, matched on the lower-case alphanumeric path), same size
Every candidate is PROVEN before it is used: S3 full-object ChecksumSHA256 equal to the content sha256, else the sha256 of the
object's bytes (streamed). Proven contents become jobs (appended to <pipe>/jobs.json, the list only grows); contents_<pipe> rows
get input_key / input_from / action convert. Writes only <root>/_state/conv2/.
"""
import os, sys, json, gzip, re, base64, hashlib, collections
from concurrent.futures import ThreadPoolExecutor
import zcensus as zc

DISK = zc.DISK; ROOT = zc.ROOT; B = zc.B
ST2 = f'{ROOT}/_state/conv2'
D12 = 'cad-disk-extract'
SRC = {'zentitude-data-4': 'Zentitude-data-4/'}[DISK]
PEERS = ('Disk-1', 'Disk-2')
log = zc.log; s3 = zc.s3; getj = zc.getj


def put(key, body, gz=False):
    assert key.startswith(ST2 + '/'), key
    if gz:
        body = gzip.compress(body, 6)
    s3().put_object(Bucket=B, Key=key, Body=body)


def head(key, checksum=False):
    try:
        return s3().head_object(Bucket=B, Key=key, **({'ChecksumMode': 'ENABLED'} if checksum else {}))
    except Exception:
        return None


def _lk(p):
    return re.sub(r'[^a-z0-9]+', '', p.lower())


def _san(s):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)


def _sc(s):
    s = re.sub(r"[^A-Za-z0-9._!+\-]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_") or "_"


def keys_under(prefix):
    out = []
    for pg in s3().get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        out += [(o['Key'], o['Size']) for o in pg.get('Contents', [])]
    return out


PEER = {}


def peer_map(archive, size):
    """member loose-key -> [(key, size)] of the earlier extraction of the byte-identical archive (cached per archive)"""
    if archive in PEER:
        return PEER[archive]
    out = {}
    rel = archive[len(SRC):] if archive.startswith(SRC) else None
    if rel:
        for disk in PEERS:
            h = head(f'{disk}/{rel}')
            if not h or (size and int(h['ContentLength']) != int(size)):
                continue
            h12 = hashlib.sha256(f'{disk}/{rel}'.encode()).hexdigest()[:12]
            used = None
            for flat in dict.fromkeys((_sc(rel)[:240], _san(rel))):
                for pref in (f'{D12}/{disk}/{flat}-{h12}/', f'{D12}/{disk}/{flat}/'):
                    ks = keys_under(pref)
                    if ks:
                        for k, sz in ks:
                            out.setdefault(_lk(k[len(pref):]), []).append((k, sz))
                        used = pref; break
                if used:
                    break
            if used:
                break
    PEER[archive] = out
    return out


def proven(key, sha, size):
    h = head(key, checksum=True)
    if not h or int(h['ContentLength']) != int(size):
        return None
    cs = h.get('ChecksumSHA256')
    if cs and h.get('ChecksumType', 'FULL_OBJECT') == 'FULL_OBJECT' and '-' not in cs:
        return 's3_checksum' if base64.b64decode(cs).hex() == sha else None
    hh = hashlib.sha256()
    body = s3().get_object(Bucket=B, Key=key)['Body']
    for chunk in iter(lambda: body.read(8 << 20), b''):
        hh.update(chunk)
    return 'sha256_of_bytes' if hh.hexdigest() == sha else None


def main():
    jl_ = getj(f'{ROOT}/_control/jobs.json') or []
    asize = {(j.get('key') or j.get('dir')): j.get('size') for j in jl_ if isinstance(j, dict)}
    summ = getj(f'{ST2}/scan/jobs_summary.json') or {}
    stats = {}
    for pipe in ('ifc', 'db1'):
        rows = [json.loads(l) for l in gzip.decompress(s3().get_object(Bucket=B, Key=f'{ST2}/scan/contents_{pipe}.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
        todo = [r for r in rows if r.get('action') == 'unresolved_input']
        archives = sorted({p.partition(' :: ')[0] for r in todo for p in r.get('paths') or []})
        log(f'{pipe}: {len(todo)} unresolved, {len(archives)} archives to map')
        with ThreadPoolExecutor(32) as ex:
            list(ex.map(lambda a: peer_map(a, asize.get(a)), archives))

        def one(r):
            sha, size = r['sha256'], r['size']
            cands = []
            if pipe == 'db1':
                r12 = getj(f'{D12}/_state/db1-v2/results/{sha}.json') or {}
                rw = getj(f'{D12}/derived/db1-step/Disk-1/by-sha256/{sha}/result.json') or {}
                cands += [(k, 'disk12_prior_result_source_key') for k in (rw.get('source_key'), r12.get('input_key'), r12.get('key')) if k]
            for p in r.get('paths') or []:
                a, _, m = p.partition(' :: ')
                for k, sz in peer_map(a, asize.get(a)).get(_lk(m), []):
                    if sz == size:
                        cands.append((k, 'disk12_peer_extraction'))
            seen = set()
            for k, how in cands:
                if k in seen:
                    continue
                seen.add(k)
                try:
                    pr = proven(k, sha, size)
                except Exception:
                    pr = None
                if pr:
                    return r, k, f'{how}:{pr}'
            return r, None, 'unresolved_after_pass2' if not cands else 'candidates_not_proven'
        got = collections.Counter(); newjobs = []
        with ThreadPoolExecutor(32) as ex:
            for r, k, how in ex.map(one, todo):
                got[how] += 1
                if k:
                    r.update(action='convert', input_key=k, input_from=how)
                    j = {'id': r['id'], 'sha256': r['id'], 'size': r['size'], 'input_key': k, 'input_from': how,
                         'n_paths': r['n_paths'], 'paths': r['paths'], 'disk': DISK}
                    if pipe == 'ifc':
                        j['kind'] = r.get('kind'); j['retry_of'] = None
                    newjobs.append(j)
                else:
                    r['pass2'] = how
        jobs = getj(f'{ST2}/{pipe}/jobs.json') or []
        have = {j['id'] for j in jobs}
        jobs += [j for j in newjobs if j['id'] not in have]
        jobs.sort(key=lambda j: -(j.get('size') or 0))
        put(f'{ST2}/{pipe}/jobs.json', json.dumps(jobs).encode())
        put(f'{ST2}/scan/contents_{pipe}.jsonl.gz', ''.join(json.dumps(r) + '\n' for r in rows).encode(), gz=True)
        stats[pipe] = {'unresolved_before': len(todo), 'resolved': len(newjobs), 'by_how': dict(got), 'jobs_total': len(jobs),
                       'still_unresolved': sum(1 for r in rows if r.get('action') == 'unresolved_input')}
        log(pipe, json.dumps(stats[pipe]))
    summ['pass2'] = dict(stats, updated=zc.now())
    put(f'{ST2}/scan/jobs_summary.json', json.dumps(summ, indent=1).encode())
    log('PASS2', json.dumps(stats))


if __name__ == '__main__':
    main()
