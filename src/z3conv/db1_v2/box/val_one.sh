#!/bin/bash
# val_one.sh TAG DB1_KEY IFC_KEY  -> bim _work/db1_v2/val/<run>/<TAG>/
TAG=$1; DB1=$2; IFC=$3; RUN=${RUN:-r1}
if [ "$DB1" = "X" ] || [ -z "$DB1" ]; then
  [ -f /opt/v2/val_keys.json ] || aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/_box/val_keys.json /opt/v2/val_keys.json
  DB1=$(python3 -c "import json,sys; print(json.load(open('/opt/v2/val_keys.json'))[sys.argv[1]][0])" "$TAG")
  IFC=$(python3 -c "import json,sys; print(json.load(open('/opt/v2/val_keys.json'))[sys.argv[1]][1])" "$TAG")
fi
OUT=s3://bim-proprietary-data/cad-disk-extract/_work/db1_v2/val/$RUN/$TAG
D=/opt/v2/val/$RUN/$TAG; mkdir -p $D; cd $D
C=/opt/v2/code; PY=/opt/conv/env/bin/python; P84=/opt/conv/ifc84/bin/python
[ -f in.db1 ] || aws s3 cp --quiet "s3://bim-proprietary-data/$DB1" in.db1
[ -f in.ifc ] || aws s3 cp --quiet "s3://bim-proprietary-data/$IFC" in.ifc
export DB1_BOLT_DEBUG=1
( time timeout 7200 $PY $C/run_conv.py in.db1 conv ) > conv.log 2>&1
timeout 3600 $PY $C/validate_bolts.py in.db1 in.ifc vb.json > vb.log 2>&1
timeout 3600 $PY $C/validate_place.py in.db1 in.ifc conv.json > vp.txt 2>&1
if [ -f conv.ifc ]; then
  ( time timeout 10800 $P84 $C/ifc2step5.py conv.ifc conv.stp --mode hybrid --prec 2 --threads 2 ) > step.log 2>&1
  [ -f conv.stp ] && timeout 7200 $PY $C/step_check.py conv.stp check.json --png render.png > check.log 2>&1
fi
for f in conv.json conv.log vb.json vb.log vp.txt step.log check.json check.log render.png conv.stp.stats.json; do [ -f $f ] && aws s3 cp --quiet $f $OUT/$f; done
rm -f in.ifc conv.stp
echo "$TAG done"
