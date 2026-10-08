#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/plan1.py .
mkdir -p plan1
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
for f in gr4d/*.json; do n=$(basename $f .json); echo $n; done | xargs -P 4 -I{} bash -c 'timeout 900 env/bin/python plan1.py v55/sds2-step-pipeline jobs/{} gr4d/{}.json plan1/{}.json' 2>&1 | grep -v LD_PRE | tail -20
aws s3 cp --recursive --quiet plan1 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/plan1/
