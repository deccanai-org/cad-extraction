#!/bin/bash
# autonomous regression driver for box 2: fetch, v4 + v5 conversions (memory gated), checks, upload, shut down
exec > /data/out/drive2.log 2>&1
set -x
mkdir -p /data/jobs /data/d2 /data/out; cd /data/jobs
for id in $(cat /opt/v5dev/tests2.txt); do /opt/conv/sds2env/bin/python /opt/v5dev/getjob.py $id /data/jobs >> /data/jobs/dirs.txt 2>> /data/jobs/fetch.err; done
cd /data/d2
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Projects_Data/MT15_061 (The Greenwood Middle School)/18.ABM/01) ABM_122115/GMS ABM  122115_JOB.zip" gms.zip && unzip -q -o gms.zip -d gms && mv "gms/GREENWOOD MIDDLE SCHOOL_JOB" gms/GREENWOOD_MIDDLE_SCHOOL_JOB
aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Jobs_Data/SDS_Jobs_7.243/CIVES NEW ENGLAND/50_Binney_Job.7z" binney.7z && 7za x -y -obinney binney.7z > 7z.log 2>&1 && rm -f binney.7z
echo /data/d2/binney/50_Binney_Job > /data/jobs/order.txt; echo /data/d2/gms/GREENWOOD_MIDDLE_SCHOOL_JOB >> /data/jobs/order.txt
for d in $(cat /data/jobs/dirs.txt); do echo "$(du -s "$d" | cut -f1) $d"; done | sort -rn | cut -d' ' -f2- >> /data/jobs/order.txt
aws s3 cp --quiet /data/jobs/order.txt s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress2/order.txt
# v5 first (that is what ships), then v4 for the before column
cat /data/jobs/order.txt | xargs -P 10 -I{} bash /opt/v5dev/run_one.sh v5 {}
cat /data/jobs/order.txt | xargs -P 10 -I{} bash /opt/v5dev/run_one.sh v4 {}
for V in v5 v4; do cat /data/jobs/order.txt | xargs -P 8 -I{} bash /opt/v5dev/check_one.sh $V {}; done
date -u +%FT%TZ > /data/out/DONE
aws s3 cp --quiet /data/out/drive2.log s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress2/drive2.log
aws s3 cp --quiet /data/out/DONE s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress2/DONE
shutdown -h now
