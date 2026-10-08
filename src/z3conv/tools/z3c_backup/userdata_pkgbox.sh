#!/bin/bash
# EC2 user-data: PARTIAL-TIER PACKAGING BOX (owner 10-06). Mounts NVMe at /opt/pkgphelper/work, installs boto3, pulls the packager kit,
# runs package jobs from the coordinator's partial job lists (data-3 + data-4), 16 at a time, and powers off (terminate) when 3
# consecutive passes find nothing left. Locks are released on SIGTERM.
exec > /var/log/pkgbox.log 2>&1
set -x
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/pkgphelper; mkdir -p $D/kit $D/work
DEVS=$(lsblk -dpno NAME,MODEL | grep -i 'Instance Storage' | awk '{print $1}' | xargs); N=$(echo $DEVS | wc -w)
if [ "$N" -gt 1 ]; then mdadm --create /dev/md0 --level=0 --raid-devices=$N $DEVS --run && mkfs.xfs -f /dev/md0 && mount /dev/md0 $D/work
elif [ "$N" -eq 1 ]; then mkfs.xfs -f $DEVS && mount $DEVS $D/work; fi
dnf install -y -q python3-pip mdadm > /dev/null 2>&1; python3 -m pip install -q boto3 > /dev/null 2>&1
for f in pkgcore.py pkg.py adapter_zen3.py adapter_zen4.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/$f $D/kit/$f; done
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/pkgbox_helper.py $D/helper.py
cd $D/kit
PKG_TIER=partial PKG_ALLOW_WRITE=1 PKG_PARTIAL_REQUIRE_CODE='{"db1": "z3-db1-2026-10-01v"}' \
PKG_D12MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz \
PKGH_PROCS=16 PKGH_MAXSZ=1e15 PKGH_MINMEM=40 PKGH_ADAPTERS=zen3,zen4 python3 $D/helper.py >> $D/helper.log 2>&1
aws s3 cp --quiet $D/helper.log s3://bim-proprietary-data/cad-disk-extract/_state/packaging_partial/pkgbox_logs/$(hostname).log || true
shutdown -h now
