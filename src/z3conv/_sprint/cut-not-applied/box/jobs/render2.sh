#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/render_pair.py stage/tools/make_spec.py stage/tools/region_spec.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
P=/opt/conv/env/bin/python
$P tools/make_spec.py 6304887153755ea3 'FLT10*75' 600 renders/s3.json && $P tools/render_pair.py renders/s3.json renders/6304_stringer_holes.png
$P tools/make_spec.py 6eabb07e71459be6 'W14X22' 700 renders/s4.json && $P tools/render_pair.py renders/s4.json renders/6eab_W14X22_cope.png
AFTER=kitp3 $P tools/make_spec.py e151a8faacbce446 'F.B 75X10' 500 renders/s5.json && $P tools/render_pair.py renders/s5.json renders/e151_FB75x10_stringer_P8.png
# a part recovered by P3 (absent before) with its cut
RP=$($P - <<'P'
import json, gzip
A = {p[0] for p in json.load(gzip.open('pipes2/kit2/0762effe61de88c0/convert.json.parts.json.gz', 'rt'))}
B = json.load(gzip.open('pipes2/kitp2/0762effe61de88c0/convert.json.parts.json.gz', 'rt'))
c = sorted([(p[6], p[0]) for p in B if p[0] not in A and p[3] == 'written' and p[1] == 'L65*65*6'], reverse=True)
print(c[0][1] if c else '')
P
)
[ -n "$RP" ] && $P tools/region_spec.py 0762effe61de88c0 $RP 450 renders/s6.json && $P tools/render_pair.py renders/s6.json renders/0762_recovered_parts.png
for f in renders/*.png; do aws s3 cp --quiet $f $OUT/renders/; done; ls -la renders/*.png
