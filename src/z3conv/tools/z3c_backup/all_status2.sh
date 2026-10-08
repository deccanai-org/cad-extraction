#!/bin/bash
echo "services: partial3 $(systemctl is-active z3pkgp-loop) partial4 $(systemctl is-active z3pkgp-loop4) perfect $(systemctl is-active z3pkgperf-loop)"
L=/opt/pkgpartial/loop.log; S=$(grep -n "04:45:22 DELTA" $L | tail -1 | cut -d: -f1); tail -n +${S:-1} $L > /tmp/p3.log
echo "data-3 partial since 04:45Z: ok $(grep -c ' ok ' /tmp/p3.log) fail $(grep -c ' fail ' /tmp/p3.log) copied $(grep -o 'copied [0-9]*' /tmp/p3.log | awk '{s+=$2} END{print s+0}')"
grep " fail " /tmp/p3.log | tail -n 3 | cut -c1-300; grep -E "ROUND|Traceback" /tmp/p3.log | tail -2 | cut -c1-300
echo "data-4 partial: ok $(grep -c ' ok ' /opt/pkgpartial4/loop.log) fail $(grep -c ' fail ' /opt/pkgpartial4/loop.log) copied $(grep -o 'copied [0-9]*' /opt/pkgpartial4/loop.log | awk '{s+=$2} END{print s+0}')"
grep " fail " /opt/pkgpartial4/loop.log | tail -n 3 | cut -c1-300; grep -E "ROUND|Traceback" /opt/pkgpartial4/loop.log | tail -2 | cut -c1-300
grep -E "DELTA|ROUND" /opt/pkgperf/loop.log | tail -n 2 | cut -c1-300
/opt/conv/env/bin/python - <<'PY'
import boto3
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'; P = 'cad-disk-extract/dataset/packages/3d_partial/'
n = b = 0; pids = set()
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P):
    for o in pg.get('Contents') or []:
        n += 1; b += o['Size']; k = o['Key'][len(P):]
        if k.endswith('/project.json') and k.count('/') == 1: pids.add(k.split('/')[0])
print('partial folder: objects', n, 'TB', round(b / 1e12, 3), 'finished projects (project.json)', len(pids), 'd3', sum(1 for p in pids if p.startswith('Zenitude-data-3')), 'd4', sum(1 for p in pids if p.startswith('Zentitude-data-4')))
PY
echo "coord $(uptime | sed 's/.*load/load/') mem $(free -g | awk '/Mem/{print $3}')G"
