#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
pkill -f "run_v55.sh"; pkill -f "conv.sh v55 "; pkill -f "sds2-grating-cylinders/v55/sds2-step-pipeline/decode/sds2_to_step.py"; sleep 2
ps -eo pid,args | grep "sds2-grating-cylinders/v55/" | grep -v grep | wc -l
rm -rf out/v55 v55; mkdir -p v55
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/v55sgc.tgz .
tar xzf v55sgc.tgz -C v55; grep -c "_on_stored_face" v55/sds2-step-pipeline/decode/grating.py
aws s3 rm --quiet --recursive s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/conv/v55/
sed -i 's/grep -v "One_Light_Tower\\|SHERIFFS" jobs_ba.txt > jobs_v55.txt/cp jobs_ba.txt jobs_v55.txt/' run_v55.sh; grep jobs_v55 run_v55.sh | head -2
setsid nohup bash run_v55.sh > run_v55.out 2>&1 < /dev/null &
# per-piece grating check with the final builder
cat > run_gr4c.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
mkdir -p gr4c; : > logs/gr4c.log
cp v55/sds2-step-pipeline/decode/grating.py ./grating.py
for n in SHERIFFS_OFFICE_JOB_e730aa One_Light_Tower_JOB_-Model_700bd1 PSU_BNR_JOB_mallesh_4e9908 18011_PNW_Freezer_J_438d3c TEMP_Wayne_Farms_Job_61d687 DSCC_JOB_ef345b; do
  timeout 2400 env/bin/python gr4.py base54/sds2-step-pipeline jobs/$n gr4c/$n.json >> logs/gr4c.log 2>&1 &
done; wait
aws s3 cp --recursive --quiet gr4c s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/gr4c/
echo done > logs/gr4c.done; aws s3 cp --quiet logs/gr4c.done s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/gr4c.done
EOS
setsid nohup bash run_gr4c.sh > run_gr4c.out 2>&1 < /dev/null &
echo restarted
