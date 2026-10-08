#!/bin/bash
# Zenitude-data-3 extraction box (AL2023, i4i NVMe). Output -> s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/
# Control (code, jobs, env, stop, hold, prior index) -> s3://annotationprod/cad-disk-extract/_control/move/z3/ (operator-writable).
exec > /var/log/zx-boot.log 2>&1
set -x
ROOT=cad-disk-extract/zenitude-data-3
K=s3://annotationprod/cad-disk-extract/_control/move/z3
O=s3://bim-proprietary-data/$ROOT
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
aws s3 cp --quiet /opt/zx/boot.txt $O/_state/boot/$(hostname).txt
until aws s3 ls $K/prior_sha64.bin > /dev/null 2>&1 && aws s3 ls $K/jobs.json > /dev/null 2>&1; do sleep 30; done
while true; do
  aws s3 cp --quiet $K/zx_worker.py /opt/zx/zx_worker.py
  ZX_DST=bim-proprietary-data ZX_ROOT=$ROOT ZX_SRC_BUCKET=bim-proprietary-data ZX_SRC_STRIP=Zenitude-data-3/ \
  ZX_CTL_BUCKET=annotationprod ZX_CTL_PREFIX=cad-disk-extract/_control/move/z3 \
  ZX_PRIOR_LABEL=prior ZX_PRIOR_INDEX=cad-disk-extract/_control/move/z3/prior_sha64.bin \
  ZX_SCRATCH=/scratch ZX_PROCS=$(( $(nproc) / 4 )) ZX_SLOTS=2 ZX_UP_THREADS=96 ZX_PROC_TAG=p \
    python3 /opt/zx/zx_worker.py >> /opt/zx/worker.out 2>&1
  aws s3 cp --quiet /opt/zx/worker.out $O/_state/logs/$(hostname).log
  [ -f /opt/zx/DONE ] && break
  sleep 30
done
shutdown -h now
