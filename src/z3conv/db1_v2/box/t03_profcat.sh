CTL=s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/_box
OUT=s3://bim-proprietary-data/cad-disk-extract/_work/db1_v2
mkdir -p /opt/v2/pc && cd /opt/v2/pc
aws s3 cp --quiet $CTL/profcat.py .
until [ -f /opt/v2/bc/keys.json ]; do sleep 10; done
cp /opt/v2/bc/keys.json keys.json
python3 profcat.py keys.json profcat.jsonl 24 &
P=$!
while kill -0 $P 2>/dev/null; do sleep 90; aws s3 cp --quiet profcat.jsonl $OUT/profcat.jsonl; done
aws s3 cp --quiet profcat.jsonl $OUT/profcat.jsonl
echo finished
