W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/diag_open2.py $W/pkg/diag_open2.py
cd $W/pkg && timeout 300 /opt/conv/env/bin/python diag_open2.py $W/w/dev3/aa33931d26f7b00f/in.bin 2tFcBAQab4uOFzjBL6IWl6 2>&1 | tail -12
timeout 300 /opt/conv/env/bin/python diag_open2.py $W/w/dev3/224b42bfc48cf6d2/in.bin 0yx\$q9P3vAyvk2wHpWzV4U 03wQzRazfC9xsAfRCD9deu 2>&1 | tail -30
