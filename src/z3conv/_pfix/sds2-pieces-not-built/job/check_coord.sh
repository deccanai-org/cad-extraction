W=/work/agentwork/sds2-pieces-not-built
cat $W/out/envcheck.log 2>/dev/null; cat $W/out/coord_dirs.txt 2>/dev/null; tail -3 $W/out/coord_ab.log; tail -2 $W/out/fetch.err 2>/dev/null
for d in $W/ab/*/*/; do [ -f $d/rc.txt ] && echo "$(basename $(dirname $d))/$(basename $d) $(cat $d/rc.txt)"; done
uptime; free -g | awk 'NR==2{print "avail", $7}'
