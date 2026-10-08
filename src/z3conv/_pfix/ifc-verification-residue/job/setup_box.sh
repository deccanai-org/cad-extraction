#!/bin/bash
# setup on BOX-A: /work/agentwork/ifc-verification-residue/{job,kit,coord,in,w}
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue; mkdir -p $W/job $W/kit $W/coord $W/in $W/w
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/ $W/job/
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/ $W/kit/ --exclude '*' --include '*.py' --include '*.json' --exclude '*/*'
rm -f $W/kit/ifc2step6.py $W/kit/ifc2step6_guard.py
for f in build_index.py grade_join.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/coord/$f $W/coord/$f; done
cp $W/job/rules.json $W/coord/rules.json
ls -la $W/job $W/kit $W/coord | head -60
/opt/conv/env/bin/python -c "import ifcopenshell, OCC; print('ifcopenshell', ifcopenshell.version)"
