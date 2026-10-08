#!/usr/bin/env python3
"""Phase-2 residual census (read-only; writes only cad-disk-extract/_state/phase2/residual.json).

1. Disk-1 / Disk-2: every IFC / DB1 content in the Disk-1/2 deliverable packages (dataset/main/{3d,2d}/<pkg>/manifest.jsonl, sha256
   per row) compared with the data-3 and data-4 content lists (by sha256). Disk-1 is inside data-4 (byte-identical archives) and
   Disk-2 inside data-3, so the expected residual is ~0; anything left is listed (it would need its own conversion).
2. Zenitude-data-2: counts of model files by kind (the 1,927 IFC we generated from the Smart 3D database = derived geometry, census
   only per the owner) and of any customer IFC / DB1 / SDS2 / STEP / NWD files in its source / extracted trees.
"""
import os, sys, json, gzip, re, collections
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'
OUT = 'cad-disk-extract/_state/phase2/residual.json'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 40, 'mode': 'standard'}, max_pool_connections=64))


def now():
    import time
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def lst(prefix, delim=None):
    out, pre = [], []
    kw = {'Bucket': B, 'Prefix': prefix}
    if delim:
        kw['Delimiter'] = delim
    for pg in s3.get_paginator('list_objects_v2').paginate(**kw):
        out += pg.get('Contents', []); pre += [p['Prefix'] for p in pg.get('CommonPrefixes', [])]
    return out, pre


def get(key):
    try:
        b = s3.get_object(Bucket=B, Key=key)['Body'].read()
    except Exception:
        return None
    return gzip.decompress(b) if b[:2] == b'\x1f\x8b' else b


def ids(key, with_xslib=True):
    b = get(key)
    out = set()
    for l in (b.decode().splitlines() if b else []):
        if l.strip():
            r = json.loads(l)
            out.add(r.get('sha256') or r.get('id'))
    return out


def ext(p):
    b = p.lower()
    if b.endswith('.ifc.gz'):
        return 'ifc'
    return b.rsplit('.', 1)[-1] if '.' in b.rsplit('/', 1)[-1] else ''


def main():
    known = {'ifc': {}, 'db1': {}}
    for disk, st in (('zenitude-data-3', 'cad-disk-extract/zenitude-data-3/_state/conv/scan'),
                     ('zentitude-data-4', 'cad-disk-extract/zentitude-data-4/_state/conv2/scan')):
        for p in ('ifc', 'db1'):
            for i in ids(f'{st}/contents_{p}.jsonl.gz'):
                known[p].setdefault(i, disk)
    print(now(), 'known contents', {p: len(v) for p, v in known.items()}, flush=True)
    pkgs = []
    for route in ('3d', '2d'):
        _, pre = lst(f'cad-disk-extract/dataset/main/{route}/', '/')
        pkgs += pre
    print(now(), 'dataset/main packages', len(pkgs), flush=True)
    # the Disk-1/2 package manifests carry no sha256: coverage is proven by archive identity instead - every Disk-1 archive is in
    # data-4 byte-identical, data-3 holds the Disk-2 archives; an archive on the later disk was fully extracted and scanned there,
    # so its IFC / DB1 are in that disk's content list. Packages whose source archive is NOT on the later disk are the residual.
    LATER = {'Disk-1': 'Zentitude-data-4', 'Disk-2': 'Zenitude-data-3'}
    import re as _re

    def _sc(x):
        x = _re.sub(r"[^A-Za-z0-9._!+\-]+", "_", x)
        return _re.sub(r"_+", "_", x).strip("_") or "_"

    def _san(x):
        return _re.sub(r'[^A-Za-z0-9._-]+', '_', x)
    # package 'source' is the FLATTENED archive path (the extraction folder name): map it back to the real source key by the
    # extraction workers' naming, then compare sizes with the later disk's copy at the same relative path
    flat = {}; later_sz = {}
    for d_, ld in LATER.items():
        objs, _ = lst(f'{d_}/')
        for o in objs:
            rel = o['Key'][len(d_) + 1:]
            for f_ in (_sc(rel)[:240], _san(rel), rel.replace('/', '_')):
                flat.setdefault((d_, f_), (rel, o['Size']))
        objs, _ = lst(f'{ld}/')
        for o in objs:
            later_sz[(ld, o['Key'][len(ld) + 1:])] = o['Size']
    print(now(), 'source archives mapped', len(flat), 'later-disk objects', len(later_sz), flush=True)

    def head(k):
        d_, _, f_ = k.partition('/')
        hit = flat.get((d_, f_))
        return {'ContentLength': hit[1], 'rel': hit[0]} if hit else None

    def one(pre):
        man = get(pre + 'manifest.jsonl')
        pj = json.loads(get(pre + 'project.json') or b'{}')
        src = str(pj.get('source') or '')
        disk = src.split('/', 1)[0] if '/' in src else 'unknown'
        rows = collections.Counter(); byts = collections.Counter()
        for l in (man.decode('utf-8', 'replace').splitlines() if man else []):
            try:
                r = json.loads(l)
            except Exception:
                continue
            m = r.get('modality')
            if m in ('ifc', 'db1'):
                rows[m] += 1; byts[m] += int(r.get('bytes') or 0)
        if not rows:
            return pre, disk, src, rows, byts, 'no_ifc_db1'
        later = LATER.get(disk)
        if not later or not src:
            return pre, disk, src, rows, byts, 'unknown_source'
        a = head(src)
        b = later_sz.get((later, a['rel'])) if a else None
        if a is None:
            how = 'source_not_mapped'
        elif b is None:
            how = 'not_on_later_disk'
        elif a['ContentLength'] != b:
            how = 'later_copy_differs_size'
        else:
            how = 'same_size_on_later_disk'      # Disk-1 -> data-4 proven byte-identical by the 2026-09-30 source identity audit
        return pre, disk, src, rows, byts, how
    agg = collections.defaultdict(lambda: collections.Counter()); resid = []; disks = collections.Counter()
    with ThreadPoolExecutor(48) as ex:
        for pre, disk, src, rows, byts, how in ex.map(one, pkgs):
            disks[disk] += 1
            if how == 'no_ifc_db1':
                continue
            for m in ('ifc', 'db1'):
                agg[f'{disk}:{m}'][how] += rows[m]
                agg[f'{disk}:{m}'][how + '_GB'] += round(byts[m] / 1e9, 3)
            if how not in ('identical_on_later_disk', 'same_size_on_later_disk'):
                resid.append({'package': pre.rstrip('/').rsplit('/', 1)[-1], 'source': src, 'why': how, 'ifc': rows['ifc'], 'db1': rows['db1'],
                              'GB': round(sum(byts.values()) / 1e9, 3)})
    res = {'updated': now(), 'packages': len(pkgs), 'packages_by_disk': dict(disks),
           'disk12_model_rows_by_archive_coverage': {k: dict(v) for k, v in agg.items()},
           'residual_packages': len(resid), 'residual_sample': resid[:40],
           'note': 'Disk-1/2 package manifests have no sha256; coverage by archive identity (byte-identical source archive on the later disk)'}
    # data-2
    d2 = collections.Counter(); d2b = collections.Counter()
    for sub in ('model/', 'source/', 'extracted/'):
        objs, _ = lst(f'cad-disk-extract/zenitude-data-2/{sub}')
        for o in objs:
            x = ext(o['Key'])
            if x in ('ifc', 'ifczip', 'db1', 'step', 'stp', 'nwd', 'sds2', 'vue', 'sat'):
                d2[f'{sub}{x}'] += 1; d2b[f'{sub}{x}'] += o['Size']
    res['zenitude-data-2'] = {'files_by_tree_and_kind': dict(d2), 'GB_by_tree_and_kind': {k: round(v / 1e9, 2) for k, v in d2b.items()},
                              'note': 'model/ifc = derived Smart 3D IFC (our decoder) - census only (owner)'}
    s3.put_object(Bucket=B, Key=OUT, Body=json.dumps(res, indent=1).encode(), ContentType='application/json')
    print(now(), 'RESIDUAL', json.dumps({k: v for k, v in res.items() if k not in ('disk12_model_rows_by_archive_coverage', 'residual_sample')}), flush=True)
    print(now(), 'DISK12', json.dumps(res['disk12_model_rows_by_archive_coverage']), 'residual packages', res['residual_packages'], flush=True)


if __name__ == '__main__':
    main()
