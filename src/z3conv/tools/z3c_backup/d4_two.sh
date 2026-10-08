#!/bin/bash
cd /opt/pkgd4/logs
for f in pkg-0891d38df6ed0e28-2b3d4dd852.log pkg-c135774e1ae7186e-195604d147.log; do
  echo "RESULT == $f $(wc -c < $f) bytes, $(grep -c NoSuchKey $f) NoSuchKey"; head -c 700 $f; echo; echo ...; grep -n "Traceback" -A3 $f | head -12; grep -o '"project_id": "[^"]*"' $f | head -1
done
ls /opt/pkgd4/jobs | head -3
PY=/opt/conv/env/bin/python
