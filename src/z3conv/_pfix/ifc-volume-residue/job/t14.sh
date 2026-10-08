W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/trace_run.py $W/pkg/trace_run.py
mkdir -p $W/diag761 && cd $W/diag761
( ulimit -v 25000000; timeout 150 /opt/conv/env/bin/python $W/pkg/trace_run.py $W/pkg/ifc2step6_dev3.py $W/w/dev3/761b25e0fe15219f/in.bin $W/diag761/out.step --mode hybrid --prec 2 --threads 2 --no-verify > $W/diag761/run.log 2>&1 )
echo rc $?
grep -v "^  File \"/opt" $W/diag761/run.log | tail -60 | cut -c1-200
