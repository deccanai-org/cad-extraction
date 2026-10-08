grep -a "1[67]:[0-9][0-9]:" /opt/conv/worker-sds2.log | grep -av " ok \| fail " | tail -n 15 | cut -c1-220
echo ---; grep -a "1[67]:[0-9][0-9]:" /opt/conv/worker-sds2.log | grep -ac " ok \| fail "
cat /proc/pressure/memory | head -1
