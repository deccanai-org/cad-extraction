W=/work/agentwork/sds2-pieces-not-built
echo cls $(ls $W/out/cls/*.json | wc -l); ls $W/out/cls/BATCH_DONE 2>/dev/null
echo "procs: classify $(pgrep -f classify_ref.py | wc -l) convert $(pgrep -f 'trees/[abc]/decode/sds2_to_step' | wc -l) diag $(pgrep -f diag_pieces.py | wc -l)"
for d in $W/ab/*/*/; do [ -f $d/rc.txt ] && echo "$(basename $(dirname $d))/$(basename $d) $(cat $d/rc.txt)"; done
uptime; free -g | awk 'NR==2{print "avail", $7}'
