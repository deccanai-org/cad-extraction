#!/bin/bash
# Zenitude-data-2 S3D restore box (RHEL 8.10 + SQL Server 2022 Standard, licence-included AMI).
# Boot: SSM agent, AWS CLI, 2 TB data volume on /data, SQL Server bound to localhost with a random SA password
# (kept only in /root/.mssql_sa, never logged), then pull the S3D backup files from the source bucket.
# Progress markers go to s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/.
exec > /var/log/zen2-boot.log 2>&1
set -x
ST=s3://annotationprod/cad-disk-extract/zenitude-data-2/_state
SRC="s3://bim-proprietary-data/Zenitude-data-2/PLC 17072025"
mark() { echo "$(date -u +%FT%TZ) $*" >> /var/log/zen2-marks.log; aws s3 cp --region ap-south-1 --quiet /var/log/zen2-marks.log $ST/boot_marks.log || true; }

# SSM agent (AWS SQL AMIs usually ship it; install if missing)
systemctl is-active --quiet amazon-ssm-agent || dnf install -y https://s3.ap-south-1.amazonaws.com/amazon-ssm-ap-south-1/latest/linux_amd64/amazon-ssm-agent.rpm
systemctl enable --now amazon-ssm-agent

# AWS CLI v2
if ! command -v aws >/dev/null; then
  dnf install -y unzip
  curl -s https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscli.zip && cd /tmp && unzip -q awscli.zip && ./aws/install
  export PATH=/usr/local/bin:$PATH
fi
aws configure set default.s3.max_concurrent_requests 64
aws configure set default.s3.multipart_chunksize 64MB
mark "boot: ssm+cli ready on $(hostname) $(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null)"

# 2 TB data volume (the only non-root EBS disk) -> /data
DEV=$(lsblk -dpno NAME,SIZE,TYPE | awk '$3=="disk" && $2 ~ /T$/ {print $1}' | head -1)
if [ -n "$DEV" ] && ! mountpoint -q /data; then
  mkfs.xfs -f "$DEV" && mkdir -p /data && mount "$DEV" /data
  echo "$DEV /data xfs defaults,nofail 0 2" >> /etc/fstab
fi
mkdir -p /data/in /data/mssql /data/work
chown -R mssql:mssql /data/mssql 2>/dev/null || true
mark "data volume: $(df -h /data | tail -1)"

# SQL Server: localhost only, random SA password (never printed), memory cap
set +x   # nothing below may echo the password into the boot log
if [ ! -f /root/.mssql_sa ]; then
  umask 077; head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 28 > /root/.mssql_sa; echo -n 'Aa1!' >> /root/.mssql_sa
fi
systemctl stop mssql-server || true
MSSQL_SA_PASSWORD="$(cat /root/.mssql_sa)" /opt/mssql/bin/mssql-conf -n set-sa-password
/opt/mssql/bin/mssql-conf set network.ipaddress 127.0.0.1
/opt/mssql/bin/mssql-conf set memory.memorylimitmb 110000
/opt/mssql/bin/mssql-conf set filelocation.defaultdatadir /data/mssql
/opt/mssql/bin/mssql-conf set filelocation.defaultlogdir /data/mssql
systemctl enable --now mssql-server
sleep 15
SQLCMD=$(ls /opt/mssql-tools18/bin/sqlcmd /opt/mssql-tools/bin/sqlcmd 2>/dev/null | head -1)
VER=$($SQLCMD -C -S 127.0.0.1 -U sa -P "$(cat /root/.mssql_sa)" -h -1 -Q "SET NOCOUNT ON; SELECT @@VERSION" 2>&1 | head -1)
mark "sql: ${VER:0:120} (sqlcmd=$SQLCMD)"
set -x

# Pull the S3D backup set (small files first; .7z copies are not needed)
cd /data/in
for f in PLC.bcf PLCBackup.log PLCRestore.log MLNG@1_SDB_SiteBackup.dat PLC_CatalogBackup.dat; do
  aws s3 cp --region ap-south-1 --only-show-errors "$SRC/$f" "/data/in/$f" && mark "got $f" || mark "FAILED to get $f"
done
T0=$(date +%s)
aws s3 cp --region ap-south-1 --only-show-errors "$SRC/PLC_Model_Backup.dat" /data/in/PLC_Model_Backup.dat \
  && mark "got PLC_Model_Backup.dat $(stat -c %s /data/in/PLC_Model_Backup.dat) B in $(( $(date +%s)-T0 )) s" \
  || mark "FAILED to get PLC_Model_Backup.dat"
chown -R mssql:mssql /data/in
mark "boot done"
aws s3 cp --region ap-south-1 --quiet /var/log/zen2-boot.log $ST/boot.log || true
