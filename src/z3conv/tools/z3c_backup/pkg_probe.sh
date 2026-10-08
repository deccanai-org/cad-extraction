#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
uptime; free -g | head -2; df -h /scratch 2>/dev/null | tail -1; nproc
for p in /opt/conv/env/bin/python /opt/conv/verifyenv/bin/python /usr/bin/python3; do [ -x "$p" ] && echo "$p $($p -c 'import sys,boto3;print(sys.version.split()[0], boto3.__version__)' 2>&1 | tail -1)"; done
ps aux --sort=-%cpu | head -5 | cut -c1-150
