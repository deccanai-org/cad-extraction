#!/bin/bash
# Zenitude-data-2 file-extraction box (Ubuntu 22.04): 7-Zip, poppler, LibreDWG/ODA for DWG->DXF, Python tools.
# Jobs are driven over SSM; this script only prepares the machine. Marks -> zenitude-data-2/_state/files_boot.log
exec > /var/log/zen2-files-boot.log 2>&1
set -x
ST=s3://annotationprod/cad-disk-extract/zenitude-data-2/_state
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q p7zip-full p7zip-rar unzip poppler-utils python3-pip python3-venv jq xvfb libgl1 libxkbcommon-x11-0 libxcb-cursor0 parallel
apt-get install -y -q libredwg-tools || apt-get install -y -q libredwg-utils || true
curl -s https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscli.zip && cd /tmp && unzip -q awscli.zip && ./aws/install
aws configure set default.s3.max_concurrent_requests 64; aws configure set default.s3.multipart_chunksize 128MB
pip3 install -q olefile pypdf pdfplumber ezdxf boto3
# 1 TB work volume
DEV=$(lsblk -dpno NAME,SIZE,TYPE | awk '$3=="disk" && ($2 ~ /T$/ || $2+0 >= 900) {print $1}' | grep -v "$(findmnt -no SOURCE / | sed 's/p[0-9]*$//')" | head -1)
if [ -n "$DEV" ] && ! mountpoint -q /work; then mkfs.xfs -f "$DEV" 2>/dev/null || mkfs.ext4 -F "$DEV"; mkdir -p /work; mount "$DEV" /work; echo "$DEV /work auto defaults,nofail 0 2" >> /etc/fstab; fi
mkdir -p /work/in /work/out
echo "$(date -u +%FT%TZ) files box ready: $(7z | sed -n 2p) | dwg2dxf=$(command -v dwg2dxf) | $(df -h /work | tail -1)" > /var/log/zen2-files-marks.log
aws s3 cp --region ap-south-1 --quiet /var/log/zen2-files-marks.log $ST/files_boot.log
