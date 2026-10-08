#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
A=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders
# stop the old queue, the superseded v553g conversions and the gr4e run (this agent's PIDs only)
pkill -f "bash run_553h.sh"; sleep 1; pkill -f "bash gate3.sh"; sleep 1
for pid in $(pgrep -f "conv.sh v553g "); do pkill -P $pid; kill $pid; done
pkill -f "sds2-grating-cylinders/v553g/sds2-step-pipeline/decode/sds2_to_step.py"
pkill -f "run_gr4e.sh"; pkill -f "gtest5/gr4.py v54sgc"; sleep 2
rm -rf out/v553g; aws s3 rm --quiet --recursive $R/conv/v553g/
for t in v553h v54h; do aws s3 cp --quiet $A/$t.tgz . && rm -rf $t && mkdir -p $t && tar xzf $t.tgz -C $t; done
grep -c "no ShapeUpgrade_UnifySameDomain" v553h/sds2-step-pipeline/decode/grating.py v54h/sds2-step-pipeline/decode/grating.py
# per-piece grating table with the final code
cat > run_gr4f.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
rm -rf gr4f gtest6; mkdir -p gr4f gtest6; cp v54h/sds2-step-pipeline/decode/grating.py gr4.py gtest6/
for n in SLC4_DATABANK_JOB_2d968e FMI_SAFFORD_SULFUR_TANK_JOB_948ebd 1504_EQUADOR_f90185 PSU_BNR_JOB_mallesh_4e9908 One_Light_Tower_JOB_-Model_700bd1 DSCC_JOB_ef345b TEMP_Wayne_Farms_Job_61d687 1510_-_LAREDO_CONVENT_JOB_ce9a53 18011_PNW_Freezer_J_438d3c SHERIFFS_OFFICE_JOB_e730aa UOM_Union_bldg_Job_040519_633e54 F35_FLIGHT_SIMULATION_TEMP_70dbbe; do echo $n; done | \
  xargs -P 3 -I{} bash -c 'timeout 7200 env/bin/python gtest6/gr4.py v54h/sds2-step-pipeline jobs/{} gr4f/{}.json >> logs/gr4f.log 2>&1'
aws s3 cp --recursive --quiet gr4f s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/gr4f/
aws s3 cp --quiet logs/gr4f.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/gr4f.log
echo done > logs/gr4f.done; aws s3 cp --quiet logs/gr4f.done s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/gr4f.done
EOS
setsid nohup bash run_gr4f.sh > run_gr4f.out 2>&1 < /dev/null &
# conversion queue: v5.5.3 base (not yet started) + v5.5.3 + final patch, then two v5.4 + final patch smoke runs
for n in SHERIFFS_OFFICE_JOB_e730aa THERMOFISHER_JOB_bff8f8 1530_-_Forsyth_County_Job_7d138e One_Light_Tower_JOB_-Model_700bd1 DSCC_JOB_ef345b PSU_BNR_JOB_mallesh_4e9908 UOM_Union_bldg_Job_040519_633e54 18011_PNW_Freezer_J_438d3c VALLEY_GROVE_1_JOB_b70519 1510_-_LAREDO_CONVENT_JOB_ce9a53 TEMP_JOB_RGK_3adae7 TEMP_Wayne_Farms_Job_61d687 SLC4_DATABANK_JOB_2d968e CLAYTON_JOB_075ea0 SUSQUEHANNOCK_HS_JOB_87316d; do
  echo "v553h $W/jobs/$n"; echo "v553 $W/jobs/$n"; done > q553h.txt
echo "v54h $W/jobs/SHERIFFS_OFFICE_JOB_e730aa" >> q553h.txt; echo "v54h $W/jobs/DSCC_JOB_ef345b" >> q553h.txt
cat > run_553i.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
cat q553h.txt | while read v j; do n=$(basename $j); [ -d out/$v/$n ] && continue; bash gate3.sh $v $j; done
echo queued_all > Q553I_DONE
EOS
setsid nohup bash run_553i.sh > run_553i.out 2>&1 < /dev/null &
sleep 3; ps -eo pid,etimes,args | grep -E "conv.sh|gate3|run_553|run_gr4" | grep -v grep | cut -c1-160
