W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/peek.py $W/pkg/peek.py
timeout 100 /opt/conv/env/bin/python $W/pkg/peek.py $W/w/dev3/761b25e0fe15219f/in.bin 1075 1077 1078 973 2>&1 | cut -c1-400
