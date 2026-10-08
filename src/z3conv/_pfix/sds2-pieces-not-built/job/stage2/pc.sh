W=/work/agentwork/sds2-pieces-not-built
uptime; free -g | awk 'NR==2{print "avail", $7}'
pgrep -af "sds2-pieces-not-built" | grep -v pgrep | grep sds2_to_step | cut -c1-200
for d in $W/ab/*/*/; do echo "$(basename $(dirname $d))/$(basename $d) $(cat $d/rc.txt 2>/dev/null || echo RUNNING)"; done
tail -3 $W/out/coord_ab2.log
