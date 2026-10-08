#!/bin/bash
# cross-validation of the ifc_improver's ifc2step6 snapshot (tools/xval_v6/ifc2step6.py, md5 9d8ef8d9...) on the
# npv evidence cases: convert the source, grade with the kit step_check, per-root regression vs the kit v5 writer (wA)
PY=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python
T=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/tools
cd /Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/data
export PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/mplcfg
for d in "$@"; do
  f=$d/src.bin; [ -f $d/src.ifc ] && f=$d/src.ifc; [ -d $d/unz ] && f=$(ls -S $d/unz/* | head -1)
  if [ ! -f $d/wA.stp ]; then $PY /Users/dhiren/Downloads/Deccan/z3conv/ifc/ifc2step5.py $f $d/wA.stp --mode hybrid --prec 2 --threads 2 > $d/wA.stats 2> $d/wA.log; $T/run_v.sh $d wA > /dev/null; fi
  [ -f $d/v6.stp ] || $PY $T/xval_v6/ifc2step6.py $f $d/v6.stp --mode hybrid --prec 2 --threads 2 --verify-procs 2 > $d/v6.stats 2> $d/v6.log
  $T/run_v.sh $d v6
  python3 $T/regress.py wA:v6 $d | head -1
done
