#!/bin/bash
SLUG=db1v2-obj3c; W=/work/agentwork/$SLUG; mkdir -p $W; cd $W
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$SLUG/ .
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$SLUG
cat > drv.sh <<'L'
#!/bin/bash
cd /work/agentwork/db1v2-obj3c; OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-obj3c
python3 -c "import json; J=json.load(open('jobs_old.json')); [json.dump(J[i::6], open(f'j{i}.json','w')) for i in range(6)]"
for i in 0 1 2 3 4 5; do ( /opt/conv/env/bin/python scan_obj.py j$i.json o$i.jsonl > l$i.log 2>&1 ) & done; wait
cat o?.jsonl > scan_obj.jsonl; aws s3 cp --quiet scan_obj.jsonl $OUT/scan_obj.jsonl; cd /; rm -rf /work/agentwork/db1v2-obj3c
L
chmod +x drv.sh; setsid nohup ./drv.sh > drv.log 2>&1 < /dev/null & echo started
