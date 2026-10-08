W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/ifc2step6_dev3_trace.py $W/pkg/ifc2step6_dev3_trace.py
cd $W/diag761
( ulimit -v 20000000; V6_TRACE_IDS=1 timeout 240 /opt/conv/env/bin/python $W/pkg/ifc2step6_dev3_trace.py $W/w/dev3/761b25e0fe15219f/in.bin $W/diag761/out.step --mode hybrid --prec 2 --threads 1 --no-verify > $W/diag761/trace.log 2>&1 ); echo rc $?
grep -c "trace shape" trace.log; grep -v "trace shape" trace.log | tail -5 | cut -c1-300; grep "trace shape" trace.log | tail -3
