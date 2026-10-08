#!/bin/bash
# box 3: v5.1 on the data-4 test set + Binney + Greenwood + 2015.25 reference-model / empty jobs; checks; shut down
exec > /data/out/drive3.log 2>&1
set -x
mkdir -p /data/jobs /data/d2 /data/out; cd /data/jobs
for id in $(cat /opt/v5dev/tests2.txt); do /opt/conv/sds2env/bin/python /opt/v5dev/getjob.py $id /data/jobs >> /data/jobs/dirs.txt 2>> /data/jobs/fetch.err; done
cd /data/d2
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Projects_Data/MT15_061 (The Greenwood Middle School)/18.ABM/01) ABM_122115/GMS ABM  122115_JOB.zip" gms.zip && unzip -q -o gms.zip -d gms && mv "gms/GREENWOOD MIDDLE SCHOOL_JOB" gms/GREENWOOD_MIDDLE_SCHOOL_JOB
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Jobs_Data/SDS_Jobs_7.243/CIVES NEW ENGLAND/50_Binney_Job.7z" binney.7z && 7za x -y -obinney binney.7z > 7z.log 2>&1 && rm -f binney.7z
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Jobs_Data/SDS_Jobs_2015.25/jobs.7z" j2015.7z
for j in hyf pp3 uuii B GHTUG BHJ duct-l5 n2; do 7za x -y -oj2015 j2015.7z "$j/main/*" "$j/mem/*" "$j/subm/*" -r > /dev/null 2>&1; done; rm -f j2015.7z
echo /data/d2/binney/50_Binney_Job > /data/jobs/order.txt; echo /data/d2/gms/GREENWOOD_MIDDLE_SCHOOL_JOB >> /data/jobs/order.txt
for j in pp3 uuii B GHTUG hyf duct-l5 n2 BHJ; do [ -d /data/d2/j2015/$j ] && echo /data/d2/j2015/$j >> /data/jobs/order.txt; done
for d in $(cat /data/jobs/dirs.txt); do echo "$(du -s "$d" | cut -f1) $d"; done | sort -rn | cut -d' ' -f2- >> /data/jobs/order.txt
aws s3 cp --quiet /data/jobs/order.txt s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress3/order.txt
cat /data/jobs/order.txt | xargs -P 10 -I{} bash /opt/v5dev/run_one3.sh v5 {}
cat /data/jobs/order.txt | xargs -P 8 -I{} bash /opt/v5dev/check_one3.sh v5 {}
date -u +%FT%TZ > /data/out/DONE
aws s3 cp --quiet /data/out/drive3.log s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress3/drive3.log
aws s3 cp --quiet /data/out/DONE s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress3/DONE
shutdown -h now
