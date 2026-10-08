W=/work/agentwork/sds2-pieces-not-built
for i in $(seq 1 50); do pgrep -f project_all.py >/dev/null || break; sleep 10; done
pgrep -f project_all.py && echo STILL || echo FINISHED; wc -l < $W/out/proj.log; grep -v " ok\| cached" $W/out/proj.log | head
