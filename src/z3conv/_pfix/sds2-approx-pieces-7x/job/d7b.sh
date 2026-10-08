#!/bin/bash
# after d7: classify what is still open (holes_scan) and whether a kind-7 marker face covers the holes (marker_match)
W=/work/agentwork/sds2-approx-pieces-7x
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x
exec > $W/d7b.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1
while [ ! -f $W/diag/d7/DONE ]; do sleep 20; done
mkdir -p $W/holes7
one() {
  J=$1; N=$(basename $J)
  [ -f $W/diag/d7/cand6__$N.json ] || exit 0
  timeout 1800 $W/env/bin/python $W/holes_scan.py $W/cand6/sds2-step-pipeline/decode $W/diag/d7/cand6__$N.json $J $W/holes7/$N.json > $W/holes7/$N.log 2>&1
  timeout 1800 $W/env/bin/python $W/marker_match.py $W/cand6/sds2-step-pipeline/decode $J $W/holes7/$N.json > $W/holes7/${N}_marker.log 2>&1
}
export -f one; export W
cat $W/dirs_d7.txt | xargs -P 8 -I{} bash -c 'one {}'
aws s3 cp --quiet --recursive $W/holes7 $R/holes7/
date -u +%FT%TZ > $W/holes7/DONE; aws s3 cp --quiet $W/holes7/DONE $R/holes7/DONE
