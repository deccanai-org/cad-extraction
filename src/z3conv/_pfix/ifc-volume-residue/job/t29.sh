W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/bool_steps.py $W/pkg/bool_steps.py
cd $W/pkg && ONLY_PF=1 timeout 250 /opt/conv/env/bin/python bool_steps.py $W/w/dev3/03af2c3170d9a570/in.bin 1XVwX2000lHp4sCpKtDZ8m 2>&1 | cut -c1-250
timeout 250 /opt/conv/env/bin/python bool_steps.py $W/w/dev3/03af2c3170d9a570/in.bin 1XUzTS000MM34sCpKrCZ8v 2>&1 | cut -c1-250
