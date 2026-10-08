#!/bin/bash
W=/work/agentwork/ifc-verification-residue/sds2; cd $W
for id in 58c969614e6f06bd a47a130792964d28 6eeedc274302b8e4032f8736; do
  JD=$(cd $(dirname $(find jobs/$id -name mem_idx | head -1))/.. && pwd)
  echo "=== $id $JD"
  for d in main mem subm; do echo "$d: $(ls $JD/$d | wc -l) files, $(du -sm $JD/$d | cut -f1) MB"; done
  ls $JD | head; ls -S $JD/subm | head -5; ls $JD/main | head -20
  /work/agentwork/sds2v54/env/bin/python - "$JD" <<'PY'
import sys, os, re, collections
sys.path.insert(0, '/work/agentwork/ifc-verification-residue/sds2/v5.4ivr/sds2-step-pipeline/decode')
job = sys.argv[1]
from piece_table import read_pieces
try:
    P = read_pieces(job); print('piece table entries', len(P)); 
    c = collections.Counter(v.get('kind') or v.get('type') or '?' for v in P.values()) if isinstance(P, dict) else None
    print('kinds', c.most_common(10) if c else None)
    ks = list(P)[:5]; print('sample', [(k, {kk: P[k][kk] for kk in list(P[k])[:6]}) for k in ks])
except Exception as e:
    print('read_pieces', type(e).__name__, e)
sub = [n for n in os.listdir(os.path.join(job, 'subm')) if n.isdigit()]
print('subm piece files', len(sub), 'ids', sorted(map(int, sub))[:10], '...')
for n in ('1', '2', '3'):
    p = os.path.join(job, 'mem', n)
    if not os.path.exists(p): continue
    b = open(p, 'rb').read()
    strs = collections.Counter(m.group().decode() for m in re.finditer(rb'[ -~]{5,}', b))
    print('mem', n, len(b), 'strings', strs.most_common(15))
PY
  ls $W/out/v5.4ivr/$id/ ; head -5 $W/out/v5.4ivr/$id/*_skipped.csv 2>/dev/null; python3 -c "
import json,glob
for f in glob.glob('$W/out/v5.4ivr/$id/*manifest.json'):
    d=json.load(open(f)); print(json.dumps({k:d.get(k) for k in ('counts','standins','class_reasons','empty_job_proof','no_geometry_proof')})[:1500])"
done
