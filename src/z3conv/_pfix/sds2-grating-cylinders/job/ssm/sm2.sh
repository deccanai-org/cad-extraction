#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders
for n in One_Light_Tower_JOB_-Model_700bd1 SHERIFFS_OFFICE_JOB_e730aa; do
  echo "== $n"; cat $W/out/v55/$n/rc.txt 2>/dev/null; grep -av "^\*\|Transferr\|^\s*$" $W/out/v55/$n/convert.log 2>/dev/null | grep -v LD_PRE | tail -25 | cut -c1-400
done
