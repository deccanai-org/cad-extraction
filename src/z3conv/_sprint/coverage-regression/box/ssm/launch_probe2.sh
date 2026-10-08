#!/bin/bash
W=/work/agentwork/coverage-regression/ab
OUTS=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/coverage-regression
cd $W && aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/coverage-regression/ab/probe2.py . --only-show-errors
Z="cad-disk-extract/zenitude-data-3/extracted/Jobs & Data_Files_Completed_On_Server12_Jobs Files_FTP Data 19-3-2014_FTP Data 21-3-2014-10.10.40.4_FTP3.7z/FTP3/CrossRoads/0-FROM CRD & RMM -TO-HYD MTTL/TEKLA/### Continental Models/3_5299_Master.zip"
timeout 300 /opt/conv/env/bin/python probe2.py "$Z" "3_5299_Master/" "TJI_14-TJI/250|LVL_1-3/4X14|RS_2X6|3/4Ø_WASHER|BAR63.5*25.4" > probe2.log 2>&1
aws s3 cp --only-show-errors probe2.log $OUTS/ab/probe2.log
head -c 9000 probe2.log
