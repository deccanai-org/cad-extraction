W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/ifc2step6_dev3pc.py $W/pkg/ifc2step6_dev3pc.py
cd $W && setsid nohup bash $W/pkg/batch.sh dev3pc $W/pkg/ifc2step6_dev3pc.py --jobs 4 --ids e5f30a12ecc5f3e5,aa33931d26f7b00f,224b42bfc48cf6d2,3a5129c14f17f9b0,83b0ffca8608124f,03af2c3170d9a570,0a2c43d06678a61b > $W/batch_dev3pc.out 2>&1 < /dev/null &
echo started
