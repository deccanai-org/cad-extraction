#!/bin/bash
# phase.sh PHASE [ARGS]: one audit phase on the box, results to S3 agentwork/audit-db1-codes/
W=/work/agentwork/audit-db1-codes; cd $W; mkdir -p logs
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-db1-codes
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
P=/opt/conv/env/bin/python
ph=$1; shift
LG=$ph${DEC_TAG:+_$DEC_TAG}${RUNTAG:+_$RUNTAG}
echo "start $ph $(date -u +%FT%TZ) $*" > logs/$LG.status; aws s3 cp logs/$LG.status $OUT/logs/$LG.status --only-show-errors
case $ph in
  fetch) $P fetch.py > logs/fetch.json 2> logs/fetch.err; bash setup_kits.sh > logs/setup_kits.log 2>&1 ;;
  decode) $P decode_all.py "$@" > logs/$LG.log 2>&1 ;;
  *) $P "$ph.py" "$@" > logs/$LG.log 2>&1 ;;
esac
rc=$?
echo "done $ph rc=$rc $(date -u +%FT%TZ)" >> logs/$LG.status
aws s3 cp logs/ $OUT/logs/ --recursive --only-show-errors
[ -d report ] && aws s3 cp report/ $OUT/report/ --recursive --only-show-errors
