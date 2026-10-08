W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/try_vol.py $W/pkg/try_vol.py
cd $W/pkg && timeout 280 /opt/conv/env/bin/python try_vol.py $W/w/dev3/03af2c3170d9a570/in.bin 1XUzTS000MM34sCpKrCZ8v 2>&1 | tail -20
