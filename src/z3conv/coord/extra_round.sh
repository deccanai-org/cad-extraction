#!/bin/bash
# copy operator-written documents from the control prefix into the state prefix (the operator SSO cannot write bim)
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
ST=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv
aws s3 cp --quiet $CTL/coord/classifier_calibration.json /work/index/classifier_calibration.json 2>/dev/null && \
  aws s3 cp --quiet /work/index/classifier_calibration.json $ST/classifier_calibration.json
# (phase 2) one index round per disk lane that has a job list (build_index.py with CONV_DISK; writes only that disk's conv2 state)
PY=/opt/z3c/venv/bin/python; K=/opt/z3c/kit
for d in $($PY $K/coord/build_index.py --list-disks 2>/dev/null); do
  CONV_DISK=$d INDEX_WORK=/work/index-$d $PY $K/coord/build_index.py >> /opt/z3c/index-$d.log 2>&1
  tail -1 /opt/z3c/index-$d.log | cut -c1-300
done
true
