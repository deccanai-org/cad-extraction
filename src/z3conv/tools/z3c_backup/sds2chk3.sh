ls -d /opt/conv/sds2-v5.5.7 && cat /opt/conv/sds2-v5.5.7/.zip_sha256; echo
grep -a "05:[0-9]\|0[6-8]:" /opt/conv/worker-sds2.log | grep -a "sds2 worker code\|Traceback\|Error" | tail -n 4 | cut -c1-200
