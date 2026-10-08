#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitp; cp -r kit kitp; cp stage/kitp/* kitp/
PY=/opt/conv/ifc84/bin/python
mkdir -p res
$PY tools/old_cut_audit.py kitp src/0762effe61de88c0.db1 > res/audit_0762.txt 2>&1
$PY tools/old_rel_types.py kitp src/0762effe61de88c0.db1 src/5b33936fcd1e3efc.db1 > res/reltypes.txt 2>&1
$PY tools/unlinked_occ.py kitp src/0762effe61de88c0.db1 6 > res/unlinked_0762.txt 2>&1
for f in res/audit_0762.txt res/reltypes.txt res/unlinked_0762.txt; do aws s3 cp --quiet $f $OUT/audit/; done
head -c 6000 res/audit_0762.txt; echo; cat res/reltypes.txt | head -60; echo; head -c 9000 res/unlinked_0762.txt
