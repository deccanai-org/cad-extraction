W=/work/agentwork/sds2-pieces-not-built
uptime
ps -eo pid,etimes,pcpu,rss,args | grep "sds2-pieces-not-built/trees" | grep -v grep | awk '{printf "%s %ss %s%% %dMB ", $1, $2, $3, $4/1024; for(i=5;i<=NF;i++) if ($i ~ /jobs\//) print $i}' | sed 's#/work/agentwork/sds2-pieces-not-built/##'
ps -eo pid,args | grep "sds2_to_step" | grep "sds2-pieces-not-built" | grep -o "trees/[a-z0-9]*" | sort | uniq -c
