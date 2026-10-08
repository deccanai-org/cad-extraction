#!/bin/bash
# EC2 user-data: Zentitude-data-4 Tekla DB1 -> STEP worker box (AL2023 or Ubuntu x86_64, instance role cad-disk-extract-ec2,
# launch with --instance-initiated-shutdown-behavior terminate). Works in ap-south-1 and ap-south-2 (S3 is in ap-south-1).
# Mounts NVMe instance store (if any) at /scratch; runs the kit's run.sh until every job has a result, then powers off.
exec > /var/log/conv-boot.log 2>&1
set -x
PIPE=db1
export AWS_DEFAULT_REGION=ap-south-1
ST=s3://annotationprod/cad-disk-extract/zentitude-data-4/_state/conv/$PIPE
if ! command -v aws > /dev/null; then
  (command -v snap && snap install aws-cli --classic) || (apt-get update -y && apt-get install -y awscli) || true
  export PATH=$PATH:/snap/bin
fi
command -v dnf > /dev/null && dnf install -y -q tar gzip xz mdadm unzip > /dev/null 2>&1
command -v apt-get > /dev/null && apt-get install -y -q mdadm xfsprogs unzip > /dev/null 2>&1
mkdir -p /scratch
DEVS=$(lsblk -dpno NAME,MODEL | grep -i 'Instance Storage' | awk '{print $1}' | xargs)
N=$(echo $DEVS | wc -w)
if [ "$N" -gt 1 ]; then mdadm --create /dev/md0 --level=0 --raid-devices=$N $DEVS --run && mkfs.xfs -f /dev/md0 && mount /dev/md0 /scratch
elif [ "$N" -eq 1 ]; then mkfs.xfs -f $DEVS && mount $DEVS /scratch; fi
echo "$(date -u +%FT%TZ) $(hostname) boot cpus=$(nproc) mem=$(free -g | awk '/Mem/{print $2}')G scratch=$(df -h /scratch | tail -1 | awk '{print $2}')" | aws s3 cp - $ST/boot/$(hostname).txt
for i in 1 2 3 4 5; do
  aws s3 cp s3://annotationprod/cad-disk-extract/zentitude-data-4/_control/conv/$PIPE/run.sh /opt/run-$PIPE.sh && break; sleep 20
done
bash /opt/run-$PIPE.sh
rc=$?
aws s3 cp /opt/conv/worker-$PIPE.log $ST/logs/$(hostname).final.log || true
echo "$(date -u +%FT%TZ) $(hostname) run.sh rc=$rc" | aws s3 cp - $ST/boot/$(hostname).done.txt
[ -f /opt/conv/DONE.$PIPE ] && shutdown -h now
