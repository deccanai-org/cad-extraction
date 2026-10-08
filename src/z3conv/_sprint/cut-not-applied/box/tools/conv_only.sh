#!/bin/bash
# conv_only.sh KIT ID OUTDIR : decoder + IFC writer only (convert_one exactly as the worker runs it), no STEP stage
set -u
KIT=$1; ID=$2; O=$3; mkdir -p $O
W=/work/agentwork/cut-not-applied; SRC=$W/src/$ID.db1; PY84=/opt/conv/ifc84/bin/python
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
ENG=$($PY84 -c "
import re,zlib
raw=open('$SRC','rb').read(1<<16)
d=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(raw) if raw[:2]==b'\x1f\x8b' else raw
m=re.search(rb'(\d+\.\d+)',d[:16]); print(m.group(1).decode() if m else 'none')")
$PY84 -c "import json; L=json.load(open('$KIT/layouts.json')); e=L.get('$ENG') or {}; json.dump(e.get('layout'), open('$O/layout.json','w')); json.dump([v['layout'] for v in L.values() if v.get('layout')], open('$O/variants.json','w'))"
T0=$(date +%s)
timeout 5400 $PY84 $KIT/convert_one.py $SRC $O/model.ifc $KIT/tekla_profiles.json $O/layout.json $O/convert.json $O/variants.json > $O/log.txt 2>&1
echo "{\"id\": \"$ID\", \"engine\": \"$ENG\", \"rc\": $?, \"sec\": $(( $(date +%s) - T0 ))}" > $O/conv.json
rm -f $O/model.ifc
