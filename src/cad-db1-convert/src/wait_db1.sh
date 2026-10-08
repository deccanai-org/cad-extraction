#!/bin/bash
cd /Users/dhiren/Downloads/Deccan/cad-db1-convert
export AWS_PROFILE=annotationprod-publish
for i in $(seq 1 60); do
  OUT=$(venv/bin/python src/db1_mon2.py 2>/dev/null)
  echo "$OUT" | sed -n '1p;$p'
  N=$(echo "$OUT" | head -1 | sed -E 's/.*final-code results ([0-9]+)\/.*/\1/')
  R=$(echo "$OUT" | tail -1 | sed -E 's/.*jobs running: ([0-9]+).*/\1/')
  if [ "${N:-0}" -ge 9400 ] || { [ "${R:-1}" -eq 0 ] && [ $i -gt 1 ]; }; then echo FINISHING; break; fi
  sleep 600
done
