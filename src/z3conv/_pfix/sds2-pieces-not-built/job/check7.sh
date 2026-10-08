W=/work/agentwork/sds2-pieces-not-built
ps -eo pid,etimes,args | grep "sds2-pieces-not-built" | grep -E "sds2_to_step|probe_parse2|ab2|xargs" | grep -v "grep\|timeout" | cut -c1-170
tail -3 $W/out/ab2.log; cat $W/out/ab2_jobs.txt 2>/dev/null | wc -l; cat $W/out/v4_dirs.txt
