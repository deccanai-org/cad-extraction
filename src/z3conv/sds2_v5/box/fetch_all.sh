#!/bin/bash
mkdir -p /data/jobs; cd /data/jobs
for id in $(cat /opt/v5dev/tests.txt); do
  /opt/conv/sds2env/bin/python /opt/v5dev/getjob.py $id /data/jobs >> /data/jobs/dirs.txt 2>> /data/jobs/fetch.err
done
echo FETCHED >> /data/jobs/fetch.err
