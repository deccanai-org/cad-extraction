W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/census3_all.sh $W/pkg/census3_all.sh
setsid nohup bash $W/pkg/census3_all.sh > $W/census3_all.out 2>&1 < /dev/null &
echo started
