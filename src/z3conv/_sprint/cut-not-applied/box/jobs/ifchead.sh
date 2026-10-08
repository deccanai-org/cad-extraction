#!/bin/bash
B=bim-proprietary-data
for k in "cad-disk-extract/Disk-1/TEKLA-HYD_JOBS-2015-2016_10.10.40.10_Server_Backup_D_Drive_Data_PROJECT_MODELS.7z/PROJECT_MODELS/CIVES_STEEL/IRON_ORE_PELLETIZING_PLANT_PELLET_LOAD_OUT_MASTER/Load_Out.ifc" \
 "cad-disk-extract/Disk-1/TEKLA-HYD_JOBS-2019-2020_Jobs_From_Server6_Jobs_Jobs_From_Server6_Jobs.7z/GSK_40A_WAREHOUSE/out.ifc" \
 "cad-disk-extract/Disk-1/TEKLA-HYD_JOBS-2015-2016_10.10.40.18_D_Drive_Backup_PROJECT_MODELS_Part1.7z/Do_not_open_model/LARD_ABM-MODEL/out.ifc" \
 "cad-disk-extract/Disk-1/TEKLA-HYD_JOBS-2015-2016_10.10.40.57_Data_Backup_D-Drive_CMC_STEEL.7z/CMC_STEEL/LIBERTY_ABM/out.ifc" \
 "cad-disk-extract/Disk-1/TEKLA-HYD_JOBS-2015-2016_10.10.40.51_Server_Backup_TEKLA-TEAM_10.10.40.59-DATA_USA_PROJECTS_FABARC_STEEL.7z/FABARC_STEEL/3._Gambro/13._Model_back_up/12232014_11.20pm/3.GAMBRO_MASTER/out.ifc"; do
  echo "=== ${k: -80}"
  aws s3api get-object --bucket $B --key "$k" --range bytes=0-1500 /tmp/_h.ifc > /dev/null 2>&1 && head -c 1500 /tmp/_h.ifc | grep -a "FILE_NAME\|FILE_SCHEMA\|FILE_DESC" | cut -c1-300
done
