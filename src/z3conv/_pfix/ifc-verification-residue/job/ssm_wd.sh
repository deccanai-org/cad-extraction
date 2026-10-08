#!/bin/bash
W=/work/agentwork/ifc-verification-residue
cat > $W/job/wd.sh <<'EOS'
#!/bin/bash
# external memory watchdog for MY processes only (cmdline contains ifc-verification-residue): kill any > LIM kB RSS
LIM=${LIM:-41943040}
while true; do
  for p in $(pgrep -f "ifc-verification-residue/(job|w|diag|in)/"); do
    r=$(awk '/VmRSS/{print $2}' /proc/$p/status 2>/dev/null)
    if [ -n "$r" ] && [ "$r" -gt "$LIM" ]; then
      echo "$(date -u +%FT%TZ) kill $p rss=${r}kB $(tr '\0' ' ' < /proc/$p/cmdline | cut -c1-200)" >> /work/agentwork/ifc-verification-residue/wd.log
      kill -9 $p
    fi
  done
  sleep 2
done
EOS
chmod +x $W/job/wd.sh
pkill -f "ifc-verification-residue/job/wd.sh" 2>/dev/null
setsid nohup bash $W/job/wd.sh > /dev/null 2>&1 < /dev/null &
sleep 1; pgrep -af "wd.sh" | cut -c1-100
