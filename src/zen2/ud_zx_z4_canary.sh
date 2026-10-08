#!/bin/bash
# Zentitude-data-4 extraction fleet box (Amazon Linux 2023, i4i with NVMe instance store).
# Restart loop: the worker is re-fetched from S3 each round; only /opt/zx/DONE (all jobs have results, no hold flag)
# ends the loop and shuts the box down (shutdown behaviour = terminate).
exec > /var/log/zx-boot.log 2>&1
set -x
ROOT=cad-disk-extract/zentitude-data-4
dnf install -y python3-pip mdadm xz tar > /dev/null 2>&1
pip3 install -q -U boto3
mkdir -p /scratch /opt/zx
DEVS=$(lsblk -dpno NAME,MODEL | grep -i 'Instance Storage' | awk '{print $1}' | xargs)
N=$(echo $DEVS | wc -w)
if [ "$N" -gt 1 ]; then mdadm --create /dev/md0 --level=0 --raid-devices=$N $DEVS --run && mkfs.xfs -f /dev/md0 && mount /dev/md0 /scratch
elif [ "$N" -eq 1 ]; then mkfs.xfs -f $DEVS && mount $DEVS /scratch; fi
( curl -sfL https://www.7-zip.org/a/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz || curl -sfL https://github.com/ip7z/7zip/releases/download/24.08/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz ) \
  && tar xJf /tmp/7z.tar.xz -C /usr/local/bin 7zz && chmod +x /usr/local/bin/7zz
echo "$(date -u +%FT%TZ) $(hostname) ready: $(/usr/local/bin/7zz | sed -n 2p | cut -c1-40) scratch=$(df -h /scratch | tail -1 | awk '{print $2}') cpus=$(nproc)" > /opt/zx/boot.txt
aws s3 cp --quiet /opt/zx/boot.txt s3://annotationprod/$ROOT/_state/boot/$(hostname).txt
while true; do
  aws s3 cp --quiet s3://annotationprod/$ROOT/_control/zx_worker.py /opt/zx/zx_worker.py
  ORDER=$(aws s3 cp --quiet s3://annotationprod/$ROOT/_control/order_$(hostname) - 2>/dev/null || true)
  ZX_ROOT=$ROOT ZX_SRC_STRIP=Zentitude-data-4/ ZX_SCRATCH=/scratch ZX_SLOTS=$(( $(nproc) / 5 )) ZX_UP_THREADS=192 ZX_ORDER=asc \
    python3 /opt/zx/zx_worker.py >> /opt/zx/worker.out 2>&1
  aws s3 cp --quiet /opt/zx/worker.out s3://annotationprod/$ROOT/_state/logs/$(hostname).log
  [ -f /opt/zx/DONE ] && break
  sleep 30
done
shutdown -h now
