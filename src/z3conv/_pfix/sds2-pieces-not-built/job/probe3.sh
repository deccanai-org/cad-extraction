cd /work/agentwork/sds2-pieces-not-built && for f in logs/*.log; do echo "=== $f"; tail -c 1500 $f; echo; done; ls jobs | head -80; ls jobs | wc -l; du -sh jobs/* 2>/dev/null | sort -h | tail -30
