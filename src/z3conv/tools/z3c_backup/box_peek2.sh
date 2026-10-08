#!/bin/bash
uptime|sed 's/.*load/load/'; echo "db1 procs: $(pgrep -fc 'db1@')"; echo "ifc procs: $(pgrep -fc 'kit/ifc@')"; free -g|sed -n 2p; ls /scratch/conv/ 2>/dev/null; tail -n 3 /scratch/conv/db1@zentitude-data-4/worker.log 2>/dev/null | cut -c1-250; ls -t /var/log/z3* /opt/conv/*.log 2>/dev/null | head -3
