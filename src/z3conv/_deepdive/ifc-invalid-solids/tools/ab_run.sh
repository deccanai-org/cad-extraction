#!/bin/bash
# ab_run.sh PREFIX... : step_shellfix on work/s/P.step -> work/fx/P.step, kit step_check on both, ab_compare
W=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-invalid-solids/work
PY=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python
CK=/Users/dhiren/Downloads/Deccan/z3conv/ifc/step_check.py
cd $W; mkdir -p fx ck
for p in "$@"; do
  ( python3 ../patch/step_shellfix.py s/$p.step fx/$p.step --stats fx/$p.stats.json > /dev/null
    [ -f ck/$p.before.json ] || $PY $CK s/$p.step ck/$p.before.json --parts ck/$p.before.parts.jsonl.gz > /dev/null 2>&1
    $PY $CK fx/$p.step ck/$p.after.json --parts ck/$p.after.parts.jsonl.gz > /dev/null 2>&1 ) &
done; wait
for p in "$@"; do echo "== $p $(cat fx/$p.stats.json)"; python3 ../tools/ab_compare.py ck/$p.before.json ck/$p.before.parts.jsonl.gz ck/$p.after.json ck/$p.after.parts.jsonl.gz; done
