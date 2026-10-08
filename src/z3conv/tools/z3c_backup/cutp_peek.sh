T=/opt/conv/scratch_v616
ls $T/src 2>/dev/null | head; for d in $T/out/*/*; do echo "$d $(tail -c 120 $d/log.txt 2>/dev/null | tr '\n' ' ') $(ls $d | tr '\n' ' ')"; done 2>/dev/null | cut -c1-300
uptime
