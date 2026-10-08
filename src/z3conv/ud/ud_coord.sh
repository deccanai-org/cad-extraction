#!/bin/bash
# Zenitude-data-3 conversion coordinator (AL2023, instance role cad-disk-extract-ec2, shutdown behaviour = terminate).
# Loops coord.sh from the control prefix (hot reload each round). Powers off only when coord.sh leaves /opt/z3c/DONE.
exec > /var/log/z3coord-boot.log 2>&1
set -x
export AWS_DEFAULT_REGION=ap-south-1
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
ST=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv
dnf install -y -q python3-pip tar gzip xz mdadm unzip > /dev/null 2>&1
mkdir -p /work /opt/z3c
DEVS=$(lsblk -dpno NAME,MODEL | grep -i 'Instance Storage' | awk '{print $1}' | xargs)
N=$(echo $DEVS | wc -w)
if [ "$N" -gt 1 ]; then mdadm --create /dev/md0 --level=0 --raid-devices=$N $DEVS --run && mkfs.xfs -f /dev/md0 && mount /dev/md0 /work
elif [ "$N" -eq 1 ]; then mkfs.xfs -f $DEVS && mount $DEVS /work; fi
python3 -m venv /opt/z3c/venv && /opt/z3c/venv/bin/pip install -q boto3 orjson numpy
echo "$(date -u +%FT%TZ) $(hostname) boot cpus=$(nproc) mem=$(free -g | awk '/Mem/{print $2}')G work=$(df -h /work | tail -1 | awk '{print $2}')" | aws s3 cp - $ST/coord/boot/$(hostname).txt
while true; do
  aws s3 cp --quiet $CTL/coord/coord.sh /opt/z3c/coord.sh
  bash /opt/z3c/coord.sh >> /opt/z3c/coord.log 2>&1
  aws s3 cp --quiet /opt/z3c/coord.log $ST/coord/logs/$(hostname).log
  [ -f /opt/z3c/DONE ] && break
  sleep 30
done
aws s3 cp --quiet /opt/z3c/coord.log $ST/coord/logs/$(hostname).final.log
shutdown -h now
