#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; mkdir -p truth; cd truth
B=s3://bim-proprietary-data
P1="cad-disk-extract/Disk-1/TEKLA-HYD_JOBS-2015-2016_10.10.40.10_Server_Backup_D_Drive_Data_PROJECT_MODELS.7z/PROJECT_MODELS/CIVES_STEEL/IRON_ORE_PELLETIZING_PLANT_PELLET_LOAD_OUT_MASTER"
aws s3 cp --quiet "$B/$P1/IRON_ORE_PELLETIZING_PLANT_PELLET_LOAD_OUT_MASTER.db1" iron.db1; aws s3 cp --quiet "$B/$P1/Load_Out.ifc" iron.ifc
P2="cad-disk-extract/Disk-1/TEKLA-HYD_JOBS-2019-2020_Jobs_From_Server6_Jobs_Jobs_From_Server6_Jobs.7z/GSK_40A_WAREHOUSE"
aws s3 cp --quiet "$B/$P2/GSK_40A_WAREHOUSE.db1" gsk.db1; aws s3 cp --quiet "$B/$P2/out.ifc" gsk.ifc
P3="cad-disk-extract/Disk-1/TEKLA-HYD_JOBS-2015-2016_10.10.40.51_Server_Backup_TEKLA-TEAM_10.10.40.59-DATA_USA_PROJECTS_FABARC_STEEL.7z/FABARC_STEEL/3._Gambro/13._Model_back_up/12232014_11.20pm/3.GAMBRO_MASTER"
aws s3 cp --quiet "$B/$P3/3.GAMBRO_MASTER.db1" gambro.db1; aws s3 cp --quiet "$B/$P3/out.ifc" gambro.ifc
aws s3 ls "$B/$P1/" | head -30
ls -la
for f in iron gsk gambro; do echo "== $f"; head -c 16 $f.db1 | strings | head -1; grep -c "IFCBEAM(" $f.ifc; grep -c "IFCPLATE(" $f.ifc; grep -o "IFCQUANTITY[A-Z]*('[A-Za-z]*'" $f.ifc | sort | uniq -c | sort -rn | head -12; grep -c "IFCOPENINGELEMENT(" $f.ifc; grep -c "IFCFACETEDBREP(" $f.ifc; grep -c "IFCEXTRUDEDAREASOLID(" $f.ifc; grep -c "IFCBOOLEANCLIPPINGRESULT(\|IFCBOOLEANRESULT(" $f.ifc; done
