#!/bin/bash
# run_v.sh CASE_DIR TAG : grade <TAG>.stp with the kit step_check + per-root OCC volumes
PY=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python; CHK=/Users/dhiren/Downloads/Deccan/z3conv/grade/step_check.py
T=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/tools
export PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/mplcfg
d=$1; t=$2
$PY $CHK $d/$t.stp $d/chk_$t.json --png $d/render_$t.png > /dev/null 2>&1
$PY $T/occ_roots.py $d/$t.stp $d/occ_$t.jsonl
python3 -c "
import json; v=json.load(open('$d/chk_$t.json')); print('$d', '$t', {k:v.get(k) for k in ('solids','valid','invalid','nonpos_vol','render_ink')})"
