#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
mkdir -p $W/test $W/cache && cd $W/test
cat > t2.py <<'PY'
import sys, time, collections, os
sys.path.insert(0, '/work/agentwork/sds2-recall-nc1')
import ifc_products
t=time.time()
d = ifc_products.digest('binney.ifc', threads=2)
ifc_products.save(d, '/work/agentwork/sds2-recall-nc1/cache/ifc_a70140e95381c7cf.npz')
print(collections.Counter(r[1] for r in d['rows']).most_common())
print('roles sample', [r[:6] for r in d['rows'][:5]])
print('sec', time.time()-t)
PY
cat > t2.sh <<'SH'
cd /work/agentwork/sds2-recall-nc1/test
aws s3 cp --quiet "s3://bim-proprietary-data/Zenitude-data-3/Completed_Jobs_Data/SDS_Jobs_7.243/CIVES NEW ENGLAND/50_Binney_Job.ifc" binney.ifc
/opt/conv/env/bin/python t2.py
rm -f binney.ifc
SH
setsid nohup bash $W/bg.sh test2 bash $W/test/t2.sh > /dev/null 2>&1 < /dev/null &
sleep 2; echo started
