#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue/sds2; cd $W
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/sds2
aws s3 cp --quiet --recursive $S/ .
PY=/opt/conv/env/bin/python; SPY=/work/agentwork/sds2v54/env/bin/python
J=""
for j in c88c625fc594c3baf4cf75e4:c88c625fc594c3baf4cf75e4 82c72b44deea79e67c269eb6:x 9b72c7bcefc4fe11f5e228fa:x 40e0ff87a224295965571bd3:x 01f4088b1de357eafa7dcfdb:x a313a9543e7cc59629c7277f:x 490530dbbebc724f5339ad33:x b42d0b1d3af9debc9a75fee3:x 6eeedc274302b8e4032f8736:full; do
  id=${j%%:*}; mode=${j#*:}
  fpc=$($PY -c "import json;print([x['fpc'] for x in json.load(open('jobs243.json')) if x['id']=='$id'][0])")
  if [ ! -d jobs/$id ]; then
    if [ "$mode" = full ]; then $PY mkfetch2.py $id $fpc $W/jobs/$id; else $PY mkfetch2.py $id $fpc $W/jobs/$id lite; fi
    $PY fetch.py fetch_$id.json 32 | cut -c1-200
  fi
  [ "$mode" = full ] && continue
  J="$J $(dirname $(find jobs/$id -name mem_idx | head -1))/.."
done
$SPY calsurvey.py $W/v5.4/sds2-step-pipeline/decode $J 2>&1 | grep '^{'
