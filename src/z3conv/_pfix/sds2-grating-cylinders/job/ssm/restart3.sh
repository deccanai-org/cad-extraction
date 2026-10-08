#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
pkill -f "run_v55.sh"; pkill -f "conv.sh v55 "; pkill -f "sds2-grating-cylinders/v55/sds2-step-pipeline/decode/sds2_to_step.py"
pkill -f "run_rod2b.sh"; pkill -f "rod2.py v55"; pkill -f "run_gr4c.sh"; pkill -f "gr4.py base54/sds2-step-pipeline jobs"; pkill -f "gr4.py /work/agentwork/sds2-grating-cylinders/base54"; sleep 3
ps -eo pid,args | grep -E "sds2-grating-cylinders/v55/|gr4.py|rod2.py" | grep -v grep | wc -l
ls rod2/v55 | wc -l; ls rod2/base54 | wc -l
rm -rf out/v55 v55; mkdir -p v55
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/v55sgc.tgz .
tar xzf v55sgc.tgz -C v55; grep -c "GRATING_BUDGET_S\|cross_deeper_than_bars" v55/sds2-step-pipeline/decode/to_step2.py v55/sds2-step-pipeline/decode/grating.py
aws s3 rm --quiet --recursive s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/conv/v55/
setsid nohup bash run_v55.sh > run_v55.out 2>&1 < /dev/null &
cat > run_after.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
# per-piece grating table with the final builder
rm -rf gr4d; mkdir -p gr4d gtest4; cp v55/sds2-step-pipeline/decode/grating.py gtest4/grating.py; cp gr4.py gtest4/
for n in SHERIFFS_OFFICE_JOB_e730aa One_Light_Tower_JOB_-Model_700bd1 PSU_BNR_JOB_mallesh_4e9908 18011_PNW_Freezer_J_438d3c TEMP_Wayne_Farms_Job_61d687 DSCC_JOB_ef345b 1504_EQUADOR_f90185 1510_-_LAREDO_CONVENT_JOB_ce9a53 UOM_Union_bldg_Job_040519_633e54 F35_FLIGHT_SIMULATION_TEMP_70dbbe FMI_SAFFORD_SULFUR_TANK_JOB_948ebd SLC4_DATABANK_JOB_2d968e; do
  echo $n
done | xargs -P 3 -I{} bash -c 'timeout 3000 env/bin/python gtest4/gr4.py base54/sds2-step-pipeline jobs/{} gr4d/{}.json >> logs/gr4d.log 2>&1'
aws s3 cp --recursive --quiet gr4d s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/gr4d/
# rod replay v55
rm -rf rod2/v55; mkdir -p rod2/v55
for d in jobs/*/; do n=$(basename $d); [ -f $d/subm/subm_idx ] || continue; echo "v55 $n"; [ -f rod2/base54/$n.json ] || echo "base54 $n"; done | \
  xargs -P 3 -L 1 bash -c 'timeout 3000 env/bin/python rod2.py $0/sds2-step-pipeline jobs/$1 rod2/$0/$1.json >> logs/rod2.log 2>&1'
aws s3 cp --recursive --quiet rod2 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/rod2/
echo done > logs/after.done; aws s3 cp --quiet logs/after.done s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/after.done
EOS
setsid nohup bash run_after.sh > run_after.out 2>&1 < /dev/null &
echo restarted; uptime
