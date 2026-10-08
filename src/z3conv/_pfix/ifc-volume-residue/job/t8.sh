W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/fixtest.py $W/pkg/fixtest.py
cd $W/pkg && timeout 900 /opt/conv/env/bin/python fixtest.py $W/w/dev3/224b42bfc48cf6d2/in.bin 2>&1 | tail -40
