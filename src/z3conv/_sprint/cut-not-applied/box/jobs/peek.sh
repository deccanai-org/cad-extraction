#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
for d in 748b957ceaceeb17 9cf26a05e061dcba; do
  for f in reports/$d/part_list.xsr reports/$d/KSS_part_list.xls; do
    [ -f "$f" ] || continue
    echo "=== $f"; head -c 700 "$f" | tr -d '\r' | iconv -f latin1 -t utf-8 | head -8; echo ...; grep -a "PD40\|D21\|PL65\*65" "$f" | head -5; grep -a -i "total" "$f" | tail -2
  done
done
ls -la --time-style=long-iso reports/748b957ceaceeb17/ | head -30
