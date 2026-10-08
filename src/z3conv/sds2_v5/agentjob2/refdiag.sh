#!/bin/bash
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/refdiag
aws s3 cp --quiet $C/refdiag.py $W/refdiag.py
mkdir -p $W/refjobs; rm -f $W/refdiag.jsonl
echo 03fd09c7 2ae9ea10 347e8c82 367f60de 37788393 49ba7137 4c8f852f 5506a388 05e3d285 185e2bd3 19be4098 2ac238d7 366c1b64 414b6e93 50e40530 606dfec9 080d0e04 0b4202d4 19334987 1c5919db 30a106d3 4a88c3fd 6ec8a810 9880dbdd 12dc07c0 18e7ad17 478e57db 6a5d0c48 7dceee06 85cfc5e4 a9da90e1 ba5e66ce 20cf4c29 3fbfbd2d 72229880 737b55f2 bb4d3e5d bbe1a0f2 f32e7ddb 2e825feb | tr ' ' '\n' | xargs -P 4 -n 5 timeout 3000 $W/env/bin/python $W/refdiag.py $W/v541/sds2-step-pipeline/decode $W/refdiag.jsonl > $W/refdiag.out 2>&1
aws s3 cp --quiet $W/refdiag.jsonl $R/refdiag.jsonl
date -u +%FT%TZ > $W/REFDIAG_DONE; aws s3 cp --quiet $W/REFDIAG_DONE $R/REFDIAG_DONE
