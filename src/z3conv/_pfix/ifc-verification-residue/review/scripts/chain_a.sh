#!/bin/bash
# runs: rvF (6.1.4 + fleet grader) || rvP (6.1.4+farall V6_FAR_ALWAYS=1 + second-read grader); then rvG (6.1.4 + second-read) || rvPF (farall + fleet grader); then the 114 MB ALM_Baylor copy F || P
W=/work/agentwork/ifc-verification-residue-review; cd $W
PY=/opt/conv/env/bin/python
export COORD_DIR=$W/coord RC_MEM_GB=32 PYTHONDONTWRITEBYTECODE=1
(KIT_DIR=$W/kitF $PY job/drive_rv.py rvF $W/job/ifc2step6_614.py job/targets_rv.json --slots 2 --threads 2 --vprocs 2 > drive_rvF.log 2>&1) &
(KIT_DIR=$W/kitS V6_FAR_ALWAYS=1 $PY job/drive_rv.py rvP $W/job/ifc2step6_614far.py job/targets_rv.json --slots 2 --threads 2 --vprocs 2 > drive_rvP.log 2>&1) &
wait
(KIT_DIR=$W/kitS $PY job/drive_rv.py rvG $W/job/ifc2step6_614.py job/targets_rv.json --slots 2 --threads 2 --vprocs 2 > drive_rvG.log 2>&1) &
(KIT_DIR=$W/kitF V6_FAR_ALWAYS=1 $PY job/drive_rv.py rvPF $W/job/ifc2step6_614far.py job/targets_rv.json --slots 2 --threads 2 --vprocs 2 > drive_rvPF.log 2>&1) &
wait
(KIT_DIR=$W/kitF RC_MEM_GB=60 $PY job/drive_rv.py rvF_big $W/job/ifc2step6_614.py job/targets_big.json --slots 1 --threads 3 --vprocs 4 > drive_rvF_big.log 2>&1) &
(KIT_DIR=$W/kitS RC_MEM_GB=60 V6_FAR_ALWAYS=1 $PY job/drive_rv.py rvP_big $W/job/ifc2step6_614far.py job/targets_big.json --slots 1 --threads 3 --vprocs 4 > drive_rvP_big.log 2>&1) &
wait
echo CHAIN_DONE > chain.done
aws s3 cp --quiet chain.done s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue-review/chain_a.done
