W=/work/agentwork/sds2-pieces-not-built
ls $W/out | head -50
wc -l $W/out/ab2_jobs.txt $W/out/ab2_queue.txt 2>/dev/null
for d in $W/ab/*/*/; do echo "$(basename $(dirname $d))/$(basename $d) $(cat $d/rc.txt 2>/dev/null || echo RUNNING)"; done
ls $W/out/AB*_DONE 2>/dev/null
pgrep -af "stage/ab" | head
