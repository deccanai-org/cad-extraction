#!/bin/bash
D=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/db1-axis-guard-cuts-versions
for id in 0762effe ba7492de f2644296 0632e878 3355ebac 6f0dcc7d 863be0aa c114f84d; do
  for k in kit_snapshot kit_patched; do
    [ "$id" = 0bbac8fc ] && continue
    echo "$k $id" ; done; done | xargs -P 3 -n 2 $D/tools/e2e.sh > $D/e2e_summary.txt 2>&1
echo DONE >> $D/e2e_summary.txt
