#!/bin/bash
# BOX-A review setup: fleet kit (6.1.4 + fleet step_check) = kitF; same kit with the second-read step_check = kitS
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue-review; mkdir -p $W/job $W/in $W/w; cd $W
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue-review
aws s3 cp --quiet --recursive $S/ $W/job/
rm -rf kitF kitS coord; mkdir -p kitF coord
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/ kitF/ --exclude '*' --include '*.py' --include '*.json' --exclude '*/*'
for f in build_index.py grade_join.py rules.json; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/coord/$f coord/$f; done
cp -r kitF kitS; cp job/step_check_sr.py kitS/step_check.py
grep -m1 "^VERSION" kitF/ifc2step6.py; md5sum kitF/ifc2step6.py job/ifc2step6_614.py job/ifc2step6_614far.py kitF/step_check.py kitS/step_check.py kitF/worker.py coord/build_index.py
