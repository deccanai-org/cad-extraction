#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitp; cp -r kit kitp; cp stage/kitp/* kitp/
PY=/opt/conv/ifc84/bin/python
mkdir -p dec/before dec/after
ls src/*.db1 | xargs -P 16 -I{} sh -c 'b=$(basename {} .db1); timeout 1800 '$PY' tools/dec_summary.py kit {} dec/before/$b.json 2>dec/before/$b.err; timeout 1800 '$PY' tools/dec_summary.py kitp {} dec/after/$b.json 2>dec/after/$b.err'
$PY tools/dec_compare.py dec/before dec/after > res/dec_compare.txt 2>&1
aws s3 cp --quiet res/dec_compare.txt $OUT/dec/dec_compare.txt
tar czf res/dec.tgz dec; aws s3 cp --quiet res/dec.tgz $OUT/dec/dec.tgz
echo DONE
