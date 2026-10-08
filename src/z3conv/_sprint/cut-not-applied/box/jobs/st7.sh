#!/bin/bash
cd /work/agentwork/cut-not-applied; echo "kitnp9 corpus $(ls convall/kitnp9/*/conv.json 2>/dev/null | wc -l)/106"; for d in pipes5/*/*; do [ -f $d/pipe.json ] && echo "done $d" || echo "run  $d"; done; uptime
