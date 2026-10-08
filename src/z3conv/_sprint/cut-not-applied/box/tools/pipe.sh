#!/bin/bash
# pipe.sh KITDIR ID OUTDIR : the DB1 worker pipeline (worker.process) without any upload: decode -> IFC -> ifc2step6 -> OCC read-back
# (+ render) -> census -> join. Kernel crash: bisect + exclude the culprits exactly like the worker.
set -u
KIT=$1; ID=$2; O=$3; mkdir -p $O
W=/work/agentwork/cut-not-applied
SRC=$W/src/$ID.db1
PY84=/opt/conv/ifc84/bin/python; PY=/opt/conv/env/bin/python
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ENG=$($PY84 -c "
import re,zlib
raw=open('$SRC','rb').read(1<<16)
d=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(raw) if raw[:2]==b'\x1f\x8b' else raw
print(re.search(rb'(\d+\.\d+)',d[:16]).group(1).decode())")
$PY84 -c "import json; L=json.load(open('$KIT/layouts.json')); json.dump(L['$ENG'].get('layout'), open('$O/layout.json','w')); json.dump([v['layout'] for v in L.values() if v.get('layout')], open('$O/variants.json','w'))"
T0=$(date +%s)
timeout 7200 $PY84 $KIT/convert_one.py $SRC $O/model.ifc $KIT/tekla_profiles.json $O/layout.json $O/convert.json $O/variants.json > $O/log.txt 2>&1
T1=$(date +%s)
IFC=$O/model.ifc
timeout 21600 $PY84 $KIT/ifc2step6.py $IFC $O/model.stp --mode hybrid --prec 2 --threads 4 >> $O/log.txt 2>&1; RC=$?
if [ $RC -eq 139 ] || [ $RC -eq 134 ] || [ $RC -eq 124 ] || [ $RC -eq 125 ] || [ $RC -eq 245 ]; then
  echo "kernel rc $RC -> bisect" >> $O/log.txt
  timeout 14400 $PY84 $KIT/ifc_crash_bisect.py $IFC $KIT/ifc2step6.py 8 120 > $O/bisect.log 2>&1
  G=$($PY84 -c "
import json
L=[l for l in open('$O/bisect.log') if l.startswith('{')]
r=json.loads(L[-1]) if L else {'culprits':[]}
print(' '.join(c['guid'] for c in r['culprits'] if c.get('guid')))")
  if [ -n "$G" ]; then
    $PY84 $KIT/ifc_exclude.py $IFC $O/fixed.ifc $G > $O/excluded.json 2>&1
    rm -f $O/model.stp $O/model.stp.stats.json
    timeout 21600 $PY84 $KIT/ifc2step6.py $O/fixed.ifc $O/model.stp --mode hybrid --prec 2 --threads 4 >> $O/log.txt 2>&1; RC=$?
  fi
fi
T2=$(date +%s)
timeout 14400 $PY $KIT/step_check.py $O/model.stp $O/check.json --png $O/model.png --parts $O/step_parts.jsonl.gz --title "$ID $(basename $KIT)" > $O/val.log 2>&1
timeout 7200 $PY $KIT/ifc_census.py $O/model.ifc $O/census.json --parts $O/src_parts.jsonl.gz > $O/census.log 2>&1
$PY -c "
import sys, json; sys.path.insert(0, '$KIT'); import grade_join
j = grade_join.join(grade_join.load('$O/src_parts.jsonl.gz'), grade_join.load('$O/step_parts.jsonl.gz')); json.dump(j, open('$O/join.json', 'w'))" > $O/join.log 2>&1
T3=$(date +%s)
echo "{\"id\": \"$ID\", \"kit\": \"$KIT\", \"engine\": \"$ENG\", \"step_rc\": $RC, \"dec_sec\": $((T1-T0)), \"step_sec\": $((T2-T1)), \"check_sec\": $((T3-T2))}" > $O/pipe.json
