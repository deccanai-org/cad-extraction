#!/bin/bash
# writer_ab.sh CASE_DIR SRC_IFC : convert the source with the kit's ifc2step5.py (A) and the patched copy (B), same
# flags as the fleet (--mode hybrid --prec 2), then grade both with the kit's step_check.py
export PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/mplcfg
B=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume
PY=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python
CHK=/Users/dhiren/Downloads/Deccan/z3conv/grade/step_check.py
d=$1; src=$2
$PY /Users/dhiren/Downloads/Deccan/z3conv/ifc/ifc2step5.py $src $d/wA.stp --mode hybrid --prec 2 --threads 2 > $d/wA.stats 2> $d/wA.log
$PY $B/patch/ifc2step5.py $src $d/wB.stp --mode hybrid --prec 2 --threads 2 > $d/wB.stats 2> $d/wB.log
$PY $CHK $d/wA.stp $d/chk_wA.json --png $d/render_wA.png > /dev/null 2>&1
$PY $CHK $d/wB.stp $d/chk_wB.json --png $d/render_wB.png > /dev/null 2>&1
$PY $B/tools/occ_roots.py $d/wA.stp $d/occ_wA.jsonl
$PY $B/tools/occ_roots.py $d/wB.stp $d/occ_wB.jsonl
python3 - <<PY
import json
k=('solids','valid','invalid','nonpos_vol','render_ink','transferred','products')
a=json.load(open('$d/chk_wA.json')); b=json.load(open('$d/chk_wB.json'))
sa=json.loads(open('$d/wA.stats').read().strip().splitlines()[-1]); sb=json.loads(open('$d/wB.stats').read().strip().splitlines()[-1])
print('$d A', {x:a.get(x) for x in k}, 'sec', sa.get('total_sec'), 'bytes', sa.get('out_bytes'))
print('$d B', {x:b.get(x) for x in k}, 'sec', sb.get('total_sec'), 'bytes', sb.get('out_bytes'), sb.get('lump_split'))
PY
