#!/bin/bash
echo "== services: partial $(systemctl is-active z3pkgp-loop) perfect $(systemctl is-active z3pkgperf-loop)"
L=/opt/pkgpartial/loop.log; S=$(grep -n "04:45:22 DELTA" $L | tail -1 | cut -d: -f1); tail -n +${S:-1} $L > /tmp/pn.log
echo "partial since 04:45Z restart: ok $(grep -c ' ok ' /tmp/pn.log) fail $(grep -c ' fail ' /tmp/pn.log) | copied files $(grep -o 'copied [0-9]*' /tmp/pn.log | awk '{s+=$2} END{print s+0}')"
grep -E "DELTA|ROUND|Traceback" /tmp/pn.log | tail -n 4 | cut -c1-330; grep " fail " /tmp/pn.log | tail -n 3 | cut -c1-300
echo "partial packages on S3: $(aws s3 ls s3://bim-proprietary-data/cad-disk-extract/dataset/packages/3d_partial/ --region ap-south-1 | wc -l)"
grep -E "DELTA|ROUND" /opt/pkgperf/loop.log | tail -n 3 | cut -c1-300
echo "== coord $(uptime | sed 's/.*load/load/') | mem used $(free -g | awk '/Mem/{print $3}')G | disk $(df -h / | tail -1 | awk '{print $4}') free"
