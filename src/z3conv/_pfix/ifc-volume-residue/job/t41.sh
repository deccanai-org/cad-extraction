W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/census3_final.sh $W/pkg/census3_final.sh
setsid nohup bash $W/pkg/census3_final.sh dev3 > $W/census3_final_dev3.out 2>&1 < /dev/null &
echo started
