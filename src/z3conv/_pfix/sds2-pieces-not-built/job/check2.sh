W=/work/agentwork/sds2-pieces-not-built
ls $W/out/cls/*.json | wc -l; ps -eo pid,etimes,pcpu,rss,args | grep -E "classify_ref|fetch_one|fetch.py" | grep -v grep | cut -c1-150
uptime; free -g | head -2; df -h / | tail -1; du -sh $W/jobs | tail -1
