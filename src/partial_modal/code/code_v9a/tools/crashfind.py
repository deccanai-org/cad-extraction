import sys, subprocess, json, os
folder = sys.argv[1]
sys.path.insert(0, 'kit'); import steelbuild
ids = [p['part_id'] for p in steelbuild.Schedules(folder).parts]
code = """
import sys; sys.path.insert(0,'kit'); import steelbuild
S=steelbuild.Schedules(sys.argv[1]); want=set(sys.argv[2].split(','))
for p in S.parts:
    if p['part_id'] in want:
        try: steelbuild.build_part(p,S)
        except Exception: pass
"""
def ok(chunk):
    r = subprocess.run([sys.executable, '-c', code, folder, ','.join(chunk)], capture_output=True)
    return r.returncode == 0
bad = []
def search(chunk):
    if ok(chunk): return
    if len(chunk) == 1: bad.append(chunk[0]); print('CRASH', chunk[0], flush=True); return
    h = len(chunk) // 2; search(chunk[:h]); search(chunk[h:])
from concurrent.futures import ThreadPoolExecutor
chunks = [ids[i:i+300] for i in range(0, len(ids), 300)]
with ThreadPoolExecutor(8) as ex: list(ex.map(search, chunks))
print('bad', bad)
