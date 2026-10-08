W=/work/agentwork/sds2-pieces-not-built
pgrep -af "sds2-pieces-not-built" | grep -v pgrep | cut -c1-250
echo; tail -5 $W/out/ab2.log; echo; cat $W/out/ab2_jobs.txt | xargs -n1 basename
