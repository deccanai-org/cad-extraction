W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/find_culprit.py $W/pkg/find_culprit.py
cd $W/diag761 && rm -f skip.txt
for k in 1 2 3; do
  ( ulimit -v 12000000; timeout 100 /opt/conv/env/bin/python $W/pkg/find_culprit.py $W/pkg/ifc2step6_dev3.py $W/w/dev3/761b25e0fe15219f/in.bin skip.txt > fc$k.log 2>&1 ); rc=$?
  last=$(grep BEGIN fc$k.log | tail -1); echo "round $k rc $rc last: $last"; grep -E "SLOW|ALL DONE" fc$k.log | tail -5
  grep -q "ALL DONE" fc$k.log && break
  echo $last | awk '{print $2}' >> skip.txt
done
