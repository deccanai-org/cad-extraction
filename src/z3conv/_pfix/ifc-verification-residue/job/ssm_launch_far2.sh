#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
for f in ifc2step6_pfix.py step_check_far.py drive.py targets_far2.json; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/$f $W/job/$f; done
rm -rf $W/kit_gp; cp -r $W/kit $W/kit_gp; cp $W/job/step_check_far.py $W/kit_gp/step_check.py
export RC_MEM_GB=24
# 1) patched converter, stock grader
CONVF=ifc2step6_pfix.py bash $W/job/launch.sh far2_pfix targets_far2.json 2 2 2
# 2) patched converter, patched grader
CONVF=ifc2step6_pfix.py KIT_DIR=$W/kit_gp bash $W/job/launch.sh far2_pfix_gp targets_far2.json 1 2 2
# 3) patched converter with the opt-in far rule, patched grader
CONVF=ifc2step6_pfix.py KIT_DIR=$W/kit_gp V6_FAR_VERIFY=1 bash $W/job/launch.sh far2_pfixB_gp targets_far2.json 1 2 2
sleep 2; pgrep -af "drive.py" | cut -c1-120
