#!/bin/bash
mkdir -p /work/agentwork/audit-ifc && cd /work/agentwork/audit-ifc
aws s3 cp --recursive --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/ .
rm -rf out; mkdir -p out src
cat > job.sh <<'J'
#!/bin/bash
cd /work/agentwork/audit-ifc
/opt/conv/env/bin/python harvest.py > harvest.log 2>&1
aws s3 cp --quiet harvest.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc/harvest.log
nice -n 5 /opt/conv/env/bin/python scan.py --small-procs 12 --big-procs 3 > scan.log 2>&1
aws s3 cp --quiet scan.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc/scan.log
J
chmod +x job.sh
setsid nohup ./job.sh > job.out 2>&1 < /dev/null &
echo "started pid $!"
sleep 5; ps -eo pid,args | grep -E 'harvest.py|scan.py|job.sh' | grep -v grep
