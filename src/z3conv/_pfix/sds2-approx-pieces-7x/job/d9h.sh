#!/bin/bash
# after d9: classify what is still open (holes_scan) and whether a kind-7 marker face covers the holes (marker_match)
W=/work/agentwork/sds2-approx-pieces-7x
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x
exec > $W/d9h.log 2>&1
cd $W; export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1
while [ ! -f $W/diag/d9/DONE ]; do sleep 20; done
mkdir -p $W/holes9
one() {
  J=$1; N=$(basename $J)
  [ -f $W/diag/d9/cand8__$N.json ] || exit 0
  timeout 1800 $W/env/bin/python $W/holes_scan.py $W/cand8/sds2-step-pipeline/decode $W/diag/d9/cand8__$N.json $J $W/holes9/$N.json > $W/holes9/$N.log 2>&1
  timeout 1800 $W/env/bin/python $W/marker_match.py $W/cand8/sds2-step-pipeline/decode $J $W/holes9/$N.json > $W/holes9/${N}_marker.log 2>&1
}
export -f one; export W
cat $W/dirs_d9.txt | xargs -P 4 -I{} bash -c 'one {}'
aws s3 cp --quiet --recursive $W/holes9 $R/holes9/
date -u +%FT%TZ > $W/holes9/DONE; aws s3 cp --quiet $W/holes9/DONE $R/holes9/DONE
