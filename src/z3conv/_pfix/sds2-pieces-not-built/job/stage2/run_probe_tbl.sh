W=/work/agentwork/sds2-pieces-not-built; cd $W
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
for f in probe_tbl.py probe_files.py; do aws s3 cp --quiet $C/$f $W/stage/$f; done
timeout 100 $W/env/bin/python $W/stage/probe_tbl.py $W/trees/v553/decode RH_PALO_PRACTICE_JOB_7e8b67 Viewer_J_3347a3 061219_Temp_BUILDING_J_JOB_986599 A-Practice_Job_1cd870 2>&1 | tail -80
timeout 30 $W/env/bin/python $W/stage/probe_files.py Viewer_J_3347a3:149 061219_Temp_BUILDING_J_JOB_986599:79 2>&1 | head -40
