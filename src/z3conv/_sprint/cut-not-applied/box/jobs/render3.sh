#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/make_spec.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
P=/opt/conv/env/bin/python
$P tools/make_spec.py 6eabb07e71459be6 'W14X22' 700 renders/s4.json && $P tools/render_pair.py renders/s4.json renders/6eab_W14X22_cope.png
aws s3 cp --quiet renders/6eab_W14X22_cope.png $OUT/renders/
