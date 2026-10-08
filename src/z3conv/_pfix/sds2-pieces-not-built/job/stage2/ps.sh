W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/trees553s.tgz $W/stage/trees553s.tgz
rm -rf $W/trees/v553s && tar xzf $W/stage/trees553s.tgz -C $W/trees
timeout 250 $W/env/bin/python $W/stage/probe_sh2.py $W/trees/v553s/decode 19156_610_WALNUT_JOB_09152020_7773ea:2923,537,2807 A-Practice_Job_1cd870:615 2>&1 | tail -6
