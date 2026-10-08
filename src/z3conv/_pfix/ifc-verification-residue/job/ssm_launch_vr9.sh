#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/ifc2step6_vr9.py $W/job/ifc2step6_vr9.py
# Gateway BoP: full worker run (grading)
CONVF=ifc2step6_vr9.py RC_MEM_GB=40 bash $W/job/launch.sh bop_vr9 targets_bop.json 1 4 3
# Seaport: converter only (memory + levels), unpacked input from diag
mkdir -p $W/w/seaport_vr9
cd $W/w/seaport_vr9
setsid nohup /opt/conv/env/bin/python $W/job/ifc2step6_vr9.py $W/diag/seaport.ifc $W/w/seaport_vr9/out.step --mode hybrid --prec 2 --threads 4 > $W/w/seaport_vr9/log.txt 2>&1 < /dev/null &
echo seaport pid $!
ls -la $W/diag/seaport.ifc
