# Mumbai box: worker has no loop, restart it explicitly
pkill -f "[p]ython3.11 /opt/db1w/db1_worker.py"; pkill -f "[c]onvert_one.py"; pkill -f "[i]fc2step5.py"; sleep 3
rm -rf /opt/db1w/jobs /opt/db1w/src
aws s3 cp --region ap-south-1 --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/src/db1_worker.py /opt/db1w/db1_worker.py
(DB1_WORK=/opt/db1w DB1_ORDER=small DB1_SLOTS=80 nohup python3.11 /opt/db1w/db1_worker.py > /opt/db1w/worker.out 2>&1 &)
sleep 30; tail -2 /opt/db1w/worker.out
