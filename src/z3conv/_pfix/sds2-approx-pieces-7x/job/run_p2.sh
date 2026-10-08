W=/work/agentwork/sds2-approx-pieces-7x
cd $W; export AWS_DEFAULT_REGION=ap-south-1
for id in 1a696fd3 c1873a60 884c5c1b; do
  d=$(ls -d $W/jobs/*_${id:0:6} 2>/dev/null | head -1)
  [ -z "$d" ] && d=$(timeout 200 $W/env/bin/python $W/getjob3.py $id $W/jobs 2>&1 | tail -1)
  echo "JOB $d"; du -sh $d
  timeout 100 $W/env/bin/python $W/p1.py $W/b553/sds2-step-pipeline/decode $d 1 2>&1 | head -40
done
