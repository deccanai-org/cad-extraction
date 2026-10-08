#!/bin/bash
# (owner-approved fleet management) A box that rebooted comes up idle: EC2 user-data runs on the first boot only. This installs the box's
# own user-data as a cloud-init per-boot script (so any later reboot resumes by itself) and, if no conversion worker is running now,
# starts it once (systemd unit; it powers the box off when every job has a result, exactly like the first boot).
TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/user-data > /opt/userdata-orig.sh || { echo "no user-data"; exit 1; }
cat > /opt/conv-perboot.sh <<'EOS'
#!/bin/bash
# resume after a reboot: the instance-store RAID may come back auto-assembled (or not at all) and unmounted -> stop it, rebuild scratch
if ! mountpoint -q /scratch; then for md in /dev/md*; do [ -b "$md" ] && mdadm --stop "$md" >/dev/null 2>&1; done; fi
exec /bin/bash /opt/userdata-orig.sh
EOS
chmod +x /opt/conv-perboot.sh; mkdir -p /var/lib/cloud/scripts/per-boot; ln -sf /opt/conv-perboot.sh /var/lib/cloud/scripts/per-boot/conv-resume.sh
up=$(cut -d. -f1 /proc/uptime); n=$(pgrep -fc 'kit/.*/worker.py|run-.*\.sh')
echo "uptime_s=$up workers=$n perboot=installed"
if [ "$n" -eq 0 ] && ! systemctl is-active -q conv-resume; then
  systemd-run --unit=conv-resume --collect /bin/bash /opt/conv-perboot.sh && echo "RESTARTED pipeline"
fi
