"""verify_rows.py RESTORED_GEOMETRY.jsonl [RESTORATION_LOG.json] - build every restored row with the shipped kit's own
exact builder (steelbuild.exact_part, the same code build_model.py runs) and check validity + volume against the log"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ref'))
import steelbuild as SB
log = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
want = {}
for e in log.get('entries', []):
    pid = e.get('part_id')
    v = (e.get('checks') or {}).get('volume_mm3') or (e.get('geometry') or {}).get('volume_mm3')
    want[pid] = v
res = []
for ln in open(sys.argv[1]):
    r = json.loads(ln)
    sols = SB.exact_part(r)
    vol = sum(s.volume for s in sols)
    ok = all(s.is_valid for s in sols) and (want.get(r['part_id']) is None or abs(vol / want[r['part_id']] - 1) < 1e-6)
    res.append(ok)
    print(r['part_id'], 'solids', len(sols), 'valid', all(s.is_valid for s in sols), 'volume', round(vol, 3), 'log', want.get(r['part_id']), 'OK' if ok else 'FAIL')
print('rows', len(res), 'ok', sum(res))
