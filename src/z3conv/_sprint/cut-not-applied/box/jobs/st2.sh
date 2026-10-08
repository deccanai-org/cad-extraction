#!/bin/bash
cd /work/agentwork/cut-not-applied; tail -5 logs/tr13.log; for d in pipes3/*/*; do echo "$d $(ls $d | tr '\n' ' ' | cut -c1-150)"; done
echo "kitn $(ls convall/kitn/*/conv.json 2>/dev/null | wc -l) kitnp $(ls convall/kitnp/*/conv.json 2>/dev/null | wc -l) kitnp5 $(ls convall/kitnp5/*/conv.json 2>/dev/null | wc -l)"; ls res/convn_sum.txt 2>&1
tail -3 logs/f12.log logs/of2.log
uptime; free -g | head -2
