W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/peek2.py $W/pkg/peek2.py
timeout 100 /opt/conv/env/bin/python $W/pkg/peek2.py $W/w/dev3/761b25e0fe15219f/in.bin 1075 2>&1 | cut -c1-300 | head -40
