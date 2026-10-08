#!/bin/bash
cd /data/s3d/out/ifc
: > /data/s3d/logs/ifc_validate.txt
for f in $(cat /data/s3d/tmp/val_list.txt); do
  echo "== $f $(stat -c %s $f)" >> /data/s3d/logs/ifc_validate.txt
  timeout 3000 $PY -m ifcopenshell.validate "$f" 2>&1 | tail -3 >> /data/s3d/logs/ifc_validate.txt
done
echo DONE >> /data/s3d/logs/ifc_validate.txt
