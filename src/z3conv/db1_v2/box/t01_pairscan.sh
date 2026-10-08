CTL=s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/_box
OUT=s3://bim-proprietary-data/cad-disk-extract/_work/db1_v2
mkdir -p /opt/v2/ps && cd /opt/v2/ps
aws s3 cp --quiet $CTL/pairscan.py . && aws s3 cp --quiet $CTL/pairscan_jobs.json .
python3 pairscan.py pairscan_jobs.json pairscan.jsonl 32 &
P=$!
while kill -0 $P 2>/dev/null; do sleep 60; aws s3 cp --quiet pairscan.jsonl $OUT/pairscan.jsonl; done
aws s3 cp --quiet pairscan.jsonl $OUT/pairscan.jsonl
echo finished
