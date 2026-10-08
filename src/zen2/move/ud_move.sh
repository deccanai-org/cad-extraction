#!/bin/bash
# annotationprod/cad-disk-extract -> bim-proprietary-data/cad-disk-extract mover box (AL2023). ROLE=coordinator runs probe + plan first.
exec > /var/log/move-boot.log 2>&1
set -x
ROLE=__ROLE__
C=s3://bim-proprietary-data/cad-disk-extract/_control/move
K=s3://annotationprod/cad-disk-extract/_control/move
L=s3://bim-proprietary-data/cad-disk-extract/_state/move/logs
dnf install -y python3-pip > /dev/null 2>&1
pip3 install -q -U boto3
mkdir -p /opt/move && cd /opt/move
aws s3 cp --quiet $K/move_worker.py move_worker.py
echo "$(date -u +%FT%TZ) $(hostname) $ROLE cpus=$(nproc)" | aws s3 cp - $L/boot-$(hostname).txt
if [ "$ROLE" = coordinator ]; then
  MOVE_MODE=probe python3 move_worker.py > probe.out 2>&1; aws s3 cp --quiet probe.out $L/probe-$(hostname).out
  aws s3 ls $C/plan.json || { MOVE_MODE=plan python3 move_worker.py > plan.out 2>&1; aws s3 cp --quiet plan.out $L/plan-$(hostname).out; }
fi
until aws s3 ls $C/plan.json > /dev/null 2>&1; do sleep 20; done
NP=$(( $(nproc) / 2 ))
while true; do
  aws s3 cp --quiet $K/move_worker.py move_worker.py
  for i in $(seq 1 $NP); do MOVE_MODE=copy MOVE_PROC=p$i MOVE_THREADS=96 python3 move_worker.py >> copy-p$i.out 2>&1 & done
  wait
  tail -q -n 50 copy-p*.out > tail.out; aws s3 cp --quiet tail.out $L/copy-$(hostname).out
  aws s3 ls $K/stop > /dev/null 2>&1 && break
  python3 - <<'PY' && break
import boto3, sys
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
def keys(p):
    out, tok = [], None
    while True:
        kw = dict(Bucket=B, Prefix=p)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw); out += [o['Key'].rsplit('/', 1)[-1] for o in r.get('Contents', [])]
        if not r.get('IsTruncated'): return out
        tok = r['NextContinuationToken']
c = set(keys('cad-disk-extract/_control/move/chunks/')); r = set(keys('cad-disk-extract/_state/move/results/'))
sys.exit(0 if c and c <= r else 1)
PY
  sleep 30
done
shutdown -h now
