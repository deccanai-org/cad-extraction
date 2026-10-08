#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/render_pair.py stage/tools/make_spec.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
mkdir -p renders; rm -f renders/*; P=/opt/conv/env/bin/python
$P tools/make_spec.py 0762effe61de88c0 'FLT10*8200' 900 renders/s1.json && $P tools/render_pair.py renders/s1.json renders/0762_stringer_holes.png
$P tools/make_spec.py 0762effe61de88c0 '[200*90*8*13.5' 500 renders/s2.json && $P tools/render_pair.py renders/s2.json renders/0762_channel_notch.png
for f in renders/*.png; do aws s3 cp --quiet $f $OUT/renders/; done; ls -la renders
