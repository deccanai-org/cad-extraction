cat > /data/work/model_pull_restore.sh <<'__EOF__'
#!/bin/bash
ST=s3://annotationprod/cad-disk-extract/zenitude-data-2/_state
T0=$(date +%s)
aws configure set default.s3.max_concurrent_requests 64; aws configure set default.s3.multipart_chunksize 128MB
aws s3 cp --region ap-south-1 --only-show-errors "s3://annotationprod/cad-disk-extract/zenitude-data-2/source/PLC 17072025/PLC_Model_Backup.dat" /data/in/PLC_Model_Backup.dat
echo "$(date -u +%FT%TZ) model pulled rc=$? size=$(stat -c %s /data/in/PLC_Model_Backup.dat) in $(( $(date +%s)-T0 ))s" >> /var/log/zen2-marks.log
chown mssql:mssql /data/in/PLC_Model_Backup.dat
aws s3 cp --quiet /var/log/zen2-marks.log $ST/boot_marks.log
/data/work/restore_s3d.sh > /data/work/restore_run2.out 2>&1
echo "$(date -u +%FT%TZ) model restore script finished" >> /var/log/zen2-marks.log
aws s3 cp --quiet /var/log/zen2-marks.log $ST/boot_marks.log
__EOF__
chmod +x /data/work/model_pull_restore.sh
nohup /data/work/model_pull_restore.sh > /data/work/model_pull_restore.out 2>&1 &
sleep 20; ls -la /data/in/ | tail -3; df -h /data | tail -1
