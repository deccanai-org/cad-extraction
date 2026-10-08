W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/try_nullseg.py $W/pkg/try_nullseg.py
cd $W/pkg && timeout 200 /opt/conv/env/bin/python try_nullseg.py $W/w/dev3/e5f30a12ecc5f3e5/in.bin 1Ff5L8dq16ehh6ac8ostWW 3d_bx4rXf9RAMFe0Ca85qq 2>&1 | cut -c1-250
for i in $(ls $W/w/dev3/); do [ -f $W/w/dev3/$i/in.bin ] && echo "$i $(grep -c 'IFCCOMPOSITECURVESEGMENT([^,]*,[^,]*,\$)' $W/w/dev3/$i/in.bin 2>/dev/null)"; done | awk '$2>0'
