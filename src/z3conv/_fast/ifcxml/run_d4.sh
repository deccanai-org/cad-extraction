#!/bin/bash
# convert + validate every data-4 ifcXML input (sequential, low memory)
cd /Users/dhiren/Downloads/Deccan/z3conv/_fast/ifcxml
PY=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/classifier-audit/venv/bin/python
for f in inputs/d4/*; do
  b=$(basename "$f"); sha=${b%%.*}; s=${sha:0:12}
  [ -f out/$s.ifc ] && [ -f out/$s.report.json ] && continue
  echo "== $(date +%T) convert $b"
  /usr/bin/time -l $PY ifcxml2spf.py "$f" out/$s.ifc --report out/$s.report.json 2> out/$s.convert.time
  echo "rc=$?"
done
for f in inputs/d4/*; do
  b=$(basename "$f"); sha=${b%%.*}; s=${sha:0:12}
  [ -f out/$s.ifc ] || continue
  [ -f out/$s.validate.json ] && continue
  echo "== $(date +%T) validate $b"
  /usr/bin/time -l $PY validate_spf.py "$f" out/$s.ifc --conv-report out/$s.report.json --report out/$s.validate.json 2> out/$s.validate.time | head -c 600; echo
done
echo ALLDONE
