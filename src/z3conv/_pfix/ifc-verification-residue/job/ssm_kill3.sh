#!/bin/bash
for p in $(pgrep -f "probe_iter.py"); do ps -o pid,rss,etimes,pcpu,args -p $p | cut -c1-120; R=$(ps -o rss= -p $p); if [ "${R:-0}" -gt 20000000 ]; then kill -9 $p; echo "killed $p rss ${R}kB"; fi; done
sleep 1; pgrep -af probe_iter.py | cut -c1-100; free -g | head -2
