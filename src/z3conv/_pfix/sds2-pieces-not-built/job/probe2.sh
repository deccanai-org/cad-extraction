cd /work/agentwork/sds2-pieces-not-built && ls -la && find . -maxdepth 3 -newer /etc/hostname -type f | head -50; du -sh . 2>/dev/null
for f in *.sh *.log *.txt; do [ -f "$f" ] && { echo "=== $f"; head -c 3000 "$f"; echo; }; done 2>/dev/null | head -200
ps -eo pid,etimes,pcpu,rss,args | grep -i "pieces-not-built" | grep -v grep | cut -c1-200
