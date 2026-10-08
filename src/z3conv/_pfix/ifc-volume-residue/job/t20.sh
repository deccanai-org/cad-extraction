W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/ifc2step6_dev3p.py $W/pkg/ifc2step6_dev3p.py
cd $W && setsid nohup bash $W/pkg/batch.sh dev3p $W/pkg/ifc2step6_dev3p.py --jobs 2 --ids aa33931d26f7b00f,224b42bfc48cf6d2 > $W/batch_dev3p_a.out 2>&1 < /dev/null &
echo started
