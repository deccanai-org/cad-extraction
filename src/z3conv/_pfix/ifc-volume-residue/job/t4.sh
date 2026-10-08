W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/diag_open.py $W/pkg/diag_open.py
cd $W/pkg && timeout 300 /opt/conv/env/bin/python diag_open.py $W/w/dev3/aa33931d26f7b00f/in.bin 2tFcBAQab4uOFzjBL6IWl6 2>&1 | tail -60
