#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
/opt/conv/env/bin/python tools/fetch_reports.py
du -sh reports; ls reports | wc -l
for f in reports/0632e878d57c36f0/KSS_part_list.xls reports/6f0dcc7daa096f45/part_list.xsr reports/172ffb7a9ab8a81d/KSS_part_list.rpt reports/863be0aa5b95f0f1/part_list.xsr; do echo "=== $f"; head -c 1500 "$f" | tr -d '\r' | iconv -f latin1 -t utf-8 | head -25; done
