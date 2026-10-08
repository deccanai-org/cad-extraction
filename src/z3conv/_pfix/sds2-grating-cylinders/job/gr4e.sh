#!/bin/bash
# per-piece grating table with the final grating.py (plan-area density check) -> gr4e/
W=/work/agentwork/sds2-grating-cylinders; cd $W
A=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders
for t in v54sgc v553sgc; do aws s3 cp --quiet $A/$t.tgz . && rm -rf $t && mkdir -p $t && tar xzf $t.tgz -C $t; done
rm -rf v553 && mkdir -p v553 && aws s3 cp --quiet $A/sds2-step-pipeline-v5.5.3.zip . && (cd v553 && unzip -q ../sds2-step-pipeline-v5.5.3.zip)
grep -c CUT_DENSITY v54sgc/sds2-step-pipeline/decode/grating.py v553sgc/sds2-step-pipeline/decode/grating.py; ls v553/sds2-step-pipeline/decode/to_step2.py
cat > run_gr4e.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
rm -rf gr4e gtest5; mkdir -p gr4e gtest5; cp v54sgc/sds2-step-pipeline/decode/grating.py gr4.py gtest5/
for n in SLC4_DATABANK_JOB_2d968e 1504_EQUADOR_f90185 PSU_BNR_JOB_mallesh_4e9908 One_Light_Tower_JOB_-Model_700bd1 DSCC_JOB_ef345b TEMP_Wayne_Farms_Job_61d687 1510_-_LAREDO_CONVENT_JOB_ce9a53 18011_PNW_Freezer_J_438d3c SHERIFFS_OFFICE_JOB_e730aa UOM_Union_bldg_Job_040519_633e54 F35_FLIGHT_SIMULATION_TEMP_70dbbe FMI_SAFFORD_SULFUR_TANK_JOB_948ebd; do echo $n; done | \
  xargs -P 4 -I{} bash -c 'timeout 5400 env/bin/python gtest5/gr4.py v54sgc/sds2-step-pipeline jobs/{} gr4e/{}.json >> logs/gr4e.log 2>&1'
aws s3 cp --recursive --quiet gr4e s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/gr4e/
aws s3 cp --quiet logs/gr4e.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/gr4e.log
echo done > logs/gr4e.done; aws s3 cp --quiet logs/gr4e.done s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/gr4e.done
EOS
setsid nohup bash run_gr4e.sh > run_gr4e.out 2>&1 < /dev/null &
echo launched gr4e; tail -3 logs/gr4d.log | cut -c1-300; grep -a FMI logs/gr4d.log | cut -c1-300
