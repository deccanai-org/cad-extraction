#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/spec2.py stage/tools/render_pair.py tools/; mkdir -p renders
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
P=/opt/conv/env/bin/python
r() { $P tools/spec2.py "$1" "$2" $3 $4 renders/$5.json "$6" "$7" "$8" && timeout 900 $P tools/render_pair.py renders/$5.json renders/$5.png && aws s3 cp --quiet renders/$5.png $OUT/renders/; }
r pipes4/nofit/fit_p7.64 pipes4/fit/fit_p7.64 1365019 450 p12_p764_C6X8_fitting 'without fittings (end 6.4 mm long)' 'P12 fitting (end trimmed to the plane)' 'Duke_Boiler 7.64 C6X8.2 1365019: bbox vs Tekla IFC 6.4 mm -> 0.0 mm'
until [ -f pipes5/kitn/a94442572f225f50/pipe.json ] && [ -f pipes4/fit/a94442572f225f50/pipe.json ]; do sleep 30; done
SEQ=$($P - <<'PY'
import json, gzip, sys
sys.path.insert(0, '/work/agentwork/cut-not-applied/kitnp7')
pl = json.load(gzip.open('pipes4/fit/a94442572f225f50/convert.json.parts.json.gz', 'rt'))
c = [p for p in pl if p[3] == 'written' and '[approx: cut outline self-crossing' in (p[1] or '') ]
print(c[0][0] if c else '')
PY
)
echo "a944 parent seq: $SEQ"
if [ -z "$SEQ" ]; then SEQ=$($P - <<'PY'
import json, gzip
A = {p[0]: p for p in json.load(gzip.open('pipes5/kitn/a94442572f225f50/convert.json.parts.json.gz', 'rt'))}
B = json.load(gzip.open('pipes4/fit/a94442572f225f50/convert.json.parts.json.gz', 'rt'))
c = sorted([(p[6] - A[p[0]][6], p[0]) for p in B if p[0] in A and p[3] == 'written' and p[6] > A[p[0]][6]], reverse=True)
print(c[0][1] if c else '')
PY
); fi
[ -n "$SEQ" ] && r pipes5/kitn/a94442572f225f50 pipes4/fit/a94442572f225f50 $SEQ 250 p14_a944_arc_cutter 'code n (cutter refused: outline crosses itself)' 'P14 (0.29 of 37 mm2 sliver dropped, cut applied)' "HRH_MASTER 7.64 part $SEQ with its BL25 arc cutters"
ls -la renders/p1*.png
