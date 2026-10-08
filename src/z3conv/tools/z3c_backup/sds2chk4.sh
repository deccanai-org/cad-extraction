for i in $(seq 1 20); do [ -f /opt/conv/sds2-v5.5.7/.zip_sha256 ] && break; sleep 15; done
cat /opt/conv/sds2-v5.5.7/.zip_sha256 2>/dev/null; echo
grep -a "sds2 worker code" /opt/conv/worker-sds2.log | tail -n 1 | cut -c1-120; grep -a -i "traceback" /opt/conv/worker-sds2.log | tail -n 2
