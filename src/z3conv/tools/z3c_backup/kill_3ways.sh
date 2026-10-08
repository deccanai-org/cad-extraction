#!/bin/bash
# stop my own slow three-ways search (python reading stdin, started by rep_3ways.sh)
for p in $(pgrep -f "^/opt/report/venv/bin/python -$"); do
  if grep -q "three_ways" /proc/$p/cmdline 2>/dev/null || [ "$(ps -o etime= -p $p | tr -d ' ')" \> "00:00" ]; then
    tr '\0' ' ' < /proc/$p/cmdline; echo; kill $p && echo "killed $p"
  fi
done
