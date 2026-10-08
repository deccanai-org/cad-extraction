#!/bin/bash
# validate every converted data-4 SPF against its ifcXML source (smallest first)
cd /Users/dhiren/Downloads/Deccan/z3conv/_fast/ifcxml
PY=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/classifier-audit/venv/bin/python
for s in 895f3bf617be c452935b7eff bbfaf0a7d8e7 bf3bffbf2f32 d8a938c44545 c50afe9138cb ff6959ad39ae 7db73d6b3c1e; do
  f=$(ls inputs/d4/$s*); [ -f out/$s.ifc ] || continue
  echo "== $(date +%T) validate $s"
  /usr/bin/time -l $PY validate_spf.py "$f" out/$s.ifc --conv-report out/$s.report.json --report out/$s.validate.json 2> out/$s.validate.time | head -c 700; echo
done
echo VALDONE
