#!/bin/bash
echo "== partial"; systemctl is-active z3pkgp-loop; grep -E "CANARY|DELTA|ROUND|Traceback|rc=" /opt/pkgpartial/loop.log | tail -n 6 | cut -c1-400; tail -n 2 /opt/pkgpartial/loop.log | cut -c1-250; ls /opt/pkgpartial/canary_* 2>/dev/null
echo "== perfect"; systemctl is-active z3pkgperf-loop; grep -E "DELTA|ROUND|Traceback|rc=" /opt/pkgperf/loop.log | tail -n 5 | cut -c1-400
echo "== coord"; uptime; free -g | sed -n 2p; df -h / | tail -1
