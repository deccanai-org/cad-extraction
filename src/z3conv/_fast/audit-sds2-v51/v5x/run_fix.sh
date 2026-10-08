#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
D=/work/agentwork/audit-sds2-v5x; mkdir -p $D && cd $D
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-v5x
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-v5x/ $D/
cat > $D/fix_job.sh <<'EOS'
#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
D=/work/agentwork/audit-sds2-v5x; R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-v5x
cd $D/fixes && timeout 120 /opt/conv/env/bin/python test_patches.py > $D/fixes/test.log 2>&1; echo "test rc=$?" >> $D/fixes/test.log
cd $D && bash job.sh all
cd $D/fixes && timeout 300 /opt/conv/env/bin/python repair_state.py --plan $D/out/repair_plan.json > $D/fixes/repair_dryrun.json 2> $D/fixes/repair_dryrun.err; echo "repair rc=$?" >> $D/fixes/repair_dryrun.err
for f in test.log test_patches_result.json repair_dryrun.json repair_dryrun.err; do aws s3 cp --quiet $D/fixes/$f $R/fixes/$f; done
echo "$(date -u +%FT%TZ) fix job done" >> $D/progress.txt; aws s3 cp --quiet $D/progress.txt $R/progress.txt
EOS
setsid nohup bash $D/fix_job.sh > $D/fix_job.log 2>&1 < /dev/null &
PID=$!
for i in $(seq 1 38); do sleep 3; kill -0 $PID 2>/dev/null || break; done
tail -4 $D/progress.txt; echo ---; tail -30 $D/fixes/test.log
