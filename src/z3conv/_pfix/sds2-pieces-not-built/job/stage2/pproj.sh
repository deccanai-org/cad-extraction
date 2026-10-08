W=/work/agentwork/sds2-pieces-not-built
wc -l < $W/out/proj.log; grep -c " ok" $W/out/proj.log; grep -v " ok\| cached" $W/out/proj.log | tail -5
uptime; df -h /work | tail -1
