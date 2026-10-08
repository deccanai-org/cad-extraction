W=/work/agentwork/ifc-volume-residue
for f in fixtest.py fullscan.py fullscan_all.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/$f $W/pkg/$f; done
chmod +x $W/pkg/*.sh
cd $W/pkg && (timeout 900 /opt/conv/env/bin/python fixtest.py $W/w/dev3/224b42bfc48cf6d2/in.bin > $W/fixtest_224b.log 2>&1; timeout 300 /opt/conv/env/bin/python fixtest.py $W/w/dev3/aa33931d26f7b00f/in.bin > $W/fixtest_aa33.log 2>&1; aws s3 cp --quiet $W/fixtest_224b.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/diag/fixtest_224b.log; aws s3 cp --quiet $W/fixtest_aa33.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/diag/fixtest_aa33.log) > /dev/null 2>&1 < /dev/null &
setsid nohup bash $W/pkg/fullscan_all.sh dev3 > $W/fullscan_dev3.out 2>&1 < /dev/null &
echo started
