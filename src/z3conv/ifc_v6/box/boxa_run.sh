#!/bin/bash
# boxa_run.sh LABEL CONVERTER_FILE [batch args...] - regression on BOX-A (agent box): /work/agentwork/ifcv6
LABEL=$1; CONVF=$2; shift 2
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifcv6; mkdir -p $W/dev $W/kit $W/in $W/w $W/index
cd $W
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcv6/ $W/dev/
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/ $W/kit/ --exclude '*' --include '*.py' --exclude '*/*'
export KIT=$W/kit COORD=$W/dev CONV_HOME=/opt/conv INDEX_WORK=$W/index PYBIN=/opt/conv/env/bin/python V6_VERIFY_PROCS=${V6_VERIFY_PROCS:-4}
CONV=$W/dev/$CONVF; [ "$CONVF" = v5 ] && CONV=$W/kit/ifc2step5.py
/opt/conv/env/bin/python - <<'PY'
import json, os, boto3
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1')
ts = json.load(open('/work/agentwork/ifcv6/dev/testset.json'))
def one(o):
    p = f"/work/agentwork/ifcv6/in/{o['id'][:16]}.bin"
    if os.path.exists(p) and os.path.getsize(p) == o['size']: return
    s3.download_file('bim-proprietary-data', o['input_key'], p)
with ThreadPoolExecutor(12) as ex: list(ex.map(one, ts))
print('inputs ok', len(ts))
PY
/opt/conv/env/bin/python $W/dev/batch.py $LABEL $CONV --testset $W/dev/testset.json --indir $W/in --out $W/w "$@" > $W/batch_$LABEL.log 2>&1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcv6/$LABEL
aws s3 cp --quiet $W/batch_$LABEL.log $R/batch.log
for d in $W/w/$LABEL/*/; do
  id=$(basename $d)
  for f in case.json out.step.stats.json out.step.check.json out.step.png out.step.parts.json log.txt src_parts.jsonl.gz step_parts.jsonl.gz; do
    [ -f $d/$f ] && aws s3 cp --quiet $d/$f $R/$id/$f
  done
done
echo done $LABEL
