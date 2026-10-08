#!/bin/bash
# conv.sh KITDIR ID OUTDIR : decode (convert_one, exactly like worker.process) for one source model
set -u
S=/Users/dhiren/Downloads/Deccan/z3conv/_sprint/cut-not-applied
PY84=/Users/dhiren/Downloads/Deccan/cad-db1-convert/venv/bin/python
KIT=$1; ID=$2; W=$3; mkdir -p $W
SRC=$(ls $S/src/$ID*.db1)
ENG=$($PY84 -c "
import re,sys,zlib
raw=open('$SRC','rb').read(1<<16)
d=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(raw) if raw[:2]==b'\x1f\x8b' else raw
print(re.search(rb'(\d+\.\d+)',d[:16]).group(1).decode())")
$PY84 -c "import json; L=json.load(open('$KIT/layouts.json')); json.dump(L['$ENG'].get('layout'), open('$W/layout.json','w')); json.dump([v['layout'] for v in L.values() if v.get('layout')], open('$W/variants.json','w'))"
/usr/bin/time -l $PY84 $KIT/convert_one.py $SRC $W/model.ifc $KIT/tekla_profiles.json $W/layout.json $W/convert.json $W/variants.json > $W/log.txt 2>&1
grep -E "maximum resident" $W/log.txt
$PY84 -c "
import json; c=json.load(open('$W/convert.json'))
print('$ID', c.get('status'), 'members', c.get('members'), 'written', c.get('written'), 'skipped', c.get('skipped'), 'cuts_applied', c.get('cuts_applied'), 'cut_layout', c.get('cut_layout'), 'secs', c.get('secs'))
"
