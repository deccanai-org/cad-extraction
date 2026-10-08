#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; mkdir -p $J/out/ctl; cd $J
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures/j2/ctl
cat > $J/ctl1.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures/j2/ctl
JD=$1; N=$(basename $JD); O=$J/out/ctl/$N; rm -rf $O; mkdir -p $O; cd $O
OMP_NUM_THREADS=1 MPLBACKEND=Agg PYTHONUNBUFFERED=1 timeout 10800 $W/env/bin/python -u $J/w553b/sds2-step-pipeline/decode/sds2_to_step.py $JD -o $O/${N}_stage2.step --stage 2 --verify > $O/run.log 2>&1
echo "rc $?" >> $O/run.log
aws s3 cp --only-show-errors --recursive $O $R/$N/ --exclude "*.step"
EOS
chmod +x $J/ctl1.sh
setsid nohup bash -c "ls -d /work/agentwork/sds2v54/jobs/METHODIST_JOB_8164be /work/agentwork/sds2v54/jobs/GMS /work/agentwork/sds2v54/jobs/AGNEWS_HS_Bldg-T_job_baa236 /work/agentwork/sds2v54/jobs/TYSONS_T4_JOB_010322_0f9728 /work/agentwork/sds2v54/jobs/160920_AGNEWS_HS_Bldg-R_job_a6168a | xargs -P 3 -n 1 $J/ctl1.sh; date > $J/CTL_DONE" > /dev/null 2>&1 < /dev/null &
echo started
