#!/bin/bash
# box_run.sh LABEL CONVERTER(v5|v6) [batch args...]  - run the regression set on the test box, upload results
LABEL=$1; CONVK=$2; shift 2
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/v6/dev; mkdir -p $D /scratch/v6/in /scratch/v6/w
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/ifc_v6dev/ $D/
touch /opt/v6/alive
export KIT=/opt/v6/kit COORD=$D CONV_HOME=/opt/conv INDEX_WORK=/scratch/v6/index PYBIN=/opt/conv/env/bin/python
case $CONVK in v5) CONV=/opt/v6/kit/ifc2step5.py;; v6) CONV=$D/ifc2step6.py;; *) CONV=$CONVK;; esac
/opt/conv/env/bin/python - <<'PY'
import json, os, boto3
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1')
ts = json.load(open('/opt/v6/dev/testset.json'))
def one(o):
    p = f"/scratch/v6/in/{o['id'][:16]}.bin"
    if os.path.exists(p) and os.path.getsize(p) == o['size']: return
    s3.download_file('bim-proprietary-data', o['input_key'], p)
with ThreadPoolExecutor(16) as ex: list(ex.map(one, ts))
print('inputs ok', len(ts))
PY
cd /scratch/v6
/opt/conv/env/bin/python $D/batch.py $LABEL $CONV --testset $D/testset.json --indir /scratch/v6/in --out /scratch/v6/w "$@" > /scratch/v6/batch_$LABEL.log 2>&1
aws s3 cp --quiet /scratch/v6/batch_$LABEL.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_dev/ifcv6/$LABEL/batch.log
for d in /scratch/v6/w/$LABEL/*/; do
  id=$(basename $d)
  for f in case.json out.step.stats.json out.step.check.json out.step.png out.step.parts.json log.txt; do
    [ -f $d/$f ] && aws s3 cp --quiet $d/$f s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_dev/ifcv6/$LABEL/$id/$f
  done
done
echo done $LABEL
