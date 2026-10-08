#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
pkill -f "gr4.py /work/agentwork/sds2-grating-cylinders" ; sleep 1
ls gr4
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders
cat > run_gr4b.sh <<'EOS'
#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
for f in gr4.py grating.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/$f .; done
PY=$WD/env/bin/python; OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders
mkdir -p gr4b; rm -f gr4b/*.json; : > logs/gr4b.log
N=0
for n in SHERIFFS_OFFICE_JOB_e730aa PSU_BNR_JOB_mallesh_4e9908 DSCC_JOB_ef345b One_Light_Tower_JOB_-Model_700bd1 18011_PNW_Freezer_J_438d3c TEMP_Wayne_Farms_Job_61d687 1504_EQUADOR_f90185 1510_-_LAREDO_CONVENT_JOB_ce9a53 UOM_Union_bldg_Job_040519_633e54 F35_FLIGHT_SIMULATION_TEMP_70dbbe HONDA_QC_JOB_35979c FMI_SAFFORD_SULFUR_TANK_JOB_948ebd SLC4_DATABANK_JOB_2d968e Dupont_Reactor_Job.rar_840192; do
  [ -d jobs/$n ] && { timeout 2400 $PY gr4.py $WD/base54/sds2-step-pipeline $WD/jobs/$n gr4b/$n.json >> logs/gr4b.log 2>&1 & N=$((N+1)); }
  if [ $N -ge 12 ]; then wait; N=0; fi
done
wait
aws s3 cp --recursive --quiet gr4b $OUT/gr4b/; aws s3 cp --quiet logs/gr4b.log $OUT/logs/gr4b.log
echo done > logs/gr4b.done; aws s3 cp --quiet logs/gr4b.done $OUT/logs/gr4b.done
EOS
setsid nohup bash run_gr4b.sh > run_gr4b.out 2>&1 < /dev/null &
echo launched
