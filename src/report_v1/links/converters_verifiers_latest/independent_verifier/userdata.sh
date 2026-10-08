#!/bin/bash
# EC2 user-data: Zenitude-data-3 conversion box for pipeline verify (AL2023 x86_64, role cad-disk-extract-ec2,
# --instance-initiated-shutdown-behavior terminate; ap-south-1 or ap-south-2, S3 is in ap-south-1).
# Mounts NVMe instance store (if any) at /scratch; runs the kit's run.sh until every job has a result, then powers off.
exec > /var/log/conv-boot.log 2>&1
set -x
PIPE=verify
export AWS_DEFAULT_REGION=ap-south-1
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv/$PIPE
ST=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/$PIPE
command -v dnf > /dev/null && dnf install -y -q tar gzip xz mdadm unzip > /dev/null 2>&1
mkdir -p /scratch
DEVS=$(lsblk -dpno NAME,MODEL | grep -i 'Instance Storage' | awk '{print $1}' | xargs)
N=$(echo $DEVS | wc -w)
if [ "$N" -gt 1 ]; then mdadm --create /dev/md0 --level=0 --raid-devices=$N $DEVS --run && mkfs.xfs -f /dev/md0 && mount /dev/md0 /scratch
elif [ "$N" -eq 1 ]; then mkfs.xfs -f $DEVS && mount $DEVS /scratch; fi
( curl -sfL https://www.7-zip.org/a/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz || curl -sfL https://github.com/ip7z/7zip/releases/download/24.08/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz ) \
  && tar xJf /tmp/7z.tar.xz -C /usr/local/bin 7zz && chmod +x /usr/local/bin/7zz
echo "$(date -u +%FT%TZ) $(hostname) boot cpus=$(nproc) mem=$(free -g | awk '/Mem/{print $2}')G scratch=$(df -h /scratch | tail -1 | awk '{print $2}') root=$(df -h / | tail -1 | awk '{print $2}')" | aws s3 cp - $ST/boot/$(hostname).txt
for i in 1 2 3 4 5; do
  aws s3 cp $CTL/run.sh /opt/run-$PIPE.sh && break; sleep 20
done
bash /opt/run-$PIPE.sh
rc=$?
aws s3 cp /opt/conv/worker-$PIPE.log $ST/boxlogs/$(hostname).final.log || true
echo "$(date -u +%FT%TZ) $(hostname) run.sh rc=$rc" | aws s3 cp - $ST/boot/$(hostname).done.txt
{ [ -f /opt/conv/DONE.$PIPE ] || [ -f /opt/conv/RELEASED.$PIPE ]; } && shutdown -h now
