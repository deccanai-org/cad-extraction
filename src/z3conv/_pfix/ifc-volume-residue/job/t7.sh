W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/diag_shell.py $W/pkg/diag_shell.py
cd $W/pkg && timeout 300 /opt/conv/env/bin/python diag_shell.py $W/w/dev3/aa33931d26f7b00f/in.bin 99 2>&1 | head -70
