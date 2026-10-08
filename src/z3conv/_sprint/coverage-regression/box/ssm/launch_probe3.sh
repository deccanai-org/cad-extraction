#!/bin/bash
W=/work/agentwork/coverage-regression/ab
OUTS=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/coverage-regression
cd $W && aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/coverage-regression/ab/probe3.py . --only-show-errors
Z="Zenitude-data-3/Jobs & Data_Files_Completed_On_Server12/Jobs Files/FTP Data 19-3-2014/FTP Data 21-3-2014-10.10.40.4/FTP2.7z"
Z2="cad-disk-extract/zenitude-data-3/extracted/Jobs & Data_Files_Completed_On_Server12_Jobs Files_FTP Data 19-3-2014_FTP Data 21-3-2014-10.10.40.4_FTP2.7z/FTP2/customer/UPLOADS FROM MOLDTEK/Master Model/MAGNETATION_GRINDING_CIRCUIT_MASTER.zip"
timeout 900 /opt/conv/env/bin/python probe3.py "$Z2" 5b33936fcd1e3efc1c15c2e95872ca9ec08ab9f3141cd16f52474913aad52e20 probe3_5b33.json > probe3.log 2>&1
aws s3 cp --only-show-errors probe3_5b33.json $OUTS/ab/probe3_5b33.json; aws s3 cp --only-show-errors probe3.log $OUTS/ab/probe3.log
head -c 7000 probe3.log
