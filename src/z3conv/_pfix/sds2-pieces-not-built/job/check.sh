ps -eo pid,etimes,pcpu,rss,args | grep -E "diag_ref|run_diag" | grep -v grep | cut -c1-180
ls -la /work/agentwork/sds2-pieces-not-built/out/diag_ref/ 2>/dev/null
tail -3 /work/agentwork/sds2-pieces-not-built/out_diag_ref.log 2>/dev/null
