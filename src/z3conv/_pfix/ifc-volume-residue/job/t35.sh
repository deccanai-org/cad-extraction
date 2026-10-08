W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/try_wire.py $W/pkg/try_wire.py
cd $W/pkg && timeout 200 /opt/conv/env/bin/python try_wire.py $W/w/dev3/e5f30a12ecc5f3e5/in.bin 1Ff5L8dq16ehh6ac8ostWW 3d_bx4rXf9RAMFe0Ca85qq 2>&1 | cut -c1-250
