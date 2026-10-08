#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue; cd $W
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue
for f in ifc2step6_612far.py targets_alm.json; do aws s3 cp --quiet $S/$f $W/job/$f; done
md5sum job/ifc2step6_612far.py
for spec in "xfar_sr kit612sr targets_mnc612.json 2" "xfar_fl kit612 targets_mnc612.json 2" "xfar_alm_sr kit612sr targets_alm.json 1"; do
  set -- $spec
  V6_FAR_ALWAYS=1 KIT_DIR=$W/$2 COORD_DIR=$W/coord612 RC_MEM_GB=40 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py $1 $W/job/ifc2step6_612far.py $W/job/$3 --slots $4 --threads 4 --vprocs 4 > $W/drive_$1.log 2>&1 < /dev/null &
  echo "$1 pid $!"
done
# 6.1.2 fleet on ALM_Baylor for the before column
KIT_DIR=$W/kit612 COORD_DIR=$W/coord612 RC_MEM_GB=40 setsid nohup /opt/conv/env/bin/python $W/job/drive2.py x612_alm $W/job/ifc2step6_612.py $W/job/targets_alm.json --slots 1 --threads 4 --vprocs 4 > $W/drive_x612_alm.log 2>&1 < /dev/null &
echo "x612_alm pid $!"
free -g | head -2
