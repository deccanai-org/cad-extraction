W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/verify_recovered.py $W/pkg/verify_recovered.py
cd $W/pkg
for i in aa33931d26f7b00f 224b42bfc48cf6d2; do timeout 600 /opt/conv/env/bin/python verify_recovered.py $W/w/dev3/$i $W/w/dev3p/$i $W/pkg/ifc2step6_dev3p.py > $W/verify_recovered_$i.jsonl 2>&1; aws s3 cp --quiet $W/verify_recovered_$i.jsonl s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/diag/verify_recovered_$i.jsonl; done
echo done
