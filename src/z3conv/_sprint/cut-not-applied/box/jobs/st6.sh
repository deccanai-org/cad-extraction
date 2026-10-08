#!/bin/bash
cd /work/agentwork/cut-not-applied; echo "kitnp8 corpus $(ls convall/kitnp8/*/conv.json 2>/dev/null | wc -l)/106"; for d in pipes5/*/* pipes4/*/* ifconly/*/*; do [ -f $d/pipe.json ] && echo "done $d" || echo "run  $d $(ls $d | tr '\n' ' ' | cut -c1-80)"; done; ls renders/p13* 2>/dev/null; tail -3 logs/rnd.log logs/tr13.log 2>/dev/null; uptime
