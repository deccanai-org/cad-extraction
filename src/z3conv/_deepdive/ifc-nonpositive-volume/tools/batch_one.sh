#!/bin/bash
# batch_one.sh <result json path> : repair + re-grade one npv model (read-only on S3, local scratch only)
#   download the graded STEP -> split_lumps_step.py -> step_check.py (same grader code, --parts) -> grade_join with the
#   source inventory the fleet stored (detail/<id>.src_parts.jsonl.gz) -> batch/<id>.json ; scratch files deleted
export AWS_PROFILE=bim PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/mplcfg
R=$1
B=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume
PY=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python
CHK=/Users/dhiren/Downloads/Deccan/z3conv/grade/step_check.py
JOIN=/Users/dhiren/Downloads/Deccan/z3conv/grade
id=$(basename $R .json)
out=$B/batch/$id.json
[ -f $out ] && exit 0
S=$B/scratch/$id; mkdir -p $S
IFS=$'\t' read STEPK DETK < <(python3 -c "
import json; r=json.load(open('$R'))
k=r.get('step_key') or r.get('out_key')
det=('cad-disk-extract/zenitude-data-3/_state/conv/grade/detail/'+r['id']) if r.get('reused') else ('cad-disk-extract/zenitude-data-3/_state/conv/ifc/detail/'+r['id'])
print(k+chr(9)+det)")
T0=$(date +%s)
aws s3 cp --quiet "s3://bim-proprietary-data/$STEPK" $S/in.stp || { echo "{\"id\":\"$id\",\"error\":\"download\"}" > $out; rm -rf $S; exit 0; }
aws s3 cp --quiet "s3://bim-proprietary-data/$DETK.src_parts.jsonl.gz" $S/src_parts.jsonl.gz 2>/dev/null
/usr/bin/time -l python3 $B/tools/split_lumps_step.py $S/in.stp $S/fix.stp > $S/split.json 2> $S/split.time
rm -f $S/in.stp
$PY $CHK $S/fix.stp $S/chk.json --parts $S/step_parts.jsonl.gz > /dev/null 2> $S/chk.log
if [ -s $S/src_parts.jsonl.gz ] && [ -s $S/step_parts.jsonl.gz ]; then
  (cd $JOIN && $PY -c "
import sys, json; sys.path.insert(0, '.'); import grade_join as g
r = g.join(g.load('$S/src_parts.jsonl.gz'), g.load('$S/step_parts.jsonl.gz')); json.dump(r, open('$S/join.json', 'w'))") 2> $S/join.log
fi
python3 - <<EOF
import json, os
S = '$S'
o = {'id': '$id', 'step_key': '$STEPK', 'sec': $(date +%s) - $T0}
try: o['split'] = json.load(open(S + '/split.json'))
except Exception as e: o['split_error'] = open(S + '/split.time').read()[-400:]
try:
    c = json.load(open(S + '/chk.json')); o['after'] = {k: c.get(k) for k in ('read_status', 'roots', 'transferred', 'empty_roots', 'solids', 'checked', 'valid', 'invalid', 'nonpos_vol', 'nonfinite', 'valid_solids_est', 'invalid_solids_est', 'sampled', 'bytes', 'occ_sec', 'invalid_examples')}
except Exception as e: o['check_error'] = open(S + '/chk.log').read()[-400:]
try: o['join'] = json.load(open(S + '/join.json'))
except Exception: pass
try:
    t = open(S + '/split.time').read()
    import re; m = re.search(r'(\d+)\s+maximum resident set size', t); o['split_rss_mb'] = int(m.group(1)) >> 20 if m else None
except Exception: pass
json.dump(o, open('$out', 'w'))
EOF
rm -rf $S
