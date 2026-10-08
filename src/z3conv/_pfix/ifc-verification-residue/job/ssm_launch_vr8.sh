#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
for L in far_vr7 far_vr7F_gp; do
  for p in $(pgrep -f "drive.py $L "); do kill -9 $p; done
  for p in $(pgrep -f "ifc-verification-residue/w/$L/"); do kill -9 $p; done
  for p in $(pgrep -f "rc.py .*w/$L/"); do kill -9 $p; done
done
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/ifc2step6_vr8.py $W/job/ifc2step6_vr8.py
CONVF=ifc2step6_vr8.py RC_MEM_GB=24 bash $W/job/launch.sh far_vr8 targets_far3.json 2 2 2
CONVF=ifc2step6_vr8.py KIT_DIR=$W/kit_gp V6_FAR_VERIFY=1 RC_MEM_GB=24 bash $W/job/launch.sh far_vr8F_gp targets_far3.json 1 2 2
CONVF=ifc2step6_vr8.py RC_MEM_GB=16 bash $W/job/launch.sh l2_vr8 targets_l2.json 1 2 2
sleep 1; pgrep -af "drive.py" | cut -c1-95; uptime
