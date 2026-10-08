#!/bin/bash
# census3_final.sh LABEL - final census v3 evaluation over the work dirs of LABEL
L=$1
W=/work/agentwork/ifc-volume-residue; export KIT=$W/pkg/kit
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/diag
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/ifc_census_v3.py $W/pkg/ifc_census_v3.py
ls -d $W/w/$L/*/ | while read d; do [ -f $d/step_parts.jsonl.gz ] && echo $d; done | xargs -P 4 -I{} timeout 1800 /opt/conv/env/bin/python $W/pkg/census3_eval.py {} $W/pkg/ifc_census_v3.py > $W/census3_final_$L.jsonl 2> $W/census3_final_$L.err
aws s3 cp --quiet $W/census3_final_$L.jsonl $R/census3_final_$L.jsonl
echo CENSUS3 FINAL DONE $L
