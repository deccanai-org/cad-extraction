#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitp; cp -r kit kitp; cp stage/kitp/* kitp/
mkdir -p res
for id in 0762effe61de88c0 5b33936fcd1e3efc 6eabb07e71459be6 7c82c44be6c7ae3f; do
  timeout 600 /opt/conv/ifc84/bin/python tools/rel_probe.py kitp src/$id.db1 > res/relprobe_$id.txt 2>&1 &
done
wait
cat res/relprobe_*.txt
for f in res/relprobe_*.txt; do aws s3 cp --quiet $f $OUT/relprobe/; done
