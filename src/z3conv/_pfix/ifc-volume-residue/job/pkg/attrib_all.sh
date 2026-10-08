#!/bin/bash
# attrib_all.sh LABEL - attribution for every finished case of LABEL that has no attrib.json yet (loops until the batch is done)
LABEL=$1
W=/work/agentwork/ifc-volume-residue; export KIT=$W/pkg/kit AWS_DEFAULT_REGION=ap-south-1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/$LABEL
while true; do
  for d in $W/w/$LABEL/*/; do
    id=$(basename $d)
    [ -f $d/case.json ] || continue
    [ -f $d/attrib.json ] && continue
    [ -f $d/src_parts.jsonl.gz ] && [ -f $d/step_parts.jsonl.gz ] || { echo '{"skipped":"no parts files"}' > $d/attrib.json; continue; }
    timeout 3600 /opt/conv/env/bin/python $W/pkg/attrib.py $d $d/attrib.json --max 250 --all-sample 20 > $d/attrib.log 2>&1 || echo "{\"error\":\"rc $?\"}" > $d/attrib.json
    aws s3 cp --quiet $d/attrib.json $R/$id/attrib.json; aws s3 cp --quiet $d/attrib.log $R/$id/attrib.log
  done
  grep -q 'BATCH DONE' $W/batch_$LABEL.log 2>/dev/null && [ -z "$(for d in $W/w/$LABEL/*/; do [ -f $d/case.json ] && [ ! -f $d/attrib.json ] && echo x; done)" ] && break
  sleep 30
done
echo ATTRIB DONE $LABEL
