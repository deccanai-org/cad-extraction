W=/work/agentwork/sds2-pieces-not-built; cd $W
timeout 100 $W/env/bin/python $W/stage/probe_tbl.py $W/trees/v553/decode RH_PALO_PRACTICE_JOB_7e8b67 2>&1 | head -30
