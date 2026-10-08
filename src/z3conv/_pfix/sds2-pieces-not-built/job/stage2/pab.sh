W=/work/agentwork/sds2-pieces-not-built
uptime; free -g | awk 'NR==2{print "avail", $7}'
cat $W/out/ab553_dirs.txt | tr '\n' ' '; echo
tail -3 $W/out/ab553_fetch.err
for d in $W/ab553/*/*/; do echo "$(basename $(dirname $d))/$(basename $d) $(cat $d/rc.txt 2>/dev/null || echo RUNNING)"; done
