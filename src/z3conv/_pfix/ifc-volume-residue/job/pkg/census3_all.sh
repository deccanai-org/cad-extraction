#!/bin/bash
W=/work/agentwork/ifc-volume-residue; export KIT=$W/pkg/kit
for f in ifc_census_v3.py census3_eval.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/$f $W/pkg/$f; done
ls -d $W/w/dev3/*/ | while read d; do [ -f $d/step_parts.jsonl.gz ] && echo $d; done | xargs -P 4 -I{} timeout 1800 /opt/conv/env/bin/python $W/pkg/census3_eval.py {} $W/pkg/ifc_census_v3.py > $W/census3_eval.jsonl 2> $W/census3_eval.err
aws s3 cp --quiet $W/census3_eval.jsonl s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/diag/census3_eval.jsonl
aws s3 cp --quiet $W/census3_eval.err s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/diag/census3_eval.err
echo CENSUS3 DONE
