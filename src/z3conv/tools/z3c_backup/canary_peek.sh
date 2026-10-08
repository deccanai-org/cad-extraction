for V in rc base; do [ -f /opt/conv/canary/$V/worker.log ] && { echo "== $V"; tail -n 6 /opt/conv/canary/$V/worker.log | cut -c1-200; }; done
