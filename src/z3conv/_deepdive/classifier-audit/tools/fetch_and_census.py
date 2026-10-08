#!/usr/bin/env python3
"""download each source IFC (AWS_PROFILE=bim) and run the ORIGINAL and the PATCHED ifc_census on it (local, own dirs only).
usage: fetch_and_census.py JOBS.txt (lines: id|size|volonly|input_key)  -> dl/v2/<id>.ifc, origcensus/, recensus/"""
import os, sys, subprocess, zipfile, gzip, shutil
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); PY = os.path.join(HERE, '..', 'venv', 'bin', 'python')
ORIG = os.path.join(HERE, '..', 'orig_v2', 'ifc_census.py'); NEW = os.path.join(HERE, '..', 'patched', 'ifc_census.py')
os.makedirs('dl/v2', exist_ok=True); os.makedirs('origcensus', exist_ok=True); os.makedirs('recensus', exist_ok=True)
jobs = [l.rstrip('\n').split('|', 3) for l in open(sys.argv[1]) if l.strip()]


def unpack(raw, d):
    with open(raw, 'rb') as f:
        head = f.read(4)
    if head == b'PK\x03\x04':
        with zipfile.ZipFile(raw) as z:
            infos = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(('.ifc', '.ifcxml'))] or [i for i in z.infolist() if not i.is_dir()]
            m = max(infos, key=lambda i: i.file_size); out = raw + '.unz.ifc'
            with z.open(m) as a, open(out, 'wb') as b:
                shutil.copyfileobj(a, b, 1 << 24)
            return out
    if head[:2] == b'\x1f\x8b':
        out = raw + '.gunz.ifc'
        with gzip.open(raw) as a, open(out, 'wb') as b:
            shutil.copyfileobj(a, b, 1 << 24)
        return out
    return raw


def one(j):
    jid, size, vo, key = j
    raw = f'dl/v2/{jid}.bin'
    if not os.path.exists(f'recensus/{jid}.src_parts.jsonl.gz') or not os.path.exists(f'origcensus/{jid}.src_parts.jsonl.gz'):
        if not os.path.exists(raw):
            subprocess.run(['aws', 's3', 'cp', '--quiet', 's3://bim-proprietary-data/' + key, raw])
        src = unpack(raw, 'dl/v2')
        for tool, dd in ((ORIG, 'origcensus'), (NEW, 'recensus')):
            if not os.path.exists(f'{dd}/{jid}.src_parts.jsonl.gz'):
                subprocess.run([PY, tool, src, f'{dd}/{jid}.census.json', '--parts', f'{dd}/{jid}.src_parts.jsonl.gz'],
                               stdout=subprocess.DEVNULL, stderr=open(f'{dd}/{jid}.err', 'w'), timeout=7200)
        for p in {raw, src}:
            if os.path.exists(p): os.remove(p)
    return jid, os.path.exists(f'recensus/{jid}.src_parts.jsonl.gz')


with ThreadPoolExecutor(int(os.environ.get('NPAR', '6'))) as ex:
    ok = 0
    for jid, good in ex.map(one, jobs):
        ok += good
        print(jid[:16], 'ok' if good else 'FAIL', flush=True)
print('done', ok, '/', len(jobs))
