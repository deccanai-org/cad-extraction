cd /work/agentwork/class1-readiness-audit
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/summ.py job/
for t in k; do timeout 600 /opt/conv/env/bin/python job/summ.py $t 2>&1 | tail -2; done
tail -3 aud_k.log; tail -2 aud_k2.log; tail -3 locate.log; ps -eo pid,etime,args | grep "kit_k/convert_one\|kit_k2/convert_one\|locate.py\|7zz" | grep -v grep | sed 's/kit_k[2]*\/convert_one.py src\///' | cut -c1-110
