#!/bin/bash
# fullscan over every finished dev3 case (2 at a time, 2 kernel threads each)
W=/work/agentwork/ifc-volume-residue; L=${1:-dev3}
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/$L
ls -d $W/w/$L/*/ | while read d; do
  id=$(basename $d)
  [ -f $d/case.json ] && [ -f $d/step_parts.jsonl.gz ] && [ ! -f $d/fullscan.json ] && echo $d
done | xargs -P 2 -I{} bash -c 'd={}; timeout 5400 /opt/conv/env/bin/python '$W'/pkg/fullscan.py $d $d/fullscan.json --threads 2 > $d/fullscan.log 2>&1; aws s3 cp --quiet $d/fullscan.json '$R'/$(basename $d)/fullscan.json'
echo FULLSCAN DONE
