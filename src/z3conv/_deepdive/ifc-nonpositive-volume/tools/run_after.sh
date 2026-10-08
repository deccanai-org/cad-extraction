#!/bin/bash
# after-fix check of one case dir: grader step_check + per-root OCC volumes of split2.stp
PY=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python; CHK=/Users/dhiren/Downloads/Deccan/z3conv/grade/step_check.py
T=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/tools
d=$1
export PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/mplcfg
[ -f $d/chk_split2.json ] || $PY $CHK $d/split2.stp $d/chk_split2.json --png $d/render_split2.png > /dev/null 2>&1
[ -f $d/chk_out.json ] || $PY $CHK $d/out.stp $d/chk_out.json --png $d/render_out.png > /dev/null 2>&1
[ -f $d/occ_roots.jsonl ] || $PY $T/occ_roots.py $d/out.stp $d/occ_roots.jsonl
$PY $T/occ_roots.py $d/split2.stp $d/occ_roots_split2.jsonl
echo done $d
