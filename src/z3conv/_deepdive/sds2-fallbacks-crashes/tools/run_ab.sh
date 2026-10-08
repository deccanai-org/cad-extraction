#!/bin/bash
# before (v5.1 as shipped) / after (v5.1 + patches) stage-2 runs on local sample jobs
PY=/Users/dhiren/Downloads/Deccan/z3conv/sds2_v5/venv/bin/python
D=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/sds2-fallbacks-crashes
for j in "$@"; do
  name=$(basename "$j")
  for v in v51 patched; do
    mkdir -p $D/runs/$v
    ( cd $D/runs/$v && /usr/bin/time -p $PY -u $D/$v/sds2-step-pipeline/decode/sds2_to_step.py "$D/$j" -o ${name}_stage2.step --stage 2 --verify > ${name}.log 2>&1; echo "exit $?" >> ${name}.log )
  done
done
echo ALLDONE
