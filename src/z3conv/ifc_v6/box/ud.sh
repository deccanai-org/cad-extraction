#!/bin/bash
# ifc2step6 test box (Mumbai). Self-terminates: hard cap 10 h (shutdown -h, instance-initiated-shutdown=terminate),
# idle watchdog: powers off when /opt/v6/alive is older than 90 min. Extend: touch /opt/v6/alive (or shutdown -c; shutdown -h +N).
exec > /var/log/v6-boot.log 2>&1
set -x
export AWS_DEFAULT_REGION=ap-south-1
shutdown -h +600
mkdir -p /opt/v6 && touch /opt/v6/alive
cat > /opt/v6/watchdog.sh <<'WD'
#!/bin/bash
while true; do
  sleep 300
  age=$(( $(date +%s) - $(stat -c %Y /opt/v6/alive) ))
  if [ $age -gt 5400 ]; then echo "$(date -u) idle ${age}s -> poweroff" >> /var/log/v6-watchdog.log; shutdown -h now; fi
done
WD
chmod +x /opt/v6/watchdog.sh; nohup setsid /opt/v6/watchdog.sh > /dev/null 2>&1 &
command -v dnf > /dev/null && dnf install -y -q tar gzip xz unzip htop > /dev/null 2>&1
mkdir -p /scratch
DEVS=$(lsblk -dpno NAME,MODEL | grep -i 'Instance Storage' | awk '{print $1}' | xargs)
[ -n "$DEVS" ] && mkfs.xfs -f $DEVS && mount $DEVS /scratch
mkdir -p /opt/v6/kit
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/ /opt/v6/kit/ --exclude '*' --include '*.py' --include '*.sh' --exclude '*/*'
bash /opt/v6/kit/setup.sh /opt/conv > /opt/v6/setup.log 2>&1
echo "setup rc=$?" >> /opt/v6/setup.log
touch /opt/v6/READY
