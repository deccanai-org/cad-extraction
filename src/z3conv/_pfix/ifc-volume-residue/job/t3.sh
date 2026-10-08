W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/diag_part.py $W/pkg/diag_part.py
cd $W/pkg && timeout 300 /opt/conv/env/bin/python diag_part.py $W/w/dev3/aa33931d26f7b00f/in.bin 2tFcBAQab4uOFzjBL6IWl6 2>&1 | tail -40
tail -3 $W/batch_dev3.log; ls $W/w/dev3 | wc -l; uptime
