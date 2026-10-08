#!/bin/bash
# v5.4 validation on the coordinator box: env, jobs, v5.4 + v5.3 on 15 jobs (6 at a time), NC1 check, Binney v5.4
exec > /work/agentwork/sds2v54/drive.log 2>&1
set -x
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54
if [ ! -x $W/env/bin/python ]; then
  /opt/conv/env/bin/python -m venv $W/env
  $W/env/bin/pip install -q --upgrade pip > pip.log 2>&1
  $W/env/bin/pip install -q cadquery-ocp==8.0.1.0.0 numpy scipy shapely matplotlib boto3 py7zr >> pip.log 2>&1
fi
mkdir -p v54 v53
tar xzf v54.tgz -C v54
$W/env/bin/python -c "import zipfile; zipfile.ZipFile('sds2-step-pipeline-v5.3.zip').extractall('v53')"
$W/env/bin/python -c "import OCP, numpy, scipy, shapely; from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox; print('env ok', BRepPrimAPI_MakeBox(1,2,3).Shape() is not None)" > envcheck.log 2>&1 || { aws s3 cp envcheck.log $R/envcheck.log; aws s3 cp pip.log $R/pip.log; exit 1; }
aws s3 cp envcheck.log $R/envcheck.log
mkdir -p jobs gms_gt
cd jobs
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Projects_Data/MT15_061 (The Greenwood Middle School)/18.ABM/01) ABM_122115/GMS ABM  122115_JOB.zip" gms.zip
$W/env/bin/python -c "import zipfile; zipfile.ZipFile('gms.zip').extractall('gmsx')"
mv "gmsx/GREENWOOD MIDDLE SCHOOL_JOB" GMS
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Projects_Data/MT15_061 (The Greenwood Middle School)/08. Uploads/For FAB/T#010_SEQ#1 PARTIAL DWGS FOR FAB  _011816/15-144_GMS_Seq# 1 Partial Dwgs  for FAB_T#010.zip" fab.zip
$W/env/bin/python -c "import zipfile; zipfile.ZipFile('fab.zip').extractall('$W/gms_gt')"
: > $W/dirs.txt
echo $W/jobs/GMS >> $W/dirs.txt
for id in 1646fd7d cf441128 15d02f20 dacd8929 0ee52d11 8164be24 0f97287d bcd6eea3 ba154ce7 a6168a5a baa236aa 2a37aab1 e56431ab bb3a3ef5; do
  $W/env/bin/python $W/getjob.py $id $W/jobs >> $W/dirs.txt 2>> $W/fetch.err
done
aws s3 cp --quiet $W/dirs.txt $R/dirs.txt
cd $W
cat dirs.txt | xargs -P 6 -I{} bash $W/conv.sh v54 {}
aws s3 cp --quiet $W/drive.log $R/drive_v54.log
cat dirs.txt | xargs -P 6 -I{} bash $W/conv.sh v53 {}
cd $W/jobs
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Jobs_Data/SDS_Jobs_7.243/CIVES NEW ENGLAND/50_Binney_Job.7z" binney.7z
/usr/local/bin/7zz x -y -obinney binney.7z > /dev/null
bash $W/conv.sh v54 $W/jobs/binney/50_Binney_Job noverify
cd $W
date -u +%FT%TZ > DONE
aws s3 cp DONE $R/DONE
aws s3 cp $W/drive.log $R/drive.log
